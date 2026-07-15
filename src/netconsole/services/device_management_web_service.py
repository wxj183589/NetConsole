from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import BinaryIO
import uuid
from threading import RLock

from netconsole.application.desktop import DesktopActionService
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.core.sites import SiteManager
from netconsole.models.api.device_management import (
    DeviceCapabilityDTO,
    DeviceCollectionSummaryDTO,
    DeviceConnectionCommandDTO,
    DeviceConnectionTestDTO,
    DeviceDetailDTO,
    DeviceDetailItemDTO,
    DeviceEditPreviewDTO,
    DeviceEditPreviewRequestDTO,
    DeviceBatchRefreshRequestDTO,
    DeviceDeleteDTO,
    DeviceDeleteRequestDTO,
    DeviceDeletionTokenDTO,
    DeviceDeletionTokenRequestDTO,
    DeviceExternalTerminalActionDTO,
    DeviceExternalTerminalRequestDTO,
    DeviceExportRequestDTO,
    DeviceGroupAssignmentDTO,
    DeviceGroupAssignmentRequestDTO,
    DeviceGroupDeleteDTO,
    DeviceGroupDTO,
    DeviceGroupRequestDTO,
    DeviceImportConfirmRequestDTO,
    DeviceImportPreviewDTO,
    DeviceOmniPeekExportRequestDTO,
    DeviceSecureCrtExportRequestDTO,
    DeviceTaskBatchDTO,
    DeviceTaskReferenceDTO,
    DeviceWriteDTO,
    DeviceWriteRequestDTO,
    DeviceErrorSummaryDTO,
    DeviceFactDTO,
    DeviceGroupOptionDTO,
    DeviceListItemDTO,
    DevicePageDTO,
    DeviceTaskSummaryDTO,
)
from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS, Device
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.device_group_service import DeviceGroupService
from netconsole.services.device_import_export import DeviceImportExportService
from netconsole.services.diagnostic_download_service import DiagnosticDownloadService, run_batch_diagnostic_download
from netconsole.services.export.export_job import ExportJob
from netconsole.services.file_contract import attach_export_metadata
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.netmiko_connection import extract_sysname_from_prompt, sanitize_sensitive_text
from netconsole.services.job_center.worker_protocol import parse_event_line
from netconsole.utils.natural_sort import natural_text_key


DEVICE_CONNECTION_TEST_TASK_TYPE = "device_connection_test"
ACTIVE_TASK_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
DEVICE_IMPORT_PREVIEW_TTL_SECONDS = 15 * 60
DEVICE_IMPORT_CLAIM_GRACE_SECONDS = 60
DEVICE_DELETE_TOKEN_TTL_SECONDS = 5 * 60
MAX_DEVICE_IMPORT_BYTES = 16 * 1024 * 1024
WEB_TASK_OWNER = "web_device_management"
WEB_ARTIFACT_DIR = "web_artifacts"
WEB_IMPORT_STAGING_DIR = "web_staging"
DEVICE_TERMINAL_ACTION_IDS = {
    "securecrt": "terminal.securecrt",
    "putty": "terminal.putty",
    "xshell": "terminal.xshell",
}
EXPORT_TASK_TYPES = frozenset(
    {
        "device_export_device_csv",
        "device_export_device_template_csv",
        "device_export_securecrt_sessions",
        "device_export_omnipeek_name_table",
    }
)
DEVICE_COLLECT_TASK_TYPE = "device_detail_collect"
DEVICE_DIAGNOSTIC_TASK_TYPE = "device_diagnostic_download"
DEVICE_IMPORT_TASK_TYPE = "device_csv_import"
DEVICE_TASK_TYPES = frozenset(
    {
        DEVICE_CONNECTION_TEST_TASK_TYPE,
        DEVICE_COLLECT_TASK_TYPE,
        DEVICE_DIAGNOSTIC_TASK_TYPE,
        DEVICE_IMPORT_TASK_TYPE,
        *EXPORT_TASK_TYPES,
    }
)
SORT_FIELDS = {
    "name": lambda item: natural_text_key(item.name),
    "system_name": lambda item: natural_text_key(item.system_name),
    "primary_address": lambda item: natural_text_key(item.primary_address),
    "station": lambda item: natural_text_key(item.station),
    "device_type": lambda item: natural_text_key(item.device_type),
    "updated_at": lambda item: natural_text_key(item.updated_at),
    "status": lambda item: natural_text_key(item.connection_status),
}


