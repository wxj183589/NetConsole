from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.services import history_legacy_migration as migration_module
from netconsole.services.database_upgrade.coordinator import (
    site_database_maintenance_key,
)
from netconsole.services.history_legacy_migration import HistoryLegacyMigrationService
from netconsole.services.history_store import HistoryStore


def _source_database(root: Path, *, rows: list[tuple[int, str, str]] | None = None) -> Path:
    path = root / "source" / "devices.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES
                ('schema_version', '2026.08.07.ap_topology_resolver', '', '');
            CREATE TABLE device_facts_history (
                id INTEGER PRIMARY KEY,
                device_uuid TEXT NOT NULL,
                model TEXT,
                collected_at TEXT,
                created_at TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO device_facts_history VALUES (?, ?, ?, ?, ?)",
            [
                (source_id, f"device-{source_id}", "S6520", collected_at, collected_at)
                for source_id, _, collected_at in (rows or [])
            ],
        )
        conn.commit()
    return path


def _service(
    tmp_path: Path, source: Path, *, immutable_source: bool = True
) -> HistoryLegacyMigrationService:
    data_root = tmp_path / "runtime"
    data_root.mkdir(parents=True, exist_ok=True)
    paths = PathResolver(app_root=tmp_path, data_root=data_root)
    return HistoryLegacyMigrationService(
        paths,
        site_id="site-a",
        source_database=source,
        history_root=tmp_path / "target" / "history",
        diagnostics_dir=tmp_path / "diagnostics",
        immutable_source=immutable_source,
    )


def _target_count(service: HistoryLegacyMigrationService) -> int:
    total = 0
    for shard in service.history_root.glob("devices-????-??.db"):
        with sqlite3.connect(shard) as conn:
            for table in ("history_events", "history_events_v2"):
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return total


