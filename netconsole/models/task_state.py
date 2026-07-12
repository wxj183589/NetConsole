from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_TASK_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})
