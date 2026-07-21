from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any
from uuid import UUID

from netconsole.application.system_maintenance import (
    SYSTEM_MAINTENANCE_TASK_TYPES,
    SYSTEM_MAINTENANCE_WEB_OWNER,
)
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.job_center import (
    JobCenterArtifactDTO,
    JobCenterLogLineDTO,
    JobCenterLogTailDTO,
    JobCenterSummaryDTO,
    JobCenterTaskDTO,
)
from netconsole.services.command_reference_application_service import (
    COMMAND_REFERENCE_EXPORT_TASK,
    COMMAND_REFERENCE_WEB_OWNER,
)
from netconsole.services.config_collection_job_handlers import CONFIG_WEB_EXPORT_TASKS
from netconsole.services.config_collection_web_service import (
    CONFIG_WEB_OWNER,
    CONFIG_WEB_TASK_TYPES,
)
from netconsole.services.config_lifecycle_service import safe_artifact_display_name
from netconsole.services.device_management_web_service import (
    DEVICE_DIAGNOSTIC_TASK_TYPE,
    DEVICE_TASK_TYPES,
    EXPORT_TASK_TYPES,
    WEB_TASK_OWNER,
    device_export_display_name,
)
from netconsole.services.file_contract import artifact_media_type
from netconsole.services.network_tools.job_handlers import (
    NETWORK_EXPORT_TASK_TYPES,
    NETWORK_TOOLBOX_EXPORT_TASK,
    NETWORK_TOOL_OWNER,
)
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.traffic.application_service import TRAFFIC_CONTROLLER_TASK_TYPES
from netconsole.services.job_center.handlers.site_jobs import (
    SITE_STORAGE_NONCANCELLABLE_TASK_TYPES,
    SITE_STORAGE_OWNER,
    SITE_STORAGE_TASK_TYPES,
)

AC_WEB_OWNER = "web_ac"
RAIL_WEB_OWNER = "web_rail_transit"


