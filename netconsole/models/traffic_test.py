from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TaskState


class TrafficTestType(StrEnum):
    IPERF_SERVER = "IPERF_SERVER"
    IPERF_CLIENT = "IPERF_CLIENT"
    HIGH_FREQUENCY_PING = "HIGH_FREQUENCY_PING"


class ExecutionTargetKind(StrEnum):
    LOCAL = "LOCAL"
    AGENT = "AGENT"


class TrafficEventType(StrEnum):
    STATE = "state"
    STDOUT = "stdout"
    STDERR = "stderr"
    SAMPLE = "sample"
    SUMMARY = "summary"
    ERROR = "error"
    SYSTEM = "system"


class TrafficSyncState(StrEnum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    CREDENTIAL_REQUIRED = "CREDENTIAL_REQUIRED"
    AGENT_OFFLINE = "AGENT_OFFLINE"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ExecutionTargetDTO:
    kind: ExecutionTargetKind
    agent_id: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        if self.kind is ExecutionTargetKind.LOCAL and self.agent_id:
            raise ValueError("LOCAL execution target cannot contain agent_id")
        if self.kind is ExecutionTargetKind.AGENT and not self.agent_id.strip():
            raise ValueError("AGENT execution target requires agent_id")


@dataclass(frozen=True)
class HighFrequencyPingConfig:
    targets: tuple[str, ...]
    interval_ms: int = 100
    timeout_ms: int = 100
    packet_size: int = 64
    count: int = 20
    continuous: bool = False
    source_address: str = ""

    def normalized(self) -> HighFrequencyPingConfig:
        targets = tuple(str(value).strip() for value in self.targets)
        if not targets or any(not value for value in targets):
            raise ValueError("at least one ping target is required")
        if len(targets) > 64:
            raise ValueError("ping targets cannot exceed 64")
        if len(set(targets)) != len(targets):
            raise ValueError("ping targets cannot contain duplicates")
        interval_ms = int(self.interval_ms)
        timeout_ms = int(self.timeout_ms)
        packet_size = int(self.packet_size)
        count = int(self.count)
        if not 1 <= interval_ms <= 60_000:
            raise ValueError("interval_ms must be between 1 and 60000")
        if not 1 <= timeout_ms <= 60_000:
            raise ValueError("timeout_ms must be between 1 and 60000")
        if not 1 <= packet_size <= 65_507:
            raise ValueError("packet_size must be between 1 and 65507")
        if self.continuous:
            if count != 0:
                raise ValueError("continuous ping requires count=0")
        elif not 1 <= count <= 1_000_000:
            raise ValueError("finite ping count must be between 1 and 1000000")
        return replace(
            self,
            targets=targets,
            interval_ms=interval_ms,
            timeout_ms=timeout_ms,
            packet_size=packet_size,
            count=count,
            source_address=str(self.source_address or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        value = self.normalized()
        return {
            "targets": list(value.targets),
            "interval_ms": value.interval_ms,
            "timeout_ms": value.timeout_ms,
            "packet_size": value.packet_size,
            "count": value.count,
            "continuous": value.continuous,
            "source_address": value.source_address,
        }


@dataclass(frozen=True)
class TrafficRun:
    traffic_run_id: str
    test_type: TrafficTestType
    role: str
    executor_kind: ExecutionTargetKind
    normalized_config: dict[str, Any]
    status: TaskState
    created_at: str
    updated_at: str
    controller_task_id: str = ""
    agent_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    raw_reference: str = ""
    result_reference: str = ""
    local_iperf_run_id: str = ""
    retry_of_traffic_run_id: str = ""
    parent_task_id: str = ""
    correlation_id: str = ""
    last_event_sequence: int = 0
    sync_state: TrafficSyncState = TrafficSyncState.ACTIVE


@dataclass(frozen=True)
class AgentTaskMapping:
    traffic_run_id: str
    controller_task_id: str
    agent_id: str
    agent_task_id: str
    agent_task_type: str
    last_remote_sequence: int = 0
    last_remote_status: str = "created"
    last_polled_at: str = ""
    sync_state: TrafficSyncState = TrafficSyncState.ACTIVE
    sync_error_code: str = ""
    sync_error_message: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TrafficPingSample:
    traffic_run_id: str
    sequence: int
    timestamp: str
    target: str
    probe_sequence: int | None
    ok: bool
    rtt_ms: float | None
    timeout: bool = False
    packet_size: int | None = None
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class TrafficEvent:
    traffic_run_id: str
    controller_task_id: str
    source: str
    type: TrafficEventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)
    sequence: int = 0
    remote_sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": int(self.sequence),
            "timestamp": self.timestamp,
            "traffic_run_id": self.traffic_run_id,
            "controller_task_id": self.controller_task_id,
            "source": self.source,
            "type": self.type.value,
            "payload": dict(self.payload),
            "remote_sequence": self.remote_sequence,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrafficEvent:
        remote_sequence = value.get("remote_sequence")
        return cls(
            sequence=int(value.get("sequence") or 0),
            timestamp=str(value.get("timestamp") or ""),
            traffic_run_id=str(value.get("traffic_run_id") or ""),
            controller_task_id=str(value.get("controller_task_id") or ""),
            source=str(value.get("source") or ""),
            type=TrafficEventType(str(value.get("type") or TrafficEventType.SYSTEM.value)),
            payload=dict(value.get("payload") or {}),
            remote_sequence=int(remote_sequence) if remote_sequence is not None else None,
        )
