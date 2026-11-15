"""Bounded Job Center SQL profile on a synthetic isolated task fixture.

The harness exercises all lifecycle states, transition events, detail/log reads,
summary/list filters and bounded history reads.  It never opens production or
real development data and does not delete task rows.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from netconsole.core.paths import PathResolver
from netconsole.core.performance_profiling import (
    ProfilingConnection,
    begin_request_profile,
    end_request_profile,
)
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.query_service import JobCenterQueryService


SITE_ID = "demo"
NOW = "2026-11-16T10:00:00.000Z"
LIFECYCLE = (
    TaskState.PENDING,
    TaskState.STARTING,
    TaskState.RUNNING,
    TaskState.STOPPING,
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELLED,
)


def _fixture(root: Path, task_count: int = 120) -> tuple[PathResolver, TaskRepository, JobCenterQueryService]:
    paths = PathResolver(root / "app", root / "data")
    paths.app_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text(json.dumps({"current_site": SITE_ID}), encoding="utf-8")
    repository = TaskRepository(paths.site_tasks_db_path(SITE_ID))
    for index in range(task_count):
        task_id = f"closeout-task-{index:04d}"
        current = TaskSnapshot(
            task_id=task_id,
            task_type="closeout_profile",
            task_name=f"Closeout task {index:04d}",
            status=TaskState.PENDING,
            created_time=NOW,
            updated_time=NOW,
            owner="profile",
            site_name=SITE_ID,
            source="local",
            message="queued",
        )
        repository.save(current)
        for transition_index, status in enumerate(LIFECYCLE[1:], start=1):
            finished = status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
            current = TaskSnapshot(
                **{
                    **current.__dict__,
                    "status": status,
                    "updated_time": f"2026-11-16T10:{index % 60:02d}:{transition_index:02d}.000Z",
                    "started_time": NOW if transition_index >= 2 else "",
                    "finished_time": NOW if finished else "",
                    "message": status.value.lower(),
                    "error_message": "synthetic failure" if status is TaskState.FAILED else "",
                }
            )
            repository.record(
                current,
                TaskEvent(
                    event_id=f"{task_id}-transition-{transition_index}",
                    task_id=task_id,
                    type="status",
                    time=current.updated_time,
                    payload={"status": status.value, "message": current.message},
                    source="profile",
                ),
                allowed_from={LIFECYCLE[transition_index - 1]},
            )
        for event_index in range(12):
            repository.record(
                current,
                TaskEvent(
                    event_id=f"{task_id}-log-{event_index:02d}",
                    task_id=task_id,
                    type="log",
                    time=f"2026-11-16T11:{index % 60:02d}:{event_index:02d}.000Z",
                    payload={"message": f"synthetic log {event_index}", "level": "INFO"},
                    source="profile",
                ),
            )
    return paths, repository, JobCenterQueryService(paths)


def _profile_connect(db_path: Path) -> sqlite3.Connection:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0, factory=ProfilingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile / 100)))
    return ordered[index]


def _measure(name: str, function: Callable[[], Any], *, iterations: int) -> dict[str, Any]:
    wall: list[float] = []
    sql_count: list[int] = []
    sql_ms: list[float] = []
    response_bytes: list[int] = []
    slowest: list[tuple[float, str]] = []
    for index in range(iterations):
        profile, token = begin_request_profile(f"job-profile-{name}-{index}", "GET", f"/profile/job/{name}")
        started = time.perf_counter()
        try:
            result = function()
            encoded = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            response_bytes.append(len(encoded))
            if hasattr(profile, "record_response_bytes"):
                profile.record_response_bytes(len(encoded))
        finally:
            wall.append((time.perf_counter() - started) * 1000)
            sql_count.append(profile.sql_count)
            sql_ms.append(profile.sql_ms)
            slowest.extend(getattr(profile, "slowest_sql", []))
            end_request_profile(token)
    slowest.sort(key=lambda item: item[0], reverse=True)
    return {
        "iterations": iterations,
        "wall_ms": {"p50": _percentile(wall, 50), "p95": _percentile(wall, 95), "p99": _percentile(wall, 99), "max": max(wall)},
        "sql_count": {"p50": _percentile([float(item) for item in sql_count], 50), "p95": _percentile([float(item) for item in sql_count], 95), "max": max(sql_count)},
        "sql_ms": {"p50": _percentile(sql_ms, 50), "p95": _percentile(sql_ms, 95), "p99": _percentile(sql_ms, 99), "max": max(sql_ms)},
        "response_bytes": {"p50": _percentile([float(item) for item in response_bytes], 50), "max": max(response_bytes)},
        "slowest_sql": [{"ms": round(ms, 4), "sql": sql} for ms, sql in sorted(slowest, reverse=True)[:5]],
    }


def _explain(db_path: Path) -> dict[str, list[str]]:
    statements = {
        "task_list": "SELECT * FROM task_snapshots WHERE dismissed_at = '' ORDER BY updated_time DESC, task_id DESC LIMIT 500",
        "task_detail": "SELECT * FROM task_snapshots WHERE task_id = ? LIMIT 1",
        "task_logs": "SELECT sequence, event_id, task_id, event_time, event_type, source, payload_json FROM task_events WHERE task_id = ? ORDER BY sequence DESC LIMIT 300",
    }
    plans: dict[str, list[str]] = {}
    with sqlite3.connect(db_path) as connection:
        for name, statement in statements.items():
            params = ("closeout-task-0000",) if name != "task_list" else ()
            plans[name] = [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + statement, params)]
    return plans


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--tasks", type=int, default=120)
    args = parser.parse_args()
    if args.iterations < 5 or args.tasks < 20:
        parser.error("iterations must be >= 5 and tasks must be >= 20")
    args.output.mkdir(parents=True, exist_ok=True)
    fixture_root = args.output / "fixture"
    fixture_root.mkdir(parents=True, exist_ok=False)
    paths, repository, query = _fixture(fixture_root, args.tasks)
    original_connect = JobCenterQueryService._connect
    JobCenterQueryService._connect = staticmethod(_profile_connect)
    try:
        def detail() -> dict[str, Any]:
            value = query.get_task(SITE_ID, "closeout-task-0000")
            return value.model_dump() if value is not None else {}

        def logs() -> dict[str, Any]:
            value = query.get_logs(SITE_ID, "closeout-task-0000", tail=300)
            return value.model_dump() if value is not None else {}

        cases: dict[str, Callable[[], Any]] = {
            "list_all": lambda: [item.model_dump() for item in query.list_tasks(SITE_ID, limit=500)],
            "list_running": lambda: [item.model_dump() for item in query.list_tasks(SITE_ID, statuses={"RUNNING"}, limit=500)],
            "list_search": lambda: [item.model_dump() for item in query.list_tasks(SITE_ID, search="closeout-task-", limit=500)],
            "summary": lambda: query.get_summary(SITE_ID).model_dump(),
            "detail": detail,
            "logs": logs,
        }
        metrics = {name: _measure(name, function, iterations=args.iterations) for name, function in cases.items()}
    finally:
        JobCenterQueryService._connect = original_connect
    db_path = paths.site_tasks_db_path(SITE_ID)
    with sqlite3.connect(db_path) as connection:
        counts = {
            "snapshots": int(connection.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0]),
            "events": int(connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]),
            "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
        }
    result = {
        "harness": "synthetic_isolated_fixture",
        "site_id": SITE_ID,
        "tasks": args.tasks,
        "lifecycle_states": [state.value for state in LIFECYCLE],
        "iterations": args.iterations,
        "counts": counts,
        "db_bytes": db_path.stat().st_size,
        "explain_query_plan": _explain(db_path),
        "metrics": metrics,
        "note": "No production or real development data opened; query service connection was profiled with an isolated sqlite factory; no task rows were deleted.",
    }
    (args.output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output / "metrics.json"), "db_bytes": result["db_bytes"], "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