class JobCenterQueryService:
    """Web 任务中心的 SQLite 只读查询边界。"""

    _ACTIVE_STATES = {"PENDING", "STARTING", "RUNNING", "STOPPING"}

    def __init__(
        self,
        paths: PathResolver,
        *,
        config_cancel_capability: Callable[[str, str], tuple[bool, str]] | None = None,
    ) -> None:
        self.paths = paths
        self._config_cancel_capability = config_cancel_capability

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

    def list_task_results(
        self,
        site_id: str,
        *,
        task_type: str,
        status: str = "COMPLETED",
        limit: int = 50,
    ) -> list[tuple[dict[str, Any], str]]:
        """Return internal structured results without exposing them through Web DTOs."""
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "task_snapshots"):
                return []
            rows = conn.execute(
                """
                SELECT result_json, updated_time
                FROM task_snapshots
                WHERE task_type = ? AND status = ? AND site_name = ?
                ORDER BY updated_time DESC
                LIMIT ?
                """,
                (
                    str(task_type),
                    str(status).upper(),
                    self._validated_site_id(site_id),
                    max(1, min(int(limit), 200)),
                ),
            ).fetchall()
        return [
            (self._json_object(row["result_json"]), str(row["updated_time"] or ""))
            for row in rows
        ]

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
        selected = self._validated_site_id(site_id)
        return self.paths.site_tasks_db_path(selected)

    def _validated_site_id(self, site_id: str) -> str:
        return SiteManager(self.paths).validate_site_name(str(site_id or "demo"))

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

    def _task_from_row(self, row: dict[str, object], *, include_result: bool = False) -> JobCenterTaskDTO:
        result = self._json_object(row.get("result_json")) if include_result else {}
        status = str(row.get("status") or "UNKNOWN").upper()
        error_summary = redact_web_task_text(row.get("mapping_error_summary") or row.get("error_message") or "")
        error_code = str(row.get("mapping_error_code") or result.get("error_code") or "")
        if not error_code and error_summary.startswith("AC_MESH_LINK_"):
            error_code = error_summary.partition(":")[0]
        source = str(row.get("source") or "local")
        executor = str(row.get("executor_kind") or result.get("executor_kind") or "")
        if not executor:
            executor = "AGENT" if source.casefold() == "agent" or row.get("agent") else "LOCAL"
        started = str(row.get("started_time") or "")
        finished = str(row.get("finished_time") or "")
        task_type = str(row.get("task_type") or "")
        task_id = str(row["task_id"])
        site_name = str(row.get("site_name") or "")
        owner = str(row.get("owner") or "")
        cancellable, cancel_reason = self._cancel_capability(
            owner, task_type, status, source, site_name, task_id
        )
        artifact_download = self._artifact_download(owner, task_type, task_id, site_name, status, result)
        return JobCenterTaskDTO(
            id=task_id,
            type=task_type,
            name=redact_web_task_text(row.get("task_name") or row.get("task_type") or ""),
            status=status,
            progress=max(0, min(int(row.get("progress") or 0), 100)),
            phase=redact_web_task_text(row.get("phase") or row.get("stage") or ""),
            stage=redact_web_task_text(row.get("stage") or ""),
            message=redact_web_task_text(row.get("message") or ""),
            site_name=site_name,
            owner=owner,
            executor=redact_web_task_text(executor).upper(),
            source=redact_web_task_text(source),
            device_id=redact_web_task_text(row.get("device_id") or ""),
            device_name=redact_web_task_text(row.get("device_name") or row.get("device") or ""),
            agent=redact_web_task_text(row.get("agent") or ""),
            mr_name=redact_web_task_text(row.get("mr_name") or ""),
            session_id=redact_web_task_text(row.get("session_id") or result.get("session_id") or ""),
            mapping_state=redact_web_task_text(row.get("mapping_state") or ""),
            created_time=str(row.get("created_time") or ""),
            started_time=started,
            finished_time=finished,
            updated_time=str(row.get("updated_time") or ""),
            duration_seconds=self._duration_seconds(started, finished),
            error_code=redact_web_task_text(error_code),
            error_summary=error_summary,
            has_warning=bool(error_summary and status != "FAILED"),
            snapshot_id=self._optional_int(result.get("snapshot_id")),
            records_count=self._optional_int(result.get("records_count")),
            parser_version=redact_web_task_text(self._first_text(result, "parser_version")),
            module=self._module(owner, task_type),
            cancellable=cancellable,
            cancel_reason=cancel_reason,
            artifact_download=artifact_download,
            artifact_reason="" if artifact_download else "当前任务 owner 未提供可下载 Artifact",
        )

    @staticmethod
    def _module(owner: str, task_type: str) -> str:
        if owner == WEB_TASK_OWNER and task_type in DEVICE_TASK_TYPES:
            return "devices"
        if owner == CONFIG_WEB_OWNER and task_type in CONFIG_WEB_TASK_TYPES:
            return "config"
        if owner == "web_file_management" and task_type in {"file_management_download", "device_sftp_enable"}:
            return "files"
        if owner == AC_WEB_OWNER:
            return "ac"
        if owner == RAIL_WEB_OWNER:
            return "rail"
        if owner == NETWORK_TOOL_OWNER:
            return "network"
        if owner == "controller" and task_type in TRAFFIC_CONTROLLER_TASK_TYPES:
            return "network"
        if owner == COMMAND_REFERENCE_WEB_OWNER:
            return "command-reference"
        if owner == SYSTEM_MAINTENANCE_WEB_OWNER:
            return "logs"
        if owner == SITE_STORAGE_OWNER and task_type in SITE_STORAGE_TASK_TYPES:
            return "logs"
        return "other"

    def _cancel_capability(
        self,
        owner: str,
        task_type: str,
        status: str,
        source: str,
        site_name: str,
        task_id: str,
    ) -> tuple[bool, str]:
        if status not in JobCenterQueryService._ACTIVE_STATES:
            return False, "任务已结束"
        if owner == "controller" and task_type in TRAFFIC_CONTROLLER_TASK_TYPES:
            return True, ""
        if source != "local":
            return False, "外部任务 owner 未提供统一停止能力"
        if owner == WEB_TASK_OWNER and task_type in DEVICE_TASK_TYPES:
            return True, ""
        if owner == CONFIG_WEB_OWNER and task_type in CONFIG_WEB_TASK_TYPES:
            if status == "STOPPING":
                return False, "已请求停止，等待配置任务 owner 收口"
            if self._config_cancel_capability is None:
                return False, "配置任务取消接收端不可用"
            try:
                return self._config_cancel_capability(site_name, task_id)
            except Exception:
                return False, "配置任务取消能力检查失败"
        if owner == "web_file_management" and task_type in {"file_management_download", "device_sftp_enable"}:
            return True, ""
        if owner == AC_WEB_OWNER:
            return True, ""
        if owner == RAIL_WEB_OWNER:
            return True, ""
        if owner == NETWORK_TOOL_OWNER:
            return True, ""
        if owner == COMMAND_REFERENCE_WEB_OWNER and task_type == COMMAND_REFERENCE_EXPORT_TASK:
            return True, ""
        if owner == SYSTEM_MAINTENANCE_WEB_OWNER and task_type in SYSTEM_MAINTENANCE_TASK_TYPES:
            return True, ""
        if owner == SITE_STORAGE_OWNER and task_type in SITE_STORAGE_TASK_TYPES:
            if task_type in SITE_STORAGE_NONCANCELLABLE_TASK_TYPES:
                return False, "数据提交阶段不可停止，以避免局点目录和 Registry 不一致"
            return True, ""
        return False, "当前任务 owner 未接入统一停止能力"

    @staticmethod
    def _artifact_download(owner: str, task_type: str, task_id: str, site_name: str, status: str, result: dict[str, Any]) -> JobCenterArtifactDTO | None:
        if status != "COMPLETED":
            return None
        artifact_id = str(result.get("artifact_id") or "")
        if artifact_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", artifact_id):
            return None
        if (
            owner == WEB_TASK_OWNER
            and task_type in {*EXPORT_TASK_TYPES, DEVICE_DIAGNOSTIC_TASK_TYPE}
            and artifact_id
            and result.get("available")
        ):
            name = device_export_display_name(task_type, result.get("display_name"))
            if not name:
                return None
            api_path = (
                f"/api/device-management/diagnostics/{task_id}/download"
                if task_type == DEVICE_DIAGNOSTIC_TASK_TYPE
                else f"/api/device-management/exports/{task_id}/download"
            )
            return JobCenterQueryService._artifact_dto(
                artifact_id,
                name,
                result.get("size_bytes"),
                api_path,
                {"artifact_id": artifact_id},
            )
        if owner == CONFIG_WEB_OWNER and task_type in CONFIG_WEB_EXPORT_TASKS and artifact_id:
            name = JobCenterQueryService._artifact_display_name(result.get("display_name"))
            if not name:
                return None
            return JobCenterQueryService._artifact_dto(artifact_id, name, result.get("size") or result.get("size_bytes"), f"/api/config-collection/artifacts/{artifact_id}")
        if owner == "web_file_management" and task_type == "file_management_download" and result.get("name"):
            name = JobCenterQueryService._artifact_display_name(result["name"])
            safe_id = str(result.get("artifact_id") or result.get("download_ref") or task_id)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", safe_id):
                return None
            return JobCenterQueryService._artifact_dto(safe_id, name, result.get("size_bytes"), f"/api/file-management/downloads/{task_id}/file", {"site_id": site_name})
        if owner == NETWORK_TOOL_OWNER and task_type in NETWORK_EXPORT_TASK_TYPES:
            network_artifact_id = str(result.get("result_id") or "")
            if not re.fullmatch(r"[0-9a-f]{32}", network_artifact_id):
                return None
            name = JobCenterQueryService._artifact_display_name(result.get("filename"))
            if not name:
                return None
            api_path = (
                f"/api/network-tools/artifacts/{network_artifact_id}"
                if task_type == NETWORK_TOOLBOX_EXPORT_TASK
                else f"/api/network-tools/wireless-scan/artifacts/{network_artifact_id}"
            )
            return JobCenterQueryService._artifact_dto(
                network_artifact_id,
                name,
                result.get("size"),
                api_path,
            )
        if task_type.startswith("web_export_") and artifact_id:
            try:
                UUID(artifact_id)
            except ValueError:
                return None
            source = str(result.get("artifact_source") or "")
            artifact_type = str(result.get("artifact_type") or "").casefold()
            name = JobCenterQueryService._artifact_display_name(
                result.get("artifact_name")
            )
            if not source or not artifact_type or not name:
                return None
            if Path(name).suffix.casefold() != f".{artifact_type}":
                return None
            return JobCenterQueryService._artifact_dto(
                artifact_id,
                name,
                result.get("size_bytes"),
                f"/api/job-center/artifacts/{artifact_id}",
            )
        return None

    @staticmethod
    def _artifact_display_name(value: object, fallback: object = "") -> str:
        candidate = str(value or fallback or "").strip()
        suffix = Path(candidate).suffix.casefold()
        if not candidate or not suffix:
            return ""
        return safe_artifact_display_name(candidate, suffix)

    @staticmethod
    def _artifact_dto(artifact_id: str, display_name: str, size: object, api_path: str, query: dict[str, str] | None = None) -> JobCenterArtifactDTO:
        return JobCenterArtifactDTO(
            artifact_id=artifact_id,
            display_name=display_name,
            size_bytes=max(0, JobCenterQueryService._optional_int(size) or 0),
            media_type=artifact_media_type(display_name),
            api_path=api_path,
            query=query or {},
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
        message = redact_web_task_text(cls._first_text(payload, "message", "error", "traceback", "diagnostic", "state", "stage") or cls._event_label(event_type))
        level = "ERROR" if event_type == "error" else "WARNING" if event_type == "cancelled" else "INFO"
        return JobCenterLogLineDTO(
            sequence=int(row.get("sequence") or 0),
            time=str(row.get("event_time") or ""),
            level=level,
            type=event_type,
            source=redact_web_task_text(row.get("source") or "service"),
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
