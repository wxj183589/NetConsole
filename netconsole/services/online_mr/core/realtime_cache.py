from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Deque

from netconsole.models.online_mr_models import OnlineMrSnapshot
from netconsole.services.online_mr.core.event_model import OnlineMrEvent


@dataclass(frozen=True)
class OnlineMrRawEvent:
    timestamp: datetime
    session_id: str
    device_id: int | None
    source: str
    raw: str
    task_type: str = ""


@dataclass(frozen=True)
class OnlineMrParsedEvent:
    timestamp: datetime
    session_id: str
    device_id: int | None
    module: str
    payload: dict[str, object]
    raw: str | None = None


@dataclass
class OnlineMrRealtimeSession:
    session_id: str
    site_id: str
    device_id: int | None
    session_type: str = "realtime"
    started_at: datetime = field(default_factory=datetime.now)
    last_seen_at: datetime = field(default_factory=datetime.now)
    closed_at: datetime | None = None
    raw_events: Deque[OnlineMrRawEvent] = field(default_factory=lambda: deque(maxlen=20000))
    parsed_samples: Deque[OnlineMrParsedEvent] = field(default_factory=lambda: deque(maxlen=20000))
    latest_snapshot: OnlineMrSnapshot | None = None
    errors: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)


class OnlineMrRealtimeCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, OnlineMrRealtimeSession] = {}
        self._device_latest_session: dict[int, str] = {}
        self._site_device_latest_session: dict[tuple[str, int], str] = {}

    def register_session(
        self,
        *,
        site_id: str,
        session_id: str,
        device_id: int | None,
        session_type: str = "realtime",
        snapshot: OnlineMrSnapshot | None = None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = OnlineMrRealtimeSession(
                    session_id=session_id,
                    site_id=site_id,
                    device_id=device_id,
                    session_type=session_type,
                )
                self._sessions[session_id] = session
            if snapshot is not None:
                session.latest_snapshot = snapshot
            if device_id is not None:
                self._device_latest_session[int(device_id)] = session_id
                self._site_device_latest_session[(site_id, int(device_id))] = session_id

    def get_latest_snapshot(self, device_id: int, site_id: str | None = None) -> OnlineMrSnapshot | None:
        with self._lock:
            if site_id is not None:
                session_id = self._site_device_latest_session.get((site_id, int(device_id)))
            else:
                session_id = self._device_latest_session.get(int(device_id))
            session = self._sessions.get(session_id or "")
            return session.latest_snapshot if session is not None and session.closed_at is None else None

    def list_running_sessions(self, site_id: str | None = None) -> list[OnlineMrRealtimeSession]:
        with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.closed_at is None and (site_id is None or session.site_id == site_id)
            ]

    def list_device_sessions(self, device_id: int) -> list[OnlineMrRealtimeSession]:
        with self._lock:
            return [session for session in self._sessions.values() if session.device_id == int(device_id)]

    def get_session_link_details(self, session_id: str, limit: int | None = None) -> list[OnlineMrParsedEvent]:
        with self._lock:
            session = self._sessions.get(session_id)
            rows = list(session.parsed_samples) if session else []
        return rows[-limit:] if limit is not None else rows

    def get_session_realtime_table(self, session_id: str) -> OnlineMrSnapshot | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.latest_snapshot if session else None

    def append_raw_event(self, session_id: str, event: OnlineMrRawEvent | OnlineMrEvent) -> None:
        raw_event = self._coerce_raw_event(event)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = OnlineMrRealtimeSession(session_id=session_id, site_id="", device_id=raw_event.device_id)
                self._sessions[session_id] = session
            session.raw_events.append(raw_event)
            session.last_seen_at = raw_event.timestamp
            session.counters["raw_events"] = session.counters.get("raw_events", 0) + 1
            if raw_event.device_id is not None:
                self._device_latest_session[int(raw_event.device_id)] = session_id
                self._site_device_latest_session[(session.site_id, int(raw_event.device_id))] = session_id

    def append_parsed_sample(self, session_id: str, sample: OnlineMrParsedEvent | OnlineMrEvent) -> None:
        parsed = self._coerce_parsed_event(sample)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = OnlineMrRealtimeSession(session_id=session_id, site_id="", device_id=parsed.device_id)
                self._sessions[session_id] = session
            session.parsed_samples.append(parsed)
            session.last_seen_at = parsed.timestamp
            session.counters["parsed_samples"] = session.counters.get("parsed_samples", 0) + 1
            if parsed.device_id is not None:
                self._device_latest_session[int(parsed.device_id)] = session_id
                self._site_device_latest_session[(session.site_id, int(parsed.device_id))] = session_id

    def update_snapshot(self, snapshot: OnlineMrSnapshot) -> None:
        with self._lock:
            session = self._sessions.get(snapshot.session_id)
            if session is None:
                session = OnlineMrRealtimeSession(session_id=snapshot.session_id, site_id="", device_id=snapshot.device_id)
                self._sessions[snapshot.session_id] = session
            session.latest_snapshot = snapshot
            session.last_seen_at = datetime.now()
            if snapshot.device_id is not None:
                self._device_latest_session[int(snapshot.device_id)] = snapshot.session_id
                self._site_device_latest_session[(session.site_id, int(snapshot.device_id))] = snapshot.session_id

    def close_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.closed_at = datetime.now()
            for device_id, latest_session_id in list(self._device_latest_session.items()):
                if latest_session_id == session_id:
                    self._device_latest_session.pop(device_id, None)
            for key, latest_session_id in list(self._site_device_latest_session.items()):
                if latest_session_id == session_id:
                    self._site_device_latest_session.pop(key, None)

    def clear_device_latest(self, *, site_id: str, device_id: int) -> None:
        with self._lock:
            normalized_device_id = int(device_id)
            old_session_id = self._site_device_latest_session.pop((site_id, normalized_device_id), None)
            if old_session_id is not None and self._device_latest_session.get(normalized_device_id) == old_session_id:
                self._device_latest_session.pop(normalized_device_id, None)

    @staticmethod
    def _coerce_raw_event(event: OnlineMrRawEvent | OnlineMrEvent) -> OnlineMrRawEvent:
        if isinstance(event, OnlineMrRawEvent):
            return event
        return OnlineMrRawEvent(
            timestamp=event.timestamp,
            session_id=event.session_id,
            device_id=event.device_id,
            source=event.source,
            raw=str(event.raw or ""),
            task_type=str(event.payload.get("task_type") or ""),
        )

    @staticmethod
    def _coerce_parsed_event(event: OnlineMrParsedEvent | OnlineMrEvent) -> OnlineMrParsedEvent:
        if isinstance(event, OnlineMrParsedEvent):
            return event
        return OnlineMrParsedEvent(
            timestamp=event.timestamp,
            session_id=event.session_id,
            device_id=event.device_id,
            module=event.module,
            payload=dict(event.payload),
            raw=event.raw,
        )
