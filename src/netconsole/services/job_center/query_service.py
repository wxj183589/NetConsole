from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.job_center import (
    JobCenterLogLineDTO,
    JobCenterLogTailDTO,
    JobCenterSummaryDTO,
    JobCenterTaskDTO,
)


class JobCenterQueryService:
    """Web 任务中心的 SQLite 只读查询边界。"""

    _ACTIVE_STATES = {"PENDING", "STARTING", "RUNNING", "STOPPING"}

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def current_site_id(self, default: str = "demo") -> str:
        try:
            payload = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            site_id = str(payload.get("current_site") or default) if isinstance(payload, dict) else default
            return SiteManager(self.paths).validate_site_name(site_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return default

    def list_tasks(
        self,
        site_id: str,
        *,
        statuses: set[str] | None = None,
        search: str = "",
        warning_only: bool = False,
        limit: int = 500,
    ) -> list[JobCenterTaskDTO]:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "task_snapshots"):
                return []
            rows = conn.execute(
                self._task_select(conn, detail=False)
                + " ORDER BY task.updated_time DESC, task.task_id DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        tasks = [self._task_from_row(dict(row)) for row in rows]
        normalized_statuses = {str(value).upper() for value in statuses or set() if value}
        if normalized_statuses:
            tasks = [task for task in tasks if task.status.upper() in normalized_statuses]
        if warning_only:
            tasks = [task for task in tasks if task.has_warning]
        keyword = str(search or "").strip().casefold()
        if keyword:
            tasks = [task for task in tasks if keyword in self._search_text(task)]
        return tasks

    def get_task(self, site_id: str, task_id: str) -> JobCenterTaskDTO | None:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return None
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "task_snapshots"):
                return None
            row = conn.execute(
                self._task_select(conn, detail=True) + " WHERE task.task_id = ? LIMIT 1",
                (str(task_id),),
            ).fetchone()
        return self._task_from_row(dict(row), include_result=True) if row is not None else None

    def get_summary(self, site_id: str) -> JobCenterSummaryDTO:
        tasks = self.list_tasks(site_id, limit=1000)
        return JobCenterSummaryDTO(
            total=len(tasks),
            active=sum(task.status.upper() in self._ACTIVE_STATES for task in tasks),
            completed=sum(task.status.upper() == "COMPLETED" for task in tasks),
            failed=sum(task.status.upper() == "FAILED" for task in tasks),
            warning=sum(task.has_warning for task in tasks),
        )

    def get_logs(self, site_id: str, task_id: str, *, tail: int = 300) -> JobCenterLogTailDTO | None:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return None
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "task_snapshots"):
                return None
            exists = conn.execute("SELECT 1 FROM task_snapshots WHERE task_id = ?", (str(task_id),)).fetchone()
            if exists is None:
                return None
            if not self._table_exists(conn, "task_events"):
                return JobCenterLogTailDTO(task_id=task_id, message="暂无日志")
            rows = conn.execute(
                """
                SELECT sequence, event_time, event_type, source, payload_json
                FROM task_events
                WHERE task_id = ?
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (str(task_id), max(1, min(int(tail), 300))),
            ).fetchall()
        lines = [self._log_line(dict(row)) for row in reversed(rows)]
        return JobCenterLogTailDTO(task_id=task_id, lines=lines, message="" if lines else "暂无日志")

    def _db_path(self, site_id: str) -> Path:
        selected = SiteManager(self.paths).validate_site_name(str(site_id or "demo"))
        return self.paths.site_tasks_db_path(selected)

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _task_select(self, conn: sqlite3.Connection, *, detail: bool) -> str:
        result_column = ", task.result_json" if detail else ""
        if self._table_exists(conn, "online_mr_task_sessions"):
            mapping_columns = """
                mapping.session_id, mapping.device_id, mapping.device_name,
                mapping.mr_name, mapping.executor_kind, mapping.phase,
                mapping.mapping_state, mapping.error_code AS mapping_error_code,
                mapping.error_summary AS mapping_error_summary
            """
            join = "LEFT JOIN online_mr_task_sessions mapping ON mapping.controller_task_id = task.task_id"
        else:
            mapping_columns = """
                NULL AS session_id, NULL AS device_id, NULL AS device_name,
                NULL AS mr_name, NULL AS executor_kind, NULL AS phase,
                NULL AS mapping_state, NULL AS mapping_error_code,
                NULL AS mapping_error_summary
            """
            join = ""
        return f"""
            SELECT task.task_id, task.task_type, task.task_name, task.status,
                   task.progress, task.stage, task.message, task.site_name,
                   task.owner, task.source, task.device, task.agent,
                   task.created_time, task.started_time, task.finished_time,
                   task.updated_time, task.result_path, task.error_message,
                   {mapping_columns}{result_column}
            FROM task_snapshots task
            {join}
        """

    @classmethod
    def _task_from_row(cls, row: dict[str, object], *, include_result: bool = False) -> JobCenterTaskDTO:
        result = cls._json_object(row.get("result_json")) if include_result else {}
        status = str(row.get("status") or "UNKNOWN").upper()
        error_summary = str(row.get("mapping_error_summary") or row.get("error_message") or "")
        error_code = str(row.get("mapping_error_code") or result.get("error_code") or "")
        if not error_code and error_summary.startswith("AC_MESH_LINK_"):
            error_code = error_summary.partition(":")[0]
        source = str(row.get("source") or "local")
        executor = str(row.get("executor_kind") or result.get("executor_kind") or "")
        if not executor:
            executor = "AGENT" if source.casefold() == "agent" or row.get("agent") else "LOCAL"
        started = str(row.get("started_time") or "")
        finished = str(row.get("finished_time") or "")
        result_path = str(row.get("result_path") or "")
        return JobCenterTaskDTO(
            id=str(row["task_id"]),
            type=str(row.get("task_type") or ""),
            name=str(row.get("task_name") or row.get("task_type") or ""),
            status=status,
            progress=max(0, min(int(row.get("progress") or 0), 100)),
            phase=str(row.get("phase") or row.get("stage") or ""),
            stage=str(row.get("stage") or ""),
            message=str(row.get("message") or ""),
            site_name=str(row.get("site_name") or ""),
            owner=str(row.get("owner") or ""),
            executor=executor.upper(),
            source=source,
            device_id=str(row.get("device_id") or ""),
            device_name=str(row.get("device_name") or row.get("device") or ""),
            agent=str(row.get("agent") or ""),
            mr_name=str(row.get("mr_name") or ""),
            session_id=str(row.get("session_id") or result.get("session_id") or ""),
            mapping_state=str(row.get("mapping_state") or ""),
            created_time=str(row.get("created_time") or ""),
            started_time=started,
            finished_time=finished,
            updated_time=str(row.get("updated_time") or ""),
            duration_seconds=cls._duration_seconds(started, finished),
            error_code=error_code,
            error_summary=error_summary,
            has_warning=bool(error_summary and status != "FAILED"),
            result_path=result_path,
            output_dir=cls._first_text(result, "output_dir", "output_path"),
            package_path=cls._first_text(result, "package_path", "zip_path"),
            session_path=cls._first_text(result, "session_dir", "session_path"),
            snapshot_id=cls._optional_int(result.get("snapshot_id")),
            records_count=cls._optional_int(result.get("records_count")),
            raw_output_reference=cls._first_text(result, "raw_output_reference"),
            parser_version=cls._first_text(result, "parser_version"),
        )

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _log_line(cls, row: dict[str, object]) -> JobCenterLogLineDTO:
        event_type = str(row.get("event_type") or "log")
        payload = cls._json_object(row.get("payload_json"))
        message = cls._first_text(payload, "message", "error", "state", "stage") or cls._event_label(event_type)
        level = "ERROR" if event_type == "error" else "WARNING" if event_type == "cancelled" else "INFO"
        return JobCenterLogLineDTO(
            sequence=int(row.get("sequence") or 0),
            time=str(row.get("event_time") or ""),
            level=level,
            type=event_type,
            source=str(row.get("source") or "service"),
            message=message,
        )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone() is not None

    @staticmethod
    def _json_object(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @staticmethod
    def _first_text(values: dict[str, Any], *keys: str) -> str:
        return next((str(values[key]) for key in keys if values.get(key) not in (None, "")), "")

    @staticmethod
    def _duration_seconds(started: str, finished: str) -> float:
        if not started:
            return 0.0
        try:
            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            end = datetime.fromisoformat(finished.replace("Z", "+00:00")) if finished else datetime.now(start.tzinfo)
            return max(0.0, (end - start).total_seconds())
        except ValueError:
            return 0.0

    @staticmethod
    def _event_label(event_type: str) -> str:
        return {
            "state": "任务状态已更新",
            "progress": "任务进度已更新",
            "finished": "任务已完成",
            "cancelled": "任务已取消",
            "error": "任务失败",
        }.get(event_type, "任务事件")

    @staticmethod
    def _search_text(task: JobCenterTaskDTO) -> str:
        return " ".join(
            (task.id, task.type, task.name, task.session_id, task.device_name, task.site_name, task.error_summary)
        ).casefold()


__all__ = ["JobCenterQueryService"]
