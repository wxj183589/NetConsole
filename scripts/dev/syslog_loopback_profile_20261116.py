"""Real UDP loopback profile for the Ground Syslog pipeline.

The harness creates only synthetic inventory and SQLite under the supplied
canonical test-data output.  It exercises receive -> raw append -> parse ->
position projection with concurrent burst senders and exact duplicate lines.
"""
from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from netconsole.core import database as database_module
from netconsole.core.storage_io import StorageIOProfile
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.syslog_runtime import SyslogUdpReceiver


SITE_ID = "loopback-site"
RUN_DATE = "2026-11-16"


def _message(hostname: str, index: int) -> bytes:
    return (
        f"%Nov 16 10:00:{index % 60:02d}:000 2026 {hostname} "
        "%%10WMESH/5/MESH_LINKUP: Mesh Link on the interface "
        f"WLAN-MeshLink841 is up: peer MAC = 0200-0000-{index + 1:04x}, "
        "peer radio mode = 3, RSSI = 25."
    ).encode("utf-8")


def _wait_until(predicate, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    if not predicate():
        raise TimeoutError("loopback pipeline did not drain before timeout")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile / 100)))
    return ordered[index]


def _run_load(root: Path, mr_count: int, trace: dict[str, Any], *, observe_transactions: bool = False) -> dict[str, Any]:
    trace_start = {
        "sql_statements": int(trace.get("sql_statements", 0)),
        "sql_writes": int(trace.get("sql_writes", 0)),
        "sql_by_prefix": dict(trace.get("sql_by_prefix", {})),
    }
    repository = GroundUnattendedRepository(root / "ground" / "index.sqlite", site_id=SITE_ID)
    repository.set_transaction_observability(observe_transactions)
    trains = [
        {"train_id": f"train-{index:03d}", "train_no": f"T{index + 1:03d}", "train_name": f"Synthetic train {index + 1:03d}"}
        for index in range(max(1, (mr_count + 1) // 2))
    ]
    endpoints = []
    for index in range(mr_count):
        hostname = f"LOOPBACK-MR-{index + 1:03d}"
        endpoints.append(
            {
                "device_uuid": f"loopback-mr-{index + 1:03d}",
                "device_id": index + 1,
                "train_id": f"train-{index // 2:03d}",
                "mr_role": "CT" if index % 2 == 0 else "CW",
                "device_name": hostname,
                "source_hostname": hostname,
                "management_ip": f"192.0.2.{index + 1}",
                "backup_management_ip": f"198.51.100.{index + 1}",
                "protocol": "SSH",
                "port": 22,
            }
        )
    repository.sync_inventory(trains=trains, endpoints=endpoints, heartbeat_revision=0)
    run_id = f"loopback-{mr_count:03d}"
    repository.create_or_get_run(
        run_id=run_id,
        run_date=RUN_DATE,
        scheduled_start_at="2026-11-16T10:00:00+08:00",
        scheduled_end_at="2026-11-16T18:00:00+08:00",
    )

    receiver = SyslogUdpReceiver(repository=repository, site_id=SITE_ID)
    started_batches: list[float] = []
    lock_errors: list[str] = []
    original_commit = repository.commit_wmesh_projection_batch
    original_raw = repository.upsert_raw_file

    def commit(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return original_commit(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).casefold() or "busy" in str(exc).casefold():
                lock_errors.append(str(exc))
            raise
        finally:
            started_batches.append((time.perf_counter() - started) * 1000)

    def raw(*args: Any, **kwargs: Any) -> Any:
        try:
            return original_raw(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).casefold() or "busy" in str(exc).casefold():
                lock_errors.append(str(exc))
            raise

    repository.commit_wmesh_projection_batch = commit  # type: ignore[method-assign]
    repository.upsert_raw_file = raw  # type: ignore[method-assign]
    try:
        receiver.start(
            run_id=run_id,
            run_date=RUN_DATE,
            active_dir=root / "ground" / "active" / RUN_DATE,
            listen_host="127.0.0.1",
            listen_port=0,
            queue_capacity=256,
            flush_records=50,
            flush_interval_seconds=0.05,
            event_batch_size=100,
            event_batch_interval_seconds=0.05,
            storage_profile=StorageIOProfile.conservative(),
        )
        port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
        payloads: list[bytes] = []
        for index in range(mr_count):
            hostname = f"LOOPBACK-MR-{index + 1:03d}"
            payload = _message(hostname, index)
            payloads.extend((payload, payload))
        burst_started = time.perf_counter()

        def send(items: list[bytes]) -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                for payload in items:
                    sender.sendto(payload, ("127.0.0.1", port))

        sender_count = min(10, max(1, len(payloads)))
        groups = [payloads[offset::sender_count] for offset in range(sender_count)]
        threads = [threading.Thread(target=send, args=(group,)) for group in groups]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            if thread.is_alive():
                raise RuntimeError("loopback sender did not finish")
        total = len(payloads)
        _wait_until(lambda: receiver.health_snapshot()["received"] == total)
        _wait_until(
            lambda: receiver.health_snapshot()["parsed"] == total
            and receiver.health_snapshot()["database_pending_count"] == 0
        )
        elapsed = time.perf_counter() - burst_started
        health_during_drain = receiver.health_snapshot()
        stop = receiver.stop(timeout_seconds=30)
        health = receiver.health_snapshot()
    finally:
        if receiver.running:
            receiver.stop(timeout_seconds=30)

    with sqlite3.connect(repository.db_path) as connection:
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        wal_bytes = repository.db_path.with_name(repository.db_path.name + "-wal").stat().st_size if repository.db_path.with_name(repository.db_path.name + "-wal").exists() else 0
        raw_file_count, raw_record_count = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(record_count), 0) "
            "FROM ground_unattended_raw_files WHERE site_id=? AND run_id=? AND data_type='syslog'",
            (SITE_ID, run_id),
        ).fetchone()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM ground_unattended_wmesh_events WHERE site_id=? AND run_id=?",
            (SITE_ID, run_id),
        ).fetchone()[0]
    current_prefix = dict(trace.get("sql_by_prefix", {}))
    trace_delta = {
        "sql_statements": int(trace.get("sql_statements", 0)) - trace_start["sql_statements"],
        "sql_writes": int(trace.get("sql_writes", 0)) - trace_start["sql_writes"],
        "sql_by_prefix": {
            key: int(value) - int(trace_start["sql_by_prefix"].get(key, 0))
            for key, value in current_prefix.items()
            if int(value) - int(trace_start["sql_by_prefix"].get(key, 0))
        },
    }
    transaction_metrics = repository.transaction_metrics_snapshot() if observe_transactions else {}
    durations = list(transaction_metrics.pop("transaction_duration_ms", ()))
    return {
        "mr_count": mr_count,
        "ip_count": mr_count * 2,
        "messages_sent": len(payloads),
        "exact_duplicate_pairs_sent": mr_count,
        "burst_seconds": round(elapsed, 4),
        "receive_eps": round(len(payloads) / max(elapsed, 0.001), 3),
        "health_during_drain": {
            key: health_during_drain.get(key)
            for key in (
                "udp_queue_length", "parser_queue_size", "disk_queue_count",
                "raw_writer_queue_length", "oldest_unprocessed_log_wait_seconds",
                "udp_receive_rate_per_second", "parser_rate_per_second",
                "queue_max_depth", "queue_wait_p50_ms", "queue_wait_p95_ms",
                "raw_file_register_p95_ms", "raw_file_register_retry_count",
                "raw_file_pending_count", "projection_checkpoint_blocked_count",
                "projection_failed_count", "projection_completed_count",
                "projection_failure_types",
                "projection_started_count", "projection_p95_ms",
                "projection_checkpoint_advanced_count", "raw_file_missing_count",
            )
        },
        "health": {
            key: health.get(key)
            for key in (
                "received", "written", "parsed", "db_saved", "dropped",
                "parse_success_count", "parse_error_count", "parse_ignored_count",
                "position_update_count", "position_duplicate_count", "position_out_of_order_count",
                "position_latency_p50_ms", "position_latency_p95_ms", "position_latency_p99_ms",
                "stage_receive_to_raw_p95_ms", "stage_raw_to_parse_p95_ms",
                "stage_parse_to_position_p95_ms", "database_last_batch_duration_ms",
                "raw_flush_count", "durable_sync_count", "spool_bytes", "spool_files",
                "compression_queue_full_count", "compression_recovery_count",
            )
        },
        "stop": stop,
        "raw_file_count": raw_file_count,
        "raw_record_count": raw_record_count,
        "event_count": event_count,
        "journal_mode": journal_mode,
        "wal_bytes_after_close": wal_bytes,
        "commit_batch_count": len(started_batches),
        "commit_batch_ms": {
            "p50": _percentile(started_batches, 50),
            "p95": _percentile(started_batches, 95),
            "p99": _percentile(started_batches, 99),
            "max": max(started_batches) if started_batches else 0.0,
        },
        "lock_errors": len(lock_errors),
        "trace": trace_delta,
        "transaction_metrics": {
            **transaction_metrics,
            "duration_p50_ms": _percentile(durations, 50),
            "duration_p95_ms": _percentile(durations, 95),
            "duration_p99_ms": _percentile(durations, 99),
        } if observe_transactions else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--loads", default="20,50,100")
    parser.add_argument("--observe-transactions", action="store_true")
    args = parser.parse_args()
    loads = [int(value) for value in args.loads.split(",") if value.strip()]
    if not loads or any(value < 1 for value in loads):
        parser.error("loads must be a comma-separated list of positive MR counts")
    args.output.mkdir(parents=True, exist_ok=True)
    original_connect = database_module.connect_sqlite
    trace_lock = threading.Lock()
    trace = {"sql_statements": 0, "sql_writes": 0, "sql_by_prefix": {}}

    def traced_connect(*connect_args: Any, **connect_kwargs: Any):
        connection = original_connect(*connect_args, **connect_kwargs)

        def callback(statement: str) -> None:
            normalized = str(statement or "").strip()
            prefix = normalized.split(None, 1)[0].upper() if normalized else "EMPTY"
            with trace_lock:
                trace["sql_statements"] += 1
                trace["sql_by_prefix"][prefix] = trace["sql_by_prefix"].get(prefix, 0) + 1
                if prefix in {"INSERT", "UPDATE", "DELETE", "REPLACE", "BEGIN", "COMMIT"}:
                    trace["sql_writes"] += 1

        connection.set_trace_callback(callback)
        return connection

    if not args.observe_transactions:
        database_module.connect_sqlite = traced_connect  # type: ignore[assignment]
    try:
        results = []
        for mr_count in loads:
            load_root = args.output / f"load-{mr_count:03d}"
            load_root.mkdir(parents=True, exist_ok=False)
            results.append(_run_load(
                load_root, mr_count, trace,
                observe_transactions=args.observe_transactions,
            ))
    finally:
        if not args.observe_transactions:
            database_module.connect_sqlite = original_connect
    output = {
        "harness": "synthetic_real_udp_loopback",
        "loads": results,
        "trace": trace,
        "transaction_observability": args.observe_transactions,
        "trace_source": "repository" if args.observe_transactions else "sqlite_connect_callback",
        "note": "No production or real development data opened; 100 MR load carries 200 synthetic IP addresses, each burst includes an exact duplicate; no packet drop is accepted.",
    }
    (args.output / "metrics.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output / "metrics.json"), "loads": [item["mr_count"] for item in results]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
