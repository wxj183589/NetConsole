from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
import uuid
from threading import RLock

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
    DeviceImportPreviewRequestDTO,
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
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.netmiko_connection import extract_sysname_from_prompt, sanitize_sensitive_text
from netconsole.services.job_center.worker_protocol import parse_event_line
from netconsole.utils.natural_sort import natural_text_key


DEVICE_CONNECTION_TEST_TASK_TYPE = "device_connection_test"
ACTIVE_TASK_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
DEVICE_IMPORT_PREVIEW_TTL_SECONDS = 15 * 60
DEVICE_DELETE_TOKEN_TTL_SECONDS = 5 * 60
SENSITIVE_DEVICE_FIELDS = {
    "password",
    "ssh_password",
    "telnet_password",
    "snmp_ro_community",
    "snmp_rw_community",
    "snmpv3_auth_password",
    "snmpv3_priv_password",
    "tunnel1_password",
    "tunnel2_password",
}
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
        site_name: str | None = None,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.site_name = site_name
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self._start_lock = RLock()
        self._mutation_lock = RLock()
        self._import_previews: dict[str, dict[str, object]] = {}
        self._delete_tokens: dict[str, dict[str, object]] = {}
        self._export_processes: dict[str, subprocess.Popen[str]] = {}

    def current_site_id(self) -> str:
        site = self.site_name or SiteManager(self.paths).get_current_site()
        return SiteManager(self.paths).validate_site_name(str(site or "demo"))

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
        tasks = self.task_service.repository(site).list(limit=1000)
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
        tasks = self._device_tasks(self.task_service.repository(site).list(limit=1000), device)
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
        deleted: list[str] = []
        for device_uuid in uuids:
            device = self._require_device(device_repository, device_uuid)
            if device.id is not None:
                device_repository.delete(int(device.id))
                deleted.append(str(device_uuid))
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
        references: list[DeviceTaskReferenceDTO] = []
        for device_uuid in self._unique_ids(payload.device_uuids):
            device = self._require_device(devices, device_uuid)
            task_id = f"device-detail-{uuid.uuid4().hex}"
            job = BackgroundJob(
                job_id=task_id,
                task_type="device_detail_load_all",
                params={
                    "site_name": site,
                    "db_path": str(self.paths.site_db_path(site)),
                    "device": self._safe_device_record(device),
                    "device_uuid": device_uuid,
                    "task_name": f"设备详情刷新 · {device.name or device_uuid}",
                    "owner": "web_device_management",
                },
            )
            self.process_adapter.start_job(job)
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is not None:
                references.append(DeviceTaskReferenceDTO(task_id=task_id, task_status=snapshot.status.value, action="batch_refresh_details"))
        return DeviceTaskBatchDTO(action="batch_refresh_details", tasks=references)

    def preview_import(self, payload: DeviceImportPreviewRequestDTO) -> DeviceImportPreviewDTO:
        path = Path(payload.path).expanduser().resolve()
        source_name = path.name
        source_sha256 = self._file_sha256(path) if path.is_file() else ""
        errors: list[str] = []
        warnings: list[str] = []
        columns: list[str] = []
        row_count = 0
        mapped_rows: list[tuple[int, dict[str, object | None]]] = []
        try:
            if not path.is_file():
                raise FileNotFoundError("CSV 文件不存在")
            site_id = self.current_site_id()
            repository, groups, _ = self._repositories(site_id)
            importer = DeviceImportExportService(repository, groups)
            rows = importer._read_csv_rows(path)
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
        with self._mutation_lock:
            self._import_previews[token] = {
                "site": self.current_site_id(),
                "path": str(path),
                "sha256": source_sha256,
                "expires": datetime.now(UTC).timestamp() + DEVICE_IMPORT_PREVIEW_TTL_SECONDS,
                "errors": tuple(errors),
            }
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
        with self._mutation_lock:
            preview = self._import_previews.pop(payload.preview_token, None)
        if not preview or preview.get("site") != site or float(preview.get("expires") or 0) < datetime.now(UTC).timestamp():
            raise ValueError("导入预览 token 无效或已过期")
        path = Path(str(preview.get("path") or ""))
        if tuple(preview.get("errors") or ()):
            raise ValueError("导入预览存在错误，不能确认")
        if not path.is_file() or self._file_sha256(path) != str(preview.get("sha256") or ""):
            raise ValueError("CSV 文件已变化，请重新预览")
        backup_path = self._backup_device_database(site)
        operation_id = f"device-import-{uuid.uuid4().hex}"
        self._write_import_audit(site, operation_id, {"status": "PENDING", "source_file": path.name, "source_sha256": preview.get("sha256"), "backup_reference": str(backup_path)})
        task_id = f"device-import-{uuid.uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type="device_csv_import",
            params={
                "path": str(path),
                "db_path": str(self.paths.site_db_path(site)),
                "site_name": site,
                "task_name": f"设备 CSV 导入 · {path.name}",
                "owner": "web_device_management",
            },
        )
        self.process_adapter.start_job(job, on_complete=lambda completion: self._finish_import(site, operation_id, backup_path, completion))
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None:
            raise RuntimeError("设备导入任务创建后未写入任务中心")
        return DeviceTaskReferenceDTO(task_id=task_id, task_status=snapshot.status.value, action="import_csv")

    def start_diagnostic_download(self, device_uuids: list[str]) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        devices, _groups, _facts = self._repositories(site)
        selected = [self._require_device(devices, value) for value in self._unique_ids(device_uuids)]
        task_id = f"device-diagnostic-{uuid.uuid4().hex}"
        self.task_service.create_external_task(
            task_id=task_id,
            task_type="device_diagnostic_download",
            task_name="设备诊断信息下载",
            source="web",
            site_name=site,
            owner="web_device_management",
            device=",".join(str(device.device_uuid or "") for device in selected),
        )
        thread = threading.Thread(target=self._run_diagnostic_task, args=(task_id, site, selected), name=f"device-diagnostic-{task_id}", daemon=True)
        thread.start()
        return DeviceTaskReferenceDTO(task_id=task_id, task_status=TaskState.PENDING.value, action="diagnostic_download")

    def external_terminal_action(self, device_uuid: str, payload: DeviceExternalTerminalRequestDTO) -> DeviceExternalTerminalActionDTO:
        devices, _groups, _facts = self._repositories(self.current_site_id())
        self._require_device(devices, device_uuid)
        return DeviceExternalTerminalActionDTO(device_uuid=device_uuid, terminal_type=payload.terminal_type)

    def start_csv_export(self, payload: DeviceExportRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        job_payload = {"db_path": str(self.paths.site_db_path(site)), "site_name": site, "filters": filters}
        return self._start_export(site, "device_csv", payload.output_path, job_payload, "export_csv")

    def start_template_export(self, output_path: str) -> DeviceTaskReferenceDTO:
        return self._start_export(self.current_site_id(), "device_template_csv", output_path, {}, "export_template")

    def start_securecrt_export(self, payload: DeviceSecureCrtExportRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        marker = Path(payload.output_dir).expanduser().resolve() / ".netconsole_securecrt_export.txt"
        job_payload = {
            "output_dir": str(Path(payload.output_dir).expanduser().resolve()),
            "db_path": str(self.paths.site_db_path(site)),
            "site_name": site,
            "selected_device_uuids": list(payload.device_uuids),
            "filters": filters,
            "template_ini": payload.template_ini,
        }
        return self._start_export(site, "securecrt_sessions", str(marker), job_payload, "securecrt_sessions")

    def start_omnipeek_export(self, payload: DeviceOmniPeekExportRequestDTO) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        output_path = Path(payload.output_path).expanduser().resolve()
        job_payload = {
            "db_path": str(self.paths.site_db_path(site)),
            "site_name": site,
            "source": {"device_filters": filters, "selected_device_uuids": list(payload.device_uuids), "ac_uuid": ""},
            "config": {"line_name": payload.line_name, "output_path": str(output_path), "include_ac_fit_ap": False, "include_ap_extensions": False, "include_device_mr": payload.include_device_mr},
            "selected_item_keys": list(payload.selected_item_keys),
            "excluded_item_keys": list(payload.excluded_item_keys),
            "force_export_keys": list(payload.force_export_keys),
        }
        return self._start_export(site, "omnipeek_name_table", str(output_path), job_payload, "omnipeek_name_table")

    def get_export_task(self, task_id: str) -> DeviceTaskReferenceDTO:
        snapshot = self.task_service.repository(self.current_site_id()).get(task_id)
        if snapshot is None or not snapshot.task_type.startswith("device_export_"):
            raise KeyError(task_id)
        result = dict(snapshot.result or {})
        return DeviceTaskReferenceDTO(task_id=task_id, task_status=snapshot.status.value, action=snapshot.task_type.removeprefix("device_export_"), output_path=str(result.get("path") or result.get("output_path") or ""))

    def open_export_artifact(self, task_id: str) -> tuple[Path, str]:
        snapshot = self.task_service.repository(self.current_site_id()).get(task_id)
        if snapshot is None or not snapshot.task_type.startswith("device_export_"):
            raise KeyError(task_id)
        if snapshot.status is not TaskState.COMPLETED:
            raise ValueError("导出任务尚未完成")
        result = dict(snapshot.result or {})
        path = Path(str(result.get("path") or result.get("output_path") or "")).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("导出文件不存在；SecureCRT 会话请打开输出目录")
        return path, path.name

    def _device_from_write(self, payload: DeviceWriteRequestDTO, existing: Device | None, groups: DeviceGroupRepository) -> Device:
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
    def _safe_device_record(device: Device) -> dict[str, object | None]:
        record = device.to_record()
        for field in SENSITIVE_DEVICE_FIELDS:
            if field in record:
                record[field] = None
        return record

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

    def _restore_device_database(self, backup_path: Path, site: str) -> None:
        target = self.paths.site_db_path(site).resolve()
        with connect_sqlite(backup_path) as source, connect_sqlite(target) as destination:
            source.backup(destination)
            destination.commit()
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("设备数据库回滚完整性校验失败")

    def _write_import_audit(self, site: str, operation_id: str, payload: dict[str, object]) -> None:
        path = self.paths.site_imports_dir(site) / "device_import_audit" / f"{operation_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"operation_id": operation_id, **payload}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _finish_import(self, site: str, operation_id: str, backup_path: Path, completion: object) -> None:
        payload = dict(getattr(completion, "payload", None) or {})
        result = dict(payload.get("result") or {})
        exit_code = getattr(completion, "exit_code", None)
        failed = (
            exit_code is None
            or int(exit_code) != 0
            or bool(getattr(completion, "cancelled", False))
            or bool(result.get("errors"))
            or int(result.get("skipped") or 0) > 0
        )
        audit: dict[str, object] = {"status": "ROLLED_BACK" if failed else "APPLIED", "backup_reference": str(backup_path), "created_count": int(result.get("created") or 0), "skipped_count": int(result.get("skipped") or 0)}
        if failed:
            try:
                self._restore_device_database(backup_path, site)
            except Exception as exc:
                audit.update({"status": "ROLLBACK_FAILED", "error_summary": str(exc)})
        self._write_import_audit(site, operation_id, audit)

    def _export_filters(self, payload: DeviceExportRequestDTO) -> dict[str, object | None]:
        return {
            "search": payload.search.strip() or None,
            "vendor": payload.vendor.strip() or None,
            "device_type": payload.device_type.strip() or None,
            "group_filter": payload.group_filter,
        }

    def _start_export(self, site: str, export_type: str, output_path: str, payload: dict[str, object], action: str) -> DeviceTaskReferenceDTO:
        target = Path(output_path).expanduser().resolve()
        task_id = f"device_export_{export_type}_{uuid.uuid4().hex}"
        job = ExportJob(
            job_id=task_id,
            job_type=export_type,
            site_name=site,
            output_path=str(target),
            db_path=str(self.paths.site_db_path(site)),
            params={"payload": payload},
        )
        job_dir = self.paths.runtime_cache_dir / "export_jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(f"{target.name}.{task_id}.tmp")
        job = job.with_runtime_paths(tmp_path=str(tmp_path), cancel_path=str(job_dir / f"{task_id}.cancel"))
        job_path = job_dir / f"{task_id}.json"
        job_path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.task_service.create_external_task(
            task_id=task_id,
            task_type=f"device_export_{export_type}",
            task_name=f"设备{action}",
            source="web",
            site_name=site,
            owner="web_device_management",
        )
        try:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(self.paths.app_root) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
            process = subprocess.Popen(
                [sys.executable, "-m", "netconsole.export_worker", "--job", str(job_path)],
                cwd=str(self.paths.app_root),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._export_processes[task_id] = process
            self.task_service.record_external_event(task_id, "state", {"state": TaskState.RUNNING.value}, site_name=site)
            threading.Thread(target=self._monitor_export, args=(task_id, site, process, job_path), name=f"device-export-{task_id}", daemon=True).start()
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc))
            self.task_service.record_external_event(task_id, "error", {"message": message, "error": message}, site_name=site)
            try:
                job_path.unlink()
            except OSError:
                pass
        return DeviceTaskReferenceDTO(task_id=task_id, task_status=TaskState.RUNNING.value, action=action, output_path=str(target))

    def _monitor_export(self, task_id: str, site: str, process: subprocess.Popen[str], job_path: Path) -> None:
        terminal = False
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    event = parse_event_line(line.strip())
                    if not event or str(event.get("job_id") or "") != task_id:
                        continue
                    event_type = str(event.get("type") or "")
                    safe_payload = {key: event[key] for key in ("stage", "current", "total", "message", "result", "error", "cancelled") if key in event}
                    if event_type in {"progress", "log", "finished", "error", "cancelled"}:
                        self.task_service.record_external_event(task_id, event_type, safe_payload, site_name=site)
                    if event_type in {"finished", "error", "cancelled"}:
                        terminal = True
            process.wait(timeout=10)
            if not terminal:
                message = "导出进程异常退出" if process.returncode else "导出任务未返回完成事件"
                self.task_service.record_external_event(task_id, "error", {"message": message, "error": message}, site_name=site)
        except Exception as exc:
            try:
                self.task_service.record_external_event(task_id, "error", {"message": str(exc), "error": str(exc)}, site_name=site)
            except Exception:
                pass
        finally:
            self._export_processes.pop(task_id, None)
            try:
                job_path.unlink()
            except OSError:
                pass

    def _run_diagnostic_task(self, task_id: str, site: str, devices: list[Device]) -> None:
        try:
            self.task_service.record_external_event(task_id, "state", {"state": TaskState.RUNNING.value}, site_name=site)
            if len(devices) == 1:
                results = [DiagnosticDownloadService(site, self.paths).download(devices[0])]
            else:
                results = run_batch_diagnostic_download(devices, lambda: DiagnosticDownloadService(site, self.paths))
            self.task_service.record_external_event(
                task_id,
                "finished",
                {
                    "result": {
                        "results": [
                            {"device_id": result.device_id, "device_name": result.device_name, "file_path": result.file_path or "", "status": result.status, "error_message": result.error_message or "", "elapsed_ms": result.elapsed_ms}
                            for result in results
                        ]
                    }
                },
                site_name=site,
            )
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc))
            self.task_service.record_external_event(task_id, "error", {"message": message, "error": message}, site_name=site)

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
                    if task.task_type == DEVICE_CONNECTION_TEST_TASK_TYPE
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
                    "owner": "web_device_management",
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
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None or snapshot.task_type != DEVICE_CONNECTION_TEST_TASK_TYPE:
            raise KeyError(task_id)
        device_repository, _, _ = self._repositories(site)
        return self._connection_test_dto(snapshot, device_repository.get_by_uuid(snapshot.device))

    async def stop(self) -> None:
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
        return [task for task in tasks if str(task.device or "").strip().casefold() in aliases]

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


def _protocol_from_task_id(task_id: str) -> str:
    parts = str(task_id or "").split("-", 3)
    return parts[2].upper() if len(parts) >= 4 and parts[:2] == ["device", "test"] and parts[2] in {"ssh", "telnet", "snmp"} else ""


__all__ = [
    "DEVICE_CONNECTION_TEST_TASK_TYPE",
    "DeviceManagementWebService",
    "run_device_connection_test",
]
