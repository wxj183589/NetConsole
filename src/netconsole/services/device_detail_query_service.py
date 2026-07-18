from __future__ import annotations

import math
import re
from typing import Protocol

from netconsole.core.optical_severity_engine import SEVERITY_RANK, compute_optical_severity
from netconsole.models.api.device_detail import (
    DeviceBusinessAssociationDTO,
    DeviceBusinessAssociationPageDTO,
    DeviceAcApAssociationFactsDTO,
    DeviceConfigSnapshotDTO,
    DeviceConfigSnapshotPageDTO,
    DeviceDetailCapabilityDTO,
    DeviceDetailSourceDTO,
    DeviceDetailTaskDTO,
    DeviceDetailTaskPageDTO,
    DeviceInterfaceDTO,
    DeviceInterfaceDetailDTO,
    DeviceInterfacePageDTO,
    DeviceLldpNeighborDTO,
    DeviceLldpPageDTO,
    DeviceMrSessionAssociationFactsDTO,
    DeviceOverviewCountsDTO,
    DeviceOverviewDTO,
    DeviceOverviewTaskFactDTO,
    DeviceOverviewTaskFactsDTO,
    DevicePlatformFactsDTO,
    DeviceTransceiverDTO,
    DeviceTransceiverPageDTO,
    DeviceTracksideApAssociationFactsDTO,
)
from netconsole.models.device import Device
from netconsole.models.device_detail import (
    DeviceCapability,
    identify_device_platform,
)
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_detail_repository import DeviceDetailDataGateway
from netconsole.services.device_operation_service import DeviceOperationService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.netmiko_connection import sanitize_sensitive_text
from netconsole.utils.interface_normalize import normalize_interface_name


class ConfigSnapshotReader(Protocol):
    def list_snapshots_page(
        self,
        site_name: str,
        device_id: int,
        snapshot_type: str = "",
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[object], int]: ...

    def count_snapshots(
        self, site_name: str, device_id: int, snapshot_type: str = ""
    ) -> int: ...


