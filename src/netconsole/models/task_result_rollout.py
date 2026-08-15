from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskResultStorageState(StrEnum):
    LEGACY_DUAL_FULL = "LEGACY_DUAL_FULL"
    TASK_RESULTS_DUAL_WRITE = "TASK_RESULTS_DUAL_WRITE"
    TASK_RESULTS_VERIFIED = "TASK_RESULTS_VERIFIED"
    RESULT_REF_AUTHORITY = "RESULT_REF_AUTHORITY"


@dataclass(frozen=True)
class TaskResultRolloutStatus:
    state: TaskResultStorageState
    revision: int
    updated_at: str
    updated_by: str
    reason: str
    schema_version: int

    @property
    def dual_write_active(self) -> bool:
        return self.state in {
            TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
            TaskResultStorageState.TASK_RESULTS_VERIFIED,
        }

    @property
    def ref_authority_active(self) -> bool:
        return self.state == TaskResultStorageState.RESULT_REF_AUTHORITY


__all__ = ["TaskResultRolloutStatus", "TaskResultStorageState"]
