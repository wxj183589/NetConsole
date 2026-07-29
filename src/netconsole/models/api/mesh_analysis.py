from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class MeshAnalysisWarningDTO(ApiModel):
    code: str
    message: str
    severity: str = "warning"


class MeshProfileDTO(ApiModel):
    mr_id: str
    display_name: str
    safe_folder_name: str
    linked_device_id: int | None = None
    linked_device_uuid: str | None = None
    source_file_count: int = 0
    sample_count: int = 0
    link_record_count: int = 0
    session_count: int = 0
    event_count: int = 0
    notes: str = ""


class MeshProfileCreateRequestDTO(ApiModel):
    display_name: str = Field(min_length=1, max_length=200)
    linked_mr_id: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=1000)


class MeshImportContextPrepareDTO(ApiModel):
    site_id: str
    vehicle_mr_count: int = 0
    profile_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class MeshBundleProfileCandidateDTO(ApiModel):
    profile_id: str
    display_name: str


class MeshBundleProfileImportStateDTO(ApiModel):
    profile_id: str
    profile_name: str = ""
    stored_filename: str = ""
    daily_sequence: int | None = None
    rename_status: str = ""
    rename_warning: str = ""
    duplicate_status: str = "new"
    import_allowed: bool = True
    existing_source_id: int | None = None
    existing_stored_filename: str = ""
    existing_session_id: str = ""
    existing_profile_id: str = ""
    existing_profile_name: str = ""


class MeshBundleMemberPreviewDTO(ApiModel):
    member_id: str
    original_name: str
    original_relative_path: str = ""
    safe_name: str
    size_bytes: int
    sha256: str
    raw_sha256: str
    content_sha256: str
    first_log_timestamp: str | None = None
    last_log_timestamp: str | None = None
    log_date: str | None = None
    stored_filename: str = ""
    daily_sequence: int | None = None
    rename_status: str = ""
    rename_warning: str = ""
    duplicate_status: str = "new"
    batch_duplicate_of: str = ""
    import_allowed: bool = True
    existing_source_id: int | None = None
    existing_stored_filename: str = ""
    existing_session_id: str = ""
    existing_profile_id: str = ""
    existing_profile_name: str = ""
    train_number: str = ""
    role: str = ""
    match_status: Literal["matched", "unmatched", "ambiguous"]
    selected_profile_id: str = ""
    selected_profile_name: str = ""
    profile_import_states: list[MeshBundleProfileImportStateDTO] = Field(default_factory=list)
    candidates: list[MeshBundleProfileCandidateDTO] = Field(default_factory=list)


class MeshBundlePreviewDTO(ApiModel):
    preview_id: str
    file_name: str
    archive_sha256: str
    archive_size_bytes: int
    member_count: int
    duplicate_archive: bool = False
    expires_at: str
    items: list[MeshBundleMemberPreviewDTO] = Field(default_factory=list)


class MeshBundleMappingDTO(ApiModel):
    member_id: str = Field(min_length=1, max_length=255)
    train_number: str = Field(min_length=1, max_length=20, pattern=r"^\d{1,3}$")
    role: Literal["CT", "CW"]
    profile_id: str = Field(min_length=1, max_length=200)


class MeshBundleImportRequestDTO(ApiModel):
    preview_id: str = Field(min_length=16, max_length=100)
    mappings: list[MeshBundleMappingDTO] = Field(min_length=1, max_length=200)
    explicit_confirmation: bool = False


class MeshRebuildRequestDTO(ApiModel):
    explicit_confirmation: bool = False


class MeshAnalysisParamsDTO(ApiModel):
    link_time_window: int = Field(default=4000, gt=0, le=600_000)
    link_switch_threshold: int = Field(default=10, ge=0, le=200)
    link_hold_rssi: int = Field(default=22, ge=0, le=200)
    link_establish_threshold: int = Field(default=4, ge=0, le=200)
    main_link_switch_time_ms: int = Field(gt=0, le=600_000)
    short_link_tolerance_ms: int = Field(ge=0, le=600_000)
    pingpong_tolerance_ms: int = Field(ge=0, le=600_000)
    pingpong_return_window_ms: int | None = Field(default=500, gt=0, le=3_600_000)
    merge_same_physical_ap_dual_radio: bool = True
    include_log_boundary_segments: bool = False
    sample_interval_ms: int | None = Field(default=None, gt=0, le=600_000)
    service_type: Literal["PIS", "CBTC", "信号", "其他"] = "PIS"
    wifi_type: Literal["WiFi5", "WiFi6", "其他"] = "WiFi6"


