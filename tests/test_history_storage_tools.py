from __future__ import annotations

import json
import sqlite3

import netconsole.services.history_store as history_store_module
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.services.history_store import HistoryStore
from scripts.maintenance.benchmark_device_history_storage_queries import run_benchmark
from scripts.maintenance.profile_device_history_storage import (
    profile_legacy_history,
    profile_v1_history,
)
from scripts.maintenance.validate_history_migration_server_hdd import validate_evidence


def _event(event_id: str, collected_at: str, value: str) -> dict[str, str]:
    return {
        "event_id": event_id,
        "kind": "device_fact",
        "entity_key": "device-1",
        "event_type": "legacy",
        "collected_at": collected_at,
        "payload_json": json.dumps(
            {
                "id": int(event_id[0], 16) + 1,
                "device_uuid": "device-1",
                "model": value,
                "collected_at": collected_at,
                "created_at": collected_at,
            },
            separators=(",", ":"),
        ),
        "created_at": collected_at,
    }


def _write_v1_shard(root, period: str, events: list[dict[str, str]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(root / f"devices-{period}.db", foreign_keys=True) as shard:
        shard.executescript(history_store_module.SHARD_SCHEMA_V1)
        shard.executemany(
            """
            INSERT INTO history_events
                (event_id, kind, entity_key, event_type, collected_at,
                 payload_json, created_at)
            VALUES (:event_id, :kind, :entity_key, :event_type, :collected_at,
                    :payload_json, :created_at)
            """,
            events,
        )
        shard.commit()


def test_storage_profiler_and_query_benchmark_use_small_isolated_fixtures(tmp_path):
    source = tmp_path / "source" / "devices.db"
    source.parent.mkdir(parents=True)
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES ('schema_version', 'test');
            CREATE TABLE device_facts_history (
                id INTEGER PRIMARY KEY,
                device_uuid TEXT NOT NULL,
                model TEXT,
                collected_at TEXT,
                created_at TEXT
            );
            CREATE INDEX idx_device_facts_history_time
                ON device_facts_history(device_uuid, collected_at DESC, id DESC);
            INSERT INTO device_facts_history VALUES
                (1, 'device-1', 'S1', '2026-06-30T23:59:00', '2026-06-30T23:59:00'),
                (2, 'device-1', 'S2', '2026-07-01T00:01:00', '2026-07-01T00:01:00');
            """
        )

    june = [
        _event(f"{index:064x}", "2026-06-30T23:59:00", f"S{index}")
        for index in range(1, 351)
    ]
    july = [
        _event(f"{index:064x}", "2026-07-01T00:01:00", f"S{index}")
        for index in range(351, 701)
    ]
    v1_root = tmp_path / "v1"
    _write_v1_shard(v1_root, "2026-06", june)
    _write_v1_shard(v1_root, "2026-07", july)

    v2_root = tmp_path / "v2"
    store = HistoryStore(tmp_path / "current" / "devices.db", site_id="demo")
    store.history_root = v2_root
    assert store._write_shard_batch(june) == 350
    assert store._write_shard_batch(july) == 350

    profile_dir = tmp_path / "profile"
    legacy = profile_legacy_history(source, output_dir=profile_dir, decompose=False)
    v1 = profile_v1_history(v1_root, output_dir=profile_dir, decompose=False)
    assert legacy["supported_rows"] == 2
    assert legacy["quick_check"] == "ok"
    assert v1["rows"] == 700
    assert all(item["quick_check"] == "ok" for item in v1["shards"])

    report = run_benchmark(
        v1_root=v1_root,
        v2_root=v2_root,
        output_dir=tmp_path / "query",
        iterations=1,
    )
    assert all(case["event_ids_match"] for case in report["cases"].values())
    plans = report["query_plans"]
    assert any("idx_history_events_entity_time" in item for item in plans["v1_entity_time"])
    assert plans["v1_time"]
    assert any(
        "idx_history_events_v2_entity_time" in item
        for item in plans["v2_entity_time"]
    ), plans
    assert any(
        "idx_history_events_v2_kind_time" in item
        for item in plans["v2_kind_time"]
    )
    assert (tmp_path / "query" / "HISTORY_QUERY_BENCHMARK.json").is_file()


def test_server_hdd_validator_keeps_missing_field_evidence_pending() -> None:
    report = validate_evidence(
        {
            "result": "COPY_ONLY_READY",
            "error_count": 0,
            "active_rows_per_second": 123.4,
            "chunk_latency_ms": {"p50": 10, "p95": 20, "p99": 30, "max": 40},
        },
        {
            "database": {"exists": True, "history_pending": 0},
            "disk_performance": {
                "active_time_percent": "unknown",
                "queue_length": "unknown",
            },
        },
        {
            "target_media_is_hdd": False,
            "migration_pause_verified": True,
            "backend_ready_verified": True,
            "outbox_recovered": True,
            "ground_unattended_healthy": True,
            "syslog_receive_healthy": True,
            "mr_ping_task_persistence_healthy": True,
            "disk_not_sustained_saturated": True,
        },
    )

    assert report["server_hdd_storage_v2_test"] == "PENDING"
    assert "target_media_is_hdd" in report["unmet_or_missing_gates"]
    assert "disk_performance_counter" in report["unmet_or_missing_gates"]
    assert report["migration_executed_by_validator"] is False
