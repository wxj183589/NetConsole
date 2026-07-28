from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Protocol
import uuid
from threading import RLock

from netconsole.application.desktop import DesktopActionService, RegisteredLaunch
from netconsole.application.web_artifacts import WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.settings import SettingsStore, normalize_external_terminal_type
from netconsole.core.sites import SiteManager
from netconsole.models.api.device_management import (
    DeviceCapabilityDTO,
    DeviceBatchConnectionRequestDTO,
    DeviceCollectionSummaryDTO,
    DeviceConnectionCommandDTO,
    DeviceConnectionTestDTO,
    DeviceCredentialRevealDTO,
    DeviceDetailDTO,
    DeviceEditProfileDTO,
    DeviceDetailItemDTO,
    DeviceBatchRefreshRequestDTO,
    DeviceDeleteDTO,
    DeviceDeleteRequestDTO,
    DeviceDeletionTokenDTO,
    DeviceDeletionTokenRequestDTO,
    DeviceExternalTerminalActionDTO,
    DeviceExternalTerminalBatchDTO,
    DeviceExternalTerminalBatchRequestDTO,
    DeviceExternalTerminalConfirmationDTO,
    DeviceExternalTerminalConfirmationRequestDTO,
    DeviceExternalTerminalRequestDTO,
    DeviceExternalTerminalSettingsDTO,
    DeviceExternalTerminalSettingsUpdateDTO,
    DeviceExportRequestDTO,
    DeviceFormConnectionTestRequestDTO,
    DeviceGroupAssignmentDTO,
    DeviceGroupAssignmentRequestDTO,
    DeviceGroupDeleteDTO,
    DeviceGroupDTO,
    DeviceGroupRequestDTO,
    DeviceImportConfirmRequestDTO,
    DeviceImportErrorDTO,
    DeviceImportPreviewDTO,
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
from netconsole.models.api.device_detail import (
    DeviceDetailSourceDTO,
    DeviceHistoryPageDTO,
    DeviceHistoryRecordDTO,
)
from netconsole.models.device import Device, validate_device_vendor_type
from netconsole.models.device_detail import DeviceOperationTask
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.config_lifecycle_service import safe_artifact_display_name
from netconsole.services.device_group_service import DeviceGroupService
from netconsole.services.device_import_export import (
    DeviceImportExportService,
    make_device_export_filename,
    make_device_template_filename,
)
from netconsole.services.device_connection_preflight import (
    DeviceConnectionPreflightError,
    credential_status_message,
    validate_device_connection_preflight,
)
from netconsole.services.device_web_service import build_https_url, effective_https_port
from netconsole.services.diagnostic_download_service import (
    DiagnosticDownloadService,
    run_batch_diagnostic_download,
)
from netconsole.services.export.export_job import ExportJob
from netconsole.services.external_terminal import (
    TERMINAL_SETTING_KEYS,
    available_external_terminal_configs,
    build_external_terminal_command,
)
from netconsole.services.file_contract import attach_export_metadata
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.netmiko_connection import (
    connection_targets,
    extract_sysname_from_prompt,
    sanitize_sensitive_text,
)
from netconsole.services.settings_tool_validation import validate_settings_tool_path
from netconsole.services.job_center.worker_protocol import parse_event_line
from netconsole.utils.natural_sort import natural_text_key


DEVICE_CONNECTION_TEST_TASK_TYPE = "device_connection_test"
ACTIVE_TASK_STATES = {
    TaskState.PENDING,
    TaskState.STARTING,
    TaskState.RUNNING,
    TaskState.STOPPING,
}
DEVICE_IMPORT_PREVIEW_TTL_SECONDS = 15 * 60
DEVICE_IMPORT_CLAIM_GRACE_SECONDS = 60
DEVICE_DELETE_TOKEN_TTL_SECONDS = 5 * 60
DEVICE_TERMINAL_TOKEN_TTL_SECONDS = 5 * 60
DEVICE_TERMINAL_CONFIRMATION_THRESHOLD = 20
MAX_DEVICE_IMPORT_BYTES = 16 * 1024 * 1024
MAX_SECURECRT_TEMPLATE_BYTES = 2 * 1024 * 1024
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
        "web_export_device_csv",
        "web_export_device_template_csv",
        "device_export_device_csv",
        "device_export_device_template_csv",
        "device_export_securecrt_sessions",
    }
)
MANAGED_DEVICE_CSV_TASK_TYPE = "web_export_device_csv"
MANAGED_DEVICE_TEMPLATE_CSV_TASK_TYPE = "web_export_device_template_csv"
MANAGED_DEVICE_CSV_TASK_TYPES = frozenset(
    {MANAGED_DEVICE_CSV_TASK_TYPE, MANAGED_DEVICE_TEMPLATE_CSV_TASK_TYPE}
)
MANAGED_DEVICE_CSV_ARTIFACT_SOURCE = "device_csv_export"
_DEVICE_EXPORT_DISPLAY_NAMES = {
    "web_export_device_csv": ("设备清单", ".csv"),
    "web_export_device_template_csv": ("设备导入模板", ".csv"),
    "device_export_device_csv": ("设备清单", ".csv"),
    "device_export_device_template_csv": ("设备导入模板", ".csv"),
    "device_export_securecrt_sessions": ("SecureCRT会话", ".zip"),
    "device_diagnostic_download": ("设备诊断", ".zip"),
}


def device_export_display_name(task_type: str, value: object = "") -> str:
    contract = _DEVICE_EXPORT_DISPLAY_NAMES.get(str(task_type or ""))
    if contract is None:
        return ""
    label, suffix = contract
    return safe_artifact_display_name(value, suffix, label)


