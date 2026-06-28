from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


EVENT_MESH_SAMPLE = "MESH_SAMPLE"
EVENT_BUSY_SAMPLE = "BUSY_SAMPLE"
EVENT_STATS_SAMPLE = "STATS_SAMPLE"
EVENT_INTERFACE_SAMPLE = "INTERFACE_SAMPLE"
EVENT_FPING_V5_SAMPLE = "FPING_V5_SAMPLE"
EVENT_IPERF3_SAMPLE = "IPERF3_SAMPLE"
EVENT_LINK_SWITCH = "LINK_SWITCH"
EVENT_SESSION_START = "SESSION_START"
EVENT_SESSION_STOP = "SESSION_STOP"
EVENT_RAW_LINE = "RAW_LINE"


@dataclass(frozen=True)
class OnlineMrEvent:
    timestamp: datetime
    session_id: str
    device_id: int | None
    source: str
    module: str
    event_type: str
    payload: dict[str, object] = field(default_factory=dict)
    raw: str | None = None
