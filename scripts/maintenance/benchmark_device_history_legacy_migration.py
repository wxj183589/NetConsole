"""Benchmark COPY-only legacy history migration on isolated databases."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.services.history_legacy_migration import HistoryLegacyMigrationService


_DEVELOPMENT_ROOT = Path("D:/study").resolve()


def _percentiles(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0, "p95": 0, "p99": 0, "max": 0}

    def value(percentile: float) -> int:
        return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)]

    return {"p50": value(0.50), "p95": value(0.95), "p99": value(0.99), "max": ordered[-1]}


def create_synthetic_source(path: Path, rows: int) -> Path:
    database = Path(path).resolve()
    if not database.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError("synthetic migration data must remain under D:/study")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO schema_metadata VALUES
                ('schema_version', 'benchmark.legacy.v1', '', '');
            CREATE TABLE device_facts_history (
                id INTEGER PRIMARY KEY,
                device_uuid TEXT NOT NULL,
                model TEXT,
                serial_number TEXT,
                collected_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        base = datetime(2025, 12, 31, 23, 0, tzinfo=UTC)
        batch: list[tuple[Any, ...]] = []
        for source_id in range(1, rows + 1):
            collected = (base + timedelta(minutes=source_id)).isoformat().replace("+00:00", "")
            batch.append(
                (
                    source_id,
                    f"device-{source_id % 1000}",
                    "S6520",
                    f"SN-{source_id:08d}",
                    collected,
                    collected,
                )
            )
            if len(batch) == 500:
                conn.executemany("INSERT INTO device_facts_history VALUES (?, ?, ?, ?, ?, ?)", batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO device_facts_history VALUES (?, ?, ?, ?, ?, ?)", batch)
        conn.commit()
    return database


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.is_dir() else 0


def run_benchmark(
    *,
    source_database: Path,
    output_dir: Path,
    chunk_rows: int,
    slow_storage_delay_seconds: float,
) -> dict[str, Any]:
    source = Path(source_database).resolve()
    output = Path(output_dir).resolve()
    if not source.is_relative_to(_DEVELOPMENT_ROOT) or not output.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError("migration benchmark source/output must remain under D:/study")
    output.mkdir(parents=True, exist_ok=True)
    data_root = output / "runtime"
    data_root.mkdir(exist_ok=True)
    history_root = output / "history"
    diagnostics = output / "diagnostics"
    service = HistoryLegacyMigrationService(
        PathResolver(app_root=Path(__file__).resolve().parents[2], data_root=data_root),
        site_id="benchmark",
        source_database=source,
        history_root=history_root,
        diagnostics_dir=diagnostics,
        immutable_source=True,
    )
    target_before = _directory_size(history_root)
    started = time.monotonic()
    result = service.start(
        chunk_rows=chunk_rows,
        max_elapsed_seconds=0,
        slow_storage_delay_seconds=slow_storage_delay_seconds,
    )
    invocation_elapsed = time.monotonic() - started
    migration = dict(result.get("migration") or {})
    range_rows = list(result.get("ranges") or [])
    processed = int(migration.get("verified_count") or 0)
    active_chunk_elapsed = sum(int(row.get("elapsed_ms") or 0) for row in range_rows) / 1000
    started_at = datetime.fromisoformat(str(migration.get("started_at") or ""))
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    wall_elapsed = max(0.0, (datetime.now(UTC) - started_at.astimezone(UTC)).total_seconds())
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_database_name": source.name,
        "source_size_bytes": source.stat().st_size,
        "target_growth_bytes": _directory_size(history_root) - target_before,
        "chunk_rows": chunk_rows,
        "current_invocation_elapsed_seconds": round(invocation_elapsed, 3),
        "active_chunk_elapsed_seconds": round(active_chunk_elapsed, 3),
        "wall_elapsed_since_start_seconds": round(wall_elapsed, 3),
        "rows_copied": int(migration.get("copied_count") or 0),
        "rows_verified": processed,
        "duplicate_count": int(migration.get("duplicate_count") or 0),
        "error_count": int(migration.get("error_count") or 0),
        "active_rows_per_second": round(processed / max(active_chunk_elapsed, 0.000001), 2),
        "target_commits": int(migration.get("target_commits") or 0),
        "checkpoint_commits": int(migration.get("checkpoint_commits") or 0),
        "chunk_latency_ms": _percentiles([int(row.get("elapsed_ms") or 0) for row in range_rows]),
        "months": sorted(
            {str(row.get("target_month") or "") for row in range_rows if row.get("target_month") != "INVALID"}
        ),
        "slow_storage_delay_seconds": slow_storage_delay_seconds,
        "result": result.get("result"),
        "source_preserved": True,
        "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
    }
    report_path = output / "DEVICE_HISTORY_MIGRATION_BENCHMARK.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--synthetic-rows", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-rows", type=int, default=250, choices=(100, 250, 500))
    parser.add_argument("--slow-storage-delay-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    if bool(args.source_db) == bool(args.synthetic_rows):
        raise SystemExit("choose exactly one of --source-db or --synthetic-rows")
    output = args.output_dir.resolve()
    source = (
        args.source_db.resolve()
        if args.source_db
        else create_synthetic_source(output / "source" / "devices.db", args.synthetic_rows)
    )
    report = run_benchmark(
        source_database=source,
        output_dir=output,
        chunk_rows=args.chunk_rows,
        slow_storage_delay_seconds=max(0.0, args.slow_storage_delay_seconds),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
