from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNAUTHORIZED = "UNAUTHORIZED"
    DISABLED = "DISABLED"


class AgentAuthenticationType(StrEnum):
    NONE = "none"
    TOKEN = "token"


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    name: str
    base_url: str
    enabled: bool = True
    authentication_type: AgentAuthenticationType = AgentAuthenticationType.NONE
    credential_reference: str = ""
    tags: list[str] = field(default_factory=list)
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    archived_at: str = ""


@dataclass(frozen=True)
class AgentRuntimeSnapshot:
    agent_id: str
    status: AgentStatus = AgentStatus.UNKNOWN
    last_seen_at: str = ""
    last_checked_at: str = ""
    latency_ms: int | None = None
    version: str = ""
    platform: str = ""
    architecture: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    last_error_code: str = ""
    last_error_message: str = ""
    updated_at: str = ""