def test_inventory_classifies_supported_unsupported_and_unknown_schema(tmp_path: Path) -> None:
    source = _source_database(tmp_path)
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE ac_fit_ap_unauthenticated_history (
                id INTEGER PRIMARY KEY, ac_device_uuid TEXT, collected_at TEXT
            );
            CREATE TABLE future_probe_history (
                id INTEGER PRIMARY KEY, collected_at TEXT
            );
            """
        )
    service = _service(tmp_path, source)

    result = service.inventory()

    classifications = {
        item["table_name"]: item["classification"] for item in result["tables"]
    }
    assert classifications == {
        "ac_fit_ap_unauthenticated_history": "UNSUPPORTED",
        "device_facts_history": "SUPPORTED",
        "future_probe_history": "UNKNOWN_SCHEMA",
    }
    assert (tmp_path / "diagnostics" / "LEGACY_HISTORY_INVENTORY.json").is_file()
    assert service.start()["result"] == "NOT_READY"


def test_copy_only_migrates_cross_month_and_year_without_exposing_duplicate_queries(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (1, "a", "2025-12-31T23:59:59"),
            (2, "b", "2026-01-01T00:00:00"),
            (3, "c", "2026-02-01T00:00:00"),
        ],
    )
    service = _service(tmp_path, source)

    result = service.start(chunk_rows=100, max_elapsed_seconds=0)

    assert result["result"] == "COPY_ONLY_READY"
    assert result["migration"]["copied_count"] == 3
    assert result["migration"]["verified_count"] == 3
    assert result["migration"]["duplicate_count"] == 0
    assert {path.name for path in service.history_root.glob("devices-*.db")} == {
        "devices-2025-12.db",
        "devices-2026-01.db",
        "devices-2026-02.db",
    }
    assert service.store.query_events(kind="device_fact") == []
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 3
    assert result["destructive_operations"] == {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"}


def test_invalid_timestamp_is_journaled_and_source_is_preserved(tmp_path: Path) -> None:
    source = _source_database(
        tmp_path,
        rows=[(1, "ok", "2026-08-01T00:00:00"), (2, "bad", "not-a-time")],
    )
    service = _service(tmp_path, source)

    result = service.start(chunk_rows=100, max_elapsed_seconds=0)

    assert result["result"] == "NOT_READY"
    assert result["migration"]["error_count"] == 1
    invalid = [
        json.loads(line)
        for line in (tmp_path / "diagnostics" / "LEGACY_HISTORY_INVALID_ROWS.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert invalid == [
        {
            "reason": "INVALID_TIMESTAMP",
            "source_key": 2,
            "source_table": "device_facts_history",
        }
    ]
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 2


def test_crash_after_target_commit_replays_only_last_idempotent_chunk(tmp_path: Path) -> None:
    source = _source_database(
        tmp_path,
        rows=[(1, "a", "2026-08-01T00:00:00"), (2, "b", "2026-08-01T00:01:00")],
    )
    service = _service(tmp_path, source)

    def crash(_table: str, _source_key: int) -> None:
        raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        service.start(migration_id="crash-target", after_target_commit=crash)
    assert _target_count(service) == 2
    assert service.status("crash-target")["tables"][0]["last_source_key"] == 0

    resumed = service.resume("crash-target", max_elapsed_seconds=0)

    assert resumed["result"] == "COPY_ONLY_READY"
    assert _target_count(service) == 2
    assert resumed["migration"]["verified_count"] == 2
    assert resumed["migration"]["duplicate_count"] == 2


def test_crash_after_checkpoint_resumes_at_next_chunk_and_rerun_is_idempotent(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (source_id, "x", f"2026-08-01T00:{source_id:02d}:00")
            for source_id in range(1, 4)
        ],
    )
    service = _service(tmp_path, source)
    crashed = False

    def crash_once(_table: str, source_key: int) -> None:
        nonlocal crashed
        if not crashed and source_key == 2:
            crashed = True
            raise RuntimeError("checkpoint crash")

    with pytest.raises(RuntimeError, match="checkpoint crash"):
        service.start(
            migration_id="crash-checkpoint",
            chunk_rows=2,
            max_elapsed_seconds=0,
            after_checkpoint=crash_once,
        )
    assert service.status("crash-checkpoint")["tables"][0]["last_source_key"] == 2

    resumed = service.resume("crash-checkpoint", max_elapsed_seconds=0)
    rerun = service.resume("crash-checkpoint", max_elapsed_seconds=0)

    assert resumed["result"] == rerun["result"] == "COPY_ONLY_READY"
    assert _target_count(service) == 3
    assert rerun["migration"]["copied_count"] == 3


def test_checkpoint_rejects_a_different_source_database(tmp_path: Path) -> None:
    source_a = _source_database(
        tmp_path / "a", rows=[(1, "a", "2026-08-01T00:00:00")]
    )
    service_a = _service(tmp_path, source_a)
    service_a.start(migration_id="stable-id", max_elapsed_seconds=0)
    source_b = _source_database(
        tmp_path / "b", rows=[(9, "b", "2026-08-02T00:00:00")]
    )
    service_b = HistoryLegacyMigrationService(
        service_a.paths,
        site_id="site-a",
        source_database=source_b,
        history_root=service_a.history_root,
        diagnostics_dir=tmp_path / "diagnostics-b",
        immutable_source=True,
    )

    with pytest.raises(ValueError, match="different source database"):
        service_b.start(migration_id="stable-id", max_elapsed_seconds=0)


def test_unattended_state_pauses_before_chunk_and_soft_budget_stops_between_chunks(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (source_id, "x", f"2026-08-01T00:{source_id:02d}:00")
            for source_id in range(1, 4)
        ],
    )
    service = _service(tmp_path, source)

    paused = service.start(
        migration_id="priority",
        chunk_rows=1,
        unattended_active=lambda: True,
        max_elapsed_seconds=0,
    )
    assert paused["result"] == "NOT_READY"
    assert _target_count(service) == 0

    ticks = iter((0.0, 0.0, 0.01, 0.01, 0.01, 0.02, 0.02))
    service._monotonic = lambda: next(ticks, 0.02)
    budget = service.resume(
        "priority",
        max_elapsed_seconds=0.015,
    )
    assert budget["budget_exceeded"] is True
    assert budget["tables"][0]["last_source_key"] == 2
    assert service.resume("priority", max_elapsed_seconds=0)["result"] == "COPY_ONLY_READY"


def test_projection_rows_share_canonical_identity_and_do_not_overwrite_authoritative_payload(
    tmp_path: Path,
) -> None:
    source = _source_database(tmp_path)
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE ac_fit_ap_optical_history (
                id INTEGER PRIMARY KEY, ac_device_uuid TEXT NOT NULL, ap_uuid TEXT NOT NULL,
                interface_name TEXT, rx_power TEXT, tx_power TEXT, collected_at TEXT, created_at TEXT
            );
            CREATE TABLE ap_optical_history (
                id INTEGER PRIMARY KEY, history_uuid TEXT, ap_uuid TEXT NOT NULL, side TEXT,
                device_uuid TEXT, interface_name TEXT, rx_power TEXT, tx_power TEXT,
                alarm_status TEXT, collected_at TEXT, data_source TEXT, is_latest INTEGER,
                created_at TEXT
            );
            INSERT INTO ac_fit_ap_optical_history VALUES
                (1, 'ac-1', 'ap-1', 'GE1/0/1', '-10', '-2', '2026-08-01T00:00:00', '2026-08-01T00:00:00');
            INSERT INTO ac_fit_ap_optical_history VALUES
                (2, 'ac-2', 'ap-1', 'GE1/0/1', '-10', '-2', '2026-08-01T00:00:00', '2026-08-01T00:00:00');
            INSERT INTO ap_optical_history VALUES
                (1, 'history-1', 'ap-1', 'A', 'ac-1', 'GE1/0/1', '-10', '-2',
                 'normal', '2026-08-01T00:00:00', 'legacy', 1, '2026-08-01T00:00:00');
            """
        )
    service = _service(tmp_path, source)

    result = service.start(max_elapsed_seconds=0)

    assert result["result"] == "COPY_ONLY_READY"
    assert _target_count(service) == 2
    assert result["migration"]["copied_count"] == 2
    assert result["migration"]["verified_count"] == 3
    assert result["migration"]["duplicate_count"] == 1
    shard = service.history_root / "devices-2026-08.db"
    with sqlite3.connect(shard) as conn:
        fields = [
            str(row[0])
            for row in conn.execute(
                "SELECT fields_json FROM history_payload_schemas_v2 ORDER BY payload_schema_id"
            )
        ]
        assert all("legacy_source_table" not in item for item in fields)
        assert all("legacy_source_id" not in item for item in fields)
    with sqlite3.connect(source) as conn:
        conn.row_factory = sqlite3.Row
        source_row = dict(
            conn.execute("SELECT * FROM ac_fit_ap_optical_history WHERE id=1").fetchone()
        )
    event = HistoryStore.legacy_migration_event("ac_fit_ap_optical_history", source_row)
    stored = service.store.read_legacy_migration_events([event])
    assert len(stored) == 1
    payload = json.loads(stored[0]["payload_json"])
    assert payload["id"] == 1
    assert payload["ac_device_uuid"] == "ac-1"
    authoritative_ranges = [
        item
        for item in result["ranges"]
        if item["source_table"] == "ac_fit_ap_optical_history"
    ]
    assert authoritative_ranges
    assert authoritative_ranges[0]["source_start_key"] == 1
    assert authoritative_ranges[0]["source_end_key"] == 2
    assert authoritative_ranges[0]["source_digest"] == authoritative_ranges[0]["target_digest"]


