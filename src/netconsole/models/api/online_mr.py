from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.online_mr_application import OnlineMrExecutorKind, OnlineMrMappingState, OnlineMrPhase
from netconsole.models.task_state import TaskState


class OnlineMrMetricType(StrEnum):
    RSSI = "rssi"
    TRACKSIDE_RSSI = "trackside_rssi"
    CTL_BUSY = "ctl_busy"
    TX_BUSY = "tx_busy"
    RX_BUSY = "rx_busy"
    INTERFACE_IN_PPS = "interface_in_pps"
    INTERFACE_OUT_PPS = "interface_out_pps"
    PING_RTT = "ping_rtt"
    PING_LOSS = "ping_loss"
    IPERF_BITRATE = "iperf_bitrate"
    IPERF_LOSS = "iperf_loss"
    IPERF_JITTER = "iperf_jitter"
    IPERF_RETRANSMITS = "iperf_retransmits"
    MAIN_LINK = "main_link"
    RADIO_STATISTICS = "radio_statistics"


class OnlineMrDownsampleMode(StrEnum):
    NONE = "NONE"
    BUCKET_AVG = "BUCKET_AVG"
    MIN_MAX = "MIN_MAX"
    LATEST_PER_BUCKET = "LATEST_PER_BUCKET"


class OnlineMrSwitchRssiSource(StrEnum):
    HISTORY = "history"
    REALTIME = "realtime"


class OnlineMrBusinessTable(StrEnum):
    MAIN_LINK = "main_link"
    LINK_DETAIL = "link_detail"
    CHANNEL_BUSY = "channel_busy"
    SWITCH_HISTORY = "switch_history"
    SWITCH_REALTIME = "switch_realtime"
    INTERFACE_RATE = "interface_rate"
    FPING_1S = "fping_1s"
    IPERF = "iperf"
    DIAGNOSTICS = "diagnostics"
    # Deprecated API boundary aliases. Internal query semantics normalize these
    # to MAIN_LINK/LINK_DETAIL so mesh_link no longer means diagnostic segments.
    MESH_LINK = "mesh_link"
    MESH_DETAIL = "mesh_detail"


