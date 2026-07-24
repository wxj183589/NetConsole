from __future__ import annotations

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
    disk_used_bytes: int = 0
    disk_free_bytes: int = 0
    disk_status: str = "UNKNOWN"
    latest_archive_status: str = ""
    latest_archive_message: str = ""
    message: str = ""
    updated_at: str = ""


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


class GroundUnattendedTrainDTO(ApiModel):
    train_id: str
    train_no: str = ""
    train_name: str = ""
    ping_eligible: bool = False
    deep_collection_eligible: bool = False
    eligibility_status: GroundEligibilityStatus = "AC_UNKNOWN"
    exclusion_reason: str = ""
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
