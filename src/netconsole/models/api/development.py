from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DevelopmentRuntimeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_mode: str
    backend_ready: bool
    data_root: str = "<redacted>"
    frontend_mode: str
    active_tasks: int = Field(ge=0)
    agent_controller_ready: bool
    traffic_supervisor_ready: bool
    version: str
