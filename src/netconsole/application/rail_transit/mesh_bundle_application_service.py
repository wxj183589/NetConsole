from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack
import logging
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
import zipfile
from uuid import uuid4

from netconsole.core import app_logger
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
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


logger = logging.getLogger(__name__)


class MeshBundleApplicationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MeshBundleApplicationService:
    _OWNER = "web_rail_transit"
    _TASK_TYPE = "mesh_bundle_import"
    _MAX_PREVIEW_FILES = 64
    _MAX_PREVIEW_SOURCE_BYTES = 100 * 1024 * 1024

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        process_adapter: LocalProcessAdapter,
        base_data_query_service: RailTransitBaseDataQueryService | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.base_data_query_service = base_data_query_service or RailTransitBaseDataQueryService(paths)

    def prepare_import_context(self, site_id: str) -> dict[str, object]:
        site_id = self._site(site_id)
        stage = "open_mesh_catalog"
        try:
            storage = MeshStorageService(site_id, self.paths)
            before = {item.mr_id: item for item in storage.catalog.list_profiles()}
            stage = "sync_vehicle_mr_profiles"
            vehicle_mrs = []
            page = 1
            while True:
                result = self.base_data_query_service.list_mrs(site_id, page=page, page_size=200)
                vehicle_mrs.extend(result.items)
                if len(vehicle_mrs) >= result.total or not result.items:
                    break
                page += 1
        except Exception as exc:
            logger.exception("MESH 导入上下文准备失败 stage=%s", stage)
            app_logger.log_error(
                "MESH_IMPORT_CONTEXT_PREPARE_FAILED",
                f"stage={stage} error_type={type(exc).__name__}",
            )
            raise MeshBundleApplicationError(
                "MESH_IMPORT_CONTEXT_PREPARE_FAILED",
                "MESH 导入上下文准备失败",
                details={"stage": stage},
            ) from exc

        warnings: list[str] = []
        skipped_count = 0
        for mr in vehicle_mrs:
            try:
                device_id = mr.device_id
                if device_id is None:
                    skipped_count += 1
                    warnings.append("存在未绑定设备的基础资料 MR，已跳过同步。")
                    continue
                storage.ensure_mr_profile_for_asset(
                    device_id=int(device_id),
                    device_uuid=str(mr.id or "").strip(),
                    display_name=str(mr.name or "").strip(),
                )
            except Exception as exc:
                skipped_count += 1
                logger.exception(
                    "MESH 导入上下文单条 MR 同步失败 mr_id=%s",
                    str(getattr(mr, "id", "") or "")[:80],
                )
                app_logger.log_warning(
                    "MESH_IMPORT_CONTEXT_PROFILE_SYNC_SKIPPED",
                    f"error_type={type(exc).__name__}",
                )
                warnings.append("一条基础资料 MR 同步失败，已跳过该记录。")

        stage = "list_mesh_profiles"
        try:
            profiles = storage.catalog.list_profiles()
        except Exception as exc:
            logger.exception("MESH 导入上下文准备失败 stage=%s", stage)
            app_logger.log_error(
                "MESH_IMPORT_CONTEXT_PREPARE_FAILED",
                f"stage={stage} error_type={type(exc).__name__}",
            )
            raise MeshBundleApplicationError(
                "MESH_IMPORT_CONTEXT_PREPARE_FAILED",
                "MESH 导入上下文准备失败",
                details={"stage": stage},
            ) from exc
        created = sum(1 for item in profiles if item.mr_id not in before)
        updated = sum(
            1
            for item in profiles
            if item.mr_id in before
            and (
                item.display_name != before[item.mr_id].display_name
                or item.linked_device_id != before[item.mr_id].linked_device_id
                or item.linked_device_uuid != before[item.mr_id].linked_device_uuid
            )
        )
        return {
            "site_id": site_id,
            "vehicle_mr_count": len(vehicle_mrs),
            "profile_count": len(profiles),
            "created_count": created,
            "updated_count": updated,
            "skipped_count": skipped_count,
            "warnings": list(dict.fromkeys(warnings)),
        }

    def preview_bundle(
        self,
        site_id: str,
        *,
        file_name: str,
        source: BinaryIO,
        original_names: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        site_id = self._site(site_id)
        profiles = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id)).list_profiles()
        try:
            preview = MeshBundleImportService(site_id, self.paths).create_preview(
                file_name,
                source,
                profiles,
                original_names=original_names,
            )
            preview["items"] = [
                {
                    key: item[key]
                    for key in (
                        "member_id",
                        "original_name",
                        "original_relative_path",
                        "safe_name",
                        "size_bytes",
                        "sha256",
                        "raw_sha256",
                        "content_sha256",
                        "first_log_timestamp",
                        "last_log_timestamp",
                        "log_date",
                        "stored_filename",
                        "daily_sequence",
                        "rename_status",
                        "rename_warning",
                        "duplicate_status",
                        "batch_duplicate_of",
                        "import_allowed",
                        "existing_source_id",
                        "existing_stored_filename",
                        "existing_session_id",
                        "existing_profile_id",
                        "existing_profile_name",
                        "train_number",
                        "role",
                        "match_status",
                        "selected_profile_id",
                        "selected_profile_name",
                        "profile_import_states",
                        "candidates",
                    )
                }
                for item in preview["items"]
            ]
            return preview
        except MeshBundleImportError as exc:
            raise MeshBundleApplicationError(exc.code, str(exc)) from exc

    def preview_files(
        self,
        site_id: str,
        files: list[tuple[str, BinaryIO]],
    ) -> dict[str, object]:
        if not files or len(files) > self._MAX_PREVIEW_FILES:
            raise MeshBundleApplicationError("FILE_COUNT_INVALID", "请选择 1 到 64 个 MESH 日志文件")
        if len(files) == 1 and str(files[0][0]).casefold().endswith(".zip"):
            return self.preview_bundle(site_id, file_name=files[0][0], source=files[0][1])
        normalized: list[tuple[str, str, BinaryIO]] = []
        original_names: dict[str, str] = {}
        for file_order, (name, source) in enumerate(files, start=1):
            safe = self._safe_preview_member_name(name)
            internal_member_name = (
                f"__uploads__/{file_order:06d}/{safe.rsplit('/', 1)[-1]}"
            )
            normalized.append((internal_member_name, safe, source))
            original_names[internal_member_name] = safe
        with ExitStack() as stack:
            archive = stack.enter_context(SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b"))
            total = 0
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for internal_member_name, _original_name, source in normalized:
                    with bundle.open(internal_member_name, "w") as target:
                        while chunk := source.read(1024 * 1024):
                            total += len(chunk)
                            if total > self._MAX_PREVIEW_SOURCE_BYTES:
                                raise MeshBundleApplicationError("SOURCE_SIZE_EXCEEDED", "MESH 日志总大小超过 100 MiB")
                            target.write(chunk)
            archive.seek(0)
            return self.preview_bundle(
                site_id,
                file_name="mesh-import.zip",
                source=archive,
                original_names=original_names,
            )

    @staticmethod
    def _safe_preview_member_name(value: str) -> str:
        normalized = str(value or "").replace("\\", "/").strip("/")
        parts = [part for part in normalized.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise MeshBundleApplicationError("MEMBER_PATH_INVALID", "MESH 日志相对路径无效")
        name = "/".join(parts)
        if not name.casefold().endswith((".log", ".txt", ".log.gz", ".txt.gz")):
            raise MeshBundleApplicationError("FILE_TYPE_INVALID", f"文件类型不匹配：{name}")
        return name

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
