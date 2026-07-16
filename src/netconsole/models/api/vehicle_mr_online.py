from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class VehicleMrEndStateDTO(ApiModel):
    seen: bool = False
    station: str = ""
    ap_name: str = ""
    rssi: int | None = None
    last_seen_at: str = ""
    match_method: str = "unmatched"
    match_score: int = 0


class VehicleMrTrainStateDTO(ApiModel):
    train_id: str
    train_no: str
    display_name: str
    is_registered: bool
    status: str
    current_station: str = "-"
    last_ac_time: str = ""
    last_seen_at: str = ""
    tc1: VehicleMrEndStateDTO = Field(default_factory=VehicleMrEndStateDTO)
    tc2: VehicleMrEndStateDTO = Field(default_factory=VehicleMrEndStateDTO)
    online_policy: str = "auto"
    expected_end: str = ""
    direction: str = "未知"
    status_reason: str = ""


class VehicleMrOnlinePageDTO(ApiModel):
    items: list[VehicleMrTrainStateDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    site_id: str
    online_count: int = 0
    abnormal_count: int = 0
    offline_count: int = 0
    unregistered_count: int = 0


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


class VehicleMrEventPageDTO(ApiModel):
    items: list[dict[str, object]] = Field(default_factory=list)
    total: int = 0


__all__ = [name for name in globals() if name.startswith("VehicleMr")]
