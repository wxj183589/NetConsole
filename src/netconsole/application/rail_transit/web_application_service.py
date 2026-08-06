from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, NoReturn, Sequence
from uuid import uuid4

from netconsole.adapters.trackside_switch import resolve_trackside_switch_adapter
from netconsole.application.web_artifacts import ReservedWebArtifact, WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core.database import Database
from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.online_mr import (
    OnlineMrDownsampleMode,
    OnlineMrManualNoteDTO,
    OnlineMrMetricType,
    OnlineMrSwitchRssiSource,
)
from netconsole.models.api.mesh_analysis import MeshAnalysisParamsDTO, MeshArtifactDeleteResultDTO
from netconsole.models.api.rail_transit_web import (
    CarNetworkPointPreviewDTO,
    CarNetworkPointPreviewRowDTO,
    CarNetworkPointRowDTO,
    CarNetworkPointTableDTO,
    RailTransitTaskDTO,
)
from netconsole.models.api.trackside_ap_business import (
    ApManagementVlanImpactDTO,
    ApManagementVlanPreviewDTO,
    EffectiveManagementNetworkDTO,
    TracksideApBusinessExportProposalDTO,
    TracksideApPlanDTO,
    TracksideApPlanDraftDTO,
    TracksideApOnlineStatusDTO,
    TracksideApOnlineStatusRowDTO,
    TracksideApPlanPreviewDTO,
    TracksideApPlanPreviewRowDTO,
    TracksideApPlanRowDTO,
    TracksideApPointTablePreviewDTO,
    TracksideApPointTableRowDTO,
    TracksideApScopeExcludedDTO,
    TracksideApScopeExcludedPageDTO,
    TracksideApUnmatchedOnlineDTO,
    TracksideApUnmatchedOnlinePageDTO,
)
from netconsole.models.api.vehicle_mr_online import (
    VehicleMrMappingPreviewDTO,
    VehicleMrMappingPreviewRowDTO,
    VehicleMrTrainMappingDTO,
)
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.services.ac.fit_ap_optical_task_guard import fit_ap_optical_resource_keys
from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_task_builders import (
    ExportTaskSpec,
    car_network_point_table_spec,
    inline_rows_source,
    online_mr_report_xlsx_spec,
    repository_query_source,
    table_xlsx_spec,
    vehicle_mr_history_xlsx_spec,
)
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService, TaskResourceConflictError
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text, sanitize_web_export_snapshot
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.mesh_import_limits import (
    MESH_SINGLE_FILE_MAX_BYTES,
    MESH_SINGLE_FILE_MAX_LABEL,
)
from netconsole.services.mesh_analysis_params_service import (
    load_site_mesh_analysis_params,
    mesh_analysis_params_template,
    save_site_mesh_analysis_params,
)
from netconsole.models.mesh_analysis_params import normalize_mesh_analysis_params
from netconsole.services.online_mr.errors import OnlineMrQueryError
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.collection_paths import OnlineMrCollectionPaths
from netconsole.services.online_mr.session_lifecycle import online_mr_session_resource_key
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    TracksideApScopeContext,
    resolve_effective_trackside_ap_scope,
    resolve_effective_trackside_ap_scope_from_database,
)
from netconsole.services.rail_transit.car_network_diagnostic import (
    DEFAULT_GLOBAL_CONFIG,
    CarNetworkNode,
    CarNetworkGlobalConfigStore,
    CarNetworkPointTableStore,
    apply_address_mapping,
    apply_global_rules_to_nodes,
    merge_global_config,
    node_from_mapping,
    normalize_train_network_defaults,
    read_point_table_file,
)
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryError, MeshAnalysisQueryService
from netconsole.services.rail_transit.train_communication_point_table_service import (
    POINT_TABLE_INVALID,
    POINT_TABLE_MISSING,
    TrainCommunicationPointTableService,
)
from netconsole.services.rail_transit.train_identity import (
    canonical_train_id_for,
    normalize_train_identity,
    train_identity_matches,
)
from netconsole.services.rail_transit.vehicle_mr_online_query_service import VehicleMrOnlineQueryService
from netconsole.services.trackside_ap_plan_io import (
    TRACKSIDE_PLAN_COLUMNS,
    TRACKSIDE_PLAN_COLUMN_WIDTHS,
    TRACKSIDE_PLAN_FIELD_NOTE_COLUMNS,
    TRACKSIDE_PLAN_FIELD_NOTES,
    TRACKSIDE_PLAN_HEADERS,
    TRACKSIDE_PLAN_SHEET,
    bind_trackside_plan_station,
    normalize_trackside_plan_row,
    normalize_trackside_plan_rows,
    read_trackside_plan_file,
)
from netconsole.services.rail_transit.ap_management_vlan_planning import (
    REALLOCATION_ONLY_UNLOCKED,
    auto_group_draft,
    build_point_table_rows,
    effective_network,
    enrich_plan,
    plan_impact,
    project_legacy_station_rows,
)
from netconsole.services.trackside_ap_export_service import (
    build_trackside_ap_business_export_snapshot,
    build_trackside_ap_business_export_name,
)
from netconsole.services.rail_transit.trackside_ap_business_snapshot import (
    TracksideApBusinessSnapshotError,
    cleanup_export_snapshot,
    write_export_snapshot,
)
from netconsole.services.trackside_ap_base_export import (
    build_trackside_ap_base_export_name,
)
from netconsole.services.trackside_ap_rename_export import (
    build_trackside_ap_rename_export_name,
)
from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore
from netconsole.services.rail_transit.vehicle_mr_mapping_io import (
    VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS,
    VEHICLE_MR_MAPPING_TEMPLATE_ROWS,
    normalize_vehicle_mr_mapping_row,
    read_vehicle_mr_mapping_file,
)


class RailTransitWebError(ValueError):
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