class OnlineMrDataIntegrity(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class OnlineMrParsedStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    LEGACY = "legacy"
    STALE = "stale"
    UNREADABLE = "unreadable"
    PARSING = "parsing"


class OnlineMrSessionSummaryDTO(ApiModel):
    session_id: str
    site_id: str
    mr_name: str = ""
    device_id: int | str | None = None
    device_name: str = ""
    status: str = ""
    phase: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    duration_seconds: float | None = None
    duration_minutes: float | None = None
    controller_task_id: str | None = None
    executor_kind: str | None = None
    agent_id: str | None = None
    has_raw_data: bool = False
    has_parsed_data: bool = False
    has_package: bool = False
    package_name: str | None = None
    package_reference: str | None = None
    force_stopped: bool | None = None
    finalization_complete: bool | None = None
    stop_reason: str | None = None
    task_status: str | None = None
    mapping_state: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class OnlineMrDatabaseSummaryDTO(ApiModel):
    status: OnlineMrParsedStatus = OnlineMrParsedStatus.MISSING
    available: bool = False
    compatible: bool | None = None
    size_bytes: int = 0
    modified_at: str | None = None
    schema_version: str | None = None
    parser_version: str | None = None
    tables: list[str] = Field(default_factory=list)
    row_counts: dict[str, int] = Field(default_factory=dict)
    available_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    missing_tables: list[str] = Field(default_factory=list)
    error_code: str | None = None
    message: str = ""
    recoverable: bool = True
    action: str | None = None


class OnlineMrSessionDetailDTO(OnlineMrSessionSummaryDTO):
    session_path_reference: str
    connection_summary: dict[str, Any] = Field(default_factory=dict)
    collection_config: dict[str, Any] = Field(default_factory=dict)
    enabled_collectors: list[str] = Field(default_factory=list)
    traffic_summary: dict[str, Any] = Field(default_factory=dict)
    file_summary: dict[str, Any] = Field(default_factory=dict)
    database_summary: OnlineMrDatabaseSummaryDTO
    notes_count: int = 0
    latest_metric_time: str | None = None
    data_integrity: OnlineMrDataIntegrity = OnlineMrDataIntegrity.UNKNOWN


class OnlineMrCollectorStatusDTO(ApiModel):
    name: str
    label: str
    status: str = "unknown"
    enabled: bool = True
    raw_file: str
    exists: bool = False
    size_bytes: int = 0
    error: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    updated_at: str | None = None
    health_status: str = "unknown"
    stale_seconds: float | None = None


class OnlineMrRealtimePreviewDTO(ApiModel):
    session_id: str
    available: bool = False
    updated_at: str | None = None
    message: str = "暂无实时链路数据"
    display_context: dict[str, Any] = Field(default_factory=dict)
    link: dict[str, Any] = Field(default_factory=dict)
    fping: dict[str, Any] = Field(default_factory=dict)
    iperf: dict[str, Any] = Field(default_factory=dict)


class OnlineMrRawFileDTO(ApiModel):
    name: str
    relative_name: str
    exists: bool = False
    size_bytes: int = 0
    modified_at: str | None = None


class OnlineMrRawTailDTO(ApiModel):
    success: bool = True
    name: str
    exists: bool = False
    lines: list[str] = Field(default_factory=list)
    message: str = ""
    size_bytes: int = 0
    modified_at: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class OnlineMrArtifactDTO(ApiModel):
    name: str
    kind: str
    relative_name: str
    size_bytes: int
    modified_at: str
    available: bool = True
    downloadable: bool = True
    is_fact_source: bool = False
    is_rebuildable: bool = False


class OnlineMrLogLineDTO(ApiModel):
    sequence: int
    timestamp: str | None = None
    source: str
    text: str
    level: str | None = None


class OnlineMrLogChunkDTO(ApiModel):
    source: str
    cursor: int
    next_cursor: int
    has_more: bool
    lines: list[OnlineMrLogLineDTO] = Field(default_factory=list)


class OnlineMrMetricPointDTO(ApiModel):
    timestamp: str | None = None
    raw_timestamp: str | None = None
    normalized_timestamp: str | None = None
    timestamp_source: str = "device"
    correction_ms: float | None = None
    correction_method: str = "none"
    correction_confidence: str = "high"
    value: float | None = None
    text_value: str | None = None
    dimensions: dict[str, Any] = Field(default_factory=dict)


class OnlineMrMetricSummaryDTO(ApiModel):
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None


class OnlineMrMetricSeriesDTO(ApiModel):
    metric_type: OnlineMrMetricType
    series_key: str
    unit: str = ""
    points: list[OnlineMrMetricPointDTO] = Field(default_factory=list)
    summary: OnlineMrMetricSummaryDTO = Field(default_factory=OnlineMrMetricSummaryDTO)


class OnlineMrMetricPageDTO(ApiModel):
    series: list[OnlineMrMetricSeriesDTO] = Field(default_factory=list)
    limit: int
    offset: int
    page_size_per_metric: int
    next_offset: int
    returned_points: int = 0
    has_more: bool = False


class OnlineMrSwitchRssiWindowDTO(ApiModel):
    event_id: str
    source: OnlineMrSwitchRssiSource
    event_time: str | None = None
    radio: int | None = None
    reason: str = ""
    old_peer_name: str = ""
    old_peer_mac: str = ""
    old_ap_mac: str = ""
    old_station: str = ""
    old_section: str = ""
    old_rssi_dbm: float | None = None
    new_peer_name: str = ""
    new_peer_mac: str = ""
    new_ap_mac: str = ""
    new_station: str = ""
    new_section: str = ""
    new_rssi_dbm: float | None = None


class OnlineMrSwitchRssiPageDTO(ApiModel):
    items: list[OnlineMrSwitchRssiWindowDTO] = Field(default_factory=list)
    limit: int
    offset: int
    has_more: bool = False


class OnlineMrTimeAlignmentDTO(ApiModel):
    base_time_source: str = "mr-device"
    anchor_count: int = 0
    inlier_count: int = 0
    offset_median_ms: float | None = None
    offset_p05_ms: float | None = None
    offset_p95_ms: float | None = None
    drift_ms_per_minute: float | None = None
    method: str = "none"
    confidence: str = "low"
    warning: str = ""
    fping_status: str = "collector-time"
    traffic_status: str = "collector-time"


class OnlineMrTrafficStatsDTO(ApiModel):
    record_count: int = 0
    duration_seconds: float | None = None
    average_mbps: float | None = None
    minimum_mbps: float | None = None
    maximum_mbps: float | None = None
    sent_bytes: float | None = None
    received_bytes: float | None = None
    lost_bytes: float | None = None
    sent_packets: int | None = None
    received_packets: int | None = None
    lost_packets: int | None = None
    loss_percent: float | None = None
    average_jitter_ms: float | None = None
    minimum_jitter_ms: float | None = None
    maximum_jitter_ms: float | None = None
    retransmits: int | None = None
    loss_source: str | None = None
    jitter_source: str | None = None
    retransmit_source: str | None = None


class OnlineMrTrafficDirectionDTO(OnlineMrTrafficStatsDTO):
    run_id: str = ""
    label: str = ""
    protocol: str = ""
    direction: str = ""
    status: str = ""
    server_ip: str = ""
    port: int | None = None
    parallel: int | None = None
    target_bandwidth: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


class OnlineMrTrafficOverviewDTO(ApiModel):
    protocol: str = ""
    direction: str = ""
    status: str = ""
    server_ip: str = ""
    port: int | None = None
    parallel: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    overall: OnlineMrTrafficStatsDTO = Field(default_factory=OnlineMrTrafficStatsDTO)
    directions: list[OnlineMrTrafficDirectionDTO] = Field(default_factory=list)
    data_quality_note: str = ""


class OnlineMrBusinessSummaryDTO(ApiModel):
    session_id: str
    sample_count: int = 0
    active_count: int = 0
    standby_count: int = 0
    active_segment_count: int = 0
    switch_count: int = 0
    fping_point_count: int = 0
    iperf_point_count: int = 0
    channel_busy_count: int = 0
    interface_pps_count: int = 0
    diagnosis_count: int = 0
    first_sample_time: str | None = None
    last_sample_time: str | None = None
    estimated_interval_seconds: float | None = None
    time_sync_status: str = "unknown"
    time_sync_avg_offset_ms: float | None = None
    time_alignment: OnlineMrTimeAlignmentDTO = Field(default_factory=OnlineMrTimeAlignmentDTO)
    traffic_overview: OnlineMrTrafficOverviewDTO = Field(default_factory=OnlineMrTrafficOverviewDTO)
    current_radio: int | None = None
    current_link_state: str = ""
    current_peer_mac: str = ""
    current_peer_name: str = ""
    current_ap_mac: str = ""
    current_peer_radio_mac: str = ""
    current_station: str = ""
    current_section: str = ""
    current_rssi: float | None = None
    current_segment_start: str | None = None
    current_segment_end: str | None = None
    current_segment_duration_seconds: float | None = None


class OnlineMrBusinessTablePageDTO(ApiModel):
    table: OnlineMrBusinessTable
    rows: list[dict[str, Any]] = Field(default_factory=list)
    limit: int
    offset: int
    returned_count: int = 0
    next_offset: int
    has_more: bool = False


class OnlineMrManualNoteDTO(ApiModel):
    event_id: str
    session_id: str
    local_time: str | None = None
    device_time: str | None = None
    source: str = "manual_note"
    event_type: str = "note"
    severity: str | None = None
    title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class OnlineMrTimelineEventDTO(OnlineMrManualNoteDTO):
    pass


class OnlineMrTaskSessionLinkDTO(ApiModel):
    controller_task_id: str | None = None
    session_id: str
    site_id: str
    device_id: int | str | None = None
    device_name: str = ""
    mapping_source: str = "unknown"
    mapping_confidence: float | None = None


class OnlineMrOperationSnapshotDTO(ApiModel):
    controller_task_id: str
    session_id: str | None = None
    site_id: str
    device_id: int | str | None = None
    device_name: str = ""
    mr_id: str = ""
    mr_name: str = ""
    executor_kind: OnlineMrExecutorKind
    agent_id: str = ""
    agent_profile_id: str = ""
    agent_task_id: str = ""
    remote_session_id: str = ""
    remote_package_id: str = ""
    last_remote_status: str = ""
    last_remote_seen_at: str | None = None
    consecutive_status_failures: int = 0
    deadline_at: str | None = None
    task_status: TaskState | None = None
    phase: OnlineMrPhase
    created_at: str
    started_at: str | None = None
    updated_at: str
    terminal_at: str | None = None
    ended_at: str | None = None
    duration_minutes: float | None = None
    stop_reason: str = ""
    force_stopped: bool = False
    error_summary: str = ""
    error_code: str = ""
    error_message: str = ""
    mapping_state: OnlineMrMappingState


__all__ = [name for name in globals() if name.startswith("OnlineMr")]
