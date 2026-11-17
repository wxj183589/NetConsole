"""Bounded Job Center SQL profile on a synthetic isolated task fixture.

The harness exercises all lifecycle states, transition events, detail/log reads,
summary/list filters and bounded history reads.  It never opens production or
real development data and does not delete task rows.
"""
from __future__ import annotations

import argparse
import contextvars
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from netconsole.core.paths import PathResolver
from netconsole.core.performance_profiling import (
    ProfilingConnection,
    ProfilingCursor,
    begin_request_profile,
    end_request_profile,
)
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.repositories.task_result_blob_repository import TaskResultBlobError, read_blob
from netconsole.services.job_center.query_service import JobCenterQueryService


SITE_ID = "demo"
_CONNECTIONS = contextvars.ContextVar("job_profile_connections", default=0)
_FETCHED_ROWS = contextvars.ContextVar("job_profile_fetched_rows", default=0)
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
                    "result": {
                        "task_index": index,
                        "status": status.value,
                        "payload": [index, transition_index, "synthetic"],
                    } if finished else {},
                }
            )
            repository.record(
                current,
                TaskEvent(
                    event_id=f"{task_id}-transition-{transition_index}",
                    task_id=task_id,
                    type={
                        TaskState.COMPLETED: "finished",
                        TaskState.FAILED: "error",
                        TaskState.CANCELLED: "cancelled",
                    }.get(status, "status"),
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
        # Keep one immutable completed result reference visible to the query
        # under test while retaining the full lifecycle/event fixture above.
        with sqlite3.connect(paths.site_tasks_db_path(SITE_ID)) as connection:
            result_row = connection.execute(
                "SELECT result_id, sha256 FROM task_results "
                "WHERE task_id=? AND terminal_event_type='finished' LIMIT 1",
                (task_id,),
            ).fetchone()
        if result_row is not None:
            repository.save(TaskSnapshot(
                **{
                    **current.__dict__,
                    "status": TaskState.COMPLETED,
                    "result": {},
                    "result_id": str(result_row[0]),
                    "result_hash": str(result_row[1]),
                }
            ))
    return paths, repository, JobCenterQueryService(paths)


def _profile_connect(db_path: Path) -> sqlite3.Connection:
    _CONNECTIONS.set(_CONNECTIONS.get() + 1)
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0, factory=_RowCountingConnection)
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


def _legacy_hydrate_result_references(cls, db_path, rows, *, include_result):
    """Reproduce the pre-phase-2 per-row read for an apples-to-apples audit."""
    for row in rows:
        if include_result and not str(row.get("result_reference_id") or ""):
            if "legacy_result_json" in row:
                row["result_json"] = row.get("legacy_result_json") or "{}"
            continue
        if not bool(row.get("result_reference_present")):
            continue
        reference_id = str(row.get("result_reference_id") or "")
        if not include_result and not str(row.get("authority_result_id") or ""):
            raise sqlite3.DatabaseError("task result read-through reference is missing")
        if include_result:
            with closing(cls._connect(db_path)) as conn:
                has_content_sha = cls._column_exists(conn, "task_results", "content_sha256")
                has_blob_ready = cls._column_exists(conn, "task_results", "blob_ready")
                content_column = "content_sha256" if has_content_sha else "''"
                ready_column = "blob_ready" if has_blob_ready else "0"
                authority = conn.execute(
                    f"SELECT canonical_json, {content_column} AS content_sha256, "
                    f"{ready_column} AS blob_ready, byte_size "
                    "FROM task_results WHERE result_id=?", (reference_id,),
                ).fetchone()
                if authority is None:
                    raise sqlite3.DatabaseError("task result authority row is missing")
                if int(authority["blob_ready"] or 0):
                    try:
                        canonical = read_blob(
                            conn,
                            content_sha256=str(authority["content_sha256"] or ""),
                            expected_bytes=int(authority["byte_size"] or -1),
                        )
                    except TaskResultBlobError as exc:
                        raise sqlite3.DatabaseError(str(exc)) from exc
                else:
                    canonical = str(authority["canonical_json"] or "")
            row["authority_result_json"] = canonical
            row["result_json"] = canonical


class _RowCountingCursor(ProfilingCursor):
    @staticmethod
    def _record_rows(rows: Any) -> Any:
        if rows is None:
            return rows
        _FETCHED_ROWS.set(_FETCHED_ROWS.get() + (1 if isinstance(rows, sqlite3.Row) else len(rows)))
        return rows

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._record_rows(super().fetchone())

    def fetchmany(self, size=-1):  # type: ignore[no-untyped-def]
        return self._record_rows(super().fetchmany(size))

    def fetchall(self):  # type: ignore[no-untyped-def]
        return self._record_rows(super().fetchall())


class _RowCountingConnection(ProfilingConnection):
    def cursor(self, factory=_RowCountingCursor):  # type: ignore[no-untyped-def]
        return super().cursor(factory)

    def execute(self, sql, parameters=(), /):  # type: ignore[no-untyped-def]
        return self.cursor().execute(sql, parameters)


def _measure(name: str, function: Callable[[], Any], *, iterations: int) -> dict[str, Any]:
    wall: list[float] = []
    sql_count: list[int] = []
    sql_ms: list[float] = []
    response_bytes: list[int] = []
    connections: list[int] = []
    fetched_rows: list[int] = []
    slowest: list[tuple[float, str]] = []
    for index in range(iterations):
        connection_token = _CONNECTIONS.set(0)
        rows_token = _FETCHED_ROWS.set(0)
        profile, token = begin_request_profile(f"job-profile-{name}-{index}", "GET", f"/profile/job/{name}")
        started = time.perf_counter()
        try:
            result = function()
            encoded = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            response_bytes.append(len(encoded))
            connections.append(_CONNECTIONS.get())
            fetched_rows.append(_FETCHED_ROWS.get())
            if hasattr(profile, "record_response_bytes"):
                profile.record_response_bytes(len(encoded))
        finally:
            wall.append((time.perf_counter() - started) * 1000)
            sql_count.append(profile.sql_count)
            sql_ms.append(profile.sql_ms)
            slowest.extend(getattr(profile, "slowest_sql", []))
            end_request_profile(token)
            _CONNECTIONS.reset(connection_token)
            _FETCHED_ROWS.reset(rows_token)
    slowest.sort(key=lambda item: item[0], reverse=True)
    return {
        "iterations": iterations,
        "wall_ms": {"p50": _percentile(wall, 50), "p95": _percentile(wall, 95), "p99": _percentile(wall, 99), "max": max(wall)},
        "sql_count": {"p50": _percentile([float(item) for item in sql_count], 50), "p95": _percentile([float(item) for item in sql_count], 95), "max": max(sql_count)},
        "sql_ms": {"p50": _percentile(sql_ms, 50), "p95": _percentile(sql_ms, 95), "p99": _percentile(sql_ms, 99), "max": max(sql_ms)},
        "response_bytes": {"p50": _percentile([float(item) for item in response_bytes], 50), "max": max(response_bytes)},
        "connections": {"p50": _percentile([float(item) for item in connections], 50), "p95": _percentile([float(item) for item in connections], 95), "max": max(connections)},
        "fetched_rows": {"p50": _percentile([float(item) for item in fetched_rows], 50), "p95": _percentile([float(item) for item in fetched_rows], 95), "max": max(fetched_rows)},
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
    if args.iterations < 5 or args.tasks < 1:
        parser.error("iterations must be >= 5 and tasks must be >= 1")
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
            "list_results": lambda: query.list_task_results(
                SITE_ID, task_type="closeout_profile", status="COMPLETED", limit=200
            ),
        }
        metrics = {name: _measure(name, function, iterations=args.iterations) for name, function in cases.items()}
        original_hydrate = JobCenterQueryService.__dict__["_hydrate_result_references"]
        JobCenterQueryService._hydrate_result_references = classmethod(_legacy_hydrate_result_references)
        try:
            legacy_list_results = _measure("list_results_legacy_n_plus_one", cases["list_results"], iterations=args.iterations)
        finally:
            JobCenterQueryService._hydrate_result_references = original_hydrate
        metrics["list_results_legacy_n_plus_one"] = legacy_list_results
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
        "note": "No production or real development data opened; query service connection was profiled with an isolated sqlite factory; no task rows were deleted. list_results_legacy_n_plus_one is a copied pre-phase-2 read path for direct comparison.",
    }
    (args.output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output / "metrics.json"), "db_bytes": result["db_bytes"], "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
