from __future__ import annotations

from netconsole.models.api.device_detail import (
    DeviceBusinessAssociationPageDTO,
    DeviceConfigSnapshotPageDTO,
    DeviceDetailTaskPageDTO,
    DeviceInterfaceDetailDTO,
    DeviceInterfacePageDTO,
    DeviceLldpPageDTO,
    DeviceOverviewDTO,
    DeviceRefreshTaskDTO,
    DeviceTransceiverPageDTO,
)
from netconsole.services.device_detail_query_service import DeviceDetailQueryService
from netconsole.services.device_operation_service import DeviceOperationService


class DeviceDetailApplicationService:
    """设备详情纵向用例边界；读快照与受控刷新分别委托专用 Service。"""

    def __init__(
        self,
        query_service: DeviceDetailQueryService,
        operation_service: DeviceOperationService,
    ) -> None:
        self.query_service = query_service
        self.operation_service = operation_service

    def overview(self, device_uuid: str) -> DeviceOverviewDTO:
        return self.query_service.overview(device_uuid)

    def interfaces(self, device_uuid: str, **filters: object) -> DeviceInterfacePageDTO:
        return self.query_service.interfaces(device_uuid, **filters)

    def interface_detail(
        self, device_uuid: str, interface_name: str
    ) -> DeviceInterfaceDetailDTO:
        return self.query_service.interface_detail(device_uuid, interface_name)

    def transceivers(
        self, device_uuid: str, **filters: object
    ) -> DeviceTransceiverPageDTO:
        return self.query_service.transceivers(device_uuid, **filters)

    def lldp(self, device_uuid: str, **filters: object) -> DeviceLldpPageDTO:
        return self.query_service.lldp(device_uuid, **filters)

    def config_snapshots(
        self, device_uuid: str, **filters: object
    ) -> DeviceConfigSnapshotPageDTO:
        return self.query_service.config_snapshots(device_uuid, **filters)

    def tasks(self, device_uuid: str, **filters: object) -> DeviceDetailTaskPageDTO:
        return self.query_service.tasks(device_uuid, **filters)

    def business_associations(
        self, device_uuid: str, **filters: object
    ) -> DeviceBusinessAssociationPageDTO:
        return self.query_service.business_associations(device_uuid, **filters)

    def refresh(
        self,
        device_uuid: str,
        operation_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> DeviceRefreshTaskDTO:
        task = self.operation_service.start(
            device_uuid,
            operation_id,
            idempotency_key=idempotency_key,
        )
        return DeviceRefreshTaskDTO(**task.__dict__)


__all__ = ["DeviceDetailApplicationService"]
