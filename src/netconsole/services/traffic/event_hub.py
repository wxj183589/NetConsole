from __future__ import annotations

import queue
import threading
import time
from collections import deque

from netconsole.models.traffic_test import TrafficEvent, TrafficEventType


_DROPPABLE_TYPES = frozenset({TrafficEventType.STDOUT, TrafficEventType.STDERR, TrafficEventType.SAMPLE})


class TrafficEventStreamClosed(RuntimeError):
    pass


class TrafficEventStreamOverflow(RuntimeError):
    pass


class TrafficEventSubscription:
    def __init__(self, hub: TrafficEventHub, max_events: int) -> None:
        self._hub = hub
        self._max_events = max(1, int(max_events))
        self._events: deque[TrafficEvent] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._overflowed = False

    def get(self, timeout: float = 1.0) -> TrafficEvent:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while not self._events:
                if self._overflowed:
                    raise TrafficEventStreamOverflow("traffic event subscriber fell behind; recover from EventStore")
                if self._closed:
                    raise TrafficEventStreamClosed("traffic event subscription is closed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self._condition.wait(remaining)
            return self._events.popleft()

    def close(self) -> None:
        self._hub._close(self)

    def _offer(self, event: TrafficEvent) -> bool:
        with self._condition:
            if self._closed:
                return False
            if len(self._events) >= self._max_events:
                droppable_index = next(
                    (index for index, current in enumerate(self._events) if current.type in _DROPPABLE_TYPES),
                    None,
                )
                if droppable_index is not None:
                    del self._events[droppable_index]
                elif event.type in _DROPPABLE_TYPES:
                    return True
                else:
                    self._overflowed = True
                    self._closed = True
                    self._condition.notify_all()
                    return False
            self._events.append(event)
            self._condition.notify()
            return True

    def _mark_closed(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class TrafficEventHub:
    def __init__(self) -> None:
        self._subscriptions: list[TrafficEventSubscription] = []
        self._lock = threading.Lock()

    def open_stream(self, *, max_events: int = 1_000) -> TrafficEventSubscription:
        subscription = TrafficEventSubscription(self, max_events)
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def publish(self, event: TrafficEvent) -> TrafficEvent:
        if event.sequence <= 0:
            raise ValueError("TrafficEvent must be persisted and sequenced before publish")
        with self._lock:
            subscriptions = tuple(self._subscriptions)
        stale: list[TrafficEventSubscription] = []
        for subscription in subscriptions:
            if not subscription._offer(event):
                stale.append(subscription)
        if stale:
            with self._lock:
                self._subscriptions = [item for item in self._subscriptions if item not in stale]
        return event

    def _close(self, subscription: TrafficEventSubscription) -> None:
        with self._lock:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)
        subscription._mark_closed()
