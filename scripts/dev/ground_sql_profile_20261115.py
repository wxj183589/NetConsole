"""Bounded synthetic SQL profile for the ground unattended read paths.

This harness uses an isolated fixture only. It never opens production or real
development data and does not claim field, Electron, or long-run acceptance.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from netconsole.core.performance_profiling import begin_request_profile, end_request_profile
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository


SITE_ID = "profile-site"
RUN_ID = "profile-run"
NOW = "2026-11-15T10:00:00+08:00"


def _fixture(root: Path) -> GroundUnattendedRepository:
    repository = GroundUnattendedRepository(root / "ground" / "index.sqlite", site_id=SITE_ID)
    repository.create_or_get_run(
        run_id=RUN_ID,
        run_date="2026-11-15",
        scheduled_start_at=NOW,
        scheduled_end_at="2026-11-15T18:00:00+08:00",
    )
    trains = [
        {"train_id": f"train-{index:03d}", "train_no": f"T{index + 1:03d}", "train_name": f"列车 {index + 1:03d}"}
        for index in range(50)
    ]
    endpoints = [
        {
            "device_uuid": f"mr-{index:03d}", "device_id": index + 1,
            "train_id": f"train-{index // 2:03d}", "mr_role": "CT" if index % 2 == 0 else "CW",
            "device_name": f"MR-{index + 1:03d}", "management_ip": f"192.0.2.{index + 1}",
            "backup_management_ip": f"198.51.100.{index + 1}", "protocol": "SSH", "port": 22,
        }
        for index in range(100)
    ]
    repository.sync_inventory(trains=trains, endpoints=endpoints, heartbeat_revision=0)
    repository.upsert_heartbeat_snapshots(
        RUN_ID,
        [
            {
                "entity_type": "MR", "entity_id": endpoint["device_uuid"],
                "snapshot": {"status": "UP", "engine_state": "RUNNING", "management_ip": endpoint["management_ip"]},
            }
            for endpoint in endpoints
        ],
    )
    for index in range(20):
        repository.save_quick_ping_state(
            {
                "site_id": SITE_ID, "run_id": f"quick-{index:03d}", "run_date": "2026-11-15",
                "state": "COMPLETED", "targets": [{"target_ip": f"192.0.2.{index + 1}", "mr_id": f"mr-{index:03d}", "train_id": f"train-{index // 2:03d}", "mr_role": "CT"}],
                "config": {"timeout_ms": 1000}, "segment_paths": [], "started_at": NOW, "ended_at": NOW,
            },
            {f"192.0.2.{index + 1}": {"received": 10, "avg_rtt_ms": 2.5, "min_rtt_ms": 2.0, "max_rtt_ms": 3.0}},
            {f"192.0.2.{index + 1}": {"rtt_sum_ms": 25.0, "jitter_sum_ms": 1.0, "jitter_count": 10}},
            event={"event_type": "COMPLETED", "state": "COMPLETED", "ts": NOW, "details": {}},
        )
    return repository


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile / 100)))
    return ordered[index]


def _measure(name: str, function: Callable[[], Any], *, iterations: int = 60) -> dict[str, Any]:
    wall: list[float] = []
    sql_counts: list[int] = []
    sql_ms: list[float] = []
    response_bytes: list[int] = []
    slowest: list[tuple[float, str]] = []
    for index in range(iterations):
        profile, token = begin_request_profile(f"profile-{name}-{index}", "GET", f"/profile/{name}")
        started = time.perf_counter()
        encoded_size = 0
        try:
            result = function()
            encoded_size = len(json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"))
            if hasattr(profile, "record_response_bytes"):
                profile.record_response_bytes(encoded_size)
        finally:
            wall.append((time.perf_counter() - started) * 1000)
            sql_counts.append(profile.sql_count)
            sql_ms.append(profile.sql_ms)
            response_bytes.append(int(getattr(profile, "response_bytes", 0) or 0) or encoded_size)
            slowest.extend(getattr(profile, "slowest_sql", []))
            end_request_profile(token)
    slowest.sort(key=lambda item: item[0], reverse=True)
    return {
        "iterations": iterations,
        "wall_ms": {"p50": _percentile(wall, 50), "p95": _percentile(wall, 95), "p99": _percentile(wall, 99), "max": max(wall)},
        "sql_count": {"p50": _percentile([float(value) for value in sql_counts], 50), "p95": _percentile([float(value) for value in sql_counts], 95), "max": max(sql_counts)},
        "sql_ms": {"p50": _percentile(sql_ms, 50), "p95": _percentile(sql_ms, 95), "p99": _percentile(sql_ms, 99), "max": max(sql_ms)},
        "response_bytes": {"p50": _percentile([float(value) for value in response_bytes], 50), "max": max(response_bytes)},
        "slowest_sql": [{"ms": round(ms, 4), "sql": sql} for ms, sql in slowest[:5]],
    }


def _explain(db_path: Path) -> dict[str, list[str]]:
    statements = {
        "inventory": "SELECT i.*, p.enabled, p.priority FROM ground_unattended_train_inventory i LEFT JOIN ground_unattended_train_policies p ON p.site_id=i.site_id AND p.train_id=i.train_id WHERE i.site_id=? AND i.inventory_status='ACTIVE' ORDER BY i.train_no",
        "heartbeat_snapshots": "SELECT * FROM ground_unattended_heartbeat_states WHERE site_id=? AND run_id=? AND entity_type=? ORDER BY entity_type, entity_id",
        "quick_ping_runs": "SELECT * FROM ground_unattended_quick_ping_runs WHERE site_id=? ORDER BY started_at DESC, run_id DESC LIMIT ?",
        "raw_files": "SELECT * FROM ground_unattended_raw_files WHERE site_id=? AND run_id=? AND data_type=? ORDER BY start_time, relative_path LIMIT ?",
    }
    result: dict[str, list[str]] = {}
    with sqlite3.connect(db_path) as connection:
        for name, sql in statements.items():
            params = {
                "inventory": (SITE_ID,),
                "heartbeat_snapshots": (SITE_ID, RUN_ID, "MR"),
                "quick_ping_runs": (SITE_ID, 100),
                "raw_files": (SITE_ID, RUN_ID, "ping", 100),
            }[name]
            result[name] = [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params)]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=60)
    args = parser.parse_args()
    if args.iterations < 5:
        parser.error("iterations must be >= 5")
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.output / "fixture"
    root.mkdir(parents=True, exist_ok=False)
    repository = _fixture(root)
    cases: dict[str, Callable[[], Any]] = {
        "inventory": lambda: repository.list_inventory(include_removed=False),
        "heartbeat_inventory_state": repository.heartbeat_inventory_state,
        "heartbeat_snapshots": lambda: repository.list_heartbeat_snapshots(RUN_ID, entity_type="MR"),
        "quick_ping_runs": lambda: repository.list_quick_ping_runs(limit=100),
        "quick_ping_query": lambda: repository.query_quick_ping_runs(limit=20, query="quick-"),
        "quick_ping_events": lambda: repository.list_quick_ping_events("quick-001", limit=500),
        "raw_files": lambda: repository.list_raw_files_for_query(data_type="ping", start_time="", end_time="", run_id=RUN_ID, limit=100),
    }
    metrics = {name: _measure(name, function, iterations=args.iterations) for name, function in cases.items()}
    with sqlite3.connect(repository.db_path) as connection:
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    result = {
        "harness": "synthetic_isolated_fixture",
        "site_id": SITE_ID,
        "trains": 50,
        "mr": 100,
        "ip": 200,
        "iterations": args.iterations,
        "db_bytes": repository.db_path.stat().st_size,
        "journal_mode": journal_mode,
        "explain_query_plan": _explain(repository.db_path),
        "metrics": metrics,
        "note": "No production or real development data opened; response bytes are JSON projection bytes; no GUI or device traffic.",
    }
    (args.output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output / 'metrics.json'), "db_bytes": result["db_bytes"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
