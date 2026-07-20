from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, NoReturn
from uuid import uuid4

from netconsole.application.web_artifacts import ReservedWebArtifact, WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.online_mr import (
    OnlineMrDownsampleMode,
    OnlineMrManualNoteDTO,
    OnlineMrMetricType,
    OnlineMrSwitchRssiSource,
)
from netconsole.models.api.rail_transit_web import (
    CarNetworkPointPreviewDTO,
    CarNetworkPointPreviewRowDTO,
    CarNetworkPointRowDTO,
    CarNetworkPointTableDTO,
    RailTransitTaskDTO,
)
from netconsole.models.api.trackside_ap_business import (
    TracksideApPlanDTO,
    TracksideApPlanPreviewDTO,
    TracksideApPlanPreviewRowDTO,
    TracksideApPlanRowDTO,
)
from netconsole.models.api.vehicle_mr_online import (
    VehicleMrMappingPreviewDTO,
    VehicleMrMappingPreviewRowDTO,
    VehicleMrTrainMappingDTO,
)
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_task_builders import (
    car_network_point_table_spec,
    online_mr_report_xlsx_spec,
    repository_query_source,
    table_xlsx_source_spec,
    table_xlsx_spec,
    vehicle_mr_history_xlsx_spec,
)
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text, sanitize_web_export_snapshot
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
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
from netconsole.services.trackside_ap_plan_io import (
    TRACKSIDE_PLAN_COLUMNS,
    TRACKSIDE_PLAN_COLUMN_WIDTHS,
    TRACKSIDE_PLAN_HEADERS,
    normalize_trackside_plan_row,
    normalize_trackside_plan_rows,
    read_trackside_plan_file,
)
from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore
from netconsole.services.rail_transit.vehicle_mr_mapping_io import (
    VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS,
    VEHICLE_MR_MAPPING_TEMPLATE_ROWS,
    normalize_vehicle_mr_mapping_row,
    read_vehicle_mr_mapping_file,
)


