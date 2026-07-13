from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.online_mr_application import OnlineMrExecutorKind, OnlineMrMappingState, OnlineMrPhase
from netconsole.models.task_state import TaskState


class OnlineMrMetricType(StrEnum):
    RSSI = "rssi"
    CTL_BUSY = "ctl_busy"
    TX_BUSY = "tx_busy"
    RX_BUSY = "rx_busy"
    INTERFACE_IN_PPS = "interface_in_pps"
    INTERFACE_OUT_PPS = "interface_out_pps"
    PING_RTT = "ping_rtt"
    PING_LOSS = "ping_loss"
    IPERF_BITRATE = "iperf_bitrate"
    MAIN_LINK = "main_link"


class OnlineMrDownsampleMode(StrEnum):
    NONE = "NONE"
    BUCKET_AVG = "BUCKET_AVG"
    MIN_MAX = "MIN_MAX"
    LATEST_PER_BUCKET = "LATEST_PER_BUCKET"


class OnlineMrDataIntegrity(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


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
    controller_task_id: str | None = None
    executor_kind: str | None = None
    agent_id: str | None = None
    has_raw_data: bool = False
    has_parsed_data: bool = False
    has_package: bool = False
    package_name: str | None = None
    force_stopped: bool | None = None
    finalization_complete: bool | None = None
    error_code: str | None = None
    error_message: str | None = None


class OnlineMrDatabaseSummaryDTO(ApiModel):
    available: bool = False
    compatible: bool | None = None
    size_bytes: int = 0
    tables: list[str] = Field(default_factory=list)
    row_counts: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None


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
    points: list[OnlineMrMetricPointDTO] = Field(default_factory=list)
    summary: OnlineMrMetricSummaryDTO = Field(default_factory=OnlineMrMetricSummaryDTO)


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
    mr_name: str = ""
    executor_kind: OnlineMrExecutorKind
    agent_id: str = ""
    task_status: TaskState | None = None
    phase: OnlineMrPhase
    created_at: str
    started_at: str | None = None
    updated_at: str
    terminal_at: str | None = None
    error_code: str = ""
    error_message: str = ""
    mapping_state: OnlineMrMappingState


__all__ = [name for name in globals() if name.startswith("OnlineMr")]
