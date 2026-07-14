from __future__ import annotations

from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel


class MeshAnalysisWarningDTO(ApiModel):
    code: str
    message: str
    severity: str = "warning"


class MeshAnalysisSummaryDTO(ApiModel):
    site_id: str
    session_count: int = 0
    train_count: int = 0
    mr_count: int = 0
    link_record_count: int = 0
    active_link_count: int = 0
    standby_link_count: int = 0
    link_up_event_count: int = 0
    link_down_event_count: int = 0
    switch_event_count: int = 0
    short_link_count: int = 0
    pingpong_count: int = 0
    rssi_anomaly_count: int = 0
    channel_busy_anomaly_count: int = 0
    unmatched_ap_count: int = 0
    warning_session_count: int = 0
    latest_analysis_time: str | None = None


class MeshAnalysisSessionDTO(ApiModel):
    session_id: str
    site_id: str
    analysis_time: str | None = None
    train_name: str = ""
    mr_name: str
    mr_role: str = ""
    source_type: str = "raw_mesh_log"
    original_filename: str
    raw_log_count: int = 1
    link_record_count: int = 0
    active_link_count: int = 0
    standby_link_count: int = 0
    event_count: int = 0
    data_integrity: str = "unknown"
    analysis_status: str = "unknown"
    warning_count: int = 0
    associated_online_mr_session_id: str | None = None
    task_id: str | None = None
    report_count: int = 0
    first_sample_time: str | None = None
    last_sample_time: str | None = None


class MeshAnalysisSessionPageDTO(ApiModel):
    items: list[MeshAnalysisSessionDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class MeshDataSourceDTO(ApiModel):
    source_id: str
    source_type: str
    name: str
    exists: bool = False
    size_bytes: int = 0
    modified_at: str | None = None
    compressed: bool = False
    tail_available: bool = False


class MeshAnalysisSessionDetailDTO(ApiModel):
    session: MeshAnalysisSessionDTO
    warnings: list[MeshAnalysisWarningDTO] = Field(default_factory=list)
    sources: list[MeshDataSourceDTO] = Field(default_factory=list)


class MeshLinkDetailDTO(ApiModel):
    record_id: int
    timestamp: str
    train_name: str = ""
    mr_name: str
    mr_role: str = ""
    local_radio: int | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    peer_radio: str | None = None
    link_role: str
    link_status: str
    rssi: float | None = None
    channel: str | None = None
    bandwidth: str | None = None
    station: str | None = None
    section: str | None = None
    mileage: str | None = None
    line_side: str | None = None
    event_type: str | None = None
    duration_ms: int | None = None
    source_file: str
    source_record_index: int | None = None
    match_method: str | None = None
    warning: str | None = None


class MeshLinkPageDTO(ApiModel):
    items: list[MeshLinkDetailDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class MeshLinkTimelineDTO(ApiModel):
    segment_id: int
    start_time: str
    end_time: str
    duration_seconds: float | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    local_radio: int | None = None
    rssi_min: float | None = None
    rssi_avg: float | None = None
    rssi_max: float | None = None
    station: str | None = None
    section: str | None = None
    mileage: str | None = None
    line_side: str | None = None
    event_type: str | None = None
    warning: str | None = None


class MeshTimelineDTO(ApiModel):
    items: list[MeshLinkTimelineDTO] = Field(default_factory=list)
    total: int = 0


class MeshSwitchEventDTO(ApiModel):
    event_id: int
    timestamp: str | None = None
    event_type: str
    mr_name: str
    local_radio: int | None = None
    from_peer_mac: str | None = None
    to_peer_mac: str | None = None
    from_ap_name: str | None = None
    to_ap_name: str | None = None
    before_rssi: float | None = None
    after_rssi: float | None = None
    duration_ms: int | None = None
    is_short_link: bool = False
    is_pingpong: bool = False
    station: str | None = None
    section: str | None = None
    warning: str | None = None


class MeshSwitchEventPageDTO(ApiModel):
    items: list[MeshSwitchEventDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class MeshRssiStatisticsDTO(ApiModel):
    min_rssi: float | None = None
    max_rssi: float | None = None
    avg_rssi: float | None = None
    latest_rssi: float | None = None
    sample_count: int = 0
    missing_sample_count: int = 0
    low_rssi_count: int = 0
    severe_low_rssi_count: int = 0


class MeshRssiPointDTO(ApiModel):
    timestamp: str
    value: float | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    local_radio: int | None = None


class MeshRssiDTO(ApiModel):
    statistics: MeshRssiStatisticsDTO
    points: list[MeshRssiPointDTO] = Field(default_factory=list)
    downsampled: bool = False
    total_points: int = 0


class MeshChannelBusyDTO(ApiModel):
    timestamp: str
    local_radio: int | None = None
    ctl_busy: float | None = None
    tx_busy: float | None = None
    rx_busy: float | None = None
    total_busy: float | None = None
    peer_ap_name: str | None = None
    station: str | None = None
    section: str | None = None
    source_type: str = "mesh_link_metrics"
    warning: str | None = None


class MeshChannelBusyPageDTO(ApiModel):
    items: list[MeshChannelBusyDTO] = Field(default_factory=list)
    total: int = 0
    downsampled: bool = False


class MeshAnomalyDTO(ApiModel):
    anomaly_id: str
    severity: str
    anomaly_type: str
    start_time: str | None = None
    end_time: str | None = None
    train_name: str = ""
    mr_name: str
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    station: str | None = None
    section: str | None = None
    description: str
    evidence_reference: str | None = None
    rule_version: str | None = None


class MeshAnomalyPageDTO(ApiModel):
    items: list[MeshAnomalyDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class MeshApStatisticsDTO(ApiModel):
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    station: str | None = None
    section: str | None = None
    mileage: str | None = None
    line_side: str | None = None
    linked_mr_count: int = 1
    link_up_count: int = 0
    link_down_count: int = 0
    switch_in_count: int = 0
    switch_out_count: int = 0
    avg_rssi: float | None = None
    min_rssi: float | None = None
    anomaly_count: int = 0
    match_status: str = "unresolved"


class MeshApStatisticsPageDTO(ApiModel):
    items: list[MeshApStatisticsDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class MeshReportArtifactDTO(ApiModel):
    artifact_id: str
    artifact_type: str
    name: str
    size_bytes: int
    modified_at: str | None = None
    status: str = "available"
    source: str = "existing_file"
    downloadable: bool = True


class MeshAlignmentPointDTO(ApiModel):
    timestamp: str
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    rssi: float | None = None
    fping_rtt_ms: float | None = None
    fping_loss_percent: float | None = None
    iperf_mbps: float | None = None
    switch_event: str | None = None
    station: str | None = None
    section: str | None = None


class MeshAlignmentDTO(ApiModel):
    associated_online_mr_session_id: str | None = None
    transient: bool = False
    items: list[MeshAlignmentPointDTO] = Field(default_factory=list)
    message: str = ""


class MeshRawTailDTO(ApiModel):
    source_id: str
    available: bool = False
    lines: list[str] = Field(default_factory=list)
    message: str = ""


class MeshGenericRowsDTO(ApiModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


__all__ = [name for name in globals() if name.startswith("Mesh")]