def test_migration_and_realtime_history_writer_share_the_same_month_safely(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (source_id, "x", f"2026-08-01T00:{source_id % 60:02d}:00")
            for source_id in range(1, 101)
        ],
    )
    service = _service(tmp_path, source, immutable_source=False)
    producer = HistoryStore(source, site_id="site-a", history_root=service.history_root)

    def write_realtime() -> None:
        with connect_sqlite(source, foreign_keys=True) as conn:
            producer.record_event(
                conn,
                kind="device_fact",
                entity_key="live-device",
                payload={"device_uuid": "live-device", "model": "live"},
                collected_at="2026-08-01T12:00:00",
            )
            conn.commit()
        producer.drain(limit=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        migration = pool.submit(service.start, chunk_rows=100, max_elapsed_seconds=0)
        realtime = pool.submit(write_realtime)
        result = migration.result()
        realtime.result()

    assert result["result"] == "COPY_ONLY_READY"
    assert _target_count(service) == 101
    assert len(producer.query_events(kind="device_fact")) == 1


def test_large_batch_uses_bounded_commits_and_verifies_every_row(tmp_path: Path) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (source_id, "x", f"2026-08-{1 + source_id // 800:02d}T00:00:{source_id % 60:02d}")
            for source_id in range(1, 1_001)
        ],
    )
    service = _service(tmp_path, source)

    result = service.start(chunk_rows=250, max_elapsed_seconds=0)

    assert result["result"] == "COPY_ONLY_READY"
    assert result["migration"]["copied_count"] == 1_000
    assert result["migration"]["verified_count"] == 1_000
    assert result["migration"]["checkpoint_commits"] == 4
    assert _target_count(service) == 1_000


