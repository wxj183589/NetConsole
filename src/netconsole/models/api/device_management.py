from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


DeviceConnectionStatus = Literal["UNKNOWN", "TESTING", "REACHABLE", "UNREACHABLE", "ERROR"]
DeviceConnectionProtocol = Literal["SSH", "TELNET", "SNMP"]


class DeviceCapabilityDTO(ApiModel):
    ssh: bool = False
    ssh_port: int | None = None
    telnet: bool = False
    telnet_port: int | None = None
    snmp: bool = False
    snmp_versions: list[str] = Field(default_factory=list)
    snmp_port: int | None = None


class DeviceGroupOptionDTO(ApiModel):
    id: int
    name: str


class DeviceListItemDTO(ApiModel):
    id: int
    device_uuid: str
    name: str
    system_name: str = ""
    station: str = ""
    group_id: int | None = None
    group_name: str = "未分组"
    device_vendor: str = ""
    device_type: str = ""
    primary_address: str = ""
    backup_address: str = ""
    updated_at: str = ""
    capabilities: DeviceCapabilityDTO
    connection_status: DeviceConnectionStatus = "UNKNOWN"
    last_test_task_id: str = ""
    last_test_time: str = ""


class DevicePageDTO(ApiModel):
    items: list[DeviceListItemDTO] = Field(default_factory=list)
    groups: list[DeviceGroupOptionDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1


class DeviceFactDTO(ApiModel):
    system_name: str = ""
    model: str = ""
    serial_number: str = ""
    mac_address: str = ""
    software_version: str = ""
    bootrom_version: str = ""
    vendor: str = ""
    uptime: str = ""
    collected_at: str = ""


class DeviceTaskSummaryDTO(ApiModel):
    task_id: str
    task_type: str
    task_name: str
    status: str
    stage: str = ""
    message: str = ""
    created_time: str = ""
    updated_time: str = ""
    error_summary: str = ""


class DeviceCollectionSummaryDTO(ApiModel):
    collect_run_uuid: str
    collect_type: str
    status: str
    started_at: str
    ended_at: str = ""
    error_summary: str = ""


class DeviceErrorSummaryDTO(ApiModel):
    source: Literal["task", "collection"]
    time: str
    message: str


class DeviceConnectionCommandDTO(ApiModel):
    protocol: Literal["SSH", "TELNET"]
    command: str


class DeviceDetailItemDTO(DeviceListItemDTO):
    location: str = ""
    mac_address: str = ""
    https_port: int | None = None
    remark: str = ""
    created_at: str = ""


class DeviceDetailDTO(ApiModel):
    device: DeviceDetailItemDTO
    fact: DeviceFactDTO | None = None
    recent_tasks: list[DeviceTaskSummaryDTO] = Field(default_factory=list)
    recent_collection: DeviceCollectionSummaryDTO | None = None
    recent_errors: list[DeviceErrorSummaryDTO] = Field(default_factory=list)
    connection_commands: list[DeviceConnectionCommandDTO] = Field(default_factory=list)


class DeviceEditPreviewRequestDTO(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    system_name: str = Field(default="", max_length=120)
    station: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=200)
    group_id: int | None = Field(default=None, ge=1)
    device_vendor: str = Field(default="H3C", max_length=40)
    device_type: str = Field(default="SW", max_length=40)
    primary_address: str = Field(min_length=1, max_length=255)
    backup_address: str = Field(default="", max_length=255)
    ssh_enabled: bool = True
    ssh_port: int = Field(default=22, ge=1, le=65535)
    telnet_enabled: bool = False
    telnet_port: int = Field(default=23, ge=1, le=65535)
    snmp_enabled: bool = True
    snmp_v1_enabled: bool = False
    snmp_v2c_enabled: bool = True
    snmp_v3_enabled: bool = False
    snmp_port: int = Field(default=161, ge=1, le=65535)
    https_port: int | None = Field(default=None, ge=1, le=65535)
    remark: str = Field(default="", max_length=1000)


class DeviceEditPreviewDTO(ApiModel):
    valid: bool
    normalized: DeviceEditPreviewRequestDTO
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    persistence: Literal["preview_only"] = "preview_only"


class DeviceConnectionTestRequestDTO(ApiModel):
    protocol: DeviceConnectionProtocol


class DeviceConnectionTestDTO(ApiModel):
    task_id: str
    task_status: str
    device_uuid: str
    protocol: DeviceConnectionProtocol | None = None
    success: bool | None = None
    result_status: str = ""
    message: str = ""
    method: str = ""
    host: str = ""
    port: int | None = None
    latency_ms: int | None = None
    system_name: str = ""
    model: str = ""
    os_family: str = ""
    interface_count: int | None = None
    error_type: str = ""
    suggestion: str = ""
    created_time: str = ""
    updated_time: str = ""


__all__ = [name for name in globals() if name.endswith("DTO")]
