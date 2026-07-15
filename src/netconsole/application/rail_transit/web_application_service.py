from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import OnlineMrDownsampleMode, OnlineMrMetricType
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.query_service import OnlineMrQueryService


class RailTransitWebError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RailTransitWebApplicationService:
    """轨交 Web 用例边界；复用正式 parser、Query 和 Job。"""

    _TASK_NAMES = {
        "mesh_log_import": "MESH 原始日志导入分析",
        "car_network_refresh_all": "车内通信检测刷新",
        "ac_trackside_business_refresh": "轨旁 AP 业务刷新",
        "trackside_ap_plan_refresh": "轨旁 AP 规划刷新",
        "online_mr_report_export": "Online MR 分析报告导出",
    }
    _UPLOAD_SUFFIXES = {".log", ".txt", ".csv"}
    _SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        query_service: OnlineMrQueryService | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.query_service = query_service or OnlineMrQueryService(paths)
        self.process_adapter = LocalProcessAdapter(task_service)

    def start_mesh_import(
        self,
        site_id: str,
        *,
        profile: dict[str, object],
        uploads: list[tuple[str, bytes]],
    ) -> RailTransitTaskDTO:
        if not str(profile.get("mr_id") or "").strip() or not str(profile.get("display_name") or "").strip():
            raise RailTransitWebError("PROFILE_REQUIRED", "MESH 导入缺少 MR 身份")
        safe_folder = self._safe_name(str(profile.get("safe_folder_name") or profile.get("mr_id") or ""))
        if not safe_folder:
            raise RailTransitWebError("PROFILE_INVALID", "MESH MR 目录名无效")
        if not uploads:
            raise RailTransitWebError("FILE_REQUIRED", "至少选择一个 MESH 原始日志文件")
        staged: list[str] = []
        upload_dir = self.paths.runtime_cache_dir / "rail_web_uploads" / uuid4().hex
        upload_dir.mkdir(parents=True, exist_ok=True)
        for index, (file_name, content) in enumerate(uploads, start=1):
            suffix = Path(file_name or "").suffix.casefold()
            if suffix not in self._UPLOAD_SUFFIXES:
                raise RailTransitWebError("FILE_TYPE_INVALID", "MESH 导入仅支持 LOG/TXT/CSV 文件")
            if len(content) > 20 * 1024 * 1024:
                raise RailTransitWebError("FILE_TOO_LARGE", "单个 MESH 日志不得超过 20 MB")
            safe_name = self._safe_name(Path(file_name).name) or f"mesh_{index}{suffix}"
            path = upload_dir / f"{index:03d}_{safe_name}"
            path.write_bytes(content)
            staged.append(str(path))
        profile_payload = {
            "mr_id": str(profile["mr_id"]).strip(),
            "display_name": str(profile["display_name"]).strip(),
            "safe_folder_name": safe_folder,
            "relative_folder_path": str(profile.get("relative_folder_path") or "").strip(),
            "linked_device_id": profile.get("linked_device_id"),
            "notes": str(profile.get("notes") or ""),
        }
        return self._start_task(
            site_id,
            "mesh_log_import",
            {"profile": profile_payload, "files": staged},
        )

    def start_car_network_diagnostic(self, site_id: str, *, train_id: str = "") -> RailTransitTaskDTO:
        return self._start_task(site_id, "car_network_refresh_all", {"train_id": str(train_id or "").strip()})

    def start_trackside_business_refresh(self, site_id: str, *, ac_id: str = "") -> RailTransitTaskDTO:
        return self._start_task(site_id, "ac_trackside_business_refresh", {"ac_uuid": str(ac_id or "").strip()})

    def start_trackside_plan_refresh(self, site_id: str, *, ac_id: str = "") -> RailTransitTaskDTO:
        return self._start_task(site_id, "trackside_ap_plan_refresh", {"ac_uuid": str(ac_id or "").strip()})

    def start_online_mr_report(self, site_id: str, session_id: str, output_name: str = "") -> RailTransitTaskDTO:
        detail = self.query_service.get_session(site_id, session_id)
        root = self.paths.online_mr_root(site_id).resolve()
        session_dir = (root / detail.session_path_reference).resolve()
        try:
            session_dir.relative_to(root)
        except ValueError as exc:
            raise RailTransitWebError("SESSION_INVALID", "Online MR 会话路径无效") from exc
        if not session_dir.is_dir():
            raise RailTransitWebError("SESSION_NOT_FOUND", "Online MR 会话不存在")
        output_dir = self.paths.rail_transit_root(site_id) / "exports"
        output_dir.mkdir(parents=True, exist_ok=True)
        name = self._safe_name(Path(output_name or f"{session_id}_online_mr.xlsx").name)
        if not name.casefold().endswith(".xlsx"):
            name += ".xlsx"
        output_path = output_dir / name
        return self._start_task(site_id, "online_mr_report_export", {"session_dir": str(session_dir), "output_path": str(output_path)}, artifact_path=str(output_path))

    def query_metrics(
        self,
        site_id: str,
        session_id: str,
        metric_types: list[str],
        *,
        start_time: str = "",
        end_time: str = "",
        limit: int = 5_000,
        downsample: str = OnlineMrDownsampleMode.NONE.value,
        bucket_seconds: int = 1,
    ):
        return self.query_service.query_metrics(
            site_id,
            session_id,
            [OnlineMrMetricType(value) for value in metric_types],
            start_time=start_time or None,
            end_time=end_time or None,
            limit=limit,
            downsample=downsample,
            bucket_seconds=bucket_seconds,
        )

    def query_timeline(self, site_id: str, session_id: str, *, limit: int = 500, offset: int = 0):
        return self.query_service.query_timeline(site_id, session_id, limit=limit, offset=offset)

    def database_summary(self, site_id: str, session_id: str):
        return self.query_service.get_database_summary(site_id, session_id)

    def artifacts(self, site_id: str, session_id: str):
        return self.query_service.list_artifacts(site_id, session_id)

    def _start_task(self, site_id: str, task_type: str, params: dict[str, object], *, artifact_path: str = "") -> RailTransitTaskDTO:
        if task_type not in self._TASK_NAMES:
            raise RailTransitWebError("TASK_NOT_ALLOWED", "不支持的轨交 Web 任务")
        task_id = f"rail-web-{uuid4().hex}"
        job_params = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": self._TASK_NAMES[task_type],
            "owner": "web_rail_transit",
            "task_source": "local",
            **params,
        }
        self.process_adapter.start_job(BackgroundJob(job_id=task_id, task_type=task_type, params=job_params))
        snapshot = self.task_service.repository(site_id).get(task_id)
        return RailTransitTaskDTO(
            task_id=task_id,
            task_type=task_type,
            status=snapshot.status.value if snapshot else "PENDING",
            message=self._TASK_NAMES[task_type],
            artifact_path=artifact_path,
        )

    @classmethod
    def _safe_name(cls, value: str) -> str:
        return cls._SAFE_NAME.sub("_", Path(value).name).strip("._ ")


__all__ = ["RailTransitWebApplicationService", "RailTransitWebError"]