class MeshAnalysisParamsOverrideDTO(MeshAnalysisParamsDTO):
    pass


class MeshReportRequestDTO(ApiModel):
    analysis_params_override: MeshAnalysisParamsOverrideDTO | None = None


class MeshLinkDetailExportRequestDTO(ApiModel):
    source_file_id: int = Field(gt=0)
    analysis_params_override: MeshAnalysisParamsOverrideDTO | None = None


class MeshAnalysisParamsSaveRequestDTO(ApiModel):
    params: MeshAnalysisParamsDTO


class MeshArtifactDeleteRequestDTO(ApiModel):
    explicit_confirmation: bool = False


class MeshAnalysisSummaryDTO(ApiModel):
    site_id: str
    session_count: int = 0
    train_count: int = 0
    mr_count: int = 0
    link_record_count: int | None = 0
    active_link_count: int | None = 0
    standby_link_count: int | None = 0
    link_up_event_count: int | None = 0
    link_down_event_count: int | None = 0
    switch_event_count: int | None = 0
    short_link_count: int | None = 0
    pingpong_count: int | None = 0
    rssi_anomaly_count: int | None = 0
    channel_busy_anomaly_count: int | None = 0
    unmatched_ap_count: int | None = 0
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
    link_record_count: int | None = 0
    active_link_count: int | None = 0
    standby_link_count: int | None = 0
    event_count: int | None = 0
    data_integrity: str = "unknown"
    analysis_status: str = "unknown"
    parsed_status: str = "missing"
    parsed_message: str = ""
    schema_version: str | None = None
    available_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    warning_count: int = 0
    report_count: int = 0
    first_sample_time: str | None = None
    last_sample_time: str | None = None


