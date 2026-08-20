"""Isolated benchmark for task storage growth and repeated-progress sampling."""

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
from netconsole.repositories.task_repository import TaskRepository


_DEVELOPMENT_ROOT = Path("D:/study").resolve()


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    def value(percentile: float) -> float:
        return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)]

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
    with sqlite3.connect(path) as conn:
        tasks = int(conn.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0])
        events = int(conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
        results = int(conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0])
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


def _terminal_layout_case(
    root: Path, *, layout: str, profile: str, count: int
) -> dict[str, Any]:
    path = root / f"terminal-{profile}-{count}-{layout}.db"
    repository = TaskRepository(path)
    result = _result_fixture(profile)
    canonical = TaskRepository._canonical_result_json(result).encode("utf-8")
    started = time.monotonic()
    latencies: list[float] = []
    for index in range(count):
        task_id = f"terminal-{profile}-{layout}-{index:05d}"
        timestamp = f"2026-08-15T00:{index % 60:02d}:{index // 60:02d}Z"
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
            _legacy_record(repository, snapshot, event)
        else:
            repository.record(snapshot, event, allowed_from=())
        latencies.append((time.perf_counter() - write_started) * 1000)
    elapsed = time.monotonic() - started
    metrics = _database_metrics(path)
    return {
        "layout": layout,
        "measurement_state": "checkpointed",
        "read_path": "legacy_full" if layout == "legacy_dual_full" else "task_results_read_through",
        "requested_tasks": count,
        "result_canonical_bytes": len(canonical),
        "result_hash": hashlib.sha256(canonical).hexdigest(),
        **metrics,
        "elapsed_seconds": round(elapsed, 3),
        "tasks_per_second": round(count / max(elapsed, 0.000001), 2),
        "bytes_per_task": round(metrics["total_storage_bytes"] / max(1, count), 2),
        "commit_latency_ms": _percentiles(latencies),
    }


def _terminal_comparison(root: Path, *, profile: str, count: int) -> dict[str, Any]:
    layouts = {
        layout: _terminal_layout_case(root, layout=layout, profile=profile, count=count)
        for layout in (
            "legacy_dual_full",
            "guarded_default",
            "task_results_dual_write",
            "future_ref_only",
        )
    }
    legacy_bytes = layouts["legacy_dual_full"]["total_storage_bytes"]
    guarded_bytes = layouts["guarded_default"]["total_storage_bytes"]
    return {
        "result_profile": profile,
        "requested_tasks": count,
        "result_canonical_bytes": layouts["legacy_dual_full"]["result_canonical_bytes"],
        "layouts": layouts,
        "storage_comparison": {
            "guarded_default_vs_legacy_percent": round(
                (guarded_bytes - legacy_bytes) * 100 / max(1, legacy_bytes), 2
            )
        },
    }


def _task_scale(root: Path, count: int) -> dict[str, Any]:
    path = root / f"tasks-{count}.db"
    repository = TaskRepository(path)
    started = time.monotonic()
    latencies: list[float] = []
    result = {"summary": "x" * 1024}
    for index in range(count):
        task_id = f"task-{index:05d}"
        timestamp = f"2026-08-15T00:{index % 60:02d}:00Z"
        snapshot = _snapshot(task_id, updated_time=timestamp, result=result)
        event = TaskEvent(
            event_id=f"finished-{index}",
            task_id=task_id,
            type="finished",
            time=timestamp,
            payload={"result": result},
            source="benchmark",
        )
        event_started = time.monotonic()
        repository.record(snapshot, event, allowed_from=())
        latencies.append((time.monotonic() - event_started) * 1000)
    elapsed = time.monotonic() - started
    metrics = _database_metrics(path)
    return {
        "requested_tasks": count,
        **metrics,
        "elapsed_seconds": round(elapsed, 3),
        "tasks_per_second": round(count / max(elapsed, 0.000001), 2),
        "bytes_per_task": round(metrics["database_bytes"] / max(1, count), 2),
        "events_per_task": round(metrics["events"] / max(1, count), 2),
        "commit_latency_ms": _percentiles(latencies),
    }


