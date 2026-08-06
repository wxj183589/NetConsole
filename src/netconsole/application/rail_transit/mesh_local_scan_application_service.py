from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from netconsole.application.desktop import DesktopActionService
from netconsole.application.rail_transit.mesh_derived_data_repair_coordinator import (
    MeshDerivedDataRepairCoordinator,
)
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.mesh_local_scan_service import MeshLocalScanError, MeshLocalScanService
from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceError


class MeshLocalScanApplicationService:
    _OWNER = "web_rail_transit"

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        process_adapter: LocalProcessAdapter,
        desktop_action_service: DesktopActionService | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.desktop_action_service = desktop_action_service
        self.mesh_derived_data_repair_coordinator = MeshDerivedDataRepairCoordinator(
            paths,
            task_service,
            process_adapter,
        )

    def start_scan(self, site_id: str) -> dict[str, object]:
        site = self._site(site_id)
        scan_id = MeshLocalScanService(site, self.paths).create_scan_id()
        task = self._start_job(
            site,
            task_type="mesh_local_scan",
            task_name="扫描本地 MESH 日志",
            params={"scan_id": scan_id},
        )
        return {"scan_id": scan_id, "task": task}

    def get_scan(self, site_id: str, scan_id: str) -> dict[str, object]:
        site = self._site(site_id)
        return MeshLocalScanService(site, self.paths).get_scan(scan_id)

    def start_import(
        self,
        site_id: str,
        scan_id: str,
        mappings: list[Mapping[str, object]],
        *,
        explicit_confirmation: bool,
    ) -> RailTransitTaskDTO:
        site = self._site(site_id)
        if not explicit_confirmation:
            raise MeshLocalScanError("CONFIRMATION_REQUIRED", "请先确认要补录的本地 MESH 日志")
        scan = MeshLocalScanService(site, self.paths).get_scan(scan_id)
        candidates = {
            str(item.get("candidate_id") or ""): item
            for item in scan.get("candidates") or []
            if isinstance(item, dict)
        }
        prepared = [
            {
                "candidate_id": str(item.get("candidate_id") or ""),
                "profile_id": str(item.get("profile_id") or ""),
            }
            for item in mappings
        ]
        if not prepared or len(prepared) > 200:
            raise MeshLocalScanError("CANDIDATE_SELECTION_INVALID", "每次必须选择 1 到 200 个本地日志")
        if any(item["candidate_id"] not in candidates for item in prepared):
            raise MeshLocalScanError("CANDIDATE_NOT_FOUND", "本地日志候选不存在或不属于当前扫描")
        if any(
            str(candidates[item["candidate_id"]].get("scan_status") or "")
            not in {"unregistered", "needs_metadata", "failed", "parse_failed", "repair_failed"}
            for item in prepared
        ):
            raise MeshLocalScanError("CANDIDATE_SELECTION_INVALID", "只能导入未登记、待补充或可重试的本地日志")
        try:
            repair_task = self.mesh_derived_data_repair_coordinator.enqueue_if_required(
                site,
                operation_kind="mesh_local_scan_import",
                operation_payload={"scan_id": scan_id, "mappings": prepared},
            )
        except MeshDerivedDataMaintenanceError as exc:
            raise MeshLocalScanError("MESH_REPAIR_START_FAILED", str(exc)) from exc
        if repair_task is not None:
            MeshLocalScanService(site, self.paths).set_repair_status(
                scan_id,
                (item["candidate_id"] for item in prepared),
                "waiting_repair",
                "检测到 MESH 分析数据库需要升级，系统正在自动修复。",
            )
            return repair_task
        return self._start_job(
            site,
            task_type="mesh_local_scan_import",
            task_name="补录本地 MESH 日志",
            params={
                "scan_id": scan_id,
                "mappings": prepared,
                "resource_keys": [f"mesh-import:{site}"],
                "resource_conflict_message": "当前局点已有 MESH 导入任务正在运行",
            },
        )

    def ignore_candidates(
        self,
        site_id: str,
        scan_id: str,
        candidate_ids: list[str],
    ) -> dict[str, object]:
        site = self._site(site_id)
        return MeshLocalScanService(site, self.paths).ignore_candidates(scan_id, candidate_ids)

    def open_candidate_directory(
        self,
        site_id: str,
        scan_id: str,
        candidate_id: str,
    ) -> dict[str, object]:
        site = self._site(site_id)
        if self.desktop_action_service is None:
            raise MeshLocalScanError("DESKTOP_ACTION_UNAVAILABLE", "当前宿主不支持打开本机目录")
        path = MeshLocalScanService(site, self.paths).candidate_directory(scan_id, candidate_id)
        result = self.desktop_action_service.open_controlled_path(path, expect_directory=True)
        return {"success": result.success, "code": result.code, "message": result.message}

    def _start_job(
        self,
        site: str,
        *,
        task_type: str,
        task_name: str,
        params: Mapping[str, object],
    ) -> RailTransitTaskDTO:
        task_id = f"{task_type.replace('_', '-')}-{uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=task_type,
            params={
                "site_name": site,
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "task_name": task_name,
                "owner": self._OWNER,
                "task_source": "local",
                **dict(params),
            },
        )
        try:
            self.process_adapter.start_job(job)
        except Exception as exc:
            raise MeshLocalScanError("JOB_START_FAILED", f"{task_name}任务启动失败") from exc
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None:
            raise MeshLocalScanError("JOB_START_FAILED", f"{task_name}任务未进入任务中心")
        return RailTransitTaskDTO(
            task_id=task_id,
            status=snapshot.status.value,
            action=task_type,
            message=snapshot.message,
            error_message=snapshot.error_message,
        )

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise MeshLocalScanError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        if not self.paths.site_dir(value).is_dir():
            raise MeshLocalScanError("SITE_CONTEXT_INVALID", "当前局点不存在")
        return value


__all__ = ["MeshLocalScanApplicationService"]
