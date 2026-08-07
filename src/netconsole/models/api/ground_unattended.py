from __future__ import annotations

import ipaddress
from typing import Literal

from pydantic import Field, model_validator

from netconsole.models.api.common import ApiModel


GroundRunState = Literal[
    "DISABLED",
    "WAITING_WINDOW",
    "STARTING",
    "RUNNING",
    "PAUSED",
    "STOPPING",
    "FINALIZING",
    "ARCHIVING",
    "COMPLETED",
    "ERROR",
]
GroundEligibilityStatus = Literal[
    "MAINLINE",
    "MAINLINE_STATIONARY",
    "DEPOT",
    "PARKING_LOT",
    "STORAGE_TRACK",
    "NON_MAIN_PATH",
    "DEPOT_CONNECTION",
    "AC_STALE",
    "AC_UNKNOWN",
    "LOCATION_UNDETERMINED",
    "AP_UNMATCHED",
    "OFFLINE",
]
GroundLocationClass = Literal[
    "MAINLINE",
    "DEPOT",
    "PARKING_YARD",
    "STABLING",
    "DEPOT_CONNECTION",
    "TEST_TRACK",
    "NON_MAINLINE",
    "OFFLINE",
    "UNKNOWN",
]
GroundCoverageStatus = Literal[
    "NOT_SEEN",
    "WAITING",
    "COLLECTING",
    "PARTIAL",
    "COVERED",
    "EXCLUDED",
    "OFFLINE",
    "FAILED",
]
GroundDataAvailability = Literal[
    "ACTIVE_RAW",
    "ARCHIVED_RAW",
    "MIXED",
    "SUMMARY_ONLY",
    "MISSING",
    "CORRUPT",
]
GroundSyslogReturnAddressStatus = Literal[
    "LOCAL_ADDRESS",
    "EXTERNAL_CONFIRMED",
    "NOT_LOCAL",
    "EMPTY",
    "INVALID",
]
GroundSyslogReceiverState = Literal["LISTENING", "STOPPED", "STARTING", "ERROR"]
GroundSyslogPortState = Literal[
    "NETCONSOLE_LISTENING",
    "AVAILABLE",
    "OCCUPIED_BY_OTHER",
    "ADDRESS_NOT_LOCAL",
    "NOT_CHECKED",
    "UNKNOWN",
]


