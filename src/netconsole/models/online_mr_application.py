from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from netconsole.models.online_mr_models import OnlineMrConnectionConfig


class OnlineMrPhase(StrEnum):
    VALIDATING = "VALIDATING"
    PREPARING_TASK = "PREPARING_TASK"
    PREPARING_SESSION = "PREPARING_SESSION"
    CONNECTING = "CONNECTING"
    STARTING_COLLECTION = "STARTING_COLLECTION"
    COLLECTING = "COLLECTING"
    STOPPING_TRAFFIC = "STOPPING_TRAFFIC"
    STOPPING_COLLECTION = "STOPPING_COLLECTION"
    FINALIZING = "FINALIZING"
    PARSING = "PARSING"
    PACKAGING = "PACKAGING"
    TERMINAL = "TERMINAL"


class OnlineMrExecutorKind(StrEnum):
    LOCAL = "LOCAL"
    AGENT = "AGENT"


class OnlineMrMappingState(StrEnum):
    PENDING_SESSION = "PENDING_SESSION"
    LINKED = "LINKED"
    TASK_ONLY_FAILED = "TASK_ONLY_FAILED"
    SESSION_ONLY_RECOVERED = "SESSION_ONLY_RECOVERED"
    STALE = "STALE"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class OnlineMrStartRequest:
    site_id: str
    device_id: int | str
    device_name: str
    mr_name: str
    config: OnlineMrConnectionConfig
    executor_kind: OnlineMrExecutorKind = OnlineMrExecutorKind.LOCAL
    agent_id: str = ""
    owner: str = "local"
    enabled_collectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class OnlineMrTaskSessionMapping:
    controller_task_id: str
    site_id: str
    device_id: str
    device_name: str
    mr_name: str
    executor_kind: OnlineMrExecutorKind
    phase: OnlineMrPhase
    mapping_state: OnlineMrMappingState
    created_at: str
    updated_at: str
    session_id: str | None = None
    agent_id: str = ""
    terminal_at: str | None = None
    error_code: str = ""
    error_message: str = ""


__all__ = [
    "OnlineMrExecutorKind",
    "OnlineMrMappingState",
    "OnlineMrPhase",
    "OnlineMrStartRequest",
    "OnlineMrTaskSessionMapping",
]
