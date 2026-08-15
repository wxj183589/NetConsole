from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
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
            total += int(conn.execute("SELECT COUNT(*) FROM history_events").fetchone()[0])
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
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM history_events WHERE payload_json LIKE '%\"legacy_source_id\":1%'"
            ).fetchone()[0]
        )
    assert payload["legacy_source_table"] == "ac_fit_ap_optical_history"


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
