from __future__ import annotations

from netconsole.models.api.common import ApiModel


class AgentStatusDTO(ApiModel):
    agent_id: str
    name: str
    status: str
    version: str = ""
    os: str = ""
    arch: str = ""
    current_tasks: int = 0
