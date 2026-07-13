from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    mr_id: str
    mr_name: str
    executor_kind: OnlineMrExecutorKind
    phase: OnlineMrPhase
    mapping_state: OnlineMrMappingState
    created_at: str
    updated_at: str
    session_id: str | None = None
    agent_id: str = ""
    terminal_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_minutes: float | None = None
    stop_reason: str = ""
    force_stopped: bool = False
    error_summary: str = ""
    error_code: str = ""
    error_message: str = ""


def calculate_duration_minutes(
    started_at: str | datetime | None,
    ended_at: str | datetime | None,
) -> float:
    def parse(value: str | datetime | None) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))

    try:
        start = parse(started_at)
        end = parse(ended_at)
        if (start.tzinfo is None) != (end.tzinfo is None):
            start = start.replace(tzinfo=None)
            end = end.replace(tzinfo=None)
        return round(max(0.0, (end - start).total_seconds()) / 60.0, 3)
    except ValueError:
        return 0.0


__all__ = [
    "OnlineMrExecutorKind",
    "OnlineMrMappingState",
    "OnlineMrPhase",
    "OnlineMrStartRequest",
    "OnlineMrTaskSessionMapping",
    "calculate_duration_minutes",
]
