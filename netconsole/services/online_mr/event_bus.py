from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Callable

from netconsole.services.online_mr.core.event_model import (
    EVENT_BUSY_SAMPLE,
    EVENT_FPING_V5_SAMPLE,
    EVENT_INTERFACE_SAMPLE,
    EVENT_IPERF3_ERROR,
    EVENT_IPERF3_SAMPLE,
    EVENT_MESH_SAMPLE,
    EVENT_RAW_LINE,
    EVENT_SESSION_START,
    EVENT_SESSION_STOP,
    EVENT_STATS_SAMPLE,
    OnlineMrEvent,
)


EVENT_MESH_LINK_SAMPLE = EVENT_MESH_SAMPLE
EVENT_CHANNEL_BUSY_SAMPLE = EVENT_BUSY_SAMPLE
EVENT_AP_STATS_SAMPLE = EVENT_STATS_SAMPLE
EVENT_INTERFACE_RATE_SAMPLE = EVENT_INTERFACE_SAMPLE


EventHandler = Callable[[OnlineMrEvent], None]


class OnlineMrEventBus:
    def __init__(self) -> None:
        self.subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        with self._lock:
            self.subscribers[event_type].append(handler)

    def publish(self, event: OnlineMrEvent) -> None:
        with self._lock:
            handlers = list(self.subscribers.get("*", [])) + list(self.subscribers.get(event.event_type, []))
        for handler in handlers:
            handler(event)
