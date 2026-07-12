from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclass(frozen=True)
class AgentFpingStartRequest:
    targets: tuple[str, ...]
    interval_ms: int = 100
    timeout_ms: int = 100
    packet_size: int = 64
    count: int = 20
    continuous: bool = False
    source_address: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "targets": list(self.targets),
            "interval_ms": self.interval_ms,
            "timeout_ms": self.timeout_ms,
            "packet_size": self.packet_size,
            "count": self.count,
            "continuous": self.continuous,
            "source_address": self.source_address,
        }


@dataclass(frozen=True)
class AgentIperfServerStartRequest:
    bind_address: str = "0.0.0.0"
    port: int = 5201
    report_interval: float = 1.0
    one_off: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "bind_address": self.bind_address,
            "port": self.port,
            "protocol": "tcp",
            "report_interval": self.report_interval,
            "one_off": self.one_off,
        }


@dataclass(frozen=True)
class AgentIperfClientStartRequest:
    server_host: str
    server_port: int = 5201
    protocol: str = "tcp"
    duration_sec: int = 10
    parallel: int = 1
    bandwidth_mbps: float = 0.0
    reverse: bool = False
    bidirectional: bool = False
    report_interval: float = 1.0
    udp_packet_length: int = 0
    tcp_block_size: int = 0
    connect_timeout_ms: int = 5_000

    def as_payload(self) -> dict[str, Any]:
        return {
            "server_host": self.server_host,
            "server_port": self.server_port,
            "protocol": self.protocol,
            "duration_sec": self.duration_sec,
            "parallel": self.parallel,
            "bandwidth_mbps": self.bandwidth_mbps,
            "reverse": self.reverse,
            "bidirectional": self.bidirectional,
            "report_interval": self.report_interval,
            "udp_packet_length": self.udp_packet_length,
            "tcp_block_size": self.tcp_block_size,
            "connect_timeout": self.connect_timeout_ms,
        }


@dataclass(frozen=True)
class AgentTaskDTO:
    task_id: str
    task_type: str
    status: str
    created_at: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    package_id: str = ""
    package_download_url: str = ""
    error_code: str = ""
    error_message: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AgentTaskDTO:
        params = payload.get("params")
        return cls(
            task_id=str(payload.get("task_id") or ""),
            task_type=str(payload.get("task_type") or ""),
            status=str(payload.get("status") or ""),
            created_at=_timestamp(payload.get("created_at")),
            start_time=_timestamp(payload.get("start_time")),
            end_time=_timestamp(payload.get("end_time")),
            package_id=str(payload.get("package_id") or ""),
            package_download_url=str(payload.get("package_download_url") or ""),
            error_code=str(payload.get("error_code") or ""),
            error_message=str(payload.get("error_message") or ""),
            params=dict(params) if isinstance(params, dict) else {},
        )


@dataclass(frozen=True)
class AgentTaskEventDTO:
    sequence: int
    timestamp: datetime | None
    type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AgentTaskEventDTO:
        event_payload = payload.get("payload")
        return cls(
            sequence=int(payload.get("sequence") or 0),
            timestamp=_timestamp(payload.get("timestamp")),
            type=str(payload.get("type") or ""),
            source=str(payload.get("source") or ""),
            payload=dict(event_payload) if isinstance(event_payload, dict) else {},
        )


@dataclass(frozen=True)
class AgentTaskEventPageDTO:
    task_id: str
    events: tuple[AgentTaskEventDTO, ...]
    next_after: int
    has_more: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AgentTaskEventPageDTO:
        events = payload.get("events")
        return cls(
            task_id=str(payload.get("task_id") or ""),
            events=tuple(AgentTaskEventDTO.from_payload(item) for item in events or () if isinstance(item, dict)),
            next_after=int(payload.get("next_after") or 0),
            has_more=bool(payload.get("has_more")),
        )


@dataclass(frozen=True)
class AgentTaskArtifactDTO:
    name: str
    kind: str
    available: bool


@dataclass(frozen=True)
class AgentTaskResultDTO:
    task_id: str
    task_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict[str, Any]
    artifacts: tuple[AgentTaskArtifactDTO, ...]
    last_sequence: int
    error_code: str
    error: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AgentTaskResultDTO:
        artifacts = payload.get("artifacts")
        summary = payload.get("summary")
        return cls(
            task_id=str(payload.get("task_id") or ""),
            task_type=str(payload.get("task_type") or ""),
            status=str(payload.get("status") or ""),
            started_at=_timestamp(payload.get("started_at")),
            finished_at=_timestamp(payload.get("finished_at")),
            summary=dict(summary) if isinstance(summary, dict) else {},
            artifacts=tuple(
                AgentTaskArtifactDTO(
                    name=str(item.get("name") or ""),
                    kind=str(item.get("kind") or ""),
                    available=bool(item.get("available")),
                )
                for item in artifacts or ()
                if isinstance(item, dict)
            ),
            last_sequence=int(payload.get("last_sequence") or 0),
            error_code=str(payload.get("error_code") or ""),
            error=str(payload.get("error") or ""),
        )