class MeshAnalysisSessionPageDTO(ApiModel):
    items: list[MeshAnalysisSessionDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class MeshDataSourceDTO(ApiModel):
    source_file_id: int = Field(gt=0, description="索引库 source_files.id，用于分析查询和导出")
    source_action_id: str = Field(description="原始来源操作 ID，用于 tail 等受控来源操作")
    source_id: str = Field(default="", description="兼容别名，等同 source_action_id；新客户端不得用于导出")
    source_type: str
    name: str
    original_filename: str = ""
    stored_filename: str = ""
    raw_sha256: str = ""
    content_sha256: str = ""
    first_log_timestamp: str | None = None
    last_log_timestamp: str | None = None
    log_date: str | None = None
    daily_sequence: int | None = None
    rename_status: str = ""
    rename_warning: str = ""
    exists: bool = False
    size_bytes: int = 0
    modified_at: str | None = None
    compressed: bool = False
    tail_available: bool = False
    recoverable: bool = False
    recovery_source: str = ""
    missing_reason: str = ""
    rebuild_capability: Literal["ready", "recoverable_from_bundle", "raw_missing", "task_running", "unsupported"] = "raw_missing"
    package_name: str = ""
    package_sha256: str = ""
    bundle_member_id: str = ""


class MeshAnalysisSessionDetailDTO(ApiModel):
    session: MeshAnalysisSessionDTO
    analysis_params: MeshAnalysisParamsDTO
    available_radios: list[int] = Field(default_factory=list)
    warnings: list[MeshAnalysisWarningDTO] = Field(default_factory=list)
    sources: list[MeshDataSourceDTO] = Field(default_factory=list)


class MeshLinkDetailDTO(ApiModel):
    record_id: int
    timestamp: str
    timestamp_tag: str = ""
    sample_group_index: int | None = None
    train_name: str = ""
    mr_name: str
    mr_role: str = ""
    local_radio: int | None = None
    peer_mac: str | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    peer_radio_mac: str | None = None
    peer_radio: str | None = None
    link_role: str
    link_status: str
    rssi: float | None = None
    peer_rssi: float | None = None
    local_noise: float | None = None
    peer_noise: float | None = None
    local_signal: float | None = None
    peer_signal: float | None = None
    local_rssi_db: float | None = None
    peer_rssi_db: float | None = None
    local_noise_dbm: float | None = None
    peer_noise_dbm: float | None = None
    local_signal_dbm: float | None = None
    peer_signal_dbm: float | None = None
    local_rate_raw: float | None = None
    peer_rate_raw: float | None = None
    local_tx_busy: float | None = None
    peer_tx_busy: float | None = None
    local_rx_busy: float | None = None
    peer_rx_busy: float | None = None
    establish_time: str | None = None
    duration_text: str | None = None
    duration_seconds: float | None = None
    link_count: int | None = None
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
    source_line_number: int | None = None
    raw_line_start: int | None = None
    raw_line_end: int | None = None
    raw_offset_start: int | None = None
    raw_offset_end: int | None = None
    local_cpu_percent: float | None = None
    peer_cpu_percent: float | None = None
    local_mem_percent: float | None = None
    peer_mem_percent: float | None = None
    local_tx_des_free_cnt: int | None = None
    peer_tx_des_free_cnt: int | None = None
    local_tx: int | None = None
    peer_tx: int | None = None
    local_rx: int | None = None
    peer_rx: int | None = None
    local_retry: int | None = None
    peer_retry: int | None = None
    local_err: int | None = None
    peer_err: int | None = None
    local_tx_garp: int | None = None
    peer_rx_garp: int | None = None
    local_tx_mul_join: int | None = None
    peer_rx_mul_join: int | None = None
    match_method: str | None = None
    warning: str | None = None


class MeshLinkPageDTO(ApiModel):
    items: list[MeshLinkDetailDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class MeshActiveBuildOrderDTO(ApiModel):
    sequence: int
    source_file_id: int | None = None
    anchor_link_id: int | None = None
    local_radio: int | None = None
    active_peer_mac: str = ""
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    peer_radio: str | None = None
    peer_radio_mac: str | None = None
    station: str | None = None
    section: str | None = None
    mileage: str | None = None
    line_side: str | None = None
    build_start_time: str
    build_end_time: str
    main_link_duration_seconds: float | None = None
    reported_duration_seconds: float | None = None
    sample_count: int = 0
    avg_mr_rssi: float | None = None
    min_mr_rssi: float | None = None
    max_mr_rssi: float | None = None
    p10_mr_rssi: float | None = None
    avg_tx_busy: float | None = None
    avg_rx_busy: float | None = None
    avg_peer_tx_busy: float | None = None
    avg_peer_rx_busy: float | None = None
    link_time_window: int | None = None
    link_switch_threshold: int | None = None
    link_hold_rssi: int | None = None
    link_establish_threshold: int | None = None
    link_establish_rssi: int | None = None
    link_establishment_accepted: bool = False
    link_establishment_signal: float | None = None
    link_establishment_reason: str = ""
    main_link_switch_time_ms: int | None = None
    short_link_tolerance_ms: int | None = None
    pingpong_tolerance_ms: int | None = None
    pingpong_return_window_ms: int | None = None
    short_threshold_seconds: float | None = None
    min_normal_sample_count: int | None = None
    build_result: str
    judge_reason: str = ""
    is_same_physical_ap_radio_switch: bool = False
    physical_ap_key: str = ""
    is_ap_return_event: bool = False
    is_pingpong_abnormal: bool = False
    pingpong_type: str = ""
    pingpong_group_id: str = ""
    pingpong_return_duration_ms: int | None = None
    middle_ap_dwell_ms: int | None = None
    previous_ap: str = ""
    middle_ap: str = ""
    return_ap: str = ""
    pingpong_judgment_reason: str = ""
    source_file: str = ""


class MeshActiveBuildOrderPageDTO(ApiModel):
    items: list[MeshActiveBuildOrderDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100


class MeshChartBackupLinkDTO(ApiModel):
    link_id: int | None = None
    source_file_id: int | None = None
    timestamp: str
    timestamp_tag: str = ""
    local_radio: int | None = None
    peer_mac: str = ""
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    peer_radio: str | None = None
    peer_radio_mac: str | None = None
    station: str | None = None
    section: str | None = None
    local_rssi: float | None = None
    peer_rssi: float | None = None
    local_signal: float | None = None
    peer_signal: float | None = None
    local_tx_busy: float | None = None
    peer_tx_busy: float | None = None
    local_rx_busy: float | None = None
    peer_rx_busy: float | None = None


class MeshChartPointDTO(ApiModel):
    link_id: int | None = None
    source_file_id: int | None = None
    timestamp: str
    timestamp_tag: str = ""
    local_radio: int | None = None
    link_state: str = ""
    peer_mac: str = ""
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    peer_radio: str | None = None
    peer_radio_mac: str | None = None
    station: str | None = None
    section: str | None = None
    local_rssi: float | None = None
    peer_rssi: float | None = None
    local_signal: float | None = None
    peer_signal: float | None = None
    local_tx_busy: float | None = None
    peer_tx_busy: float | None = None
    local_rx_busy: float | None = None
    peer_rx_busy: float | None = None
    establish_time: str | None = None
    segment_sequence: int | None = None
    segment_start: str | None = None
    segment_end: str | None = None
    segment_duration_seconds: float | None = None
    is_switch: bool = False
    is_anomaly: bool = False
    gap_before: bool = False
    backups: list[MeshChartBackupLinkDTO] = Field(default_factory=list)


class MeshChartEventDTO(ApiModel):
    event_id: int
    timestamp: str
    event_type: str
    local_radio: int | None = None
    from_peer_mac: str | None = None
    to_peer_mac: str | None = None
    from_ap_name: str | None = None
    to_ap_name: str | None = None
    segment_sequence: int | None = None
    duration_ms: int | None = None
    point_timestamp: str | None = None
    point_rssi: float | None = None
    point_context: MeshChartPointDTO | None = None
    render_point_timestamp: str | None = None
    render_point_rssi: float | None = None
    render_aligned: bool = False
    render_busy_point_timestamp: str | None = None
    render_busy_point_index: int | None = None
    render_busy_tx_busy: float | None = None
    render_busy_rx_busy: float | None = None
    render_busy_aligned: bool = False
    busy_point_context: MeshChartPointDTO | None = None
    before_rssi: float | None = None
    after_rssi: float | None = None
    station: str | None = None
    section: str | None = None


class MeshChartLocationSegmentDTO(ApiModel):
    start_time: str
    end_time: str
    station: str | None = None
    section: str | None = None
    label: str
    direction: str | None = None
    mileage_start: str | None = None
    mileage_end: str | None = None


class MeshPathChartSummaryDTO(ApiModel):
    current_peer_mac: str | None = None
    current_peer_ap_name: str | None = None
    current_radio: int | None = None
    sample_count: int = 0
    active_count: int = 0
    standby_context_count: int = 0
    switch_count: int = 0
    earliest_sample_time: str | None = None
    latest_sample_time: str | None = None
    first_sample_time: str | None = None
    last_sample_time: str | None = None
    estimated_interval_seconds: float | None = None
    continuity_gap_seconds: float | None = None


class MeshPathChartDTO(ApiModel):
    mode: Literal["active_path", "peer_segment"]
    anchor: MeshChartPointDTO | None = None
    points: list[MeshChartPointDTO] = Field(default_factory=list)
    events: list[MeshChartEventDTO] = Field(default_factory=list)
    location_segments: list[MeshChartLocationSegmentDTO] = Field(default_factory=list)
    summary: MeshPathChartSummaryDTO = Field(default_factory=MeshPathChartSummaryDTO)
    total_points: int = 0
    returned_points: int = 0
    downsampled: bool = False
    requested_max_points: int = 0
    effective_max_points: int = 0
    downsample_warning: str | None = None
    time_from: str | None = None
    time_to: str | None = None
    requested_time_from: str | None = None
    requested_time_to: str | None = None
    effective_time_from: str | None = None
    effective_time_to: str | None = None
    first_sample_time: str | None = None
    last_sample_time: str | None = None
    total_points_in_range: int = 0


class MeshTracksideSignalPointDTO(ApiModel):
    timestamp: str
    timestamp_tag: str = ""
    source_file_id: int | None = None
    link_id: int | None = None
    sample_id: int | None = None
    local_radio: int | None = None
    role: Literal["ACTIVE", "STANDBY"]
    peer_mac: str | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    peer_radio: str | None = None
    peer_radio_mac: str | None = None
    station: str | None = None
    section: str | None = None
    peer_rssi: float | None = None
    local_rssi: float | None = None
    peer_signal: float | None = None
    local_signal: float | None = None
    run_id: str | None = None
    run_sequence: int | None = None
    segment_sequence: int | None = None
    segment_start: str | None = None
    segment_end: str | None = None
    segment_duration_seconds: float | None = None
    break_before: bool = False
    data_source: str = ""


class MeshTracksideSignalSeriesDTO(ApiModel):
    series_id: str
    peer_name: str | None = None
    peer_mac: str | None = None
    ap_mac: str | None = None
    peer_radio_mac: str | None = None
    radio: int | None = None
    station: str | None = None
    section: str | None = None
    roles_present: list[Literal["ACTIVE", "STANDBY"]] = Field(default_factory=list)
    data_source: str = "peer_rssi_db"
    total_points: int = 0
    returned_points: int = 0
    points: list[MeshTracksideSignalPointDTO] = Field(default_factory=list)


class MeshTracksideSignalRangeDTO(ApiModel):
    start: str | None = None
    end: str | None = None


class MeshTracksideSignalChartDTO(ApiModel):
    source_id: str
    radio: int | None = None
    time_range: MeshTracksideSignalRangeDTO = Field(default_factory=MeshTracksideSignalRangeDTO)
    series: list[MeshTracksideSignalSeriesDTO] = Field(default_factory=list)
    events: list[MeshChartEventDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    estimated_interval_seconds: float | None = None
    continuity_gap_seconds: float | None = None
    total_series: int = 0
    returned_series: int = 0
    total_frames: int = 0
    returned_frames: int = 0
    total_link_points: int = 0
    returned_link_points: int = 0
    total_link_runs: int = 0
    active_link_points: int = 0
    standby_link_points: int = 0
    returned_active_link_points: int = 0
    returned_standby_link_points: int = 0
    role_switch_count: int = 0
    skipped_missing_signal_points: int = 0
    skipped_missing_identity_points: int = 0
    total_points: int = 0
    returned_points: int = 0
    downsampled: bool = False
    requested_max_frames: int = 0
    effective_max_frames: int = 0
    requested_max_points: int = 0
    effective_max_points: int = 0
    top_n: int = 0
    included_roles: list[Literal["ACTIVE", "STANDBY"]] = Field(
        default_factory=lambda: ["ACTIVE", "STANDBY"]
    )
    include_standby: bool = True


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


class MeshRatePointDTO(ApiModel):
    timestamp: str
    local_radio: int | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    local_rate_raw: float | None = None
    peer_rate_raw: float | None = None


class MeshRatePageDTO(ApiModel):
    items: list[MeshRatePointDTO] = Field(default_factory=list)
    total: int = 0
    downsampled: bool = False


class MeshCounterDeltaPointDTO(ApiModel):
    timestamp: str
    local_radio: int | None = None
    peer_ap_name: str | None = None
    peer_ap_mac: str | None = None
    local_retry_delta: int | None = None
    peer_retry_delta: int | None = None
    local_error_delta: int | None = None
    peer_error_delta: int | None = None


class MeshCounterDeltaPageDTO(ApiModel):
    items: list[MeshCounterDeltaPointDTO] = Field(default_factory=list)
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
    deletable: bool = False


class MeshArtifactDeleteResultDTO(ApiModel):
    artifact_id: str
    name: str
    deleted_files: int = 0


class MeshRawTailDTO(ApiModel):
    source_action_id: str
    source_id: str = Field(default="", description="兼容别名，等同 source_action_id")
    available: bool = False
    lines: list[str] = Field(default_factory=list)
    message: str = ""


class MeshGenericRowsDTO(ApiModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


__all__ = [name for name in globals() if name.startswith("Mesh")]
