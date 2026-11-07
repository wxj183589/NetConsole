"""Run a bounded Ground V2 pressure check with mock-only inputs.

The harness exercises the production heartbeat state engine, the bounded task
scheduler, a Raw-first parser queue, and competing SQLite writers. It never
opens a network socket, starts fping, or reads a configured data root.

Example::

    python -m scripts.dev.ground_r3_short_stress
    python -m scripts.dev.ground_r3_short_stress --targets 500 --iterations 3
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sqlite3
import threading
import time
import tracemalloc
import uuid

from netconsole.core.runtime_environment import test_data_root_base
from netconsole.services.ground_unattended.heartbeat_state import (
    HeartbeatIpObservation,
    HeartbeatStateEngine,
    HeartbeatTarget,
)
from netconsole.services.ground_unattended.task_scheduler import GroundTaskScheduler


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _heartbeat_batch(target_count: int) -> dict[str, object]:
    engine = HeartbeatStateEngine()
    targets = [
        HeartbeatTarget(
            mr_uuid=f"mock-mr-{index}",
            train_id=f"mock-train-{index // 2}",
            role="CT" if index % 2 == 0 else "CW",
            management_ips=(f"192.0.{(index // 250) + 2}.{(index % 250) + 1}",),
        )
        for index in range(target_count)
    ]
    engine.configure_targets(targets)
    engine.set_engine_state("RUNNING")
    started = time.perf_counter()
    samples = 0
    for target in targets:
        engine.record_cycle(
            target.mr_uuid,
            {
                ip: HeartbeatIpObservation(ip=ip, success=True, rtt_ms=1.0)
                for ip in target.management_ips
            },
            at=datetime.now(timezone.utc),
        )
        samples += len(target.management_ips)
    return {
        "targets": target_count,
        "samples": samples,
        "online": sum(snapshot.status == "ONLINE" for snapshot in engine.snapshots()),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _scheduler_batch(task_count: int) -> dict[str, object]:
    scheduler = GroundTaskScheduler(
        capacities={"HEARTBEAT": 4, "QUICK_PING": max(task_count, 1)},
    )
    calls: list[str] = []
    scheduler.submit("HEARTBEAT", lambda: calls.append("heartbeat"), priority=100)
    for index in range(task_count):
        def callback(index: int = index) -> None:
            time.sleep(0.0005)
            if index % 29 == 0:
                raise RuntimeError("synthetic quick ping failure")
            calls.append(f"quick-{index}")

        scheduler.submit("QUICK_PING", callback, priority=index % 3)

    def run_once(domain: str) -> None:
        scheduler.run_once(domain)

    with ThreadPoolExecutor(max_workers=min(32, task_count + 1)) as pool:
        futures = [pool.submit(run_once, "HEARTBEAT")]
        futures.extend(pool.submit(run_once, "QUICK_PING") for _ in range(task_count))
        for future in futures:
            future.result()
    snapshot = scheduler.snapshot()
    return {
        "submitted": task_count + 1,
        "callback_count": len(calls),
        "snapshot": snapshot,
    }


def _syslog_batch(root: Path, record_count: int) -> dict[str, object]:
    raw_path = root / "raw" / "burst.ndjson"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index in range(record_count):
            handle.write(json.dumps({"sequence": index, "received_at": _stamp()}) + "\n")

    pending: queue.Queue[str] = queue.Queue(maxsize=max(record_count, 1))
    parsed = 0
    parse_errors = 0
    peak_backlog = 0
    counter_lock = threading.Lock()

    def parser() -> None:
        nonlocal parsed, parse_errors, peak_backlog
        while True:
            value = pending.get()
            try:
                if value == "__STOP__":
                    return
                try:
                    json.loads(value)
                except json.JSONDecodeError:
                    with counter_lock:
                        parse_errors += 1
                else:
                    with counter_lock:
                        parsed += 1
                with counter_lock:
                    peak_backlog = max(peak_backlog, pending.qsize())
                time.sleep(0.0001)
            finally:
                pending.task_done()

    workers = [threading.Thread(target=parser, daemon=True) for _ in range(4)]
    for worker in workers:
        worker.start()
    with raw_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            pending.put(line.rstrip("\n"))
    pending.join()
    for _ in workers:
        pending.put("__STOP__")
    for worker in workers:
        worker.join(timeout=2)
    return {
        "raw_written": record_count,
        "parsed": parsed,
        "parse_errors": parse_errors,
        "peak_backlog": peak_backlog,
        "raw_bytes": raw_path.stat().st_size,
    }


def _sqlite_batch(root: Path, writes_per_worker: int) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "storage.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE samples (worker INTEGER, sequence INTEGER, PRIMARY KEY(worker, sequence))")
        connection.commit()
    lock_retries = 0
    write_failures = 0
    counter_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def writer(worker_id: int) -> None:
        nonlocal lock_retries, write_failures
        connection = sqlite3.connect(db_path, timeout=0.01)
        try:
            barrier.wait(timeout=2)
            for sequence in range(writes_per_worker):
                for attempt in range(32):
                    try:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.execute("INSERT INTO samples VALUES (?, ?)", (worker_id, sequence))
                        time.sleep(0.0003)
                        connection.commit()
                        break
                    except sqlite3.OperationalError as exc:
                        connection.rollback()
                        if "locked" not in str(exc).lower() or attempt == 31:
                            with counter_lock:
                                write_failures += 1
                            break
                        with counter_lock:
                            lock_retries += 1
                        time.sleep(min(0.01, 0.001 * (attempt + 1)))
        finally:
            connection.close()

    threads = [threading.Thread(target=writer, args=(worker_id,)) for worker_id in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    with sqlite3.connect(db_path) as connection:
        rows = int(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    return {
        "expected_rows": writes_per_worker * 2,
        "rows": rows,
        "lock_retries": lock_retries,
        "write_failures": write_failures,
        "integrity": integrity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=int, default=1000)
    parser.add_argument("--quick-tasks", type=int, default=100)
    parser.add_argument("--syslog-records", type=int, default=2000)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--sqlite-writes", type=int, default=100)
    args = parser.parse_args()
    if any(value <= 0 for value in (args.targets, args.quick_tasks, args.syslog_records, args.iterations, args.sqlite_writes)):
        parser.error("all workload sizes must be positive")
    if args.targets > 1000 or args.quick_tasks > 100 or args.iterations > 20:
        parser.error("short stress limits are targets<=1000, quick-tasks<=100, iterations<=20")

    run_id = f"ground-r3-short-stress-{uuid.uuid4().hex[:12]}"
    root = test_data_root_base() / run_id
    root.mkdir(parents=True, exist_ok=False)
    (root / "owner.json").write_text(json.dumps({"task": "R3 mock short stress", "created_at": _stamp(), "pid": __import__("os").getpid()}, indent=2), encoding="utf-8")
    started = time.perf_counter()
    tracemalloc.start()
    heartbeat = []
    scheduler = []
    syslog = []
    sqlite_results = []
    for iteration in range(args.iterations):
        heartbeat.append(_heartbeat_batch(args.targets))
        scheduler.append(_scheduler_batch(args.quick_tasks))
        syslog.append(_syslog_batch(root, args.syslog_records))
        sqlite_results.append(_sqlite_batch(root / f"sqlite-{iteration + 1}", args.sqlite_writes))
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    summary = {
        "result": "PASS" if all(
            item["samples"] == args.targets and item["online"] == args.targets for item in heartbeat
        ) and all(
            item["snapshot"]["completed_tasks"] + item["snapshot"]["failed_tasks"] == args.quick_tasks + 1
            for item in scheduler
        ) and all(
            item["raw_written"] == item["parsed"] and item["parse_errors"] == 0 for item in syslog
        ) and all(
            item["rows"] == item["expected_rows"] and item["integrity"] == "ok" and item["write_failures"] == 0
            for item in sqlite_results
        ) else "FAIL",
        "scope": "mock-only; no device, fping, Electron, or Backend process",
        "run_id": run_id,
        "root": str(root),
        "started_at": _stamp(),
        "actual_seconds": round(time.perf_counter() - started, 3),
        "iterations": args.iterations,
        "heartbeat": heartbeat,
        "scheduler": scheduler,
        "syslog": syslog,
        "sqlite": sqlite_results,
        "peak_traced_memory_bytes": peak_memory,
        "thread_count_after_run": threading.active_count(),
        "notes": [
            "This is a short equivalent pressure check, not a 1/4/8 hour soak.",
            "Use the generated run directory as evidence; remove only this owned directory after review.",
        ],
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": summary["result"], "summary": str(root / "summary.json")}, ensure_ascii=False), flush=True)
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
