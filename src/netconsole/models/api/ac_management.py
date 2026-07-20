from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class AcOverviewDTO(ApiModel):
    id: str
    name: str
    management_ip: str = ""
    web_url: str = ""
    model: str = ""
    software_version: str = ""
    cpu_usage: str = ""
    memory_usage: str = ""
    https_port: int | None = None
    ap_total: int = 0
    online_aps: int = 0
    offline_aps: int = 0
    unauthenticated_aps: int = 0
    radio_total: int = 0
    optical_anomalies: int = 0
    updated_at: str = ""
    data_source: str = "SQLite 已采集数据"


class AcManagementSummaryDTO(ApiModel):
    site_id: str
    acs: list[AcOverviewDTO] = Field(default_factory=list)
    ap_total: int = 0
    online_aps: int = 0
    offline_aps: int = 0
    unauthenticated_aps: int = 0
    radio_total: int = 0
    optical_anomalies: int = 0
    updated_at: str = ""
    message: str = ""


class AcOpticalDTO(ApiModel):
    optical_status: str = "no_data"
    optical_severity: str = "no_data"
    raw_status: str = "unknown"
    ap_offline_related: bool = False
    ap_online_status: str = "unknown"
    data_freshness: str = "unknown"
    is_current_anomaly: bool = False
    anomaly_reason: str = ""
    source_switch: str = ""
    source_interface: str = ""
    tx_power: str = ""
    rx_power: str = ""
    switch_rx_power: str = ""
    temperature: str = ""
    voltage: str = ""
    bias_current: str = ""
    threshold_status: str = ""
    error_summary: str = ""
    updated_at: str = ""


class AcRadioDTO(ApiModel):
    radio_id: int
    status: str = ""
    mode: str = ""
    band: str = ""
    channel: str = ""
    bandwidth: str = ""
    usage: str = ""
    tx_power: str = ""
    clients: int = 0
    bssid: str = ""
    updated_at: str = ""


class AcConnectionRecordDTO(ApiModel):
    ip_address: str = ""
    state: str = ""
    connected_at: str = ""
    updated_at: str = ""


class AcLldpDTO(ApiModel):
    switch_device_uuid: str = ""
    switch_name: str = ""
    switch_ip: str = ""
    interface_name: str = ""
    lldp_neighbor: str = ""
    port_status: str = ""
    vlan: str = ""
    optical_module_status: str = ""
    raw_match_status: str = ""
    match_status: str = ""
    source: str = ""
    updated_at: str = ""


class AcApDTO(ApiModel):
    id: str
    ac_id: str
    ac_name: str = ""
    name: str
    ip: str = ""
    mac: str = ""
    status: str = "unknown"
    state_display: str = ""
    model: str = ""
    online_time: str = ""
    is_unauthenticated: bool = False
    radio1_status: str = ""
    radio2_status: str = ""
    radio1_channel: str = ""
    radio2_channel: str = ""
    radio1_power: str = ""
    radio2_power: str = ""
    station: str = ""
    station_source: str = "empty"
    section: str = ""
    mileage: str = ""
    direction: str = ""
    location_note: str = ""
    switch_name: str = ""
    switch_interface: str = ""
    lldp_status: str = ""
    optical_status: str = "no_data"
    optical_severity: str = "no_data"
    optical_data_freshness: str = "unknown"
    optical_is_current_anomaly: bool = False
    optical_rx_power: str = ""
    updated_at: str = ""


