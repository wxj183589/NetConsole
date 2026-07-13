from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, SecretStr

from netconsole.models.agent import AgentAuthenticationType, AgentStatus
from netconsole.models.api.common import ApiModel


class AgentCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=8, max_length=500)
    enabled: bool = True
    authentication_type: AgentAuthenticationType = AgentAuthenticationType.NONE
    token: SecretStr | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=1000)


class AgentUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    enabled: bool | None = None
    authentication_type: AgentAuthenticationType | None = None
    token: SecretStr | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=1000)


class AgentProbeRequest(ApiModel):
    base_url: str = Field(min_length=8, max_length=500)
    authentication_type: AgentAuthenticationType = AgentAuthenticationType.NONE
    token: SecretStr | None = None


class AgentDTO(ApiModel):
    agent_id: str
    name: str
    base_url: str
    enabled: bool
    authentication_type: AgentAuthenticationType
    has_credential: bool
    tags: list[str] = Field(default_factory=list)
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: AgentStatus = AgentStatus.UNKNOWN
    last_seen_at: str = ""
    last_checked_at: str = ""
    latency_ms: int | None = None
    version: str = ""
    platform: str = ""
    architecture: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)
    last_error_code: str = ""
    last_error_message: str = ""


class AgentProbeDTO(ApiModel):
    remote_agent_id: str
    remote_name: str = ""
    version: str
    platform: str
    architecture: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int


class AgentDeleteDTO(ApiModel):
    agent_id: str
    archived: bool


class AgentEventDTO(ApiModel):
    id: str
    type: str
    agent_id: str
    time: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentStatusDTO(ApiModel):
    """阶段 0 DTO 兼容层；新接口使用 AgentDTO。"""

    agent_id: str
    name: str
    status: str
    version: str = ""
    os: str = ""
    arch: str = ""
    current_tasks: int = 0


class AgentRemoteStatusDTO(ApiModel):
    agent_id: str
    agent_name: str = ""
    version: str
    os: str
    arch: str
    listen: str = ""
    uptime: str = ""
    current_tasks: int = 0
    task_count: int = 0
    package_count: int = 0
    data_dir: str = ""
    package_dir: str = ""
    power: dict[str, Any] = Field(default_factory=dict)
    disk: dict[str, Any] = Field(default_factory=dict)


class AgentToolFileDTO(ApiModel):
    name: str
    exists: bool = False


class AgentToolStatusDTO(ApiModel):
    exists: bool = False
    ready: bool = False
    path: str = ""
    work_dir: str = ""
    version: str = ""
    warning: str = ""
    required_files: list[AgentToolFileDTO] = Field(default_factory=list)


class AgentToolsStatusDTO(ApiModel):
    iperf3: AgentToolStatusDTO
    fping: AgentToolStatusDTO
    mr_collector: AgentToolStatusDTO


class AgentRemoteTaskDTO(ApiModel):
    task_id: str
    task_type: str
    status: str
    created_at: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    package_id: str = ""
    package_download_url: str = ""
    error_code: str = ""
    error_message: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class AgentRemoteTaskLogsDTO(ApiModel):
    task_id: str
    lines: list[str] = Field(default_factory=list)


class AgentRemotePackageDTO(ApiModel):
    package_id: str
    task_id: str = ""
    task_type: str = ""
    start_time: str = ""
    end_time: str = ""
    size: int = Field(default=0, ge=0)
    package_download_url: str = ""
