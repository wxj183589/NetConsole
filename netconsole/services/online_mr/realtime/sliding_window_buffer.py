from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from threading import RLock

from netconsole.services.online_mr.core.event_model import OnlineMrEvent


class SlidingWindowBuffer:
    """Maintain recent event data for realtime UI refresh."""

    def __init__(self, window_seconds: float = 5.0) -> None:
        self.window_seconds = float(window_seconds)
        self.buffer: deque[OnlineMrEvent] = deque()
        self.latest_by_module: dict[str, OnlineMrEvent] = {}
        self.last_event_time: datetime | None = None
        self._lock = RLock()

    def add(self, event: OnlineMrEvent) -> None:
        with self._lock:
            self.buffer.append(event)
            self.latest_by_module[event.module] = event
            self.last_event_time = event.timestamp
            self._trim_locked(event.timestamp)

    def get_window(self) -> list[OnlineMrEvent]:
        with self._lock:
            self._trim_locked(self.last_event_time or datetime.now())
            rows = list(self.buffer)
            present = {id(event) for event in rows}
            for event in self.latest_by_module.values():
                if id(event) not in present:
                    rows.append(event)
            rows.sort(key=lambda event: event.timestamp)
            return rows

    def clear(self) -> None:
        with self._lock:
            self.buffer.clear()
            self.latest_by_module.clear()
            self.last_event_time = None

    def _trim_locked(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self.buffer and self.buffer[0].timestamp < cutoff:
            self.buffer.popleft()
