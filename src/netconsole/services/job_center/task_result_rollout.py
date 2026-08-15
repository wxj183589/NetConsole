from __future__ import annotations

from pathlib import Path

from netconsole.models.task_result_rollout import (
    TaskResultRolloutStatus,
    TaskResultStorageState,
)
from netconsole.repositories.task_repository import TaskRepository


class TaskResultRolloutError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TaskResultRolloutService:
    """Own explicit, revision-safe transitions for one site's tasks database."""

    _ALLOWED_TRANSITIONS = frozenset(
        {
            (
                TaskResultStorageState.LEGACY_DUAL_FULL,
                TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
            ),
            (
                TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
                TaskResultStorageState.LEGACY_DUAL_FULL,
            ),
        }
    )

    def __init__(self, tasks_db: str | Path) -> None:
        self.repository = TaskRepository(tasks_db)

    def status(self) -> dict[str, object]:
        rollout = self.repository.task_result_rollout_status()
        return {
            "schema_version": rollout.schema_version,
            "task_result_storage_state": rollout.state.value,
            "revision": rollout.revision,
            "updated_at": rollout.updated_at,
            "task_results_rows": self.repository.task_result_count(),
            "dual_write_active": rollout.dual_write_active,
            "ref_authority_active": rollout.ref_authority_active,
        }

    def enable_dual_write(
        self,
        *,
        expected_revision: int,
        reason: str,
        updated_by: str,
    ) -> TaskResultRolloutStatus:
        return self._transition(
            TaskResultStorageState.TASK_RESULTS_DUAL_WRITE,
            expected_revision=expected_revision,
            reason=reason,
            updated_by=updated_by,
        )

    def disable_dual_write(
        self,
        *,
        expected_revision: int,
        reason: str,
        updated_by: str,
    ) -> TaskResultRolloutStatus:
        return self._transition(
            TaskResultStorageState.LEGACY_DUAL_FULL,
            expected_revision=expected_revision,
            reason=reason,
            updated_by=updated_by,
        )

    def transition(
        self,
        target: TaskResultStorageState,
        *,
        expected_revision: int,
        reason: str,
        updated_by: str,
    ) -> TaskResultRolloutStatus:
        """Expose the guarded model for validation without opening unsafe applies."""

        return self._transition(
            target,
            expected_revision=expected_revision,
            reason=reason,
            updated_by=updated_by,
        )

    def _transition(
        self,
        target: TaskResultStorageState,
        *,
        expected_revision: int,
        reason: str,
        updated_by: str,
    ) -> TaskResultRolloutStatus:
        current = self.repository.task_result_rollout_status()
        if current.revision != int(expected_revision):
            raise TaskResultRolloutError(
                "TASK_RESULT_ROLLOUT_REVISION_CONFLICT",
                "task result storage rollout revision changed; refresh status",
            )
        if target == TaskResultStorageState.RESULT_REF_AUTHORITY:
            raise TaskResultRolloutError(
                "TASK_RESULT_REF_AUTHORITY_DISABLED",
                "RESULT_REF_AUTHORITY requires a separate approved migration phase",
            )
        if target == TaskResultStorageState.TASK_RESULTS_VERIFIED:
            raise TaskResultRolloutError(
                "TASK_RESULT_VERIFIED_APPLY_DISABLED",
                "TASK_RESULTS_VERIFIED requires a separate validation evidence gate",
            )
        if (current.state, target) not in self._ALLOWED_TRANSITIONS:
            raise TaskResultRolloutError(
                "TASK_RESULT_ROLLOUT_TRANSITION_INVALID",
                f"task result storage transition {current.state.value} -> {target.value} is not allowed",
            )
        normalized_reason = self._required_text(reason, "reason", maximum=500)
        normalized_actor = self._required_text(updated_by, "updated_by", maximum=128)
        updated = self.repository.compare_and_set_task_result_rollout(
            expected_state=current.state,
            expected_revision=current.revision,
            target_state=target,
            updated_by=normalized_actor,
            reason=normalized_reason,
        )
        if updated is None:
            raise TaskResultRolloutError(
                "TASK_RESULT_ROLLOUT_REVISION_CONFLICT",
                "task result storage rollout revision changed; refresh status",
            )
        return updated

    @staticmethod
    def _required_text(value: str, field: str, *, maximum: int) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise TaskResultRolloutError(
                "TASK_RESULT_ROLLOUT_REASON_REQUIRED",
                f"{field} is required",
            )
        if len(normalized) > maximum or any(ord(character) < 32 for character in normalized):
            raise TaskResultRolloutError(
                "TASK_RESULT_ROLLOUT_TEXT_INVALID",
                f"{field} is invalid",
            )
        return normalized


__all__ = ["TaskResultRolloutError", "TaskResultRolloutService"]
