from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.services.online_mr.db.event_writer import EventWriter
from netconsole.services.online_mr.diagnosis_engine import OnlineMrDiagnosisEngine
from netconsole.services.online_mr.event_bus import OnlineMrEventBus
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine
from netconsole.services.online_mr.realtime.sliding_window_buffer import SlidingWindowBuffer
from netconsole.services.online_mr.session_adapter import SessionAdapter


@dataclass(frozen=True)
class OfflineReplayResult:
    events: int = 0
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None
    diagnosis_score: float = 0.0
    issues: int = 0
    fping: dict[str, Any] = field(default_factory=dict)
    iperf: dict[str, Any] = field(default_factory=dict)


def replay_session(
    session_dir: Path,
    session_id: str = "",
    device_id: int | None = None,
    event_bus: OnlineMrEventBus | None = None,
    sliding_window_buffer: SlidingWindowBuffer | None = None,
) -> OfflineReplayResult:
    """Replay offline raw/json artifacts through the same event pipeline used online."""

    session_dir = Path(session_dir)
    bus = event_bus or OnlineMrEventBus()
    buffer = sliding_window_buffer or SlidingWindowBuffer(window_seconds=10)
    parser = EventParserEngine()
    diagnosis = OnlineMrDiagnosisEngine()
    writer = EventWriter(session_dir / "parsed" / "online_diagnosis.sqlite")

    bus.subscribe("*", buffer.add)
    bus.subscribe("*", parser.on_event)
    bus.subscribe("*", diagnosis.on_event)
    bus.subscribe("*", writer.write_event_to_db)

    first_time: datetime | None = None
    last_time: datetime | None = None
    count = 0
    for event in SessionAdapter(session_dir, session_id=session_id, device_id=device_id).iter_events():
        if first_time is None or event.timestamp < first_time:
            first_time = event.timestamp
        if last_time is None or event.timestamp > last_time:
            last_time = event.timestamp
        count += 1
        bus.publish(event)

    return OfflineReplayResult(
        events=count,
        first_event_time=first_time,
        last_event_time=last_time,
        diagnosis_score=diagnosis.score,
        issues=len(diagnosis.issues),
        fping=parser.latest("fping") or {},
        iperf=parser.latest("iperf") or {},
    )