class BusinessAssociationReader(Protocol):
    def list_rows(
        self,
        site_id: str,
        *,
        station: str = "",
        query: str = "",
        optical_anomaly_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> object: ...


class AcBusinessAssociationReader(Protocol):
    def list_aps(
        self,
        site_id: str,
        *,
        ac_id: str,
        page: int,
        page_size: int,
    ) -> object: ...


class OnlineMrBusinessAssociationReader(Protocol):
    def list_sessions(
        self,
        site_id: str,
        *,
        mr_name: str | None,
        limit: int,
        offset: int,
    ) -> list[object]: ...

    def get_session(self, site_id: str, session_id: str) -> object: ...

    def get_realtime_preview(self, site_id: str, session_id: str) -> object: ...


class DeviceDetailQueryService:
    def __init__(
        self,
        gateway: DeviceDetailDataGateway,
        task_service: TaskApplicationService,
        operation_service: DeviceOperationService,
        *,
        config_reader: ConfigSnapshotReader | None = None,
        business_reader: BusinessAssociationReader | None = None,
        ac_business_reader: AcBusinessAssociationReader | None = None,
        online_mr_reader: OnlineMrBusinessAssociationReader | None = None,
    ) -> None:
        self.gateway = gateway
        self.task_service = task_service
        self.operation_service = operation_service
        self.config_reader = config_reader
        self.business_reader = business_reader
        self.ac_business_reader = ac_business_reader
        self.online_mr_reader = online_mr_reader

    def overview(self, device_uuid: str) -> DeviceOverviewDTO:
        device = self._device(device_uuid)
        fact = self.gateway.get_fact(device_uuid)
        platform = identify_device_platform(
            vendor=(fact or {}).get("vendor") or device.device_vendor,
            device_type=device.device_type,
            software_version=(fact or {}).get("software_version"),
            collected_at=(fact or {}).get("collected_at"),
        )
        counts = self.gateway.snapshot_counts(device_uuid)
        dataset_sources = {
            dataset: self.gateway.snapshot_source(device_uuid, dataset)
            for dataset in ("interfaces", "transceivers", "lldp")
        }
        operation = self.operation_service.capability(device, fact)
        config_available = (
            self.config_reader is not None
            and device.id is not None
            and str(device.device_vendor or "").strip().casefold() == "h3c"
        )
        capabilities = [
            self._capability(capability_id)
            for capability_id in (
                "device.overview.read",
                "device.interfaces.read",
                "device.transceivers.read",
                "device.lldp.read",
                "device.tasks.read",
            )
        ]
        operation_capability = self._capability_dto(operation)
        capabilities.extend(
            (
                self._capability(
                    "device.config_snapshots.read",
                    available=config_available,
                    reason=None
                    if config_available
                    else "配置快照仅通过已接线的 H3C 配置中心读取",
                    source="config_collection_application_service",
                ),
                self._capability(
                    "device.business_associations.read",
                    available=self._business_reader_available(platform.role),
                    reason=self._business_unavailable_reason(platform.role),
                    source=self._business_source(platform.role),
                ),
                operation_capability,
                self._capability(
                    "device.interfaces.refresh",
                    available=False,
                    reason="未注册独立接口刷新 Operation；仅支持 device.inventory.collect",
                    source="device_operation_service",
                ),
                self._capability(
                    "device.transceivers.refresh",
                    available=False,
                    reason="未注册独立光模块刷新 Operation；仅支持 device.inventory.collect",
                    source="device_operation_service",
                ),
                self._capability(
                    "device.lldp.refresh",
                    available=False,
                    reason="未注册独立 LLDP 刷新 Operation；仅支持 device.inventory.collect",
                    source="device_operation_service",
                ),
                self._capability(
                    "device.config_snapshots.refresh",
                    available=False,
                    reason="配置采集不属于设备详情稳定 Operation，本接口失败关闭",
                    source="device_operation_service",
                ),
            )
        )
        task_facts, connection_status = self._overview_task_facts(device)
        config_count = (
            self.config_reader.count_snapshots(
                self.gateway.current_site_id(), int(device.id)
            )
            if config_available
            else None
        )
        return DeviceOverviewDTO(
            device_uuid=str(device.device_uuid or ""),
            name=str(device.name or ""),
            system_name=_text((fact or {}).get("sysname") or device.system_name),
            device_type=_text(device.device_type),
            station=_text(device.station),
            location=_text(device.location),
            primary_address=_text(device.primary_address),
            backup_address=_text(device.backup_address),
            protocol=_text(device.protocol),
            port=int(device.port) if device.port is not None else None,
            group_id=int(device.group_id) if device.group_id is not None else None,
            group_name=(
                self.gateway.get_group_name(int(device.group_id))
                if device.group_id is not None
                else None
            ),
            cpu_usage=None,
            memory_usage=None,
            model=_text((fact or {}).get("model")),
            serial_number=_text((fact or {}).get("serial_number")),
            mac_address=_text((fact or {}).get("mac_address") or device.mac_address),
            bootrom_version=_text((fact or {}).get("bootrom_version")),
            uptime=_text((fact or {}).get("uptime")),
            connection_status=connection_status,
            platform_facts=DevicePlatformFactsDTO(**platform.__dict__),
            capabilities=capabilities,
            command_profile=operation_capability,
            visible_sections=self._visible_sections(platform.role, capabilities),
            task_facts=task_facts,
            counts=DeviceOverviewCountsDTO(
                interfaces=(
                    counts["interfaces"]
                    if dataset_sources["interfaces"] is not None
                    else None
                ),
                transceivers=(
                    counts["transceivers"]
                    if dataset_sources["transceivers"] is not None
                    else None
                ),
                lldp_neighbors=(
                    counts["lldp_neighbors"]
                    if dataset_sources["lldp"] is not None
                    else None
                ),
                recent_tasks=task_facts.recent_task_count,
                config_snapshots=config_count,
            ),
            snapshot=self._snapshot_source(fact),
        )

    def interfaces(
        self,
        device_uuid: str,
        *,
        search: str = "",
        status: str = "",
        interface_type: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceInterfacePageDTO:
        self._device(device_uuid)
        current_page, size, offset = _pagination(page, page_size)
        rows, total = self.gateway.list_interfaces(
            device_uuid,
            search=search,
            status=status,
            interface_type=interface_type,
            limit=size,
            offset=offset,
        )
        return DeviceInterfacePageDTO(
            items=[self._interface(row) for row in rows],
            total=total,
            page=current_page,
            page_size=size,
            total_pages=_total_pages(total, size),
            source=self._dataset_source(device_uuid, "interfaces"),
        )

    def interface_detail(
        self, device_uuid: str, interface_name: str
    ) -> DeviceInterfaceDetailDTO:
        self._device(device_uuid)
        row = self.gateway.get_interface(device_uuid, interface_name)
        if row is None:
            raise KeyError(interface_name)
        lldp_rows, _lldp_total, lldp_truncated = self.gateway.list_lldp_for_interface(
            device_uuid,
            str(row.get("interface_name") or interface_name),
            limit=_INTERFACE_LLDP_LIMIT,
        )
        neighbors = [self._lldp(item) for item in lldp_rows]
        optical = self.gateway.get_transceiver(device_uuid, interface_name)
        return DeviceInterfaceDetailDTO(
            interface=self._interface(
                row,
                optical_status=_text((optical or {}).get("status")),
                lldp_summary=(
                    ", ".join(
                        filter(
                            None,
                            (
                                item.neighbor_system_name
                                or item.neighbor_mac
                                or item.neighbor_ip
                                for item in neighbors[:3]
                            ),
                        )
                    )
                    or None
                ),
            ),
            transceiver=self._transceiver(optical) if optical else None,
            lldp_neighbors=neighbors,
            lldp_truncated=lldp_truncated,
            source=self._combined_dataset_source(
                device_uuid, ("interfaces", "transceivers", "lldp")
            ),
        )

    def transceivers(
        self,
        device_uuid: str,
        *,
        search: str = "",
        severity: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceTransceiverPageDTO:
        self._device(device_uuid)
        current_page, size, offset = _pagination(page, page_size)
        selected_severity = str(severity or "").strip().casefold()
        truncated = False
        if selected_severity:
            rows, _scanned_total, truncated = self.gateway.list_transceivers_bounded(
                device_uuid, search=search, limit=_TRANSCEIVER_SCAN_LIMIT
            )
            mapped = [
                self._transceiver(row)
                for row in rows
            ]
            selected = [item for item in mapped if item.severity == selected_severity]
            total = len(selected)
            items = selected[offset : offset + size]
        else:
            rows, total = self.gateway.list_transceivers(
                device_uuid, search=search, limit=size, offset=offset
            )
            items = [self._transceiver(row) for row in rows]
        return DeviceTransceiverPageDTO(
            items=items,
            total=total,
            page=current_page,
            page_size=size,
            total_pages=_total_pages(total, size),
            truncated=truncated,
            source=self._dataset_source(
                device_uuid,
                "transceivers",
                reason=(
                    f"严重度筛选仅扫描前 {_TRANSCEIVER_SCAN_LIMIT} 条光模块快照，"
                    "total 为已扫描匹配数"
                    if truncated
                    else None
                ),
            ),
        )

    def lldp(
        self,
        device_uuid: str,
        *,
        search: str = "",
        linked_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceLldpPageDTO:
        self._device(device_uuid)
        current_page, size, offset = _pagination(page, page_size)
        rows, total = self.gateway.list_lldp(
            device_uuid,
            search=search,
            linked_only=linked_only,
            limit=size,
            offset=offset,
        )
        return DeviceLldpPageDTO(
            items=[self._lldp(row) for row in rows],
            total=total,
            page=current_page,
            page_size=size,
            total_pages=_total_pages(total, size),
            source=self._dataset_source(device_uuid, "lldp"),
        )

    def config_snapshots(
        self,
        device_uuid: str,
        *,
        snapshot_type: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceConfigSnapshotPageDTO:
        device = self._device(device_uuid)
        current_page, size, offset = _pagination(page, page_size)
        if (
            self.config_reader is None
            or device.id is None
            or str(device.device_vendor or "").strip().casefold() != "h3c"
        ):
            return DeviceConfigSnapshotPageDTO(
                page=current_page,
                page_size=size,
                source=DeviceDetailSourceDTO(
                    available=False,
                    source="config_collection_application_service",
                    reason="配置快照仅通过已接线的 H3C 配置中心读取",
                ),
            )
        rows, total = self.config_reader.list_snapshots_page(
            self.gateway.current_site_id(),
            int(device.id),
            snapshot_type,
            limit=size,
            offset=offset,
        )
        items = [self._config_snapshot(row) for row in rows]
        return DeviceConfigSnapshotPageDTO(
            items=items,
            total=total,
            page=current_page,
            page_size=size,
            total_pages=_total_pages(total, size),
            source=DeviceDetailSourceDTO(
                source="config_collection_application_service",
                collected_at=max(
                    (item.timestamp for item in items if item.timestamp), default=None
                ),
                task_id=None,
            ),
        )

    def tasks(
        self,
        device_uuid: str,
        *,
        status: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceDetailTaskPageDTO:
        device = self._device(device_uuid)
        current_page, size, offset = _pagination(page, page_size)
        selected_status = str(status or "").strip().upper()
        statuses = {TaskState(selected_status)} if selected_status else None
        repository = self.task_service.repository(self.gateway.current_site_id())
        aliases = self._task_aliases(device)
        tasks = repository.list_filtered(
            statuses=statuses,
            device_aliases=aliases,
            limit=size,
            offset=offset,
        )
        total = repository.count_filtered(
            statuses=statuses, device_aliases=aliases
        )
        return DeviceDetailTaskPageDTO(
            items=[self._task(task, device) for task in tasks],
            total=total,
            page=current_page,
            page_size=size,
            total_pages=_total_pages(total, size),
            truncated=False,
            source=DeviceDetailSourceDTO(
                source="task_application_service",
                collected_at=tasks[0].updated_time if tasks else None,
                task_id=tasks[0].task_id if tasks else None,
            ),
        )

    def business_associations(
        self,
        device_uuid: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> DeviceBusinessAssociationPageDTO:
        device = self._device(device_uuid)
        current_page, size, offset = _pagination(page, page_size)
        platform = identify_device_platform(
            vendor=device.device_vendor,
            device_type=device.device_type,
            software_version=(self.gateway.get_fact(device_uuid) or {}).get(
                "software_version"
            ),
        )
        if not self._business_reader_available(platform.role):
            return DeviceBusinessAssociationPageDTO(
                page=current_page,
                page_size=size,
                source=DeviceDetailSourceDTO(
                    available=False,
                    source=self._business_source(platform.role),
                    reason=self._business_unavailable_reason(platform.role),
                ),
            )
        if platform.role == "wireless_controller":
            return self._ac_business(device, current_page, size)
        if platform.role == "mobile_router":
            return self._mr_business(device, current_page, size, offset)
        return self._switch_business(device, current_page, size, offset)

    def _switch_business(
        self, device: Device, page: int, page_size: int, offset: int
    ) -> DeviceBusinessAssociationPageDTO:
        assert self.business_reader is not None
        aliases = {
            str(value or "").strip().casefold()
            for value in (device.name, device.system_name)
            if str(value or "").strip()
        }
        rows: list[object] = []
        seen: set[tuple[str, str, str]] = set()
        truncated = False
        empty_reason: str | None = None
        scanned = 0
        for alias in sorted(aliases):
            candidate_page = 1
            while scanned < _BUSINESS_SCAN_LIMIT:
                result = self.business_reader.list_rows(
                    self.gateway.current_site_id(),
                    query=alias,
                    page=candidate_page,
                    page_size=min(200, _BUSINESS_SCAN_LIMIT - scanned),
                )
                candidates = list(getattr(result, "items", []) or [])
                empty_reason = empty_reason or _text(
                    getattr(result, "empty_reason", "")
                )
                scanned += len(candidates)
                for row in candidates:
                    if (
                        str(getattr(row, "device_name", "") or "")
                        .strip()
                        .casefold()
                        not in aliases
                    ):
                        continue
                    key = (
                        str(getattr(row, "device_name", "") or "").casefold(),
                        normalize_interface_name(
                            getattr(row, "interface_name", "")
                        ).casefold(),
                        str(getattr(row, "ap_mac", "") or "").casefold(),
                    )
                    if key not in seen:
                        seen.add(key)
                        rows.append(row)
                candidate_total = int(getattr(result, "total", 0) or 0)
                if not candidates or candidate_page * 200 >= candidate_total:
                    break
                candidate_page += 1
            if scanned >= _BUSINESS_SCAN_LIMIT:
                truncated = True
                break
        items = [self._business(row) for row in rows]
        total = len(items)
        return DeviceBusinessAssociationPageDTO(
            items=items[offset : offset + page_size],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=_total_pages(total, page_size),
            truncated=truncated,
            source=DeviceDetailSourceDTO(
                source="trackside_ap_business_query_service",
                collected_at=max(
                    (
                        _text(getattr(row, "updated_at", "")) or ""
                        for row in rows
                    ),
                    default="",
                )
                or None,
                task_id=None,
                reason=(
                    f"关联扫描严格限制为 {_BUSINESS_SCAN_LIMIT} 条；total 为已确认精确匹配数"
                    if truncated
                    else empty_reason
                ),
            ),
        )

    def _ac_business(
        self, device: Device, page: int, page_size: int
    ) -> DeviceBusinessAssociationPageDTO:
        assert self.ac_business_reader is not None
        result = self.ac_business_reader.list_aps(
            self.gateway.current_site_id(),
            ac_id=str(device.device_uuid or ""),
            page=page,
            page_size=page_size,
        )
        rows = list(getattr(result, "items", []) or [])
        items = [self._ac_ap_business(row) for row in rows]
        total = int(getattr(result, "total", len(items)) or 0)
        return DeviceBusinessAssociationPageDTO(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=_total_pages(total, page_size),
            source=DeviceDetailSourceDTO(
                source="ac_management_query_service",
                collected_at=max(
                    (_text(getattr(row, "updated_at", "")) or "" for row in rows),
                    default="",
                )
                or None,
                task_id=None,
            ),
        )

    def _mr_business(
        self, device: Device, page: int, page_size: int, offset: int
    ) -> DeviceBusinessAssociationPageDTO:
        assert self.online_mr_reader is not None
        names = sorted(
            {
                str(value or "").strip()
                for value in (device.name, device.system_name)
                if str(value or "").strip()
            }
        )
        rows: list[object] = []
        seen: set[str] = set()
        truncated = False
        for name in names:
            matches = self.online_mr_reader.list_sessions(
                self.gateway.current_site_id(),
                mr_name=name,
                limit=_MR_SESSION_SCAN_LIMIT + 1,
                offset=0,
            )
            if len(matches) > _MR_SESSION_SCAN_LIMIT:
                truncated = True
            for row in matches[:_MR_SESSION_SCAN_LIMIT]:
                session_id = str(getattr(row, "session_id", "") or "")
                if session_id and session_id not in seen:
                    seen.add(session_id)
                    rows.append(row)
        rows.sort(
            key=lambda row: (
                str(getattr(row, "started_at", "") or ""),
                str(getattr(row, "session_id", "") or ""),
            ),
            reverse=True,
        )
        selected = rows[offset : offset + page_size]
        items = [self._mr_session_business(row) for row in selected]
        total = len(rows)
        return DeviceBusinessAssociationPageDTO(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=_total_pages(total, page_size),
            truncated=truncated,
            source=DeviceDetailSourceDTO(
                source="online_mr_query_service",
                collected_at=max(
                    (
                        _text(getattr(row, "stopped_at", ""))
                        or _text(getattr(row, "started_at", ""))
                        or ""
                        for row in selected
                    ),
                    default="",
                )
                or None,
                task_id=None,
                reason=(
                    f"每个 MR 名称最多读取 {_MR_SESSION_SCAN_LIMIT} 个会话"
                    if truncated
                    else None
                ),
            ),
        )

    def _device(self, device_uuid: str) -> Device:
        device = self.gateway.get_device(device_uuid)
        if device is None:
            raise KeyError(device_uuid)
        return device

    @staticmethod
    def _task_aliases(device: Device) -> set[str]:
        return {
            str(value).strip()
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

    @staticmethod
    def _connection_status(tasks: list[TaskSnapshot]) -> str:
        test = next(
            (
                task
                for task in tasks
                if task.task_type == "device_connection_test"
            ),
            None,
        )
        if test is None:
            return "UNKNOWN"
        if test.status in _ACTIVE_STATES:
            return "TESTING"
        if test.status is TaskState.COMPLETED:
            return "REACHABLE" if test.result.get("success") is True else "UNREACHABLE"
        return "ERROR"

    @staticmethod
    def _visible_sections(
        role: str, capabilities: list[DeviceDetailCapabilityDTO]
    ) -> list[str]:
        available = {
            item.capability_id for item in capabilities if item.available
        }
        sections = ["overview"]
        requirements = (
            ("interfaces", "device.interfaces.read"),
            ("optical", "device.transceivers.read"),
            ("lldp", "device.lldp.read"),
            ("configuration", "device.config_snapshots.read"),
            ("tasks", "device.tasks.read"),
        )
        sections.extend(
            section
            for section, capability_id in requirements
            if capability_id in available
        )
        if "device.business_associations.read" in available:
            sections.append("business")
        return sections

    def _overview_task_facts(
        self, device: Device
    ) -> tuple[DeviceOverviewTaskFactsDTO, str]:
        repository = self.task_service.repository(self.gateway.current_site_id())
        aliases = self._task_aliases(device)
        total = repository.count_filtered(device_aliases=aliases)
        active_count = repository.count_filtered(
            statuses=_ACTIVE_STATES, device_aliases=aliases
        )
        running = next(
            iter(
                repository.list_filtered(
                    statuses=_ACTIVE_STATES, device_aliases=aliases, limit=1
                )
            ),
            None,
        )
        successful = next(
            iter(
                repository.list_filtered(
                    statuses={TaskState.COMPLETED},
                    device_aliases=aliases,
                    limit=1,
                )
            ),
            None,
        )
        failed = next(
            iter(
                repository.list_filtered(
                    statuses={TaskState.FAILED}, device_aliases=aliases, limit=1
                )
            ),
            None,
        )
        connection = next(
            iter(
                repository.list_filtered(
                    task_types={"device_connection_test"},
                    device_aliases=aliases,
                    limit=1,
                )
            ),
            None,
        )
        return (
            self._overview_task_facts_dto(
                total, active_count, running, successful, failed, device
            ),
            self._connection_status([connection] if connection else []),
        )

    @classmethod
    def _overview_task_facts_dto(
        cls,
        total: int,
        active_count: int,
        running: TaskSnapshot | None,
        successful: TaskSnapshot | None,
        failed: TaskSnapshot | None,
        device: Device,
    ) -> DeviceOverviewTaskFactsDTO:
        return DeviceOverviewTaskFactsDTO(
            recent_task_count=total,
            active_task_count=active_count,
            latest_running_task=(
                cls._overview_task(running, device) if running else None
            ),
            latest_successful_task=(
                cls._overview_task(successful, device) if successful else None
            ),
            latest_failed_task=(
                cls._overview_task(failed, device) if failed else None
            ),
            latest_error=(
                cls._safe_task_text(
                    failed.error_message or failed.message, device
                )
                or None
                if failed
                else None
            ),
            truncated=False,
        )

    @classmethod
    def _overview_task(
        cls, task: TaskSnapshot, device: Device
    ) -> DeviceOverviewTaskFactDTO:
        return DeviceOverviewTaskFactDTO(
            task_id=task.task_id,
            task_type=task.task_type,
            status=task.status.value,
            updated_at=task.updated_time,
            finished_at=_text(task.finished_time),
            message=cls._safe_task_text(
                task.error_message or task.message, device
            )
            or None,
        )

    @staticmethod
    def _interface(
        row: dict[str, object | None],
        *,
        optical_status: str | None = None,
        lldp_summary: str | None = None,
    ) -> DeviceInterfaceDTO:
        name = str(row.get("interface_name") or "")
        return DeviceInterfaceDTO(
            name=name,
            normalized_name=normalize_interface_name(name),
            category=_interface_category(name, row.get("interface_type")),
            link_status=_text(row.get("link_status")),
            protocol_status=_text(row.get("protocol_status")),
            speed=_text(row.get("speed")),
            duplex=_text(row.get("duplex")),
            interface_type=_text(row.get("interface_type")),
            port_status=_text(row.get("port_status")),
            pvid=_text(row.get("pvid")),
            description=_text(row.get("description")),
            ip_address=_text(row.get("ip_address")),
            mac_address=_text(row.get("mac_address")),
            vlan=_text(row.get("vlan")),
            optical_status=optical_status,
            lldp_summary=lldp_summary,
            collected_at=_text(row.get("collected_at")),
        )

    @staticmethod
    def _transceiver(row: dict[str, object | None]) -> DeviceTransceiverDTO:
        severity, severity_reason, _threshold_source = _optical_severity(row)
        interface_name = str(row.get("interface_name") or "")
        module_missing = severity == "no_module"
        public_reason = (
            None
            if severity == "normal"
            else _translate_optical_reason(severity_reason)
        )
        return DeviceTransceiverDTO(
            interface_name=interface_name,
            normalized_interface_name=normalize_interface_name(interface_name),
            rx_power=_number(row.get("rx_power")),
            tx_power=_number(row.get("tx_power")),
            temperature=_number(row.get("temperature")),
            voltage=_number(row.get("voltage")),
            bias_current=_number(row.get("bias_current")),
            module_model=None if module_missing else _text(row.get("module_model")),
            module_serial_number=(
                None if module_missing else _text(row.get("module_serial_number"))
            ),
            module_vendor=None if module_missing else _text(row.get("module_vendor")),
            wavelength=None if module_missing else _text(row.get("wavelength")),
            transmission_distance=(
                None if module_missing else _text(row.get("transmission_distance"))
            ),
            connector_type=(
                None if module_missing else _text(row.get("connector_type"))
            ),
            rx_low_alarm=_number(row.get("rx_low_alarm")),
            rx_high_alarm=_number(row.get("rx_high_alarm")),
            rx_low_warning=_number(row.get("rx_low_warning")),
            rx_high_warning=_number(row.get("rx_high_warning")),
            tx_low_alarm=_number(row.get("tx_low_alarm")),
            tx_high_alarm=_number(row.get("tx_high_alarm")),
            tx_low_warning=_number(row.get("tx_low_warning")),
            tx_high_warning=_number(row.get("tx_high_warning")),
            severity=severity,
            severity_reason=public_reason,
            collected_at=_text(row.get("collected_at")),
        )

    @staticmethod
    def _lldp(row: dict[str, object | None]) -> DeviceLldpNeighborDTO:
        local = str(row.get("local_interface") or "")
        linked = _text(row.get("neighbor_device_uuid"))
        return DeviceLldpNeighborDTO(
            local_interface=local,
            normalized_local_interface=normalize_interface_name(local),
            neighbor_system_name=_text(row.get("neighbor_sysname")),
            neighbor_mac=_text(row.get("neighbor_mac")),
            neighbor_interface=_text(row.get("neighbor_interface")),
            neighbor_ip=_text(row.get("neighbor_ip")),
            neighbor_device_uuid=linked,
            association_status="matched" if linked else "unresolved",
            collected_at=_text(row.get("collected_at")),
        )

    @staticmethod
    def _config_snapshot(row: object) -> DeviceConfigSnapshotDTO:
        size = getattr(row, "size_bytes", None)
        return DeviceConfigSnapshotDTO(
            snapshot_id=int(getattr(row, "id", 0) or 0),
            snapshot_type=str(getattr(row, "type", "") or ""),
            timestamp=str(getattr(row, "timestamp", "") or ""),
            size_bytes=int(size) if size is not None else None,
            artifact_id=_text(getattr(row, "artifact_id", "")),
            filename=_safe_filename(getattr(row, "filename", "")),
            sha256=_text(getattr(row, "hash", "")),
            created_at=_text(getattr(row, "created_at", "")),
            error_summary=redact_web_task_text(
                getattr(row, "error_message", "")
            )
            or None,
        )

    @classmethod
    def _task(cls, task: TaskSnapshot, device: Device) -> DeviceDetailTaskDTO:
        return DeviceDetailTaskDTO(
            task_id=task.task_id,
            task_type=task.task_type,
            task_name=cls._safe_task_text(task.task_name, device),
            status=task.status.value,
            progress=task.progress,
            stage=cls._safe_task_text(task.stage, device) or None,
            message=cls._safe_task_text(task.message, device) or None,
            error_summary=cls._safe_task_text(task.error_message, device) or None,
            created_at=task.created_time,
            updated_at=task.updated_time,
            started_at=_text(task.started_time),
            finished_at=_text(task.finished_time),
        )

    @staticmethod
    def _business(row: object) -> DeviceBusinessAssociationDTO:
        interface_name = str(getattr(row, "interface_name", "") or "")
        ap_mac = str(getattr(row, "ap_mac", "") or "")
        ap_name = str(getattr(row, "ap_name", "") or "")
        association_id = f"trackside-ap:{interface_name}:{ap_mac or ap_name}"
        return DeviceBusinessAssociationDTO(
            association_type="trackside_ap",
            association_id=association_id,
            name=ap_name or None,
            status=_text(getattr(row, "optical_severity", "")),
            local_interface=normalize_interface_name(interface_name) or None,
            peer_address=ap_mac or None,
            trackside_ap=DeviceTracksideApAssociationFactsDTO(
                link_status=_text(getattr(row, "link_status", "")),
                switch_rx_power=_number(getattr(row, "switch_rx_power", None)),
                ap_rx_power=_number(getattr(row, "ap_rx_power", None)),
            ),
            updated_at=_text(getattr(row, "updated_at", "")),
        )

    @staticmethod
    def _ac_ap_business(row: object) -> DeviceBusinessAssociationDTO:
        ap_id = str(getattr(row, "id", "") or "")
        return DeviceBusinessAssociationDTO(
            association_type="fit_ap",
            association_id=f"fit-ap:{ap_id}",
            name=_text(getattr(row, "name", "")),
            status=_text(getattr(row, "status", "")),
            local_interface=_text(getattr(row, "switch_interface", "")),
            peer_address=_text(
                getattr(row, "mac", "") or getattr(row, "ip", "")
            ),
            fit_ap=DeviceAcApAssociationFactsDTO(
                mac_address=_text(getattr(row, "mac", "")),
                radio1_status=_text(getattr(row, "radio1_status", "")),
                radio1_channel=_text(getattr(row, "radio1_channel", "")),
                radio1_power=_text(getattr(row, "radio1_power", "")),
                radio2_status=_text(getattr(row, "radio2_status", "")),
                radio2_channel=_text(getattr(row, "radio2_channel", "")),
                radio2_power=_text(getattr(row, "radio2_power", "")),
                lldp_status=_text(getattr(row, "lldp_status", "")),
                optical_status=_text(getattr(row, "optical_status", "")),
                optical_rx_power=_number(getattr(row, "optical_rx_power", None)),
            ),
            updated_at=_text(getattr(row, "updated_at", "")),
        )

    def _mr_session_business(self, row: object) -> DeviceBusinessAssociationDTO:
        assert self.online_mr_reader is not None
        site = self.gateway.current_site_id()
        session_id = str(getattr(row, "session_id", "") or "")
        detail = self.online_mr_reader.get_session(site, session_id)
        preview = self.online_mr_reader.get_realtime_preview(site, session_id)
        enabled = {
            str(value).casefold()
            for value in list(getattr(detail, "enabled_collectors", []) or [])
        }
        database = getattr(detail, "database_summary", None)
        row_counts = dict(getattr(database, "row_counts", {}) or {})
        traffic = dict(getattr(detail, "traffic_summary", {}) or {})
        link_preview = dict(getattr(preview, "link", {}) or {})
        fping_preview = dict(getattr(preview, "fping", {}) or {})
        iperf_preview = dict(getattr(preview, "iperf", {}) or {})
        mesh_available = (
            "mesh_link" in enabled
            or any("mesh" in str(key).casefold() for key, value in row_counts.items() if value)
            or bool(link_preview)
        )
        rssi_available = any(
            "rssi" in str(key).casefold() for key, value in row_counts.items() if value
        ) or any(
            key in link_preview for key in ("rssi", "rssi_dbm", "signal_strength")
        )
        fping_available = (
            bool({"fping", "fping_v5"} & enabled)
            or bool(traffic.get("fping"))
            or bool(fping_preview)
        )
        iperf_available = (
            bool({"iperf", "iperf_client"} & enabled)
            or bool(traffic.get("iperf"))
            or bool(iperf_preview)
        )
        return DeviceBusinessAssociationDTO(
            association_type="online_mr_session",
            association_id=f"online-mr-session:{session_id}",
            name=_text(getattr(row, "mr_name", "")),
            status=_text(getattr(row, "status", "")),
            online_mr_session=DeviceMrSessionAssociationFactsDTO(
                site_id=str(getattr(row, "site_id", "") or site),
                started_at=_text(getattr(row, "started_at", "")),
                stopped_at=_text(getattr(row, "stopped_at", "")),
                executor_kind=_text(getattr(row, "executor_kind", "")),
                has_raw_data=bool(getattr(row, "has_raw_data", False)),
                has_parsed_data=bool(getattr(row, "has_parsed_data", False)),
                has_package=bool(getattr(row, "has_package", False)),
                mesh_available=mesh_available,
                rssi_available=rssi_available,
                fping_available=fping_available,
                iperf_available=iperf_available,
            ),
            updated_at=(
                _text(getattr(preview, "updated_at", ""))
                or _text(getattr(row, "stopped_at", ""))
                or _text(getattr(row, "started_at", ""))
            ),
        )

    @staticmethod
    def _snapshot_source(
        fact: dict[str, object | None] | None,
        *,
        reason: str | None = None,
    ) -> DeviceDetailSourceDTO:
        return DeviceDetailSourceDTO(
            available=fact is not None,
            source="devices.db.latest_snapshot",
            collected_at=_text((fact or {}).get("collected_at")),
            task_id=None,
            reason=reason if fact is not None else "尚无设备详情采集快照",
        )

    def _dataset_source(
        self, device_uuid: str, dataset: str, *, reason: str | None = None
    ) -> DeviceDetailSourceDTO:
        source = self.gateway.snapshot_source(device_uuid, dataset)
        return DeviceDetailSourceDTO(
            available=source is not None,
            source=f"devices.db.{dataset}.latest_snapshot",
            collected_at=_text((source or {}).get("collected_at")),
            task_id=_text((source or {}).get("task_id")),
            reason=reason if source is not None else f"尚无 {dataset} 快照",
        )

    def _combined_dataset_source(
        self,
        device_uuid: str,
        datasets: tuple[str, ...],
        *,
        reason: str | None = None,
    ) -> DeviceDetailSourceDTO:
        sources = [
            self.gateway.snapshot_source(device_uuid, dataset)
            for dataset in datasets
        ]
        available = [source for source in sources if source is not None]
        return DeviceDetailSourceDTO(
            available=bool(available),
            source="devices.db.combined_snapshot",
            collected_at=max(
                (_text(source.get("collected_at")) or "" for source in available),
                default="",
            )
            or None,
            task_id=None,
            reason=reason if available else "尚无健康相关快照",
        )

    def _business_reader_available(self, role: str) -> bool:
        return {
            "switch": self.business_reader is not None,
            "wireless_controller": self.ac_business_reader is not None,
            "mobile_router": self.online_mr_reader is not None,
        }.get(role, False)

    def _business_source(self, role: str) -> str:
        return {
            "switch": "trackside_ap_business_query_service",
            "wireless_controller": "ac_management_query_service",
            "mobile_router": "online_mr_query_service",
        }.get(role, "device_detail_query_service")

    def _business_unavailable_reason(self, role: str) -> str | None:
        if self._business_reader_available(role):
            return None
        return {
            "switch": "轨旁 AP 业务 Query 未接线",
            "wireless_controller": "AC 管理 Query 未接线",
            "mobile_router": "Online MR Query 未接线",
        }.get(role, "当前设备角色没有已验证的关联业务 Query")

    @staticmethod
    def _capability(
        capability_id: str,
        *,
        available: bool = True,
        reason: str | None = None,
        source: str = "device_detail_query_service",
    ) -> DeviceDetailCapabilityDTO:
        return DeviceDetailCapabilityDTO(
            capability_id=capability_id,
            available=available,
            executable=False,
            source=source,
            reason=reason,
        )

    @staticmethod
    def _capability_dto(
        capability: DeviceCapability,
    ) -> DeviceDetailCapabilityDTO:
        return DeviceDetailCapabilityDTO(**capability.__dict__)

    @staticmethod
    def _safe_task_text(value: object, device: Device) -> str:
        return redact_web_task_text(
            sanitize_sensitive_text(str(value or ""), device)
        )


_ACTIVE_STATES = frozenset(
    {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
)
_INTERFACE_LLDP_LIMIT = 200
_TRANSCEIVER_SCAN_LIMIT = 1000
_BUSINESS_SCAN_LIMIT = 1000
_MR_SESSION_SCAN_LIMIT = 1000

_OPTICAL_REASON_TRANSLATIONS = {
    "Optical module is not present": "未检测到光模块",
    "RX power is missing or <= -35 dBm": "接收光功率缺失或 ≤ -35 dBm",
    "Port is DOWN": "端口状态为 DOWN",
    "RX threshold is missing": "接收光功率阈值缺失",
    "RX power is above maintenance normal line": "接收光功率位于维护正常线以上",
    "RX power is below maintenance normal line": "接收光功率位于维护正常线以下",
    "RX power is between alarm low and warning low threshold": (
        "接收光功率介于告警低阈值与警告低阈值之间"
    ),
    "RX power below alarm low threshold": "接收光功率低于告警低阈值",
}

_OPTICAL_MODULE_IDENTITY_FIELDS = (
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
)
_OPTICAL_MODULE_NUMERIC_FIELDS = (
    "rx_power",
    "tx_power",
    "temperature",
    "voltage",
    "bias_current",
    "rx_low_alarm",
    "rx_high_alarm",
    "rx_low_warning",
    "rx_high_warning",
    "tx_low_alarm",
    "tx_high_alarm",
    "tx_low_warning",
    "tx_high_warning",
)
_MISSING_OPTICAL_FACT_VALUES = {"", "-", "--", "—", "n/a", "na", "none", "null", "missing", "unknown"}


def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
    current = max(1, int(page))
    size = max(1, min(int(page_size), 200))
    return current, size, (current - 1) * size


def _total_pages(total: int, page_size: int) -> int:
    return max(1, math.ceil(max(0, int(total)) / max(1, int(page_size))))


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _translate_optical_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    return _OPTICAL_REASON_TRANSLATIONS.get(reason, reason)


def _number(value: object) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _has_optical_module_evidence(row: dict[str, object | None]) -> bool:
    for field in _OPTICAL_MODULE_IDENTITY_FIELDS:
        value = str(row.get(field) or "").strip().casefold()
        if value not in _MISSING_OPTICAL_FACT_VALUES:
            return True
    return any(_number(row.get(field)) is not None for field in _OPTICAL_MODULE_NUMERIC_FIELDS)


def _optical_severity(
    row: dict[str, object | None],
) -> tuple[str, str | None, str]:
    status = str(row.get("status") or "").strip().casefold()
    if status == "no_module":
        return status, "Optical module is not present", "collector_status"

    module_present = _has_optical_module_evidence(row)
    if not module_present:
        result = compute_optical_severity({"module_present": False})
        return result.severity, result.reason, result.warning_source

    if status in {
        "no_light",
        "link_abnormal",
        "link_down",
        "offline",
        "not_collected",
        "skipped",
    }:
        return status, f"采集状态: {status}", "collector_status"

    rx = compute_optical_severity(
        {
            "module_present": module_present,
            "rx_power": row.get("rx_power"),
            "rx_low_alarm": row.get("rx_low_alarm"),
            "rx_high_alarm": row.get("rx_high_alarm"),
            "rx_low_warning": row.get("rx_low_warning"),
            "rx_high_warning": row.get("rx_high_warning"),
        }
    )
    candidates = [
        (rx.severity, rx.reason, rx.warning_source),
        _power_threshold_severity(
            "RX",
            row.get("rx_power"),
            row.get("rx_low_alarm"),
            row.get("rx_high_alarm"),
            row.get("rx_low_warning"),
            row.get("rx_high_warning"),
        ),
        _power_threshold_severity(
            "TX",
            row.get("tx_power"),
            row.get("tx_low_alarm"),
            row.get("tx_high_alarm"),
            row.get("tx_low_warning"),
            row.get("tx_high_warning"),
        ),
    ]
    if status in SEVERITY_RANK:
        candidates.append((status, f"采集状态: {status}", "collector_status"))
    return max(candidates, key=lambda item: SEVERITY_RANK.get(item[0], 0))


def _power_threshold_severity(
    label: str,
    power: object,
    low_alarm: object,
    high_alarm: object,
    low_warning: object,
    high_warning: object,
) -> tuple[str, str | None, str]:
    value = _number(power)
    thresholds = {
        "low_alarm": _number(low_alarm),
        "high_alarm": _number(high_alarm),
        "low_warning": _number(low_warning),
        "high_warning": _number(high_warning),
    }
    if value is None or not any(item is not None for item in thresholds.values()):
        return "unknown", f"{label} 功率或阈值缺失", "missing"
    if (
        thresholds["low_alarm"] is not None
        and value <= thresholds["low_alarm"]
    ) or (
        thresholds["high_alarm"] is not None
        and value >= thresholds["high_alarm"]
    ):
        return "alarm", f"{label} 功率越过告警阈值", f"native_{label.lower()}"
    if (
        thresholds["low_warning"] is not None
        and value <= thresholds["low_warning"]
    ) or (
        thresholds["high_warning"] is not None
        and value >= thresholds["high_warning"]
    ):
        return "warning", f"{label} 功率越过预警阈值", f"native_{label.lower()}"
    return "normal", f"{label} 功率处于原生阈值范围", f"native_{label.lower()}"


def _safe_filename(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text:
        return None
    return text


def _interface_category(name: str, raw_type: object) -> str:
    normalized = normalize_interface_name(name).casefold()
    raw = str(raw_type or "").strip().casefold()
    if normalized.startswith(("gigabitethernet", "ten-gigabitethernet")):
        return "physical"
    if normalized.startswith(("bridge-aggregation", "eth-trunk", "port-channel")):
        return "aggregate"
    if normalized.startswith(("vlan-interface", "vlanif")):
        return "vlan"
    if normalized.startswith("loopback"):
        return "loopback"
    if normalized.startswith(("management", "meth")):
        return "management"
    if normalized.startswith("tunnel"):
        return "tunnel"
    return raw or "other"


__all__ = [
    "AcBusinessAssociationReader",
    "BusinessAssociationReader",
    "ConfigSnapshotReader",
    "DeviceDetailQueryService",
    "OnlineMrBusinessAssociationReader",
]