def test_per_table_cutover_query_authority_persists_and_rolls_back(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (1, "a", "2025-12-31T23:59:59"),
            (2, "b", "2026-01-01T00:00:00"),
            (3, "c", "2026-02-01T00:00:00"),
        ],
    )
    service = _service(tmp_path, source)
    migrated = service.start(migration_id="authority", max_elapsed_seconds=0)
    checkpoint = migrated["tables"][0]

    assert checkpoint["authority_state"] == "SHARD_VERIFIED"
    assert checkpoint["cutover_revision"] == 1
    assert service.store.query_events(kind="device_fact") == []

    cutover = service.cutover(
        "authority",
        "device_facts_history",
        expected_revision=1,
        reason="consumer validation passed",
    )

    assert cutover["table"]["authority_state"] == "SHARD_AUTHORITY"
    assert cutover["table"]["cutover_revision"] == 2
    assert [
        row["collected_at"]
        for row in service.store.query_events(kind="device_fact", limit=2)
    ] == ["2026-02-01T00:00:00", "2026-01-01T00:00:00"]
    assert [
        row["collected_at"]
        for row in service.store.query_events(kind="device_fact", limit=2, offset=1)
    ] == ["2026-01-01T00:00:00", "2025-12-31T23:59:59"]
    assert service.store.count_events(kind="device_fact") == 3
    assert not service.store.legacy_source_is_authoritative("device_facts_history")
    parity = service.validate_query_parity("authority", "device_facts_history")
    assert parity["result"] == "PASS"
    assert parity["month_counts"] == {
        "2025-12": 1,
        "2026-01": 1,
        "2026-02": 1,
    }

    restarted = _service(tmp_path / "restart", source)
    restarted.history_root = service.history_root
    restarted.store = HistoryStore(
        source, site_id="site-a", history_root=service.history_root
    )
    restarted.journal = service.journal
    assert (
        restarted.status("authority")["tables"][0]["authority_state"]
        == "SHARD_AUTHORITY"
    )
    assert len(restarted.store.query_events(kind="device_fact")) == 3

    rolled_back = service.rollback_cutover(
        "authority",
        "device_facts_history",
        expected_revision=2,
        reason="consumer mismatch",
    )
    assert rolled_back["table"]["authority_state"] == "LEGACY_AUTHORITY"
    assert rolled_back["table"]["cutover_revision"] == 3
    assert service.store.query_events(kind="device_fact") == []
    recutover = service.cutover(
        "authority",
        "device_facts_history",
        expected_revision=3,
        reason="rollback validation passed",
    )
    assert recutover["table"]["authority_state"] == "SHARD_AUTHORITY"
    assert recutover["table"]["cutover_revision"] == 5
    assert len(service.store.query_events(kind="device_fact")) == 3
    with pytest.raises(ValueError, match="revision mismatch"):
        service.cutover(
            "authority",
            "device_facts_history",
            expected_revision=1,
            reason="stale operator request",
        )


