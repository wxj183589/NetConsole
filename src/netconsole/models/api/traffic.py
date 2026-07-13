from __future__ import annotations

from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import ExecutionTargetKind, TrafficSyncState, TrafficTestType


class TrafficExecutionTargetRequest(ApiModel):
    kind: ExecutionTargetKind = ExecutionTargetKind.LOCAL
    agent_id: str = Field(default="", max_length=128)
    display_name: str = Field(default="", max_length=200)


class TrafficExecutionTargetDTO(ApiModel):
    kind: ExecutionTargetKind
    id: str
    display_name: str
    available: bool = True
    unavailable_reason: str = ""
    agent_id: str = ""
    status: str = ""
    platform: str = ""
    architecture: str = ""
    version: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)


class IperfServerStartRequest(ApiModel):
    execution_target: TrafficExecutionTargetRequest = Field(default_factory=TrafficExecutionTargetRequest)
    bind_ip: str = Field(default="", max_length=128)
    port: int = Field(default=5201, ge=1, le=65535)
    interval_seconds: int = Field(default=1, ge=1, le=60)
    one_off: bool = False
    parent_task_id: str = Field(default="", max_length=128)
    correlation_id: str = Field(default="", max_length=128)


class IperfClientStartRequest(ApiModel):
    execution_target: TrafficExecutionTargetRequest = Field(default_factory=TrafficExecutionTargetRequest)
    server_ip: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5201, ge=1, le=65535)
    protocol: str = Field(default="TCP", max_length=8)
    duration_seconds: int = Field(default=10, ge=1, le=86400)
    interval_seconds: int = Field(default=1, ge=1, le=60)
    parallel: int = Field(default=1, ge=1, le=128)
    direction: str = Field(default="upload", max_length=20)
    target_bandwidth: str | None = Field(default=None, max_length=32)
    tcp_block_size: str | None = Field(default=None, max_length=32)
    packet_length: int | None = Field(default=None, ge=1, le=65507)
    tcp_report_threshold_mbps: float | None = None
    tcp_pacing_enabled: bool = False
    tcp_pacing_mbps: float | None = None
    udp_bitrate_mbps: float | None = None
    udp_report_threshold_mbps: float | None = None
    parent_task_id: str = Field(default="", max_length=128)
    correlation_id: str = Field(default="", max_length=128)


class FpingStartRequest(ApiModel):
    execution_target: TrafficExecutionTargetRequest = Field(default_factory=TrafficExecutionTargetRequest)
    targets: list[str] = Field(min_length=1, max_length=64)
    interval_ms: int = Field(default=100, ge=1, le=60000)
    timeout_ms: int = Field(default=100, ge=1, le=60000)
    packet_size: int = Field(default=64, ge=1, le=65507)
    count: int = Field(default=20, ge=0, le=1000000)
    continuous: bool = False
    source_address: str = Field(default="", max_length=128)
    parent_task_id: str = Field(default="", max_length=128)
    correlation_id: str = Field(default="", max_length=128)


class TrafficRunDTO(ApiModel):
    id: str
    traffic_run_id: str
    controller_task_id: str = ""
    test_type: TrafficTestType
    role: str
    executor_kind: ExecutionTargetKind
    agent_id: str = ""
    normalized_config: dict[str, Any] = Field(default_factory=dict)
    status: TaskState
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    updated_at: str
    summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    raw_reference: str = ""
    result_reference: str = ""
    retry_of_traffic_run_id: str = ""
    parent_task_id: str = ""
    correlation_id: str = ""
    last_event_sequence: int = 0
    sync_state: TrafficSyncState = TrafficSyncState.ACTIVE
    cancellable: bool = False


class TrafficStartResponse(ApiModel):
    run: TrafficRunDTO


class TrafficCancelResponse(ApiModel):
    traffic_run_id: str
    controller_task_id: str
    status: TaskState
    message: str


class TrafficRetryResponse(ApiModel):
    run: TrafficRunDTO
    retry_of_traffic_run_id: str


class TrafficEventDTO(ApiModel):
    sequence: int
    timestamp: str
    traffic_run_id: str
    controller_task_id: str
    source: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    remote_sequence: int | None = None


class TrafficPingSampleDTO(ApiModel):
    traffic_run_id: str
    sequence: int
    timestamp: str
    target: str
    probe_sequence: int | None = None
    ok: bool
    rtt_ms: float | None = None
    timeout: bool = False
    packet_size: int | None = None
    error_code: str = ""
    error_message: str = ""


class TrafficSummaryDTO(ApiModel):
    traffic_run_id: str
    updated_at: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
