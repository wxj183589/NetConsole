"""Isolated benchmark for task result layouts and repeated-progress sampling."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import (
    TASK_RESULT_SCHEMA_VERSION,
    TaskRepository,
)


_DEVELOPMENT_ROOT = Path("D:/study").resolve()
_TERMINAL_LAYOUTS = (
    "legacy_dual_full",
    "b3_dual_write",
    "future_ref_only",
)


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    def value(percentile: float) -> float:
        index = min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)
        return ordered[index]

    return {
        "p50": round(value(0.50), 3),
        "p95": round(value(0.95), 3),
        "p99": round(value(0.99), 3),
        "max": round(ordered[-1], 3),
    }


def _snapshot(task_id: str, *, updated_time: str, result: dict[str, Any] | None = None) -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task_id,
        task_type="benchmark_task",
        task_name="任务存储基准",
        status=TaskState.RUNNING if result is None else TaskState.COMPLETED,
        created_time="2026-08-15T00:00:00Z",
        updated_time=updated_time,
        finished_time=updated_time if result is not None else "",
        stage="collect",
        current=1,
        total=10,
        message="benchmark",
        result=result or {},
        progress=100 if result is not None else 10,
    )


def _database_metrics(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        tasks = int(
            connection.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0]
        )
        events = int(
            connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        )
        results = int(
            connection.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
        )
    wal = path.with_name(path.name + "-wal")
    metrics = {
        "tasks": tasks,
        "events": events,
        "results": results,
        "database_bytes": path.stat().st_size,
        "wal_bytes": wal.stat().st_size if wal.is_file() else 0,
    }
    metrics["total_storage_bytes"] = metrics["database_bytes"] + metrics["wal_bytes"]
    return metrics


def _result_fixture(profile: str) -> dict[str, Any]:
    if profile == "small":
        return {"summary": "s" * 1024, "rows": 25, "status": "ok"}
    if profile == "medium":
        return {
            "items": [f"row-{index:04d}:" + "m" * 1014 for index in range(128)],
            "rows": 128,
            "status": "ok",
        }
    if profile == "large":
        return {
            "items": [f"row-{index:04d}:" + "l" * 1014 for index in range(4_500)],
            "rows": 4_500,
            "status": "ok",
        }
    raise ValueError(f"unknown result profile: {profile}")


def _result_authority(
    task_id: str,
    event_type: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    canonical = TaskRepository._canonical_result_json(result)
    encoded = canonical.encode("utf-8")
    result_hash = hashlib.sha256(encoded).hexdigest()
    result_id = (
        "tr-"
        + hashlib.sha256(
            f"{task_id}\0{event_type}\0{result_hash}".encode("utf-8")
        ).hexdigest()
    )
    return {
        "result_id": result_id,
        "result_hash": result_hash,
        "canonical_json": canonical,
        "byte_size": len(encoded),
        "result_summary": TaskRepository._result_summary(
            result,
            byte_size=len(encoded),
        ),
    }


def _write_legacy_dual_full(
    repository: TaskRepository,
    snapshot: TaskSnapshot,
    event: TaskEvent,
) -> None:
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository._upsert(connection, snapshot)
        connection.execute(
            "INSERT INTO task_events(event_id,task_id,event_type,event_time,source,payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.task_id,
                event.type,
                event.time,
                event.source,
                json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        connection.commit()


def _write_future_ref_only(
    repository: TaskRepository,
    snapshot: TaskSnapshot,
    event: TaskEvent,
) -> None:
    result = event.payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("terminal benchmark event requires an object result")
    authority = _result_authority(event.task_id, event.type, result)
    summary = dict(authority["result_summary"])
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO task_results (
                result_id, task_id, terminal_event_type, canonical_json,
                sha256, byte_size, schema_version, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                authority["result_id"],
                event.task_id,
                event.type,
                authority["canonical_json"],
                authority["result_hash"],
                authority["byte_size"],
                TASK_RESULT_SCHEMA_VERSION,
                event.time,
            ),
        )
        stored_snapshot = replace(
            snapshot,
            result={},
            result_id=str(authority["result_id"]),
            result_hash=str(authority["result_hash"]),
            result_summary=summary,
        )
        repository._upsert(connection, stored_snapshot)
        connection.execute(
            "UPDATE task_snapshots SET result_json='' WHERE task_id=?",
            (event.task_id,),
        )
        payload = {
            key: value for key, value in event.payload.items() if key != "result"
        }
        payload.update(
            {
                "result_id": authority["result_id"],
                "result_hash": authority["result_hash"],
                "result_summary": summary,
            }
        )
        connection.execute(
            "INSERT INTO task_events(event_id,task_id,event_type,event_time,source,payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.task_id,
                event.type,
                event.time,
                event.source,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        connection.commit()


def _measure_reads(
    repository: TaskRepository,
    task_ids: list[str],
    expected_result: dict[str, Any],
) -> dict[str, dict[str, float]]:
    snapshot_latencies: list[float] = []
    event_latencies: list[float] = []
    for task_id in task_ids[:100]:
        started = time.perf_counter()
        snapshot = repository.get(task_id)
        snapshot_latencies.append((time.perf_counter() - started) * 1000)
        if snapshot is None or snapshot.result != expected_result:
            raise RuntimeError(f"snapshot result mismatch for {task_id}")

        started = time.perf_counter()
        events = repository.list_events(task_id, limit=1)
        event_latencies.append((time.perf_counter() - started) * 1000)
        if not events or events[0]["payload"].get("result") != expected_result:
            raise RuntimeError(f"event result mismatch for {task_id}")
    return {
        "snapshot_ms": _percentiles(snapshot_latencies),
        "terminal_event_ms": _percentiles(event_latencies),
    }


def _measure_hash_cost(result: dict[str, Any]) -> dict[str, float]:
    canonical = TaskRepository._canonical_result_json(result)
    encoded = canonical.encode("utf-8")
    samples = 3 if len(encoded) >= 4_000_000 else 20
    latencies: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        hashlib.sha256(encoded).hexdigest()
        latencies.append((time.perf_counter() - started) * 1000)
    return _percentiles(latencies)


def _terminal_layout_case(
    root: Path,
    *,
    layout: str,
    profile: str,
    count: int,
) -> dict[str, Any]:
    if layout not in _TERMINAL_LAYOUTS:
        raise ValueError(f"unsupported terminal layout: {layout}")
    path = root / f"terminal-{profile}-{count}-{layout}.db"
    repository = TaskRepository(path)
    wal_keeper = repository._connect()
    result = _result_fixture(profile)
    canonical_bytes = len(TaskRepository._canonical_result_json(result).encode("utf-8"))
    task_ids: list[str] = []
    latencies: list[float] = []
    started = time.monotonic()
    try:
        for index in range(count):
            task_id = f"{layout}-{profile}-{index:05d}"
            timestamp = (
                (datetime(2026, 8, 15, tzinfo=UTC) + timedelta(seconds=index))
                .isoformat()
                .replace("+00:00", "Z")
            )
            snapshot = _snapshot(task_id, updated_time=timestamp, result=result)
            event = TaskEvent(
                event_id=f"finished-{task_id}",
                task_id=task_id,
                type="finished",
                time=timestamp,
                payload={"result": result},
                source="benchmark",
            )
            write_started = time.perf_counter()
            if layout == "legacy_dual_full":
                _write_legacy_dual_full(repository, snapshot, event)
            elif layout == "b3_dual_write":
                repository.record(snapshot, event, allowed_from=())
            else:
                _write_future_ref_only(repository, snapshot, event)
            latencies.append((time.perf_counter() - write_started) * 1000)
            task_ids.append(task_id)
        elapsed = time.monotonic() - started
        read_latency = _measure_reads(repository, task_ids, result)
        metrics = _database_metrics(path)
    finally:
        wal_keeper.close()
    return {
        "layout": layout,
        "read_path": (
            "legacy_full"
            if layout == "legacy_dual_full"
            else "dual_full_validated"
            if layout == "b3_dual_write"
            else "task_results_read_through"
        ),
        "requested_tasks": count,
        "result_canonical_bytes": canonical_bytes,
        **metrics,
        "bytes_per_task": round(metrics["total_storage_bytes"] / max(1, count), 2),
        "elapsed_seconds": round(elapsed, 3),
        "tasks_per_second": round(count / max(elapsed, 0.000001), 2),
        "write_latency_ms": _percentiles(latencies),
        "read_latency": read_latency,
    }


def _terminal_comparison(
    root: Path,
    *,
    profile: str,
    count: int,
) -> dict[str, Any]:
    layouts = {
        layout: _terminal_layout_case(
            root,
            layout=layout,
            profile=profile,
            count=count,
        )
        for layout in _TERMINAL_LAYOUTS
    }
    legacy_bytes = layouts["legacy_dual_full"]["total_storage_bytes"]
    b3_bytes = layouts["b3_dual_write"]["total_storage_bytes"]
    future_bytes = layouts["future_ref_only"]["total_storage_bytes"]
    return {
        "result_profile": profile,
        "requested_tasks": count,
        "result_canonical_bytes": layouts["legacy_dual_full"]["result_canonical_bytes"],
        "result_hash_latency_ms": _measure_hash_cost(_result_fixture(profile)),
        "layouts": layouts,
        "storage_comparison": {
            "b3_vs_legacy_bytes_delta": b3_bytes - legacy_bytes,
            "b3_vs_legacy_percent": round(
                (b3_bytes - legacy_bytes) * 100 / max(1, legacy_bytes), 2
            ),
            "future_ref_only_vs_legacy_potential_bytes_delta": (
                future_bytes - legacy_bytes
            ),
            "future_ref_only_vs_legacy_potential_percent": round(
                (future_bytes - legacy_bytes) * 100 / max(1, legacy_bytes), 2
            ),
        },
    }


def _legacy_progress_record(
    repository: TaskRepository,
    snapshot: TaskSnapshot,
    event: TaskEvent,
) -> None:
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        repository._upsert(connection, snapshot)
        connection.execute(
            "INSERT INTO task_events(event_id,task_id,event_type,event_time,source,payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.event_id,
                event.task_id,
                event.type,
                event.time,
                event.source,
                json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        connection.commit()


def _progress_case(
    root: Path,
    *,
    sampled: bool,
    events: int,
    interval_seconds: float,
) -> dict[str, Any]:
    name = "sampled" if sampled else "legacy"
    path = root / f"progress-{name}.db"
    repository = TaskRepository(path)
    wal_keeper = repository._connect()
    base_time = datetime(2026, 8, 15, tzinfo=UTC)
    snapshot = _snapshot(
        "progress-task",
        updated_time=base_time.isoformat().replace("+00:00", "Z"),
    )
    repository.save(snapshot)
    payload = {
        "stage": "fit_ap",
        "current": 1,
        "total": 100,
        "message": "正在采集",
        "details": {"ap": "ap-1", "state": "unchanged"},
    }
    latencies: list[float] = []
    started = time.monotonic()
    try:
        for index in range(events):
            timestamp = (
                (base_time + timedelta(seconds=index * interval_seconds))
                .isoformat()
                .replace("+00:00", "Z")
            )
            current = replace(snapshot, updated_time=timestamp)
            event = TaskEvent(
                event_id=f"progress-{index}",
                task_id=snapshot.task_id,
                type="progress",
                time=timestamp,
                payload=payload,
                source="benchmark",
            )
            event_started = time.perf_counter()
            if sampled:
                repository.record(current, event)
            else:
                _legacy_progress_record(repository, current, event)
            latencies.append((time.perf_counter() - event_started) * 1000)
        elapsed = time.monotonic() - started
        metrics = _database_metrics(path)
    finally:
        wal_keeper.close()
    return {
        "mode": name,
        "input_progress_events": events,
        **metrics,
        "elapsed_seconds": round(elapsed, 3),
        "input_events_per_second": round(events / max(elapsed, 0.000001), 2),
        "commit_latency_ms": _percentiles(latencies),
    }


def run_benchmark(
    output_dir: Path,
    *,
    task_counts: tuple[int, ...] = (100, 1_000, 10_000),
    result_sample_counts: dict[str, int] | None = None,
    progress_events: int = 3_000,
) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    if not root.is_relative_to(_DEVELOPMENT_ROOT):
        raise ValueError("benchmark output must remain under D:/study")
    if any(count <= 0 for count in task_counts):
        raise ValueError("task counts must be positive")
    sample_counts = result_sample_counts or {"small": 100, "medium": 10, "large": 1}
    if set(sample_counts) != {"small", "medium", "large"}:
        raise ValueError("result sample counts must define small, medium and large")
    if any(count <= 0 for count in sample_counts.values()):
        raise ValueError("result sample counts must be positive")
    if progress_events <= 0:
        raise ValueError("progress event count must be positive")

    root.mkdir(parents=True, exist_ok=True)
    scale_root = root / "task-count-scale"
    size_root = root / "result-size-samples"
    progress_root = root / "progress-sampling"
    scale_root.mkdir(exist_ok=True)
    size_root.mkdir(exist_ok=True)
    progress_root.mkdir(exist_ok=True)
    task_scale = [
        _terminal_comparison(scale_root, profile="small", count=count)
        for count in task_counts
    ]
    result_size_samples = [
        _terminal_comparison(size_root, profile=profile, count=count)
        for profile, count in sample_counts.items()
    ]
    legacy_progress = _progress_case(
        progress_root,
        sampled=False,
        events=progress_events,
        interval_seconds=0.05,
    )
    sampled_progress = _progress_case(
        progress_root,
        sampled=True,
        events=progress_events,
        interval_seconds=0.05,
    )
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "phase": "B3_COMPATIBILITY_PHASE",
        "terminal_result_storage": {
            "task_count_scale": task_scale,
            "result_size_samples": result_size_samples,
            "actual_measurement_note": (
                "100/1000/10000 scales use small results; medium and approximately "
                "4.5 MB results use bounded actual samples to avoid multi-GB test output."
            ),
            "space_claim": (
                "Current B3 is additive dual-write and does not claim saved space; "
                "future ref-only deltas are potential only."
            ),
        },
        "progress_before": legacy_progress,
        "progress_after": sampled_progress,
        "progress_reduction": {
            "event_rows": legacy_progress["events"] - sampled_progress["events"],
            "event_rows_percent": round(
                (legacy_progress["events"] - sampled_progress["events"])
                * 100
                / max(1, legacy_progress["events"]),
                2,
            ),
            "database_bytes": (
                legacy_progress["database_bytes"] - sampled_progress["database_bytes"]
            ),
            "wal_bytes": legacy_progress["wal_bytes"] - sampled_progress["wal_bytes"],
            "total_storage_bytes": (
                legacy_progress["total_storage_bytes"]
                - sampled_progress["total_storage_bytes"]
            ),
            "total_storage_percent": round(
                (
                    legacy_progress["total_storage_bytes"]
                    - sampled_progress["total_storage_bytes"]
                )
                * 100
                / max(1, legacy_progress["total_storage_bytes"]),
                2,
            ),
        },
        "online_mr_heartbeat_contract": "same 30-second identical-progress sampling",
        "retention": "PREVIEW_ONLY_USER_POLICY_REQUIRED",
        "destructive_operations": {
            "DELETE": "NO",
            "DROP": "NO",
            "VACUUM": "NO",
        },
    }
    report_path = root / "TASKS_DB_GOVERNANCE_BENCHMARK.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
    return result


def _parse_counts(value: str) -> tuple[int, ...]:
    counts = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not counts:
        raise argparse.ArgumentTypeError("at least one task count is required")
    if any(count <= 0 for count in counts):
        raise argparse.ArgumentTypeError("task counts must be positive")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--task-counts",
        type=_parse_counts,
        default=(100, 1_000, 10_000),
        help="comma-separated small-result terminal task scales",
    )
    parser.add_argument("--progress-events", type=int, default=3_000)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            run_benchmark(
                args.output_dir,
                task_counts=args.task_counts,
                progress_events=args.progress_events,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
