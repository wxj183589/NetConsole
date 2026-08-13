from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.services.history_store import HistoryStore


def _timestamp(start: datetime, sample: int, interval_minutes: int) -> str:
    return (start + timedelta(minutes=sample * interval_minutes)).isoformat(
        timespec="seconds"
    )


def _legacy_metrics(
    root: Path,
    *,
    entities: int,
    samples: int,
    interval_minutes: int,
) -> dict[str, int]:
    path = root / "legacy-history.db"
    with connect_sqlite(path, foreign_keys=True) as conn:
        conn.execute(
            """
            CREATE TABLE legacy_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ac_device_uuid TEXT NOT NULL,
                ap_uuid TEXT NOT NULL,
                ap_name TEXT,
                ap_ip TEXT,
                state_raw TEXT,
                model TEXT,
                collected_at TEXT NOT NULL,
                collect_run_uuid TEXT,
                raw_log_path TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX idx_legacy_history_ac_time "
            "ON legacy_history(ac_device_uuid, collected_at DESC, id DESC)"
        )
        baseline_bytes = path.stat().st_size
        start = datetime(2026, 8, 1, tzinfo=UTC)
        rows = [
            (
                "ac-1",
                f"ap-{entity:04d}",
                f"AP-{entity:04d}",
                f"10.0.{entity // 256}.{entity % 256}",
                "R/M",
                "WA6522",
                _timestamp(start, sample, interval_minutes),
                f"run-{sample}",
                "collection/ac-1.json",
                _timestamp(start, sample, interval_minutes),
            )
            for sample in range(samples)
            for entity in range(entities)
        ]
        conn.executemany(
            """
            INSERT INTO legacy_history
                (ac_device_uuid, ap_uuid, ap_name, ap_ip, state_raw, model,
                 collected_at, collect_run_uuid, raw_log_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        count = int(conn.execute("SELECT COUNT(*) FROM legacy_history").fetchone()[0])
    return {
        "rows": count,
        "estimated_collection_commits_per_day": samples,
        "database_baseline_bytes": baseline_bytes,
        "history_growth_bytes": path.stat().st_size - baseline_bytes,
    }


def _phase2_metrics(
    root: Path,
    *,
    entities: int,
    samples: int,
    interval_minutes: int,
) -> dict[str, int]:
    database_path = root / "sites" / "benchmark" / "db" / "devices.db"
    Database(database_path).initialize()
    current_database_baseline_bytes = database_path.stat().st_size
    store = HistoryStore(database_path, site_id="benchmark")
    start = datetime(2026, 8, 1, tzinfo=UTC)
    with connect_sqlite(database_path, foreign_keys=True) as conn:
        for sample in range(samples):
            collected_at = _timestamp(start, sample, interval_minutes)
            for entity in range(entities):
                store.record_event(
                    conn,
                    kind="fit_ap_resource",
                    entity_key=f"ac-1:ap-{entity:04d}",
                    payload={
                        "ac_device_uuid": "ac-1",
                        "ap_uuid": f"ap-{entity:04d}",
                        "state_raw": "R/M",
                    "ap_ip": f"10.0.{entity // 256}.{entity % 256}",
                    "model": "WA6522",
                    "collected_at": collected_at,
                    "collect_run_uuid": f"run-{sample}",
                    "raw_log_path": "collection/ac-1.json",
                    },
                    collected_at=collected_at,
                    meaningful_fields=(
                        "ac_device_uuid",
                        "ap_uuid",
                        "state_raw",
                        "ap_ip",
                        "model",
                    ),
                )
        conn.commit()
    written = 0
    while True:
        result = store.drain(limit=500)
        written += result.written
        if result.pending == 0 or result.degraded:
            break
    shard_bytes = sum(path.stat().st_size for path in store.history_root.glob("devices-*.db"))
    catalog_path = store.history_root / "catalog.db"
    catalog_bytes = catalog_path.stat().st_size if catalog_path.is_file() else 0
    current_database_growth_bytes = database_path.stat().st_size - current_database_baseline_bytes
    return {
        "rows": written,
        "estimated_collection_commits_per_day": samples,
        "current_database_baseline_bytes": current_database_baseline_bytes,
        # This is a fixed current-state/outbox schema and entity-state cost for
        # a stable fixture. It must not be projected as daily history growth.
        "current_database_growth_bytes": current_database_growth_bytes,
        "shard_bytes": shard_bytes,
        "catalog_bytes": catalog_bytes,
        "history_growth_bytes": shard_bytes + catalog_bytes,
        "total_incremental_bytes": current_database_growth_bytes
        + shard_bytes
        + catalog_bytes,
    }


def _telemetry_metrics(
    root: Path,
    *,
    entities: int,
    samples: int,
    interval_minutes: int,
) -> dict[str, int | float | str]:
    database_path = root / "sites" / "telemetry" / "db" / "devices.db"
    Database(database_path).initialize()
    store = HistoryStore(database_path, site_id="telemetry")
    start = datetime(2026, 8, 1, tzinfo=UTC)
    state_changes = 0
    with connect_sqlite(database_path, foreign_keys=True) as conn:
        for sample in range(samples):
            collected_at = _timestamp(start, sample, interval_minutes)
            for entity in range(entities):
                online = not (sample == samples // 2 and entity % 10 == 0)
                usage = (sample * 7 + entity) % 100
                store.record_event(
                    conn,
                    kind="fit_ap_radio",
                    entity_key=f"ap-{entity:04d}:1",
                    payload={
                        "ap_uuid": f"ap-{entity:04d}",
                        "rid": 1,
                        "status": "up" if online else "down",
                        "channel": "149",
                        "usage": usage,
                        "clients": (sample + entity) % 8,
                        "collected_at": collected_at,
                    },
                    collected_at=collected_at,
                    meaningful_fields=("ap_uuid", "rid", "status", "channel"),
                    heartbeat_seconds=1800,
                )
                state_changes += int(not online and sample == samples // 2)
        conn.commit()
    outbox_peak = store.pending_count()
    written = 0
    while True:
        result = store.drain(limit=500)
        written += result.written
        if result.pending == 0 or result.degraded:
            break
    shard_bytes = sum(path.stat().st_size for path in store.history_root.glob("devices-*.db"))
    catalog = store.history_root / "catalog.db"
    return {
        "rows": written,
        "estimated_collection_commits_per_day": samples,
        "outbox_peak": outbox_peak,
        "state_changes": state_changes,
        "history_growth_bytes": shard_bytes + (catalog.stat().st_size if catalog.is_file() else 0),
        "sampling_policy": "radio heartbeat=1800s; status/channel immediate",
    }


def _project(value: int, *, observed_days: float, days: int) -> int:
    return round(value * days / max(observed_days, 1 / 1440))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在临时目录比较 legacy history 与 change-aware 月分片增长。"
    )
    parser.add_argument("--entities", type=int, default=100)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--poll-minutes", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.entities < 1 or args.days < 1 or args.poll_minutes < 1:
        raise SystemExit("entities、days 和 poll-minutes 必须大于 0")

    samples = (args.days * 24 * 60) // args.poll_minutes
    observed_days = samples * args.poll_minutes / (24 * 60)
    # SQLite/antivirus can briefly retain a just-closed WAL handle on Windows.
    # Benchmark cleanup must not turn an otherwise valid measurement into a
    # failure or touch any user-selected data root.
    with tempfile.TemporaryDirectory(
        prefix="netconsole-history-growth-", ignore_cleanup_errors=True
    ) as temporary:
        root = Path(temporary)
        legacy = _legacy_metrics(
            root,
            entities=args.entities,
            samples=samples,
            interval_minutes=args.poll_minutes,
        )
        phase2 = _phase2_metrics(
            root,
            entities=args.entities,
            samples=samples,
            interval_minutes=args.poll_minutes,
        )
        telemetry = _telemetry_metrics(
            root,
            entities=args.entities,
            samples=samples,
            interval_minutes=args.poll_minutes,
        )
        report = {
            "fixture": {
                "entities": args.entities,
                "days": args.days,
                "poll_minutes": args.poll_minutes,
                "samples": samples,
                "stable_state": True,
            },
            "legacy_per_sample": legacy,
            "change_aware_month_shard": phase2,
            "telemetry_and_state_mix": telemetry,
            "projection": {
                f"{days}_days": {
                    "legacy_rows": _project(legacy["rows"], observed_days=observed_days, days=days),
                    "phase2_rows": _project(phase2["rows"], observed_days=observed_days, days=days),
                    "legacy_history_growth_bytes": _project(
                        legacy["history_growth_bytes"], observed_days=observed_days, days=days
                    ),
                    # The current database increase is a fixed stable-state
                    # cost. Only append-only history storage is extrapolated.
                    "phase2_current_database_fixed_bytes": phase2[
                        "current_database_growth_bytes"
                    ],
                    "phase2_history_growth_bytes": _project(
                        phase2["history_growth_bytes"],
                        observed_days=observed_days,
                        days=days,
                    ),
                    "phase2_total_incremental_bytes": phase2[
                        "current_database_growth_bytes"
                    ]
                    + _project(
                        phase2["history_growth_bytes"],
                        observed_days=observed_days,
                        days=days,
                    ),
                }
                for days in (30, 90, 365)
            },
        }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
