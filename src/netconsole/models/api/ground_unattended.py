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
    "AP_UNMATCHED",
    "OFFLINE",
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


class GroundUnattendedProfileDTO(ApiModel):
    site_id: str
    enabled: bool = False
    schedule_start_time: str = Field(
        default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    schedule_end_time: str = Field(
        default="23:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    timezone: str = Field(default="system", min_length=1, max_length=100)
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
    fleet_ping_interval_ms: int = Field(default=1000, ge=100, le=60_000)
    fleet_ping_timeout_ms: int = Field(default=4000, ge=100, le=60_000)
    fleet_ping_packet_size: int = Field(default=64, ge=1, le=65_507)
    fleet_ping_shard_size: int = Field(default=12, ge=2, le=32)
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
    paused: bool = False
    run_id: str = ""
    run_date: str = ""
    actual_started_at: str = ""
    actual_ended_at: str = ""
    schedule_start_time: str = "07:00"
    schedule_end_time: str = "23:00"
    timezone: str = "system"
    next_start_at: str = ""
    next_end_at: str = ""
    profile_effective_at: str = "下一次调度周期"
    ac_last_updated_at: str = ""
    ac_freshness_status: str = "NO_DATA"
    mainline_train_count: int = 0
    ping_target_count: int = 0
    active_deep_train_count: int = 0
    covered_train_count: int = 0
    incomplete_train_count: int = 0
    inventory_train_count: int = 0
    syslog_active_mr_count: int = 0
    config_abnormal_count: int = 0
    data_quality_warning_count: int = 0
    disk_used_bytes: int = 0
    disk_free_bytes: int = 0
    disk_status: str = "UNKNOWN"
    latest_archive_status: str = ""
    latest_archive_message: str = ""
    message: str = ""
    updated_at: str = ""


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


class GroundUnattendedTrainDTO(ApiModel):
    train_id: str
    train_no: str = ""
    train_name: str = ""
    ping_eligible: bool = False
    deep_collection_eligible: bool = False
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
    allow_target_port_change: bool = False
    explicit_confirmation: bool = False


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


class GroundHealthDTO(ApiModel):
    site_id: str
    status: str = "UNKNOWN"
    udp_running: bool = False
    udp_listen_address: str = ""
    udp_receive_rate_per_second: float = 0.0
    udp_received_count: int = 0
    udp_unidentified_count: int = 0
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
    disk_free_bytes: int = 0
    last_error: str = ""
    updated_at: str = ""


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
    target_ip: str
    train_id: str = ""
    train_no: str = ""
    mr_id: str = ""
    mr_position_code: str = ""
    started_at: str = ""
    updated_at: str = ""
    shard_id: str = ""
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
    mr_id: str = ""
    title: str = ""
    message: str = ""
    details: dict[str, object] = Field(default_factory=dict)


class GroundTimelinePageDTO(ApiModel):
    items: list[GroundTimelineEventDTO] = Field(default_factory=list)
    total: int = 0


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
    archive_status: str = ""
    retention_until: str = ""
    summary: dict[str, object] = Field(default_factory=dict)
    message: str = ""
    created_at: str = ""
    updated_at: str = ""


class GroundArchivePageDTO(ApiModel):
    items: list[GroundArchiveDTO] = Field(default_factory=list)
    total: int = 0


class GroundActionResponseDTO(ApiModel):
    accepted: bool = True
    state: GroundRunState
    run_id: str = ""
    message: str = ""


class GroundArchiveDeleteRequestDTO(ApiModel):
    explicit_confirmation: bool = False


__all__ = [name for name in globals() if name.startswith("Ground")]