def _legacy_record(repository: TaskRepository, snapshot: TaskSnapshot, event: TaskEvent) -> None:
    with repository._connect() as conn:
        repository._upsert(conn, snapshot)
        conn.execute(
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
        conn.commit()


def _progress_case(root: Path, *, sampled: bool, events: int, interval_seconds: float) -> dict[str, Any]:
    name = "sampled" if sampled else "legacy"
    path = root / f"progress-{name}.db"
    repository = TaskRepository(path)
    base_time = datetime(2026, 8, 15, tzinfo=UTC)
    snapshot = _snapshot("progress-task", updated_time=base_time.isoformat().replace("+00:00", "Z"))
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
    for index in range(events):
        timestamp = (base_time + timedelta(seconds=index * interval_seconds)).isoformat().replace(
            "+00:00", "Z"
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
        event_started = time.monotonic()
        if sampled:
            repository.record(current, event)
        else:
            _legacy_record(repository, current, event)
        latencies.append((time.monotonic() - event_started) * 1000)
    elapsed = time.monotonic() - started
    metrics = _database_metrics(path)
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
    if any(int(count) <= 0 for count in task_counts):
        raise ValueError("task counts must be positive")
    sample_counts = result_sample_counts or {"small": 100, "medium": 10, "large": 1}
    if set(sample_counts) != {"small", "medium", "large"}:
        raise ValueError("result sample counts must define small, medium and large")
    if any(int(count) <= 0 for count in sample_counts.values()):
        raise ValueError("result sample counts must be positive")
    if int(progress_events) <= 0:
        raise ValueError("progress event count must be positive")
    root.mkdir(parents=True, exist_ok=True)
    task_scale_root = root / "task-count-scale"
    result_size_root = root / "result-size-samples"
    progress_root = root / "progress-sampling"
    for directory in (task_scale_root, result_size_root, progress_root):
        directory.mkdir(exist_ok=True)
    task_scale = [
        _terminal_comparison(task_scale_root, profile="small", count=int(count))
        for count in task_counts
    ]
    result_size_samples = [
        _terminal_comparison(result_size_root, profile=profile, count=int(count))
        for profile, count in sample_counts.items()
    ]
    legacy = _progress_case(
        progress_root, sampled=False, events=int(progress_events), interval_seconds=0.05
    )
    sampled = _progress_case(
        progress_root, sampled=True, events=int(progress_events), interval_seconds=0.05
    )
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "phase": "B3_ROLLOUT_GUARDED_COMPATIBILITY_PHASE",
        "default_rollout_state": "LEGACY_DUAL_FULL",
        "task_results_dual_write_default": False,
        "terminal_result_storage": {
            "task_count_scale": task_scale,
            "result_size_samples": result_size_samples,
            "space_claim": (
                "Terminal tasks use immutable task_results authority rows; "
                "legacy full payload is retained only as a comparison baseline."
            ),
        },
        "progress_before": legacy,
        "progress_after": sampled,
        "progress_reduction": {
            "event_rows": legacy["events"] - sampled["events"],
            "event_rows_percent": round(
                (legacy["events"] - sampled["events"]) * 100 / max(1, legacy["events"]), 2
            ),
            "database_bytes": legacy["database_bytes"] - sampled["database_bytes"],
            "database_bytes_percent": round(
                (legacy["database_bytes"] - sampled["database_bytes"])
                * 100
                / max(1, legacy["database_bytes"]),
                2,
            ),
            "wal_bytes": legacy["wal_bytes"] - sampled["wal_bytes"],
            "total_storage_bytes": legacy["total_storage_bytes"]
            - sampled["total_storage_bytes"],
            "total_storage_percent": round(
                (legacy["total_storage_bytes"] - sampled["total_storage_bytes"])
                * 100
                / max(1, legacy["total_storage_bytes"]),
                2,
            ),
        },
        "online_mr_heartbeat_contract": "same 30-second identical-progress sampling",
        "retention": "KEEP_LAST_10_EFFECTIVE",
        "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
    }
    report_path = root / "TASKS_DB_GOVERNANCE_BENCHMARK.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--task-counts",
        type=lambda value: tuple(
            int(item.strip()) for item in value.split(",") if item.strip()
        ),
        default=(100, 1_000, 10_000),
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
