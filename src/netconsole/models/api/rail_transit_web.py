from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class RailTransitTaskDTO(ApiModel):
    task_id: str
    status: str = "PENDING"
    action: str
    artifact_id: str = ""
    artifact_name: str = ""
    available: bool = False
    sha256: str = ""
    size_bytes: int = 0
    message: str = ""
    error_message: str = ""
    result_summary: dict[str, object] = Field(default_factory=dict)


class CarNetworkPointRowDTO(ApiModel):
    train_id: str = ""
    train_no: str = ""
    display_name: str = ""
    tc: str = ""
    end: str = ""
    node_name: str = ""
    node_type: str = ""
    device_id: str = ""
    device_name: str = ""
    device_group: str = ""
    station: str = ""
    primary_address: str = ""
    backup_address: str = ""
    ip_vehicle: str = ""
    ip_uplink: str = ""
    ssh_host: str = ""
    vrrp_ip: str = ""
    address_mapping_mode: str = "global"
    primary_address_role: str = ""
    backup_address_role: str = ""
    remark: str = ""


class CarNetworkPointTableDTO(ApiModel):
    rows: list[CarNetworkPointRowDTO] = Field(default_factory=list)
    global_config: dict[str, object] = Field(default_factory=dict)
    locked: bool = False
    revision: str = ""


class CarNetworkPointPreviewRowDTO(ApiModel):
    row_number: int
    status: Literal["valid", "duplicate", "error"]
    key: str = ""
    message: str = ""
    row: CarNetworkPointRowDTO | None = None


class CarNetworkPointPreviewDTO(ApiModel):
    file_name: str
    file_sha256: str
    duplicate_strategy: Literal["replace", "skip", "error"]
    can_apply: bool
    total_count: int
    valid_count: int
    duplicate_count: int
    error_count: int
    rows: list[CarNetworkPointPreviewRowDTO] = Field(default_factory=list)
    result_rows: list[CarNetworkPointRowDTO] = Field(default_factory=list)


class CarNetworkPointTableWriteRequestDTO(ApiModel):
    rows: list[CarNetworkPointRowDTO] = Field(default_factory=list)
    global_config: dict[str, object] = Field(default_factory=dict)
    target_train: dict[str, object] = Field(default_factory=dict)
    overwrite_custom: bool = False
    explicit_confirmation: bool = False
    audit: dict[str, str] = Field(default_factory=dict)
    revision: str = "missing"


class CarNetworkPointTableTransformRequestDTO(ApiModel):
    operation: Literal["apply_mapping", "apply_global", "apply_global_override", "restore_defaults"]
    rows: list[CarNetworkPointRowDTO] = Field(default_factory=list)
    global_config: dict[str, object] = Field(default_factory=dict)


class CarNetworkPointTableExportRequestDTO(ApiModel):
    format: Literal["xlsx", "csv"] = "xlsx"


class OnlineMrReportRequestDTO(ApiModel):
    output_name: str = ""


class OnlineMrParseRequestDTO(ApiModel):
    force_reparse: bool = False


class OnlineMrDeleteRequestDTO(ApiModel):
    expected_session_id: str = Field(min_length=1, max_length=160)
    explicit_confirmation: bool = False


class OnlineMrDesktopLocationDTO(ApiModel):
    target_type: Literal["file", "directory"]
    path: str


class OnlineMrNoteCreateRequestDTO(ApiModel):
    note: str = Field(min_length=1, max_length=500)
    explicit_confirmation: bool = False
    audit: dict[str, str] = Field(default_factory=dict)


class OnlineMrTimelineQueryDTO(ApiModel):
    limit: int = 500
    offset: int = 0


__all__ = [
    "CarNetworkPointPreviewDTO",
    "CarNetworkPointPreviewRowDTO",
    "CarNetworkPointRowDTO",
    "CarNetworkPointTableDTO",
    "CarNetworkPointTableExportRequestDTO",
    "CarNetworkPointTableTransformRequestDTO",
    "CarNetworkPointTableWriteRequestDTO",
    "OnlineMrNoteCreateRequestDTO",
    "OnlineMrParseRequestDTO",
    "OnlineMrDeleteRequestDTO",
    "OnlineMrDesktopLocationDTO",
    "OnlineMrReportRequestDTO",
    "OnlineMrTimelineQueryDTO",
    "RailTransitTaskDTO",
]