def test_delete_eligibility_plan_excludes_unsupported_and_verifies_projection(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[(1, "a", "2026-08-01T00:00:00")],
    )
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE ac_fit_ap_optical_history (
                id INTEGER PRIMARY KEY, ac_device_uuid TEXT NOT NULL, ap_uuid TEXT NOT NULL,
                interface_name TEXT, rx_power TEXT, tx_power TEXT, collected_at TEXT, created_at TEXT
            );
            CREATE TABLE ap_optical_history (
                id INTEGER PRIMARY KEY, history_uuid TEXT, ap_uuid TEXT NOT NULL, side TEXT,
                device_uuid TEXT, interface_name TEXT, rx_power TEXT, tx_power TEXT,
                alarm_status TEXT, collected_at TEXT, data_source TEXT, is_latest INTEGER,
                created_at TEXT
            );
            CREATE TABLE ac_fit_ap_unauthenticated_history (
                id INTEGER PRIMARY KEY, ac_device_uuid TEXT, collected_at TEXT
            );
            INSERT INTO ac_fit_ap_optical_history VALUES
                (1, 'ac-1', 'ap-1', 'GE1/0/1', '-10', '-2',
                 '2026-08-01T00:00:00', '2026-08-01T00:00:00');
            INSERT INTO ap_optical_history VALUES
                (9, 'history-9', 'ap-1', 'A', 'ac-1', 'GE1/0/1', '-10', '-2',
                 'normal', '2026-08-01T00:00:00', 'legacy', 1,
                 '2026-08-01T00:00:00');
            INSERT INTO ac_fit_ap_unauthenticated_history VALUES
                (607, 'ac-unsupported', '2026-08-01T00:00:00');
            """
        )
    service = _service(tmp_path, source)
    migrated = service.start(migration_id="delete-plan", max_elapsed_seconds=0)
    checkpoints = {item["source_table"]: item for item in migrated["tables"]}
    assert checkpoints["ap_optical_history"]["duplicate_count"] == 1

    for table in (
        "device_facts_history",
        "ac_fit_ap_optical_history",
        "ap_optical_history",
    ):
        checkpoint = service.status("delete-plan")["tables"]
        current = next(item for item in checkpoint if item["source_table"] == table)
        service.cutover(
            "delete-plan",
            table,
            expected_revision=int(current["cutover_revision"]),
            reason="query and consumer validation",
        )
        current = next(
            item
            for item in service.status("delete-plan")["tables"]
            if item["source_table"] == table
        )
        service.evaluate_delete_eligibility(
            "delete-plan",
            table,
            expected_revision=int(current["cutover_revision"]),
            observation={
                "query_validation": True,
                "consumer_validation": True,
                "integrity_mismatch": False,
            },
            reason="observation window passed",
        )

    plan = service.preview_delete_plan("delete-plan")

    assert plan["source_delete_executor"] == "DEVELOPMENT_ROOT_ONLY_V1"
    assert plan["source_delete_executed"] is False
    assert len(plan["plan_digest"]) == 64
    assert service.validate_delete_plan(plan)["valid"] is True
    unsupported = next(
        item
        for item in plan["excluded_sources"]
        if item["source_table"] == "ac_fit_ap_unauthenticated_history"
    )
    assert unsupported["eligibility"] is False
    assert unsupported["row_count"] == 1
    projection = next(
        item for item in plan["tables"] if item["source_table"] == "ap_optical_history"
    )
    assert projection["eligibility"] is True
    assert projection["duplicate_count"] == 1
    assert projection["ranges"][0]["projection_duplicate"] is True
    assert projection["ranges"][0]["source_key_ranges"] == [{"start": 9, "end": 9}]
    assert (tmp_path / "diagnostics" / "LEGACY_HISTORY_DELETE_PLAN.json").is_file()
    with sqlite3.connect(source) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ap_optical_history").fetchone()[0] == 1
        )


def test_cutover_revalidates_source_inside_shared_maintenance_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[(1, "a", "2026-08-01T00:00:00")],
    )
    service = _service(tmp_path, source)
    service.start(migration_id="locked-cutover", max_elapsed_seconds=0)
    observed_keys: list[str] = []

    @contextmanager
    def maintenance_lock(_paths: PathResolver, key: str):
        observed_keys.append(key)
        with sqlite3.connect(source) as connection:
            connection.execute(
                "INSERT INTO device_facts_history VALUES (2, 'device-2', 'S6520', ?, ?)",
                ("2026-08-02T00:00:00", "2026-08-02T00:00:00"),
            )
            connection.commit()
        yield

    monkeypatch.setattr(
        migration_module,
        "database_maintenance_lock",
        maintenance_lock,
    )

    with pytest.raises(ValueError, match="identity changed"):
        service.cutover(
            "locked-cutover",
            "device_facts_history",
            expected_revision=1,
            reason="must revalidate under lock",
        )

    assert observed_keys == [site_database_maintenance_key("site-a")]
    checkpoint = service.status("locked-cutover")["tables"][0]
    assert checkpoint["authority_state"] == "SHARD_VERIFIED"


def test_delete_plan_rejects_digest_source_identity_and_revision_staleness(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[(1, "a", "2026-08-01T00:00:00")],
    )
    service = _service(tmp_path, source)
    service.start(migration_id="stale-plan", max_elapsed_seconds=0)
    service.cutover(
        "stale-plan",
        "device_facts_history",
        expected_revision=1,
        reason="validated",
    )
    service.evaluate_delete_eligibility(
        "stale-plan",
        "device_facts_history",
        expected_revision=2,
        observation={
            "query_validation": True,
            "consumer_validation": True,
            "integrity_mismatch": False,
        },
        reason="observed",
    )
    plan = service.preview_delete_plan("stale-plan")

    changed = json.loads(json.dumps(plan))
    changed["tables"][0]["row_count"] = 99
    with pytest.raises(ValueError, match="digest mismatch"):
        service.validate_delete_plan(changed)

    service.rollback_cutover(
        "stale-plan",
        "device_facts_history",
        expected_revision=3,
        reason="rollback after preview",
    )
    with pytest.raises(ValueError, match="authority is stale"):
        service.validate_delete_plan(plan)

    other = _service(tmp_path / "identity", source)
    other.history_root = service.history_root
    other.store = HistoryStore(
        source, site_id="site-a", history_root=service.history_root
    )
    other.journal = service.journal
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO device_facts_history VALUES (2, 'device-2', 'S6520', ?, ?)",
            ("2026-08-02T00:00:00", "2026-08-02T00:00:00"),
        )
        conn.commit()
    with pytest.raises(ValueError, match="identity changed"):
        other.validate_delete_plan(plan)


def test_source_delete_applies_exact_plan_and_preserves_unsupported_rows(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path,
        rows=[
            (1, "a", "2026-08-01T00:00:00"),
            (2, "b", "2026-08-02T00:00:00"),
            (3, "c", "2026-08-03T00:00:00"),
        ],
    )
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE ac_fit_ap_unauthenticated_history "
            "(id INTEGER PRIMARY KEY, ac_device_uuid TEXT, collected_at TEXT)"
        )
        connection.execute(
            "INSERT INTO ac_fit_ap_unauthenticated_history VALUES (1, 'ac-1', '2026-08-01')"
        )
        connection.commit()
    service = _service(tmp_path, source, immutable_source=False)
    service.start(migration_id="delete-executor", max_elapsed_seconds=0)
    service.cutover(
        "delete-executor",
        "device_facts_history",
        expected_revision=1,
        reason="isolated verification passed",
    )
    service.evaluate_delete_eligibility(
        "delete-executor",
        "device_facts_history",
        expected_revision=2,
        observation={
            "query_validation": True,
            "consumer_validation": True,
            "integrity_mismatch": False,
        },
        reason="isolated observation passed",
    )
    plan = service.preview_delete_plan("delete-executor")

    result = service.delete_source(
        plan,
        expected_plan_digest=str(plan["plan_digest"]),
        expected_source_identity=str(plan["source_database_identity"]),
        expected_revision=3,
        batch_rows=250,
        apply=True,
        allow_development_root_only=True,
        development_root=tmp_path,
    )

    assert result["deleted_rows"] == 3
    assert result["tables"][0]["authority_state"] == "SOURCE_DELETED"
    with sqlite3.connect(source) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_facts_history"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM ac_fit_ap_unauthenticated_history"
        ).fetchone()[0] == 1


def test_source_delete_requires_development_root_and_exact_expectations(
    tmp_path: Path,
) -> None:
    source = _source_database(
        tmp_path, rows=[(1, "a", "2026-08-01T00:00:00")]
    )
    service = _service(tmp_path, source, immutable_source=False)
    service.start(migration_id="guarded-delete", max_elapsed_seconds=0)
    service.cutover(
        "guarded-delete",
        "device_facts_history",
        expected_revision=1,
        reason="verified",
    )
    service.evaluate_delete_eligibility(
        "guarded-delete",
        "device_facts_history",
        expected_revision=2,
        observation={
            "query_validation": True,
            "consumer_validation": True,
            "integrity_mismatch": False,
        },
        reason="observed",
    )
    plan = service.preview_delete_plan("guarded-delete")

    with pytest.raises(ValueError, match="expected delete plan digest mismatch"):
        service.delete_source(
            plan,
            expected_plan_digest="0" * 64,
            expected_source_identity=str(plan["source_database_identity"]),
            expected_revision=3,
            apply=True,
            allow_development_root_only=True,
            development_root=tmp_path,
        )
    with pytest.raises(ValueError, match="maintenance target"):
        service.delete_source(
            plan,
            expected_plan_digest=str(plan["plan_digest"]),
            expected_source_identity=str(plan["source_database_identity"]),
            expected_revision=3,
            apply=True,
            allow_development_root_only=True,
            development_root=tmp_path / "different-root",
        )
