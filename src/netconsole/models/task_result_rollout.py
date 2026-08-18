from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskResultStorageState(StrEnum):
    LEGACY_DUAL_FULL = "LEGACY_DUAL_FULL"
    TASK_RESULTS_DUAL_WRITE = "TASK_RESULTS_DUAL_WRITE"
    TASK_RESULTS_VERIFIED = "TASK_RESULTS_VERIFIED"
    RESULT_REF_AUTHORITY = "RESULT_REF_AUTHORITY"


# The current runtime deliberately remains on the legacy full-result writer.
# Persisted rollout rows are historical maintenance state and do not change it.
TASK_RESULT_RUNTIME_WRITE_STATE = TaskResultStorageState.LEGACY_DUAL_FULL


@dataclass(frozen=True)
class TaskResultRolloutStatus:
    state: TaskResultStorageState
    revision: int
    updated_at: str
    updated_by: str
    reason: str
    schema_version: int

    @property
    def persisted_rollout_state(self) -> str:
        return self.state.value

    @property
    def persisted_dual_write_active(self) -> bool:
        return self.state in {
            TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
            TaskResultStorageState.TASK_RESULTS_VERIFIED,
        }

    @property
    def persisted_ref_authority_active(self) -> bool:
        return self.state == TaskResultStorageState.RESULT_REF_AUTHORITY

    @property
    def runtime_write_state(self) -> TaskResultStorageState:
        return TASK_RESULT_RUNTIME_WRITE_STATE

    @property
    def runtime_dual_write_active(self) -> bool:
        return self.runtime_write_state in {
            TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
            TaskResultStorageState.TASK_RESULTS_VERIFIED,
        }

    @property
    def runtime_ref_authority_active(self) -> bool:
        return self.runtime_write_state == TaskResultStorageState.RESULT_REF_AUTHORITY

    @property
    def dual_write_active(self) -> bool:
        """Compatibility alias for the effective runtime writer state."""

        return self.runtime_dual_write_active

    @property
    def ref_authority_active(self) -> bool:
        """Compatibility alias for the effective runtime writer state."""

        return self.runtime_ref_authority_active


__all__ = [
    "TASK_RESULT_RUNTIME_WRITE_STATE",
    "TaskResultRolloutStatus",
    "TaskResultStorageState",
]
