from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Callable

from netconsole.core import app_logger


StopHandler = Callable[[], None]


@dataclass
class BackgroundTaskManager:
    _tasks: dict[str, StopHandler] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)
    app_is_exiting: bool = False

    def register(self, task_id: str, stop_handler: StopHandler) -> None:
        if self.app_is_exiting:
            app_logger.log_warning("BACKGROUND_TASK_REJECTED", task_id)
            return
        with self._lock:
            self._tasks[task_id] = stop_handler

    def unregister(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    def active_count(self) -> int:
        with self._lock:
            return len(self._tasks)

    def stop_all(self) -> None:
        self.app_is_exiting = True
        with self._lock:
            tasks = list(self._tasks.items())
            self._tasks.clear()
        for task_id, stop_handler in tasks:
            try:
                stop_handler()
                app_logger.log_info("BACKGROUND_TASK_STOPPED", task_id)
            except Exception as exc:
                app_logger.log_error("BACKGROUND_TASK_STOP_FAILED", f"{task_id}: {exc}")


background_task_manager = BackgroundTaskManager()