class AcApPageDTO(ApiModel):
    items: list[AcApDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class AcApHistoryPageDTO(ApiModel):
    kind: str
    ap_id: str
    items: list[dict[str, object | None]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class AcApDetailDTO(ApiModel):
    ap: AcApDTO
    radios: list[AcRadioDTO] = Field(default_factory=list)
    lldp: AcLldpDTO
    optical: AcOpticalDTO
    connection: AcConnectionRecordDTO = Field(default_factory=AcConnectionRecordDTO)


class AcConfigSnapshotDTO(ApiModel):
    id: int
    device_id: str
    ac_name: str = ""
    timestamp: str
    type: str
    status: str
    size_bytes: int = 0
    task_id: str = ""
    error_summary: str = ""
    path_id: str
    file_name: str = ""
    created_at: str = ""


class AcConfigSnapshotPageDTO(ApiModel):
    items: list[AcConfigSnapshotDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 30


class AcConfigContentDTO(ApiModel):
    snapshot: AcConfigSnapshotDTO
    content: str = ""
    offset: int = 0
    next_offset: int | None = None
    total_chars: int = 0
    truncated: bool = False


class AcConfigDiffDTO(ApiModel):
    from_snapshot_id: int
    to_snapshot_id: int
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    modified: list[dict[str, str]] = Field(default_factory=list)
    raw_diff: str = ""
    truncated: bool = False


class AcExtensionDTO(ApiModel):
    id: int
    ap_name: str = ""
    ap_mac_display: str = ""
    ap_mac_norm: str = ""
    station_name: str = ""
    section_name: str = ""
    section_start_station: str = ""
    section_end_station: str = ""
    line_side: str = ""
    direction: str = ""
    mileage_text: str = ""
    location_desc: str = ""
    remark: str = ""
    match_status: str = "unmatched"
    updated_at: str = ""


class AcExtensionPageDTO(ApiModel):
    items: list[AcExtensionDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class AcWebTaskDTO(ApiModel):
    task_id: str
    status: str = "PENDING"
    action: str
    artifact_id: str = ""
    available: bool = False
    progress: int = 0
    stage: str = ""
    current: int = 0
    total: int = 0
    sha256: str = ""
    size_bytes: int = 0
    message: str = ""
    error_message: str = ""
    result_summary: dict[str, object] = Field(default_factory=dict)


class AcActionPlanDTO(ApiModel):
    plan_id: str
    target_id: str
    action_id: str
    action_label: str
    plan_digest: str
    confirm_token: str
    expires_at: float
    status: str = "PREVIEW"
    command_summary: list[str] = Field(default_factory=list)
    task_id: str = ""


class AcActionConfirmRequestDTO(ApiModel):
    plan_digest: str
    confirm_token: str


class AcActionPlanCreateRequestDTO(ApiModel):
    target_id: str
    action_id: str


class AcExtensionPreviewDTO(ApiModel):
    preview_id: str
    file_name: str
    template_type: str = ""
    confidence_score: int = 0
    low_confidence: bool = False
    summary: dict[str, int] = Field(default_factory=dict)
    row_count: int = 0
    preview_digest: str


class AcExtensionApplyRequestDTO(ApiModel):
    preview_id: str
    preview_digest: str
    explicit_confirmation: bool = False


class AcExtensionApplyResultDTO(ApiModel):
    audit_id: str
    status: str
    preview_id: str
    total_rows: int = 0
    success_rows: int = 0
    updated_rows: int = 0
    skipped_rows: int = 0
    error_rows: int = 0


class AcExtensionRollbackRequestDTO(ApiModel):
    explicit_confirmation: bool = False


class AcExtensionRollbackResultDTO(ApiModel):
    audit_id: str
    status: str
    restored_rows: int = 0


class AcLocalRebuildRequestDTO(ApiModel):
    ac_id: str = Field(default="", max_length=100)


class AcRefreshRequestDTO(ApiModel):
    ac_id: str = Field(min_length=1, max_length=100)
    ap_id: str = Field(default="", max_length=100)


class AcFitApDeleteRequestDTO(ApiModel):
    ac_id: str = Field(min_length=1, max_length=100)
    ap_ids: list[str] = Field(min_length=1, max_length=2000)
    explicit_confirmation: bool = False


class AcFitApMetadataSaveRequestDTO(ApiModel):
    ac_id: str = Field(min_length=1, max_length=100)
    site_name: str = Field(default="", max_length=100)
    mileage: str = Field(default="", max_length=100)
    location_note: str = Field(default="", max_length=500)
    direction: str = Field(default="", max_length=30)


__all__ = [
    "AcApDTO",
    "AcApDetailDTO",
    "AcApHistoryPageDTO",
    "AcApPageDTO",
    "AcConfigContentDTO",
    "AcConfigDiffDTO",
    "AcConfigSnapshotDTO",
    "AcConfigSnapshotPageDTO",
    "AcConnectionRecordDTO",
    "AcLldpDTO",
    "AcManagementSummaryDTO",
    "AcOpticalDTO",
    "AcOverviewDTO",
    "AcRadioDTO",
    "AcActionConfirmRequestDTO",
    "AcActionPlanCreateRequestDTO",
    "AcActionPlanDTO",
    "AcExtensionApplyRequestDTO",
    "AcExtensionApplyResultDTO",
    "AcExtensionDTO",
    "AcExtensionPageDTO",
    "AcExtensionPreviewDTO",
    "AcExtensionRollbackRequestDTO",
    "AcExtensionRollbackResultDTO",
    "AcFitApDeleteRequestDTO",
    "AcFitApMetadataSaveRequestDTO",
    "AcLocalRebuildRequestDTO",
    "AcRefreshRequestDTO",
    "AcWebTaskDTO",
]
