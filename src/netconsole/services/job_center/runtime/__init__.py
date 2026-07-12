from __future__ import annotations

from netconsole.services.job_center.runtime.task_event_bus import TaskEventBus
from netconsole.services.job_center.runtime.task_event_hub import TaskEventHub
from netconsole.services.job_center.runtime.task_runtime import TaskLaunch, TaskRuntime
from netconsole.services.job_center.runtime.task_state import TaskState

__all__ = ["TaskApplicationService", "TaskEventBus", "TaskEventHub", "TaskLaunch", "TaskRuntime", "TaskState"]


def __getattr__(name: str):
    if name == "TaskApplicationService":
        from netconsole.services.job_center.task_application_service import TaskApplicationService

        return TaskApplicationService
    raise AttributeError(name)
