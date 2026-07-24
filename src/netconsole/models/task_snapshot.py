from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from netconsole.models.task_state import TaskState


CURRENT_TEXT_SCHEMA_VERSION = 2
TEXT_INTEGRITY_VALUES = frozenset(
    {"ok", "current_corrupted", "historical_corrupted", "unknown_corrupted"}
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    task_type: str
    task_name: str
    status: TaskState
    created_time: str
    updated_time: str
    started_time: str = ""
    finished_time: str = ""
    progress: int = 0
    stage: str = ""
    current: int = 0
    total: int = 0
    message: str = ""
    owner: str = ""
    device: str = ""
    agent: str = ""
    result_path: str = ""
    error_message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    source: str = "local"
    site_name: str = "demo"
    owner_pid: int = 0
    resource_keys: list[str] = field(default_factory=list)
    text_integrity: str = "ok"
    text_integrity_reason: str = ""
    text_integrity_updated_at: str = ""
    text_schema_version: int = CURRENT_TEXT_SCHEMA_VERSION
    producer_kind: str = "local_backend"
    producer_version: str = "unknown"
    producer_commit: str = "unknown"


@dataclass(frozen=True)
class TaskEvent:
    event_id: str
    task_id: str
    type: str
    time: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "service"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "task_id": self.task_id,
            "type": self.type,
            "time": self.time,
            "source": self.source,
            "payload": dict(self.payload),
        }
