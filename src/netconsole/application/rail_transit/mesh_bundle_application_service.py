from __future__ import annotations

from collections.abc import Mapping
from typing import BinaryIO
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.mesh_bundle_import_service import (
    MeshBundleImportError,
    MeshBundleImportService,
)


class MeshBundleApplicationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MeshBundleApplicationService:
    _OWNER = "web_rail_transit"
    _TASK_TYPE = "mesh_bundle_import"

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        process_adapter: LocalProcessAdapter,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter

    def preview_bundle(
        self,
        site_id: str,
        *,
        file_name: str,
        source: BinaryIO,
    ) -> dict[str, object]:
        site_id = self._site(site_id)
        profiles = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id)).list_profiles()
        try:
            preview = MeshBundleImportService(site_id, self.paths).create_preview(
                file_name,
                source,
                profiles,
            )
            preview["items"] = [
                {
                    key: item[key]
                    for key in (
                        "member_id",
                        "original_name",
                        "safe_name",
                        "size_bytes",
                        "sha256",
                        "train_number",
                        "role",
                        "match_status",
                        "selected_profile_id",
                        "selected_profile_name",
                        "candidates",
                    )
                }
                for item in preview["items"]
            ]
            return preview
        except MeshBundleImportError as exc:
            raise MeshBundleApplicationError(exc.code, str(exc)) from exc

    def start_import(
        self,
        site_id: str,
        *,
        preview_id: str,
        mappings: list[Mapping[str, object]],
        explicit_confirmation: bool,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise MeshBundleApplicationError("CONFIRMATION_REQUIRED", "请先确认全部 MESH ZIP 文件映射")
        service = MeshBundleImportService(site_id, self.paths)
        profiles = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id)).list_profiles()
        try:
            manifest, approved = service.approve_preview(
                preview_id,
                mappings,
                (profile.mr_id for profile in profiles),
            )
        except MeshBundleImportError as exc:
            raise MeshBundleApplicationError(exc.code, str(exc)) from exc
        task_id = f"mesh-bundle-{uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=self._TASK_TYPE,
            params={
                "site_name": site_id,
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "task_name": "MESH ZIP 批量导入分析",
                "owner": self._OWNER,
                "task_source": "local",
                "preview_id": preview_id,
                "archive_sha256": manifest.archive_sha256,
                "mappings": [dict(item) for item in approved],
            },
        )
        try:
            self.process_adapter.start_job(job)
        except Exception as exc:
            raise MeshBundleApplicationError("JOB_START_FAILED", "MESH ZIP 导入任务启动失败") from exc
        snapshot = self.task_service.repository(site_id).get(task_id)
        if snapshot is None:
            raise MeshBundleApplicationError("JOB_START_FAILED", "MESH ZIP 导入任务未进入任务中心")
        return RailTransitTaskDTO(
            task_id=task_id,
            status=snapshot.status.value,
            action=self._TASK_TYPE,
            message=snapshot.message,
            error_message=snapshot.error_message,
        )

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise MeshBundleApplicationError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        if not self.paths.site_dir(value).is_dir():
            raise MeshBundleApplicationError("SITE_CONTEXT_INVALID", "当前局点不存在")
        return value


__all__ = ["MeshBundleApplicationError", "MeshBundleApplicationService"]
