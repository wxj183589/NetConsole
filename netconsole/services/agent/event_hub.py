from __future__ import annotations

import asyncio
import queue
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


class AgentEventSubscription:
    def __init__(self, event_queue: queue.Queue[dict[str, Any]], close: Callable[[], None]) -> None:
        self.queue = event_queue
        self._close = close

    def close(self) -> None:
        self._close()


class AgentEventHub:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._streams: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def publish(self, event_type: str, agent_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex,
            "type": event_type,
            "agent_id": agent_id,
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "payload": dict(payload or {}),
        }
        with self._lock:
            subscribers = list(self._subscribers)
            streams = list(self._streams)
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                continue
        for stream in streams:
            try:
                stream.put_nowait(event)
            except queue.Full:
                try:
                    stream.get_nowait()
                    stream.put_nowait(event)
                except (queue.Empty, queue.Full):
                    continue
        return event

    def subscribe_stream(self, maxsize: int = 200) -> AgentEventSubscription:
        event_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(1, maxsize))
        with self._lock:
            self._streams.append(event_queue)

        def close() -> None:
            with self._lock:
                if event_queue in self._streams:
                    self._streams.remove(event_queue)

        return AgentEventSubscription(event_queue, close)

    @staticmethod
    async def next_event(subscription: AgentEventSubscription, timeout: float = 15.0) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, timeout)
        while loop.time() < deadline:
            try:
                return subscription.queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
        return None