class DeviceManagementWebService:
    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        desktop_action_service: DesktopActionService,
        site_name: str | None = None,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.desktop_action_service = desktop_action_service
        self.site_name = site_name
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self._start_lock = RLock()
        self._mutation_lock = RLock()
        self._delete_tokens: dict[str, dict[str, object]] = {}
        self._export_processes: dict[str, subprocess.Popen[str]] = {}
        self._export_artifacts: dict[str, dict[str, object]] = {}
        self._reconciled_import_sites: set[str] = set()

    def current_site_id(self) -> str:
        site = self.site_name or SiteManager(self.paths).get_current_site()
        selected = SiteManager(self.paths).validate_site_name(str(site or "demo"))
        with self._mutation_lock:
            if selected not in self._reconciled_import_sites:
                self._reconcile_import_audits(selected)
                self._cleanup_expired_import_previews(selected)
                self._reconciled_import_sites.add(selected)
        return selected

    def list_devices(
        self,
        *,
        search: str = "",
        group_id: int | None = None,
        ungrouped: bool = False,
        device_type: str = "",
        vendor: str = "",
        connection_status: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> DevicePageDTO:
        site = self.current_site_id()
        device_repository, group_repository, _ = self._repositories(site)
        groups = group_repository.list()
        group_names = {int(group.id): group.name for group in groups if group.id is not None}
        tasks = self._owned_web_tasks(
            self.task_service.repository(site).list(limit=1000),
            site,
            frozenset({DEVICE_CONNECTION_TEST_TASK_TYPE}),
        )
        devices = device_repository.list(
            search=search.strip() or None,
            vendor=vendor.strip() or None,
            device_type=device_type.strip() or None,
            group_filter="__ungrouped__" if ungrouped else group_id,
        )
        items = [self._list_item(device, group_names, self._latest_test(tasks, device)) for device in devices]
        selected_status = connection_status.strip().upper()
        if selected_status:
            items = [item for item in items if item.connection_status == selected_status]
        try:
            sort_key = SORT_FIELDS[sort_by]
        except KeyError as exc:
            raise ValueError("不支持的设备排序字段") from exc
        items.sort(key=sort_key, reverse=sort_order == "desc")
        total = len(items)
        total_pages = max(1, math.ceil(total / page_size))
        selected_page = min(max(1, page), total_pages)
        start = (selected_page - 1) * page_size
        return DevicePageDTO(
            items=items[start : start + page_size],
            groups=[DeviceGroupOptionDTO(id=int(group.id), name=group.name) for group in groups if group.id is not None],
            total=total,
            page=selected_page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_device_detail(self, device_uuid: str) -> DeviceDetailDTO:
        site = self.current_site_id()
        device_repository, group_repository, fact_repository = self._repositories(site)
        device = self._require_device(device_repository, device_uuid)
        groups = {int(group.id): group.name for group in group_repository.list() if group.id is not None}
        tasks = self._device_tasks(
            self._owned_web_tasks(
                self.task_service.repository(site).list(limit=1000),
                site,
            ),
            device,
        )
        list_item = self._list_item(device, groups, self._latest_test(tasks, device))
        fact = fact_repository.get_device_fact(device_uuid)
        collection = fact_repository.get_collect_run(str(fact.get("collect_run_uuid") or "")) if fact else None
        task_summaries = [self._task_summary(task, device) for task in tasks[:10]]
        collection_summary = self._collection_summary(collection, device)
        errors = self._recent_errors(tasks, collection, device)
        return DeviceDetailDTO(
            device=DeviceDetailItemDTO(
                **list_item.model_dump(),
                location=str(device.location or ""),
                mac_address=str(device.mac_address or ""),
                https_port=int(device.https_port) if device.https_port else None,
                remark=str(device.remark or ""),
                created_at=str(device.created_at or ""),
            ),
            fact=self._fact_summary(fact),
            recent_tasks=task_summaries,
            recent_collection=collection_summary,
            recent_errors=errors,
            connection_commands=self._connection_commands(device),
        )

    def list_groups(self) -> list[DeviceGroupDTO]:
        _device_repository, group_repository, _facts = self._repositories(self.current_site_id())
        counts = group_repository.counts()
        return [
            DeviceGroupDTO(id=int(group.id), name=group.name, device_count=counts.get(int(group.id), 0))
            for group in group_repository.list()
            if group.id is not None
        ]

    def create_device(self, payload: DeviceWriteRequestDTO) -> DeviceWriteDTO:
        site = self.current_site_id()
        device_repository, group_repository, _facts = self._repositories(site)
        device = self._device_from_write(payload, None, group_repository)
        created = device_repository.create(device)
        return DeviceWriteDTO(action="created", device=self.get_device_detail(str(created.device_uuid)).device)

    def update_device(self, device_uuid: str, payload: DeviceWriteRequestDTO) -> DeviceWriteDTO:
        site = self.current_site_id()
        device_repository, group_repository, _facts = self._repositories(site)
        existing = self._require_device(device_repository, device_uuid)
        updated = self._device_from_write(payload, existing, group_repository)
        saved = device_repository.update(updated)
        return DeviceWriteDTO(action="updated", device=self.get_device_detail(str(saved.device_uuid)).device)

    def duplicate_device(self, device_uuid: str) -> DeviceWriteDTO:
        site = self.current_site_id()
        device_repository, _group_repository, _facts = self._repositories(site)
        source = self._require_device(device_repository, device_uuid)
        record = source.to_record()
        record.update({"id": None, "device_uuid": None, "created_at": None, "updated_at": None})
        if str(record.get("name") or "").strip():
            record["name"] = f"{str(record['name']).strip()}-副本"
        created = device_repository.create(Device.from_mapping(record))
        return DeviceWriteDTO(action="duplicated", device=self.get_device_detail(str(created.device_uuid)).device)

    def issue_delete_token(self, payload: DeviceDeletionTokenRequestDTO) -> DeviceDeletionTokenDTO:
        site = self.current_site_id()
        device_repository, _groups, _facts = self._repositories(site)
        uuids = self._unique_ids(payload.device_uuids)
        for device_uuid in uuids:
            self._require_device(device_repository, device_uuid)
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=DEVICE_DELETE_TOKEN_TTL_SECONDS)
        with self._mutation_lock:
            self._delete_tokens[token] = {"site": site, "device_uuids": tuple(uuids), "expires": expires.timestamp()}
        return DeviceDeletionTokenDTO(confirmation_token=token, device_uuids=uuids, expires_at=expires.isoformat())

    def delete_devices(self, payload: DeviceDeleteRequestDTO) -> DeviceDeleteDTO:
        site = self.current_site_id()
        device_repository, _groups, _facts = self._repositories(site)
        uuids = self._unique_ids(payload.device_uuids)
        with self._mutation_lock:
            token = self._delete_tokens.pop(str(payload.confirmation_token), None)
        if not token or token.get("site") != site or float(token.get("expires") or 0) < datetime.now(UTC).timestamp():
            raise ValueError("删除确认 token 无效或已过期")
        if tuple(uuids) != tuple(token.get("device_uuids") or ()):
            raise ValueError("删除确认 token 与设备范围不匹配")
        deleted = device_repository.delete_many_by_uuid(uuids)
        return DeviceDeleteDTO(deleted=len(deleted), device_uuids=deleted)

    def create_group(self, payload: DeviceGroupRequestDTO) -> DeviceGroupDTO:
        site = self.current_site_id()
        _devices, groups, _facts = self._repositories(site)
        group = groups.create(payload.name)
        return DeviceGroupDTO(id=int(group.id), name=group.name, device_count=0)

    def rename_group(self, group_id: int, payload: DeviceGroupRequestDTO) -> DeviceGroupDTO:
        site = self.current_site_id()
        _devices, groups, _facts = self._repositories(site)
        group = groups.rename(group_id, payload.name)
        return DeviceGroupDTO(id=int(group.id), name=group.name, device_count=groups.count_devices(group_id))

    def delete_group(self, group_id: int) -> DeviceGroupDeleteDTO:
        site = self.current_site_id()
        _devices, groups, _facts = self._repositories(site)
        groups.delete(group_id)
        return DeviceGroupDeleteDTO()

    def assign_group(self, payload: DeviceGroupAssignmentRequestDTO) -> DeviceGroupAssignmentDTO:
        site = self.current_site_id()
        devices, groups, _facts = self._repositories(site)
        if payload.group_id is not None:
            groups.get(payload.group_id)
        ids = [int(self._require_device(devices, device_uuid).id or 0) for device_uuid in self._unique_ids(payload.device_uuids)]
        result = DeviceGroupService(devices, groups).assign_devices(ids, payload.group_id)
        return DeviceGroupAssignmentDTO(success=result.success, failed=result.failed, group_id=payload.group_id)

    def start_batch_refresh(self, payload: DeviceBatchRefreshRequestDTO) -> DeviceTaskBatchDTO:
        site = self.current_site_id()
        devices, _groups, _facts = self._repositories(site)
        device_uuids = self._unique_ids(payload.device_uuids)
        for device_uuid in device_uuids:
            self._require_device(devices, device_uuid)
        task_id = f"device-detail-{uuid.uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=DEVICE_COLLECT_TASK_TYPE,
            params={
                "site_name": site,
                "device_uuids": device_uuids,
                "task_name": f"设备详情批量采集 · {len(device_uuids)} 台",
                "owner": WEB_TASK_OWNER,
                "task_source": "local",
                "device": ",".join(device_uuids),
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "_cancel_grace_ms": 2000,
            },
        )
        self.process_adapter.start_job(job)
        snapshot = self.task_service.repository(site).get(task_id)
        references = [] if snapshot is None else [self._task_reference(snapshot)]
        return DeviceTaskBatchDTO(action="batch_refresh_details", tasks=references)

    def preview_import(self, filename: str, stream: BinaryIO) -> DeviceImportPreviewDTO:
        site = self.current_site_id()
        self._cleanup_expired_import_previews(site)
        source_name = self._validate_upload_filename(filename)
        staged_path, source_sha256 = self._stage_csv_upload(site, source_name, stream)
        errors: list[str] = []
        warnings: list[str] = []
        columns: list[str] = []
        row_count = 0
        mapped_rows: list[tuple[int, dict[str, object | None]]] = []
        try:
            repository, groups, _ = self._repositories(site)
            importer = DeviceImportExportService(repository, groups)
            rows = importer._read_csv_rows(staged_path)
            if rows:
                columns = [str(value).strip() for value in rows[0]]
                mode = importer._detect_mode(columns)
                mapped_rows = [
                    (line, importer._map_row(columns, values, mode))
                    for line, values in enumerate(rows[1:], start=2)
                ]
                importer._validate_all_rows(mapped_rows)
                row_count = len(mapped_rows)
                existing_addresses = {
                    str(device.primary_address or "").strip().casefold()
                    for device in importer.repository.list()
                    if str(device.primary_address or "").strip()
                }
                conflicts = sum(
                    1 for _line, row in mapped_rows if str(row.get("primary_address") or "").strip().casefold() in existing_addresses
                )
                if conflicts:
                    warnings.append(f"有 {conflicts} 行主用地址已存在，确认后仍将按新增设备处理")
        except Exception as exc:
            errors.append(str(exc) or exc.__class__.__name__)
        token = secrets.token_urlsafe(32)
        self._write_import_preview(
            site,
            token,
            {
                "site": site,
                "staged_name": staged_path.name,
                "source_name": source_name,
                "sha256": source_sha256,
                "expires": datetime.now(UTC).timestamp()
                + DEVICE_IMPORT_PREVIEW_TTL_SECONDS,
                "row_count": row_count,
                "columns": columns,
                "errors": errors,
                "warnings": warnings,
            },
        )
        return DeviceImportPreviewDTO(
            preview_token=token,
            source_name=source_name,
            source_sha256=source_sha256,
            row_count=row_count,
            columns=columns,
            errors=errors,
            warnings=warnings,
        )

    def confirm_import(self, payload: DeviceImportConfirmRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        self._cleanup_expired_import_previews(site)
        operation_id = f"device-import-{uuid.uuid4().hex}"
        task_id = f"device-import-{uuid.uuid4().hex}"
        preview, claimed_manifest = self._claim_import_preview(
            site,
            payload.preview_token,
            operation_id=operation_id,
            task_id=task_id,
        )
        if (
            preview.get("site") != site
            or float(preview.get("expires") or 0) < datetime.now(UTC).timestamp()
        ):
            self._remove_controlled_file(
                claimed_manifest, self._import_staging_root(site)
            )
            raise ValueError("导入预览 token 无效或已过期")
        path = self._import_staging_root(site) / str(preview.get("staged_name") or "")
        try:
            self._assert_controlled_path(path, self._import_staging_root(site))
            if tuple(preview.get("errors") or ()):
                raise ValueError("导入预览存在错误，不能确认")
            if self._file_sha256(path) != str(preview.get("sha256") or ""):
                raise ValueError("CSV 文件已变化，请重新预览")
            backup_path = self._backup_device_database(site)
            self._write_import_audit(
                site,
                operation_id,
                {
                    "status": "PENDING",
                    "task_id": task_id,
                    "source_file": str(preview.get("source_name") or path.name),
                    "source_sha256": preview.get("sha256"),
                    "backup_reference": str(backup_path),
                },
            )
            job = BackgroundJob(
                job_id=task_id,
                task_type=DEVICE_IMPORT_TASK_TYPE,
                params={
                    "path": str(path),
                    "db_path": str(self.paths.site_db_path(site)),
                    "site_name": site,
                    "task_name": f"设备 CSV 导入 · {path.name}",
                    "owner": WEB_TASK_OWNER,
                    "task_source": "local",
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "_cancel_grace_ms": 1000,
                },
            )
            self.process_adapter.start_job(
                job,
                on_complete=lambda completion: self._finish_import(
                    site,
                    operation_id,
                    path,
                    claimed_manifest,
                    completion,
                ),
            )
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is None:
                raise RuntimeError("设备导入任务创建后未写入任务中心")
            return self._task_reference(snapshot)
        except Exception as exc:
            audit_path = self._import_audit_path(site, operation_id)
            if audit_path.exists():
                self._write_import_audit(
                    site,
                    operation_id,
                    {
                        "status": "FAILED",
                        "task_id": task_id,
                        "error_summary": sanitize_sensitive_text(str(exc)),
                    },
                )
            self._remove_controlled_file(path, self._import_staging_root(site))
            self._remove_controlled_file(
                claimed_manifest, self._import_staging_root(site)
            )
            raise

    def start_diagnostic_download(self, device_uuids: list[str]) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        devices, _groups, _facts = self._repositories(site)
        selected_uuids = self._unique_ids(device_uuids)
        for value in selected_uuids:
            self._require_device(devices, value)
        task_id = f"device-diagnostic-{uuid.uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=DEVICE_DIAGNOSTIC_TASK_TYPE,
            params={
                "site_name": site,
                "device_uuids": selected_uuids,
                "task_name": f"设备诊断信息下载 · {len(selected_uuids)} 台",
                "owner": WEB_TASK_OWNER,
                "task_source": "local",
                "device": ",".join(selected_uuids),
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "_cancel_grace_ms": 2000,
            },
        )
        self.process_adapter.start_job(job)
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None:
            raise RuntimeError("设备诊断任务创建后未写入任务中心")
        return self._task_reference(snapshot)

    def external_terminal_action(self, device_uuid: str, payload: DeviceExternalTerminalRequestDTO) -> DeviceExternalTerminalActionDTO:
        devices, _groups, _facts = self._repositories(self.current_site_id())
        self._require_device(devices, device_uuid)
        result = self.desktop_action_service.launch_registered_terminal(
            DEVICE_TERMINAL_ACTION_IDS[payload.terminal_type],
            device_uuid,
        )
        if not result.success:
            raise ValueError(result.message or result.code)
        return DeviceExternalTerminalActionDTO(
            device_uuid=device_uuid,
            terminal_type=payload.terminal_type,
            code=result.code,
            message=result.message,
        )

    def start_csv_export(self, payload: DeviceExportRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        job_payload = {
            "db_path": str(self.paths.site_db_path(site)),
            "site_name": site,
            "filters": filters,
            "selected_device_uuids": self._unique_ids(payload.device_uuids)
            if payload.device_uuids
            else [],
            "omit_credentials": True,
        }
        return self._start_export(site, "device_csv", "csv", job_payload, "export_csv")

    def start_template_export(self) -> DeviceTaskReferenceDTO:
        return self._start_export(self.current_site_id(), "device_template_csv", "csv", {}, "export_template")

    def start_securecrt_export(self, payload: DeviceSecureCrtExportRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        job_payload = {
            "db_path": str(self.paths.site_db_path(site)),
            "site_name": site,
            "selected_device_uuids": list(payload.device_uuids),
            "filters": filters,
        }
        return self._start_export(site, "securecrt_sessions", "zip", job_payload, "securecrt_sessions")

    def start_omnipeek_export(self, payload: DeviceOmniPeekExportRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        job_payload = {
            "db_path": str(self.paths.site_db_path(site)),
            "site_name": site,
            "source": {"device_filters": filters, "selected_device_uuids": list(payload.device_uuids), "ac_uuid": ""},
            "config": {"line_name": payload.line_name, "include_ac_fit_ap": False, "include_ap_extensions": False, "include_device_mr": payload.include_device_mr},
            "selected_item_keys": list(payload.selected_item_keys),
            "excluded_item_keys": list(payload.excluded_item_keys),
            "force_export_keys": list(payload.force_export_keys),
        }
        return self._start_export(site, "omnipeek_name_table", "nam", job_payload, "omnipeek_name_table")

    def get_export_task(self, task_id: str) -> DeviceTaskReferenceDTO:
        snapshot = self._require_web_export_task(task_id)
        return self._task_reference(snapshot)

    def open_export_artifact(self, task_id: str, artifact_id: str) -> tuple[Path, str]:
        snapshot = self._require_web_export_task(task_id)
        if snapshot.status is not TaskState.COMPLETED:
            raise ValueError("导出任务尚未完成")
        result = dict(snapshot.result or {})
        if str(result.get("artifact_id") or "") != artifact_id or not bool(result.get("available")):
            raise KeyError(artifact_id)
        name = self._validate_artifact_name(str(result.get("artifact_name") or ""))
        artifact_root = self._artifact_root(snapshot.site_name)
        path = self._assert_controlled_path(artifact_root / name, artifact_root)
        expected_size = int(result.get("size_bytes") or -1)
        expected_sha256 = str(result.get("sha256") or "")
        if expected_size < 0 or len(expected_sha256) != 64:
            raise ValueError("导出文件完整性信息缺失")
        if path.stat().st_size != expected_size or not secrets.compare_digest(
            self._file_sha256(path), expected_sha256
        ):
            raise ValueError("导出文件完整性校验失败")
        return path, path.name

    def get_task(self, task_id: str) -> DeviceTaskReferenceDTO:
        return self._task_reference(self._require_web_task(task_id))

    def cancel_task(self, task_id: str) -> DeviceTaskReferenceDTO:
        snapshot = self._require_web_task(task_id)
        if snapshot.status in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            return self._task_reference(snapshot)
        if snapshot.task_type in EXPORT_TASK_TYPES:
            spec = self._export_artifacts.get(task_id)
            if spec is not None:
                Path(str(spec["cancel_path"])).write_text("cancelled", encoding="utf-8")
            self.task_service.record_external_event(
                task_id,
                "state",
                {"state": TaskState.STOPPING.value, "message": "已请求停止导出任务"},
                site_name=snapshot.site_name,
            )
            process = self._export_processes.get(task_id)
            if process is not None:
                threading.Thread(
                    target=self._stop_export_after_grace,
                    args=(task_id, snapshot.site_name, process),
                    name=f"device-export-cancel-{task_id}",
                    daemon=True,
                ).start()
        else:
            cancel_job = getattr(self.process_adapter, "cancel_job", None)
            if not callable(cancel_job) or not cancel_job(task_id):
                self.task_service.cancel_task(task_id)
        return self._task_reference(self._require_web_task(task_id))

    def _device_from_write(
        self,
        payload: DeviceWriteRequestDTO,
        existing: Device | None,
        groups: DeviceGroupRepository,
    ) -> Device:
        values = payload.model_dump()
        for field in ("name", "system_name", "station", "location", "device_vendor", "device_type", "primary_address", "backup_address", "remark"):
            values[field] = str(values.get(field) or "").strip()
        if not values["name"] or not values["primary_address"]:
            raise ValueError("设备名称和主用地址必填")
        if values["device_vendor"] not in DEVICE_VENDORS:
            raise ValueError("设备厂商不在受支持白名单中")
        if values["device_type"] not in DEVICE_TYPES:
            raise ValueError("设备类型不在受支持白名单中")
        if not values["ssh_enabled"] and not values["telnet_enabled"]:
            raise ValueError("至少启用 SSH 或 Telnet 之一")
        if values["group_id"] is not None:
            groups.get(int(values["group_id"]))
        record = existing.to_record() if existing is not None else {}
        record.update(values)
        if existing is None:
            record.pop("id", None)
            record.pop("device_uuid", None)
        return Device.from_mapping(record)

    @staticmethod
    def _unique_ids(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = str(value or "").strip()
            if clean and clean not in seen:
                result.append(clean)
                seen.add(clean)
        if not result:
            raise ValueError("至少选择一台设备")
        return result

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _site_files_root(self, site: str) -> Path:
        raw_root = self.paths.site_files_dir(site)
        if raw_root.is_symlink():
            raise ValueError("设备文件根目录不允许使用符号链接")
        return raw_root.resolve()

    def _controlled_root(self, site: str, name: str) -> Path:
        base = self._site_files_root(site)
        raw_root = base / name
        if raw_root.exists() and raw_root.is_symlink():
            raise ValueError("受控文件根目录不允许使用符号链接")
        raw_root.mkdir(parents=True, exist_ok=True)
        root = raw_root.resolve()
        if not root.is_relative_to(base):
            raise ValueError("受控文件根目录越界")
        return root

    def _import_staging_root(self, site: str) -> Path:
        return self._controlled_root(site, WEB_IMPORT_STAGING_DIR)

    def _artifact_root(self, site: str) -> Path:
        return self._controlled_root(site, WEB_ARTIFACT_DIR)

    @staticmethod
    def _validate_upload_filename(filename: str) -> str:
        clean = str(filename or "").strip()
        if not clean or "\x00" in clean or "/" in clean or "\\" in clean or ":" in clean:
            raise ValueError("只允许上传本地 CSV 文件名")
        if PureWindowsPath(clean).name != clean or not clean.casefold().endswith(".csv"):
            raise ValueError("只允许上传 .csv 文件")
        return clean

    @staticmethod
    def _validate_artifact_name(name: str) -> str:
        clean = str(name or "").strip()
        if not clean or clean in {".", ".."} or PureWindowsPath(clean).name != clean or "/" in clean or "\\" in clean or "\x00" in clean:
            raise ValueError("artifact 文件名无效")
        return clean

    @staticmethod
    def _assert_controlled_path(path: Path, root: Path, *, require_exists: bool = True, directory: bool = False) -> Path:
        candidate = Path(path)
        controlled_root = Path(root).resolve()
        if candidate.is_symlink():
            raise ValueError("受控文件不允许使用符号链接")
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(controlled_root)
        except ValueError as exc:
            raise ValueError("文件路径越过受控根目录") from exc
        current = controlled_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("受控文件路径包含符号链接")
        if require_exists:
            if directory and not candidate.is_dir():
                raise FileNotFoundError("受控目录不存在")
            if not directory and not candidate.is_file():
                raise FileNotFoundError("受控文件不存在")
        return resolved

    def _remove_controlled_file(self, path: Path, root: Path) -> None:
        candidate = Path(path)
        try:
            controlled_root = Path(root).resolve()
            parent = self._assert_controlled_path(candidate.parent, controlled_root, directory=True)
            candidate = parent / candidate.name
            if candidate.is_symlink():
                candidate.unlink()
            elif candidate.is_dir():
                for child in candidate.rglob("*"):
                    if child.is_symlink():
                        child.unlink()
                shutil.rmtree(candidate)
            elif candidate.exists():
                candidate.unlink()
        except (FileNotFoundError, ValueError, OSError):
            return

    def _stage_csv_upload(self, site: str, filename: str, stream: BinaryIO) -> tuple[Path, str]:
        staging_root = self._import_staging_root(site)
        path = staging_root / f"device-preview-{uuid.uuid4().hex}.csv"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        digest = hashlib.sha256()
        total = 0
        try:
            fd = os.open(path, flags, 0o600)
            with os.fdopen(fd, "wb") as handle:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DEVICE_IMPORT_BYTES:
                        raise ValueError(f"CSV 文件超过 {MAX_DEVICE_IMPORT_BYTES // (1024 * 1024)} MiB 限制")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self._remove_controlled_file(path, staging_root)
            raise
        return path, digest.hexdigest()

    @staticmethod
    def _preview_token_digest(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _preview_manifest_path(self, site: str, token: str) -> Path:
        return (
            self._import_staging_root(site)
            / f"device-preview-{self._preview_token_digest(token)}.preview.json"
        )

    def _write_json_atomic(
        self, path: Path, payload: dict[str, object], root: Path
    ) -> None:
        target = self._assert_controlled_path(path, root, require_exists=False)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        self._assert_controlled_path(temporary, root, require_exists=False)
        try:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            self._remove_controlled_file(temporary, root)

    def _write_import_preview(
        self, site: str, token: str, payload: dict[str, object]
    ) -> None:
        root = self._import_staging_root(site)
        manifest = self._preview_manifest_path(site, token)
        self._write_json_atomic(manifest, payload, root)

    def _claim_import_preview(
        self,
        site: str,
        token: str,
        *,
        operation_id: str,
        task_id: str,
    ) -> tuple[dict[str, object], Path]:
        root = self._import_staging_root(site)
        manifest = self._preview_manifest_path(site, token)
        digest = self._preview_token_digest(token)
        claim_id = uuid.uuid4().hex
        lock = root / f".claim-{digest}.lock"
        ready = root / f".claim-ready-{digest}-{claim_id}.preview.json"
        reservation = root / f".claim-source-{digest}-{claim_id}.preview.json"
        claimed = root / f".claimed-{claim_id}.preview.json"
        if (
            not self._valid_import_operation_id(operation_id)
            or not self._valid_import_operation_id(task_id)
        ):
            raise ValueError("导入认领标识无效")
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("导入预览状态已损坏")
        except FileNotFoundError as exc:
            raise ValueError("导入预览 token 无效或已过期") from exc
        claimed_payload = {
            **payload,
            "claimed_at": datetime.now(UTC).timestamp(),
            "operation_id": operation_id,
            "task_id": task_id,
        }
        self._write_json_atomic(ready, claimed_payload, root)
        lock_acquired = False
        source_reserved = False
        release_lock = True
        try:
            lock_data = json.dumps(claimed_payload, ensure_ascii=False).encode("utf-8")
            try:
                fd = os.open(
                    lock,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            except FileExistsError as exc:
                raise ValueError("导入预览 token 无效或已过期") from exc
            lock_acquired = True
            with os.fdopen(fd, "wb") as handle:
                handle.write(lock_data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(manifest, reservation)
            except FileNotFoundError as exc:
                raise ValueError("导入预览 token 无效或已过期") from exc
            source_reserved = True
            os.replace(ready, claimed)
            self._remove_controlled_file(reservation, root)
            source_reserved = False
            return dict(claimed_payload), claimed
        except Exception:
            if source_reserved and not claimed.exists():
                try:
                    os.replace(reservation, manifest)
                    source_reserved = False
                except OSError:
                    release_lock = False
            raise
        finally:
            self._remove_controlled_file(ready, root)
            if lock_acquired and release_lock:
                self._remove_controlled_file(lock, root)

    def _cleanup_expired_import_previews(self, site: str) -> None:
        now = datetime.now(UTC).timestamp()
        staging_root = self._import_staging_root(site)
        referenced: set[str] = set()
        for lock in staging_root.glob(".claim-*.lock"):
            digest = lock.name.removeprefix(".claim-").removesuffix(".lock")
            try:
                payload = json.loads(lock.read_text(encoding="utf-8"))
                if (
                    not isinstance(payload, dict)
                    or payload.get("site") != site
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    or not self._valid_import_operation_id(
                        str(payload.get("task_id") or "")
                    )
                    or not self._valid_import_operation_id(
                        str(payload.get("operation_id") or "")
                    )
                ):
                    raise ValueError("导入认领锁无效")
                staged_name = self._validate_artifact_name(
                    str(payload.get("staged_name") or "")
                )
                claimed_at = float(payload["claimed_at"])
                if now < claimed_at + DEVICE_IMPORT_CLAIM_GRACE_SECONDS:
                    referenced.add(staged_name)
                    continue
            except Exception:
                pass
            self._remove_controlled_file(lock, staging_root)
            for pending in (
                *staging_root.glob(f".claim-ready-{digest}-*.preview.json"),
                *staging_root.glob(f".claim-source-{digest}-*.preview.json"),
            ):
                self._remove_controlled_file(pending, staging_root)
        for pattern in (
            ".claim-ready-*.preview.json",
            ".claim-source-*.preview.json",
        ):
            for pending in staging_root.glob(pattern):
                try:
                    stale = (
                        pending.stat().st_mtime
                        < now - DEVICE_IMPORT_CLAIM_GRACE_SECONDS
                    )
                except OSError:
                    stale = False
                if stale:
                    self._remove_controlled_file(pending, staging_root)
        for manifest in staging_root.glob("device-preview-*.preview.json"):
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                staged_name = self._validate_artifact_name(
                    str(payload.get("staged_name") or "")
                )
                expired = float(payload.get("expires") or 0) < now
            except Exception:
                expired = True
                staged_name = ""
            if expired:
                if staged_name and staged_name not in referenced:
                    self._remove_controlled_file(
                        staging_root / staged_name, staging_root
                    )
                self._remove_controlled_file(manifest, staging_root)
            elif staged_name:
                referenced.add(staged_name)
        repository = self.task_service.repository(site)
        for manifest in staging_root.glob(".claimed-*.preview.json"):
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or payload.get("site") != site:
                    raise ValueError("导入认领状态无效")
                staged_name = self._validate_artifact_name(
                    str(payload.get("staged_name") or "")
                )
                task_id = str(payload.get("task_id") or "")
                operation_id = str(payload.get("operation_id") or "")
                claimed_at = float(payload["claimed_at"])
                if (
                    not self._valid_import_operation_id(task_id)
                    or not self._valid_import_operation_id(operation_id)
                ):
                    raise ValueError("导入认领标识无效")
                snapshot = repository.get(task_id) if task_id else None
                owned_task = snapshot is not None and self._is_owned_import_task(
                    snapshot, site
                )
                if owned_task and snapshot.status in ACTIVE_TASK_STATES:
                    referenced.add(staged_name)
                    continue
                if owned_task and snapshot.status in {
                    TaskState.COMPLETED,
                    TaskState.FAILED,
                    TaskState.CANCELLED,
                }:
                    if self._valid_import_operation_id(operation_id):
                        self._reconcile_import_audit_snapshot(
                            site, operation_id, snapshot
                        )
                elif now < claimed_at + DEVICE_IMPORT_CLAIM_GRACE_SECONDS:
                    referenced.add(staged_name)
                    continue
                elif self._valid_import_operation_id(operation_id):
                    self._write_import_audit(
                        site,
                        operation_id,
                        {
                            "status": "FAILED",
                            "task_id": task_id,
                            "error_summary": "设备导入任务状态不存在，已回收暂存文件",
                        },
                    )
                self._remove_controlled_file(staging_root / staged_name, staging_root)
                self._remove_controlled_file(manifest, staging_root)
            except Exception:
                try:
                    stale = (
                        manifest.stat().st_mtime
                        < now - DEVICE_IMPORT_PREVIEW_TTL_SECONDS
                    )
                except OSError:
                    stale = False
                if stale:
                    self._remove_controlled_file(manifest, staging_root)
        cutoff = now - DEVICE_IMPORT_PREVIEW_TTL_SECONDS
        for staged in staging_root.glob("device-preview-*.csv"):
            try:
                if staged.name not in referenced and staged.stat().st_mtime < cutoff:
                    self._remove_controlled_file(staged, staging_root)
            except OSError:
                continue

    def _backup_device_database(self, site: str) -> Path:
        source_path = self.paths.site_db_path(site).resolve()
        if not source_path.is_file():
            raise FileNotFoundError("设备数据库不存在")
        target = self.paths.site_backups_dir(site) / f"device-import-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}.sqlite"
        target.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(source_path) as source, connect_sqlite(target) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("设备数据库备份完整性校验失败")
        return target

    def _import_audit_path(self, site: str, operation_id: str) -> Path:
        return (
            self.paths.site_imports_dir(site)
            / "device_import_audit"
            / f"{operation_id}.json"
        )

    def _write_import_audit(
        self, site: str, operation_id: str, payload: dict[str, object]
    ) -> None:
        path = self._import_audit_path(site, operation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        current: dict[str, object] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                current = dict(loaded) if isinstance(loaded, dict) else {}
            except Exception:
                current = {}
        now = datetime.now(UTC).isoformat()
        merged = {
            "operation_id": operation_id,
            "created_at": current.get("created_at") or now,
            **current,
            **payload,
            "updated_at": now,
        }
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)

    def _finish_import(
        self,
        site: str,
        operation_id: str,
        staged_path: Path,
        claimed_manifest: Path,
        completion: object,
    ) -> None:
        payload = dict(getattr(completion, "payload", None) or {})
        result = dict(payload.get("result") or {})
        exit_code = getattr(completion, "exit_code", None)
        cancelled = bool(getattr(completion, "cancelled", False))
        failed = (
            exit_code is None
            or int(exit_code) != 0
            or bool(result.get("errors"))
            or int(result.get("skipped") or 0) > 0
        )
        audit: dict[str, object] = {
            "status": "CANCELLED" if cancelled else "FAILED" if failed else "APPLIED",
            "created_count": int(result.get("created") or 0),
            "skipped_count": int(result.get("skipped") or 0),
        }
        if failed or cancelled:
            audit["error_summary"] = sanitize_sensitive_text(
                str(result.get("error") or "设备导入任务未成功提交全部数据")
            )
        try:
            self._write_import_audit(site, operation_id, audit)
        finally:
            self._remove_controlled_file(staged_path, self._import_staging_root(site))
            self._remove_controlled_file(
                claimed_manifest, self._import_staging_root(site)
            )

    def _reconcile_import_audits(self, site: str) -> None:
        root = self.paths.site_imports_dir(site) / "device_import_audit"
        if not root.is_dir():
            return
        repository = self.task_service.repository(site)
        for path in root.glob("device-import-*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or payload.get("status") != "PENDING":
                    continue
                task_id = str(payload.get("task_id") or "")
                snapshot = repository.get(task_id)
                if (
                    snapshot is None
                    or not self._is_owned_import_task(snapshot, site)
                    or snapshot.status
                    not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
                ):
                    continue
                self._reconcile_import_audit_snapshot(
                    site,
                    str(payload.get("operation_id") or path.stem),
                    snapshot,
                )
            except Exception:
                continue

    def _reconcile_import_audit_snapshot(
        self, site: str, operation_id: str, snapshot: TaskSnapshot
    ) -> None:
        result = dict(snapshot.result or {})
        self._write_import_audit(
            site,
            operation_id,
            {
                "status": "APPLIED"
                if snapshot.status is TaskState.COMPLETED
                else snapshot.status.value,
                "created_count": int(result.get("created") or 0),
                "skipped_count": int(result.get("skipped") or 0),
                "error_summary": sanitize_sensitive_text(snapshot.error_message),
            },
        )

    @staticmethod
    def _is_owned_import_task(snapshot: TaskSnapshot, site: str) -> bool:
        return DeviceManagementWebService._is_owned_web_task(
            snapshot,
            site,
            frozenset({DEVICE_IMPORT_TASK_TYPE}),
        )

    @staticmethod
    def _is_owned_web_task(
        snapshot: TaskSnapshot,
        site: str,
        allowed_types: frozenset[str] = DEVICE_TASK_TYPES,
    ) -> bool:
        return (
            snapshot.site_name == site
            and snapshot.owner == WEB_TASK_OWNER
            and snapshot.source == "local"
            and snapshot.task_type in allowed_types
        )

    @classmethod
    def _owned_web_tasks(
        cls,
        tasks: list[TaskSnapshot],
        site: str,
        allowed_types: frozenset[str] = DEVICE_TASK_TYPES,
    ) -> list[TaskSnapshot]:
        return [
            task
            for task in tasks
            if cls._is_owned_web_task(task, site, allowed_types)
        ]

    @staticmethod
    def _valid_import_operation_id(value: str) -> bool:
        prefix = "device-import-"
        suffix = value.removeprefix(prefix)
        return (
            value.startswith(prefix)
            and len(suffix) == 32
            and all(character in "0123456789abcdef" for character in suffix)
        )

    def _export_filters(self, payload: DeviceExportRequestDTO) -> dict[str, object | None]:
        return {
            "search": payload.search.strip() or None,
            "vendor": payload.vendor.strip() or None,
            "device_type": payload.device_type.strip() or None,
            "group_filter": payload.group_filter,
        }

    def _require_web_task(
        self, task_id: str, allowed_types: frozenset[str] = DEVICE_TASK_TYPES
    ) -> TaskSnapshot:
        site = self.current_site_id()
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None or not self._is_owned_web_task(
            snapshot, site, allowed_types
        ):
            raise KeyError(task_id)
        return snapshot

    def _require_web_export_task(self, task_id: str) -> TaskSnapshot:
        return self._require_web_task(task_id, EXPORT_TASK_TYPES)

    def _task_reference(self, snapshot: TaskSnapshot) -> DeviceTaskReferenceDTO:
        result = dict(snapshot.result or {})
        spec = self._export_artifacts.get(snapshot.task_id) or {}
        actions = {
            DEVICE_COLLECT_TASK_TYPE: "batch_refresh_details",
            DEVICE_DIAGNOSTIC_TASK_TYPE: "diagnostic_download",
            DEVICE_IMPORT_TASK_TYPE: "import_csv",
            DEVICE_CONNECTION_TEST_TASK_TYPE: "connection_test",
        }
        return DeviceTaskReferenceDTO(
            task_id=snapshot.task_id,
            task_status=snapshot.status.value,
            action=actions.get(
                snapshot.task_type, snapshot.task_type.removeprefix("device_export_")
            ),
            artifact_id=str(result.get("artifact_id") or spec.get("artifact_id") or ""),
            available=bool(result.get("available")),
            sha256=str(result.get("sha256") or ""),
            size_bytes=int(result.get("size_bytes") or 0),
            message=sanitize_sensitive_text(snapshot.message or snapshot.error_message),
        )

    def _start_export(
        self,
        site: str,
        export_type: str,
        extension: str,
        payload: dict[str, object],
        action: str,
    ) -> DeviceTaskReferenceDTO:
        artifact_root = self._artifact_root(site)
        artifact_id = f"device-{uuid.uuid4().hex}"
        target = artifact_root / f"{artifact_id}.{extension}"
        staging_dir: Path | None = None
        job_payload = dict(payload)
        if export_type == "securecrt_sessions":
            staging_dir = artifact_root / f".{artifact_id}-sessions"
            self._assert_controlled_path(staging_dir.parent, artifact_root, directory=True)
            staging_dir.mkdir(parents=True, exist_ok=False)
            job_payload["output_dir"] = str(staging_dir)
        task_id = f"device_export_{export_type}_{uuid.uuid4().hex}"
        job_dir = self.paths.runtime_cache_dir / "export_jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(f"{target.name}.{task_id}.tmp")
        zip_tmp = target.with_name(f"{target.name}.tmp")
        cancel_path = job_dir / f"{task_id}.cancel"
        job = ExportJob(
            job_id=task_id,
            job_type=export_type,
            site_name=site,
            output_path=str(target),
            db_path=str(self.paths.site_db_path(site)),
            params={"payload": job_payload},
        ).with_runtime_paths(tmp_path=str(tmp_path), cancel_path=str(cancel_path))
        job_path = job_dir / f"{task_id}.json"
        spec = {
            "site": site,
            "artifact_id": artifact_id,
            "artifact_name": target.name,
            "export_type": export_type,
            "artifact_root": artifact_root,
            "target": target,
            "tmp_path": tmp_path,
            "zip_tmp": zip_tmp,
            "staging_dir": staging_dir,
            "job_path": job_path,
            "cancel_path": cancel_path,
        }
        self._export_artifacts[task_id] = spec
        task_created = False
        process: subprocess.Popen[str] | None = None
        try:
            job_path.write_text(
                json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            snapshot = self.task_service.create_external_task(
                task_id=task_id,
                task_type=f"device_export_{export_type}",
                task_name=f"设备{action}",
                source="local",
                site_name=site,
                owner=WEB_TASK_OWNER,
            )
            self.task_service.repository(site).save(
                TaskSnapshot(**{**snapshot.__dict__, "owner_pid": os.getpid()})
            )
            task_created = True
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(self.paths.app_root) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
            process = subprocess.Popen(
                self._export_worker_command(job_path),
                cwd=str(self.paths.app_root),
                env=environment,
                shell=False,
                close_fds=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._export_processes[task_id] = process
            self.task_service.record_external_event(task_id, "state", {"state": TaskState.RUNNING.value}, site_name=site)
            threading.Thread(target=self._monitor_export, args=(task_id, site, process), name=f"device-export-{task_id}", daemon=True).start()
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc))
            if process is not None:
                try:
                    self._stop_export_process(process)
                except Exception:
                    pass
                if process.stdout is not None:
                    process.stdout.close()
                self._export_processes.pop(task_id, None)
            self._cleanup_export_files(spec, remove_artifact=True)
            self._export_artifacts.pop(task_id, None)
            if (
                task_created
                or self.task_service.repository(site).get(task_id) is not None
            ):
                self.task_service.record_external_event(
                    task_id,
                    "error",
                    {"message": message, "error": message},
                    site_name=site,
                )
            else:
                raise
        snapshot = self.task_service.repository(site).get(task_id)
        return DeviceTaskReferenceDTO(
            task_id=task_id,
            task_status=snapshot.status.value if snapshot is not None else TaskState.FAILED.value,
            action=action,
            artifact_id=artifact_id,
            available=False,
        )

    def _finalize_export_artifact(self, spec: dict[str, object], raw_result: dict[str, object]) -> dict[str, object]:
        root = Path(str(spec["artifact_root"]))
        target = Path(str(spec["target"]))
        export_type = str(spec["export_type"])
        if export_type == "securecrt_sessions":
            staging_dir = self._assert_controlled_path(
                Path(str(spec["staging_dir"])), root, directory=True
            )
            source_text = str(
                raw_result.get("path") or raw_result.get("output_path") or ""
            )
            source = self._assert_controlled_path(
                Path(source_text), root, directory=True
            )
            if source != staging_dir and not source.is_relative_to(staging_dir):
                raise ValueError("SecureCRT 输出目录未绑定到本任务 staging 目录")
            zip_tmp = self._assert_controlled_path(Path(str(spec["zip_tmp"])), root, require_exists=False)
            with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED) as archive:
                for entry in source.rglob("*"):
                    if entry.is_symlink():
                        raise ValueError("SecureCRT 输出包含符号链接")
                    if entry.is_file():
                        resolved = entry.resolve()
                        if not resolved.is_relative_to(source):
                            raise ValueError("SecureCRT 输出越过受控目录")
                        archive.write(resolved, resolved.relative_to(source).as_posix())
            attach_export_metadata(
                zip_tmp,
                effective_suffix=".zip",
                export_type="securecrt_sessions",
                payload={"source_module": "devices"},
            )
            os.replace(zip_tmp, target)
            self._remove_controlled_file(staging_dir, staging_dir.parent)
        else:
            candidate = Path(
                str(
                    raw_result.get("path")
                    or raw_result.get("output_path")
                    or spec["tmp_path"]
                )
            )
            candidate = self._assert_controlled_path(candidate, root)
            expected = self._assert_controlled_path(target, root, require_exists=False)
            if candidate != expected:
                raise ValueError("导出输出文件未绑定到本任务 artifact")
            target = self._assert_controlled_path(expected, root)
        return {
            "artifact_id": str(spec["artifact_id"]),
            "artifact_name": target.name,
            "available": True,
            "sha256": self._file_sha256(target),
            "size_bytes": target.stat().st_size,
            "row_count": int(raw_result.get("row_count") or 0),
        }

    @staticmethod
    def _export_worker_command(job_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--export-worker", "--job", str(job_path)]
        return [sys.executable, "-m", "netconsole.export_worker", "--job", str(job_path)]

    def _cleanup_export_files(self, spec: dict[str, object], *, remove_artifact: bool) -> None:
        root = Path(str(spec["artifact_root"]))
        for key in ("tmp_path", "zip_tmp"):
            self._remove_controlled_file(Path(str(spec[key])), root)
        staging_dir = spec.get("staging_dir")
        if staging_dir:
            self._remove_controlled_file(Path(str(staging_dir)), root)
        if remove_artifact:
            self._remove_controlled_file(Path(str(spec["target"])), root)
        for key in ("job_path", "cancel_path"):
            try:
                Path(str(spec[key])).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _stop_export_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _stop_export_after_grace(
        self, task_id: str, site: str, process: subprocess.Popen[str]
    ) -> None:
        if threading.Event().wait(2.0) or process.poll() is not None:
            return
        self._stop_export_process(process)
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is not None and snapshot.status not in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            self.task_service.record_external_event(
                task_id,
                "cancelled",
                {
                    "message": "导出任务已取消",
                    "error": "导出任务已取消",
                    "cancelled": True,
                },
                site_name=site,
            )

    def _record_export_error_if_active(
        self, task_id: str, site: str, message: str
    ) -> None:
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is not None and snapshot.status not in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            self.task_service.record_external_event(
                task_id,
                "error",
                {"message": message, "error": message},
                site_name=site,
            )

    def _monitor_export(
        self, task_id: str, site: str, process: subprocess.Popen[str]
    ) -> None:
        spec = self._export_artifacts.get(task_id)
        terminal = False
        completed = False
        try:
            if spec is None:
                raise RuntimeError("导出任务 artifact 状态不存在")
            if process.stdout is not None:
                for line in process.stdout:
                    event = parse_event_line(line.strip())
                    if not event or str(event.get("job_id") or "") != task_id:
                        continue
                    event_type = str(event.get("type") or "")
                    safe_payload = {key: event[key] for key in ("stage", "current", "total") if key in event}
                    if event_type in {"progress", "log"}:
                        safe_payload["message"] = sanitize_sensitive_text(str(event.get("message") or ""))
                    if event_type == "finished":
                        try:
                            safe_payload["result"] = self._finalize_export_artifact(spec, dict(event.get("result") or {}))
                        except Exception as exc:
                            message = sanitize_sensitive_text(str(exc))
                            self.task_service.record_external_event(task_id, "error", {"message": message, "error": message}, site_name=site)
                        else:
                            self.task_service.record_external_event(task_id, "finished", safe_payload, site_name=site)
                            completed = True
                        terminal = True
                    elif event_type in {"error", "cancelled"}:
                        message = sanitize_sensitive_text(str(event.get("error") or event.get("message") or "导出任务失败"))
                        self.task_service.record_external_event(task_id, event_type, {"message": message, "error": message, "cancelled": event_type == "cancelled"}, site_name=site)
                        terminal = True
                    elif event_type in {"progress", "log"}:
                        self.task_service.record_external_event(task_id, event_type, safe_payload, site_name=site)
            process.wait(timeout=10)
            if not terminal:
                message = (
                    "导出进程异常退出"
                    if process.returncode
                    else "导出任务未返回完成事件"
                )
                self._record_export_error_if_active(task_id, site, message)
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc))
            try:
                if not terminal:
                    self.task_service.record_external_event(task_id, "error", {"message": message, "error": message}, site_name=site)
            except Exception:
                pass
        finally:
            if process.poll() is None:
                try:
                    self._stop_export_process(process)
                except Exception:
                    pass
            if process.stdout is not None:
                process.stdout.close()
            self._export_processes.pop(task_id, None)
            if spec is not None:
                self._cleanup_export_files(spec, remove_artifact=not completed)
            self._export_artifacts.pop(task_id, None)

    def preview_edit(self, device_uuid: str, payload: DeviceEditPreviewRequestDTO) -> DeviceEditPreviewDTO:
        site = self.current_site_id()
        device_repository, group_repository, _ = self._repositories(site)
        self._require_device(device_repository, device_uuid)
        values = payload.model_dump()
        for field in ("name", "system_name", "station", "location", "device_vendor", "device_type", "primary_address", "backup_address", "remark"):
            values[field] = str(values[field] or "").strip()
        normalized = DeviceEditPreviewRequestDTO.model_validate(values)
        errors: list[str] = []
        warnings: list[str] = []
        if not normalized.ssh_enabled and not normalized.telnet_enabled:
            errors.append("至少启用 SSH 或 Telnet 之一")
        if normalized.device_vendor not in DEVICE_VENDORS:
            errors.append("设备厂商不在受支持白名单中")
        if normalized.device_type not in DEVICE_TYPES:
            errors.append("设备类型不在受支持白名单中")
        if normalized.group_id is not None:
            try:
                group_repository.get(normalized.group_id)
            except KeyError:
                errors.append("设备分组不存在")
        if normalized.backup_address and normalized.backup_address == normalized.primary_address:
            warnings.append("备用地址与主地址相同")
        return DeviceEditPreviewDTO(valid=not errors, normalized=normalized, errors=errors, warnings=warnings)

    def start_connection_test(self, device_uuid: str, protocol: str) -> DeviceConnectionTestDTO:
        site = self.current_site_id()
        device_repository, _, _ = self._repositories(site)
        device = self._require_device(device_repository, device_uuid)
        selected_protocol = protocol.strip().upper()
        self._validate_protocol_enabled(device, selected_protocol)
        with self._start_lock:
            active = next(
                (
                    task
                    for task in self.task_service.repository(site).list(statuses=ACTIVE_TASK_STATES, limit=1000)
                    if self._is_owned_web_task(
                        task,
                        site,
                        frozenset({DEVICE_CONNECTION_TEST_TASK_TYPE}),
                    )
                    and task.device == device_uuid
                    and _protocol_from_task_id(task.task_id) == selected_protocol
                ),
                None,
            )
            if active is not None:
                return self._connection_test_dto(active, device)
            task_id = f"device-test-{selected_protocol.lower()}-{uuid.uuid4().hex}"
            job = BackgroundJob(
                job_id=task_id,
                task_type=DEVICE_CONNECTION_TEST_TASK_TYPE,
                params={
                    "site_name": site,
                    "device_uuid": device_uuid,
                    "protocol": selected_protocol,
                    "task_name": f"设备连接测试 · {device.name or device_uuid} · {selected_protocol}",
                    "owner": WEB_TASK_OWNER,
                    "task_source": "local",
                    "device": device_uuid,
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "_emit_log_events": True,
                    "_cancel_grace_ms": 1000,
                },
            )
            self.process_adapter.start_job(job)
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is None:
                raise RuntimeError("连接测试任务创建后未写入任务中心")
            return self._connection_test_dto(snapshot, device)

    def get_connection_test(self, task_id: str) -> DeviceConnectionTestDTO:
        site = self.current_site_id()
        snapshot = self._require_web_task(
            task_id, frozenset({DEVICE_CONNECTION_TEST_TASK_TYPE})
        )
        device_repository, _, _ = self._repositories(site)
        return self._connection_test_dto(snapshot, device_repository.get_by_uuid(snapshot.device))

    async def stop_exports(self) -> None:
        for task_id, process in tuple(self._export_processes.items()):
            spec = self._export_artifacts.get(task_id)
            if spec is not None:
                try:
                    Path(str(spec["cancel_path"])).write_text(
                        "cancelled", encoding="utf-8"
                    )
                except OSError:
                    pass
            await asyncio.to_thread(self._stop_export_process, process)
            site = str(spec.get("site") or self.current_site_id()) if spec is not None else self.current_site_id()
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is not None and snapshot.status not in {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                try:
                    self.task_service.record_external_event(
                        task_id,
                        "cancelled",
                        {
                            "message": "WebHost 正在关闭",
                            "error": "WebHost 正在关闭",
                            "cancelled": True,
                        },
                        site_name=snapshot.site_name,
                    )
                except Exception:
                    pass

    async def stop(self) -> None:
        await self.stop_exports()
        await asyncio.to_thread(self.process_adapter.shutdown)

    def _repositories(self, site: str) -> tuple[DeviceRepository, DeviceGroupRepository, DeviceFactRepository]:
        database = Database(self.paths.site_db_path(site))
        return DeviceRepository(database), DeviceGroupRepository(database, site), DeviceFactRepository(database)

    @staticmethod
    def _require_device(repository: DeviceRepository, device_uuid: str) -> Device:
        device = repository.get_by_uuid(str(device_uuid or ""))
        if device is None:
            raise KeyError(device_uuid)
        return device

    @staticmethod
    def _validate_protocol_enabled(device: Device, protocol: str) -> None:
        enabled = {
            "SSH": bool(device.ssh_enabled),
            "TELNET": bool(device.telnet_enabled),
            "SNMP": bool(device.snmp_enabled and (device.snmp_v1_enabled or device.snmp_v2c_enabled or device.snmp_v3_enabled)),
        }
        if protocol not in enabled:
            raise ValueError("不支持的连接测试协议")
        if not enabled[protocol]:
            raise ValueError(f"设备未启用 {protocol}")

    @staticmethod
    def _capabilities(device: Device) -> DeviceCapabilityDTO:
        versions = [
            version
            for version, enabled in (("v1", device.snmp_v1_enabled), ("v2c", device.snmp_v2c_enabled), ("v3", device.snmp_v3_enabled))
            if enabled
        ]
        return DeviceCapabilityDTO(
            ssh=bool(device.ssh_enabled),
            ssh_port=int(device.ssh_port or 22) if device.ssh_enabled else None,
            telnet=bool(device.telnet_enabled),
            telnet_port=int(device.telnet_port or 23) if device.telnet_enabled else None,
            snmp=bool(device.snmp_enabled and versions),
            snmp_versions=versions,
            snmp_port=int(device.snmp_port or 161) if device.snmp_enabled and versions else None,
        )

    def _list_item(
        self,
        device: Device,
        group_names: dict[int, str],
        latest_test: TaskSnapshot | None,
    ) -> DeviceListItemDTO:
        return DeviceListItemDTO(
            id=int(device.id or 0),
            device_uuid=str(device.device_uuid or ""),
            name=str(device.name or ""),
            system_name=str(device.system_name or ""),
            station=str(device.station or ""),
            group_id=int(device.group_id) if device.group_id is not None else None,
            group_name=group_names.get(int(device.group_id), "未分组") if device.group_id is not None else "未分组",
            device_vendor=str(device.device_vendor or ""),
            device_type=str(device.device_type or ""),
            primary_address=str(device.primary_address or ""),
            backup_address=str(device.backup_address or ""),
            updated_at=str(device.updated_at or ""),
            capabilities=self._capabilities(device),
            connection_status=self._connection_status(latest_test),
            last_test_task_id=latest_test.task_id if latest_test else "",
            last_test_time=latest_test.updated_time if latest_test else "",
        )

    @staticmethod
    def _connection_status(task: TaskSnapshot | None) -> str:
        if task is None:
            return "UNKNOWN"
        if task.status in ACTIVE_TASK_STATES:
            return "TESTING"
        if task.status is TaskState.COMPLETED:
            return "REACHABLE" if task.result.get("success") is True else "UNREACHABLE"
        return "ERROR"

    @staticmethod
    def _latest_test(tasks: list[TaskSnapshot], device: Device) -> TaskSnapshot | None:
        device_uuid = str(device.device_uuid or "")
        return next(
            (
                task
                for task in tasks
                if task.task_type == DEVICE_CONNECTION_TEST_TASK_TYPE and task.device == device_uuid
            ),
            None,
        )

    @staticmethod
    def _device_tasks(tasks: list[TaskSnapshot], device: Device) -> list[TaskSnapshot]:
        aliases = {
            str(value).strip().casefold()
            for value in (
                device.id,
                device.device_uuid,
                device.name,
                device.system_name,
                device.primary_address,
                device.backup_address,
            )
            if str(value or "").strip()
        }
        return [
            task
            for task in tasks
            if aliases
            & {
                value.strip().casefold()
                for value in str(task.device or "").split(",")
                if value.strip()
            }
        ]

    @staticmethod
    def _task_summary(task: TaskSnapshot, device: Device) -> DeviceTaskSummaryDTO:
        return DeviceTaskSummaryDTO(
            task_id=task.task_id,
            task_type=task.task_type,
            task_name=task.task_name,
            status=task.status.value,
            stage=task.stage,
            message=sanitize_sensitive_text(task.message, device),
            created_time=task.created_time,
            updated_time=task.updated_time,
            error_summary=sanitize_sensitive_text(task.error_message, device),
        )

    @staticmethod
    def _fact_summary(fact: dict[str, object | None] | None) -> DeviceFactDTO | None:
        if not fact:
            return None
        return DeviceFactDTO(
            system_name=str(fact.get("sysname") or ""),
            model=str(fact.get("model") or ""),
            serial_number=str(fact.get("serial_number") or ""),
            mac_address=str(fact.get("mac_address") or ""),
            software_version=str(fact.get("software_version") or ""),
            bootrom_version=str(fact.get("bootrom_version") or ""),
            vendor=str(fact.get("vendor") or ""),
            uptime=str(fact.get("uptime") or ""),
            collected_at=str(fact.get("collected_at") or ""),
        )

    @staticmethod
    def _collection_summary(collection: dict[str, object | None] | None, device: Device) -> DeviceCollectionSummaryDTO | None:
        if not collection:
            return None
        return DeviceCollectionSummaryDTO(
            collect_run_uuid=str(collection.get("collect_run_uuid") or ""),
            collect_type=str(collection.get("collect_type") or ""),
            status=str(collection.get("status") or ""),
            started_at=str(collection.get("started_at") or ""),
            ended_at=str(collection.get("ended_at") or ""),
            error_summary=sanitize_sensitive_text(str(collection.get("error_message") or ""), device),
        )

    @staticmethod
    def _recent_errors(
        tasks: list[TaskSnapshot],
        collection: dict[str, object | None] | None,
        device: Device,
    ) -> list[DeviceErrorSummaryDTO]:
        errors = [
            DeviceErrorSummaryDTO(
                source="task",
                time=task.updated_time,
                message=sanitize_sensitive_text(task.error_message, device),
            )
            for task in tasks
            if task.error_message
        ]
        if collection and collection.get("error_message"):
            errors.append(
                DeviceErrorSummaryDTO(
                    source="collection",
                    time=str(collection.get("ended_at") or collection.get("started_at") or ""),
                    message=sanitize_sensitive_text(str(collection.get("error_message") or ""), device),
                )
            )
        errors.sort(key=lambda item: item.time, reverse=True)
        return errors[:10]

    @staticmethod
    def _connection_commands(device: Device) -> list[DeviceConnectionCommandDTO]:
        host = str(device.primary_address or "").strip()
        if not host:
            return []
        commands: list[DeviceConnectionCommandDTO] = []
        if device.ssh_enabled:
            commands.append(DeviceConnectionCommandDTO(protocol="SSH", command=f"ssh -p {int(device.ssh_port or 22)} {host}"))
        if device.telnet_enabled:
            commands.append(DeviceConnectionCommandDTO(protocol="TELNET", command=f"telnet {host} {int(device.telnet_port or 23)}"))
        return commands

    @staticmethod
    def _connection_test_dto(snapshot: TaskSnapshot, device: Device | None = None) -> DeviceConnectionTestDTO:
        result = dict(snapshot.result or {})
        protocol = str(result.get("protocol") or "").upper() or _protocol_from_task_id(snapshot.task_id)
        return DeviceConnectionTestDTO(
            task_id=snapshot.task_id,
            task_status=snapshot.status.value,
            device_uuid=str(result.get("device_uuid") or snapshot.device or ""),
            protocol=protocol or None,
            success=result.get("success") if isinstance(result.get("success"), bool) else None,
            result_status=str(result.get("status") or ""),
            message=sanitize_sensitive_text(str(result.get("message") or snapshot.message or snapshot.error_message or ""), device),
            method=str(result.get("method") or ""),
            host=str(result.get("host") or ""),
            port=int(result["port"]) if result.get("port") is not None else None,
            latency_ms=int(result["latency_ms"]) if result.get("latency_ms") is not None else None,
            system_name=str(result.get("system_name") or ""),
            model=str(result.get("model") or ""),
            os_family=str(result.get("os_family") or ""),
            interface_count=int(result["interface_count"]) if result.get("interface_count") is not None else None,
            error_type=str(result.get("error_type") or ""),
            suggestion=sanitize_sensitive_text(str(result.get("suggestion") or ""), device),
            created_time=snapshot.created_time,
            updated_time=snapshot.updated_time,
        )


def run_device_connection_test(context: JobContext) -> dict[str, object]:
    from netconsole.services.device_snmp_detect_service import DeviceSnmpDetectService
    from netconsole.services.netmiko_connection import test_device_connection

    site = SiteManager(context.paths).validate_site_name(str(context.params.get("site_name") or ""))
    device_uuid = str(context.params.get("device_uuid") or "")
    protocol = str(context.params.get("protocol") or "").upper()
    repository = DeviceRepository(Database(context.paths.site_db_path(site)))
    device = repository.get_by_uuid(device_uuid)
    if device is None:
        raise KeyError(f"设备不存在：{device_uuid}")
    DeviceManagementWebService._validate_protocol_enabled(device, protocol)
    context.check_cancelled()
    context.progress("connect", 0, 1, f"正在执行 {protocol} 连接测试")
    if protocol == "SNMP":
        result = DeviceSnmpDetectService().detect(device, cancel_checker=context.should_cancel)
        payload = {
            "device_uuid": device_uuid,
            "protocol": protocol,
            "success": result.status == "success",
            "status": result.status,
            "message": sanitize_sensitive_text(result.error_message or ("SNMP 探测成功" if result.status == "success" else "SNMP 探测失败"), device),
            "host": str(device.primary_address or ""),
            "port": int(device.snmp_port or 161),
            "latency_ms": int(result.latency_ms or 0),
            "system_name": result.sys_name,
            "model": result.model,
            "os_family": result.os_family,
            "interface_count": int(result.interface_count or 0),
        }
    else:
        selected = Device.from_mapping(device.to_record())
        selected.ssh_enabled = int(protocol == "SSH")
        selected.telnet_enabled = int(protocol == "TELNET")
        result = test_device_connection(selected)
        payload = {
            "device_uuid": device_uuid,
            "protocol": protocol,
            "success": bool(result.success),
            "status": str(result.status or ("success" if result.success else "failed")),
            "message": sanitize_sensitive_text(result.message, device),
            "method": str(result.method or ""),
            "host": str(result.host or ""),
            "port": int(result.port or 0),
            "latency_ms": int(result.elapsed_ms or 0),
            "system_name": str(extract_sysname_from_prompt(result.prompt or "") or ""),
            "error_type": str(result.error_type or ""),
            "suggestion": str(result.suggestion or ""),
        }
    context.check_cancelled()
    context.progress("connect", 1, 1, f"{protocol} 连接测试完成")
    return payload


def run_device_csv_import(context: JobContext) -> dict[str, object]:
    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    path = Path(str(context.params.get("path") or ""))
    if str(context.params.get("owner") or "") == WEB_TASK_OWNER:
        staging_root = (
            context.paths.site_files_dir(site) / WEB_IMPORT_STAGING_DIR
        ).resolve()
        DeviceManagementWebService._assert_controlled_path(path, staging_root)
    context.check_cancelled()
    context.progress("device_csv_import", 0, 1, "正在原子导入设备 CSV")
    database = Database(
        Path(str(context.params.get("db_path") or context.paths.site_db_path(site)))
    )
    service = DeviceImportExportService(
        DeviceRepository(database),
        DeviceGroupRepository(database, site),
    )
    result = service.import_csv_atomic(path, check_cancelled=context.check_cancelled)
    context.progress("device_csv_import", 1, 1, "设备 CSV 导入完成")
    return {
        "created": result.created,
        "skipped": result.skipped,
        "groups_created": result.groups_created,
        "errors": list(result.errors),
    }


def run_device_detail_collect(context: JobContext) -> dict[str, object]:
    from netconsole.services.h3c_collect_service import collect_h3c_device_details

    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    values = DeviceManagementWebService._unique_ids(
        list(context.params.get("device_uuids") or [])
    )
    database = Database(context.paths.site_db_path(site))
    devices = DeviceRepository(database)
    facts = DeviceFactRepository(database)
    selected = [
        DeviceManagementWebService._require_device(devices, value) for value in values
    ]
    results: list[dict[str, object]] = []
    context.progress("device_detail_collect", 0, len(selected), "正在采集设备详情")

    def collect(device: Device):
        context.check_cancelled()
        return collect_h3c_device_details(
            device, site, repository=facts, paths=context.paths
        )

    worker_count = max(1, min(20, len(selected)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(collect, device): device for device in selected}
        for index, future in enumerate(as_completed(futures), start=1):
            context.check_cancelled()
            device = futures[future]
            try:
                result = future.result()
                item = {
                    "device_uuid": str(device.device_uuid or ""),
                    "success": bool(result.success),
                    "collect_run_uuid": result.collect_run_uuid,
                    "facts_updated": bool(result.facts_updated),
                    "interfaces_updated": int(result.interfaces_updated),
                    "optical_modules_updated": int(result.optical_modules_updated),
                    "lldp_neighbors_updated": int(result.lldp_neighbors_updated),
                    "error_message": sanitize_sensitive_text(
                        result.error_message or "", device
                    ),
                }
            except Exception as exc:
                item = {
                    "device_uuid": str(device.device_uuid or ""),
                    "success": False,
                    "error_message": sanitize_sensitive_text(str(exc), device),
                }
            results.append(item)
            context.progress(
                "device_detail_collect",
                index,
                len(selected),
                f"设备详情采集 {index}/{len(selected)}",
            )
    return {
        "total": len(results),
        "success": sum(1 for item in results if item["success"]),
        "failed": sum(1 for item in results if not item["success"]),
        "results": results,
    }


def run_device_diagnostic_download(context: JobContext) -> dict[str, object]:
    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    values = DeviceManagementWebService._unique_ids(
        list(context.params.get("device_uuids") or [])
    )
    repository = DeviceRepository(Database(context.paths.site_db_path(site)))
    devices = [
        DeviceManagementWebService._require_device(repository, value)
        for value in values
    ]
    context.check_cancelled()
    context.progress(
        "device_diagnostic_download", 0, len(devices), "正在下载设备诊断信息"
    )
    if len(devices) == 1:
        results = [DiagnosticDownloadService(site, context.paths).download(devices[0])]
    else:
        results = run_batch_diagnostic_download(
            devices,
            lambda: DiagnosticDownloadService(site, context.paths),
        )
    context.check_cancelled()
    context.progress(
        "device_diagnostic_download", len(devices), len(devices), "设备诊断信息下载完成"
    )
    return {
        "total": len(results),
        "success": sum(1 for result in results if result.success),
        "failed": sum(1 for result in results if not result.success),
        "results": [
            {
                "device_id": result.device_id,
                "device_name": result.device_name,
                "status": result.status,
                "error_message": result.error_message or "",
                "elapsed_ms": result.elapsed_ms,
            }
            for result in results
        ],
    }


def _protocol_from_task_id(task_id: str) -> str:
    parts = str(task_id or "").split("-", 3)
    return parts[2].upper() if len(parts) >= 4 and parts[:2] == ["device", "test"] and parts[2] in {"ssh", "telnet", "snmp"} else ""


__all__ = [
    "DEVICE_CONNECTION_TEST_TASK_TYPE",
    "DeviceManagementWebService",
    "run_device_connection_test",
    "run_device_csv_import",
    "run_device_detail_collect",
    "run_device_diagnostic_download",
]
