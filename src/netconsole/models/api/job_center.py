from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class JobCenterTaskDTO(ApiModel):
    id: str
    type: str
    name: str
    status: str
    progress: int = 0
    phase: str = ""
    stage: str = ""
    message: str = ""
    site_name: str = ""
    owner: str = ""
    executor: str = "LOCAL"
    source: str = "local"
    device_id: str = ""
    device_name: str = ""
    agent: str = ""
    mr_name: str = ""
    session_id: str = ""
    mapping_state: str = ""
    created_time: str = ""
    started_time: str = ""
    finished_time: str = ""
    updated_time: str = ""
    duration_seconds: float = 0.0
    error_code: str = ""
    error_summary: str = ""
    has_warning: bool = False
    result_path: str = ""
    output_dir: str = ""
    package_path: str = ""
    session_path: str = ""


class JobCenterSummaryDTO(ApiModel):
    total: int = 0
    active: int = 0
    completed: int = 0
    failed: int = 0
    warning: int = 0


class JobCenterLogLineDTO(ApiModel):
    sequence: int
    time: str
    level: str = "INFO"
    type: str
    source: str = "service"
    message: str


class JobCenterLogTailDTO(ApiModel):
    task_id: str
    lines: list[JobCenterLogLineDTO] = Field(default_factory=list)
    message: str = ""


__all__ = [
    "JobCenterLogLineDTO",
    "JobCenterLogTailDTO",
    "JobCenterSummaryDTO",
    "JobCenterTaskDTO",
]
