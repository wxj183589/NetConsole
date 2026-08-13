from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import pairwise
from threading import Barrier

import pytest

import netconsole.services.history_store as history_store_module
from netconsole.core.database import Database
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services.history_store import HistoryStore


def _store(tmp_path) -> HistoryStore:
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    with connect_sqlite(database_path, foreign_keys=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS current_probe (id INTEGER PRIMARY KEY)")
    return HistoryStore(database_path, site_id="demo")


def _record(store: HistoryStore, *, collected_at: str, value: str = "up") -> bool:
    with connect_sqlite(store.database_path, foreign_keys=True) as conn:
        recorded = store.record_event(
            conn,
            kind="device_interface",
            entity_key="device-1:GE1/0/1",
            payload={
                "device_uuid": "device-1",
                "interface_name": "GE1/0/1",
                "link_status": value,
                "collected_at": collected_at,
                "collect_run_uuid": f"run-{collected_at}",
            },
            collected_at=collected_at,
            heartbeat_seconds=3600,
            meaningful_fields=("device_uuid", "interface_name", "link_status"),
        )
        conn.commit()
    return recorded


def test_change_aware_history_records_one_initial_event_then_per_kind_heartbeat(tmp_path):
    store = _store(tmp_path)

    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")
    for minute in range(1, 101):
        assert not _record(
            store,
            collected_at=f"2026-08-01T10:{minute % 60:02d}:00",
            value="up",
        )
    assert _record(store, collected_at="2026-08-01T11:00:00", value="up")
    assert _record(store, collected_at="2026-08-01T11:01:00", value="down")

    result = store.drain(limit=20)

    assert (result.written, result.pending, result.degraded) == (3, 0, False)
    assert [event["event_type"] for event in store.query_events(kind="device_interface")] == [
        "change",
        "heartbeat",
        "change",
    ]


def test_telemetry_only_changes_are_sampled_and_latest_payload_is_kept(tmp_path):
    store = _store(tmp_path)

    def record(collected_at: str, uptime: int) -> bool:
        with connect_sqlite(store.database_path, foreign_keys=True) as conn:
            value = store.record_event(
                conn,
                kind="device_fact",
                entity_key="device-1",
                payload={"device_uuid": "device-1", "model": "S6520", "uptime": uptime},
                collected_at=collected_at,
                heartbeat_seconds=3600,
                meaningful_fields=("device_uuid", "model"),
            )
            conn.commit()
        return value

    assert record("2026-08-01T10:00:00", 100)
    assert not record("2026-08-01T10:05:00", 400)
    assert record("2026-08-01T11:00:00", 3700)
    assert store.drain(limit=10).written == 2
    events = store.query_events(kind="device_fact")
    assert [event["event_type"] for event in events] == ["heartbeat", "change"]
    assert events[0]["uptime"] == 3700


def test_history_store_rotates_month_shards_without_losing_or_duplicating_events(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-07-31T23:59:00", value="up")
    assert _record(store, collected_at="2026-08-01T00:00:00", value="down")

    first = store.drain(limit=20)
    second = store.drain(limit=20)

    assert (first.written, first.pending) == (2, 0)
    assert (second.written, second.pending) == (0, 0)
    assert (store.history_root / "devices-2026-07.db").is_file()
    assert (store.history_root / "devices-2026-08.db").is_file()
    assert len(store.query_events(kind="device_interface")) == 2
    with connect_sqlite(store.history_root / "catalog.db", foreign_keys=True) as conn:
        catalog = {
            row["shard_id"]: dict(row)
            for row in conn.execute(
                "SELECT shard_id, period_end, status FROM history_catalog"
            ).fetchall()
        }
    assert catalog["2026-07"]["period_end"] == "2026-07-31"
    assert catalog["2026-08"]["status"] == "ACTIVE"


def test_unattended_drain_adapts_to_backlog_without_tiny_commit_policy(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")
    assert _record(store, collected_at="2026-08-01T10:01:00", value="down")

    result = store.drain(unattended_active=True, high_watermark=10)

    assert result.paused is False
    assert result.written == 2
    assert result.pending == 0


def test_unattended_soft_budget_finishes_started_chunk_and_keeps_later_rows(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    for index in range(150):
        with connect_sqlite(store.database_path, foreign_keys=True) as conn:
            assert store.record_event(
                conn,
                kind="fit_ap_resource",
                entity_key=f"ap-{index}",
                payload={"ap_uuid": f"ap-{index}", "status": "up"},
                collected_at="2026-08-01T10:00:00",
                meaningful_fields=("ap_uuid", "status"),
            )
            conn.commit()

    writes: list[int] = []
    original_write = store._write_shard_batch

    def slow_write(rows):
        writes.append(len(rows))
        time.sleep(0.02)
        original_write(rows)

    monkeypatch.setattr(store, "_write_shard_batch", slow_write)
    result = store.drain(
        unattended_active=True,
        high_watermark=1,
        max_elapsed_seconds=0.01,
    )

    assert result.written == 100
    assert result.pending == 50
    assert writes == [100]
    assert result.budget_exceeded is True
    assert result.shard_commits == 1
    assert result.elapsed_ms >= 20


def test_unattended_drain_limit_scales_with_backlog_and_age():
    base = history_store_module.HistoryOutboxDiagnostics(pending=1)
    elevated = history_store_module.HistoryOutboxDiagnostics(pending=1_500)
    urgent = history_store_module.HistoryOutboxDiagnostics(
        pending=1, oldest_pending_age_seconds=history_store_module.UNATTENDED_URGENT_AGE_SECONDS
    )

    assert HistoryStore._unattended_drain_limit(base, high_watermark=5_000) == 100
    assert HistoryStore._unattended_drain_limit(elevated, high_watermark=5_000) == 250
    assert HistoryStore._unattended_drain_limit(urgent, high_watermark=5_000) == 500


def test_outbox_diagnostics_reports_bounded_pressure_and_age(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")
    diagnostics = store.outbox_diagnostics(high_watermark=1)
    assert diagnostics.pending == 1
    assert diagnostics.pressure == "high"
    assert diagnostics.attempts == 0


def test_new_outbox_write_preserves_existing_legacy_rows(tmp_path):
    store = _store(tmp_path)
    with connect_sqlite(store.database_path, foreign_keys=True) as conn:
        conn.execute(
            "CREATE TABLE device_facts_history (id INTEGER PRIMARY KEY, device_uuid TEXT, "
            "sysname TEXT, collected_at TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO device_facts_history VALUES (1, 'device-1', 'legacy', '2026-07-01T00:00:00', '2026-07-01T00:00:00')"
        )
        conn.commit()
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")
    with connect_sqlite(store.database_path, foreign_keys=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM history_outbox").fetchone()[0] == 1


def test_outbox_survives_current_commit_before_shard_drain_and_recovers_after_restart(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")

    restarted = HistoryStore(store.database_path, site_id="demo", history_root=store.history_root)
    assert restarted.pending_count() == 1
    result = restarted.drain(limit=1)

    assert (result.written, result.pending, result.degraded) == (1, 0, False)
    assert restarted.pending_count() == 0
    assert [event["link_status"] for event in restarted.query_events(kind="device_interface")] == ["up"]


def test_unattended_mode_drains_normal_backlog_without_discarding_outbox(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")

    drained = store.drain(unattended_active=True)

    assert (drained.written, drained.pending, drained.paused, drained.degraded) == (1, 0, False, False)


def test_first_outbox_write_is_safe_across_concurrent_connections(tmp_path):
    store = _store(tmp_path)
    worker_count = 25
    barrier = Barrier(worker_count)

    def record(index: int) -> bool:
        barrier.wait()
        with connect_sqlite(store.database_path, foreign_keys=True) as conn:
            recorded = store.record_event(
                conn,
                kind="device_interface",
                entity_key=f"device-{index}:GE1/0/1",
                payload={"device_uuid": f"device-{index}", "link_status": "up"},
                collected_at="2026-08-01T10:00:00",
                meaningful_fields=("device_uuid", "link_status"),
            )
            conn.commit()
        return recorded

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(record, range(worker_count)))

    assert results == [True] * worker_count
    assert store.pending_count() == worker_count
    assert store.drain(limit=worker_count).written == worker_count


def test_unattended_adaptive_drain_keeps_simulated_steady_outbox_bounded(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    clock = [datetime.fromisoformat("2026-08-01T10:00:00")]
    monkeypatch.setattr(history_store_module, "_local_now", lambda: clock[0])
    pending = []
    oldest_ages = []

    # A 250-event burst followed by 80 events per scheduler minute is above
    # the measured average production rate.  The 100-event base batch must
    # clear it without letting the outbox age or pending count diverge.
    for minute in range(24):
        produced = 250 if minute in {0, 12} else 80
        with connect_sqlite(store.database_path, foreign_keys=True) as conn:
            for index in range(produced):
                assert store.record_event(
                    conn,
                    kind="fit_ap_radio",
                    entity_key=f"ap-{minute}-{index}:1",
                    payload={"ap_uuid": f"ap-{minute}-{index}", "channel": 36},
                    collected_at=clock[0].isoformat(timespec="seconds"),
                    meaningful_fields=("ap_uuid", "channel"),
                )
            conn.commit()
        result = store.drain(unattended_active=True, limit=10)
        pending.append(result.pending)
        oldest_ages.append(result.oldest_pending_age_seconds)
        clock[0] += timedelta(minutes=1)

    assert pending[0] == 150
    assert pending[-1] == 0
    assert max(pending) <= 160
    assert any(later < earlier for earlier, later in pairwise(pending))
    assert max(oldest_ages) <= 7 * 60


def test_corrupt_shard_reports_degraded_and_leaves_outbox_for_retry(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")
    store.history_root.mkdir(parents=True)
    (store.history_root / "devices-2026-08.db").write_bytes(b"not a sqlite database")

    result = store.drain(limit=1)

    assert result.written == 0
    assert result.degraded is True
    assert result.pending == 1
    assert store.pending_count() == 1


def test_database_fast_path_does_not_open_or_scan_history_shards(tmp_path):
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    database = Database(database_path)
    database.initialize()
    history_root = database_path.parent / "history"
    history_root.mkdir()
    corrupt_catalog = history_root / "catalog.db"
    corrupt_catalog.write_bytes(b"history data must not be opened by startup")

    database.initialize()

    assert corrupt_catalog.read_bytes() == b"history data must not be opened by startup"


def test_read_only_history_query_does_not_create_outbox_or_catalog(tmp_path):
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    database_path.parent.mkdir(parents=True)
    database = Database(database_path)
    database.initialize()
    store = HistoryStore(database_path, site_id="demo")

    assert store.query_events(kind="device_fact") == []
    assert not (database_path.parent / "history").exists()
    with database.connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='history_outbox'"
        ).fetchone() is None


def test_catalog_shard_path_cannot_escape_history_root(tmp_path):
    store = _store(tmp_path)
    assert _record(store, collected_at="2026-08-01T10:00:00", value="up")
    assert store.drain(limit=1).written == 1

    outside = store.history_root.parent / "outside.db"
    with connect_sqlite(outside, foreign_keys=True) as conn:
        conn.execute(
            "CREATE TABLE history_events (event_id TEXT PRIMARY KEY, kind TEXT, entity_key TEXT, "
            "event_type TEXT, collected_at TEXT, payload_json TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO history_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("outside", "device_interface", "device-1:GE1/0/1", "change", "2026-08-01T10:00:00", "{}", "2026-08-01T10:00:00"),
        )

    catalog = store.history_root / "catalog.db"
    with connect_sqlite(catalog, foreign_keys=True) as conn:
        conn.execute("UPDATE history_catalog SET relative_path='../outside.db'")
        conn.commit()

    assert store.query_events(kind="device_interface") == []
    assert store.count_events(kind="device_interface") == 0
    assert store.history_health()["status"] == "degraded"
    assert any("invalid_path" in error for error in store.history_health()["errors"])


def test_history_query_paginates_600_cross_month_events_with_global_time_order(tmp_path):
    store = _store(tmp_path)
    start = datetime.fromisoformat("2026-07-31T20:00:00")
    entity_key = "device-1:GE1/0/1"
    with connect_sqlite(store.database_path, foreign_keys=True) as conn:
        for sequence in range(600):
            collected_at = (start + timedelta(minutes=sequence)).isoformat(
                timespec="seconds"
            )
            assert store.record_event(
                conn,
                kind="device_interface",
                entity_key=entity_key,
                payload={
                    "device_uuid": "device-1",
                    "interface_name": "GE1/0/1",
                    "sequence": sequence,
                },
                collected_at=collected_at,
                meaningful_fields=("device_uuid", "interface_name", "sequence"),
            )
        conn.commit()

    assert store.drain(limit=500).written == 500
    assert store.drain(limit=500).written == 100
    assert store.count_events(kind="device_interface", entity_key=entity_key) == 600

    # Pagination must aggregate known shards globally before slicing.  The
    # current API has no offset yet; this call defines the required contract.
    last_page = store.query_events(
        kind="device_interface",
        entity_key=entity_key,
        limit=100,
        offset=500,
    )

    assert [row["sequence"] for row in last_page] == list(range(99, -1, -1))
    assert [row["collected_at"] for row in last_page] == sorted(
        (row["collected_at"] for row in last_page), reverse=True
    )
    bounded = store.query_events(
        kind="device_interface",
        entity_key=entity_key,
        limit=100,
        collected_to=(start + timedelta(minutes=50)).isoformat(timespec="seconds"),
    )
    assert [row["sequence"] for row in bounded] == list(range(50, -1, -1))


def test_migration_checkpoint_is_bounded_and_never_marks_source_deleted(tmp_path):
    store = _store(tmp_path)
    checkpoint = store.record_migration_checkpoint(
        "device_facts_history",
        last_source_id=25,
        rows_copied=25,
        rows_verified=25,
        status="paused",
    )

    assert checkpoint.last_source_id == 25
    assert checkpoint.rows_deleted == 0
    assert store.migration_checkpoint("device_facts_history") == checkpoint

    with pytest.raises(ValueError):
        store.record_migration_checkpoint(
            "tasks_history",
            last_source_id=1,
            rows_copied=1,
            rows_verified=1,
            status="done",
        )


def test_explicit_legacy_migration_copies_verifies_and_resumes_without_source_deletion(
    tmp_path,
):
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    database = Database(database_path)
    database.initialize()
    store = HistoryStore(database_path, site_id="demo")
    with database.connect() as conn:
        for source_id in range(1, 4):
            conn.execute(
                """
                INSERT INTO device_facts_history
                    (device_uuid, sysname, collected_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "device-1",
                    f"legacy-{source_id}",
                    f"2026-08-01T00:0{source_id}:00",
                    f"2026-08-01T00:0{source_id}:00",
                ),
            )
        conn.commit()

    paused = store.migrate_legacy_batch(
        "device_facts_history", limit=2, unattended_active=True
    )
    assert paused.paused is True
    assert not store.history_root.exists()

    first = store.migrate_legacy_batch("device_facts_history", limit=2)
    assert (first.copied, first.verified, first.pending) == (2, 2, True)
    assert first.checkpoint is not None
    assert first.checkpoint.last_source_id == 2
    assert first.checkpoint.rows_deleted == 0

    resumed = store.migrate_legacy_batch("device_facts_history", limit=2)
    assert (resumed.copied, resumed.verified, resumed.pending) == (1, 1, False)
    assert resumed.checkpoint is not None
    assert resumed.checkpoint.rows_copied == 3
    assert resumed.checkpoint.rows_verified == 3
    assert resumed.checkpoint.rows_deleted == 0
    assert resumed.checkpoint.status == "complete"

    # A copy/verify maintenance pass must not make legacy readers return a
    # duplicate before a future source-table cutover is explicitly enabled.
    assert store.query_events(kind="device_fact", entity_key="device-1") == []
    assert store.count_events(kind="device_fact", entity_key="device-1") == 0
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 3
    with connect_sqlite(store.history_root / "devices-2026-08.db", foreign_keys=True) as shard:
        assert shard.execute("SELECT COUNT(*) FROM history_events").fetchone()[0] == 3
        assert shard.execute(
            "SELECT COUNT(DISTINCT event_id) FROM history_events"
        ).fetchone()[0] == 3

    complete = store.migrate_legacy_batch("device_facts_history", limit=2)
    assert complete.copied == 0
    assert complete.checkpoint is not None
    assert complete.checkpoint.last_source_id == resumed.checkpoint.last_source_id
    assert complete.checkpoint.rows_copied == resumed.checkpoint.rows_copied


def test_legacy_migration_journals_unmigratable_rows_without_blocking_later_ids(tmp_path):
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    database = Database(database_path)
    database.initialize()
    store = HistoryStore(database_path, site_id="demo")
    with database.connect() as conn:
        conn.executemany(
            """
            INSERT INTO ac_fit_ap_radio_history
                (ac_device_uuid, ap_uuid, rid, collected_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("ac-1", "ap-valid", 1, "2026-08-01T10:00:00", "2026-08-01T10:00:00"),
                ("ac-1", "ap-no-time", 2, None, None),
                ("ac-1", "ap-no-radio", None, "2026-08-01T10:02:00", "2026-08-01T10:02:00"),
            ],
        )
        conn.commit()

    migrated = store.migrate_legacy_batch("ac_fit_ap_radio_history", limit=10)

    assert (migrated.copied, migrated.verified, migrated.skipped, migrated.pending) == (
        1,
        1,
        2,
        False,
    )
    assert migrated.checkpoint is not None
    assert migrated.checkpoint.last_source_id == 3
    assert migrated.checkpoint.rows_skipped == 2
    with connect_sqlite(store.history_root / "catalog.db", foreign_keys=True) as catalog:
        skips = catalog.execute(
            "SELECT source_id, reason FROM history_migration_skips ORDER BY source_id"
        ).fetchall()
    assert [(row["source_id"], row["reason"]) for row in skips] == [
        (2, "missing_collection_time"),
        (3, "missing_entity_key"),
    ]
    with database.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ac_fit_ap_radio_history"
        ).fetchone()[0] == 3


def test_snapshot_projection_is_not_a_generic_history_migration_source(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="unsupported legacy history source"):
        store.migrate_legacy_batch("ap_resource_snapshots")


def test_catalog_checkpoint_schema_is_additive_for_early_phase2_catalogs(tmp_path):
    store = _store(tmp_path)
    store.history_root.mkdir(parents=True)
    with connect_sqlite(store.history_root / "catalog.db", foreign_keys=True) as catalog:
        catalog.execute(
            """
            CREATE TABLE history_catalog (
                shard_id TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        catalog.execute(
            """
            CREATE TABLE history_migration_journal (
                source_table TEXT PRIMARY KEY,
                last_source_id INTEGER NOT NULL DEFAULT 0,
                rows_copied INTEGER NOT NULL DEFAULT 0,
                rows_verified INTEGER NOT NULL DEFAULT 0,
                rows_deleted INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        catalog.commit()

    checkpoint = store.record_migration_checkpoint(
        "device_facts_history",
        last_source_id=3,
        rows_copied=2,
        rows_verified=2,
        rows_skipped=1,
        status="pending",
    )

    assert checkpoint.rows_skipped == 1
    with connect_sqlite(store.history_root / "catalog.db", foreign_keys=True) as catalog:
        columns = {row[1] for row in catalog.execute("PRAGMA table_info(history_migration_journal)")}
        assert "rows_skipped" in columns
        assert catalog.execute(
            "SELECT 1 FROM sqlite_master WHERE name='history_migration_skips'"
        ).fetchone() is not None


def test_legacy_migration_resumes_10000_rows_exactly_once_after_checkpoint(
    tmp_path,
):
    database_path = tmp_path / "sites" / "demo" / "db" / "devices.db"
    database = Database(database_path)
    database.initialize()
    store = HistoryStore(database_path, site_id="demo")
    with database.connect() as conn:
        conn.executemany(
            """
            INSERT INTO device_facts_history
                (device_uuid, sysname, collected_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    "device-1",
                    f"legacy-{source_id}",
                    (
                        f"2026-08-{(source_id - 1) // 1440 + 1:02d}T"
                        f"{((source_id - 1) // 60) % 24:02d}:{(source_id - 1) % 60:02d}:00"
                    ),
                    "2026-08-01T00:00:00",
                )
                for source_id in range(1, 10_001)
            ],
        )
        conn.commit()

    for _ in range(10):
        result = store.migrate_legacy_batch("device_facts_history", limit=500)
        assert (result.copied, result.verified) == (500, 500)
    midpoint = store.migration_checkpoint("device_facts_history")
    assert midpoint is not None
    assert (midpoint.last_source_id, midpoint.rows_copied, midpoint.rows_verified) == (
        5000,
        5000,
        5000,
    )

    # Simulate a crash after the next shard commit but before its journal
    # checkpoint. Restarting must retry these source IDs without duplicating
    # their deterministic event IDs.
    with database.connect_readonly() as conn:
        interrupted_rows = conn.execute(
            "SELECT * FROM device_facts_history WHERE id > 5000 ORDER BY id LIMIT 500"
        ).fetchall()
    store._write_shard_batch(
        [store._legacy_event("device_facts_history", dict(row)) for row in interrupted_rows]
    )

    restarted = HistoryStore(database_path, site_id="demo", history_root=store.history_root)
    while True:
        result = restarted.migrate_legacy_batch("device_facts_history", limit=500)
        if not result.pending:
            break

    completed = restarted.migration_checkpoint("device_facts_history")
    assert completed is not None
    assert (completed.rows_copied, completed.rows_verified, completed.rows_deleted) == (
        10_000,
        10_000,
        0,
    )
    with connect_sqlite(restarted.history_root / "devices-2026-08.db", foreign_keys=True) as shard:
        assert shard.execute("SELECT COUNT(*) FROM history_events").fetchone()[0] == 10_000
        assert shard.execute(
            "SELECT COUNT(DISTINCT event_id) FROM history_events"
        ).fetchone()[0] == 10_000
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 10_000


def test_legacy_history_remains_queryable_alongside_new_outbox_history(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceFactRepository(database)
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO device_facts_history
                (device_uuid, sysname, collected_at, created_at)
            VALUES ('device-1', 'LEGACY', '2026-07-01T10:00:00', '2026-07-01T10:00:00')
            """
        )
        conn.commit()
    repository.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "CURRENT",
            "collected_at": "2026-08-01T10:00:00",
            "updated_at": "2026-08-01T10:00:00",
        }
    )

    history = repository.list_fact_history("device-1")

    assert [row["sysname"] for row in history] == ["CURRENT", "LEGACY"]
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_facts_history").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM history_outbox").fetchone()[0] == 1
