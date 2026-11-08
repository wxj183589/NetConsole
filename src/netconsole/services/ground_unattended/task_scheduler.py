from __future__ import annotations

import heapq
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


TASK_TYPES = (
    "HEARTBEAT", "QUICK_PING", "AC_POLLING", "SYSLOG_PARSE",
    "CONFIG_BACKUP", "CONFIG_RESTORE", "REPORT_EXPORT", "HISTORY_ARCHIVE",
    "DEEP_ANALYSIS",
)


@dataclass(order=True)
class ScheduledTask:
    sort_key: tuple[int, float] = field(init=False, repr=False)
    priority: int
    created_at: float
    task_id: str = field(compare=False)
    task_type: str = field(compare=False)
    callback: Callable[[], Any] = field(compare=False, repr=False)
    status: str = field(default="QUEUED", compare=False)
    retry_count: int = field(default=0, compare=False)
    error_code: str = field(default="", compare=False)
    error_message: str = field(default="", compare=False)
    owner: str = field(default="core", compare=False)
    dedupe_key: str = field(default="", compare=False)
    cancel_requested: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        self.sort_key = (-int(self.priority), float(self.created_at))


class GroundTaskScheduler:
    """Small bounded scheduler with independent queues per business domain."""

    def __init__(self, *, capacities: Mapping[str, int] | None = None) -> None:
        self.capacities = {name: int((capacities or {}).get(name, 128)) for name in TASK_TYPES}
        self._queues: dict[str, list[ScheduledTask]] = {name: [] for name in TASK_TYPES}
        self._tasks: dict[str, ScheduledTask] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()

    def submit(
        self,
        task_type: str,
        callback: Callable[[], Any],
        *,
        priority: int = 0,
        dedupe_key: str = "",
        owner: str = "core",
    ) -> str:
        normalized = str(task_type).upper()
        if normalized not in self._queues:
            raise ValueError(f"unknown task type: {task_type}")
        with self._lock:
            if dedupe_key:
                for task in self._tasks.values():
                    if (
                        task.task_type == normalized
                        and task.status in {"QUEUED", "RUNNING"}
                        and task.dedupe_key == str(dedupe_key)
                    ):
                        return task.task_id
            queued = sum(task.status == "QUEUED" for task in self._queues[normalized])
            if queued >= self.capacities[normalized]:
                raise RuntimeError(f"{normalized}_QUEUE_FULL")
            task = ScheduledTask(
                priority=int(priority), created_at=time.monotonic(),
                task_id=f"task-{uuid.uuid4().hex}", task_type=normalized,
                callback=callback, owner=str(owner),
                dedupe_key=str(dedupe_key or ""),
            )
            heapq.heappush(self._queues[normalized], task)
            self._tasks[task.task_id] = task
            return task.task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(str(task_id))
            if task is None or task.status not in {"QUEUED", "RUNNING"}:
                return False
            task.status = "CANCELLED"
            task.cancel_requested = True
            self._cancelled.add(task.task_id)
            return True

    def run_once(self, task_type: str) -> str | None:
        normalized = str(task_type).upper()
        with self._lock:
            queue = self._queues.get(normalized)
            if queue is None:
                raise ValueError(f"unknown task type: {task_type}")
            while queue:
                task = heapq.heappop(queue)
                if task.status == "CANCELLED" or task.task_id in self._cancelled:
                    continue
                task.status = "RUNNING"
                break
            else:
                return None
        try:
            task.callback()
        except Exception as exc:
            with self._lock:
                if task.status != "CANCELLED":
                    task.status = "FAILED"
                    task.error_code = "TASK_FAILED"
                    task.error_message = f"{type(exc).__name__}: {exc}"
        else:
            with self._lock:
                if task.status != "CANCELLED":
                    task.status = "COMPLETED"
        return task.task_id

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_lengths": {
                    name: sum(task.status == "QUEUED" for task in queue)
                    for name, queue in self._queues.items()
                },
                "active_tasks": sum(task.status == "RUNNING" for task in self._tasks.values()),
                "completed_tasks": sum(task.status == "COMPLETED" for task in self._tasks.values()),
                "failed_tasks": sum(task.status == "FAILED" for task in self._tasks.values()),
                "cancelled_tasks": sum(task.status == "CANCELLED" for task in self._tasks.values()),
                "worker_count": 0,
            }
