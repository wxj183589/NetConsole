from __future__ import annotations

from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.task_state import TaskState


class TaskDTO(ApiModel):
    id: str
    type: str
    name: str
    status: TaskState
    progress: int = 0
    stage: str = ""
    current: int = 0
    total: int = 0
    message: str = ""
    created_time: str
    started_time: str = ""
    finished_time: str = ""
    updated_time: str
    owner: str = ""
    device: str = ""
    agent: str = ""
    result_path: str = ""
    error_message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    source: str = "local"
    cancellable: bool = False


class TaskEventDTO(ApiModel):
    sequence: int = 0
    id: str
    task_id: str
    type: str
    time: str
    source: str = "service"
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskCancelResponse(ApiModel):
    id: str
    status: TaskState
    message: str