class RailTransitWebApplicationService:
    """轨交 Web 用例边界；任务、导出和 Artifact 都复用正式生命周期。"""

    _TASK_NAMES = {
        "mesh_log_import": "MESH 原始日志导入分析",
        "mesh_bundle_import": "MESH ZIP 批量导入分析",
        "mesh_schema_rebuild": "MESH 派生数据库重建",
        "mesh_source_rebuild": "MESH 当前来源恢复与重新解析",
        "mesh_analysis_source_delete": "删除 MESH 来源及解析结果",
        "car_network_diagnostic": "车内通信检测",
        "car_network_generate_point_table": "从设备管理生成车内通信点表",
        "car_network_save_point_table": "保存车内通信点表",
        "trackside_ap_optical_update": "轨旁 AP 光衰更新",
        "switch_vendor_sample_collect": "交换机厂商适配采样",
        "trackside_ap_plan_save": "保存轨旁 AP 规划",
        "vehicle_mr_online_refresh_all": "列车在线状态刷新",
        "vehicle_mr_ap_mapping_refresh": "轨旁 AP 映射刷新",
        "vehicle_mr_mapping_save": "列车 MR 映射保存",
        "vehicle_mr_online_collection_start": "列车在线连续采集",
        "online_mr_parse": "Online MR 会话解析",
        "online_mr_session_delete": "删除 Online MR 历史会话",
    }
    _UPLOAD_SUFFIXES = (".log", ".txt", ".log.gz", ".txt.gz")
    _TABLE_SUFFIXES = {".xlsx", ".csv"}
    _SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")
    _ALLOWED_TASK_TYPES = {
        *_TASK_NAMES,
        "web_export_online_mr_report_xlsx",
        "web_export_mesh_analysis_report",
        "web_export_mesh_link_detail_export",
        "web_export_car_network_point_table",
        "web_export_trackside_ap_business",
        "web_export_trackside_ap_base_xlsx",
        "web_export_trackside_ap_rename_commands",
        "web_export_multi_sheet_xlsx",
        "web_export_table_xlsx",
        "web_export_vehicle_mr_history_xlsx",
    }
    _OWNER = "web_rail_transit"
    _ARTIFACT_TASK_TYPES = {
        "online_mr_report": "web_export_online_mr_report_xlsx",
        "mesh_analysis_report": "web_export_mesh_analysis_report",
        "mesh_link_detail_export": "web_export_mesh_link_detail_export",
        "car_network_point_table": "web_export_car_network_point_table",
        "trackside_ap_business": "web_export_trackside_ap_business",
        "trackside_ap_base": "web_export_trackside_ap_base_xlsx",
        "trackside_ap_rename_commands": "web_export_trackside_ap_rename_commands",
        "trackside_ap_plan": "web_export_multi_sheet_xlsx",
        "vehicle_mr_history": "web_export_vehicle_mr_history_xlsx",
        "vehicle_mr_mapping_template": "web_export_table_xlsx",
        "switch_vendor_sample": "switch_vendor_sample_collect",
    }
    _ACTIONS = {
        "web_export_online_mr_report_xlsx": "online_mr_report",
        "web_export_mesh_analysis_report": "mesh_analysis_report",
        "web_export_mesh_link_detail_export": "mesh_link_detail_export",
        "web_export_car_network_point_table": "car_network_point_table_export",
        "web_export_trackside_ap_business": "trackside_ap_business_export",
        "web_export_trackside_ap_base_xlsx": "trackside_ap_base_export",
        "web_export_trackside_ap_rename_commands": "trackside_ap_rename_command_export",
        "web_export_multi_sheet_xlsx": "trackside_ap_plan_export",
        "web_export_table_xlsx": "trackside_ap_plan_export",
        "web_export_vehicle_mr_history_xlsx": "vehicle_mr_history_export",
        "switch_vendor_sample_collect": "switch_vendor_sample_collect",
    }
    _ARTIFACT_ACTIONS = {
        "online_mr_report": "online_mr_report",
        "mesh_analysis_report": "mesh_analysis_report",
        "mesh_link_detail_export": "mesh_link_detail_export",
        "car_network_point_table": "car_network_point_table_export",
        "trackside_ap_business": "trackside_ap_business_export",
        "trackside_ap_base": "trackside_ap_base_export",
        "trackside_ap_rename_commands": "trackside_ap_rename_command_export",
        "trackside_ap_plan": "trackside_ap_plan_export",
        "vehicle_mr_history": "vehicle_mr_history_export",
        "vehicle_mr_mapping_template": "vehicle_mr_mapping_template_export",
        "switch_vendor_sample": "switch_vendor_sample_collect",
    }
    _NOTE_LOCK = threading.RLock()

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter,
        export_adapter: WebExportProcessAdapter,
        query_service: OnlineMrQueryService | None = None,
        mesh_query_service: MeshAnalysisQueryService | None = None,
        vehicle_mr_online_query_service: VehicleMrOnlineQueryService | None = None,
        artifact_store: WebArtifactStore | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.export_adapter = export_adapter
        self.query_service = query_service or OnlineMrQueryService(paths)
        self.mesh_query_service = mesh_query_service or MeshAnalysisQueryService(paths)
        self.vehicle_mr_online_query_service = vehicle_mr_online_query_service or VehicleMrOnlineQueryService(paths)
        self.artifact_store = artifact_store or WebArtifactStore(paths, task_service)
        self._trackside_online_cache: dict[
            str,
            tuple[str, TracksideApOnlineStatusDTO],
        ] = {}
        self._trackside_online_cache_lock = threading.RLock()

    def create_mesh_staging(self, site_id: str) -> Path:
        site_id = self._site(site_id)
        root = (self.paths.runtime_cache_dir / "rail_web_uploads" / site_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        staging = (root / uuid4().hex).resolve()
        if root not in staging.parents:
            raise RailTransitWebError("STAGING_INVALID", "MESH 临时目录无效")
        staging.mkdir(parents=False, exist_ok=False)
        return staging

    def stage_mesh_uploads(
        self,
        site_id: str,
        uploads: list[tuple[str, BinaryIO]],
    ) -> tuple[Path, list[Path]]:
        """在线程中完成受控 MESH 上传落盘和大小校验。"""

        site_id = self._site(site_id)
        if not uploads:
            raise RailTransitWebError("FILE_REQUIRED", "至少选择一个 MESH 原始日志文件")
        staging = self.create_mesh_staging(site_id)
        staged: list[Path] = []
        total_size = 0
        try:
            for index, (file_name, source) in enumerate(uploads, 1):
                upload_name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()
                if not upload_name.endswith(self._UPLOAD_SUFFIXES):
                    raise RailTransitWebError("FILE_TYPE_INVALID", "MESH 导入仅支持 LOG/TXT/GZ 文件")
                suffix = next((item for item in self._UPLOAD_SUFFIXES if upload_name.endswith(item)), Path(upload_name).suffix)
                target = staging / f"{index:03d}-{uuid4().hex}{suffix}"
                file_size = 0
                with target.open("xb") as handle:
                    while chunk := source.read(1024 * 1024):
                        file_size += len(chunk)
                        total_size += len(chunk)
                        if file_size > MESH_SINGLE_FILE_MAX_BYTES:
                            raise RailTransitWebError(
                                "FILE_TOO_LARGE",
                                f"单个 MESH 日志不得超过 {MESH_SINGLE_FILE_MAX_LABEL}",
                            )
                        if total_size > 100 * 1024 * 1024:
                            raise RailTransitWebError("FILES_TOO_LARGE", "MESH 导入文件总大小不得超过 100 MiB")
                        handle.write(chunk)
                staged.append(target)
            return staging, staged
        except Exception:
            self._cleanup_staging(site_id, staging)
            raise

    def discard_mesh_staging(self, site_id: str, staging_dir: Path) -> None:
        self._cleanup_staging(self._site(site_id), staging_dir)

    def start_mesh_import(
        self,
        site_id: str,
        *,
        mr_id: str,
        staging_dir: Path,
        uploads: list[Path],
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        try:
            staged = self._validated_staged_files(site_id, staging_dir, uploads)
            selected_mr_id = str(mr_id or "").strip()
            profile = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id)).get_profile(selected_mr_id)
            if profile is None:
                raise RailTransitWebError("PROFILE_NOT_FOUND", "MESH MR profile 不存在，请先创建或刷新基础资料")
            safe_folder = str(profile.safe_folder_name or "").strip()
            if not safe_folder or safe_folder in {".", ".."} or Path(safe_folder).name != safe_folder:
                raise RailTransitWebError("PROFILE_INVALID", "MESH MR 目录名无效")
            self._require_within(
                self.paths.mesh_mr_root(site_id, safe_folder).resolve(),
                self.paths.site_mesh_root(site_id).resolve(),
            )
            profile_payload = {
                "mr_id": profile.mr_id,
                "display_name": profile.display_name,
                "safe_folder_name": safe_folder,
                "relative_folder_path": f"files/rail_transit/mr_raw_mesh/{safe_folder}",
                "linked_device_id": profile.linked_device_id,
                "notes": profile.notes,
            }
            return self._start_task(
                site_id,
                "mesh_log_import",
                {"profile": profile_payload, "files": [str(path) for path in staged]},
                on_complete=lambda _value: self._cleanup_staging(site_id, staging_dir),
            )
        except Exception:
            self._cleanup_staging(site_id, staging_dir)
            raise

    def create_mesh_profile(
        self,
        site_id: str,
        *,
        display_name: str,
        linked_mr_id: str = "",
        notes: str = "",
    ):
        site_id = self._site(site_id)
        name = str(display_name or "").strip()
        if not name:
            raise RailTransitWebError("PROFILE_REQUIRED", "请输入 MESH MR 名称")
        linked_device_id = None
        linked_device_uuid = None
        selected_mr_id = str(linked_mr_id or "").strip()
        storage = MeshStorageService(site_id, self.paths)
        if selected_mr_id:
            detail = RailTransitBaseDataQueryService(self.paths).get_mr(site_id, selected_mr_id)
            if detail is None or detail.mr.device_id is None:
                raise RailTransitWebError("PROFILE_DEVICE_NOT_FOUND", "所选基础资料 MR 不存在或未绑定设备")
            linked_device_id = int(detail.mr.device_id)
            linked_device_uuid = detail.mr.id
            existing = (
                storage.catalog.get_by_linked_device_uuid(linked_device_uuid)
                or storage.catalog.get_by_linked_device_id(linked_device_id)
            )
            if existing is not None:
                raise RailTransitWebError(
                    "PROFILE_ALREADY_LINKED",
                    "所选基础资料 MR 已存在内部 MESH 归属",
                    details={
                        "profile_id": existing.mr_id,
                        "display_name": existing.display_name,
                    },
                )
        try:
            return storage.create_mr_profile(
                name,
                notes=str(notes or "").strip(),
                linked_device_id=linked_device_id,
                linked_device_uuid=linked_device_uuid,
            )
        except ValueError as exc:
            raise RailTransitWebError("PROFILE_CONFLICT", str(exc)) from exc

    def get_car_network_point_table(self, site_id: str) -> CarNetworkPointTableDTO:
        site_id = self._site(site_id)
        config = merge_global_config(CarNetworkGlobalConfigStore(self.paths, site_id).load())
        return CarNetworkPointTableDTO(
            rows=[self._point_row(node) for node in CarNetworkPointTableStore(self.paths, site_id).load()],
            global_config=config,
            locked=bool(config.get("point_table_locked", False)),
            revision=TrainCommunicationPointTableService(self.paths).revision(site_id),
        )

    def preview_car_network_point_table(
        self,
        site_id: str,
        *,
        file_name: str,
        content: bytes,
        duplicate_strategy: str,
    ) -> CarNetworkPointPreviewDTO:
        site_id = self._site(site_id)
        strategy = self._duplicate_strategy(duplicate_strategy)
        raw_rows = self._read_table_upload(site_id, file_name, content, read_point_table_file)
        existing = CarNetworkPointTableStore(self.paths, site_id).load()
        merged = {self._point_key(node): node for node in existing}
        imported: set[tuple[str, str]] = set()
        preview_rows: list[CarNetworkPointPreviewRowDTO] = []
        duplicate_count = 0
        error_count = 0
        valid_count = 0
        for row_number, raw in enumerate(raw_rows, start=2):
            try:
                node = node_from_mapping(raw)
                self._validate_point_node(node, row_number)
            except (TypeError, ValueError) as exc:
                error_count += 1
                preview_rows.append(
                    CarNetworkPointPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        message=str(exc),
                    )
                )
                continue
            key = self._point_key(node)
            duplicate = key in merged or key in imported
            if duplicate:
                duplicate_count += 1
                preview_rows.append(
                    CarNetworkPointPreviewRowDTO(
                        row_number=row_number,
                        status="duplicate",
                        key=" / ".join(key),
                        message={
                            "replace": "重复节点将由导入行覆盖",
                            "skip": "重复节点将保留现有值",
                            "error": "重复节点阻止确认导入",
                        }[strategy],
                        row=self._point_row(node),
                    )
                )
                if strategy == "replace":
                    merged[key] = node
                imported.add(key)
                continue
            valid_count += 1
            imported.add(key)
            merged[key] = node
            preview_rows.append(
                CarNetworkPointPreviewRowDTO(
                    row_number=row_number,
                    status="valid",
                    key=" / ".join(key),
                    row=self._point_row(node),
                )
            )
        can_apply = error_count == 0 and (strategy != "error" or duplicate_count == 0)
        return CarNetworkPointPreviewDTO(
            file_name=Path(file_name).name,
            file_sha256=hashlib.sha256(content).hexdigest(),
            duplicate_strategy=strategy,
            can_apply=can_apply,
            total_count=len(raw_rows),
            valid_count=valid_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            rows=preview_rows,
            result_rows=[self._point_row(node) for node in merged.values()] if can_apply else [],
        )

    def transform_car_network_point_table(
        self,
        site_id: str,
        *,
        operation: str,
        rows: list[dict[str, object]],
        global_config: dict[str, object],
    ) -> CarNetworkPointTableDTO:
        self._site(site_id)
        config = merge_global_config(global_config)
        nodes = self._point_nodes(rows)
        if bool(config.get("point_table_locked", False)):
            raise RailTransitWebError("POINT_TABLE_LOCKED", "当前点表已锁定，请先解锁")
        if operation == "apply_mapping":
            nodes = [
                apply_address_mapping(node, config, overwrite=node.address_mapping_mode == "global")
                for node in nodes
            ]
            nodes = normalize_train_network_defaults(nodes, config, overwrite_custom=False)
        elif operation == "apply_global":
            nodes = apply_global_rules_to_nodes(nodes, config, overwrite_custom=False)
        elif operation == "apply_global_override":
            nodes = apply_global_rules_to_nodes(nodes, config, overwrite_custom=True)
        elif operation == "restore_defaults":
            config = merge_global_config(DEFAULT_GLOBAL_CONFIG)
        else:
            raise RailTransitWebError("POINT_TABLE_OPERATION_INVALID", "不支持的点表转换操作")
        return CarNetworkPointTableDTO(
            rows=[self._point_row(node) for node in nodes],
            global_config=config,
            locked=False,
        )

    def start_car_network_point_table_save(
        self,
        site_id: str,
        *,
        rows: list[dict[str, object]],
        global_config: dict[str, object],
        overwrite_custom: bool,
        explicit_confirmation: bool,
        audit: dict[str, str] | None = None,
        revision: str = "",
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise RailTransitWebError("CONFIRMATION_REQUIRED", "保存点表前必须明确确认")
        nodes = self._point_nodes(rows)
        config = merge_global_config(global_config)
        current = self.get_car_network_point_table(site_id)
        expected_revision = str(revision or "").strip()
        if expected_revision and expected_revision != current.revision:
            raise RailTransitWebError("TRAIN_COMMUNICATION_REVISION_CONFLICT", "点表已被其他操作修改，请重新加载")
        if current.locked and bool(config.get("point_table_locked", False)):
            if [row.model_dump() for row in current.rows] != [self._point_row(node).model_dump() for node in nodes]:
                raise RailTransitWebError("POINT_TABLE_LOCKED", "当前点表已锁定，不能修改行数据")
        return self._start_task(
            site_id,
            "car_network_save_point_table",
            {
                "nodes": [asdict(node) for node in nodes],
                "global_config": config,
                "overwrite_custom": bool(overwrite_custom),
                "audit": {str(key): str(value) for key, value in (audit or {}).items()},
                "explicit_confirmation": True,
                "revision": current.revision,
            },
        )

    def start_car_network_point_table_generate(
        self,
        site_id: str,
        *,
        rows: list[dict[str, object]],
        global_config: dict[str, object],
        target_train: dict[str, object] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        config = merge_global_config(global_config)
        if bool(config.get("point_table_locked", False)):
            raise RailTransitWebError("POINT_TABLE_LOCKED", "当前点表已锁定，请先解锁")
        return self._start_task(
            site_id,
            "car_network_generate_point_table",
            {
                "nodes": [asdict(node) for node in self._point_nodes(rows)],
                "global_config": config,
                "save_result": False,
                "target_train": self._target_train_payload(target_train or {}),
            },
        )

    def start_car_network_point_table_export(self, site_id: str, *, file_format: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        suffix = ".csv" if file_format == "csv" else ".xlsx"
        task_id = f"rail-export-{uuid4().hex}"
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="car_network_point_table",
                artifact_type=suffix.removeprefix("."),
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["car_network_point_table"],
                output_root=self.paths.car_network_diagnostic_parsed_dir(site_id) / "exports",
                preferred_name=f"车内通信点表{suffix}",
            )
        except WebArtifactError as exc:
            self._task_window_blocked("车内通信点表导出", exc)
        job = car_network_point_table_spec(
            reservation.output_path,
            site_name=site_id,
            title="导出车内通信点表",
            open_dir_on_success=False,
        ).to_job(task_id)
        return self._start_export(site_id, replace(job, site_name=site_id), "car_network_point_table_export", reservation)

    def open_car_network_point_table_export(
        self,
        site_id: str,
        artifact_id: str,
        *,
        file_format: str,
    ) -> tuple[Path, str]:
        artifact_type = "csv" if file_format == "csv" else "xlsx"
        return self._open_artifact(site_id, artifact_id, "car_network_point_table", artifact_type)

    def get_trackside_ap_business_export_proposal(
        self,
        site_id: str,
    ) -> TracksideApBusinessExportProposalDTO:
        site_id = self._site(site_id)
        generated_at = datetime.now().astimezone()
        site_display_name = self._site_display_name(site_id)
        try:
            suggested_name = build_trackside_ap_business_export_name(
                site_display_name,
                generated_at,
            )
        except ValueError as exc:
            raise RailTransitWebError("SITE_DISPLAY_NAME_INVALID", str(exc)) from exc
        return TracksideApBusinessExportProposalDTO(
            site_id=site_id,
            site_display_name=site_display_name,
            generated_at=generated_at.isoformat(timespec="seconds"),
            suggested_name=suggested_name,
        )

    def start_trackside_ap_business_export(
        self,
        site_id: str,
        *,
        generated_at: str = "",
        suggested_name: str = "",
        expected_revision: str = "",
        station: str = "",
        query: str = "",
        optical_anomaly_only: bool = False,
        selected_row_ids: Sequence[str] = (),
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        site_display_name = self._site_display_name(site_id)
        if generated_at:
            try:
                created_at = datetime.fromisoformat(generated_at)
            except ValueError as exc:
                raise RailTransitWebError(
                    "TRACKSIDE_AP_EXPORT_PROPOSAL_INVALID",
                    "轨旁 AP 业务导出时间无效，请重新打开保存对话框",
                ) from exc
        else:
            created_at = datetime.now().astimezone()
        try:
            preferred_name = build_trackside_ap_business_export_name(
                site_display_name,
                created_at,
            )
        except ValueError as exc:
            raise RailTransitWebError("SITE_DISPLAY_NAME_INVALID", str(exc)) from exc
        if suggested_name and suggested_name != preferred_name:
            raise RailTransitWebError(
                "TRACKSIDE_AP_EXPORT_NAME_MISMATCH",
                "导出文件名契约已变化，请重新打开保存对话框",
            )
        site_metadata = SiteManager(self.paths).load_site_metadata(site_id)
        scope_context = {
            **{
                key: site_metadata[key]
                for key in (
                    "project_id",
                    "line_name",
                    "construction_phase_id",
                    "project_phase_id",
                    "project_phase",
                    "display_name",
                )
                if key in site_metadata
            },
            "site_id": site_id,
            "site_display_name": site_display_name,
            "generated_at": created_at.isoformat(timespec="seconds"),
        }
        snapshot_payload = build_trackside_ap_business_export_snapshot(
            DeviceRepository(Database(self.paths.site_db_path(site_id))),
            site_id,
            scope_context=scope_context,
            station=station,
            query=query,
            optical_anomaly_only=optical_anomaly_only,
            selected_row_ids=selected_row_ids,
        )
        current_revision = str(snapshot_payload.get("business_revision") or "")
        if expected_revision and expected_revision != current_revision:
            raise TracksideApBusinessSnapshotError(
                "TRACKSIDE_AP_SNAPSHOT_STALE",
                "轨旁 AP 数据已更新，请刷新后重新导出。",
            )
        task_id = f"rail-export-{uuid4().hex}"
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="trackside_ap_business",
                artifact_type="xlsx",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["trackside_ap_business"],
                output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_business",
                preferred_name=preferred_name,
                use_display_name_as_file_name=True,
            )
        except WebArtifactError as exc:
            self._task_window_blocked("轨旁 AP 业务导出", exc)
        try:
            snapshot_path, snapshot_sha256 = write_export_snapshot(
                self.paths.staging_dir,
                site_id=site_id,
                task_id=task_id,
                payload=snapshot_payload,
            )
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        job = ExportJob(
            job_id=task_id,
            job_type="trackside_ap_business",
            site_name=site_id,
            output_path=str(reservation.output_path),
            params={
                "language": "zh_CN",
                "snapshot_path": str(snapshot_path),
                "snapshot_sha256": snapshot_sha256,
            },
        )
        try:
            return self._start_export(
                site_id,
                job,
                "trackside_ap_business_export",
                reservation,
                cleanup_paths=[snapshot_path],
            )
        except Exception:
            self._cleanup_staging_paths([snapshot_path])
            raise

    def open_trackside_ap_business_export(
        self,
        site_id: str,
        artifact_id: str,
    ) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "trackside_ap_business")

    def start_switch_vendor_sample(
        self,
        site_id: str,
        *,
        device_uuid: str,
        vendor: str,
        command_profile: str,
        selected_interface: str = "",
        requested_commands: list[str] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        selected_device_uuid = str(device_uuid or "").strip()
        device = DeviceRepository(
            Database(self.paths.site_db_path(site_id))
        ).get_by_uuid(selected_device_uuid)
        if device is None or str(device.device_type or "") != "SW":
            raise RailTransitWebError(
                "SWITCH_DEVICE_NOT_FOUND",
                "厂商适配采样设备不存在或不是交换机",
            )
        try:
            adapter = resolve_trackside_switch_adapter(device)
        except ValueError as exc:
            raise RailTransitWebError(
                "SWITCH_VENDOR_NOT_SUPPORTED",
                "当前交换机厂商没有轨旁 AP Adapter",
            ) from exc
        if adapter.vendor.casefold() != "zte":
            raise RailTransitWebError(
                "SWITCH_SAMPLE_VENDOR_UNSUPPORTED",
                "第一阶段仅支持 ZTE 交换机厂商适配采样",
            )
        if str(vendor or "").strip().casefold() != adapter.vendor.casefold():
            raise RailTransitWebError(
                "SWITCH_VENDOR_MISMATCH",
                "采样厂商与所选设备 Adapter 不一致",
            )
        if str(command_profile or "").strip() != adapter.profile_id:
            raise RailTransitWebError(
                "SWITCH_PROFILE_MISMATCH",
                "采样命令 Profile 与所选设备 Adapter 不一致",
            )
        commands = list(
            dict.fromkeys(
                str(value or "").strip()
                for value in (requested_commands or [])
                if str(value or "").strip()
            )
        )
        try:
            plan = adapter.build_command_plan(
                selected_interface=selected_interface,
                requested_commands=commands,
            )
        except ValueError as exc:
            raise RailTransitWebError(
                "SWITCH_SAMPLE_COMMAND_INVALID",
                str(exc),
            ) from exc
        if not plan.items:
            raise RailTransitWebError(
                "SWITCH_SAMPLE_COMMAND_REQUIRED",
                "当前采样范围没有可执行的只读命令",
            )
        task_id = f"rail-web-{uuid4().hex}"
        safe_device_name = (
            self._SAFE_NAME.sub("-", str(device.name or "")).strip(".-_")
            or selected_device_uuid[:8]
            or "device"
        )
        preferred_name = (
            f"{adapter.vendor.casefold()}-adapter-sample-{safe_device_name}-"
            f"{datetime.now():%Y%m%d_%H%M%S}.zip"
        )
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="switch_vendor_sample",
                artifact_type="zip",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["switch_vendor_sample"],
                output_root=self.paths.trackside_ap_outputs_dir(site_id)
                / "vendor_samples",
                preferred_name=preferred_name,
                use_display_name_as_file_name=True,
                context={
                    "kind": "switch_vendor_sample",
                    "device_uuid": selected_device_uuid,
                    "vendor": adapter.vendor,
                    "command_profile": adapter.profile_id,
                },
            )
        except WebArtifactError as exc:
            self._task_window_blocked("交换机厂商适配采样", exc)
        return self._start_artifact_task(
            site_id,
            "switch_vendor_sample_collect",
            {
                "device_uuid": selected_device_uuid,
                "vendor": adapter.vendor,
                "command_profile": adapter.profile_id,
                "selected_interface": plan.selected_interface,
                "requested_commands": commands,
                "artifact_output_path": str(reservation.output_path),
                "resource_keys": [
                    f"site:{site_id}|device:{selected_device_uuid}|switch_vendor_sample"
                ],
                "resource_conflict_message": "该交换机已有厂商适配采样任务正在执行。",
            },
            reservation,
            task_id=task_id,
        )

    def open_switch_vendor_sample(
        self,
        site_id: str,
        artifact_id: str,
    ) -> tuple[Path, str]:
        return self._open_artifact(
            site_id,
            artifact_id,
            "switch_vendor_sample",
            "zip",
        )

    def start_trackside_ap_base_export(
        self,
        site_id: str,
        *,
        template: bool,
        rows: list[dict[str, object]] | None = None,
        issues: list[dict[str, object]] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        task_id = f"rail-export-{uuid4().hex}"
        if issues is not None:
            try:
                preferred_name = build_trackside_ap_base_export_name(
                    self._site_display_name(site_id),
                    datetime.now(),
                ).replace("_轨旁AP基础资料_", "_轨旁AP导入问题明细_")
            except ValueError as exc:
                raise RailTransitWebError("SITE_DISPLAY_NAME_INVALID", str(exc)) from exc
        elif template:
            preferred_name = "轨旁AP基础资料模板.xlsx"
        else:
            try:
                preferred_name = build_trackside_ap_base_export_name(
                    self._site_display_name(site_id), datetime.now()
                )
            except ValueError as exc:
                raise RailTransitWebError("SITE_DISPLAY_NAME_INVALID", str(exc)) from exc
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="trackside_ap_base",
                artifact_type="xlsx",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["trackside_ap_base"],
                output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_base",
                preferred_name=preferred_name,
                use_display_name_as_file_name=not template,
            )
        except WebArtifactError as exc:
            self._task_window_blocked("轨旁 AP 基础资料导出", exc)
        payload: dict[str, object] = {
            "source_module": "rail.trackside_ap_base",
            "site_id": site_id,
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "template": template,
        }
        if rows is not None:
            payload["draft_rows"] = rows
        if issues is not None:
            payload["issue_rows"] = issues
        job = replace(
            ExportTaskSpec(
                task_type="trackside_ap_base_xlsx",
                output_path=str(reservation.output_path),
                payload=payload,
                site_name=site_id,
            )
            .to_job(task_id)
            .with_runtime_paths(
                tmp_path=str(
                    reservation.output_path.with_name(
                        f"{reservation.output_path.name}.{task_id}.tmp"
                    )
                ),
                cancel_path=str(
                    self.paths.runtime_cache_dir / "export_jobs" / f"{task_id}.cancel"
                ),
            ),
            site_name=site_id,
        )
        return self._start_export(
            site_id,
            job,
            "trackside_ap_base_export",
            reservation,
        )

    def open_trackside_ap_base_export(
        self,
        site_id: str,
        artifact_id: str,
    ) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "trackside_ap_base")

    def start_trackside_ap_rename_command_export(
        self,
        site_id: str,
        *,
        rows: list[dict[str, object]] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        task_id = f"rail-export-{uuid4().hex}"
        now = datetime.now()
        site_display_name = self._site_display_name(site_id)
        try:
            preferred_name = build_trackside_ap_rename_export_name(site_display_name, now)
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="trackside_ap_rename_commands",
                artifact_type="txt",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["trackside_ap_rename_commands"],
                output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_rename_commands",
                preferred_name=preferred_name,
                use_display_name_as_file_name=True,
            )
        except ValueError as exc:
            raise RailTransitWebError("SITE_DISPLAY_NAME_INVALID", str(exc)) from exc
        except WebArtifactError as exc:
            self._task_window_blocked("轨旁 AP 重命名命令导出", exc)
        payload: dict[str, object] = {
            "source_module": "rail.trackside_ap_rename_commands",
            "site_id": site_id,
            "site_display_name": site_display_name,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
        }
        if rows is not None:
            payload["draft_rows"] = rows
        job = replace(
            ExportTaskSpec(
                task_type="trackside_ap_rename_commands",
                output_path=str(reservation.output_path),
                payload=payload,
                site_name=site_id,
            ).to_job(task_id).with_runtime_paths(
                tmp_path=str(reservation.output_path.with_name(f"{reservation.output_path.name}.{task_id}.tmp")),
                cancel_path=str(self.paths.runtime_cache_dir / "export_jobs" / f"{task_id}.cancel"),
            ),
            site_name=site_id,
        )
        return self._start_export(site_id, job, "trackside_ap_rename_command_export", reservation)

    def open_trackside_ap_rename_command_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "trackside_ap_rename_commands", "txt")

    def get_trackside_ap_plan(
        self,
        site_id: str,
        *,
        request_id: str = "",
    ) -> TracksideApPlanDTO:
        site_id = self._site(site_id)
        stations, aps = self._trackside_vlan_context(site_id)
        app_logger.log_info(
            "trackside_ap_plan.context_loaded",
            (
                f"request_id={request_id} site_id={site_id} "
                f"backend_pid={os.getpid()} thread_id={threading.get_ident()} "
                f"stations={len(stations)} aps={len(aps)}"
            ),
        )
        database = Database(self.paths.site_db_path(site_id))
        repository = AcRepository(database)
        repository_started = time.perf_counter()
        station_rows = repository.list_trackside_ap_plan(
            TRACKSIDE_AP_PLAN_MODE
        )
        app_logger.log_info(
            "trackside_ap_plan.repository_loaded",
            (
                f"request_id={request_id} site_id={site_id} "
                f"backend_pid={os.getpid()} thread_id={threading.get_ident()} "
                f"database_path={database.path} rows={len(station_rows)} "
                f"sql_ms={(time.perf_counter() - repository_started) * 1000:.2f}"
            ),
        )
        source_rows: list[Mapping[str, object]] = []
        for index, row in enumerate(station_rows, start=2):
            try:
                source_rows.append(
                    normalize_trackside_plan_row(
                        dict(row),
                        row_number=index,
                    )
                )
            except ValueError:
                source_rows.append(row)
        result = self._trackside_plan_dto(
            {}, source_rows=source_rows, stations=stations
        )
        result.model_dump(mode="json")
        app_logger.log_info(
            "trackside_ap_plan.dto_validated",
            (
                f"request_id={request_id} site_id={site_id} "
                f"backend_pid={os.getpid()} thread_id={threading.get_ident()} "
                f"rows={len(result.items)}"
            ),
        )
        return result

    def get_trackside_ap_online_status(
        self,
        site_id: str,
        *,
        _snapshot_attempt: int = 0,
    ) -> TracksideApOnlineStatusDTO:
        started = time.perf_counter()
        site_id = self._site(site_id)
        database = Database(self.paths.site_db_path(site_id))
        repository = AcRepository(database)
        revision, source_revision = self._trackside_online_revision(
            site_id,
            repository,
        )
        with self._trackside_online_cache_lock:
            cached = self._trackside_online_cache.get(site_id)
        if cached and cached[0] == revision:
            result = cached[1].model_copy(update={"cache_hit": True})
            total_ms = (time.perf_counter() - started) * 1000
            app_logger.log_info(
                "trackside_ap_online_status.performance",
                (
                    "planning_ms=0.0 fit_ap_ms=0.0 identity_ms=0.0 "
                    "aggregation_ms=0.0 serialization_ms=0.0 "
                    f"total_ms={total_ms:.1f} revision={revision} cache_hit=true"
                ),
            )
            return result

        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        planning_started = time.perf_counter()
        selected_plans = repository.list_trackside_ap_plan(
            TRACKSIDE_AP_PLAN_MODE
        )
        planning_ms = (time.perf_counter() - planning_started) * 1000
        identity_started = time.perf_counter()
        references = repository.list_trackside_ap_scope_reference_rows()
        runtime_station_rows = (
            repository.list_trackside_ap_runtime_station_evidence_rows()
        )
        switch_identity_rows = repository.list_trackside_switch_identity_rows()
        identity_ms = (time.perf_counter() - identity_started) * 1000
        fit_ap_started = time.perf_counter()
        resources = repository.list_fit_ap_online_scope_rows()
        fit_ap_ms = (time.perf_counter() - fit_ap_started) * 1000
        aggregation_started = time.perf_counter()
        scope = resolve_effective_trackside_ap_scope(
            context=TracksideApScopeContext.from_metadata(site_id, metadata),
            station_rows=references,
            plan_rows=selected_plans,
            reference_rows=references,
            resource_rows=resources,
            runtime_station_rows=runtime_station_rows,
            switch_identity_rows=switch_identity_rows,
            detail_limit=0,
        )
        confirmed_revision, _confirmed_source_revision = (
            self._trackside_online_revision(site_id, repository)
        )
        if confirmed_revision != revision:
            if _snapshot_attempt < 2:
                return self.get_trackside_ap_online_status(
                    site_id,
                    _snapshot_attempt=_snapshot_attempt + 1,
                )
            raise TracksideApBusinessSnapshotError(
                "TRACKSIDE_AP_SNAPSHOT_UNSTABLE",
                "轨旁 AP 数据正在刷新，暂时无法形成一致快照，请稍后重试。",
            )
        aggregation_ms = (time.perf_counter() - aggregation_started) * 1000
        serialization_started = time.perf_counter()
        result = [
            TracksideApOnlineStatusRowDTO.model_validate(row)
            for row in scope.station_statistics()
        ]
        planned_total = sum(row.planned_ap_count for row in result)
        matched_online_total = sum(row.actual_online_count for row in result)
        actual_online_total = min(matched_online_total, planned_total)
        anomaly = any(row.count_anomaly for row in result)
        warning_parts = []
        if unmatched_summary := scope.unmatched_online_summary():
            warning_parts.append(unmatched_summary)
        if scope.excluded_device_count:
            warning_parts.append(
                f"已按项目、当前工作状态、站点关联和稳定身份排除 {scope.excluded_device_count} 项。"
            )
        dto = TracksideApOnlineStatusDTO(
            items=result,
            planned_ap_count=planned_total,
            actual_online_count=actual_online_total,
            offline_count=max(planned_total - actual_online_total, 0),
            online_rate=(
                round(actual_online_total * 100 / planned_total, 1)
                if planned_total and not anomaly
                else None
            ),
            unassigned_count=scope.fit_ap_unmatched_online_count,
            unassigned_items=[],
            updated_at=scope.updated_at,
            warning=" ".join(warning_parts),
            count_anomaly=anomaly,
            status="anomaly" if anomaly else "normal",
            scope_description=scope.scope_description,
            scope_station_count=scope.scope_station_count,
            scope_device_count=scope.scope_device_count,
            scope_ap_reference_count=scope.scope_ap_reference_count,
            excluded_device_count=scope.excluded_device_count,
            excluded_items=[],
            fit_ap_resource_total_count=scope.fit_ap_resource_total_count,
            fit_ap_matched_count=scope.fit_ap_matched_count,
            fit_ap_matched_online_count=scope.fit_ap_matched_online_count,
            fit_ap_online_total_count=scope.fit_ap_online_total_count,
            fit_ap_offline_total_count=scope.fit_ap_offline_total_count,
            fit_ap_unknown_total_count=scope.fit_ap_unknown_total_count,
            fit_ap_unmatched_online_count=scope.fit_ap_unmatched_online_count,
            fit_ap_unresolved_online_count=scope.fit_ap_unmatched_online_count,
            fit_ap_lldp_snapshot_stale_count=scope.fit_ap_lldp_snapshot_stale_count,
            fit_ap_lldp_exact_match_pending_count=scope.fit_ap_lldp_exact_match_pending_count,
            fit_ap_current_conflict_count=scope.fit_ap_current_conflict_count,
            fit_ap_planning_missing_count=scope.fit_ap_planning_missing_count,
            fit_ap_ambiguous_online_count=scope.fit_ap_ambiguous_online_count,
            fit_ap_station_master_missing_count=scope.fit_ap_station_master_missing_count,
            fit_ap_unknown_association_count=scope.fit_ap_unknown_association_count,
            fit_ap_switch_not_found_count=scope.fit_ap_switch_not_found_count,
            fit_ap_switch_identity_ambiguous_count=scope.fit_ap_switch_identity_ambiguous_count,
            fit_ap_switch_data_incomplete_count=scope.fit_ap_switch_data_incomplete_count,
            fit_ap_plan_not_found_count=scope.fit_ap_plan_not_found_count,
            fit_ap_plan_station_missing_count=scope.fit_ap_plan_station_missing_count,
            fit_ap_plan_station_invalid_count=scope.fit_ap_plan_station_invalid_count,
            unmatched_online_items=[],
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            revision=revision,
            source_revision=source_revision,
            cache_hit=False,
            snapshot_status=scope.runtime_snapshot.snapshot_status,
            snapshot_age_seconds=scope.runtime_snapshot.snapshot_age_seconds,
            snapshot_warnings=list(scope.runtime_snapshot.warnings),
            fit_ap_collected_at=scope.runtime_snapshot.fit_ap_collected_at,
            switch_lldp_collected_at=scope.runtime_snapshot.switch_lldp_collected_at,
        )
        serialization_ms = (time.perf_counter() - serialization_started) * 1000
        with self._trackside_online_cache_lock:
            self._trackside_online_cache[site_id] = (revision, dto)
        total_ms = (time.perf_counter() - started) * 1000
        detail = (
            f"planning_ms={planning_ms:.1f} fit_ap_ms={fit_ap_ms:.1f} "
            f"identity_ms={identity_ms:.1f} aggregation_ms={aggregation_ms:.1f} "
            f"serialization_ms={serialization_ms:.1f} total_ms={total_ms:.1f} "
            f"revision={revision} cache_hit=false"
        )
        if total_ms > 2000:
            app_logger.log_warning("trackside_ap_online_status.performance", detail)
        else:
            app_logger.log_info("trackside_ap_online_status.performance", detail)
        return dto

    def list_trackside_ap_online_excluded(
        self,
        site_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> TracksideApScopeExcludedPageDTO:
        site_id = self._site(site_id)
        scope, revision = self._trackside_online_scope_with_details(site_id)
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        items = [
            TracksideApScopeExcludedDTO.model_validate(item.to_dict())
            for item in scope.excluded_items[start : start + size]
        ]
        return TracksideApScopeExcludedPageDTO(
            items=items,
            total=len(scope.excluded_items),
            page=current,
            page_size=size,
            revision=revision,
        )

    def list_trackside_ap_online_unmatched(
        self,
        site_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> TracksideApUnmatchedOnlinePageDTO:
        site_id = self._site(site_id)
        scope, revision = self._trackside_online_scope_with_details(site_id)
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        items = [
            TracksideApUnmatchedOnlineDTO.model_validate(item.to_dict())
            for item in scope.unmatched_online_items[start : start + size]
        ]
        return TracksideApUnmatchedOnlinePageDTO(
            items=items,
            total=len(scope.unmatched_online_items),
            page=current,
            page_size=size,
            revision=revision,
        )

    def _trackside_online_scope_with_details(
        self,
        site_id: str,
    ):
        database = Database(self.paths.site_db_path(site_id))
        repository = AcRepository(database)
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        for _attempt in range(3):
            revision, source_revision = self._trackside_online_revision(
                site_id,
                repository,
            )
            scope = resolve_effective_trackside_ap_scope_from_database(
                database,
                site_id=site_id,
                context=TracksideApScopeContext.from_metadata(site_id, metadata),
                lightweight=True,
                detail_limit=None,
            )
            confirmed_revision, _confirmed_source_revision = (
                self._trackside_online_revision(site_id, repository)
            )
            if confirmed_revision != revision:
                continue
            generated_at = datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            )
            scope.unmatched_online_items = [
                replace(
                    item,
                    source_revisions={
                        key: str(value) for key, value in source_revision.items()
                    },
                    snapshot_revision=revision,
                    snapshot_created_at=generated_at,
                )
                for item in scope.unmatched_online_items
            ]
            return scope, revision
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_UNSTABLE",
            "轨旁 AP 数据正在刷新，暂时无法形成一致快照，请稍后重试。",
        )

    def _trackside_online_revision(
        self,
        site_id: str,
        repository: AcRepository,
    ) -> tuple[str, dict[str, object]]:
        source_revision = repository.trackside_online_status_revision()
        metadata_path = self.paths.site_dir(site_id) / "site_meta.json"
        try:
            stat = metadata_path.stat()
            source_revision["site_meta_mtime_ns"] = stat.st_mtime_ns
            source_revision["site_meta_size"] = stat.st_size
        except OSError:
            source_revision["site_meta_mtime_ns"] = 0
            source_revision["site_meta_size"] = 0
        serialized = json.dumps(
            source_revision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        revision = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        return revision, source_revision

    def preview_trackside_ap_vlan_auto_group(
        self,
        site_id: str,
        *,
        planning_mode: str,
        auto_group_station_count: int,
        current: dict[str, object] | None = None,
        reallocation_policy: str = REALLOCATION_ONLY_UNLOCKED,
    ) -> ApManagementVlanPreviewDTO:
        site_id = self._site(site_id)
        stations, aps = self._trackside_vlan_context(site_id)
        persisted = self._trackside_plan_payload(self.get_trackside_ap_plan(site_id))
        proposed = auto_group_draft(
            stations=stations,
            planning_mode=planning_mode,
            auto_group_station_count=auto_group_station_count,
            current_draft=current or persisted,
        )
        view = enrich_plan(
            proposed,
            stations=stations,
            aps=aps,
            reallocation_policy=reallocation_policy,
        )
        return ApManagementVlanPreviewDTO(
            plan=self._trackside_plan_dto(view),
            impact=ApManagementVlanImpactDTO.model_validate(
                plan_impact(
                    persisted,
                    view,
                    stations=stations,
                    aps=aps,
                )
            ),
        )

    def preview_trackside_ap_vlan_change(
        self,
        site_id: str,
        *,
        proposed: dict[str, object],
        reallocation_policy: str = REALLOCATION_ONLY_UNLOCKED,
    ) -> ApManagementVlanPreviewDTO:
        site_id = self._site(site_id)
        stations, aps = self._trackside_vlan_context(site_id)
        persisted = self._trackside_plan_payload(self.get_trackside_ap_plan(site_id))
        view = enrich_plan(
            proposed,
            stations=stations,
            aps=aps,
            reallocation_policy=reallocation_policy,
        )
        return ApManagementVlanPreviewDTO(
            plan=self._trackside_plan_dto(view),
            impact=ApManagementVlanImpactDTO.model_validate(
                plan_impact(
                    persisted,
                    view,
                    stations=stations,
                    aps=aps,
                )
            ),
        )

    def get_effective_trackside_ap_management_network(
        self,
        site_id: str,
        *,
        station_id: str = "",
        ap_id: str = "",
    ) -> EffectiveManagementNetworkDTO:
        site_id = self._site(site_id)
        plan = self.get_trackside_ap_plan(site_id)
        network = effective_network(
            self._trackside_plan_payload(plan),
            stations=[
                {
                    "id": row.station_id,
                    "name": row.station_name,
                    "sort_order": row.station_sequence,
                    "ap_count": row.ap_count,
                }
                for row in plan.station_details
            ],
            station_id=station_id,
            ap_id=ap_id,
        )
        if network is None:
            raise RailTransitWebError(
                "AP_MANAGEMENT_NETWORK_UNRESOLVED",
                "未找到站点或 AP 的有效管理网络配置",
            )
        return EffectiveManagementNetworkDTO.model_validate(network)

    def preview_trackside_ap_point_table(
        self,
        site_id: str,
        *,
        proposed: dict[str, object] | None = None,
    ) -> TracksideApPointTablePreviewDTO:
        site_id = self._site(site_id)
        stations, aps = self._trackside_vlan_context(site_id)
        persisted = self._trackside_plan_payload(self.get_trackside_ap_plan(site_id))
        draft = proposed or persisted
        try:
            rows = build_point_table_rows(
                draft,
                stations=stations,
                aps=aps,
            )
        except ValueError as exc:
            raise RailTransitWebError(
                "TRACKSIDE_AP_POINT_TABLE_INVALID",
                str(exc),
            ) from exc
        return TracksideApPointTablePreviewDTO(
            items=[TracksideApPointTableRowDTO.model_validate(row) for row in rows],
            total=len(rows),
            impact=ApManagementVlanImpactDTO.model_validate(
                plan_impact(
                    persisted,
                    draft,
                    stations=stations,
                    aps=aps,
                )
            ),
        )

    def _trackside_vlan_context(
        self,
        site_id: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        query = RailTransitBaseDataQueryService(self.paths)
        stations = [
            row.model_dump()
            for row in query.list_stations(
                site_id,
                page=1,
                page_size=10_000,
            ).items
        ]
        aps = [row.model_dump() for row in query.list_ap_location_items(site_id)]
        return stations, aps

    @staticmethod
    def _trackside_plan_dto(
        view: Mapping[str, object],
        *,
        source_rows: list[Mapping[str, object]] | None = None,
        stations: list[Mapping[str, object]] | None = None,
    ) -> TracksideApPlanDTO:
        legacy_rows = (
            source_rows
            if source_rows is not None
            else project_legacy_station_rows(view)
        )
        items = []
        station_by_id = {
            str(row.get("id") or row.get("station_id") or "").strip(): row
            for row in stations or []
        }
        station_ids_by_name: dict[str, list[str]] = {}
        for row in stations or []:
            station_name = str(row.get("name") or row.get("station_name") or "").strip()
            station_id = str(row.get("id") or row.get("station_id") or "").strip()
            if station_name and station_id:
                station_ids_by_name.setdefault(station_name, []).append(station_id)
        for index, row in enumerate(legacy_rows):
            item = dict(row)
            sequence_no = int(item.get("sequence_no") or 0)
            if sequence_no <= 0:
                sequence_no = int(item.get("sort_order") or index) + 1
            raw_vlan = (
                item.get("management_vlan")
                if "management_vlan" in item
                else item.get("ap_management_vlans")
            )
            try:
                management_vlan = int(str(raw_vlan).strip())
            except (TypeError, ValueError):
                management_vlan = None
            station_id = str(item.get("station_id") or "").strip()
            station_name = str(item.get("station_name") or "").strip()
            candidates = station_ids_by_name.get(station_name, [])
            if station_id and station_id in station_by_id:
                relation_status = "resolved"
                current = station_by_id[station_id]
                station_name = str(
                    current.get("name") or current.get("station_name") or station_name
                )
            elif station_id:
                relation_status = "stale"
            elif len(candidates) > 1:
                relation_status = "ambiguous"
            else:
                relation_status = "missing"
            items.append(
                TracksideApPlanRowDTO(
                    station_id=station_id,
                    sequence_no=sequence_no,
                    station_name=station_name,
                    planned_ap_count=int(
                        item.get("planned_ap_count")
                        if item.get("planned_ap_count") not in (None, "")
                        else item.get("ap_count")
                        or 0
                    ),
                    management_vlan=management_vlan,
                    remark=str(item.get("remark") or "").strip(),
                    relation_status=relation_status,
                    candidate_station_ids=candidates,
                )
            )
        return TracksideApPlanDTO.model_validate(
            {
                **dict(view),
                "items": items,
                "total": len(items),
            }
        )

    @staticmethod
    def _trackside_plan_payload(
        plan: TracksideApPlanDTO,
    ) -> dict[str, object]:
        return TracksideApPlanDraftDTO(
            planning=plan.planning,
            groups=plan.groups,
            assignments=plan.assignments,
            allocations=plan.allocations,
        ).model_dump()

    def preview_trackside_ap_plan(
        self,
        site_id: str,
        *,
        file_name: str,
        content: bytes,
        duplicate_strategy: str,
    ) -> TracksideApPlanPreviewDTO:
        site_id = self._site(site_id)
        strategy = self._duplicate_strategy(duplicate_strategy)
        raw_rows = self._read_table_upload(
            site_id, file_name, content, read_trackside_plan_file
        )
        legacy_schema = any(
            bool(row.pop("__legacy_schema__", False)) for row in raw_rows
        )
        stations, _aps = self._trackside_vlan_context(site_id)
        current_plan = self.get_trackside_ap_plan(site_id)
        existing = {
            self._trackside_plan_station_key(row.model_dump()): row
            for row in current_plan.items
        }
        imported: set[str] = set()
        preview_rows: list[TracksideApPlanPreviewRowDTO] = []
        duplicate_count = 0
        error_count = 0
        valid_count = 0
        applied_count = 0
        for fallback_row_number, raw in enumerate(raw_rows, start=2):
            row_number = int(
                raw.pop("__source_row_number__", fallback_row_number)
                or fallback_row_number
            )
            preview_value = self._trackside_plan_preview_value(raw)
            try:
                normalized = normalize_trackside_plan_row(
                    dict(raw),
                    row_number=row_number,
                )
                bound = bind_trackside_plan_station(
                    normalized,
                    stations,
                    row_number=row_number,
                )
                row = TracksideApPlanRowDTO.model_validate(
                    self._trackside_plan_preview_value(bound)
                )
            except (TypeError, ValueError) as exc:
                error_count += 1
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        message=str(exc),
                        row=preview_value,
                    )
                )
                continue
            key = self._trackside_plan_station_key(row.model_dump())
            duplicate = key in existing or key in imported
            if duplicate:
                duplicate_count += 1
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="duplicate",
                        key=row.station_name,
                        message={
                            "replace": "重复车站将由导入行覆盖",
                            "skip": "重复车站将保留现有值",
                            "error": "重复车站阻止确认导入",
                        }[strategy],
                        row=row.model_dump(),
                    )
                )
                if strategy == "replace":
                    existing[key] = row
                    applied_count += 1
                imported.add(key)
                continue
            valid_count += 1
            applied_count += 1
            imported.add(key)
            existing[key] = row
            preview_rows.append(
                TracksideApPlanPreviewRowDTO(
                    row_number=row_number,
                    status="valid",
                    key=row.station_name,
                    row=row.model_dump(),
                )
            )
        can_apply = applied_count > 0
        result_rows = list(existing.values()) if can_apply else []
        if can_apply:
            try:
                result_rows = [
                    TracksideApPlanRowDTO.model_validate(
                        self._trackside_plan_preview_value(row)
                    )
                    for row in normalize_trackside_plan_rows(
                        [row.model_dump() for row in result_rows]
                    )
                ]
            except ValueError as exc:
                can_apply = False
                error_count += 1
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=0,
                        status="error",
                        message=str(exc),
                    )
                )
                result_rows = []
        return TracksideApPlanPreviewDTO(
            file_name=Path(file_name).name,
            file_sha256=hashlib.sha256(content).hexdigest(),
            duplicate_strategy=strategy,
            can_apply=can_apply,
            total_count=len(raw_rows),
            valid_count=valid_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            rows=preview_rows,
            result_rows=result_rows,
            result_plan=(
                self._trackside_plan_dto(
                    {"planning": current_plan.planning.model_dump()},
                    source_rows=[row.model_dump() for row in result_rows],
                )
                if can_apply
                else None
            ),
            legacy_schema=legacy_schema,
            message=(
                "已识别旧版 VLAN 分组模板，将转换为逐站 AP 规划。"
                if legacy_schema
                else ""
            ),
        )

    @staticmethod
    def _trackside_plan_station_key(row: Mapping[str, object]) -> str:
        station_id = str(row.get("station_id") or "").strip()
        if station_id:
            return f"id:{station_id.casefold()}"
        return f"name:{str(row.get('station_name') or '').strip().casefold()}"

    @staticmethod
    def _trackside_plan_preview_value(
        row: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "station_id": str(row.get("station_id") or "").strip(),
            "sequence_no": row.get("sequence_no"),
            "station_name": row.get("station_name"),
            "planned_ap_count": (
                row.get("planned_ap_count")
                if row.get("planned_ap_count") not in (None, "")
                else row.get("ap_count")
            ),
            "management_vlan": (
                row.get("management_vlan")
                if "management_vlan" in row
                else row.get("ap_management_vlans")
            ),
            "remark": row.get("remark"),
        }

    def _preview_grouped_trackside_ap_plan(
        self,
        site_id: str,
        *,
        file_name: str,
        content: bytes,
        raw_rows: list[dict[str, object | None]],
        duplicate_strategy: str,
    ) -> TracksideApPlanPreviewDTO:
        stations, aps = self._trackside_vlan_context(site_id)
        current = self.get_trackside_ap_plan(site_id)
        groups_by_code: dict[str, dict[str, object]] = {}
        group_order: list[str] = []
        preview_rows: list[TracksideApPlanPreviewRowDTO] = []
        errors: list[str] = []
        mode = ""
        for row_number, raw in enumerate(raw_rows, start=2):
            code = str(raw.get("group_code") or "").strip()
            station_name = str(raw.get("station_name") or "").strip()
            row_mode = str(raw.get("planning_mode") or "").strip()
            if row_mode:
                if mode and row_mode != mode:
                    errors.append(f"第{row_number}行规划方式与前序行不一致")
                mode = mode or row_mode
            if not code:
                errors.append(f"第{row_number}行 VLAN组编号：必填")
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        message=errors[-1],
                    )
                )
                continue
            if not station_name:
                errors.append(f"第{row_number}行 车站名称：必填")
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        key=code,
                        message=errors[-1],
                    )
                )
                continue
            try:
                station_input = dict(raw)
                station_input["ap_management_vlans"] = (
                    station_input.get("ap_management_vlans")
                    or station_input.get("management_vlan")
                )
                station_input["ap_gateway"] = (
                    station_input.get("ap_gateway")
                    or station_input.get("default_gateway")
                )
                station_input["ap_start_address"] = (
                    station_input.get("ap_start_address")
                    or station_input.get("ap_start_ip")
                )
                station_input["mask_length"] = (
                    station_input.get("mask_length")
                    or station_input.get("subnet_mask")
                )
                station_row = normalize_trackside_plan_row(
                    station_input,
                    row_number=row_number,
                )
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        key=f"{code}/{station_name}",
                        message=str(exc),
                    )
                )
                continue
            station_id = ""
            imported_station_ids = [
                item.strip()
                for item in re.split(
                    r"[,，;；\r\n]+",
                    str(raw.get("station_ids") or ""),
                )
                if item.strip()
            ]
            imported_station_names = [
                item.strip()
                for item in re.split(
                    r"[,，、;；\r\n]+",
                    str(raw.get("station_names") or ""),
                )
                if item.strip()
            ]
            if len(imported_station_ids) == 1:
                station_id = imported_station_ids[0]
            elif len(imported_station_ids) == len(imported_station_names):
                station_id = next(
                    (
                        imported_station_ids[index]
                        for index, name in enumerate(imported_station_names)
                        if name.casefold() == station_name.casefold()
                    ),
                    "",
                )
            if code not in groups_by_code:
                group_order.append(code)
                groups_by_code[code] = {
                    "group_id": f"import:{hashlib.sha1(code.casefold().encode('utf-8')).hexdigest()[:16]}",
                    "group_code": code,
                    "group_name": str(raw.get("group_name") or code).strip(),
                    "sequence": len(group_order) - 1,
                    "management_vlan": (
                        raw.get("management_vlan")
                        if raw.get("management_vlan") not in (None, "")
                        else station_row["ap_management_vlans"]
                    ),
                    "network_address": str(raw.get("network_address") or "").strip(),
                    "prefix_length": station_row["mask_length"],
                    "subnet_mask": str(raw.get("subnet_mask") or "").strip(),
                    "default_gateway": str(
                        raw.get("default_gateway")
                        or station_row["ap_gateway"]
                        or ""
                    ).strip(),
                    "ap_start_ip": str(
                        raw.get("ap_start_ip")
                        or station_row["ap_start_address"]
                        or ""
                    ).strip(),
                    "ap_end_ip": str(raw.get("ap_end_ip") or "").strip(),
                    "notes": str(raw.get("remark") or "").strip(),
                    "members": [],
                }
            group = groups_by_code[code]
            imported_group_values = {
                "management_vlan": (
                    raw.get("management_vlan")
                    if raw.get("management_vlan") not in (None, "")
                    else station_row["ap_management_vlans"]
                ),
                "network_address": str(raw.get("network_address") or "").strip(),
                "prefix_length": station_row["mask_length"],
                "subnet_mask": str(raw.get("subnet_mask") or "").strip(),
                "default_gateway": str(
                    raw.get("default_gateway")
                    or station_row["ap_gateway"]
                    or ""
                ).strip(),
                "ap_start_ip": str(
                    raw.get("ap_start_ip")
                    or station_row["ap_start_address"]
                    or ""
                ).strip(),
                "ap_end_ip": str(raw.get("ap_end_ip") or "").strip(),
            }
            inconsistent_fields: list[str] = []
            for field_name, imported_value in imported_group_values.items():
                if imported_value in (None, ""):
                    continue
                existing_value = group.get(field_name)
                if existing_value in (None, ""):
                    group[field_name] = imported_value
                elif (
                    field_name == "management_vlan"
                    and str(existing_value) != str(imported_value)
                ):
                    inconsistent_fields.append(field_name)
            if inconsistent_fields:
                message = (
                    f"第{row_number}行 VLAN组“{code}”的管理 VLAN 与组内前序行不一致"
                )
                errors.append(message)
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        key=f"{code}/{station_name}",
                        message=message,
                    )
                )
                continue
            members = group["members"]
            assert isinstance(members, list)
            if any(
                (
                    station_id
                    and str(member.get("station_id") or "") == station_id
                )
                or (
                    str(member.get("station_name") or "").casefold()
                    == station_name.casefold()
                )
                for member in members
                if isinstance(member, Mapping)
            ):
                errors.append(f"第{row_number}行站点“{station_name}”在组内重复")
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        key=f"{code}/{station_name}",
                        message=errors[-1],
                    )
                )
                continue
            members.append(
                {
                    "station_id": station_id,
                    "station_name": station_name,
                }
            )
            preview_rows.append(
                TracksideApPlanPreviewRowDTO(
                    row_number=row_number,
                    status="valid",
                    key=f"{code}/{station_name}",
                    row=TracksideApPlanRowDTO.model_validate(
                        self._trackside_plan_preview_value(station_row)
                    ).model_dump(),
                )
            )
        proposed = {
            "planning": {
                "line_id": "current",
                "planning_mode": mode or "station_grouped",
                "auto_group_station_count": 1,
                "address_allocation_strategy": "station_then_point",
                "revision": current.planning.revision,
            },
            "groups": [groups_by_code[code] for code in group_order],
            "assignments": [],
            "allocations": [],
        }
        try:
            view = enrich_plan(proposed, stations=stations, aps=aps)
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
            view = None
        if view is not None:
            errors.extend(
                str(issue.get("message") or "")
                for issue in view["issues"]
                if bool(issue.get("blocking"))
            )
        can_apply = not errors
        result_plan = self._trackside_plan_dto(view) if view is not None else None
        result_rows = (
            [
                TracksideApPlanRowDTO.model_validate(
                    self._trackside_plan_preview_value(row)
                )
                for row in project_legacy_station_rows(view)
            ]
            if can_apply and view is not None
            else []
        )
        return TracksideApPlanPreviewDTO(
            file_name=Path(file_name).name,
            file_sha256=hashlib.sha256(content).hexdigest(),
            duplicate_strategy=duplicate_strategy,
            can_apply=can_apply,
            total_count=len(raw_rows),
            valid_count=sum(row.status == "valid" for row in preview_rows),
            duplicate_count=0,
            error_count=len(errors),
            rows=preview_rows,
            result_rows=result_rows,
            result_plan=result_plan,
        )

    def start_trackside_ap_plan_save(
        self,
        site_id: str,
        *,
        rows: list[dict[str, object | None]],
        draft: dict[str, object] | None = None,
        expected_revision: int | None = None,
        reallocation_policy: str = REALLOCATION_ONLY_UNLOCKED,
        explicit_confirmation: bool,
        audit: dict[str, str] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise RailTransitWebError(
                "CONFIRMATION_REQUIRED", "保存轨旁 AP 规划前必须明确确认"
            )
        stations, _aps = self._trackside_vlan_context(site_id)
        if draft is None:
            raw_rows = rows
        else:
            raw_rows = project_legacy_station_rows(draft)
        bound_rows = [
            bind_trackside_plan_station(
                normalize_trackside_plan_row(row, row_number=index),
                stations,
                row_number=index,
            )
            for index, row in enumerate(raw_rows, start=2)
        ]
        normalized_rows = normalize_trackside_plan_rows(bound_rows)
        current_revision = int(self.get_trackside_ap_plan(site_id).planning.revision)
        return self._start_task(
            site_id,
            "trackside_ap_plan_save",
            {
                "rows": normalized_rows,
                "expected_revision": (
                    current_revision
                    if draft is None or expected_revision is None
                    else int(expected_revision)
                ),
                "audit": {str(key): str(value) for key, value in (audit or {}).items()},
                "explicit_confirmation": True,
            },
        )

    def start_trackside_ap_plan_export(
        self,
        site_id: str,
        *,
        template: bool,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        generated_at = datetime.now().astimezone()
        summary = RailTransitBaseDataQueryService(self.paths).get_summary(site_id)
        line_name = str(summary.line_name or summary.site_name or site_id).strip()
        safe_line_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", line_name)
        preferred_name = (
            "轨旁AP逐站规划模板.xlsx"
            if template
            else (
                f"{safe_line_name}_轨旁AP规划及上线概览_"
                f"{generated_at:%Y%m%d}.xlsx"
            )
        )
        task_id = f"rail-export-{uuid4().hex}"
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="trackside_ap_plan",
                artifact_type="xlsx",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["trackside_ap_plan"],
                output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_plan",
                preferred_name=preferred_name,
            )
        except WebArtifactError as exc:
            self._task_window_blocked("轨旁 AP 规划导出", exc)
        columns = []
        for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS):
            column = {
                "key": field,
                "title": TRACKSIDE_PLAN_HEADERS[index],
                "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field),
            }
            if field in {"sequence_no", "ap_count", "management_vlan"}:
                column["number_format"] = "0"
            if field == "remark":
                column["wrap"] = True
                column["horizontal"] = "left"
            columns.append(column)
        if template:
            plan_source = inline_rows_source(
                [],
                allow_inline_rows=True,
                inline_reason="轨旁 AP 规划空白模板",
            )
        else:
            plan_source = repository_query_source(
                db_path=self.paths.site_db_path(site_id),
                repository="ac_repository",
                method="list_trackside_ap_plan",
                filters={"mode": TRACKSIDE_AP_PLAN_MODE},
            )
        sheets: list[dict[str, object]] = [
            {
                "sheet_name": TRACKSIDE_PLAN_SHEET,
                "columns": columns,
                "source": plan_source,
            }
        ]
        if template:
            sheets.append(
                {
                    "sheet_name": "字段说明",
                    "columns": [
                        dict(column)
                        for column in TRACKSIDE_PLAN_FIELD_NOTE_COLUMNS
                    ],
                    "rows": [
                        dict(row) for row in TRACKSIDE_PLAN_FIELD_NOTES
                    ],
                    "auto_filter": False,
                }
            )
        else:
            status = self.get_trackside_ap_online_status(site_id)
            status_rows = [
                {
                    "station_name": row.station_name,
                    "planned_ap_count": (
                        None if row.planning_missing else row.planned_ap_count
                    ),
                    "actual_online_count": row.actual_online_count,
                    "offline_count": row.offline_count,
                    "online_rate": (
                        None
                        if row.online_rate is None
                        else row.online_rate / 100
                    ),
                    "remark": row.remark,
                    "__row_kind": "station",
                }
                for row in status.items
            ]
            status_rows.append(
                {
                    "station_name": "合计",
                    "planned_ap_count": status.planned_ap_count,
                    "actual_online_count": status.actual_online_count,
                    "offline_count": status.offline_count,
                    "online_rate": (
                        None
                        if status.online_rate is None
                        else status.online_rate / 100
                    ),
                    "remark": status.warning,
                    "__row_kind": "total",
                }
            )
            sheets.append(
                {
                    "sheet_name": "AP上线情况概览",
                    "columns": [
                        {"key": "station_name", "title": "归属站点", "width": 24},
                        {
                            "key": "planned_ap_count",
                            "title": "规划AP总数量",
                            "width": 16,
                            "number_format": "0",
                        },
                        {
                            "key": "actual_online_count",
                            "title": "实际上线",
                            "width": 12,
                            "number_format": "0",
                        },
                        {
                            "key": "offline_count",
                            "title": "未上线",
                            "width": 12,
                            "number_format": "0",
                        },
                        {
                            "key": "online_rate",
                            "title": "上线率",
                            "width": 12,
                            "number_format": "0.0%",
                        },
                        {
                            "key": "remark",
                            "title": "备注",
                            "width": 42,
                            "wrap": True,
                            "horizontal": "left",
                        },
                    ],
                    "rows": status_rows,
                    "bold_row_field": "__row_kind",
                    "bold_row_values": ["total"],
                }
            )
        job = replace(
            ExportTaskSpec(
                task_type="multi_sheet_xlsx",
                output_path=str(reservation.output_path),
                site_name=site_id,
                payload={
                    "source_module": "ac.trackside_ap_plan",
                    "contract_metadata": {
                        "template_type": "trackside_ap_station_plan",
                        "schema_version": 4,
                        "generated_at": generated_at.isoformat(timespec="seconds"),
                        "project_id": site_id,
                        "line_id": "current",
                    },
                    "sheets": sheets,
                },
            )
            .to_job(task_id)
            .with_runtime_paths(
                tmp_path=str(
                    reservation.output_path.with_name(
                        f"{reservation.output_path.name}.{task_id}.tmp"
                    )
                ),
                cancel_path=str(
                    self.paths.runtime_cache_dir / "export_jobs" / f"{task_id}.cancel"
                ),
            ),
            site_name=site_id,
        )
        return self._start_export(
            site_id,
            job,
            "trackside_ap_plan_export",
            reservation,
        )

    def open_trackside_ap_plan_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "trackside_ap_plan")

    def start_car_network_diagnostic(self, site_id: str, *, train_id: str = "") -> RailTransitTaskDTO:
        selected_train = str(train_id or "").strip()
        if not selected_train:
            raise RailTransitWebError("TRAIN_REQUIRED", "请选择要检测的列车")
        site_id = self._site(site_id)
        trains = RailTransitBaseDataQueryService(self.paths).list_trains(site_id, page=1, page_size=200).items
        train = next((item for item in trains if train_identity_matches((selected_train,), (item.id, item.train_no, item.name))), None)
        point_nodes = [
            item
            for item in TrainCommunicationPointTableService(self.paths).read_nodes(site_id)
            if train_identity_matches(
                (selected_train,),
                (item.train_id, item.train_no, item.display_name),
            )
        ]
        try:
            online = self.vehicle_mr_online_query_service.get_train_by_identity(
                site_id, selected_train
            )
        except Exception:
            online = None
        online_ct = getattr(online, "ct", None)
        online_tc = getattr(online, "tc", None)
        identity = normalize_train_identity(
            selected_train,
            train.id if train is not None else "",
            train.train_no if train is not None else "",
            train.name if train is not None else "",
            point_nodes[0].train_id if point_nodes else "",
            point_nodes[0].train_no if point_nodes else "",
            point_nodes[0].display_name if point_nodes else "",
            getattr(online, "train_id", ""),
            getattr(online, "train_no", ""),
            getattr(online, "train_name", ""),
        )
        train_no = identity.train_no or (
            train.train_no
            if train is not None
            else point_nodes[0].train_no
            if point_nodes
            else ""
        )
        display_name = (
            train.name
            if train is not None
            else point_nodes[0].display_name
            if point_nodes
            else identity.display_name or selected_train
        )
        inspection = TrainCommunicationPointTableService(self.paths).inspect(
            site_id,
            identity.canonical_train_id or selected_train,
            train_no=train_no,
            display_name=display_name,
        )
        if inspection.status == POINT_TABLE_MISSING:
            raise RailTransitWebError("TRAIN_COMMUNICATION_POINT_TABLE_MISSING", inspection.message)
        if inspection.status == POINT_TABLE_INVALID:
            raise RailTransitWebError("TRAIN_COMMUNICATION_POINT_TABLE_INVALID", inspection.message)
        return self._start_task(
            site_id,
            "car_network_diagnostic",
            {
                "train_id": identity.canonical_train_id or selected_train,
                "canonical_train_id": identity.canonical_train_id,
                "train_no": train_no,
                "display_name": display_name,
                "ct_mr_id": str(getattr(online_ct, "mr_id", "") or ""),
                "ct_mr_name": str(getattr(online_ct, "mr_name", "") or ""),
                "tc_mr_id": str(getattr(online_tc, "mr_id", "") or ""),
                "tc_mr_name": str(getattr(online_tc, "mr_name", "") or ""),
                "point_table_revision": inspection.revision,
                "online_snapshot_time": str(getattr(online, "updated_at", "") or ""),
                "online_status": str(getattr(online, "overall_status", "UNKNOWN") or "UNKNOWN"),
            },
        )

    def get_car_network_diagnostic(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        task = self.get_task(site_id, task_id)
        if task.action != "car_network_diagnostic":
            raise RailTransitWebError("TASK_NOT_FOUND", "车内通信检测任务不存在")
        return task

    def cancel_car_network_diagnostic(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        self.get_car_network_diagnostic(site_id, task_id)
        return self.cancel_task(site_id, task_id)

    def recover_car_network_diagnostics(self, site_id: str) -> list[RailTransitTaskDTO]:
        return [task for task in self.recover_tasks(site_id) if task.action == "car_network_diagnostic"]

    def start_trackside_ap_update(
        self,
        site_id: str,
        *,
        station: str = "",
        ap_uuid: str = "",
        ap_mac: str = "",
        ap_name: str = "",
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        params = self._trackside_ap_update_scope_params(
            site_id,
            station=station,
            ap_uuid=ap_uuid,
            ap_mac=ap_mac,
            ap_name=ap_name,
        )
        ac_uuids = self._trackside_ap_optical_ac_uuids(
            site_id,
            station=params.get("station", ""),
            ap_uuid=params.get("ap_uuid", ""),
            ap_mac=params.get("ap_mac", ""),
            ap_name=params.get("ap_name", ""),
        )
        resource_keys = fit_ap_optical_resource_keys(site_id, ac_uuids)
        scope_key = self._trackside_ap_update_scope_resource_key(site_id, params)
        params["resource_keys"] = [
            self._trackside_ap_business_data_resource_key(site_id),
            *resource_keys,
            scope_key,
        ]
        params["reuse_equivalent_task"] = True
        existing = self._active_equivalent_trackside_task(
            site_id,
            params["resource_keys"],
        )
        if existing is not None:
            return existing
        if len(ac_uuids) == 1:
            params["device_uuid"] = ac_uuids[0]
            params["ac_uuid"] = ac_uuids[0]
        return self._start_task(
            site_id,
            "trackside_ap_optical_update",
            params,
            on_complete=lambda _value: self.invalidate_trackside_ap_runtime_views(site_id),
        )

    def invalidate_trackside_ap_runtime_views(self, site_id: str) -> None:
        """清理轨旁运行态内存视图；数据库事实仍由下一次只读查询读取。"""

        with self._trackside_online_cache_lock:
            self._trackside_online_cache.pop(self._site(site_id), None)

    @staticmethod
    def _trackside_ap_update_scope_resource_key(
        site_id: str,
        params: dict[str, object],
    ) -> str:
        if params.get("station"):
            scope = f"station:{str(params['station']).strip().casefold()}"
        elif any(params.get(key) for key in ("ap_uuid", "ap_mac", "ap_name")):
            scope = "|".join(
                f"{key}:{str(params.get(key) or '').strip().casefold()}"
                for key in ("ap_uuid", "ap_mac", "ap_name")
                if params.get(key)
            )
        else:
            scope = "all"
        return f"site:{site_id}|trackside_ap_optical|scope:{scope}"

    @staticmethod
    def _trackside_ap_business_data_resource_key(site_id: str) -> str:
        return f"site:{site_id}|trackside_ap_business_data"

    def _active_equivalent_trackside_task(
        self,
        site_id: str,
        resource_keys: list[str],
    ) -> RailTransitTaskDTO | None:
        requested = {
            str(value)
            for value in resource_keys
            if str(value or "").strip()
        }
        active = {
            TaskState.PENDING,
            TaskState.STARTING,
            TaskState.RUNNING,
            TaskState.STOPPING,
        }
        for snapshot in self.task_service.repository(site_id).list_filtered(
            statuses=active,
            owner=self._OWNER,
            source="local",
            site_name=site_id,
            limit=1000,
        ):
            if (
                snapshot.task_type == "trackside_ap_optical_update"
                and set(snapshot.resource_keys) == requested
            ):
                return self._task_dto(site_id, snapshot)
        return None

    def _trackside_ap_update_scope_params(
        self,
        site_id: str,
        *,
        station: str = "",
        ap_uuid: str = "",
        ap_mac: str = "",
        ap_name: str = "",
    ) -> dict[str, object]:
        selected_station = str(station or "").strip()
        selected_uuid = str(ap_uuid or "").strip()
        selected_mac_text = str(ap_mac or "").strip()
        selected_name = str(ap_name or "").strip()
        selected_mac = normalize_mac(selected_mac_text) if selected_mac_text else None
        if selected_mac_text and selected_mac is None:
            raise RailTransitWebError("AP_MAC_INVALID", "AP MAC 格式无效，无法定向更新")
        has_ap_identity = bool(selected_uuid or selected_mac or selected_name)
        if selected_name and not (selected_uuid or selected_mac):
            raise RailTransitWebError(
                "TRACKSIDE_UPDATE_AP_NAME_DEPRECATED",
                "AP 名称仅用于展示兼容，定向更新必须提供 AP UUID 或规范化 MAC",
            )
        if selected_station and has_ap_identity:
            raise RailTransitWebError("TRACKSIDE_UPDATE_SCOPE_CONFLICT", "站点范围和 AP 身份不能同时提交")
        if not has_ap_identity:
            return {"station": selected_station, "ap_uuid": "", "ap_mac": "", "ap_name": ""}

        matched = self._resolve_trackside_ap_update_target(
            site_id,
            ap_uuid=selected_uuid,
            ap_mac=selected_mac,
            ap_name=selected_name,
        )
        matched_ac_uuid = str(matched.get("ac_device_uuid") or "").strip()
        if not matched_ac_uuid:
            raise RailTransitWebError("TRACKSIDE_UPDATE_AP_AC_MISSING", "目标 AP 未绑定 AC，无法定向更新")
        matched_mac = normalize_mac(matched.get("ap_mac")) or selected_mac or ""
        return {
            "station": "",
            "ap_uuid": str(matched.get("ap_uuid") or selected_uuid),
            "ap_mac": matched_mac,
            "ap_name": str(matched.get("ap_name") or selected_name),
            "ac_uuid": matched_ac_uuid,
            "device_uuid": matched_ac_uuid,
        }

    def _trackside_ap_optical_ac_uuids(
        self,
        site_id: str,
        *,
        station: object = "",
        ap_uuid: object = "",
        ap_mac: object = "",
        ap_name: object = "",
    ) -> list[str]:
        database = Database(self.paths.site_db_path(site_id))
        ac_repository = AcRepository(database)
        try:
            rows = ac_repository.list_all_fit_ap_resources_with_metadata()
        except sqlite3.OperationalError as exc:
            if not self._is_missing_table_error(exc):
                raise
            rows = []
        selected_station = str(station or "").strip().casefold()
        selected_uuid = str(ap_uuid or "").strip()
        selected_mac = normalize_mac(ap_mac) if str(ap_mac or "").strip() else None
        selected_name = str(ap_name or "").strip().casefold()
        has_ap_identity = bool(selected_uuid or selected_mac or selected_name)
        if not selected_station and not has_ap_identity:
            return self._h3c_ac_device_uuids(database)
        matched_ac_uuids: list[str] = []
        for row in rows:
            ac_uuid = str(row.get("ac_device_uuid") or "").strip()
            if not ac_uuid:
                continue
            if has_ap_identity:
                if selected_uuid and str(row.get("ap_uuid") or "").strip() != selected_uuid:
                    continue
                if selected_mac and normalize_mac(row.get("ap_mac")) != selected_mac:
                    continue
                if selected_name and str(row.get("ap_name") or "").strip().casefold() != selected_name:
                    continue
                matched_ac_uuids.append(ac_uuid)
                continue
            row_station = str(row.get("site") or row.get("site_name") or row.get("station") or "").strip().casefold()
            if selected_station and row_station != selected_station:
                continue
            matched_ac_uuids.append(ac_uuid)
        if matched_ac_uuids:
            return list(dict.fromkeys(matched_ac_uuids))
        if has_ap_identity:
            raise RailTransitWebError("TRACKSIDE_UPDATE_AP_AC_MISSING", "目标 AP 未绑定 AC，无法定向更新")
        if selected_station:
            return []
        return self._h3c_ac_device_uuids(database)

    def _h3c_ac_device_uuids(self, database: Database) -> list[str]:
        try:
            return [
                str(device.device_uuid or "")
                for device in DeviceRepository(database).list(
                    vendor="H3C",
                    device_type="AC",
                    work_scope_status="included",
                )
                if str(device.device_uuid or "").strip()
            ]
        except sqlite3.OperationalError as exc:
            if self._is_missing_table_error(exc):
                return []
            raise

    @staticmethod
    def _is_missing_table_error(exc: sqlite3.OperationalError) -> bool:
        return "no such table" in str(exc).casefold()

    def _resolve_trackside_ap_update_target(
        self,
        site_id: str,
        *,
        ap_uuid: str,
        ap_mac: str | None,
        ap_name: str,
    ) -> dict[str, object | None]:
        rows = AcRepository(Database(self.paths.site_db_path(site_id))).list_all_fit_ap_resources_with_metadata()
        matches_by_field: dict[str, list[dict[str, object | None]]] = {}
        if ap_uuid:
            matches_by_field["ap_uuid"] = [
                row for row in rows if str(row.get("ap_uuid") or "").strip() == ap_uuid
            ]
        if ap_mac:
            matches_by_field["ap_mac"] = [
                row for row in rows if normalize_mac(row.get("ap_mac")) == ap_mac
            ]
        if ap_name:
            folded = ap_name.casefold()
            matches_by_field["ap_name"] = [
                row for row in rows if str(row.get("ap_name") or "").strip().casefold() == folded
            ]
        missing_fields = [field for field, values in matches_by_field.items() if not values]
        if missing_fields and len(matches_by_field) > 1:
            raise RailTransitWebError("TRACKSIDE_UPDATE_AP_CONFLICT", "AP UUID、MAC 或名称不一致，已拒绝更新")
        if missing_fields:
            raise RailTransitWebError("TRACKSIDE_UPDATE_AP_NOT_FOUND", "未找到目标 AP，无法定向更新")

        candidates = [row for values in matches_by_field.values() for row in values]
        by_key: dict[str, dict[str, object | None]] = {}
        for row in candidates:
            key = self._trackside_ap_identity_key(row)
            if key:
                by_key[key] = row
        if not by_key:
            raise RailTransitWebError("TRACKSIDE_UPDATE_AP_NOT_FOUND", "未找到目标 AP，无法定向更新")
        if len(by_key) > 1:
            raise RailTransitWebError("TRACKSIDE_UPDATE_AP_CONFLICT", "AP UUID、MAC 或名称命中了不同 AP，已拒绝更新")
        return next(iter(by_key.values()))

    @staticmethod
    def _trackside_ap_identity_key(row: dict[str, object | None]) -> str:
        ap_uuid = str(row.get("ap_uuid") or "").strip()
        if ap_uuid:
            return f"uuid:{ap_uuid.casefold()}"
        ap_mac = normalize_mac(row.get("ap_mac"))
        if ap_mac:
            return f"mac:{ap_mac}"
        ap_name = str(row.get("ap_name") or "").strip()
        return f"name:{ap_name.casefold()}" if ap_name else ""

    def start_vehicle_mr_online_refresh(self, site_id: str) -> RailTransitTaskDTO:
        return self._start_task(self._site(site_id), "vehicle_mr_online_refresh_all", {})

    def start_vehicle_mr_online_collection(
        self,
        site_id: str,
        *,
        ac_device_id: int,
        interval_seconds: int,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if "vehicle_mr_online_collection_start" not in registered_task_types():
            raise RailTransitWebError(
                "BLOCKED_ON_TASK_WINDOW",
                "连续采集领域 Job 已实现，但共享 Job Center 尚未注册 vehicle_mr_online_collection_start",
            )
        if int(ac_device_id) <= 0:
            raise RailTransitWebError("AC_REQUIRED", "请选择无线控制器 AC")
        if not 3 <= int(interval_seconds) <= 300:
            raise RailTransitWebError("INTERVAL_INVALID", "采集间隔必须是 3-300 秒")
        return self._start_task(
            site_id,
            "vehicle_mr_online_collection_start",
            {"ac_device_id": int(ac_device_id), "interval_seconds": int(interval_seconds)},
        )

    def start_vehicle_mr_ap_mapping_refresh(self, site_id: str, *, train_id: str = "") -> RailTransitTaskDTO:
        return self._start_task(
            self._site(site_id),
            "vehicle_mr_ap_mapping_refresh",
            {"train_id": str(train_id or "").strip()},
        )

    def preview_vehicle_mr_mappings(
        self,
        site_id: str,
        *,
        file_name: str,
        content: bytes,
        duplicate_strategy: str,
    ) -> VehicleMrMappingPreviewDTO:
        site_id = self._site(site_id)
        strategy = self._duplicate_strategy(duplicate_strategy)
        raw_rows = self._read_table_upload(site_id, file_name, content, read_vehicle_mr_mapping_file)
        existing_rows = [VehicleMrTrainMappingDTO.model_validate(row) for row in self._vehicle_mapping_rows(site_id)]
        merged = {self._vehicle_mapping_key(row): row for row in existing_rows}
        peer_owner = self._vehicle_peer_owners(merged)
        imported: set[str] = set()
        previews: list[VehicleMrMappingPreviewRowDTO] = []
        duplicate_count = 0
        error_count = 0
        valid_count = 0
        for row_number, raw in enumerate(raw_rows, start=2):
            try:
                row = VehicleMrTrainMappingDTO.model_validate(asdict(normalize_vehicle_mr_mapping_row(raw, row_number=row_number)))
            except (TypeError, ValueError) as exc:
                error_count += 1
                previews.append(VehicleMrMappingPreviewRowDTO(row_number=row_number, status="error", message=str(exc)))
                continue
            key = self._vehicle_mapping_key(row)
            duplicate = key in merged or key in imported
            if duplicate and strategy == "skip":
                duplicate_count += 1
                imported.add(key)
                previews.append(VehicleMrMappingPreviewRowDTO(row_number=row_number, status="duplicate", key=key, message="重复车次将保留现有值", row=row))
                continue
            if duplicate and strategy == "error":
                duplicate_count += 1
                imported.add(key)
                previews.append(VehicleMrMappingPreviewRowDTO(row_number=row_number, status="duplicate", key=key, message="重复车次阻止确认导入", row=row))
                continue
            previous = merged.get(key)
            if previous is not None:
                for peer in (previous.tc1_peer_name, previous.tc2_peer_name):
                    if peer and peer_owner.get(peer.casefold()) == key:
                        peer_owner.pop(peer.casefold(), None)
            conflict = next(
                (
                    peer
                    for peer in (row.tc1_peer_name, row.tc2_peer_name)
                    if peer and peer_owner.get(peer.casefold()) not in {None, key}
                ),
                "",
            )
            if conflict:
                error_count += 1
                previews.append(VehicleMrMappingPreviewRowDTO(row_number=row_number, status="error", key=key, message=f"Peer Name 重复：{conflict}", row=row))
                if previous is not None:
                    merged[key] = previous
                    peer_owner.update(self._vehicle_peer_owners({key: previous}))
                continue
            if duplicate:
                duplicate_count += 1
                status_value = "duplicate"
                message = "重复车次将由导入行覆盖"
            else:
                valid_count += 1
                status_value = "valid"
                message = ""
            imported.add(key)
            merged[key] = row
            for peer in (row.tc1_peer_name, row.tc2_peer_name):
                if peer:
                    peer_owner[peer.casefold()] = key
            previews.append(VehicleMrMappingPreviewRowDTO(row_number=row_number, status=status_value, key=key, message=message, row=row))
        can_apply = error_count == 0 and (strategy != "error" or duplicate_count == 0)
        return VehicleMrMappingPreviewDTO(
            file_name=Path(file_name).name,
            file_sha256=hashlib.sha256(content).hexdigest(),
            duplicate_strategy=strategy,
            can_apply=can_apply,
            total_count=len(raw_rows),
            valid_count=valid_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            rows=previews,
            result_rows=list(merged.values()) if can_apply else [],
        )

    def save_vehicle_mr_mappings(
        self,
        site_id: str,
        mappings: list[dict[str, object]],
        *,
        explicit_confirmation: bool = False,
        audit: dict[str, str] | None = None,
    ) -> RailTransitTaskDTO:
        if not explicit_confirmation:
            raise RailTransitWebError("CONFIRMATION_REQUIRED", "保存列车 MR 映射前必须明确确认")
        return self._start_task(
            self._site(site_id),
            "vehicle_mr_mapping_save",
            {
                "mappings": [dict(row) for row in mappings],
                "explicit_confirmation": True,
                "audit": {str(key): str(value) for key, value in (audit or {}).items()},
            },
        )

    def start_vehicle_mr_mapping_template_export(self, site_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        task_id = f"rail-export-{uuid4().hex}"
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="vehicle_mr_mapping_template",
                artifact_type="xlsx",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["vehicle_mr_mapping_template"],
                output_root=self.paths.online_mr_root(site_id) / "exports" / "vehicle_mr_mapping",
                preferred_name="车载MR映射模板.xlsx",
            )
        except WebArtifactError as exc:
            self._task_window_blocked("车载 MR 映射模板导出", exc)
        spec = table_xlsx_spec(
            reservation.output_path,
            columns=list(VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS),
            rows=list(VEHICLE_MR_MAPPING_TEMPLATE_ROWS),
            sheet_name="车载MR映射表",
            title="导出车载 MR 映射模板",
            open_dir_on_success=False,
            allow_inline_rows=True,
            inline_reason="车载 MR 映射模板为固定示例行",
        )
        return self._start_export(site_id, replace(spec.to_job(task_id), site_name=site_id), "vehicle_mr_mapping_template_export", reservation)

    def open_vehicle_mr_mapping_template(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "vehicle_mr_mapping_template")

    def start_vehicle_mr_history_export(
        self,
        site_id: str,
        *,
        train_id: str,
        filters: dict[str, object],
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        selected_train = str(train_id or "").strip()
        if not selected_train:
            raise RailTransitWebError("TRAIN_REQUIRED", "请选择要导出历史的列车")
        task_id = f"rail-export-{uuid4().hex}"
        try:
            reservation = self.artifact_store.reserve(
                site_id=site_id,
                owner=self._OWNER,
                source="vehicle_mr_history",
                artifact_type="xlsx",
                task_id=task_id,
                task_type=self._ARTIFACT_TASK_TYPES["vehicle_mr_history"],
                output_root=self.paths.online_mr_root(site_id) / "exports" / "vehicle_mr_history",
                preferred_name=f"{selected_train}_列车经过历史.xlsx",
            )
        except WebArtifactError as exc:
            self._task_window_blocked("列车经过历史导出", exc)
        job = vehicle_mr_history_xlsx_spec(
            reservation.output_path,
            app_root=self.paths.app_root,
            data_root=self.paths.data_root,
            site_name=site_id,
            train_id=selected_train,
            filters=filters,
            title="导出列车经过历史",
            open_dir_on_success=False,
        ).to_job(task_id)
        return self._start_export(site_id, job, "vehicle_mr_history_export", reservation)

    def open_vehicle_mr_history_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "vehicle_mr_history")

    def start_online_mr_report(self, site_id: str, session_id: str, output_name: str = "") -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        detail, session_dir = self._online_mr_session_dir(site_id, session_id)
        if detail.database_summary.status != "ready":
            raise RailTransitWebError(
                "PARSE_REQUIRED",
                detail.database_summary.message or "Online MR 解析数据库尚未就绪，请先解析当前会话",
            )
        root = self.paths.online_mr_root(site_id).resolve()
        task_id = f"rail-export-{uuid4().hex}"
        name = self._report_name(output_name or f"{session_id}_online_mr.xlsx")
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="online_mr_report",
            artifact_type="xlsx",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["online_mr_report"],
            output_root=root / "reports",
            preferred_name=name,
            context={"kind": "online_mr_session", "session_id": session_id},
        )
        job = online_mr_report_xlsx_spec(
            reservation.output_path,
            session_dir=session_dir,
            title="Online MR 分析报告",
            open_dir_on_success=False,
        ).to_job(task_id)
        return self._start_export(
            site_id,
            replace(job, site_name=site_id),
            "online_mr_report",
            reservation,
            resource_keys=[online_mr_session_resource_key(site_id, session_id)],
        )

    def add_online_mr_note(
        self,
        site_id: str,
        session_id: str,
        *,
        note: str,
        explicit_confirmation: bool,
        audit: dict[str, str] | None = None,
    ) -> OnlineMrManualNoteDTO:
        site_id = self._site(site_id)
        text = str(note or "").strip()
        if not explicit_confirmation:
            raise RailTransitWebError("CONFIRMATION_REQUIRED", "记录 Online MR 备注前必须显式确认")
        if not text:
            raise RailTransitWebError("NOTE_REQUIRED", "备注内容不能为空")
        if len(text) > 500:
            raise RailTransitWebError("NOTE_TOO_LONG", "备注内容不得超过 500 字符")
        detail, session_dir = self._online_mr_session_dir(site_id, session_id)
        local_time = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        audit_payload = {
            str(key)[:80]: str(value)[:500]
            for key, value in list(dict(audit or {}).items())[:20]
            if str(key).strip()
            and str(value).strip()
            and str(key) not in {"source", "action"}
        }
        audit_payload.update(source="electron_online_mr", action="add_note")
        payload: dict[str, object] = {
            "local_time": local_time,
            "device_aligned_time": None,
            "session_id": session_id,
            "device_id": detail.device_id,
            "device_name": detail.device_name or detail.mr_name or "-",
            "note": text,
            "audit": audit_payload,
        }
        jsonl_path = session_dir / "manual_notes.jsonl"
        text_path = session_dir / "manual_notes.txt"
        if jsonl_path.is_symlink() or text_path.is_symlink():
            raise RailTransitWebError("NOTE_PATH_INVALID", "Online MR 备注文件路径无效")
        with self._NOTE_LOCK:
            with jsonl_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            with text_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"[{local_time}] [{payload['device_name']}] {text}\n")
        return OnlineMrManualNoteDTO(
            event_id=f"note-{uuid4().hex}",
            session_id=session_id,
            local_time=local_time,
            title=text,
            payload={"device_id": detail.device_id, "device_name": payload["device_name"], "audit": audit_payload},
        )

    def start_online_mr_parse(self, site_id: str, session_id: str, *, force_reparse: bool) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        _detail, session_dir = self._online_mr_session_dir(site_id, session_id)
        raw_dir = session_dir / "raw"
        if not raw_dir.is_dir() or raw_dir.is_symlink():
            raise RailTransitWebError("RAW_DATA_NOT_FOUND", "Online MR 会话缺少可解析的 raw 目录")
        return self._start_task(
            site_id,
            "online_mr_parse",
            {
                "session_dir": str(session_dir),
                "force_reparse": bool(force_reparse),
                "audit": {"source": "electron_online_mr", "action": "force_reparse" if force_reparse else "parse"},
                "resource_keys": [online_mr_session_resource_key(site_id, session_id)],
                "resource_conflict_message": "当前会话已有解析、报告或删除任务正在执行，请等待任务完成。",
            },
        )

    def online_mr_desktop_location(self, site_id: str, session_id: str) -> dict[str, str]:
        site_id = self._site(site_id)
        try:
            _detail, session_dir = self._online_mr_session_dir(site_id, session_id)
        except RailTransitWebError as exc:
            if exc.code == "SESSION_NOT_FOUND":
                report_location = self._online_mr_report_location(site_id, session_id)
                if report_location is not None:
                    return report_location
                raise RailTransitWebError(
                    "ONLINE_MR_LOCAL_FILES_MISSING",
                    "该会话的本地文件已不存在。",
                ) from exc
            raise
        root = self.paths.online_mr_root(site_id).resolve()
        paths = OnlineMrCollectionPaths.from_session_dir(session_dir)
        preferred_files = [
            paths.package_path,
            paths.raw_dir / "mesh_link_raw.log",
            paths.raw_dir / "terminal_monitor_raw.log",
            paths.raw_dir / "collector_output_raw.log",
        ]
        for candidate in preferred_files:
            resolved = candidate.resolve(strict=False)
            self._require_within(resolved, root)
            if candidate.is_file() and not candidate.is_symlink():
                return {"target_type": "file", "path": str(resolved)}
        raw_dir = paths.raw_dir.resolve(strict=False)
        self._require_within(raw_dir, root)
        if raw_dir.is_dir() and not raw_dir.is_symlink():
            return {"target_type": "directory", "path": str(raw_dir)}
        if session_dir.is_dir() and not session_dir.is_symlink():
            return {"target_type": "directory", "path": str(session_dir)}
        parsed = (session_dir / "parsed").resolve(strict=False)
        if parsed.is_dir() and not parsed.is_symlink():
            return {"target_type": "directory", "path": str(parsed)}
        report_location = self._online_mr_report_location(site_id, session_id)
        if report_location is not None:
            return report_location
        raise RailTransitWebError(
            "ONLINE_MR_LOCAL_FILES_MISSING",
            "该会话的本地文件已不存在。",
        )

    def _online_mr_report_location(
        self,
        site_id: str,
        session_id: str,
    ) -> dict[str, str] | None:
        reports = self.artifact_store.online_mr_session_artifacts(
            site_id,
            session_id,
            owner=self._OWNER,
            task_type=self._ARTIFACT_TASK_TYPES["online_mr_report"],
        )
        for item in reports:
            candidate = Path(str(item.get("path") or ""))
            if candidate.is_file() and not candidate.is_symlink():
                return {"target_type": "file", "path": str(candidate.resolve())}
            parent = candidate.parent
            if parent.is_dir() and not parent.is_symlink():
                return {"target_type": "directory", "path": str(parent.resolve())}
        return None

    def start_online_mr_delete(
        self,
        site_id: str,
        session_id: str,
        *,
        expected_session_id: str,
        explicit_confirmation: bool,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation or expected_session_id != session_id:
            raise RailTransitWebError(
                "CONFIRMATION_REQUIRED",
                "删除目标已变化，请重新选择会话并确认。",
            )
        detail, session_dir = self._online_mr_session_dir(site_id, session_id)
        active_session_states = {
            "CREATED",
            "CONNECTING",
            "INITIALIZING",
            "COLLECTING",
            "RECONNECTING",
            "STARTING",
            "RUNNING",
            "STOPPING",
            "VALIDATING",
            "PREPARING_TASK",
            "PREPARING_SESSION",
            "STARTING_COLLECTION",
            "STOPPING_TRAFFIC",
            "STOPPING_COLLECTION",
        }
        finalizing_session_states = {
            "FINALIZING",
            "PARSING",
            "PACKAGING",
            "ARCHIVING",
            "RECOVERING",
        }
        active_task_states = {
            TaskState.PENDING.value,
            TaskState.STARTING.value,
            TaskState.RUNNING.value,
            TaskState.STOPPING.value,
        }
        session_status = str(detail.status or "").upper()
        session_phase = str(detail.phase or "").upper()
        if (
            session_status in finalizing_session_states
            or session_phase in finalizing_session_states
        ):
            raise RailTransitWebError(
                "ONLINE_MR_SESSION_FINALIZING",
                "当前会话正在归档、解析或打包，请等待任务完成。",
            )
        if session_status in active_session_states or session_phase in active_session_states:
            raise RailTransitWebError(
                "ONLINE_MR_SESSION_RUNNING",
                "当前会话仍在采集或停止处理中，请先停止并等待任务完成。",
            )
        if (
            str(detail.task_status or "").upper() in active_task_states
            or str(detail.mapping_state or "").upper() in {"PENDING_SESSION", "LINKED"}
        ):
            raise RailTransitWebError(
                "ONLINE_MR_SESSION_RESOURCE_ACTIVE",
                "当前会话资源正在使用，请等待关联任务完成。",
            )
        resource_key = online_mr_session_resource_key(site_id, session_id)
        artifacts = self.artifact_store.online_mr_session_artifacts(
            site_id,
            session_id,
            owner=self._OWNER,
            task_type=self._ARTIFACT_TASK_TYPES["online_mr_report"],
        )
        related_task_ids = {
            str(detail.controller_task_id or ""),
            *(str(item.get("task_id") or "") for item in artifacts),
        }
        repository = self.task_service.repository(site_id)
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        for snapshot in repository.list_filtered(
            statuses=active,
            site_name=site_id,
            limit=1000,
        ):
            if resource_key in snapshot.resource_keys or snapshot.task_id in related_task_ids:
                raise RailTransitWebError(
                    "ONLINE_MR_SESSION_TASK_ACTIVE",
                    "当前会话仍有关联解析、导出或恢复任务正在执行，请等待任务完成。",
                )
        related_task_ids.update(
            snapshot.task_id
            for snapshot in repository.list_filtered(site_name=site_id, limit=1000)
            if resource_key in snapshot.resource_keys
        )
        return self._start_task(
            site_id,
            "online_mr_session_delete",
            {
                "site_id": site_id,
                "session_id": session_id,
                "session_dir": str(session_dir),
                "artifact_items": artifacts,
                "related_task_ids": sorted(value for value in related_task_ids if value),
                "resource_keys": [resource_key],
                "resource_conflict_message": "当前会话已有解析、报告或删除任务正在执行，请等待任务完成。",
                "audit": {"source": "electron_online_mr", "action": "delete_session"},
            },
        )

    def start_mesh_report(
        self,
        site_id: str,
        session_id: str,
        *,
        analysis_params_override: dict[str, object] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        try:
            context = self.mesh_query_service._context(site_id, session_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_SESSION_NOT_FOUND", str(exc)) from exc
        if context.detail_db is None or not context.detail_db.is_file():
            raise RailTransitWebError("MESH_RESULT_NOT_FOUND", "MESH 结构化分析结果不存在")
        try:
            site_analysis_params = load_site_mesh_analysis_params(self.paths, site_id).to_dict()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            site_analysis_params = {}
        ap_location_snapshot = self.mesh_query_service.ap_location_snapshot(site_id).to_serializable()
        output_root = self.paths.mesh_mr_export_dir(site_id, context.safe_folder_name).resolve()
        self._require_within(output_root, self.paths.site_mesh_root(site_id).resolve())
        task_id = f"rail-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="mesh_analysis_report",
            artifact_type="xlsx",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["mesh_analysis_report"],
            output_root=output_root,
            preferred_name=f"{context.mr_name}_MESH分析报告.xlsx",
            context={
                "kind": "mesh_analysis_session",
                "session_id": session_id,
            },
        )
        job = ExportJob(
            job_id=task_id,
            job_type="mesh_analysis_report",
            site_name=site_id,
            output_path=str(reservation.output_path),
            db_path=str(context.detail_db),
            params={
                "payload": {
                    "mr_name": context.mr_name,
                    "source_file_ids": [context.detail_source_id],
                        "options": {
                            "report_name": f"{context.mr_name} MESH 分析报告",
                            "analysis_params_override": analysis_params_override,
                            "site_analysis_params": site_analysis_params,
                        "ap_location_snapshot": ap_location_snapshot,
                    },
                }
            },
            context={"session_id": session_id},
        )
        return self._start_export(site_id, job, "mesh_analysis_report", reservation)

    def get_mesh_analysis_params(self, site_id: str) -> MeshAnalysisParamsDTO:
        return MeshAnalysisParamsDTO(**load_site_mesh_analysis_params(self.paths, self._site(site_id)).to_dict())

    def get_mesh_analysis_params_template(self, site_id: str, service_type: str) -> MeshAnalysisParamsDTO:
        self._site(site_id)
        return MeshAnalysisParamsDTO(**mesh_analysis_params_template(service_type).to_dict())

    def save_mesh_analysis_params(self, site_id: str, values: dict[str, object]) -> MeshAnalysisParamsDTO:
        site_id = self._site(site_id)
        params = normalize_mesh_analysis_params(values)
        save_site_mesh_analysis_params(self.paths, site_id, params)
        self.mesh_query_service._build_rows_cached.cache_clear()
        return MeshAnalysisParamsDTO(**params.to_dict())

    def start_mesh_link_detail_export(
        self,
        site_id: str,
        session_id: str,
        *,
        source_file_id: int,
        analysis_params_override: dict[str, object] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        try:
            context = self.mesh_query_service._context(site_id, session_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_SESSION_NOT_FOUND", str(exc)) from exc
        if int(source_file_id) != context.source_id:
            raise RailTransitWebError("MESH_SOURCE_NOT_FOUND", "导出来源必须是当前选中的具体日志")
        if context.detail_db is None or not context.detail_db.is_file():
            raise RailTransitWebError("MESH_RESULT_NOT_FOUND", "MESH 结构化分析结果不存在")
        try:
            site_analysis_params = load_site_mesh_analysis_params(self.paths, site_id).to_dict()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            site_analysis_params = {}
        ap_location_snapshot = self.mesh_query_service.ap_location_snapshot(site_id).to_serializable()
        output_root = self.paths.mesh_mr_export_dir(site_id, context.safe_folder_name).resolve()
        self._require_within(output_root, self.paths.site_mesh_root(site_id).resolve())
        task_id = f"rail-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner=self._OWNER,
            source="mesh_link_detail_export",
            artifact_type="xlsx",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["mesh_link_detail_export"],
            output_root=output_root,
            preferred_name=f"{context.mr_name}_链路明细_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
            context={
                "kind": "mesh_analysis_session",
                "session_id": session_id,
            },
        )
        job = ExportJob(
            job_id=task_id,
            job_type="mesh_link_detail_export",
            site_name=site_id,
            output_path=str(reservation.output_path),
            db_path=str(context.detail_db),
            filters={"source_file_id": context.detail_source_id},
            params={
                "analysis_params": analysis_params_override,
                "fallback_analysis_params": site_analysis_params,
                "ap_location_snapshot": ap_location_snapshot,
            },
            context={
                "session_id": session_id,
                "source_file_id": context.detail_source_id,
                "site_name": site_id,
                "mr_name": context.mr_name,
                "source_label": str(
                    context.source.get("original_filename")
                    or context.source.get("archived_filename")
                    or context.source_id
                ),
            },
        )
        return self._start_export(site_id, job, "mesh_link_detail_export", reservation)

    def delete_mesh_artifact(self, site_id: str, session_id: str, artifact_id: str) -> MeshArtifactDeleteResultDTO:
        site_id = self._site(site_id)
        try:
            name, targets = self.mesh_query_service.artifact_delete_targets(site_id, session_id, artifact_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_ARTIFACT_NOT_FOUND", str(exc)) from exc
        deleted = 0
        for target in targets:
            try:
                target.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RailTransitWebError("MESH_ARTIFACT_DELETE_FAILED", f"删除分析报告失败：{exc}") from exc
            deleted += 1
        if deleted == 0:
            raise RailTransitWebError("MESH_ARTIFACT_NOT_FOUND", "分析报告已不存在")
        MeshCatalogRepository(
            self.paths.mesh_catalog_path(site_id)
        ).mark_session_index_dirty(session_id)
        return MeshArtifactDeleteResultDTO(artifact_id=artifact_id, name=name, deleted_files=deleted)

    def start_mesh_rebuild(self, site_id: str, session_id: str, *, explicit_confirmation: bool) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise RailTransitWebError("CONFIRMATION_REQUIRED", "重建 MESH 派生数据库前必须显式确认")
        try:
            self.mesh_query_service._context(site_id, session_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_SESSION_NOT_FOUND", str(exc)) from exc
        return self._start_task(
            site_id,
            "mesh_source_rebuild",
            {
                "session_id": session_id,
                "explicit_confirmation": True,
                "resource_keys": [f"mesh_source:{session_id}"],
                "audit": {"source": "electron_mesh_analysis", "action": "rebuild_source"},
            },
        )

    def start_mesh_source_delete(
        self,
        site_id: str,
        session_id: str,
        *,
        delete_raw_archive: bool,
        delete_parsed_data: bool,
        delete_generated_reports: bool,
        explicit_confirmation: bool,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise RailTransitWebError(
                "CONFIRMATION_REQUIRED",
                "删除 MESH 来源前必须显式确认",
            )
        if not delete_parsed_data:
            raise RailTransitWebError(
                "DELETE_SCOPE_INVALID",
                "MESH 来源删除必须包含解析结果",
            )
        try:
            self.mesh_query_service._context(site_id, session_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_SESSION_NOT_FOUND", str(exc)) from exc
        active = self.task_service.repository(site_id).list(
            statuses={
                TaskState.PENDING,
                TaskState.STARTING,
                TaskState.RUNNING,
                TaskState.STOPPING,
            },
            limit=1000,
        )
        blocking_types = {
            "mesh_log_import",
            "mesh_bundle_import",
            "mesh_schema_rebuild",
            "mesh_source_rebuild",
            "mesh_analysis_source_delete",
            "web_export_mesh_analysis_report",
            "web_export_mesh_link_detail_export",
        }
        source_key = f"mesh_source:{session_id}"
        if any(
            item.task_type in blocking_types
            and (
                item.task_type != "mesh_analysis_source_delete"
                or source_key in item.resource_keys
            )
            for item in active
        ):
            raise RailTransitWebError(
                "MESH_SOURCE_TASK_RUNNING",
                "当前有 MESH 导入、解析、重建、报告或删除任务正在运行",
            )
        return self._start_task(
            site_id,
            "mesh_analysis_source_delete",
            {
                "session_id": session_id,
                "delete_raw_archive": bool(delete_raw_archive),
                "delete_parsed_data": True,
                "delete_generated_reports": bool(delete_generated_reports),
                "explicit_confirmation": True,
                "resource_keys": [source_key],
                "audit": {
                    "source": "electron_mesh_analysis",
                    "action": "delete_source",
                    "delete_raw_archive": bool(delete_raw_archive),
                },
            },
        )

    def get_task(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        return self._task_dto(site_id, self._snapshot(site_id, task_id))

    def cancel_task(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        snapshot = self._snapshot(site_id, task_id)
        if (
            snapshot.task_type == "online_mr_session_delete"
            and snapshot.status not in TERMINAL_TASK_STATES
        ):
            raise RailTransitWebError(
                "TASK_NOT_CANCELLABLE",
                "会话删除进入受控提交后不可停止，请等待任务完成。",
            )
        if snapshot.status not in TERMINAL_TASK_STATES:
            cancelled = self.process_adapter.cancel_job(task_id) or self.export_adapter.cancel_job(task_id)
            if not cancelled:
                self._reconcile_owned_orphans(site_id)
            snapshot = self._snapshot(site_id, task_id)
        return self._task_dto(site_id, snapshot)

    def recover_tasks(self, site_id: str) -> list[RailTransitTaskDTO]:
        site_id = self._site(site_id)
        repository = self.task_service.repository(site_id)
        self._reconcile_owned_orphans(site_id)
        for item in repository.list(statuses=TERMINAL_TASK_STATES, limit=1000):
            if (
                item.site_name != site_id
                or not self._authorized(item)
                or item.dismissed_at
            ):
                continue
            self._cleanup_recovered_task(site_id, item)
            if item.task_type in self._ARTIFACT_TASK_TYPES.values():
                if item.status is TaskState.COMPLETED:
                    self.artifact_store.reconcile_completed_task(
                        site_id,
                        item.task_id,
                        owner=self._OWNER,
                        source_task_types=self._ARTIFACT_TASK_TYPES,
                    )
                else:
                    self.artifact_store.discard_incomplete_terminal_task(
                        site_id,
                        item.task_id,
                        owner=self._OWNER,
                        source_task_types=self._ARTIFACT_TASK_TYPES,
                    )
        return [
            self._task_dto(site_id, item)
            for item in repository.list(limit=200)
            if (
                item.site_name == site_id
                and self._authorized(item)
                and not item.dismissed_at
            )
        ]

    def open_online_mr_report(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "online_mr_report")

    def open_mesh_report(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "mesh_analysis_report")

    def open_mesh_link_detail_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "mesh_link_detail_export")

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
        site_id = self._site(site_id)
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

    def query_metric_page(
        self,
        site_id: str,
        session_id: str,
        metric_types: list[str],
        *,
        start_time: str = "",
        end_time: str = "",
        limit: int = 1_000,
        offset: int = 0,
        downsample: str = OnlineMrDownsampleMode.NONE.value,
        bucket_seconds: int = 1,
    ):
        return self.query_service.query_metric_page(
            self._site(site_id),
            session_id,
            [OnlineMrMetricType(value) for value in metric_types],
            start_time=start_time or None,
            end_time=end_time or None,
            limit=limit,
            offset=offset,
            downsample=downsample,
            bucket_seconds=bucket_seconds,
        )

    def query_switch_rssi_windows(
        self,
        site_id: str,
        session_id: str,
        source: str,
        *,
        start_time: str = "",
        end_time: str = "",
        limit: int = 200,
        offset: int = 0,
    ):
        return self.query_service.query_switch_rssi_windows(
            self._site(site_id),
            session_id,
            OnlineMrSwitchRssiSource(source),
            start_time=start_time or None,
            end_time=end_time or None,
            limit=limit,
            offset=offset,
        )

    def query_timeline(self, site_id: str, session_id: str, *, limit: int = 500, offset: int = 0):
        return self.query_service.query_timeline(self._site(site_id), session_id, limit=limit, offset=offset)

    def database_summary(self, site_id: str, session_id: str):
        return self.query_service.get_database_summary(self._site(site_id), session_id)

    def artifacts(self, site_id: str, session_id: str):
        return self.query_service.list_artifacts(self._site(site_id), session_id)

    def notes(self, site_id: str, session_id: str, *, limit: int = 200, offset: int = 0):
        return self.query_service.list_notes(self._site(site_id), session_id, limit=limit, offset=offset)

    def _start_task(
        self,
        site_id: str,
        task_type: str,
        params: dict[str, object],
        *,
        on_complete=None,
        task_id: str = "",
    ) -> RailTransitTaskDTO:
        if task_type not in self._TASK_NAMES:
            raise RailTransitWebError("TASK_NOT_ALLOWED", "不支持的轨交 Web 任务")
        task_id = str(task_id or f"rail-web-{uuid4().hex}")
        job_params = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": self._TASK_NAMES[task_type],
            "owner": self._OWNER,
            "task_source": "local",
            **params,
        }
        try:
            self.process_adapter.start_job(
                BackgroundJob(job_id=task_id, task_type=task_type, params=job_params),
                on_complete=on_complete,
            )
        except TaskResourceConflictError as exc:
            requested_keys = {
                str(value)
                for value in job_params.get("resource_keys", [])
                if str(value or "").strip()
            }
            if (
                bool(job_params.get("reuse_equivalent_task"))
                and exc.task.task_type == task_type
                and set(exc.task.resource_keys) == requested_keys
            ):
                return self._task_dto(site_id, exc.task)
            code = "TRACKSIDE_AP_OPTICAL_UPDATE_RUNNING" if task_type == "trackside_ap_optical_update" else "TASK_RESOURCE_BUSY"
            raise RailTransitWebError(code, str(exc)) from exc
        return self.get_task(site_id, task_id)

    def _start_artifact_task(
        self,
        site_id: str,
        task_type: str,
        params: dict[str, object],
        reservation: ReservedWebArtifact,
        *,
        task_id: str,
    ) -> RailTransitTaskDTO:
        def completed(value: LocalProcessCompletion) -> None:
            if value.exit_code == 0 and not value.cancelled:
                try:
                    self.artifact_store.complete(reservation)
                except WebArtifactError:
                    self.artifact_store.fail(reservation)
            else:
                self.artifact_store.fail(reservation)

        try:
            return self._start_task(
                site_id,
                task_type,
                params,
                on_complete=completed,
                task_id=task_id,
            )
        except Exception:
            self.artifact_store.fail(reservation)
            raise

    def _start_export(
        self,
        site_id: str,
        job: ExportJob,
        action: str,
        reservation: ReservedWebArtifact,
        *,
        resource_keys: list[str] | None = None,
        cleanup_paths: Sequence[Path] = (),
    ) -> RailTransitTaskDTO:
        def completed(value: LocalProcessCompletion) -> None:
            try:
                if value.exit_code == 0 and not value.cancelled:
                    try:
                        self.artifact_store.complete(reservation)
                    except WebArtifactError:
                        self.artifact_store.fail(reservation)
                else:
                    payload = value.payload or {}
                    failure_message = str(
                        payload.get("error_message")
                        or payload.get("error")
                        or "报告不可用"
                    )
                    self.artifact_store.fail(reservation, failure_message)
            finally:
                self._cleanup_staging_paths(cleanup_paths)

        try:
            self.export_adapter.start_export(
                job,
                task_name=action,
                owner=self._OWNER,
                public_result={
                    "artifact_id": reservation.artifact_id,
                    "artifact_name": reservation.display_name,
                    "artifact_source": reservation.source,
                    "artifact_type": reservation.artifact_type,
                },
                resource_keys=resource_keys,
                on_complete=completed,
            )
        except TaskResourceConflictError as exc:
            self.artifact_store.fail(reservation)
            code = (
                "TRACKSIDE_AP_OPTICAL_UPDATE_RUNNING"
                if exc.task.task_type == "trackside_ap_optical_update"
                else "TASK_RESOURCE_BUSY"
            )
            raise RailTransitWebError(code, str(exc)) from exc
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        snapshot = self._snapshot(site_id, job.job_id)
        return RailTransitTaskDTO(
            task_id=job.job_id,
            status=snapshot.status.value,
            action=action,
            artifact_id=reservation.artifact_id,
            artifact_name=reservation.display_name,
        )

    @staticmethod
    def _cleanup_staging_paths(paths: Sequence[Path]) -> None:
        for raw_path in paths:
            path = Path(raw_path)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            for parent in (path.parent, path.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break

    def _snapshot(self, site_id: str, task_id: str):
        snapshot = self.task_service.repository(site_id).get(str(task_id or ""))
        if snapshot is None or not self._authorized(snapshot) or snapshot.site_name != site_id:
            raise RailTransitWebError("TASK_NOT_FOUND", "任务不存在或不属于当前局点")
        return snapshot

    def _authorized(self, snapshot) -> bool:
        return (
            snapshot.owner == self._OWNER
            and snapshot.source == "local"
            and snapshot.task_type in self._ALLOWED_TASK_TYPES
        )

    def _task_dto(self, site_id: str, snapshot) -> RailTransitTaskDTO:
        snapshot = sanitize_web_export_snapshot(snapshot)
        artifact = self.artifact_store.artifact_status(
            site_id,
            snapshot.task_id,
            owner=self._OWNER,
            source_task_types=self._ARTIFACT_TASK_TYPES,
        )
        metadata = artifact if artifact and artifact.get("artifact_state") == "AVAILABLE" else None
        artifact_source = str((artifact or {}).get("source") or "")
        action = self._ARTIFACT_ACTIONS.get(artifact_source, self._ACTIONS.get(snapshot.task_type, snapshot.task_type))
        artifact_task = snapshot.task_type in self._ARTIFACT_TASK_TYPES.values()
        artifact_state = str((artifact or {}).get("artifact_state") or "")
        if artifact_task and snapshot.status is TaskState.COMPLETED and not artifact_state:
            artifact_state = "MISSING"
        artifact_id = str((artifact or {}).get("artifact_id") or "")
        artifact_name = str((artifact or {}).get("display_name") or "")
        if not artifact_id:
            artifact_id = str(snapshot.result.get("artifact_id") or "")
        if not artifact_name:
            artifact_name = str(snapshot.result.get("artifact_name") or "")
        result_summary = self._result_summary(snapshot.task_type, snapshot.result)
        if snapshot.task_type == "online_mr_session_delete" and not result_summary.get("session_id"):
            resource_prefix = f"online_mr_session:{site_id}:"
            session_ids = [
                value.removeprefix(resource_prefix)
                for value in snapshot.resource_keys
                if value.startswith(resource_prefix) and value.removeprefix(resource_prefix)
            ]
            if len(session_ids) == 1:
                result_summary["session_id"] = session_ids[0]
        return RailTransitTaskDTO(
            task_id=snapshot.task_id,
            status=snapshot.status.value,
            action=action,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            available=bool(metadata and metadata.get("completed") is True),
            artifact_state=artifact_state,
            artifact_message=str((artifact or {}).get("artifact_message") or ("导出文件已不存在" if artifact_state == "MISSING" else "")),
            sha256=str((metadata or {}).get("sha256") or ""),
            size_bytes=int((metadata or {}).get("size_bytes") or 0),
            message=redact_web_task_text(snapshot.message),
            error_message=redact_web_task_text(snapshot.error_message),
            result_summary=result_summary,
        )

    @staticmethod
    def _result_summary(task_type: str, result: dict[str, object]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for key in (
            "count", "row_count", "train_count", "success_count", "failed_count",
            "imported_count", "duplicate_count", "parsed_record_count", "member_count",
            "raw_archived_count", "parsed_source_count",
            "mesh_samples", "channel_busy_samples", "fping_samples", "iperf_samples", "issue_count",
            "session_id", "status", "scope", "target_label", "target_count", "skipped_count",
            "fit_ap_resource_count", "fit_ap_optical_success_count", "fit_ap_optical_failed_count",
            "candidate_ap_interface_count", "current_lldp_port_count", "preserved_lldp_port_count",
            "concurrency", "requested_concurrency", "effective_concurrency",
            "platform_concurrency_limit", "fit_ap_effective_concurrency",
            "session_deleted", "parsed_data_deleted", "artifacts_deleted",
            "managed_files_deleted", "artifact_count", "mapping_records_deleted",
            "task_records_deleted", "error_code", "error_message",
            "already_deleted", "delete_raw_archive", "delete_parsed_data",
            "already_deleted_count", "delete_generated_reports", "deleted_files",
            "deleted_file_count", "missing_file_count", "deleted_reports",
            "parsed_links", "parsed_events", "parsed_issues", "source_file_id",
            "scanned_count", "valid_command_count", "blocking_error_count",
            "snapshot_id", "business_revision", "export_revision",
            "content_sha256", "export_content_sha256", "snapshot_created_at",
            "export_kind", "identity_revision", "abnormal_count",
            "unresolved_count", "ambiguous_count", "identity_distinct_count",
            "snapshot_build_ms", "snapshot_retry_count", "export_render_ms",
        ):
            value = result.get(key)
            if isinstance(value, (bool, int, float, str)):
                summary[key] = value
        source_revisions = result.get("source_revisions")
        if isinstance(source_revisions, dict) and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in source_revisions.items()
        ):
            summary["source_revisions"] = dict(source_revisions)
        round_summaries = result.get("round_summaries")
        if isinstance(round_summaries, list):
            summary["round_summaries_count"] = len(round_summaries)
        for key in ("rows", "items", "generated_files"):
            value = result.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
        created_session_ids = result.get("created_session_ids")
        if isinstance(created_session_ids, list) and all(isinstance(item, str) for item in created_session_ids):
            summary["created_session_ids"] = created_session_ids
        for key in ("warnings", "failed_items"):
            values = result.get(key)
            if isinstance(values, list) and all(isinstance(item, str) for item in values):
                summary[key] = values[:20]
        if task_type == "car_network_generate_point_table":
            raw_nodes = result.get("nodes")
            if not isinstance(raw_nodes, list):
                summary["nodes_available"] = False
                summary["nodes_error"] = "点表生成任务未返回有效的节点列表"
                return summary
            normalized_nodes: list[dict[str, object]] = []
            for raw_node in raw_nodes:
                if not isinstance(raw_node, dict):
                    summary["nodes_available"] = False
                    summary["nodes_error"] = "点表生成任务返回了无效节点数据"
                    return summary
                try:
                    normalized_nodes.append(
                        CarNetworkPointRowDTO.model_validate(raw_node).model_dump()
                    )
                except ValueError:
                    summary["nodes_available"] = False
                    summary["nodes_error"] = "点表生成任务返回了无效节点数据"
                    return summary
            summary["nodes"] = normalized_nodes
            summary["nodes_count"] = len(normalized_nodes)
            summary["nodes_available"] = True
            generated_nodes_count = result.get("generated_nodes_count")
            if isinstance(generated_nodes_count, int) and generated_nodes_count >= 0:
                summary["generated_nodes_count"] = generated_nodes_count
            for key in ("target_train", "target_train_display", "preview_status", "preview_message"):
                value = result.get(key)
                if isinstance(value, str):
                    summary[key] = value
        return summary

    def _open_artifact(
        self,
        site_id: str,
        artifact_id: str,
        source: str,
        artifact_type: str = "xlsx",
    ) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner=self._OWNER,
                source=source,
                artifact_type=artifact_type,
                task_type=self._ARTIFACT_TASK_TYPES[source],
            )
        except WebArtifactError as exc:
            raise RailTransitWebError("ARTIFACT_INVALID", str(exc)) from exc
        return path, name

    @staticmethod
    def _point_row(node: CarNetworkNode) -> CarNetworkPointRowDTO:
        return CarNetworkPointRowDTO.model_validate(asdict(node))

    def _point_nodes(self, rows: list[dict[str, object]]) -> list[CarNetworkNode]:
        nodes: list[CarNetworkNode] = []
        seen: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows, start=1):
            try:
                node = node_from_mapping(row)
                self._validate_point_node(node, row_number)
            except (TypeError, ValueError) as exc:
                raise RailTransitWebError("POINT_TABLE_ROW_INVALID", str(exc)) from exc
            key = self._point_key(node)
            if key in seen:
                raise RailTransitWebError(
                    "POINT_TABLE_DUPLICATE",
                    f"第{row_number}行节点重复：{' / '.join(key)}",
                )
            seen.add(key)
            nodes.append(node)
        return nodes

    def _vehicle_mapping_rows(self, site_id: str) -> list[dict[str, object]]:
        return [asdict(row) for row in VehicleMrOnlineStore(self.paths, site_id).list_mappings()]

    @staticmethod
    def _vehicle_mapping_key(row: VehicleMrTrainMappingDTO) -> str:
        return str(row.train_no or row.train_id or row.train_display_name).strip().casefold()

    @classmethod
    def _vehicle_peer_owners(cls, rows: dict[str, VehicleMrTrainMappingDTO]) -> dict[str, str]:
        owners: dict[str, str] = {}
        for key, row in rows.items():
            for peer in (row.tc1_peer_name, row.tc2_peer_name):
                normalized = peer.strip().casefold()
                if normalized:
                    owners[normalized] = key
        return owners

    @staticmethod
    def _validate_point_node(node: CarNetworkNode, row_number: int) -> None:
        if not (node.train_id or node.train_no):
            raise ValueError(f"第{row_number}行 列车标识：必填")
        if not node.node_name:
            raise ValueError(f"第{row_number}行 节点名称：必填")
        if not node.node_type:
            raise ValueError(f"第{row_number}行 节点类型：必填")

    @staticmethod
    def _point_key(node: CarNetworkNode) -> tuple[str, str]:
        return (
            canonical_train_id_for(node.train_id, node.train_no, node.display_name) or str(node.train_no or node.train_id).strip().casefold(),
            node.normalized_name.strip().casefold(),
        )

    @staticmethod
    def _target_train_payload(value: dict[str, object]) -> dict[str, str]:
        identity = normalize_train_identity(
            value.get("canonical_train_id"),
            value.get("train_id"),
            value.get("train_no"),
            value.get("train_name"),
            value.get("display_name"),
        )
        if not identity.canonical_train_id:
            return {}
        return {
            "canonical_train_id": identity.canonical_train_id,
            "train_id": str(value.get("train_id") or identity.canonical_train_id),
            "train_no": identity.train_no,
            "display_name": str(value.get("display_name") or value.get("train_name") or identity.display_name),
            "ct_mr_id": str(value.get("ct_mr_id") or ""),
            "ct_mr_name": str(value.get("ct_mr_name") or ""),
            "tc_mr_id": str(value.get("tc_mr_id") or ""),
            "tc_mr_name": str(value.get("tc_mr_name") or ""),
        }

    def _read_table_upload(
        self,
        site_id: str,
        file_name: str,
        content: bytes,
        reader: Callable[[Path], list[dict[str, object | None]]],
    ) -> list[dict[str, object | None]]:
        name = Path(str(file_name or "")).name
        suffix = Path(name).suffix.casefold()
        if suffix not in self._TABLE_SUFFIXES:
            raise RailTransitWebError("FILE_TYPE_INVALID", "仅支持 XLSX/CSV 文件")
        if not content:
            raise RailTransitWebError("FILE_EMPTY", "导入文件为空")
        if len(content) > 10 * 1024 * 1024:
            raise RailTransitWebError("FILE_TOO_LARGE", "导入文件不得超过 10 MiB")
        root = (self.paths.runtime_cache_dir / "rail_web_table_previews" / site_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = (root / f"{uuid4().hex}{suffix}").resolve()
        self._require_within(target, root)
        try:
            target.write_bytes(content)
            return reader(target)
        except RailTransitWebError:
            raise
        except Exception as exc:
            message = redact_web_task_text(str(exc)) or "文件格式或元数据校验失败"
            raise RailTransitWebError("IMPORT_INVALID", message) from exc
        finally:
            target.unlink(missing_ok=True)

    @staticmethod
    def _duplicate_strategy(value: str) -> str:
        strategy = str(value or "replace").strip().casefold()
        if strategy not in {"replace", "skip", "error"}:
            raise RailTransitWebError("DUPLICATE_STRATEGY_INVALID", "重复策略无效")
        return strategy

    @staticmethod
    def _task_window_blocked(action: str, exc: Exception) -> NoReturn:
        raise RailTransitWebError(
            "BLOCKED_ON_TASK_WINDOW",
            f"{action}等待公共 Artifact source/任务授权：{exc}",
        ) from exc

    def _validated_staged_files(self, site_id: str, staging_dir: Path, uploads: list[Path]) -> list[Path]:
        expected_root = (self.paths.runtime_cache_dir / "rail_web_uploads" / site_id).resolve()
        if staging_dir.is_symlink():
            raise RailTransitWebError("STAGING_INVALID", "MESH 临时目录不受控")
        staging = staging_dir.resolve()
        if staging.parent != expected_root or not staging.is_dir():
            raise RailTransitWebError("STAGING_INVALID", "MESH 临时目录不受控")
        if not uploads:
            raise RailTransitWebError("FILE_REQUIRED", "至少选择一个 MESH 原始日志文件")
        result: list[Path] = []
        for path in uploads:
            if path.is_symlink():
                raise RailTransitWebError("FILE_PATH_INVALID", "MESH 上传文件路径无效")
            candidate = path.resolve()
            if candidate.parent != staging or not candidate.is_file():
                raise RailTransitWebError("FILE_PATH_INVALID", "MESH 上传文件路径无效")
            if not candidate.name.casefold().endswith(self._UPLOAD_SUFFIXES):
                raise RailTransitWebError("FILE_TYPE_INVALID", "MESH 导入仅支持 LOG/TXT/GZ 文件")
            result.append(candidate)
        return result

    def _cleanup_staging(self, site_id: str, staging_dir: Path) -> None:
        root = (self.paths.runtime_cache_dir / "rail_web_uploads" / self._site(site_id)).resolve()
        staging = staging_dir.resolve()
        if staging.parent != root or staging == root:
            return
        try:
            shutil.rmtree(staging)
        except FileNotFoundError:
            pass

    def _online_mr_session_dir(self, site_id: str, session_id: str):
        try:
            detail = self.query_service.get_session(site_id, session_id)
        except OnlineMrQueryError as exc:
            raise RailTransitWebError("SESSION_NOT_FOUND", str(exc)) from exc
        root = self.paths.online_mr_root(site_id).resolve()
        candidate = root / detail.session_path_reference
        if candidate.is_symlink():
            raise RailTransitWebError("SESSION_NOT_FOUND", "Online MR 会话不存在")
        session_dir = candidate.resolve()
        self._require_within(session_dir, root)
        if not session_dir.is_dir() or session_dir.is_symlink():
            raise RailTransitWebError("SESSION_NOT_FOUND", "Online MR 会话不存在")
        return detail, session_dir

    def _reconcile_owned_orphans(self, site_id: str):
        repository = self.task_service.repository(site_id)
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        owned_pids = {
            item.owner_pid
            for item in repository.list(statuses=active, limit=1000)
            if item.site_name == site_id and self._authorized(item) and item.owner_pid > 0
        }
        if not owned_pids:
            return []
        return repository.reconcile_orphaned_local_tasks(
            lambda pid: True if pid not in owned_pids else self.task_service._is_process_alive(pid)
        )

    def _cleanup_recovered_task(self, site_id: str, snapshot) -> bool:
        cleaned = False
        if snapshot.task_type == self._ARTIFACT_TASK_TYPES["trackside_ap_business"]:
            try:
                cleaned = cleanup_export_snapshot(
                    self.paths.staging_dir,
                    site_id=site_id,
                    task_id=snapshot.task_id,
                ) or cleaned
            except ValueError:
                pass
        if snapshot.task_type == "mesh_log_import":
            job_path = self.paths.runtime_cache_dir / "background_jobs" / f"{snapshot.task_id}.json"
            try:
                payload = json.loads(job_path.read_text(encoding="utf-8"))
                params = dict(payload.get("params") or {})
                files = [Path(str(value)) for value in params.get("files") or ()]
                if params.get("site_name") == site_id and files:
                    self._cleanup_staging(site_id, files[0].parent)
                    cleaned = True
            except (OSError, ValueError, TypeError):
                pass
        for directory, suffix in (
            (self.paths.runtime_cache_dir / "background_jobs", ".json"),
            (self.paths.runtime_cache_dir / "background_jobs", ".cancel"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json.tmp"),
        ):
            path = (directory / f"{snapshot.task_id}{suffix}").resolve()
            try:
                if directory.resolve() in path.parents and path.exists():
                    path.unlink(missing_ok=True)
                    cleaned = True
            except OSError:
                pass
        return cleaned

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise RailTransitWebError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        root = self.paths.site_dir(value).resolve()
        self._require_within(root, self.paths.sites_dir.resolve())
        if not root.is_dir():
            raise RailTransitWebError("SITE_CONTEXT_INVALID", "当前局点不存在")
        return value

    def _site_display_name(self, site_id: str) -> str:
        try:
            metadata = SiteManager(self.paths).load_site_metadata(site_id)
        except ValueError as exc:
            raise RailTransitWebError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        display_name = str(metadata.get("display_name") or "").strip()
        if not display_name:
            raise RailTransitWebError("SITE_DISPLAY_NAME_INVALID", "当前局点缺少显示名称")
        return display_name

    @classmethod
    def _safe_name(cls, value: str) -> str:
        return cls._SAFE_NAME.sub("_", Path(value).name).strip("._ ")

    @classmethod
    def _report_name(cls, value: str) -> str:
        name = cls._safe_name(value)
        if not name.casefold().endswith(".xlsx"):
            name += ".xlsx"
        return name

    @staticmethod
    def _require_within(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RailTransitWebError("PATH_OUTSIDE_ROOT", "路径不在受控目录") from exc
        if path == root:
            raise RailTransitWebError("PATH_OUTSIDE_ROOT", "文件路径不能等于受控目录")


__all__ = ["RailTransitWebApplicationService", "RailTransitWebError"]
