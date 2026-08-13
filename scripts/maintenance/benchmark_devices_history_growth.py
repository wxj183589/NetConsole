from __future__ import annotations

import argparse
import json
import tempfile
import time
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
        "synthetic_sample_count": samples,
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
        "synthetic_sample_count": samples,
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
) -> dict[str, object]:
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
        "synthetic_sample_count": samples,
        "outbox_peak": outbox_peak,
        "state_changes": state_changes,
        "history_growth_bytes": shard_bytes + (catalog.stat().st_size if catalog.is_file() else 0),
        "sampling_policy": "radio heartbeat=1800s; status/channel immediate",
    }


def _production_metrics(
    root: Path,
    *,
    entities: int,
    samples: int,
    interval_minutes: int,
    slow_storage_ms: int = 0,
) -> dict[str, object]:
    """Exercise collector cadence and the real one-minute history scheduler on virtual time."""

    database_path = root / "sites" / "production-shaped" / "db" / "devices.db"
    Database(database_path).initialize()
    virtual_now = [datetime(2026, 8, 1, tzinfo=UTC)]
    store = HistoryStore(
        database_path,
        site_id="production-shaped",
        clock=lambda: virtual_now[0],
    )
    if slow_storage_ms > 0:
        original_write = store._write_shard_batch

        def delayed_write(rows):
            time.sleep(slow_storage_ms / 1000)
            original_write(rows)

        store._write_shard_batch = delayed_write

    generated = 0
    logical_transactions = 0
    peak_pending = 0
    peak_age = 0
    drained_during_unattended = 0
    drain_cycles = 0
    shard_commits = 0
    drain_elapsed_ms: list[int] = []
    started = time.perf_counter()
    kinds = (
        "fit_ap_resource", "fit_ap_radio", "fit_ap_optical", "fit_ap_lldp",
        "device_interface", "device_optical", "device_lldp",
    )
    collector_periods = {
        "fit_ap_resource": 5,
        "fit_ap_radio": 5,
        "fit_ap_optical": 15,
        "fit_ap_lldp": 15,
        "device_interface": 5,
        "device_optical": 15,
        "device_lldp": 15,
    }
    total_minutes = samples * interval_minutes
    with connect_sqlite(database_path, foreign_keys=True) as conn:
        for minute in range(total_minutes):
            virtual_now[0] = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(minutes=minute)
            due_kinds = [kind for kind, period in collector_periods.items() if minute % period == 0]
            if due_kinds:
                collected_at = virtual_now[0].isoformat(timespec="seconds")
            for entity in range(entities):
                if not due_kinds:
                    continue
                ap = f"ap-{entity:04d}"
                status = "down" if minute == total_minutes // 2 and entity % 10 == 0 else "up"
                common = {"ap_uuid": ap, "status": status, "channel": 149}
                events = (
                    ("fit_ap_resource", f"ac-1:{ap}", common, ("ap_uuid", "status")),
                    ("fit_ap_radio", f"{ap}:1", {**common, "rid": 1, "usage": minute % 100}, ("ap_uuid", "rid", "status", "channel")),
                    ("fit_ap_radio", f"{ap}:2", {**common, "rid": 2, "usage": (minute + 1) % 100}, ("ap_uuid", "rid", "status", "channel")),
                    ("fit_ap_optical", ap, {**common, "optical_alarm_status": "normal", "rx": -3.0}, ("ap_uuid", "optical_alarm_status")),
                    ("fit_ap_lldp", ap, {**common, "neighbor": "sw-1", "port": "GE1/0/1"}, ("ap_uuid", "neighbor", "port")),
                    ("device_interface", f"device-1:GE{entity}/0/1", {"device_uuid": "device-1", "interface_name": f"GE{entity}/0/1", "link_status": status}, ("device_uuid", "interface_name", "link_status")),
                    ("device_optical", f"device-1:GE{entity}/0/1", {"device_uuid": "device-1", "interface_name": f"GE{entity}/0/1", "status": "normal", "rx": -3.0}, ("device_uuid", "interface_name", "status")),
                    ("device_lldp", f"device-1:GE{entity}/0/1", {"device_uuid": "device-1", "local_interface": f"GE{entity}/0/1", "neighbor": "sw-1"}, ("device_uuid", "local_interface", "neighbor")),
                )
                for kind, key, payload, fields in events:
                    if kind not in due_kinds:
                        continue
                    payload = {**payload, "collected_at": collected_at, "collect_run_uuid": f"run-{minute}"}
                    generated += int(store.record_event(conn, kind=kind, entity_key=key, payload=payload, collected_at=collected_at, meaningful_fields=fields))
            if due_kinds:
                conn.commit()
                logical_transactions += 1
            # Backend's unattended scheduler is a one-minute loop, independent
            # of collector cadence.  Every virtual minute is one drain cycle.
            result = store.drain(unattended_active=True, limit=100, max_elapsed_seconds=2.0)
            drain_cycles += 1
            drained_during_unattended += result.written
            shard_commits += result.shard_commits
            drain_elapsed_ms.append(result.elapsed_ms)
            diagnostics = store.outbox_diagnostics()
            peak_pending = max(peak_pending, diagnostics.pending, result.pending)
            peak_age = max(peak_age, diagnostics.oldest_pending_age_seconds, result.oldest_pending_age_seconds)
    pending_before_catchup = store.pending_count()
    oldest_before_catchup = store.outbox_diagnostics().oldest_pending_age_seconds
    catchup_drained = 0
    while store.pending_count():
        result = store.drain(limit=500)
        catchup_drained += result.written
        if result.degraded or result.written == 0:
            break
    shard_bytes = sum(path.stat().st_size for path in store.history_root.glob("devices-*.db"))
    catalog = store.history_root / "catalog.db"
    return {
        "events_generated": generated,
        "events_drained_during_unattended": drained_during_unattended,
        "pending_before_catchup": pending_before_catchup,
        "oldest_pending_before_catchup_seconds": oldest_before_catchup,
        "peak_pending_during_unattended": peak_pending,
        "peak_oldest_pending_age_seconds": peak_age,
        "catchup_drained": catchup_drained,
        "final_pending_after_catchup": store.pending_count(),
        "drain_cycles": drain_cycles,
        "virtual_duration_minutes": total_minutes,
        "history_scheduler_interval_minutes": 1,
        "shard_commit_count": shard_commits,
        "average_drain_elapsed_ms": round(sum(drain_elapsed_ms) / max(1, len(drain_elapsed_ms)), 2),
        "max_drain_elapsed_ms": max(drain_elapsed_ms, default=0),
        "logical_transaction_count": logical_transactions,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "current_database_bytes": database_path.stat().st_size,
        "shard_bytes": shard_bytes,
        "catalog_bytes": catalog.stat().st_size if catalog.is_file() else 0,
        "slow_storage_ms": slow_storage_ms,
        "kinds": list(kinds),
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
    parser.add_argument(
        "--slow-storage-ms",
        type=int,
        nargs="+",
        default=[0],
        help="每个 shard chunk 注入的慢存储毫秒数，可重复/一次传入多个档位",
    )
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
        production_by_delay = {
            str(max(0, delay)): _production_metrics(
                root / f"slow-{max(0, delay)}",
                entities=args.entities,
                samples=samples,
                interval_minutes=args.poll_minutes,
                slow_storage_ms=max(0, delay),
            )
            for delay in args.slow_storage_ms
        }
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
            "production_shaped": production_by_delay[str(max(0, args.slow_storage_ms[0]))],
            "production_shaped_by_slow_storage": production_by_delay,
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
