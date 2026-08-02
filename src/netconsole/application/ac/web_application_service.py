from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from netconsole.application.web_artifacts import WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.application.desktop.actions import DesktopActionService, RegisteredLaunch
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.settings import SettingsStore, normalize_external_terminal_type
from netconsole.core.sites import SiteManager
from netconsole.models.api.ac_management import (
    AcActionPlanDTO,
    AcExternalTerminalActionDTO,
    AcExternalTerminalOptionDTO,
    AcExternalTerminalOptionsDTO,
    AcExtensionApplyResultDTO,
    AcExtensionDTO,
    AcExtensionPageDTO,
    AcExtensionPreviewDTO,
    AcExtensionRollbackResultDTO,
    AcOmniPeekPreviewDTO,
    AcOmniPeekPreferencesDTO,
    AcWebTaskDTO,
)
from netconsole.models.device import Device
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.fit_ap_optical_task_guard import fit_ap_optical_resource_key
from netconsole.services.ac.fit_ap_resource_export import make_fit_ap_resource_filename
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_task_builders import (
    fit_ap_extension_xlsx_spec,
    fit_ap_resource_xlsx_spec,
    omnipeek_name_table_spec,
)
from netconsole.services.external_terminal import (
    TERMINAL_LABELS,
    available_external_terminal_configs,
    build_external_terminal_command,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac_key
from netconsole.services.fit_ap_import_export import normalize_ap_direction
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService, TaskResourceConflictError
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text, sanitize_web_export_snapshot
from netconsole.services.rail_transit.base_data_import_service import BaseDataImportError, RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService
from netconsole.services.omnipeek_name_table_service import (
    default_omnipeek_line_name,
    load_omnipeek_color_settings,
    make_omnipeek_filename,
    save_omnipeek_color_settings,
)
from netconsole.services.netmiko_connection import ConnectionTarget
from netconsole.utils.mileage import mileage_storage_text


ACTION_DEFINITIONS = {
    "persist_auto_ap": ("固化新 AP", ("system-view", "wlan auto-ap persistent all", "save force", "return", "quit")),
    "enable_ap_remote_login": ("开启 AP 远程登录", ("screen-length disable", "system-view", "probe", "wlan ap-execute all exec-console enable", "return", "quit")),
}
_PLAN_ID = re.compile(r"^ac-plan-[0-9a-f]{32}$")


class AcWebActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AcWebApplicationService:
    """AC Web 用例边界；设备 IO 只通过持久化后台任务执行。"""

    _OWNER = "web_ac"
    _ARTIFACT_TASK_TYPES = {
        "ac_extension_export": "web_export_fit_ap_extension_xlsx",
        "ac_omnipeek_export": "web_export_omnipeek_name_table",
        "ac_fit_ap_resource_export": "web_export_fit_ap_resource_xlsx",
    }
    _LOCAL_REBUILD_TASKS = {
        "ac_overview_refresh": "AC 在线概览本地重算",
        "ac_fit_ap_resources_refresh": "FIT-AP 信息本地重算",
        "ac_fit_ap_optical_refresh": "FIT-AP 光衰本地重算",
        "trackside_ap_plan_refresh": "轨旁 AP 规划本地加载",
        "ac_trackside_business_refresh": "轨旁 AP 业务本地重算",
    }
    _REFRESH_TASKS = {
        "ac": ("ac_info_refresh", "更新 AC 信息"),
        "fit-ap": ("ac_fit_ap_resources_refresh", "更新 FIT-AP 资源"),
        "ap-detail": ("ac_fit_ap_detail_refresh", "深度更新 FIT-AP"),
        "verbose-all": ("ac_fit_ap_verbose_all_refresh", "获取当前 AC 全部 AP 详细信息"),
        "verbose-selected": ("ac_fit_ap_verbose_selected_refresh", "获取已选择 AP 详细信息"),
        "optical": ("ac_fit_ap_optical_refresh", "更新 FIT-AP 光衰"),
    }
    _TASK_ACTIONS = {
        **{task_type: task_type for task_type in _LOCAL_REBUILD_TASKS},
        **{task_type: task_type for task_type, _task_name in _REFRESH_TASKS.values()},
        "ac_command_action_execute": "ac_command_action_execute",
        "ac_fit_ap_delete_many": "ac_fit_ap_delete_many",
        "fit_ap_metadata_import": "fit_ap_metadata_import",
        "fit_ap_metadata_save": "fit_ap_metadata_save",
        "omnipeek_name_table_preview": "ac_omnipeek_preview",
        "web_export_omnipeek_name_table": "ac_omnipeek_export",
        "web_export_fit_ap_extension_xlsx": "ac_extension_export",
        "web_export_fit_ap_resource_xlsx": "ac_fit_ap_resource_export",
    }
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter,
        import_preview_service: RailTransitImportPreviewService | None = None,
        base_import_service: RailTransitBaseDataImportService | None = None,
        export_adapter: WebExportProcessAdapter | None = None,
        artifact_store: WebArtifactStore | None = None,
        desktop_action_service: DesktopActionService | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.base_import_service = base_import_service or RailTransitBaseDataImportService(paths)
        self.import_preview_service = import_preview_service or RailTransitImportPreviewService(
            RailTransitBaseDataQueryService(paths), import_service=self.base_import_service
        )
        self.export_adapter = export_adapter
        self.artifact_store = artifact_store or WebArtifactStore(paths, task_service)
        self.desktop_action_service = desktop_action_service

    def current_site_id(self) -> str:
        try:
            data = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            value = data.get("current_site") if isinstance(data, dict) else None
            return self._site(str(value or ""))
        except (OSError, TypeError, ValueError, json.JSONDecodeError, AcWebActionError) as exc:
            raise AcWebActionError("SITE_CONTEXT_INVALID", "当前局点上下文无效") from exc

    def list_extensions(self, site_id: str, *, search: str = "", page: int = 1, page_size: int = 50) -> AcExtensionPageDTO:
        site_id = self._site(site_id)
        repository = self._repository(site_id)
        if normalize_mac_key(search):
            identity_rows = ApIdentityQueryService(
                repository.database
            ).search_aps(search)
            base_ids = {
                str(row.get("base_record_id") or "")
                for row in identity_rows
                if row.get("base_record_id")
            }
            rows = [
                row
                for row in repository.list_ap_extension_points()
                if str(row.get("id") or "") in base_ids
            ]
        else:
            rows = repository.list_ap_extension_points(search=search)
        items = [self._extension_dto(row) for row in rows]
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        start = (page - 1) * page_size
        return AcExtensionPageDTO(items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)

    def start_local_rebuild(
        self,
        site_id: str,
        task_type: str,
        *,
        ac_id: str,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if task_type not in self._LOCAL_REBUILD_TASKS:
            raise AcWebActionError("TASK_NOT_ALLOWED", "不支持的 AC Web 本地重算任务")
        ac_id = str(ac_id or "").strip()
        if ac_id:
            ac_id = str(self._target(site_id, ac_id).device_uuid)
        task_id = f"ac-web-{uuid4().hex}"
        params: dict[str, object] = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": self._LOCAL_REBUILD_TASKS[task_type],
            "owner": self._OWNER,
            "task_source": "local",
            "device_uuid": ac_id,
            "ac_uuid": ac_id,
        }
        if task_type == "trackside_ap_plan_refresh":
            params["mode"] = TRACKSIDE_AP_PLAN_MODE
        self.process_adapter.start_job(BackgroundJob(job_id=task_id, task_type=task_type, params=params))
        return self._task_dto(site_id, task_id)

    def start_refresh(self, site_id: str, refresh_kind: str, *, ac_id: str, ap_id: str = "") -> AcWebTaskDTO:
        site_id = self._site(site_id)
        try:
            task_type, task_name = self._REFRESH_TASKS[refresh_kind]
        except KeyError as exc:
            raise AcWebActionError("TASK_NOT_ALLOWED", "不支持的 AC/FIT-AP 更新类型") from exc
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        ap_uuid = str(ap_id or "").strip()
        if refresh_kind == "ap-detail" or (refresh_kind == "optical" and ap_uuid):
            if not ap_uuid:
                raise AcWebActionError("AP_TARGET_REQUIRED", "FIT-AP 深度更新缺少 AP 目标")
            if self._repository(site_id).get_fit_ap_resource_by_uuid(device_uuid, ap_uuid) is None:
                raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "目标 FIT-AP 不属于当前 AC")
        task_id = f"ac-web-{uuid4().hex}"
        params = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": task_name,
            "owner": self._OWNER,
            "task_source": "local",
            "device_uuid": device_uuid,
            "ac_uuid": device_uuid,
            "mode": "collect",
            "source": "cli",
        }
        if ap_uuid:
            params["ap_uuid"] = ap_uuid
        if refresh_kind == "optical":
            params.update(source="auto", refresh_scope="single" if ap_uuid else "all")
        if refresh_kind in {"fit-ap", "ap-detail", "optical"}:
            resource_key = fit_ap_optical_resource_key(site_id, device_uuid)
            if resource_key:
                params["resource_keys"] = [resource_key]
        try:
            self.process_adapter.start_job(BackgroundJob(job_id=task_id, task_type=task_type, params=params))
        except TaskResourceConflictError as exc:
            code = "FIT_AP_OPTICAL_UPDATE_RUNNING" if refresh_kind == "optical" else "FIT_AP_UPDATE_RUNNING"
            raise AcWebActionError(code, str(exc)) from exc
        return self._task_dto(site_id, task_id)

    def start_fit_ap_verbose(
        self,
        site_id: str,
        *,
        ac_id: str,
        scope: str,
        ap_ids: list[str] | None = None,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        normalized_scope = str(scope or "").strip().casefold()
        if normalized_scope not in {"all", "selected"}:
            raise AcWebActionError("TASK_NOT_ALLOWED", "不支持的 FIT-AP 详细信息范围")
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        selected = list(dict.fromkeys(str(value or "").strip() for value in ap_ids or [] if str(value or "").strip()))
        if normalized_scope == "selected":
            if not selected:
                raise AcWebActionError("AP_TARGET_REQUIRED", "未选择要获取详细信息的 FIT-AP")
            repository = self._repository(site_id)
            if any(repository.get_fit_ap_resource_by_uuid(device_uuid, ap_uuid) is None for ap_uuid in selected):
                raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "目标 FIT-AP 不属于当前 AC")
        task_id = f"ac-web-{uuid4().hex}"
        task_type = "ac_fit_ap_verbose_selected_refresh" if normalized_scope == "selected" else "ac_fit_ap_verbose_all_refresh"
        params = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": self._REFRESH_TASKS[f"verbose-{normalized_scope}"][1],
            "owner": self._OWNER,
            "task_source": "local",
            "device_uuid": device_uuid,
            "ac_uuid": device_uuid,
            "target_ap_uuids": selected,
            "mode": "collect",
            "source": "cli",
        }
        resource_key = fit_ap_optical_resource_key(site_id, device_uuid)
        if resource_key:
            params["resource_keys"] = [resource_key]
        try:
            self.process_adapter.start_job(
                BackgroundJob(job_id=task_id, task_type=task_type, params=params)
            )
        except TaskResourceConflictError as exc:
            raise AcWebActionError("FIT_AP_UPDATE_RUNNING", str(exc)) from exc
        return self._task_dto(site_id, task_id)

    def get_task(self, site_id: str, task_id: str) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        return self._task_dto(site_id, task_id)

    def start_fit_ap_delete(
        self,
        site_id: str,
        *,
        ac_id: str,
        ap_ids: list[str],
        explicit_confirmation: bool,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise AcWebActionError("CONFIRMATION_REQUIRED", "批量删除 FIT-AP 前必须明确确认")
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        selected = list(dict.fromkeys(str(value or "").strip() for value in ap_ids if str(value or "").strip()))
        if not selected:
            raise AcWebActionError("AP_TARGET_REQUIRED", "未选择要删除的 FIT-AP")
        repository = self._repository(site_id)
        if any(repository.get_fit_ap_resource_by_uuid(device_uuid, ap_uuid) is None for ap_uuid in selected):
            raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "待删除 FIT-AP 不属于当前 AC")
        task_id = f"ac-web-delete-{uuid4().hex}"
        self.process_adapter.start_job(
            BackgroundJob(
                job_id=task_id,
                task_type="ac_fit_ap_delete_many",
                params={
                    "site_name": site_id,
                    "db_path": str(self.paths.site_db_path(site_id)),
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "task_name": "批量删除 FIT-AP",
                    "owner": self._OWNER,
                    "task_source": "local",
                    "device_uuid": device_uuid,
                    "ac_uuid": device_uuid,
                    "ap_uuids": selected,
                },
            )
        )
        return self._task_dto(site_id, task_id)

    def start_fit_ap_metadata_import(self, site_id: str, *, file_name: str, content: bytes) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        suffix = Path(str(file_name or "")).suffix.casefold()
        if suffix not in {".csv", ".xlsx"}:
            raise AcWebActionError("IMPORT_TYPE_INVALID", "FIT-AP 元数据只支持 CSV 或 XLSX")
        if not content:
            raise AcWebActionError("IMPORT_EMPTY", "FIT-AP 元数据导入文件为空")
        if len(content) > 20 * 1024 * 1024:
            raise AcWebActionError("IMPORT_TOO_LARGE", "FIT-AP 元数据导入文件不能超过 20 MiB")
        task_id = f"ac-web-metadata-{uuid4().hex}"
        input_root = self.paths.trackside_ap_outputs_dir(site_id) / "web_imports"
        input_path = (input_root / f"{task_id}{suffix}").resolve()
        if input_root.resolve() not in input_path.parents:
            raise AcWebActionError("IMPORT_PATH_INVALID", "FIT-AP 元数据暂存路径无效")
        pending = input_path.with_suffix(f"{suffix}.tmp")
        try:
            input_root.mkdir(parents=True, exist_ok=True)
            pending.write_bytes(content)
            os.replace(pending, input_path)
        except OSError as exc:
            pending.unlink(missing_ok=True)
            raise AcWebActionError("IMPORT_STAGE_FAILED", "FIT-AP 元数据导入文件暂存失败") from exc

        def completed(_value: LocalProcessCompletion) -> None:
            self._cleanup_task_runtime(site_id, task_id)

        try:
            self.process_adapter.start_job(
                BackgroundJob(
                    job_id=task_id,
                    task_type="fit_ap_metadata_import",
                    params={
                        "site_name": site_id,
                        "db_path": str(self.paths.site_db_path(site_id)),
                        "app_root": str(self.paths.app_root),
                        "data_root": str(self.paths.data_root),
                        "task_name": "导入 FIT-AP 元数据",
                        "owner": self._OWNER,
                        "task_source": "local",
                        "path": str(input_path),
                    },
                ),
                on_complete=completed,
            )
        except Exception:
            input_path.unlink(missing_ok=True)
            pending.unlink(missing_ok=True)
            raise
        return self._task_dto(site_id, task_id)

    def start_fit_ap_metadata_save(
        self,
        site_id: str,
        *,
        ac_id: str,
        ap_id: str,
        metadata: dict[str, object],
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        ap_uuid = str(ap_id or "").strip()
        resource = self._repository(site_id).get_fit_ap_resource_by_uuid(device_uuid, ap_uuid)
        if resource is None:
            raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "目标 FIT-AP 不属于当前 AC")
        repository = self._repository(site_id)
        has_station_contract = "station_id" in metadata or "station_override_enabled" in metadata
        station_id = str(metadata.get("station_id") or "").strip()
        station_enabled = bool(metadata.get("station_override_enabled"))
        station_name = ""
        if has_station_contract and station_enabled:
            with repository.database.connect() as conn:
                station = conn.execute(
                    """
                    SELECT station_name
                    FROM ap_extension_points
                    WHERE belong_type = '__base_station__' AND station_id = ?
                    ORDER BY id
                    LIMIT 2
                    """,
                    (station_id,),
                ).fetchall()
            if len(station) != 1 or not str(station[0]["station_name"] or "").strip():
                raise AcWebActionError("STATION_NOT_FOUND", "手工覆盖站点必须选择正式站点")
            station_name = str(station[0]["station_name"] or "").strip()
        payload = {
            "ap_uuid": ap_uuid,
            "ap_name": str(resource.get("ap_name") or ""),
            "mileage": mileage_storage_text(metadata.get("mileage")),
            "location_note": str(metadata.get("location_note") or "").strip(),
            "direction": normalize_ap_direction(str(metadata.get("direction") or "")),
        }
        if has_station_contract:
            payload.update(
                {
                    "station_id": station_id if station_enabled else "",
                    "station_override_enabled": station_enabled,
                    "site_name": station_name if station_enabled else "",
                }
            )
        else:
            # Legacy clients are kept readable; the Vue path always uses station_id.
            payload["site_name"] = str(metadata.get("site_name") or "").strip()
        task_id = f"ac-web-metadata-save-{uuid4().hex}"
        self.process_adapter.start_job(
            BackgroundJob(
                job_id=task_id,
                task_type="fit_ap_metadata_save",
                params={
                    "site_name": site_id,
                    "db_path": str(self.paths.site_db_path(site_id)),
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "task_name": "保存 FIT-AP 元数据",
                    "owner": self._OWNER,
                    "task_source": "local",
                    "device_uuid": device_uuid,
                    "ac_uuid": device_uuid,
                    "metadata": payload,
                },
            )
        )
        return self._task_dto(site_id, task_id)

    def start_omnipeek_preview(
        self,
        site_id: str,
        *,
        ac_id: str,
        ap_ids: list[str],
        options: dict[str, object] | None = None,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        selected = self._validated_ap_ids(site_id, device_uuid, ap_ids)
        values = dict(options or {})
        line_name = str(values.get("line_name") or "").strip() or default_omnipeek_line_name(site_id, self.paths)
        colors = dict(values.get("colors") or {}) or load_omnipeek_color_settings(SettingsStore(self.paths))
        task_id = f"ac-omnipeek-preview-{uuid4().hex}"
        self.process_adapter.start_job(
            BackgroundJob(
                job_id=task_id,
                task_type="omnipeek_name_table_preview",
                params={
                    "site_name": site_id,
                    "db_path": str(self.paths.site_db_path(site_id)),
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "task_name": "预览 OmniPeek 名称表",
                    "owner": self._OWNER,
                    "task_source": "local",
                    "device_uuid": device_uuid,
                    "ac_uuid": device_uuid,
                    "selected_fit_ap_ids": selected,
                    "scope_extensions_to_fit_ap": True,
                    "include_ac_fit_ap": bool(values.get("include_ac_fit_ap", True)),
                    "include_ap_extensions": bool(values.get("include_ap_extensions", True)),
                    "include_device_mr": bool(values.get("include_device_mr", False)),
                    "line_name": line_name,
                    "export_trackside_physical": bool(values.get("export_trackside_physical", True)),
                    "export_trackside_r1": bool(values.get("export_trackside_r1", True)),
                    "export_trackside_r2": bool(values.get("export_trackside_r2", True)),
                    "export_onboard_physical": bool(values.get("export_onboard_physical", True)),
                    "export_onboard_r1": bool(values.get("export_onboard_r1", True)),
                    "export_onboard_r2": bool(values.get("export_onboard_r2", True)),
                    "onboard_radio_mode": str(values.get("onboard_radio_mode") or "auto"),
                    "enable_h3c_derivation": bool(values.get("enable_h3c_derivation", True)),
                    "colors": colors,
                },
            )
        )
        return self._task_dto(site_id, task_id)

    def get_omnipeek_preview(
        self,
        site_id: str,
        task_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
        status_filter: str = "all",
        search: str = "",
    ) -> AcOmniPeekPreviewDTO:
        site_id = self._site(site_id)
        snapshot = self._task_snapshot(site_id, task_id)
        if snapshot.task_type != "omnipeek_name_table_preview":
            raise AcWebActionError("TASK_NOT_FOUND", "OmniPeek 预览任务不存在")
        result = dict(snapshot.result or {})
        stats = dict(result.get("stats") or {})
        source_counts = dict(result.get("source_counts") or {})
        rows = [dict(item) for item in result.get("items") or [] if isinstance(item, dict)]
        filtered = [
            item
            for item in rows
            if self._matches_omnipeek_filter(item, status_filter)
            and self._matches_omnipeek_search(item, search)
        ]
        page_size = max(20, min(int(page_size), 500))
        page = max(1, int(page))
        start = (page - 1) * page_size
        selected_keys = [str(item.get("item_key") or "") for item in rows if item.get("selected")]
        return AcOmniPeekPreviewDTO(
            task_id=task_id,
            task_status=snapshot.status.value,
            ready=snapshot.status is TaskState.COMPLETED,
            config=dict(result.get("config") or {}),
            source_counts={str(key): int(value) for key, value in source_counts.items()},
            statistics={str(key): int(value) for key, value in stats.items()},
            items=filtered[start:start + page_size],
            matching_item_keys=[str(item.get("item_key") or "") for item in filtered],
            selected_item_keys=selected_keys,
            total=len(filtered),
            page=page,
            page_size=page_size,
            input_ap_count=int(source_counts.get("AC FIT-AP资源") or 0),
            exportable_entry_count=int(stats.get("exportable_entries") or 0),
            skipped_count=int(stats.get("skipped") or 0),
            error_count=int(stats.get("error_count") or stats.get("abnormal") or 0),
            message=redact_web_task_text(snapshot.message or snapshot.error_message),
        )

    def start_omnipeek_export(
        self,
        site_id: str,
        *,
        ac_id: str,
        ap_ids: list[str],
        options: dict[str, object] | None = None,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if self.export_adapter is None:
            raise AcWebActionError("EXPORT_NOT_WIRED", "OmniPeek 导出进程未接线")
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        selected = self._validated_ap_ids(site_id, device_uuid, ap_ids)
        values = dict(options or {})
        line_name = str(values.get("line_name") or "").strip() or default_omnipeek_line_name(site_id, self.paths)
        colors = dict(values.get("colors") or {}) or load_omnipeek_color_settings(SettingsStore(self.paths))
        save_omnipeek_color_settings(SettingsStore(self.paths), colors)
        task_id = f"ac-omnipeek-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="ac_omnipeek_export",
            artifact_type="nam",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["ac_omnipeek_export"],
            output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_omnipeek",
            preferred_name=make_omnipeek_filename(line_name),
            use_display_name_as_file_name=True,
        )
        job = omnipeek_name_table_spec(
            reservation.output_path,
            db_path=self.paths.site_db_path(site_id),
            site_name=site_id,
            source={
                "ac_uuid": device_uuid,
                "selected_fit_ap_ids": selected,
                "selected_device_uuids": [],
                "scope_extensions_to_fit_ap": True,
            },
            config={
                "line_name": line_name,
                "include_ac_fit_ap": bool(values.get("include_ac_fit_ap", True)),
                "include_ap_extensions": bool(values.get("include_ap_extensions", True)),
                "include_device_mr": bool(values.get("include_device_mr", False)),
                "export_trackside_physical": bool(values.get("export_trackside_physical", True)),
                "export_trackside_r1": bool(values.get("export_trackside_r1", True)),
                "export_trackside_r2": bool(values.get("export_trackside_r2", True)),
                "export_onboard_physical": bool(values.get("export_onboard_physical", True)),
                "export_onboard_r1": bool(values.get("export_onboard_r1", True)),
                "export_onboard_r2": bool(values.get("export_onboard_r2", True)),
                "onboard_radio_mode": str(values.get("onboard_radio_mode") or "auto"),
                "enable_h3c_derivation": bool(values.get("enable_h3c_derivation", True)),
                "colors": colors,
            },
            selected_item_keys=[str(value) for value in values.get("selected_item_keys") or []],
            excluded_item_keys=[str(value) for value in values.get("excluded_item_keys") or []],
            force_export_keys=[str(value) for value in values.get("force_export_keys") or []],
            title="导出 OmniPeek 名称表",
            open_dir_on_success=False,
        ).to_job(task_id)
        job = replace(job, site_name=site_id)

        def completed(value: LocalProcessCompletion) -> None:
            try:
                if value.exit_code == 0 and not value.cancelled:
                    self.artifact_store.complete(reservation)
                else:
                    self.artifact_store.fail(reservation)
            except WebArtifactError:
                self.artifact_store.fail(reservation)

        try:
            self.export_adapter.start_export(
                job,
                task_name="导出 OmniPeek 名称表",
                owner=self._OWNER,
                public_result=self._public_artifact_result(reservation),
                on_complete=completed,
            )
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        return self._task_dto(site_id, task_id)

    def start_fit_ap_resource_export(
        self,
        site_id: str,
        *,
        ac_id: str,
        scope: str,
        selected_ap_ids: list[str],
        filters: dict[str, object] | None = None,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if self.export_adapter is None:
            raise AcWebActionError("EXPORT_NOT_WIRED", "FIT-AP 资源导出进程未接线")
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        scope = str(scope or "").casefold()
        if scope not in {"filtered", "selected", "all"}:
            raise AcWebActionError("EXPORT_SCOPE_INVALID", "FIT-AP 资源导出范围无效")
        selected = list(dict.fromkeys(str(value or "").strip() for value in selected_ap_ids if str(value or "").strip()))
        if scope == "selected" and not selected:
            raise AcWebActionError("AP_SELECTION_REQUIRED", "请先选择要导出的 FIT-AP")
        allowed_filters = {"query", "status", "optical_status", "station", "section", "model", "switch"}
        values = {
            key: str(value or "").strip()
            for key, value in dict(filters or {}).items()
            if key in allowed_filters and str(value or "").strip()
        }
        effective_filters = values if scope == "filtered" else {}
        effective_selected = selected if scope == "selected" else []
        details = AcManagementQueryService(self.paths).list_ap_details_for_export(
            site_id,
            ac_id=device_uuid,
            filters=effective_filters,
            selected_ap_ids=effective_selected,
        )
        if effective_selected and {item.ap.id for item in details} != set(effective_selected):
            raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "已选择 AP 不属于当前 AC")
        if not details:
            raise AcWebActionError("EXPORT_SCOPE_EMPTY", "当前范围内没有可导出的 FIT AP")

        ac = AcManagementQueryService(self.paths).get_ac_export_identity(site_id, device_uuid)
        if ac is None:
            raise AcWebActionError("TARGET_NOT_AUTHORIZED", "当前 AC 不存在")
        requested_at = datetime.now(timezone.utc).isoformat()
        task_id = f"ac-fit-ap-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="ac_fit_ap_resource_export",
            artifact_type="xlsx",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["ac_fit_ap_resource_export"],
            output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_fit_ap_resources",
            preferred_name=make_fit_ap_resource_filename(site_id, ac.name),
            use_display_name_as_file_name=True,
        )
        job = fit_ap_resource_xlsx_spec(
            reservation.output_path,
            db_path=self.paths.site_db_path(site_id),
            site_name=site_id,
            ac_uuid=device_uuid,
            scope=scope,
            selected_ap_ids=effective_selected,
            filters=effective_filters,
            requested_at=requested_at,
            app_root=self.paths.app_root,
            data_root=self.paths.data_root,
            title="导出 FIT-AP 资源",
            open_dir_on_success=False,
        ).to_job(task_id)
        job = replace(job, site_name=site_id)
        scope_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "ac_id": device_uuid,
                    "scope": scope,
                    "selected_ap_ids": sorted(effective_selected),
                    "filters": effective_filters,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:20]

        def completed(value: LocalProcessCompletion) -> None:
            try:
                if value.exit_code == 0 and not value.cancelled:
                    self.artifact_store.complete(reservation)
                else:
                    self.artifact_store.fail(reservation)
            except WebArtifactError:
                self.artifact_store.fail(reservation)

        try:
            self.export_adapter.start_export(
                job,
                task_name="导出 FIT-AP 资源",
                owner=self._OWNER,
                public_result=self._public_artifact_result(reservation),
                resource_keys=[f"ac-fit-ap-export:{site_id}:{device_uuid}:{scope_fingerprint}"],
                on_complete=completed,
            )
        except TaskResourceConflictError as exc:
            self.artifact_store.fail(reservation)
            raise AcWebActionError("EXPORT_ALREADY_RUNNING", "相同范围的 FIT-AP 资源导出正在运行") from exc
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        return self._task_dto(site_id, task_id)

    def omnipeek_preferences(self, site_id: str) -> AcOmniPeekPreferencesDTO:
        site_id = self._site(site_id)
        return AcOmniPeekPreferencesDTO(
            line_name=default_omnipeek_line_name(site_id, self.paths),
            colors=load_omnipeek_color_settings(SettingsStore(self.paths)),
        )

    def save_omnipeek_preferences(self, site_id: str, colors: dict[str, str]) -> AcOmniPeekPreferencesDTO:
        self._site(site_id)
        save_omnipeek_color_settings(SettingsStore(self.paths), colors)
        return self.omnipeek_preferences(site_id)

    def external_terminal_options(self) -> AcExternalTerminalOptionsDTO:
        self._require_desktop_runtime()
        settings = SettingsStore(self.paths)
        configs = available_external_terminal_configs(settings)
        available = {config.terminal_type for config in configs}
        default_type = normalize_external_terminal_type(settings.get_value("external_terminal/type", "securecrt"))
        if default_type not in available:
            default_type = configs[0].terminal_type if configs else None
        return AcExternalTerminalOptionsDTO(
            default_terminal_type=default_type,
            options=[
                AcExternalTerminalOptionDTO(
                    terminal_type=config.terminal_type,
                    label=TERMINAL_LABELS.get(config.terminal_type, config.terminal_type),
                )
                for config in configs
            ],
        )

    def launch_fit_ap_external_terminal(
        self,
        site_id: str,
        *,
        ac_id: str,
        ap_id: str,
        terminal_type: str,
    ) -> AcExternalTerminalActionDTO:
        site_id = self._site(site_id)
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        detail = AcManagementQueryService(self.paths).get_ap_detail(site_id, str(ap_id or "").strip())
        if detail is None or detail.ap.ac_id != device_uuid:
            raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "目标 FIT-AP 不属于当前 AC")
        if not detail.ap.ip:
            raise AcWebActionError("AP_ADDRESS_MISSING", "当前 AP 没有 IP，无法打开外部终端")
        if detail.ap.status != "online":
            raise AcWebActionError("AP_NOT_ONLINE", "当前 AP 离线或状态异常，无法打开外部终端")
        self._require_desktop_runtime()
        configs = {
            config.terminal_type: config
            for config in available_external_terminal_configs(SettingsStore(self.paths))
        }
        config = configs.get(str(terminal_type or "").casefold())
        if config is None:
            raise AcWebActionError("TERMINAL_NOT_CONFIGURED", "未配置所选外部终端，请先到系统设置配置")
        temporary_device = Device(
            device_uuid=detail.ap.id,
            name=detail.ap.name,
            device_vendor="H3C",
            device_type="Cloud-AP",
            primary_address=detail.ap.ip,
            protocol="telnet",
            port=23,
            username="",
            password="",
            ssh_enabled=0,
            telnet_enabled=1,
            telnet_port=23,
            telnet_username="",
            telnet_password="",
        )
        telnet_target = ConnectionTarget(
            protocol="telnet",
            device_type="hp_comware_telnet",
            host=detail.ap.ip,
            port=23,
            username="",
            password="",
        )
        args = build_external_terminal_command(
            temporary_device,
            telnet_target,
            config.terminal_type,
            config.exe_path,
            include_password=False,
        )
        assert self.desktop_action_service is not None
        executable = Path(args[0])
        result = self.desktop_action_service.launch_terminal(
            f"terminal.{config.terminal_type}",
            detail.ap.id,
            RegisteredLaunch(executable, tuple(args[1:]), executable.parent),
        )
        if not result.success:
            raise AcWebActionError("TERMINAL_LAUNCH_FAILED", result.message or "外部终端启动失败")
        return AcExternalTerminalActionDTO(
            ap_id=detail.ap.id,
            terminal_type=config.terminal_type,
            protocol="telnet",
            port=23,
            message=f"已打开 {detail.ap.name} 的 Telnet 终端",
        )

    @staticmethod
    def _matches_omnipeek_filter(item: dict[str, object], status_filter: str) -> bool:
        value = str(status_filter or "all")
        status = str(item.get("status") or "")
        if value == "selected":
            return bool(item.get("selected"))
        if value == "abnormal":
            return status != "正常"
        if value == "mac_conflict":
            return status == "MAC冲突"
        if value == "r2_failed":
            return status == "R2推导失败"
        if value == "missing_mac":
            return status == "缺少物理MAC"
        return True

    @staticmethod
    def _matches_omnipeek_search(item: dict[str, object], search: str) -> bool:
        needle = str(search or "").strip().casefold()
        if not needle:
            return True
        return any(
            needle in str(item.get(key) or "").casefold()
            for key in ("name", "location", "physical_mac", "r1_mac", "r2_mac", "data_source")
        )

    def cancel_task(self, site_id: str, task_id: str) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        snapshot = self._task_snapshot(site_id, task_id)
        if snapshot.status not in TERMINAL_TASK_STATES:
            cancelled = self.process_adapter.cancel_job(task_id)
            if not cancelled and self.export_adapter is not None:
                cancelled = self.export_adapter.cancel_job(task_id)
            if not cancelled:
                self._reconcile_owned_orphans(site_id)
        return self._task_dto(site_id, task_id)

    def recover_tasks(self, site_id: str) -> list[AcWebTaskDTO]:
        site_id = self._site(site_id)
        repository = self.task_service.repository(site_id)
        self._reconcile_owned_orphans(site_id)
        for item in repository.list(statuses=TERMINAL_TASK_STATES, limit=1000):
            if item.site_name != site_id or not self._authorized_task(item):
                continue
            self._cleanup_task_runtime(site_id, item.task_id)
            if item.task_type in self._ARTIFACT_TASK_TYPES.values():
                self.artifact_store.recover_task(
                    site_id,
                    item.task_id,
                    owner=self._OWNER,
                    source_task_types=self._ARTIFACT_TASK_TYPES,
                    succeeded=item.status == TaskState.COMPLETED,
                )
        return [
            self._task_dto(site_id, item.task_id)
            for item in repository.list(limit=200)
            if item.site_name == site_id and self._authorized_task(item)
        ]

    def create_action_plan(self, site_id: str, target_id: str, action_id: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        label, commands = self._action(action_id)
        target = self._target(site_id, target_id)
        plan_id = f"ac-plan-{uuid4().hex}"
        fingerprint = self._fingerprint(target)
        digest = self._digest(plan_id, site_id, str(target.device_uuid), action_id, commands, fingerprint)
        plan: dict[str, object] = {
            "plan_id": plan_id,
            "site_id": site_id,
            "target_id": str(target.device_uuid),
            "target_fingerprint": fingerprint,
            "action_id": action_id,
            "action_label": label,
            "commands": list(commands),
            "digest": digest,
            "token": secrets.token_urlsafe(24),
            "expires_at": time.time() + 300,
            "status": "PREVIEW",
            "task_id": "",
        }
        self._save_plan(plan)
        return self._plan_dto(plan)

    def preview_action_plan(self, site_id: str, plan_id: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            if float(plan["expires_at"]) <= time.time() and plan["status"] == "PREVIEW":
                plan["status"] = "EXPIRED"
                self._save_plan(plan)
            self._refresh_plan_status(site_id, plan)
            return self._plan_dto(plan)

    def confirm_action_plan(self, site_id: str, plan_id: str, plan_digest: str, confirm_token: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            self._validate_plan(plan, plan_digest, confirm_token)
            if plan["status"] != "PREVIEW":
                raise AcWebActionError("PLAN_ALREADY_CONFIRMED", "计划已确认或已执行")
            self._revalidate_target(plan)
            plan["status"] = "CONFIRMED"
            self._save_plan(plan)
            return self._plan_dto(plan)

    def execute_action_plan(self, site_id: str, plan_id: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            if float(plan["expires_at"]) <= time.time():
                raise AcWebActionError("PLAN_EXPIRED", "动作计划已过期")
            if plan["status"] != "CONFIRMED":
                raise AcWebActionError("CONFIRMATION_REQUIRED", "执行前必须完成二次确认")
            self._validate_plan(plan, str(plan["digest"]), str(plan["token"]))
            self._revalidate_target(plan)
            label, commands = self._action(str(plan["action_id"]))
            task_id = f"ac-web-action-{uuid4().hex}"
            plan["status"] = "EXECUTING"
            plan["task_id"] = task_id
            self._save_plan(plan)
            try:
                self.process_adapter.start_job(
                    BackgroundJob(
                        job_id=task_id,
                        task_type="ac_command_action_execute",
                        params={
                            "site_name": site_id,
                            "db_path": str(self.paths.site_db_path(site_id)),
                            "app_root": str(self.paths.app_root),
                            "data_root": str(self.paths.data_root),
                            "task_name": label,
                            "owner": self._OWNER,
                            "task_source": "local",
                            "device_uuid": str(plan["target_id"]),
                            "ac_uuid": str(plan["target_id"]),
                            "action": str(plan["action_id"]),
                            "command_sequence": list(commands),
                            "confirm_required": True,
                            "source": "cli",
                            "plan_id": str(plan["plan_id"]),
                            "plan_digest": str(plan["digest"]),
                            "resource_keys": [f"{site_id}:{plan['target_id']}:ac_config_write"],
                            "resource_conflict_message": "当前 AC 已有配置写任务正在运行",
                        },
                    )
                )
            except TaskResourceConflictError as exc:
                plan["status"] = "CONFIRMED"
                plan["task_id"] = ""
                self._save_plan(plan)
                raise AcWebActionError("AC_ACTION_RUNNING", "当前 AC 已有配置写任务正在运行") from exc
            except Exception:
                plan["status"] = "START_FAILED"
                self._save_plan(plan)
                raise
            return self._plan_dto(plan)

    def action_audit(self, site_id: str, plan_id: str) -> dict[str, object]:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            snapshot = self._refresh_plan_status(site_id, plan)
            return {
                "plan_id": plan["plan_id"],
                "target_id": plan["target_id"],
                "action_id": plan["action_id"],
                "commands": list(plan["commands"]),
                "plan_digest": plan["digest"],
                "status": plan["status"],
                "task_id": plan["task_id"],
                "task_status": snapshot.status.value if snapshot is not None else "",
                "result_summary": self._result_summary(snapshot.result) if snapshot is not None else {},
                "executor": "LOCAL",
                "real_device_task": bool(plan["task_id"]),
                "audit": True,
            }

    def preview_extension(self, site_id: str, file_name: str, content: bytes, content_type: str = "") -> AcExtensionPreviewDTO:
        site_id = self._site(site_id)
        try:
            preview = self.import_preview_service.preview(
                site_id=site_id,
                file_name=file_name,
                content=content,
                content_type=content_type,
            )
        except (BaseDataImportError, ValueError) as exc:
            self._import_error(exc)
        summary = preview.merge_plan.summary.model_dump() if preview.merge_plan is not None else {}
        return AcExtensionPreviewDTO(
            preview_id=preview.preview_id,
            file_name=preview.file_name,
            template_type=preview.template_type,
            confidence_score=preview.confidence_score,
            low_confidence=preview.confidence_score < 70,
            summary={key: int(value or 0) for key, value in summary.items()},
            row_count=preview.total_rows,
            preview_digest=preview.database_hash,
        )

    def apply_extension(self, site_id: str, preview_id: str, preview_digest: str, explicit_confirmation: bool) -> AcExtensionApplyResultDTO:
        site_id = self._site(site_id)
        with self._lock(f"import:{site_id}:{preview_id}"):
            try:
                audit = self.base_import_service.apply_preview(
                    preview_id=preview_id,
                    site_id=site_id,
                    expected_database_sha256=preview_digest,
                    explicit_confirmation=explicit_confirmation,
                    owner="web_ac",
                )
            except BaseDataImportError as exc:
                if exc.code != "ALREADY_APPLIED":
                    self._import_error(exc)
                operation = self.base_import_service.get_operation(site_id, preview_id)
                return self._apply_result(operation.model_dump())
        return self._apply_result(audit)

    def rollback_extension(self, site_id: str, audit_id: str, explicit_confirmation: bool) -> AcExtensionRollbackResultDTO:
        site_id = self._site(site_id)
        with self._lock(f"import:{site_id}:{audit_id}"):
            try:
                audit = self.base_import_service.rollback_import(
                    site_id=site_id,
                    operation_id=audit_id,
                    explicit_confirmation=explicit_confirmation,
                )
            except BaseDataImportError as exc:
                self._import_error(exc)
        return AcExtensionRollbackResultDTO(
            audit_id=str(audit.get("operation_id") or audit_id),
            status=str(audit.get("status") or "ROLLED_BACK"),
            restored_rows=len(audit.get("changes") or ()),
        )

    def start_extension_export(self, site_id: str, *, search: str = "", ac_id: str = "") -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if self.export_adapter is None:
            raise AcWebActionError("EXPORT_NOT_WIRED", "AC 扩展导出进程未接线")
        task_id = f"ac-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner="web_ac",
            source="ac_extension_export",
            artifact_type="xlsx",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["ac_extension_export"],
            output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_extensions",
            preferred_name="AP扩展信息.xlsx",
        )
        job = fit_ap_extension_xlsx_spec(
            reservation.output_path,
            db_path=self.paths.site_db_path(site_id),
            ac_uuid=ac_id,
            search=search,
            title="AP 扩展信息导出",
            open_dir_on_success=False,
        ).to_job(task_id)
        job = replace(job, site_name=site_id)

        def completed(value: LocalProcessCompletion) -> None:
            if value.exit_code == 0 and not value.cancelled:
                try:
                    self.artifact_store.complete(reservation)
                except WebArtifactError:
                    self.artifact_store.fail(reservation)
            else:
                self.artifact_store.fail(reservation)

        try:
            self.export_adapter.start_export(
                job,
                task_name="AP 扩展信息导出",
                owner="web_ac",
                public_result=self._public_artifact_result(reservation),
                on_complete=completed,
            )
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        return self._task_dto(site_id, task_id)

    @staticmethod
    def _public_artifact_result(reservation) -> dict[str, object]:
        return {
            "artifact_id": reservation.artifact_id,
            "artifact_name": reservation.output_path.name,
            "artifact_source": reservation.source,
            "artifact_type": reservation.artifact_type,
        }

    def open_extension_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner="web_ac",
                source="ac_extension_export",
                artifact_type="xlsx",
                task_type=self._ARTIFACT_TASK_TYPES["ac_extension_export"],
            )
        except WebArtifactError as exc:
            raise AcWebActionError("ARTIFACT_INVALID", str(exc)) from exc
        return path, name

    def open_omnipeek_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner=self._OWNER,
                source="ac_omnipeek_export",
                artifact_type="nam",
                task_type=self._ARTIFACT_TASK_TYPES["ac_omnipeek_export"],
            )
        except WebArtifactError as exc:
            raise AcWebActionError("ARTIFACT_INVALID", str(exc)) from exc
        return path, name

    def open_fit_ap_resource_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner=self._OWNER,
                source="ac_fit_ap_resource_export",
                artifact_type="xlsx",
                task_type=self._ARTIFACT_TASK_TYPES["ac_fit_ap_resource_export"],
            )
        except WebArtifactError as exc:
            raise AcWebActionError("ARTIFACT_INVALID", str(exc)) from exc
        return path, name

    def _task_dto(self, site_id: str, task_id: str) -> AcWebTaskDTO:
        snapshot = sanitize_web_export_snapshot(self._task_snapshot(site_id, task_id))
        metadata = (
            self.artifact_store.task_metadata(
                site_id,
                task_id,
                owner=self._OWNER,
                source_task_types=self._ARTIFACT_TASK_TYPES,
            )
            if snapshot.task_type in self._ARTIFACT_TASK_TYPES.values()
            else None
        )
        return AcWebTaskDTO(
            task_id=task_id,
            status=snapshot.status.value,
            action=self._TASK_ACTIONS[snapshot.task_type],
            target_id=str(snapshot.device if snapshot.task_type == "ac_command_action_execute" else ""),
            artifact_id=str((metadata or {}).get("artifact_id") or ""),
            artifact_name=str((metadata or {}).get("display_name") or (metadata or {}).get("file_name") or ""),
            available=bool(metadata and metadata.get("completed") is True),
            progress=snapshot.progress,
            stage=snapshot.stage,
            current=snapshot.current,
            total=snapshot.total,
            sha256=str((metadata or {}).get("sha256") or ""),
            size_bytes=int((metadata or {}).get("size_bytes") or 0),
            message=redact_web_task_text(snapshot.message),
            error_message=redact_web_task_text(snapshot.error_message),
            result_summary=self._result_summary(snapshot.result),
        )

    def _task_snapshot(self, site_id: str, task_id: str):
        snapshot = self.task_service.repository(site_id).get(str(task_id or ""))
        if snapshot is None or snapshot.site_name != site_id or not self._authorized_task(snapshot):
            raise AcWebActionError("TASK_NOT_FOUND", "任务不存在或不属于当前局点")
        return snapshot

    def _authorized_task(self, snapshot) -> bool:
        return (
            snapshot.owner == self._OWNER
            and snapshot.source == "local"
            and snapshot.task_type in self._TASK_ACTIONS
        )

    def _reconcile_owned_orphans(self, site_id: str):
        repository = self.task_service.repository(site_id)
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        owned_pids = {
            item.owner_pid
            for item in repository.list(statuses=active, limit=1000)
            if item.site_name == site_id and self._authorized_task(item) and item.owner_pid > 0
        }
        if not owned_pids:
            return []
        return repository.reconcile_orphaned_local_tasks(
            lambda pid: True if pid not in owned_pids else self.task_service._is_process_alive(pid)
        )

    def _cleanup_task_runtime(self, site_id: str, task_id: str) -> None:
        for directory, suffix in (
            (self.paths.runtime_cache_dir / "background_jobs", ".json"),
            (self.paths.runtime_cache_dir / "background_jobs", ".cancel"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json.tmp"),
        ):
            path = (directory / f"{task_id}{suffix}").resolve()
            try:
                if directory.resolve() in path.parents:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        import_root = self.paths.trackside_ap_outputs_dir(site_id) / "web_imports"
        for suffix in (".csv", ".xlsx", ".csv.tmp", ".xlsx.tmp"):
            path = (import_root / f"{task_id}{suffix}").resolve()
            try:
                if import_root.resolve() in path.parents:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _result_summary(result: dict[str, object]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for key in (
            "count",
            "row_count",
            "uses_trackside_plan",
            "offline_ap_stats",
            "success",
            "action",
            "collect_run_uuid",
            "ac_uuid",
            "snapshot_revision",
            "fit_ap_resources_updated",
            "unauthenticated_rows_updated",
            "bbssid_rows_parsed",
            "lldp_rows_parsed",
            "reload_required",
            "data_persisted",
            "error_code",
            "error_message",
            "confirm_required",
            "plan_id",
            "plan_digest",
            "updated",
            "skipped",
            "ap_count",
            "radio_count",
            "warning_count",
            "detail_rows_updated",
            "detail_failed_count",
            "detail_mode",
        ):
            value = result.get(key)
            if isinstance(value, (bool, int, float, str, dict)):
                summary[key] = redact_web_task_text(value) if isinstance(value, str) else value
        for key in ("rows", "overview_rows", "resources", "optical_rows", "offline_ap_ledger_rows"):
            value = result.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
        collection = result.get("collection")
        if isinstance(collection, dict):
            summary["collection"] = {
                key: collection[key]
                for key in (
                    "success",
                    "source",
                    "collect_run_uuid",
                    "fit_ap_resources_updated",
                    "unauthenticated_rows_updated",
                    "bbssid_rows_parsed",
                    "lldp_rows_parsed",
                    "failed_commands",
                    "summary_updated",
                    "https_port",
                    "https_port_persisted",
                    "target_ap_uuid",
                    "detail_rows_updated",
                    "detail_failed_count",
                    "detail_mode",
                    "partial_success",
                    "refresh_scope",
                    "optical_rows_updated",
                    "failed_aps",
                    "error_message",
                    "requested_concurrency",
                    "effective_concurrency",
                    "platform_concurrency_limit",
                )
                if key in collection
            }
            round_summaries = collection.get("round_summaries")
            if isinstance(round_summaries, list):
                summary["collection"]["round_summaries_count"] = len(round_summaries)
        commands = result.get("commands")
        if isinstance(commands, list):
            summary["commands"] = [str(command) for command in commands]
        command_results = result.get("command_results")
        if isinstance(command_results, list):
            summary["command_results"] = [
                {
                    "command": str(item.get("command") or ""),
                    "success": bool(item.get("success")),
                    "error_message": redact_web_task_text(str(item.get("error_message") or "")),
                }
                for item in command_results
                if isinstance(item, dict)
            ]
        errors = result.get("errors")
        if isinstance(errors, list):
            summary["errors"] = [redact_web_task_text(str(value)) for value in errors[:50]]
            summary["errors_count"] = len(errors)
        return summary

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise AcWebActionError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        root = self.paths.site_dir(value).resolve()
        try:
            root.relative_to(self.paths.sites_dir.resolve())
        except ValueError as exc:
            raise AcWebActionError("SITE_CONTEXT_INVALID", "局点目录不受控") from exc
        if not root.is_dir():
            raise AcWebActionError("SITE_CONTEXT_INVALID", "当前局点不存在")
        return value

    def _repository(self, site_id: str) -> AcRepository:
        site_id = self._site(site_id)
        return AcRepository(Database(self.paths.site_db_path(site_id)))

    def _validated_ap_ids(self, site_id: str, ac_id: str, ap_ids: list[str]) -> list[str]:
        selected = list(dict.fromkeys(str(value or "").strip() for value in ap_ids if str(value or "").strip()))
        if not selected:
            return []
        repository = self._repository(site_id)
        if any(repository.get_fit_ap_resource_by_uuid(ac_id, ap_id) is None for ap_id in selected):
            raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "OmniPeek 导出目标 FIT-AP 不属于当前 AC")
        return selected

    def _require_desktop_runtime(self) -> None:
        service = self.desktop_action_service
        if service is None or service.runtime_mode is not RuntimeMode.DESKTOP:
            raise AcWebActionError("DESKTOP_REQUIRED", "仅桌面版支持打开外部终端")

    def _action(self, action_id: str) -> tuple[str, tuple[str, ...]]:
        try:
            return ACTION_DEFINITIONS[action_id]
        except KeyError as exc:
            raise AcWebActionError("ACTION_NOT_ALLOWED", "AC 动作不在固定白名单") from exc

    def _target(self, site_id: str, target_id: str):
        target_id = str(target_id or "").strip()
        if not target_id:
            raise AcWebActionError("TARGET_REQUIRED", "AC 动作缺少目标")
        device = DeviceRepository(Database(self.paths.site_db_path(self._site(site_id)))).get_by_uuid(target_id)
        if device is None or str(device.device_type or "").upper() != "AC":
            raise AcWebActionError("TARGET_NOT_AUTHORIZED", "目标 AC 在当前局点不存在")
        return device

    def _revalidate_target(self, plan: dict[str, object]) -> None:
        current = self._target(str(plan["site_id"]), str(plan["target_id"]))
        if self._fingerprint(current) != plan.get("target_fingerprint"):
            raise AcWebActionError("TARGET_STALE", "目标 AC 已变化，请重新创建动作计划")

    def _refresh_plan_status(self, site_id: str, plan: dict[str, object]):
        task_id = str(plan.get("task_id") or "")
        if not task_id:
            return None
        snapshot = self.task_service.repository(site_id).get(task_id)
        if snapshot is None or not self._authorized_task(snapshot):
            return None
        status = {
            TaskState.COMPLETED: "COMPLETED",
            TaskState.FAILED: "FAILED",
            TaskState.CANCELLED: "CANCELLED",
        }.get(snapshot.status, "EXECUTING")
        if plan.get("status") != status:
            plan["status"] = status
            self._save_plan(plan)
        return snapshot

    def _plan_data(self, plan_id: str, site_id: str) -> dict[str, object]:
        path = self._plan_path(plan_id)
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在") from exc
        if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
            raise AcWebActionError("PLAN_TAMPERED", "动作计划内容无效")
        if plan.get("site_id") != site_id:
            raise AcWebActionError("PLAN_SITE_MISMATCH", "动作计划不属于当前局点")
        return plan

    def _validate_plan(self, plan: dict[str, object], digest: str, token: str) -> None:
        if float(plan["expires_at"]) <= time.time():
            raise AcWebActionError("PLAN_EXPIRED", "动作计划已过期")
        label, commands = self._action(str(plan["action_id"]))
        if str(plan.get("action_label") or "") != label or tuple(plan.get("commands") or ()) != commands:
            raise AcWebActionError("PLAN_TAMPERED", "动作计划命令不一致")
        expected = self._digest(
            str(plan["plan_id"]),
            str(plan["site_id"]),
            str(plan["target_id"]),
            str(plan["action_id"]),
            commands,
            dict(plan.get("target_fingerprint") or {}),
        )
        if not (
            hmac.compare_digest(str(plan.get("digest") or ""), expected)
            and hmac.compare_digest(expected, str(digest or ""))
            and hmac.compare_digest(str(plan.get("token") or ""), str(token or ""))
        ):
            raise AcWebActionError("PLAN_TAMPERED", "动作计划摘要或确认令牌无效")

    def _plan_path(self, plan_id: str) -> Path:
        if not _PLAN_ID.fullmatch(str(plan_id or "")):
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在")
        root = (self.paths.runtime_cache_dir / "ac_web_action_plans").resolve()
        path = (root / f"{plan_id}.json").resolve()
        if root not in path.parents:
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在")
        return path

    def _save_plan(self, plan: dict[str, object]) -> None:
        path = self._plan_path(str(plan["plan_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def _lock(cls, key: str) -> threading.RLock:
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _fingerprint(device) -> dict[str, str]:
        return {
            "device_uuid": str(device.device_uuid or ""),
            "name": str(device.name or ""),
            "system_name": str(device.system_name or ""),
            "primary_address": str(device.primary_address or ""),
            "device_type": str(device.device_type or ""),
            "updated_at": str(device.updated_at or ""),
        }

    @staticmethod
    def _digest(
        plan_id: str,
        site_id: str,
        target_id: str,
        action_id: str,
        commands: tuple[str, ...],
        fingerprint: dict[str, str],
    ) -> str:
        value = json.dumps(
            [plan_id, site_id, target_id, action_id, list(commands), fingerprint],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _plan_dto(plan: dict[str, object]) -> AcActionPlanDTO:
        return AcActionPlanDTO(
            plan_id=str(plan["plan_id"]),
            target_id=str(plan["target_id"]),
            action_id=str(plan["action_id"]),
            action_label=str(plan["action_label"]),
            plan_digest=str(plan["digest"]),
            confirm_token=str(plan["token"]),
            expires_at=float(plan["expires_at"]),
            status=str(plan["status"]),
            command_summary=[str(value) for value in plan["commands"]],
            task_id=str(plan.get("task_id") or ""),
        )

    @staticmethod
    def _extension_dto(row: dict[str, object | None]) -> AcExtensionDTO:
        return AcExtensionDTO(
            id=int(row.get("id") or 0),
            ap_name=str(row.get("ap_name") or ""),
            ap_mac_display=str(row.get("ap_mac_display") or ""),
            ap_mac_norm=str(row.get("ap_mac_norm") or ""),
            station_name=str(row.get("station_name") or ""),
            section_name=str(row.get("section_name") or ""),
            section_start_station=str(row.get("section_start_station") or ""),
            section_end_station=str(row.get("section_end_station") or ""),
            line_side=str(row.get("line_side") or ""),
            direction=str(row.get("direction") or ""),
            mileage_text=str(row.get("mileage_text") or ""),
            location_desc=str(row.get("location_desc") or ""),
            remark=str(row.get("remark") or ""),
            match_status=str(row.get("match_status") or "unmatched"),
            updated_at=str(row.get("updated_at") or ""),
        )

    @staticmethod
    def _apply_result(data: dict[str, object]) -> AcExtensionApplyResultDTO:
        created = int(data.get("created_count") or 0)
        updated = int(data.get("updated_count") or 0)
        skipped = int(data.get("skipped_count") or 0)
        operation_id = str(data.get("operation_id") or data.get("preview_id") or "")
        return AcExtensionApplyResultDTO(
            audit_id=operation_id,
            status=str(data.get("status") or "APPLIED"),
            preview_id=str(data.get("preview_id") or operation_id),
            total_rows=created + updated + skipped,
            success_rows=created + updated,
            updated_rows=updated,
            skipped_rows=skipped,
            error_rows=0,
        )

    @staticmethod
    def _import_error(exc: Exception) -> None:
        code = getattr(exc, "code", "IMPORT_INVALID")
        raise AcWebActionError(str(code), str(exc)) from exc


__all__ = ["ACTION_DEFINITIONS", "AcWebActionError", "AcWebApplicationService"]
