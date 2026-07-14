from __future__ import annotations

import asyncio
import math
import uuid
from threading import RLock

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
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
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.netmiko_connection import extract_sysname_from_prompt, sanitize_sensitive_text
from netconsole.utils.natural_sort import natural_text_key


DEVICE_CONNECTION_TEST_TASK_TYPE = "device_connection_test"
ACTIVE_TASK_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
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