DEVICE_COLLECT_TASK_TYPE = "device_detail_collect"
DEVICE_OPTICAL_REFRESH_TASK_TYPE = "device_optical_refresh"
DEVICE_DIAGNOSTIC_TASK_TYPE = "device_diagnostic_download"
DEVICE_IMPORT_TASK_TYPE = "device_csv_import"
DEVICE_FORM_TEST_BOOTSTRAP_MAX_BYTES = 64 * 1024
DEVICE_FORM_TEST_SECRET_FIELDS = (
    "ssh_password",
    "telnet_password",
    "tunnel1_password",
    "tunnel2_password",
    "snmp_ro_community",
)
DEVICE_SECRET_FIELD_NAMES = (
    "password",
    "ssh_password",
    "telnet_password",
    "tunnel1_password",
    "tunnel2_password",
    "snmp_ro_community",
)
VEHICLE_MR_GROUP_NAME = "车载-MR"
VEHICLE_MR_LEGACY_TYPE = "Cloud-AP"
VEHICLE_MR_DEVICE_TYPE = "MR"
VEHICLE_MR_NAME_PATTERN = re.compile(r"^列车\d{1,3}-MR-(?:CT|CW)$", re.IGNORECASE)
DEVICE_TASK_TYPES = frozenset(
    {
        DEVICE_CONNECTION_TEST_TASK_TYPE,
        DEVICE_COLLECT_TASK_TYPE,
        DEVICE_OPTICAL_REFRESH_TASK_TYPE,
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


class DeviceInventoryOperationService(Protocol):
    def start_many(
        self,
        device_uuids: list[str],
        operation_id: str,
        *,
        idempotency_key: str,
    ) -> list[DeviceOperationTask]: ...


class DeviceManagementWebService:
    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        desktop_action_service: DesktopActionService,
        site_name: str | None = None,
        process_adapter: LocalProcessAdapter | None = None,
        export_adapter: WebExportProcessAdapter | None = None,
        artifact_store: WebArtifactStore | None = None,
        device_operation_service: DeviceInventoryOperationService | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.desktop_action_service = desktop_action_service
        self.site_name = site_name
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self.export_adapter = export_adapter or WebExportProcessAdapter(task_service)
        self.artifact_store = artifact_store or WebArtifactStore(paths, task_service)
        self.device_operation_service = device_operation_service
        self._start_lock = RLock()
        self._mutation_lock = RLock()
        self._delete_tokens: dict[str, dict[str, object]] = {}
        self._terminal_tokens: dict[str, dict[str, object]] = {}
        self._export_processes: dict[str, subprocess.Popen[str]] = {}
        self._export_artifacts: dict[str, dict[str, object]] = {}
        self._reconciled_import_sites: set[str] = set()
        self._reconciled_vehicle_mr_sites: set[str] = set()

    def current_site_id(self) -> str:
        site = self.site_name or SiteManager(self.paths).get_current_site()
        selected = SiteManager(self.paths).validate_site_name(str(site or "demo"))
        with self._mutation_lock:
            if selected not in self._reconciled_vehicle_mr_sites:
                self._migrate_vehicle_mr_device_types(selected)
                self._reconciled_vehicle_mr_sites.add(selected)
            if selected not in self._reconciled_import_sites:
                self._reconcile_import_audits(selected)
                self._cleanup_expired_import_previews(selected)
                self._cleanup_stale_securecrt_templates(selected)
                self._cleanup_unowned_diagnostic_temps(selected)
                self._reconciled_import_sites.add(selected)
        return selected

    def _migrate_vehicle_mr_device_types(self, site: str) -> None:
        """修正早期把车载 MR 保存为 Cloud-AP 的受控历史数据。"""

        database = Database(self.paths.site_db_path(site))
        if not database.exists():
            return
        with database.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.device_uuid, d.name, d.device_type, g.name AS group_name
                FROM devices d
                JOIN device_groups g ON g.id = d.group_id
                WHERE d.device_type = ? AND g.name = ?
                ORDER BY d.id
                """,
                (VEHICLE_MR_LEGACY_TYPE, VEHICLE_MR_GROUP_NAME),
            ).fetchall()
        candidates = [dict(row) for row in rows]
        matched = [
            row
            for row in candidates
            if VEHICLE_MR_NAME_PATTERN.fullmatch(str(row.get("name") or "").strip())
        ]
        skipped_count = len(candidates) - len(matched)
        if not matched:
            app_logger.log_info(
                "DEVICE_TYPE_MIGRATION_SKIPPED",
                (
                    f"site_name={site}, scanned_count={len(candidates)}, "
                    f"migrated_count=0, skipped_count={skipped_count}"
                ),
            )
            return
        backup_dir = self.paths.site_backups_dir(site) / "device-type-migrations"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / (
            "vehicle-mr-device-type-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.sqlite"
        )
        DeviceRepository(database).backup_to(backup_path)
        now = datetime.now().isoformat(timespec="seconds")
        ids = [int(row["id"]) for row in matched]
        placeholders = ", ".join("?" for _ in ids)
        with database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"""
                UPDATE devices
                SET device_type = ?, updated_at = ?
                WHERE id IN ({placeholders}) AND device_type = ?
                """,
                [VEHICLE_MR_DEVICE_TYPE, now, *ids, VEHICLE_MR_LEGACY_TYPE],
            )
            conn.commit()
        migrated_count = int(cursor.rowcount or 0)
        for row in matched:
            app_logger.log_info(
                "DEVICE_TYPE_MIGRATION_ITEM",
                (
                    f"site_name={site}, device_uuid={row.get('device_uuid')}, "
                    f"old_type={VEHICLE_MR_LEGACY_TYPE}, new_type={VEHICLE_MR_DEVICE_TYPE}"
                ),
            )
        app_logger.log_info(
            "DEVICE_TYPE_MIGRATION_COMPLETED",
            (
                f"site_name={site}, scanned_count={len(candidates)}, "
                f"migrated_count={migrated_count}, skipped_count={skipped_count}, "
                f"backup={backup_path.name}"
            ),
        )

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
        group_names = {
            int(group.id): group.name for group in groups if group.id is not None
        }
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
        items = [
            self._list_item(device, group_names, self._latest_test(tasks, device))
            for device in devices
        ]
        selected_status = connection_status.strip().upper()
        if selected_status:
            items = [
                item for item in items if item.connection_status == selected_status
            ]
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
            groups=[
                DeviceGroupOptionDTO(id=int(group.id), name=group.name)
                for group in groups
                if group.id is not None
            ],
            site_name=site,
            total=total,
            page=selected_page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_device_detail(self, device_uuid: str) -> DeviceDetailDTO:
        """旧详情兼容路径；新抽屉/详情页不得调用此全量聚合。"""
        site = self.current_site_id()
        device_repository, group_repository, fact_repository = self._repositories(site)
        device = self._require_device(device_repository, device_uuid)
        groups = {
            int(group.id): group.name
            for group in group_repository.list()
            if group.id is not None
        }
        tasks = self._device_tasks(
            self._owned_web_tasks(
                self.task_service.repository(site).list(limit=1000),
                site,
            ),
            device,
        )
        list_item = self._list_item(device, groups, self._latest_test(tasks, device))
        fact = fact_repository.get_device_fact(device_uuid)
        collection = (
            fact_repository.get_collect_run(str(fact.get("collect_run_uuid") or ""))
            if fact
            else None
        )
        task_summaries = [self._task_summary(task, device) for task in tasks[:10]]
        collection_summary = self._collection_summary(collection, device)
        errors = self._recent_errors(tasks, collection, device)
        interfaces = fact_repository.list_device_interfaces(device_uuid)
        optical_modules = fact_repository.list_optical_modules(device_uuid)
        lldp_neighbors = fact_repository.list_lldp_neighbors(device_uuid)
        trackside_ap_business = self._trackside_ap_business(
            device,
            interfaces,
            optical_modules,
            lldp_neighbors,
        )
        return DeviceDetailDTO(
            device=self._detail_item(device, list_item),
            fact=self._fact_summary(fact),
            recent_tasks=task_summaries,
            recent_collection=collection_summary,
            recent_errors=errors,
            connection_commands=self._connection_commands(device),
            interfaces=interfaces,
            optical_modules=optical_modules,
            lldp_neighbors=lldp_neighbors,
            trackside_ap_business=trackside_ap_business,
        )

    def get_device_edit_profile(self, device_uuid: str) -> DeviceEditProfileDTO:
        site = self.current_site_id()
        devices, groups, _facts = self._repositories(site)
        device = self._require_device(devices, device_uuid)
        latest_test = next(
            iter(
                self.task_service.repository(site).list_filtered(
                    task_types={DEVICE_CONNECTION_TEST_TASK_TYPE},
                    device=str(device.device_uuid or ""),
                    limit=1,
                )
            ),
            None,
        )
        group_names: dict[int, str] = {}
        if device.group_id is not None:
            try:
                group_names[int(device.group_id)] = groups.get(
                    int(device.group_id)
                ).name
            except KeyError:
                pass
        detail = self._detail_item(
            device, self._list_item(device, group_names, latest_test)
        )
        return DeviceEditProfileDTO(
            **detail.model_dump(),
            protocol=str(device.protocol or "").strip() or None,
            port=int(device.port) if device.port is not None else None,
            ssh_enabled=bool(device.ssh_enabled),
            ssh_port=int(device.ssh_port or 22),
            telnet_enabled=bool(device.telnet_enabled),
            telnet_port=int(device.telnet_port or 23),
            snmp_enabled=bool(device.snmp_enabled),
            snmp_port=int(device.snmp_port or 161),
        )

    def reveal_device_credentials(
        self, device_uuid: str, credential_field: str
    ) -> DeviceCredentialRevealDTO:
        if credential_field not in DEVICE_FORM_TEST_SECRET_FIELDS:
            raise ValueError("设备凭据字段无效")
        devices, _groups, _facts = self._repositories(self.current_site_id())
        device = self._require_device(devices, device_uuid)
        value = getattr(device, credential_field)
        if credential_field == "ssh_password" and not value:
            value = device.password
        return DeviceCredentialRevealDTO(
            device_uuid=str(device.device_uuid or ""),
            credential_field=credential_field,
            value=str(value or ""),
        )

    def get_device_history(
        self,
        device_uuid: str,
        kind: str,
        object_name: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceHistoryPageDTO:
        devices, _groups, facts = self._repositories(self.current_site_id())
        self._require_device(devices, device_uuid)
        normalized_kind = str(kind or "").strip().lower()
        name = str(object_name or "").strip()
        if normalized_kind not in {"interface", "optical", "lldp"}:
            raise ValueError("不支持的设备历史类型")
        size = max(1, min(int(page_size), 200))
        total = facts.count_object_history(normalized_kind, device_uuid, name)
        total_pages = max(1, math.ceil(total / size))
        selected_page = min(max(1, page), total_pages)
        rows = facts.list_object_history_page(
            normalized_kind,
            device_uuid,
            name,
            limit=size,
            offset=(selected_page - 1) * size,
        )
        fields = {
            "interface": (
                "link_status",
                "protocol_status",
                "speed",
                "duplex",
                "interface_type",
                "port_status",
                "pvid",
                "description",
                "ip_address",
                "mac_address",
                "vlan",
            ),
            "optical": (
                "rx_power",
                "tx_power",
                "temperature",
                "voltage",
                "bias_current",
                "module_model",
                "module_serial_number",
                "module_vendor",
                "rx_low_alarm",
                "rx_high_alarm",
                "rx_low_warning",
                "rx_high_warning",
            ),
            "lldp": (
                "neighbor_sysname",
                "neighbor_mac",
                "neighbor_interface",
                "neighbor_ip",
                "neighbor_device_uuid",
            ),
        }[normalized_kind]
        items = [
            DeviceHistoryRecordDTO(
                kind=normalized_kind,
                object_name=name,
                collected_at=str(row.get("collected_at") or "") or None,
                values={field: row.get(field) for field in fields},
            )
            for row in rows
        ]
        return DeviceHistoryPageDTO(
            items=items,
            total=total,
            page=selected_page,
            page_size=size,
            total_pages=total_pages,
            source=DeviceDetailSourceDTO(
                source="device_management_web_service",
                collected_at=items[0].collected_at if items else None,
            ),
        )

    def list_groups(self) -> list[DeviceGroupDTO]:
        _device_repository, group_repository, _facts = self._repositories(
            self.current_site_id()
        )
        counts = group_repository.counts()
        return [
            DeviceGroupDTO(
                id=int(group.id),
                name=group.name,
                device_count=counts.get(int(group.id), 0),
            )
            for group in group_repository.list()
            if group.id is not None
        ]

    def create_device(self, payload: DeviceWriteRequestDTO) -> DeviceWriteDTO:
        site = self.current_site_id()
        device_repository, group_repository, _facts = self._repositories(site)
        device = self._device_from_write(payload, None, group_repository)
        created = device_repository.create(device)
        return DeviceWriteDTO(
            action="created",
            device=self._write_result_item(created, group_repository),
        )

    def update_device(
        self, device_uuid: str, payload: DeviceWriteRequestDTO
    ) -> DeviceWriteDTO:
        site = self.current_site_id()
        device_repository, group_repository, _facts = self._repositories(site)
        existing = self._require_device(device_repository, device_uuid)
        updated = self._device_from_write(payload, existing, group_repository)
        saved = device_repository.update(updated)
        return DeviceWriteDTO(
            action="updated", device=self._write_result_item(saved, group_repository)
        )

    def duplicate_device(self, device_uuid: str) -> DeviceWriteDTO:
        site = self.current_site_id()
        device_repository, group_repository, _facts = self._repositories(site)
        source = self._require_device(device_repository, device_uuid)
        record = source.to_record()
        record.update(
            {"id": None, "device_uuid": None, "created_at": None, "updated_at": None}
        )
        if str(record.get("name") or "").strip():
            record["name"] = f"{str(record['name']).strip()}-副本"
        created = device_repository.create(Device.from_mapping(record))
        return DeviceWriteDTO(
            action="duplicated",
            device=self._write_result_item(created, group_repository),
        )

    def issue_delete_token(
        self, payload: DeviceDeletionTokenRequestDTO
    ) -> DeviceDeletionTokenDTO:
        site = self.current_site_id()
        device_repository, _groups, _facts = self._repositories(site)
        uuids = self._unique_ids(payload.device_uuids)
        for device_uuid in uuids:
            self._require_device(device_repository, device_uuid)
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=DEVICE_DELETE_TOKEN_TTL_SECONDS)
        with self._mutation_lock:
            self._delete_tokens[token] = {
                "site": site,
                "device_uuids": tuple(uuids),
                "expires": expires.timestamp(),
            }
        return DeviceDeletionTokenDTO(
            confirmation_token=token, device_uuids=uuids, expires_at=expires.isoformat()
        )

    def delete_devices(self, payload: DeviceDeleteRequestDTO) -> DeviceDeleteDTO:
        site = self.current_site_id()
        device_repository, _groups, _facts = self._repositories(site)
        uuids = self._unique_ids(payload.device_uuids)
        with self._mutation_lock:
            token = self._delete_tokens.pop(str(payload.confirmation_token), None)
        if (
            not token
            or token.get("site") != site
            or float(token.get("expires") or 0) < datetime.now(UTC).timestamp()
        ):
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

    def rename_group(
        self, group_id: int, payload: DeviceGroupRequestDTO
    ) -> DeviceGroupDTO:
        site = self.current_site_id()
        _devices, groups, _facts = self._repositories(site)
        group = groups.rename(group_id, payload.name)
        return DeviceGroupDTO(
            id=int(group.id),
            name=group.name,
            device_count=groups.count_devices(group_id),
        )

    def delete_group(self, group_id: int) -> DeviceGroupDeleteDTO:
        site = self.current_site_id()
        _devices, groups, _facts = self._repositories(site)
        groups.delete(group_id)
        return DeviceGroupDeleteDTO()

    def assign_group(
        self, payload: DeviceGroupAssignmentRequestDTO
    ) -> DeviceGroupAssignmentDTO:
        site = self.current_site_id()
        devices, groups, _facts = self._repositories(site)
        if payload.group_id is not None:
            groups.get(payload.group_id)
        ids = [
            int(self._require_device(devices, device_uuid).id or 0)
            for device_uuid in self._unique_ids(payload.device_uuids)
        ]
        result = DeviceGroupService(devices, groups).assign_devices(
            ids, payload.group_id
        )
        return DeviceGroupAssignmentDTO(
            success=result.success, failed=result.failed, group_id=payload.group_id
        )

    def start_batch_refresh(
        self, payload: DeviceBatchRefreshRequestDTO
    ) -> DeviceTaskBatchDTO:
        if self.device_operation_service is None:
            raise RuntimeError("DeviceOperationService 未接线")
        operation_id = "device.inventory.collect"
        batch_key = f"legacy-batch-{uuid.uuid4().hex}"
        tasks = self.device_operation_service.start_many(
            self._unique_ids(payload.device_uuids),
            operation_id,
            idempotency_key=batch_key,
        )
        references = [
            DeviceTaskReferenceDTO(
                task_id=task.task_id,
                task_status=task.status,
                action=task.operation_id,
                message=task.message or "",
            )
            for task in tasks
        ]
        return DeviceTaskBatchDTO(action="batch_refresh_details", tasks=references)

    def start_batch_connection_tests(
        self,
        payload: DeviceBatchConnectionRequestDTO,
    ) -> DeviceTaskBatchDTO:
        site = self.current_site_id()
        devices, _groups, _facts = self._repositories(site)
        planned: list[tuple[str, str]] = []
        for device_uuid in self._unique_ids(payload.device_uuids):
            device = self._require_device(devices, device_uuid)
            protocol = (
                "SSH"
                if device.ssh_enabled
                else "TELNET"
                if device.telnet_enabled
                else "SNMP"
                if device.snmp_enabled
                else ""
            )
            if not protocol:
                raise ValueError(f"设备 {device.name or device_uuid} 未启用连接协议")
            self._validate_connection_preflight(device, protocol)
            planned.append((device_uuid, protocol))
        references: list[DeviceTaskReferenceDTO] = []
        for device_uuid, protocol in planned:
            result = self.start_connection_test(device_uuid, protocol)
            references.append(
                DeviceTaskReferenceDTO(
                    task_id=result.task_id,
                    task_status=result.task_status,
                    action="connection_test",
                    message=result.message,
                )
            )
        return DeviceTaskBatchDTO(action="batch_connection_test", tasks=references)

    def start_optical_refresh(self, device_uuid: str) -> DeviceTaskReferenceDTO:
        devices, _groups, _facts = self._repositories(self.current_site_id())
        self._require_device(devices, device_uuid)
        raise ValueError(
            "未注册独立光模块刷新 Operation；请使用 device.inventory.collect"
        )

    def preview_import(self, filename: str, stream: BinaryIO) -> DeviceImportPreviewDTO:
        site = self.current_site_id()
        self._cleanup_expired_import_previews(site)
        source_name = self._validate_upload_filename(filename)
        staged_path, source_sha256 = self._stage_csv_upload(site, source_name, stream)
        errors: list[DeviceImportErrorDTO] = []
        warnings: list[str] = []
        columns: list[str] = []
        duplicate_rows: list[int] = []
        row_count = 0
        total_rows = 0
        valid_rows = 0
        invalid_rows = 0
        vendor_summary: dict[str, int] = {}
        device_type_summary: dict[str, int] = {}
        create_count = 0
        update_count = 0
        conflict_count = 0
        detected_encoding = ""
        try:
            repository, groups, _ = self._repositories(site)
            importer = DeviceImportExportService(repository, groups)
            preview = importer.preview_csv(staged_path)
            columns = list(preview.columns)
            row_count = preview.total_rows
            total_rows = preview.total_rows
            valid_rows = preview.valid_rows
            invalid_rows = preview.invalid_rows
            vendor_summary = dict(preview.vendor_summary)
            device_type_summary = dict(preview.device_type_summary)
            create_count = preview.create_count
            update_count = preview.update_count
            conflict_count = preview.conflict_count
            detected_encoding = preview.detected_encoding
            duplicate_rows = list(preview.duplicate_rows)
            errors = [
                DeviceImportErrorDTO(
                    line=item.line,
                    device_name=item.device_name,
                    field=item.field,
                    raw_value=item.raw_value,
                    message=item.message,
                )
                for item in preview.errors
            ]
            if duplicate_rows:
                warnings.append(
                    f"有 {len(duplicate_rows)} 行主用地址已存在，请选择重复处理策略"
                )
        except Exception as exc:
            errors.append(
                DeviceImportErrorDTO(
                    message=str(exc) or "CSV 文件解析失败",
                )
            )
            invalid_rows = total_rows
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
                "errors": [item.model_dump(mode="json") for item in errors],
                "warnings": warnings,
                "duplicate_rows": duplicate_rows,
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "invalid_rows": invalid_rows,
                "vendor_summary": vendor_summary,
                "device_type_summary": device_type_summary,
                "create_count": create_count,
                "update_count": update_count,
                "conflict_count": conflict_count,
                "detected_encoding": detected_encoding,
            },
        )
        return DeviceImportPreviewDTO(
            preview_token=token,
            source_name=source_name,
            source_sha256=source_sha256,
            row_count=row_count,
            total_rows=total_rows,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            vendor_summary=vendor_summary,
            device_type_summary=device_type_summary,
            create_count=create_count,
            update_count=update_count,
            conflict_count=conflict_count,
            detected_encoding=detected_encoding,
            columns=columns,
            errors=errors,
            warnings=warnings,
            duplicate_rows=duplicate_rows,
        )

    def confirm_import(
        self, payload: DeviceImportConfirmRequestDTO
    ) -> DeviceTaskReferenceDTO:
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
                    "duplicate_strategy": payload.duplicate_strategy,
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
                    "duplicate_strategy": payload.duplicate_strategy,
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

    def start_diagnostic_download(
        self, device_uuids: list[str]
    ) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        devices, _groups, _facts = self._repositories(site)
        selected_uuids = self._unique_ids(device_uuids)
        for value in selected_uuids:
            self._require_device(devices, value)
        task_id = f"device-diagnostic-{uuid.uuid4().hex}"
        artifact_id = f"device-diagnostic-{uuid.uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=DEVICE_DIAGNOSTIC_TASK_TYPE,
            params={
                "site_name": site,
                "device_uuids": selected_uuids,
                "artifact_id": artifact_id,
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

    def external_terminal_action(
        self, device_uuid: str, payload: DeviceExternalTerminalRequestDTO
    ) -> DeviceExternalTerminalActionDTO:
        devices, _groups, _facts = self._repositories(self.current_site_id())
        device = self._require_device(devices, device_uuid)
        result = self.desktop_action_service.launch_terminal(
            DEVICE_TERMINAL_ACTION_IDS[payload.terminal_type],
            device_uuid,
            self._external_terminal_launch(device, payload.terminal_type),
        )
        if not result.success:
            raise ValueError(result.message or result.code)
        return DeviceExternalTerminalActionDTO(
            device_uuid=device_uuid,
            terminal_type=payload.terminal_type,
            code=result.code,
            message=result.message,
        )

    def launch_external_terminals(
        self, payload: DeviceExternalTerminalBatchRequestDTO
    ) -> DeviceExternalTerminalBatchDTO:
        selected = self._unique_ids(payload.device_uuids)
        if len(selected) > DEVICE_TERMINAL_CONFIRMATION_THRESHOLD:
            with self._mutation_lock:
                confirmation = self._terminal_tokens.pop(
                    str(payload.confirmation_token or ""), None
                )
            if (
                not confirmation
                or confirmation.get("site") != self.current_site_id()
                or float(confirmation.get("expires") or 0)
                < datetime.now(UTC).timestamp()
                or tuple(confirmation.get("device_uuids") or ()) != tuple(selected)
                or confirmation.get("terminal_type") != payload.terminal_type
            ):
                raise ValueError("批量外部终端确认 token 无效或已过期")
        success = 0
        failures: list[str] = []
        for device_uuid in selected:
            try:
                self.external_terminal_action(
                    device_uuid,
                    DeviceExternalTerminalRequestDTO(
                        terminal_type=payload.terminal_type
                    ),
                )
                success += 1
            except (KeyError, ValueError) as exc:
                failures.append(f"{device_uuid}: {sanitize_sensitive_text(str(exc))}")
        return DeviceExternalTerminalBatchDTO(
            terminal_type=payload.terminal_type,
            success=success,
            failed=len(failures),
            failures=failures[:20],
        )

    def issue_external_terminal_confirmation(
        self, payload: DeviceExternalTerminalConfirmationRequestDTO
    ) -> DeviceExternalTerminalConfirmationDTO:
        site = self.current_site_id()
        devices, _groups, _facts = self._repositories(site)
        selected = self._unique_ids(payload.device_uuids)
        if len(selected) <= DEVICE_TERMINAL_CONFIRMATION_THRESHOLD:
            raise ValueError("不超过 20 台设备无需批量终端确认")
        for device_uuid in selected:
            self._require_device(devices, device_uuid)
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(
            seconds=DEVICE_TERMINAL_TOKEN_TTL_SECONDS
        )
        with self._mutation_lock:
            self._terminal_tokens[token] = {
                "site": site,
                "device_uuids": tuple(selected),
                "terminal_type": payload.terminal_type,
                "expires": expires.timestamp(),
            }
        return DeviceExternalTerminalConfirmationDTO(
            confirmation_token=token,
            device_uuids=selected,
            terminal_type=payload.terminal_type,
            expires_at=expires.isoformat(),
        )

    def get_external_terminal_settings(self) -> DeviceExternalTerminalSettingsDTO:
        self._require_desktop_runtime()
        settings = SettingsStore(self.paths)
        return DeviceExternalTerminalSettingsDTO(
            terminal_type=normalize_external_terminal_type(
                settings.get_value("external_terminal/type", "securecrt")
            ),
            securecrt_path=str(
                settings.get_value("external_terminal/securecrt_path", "") or ""
            ),
            xshell_path=str(
                settings.get_value("external_terminal/xshell_path", "") or ""
            ),
            putty_path=str(
                settings.get_value("external_terminal/putty_path", "") or ""
            ),
            pass_password=bool(
                settings.get_value("external_terminal/pass_password", False)
            ),
        )

    def update_external_terminal_settings(
        self, payload: DeviceExternalTerminalSettingsUpdateDTO
    ) -> DeviceExternalTerminalSettingsDTO:
        self._require_desktop_runtime()
        values = {
            "securecrt": payload.securecrt_path,
            "xshell": payload.xshell_path,
            "putty": payload.putty_path,
        }
        validated = {
            terminal_type: self._validated_terminal_executable(terminal_type, value)
            for terminal_type, value in values.items()
        }
        settings = SettingsStore(self.paths)
        for terminal_type, value in validated.items():
            settings.set_value(
                TERMINAL_SETTING_KEYS[terminal_type],
                value,
            )
        settings.set_value("external_terminal/type", payload.terminal_type)
        settings.set_value("external_terminal/pass_password", payload.pass_password)
        return self.get_external_terminal_settings()

    def _external_terminal_launch(
        self, device: Device, terminal_type: str
    ) -> RegisteredLaunch:
        self._require_desktop_runtime()
        configs = {
            config.terminal_type: config
            for config in available_external_terminal_configs(SettingsStore(self.paths))
        }
        config = configs.get(terminal_type)
        if config is None:
            raise ValueError("未配置所选外部终端，请先设置程序路径")
        targets = connection_targets(device)
        if not targets:
            raise ValueError("未启用 SSH/Telnet")
        target = targets[0]
        if target.via_tunnel:
            raise ValueError("外部终端暂不支持内部临时隧道，请使用直连地址或可访问地址")
        args = build_external_terminal_command(
            device,
            target,
            config.terminal_type,
            config.exe_path,
            config.include_password,
        )
        executable = Path(args[0])
        return RegisteredLaunch(executable, tuple(args[1:]), executable.parent)

    def _require_desktop_runtime(self) -> None:
        if self.desktop_action_service.runtime_mode is not RuntimeMode.DESKTOP:
            raise ValueError("外部终端仅允许在 Electron Desktop 中使用")

    @staticmethod
    def _validated_terminal_executable(terminal_type: str, value: str) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        return str(validate_settings_tool_path(terminal_type, raw_value))

    def start_csv_export(
        self, payload: DeviceExportRequestDTO
    ) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        selected_device_uuids = (
            self._unique_ids(payload.device_uuids) if payload.device_uuids else []
        )
        export_scope = payload.export_scope or (
            "selected" if selected_device_uuids else "filtered_all"
        )
        if export_scope == "selected" and not selected_device_uuids:
            raise ValueError("导出已选设备时至少需要一个设备 UUID")
        if export_scope == "filtered_all":
            selected_device_uuids = []
        return self._start_managed_device_csv_export(
            site=site,
            job_type="device_csv",
            task_type=MANAGED_DEVICE_CSV_TASK_TYPE,
            task_name=f"设备表格导出 · {site}",
            preferred_name=make_device_export_filename(site),
            job_payload={
                "db_path": str(self.paths.site_db_path(site)),
                "site_name": site,
                "filters": filters,
                "export_scope": export_scope,
                "selected_device_uuids": selected_device_uuids,
                "omit_credentials": not payload.include_credentials,
            },
            start_failure_message="设备表格导出任务启动失败",
            worker_failure_message="设备表格导出 Worker 执行失败",
            cancelled_message="设备表格导出已取消",
        )

    def start_template_export(self) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        return self._start_managed_device_csv_export(
            site=site,
            job_type="device_template_csv",
            task_type=MANAGED_DEVICE_TEMPLATE_CSV_TASK_TYPE,
            task_name=f"设备导入模板 · {site}",
            preferred_name=make_device_template_filename(site),
            job_payload={"mode": "template"},
            start_failure_message="设备导入模板任务启动失败",
            worker_failure_message="设备导入模板生成失败，请查看任务日志",
            cancelled_message="设备导入模板导出已取消",
        )

    def _start_managed_device_csv_export(
        self,
        *,
        site: str,
        job_type: str,
        task_type: str,
        task_name: str,
        preferred_name: str,
        job_payload: dict[str, object],
        start_failure_message: str,
        worker_failure_message: str,
        cancelled_message: str,
    ) -> DeviceTaskReferenceDTO:
        task_id = f"{task_type.replace('_', '-')}-{uuid.uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site,
            owner=WEB_TASK_OWNER,
            source=MANAGED_DEVICE_CSV_ARTIFACT_SOURCE,
            artifact_type="csv",
            task_id=task_id,
            task_type=task_type,
            output_root=self._artifact_root(site),
            preferred_name=preferred_name,
            use_display_name_as_file_name=True,
        )
        job = ExportJob(
            job_id=task_id,
            job_type=job_type,
            site_name=site,
            output_path=str(reservation.output_path),
            db_path=str(self.paths.site_db_path(site)),
            params={"payload": job_payload},
        )

        def completed(result) -> None:
            if result.exit_code == 0 and not result.cancelled:
                try:
                    self.artifact_store.complete(reservation)
                except WebArtifactError:
                    return
            else:
                self.artifact_store.fail(
                    reservation,
                    cancelled_message if result.cancelled else worker_failure_message,
                )

        try:
            self.export_adapter.start_export(
                job,
                task_name=task_name,
                owner=WEB_TASK_OWNER,
                task_type=task_type,
                public_result={
                    "artifact_id": reservation.artifact_id,
                    "artifact_name": reservation.display_name,
                    "artifact_source": MANAGED_DEVICE_CSV_ARTIFACT_SOURCE,
                    "artifact_type": "csv",
                },
                on_complete=completed,
            )
        except Exception:
            self.artifact_store.fail(reservation, start_failure_message)
            raise
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None:
            self.artifact_store.fail(reservation, f"{task_name}未写入任务中心")
            raise RuntimeError(f"{task_name}创建后未写入任务中心")
        return self._task_reference(snapshot)

    def start_securecrt_export(
        self,
        payload: DeviceSecureCrtExportRequestDTO,
        *,
        template_name: str = "",
        template_stream: BinaryIO | None = None,
    ) -> DeviceTaskReferenceDTO:
        site = self.current_site_id()
        filters = self._export_filters(payload)
        job_payload = {
            "db_path": str(self.paths.site_db_path(site)),
            "site_name": site,
            "selected_device_uuids": list(payload.device_uuids),
            "filters": filters,
        }
        staged_template: Path | None = None
        if template_stream is not None:
            staged_template = self._stage_securecrt_template(
                site, template_name, template_stream
            )
            job_payload["template_ini"] = str(staged_template)
        try:
            return self._start_export(
                site,
                "securecrt_sessions",
                "zip",
                job_payload,
                "securecrt_sessions",
            )
        except Exception:
            if staged_template is not None:
                self._remove_sensitive_staged_file(
                    staged_template, self._artifact_root(site)
                )
            raise

    def get_export_task(self, task_id: str) -> DeviceTaskReferenceDTO:
        snapshot = self._require_web_export_task(task_id)
        return self._task_reference(snapshot)

    def open_export_artifact(self, task_id: str, artifact_id: str) -> tuple[Path, str]:
        snapshot = self._require_web_export_task(task_id)
        return self._open_task_artifact(snapshot, artifact_id)

    def open_diagnostic_artifact(
        self, task_id: str, artifact_id: str
    ) -> tuple[Path, str]:
        snapshot = self._require_web_task(
            task_id, frozenset({DEVICE_DIAGNOSTIC_TASK_TYPE})
        )
        return self._open_task_artifact(snapshot, artifact_id)

    def _open_task_artifact(
        self, snapshot: TaskSnapshot, artifact_id: str
    ) -> tuple[Path, str]:
        if snapshot.task_type in MANAGED_DEVICE_CSV_TASK_TYPES:
            path, display_name, _manifest = self.artifact_store.open(
                site_id=snapshot.site_name,
                artifact_id=artifact_id,
                owner=WEB_TASK_OWNER,
                source=MANAGED_DEVICE_CSV_ARTIFACT_SOURCE,
                artifact_type="csv",
                task_type=snapshot.task_type,
            )
            return path, display_name
        if snapshot.status is not TaskState.COMPLETED:
            raise ValueError("文件任务尚未完成")
        result = dict(snapshot.result or {})
        if str(result.get("artifact_id") or "") != artifact_id or not bool(
            result.get("available")
        ):
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
        display_name = device_export_display_name(
            snapshot.task_type, result.get("display_name")
        )
        if not display_name:
            raise ValueError("导出文件显示名无效")
        return path, display_name

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
        if snapshot.task_type in MANAGED_DEVICE_CSV_TASK_TYPES:
            cancel_job = getattr(self.export_adapter, "cancel_job", None)
            if not callable(cancel_job) or not cancel_job(task_id):
                self.task_service.cancel_task(task_id)
        elif snapshot.task_type in EXPORT_TASK_TYPES:
            spec = self._export_artifacts.get(task_id)
            process = self._export_processes.get(task_id)
            job_dir = (self.paths.runtime_cache_dir / "export_jobs").resolve()
            expected_cancel = job_dir / f"{task_id}.cancel"
            expected_job = job_dir / f"{task_id}.json"
            if (
                spec is None
                or str(spec.get("task_id") or "") != task_id
                or str(spec.get("site") or "") != snapshot.site_name
                or str(spec.get("artifact_id") or "") == ""
                or process is None
                or process.poll() is not None
            ):
                raise ValueError("导出任务已失去受管取消接收端")
            cancel_path = Path(str(spec.get("cancel_path") or "")).resolve()
            job_path = Path(str(spec.get("job_path") or "")).resolve()
            if (
                cancel_path != expected_cancel
                or job_path != expected_job
                or not job_path.is_file()
            ):
                raise ValueError("导出任务取消路径不受控")
            try:
                export_job = ExportJob.from_dict(
                    json.loads(job_path.read_text(encoding="utf-8"))
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("导出任务取消接收端无效") from exc
            if (
                export_job.job_id != task_id
                or export_job.site_name != snapshot.site_name
                or snapshot.task_type != f"device_export_{export_job.job_type}"
                or Path(export_job.cancel_path).resolve() != expected_cancel
                or Path(export_job.output_path).resolve()
                != Path(str(spec.get("target") or "")).resolve()
            ):
                raise ValueError("导出任务取消接收端无效")
            try:
                cancel_path.write_text("cancelled", encoding="utf-8")
            except OSError as exc:
                raise ValueError("导出任务取消请求写入失败") from exc
            if process.poll() is not None:
                try:
                    cancel_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise ValueError("导出任务取消请求清理失败") from exc
                raise ValueError("导出任务已结束，取消请求未被接收")
            latest = self._require_web_export_task(task_id)
            if latest.status not in ACTIVE_TASK_STATES:
                try:
                    cancel_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise ValueError("导出任务取消请求清理失败") from exc
                return self._task_reference(latest)
            updated = self.task_service.record_external_event(
                task_id,
                "state",
                {"state": TaskState.STOPPING.value, "message": "已请求停止导出任务"},
                site_name=snapshot.site_name,
            )
            if updated.status is not TaskState.STOPPING:
                try:
                    cancel_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise ValueError("导出任务取消请求清理失败") from exc
                return self._task_reference(updated)
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
        clear_secret_fields = set(values.pop("clear_secret_fields", ()))
        secret_fields = (
            "ssh_password",
            "telnet_password",
            "tunnel1_password",
            "tunnel2_password",
            "snmp_ro_community",
        )
        replaced_secret_fields: set[str] = set()
        for field in secret_fields:
            secret = getattr(payload, field)
            raw = secret.get_secret_value() if secret is not None else ""
            if field in clear_secret_fields:
                if raw:
                    raise ValueError(f"{field} 不能同时替换和清除")
                values[field] = None
            elif existing is not None and not raw:
                values.pop(field, None)
            else:
                values[field] = raw or None
                if raw:
                    replaced_secret_fields.add(field)
        for field in (
            "name",
            "system_name",
            "station",
            "location",
            "device_vendor",
            "device_type",
            "primary_address",
            "backup_address",
            "remark",
            "ssh_username",
            "telnet_username",
            "tunnel1_host",
            "tunnel1_username",
            "tunnel2_host",
            "tunnel2_username",
        ):
            values[field] = str(values.get(field) or "").strip()
        if not values.get("ssh_username") and existing is not None:
            values["ssh_username"] = str(
                existing.ssh_username or existing.username or ""
            ).strip()
        required_usernames = {
            "ssh_password": "ssh_username",
            "telnet_password": "telnet_username",
            "tunnel1_password": "tunnel1_username",
            "tunnel2_password": "tunnel2_username",
        }
        for secret_field, username_field in required_usernames.items():
            if secret_field in replaced_secret_fields and not values.get(
                username_field
            ):
                raise ValueError(f"{username_field} 不能为空，密码尚未保存")
        if not values["name"] or not (
            values["primary_address"] or values["backup_address"]
        ):
            raise ValueError("设备名称以及主用地址或备用地址必填")
        values["device_vendor"], values["device_type"] = validate_device_vendor_type(
            values["device_vendor"], values["device_type"]
        )
        if not values["ssh_enabled"] and not values["telnet_enabled"]:
            raise ValueError("至少启用 SSH 或 Telnet 之一")
        if values["group_id"] is not None:
            groups.get(int(values["group_id"]))
        tunnel1_enabled = bool(values.get("tunnel1_host"))
        tunnel2_enabled = bool(values.get("tunnel2_host"))
        values["tunnel1_enabled"] = tunnel1_enabled
        values["tunnel2_enabled"] = tunnel2_enabled
        values["tunnel_enabled"] = tunnel1_enabled or tunnel2_enabled
        record = existing.to_record() if existing is not None else {}
        record.update(values)
        if record["ssh_enabled"]:
            if "ssh_password" not in clear_secret_fields:
                record["ssh_username"] = (
                    record.get("ssh_username") or record.get("username") or None
                )
                record["ssh_password"] = (
                    record.get("ssh_password") or record.get("password") or None
                )
            record["protocol"] = "SSH"
            record["port"] = record.get("ssh_port") or 22
            record["username"] = record.get("ssh_username") or None
            record["password"] = record.get("ssh_password") or None
        elif record["telnet_enabled"]:
            record["protocol"] = "Telnet"
            record["port"] = record.get("telnet_port") or 23
            record["username"] = record.get("telnet_username") or None
            record["password"] = record.get("telnet_password") or None
        if existing is None:
            record.pop("id", None)
            record.pop("device_uuid", None)
        device = Device.from_mapping(record)
        device.credential_clear_fields = tuple(clear_secret_fields)
        return device

    def _trackside_ap_business(
        self,
        device: Device,
        interfaces: list[dict[str, object | None]],
        optical_modules: list[dict[str, object | None]],
        lldp_neighbors: list[dict[str, object | None]],
    ) -> list[dict[str, object | None]]:
        from netconsole.core.sources.switch_source import build_switch_data_lookup
        from netconsole.repositories.ac_repository import AcRepository
        from netconsole.services.trackside_ap_business import (
            build_trackside_ap_business_rows,
        )

        site = self.current_site_id()
        database = Database(self.paths.site_db_path(site))
        device_uuid = str(device.device_uuid or "")
        lookup = build_switch_data_lookup([device], {device_uuid: optical_modules})
        ac_repository = AcRepository(database)
        return build_trackside_ap_business_rows(
            [device],
            {device_uuid: interfaces},
            {device_uuid: optical_modules},
            ac_repository.list_all_fit_ap_optical(),
            {device_uuid: lldp_neighbors},
            ac_repository.list_all_fit_ap_resources_with_metadata(),
            lookup,
        )

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

    def _cleanup_unowned_diagnostic_temps(self, site: str) -> None:
        repository = self.task_service.repository(site)
        for path in self._artifact_root(site).glob(
            ".device-diagnostic-*.device-diagnostic-*.tmp"
        ):
            parts = path.name.split(".")
            task_id = parts[2] if len(parts) == 4 else ""
            snapshot = repository.get(task_id) if task_id else None
            if snapshot is None or snapshot.status in {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                self._remove_controlled_file(path, path.parent)

    @staticmethod
    def _validate_upload_filename(filename: str) -> str:
        clean = str(filename or "").strip()
        if (
            not clean
            or "\x00" in clean
            or "/" in clean
            or "\\" in clean
            or ":" in clean
        ):
            raise ValueError("只允许上传本地 CSV 文件名")
        if PureWindowsPath(clean).name != clean or not clean.casefold().endswith(
            ".csv"
        ):
            raise ValueError("只允许上传 .csv 文件")
        return clean

    @staticmethod
    def _validate_artifact_name(name: str) -> str:
        clean = str(name or "").strip()
        if (
            not clean
            or clean in {".", ".."}
            or PureWindowsPath(clean).name != clean
            or "/" in clean
            or "\\" in clean
            or "\x00" in clean
        ):
            raise ValueError("artifact 文件名无效")
        return clean

    @staticmethod
    def _assert_controlled_path(
        path: Path, root: Path, *, require_exists: bool = True, directory: bool = False
    ) -> Path:
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
            parent = self._assert_controlled_path(
                candidate.parent, controlled_root, directory=True
            )
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

    def _remove_sensitive_staged_file(self, path: Path, root: Path) -> None:
        controlled_root = Path(root).resolve()
        parent = self._assert_controlled_path(
            Path(path).parent, controlled_root, directory=True
        )
        candidate = parent / Path(path).name
        if candidate.is_dir():
            raise OSError("敏感暂存路径不是普通文件")
        if candidate.exists() or candidate.is_symlink():
            candidate.unlink()
        if candidate.exists() or candidate.is_symlink():
            raise OSError("敏感暂存文件清理失败")

    def _cleanup_stale_securecrt_templates(self, site: str) -> None:
        root = self._artifact_root(site)
        for candidate in root.glob(".securecrt-template-*.ini"):
            try:
                self._remove_sensitive_staged_file(candidate, root)
            except OSError as exc:
                app_logger.log_warning(
                    "DEVICE_SECURECRT_TEMPLATE_CLEANUP_PENDING",
                    f"site={site}; file={candidate.name}; error={exc.__class__.__name__}",
                )

    def _stage_csv_upload(
        self, site: str, filename: str, stream: BinaryIO
    ) -> tuple[Path, str]:
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
                        raise ValueError(
                            f"CSV 文件超过 {MAX_DEVICE_IMPORT_BYTES // (1024 * 1024)} MiB 限制"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self._remove_controlled_file(path, staging_root)
            raise
        return path, digest.hexdigest()

    def _stage_securecrt_template(
        self, site: str, filename: str, stream: BinaryIO
    ) -> Path:
        safe_name = str(filename or "").strip()
        if (
            not safe_name
            or "\x00" in safe_name
            or "/" in safe_name
            or "\\" in safe_name
            or ":" in safe_name
            or PureWindowsPath(safe_name).name != safe_name
            or Path(safe_name).suffix.casefold() != ".ini"
        ):
            raise ValueError("SecureCRT 模板必须是 .ini 文件")
        root = self._artifact_root(site)
        path = root / f".securecrt-template-{uuid.uuid4().hex}.ini"
        written = 0
        try:
            with path.open("xb") as handle:
                while chunk := stream.read(64 * 1024):
                    written += len(chunk)
                    if written > MAX_SECURECRT_TEMPLATE_BYTES:
                        raise ValueError("SecureCRT 模板超过 2 MiB 限制")
                    handle.write(chunk)
            if written == 0:
                raise ValueError("SecureCRT 模板不能为空")
            return self._assert_controlled_path(path, root)
        except Exception:
            self._remove_sensitive_staged_file(path, root)
            raise

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
        if not self._valid_import_operation_id(
            operation_id
        ) or not self._valid_import_operation_id(task_id):
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
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
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
                if not self._valid_import_operation_id(
                    task_id
                ) or not self._valid_import_operation_id(operation_id):
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
        target = (
            self.paths.site_backups_dir(site)
            / f"device-import-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}.sqlite"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            DeviceRepository(Database(source_path)).backup_to(temporary)
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
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
        failed = exit_code is None or int(exit_code) != 0 or bool(result.get("errors"))
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
            task for task in tasks if cls._is_owned_web_task(task, site, allowed_types)
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

    def _export_filters(
        self, payload: DeviceExportRequestDTO
    ) -> dict[str, object | None]:
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
            DEVICE_OPTICAL_REFRESH_TASK_TYPE: "optical_refresh",
            DEVICE_DIAGNOSTIC_TASK_TYPE: "diagnostic_download",
            DEVICE_IMPORT_TASK_TYPE: "import_csv",
            DEVICE_CONNECTION_TEST_TASK_TYPE: "connection_test",
            MANAGED_DEVICE_CSV_TASK_TYPE: "export_csv",
            MANAGED_DEVICE_TEMPLATE_CSV_TASK_TYPE: "export_template",
        }
        artifact_id = str(result.get("artifact_id") or spec.get("artifact_id") or "")
        sha256 = str(result.get("sha256") or "")
        task_status = snapshot.status.value
        message = sanitize_sensitive_text(
            snapshot.message or snapshot.error_message
        )
        if (
            snapshot.task_type in MANAGED_DEVICE_CSV_TASK_TYPES
            and snapshot.status is TaskState.COMPLETED
            and not sha256
        ):
            # Worker 退出后还需在 Controller 侧计算大小与摘要并固化 Artifact。
            # 对设备导出 API 来说，只有 Artifact 可下载才算真正完成，避免前端
            # 观察到短暂的“COMPLETED 但文件不可用”中间态。
            task_status = TaskState.RUNNING.value
            message = "正在校验导出文件"
        return DeviceTaskReferenceDTO(
            task_id=snapshot.task_id,
            task_status=task_status,
            action=actions.get(
                snapshot.task_type, snapshot.task_type.removeprefix("device_export_")
            ),
            artifact_id=artifact_id,
            available=bool(result.get("available")) or bool(artifact_id and sha256),
            sha256=sha256,
            size_bytes=int(result.get("size_bytes") or 0),
            row_count=int(result.get("row_count") or 0),
            message=message,
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
            self._assert_controlled_path(
                staging_dir.parent, artifact_root, directory=True
            )
            staging_dir.mkdir(parents=True, exist_ok=False)
            job_payload["output_dir"] = str(staging_dir)
        template_path: Path | None = None
        template_value = str(job_payload.get("template_ini") or "")
        if template_value:
            template_path = self._assert_controlled_path(
                Path(template_value), artifact_root
            )
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
            "task_id": task_id,
            "site": site,
            "artifact_id": artifact_id,
            "artifact_name": target.name,
            "display_name": device_export_display_name(
                f"device_export_{export_type}",
                f"{_DEVICE_EXPORT_DISPLAY_NAMES[f'device_export_{export_type}'][0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}",
            ),
            "export_type": export_type,
            "artifact_root": artifact_root,
            "target": target,
            "tmp_path": tmp_path,
            "zip_tmp": zip_tmp,
            "staging_dir": staging_dir,
            "template_path": template_path,
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
            environment["PYTHONPATH"] = str(self.paths.app_root) + (
                os.pathsep + environment["PYTHONPATH"]
                if environment.get("PYTHONPATH")
                else ""
            )
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
            self.task_service.record_external_event(
                task_id, "state", {"state": TaskState.RUNNING.value}, site_name=site
            )
            threading.Thread(
                target=self._monitor_export,
                args=(task_id, site, process),
                name=f"device-export-{task_id}",
                daemon=True,
            ).start()
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
            try:
                self._cleanup_export_files(spec, remove_artifact=True)
            except OSError as cleanup_exc:
                app_logger.log_warning(
                    "DEVICE_EXPORT_CLEANUP_PENDING",
                    f"task_id={task_id}; error={sanitize_sensitive_text(str(cleanup_exc))}",
                )
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
            task_status=snapshot.status.value
            if snapshot is not None
            else TaskState.FAILED.value,
            action=action,
            artifact_id=artifact_id,
            available=False,
        )

    def _finalize_export_artifact(
        self, spec: dict[str, object], raw_result: dict[str, object]
    ) -> dict[str, object]:
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
            zip_tmp = self._assert_controlled_path(
                Path(str(spec["zip_tmp"])), root, require_exists=False
            )
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
            template_path = spec.get("template_path")
            if template_path:
                self._remove_sensitive_staged_file(Path(str(template_path)), root)
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
        display_name = device_export_display_name(
            f"device_export_{export_type}", spec.get("display_name")
        )
        if not display_name:
            raise ValueError("导出文件显示名无效")
        return {
            "artifact_id": str(spec["artifact_id"]),
            "artifact_name": target.name,
            "display_name": display_name,
            "available": True,
            "sha256": self._file_sha256(target),
            "size_bytes": target.stat().st_size,
            "row_count": int(raw_result.get("row_count") or 0),
        }

    @staticmethod
    def _export_worker_command(job_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--export-worker", "--job", str(job_path)]
        return [
            sys.executable,
            "-m",
            "netconsole.export_worker",
            "--job",
            str(job_path),
        ]

    def _cleanup_export_files(
        self, spec: dict[str, object], *, remove_artifact: bool
    ) -> None:
        root = Path(str(spec["artifact_root"]))
        errors: list[str] = []
        for key in ("tmp_path", "zip_tmp"):
            try:
                self._remove_controlled_file(Path(str(spec[key])), root)
            except Exception as exc:
                errors.append(f"{key}:{exc.__class__.__name__}")
        staging_dir = spec.get("staging_dir")
        if staging_dir:
            try:
                self._remove_controlled_file(Path(str(staging_dir)), root)
            except Exception as exc:
                errors.append(f"staging_dir:{exc.__class__.__name__}")
        template_path = spec.get("template_path")
        if template_path:
            try:
                self._remove_sensitive_staged_file(Path(str(template_path)), root)
            except Exception as exc:
                errors.append(f"template_path:{exc.__class__.__name__}")
        if remove_artifact:
            try:
                self._remove_controlled_file(Path(str(spec["target"])), root)
            except Exception as exc:
                errors.append(f"target:{exc.__class__.__name__}")
        for key in ("job_path", "cancel_path"):
            try:
                Path(str(spec[key])).unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"{key}:{exc.__class__.__name__}")
        if errors:
            raise OSError("导出临时文件清理不完整: " + ", ".join(errors))

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
                    safe_payload = {
                        key: event[key]
                        for key in ("stage", "current", "total")
                        if key in event
                    }
                    if event_type in {"progress", "log"}:
                        safe_payload["message"] = sanitize_sensitive_text(
                            str(event.get("message") or "")
                        )
                    if event_type == "finished":
                        try:
                            safe_payload["result"] = self._finalize_export_artifact(
                                spec, dict(event.get("result") or {})
                            )
                        except Exception as exc:
                            message = sanitize_sensitive_text(str(exc))
                            self.task_service.record_external_event(
                                task_id,
                                "error",
                                {"message": message, "error": message},
                                site_name=site,
                            )
                        else:
                            updated = self.task_service.record_external_event(
                                task_id, "finished", safe_payload, site_name=site
                            )
                            completed = updated.status is TaskState.COMPLETED
                        terminal = True
                    elif event_type in {"error", "cancelled"}:
                        message = sanitize_sensitive_text(
                            str(
                                event.get("error")
                                or event.get("message")
                                or "导出任务失败"
                            )
                        )
                        self.task_service.record_external_event(
                            task_id,
                            event_type,
                            {
                                "message": message,
                                "error": message,
                                "cancelled": event_type == "cancelled",
                            },
                            site_name=site,
                        )
                        terminal = True
                    elif event_type in {"progress", "log"}:
                        self.task_service.record_external_event(
                            task_id, event_type, safe_payload, site_name=site
                        )
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
                    self.task_service.record_external_event(
                        task_id,
                        "error",
                        {"message": message, "error": message},
                        site_name=site,
                    )
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
                try:
                    self._cleanup_export_files(spec, remove_artifact=not completed)
                except OSError as exc:
                    app_logger.log_warning(
                        "DEVICE_EXPORT_CLEANUP_PENDING",
                        f"task_id={task_id}; error={sanitize_sensitive_text(str(exc))}",
                    )
            self._export_artifacts.pop(task_id, None)

    def start_form_connection_test(
        self, payload: DeviceFormConnectionTestRequestDTO
    ) -> DeviceConnectionTestDTO:
        site = self.current_site_id()
        devices, groups, _facts = self._repositories(site)
        existing = (
            self._require_device(devices, payload.device_uuid)
            if payload.device_uuid
            else None
        )
        write_payload = DeviceWriteRequestDTO.model_validate(
            payload.model_dump(exclude={"protocol", "device_uuid"})
        )
        device = self._device_from_write(write_payload, existing, groups)
        protocol = payload.protocol.upper()
        self._validate_protocol_enabled(device, protocol)
        credential_sources, ephemeral_credentials = _form_test_credentials(
            payload,
            existing,
            device,
            protocol,
        )
        self._validate_connection_preflight(
            device,
            protocol,
            credential_sources=credential_sources,
        )
        if ephemeral_credentials and not bool(
            getattr(self.process_adapter, "supports_runtime_bootstrap", False)
        ):
            _clear_secret_mapping(ephemeral_credentials)
            raise RuntimeError("共享 Job Runtime 暂不支持一次性表单凭据")
        task_id = f"device-form-test-{protocol.lower()}-{uuid.uuid4().hex}"
        bootstrap_size = len(
            json.dumps(
                ephemeral_credentials,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if bootstrap_size > DEVICE_FORM_TEST_BOOTSTRAP_MAX_BYTES:
            _clear_secret_mapping(ephemeral_credentials)
            raise ValueError("表单连接测试参数过大")
        try:
            job = BackgroundJob(
                job_id=task_id,
                task_type=DEVICE_CONNECTION_TEST_TASK_TYPE,
                params={
                    "site_name": site,
                    "device_uuid": str(existing.device_uuid or "")
                    if existing is not None
                    else "",
                    "protocol": protocol,
                    "task_name": f"设备表单连接测试 · {device.name} · {protocol}",
                    "owner": WEB_TASK_OWNER,
                    "task_source": "local",
                    "device": str(existing.device_uuid or "")
                    if existing is not None
                    else "",
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "input_source": "form",
                    "form_device": _form_test_job_payload(device, protocol),
                    "credential_sources": credential_sources,
                    "credential_source": credential_sources.get(
                        _protocol_secret_field(protocol), "none"
                    ),
                    "recovery_policy": "fail_closed"
                    if ephemeral_credentials
                    else "saved_reference",
                    "_cancel_grace_ms": 1000,
                },
            )
            self.process_adapter.start_job(
                job,
                sensitive_bootstrap=ephemeral_credentials or None,
            )
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is None:
                raise RuntimeError("表单连接测试任务创建后未写入任务中心")
            return self._connection_test_dto(snapshot, device)
        finally:
            _clear_secret_mapping(ephemeral_credentials)

    def start_connection_test(
        self, device_uuid: str, protocol: str
    ) -> DeviceConnectionTestDTO:
        site = self.current_site_id()
        device_repository, _, _ = self._repositories(site)
        device = self._require_device(device_repository, device_uuid)
        selected_protocol = protocol.strip().upper()
        self._validate_protocol_enabled(device, selected_protocol)
        self._validate_connection_preflight(device, selected_protocol)
        with self._start_lock:
            active = next(
                (
                    task
                    for task in self.task_service.repository(site).list(
                        statuses=ACTIVE_TASK_STATES, limit=1000
                    )
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
        return self._connection_test_dto(
            snapshot, device_repository.get_by_uuid(snapshot.device)
        )

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
            site = (
                str(spec.get("site") or self.current_site_id())
                if spec is not None
                else self.current_site_id()
            )
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

    def _repositories(
        self, site: str
    ) -> tuple[DeviceRepository, DeviceGroupRepository, DeviceFactRepository]:
        database = Database(self.paths.site_db_path(site))
        return (
            DeviceRepository(database),
            DeviceGroupRepository(database, site),
            DeviceFactRepository(database),
        )

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
            "SNMP": bool(
                device.snmp_enabled
                and (device.snmp_v1_enabled or device.snmp_v2c_enabled)
            ),
        }
        if protocol not in enabled:
            raise ValueError("不支持的连接测试协议")
        if not enabled[protocol]:
            raise ValueError(f"设备未启用 {protocol}")

    @staticmethod
    def _validate_form_connection_test(
        device: Device,
        protocol: str,
        credential_sources: dict[str, str],
    ) -> None:
        if not str(device.primary_address or device.backup_address or "").strip():
            raise ValueError("请输入主用地址或备用地址")
        if protocol == "SSH":
            if not str(device.ssh_username or "").strip():
                raise ValueError("请输入 SSH 用户名")
            if credential_sources.get("ssh_password") == "none":
                raise ValueError("请输入 SSH 密码")
        elif protocol == "TELNET":
            if not str(device.telnet_username or "").strip():
                raise ValueError("请输入 Telnet 用户名")
            if credential_sources.get("telnet_password") == "none":
                raise ValueError("请输入 Telnet 密码")
        elif credential_sources.get("snmp_ro_community") == "none":
            raise ValueError("请输入 SNMP 只读团体字")
        if protocol not in {"SSH", "TELNET"}:
            return
        for prefix, label in (("tunnel1", "第一跳"), ("tunnel2", "第二跳")):
            if not bool(getattr(device, f"{prefix}_enabled")):
                continue
            if not str(getattr(device, f"{prefix}_host") or "").strip():
                raise ValueError(f"请输入 SSH 隧道{label}主机")
            if not str(getattr(device, f"{prefix}_username") or "").strip():
                raise ValueError(f"请输入 SSH 隧道{label}用户名")
            if credential_sources.get(f"{prefix}_password") == "none":
                raise ValueError(f"请输入 SSH 隧道{label}密码")

    @staticmethod
    def _validate_connection_preflight(
        device: Device,
        protocol: str,
        *,
        credential_sources: dict[str, str] | None = None,
    ) -> None:
        try:
            validate_device_connection_preflight(
                device,
                protocol,
                credential_sources=credential_sources,
            )
        except DeviceConnectionPreflightError as exc:
            detail = (
                f"code={exc.code}; device_uuid={device.device_uuid or ''}; "
                f"protocol={str(protocol or '').upper()}"
            )
            if exc.code == "CREDENTIAL_REENTRY_REQUIRED":
                app_logger.log_warning("CREDENTIAL_REENTRY_REQUIRED", detail)
            app_logger.log_warning("DEVICE_CONNECTION_PREFLIGHT_FAILED", detail)
            raise
        app_logger.log_info(
            "CREDENTIAL_STATUS_RESOLVED",
            f"device_uuid={device.device_uuid or ''}; protocol={str(protocol or '').upper()}",
        )

    @staticmethod
    def _capabilities(device: Device) -> DeviceCapabilityDTO:
        versions = [
            version
            for version, enabled in (
                ("v1", device.snmp_v1_enabled),
                ("v2c", device.snmp_v2c_enabled),
            )
            if enabled
        ]
        return DeviceCapabilityDTO(
            ssh=bool(device.ssh_enabled),
            ssh_port=int(device.ssh_port or 22) if device.ssh_enabled else None,
            telnet=bool(device.telnet_enabled),
            telnet_port=int(device.telnet_port or 23)
            if device.telnet_enabled
            else None,
            snmp=bool(device.snmp_enabled and versions),
            snmp_versions=versions,
            snmp_port=int(device.snmp_port or 161)
            if device.snmp_enabled and versions
            else None,
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
            group_name=group_names.get(int(device.group_id), "未分组")
            if device.group_id is not None
            else "未分组",
            device_vendor=str(device.device_vendor or ""),
            device_type=str(device.device_type or ""),
            primary_address=str(device.primary_address or ""),
            backup_address=str(device.backup_address or ""),
            updated_at=str(device.updated_at or ""),
            capabilities=self._capabilities(device),
            connection_status=self._connection_status(latest_test),
            last_test_task_id=latest_test.task_id if latest_test else "",
            last_test_time=latest_test.updated_time if latest_test else "",
            credential_status=str(getattr(device, "credential_status", "missing")),
            credential_source=str(getattr(device, "credential_source", "none")),
            credential_error_code=str(
                getattr(device, "credential_error_code", "CREDENTIAL_MISSING")
            ),
            credential_message=credential_status_message(
                str(getattr(device, "credential_status", "missing")),
                str(getattr(device, "credential_error_code", "CREDENTIAL_MISSING")),
            ),
        )

    def _write_result_item(
        self, device: Device, groups: DeviceGroupRepository
    ) -> DeviceDetailItemDTO:
        group_names: dict[int, str] = {}
        if device.group_id is not None:
            try:
                group = groups.get(int(device.group_id))
                group_names[int(device.group_id)] = group.name
            except KeyError:
                pass
        return self._detail_item(
            device, self._list_item(device, group_names, latest_test=None)
        )

    @staticmethod
    def _detail_item(
        device: Device, list_item: DeviceListItemDTO
    ) -> DeviceDetailItemDTO:
        https_port, _https_port_source = effective_https_port(device.https_port)
        return DeviceDetailItemDTO(
            **list_item.model_dump(),
            location=str(device.location or ""),
            mac_address=str(device.mac_address or ""),
            https_port=int(device.https_port) if device.https_port else None,
            web_url=build_https_url(device.primary_address, https_port) or "",
            ssh_username=str(device.ssh_username or device.username or ""),
            telnet_username=str(device.telnet_username or ""),
            tunnel_enabled=bool(device.tunnel_enabled),
            tunnel1_enabled=bool(device.tunnel1_enabled),
            tunnel1_host=str(device.tunnel1_host or ""),
            tunnel1_port=int(device.tunnel1_port) if device.tunnel1_port else None,
            tunnel1_username=str(device.tunnel1_username or ""),
            tunnel2_enabled=bool(device.tunnel2_enabled),
            tunnel2_host=str(device.tunnel2_host or ""),
            tunnel2_port=int(device.tunnel2_port) if device.tunnel2_port else None,
            tunnel2_username=str(device.tunnel2_username or ""),
            snmp_v1_enabled=bool(device.snmp_v1_enabled),
            snmp_v2c_enabled=bool(device.snmp_v2c_enabled),
            snmp_timeout_ms=int(device.snmp_timeout_ms or 2000),
            snmp_retries=(
                int(device.snmp_retries) if device.snmp_retries is not None else 1
            ),
            ssh_secret_configured=bool(device.ssh_password or device.password),
            telnet_secret_configured=bool(device.telnet_password),
            tunnel1_secret_configured=bool(device.tunnel1_password),
            tunnel2_secret_configured=bool(device.tunnel2_password),
            snmp_ro_secret_configured=bool(device.snmp_ro_community),
            remark=str(device.remark or ""),
            created_at=str(device.created_at or ""),
        )

    @staticmethod
    def _connection_status(task: TaskSnapshot | None) -> str:
        if task is None:
            return "UNKNOWN"
        if task.status in ACTIVE_TASK_STATES:
            return "TESTING"
        if task.status is TaskState.COMPLETED:
            error_code = str(task.result.get("error_code") or "").upper()
            result_status = str(task.result.get("status") or "").casefold()
            if error_code in {
                "AUTHENTICATION_FAILED",
                "TELNET_LOGIN_FAILED",
            } or result_status in {
                "auth_failed",
                "authentication_failed",
            }:
                return "AUTH_FAILED"
            return "REACHABLE" if task.result.get("success") is True else "UNREACHABLE"
        return "ERROR"

    @staticmethod
    def _latest_test(tasks: list[TaskSnapshot], device: Device) -> TaskSnapshot | None:
        device_uuid = str(device.device_uuid or "")
        return next(
            (
                task
                for task in tasks
                if task.task_type == DEVICE_CONNECTION_TEST_TASK_TYPE
                and task.device == device_uuid
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
    def _collection_summary(
        collection: dict[str, object | None] | None, device: Device
    ) -> DeviceCollectionSummaryDTO | None:
        if not collection:
            return None
        return DeviceCollectionSummaryDTO(
            collect_run_uuid=str(collection.get("collect_run_uuid") or ""),
            collect_type=str(collection.get("collect_type") or ""),
            status=str(collection.get("status") or ""),
            started_at=str(collection.get("started_at") or ""),
            ended_at=str(collection.get("ended_at") or ""),
            error_summary=sanitize_sensitive_text(
                str(collection.get("error_message") or ""), device
            ),
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
                    time=str(
                        collection.get("ended_at") or collection.get("started_at") or ""
                    ),
                    message=sanitize_sensitive_text(
                        str(collection.get("error_message") or ""), device
                    ),
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
            commands.append(
                DeviceConnectionCommandDTO(
                    protocol="SSH",
                    command=f"ssh -p {int(device.ssh_port or 22)} {host}",
                )
            )
        if device.telnet_enabled:
            commands.append(
                DeviceConnectionCommandDTO(
                    protocol="TELNET",
                    command=f"telnet {host} {int(device.telnet_port or 23)}",
                )
            )
        return commands

    @staticmethod
    def _connection_test_dto(
        snapshot: TaskSnapshot, device: Device | None = None
    ) -> DeviceConnectionTestDTO:
        result = dict(snapshot.result or {})
        protocol = str(result.get("protocol") or "").upper() or _protocol_from_task_id(
            snapshot.task_id
        )
        return DeviceConnectionTestDTO(
            task_id=snapshot.task_id,
            task_status=snapshot.status.value,
            device_uuid=str(result.get("device_uuid") or snapshot.device or ""),
            protocol=protocol or None,
            success=result.get("success")
            if isinstance(result.get("success"), bool)
            else None,
            result_status=str(result.get("status") or ""),
            failure_category=str(result.get("failure_category") or ""),
            error_code=str(result.get("error_code") or ""),
            summary=str(result.get("summary") or ""),
            retryable=bool(result.get("retryable")),
            suggested_action=sanitize_sensitive_text(
                str(result.get("suggested_action") or result.get("suggestion") or ""),
                device,
            ),
            message=sanitize_sensitive_text(
                str(
                    result.get("message")
                    or snapshot.message
                    or snapshot.error_message
                    or ""
                ),
                device,
            ),
            safe_message=sanitize_sensitive_text(
                str(
                    result.get("safe_message")
                    or result.get("message")
                    or snapshot.message
                    or snapshot.error_message
                    or ""
                ),
                device,
            ),
            method=str(result.get("method") or ""),
            host=str(result.get("host") or ""),
            port=int(result["port"]) if result.get("port") is not None else None,
            latency_ms=int(result["latency_ms"])
            if result.get("latency_ms") is not None
            else None,
            elapsed_ms=int(result["elapsed_ms"])
            if result.get("elapsed_ms") is not None
            else None,
            tested_at=str(result.get("tested_at") or ""),
            system_name=str(result.get("system_name") or ""),
            model=str(result.get("model") or ""),
            os_family=str(result.get("os_family") or ""),
            interface_count=int(result["interface_count"])
            if result.get("interface_count") is not None
            else None,
            error_type=str(result.get("error_type") or ""),
            suggestion=sanitize_sensitive_text(
                str(result.get("suggestion") or ""), device
            ),
            created_time=snapshot.created_time,
            updated_time=snapshot.updated_time,
        )


def run_device_connection_test(context: JobContext) -> dict[str, object]:
    from netconsole.services.device_snmp_detect_service import DeviceSnmpDetectService
    from netconsole.services.host_key_trust_service import HostKeyTrustService
    from netconsole.services.netmiko_connection import test_device_connection

    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    device_uuid = str(context.params.get("device_uuid") or "")
    protocol = str(context.params.get("protocol") or "").upper()
    form_input = context.params.get("input_source") == "form"
    context.check_cancelled()
    context.progress("validating", 1, 7, "正在校验连接参数")
    if form_input:
        device = _consume_form_test_device(context)
    else:
        repository = DeviceRepository(Database(context.paths.site_db_path(site)))
        device = repository.get_by_uuid(device_uuid)
        if device is None:
            raise KeyError(f"设备不存在：{device_uuid}")
    selected: Device | None = None
    try:
        DeviceManagementWebService._validate_protocol_enabled(device, protocol)
        DeviceManagementWebService._validate_connection_preflight(device, protocol)
        context.check_cancelled()
        context.progress("resolving_credential", 2, 7, "连接凭据已安全解析")
        if protocol == "SNMP":
            context.progress("connecting", 3, 7, "正在执行 SNMP 连接测试")
            try:
                result = DeviceSnmpDetectService().detect(
                    device, cancel_checker=context.should_cancel
                )
            except Exception as exc:
                raise RuntimeError(
                    _sanitize_device_secret_text(str(exc), device)
                    or "SNMP 连接测试失败"
                ) from None
            payload = {
                "device_uuid": device_uuid,
                "protocol": protocol,
                "success": result.status == "success",
                "status": result.status,
                "message": _sanitize_device_secret_text(
                    result.error_message
                    or (
                        "SNMP 探测成功"
                        if result.status == "success"
                        else "SNMP 探测失败"
                    ),
                    device,
                ),
                "host": str(device.primary_address or ""),
                "port": int(device.snmp_port or 161),
                "latency_ms": int(result.latency_ms or 0),
                "elapsed_ms": int(result.latency_ms or 0),
                "system_name": result.sys_name,
                "model": result.model,
                "os_family": result.os_family,
                "interface_count": int(result.interface_count or 0),
            }
        else:
            selected = Device.from_mapping(device.to_record())
            selected.ssh_enabled = int(protocol == "SSH")
            selected.telnet_enabled = int(protocol == "TELNET")

            def report_phase(stage: str, message: str) -> None:
                context.check_cancelled()
                current = {
                    "connecting": 3,
                    "handshaking": 4,
                    "authenticating": 5,
                    "verifying_session": 6,
                }.get(stage, 3)
                context.progress(stage, current, 7, message)

            try:
                app_logger.log_info(
                    "DEVICE_CONNECTION_STARTED",
                    f"device_uuid={device_uuid}; protocol={protocol}",
                )
                result = test_device_connection(
                    selected,
                    phase_callback=report_phase,
                    host_key_trust=HostKeyTrustService(context.paths),
                )
            except Exception as exc:
                raise RuntimeError(
                    _sanitize_device_secret_text(str(exc), device)
                    or f"{protocol} 连接测试失败"
                ) from None
            payload = {
                "device_uuid": device_uuid,
                "protocol": protocol,
                "success": bool(result.success),
                "status": str(
                    result.status or ("success" if result.success else "failed")
                ),
                "message": _sanitize_device_secret_text(result.message, device),
                "method": str(result.method or ""),
                "host": str(result.host or ""),
                "port": int(result.port or 0),
                "latency_ms": int(result.elapsed_ms or 0),
                "elapsed_ms": int(result.elapsed_ms or 0),
                "system_name": str(
                    extract_sysname_from_prompt(result.prompt or "") or ""
                ),
                "error_type": str(result.error_type or ""),
                "suggestion": _sanitize_device_secret_text(
                    str(result.suggestion or ""), device
                ),
            }
        failure_category = _connection_failure_category(payload)
        safe_message = (
            f"{protocol} 连接成功"
            if bool(payload["success"])
            else str(payload.get("message") or f"{protocol} 连接失败")
        )
        payload.update(
            failure_category=failure_category,
            error_code=_connection_error_code(payload),
            summary=_connection_summary(payload, protocol),
            retryable=not bool(payload["success"]),
            suggested_action=str(payload.get("suggestion") or ""),
            safe_message=safe_message,
            message=safe_message,
            tested_at=datetime.now(UTC).isoformat(),
        )
        context.check_cancelled()
        expected_failure = _is_expected_connection_failure(payload, failure_category)
        terminal_stage = (
            "succeeded"
            if bool(payload["success"])
            else "completed"
            if expected_failure
            else "failed"
        )
        context.progress(terminal_stage, 7, 7, safe_message)
        if expected_failure:
            payload["terminal_state"] = TaskState.COMPLETED.value
        elif not bool(payload["success"]):
            payload["terminal_state"] = TaskState.FAILED.value
        if not bool(payload["success"]):
            if payload["error_code"] == "AUTHENTICATION_FAILED":
                app_logger.log_warning(
                    "DEVICE_CONNECTION_AUTH_FAILED",
                    f"device_uuid={device_uuid}; protocol={protocol}",
                )
        app_logger.log_info(
            "DEVICE_CONNECTION_COMPLETED",
            f"device_uuid={device_uuid}; protocol={protocol}; success={bool(payload['success'])}",
        )
        return payload
    finally:
        if form_input:
            _clear_device_secrets(device)
            if selected is not None:
                _clear_device_secrets(selected)


def _consume_form_test_device(context: JobContext) -> Device:
    payload = context.params.get("form_device")
    sources = context.params.get("credential_sources")
    if not isinstance(payload, dict) or not isinstance(sources, dict):
        raise RuntimeError("表单连接测试安全参数不可用")
    device_values = dict(payload)
    selected_sources = {
        str(field): str(source)
        for field, source in sources.items()
        if str(field) in DEVICE_FORM_TEST_SECRET_FIELDS
    }
    expected_ephemeral = {
        field for field, source in selected_sources.items() if source == "ephemeral"
    }
    ephemeral: dict[str, str] = {}
    if expected_ephemeral:
        consume = getattr(context, "consume_sensitive_bootstrap", None)
        if not callable(consume):
            raise RuntimeError("临时表单凭据已失效，任务不可恢复，请重新提交")
        ephemeral = consume()
    try:
        if set(ephemeral) != expected_ephemeral:
            raise RuntimeError("临时表单凭据无效，任务不可恢复，请重新提交")
        saved: Device | None = None
        if any(source == "saved_device" for source in selected_sources.values()):
            device_uuid = str(context.params.get("device_uuid") or "")
            if not device_uuid:
                raise RuntimeError("已保存凭据引用无效")
            site = SiteManager(context.paths).validate_site_name(
                str(context.params.get("site_name") or "")
            )
            repository = DeviceRepository(Database(context.paths.site_db_path(site)))
            saved = repository.get_by_uuid(device_uuid)
            if saved is None:
                raise RuntimeError("已保存凭据对应的设备不存在")
        for field, source in selected_sources.items():
            if source == "ephemeral":
                device_values[field] = ephemeral[field]
            elif source == "saved_device":
                assert saved is not None
                device_values[field] = getattr(saved, field)
            elif source == "none":
                device_values[field] = None
            else:
                raise RuntimeError("表单连接测试凭据来源无效")
        return Device.from_mapping(device_values)
    finally:
        _clear_secret_mapping(ephemeral)
        if saved is not None:
            _clear_device_secrets(saved)


def _form_test_job_payload(device: Device, protocol: str) -> dict[str, object | None]:
    payload: dict[str, object | None] = {
        "name": device.name,
        "device_vendor": device.device_vendor,
        "device_type": device.device_type,
        "primary_address": device.primary_address,
        "backup_address": device.backup_address,
    }
    if protocol == "SSH":
        payload.update(
            ssh_enabled=1,
            telnet_enabled=0,
            ssh_port=device.ssh_port,
            ssh_username=device.ssh_username,
        )
        _append_tunnel_bootstrap(payload, device)
    elif protocol == "TELNET":
        payload.update(
            ssh_enabled=0,
            telnet_enabled=1,
            telnet_port=device.telnet_port,
            telnet_username=device.telnet_username,
        )
        _append_tunnel_bootstrap(payload, device)
    else:
        payload.update(
            snmp_enabled=1,
            snmp_v1_enabled=device.snmp_v1_enabled,
            snmp_v2c_enabled=device.snmp_v2c_enabled,
            snmp_port=device.snmp_port,
            snmp_timeout_ms=device.snmp_timeout_ms,
            snmp_retries=device.snmp_retries,
        )
    return payload


def _append_tunnel_bootstrap(payload: dict[str, object | None], device: Device) -> None:
    payload["tunnel_enabled"] = device.tunnel_enabled
    for prefix in ("tunnel1", "tunnel2"):
        enabled = bool(getattr(device, f"{prefix}_enabled"))
        payload[f"{prefix}_enabled"] = int(enabled)
        if not enabled:
            continue
        for suffix in ("host", "port", "username"):
            payload[f"{prefix}_{suffix}"] = getattr(device, f"{prefix}_{suffix}")


def _form_test_credentials(
    payload: DeviceFormConnectionTestRequestDTO,
    existing: Device | None,
    device: Device,
    protocol: str,
) -> tuple[dict[str, str], dict[str, str]]:
    fields = [_protocol_secret_field(protocol)]
    if protocol in {"SSH", "TELNET"}:
        fields.extend(
            f"{prefix}_password"
            for prefix in ("tunnel1", "tunnel2")
            if bool(getattr(device, f"{prefix}_enabled"))
        )
    cleared = set(payload.clear_secret_fields)
    sources: dict[str, str] = {}
    ephemeral: dict[str, str] = {}
    for field in fields:
        secret = getattr(payload, field)
        raw = secret.get_secret_value() if secret is not None else ""
        if raw:
            sources[field] = "ephemeral"
            ephemeral[field] = raw
        elif existing is not None and field not in cleared and getattr(existing, field):
            sources[field] = "saved_device"
        elif (
            existing is not None
            and field not in cleared
            and str(getattr(existing, "credential_field_statuses", {}).get(field) or "")
            == "needs_reentry"
        ):
            sources[field] = "needs_reentry"
        else:
            sources[field] = "none"
    return sources, ephemeral


def _protocol_secret_field(protocol: str) -> str:
    return {
        "SSH": "ssh_password",
        "TELNET": "telnet_password",
        "SNMP": "snmp_ro_community",
    }[protocol]


def _connection_failure_category(payload: dict[str, object]) -> str:
    if bool(payload.get("success")):
        return ""
    status = str(payload.get("status") or "").casefold()
    error_type = str(payload.get("error_type") or "").casefold()
    message = str(payload.get("message") or "").casefold()
    if status == "auth_failed":
        return "authentication_failed"
    method = str(payload.get("method") or "").casefold()
    if method.startswith("tunnel"):
        return "jump_host_failed"
    if "gaierror" in error_type or "name or service not known" in message:
        return "address_resolution_failed"
    if "connectionrefused" in error_type or "connection refused" in message:
        return "connection_refused"
    return {
        "address_resolution_failed": "address_resolution_failed",
        "connection_refused": "connection_refused",
        "auth_failed": "authentication_failed",
        "ssh_banner_failed": "ssh_handshake_failed",
        "timeout": "tcp_timeout",
        "tcp_failed": "tcp_connection_failed",
        "unknown_error": "ssh_connection_failed",
    }.get(status, status or "connection_failed")


_EXPECTED_CONNECTION_FAILURE_CATEGORIES = frozenset(
    {
        "address_resolution_failed",
        "connection_refused",
        "jump_host_failed",
        "ssh_handshake_failed",
        "tcp_connection_failed",
        "tcp_timeout",
        "authentication_failed",
    }
)


def _is_expected_connection_failure(
    payload: dict[str, object], failure_category: str
) -> bool:
    """Return whether a failed probe completed normally with a device result."""
    return (
        not bool(payload.get("success"))
        and failure_category in _EXPECTED_CONNECTION_FAILURE_CATEGORIES
    )


def _connection_error_code(payload: dict[str, object]) -> str:
    if bool(payload.get("success")):
        return ""
    status = str(payload.get("status") or "").casefold()
    protocol = str(payload.get("protocol") or "").upper()
    if status == "auth_failed":
        return "AUTHENTICATION_FAILED"
    if status == "ssh_banner_failed":
        return "SSH_NEGOTIATION_FAILED"
    if status == "timeout":
        return "CONNECTION_TIMEOUT"
    if status in {
        "address_resolution_failed",
        "connection_refused",
        "tcp_failed",
    }:
        return "TCP_UNREACHABLE"
    if protocol == "TELNET":
        return "TELNET_LOGIN_FAILED"
    return "UNEXPECTED_ERROR"


def _connection_summary(payload: dict[str, object], protocol: str) -> str:
    if bool(payload.get("success")):
        return f"{protocol} 连接成功"
    return {
        "AUTHENTICATION_FAILED": f"{protocol} 认证失败",
        "SSH_NEGOTIATION_FAILED": "SSH 握手失败",
        "CONNECTION_TIMEOUT": f"{protocol} 连接超时",
        "TCP_UNREACHABLE": "设备端口不可达",
        "TELNET_LOGIN_FAILED": "Telnet 登录失败",
    }.get(_connection_error_code(payload), f"{protocol} 连接失败")


def _clear_secret_mapping(values: dict[str, str]) -> None:
    for key in tuple(values):
        values[key] = ""
    values.clear()


def _clear_device_secrets(device: Device) -> None:
    for field in DEVICE_SECRET_FIELD_NAMES:
        setattr(device, field, None)


def _sanitize_device_secret_text(text: str, device: Device) -> str:
    safe = sanitize_sensitive_text(text, device)
    secrets = {
        str(getattr(device, field))
        for field in DEVICE_SECRET_FIELD_NAMES
        if getattr(device, field, None)
    }
    for secret in sorted(secrets, key=len, reverse=True):
        safe = safe.replace(secret, "***")
    return safe


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
    result = service.import_csv_atomic(
        path,
        check_cancelled=context.check_cancelled,
        duplicate_strategy=str(
            context.params.get("duplicate_strategy") or "create_new"
        ),
    )
    context.progress("device_csv_import", 1, 1, "设备 CSV 导入完成")
    return {
        "created": result.created,
        "skipped": result.skipped,
        "groups_created": result.groups_created,
        "errors": list(result.errors),
    }


def run_device_detail_collect(context: JobContext) -> dict[str, object]:
    from netconsole.services.device_operation_service import (
        run_device_inventory_refresh,
    )

    return run_device_inventory_refresh(context)


def run_device_optical_refresh(context: JobContext) -> dict[str, object]:
    from netconsole.services.h3c_optical_refresh_service import (
        refresh_h3c_device_optical,
    )

    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    device_uuid = str(context.params.get("device_uuid") or "")
    database = Database(context.paths.site_db_path(site))
    device = DeviceManagementWebService._require_device(
        DeviceRepository(database), device_uuid
    )
    context.check_cancelled()
    context.progress("device_optical_refresh", 0, 1, "正在刷新设备光模块")
    result = refresh_h3c_device_optical(
        device,
        site,
        repository=DeviceFactRepository(database),
        paths=context.paths,
    )
    context.check_cancelled()
    context.progress("device_optical_refresh", 1, 1, "设备光模块刷新完成")
    return {
        "device_uuid": result.device_uuid,
        "success": result.success,
        "collect_run_uuid": result.collect_run_uuid,
        "interfaces_updated": result.interfaces_updated,
        "optical_modules_updated": result.optical_modules_updated,
        "error_message": sanitize_sensitive_text(result.error_message or "", device),
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
    summary = {
        "total": len(results),
        "success": sum(1 for result in results if result.success),
        "failed": sum(1 for result in results if not result.success),
        "results": [
            {
                "device_id": result.device_id,
                "device_name": result.device_name,
                "timestamp": result.timestamp,
                "status": result.status,
                "error_message": result.error_message or "",
                "elapsed_ms": result.elapsed_ms,
            }
            for result in results
        ],
    }
    artifact_id = str(context.params.get("artifact_id") or "")
    if (
        not artifact_id.startswith("device-diagnostic-")
        or len(artifact_id) != 50
        or any(character not in "0123456789abcdef" for character in artifact_id[18:])
    ):
        raise ValueError("诊断 Artifact 标识无效")
    artifact_root = _diagnostic_artifact_root(context.paths, site)
    artifact_name = f"{artifact_id}.zip"
    artifact_path = artifact_root / artifact_name
    if artifact_path.exists():
        raise FileExistsError("诊断 Artifact 已存在")
    temp_path = artifact_root / f".{artifact_id}.{context.job_id}.tmp"
    artifact_sha256 = ""
    artifact_size = 0
    try:
        with zipfile.ZipFile(temp_path, "x", zipfile.ZIP_DEFLATED) as archive:
            for result in results:
                context.check_cancelled()
                if not result.success or not result.file_path:
                    continue
                source, archive_name = _controlled_diagnostic_source(
                    context.paths, site, result.file_path
                )
                archive.write(source, archive_name)
            archive.writestr(
                "diagnostic_summary.json",
                json.dumps(summary, ensure_ascii=False, indent=2),
            )
        attach_export_metadata(
            temp_path,
            effective_suffix=".zip",
            export_type="device_diagnostics",
            payload={"source_module": "devices"},
        )
        artifact_sha256 = DeviceManagementWebService._file_sha256(temp_path)
        artifact_size = temp_path.stat().st_size
        context.check_cancelled()
        os.replace(temp_path, artifact_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        **summary,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "available": True,
        "sha256": artifact_sha256,
        "size_bytes": artifact_size,
    }


def _diagnostic_artifact_root(paths: PathResolver, site: str) -> Path:
    files_root = paths.site_files_dir(site)
    if files_root.is_symlink():
        raise ValueError("设备文件根目录不允许使用符号链接")
    files_root.mkdir(parents=True, exist_ok=True)
    controlled_files_root = files_root.resolve()
    raw_artifact_root = files_root / WEB_ARTIFACT_DIR
    if raw_artifact_root.exists() and raw_artifact_root.is_symlink():
        raise ValueError("诊断 Artifact 目录不允许使用符号链接")
    raw_artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_root = raw_artifact_root.resolve()
    if not artifact_root.is_relative_to(controlled_files_root):
        raise ValueError("诊断 Artifact 目录越界")
    return artifact_root


def _controlled_diagnostic_source(
    paths: PathResolver, site: str, relative_path: str
) -> tuple[Path, str]:
    relative = PurePosixPath(str(relative_path or ""))
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or any(":" in part for part in relative.parts)
    ):
        raise ValueError("诊断结果文件路径无效")
    diagnostics_root = paths.config_center_raw_logs_root(site)
    if diagnostics_root.is_symlink():
        raise ValueError("诊断结果目录不允许使用符号链接")
    controlled_root = diagnostics_root.resolve(strict=True)
    source = paths.site_dir(site).joinpath(*relative.parts)
    if source.is_symlink():
        raise ValueError("诊断结果文件不允许使用符号链接")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(controlled_root):
        raise ValueError("诊断结果文件越界")
    archive_name = f"diagnostics/{resolved.relative_to(controlled_root).as_posix()}"
    return resolved, archive_name


def _protocol_from_task_id(task_id: str) -> str:
    parts = str(task_id or "").split("-", 3)
    return (
        parts[2].upper()
        if len(parts) >= 4
        and parts[:2] == ["device", "test"]
        and parts[2] in {"ssh", "telnet", "snmp"}
        else ""
    )


__all__ = [
    "DEVICE_CONNECTION_TEST_TASK_TYPE",
    "DEVICE_OPTICAL_REFRESH_TASK_TYPE",
    "DeviceManagementWebService",
    "run_device_connection_test",
    "run_device_csv_import",
    "run_device_detail_collect",
    "run_device_optical_refresh",
    "run_device_diagnostic_download",
]