class GroundUnattendedProfileDTO(ApiModel):
    site_id: str
    enabled: bool = False
    schedule_start_time: str = Field(
        default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    schedule_end_time: str = Field(
        default="23:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    ac_poll_interval_seconds: int = Field(default=10, ge=3, le=300)
    stationary_exclusion_minutes: int = Field(default=10, ge=1, le=180)
    ac_stale_grace_seconds: int = Field(default=120, ge=0, le=3600)
    ac_ping_correlation_tolerance_seconds: int = Field(default=15, ge=1, le=300)
    ap_switch_before_seconds: int = Field(default=5, ge=0, le=60)
    ap_switch_after_seconds: int = Field(default=5, ge=0, le=60)
    max_active_trains: int = Field(default=2, ge=1, le=8)
    max_active_mrs: int = Field(default=4, ge=1, le=16)
    max_starting_mrs: int = Field(default=2, ge=1, le=8)
    max_finalizing_mrs: int = Field(default=2, ge=1, le=8)
    deep_collection_master_enabled: bool = True
    fleet_ping_interval_ms: int = Field(default=1000, ge=100, le=60_000)
    fleet_ping_timeout_ms: int = Field(default=4000, ge=100, le=60_000)
    fleet_ping_packet_size: int = Field(default=64, ge=1, le=65_507)
    fleet_ping_shard_size: int = Field(default=12, ge=2, le=32)
    fleet_ping_warmup_seconds: int = Field(default=10, ge=0, le=300)
    ping_depot_trains_enabled: bool = False
    udp_listen_host: str = Field(default="0.0.0.0", min_length=1, max_length=255)
    udp_listen_port: int = Field(default=514, ge=1, le=65_535)
    udp_queue_capacity: int = Field(default=20_000, ge=100, le=500_000)
    raw_flush_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    raw_flush_record_count: int = Field(default=100, ge=1, le=10_000)
    event_batch_size: int = Field(default=100, ge=1, le=5_000)
    event_batch_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    boot_time_tolerance_seconds: int = Field(default=120, ge=10, le=900)
    config_check_cooldown_seconds: int = Field(default=1800, ge=30, le=86_400)
    syslog_server_ip: str = Field(default="", max_length=255)
    syslog_server_port: int = Field(default=514, ge=1, le=65_535)
    syslog_auto_repair_enabled: bool = True
    allow_external_syslog_address: bool = False
    ping_raw_retention_days: int = Field(default=30, ge=1, le=3650)
    syslog_raw_retention_days: int = Field(default=30, ge=1, le=3650)
    minimum_valid_collection_minutes: int = Field(default=10, ge=1, le=720)
    preferred_collection_minutes: int = Field(default=20, ge=1, le=720)
    maximum_collection_minutes: int = Field(default=30, ge=1, le=1440)
    start_jitter_seconds: int = Field(default=3, ge=0, le=60)
    start_batch_size: int = Field(default=1, ge=1, le=4)
    detail_retention_days: int = Field(default=30, ge=1, le=3650)
    summary_retention_days: int = Field(default=180, ge=1, le=3650)
    storage_warning_free_gb: float = Field(default=5.0, ge=0.1, le=1024)
    storage_critical_free_gb: float = Field(default=1.0, ge=0.1, le=1024)
    created_at: str = ""
    updated_at: str = ""

    @model_validator(mode="after")
    def validate_limits(self) -> "GroundUnattendedProfileDTO":
        try:
            if ipaddress.ip_address(self.udp_listen_host).version != 4:
                raise ValueError
        except ValueError:
            raise ValueError("UDP 监听地址必须是 IPv4 地址") from None
        if self.syslog_server_ip:
            try:
                address = ipaddress.ip_address(self.syslog_server_ip)
                if address.version != 4:
                    raise ValueError
            except ValueError:
                raise ValueError("MR 日志回传地址必须是 IPv4 地址") from None
            if (
                address.is_unspecified
                or address.is_loopback
                or address.is_multicast
                or str(address) == "255.255.255.255"
            ):
                raise ValueError("MR 日志回传地址必须是具体的单播 IPv4 地址")
        if self.schedule_start_time == self.schedule_end_time:
            raise ValueError("开始时间和结束时间不能相同")
        if not (
            self.minimum_valid_collection_minutes
            <= self.preferred_collection_minutes
            <= self.maximum_collection_minutes
        ):
            raise ValueError("深度采集时长必须满足最低时长 <= 建议时长 <= 最大时长")
        if self.max_active_mrs < self.max_active_trains:
            raise ValueError("最大活动 MR 数不能小于最大活动列车数")
        if self.max_starting_mrs > self.max_active_mrs:
            raise ValueError("最大启动中 MR 数不能大于最大活动 MR 数")
        if self.max_finalizing_mrs > self.max_active_mrs:
            raise ValueError("最大最终化 MR 数不能大于最大活动 MR 数")
        if self.storage_critical_free_gb >= self.storage_warning_free_gb:
            raise ValueError("严重空间阈值必须小于空间预警阈值")
        if self.summary_retention_days < self.detail_retention_days:
            raise ValueError("汇总保留天数不能小于详细数据保留天数")
        return self


class GroundUnattendedProfileUpdateDTO(GroundUnattendedProfileDTO):
    created_at: str = Field(default="", exclude=True)
    updated_at: str = Field(default="", exclude=True)
    external_syslog_address_confirmation: bool = Field(default=False, exclude=True)


class GroundUnattendedStatusDTO(ApiModel):
    site_id: str
    enabled: bool = False
    state: GroundRunState = "DISABLED"
    service_state: GroundRunState = "DISABLED"
    paused: bool = False
    run_id: str = ""
    run_date: str = ""
    actual_started_at: str = ""
    actual_ended_at: str = ""
    schedule_start_time: str = "07:00"
    schedule_end_time: str = "23:00"
    timezone: str = "Asia/Shanghai"
    running_mode: Literal["STANDARD", "LIGHTWEIGHT"] = "STANDARD"
    next_start_at: str = ""
    next_end_at: str = ""
    profile_effective_at: str = "下一次调度周期"
    ac_last_updated_at: str = ""
    ac_freshness_status: str = "NO_DATA"
    mainline_train_count: int = 0
    mainline_ping_target_count: int = 0
    depot_ping_target_count: int = 0
    ping_target_count: int = 0
    active_deep_train_count: int = 0
    covered_train_count: int = 0
    incomplete_train_count: int = 0
    inventory_train_count: int = 0
    syslog_active_mr_count: int = 0
    config_abnormal_count: int = 0
    data_quality_warning_count: int = 0
    radio_down_mr_count: int = 0
    radio_bounce_today_count: int = 0
    snmp_radio_control_today_count: int = 0
    snmp_unrecovered_count: int = 0
    radio_flapping_mr_count: int = 0
    last_snmp_radio_control_at: str = ""
    disk_used_bytes: int = 0
    disk_free_bytes: int = 0
    disk_status: str = "UNKNOWN"
    latest_archive_status: str = ""
    latest_archive_message: str = ""
    active_run_id: str = ""
    active_run_state: str = ""
    active_run_date: str = ""
    active_run_started_at: str = ""
    latest_run_id: str = ""
    latest_run_state: str = ""
    latest_run_date: str = ""
    latest_run_started_at: str = ""
    latest_run_ended_at: str = ""
    active_operation_id: str = ""
    active_operation_state: str = ""
    latest_operation_id: str = ""
    latest_operation_state: str = ""
    message: str = ""
    updated_at: str = ""


class GroundRunDTO(ApiModel):
    run_id: str
    site_id: str
    run_date: str
    state: GroundRunState
    paused: bool = False
    scheduled_start_at: str = ""
    scheduled_end_at: str = ""
    actual_started_at: str = ""
    actual_ended_at: str = ""
    ping_sample_count: int = 0
    archive_id: str = ""
    archive_status: str = ""
    data_availability: GroundDataAvailability = "MISSING"
    message: str = ""
    created_at: str = ""
    updated_at: str = ""


class GroundRunPageDTO(ApiModel):
    items: list[GroundRunDTO] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0


class GroundRunDeleteRequestDTO(ApiModel):
    explicit_confirmation: bool = False


class GroundSyslogHostDTO(ApiModel):
    ip: str
    port: int = Field(ge=1, le=65_535)
    facility: str = ""
    is_managed_target: bool = False
    same_ip_different_port: bool = False
    source: Literal["DEVICE_EXISTING", "NETCONSOLE_MANAGED"] = "DEVICE_EXISTING"


class GroundUnattendedEndpointDTO(ApiModel):
    endpoint: Literal["CT", "CW"]
    mr_id: str = ""
    mr_name: str = ""
    device_id: int | None = None
    management_ip: str = ""
    online_status: str = "UNKNOWN"
    ping_target_eligible: bool = False
    ping_exclusion_reason: str = ""
    ping_active: bool = False
    ping_sent_count: int = 0
    ping_success_count: int = 0
    ping_loss_rate_percent: float | None = None
    ping_avg_rtt_ms: float | None = None
    active_operation_id: str = ""
    latest_session_id: str = ""
    syslog_status: str = "WAITING"
    last_syslog_received_at: str = ""
    current_active_peer: str = ""
    last_link_switch_at: str = ""
    boot_session_id: str = ""
    estimated_boot_time: str = ""
    uptime_seconds: int | None = None
    boot_time_uncertainty_seconds: int = 0
    reboot_reason: str = ""
    timezone_name: str = ""
    utc_offset_seconds: int | None = None
    device_time_quality: str = ""
    config_status: str = "NOT_CHECKED"
    config_checked_at: str = ""
    managed_target_ip: str = ""
    managed_target_port: int | None = None
    managed_target_statuses: list[str] = Field(default_factory=list)
    configured_log_hosts: list[GroundSyslogHostDTO] = Field(default_factory=list)
    managed_profile_version: int = 2
    radio_interfaces: list[dict[str, object]] = Field(default_factory=list)
    radio_overall_state: Literal["UP", "DOWN", "FLAPPING", "UNKNOWN"] = "UNKNOWN"
    snmp_radio_control_state: Literal[
        "NONE",
        "RECENT_CHANGE",
        "RADIO_DOWN",
        "RADIO_RECOVERED",
        "FREQUENT_SWITCHING",
    ] = "NONE"
    last_radio_event_at: str = ""
    last_cfg_event_at: str = ""
    cfg_command_source: str = ""
    cfg_event_index: str = ""
    correlation_confidence: Literal["HIGH", "MEDIUM", "UNCONFIRMED"] = (
        "UNCONFIRMED"
    )


class GroundApIdentityDiagnosticsDTO(ApiModel):
    """Current-AP identity evidence retained with the live train state."""

    train_id: str = ""
    mr_id: str = ""
    site_id: str = ""
    line_id: str = ""
    raw_current_ap: str = ""
    canonical_current_ap: str = ""
    identity_revision: int = 0
    identity_generated_at: str = ""
    candidate_count: int = 0
    matched_by: str = "none"
    ap_identity_status: str = "NOT_FOUND"
    station_match_status: str = "UNMATCHED"
    ap_identity_match_status: str = "NOT_FOUND"
    resolved_ap_id: str = ""
    resolved_ap_name: str = ""
    resolved_ap_physical_mac: str = ""
    resolved_station_id: str = ""
    resolved_station_name: str = ""
    resolved_section_id: str = ""
    resolved_section_name: str = ""
    position_type: str = "UNKNOWN"
    mainline_eligible: bool = False
    mainline_exclusion_code: str = ""
    mainline_exclusion_reason: str = ""
    ping_eligible: bool = False
    ping_exclusion_code: str = ""
    ping_exclusion_reason: str = ""
    result_code: str = ""


class GroundUnattendedTrainDTO(ApiModel):
    train_id: str
    train_no: str = ""
    train_name: str = ""
    location_class: GroundLocationClass = "UNKNOWN"
    mainline_eligible: bool = False
    ping_eligible: bool = False
    deep_collection_eligible: bool = False
    ping_inclusion_reason: str = ""
    ping_exclusion_reason: str = ""
    deep_exclusion_reason: str = ""
    eligibility_status: GroundEligibilityStatus = "AC_UNKNOWN"
    exclusion_reason: str = ""
    location_match_level: Literal[
        "AP_EXACT",
        "AP_REGISTRY",
        "AP_ALIAS",
        "STATION_EXACT",
        "STATION_ALIAS",
        "UNMATCHED",
    ] = "UNMATCHED"
    location_match_reason: str = ""
    resolved_ap_id: str = ""
    resolved_ap_name: str = ""
    raw_peer_ap_name: str = ""
    raw_peer_ap_mac: str = ""
    canonical_station_name: str = ""
    current_ap_name: str = ""
    current_ap_mac: str = ""
    station: str = ""
    section: str = ""
    mileage: str = ""
    rssi: int | None = None
    same_ap_duration_seconds: int = 0
    ac_snapshot_id: int | None = None
    ac_received_at: str = ""
    coverage_status: GroundCoverageStatus = "NOT_SEEN"
    priority: bool = False
    enabled: bool = True
    scheduling_priority: int = 0
    deep_collection_enabled: bool = True
    monitor_only: bool = False
    remark: str = ""
    inventory_status: str = "ACTIVE"
    attempt_count: int = 0
    covered_rounds: int = 0
    selection_reason: str = ""
    failure_reason: str = ""
    endpoints: list[GroundUnattendedEndpointDTO] = Field(default_factory=list)
    ap_identity_diagnostics: GroundApIdentityDiagnosticsDTO = Field(
        default_factory=GroundApIdentityDiagnosticsDTO
    )
    updated_at: str = ""


class GroundUnattendedTrainPageDTO(ApiModel):
    items: list[GroundUnattendedTrainDTO] = Field(default_factory=list)
    total: int = 0


class GroundPriorityUpdateDTO(ApiModel):
    priority: bool


class GroundTrainPolicyUpdateDTO(ApiModel):
    enabled: bool = True
    priority: bool = False
    scheduling_priority: int = Field(default=0, ge=-100, le=100)
    deep_collection_enabled: bool = True
    monitor_only: bool = False
    remark: str = Field(default="", max_length=1000)


class GroundConfigCheckRequestDTO(ApiModel):
    device_uuid: str = Field(default="", max_length=100)
    mode: Literal["VERIFY_ONLY", "AUTO_REPAIR"] = "AUTO_REPAIR"
    allow_target_port_change: bool = False
    explicit_confirmation: bool = False


class GroundMrRuntimeStatusDTO(ApiModel):
    device_uuid: str
    train_id: str = ""
    mr_role: str = ""
    mr_name: str = ""
    radio_interfaces: list[dict[str, object]] = Field(default_factory=list)
    radio_overall_state: Literal["UP", "DOWN", "FLAPPING", "UNKNOWN"] = "UNKNOWN"
    snmp_radio_control_state: Literal[
        "NONE",
        "RECENT_CHANGE",
        "RADIO_DOWN",
        "RADIO_RECOVERED",
        "FREQUENT_SWITCHING",
    ] = "NONE"
    last_radio_event_at: str = ""
    last_cfg_event_at: str = ""
    cfg_command_source: str = ""
    cfg_event_index: str = ""
    config_source: str = ""
    config_destination: str = ""
    correlation_confidence: Literal["HIGH", "MEDIUM", "UNCONFIRMED"] = (
        "UNCONFIRMED"
    )
    managed_config_status: str = "NOT_CHECKED"
    managed_config_checked_at: str = ""
    managed_profile_version: int = 2


class GroundMrRuntimeStatusPageDTO(ApiModel):
    items: list[GroundMrRuntimeStatusDTO] = Field(default_factory=list)
    total: int = 0


class GroundInventorySummaryDTO(ApiModel):
    site_id: str
    discovered_train_count: int = 0
    complete_train_count: int = 0
    ct_only_count: int = 0
    cw_only_count: int = 0
    missing_management_ip_count: int = 0
    missing_credential_count: int = 0
    added_endpoint_count: int = 0
    updated_endpoint_count: int = 0
    removed_endpoint_count: int = 0
    removed_train_count: int = 0
    synchronized_at: str = ""


class GroundAcPollerHealthDTO(ApiModel):
    controller_id: str
    controller_name: str = ""
    task_id: str = ""
    run_id: str = ""
    status: str = "UNKNOWN"
    connection_state: str = "UNKNOWN"
    last_success_at: str = ""
    latest_snapshot_id: int | None = None
    next_poll_at: str = ""
    poll_interval_seconds: float = 0.0
    poll_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    reconnect_count: int = 0
    consecutive_failures: int = 0
    heartbeat_at: str = ""
    heartbeat_age_seconds: float | None = None
    last_error: str = ""


class GroundHealthDTO(ApiModel):
    site_id: str
    status: str = "UNKNOWN"
    udp_running: bool = False
    udp_listen_address: str = ""
    udp_receive_rate_per_second: float = 0.0
    udp_received_count: int = 0
    udp_unidentified_count: int = 0
    udp_identity_conflict_count: int = 0
    udp_last_received_at: str = ""
    udp_queue_length: int = 0
    udp_queue_capacity: int = 0
    udp_dropped_count: int = 0
    raw_records_written: int = 0
    raw_bytes_written: int = 0
    raw_last_write_duration_ms: float = 0.0
    database_pending_count: int = 0
    database_last_batch_duration_ms: float = 0.0
    open_file_count: int = 0
    ping_target_count: int = 0
    ping_process_count: int = 0
    deep_queue_length: int = 0
    archive_pending_count: int = 0
    ac_pollers: list[GroundAcPollerHealthDTO] = Field(default_factory=list)
    disk_free_bytes: int = 0
    last_error: str = ""
    updated_at: str = ""


class GroundSyslogTransportStatusDTO(ApiModel):
    configured_return_ip: str = ""
    configured_return_port: int = Field(default=514, ge=1, le=65_535)
    return_address_status: GroundSyslogReturnAddressStatus = "EMPTY"
    return_address_is_local: bool = False
    allow_external_address: bool = False
    listen_host: str = "0.0.0.0"
    listen_port: int = Field(default=514, ge=1, le=65_535)
    receiver_running: bool = False
    receiver_state: GroundSyslogReceiverState = "STOPPED"
    actual_listen_address: str = ""
    port_state: GroundSyslogPortState = "NOT_CHECKED"
    port_message: str = ""
    ports_match: bool | None = None
    target_port_message: str = ""
    last_received_at: str = ""
    received_count: int = 0
    active_mr_count: int = 0
    unidentified_count: int = 0
    identity_conflict_count: int = 0
    queue_length: int = 0
    queue_capacity: int = 0
    dropped_count: int = 0
    recommended_local_ip: str = ""
    recommended_adapter_name: str = ""
    checked_at: str = ""


class GroundRawFileDTO(ApiModel):
    file_id: str
    site_id: str
    run_id: str = ""
    train_id: str = ""
    device_id: int | None = None
    mr_role: str = ""
    data_type: str
    relative_path: str
    start_time: str = ""
    end_time: str = ""
    record_count: int = 0
    size_bytes: int = 0
    sha256: str = ""
    status: str = "OPEN"
    archive_status: str = "PENDING"
    parse_status: str = "PENDING"
    compressed_path: str = ""
    created_at: str = ""
    updated_at: str = ""


class GroundRawFilePageDTO(ApiModel):
    items: list[GroundRawFileDTO] = Field(default_factory=list)
    total: int = 0


class GroundPingTargetDTO(ApiModel):
    run_id: str = ""
    run_date: str = ""
    target_ip: str
    train_id: str = ""
    train_no: str = ""
    mr_id: str = ""
    mr_name: str = ""
    mr_position_code: str = ""
    location_class: GroundLocationClass = "UNKNOWN"
    ping_inclusion_reason: str = ""
    mainline_eligible: bool = False
    deep_collection_eligible: bool = False
    started_at: str = ""
    updated_at: str = ""
    shard_id: str = ""
    raw_sample_count: int = 0
    effective_sample_count: int = 0
    warmup_ignored_count: int = 0
    sent_count: int = 0
    success_count: int = 0
    loss_count: int = 0
    loss_rate_percent: float = 0.0
    min_rtt_ms: float | None = None
    avg_rtt_ms: float | None = None
    max_rtt_ms: float | None = None
    continuous_loss_max_count: int = 0
    continuous_loss_max_seconds: float = 0.0
    current_ap_name: str = ""
    station: str = ""
    section: str = ""
    first_sample_at: str = ""
    last_sample_at: str = ""
    active_raw_file_count: int = 0
    archived_raw_file_count: int = 0
    raw_file_count: int = 0
    raw_record_count: int = 0
    raw_file_ids: list[str] = Field(default_factory=list)
    raw_file_available: bool = False
    archive_available: bool = False
    archive_id: str = ""
    data_source: Literal["ACTIVE", "ARCHIVE", "MIXED", "NONE"] = "NONE"
    source_kind: Literal["ACTIVE", "ARCHIVE", "MIXED", "NONE"] = "NONE"
    data_availability: GroundDataAvailability = "MISSING"
    availability_reason: str = ""
    query_identity: str = ""


class GroundPingSummaryPageDTO(ApiModel):
    items: list[GroundPingTargetDTO] = Field(default_factory=list)
    total: int = 0


class GroundDeepCollectionDTO(ApiModel):
    train_id: str
    train_no: str = ""
    status: GroundCoverageStatus = "NOT_SEEN"
    queue_position: int | None = None
    scheduling_priority: int = 0
    selection_reason: str = ""
    started_at: str = ""
    valid_duration_minutes: float = 0.0
    ct_operation_id: str = ""
    cw_operation_id: str = ""
    ct_session_id: str = ""
    cw_session_id: str = ""
    attempt_count: int = 0
    covered_rounds: int = 0
    failure_reason: str = ""
    updated_at: str = ""


class GroundDeepCollectionPageDTO(ApiModel):
    items: list[GroundDeepCollectionDTO] = Field(default_factory=list)
    total: int = 0


class GroundTimelineEventDTO(ApiModel):
    event_id: int | str
    ts: str
    event_type: str
    severity: str = "info"
    train_id: str = ""
    train_no: str = ""
    train_name: str = ""
    mr_id: str = ""
    mr_name: str = ""
    mr_position_code: str = ""
    title: str = ""
    message: str = ""
    peer_ap_id: str = ""
    peer_ap_name: str = ""
    peer_ap_mac: str = ""
    peer_radio_mac: str = ""
    previous_peer_ap_id: str = ""
    previous_peer_ap_name: str = ""
    previous_peer_ap_mac: str = ""
    previous_peer_radio_mac: str = ""
    station: str = ""
    section: str = ""
    previous_station: str = ""
    previous_section: str = ""
    rssi: int | None = None
    previous_rssi: int | None = None
    reason_code: str = ""
    reason_label: str = ""
    resolution_status: str = ""
    ap_display: str = ""
    ap_transition_display: str = ""
    resolved_ap_name: str = ""
    previous_resolved_ap_name: str = ""
    details: dict[str, object] = Field(default_factory=dict)


class GroundTimelinePageDTO(ApiModel):
    items: list[GroundTimelineEventDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100
    total_exact: bool = True


class GroundArchiveDTO(ApiModel):
    archive_id: str
    site_id: str
    run_id: str
    run_date: str
    actual_started_at: str = ""
    actual_ended_at: str = ""
    mainline_train_count: int = 0
    ping_target_count: int = 0
    ping_sample_count: int = 0
    covered_train_count: int = 0
    complete_session_count: int = 0
    partial_session_count: int = 0
    archive_size_bytes: int = 0
    sha256: str = ""
    manifest_sha256: str = ""
    archive_status: str = ""
    file_count: int = 0
    integrity_status: str = "NOT_CHECKED"
    retention_until: str = ""
    summary: dict[str, object] = Field(default_factory=dict)
    message: str = ""
    created_at: str = ""
    updated_at: str = ""


class GroundArchivePageDTO(ApiModel):
    items: list[GroundArchiveDTO] = Field(default_factory=list)
    total: int = 0


class GroundArchiveFileDTO(ApiModel):
    path: str
    data_type: str = ""
    train_id: str = ""
    mr_id: str = ""
    mr_role: str = ""
    hour: str = ""
    record_count: int = 0
    size_bytes: int = 0
    compressed_size_bytes: int = 0
    sha256: str = ""
    parse_status: str = ""


class GroundArchiveValidationDTO(ApiModel):
    status: Literal["READY", "FAILED", "NOT_CHECKED"] = "NOT_CHECKED"
    checked_at: str = ""
    archive_size_bytes: int = 0
    archive_sha256: str = ""
    manifest_sha256: str = ""
    file_count: int = 0
    legacy_manifest: bool = False
    message: str = ""


class GroundArchiveDetailDTO(ApiModel):
    archive: GroundArchiveDTO
    files: list[GroundArchiveFileDTO] = Field(default_factory=list)
    validation: GroundArchiveValidationDTO = Field(
        default_factory=GroundArchiveValidationDTO
    )


class GroundActionResponseDTO(ApiModel):
    accepted: bool = True
    state: GroundRunState
    run_id: str = ""
    operation_id: str = ""
    message: str = ""


class GroundOperationDTO(ApiModel):
    operation_id: str
    site_id: str
    run_id: str
    operation_type: Literal["STOP", "STOP_AND_ARCHIVE"]
    operation_state: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    operation_stage: str
    progress_percent: int = Field(default=0, ge=0, le=100)
    message: str = ""
    started_at: str
    updated_at: str
    completed_at: str = ""
    failure_code: str = ""
    failure_reason: str = ""
    result_summary: dict[str, object] = Field(default_factory=dict)


class GroundPingSampleDTO(ApiModel):
    sample_id: str = ""
    ts: str
    target_ip: str
    train_id: str = ""
    train_no: str = ""
    mr_id: str = ""
    mr_name: str = ""
    mr_position_code: str = ""
    seq: int | None = None
    ok: bool
    rtt_ms: float | None = None
    timeout_ms: int | None = None
    packet_size: int | None = None
    current_ap_identity: str = ""
    current_ap_name: str = ""
    current_ap_mac: str = ""
    station: str = ""
    section: str = ""
    mileage: str = ""
    rssi: int | None = None
    ac_snapshot_id: int | None = None
    ac_received_at: str = ""
    position_quality: str = ""
    ap_transition_context: str = ""
    warmup_ignored: bool = False
    target_activation_started_at: str = ""
    archive_entry: str = ""
    data_source: Literal["ACTIVE", "ARCHIVE"] = "ACTIVE"


class GroundQueryDiagnosticsDTO(ApiModel):
    request_id: str = ""
    requested_run_id: str = ""
    resolved_start_time: str = ""
    resolved_end_time: str = ""
    source_kind: Literal["ACTIVE", "ARCHIVE", "MIXED", "NONE"] = "NONE"
    data_availability: GroundDataAvailability = "MISSING"
    files_considered: int = 0
    files_scanned: int = 0
    registered_record_count: int = 0
    records_scanned: int = 0
    bytes_scanned: int = 0
    malformed_record_count: int = 0
    duplicate_record_count: int = 0
    truncated: bool = False
    optimized_latest_page: bool = False
    legacy_archive: bool = False
    no_data_reason: str = ""
    resolved_train_ids: list[str] = Field(default_factory=list)
    resolved_mr_ids: list[str] = Field(default_factory=list)
    raw_file_registry_hit_count: int = 0
    matched_count: int = 0


class GroundPingSamplePageDTO(ApiModel):
    items: list[GroundPingSampleDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 100
    raw_sample_count: int = 0
    effective_sample_count: int = 0
    ignored_sample_count: int = 0
    query_identity: str = ""
    diagnostics: GroundQueryDiagnosticsDTO = Field(
        default_factory=GroundQueryDiagnosticsDTO
    )


class GroundPingSeriesDTO(ApiModel):
    raw_sample_count: int = 0
    effective_sample_count: int = 0
    ignored_sample_count: int = 0
    success_count: int = 0
    loss_count: int = 0
    rtt_sample_count: int = 0
    rtt_sum_ms: float = 0.0
    current_rtt_ms: float | None = None
    average_rtt_ms: float | None = None
    max_rtt_ms: float | None = None
    points: list[GroundPingSampleDTO] = Field(default_factory=list)
    loss_windows: list[dict[str, object]] = Field(default_factory=list)
    ap_transitions: list[dict[str, object]] = Field(default_factory=list)
    position_segments: list[dict[str, object]] = Field(default_factory=list)
    diagnostics: GroundQueryDiagnosticsDTO = Field(
        default_factory=GroundQueryDiagnosticsDTO
    )
    next_cursor: str = ""
    latest_sequence: int | None = None
    latest_timestamp: str = ""
    server_time: str = ""
    active: bool = False
    target_state: str = ""
    has_more: bool = False
    query_identity: str = ""


class GroundSyslogRecordDTO(ApiModel):
    receive_time: str
    device_time: str = ""
    source_ip: str = ""
    source_port: int | None = None
    hostname: str = ""
    system_name: str = ""
    facility: str = ""
    severity: str = ""
    train_id: str = ""
    train_no: str = ""
    device_uuid: str = ""
    mr_name: str = ""
    mr_role: str = ""
    identity_status: str = ""
    parse_status: str = ""
    data_quality: str = ""
    clock_offset_ms: float | None = None
    raw_text: str = ""
    global_receive_sequence: int | None = None
    source_receive_sequence: int | None = None
    raw_file_id: str = ""
    raw_line_number: int | None = None
    raw_file_status: str = ""
    archive_entry: str = ""
    data_source: Literal["ACTIVE", "ARCHIVE"] = "ACTIVE"
    display_enriched: bool = False
    event_type: str = ""
    event_family: str = ""
    interface_name: str = ""
    interface_type: str = ""
    physical_state: str = ""
    cfg_event_index: str = ""
    cfg_command_source: str = ""
    cfg_source: str = ""
    cfg_destination: str = ""
    expected_internal_change: bool = False
    correlation_status: str = "UNCONFIRMED"
    correlation_confidence: str = "UNCONFIRMED"
    correlation_delta_ms: int | None = None
    correlated_event_ids: list[int] = Field(default_factory=list)
    composite_event_type: str = ""
    peer_ap_id: str = ""
    peer_name: str = ""
    peer_mac: str = ""
    peer_radio_mac: str = ""
    previous_peer_ap_id: str = ""
    previous_peer_name: str = ""
    previous_peer_mac: str = ""
    previous_peer_radio_mac: str = ""
    station: str = ""
    section: str = ""
    previous_station: str = ""
    previous_section: str = ""
    rssi: int | None = None
    previous_rssi: int | None = None
    reason_code: str = ""
    reason_text: str = ""
    resolution_status: str = ""
    parsed_details: dict[str, object] = Field(default_factory=dict)


class GroundSyslogRecordPageDTO(ApiModel):
    items: list[GroundSyslogRecordDTO] = Field(default_factory=list)
    total: int = 0
    total_exact: bool = True
    page: int = 1
    page_size: int = 100
    diagnostics: GroundQueryDiagnosticsDTO = Field(
        default_factory=GroundQueryDiagnosticsDTO
    )


class GroundSyslogRecordKeyDTO(ApiModel):
    raw_file_id: str = Field(min_length=1, max_length=200)
    global_receive_sequence: int | None = Field(default=None, ge=0)
    source_receive_sequence: int | None = Field(default=None, ge=0)
    raw_line_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_stable_identity(self) -> "GroundSyslogRecordKeyDTO":
        if (
            self.global_receive_sequence is None
            and self.source_receive_sequence is None
            and self.raw_line_number is None
        ):
            raise ValueError("Syslog 记录身份缺少接收序号或原始行号")
        return self


class GroundSyslogDeleteFiltersDTO(ApiModel):
    train_id: str = Field(default="", max_length=100)
    mr_id: str = Field(default="", max_length=100)
    mr_name: str = Field(default="", max_length=200)
    mr_role: str = Field(default="", max_length=20)
    source_ip: str = Field(default="", max_length=100)
    system_name: str = Field(default="", max_length=200)
    facility: str = Field(default="", max_length=50)
    severity: str = Field(default="", max_length=50)
    identity_status: str = Field(default="", max_length=100)
    event_type: str = Field(default="", max_length=100)
    event_family: str = Field(default="", max_length=20)
    cfg_command_source: str = Field(default="", max_length=50)
    physical_state: str = Field(default="", max_length=20)
    correlation_status: str = Field(default="", max_length=20)
    correlation_confidence: str = Field(default="", max_length=20)
    peer_name: str = Field(default="", max_length=200)
    data_source: str = Field(default="", max_length=20)
    keyword: str = Field(default="", max_length=500)
    start_time: str = Field(default="", max_length=100)
    end_time: str = Field(default="", max_length=100)


class GroundSyslogDeletePreviewRequestDTO(ApiModel):
    run_id: str = Field(min_length=1, max_length=100)
    mode: Literal["SELECTED", "FILTERED", "RUN_ALL"]
    record_keys: list[GroundSyslogRecordKeyDTO] = Field(
        default_factory=list,
        max_length=5000,
    )
    filters: GroundSyslogDeleteFiltersDTO = Field(
        default_factory=GroundSyslogDeleteFiltersDTO
    )
    include_derived_events: bool = True

    @model_validator(mode="after")
    def validate_scope(self) -> "GroundSyslogDeletePreviewRequestDTO":
        if self.mode == "SELECTED" and not self.record_keys:
            raise ValueError("删除选中记录必须提供稳定记录身份")
        if self.mode != "SELECTED" and self.record_keys:
            raise ValueError("非选中删除模式不得携带记录身份")
        if self.mode == "FILTERED" and not any(
            str(value or "").strip()
            for value in self.filters.model_dump().values()
        ):
            raise ValueError("筛选范围删除至少需要一个筛选条件")
        return self


class GroundSyslogDeletePreviewDTO(ApiModel):
    run_id: str
    run_date: str = ""
    mode: Literal["SELECTED", "FILTERED", "RUN_ALL"]
    matched_record_count: int = 0
    affected_file_count: int = 0
    affected_event_count: int = 0
    affected_timeline_count: int = 0
    total_bytes: int = 0
    file_statuses: list[dict[str, object]] = Field(default_factory=list)
    archive_status: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    preview_token: str = ""
    expires_at: str = ""
    confirmation_hint: str = ""


class GroundSyslogDeleteRequestDTO(ApiModel):
    preview_token: str = Field(min_length=20, max_length=200)
    explicit_confirmation: bool
    confirmation_text: str = Field(min_length=1, max_length=200)
    include_derived_events: bool = True


class GroundSyslogDeleteAcceptedDTO(ApiModel):
    accepted: bool = True
    operation_id: str
    task_id: str
    run_id: str
    status: str = "PENDING"
    message: str


class GroundArchiveDeleteRequestDTO(ApiModel):
    explicit_confirmation: bool = False


__all__ = [name for name in globals() if name.startswith("Ground")]
