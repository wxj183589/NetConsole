from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class AcMeshLinkRecordDTO(ApiModel):
    id: int
    snapshot_id: int
    controller_id: str = ""
    controller_name: str = ""
    mr_id: str
    train_no: str = ""
    car_end: str = ""
    mr_name: str = ""
    mr_mac: str = ""
    mr_device_id: str = ""
    mr_management_ip: str = ""
    mr_online_status: str = "unknown"
    peer_ap_id: str = ""
    peer_ap_name: str = ""
    peer_ap_mac: str = ""
    peer_radio: str = ""
    mesh_interface: str = ""
    rssi: int | None = None
    station: str = ""
    section: str = ""
    mileage: str = ""
    line_side: str = ""
    ap_rx_power: str = ""
    switch_rx_power: str = ""
    last_seen_at: str = ""
    match_method: str = "unmatched"
    match_warning: str = ""
    data_status: str = "no_data"


class AcMeshLinkPageDTO(ApiModel):
    items: list[AcMeshLinkRecordDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class AcMeshMrStatusDTO(ApiModel):
    mr_id: str
    train_no: str = ""
    train_display_name: str = ""
    car_end: str = ""
    mr_name: str = ""
    mr_mac: str = ""
    mr_device_id: str = ""
    management_ip: str = ""
    online_status: str = "unknown"
    peer_ap_id: str = ""
    peer_ap_name: str = ""
    peer_ap_mac: str = ""
    mesh_radio: str = ""
    rssi: int | None = None
    station: str = ""
    section: str = ""
    mileage: str = ""
    line_side: str = ""
    ap_rx_power: str = ""
    switch_rx_power: str = ""
    last_seen_at: str = ""
    match_method: str = "unmatched"
    match_warning: str = ""
    data_status: str = "no_data"


class AcMeshMrPageDTO(ApiModel):
    items: list[AcMeshMrStatusDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class AcMeshMrEventDTO(ApiModel):
    id: int
    event_time: str = ""
    event_type: str = ""
    status: str = ""
    station: str = ""
    ap_name: str = ""
    rssi: int | None = None
    car_end: str = ""


class AcMeshMrDetailDTO(ApiModel):
    mr: AcMeshMrStatusDTO
    current_links: list[AcMeshLinkRecordDTO] = Field(default_factory=list)
    recent_events: list[AcMeshMrEventDTO] = Field(default_factory=list)


class AcMeshSnapshotDTO(ApiModel):
    id: int
    session_id: str
    controller_id: str = ""
    controller_name: str = ""
    site_id: str
    collected_at: str = ""
    ac_time: str = ""
    source_type: str = "vehicle_mr_online_snapshot"
    source_reference: str = ""
    data_status: str = "no_data"
    age_seconds: int | None = None
    link_count: int = 0
    parse_status: str = ""
    error_summary: str = ""


class AcMeshSnapshotPageDTO(ApiModel):
    items: list[AcMeshSnapshotDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 30


class AcMeshSnapshotDetailDTO(ApiModel):
    snapshot: AcMeshSnapshotDTO
    links: list[AcMeshLinkRecordDTO] = Field(default_factory=list)


class AcMeshLinkSummaryDTO(ApiModel):
    site_id: str
    controller_id: str = ""
    controller_name: str = ""
    registered_mrs: int = 0
    online_mrs: int = 0
    offline_mrs: int = 0
    stale_mrs: int = 0
    unknown_mrs: int = 0
    active_links: int = 0
    link_total: int = 0
    unmatched_links: int = 0
    offline_ap_links: int = 0
    updated_at: str = ""
    age_seconds: int | None = None
    data_status: str = "no_data"
    source_type: str = "vehicle_mr_online_snapshot"
    raw_available: bool = False
    message: str = ""


class AcMeshRawTailDTO(ApiModel):
    snapshot_id: int | None = None
    available: bool = False
    lines: list[str] = Field(default_factory=list)
    line_count: int = 0
    source_reference: str = ""
    updated_at: str = ""
    message: str = "暂无 Mesh-Link 原始数据"


class AcMeshLinkRefreshRequestDTO(ApiModel):
    controller_id: str = Field(min_length=1, max_length=100)
    include_switch_history: bool = False


class AcMeshLinkRefreshResponseDTO(ApiModel):
    success: bool = True
    task_id: str
    status: str
    already_running: bool = False
    message: str


__all__ = [
    "AcMeshLinkPageDTO",
    "AcMeshLinkRecordDTO",
    "AcMeshLinkRefreshRequestDTO",
    "AcMeshLinkRefreshResponseDTO",
    "AcMeshLinkSummaryDTO",
    "AcMeshMrDetailDTO",
    "AcMeshMrEventDTO",
    "AcMeshMrPageDTO",
    "AcMeshMrStatusDTO",
    "AcMeshRawTailDTO",
    "AcMeshSnapshotDTO",
    "AcMeshSnapshotDetailDTO",
    "AcMeshSnapshotPageDTO",
]
