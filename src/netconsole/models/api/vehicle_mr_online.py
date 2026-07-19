from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class VehicleMrEndStateDTO(ApiModel):
    endpoint: Literal["CT", "TC"]
    mr_id: str | None = None
    mr_name: str | None = None
    online_status: Literal["ONLINE", "OFFLINE", "STALE", "UNKNOWN"] = "UNKNOWN"
    current_ap_name: str | None = None
    current_ap_mac: str | None = None
    mesh_radio: str | None = None
    rssi_dbm: int | None = None
    station_name: str | None = None
    section_name: str | None = None
    mileage: str | None = None
    direction: str | None = None
    match_status: Literal[
        "EXACT", "NAME_NORMALIZED", "MAC_MATCHED", "UNMATCHED", "UNKNOWN"
    ] = "UNKNOWN"
    outdoor_optical_power: str | None = None
    indoor_optical_power: str | None = None
    updated_at: str | None = None
    data_status: Literal["FRESH", "STALE", "ERROR", "NO_DATA", "UNKNOWN"] = "NO_DATA"


class VehicleMrTrainStateDTO(ApiModel):
    train_id: str
    train_no: str
    train_name: str
    is_registered: bool
    overall_status: Literal[
        "BOTH_ONLINE", "ONE_SIDE_ONLINE", "BOTH_OFFLINE", "STALE", "UNKNOWN"
    ]
    ct: VehicleMrEndStateDTO
    tc: VehicleMrEndStateDTO
    current_station: str | None = None
    current_section: str | None = None
    current_mileage: str | None = None
    direction: str | None = None
    policy: str | None = None
    reason_code: str | None = None
    reason_text: str | None = None
    updated_at: str | None = None


class VehicleMrOnlinePageDTO(ApiModel):
    items: list[VehicleMrTrainStateDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    site_id: str
    mr_total: int = 0
    both_online_count: int = 0
    one_side_online_count: int = 0
    both_offline_count: int = 0
    stale_count: int = 0
    unknown_count: int = 0
    active_mesh_link_count: int = 0
    unmatched_ap_count: int = 0


class VehicleMrTrainMappingDTO(ApiModel):
    id: int | None = None
    enabled: bool = True
    train_display_name: str = ""
    train_id: str = ""
    train_no: str = ""
    tc1_peer_name: str = ""
    tc2_peer_name: str = ""
    online_policy: str = "auto"
    remark: str = ""
    created_at: str = ""
    updated_at: str = ""


class VehicleMrMappingSaveRequestDTO(ApiModel):
    mappings: list[VehicleMrTrainMappingDTO] = Field(default_factory=list)
    explicit_confirmation: bool = False
    audit: dict[str, str] = Field(default_factory=dict)


class VehicleMrControllerDTO(ApiModel):
    controller_id: str
    device_id: int
    name: str
    primary_address: str = ""
    protocol: str = ""
    connection_ready: bool = False


class VehicleMrCollectionStartRequestDTO(ApiModel):
    ac_device_id: int
    interval_seconds: int = Field(default=10, ge=3, le=300)


class VehicleMrHistoryExportRequestDTO(ApiModel):
    train_id: str
    start_time: str = ""
    end_time: str = ""
    car_end_label: str = ""
    status: str = ""
    station: str = ""
    ap_name: str = ""


class VehicleMrMappingPreviewRowDTO(ApiModel):
    row_number: int
    status: Literal["valid", "duplicate", "error"]
    key: str = ""
    message: str = ""
    row: VehicleMrTrainMappingDTO | None = None


class VehicleMrMappingPreviewDTO(ApiModel):
    file_name: str
    file_sha256: str
    duplicate_strategy: Literal["replace", "skip", "error"]
    can_apply: bool
    total_count: int
    valid_count: int
    duplicate_count: int
    error_count: int
    rows: list[VehicleMrMappingPreviewRowDTO] = Field(default_factory=list)
    result_rows: list[VehicleMrTrainMappingDTO] = Field(default_factory=list)


class VehicleMrEventPageDTO(ApiModel):
    items: list[dict[str, object]] = Field(default_factory=list)
    total: int = 0


__all__ = [name for name in globals() if name.startswith("VehicleMr")]
