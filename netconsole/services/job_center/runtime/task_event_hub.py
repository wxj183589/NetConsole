from __future__ import annotations

import queue
import uuid
from collections.abc import Callable
from threading import RLock

from netconsole.models.task_snapshot import TaskEvent, utc_now_iso


TaskEventHandler = Callable[[dict[str, object]], None]


class TaskEventSubscription:
    def __init__(self, hub: "TaskEventHub", event_queue: queue.Queue[dict[str, object]]) -> None:
        self._hub = hub
        self._queue = event_queue

    def get(self, timeout: float = 1.0) -> dict[str, object]:
        return self._queue.get(timeout=timeout)

    def close(self) -> None:
        self._hub._close_stream(self._queue)


class TaskEventHub:
    def __init__(self) -> None:
        self._handlers: list[TaskEventHandler] = []
        self._streams: list[queue.Queue[dict[str, object]]] = []
        self._lock = RLock()

    def subscribe(self, handler: TaskEventHandler) -> Callable[[], None]:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

        def unsubscribe() -> None:
            self.unsubscribe(handler)

        return unsubscribe

    def unsubscribe(self, handler: TaskEventHandler) -> None:
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def open_stream(self, *, max_events: int = 1000) -> TaskEventSubscription:
        event_queue: queue.Queue[dict[str, object]] = queue.Queue(maxsize=max(1, max_events))
        with self._lock:
            self._streams.append(event_queue)
        return TaskEventSubscription(self, event_queue)

    def publish(self, event: dict[str, object], *, source: str = "service") -> dict[str, object]:
        envelope = self._normalize(event, source=source)
        with self._lock:
            handlers = tuple(self._handlers)
            streams = tuple(self._streams)
        for handler in handlers:
            try:
                handler(dict(envelope))
            except Exception:
                continue
        for stream in streams:
            self._put_latest(stream, envelope)
        return envelope

    def _close_stream(self, event_queue: queue.Queue[dict[str, object]]) -> None:
        with self._lock:
            if event_queue in self._streams:
                self._streams.remove(event_queue)

    @staticmethod
    def _put_latest(event_queue: queue.Queue[dict[str, object]], event: dict[str, object]) -> None:
        try:
            event_queue.put_nowait(dict(event))
        except queue.Full:
            try:
                event_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                event_queue.put_nowait(dict(event))
            except queue.Full:
                pass

    @staticmethod
    def _normalize(event: dict[str, object], *, source: str) -> dict[str, object]:
        if {"id", "task_id", "type", "time", "payload"} <= event.keys():
            return dict(event)
        payload = dict(event)
        task_id = str(payload.get("job_id") or payload.get("task_id") or "")
        event_type = str(payload.get("type") or "log")
        return TaskEvent(
            event_id=uuid.uuid4().hex,
            task_id=task_id,
            type=event_type,
            time=utc_now_iso(),
            payload=payload,
            source=source,
        ).to_dict()