class RailTransitWebError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RailTransitWebApplicationService:
    """轨交 Web 用例边界；任务、导出和 Artifact 都复用正式生命周期。"""

    _TASK_NAMES = {
        "mesh_log_import": "MESH 原始日志导入分析",
        "mesh_bundle_import": "MESH ZIP 批量导入分析",
        "car_network_diagnostic": "车内通信检测",
        "car_network_generate_point_table": "从设备管理生成车内通信点表",
        "car_network_save_point_table": "保存车内通信点表",
        "trackside_ap_optical_update": "轨旁 AP 光衰更新",
        "trackside_ap_plan_save": "保存轨旁 AP 规划",
        "vehicle_mr_online_refresh_all": "列车在线状态刷新",
        "vehicle_mr_ap_mapping_refresh": "轨旁 AP 映射刷新",
        "vehicle_mr_mapping_save": "列车 MR 映射保存",
        "vehicle_mr_online_collection_start": "列车在线连续采集",
        "online_mr_parse": "Online MR 会话解析",
    }
    _UPLOAD_SUFFIXES = (".log", ".txt", ".log.gz", ".txt.gz")
    _TABLE_SUFFIXES = {".xlsx", ".csv"}
    _SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")
    _ALLOWED_TASK_TYPES = {
        *_TASK_NAMES,
        "web_export_online_mr_report_xlsx",
        "web_export_mesh_analysis_report",
        "web_export_car_network_point_table",
        "web_export_trackside_ap_business",
        "web_export_table_xlsx",
        "web_export_vehicle_mr_history_xlsx",
    }
    _OWNER = "web_rail_transit"
    _ARTIFACT_TASK_TYPES = {
        "online_mr_report": "web_export_online_mr_report_xlsx",
        "mesh_analysis_report": "web_export_mesh_analysis_report",
        "car_network_point_table": "web_export_car_network_point_table",
        "trackside_ap_business": "web_export_trackside_ap_business",
        "trackside_ap_plan": "web_export_table_xlsx",
        "vehicle_mr_history": "web_export_vehicle_mr_history_xlsx",
        "vehicle_mr_mapping_template": "web_export_table_xlsx",
    }
    _ACTIONS = {
        "web_export_online_mr_report_xlsx": "online_mr_report",
        "web_export_mesh_analysis_report": "mesh_analysis_report",
        "web_export_car_network_point_table": "car_network_point_table_export",
        "web_export_trackside_ap_business": "trackside_ap_business_export",
        "web_export_table_xlsx": "trackside_ap_plan_export",
        "web_export_vehicle_mr_history_xlsx": "vehicle_mr_history_export",
    }
    _ARTIFACT_ACTIONS = {
        "online_mr_report": "online_mr_report",
        "mesh_analysis_report": "mesh_analysis_report",
        "car_network_point_table": "car_network_point_table_export",
        "trackside_ap_business": "trackside_ap_business_export",
        "trackside_ap_plan": "trackside_ap_plan_export",
        "vehicle_mr_history": "vehicle_mr_history_export",
        "vehicle_mr_mapping_template": "vehicle_mr_mapping_template_export",
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
        artifact_store: WebArtifactStore | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.export_adapter = export_adapter
        self.query_service = query_service or OnlineMrQueryService(paths)
        self.mesh_query_service = mesh_query_service or MeshAnalysisQueryService(paths)
        self.artifact_store = artifact_store or WebArtifactStore(paths, task_service)

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
                        if file_size > 20 * 1024 * 1024:
                            raise RailTransitWebError("FILE_TOO_LARGE", "单个 MESH 日志不得超过 20 MiB")
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
        selected_mr_id = str(linked_mr_id or "").strip()
        if selected_mr_id:
            detail = RailTransitBaseDataQueryService(self.paths).get_mr(site_id, selected_mr_id)
            if detail is None or detail.mr.device_id is None:
                raise RailTransitWebError("PROFILE_DEVICE_NOT_FOUND", "所选基础资料 MR 不存在或未绑定设备")
            linked_device_id = int(detail.mr.device_id)
        try:
            return MeshStorageService(site_id, self.paths).create_mr_profile(
                name,
                notes=str(notes or "").strip(),
                linked_device_id=linked_device_id,
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

    def start_trackside_ap_business_export(self, site_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
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
                preferred_name=f"轨旁AP业务_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
            )
        except WebArtifactError as exc:
            self._task_window_blocked("轨旁 AP 业务导出", exc)
        job = ExportJob(
            job_id=task_id,
            job_type="trackside_ap_business",
            site_name=site_id,
            output_path=str(reservation.output_path),
            db_path=str(self.paths.site_db_path(site_id)),
            params={"language": "zh_CN"},
        )
        return self._start_export(
            site_id,
            job,
            "trackside_ap_business_export",
            reservation,
        )

    def open_trackside_ap_business_export(
        self,
        site_id: str,
        artifact_id: str,
    ) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "trackside_ap_business")

    def get_trackside_ap_plan(self, site_id: str) -> TracksideApPlanDTO:
        site_id = self._site(site_id)
        rows = AcRepository(Database(self.paths.site_db_path(site_id))).list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
        items = [
            TracksideApPlanRowDTO.model_validate(normalize_trackside_plan_row(row, row_number=index))
            for index, row in enumerate(rows, start=2)
        ]
        return TracksideApPlanDTO(items=items, total=len(items))

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
        raw_rows = self._read_table_upload(site_id, file_name, content, read_trackside_plan_file)
        existing = {row.station_name.casefold(): row for row in self.get_trackside_ap_plan(site_id).items}
        imported: set[str] = set()
        preview_rows: list[TracksideApPlanPreviewRowDTO] = []
        duplicate_count = 0
        error_count = 0
        valid_count = 0
        for row_number, raw in enumerate(raw_rows, start=2):
            try:
                row = TracksideApPlanRowDTO.model_validate(
                    normalize_trackside_plan_row(dict(raw), row_number=row_number)
                )
            except (TypeError, ValueError) as exc:
                error_count += 1
                preview_rows.append(
                    TracksideApPlanPreviewRowDTO(
                        row_number=row_number,
                        status="error",
                        message=str(exc),
                    )
                )
                continue
            key = row.station_name.casefold()
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
                        row=row,
                    )
                )
                if strategy == "replace":
                    existing[key] = row
                imported.add(key)
                continue
            valid_count += 1
            imported.add(key)
            existing[key] = row
            preview_rows.append(
                TracksideApPlanPreviewRowDTO(
                    row_number=row_number,
                    status="valid",
                    key=row.station_name,
                    row=row,
                )
            )
        can_apply = error_count == 0 and (strategy != "error" or duplicate_count == 0)
        result_rows = list(existing.values()) if can_apply else []
        for index, row in enumerate(result_rows):
            row.sort_order = index
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
        )

    def start_trackside_ap_plan_save(
        self,
        site_id: str,
        *,
        rows: list[dict[str, object | None]],
        explicit_confirmation: bool,
        audit: dict[str, str] | None = None,
    ) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        if not explicit_confirmation:
            raise RailTransitWebError("CONFIRMATION_REQUIRED", "保存轨旁 AP 规划前必须明确确认")
        normalized = normalize_trackside_plan_rows(rows)
        return self._start_task(
            site_id,
            "trackside_ap_plan_save",
            {
                "mode": TRACKSIDE_AP_PLAN_MODE,
                "rows": normalized,
                "audit": {str(key): str(value) for key, value in (audit or {}).items()},
                "explicit_confirmation": True,
            },
        )

    def start_trackside_ap_plan_export(self, site_id: str, *, template: bool) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
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
                preferred_name="轨旁AP规划模板.xlsx" if template else "轨旁AP规划.xlsx",
            )
        except WebArtifactError as exc:
            self._task_window_blocked("轨旁 AP 规划导出", exc)
        columns = [
            {
                "key": field,
                "title": TRACKSIDE_PLAN_HEADERS[index],
                "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field),
            }
            for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)
        ]
        spec = (
            table_xlsx_spec(
                reservation.output_path,
                columns=columns,
                rows=[],
                sheet_name="轨旁AP规划",
                title="轨旁 AP 规划模板",
                open_dir_on_success=False,
                allow_inline_rows=True,
                inline_reason="轨旁 AP 规划空白模板",
            )
            if template
            else table_xlsx_source_spec(
                reservation.output_path,
                columns=columns,
                source=repository_query_source(
                    db_path=self.paths.site_db_path(site_id),
                    repository="ac_repository",
                    method="list_trackside_ap_plan",
                    filters={"mode": TRACKSIDE_AP_PLAN_MODE},
                ),
                sheet_name="轨旁AP规划",
                title="轨旁 AP 规划",
                open_dir_on_success=False,
            )
        )
        return self._start_export(
            site_id,
            replace(spec.to_job(task_id), site_name=site_id),
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
        train = next((item for item in trains if selected_train in {item.id, item.train_no, item.name}), None)
        inspection = TrainCommunicationPointTableService(self.paths).inspect(
            site_id,
            selected_train,
            train_no=train.train_no if train is not None else "",
            display_name=train.name if train is not None else "",
        )
        if inspection.status == POINT_TABLE_MISSING:
            raise RailTransitWebError("TRAIN_COMMUNICATION_POINT_TABLE_MISSING", inspection.message)
        if inspection.status == POINT_TABLE_INVALID:
            raise RailTransitWebError("TRAIN_COMMUNICATION_POINT_TABLE_INVALID", inspection.message)
        return self._start_task(site_id, "car_network_diagnostic", {"train_id": selected_train})

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
        return self._start_task(
            self._site(site_id),
            "trackside_ap_optical_update",
            {
                "station": str(station or "").strip(),
                "ap_uuid": str(ap_uuid or "").strip(),
                "ap_mac": str(ap_mac or "").strip(),
                "ap_name": str(ap_name or "").strip(),
            },
        )

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
        detail = self.query_service.get_session(site_id, session_id)
        root = self.paths.online_mr_root(site_id).resolve()
        session_dir = (root / detail.session_path_reference).resolve()
        self._require_within(session_dir, root)
        if not session_dir.is_dir() or session_dir.is_symlink():
            raise RailTransitWebError("SESSION_NOT_FOUND", "Online MR 会话不存在")
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
        )
        job = online_mr_report_xlsx_spec(
            reservation.output_path,
            session_dir=session_dir,
            title="Online MR 分析报告",
            open_dir_on_success=False,
        ).to_job(task_id)
        return self._start_export(site_id, replace(job, site_name=site_id), "online_mr_report", reservation)

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
            },
        )

    def start_mesh_report(self, site_id: str, session_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        try:
            context = self.mesh_query_service._context(site_id, session_id)
        except MeshAnalysisQueryError as exc:
            raise RailTransitWebError("MESH_SESSION_NOT_FOUND", str(exc)) from exc
        if context.detail_db is None or not context.detail_db.is_file():
            raise RailTransitWebError("MESH_RESULT_NOT_FOUND", "MESH 结构化分析结果不存在")
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
                    "source_file_ids": [context.source_id],
                    "options": {"report_name": f"{context.mr_name} MESH 分析报告"},
                }
            },
        )
        return self._start_export(site_id, job, "mesh_analysis_report", reservation)

    def get_task(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        return self._task_dto(site_id, self._snapshot(site_id, task_id))

    def cancel_task(self, site_id: str, task_id: str) -> RailTransitTaskDTO:
        site_id = self._site(site_id)
        snapshot = self._snapshot(site_id, task_id)
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
            if item.site_name != site_id or not self._authorized(item):
                continue
            self._cleanup_recovered_task(site_id, item)
            if item.task_type.startswith("web_export_"):
                self.artifact_store.recover_task(
                    site_id,
                    item.task_id,
                    owner=self._OWNER,
                    source_task_types=self._ARTIFACT_TASK_TYPES,
                    succeeded=item.status == TaskState.COMPLETED,
                )
        return [
            self._task_dto(site_id, item)
            for item in repository.list(limit=200)
            if item.site_name == site_id and self._authorized(item)
        ]

    def open_online_mr_report(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "online_mr_report")

    def open_mesh_report(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._open_artifact(site_id, artifact_id, "mesh_analysis_report")

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
    ) -> RailTransitTaskDTO:
        if task_type not in self._TASK_NAMES:
            raise RailTransitWebError("TASK_NOT_ALLOWED", "不支持的轨交 Web 任务")
        task_id = f"rail-web-{uuid4().hex}"
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
        self.process_adapter.start_job(
            BackgroundJob(job_id=task_id, task_type=task_type, params=job_params),
            on_complete=on_complete,
        )
        return self.get_task(site_id, task_id)

    def _start_export(
        self,
        site_id: str,
        job: ExportJob,
        action: str,
        reservation: ReservedWebArtifact,
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
            self.export_adapter.start_export(
                job,
                task_name=action,
                owner=self._OWNER,
                public_result={
                    "artifact_id": reservation.artifact_id,
                    "artifact_name": reservation.output_path.name,
                    "artifact_source": reservation.source,
                    "artifact_type": reservation.artifact_type,
                },
                on_complete=completed,
            )
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        snapshot = self._snapshot(site_id, job.job_id)
        return RailTransitTaskDTO(
            task_id=job.job_id,
            status=snapshot.status.value,
            action=action,
            artifact_id=reservation.artifact_id,
        )

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
        metadata = self.artifact_store.task_metadata(
            site_id,
            snapshot.task_id,
            owner=self._OWNER,
            source_task_types=self._ARTIFACT_TASK_TYPES,
        )
        artifact_source = str((metadata or {}).get("source") or "")
        action = self._ARTIFACT_ACTIONS.get(artifact_source, self._ACTIONS.get(snapshot.task_type, snapshot.task_type))
        return RailTransitTaskDTO(
            task_id=snapshot.task_id,
            status=snapshot.status.value,
            action=action,
            artifact_id=str((metadata or {}).get("artifact_id") or ""),
            available=bool(metadata and metadata.get("completed") is True),
            sha256=str((metadata or {}).get("sha256") or ""),
            size_bytes=int((metadata or {}).get("size_bytes") or 0),
            message=redact_web_task_text(snapshot.message),
            error_message=redact_web_task_text(snapshot.error_message),
            result_summary=self._result_summary(snapshot.result),
        )

    @staticmethod
    def _result_summary(result: dict[str, object]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for key in (
            "count", "row_count", "train_count", "success_count", "failed_count",
            "imported_count", "duplicate_count", "parsed_record_count", "member_count",
            "mesh_samples", "channel_busy_samples", "fping_samples", "iperf_samples", "issue_count",
        ):
            value = result.get(key)
            if isinstance(value, (bool, int, float, str)):
                summary[key] = value
        for key in ("rows", "items", "generated_files"):
            value = result.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
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
            str(node.train_no or node.train_id).strip().casefold(),
            node.normalized_name.strip().casefold(),
        )

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
        detail = self.query_service.get_session(site_id, session_id)
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
