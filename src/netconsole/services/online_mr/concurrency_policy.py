from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from netconsole.models.api.online_mr import OnlineMrOperationSnapshotDTO
from netconsole.models.online_mr_application import OnlineMrPhase
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)


_STARTING_PHASES = {
    OnlineMrPhase.VALIDATING,
    OnlineMrPhase.PREPARING_TASK,
    OnlineMrPhase.PREPARING_SESSION,
    OnlineMrPhase.CONNECTING,
    OnlineMrPhase.STARTING_COLLECTION,
}
_FINALIZING_PHASES = {
    OnlineMrPhase.STOPPING_TRAFFIC,
    OnlineMrPhase.STOPPING_COLLECTION,
    OnlineMrPhase.FINALIZING,
    OnlineMrPhase.PARSING,
    OnlineMrPhase.PACKAGING,
}


@dataclass(frozen=True)
class OnlineMrConcurrencyBudget:
    max_active_mrs: int = 4
    max_starting_mrs: int = 2
    max_finalizing_mrs: int = 2


@dataclass(frozen=True)
class OnlineMrAllocation:
    operation: OnlineMrOperationSnapshotDTO
    owner: str

    @property
    def automated(self) -> bool:
        return self.owner == "ground_unattended"


@dataclass(frozen=True)
class OnlineMrConcurrencyDecision:
    allowed: bool
    code: str = ""
    message: str = ""


class OnlineMrConcurrencyPolicy:
    """人工与无人值守共用的设备互斥和资源预算事实源。"""

    def __init__(self, task_service: TaskApplicationService) -> None:
        self.task_service = task_service

    def allocations(
        self,
        site_id: str,
        operations: Iterable[OnlineMrOperationSnapshotDTO],
    ) -> list[OnlineMrAllocation]:
        repository = self.task_service.repository(site_id)
        result = []
        for operation in operations:
            if operation.phase is OnlineMrPhase.TERMINAL:
                continue
            task = repository.get(operation.controller_task_id)
            result.append(
                OnlineMrAllocation(operation, str(task.owner if task else ""))
            )
        return result

    def can_start(
        self,
        *,
        site_id: str,
        device_id: int | str,
        operations: Iterable[OnlineMrOperationSnapshotDTO],
        budget: OnlineMrConcurrencyBudget,
        automated: bool,
    ) -> OnlineMrConcurrencyDecision:
        allocations = self.allocations(site_id, operations)
        if any(str(item.operation.device_id) == str(device_id) for item in allocations):
            return OnlineMrConcurrencyDecision(
                False, "MR_ALREADY_ACTIVE", "同一 MR 已有采集任务"
            )
        if len(allocations) >= max(1, int(budget.max_active_mrs)):
            return OnlineMrConcurrencyDecision(
                False, "MR_CAPACITY_EXHAUSTED", "Online MR 活动资源预算已满"
            )
        starting = sum(item.operation.phase in _STARTING_PHASES for item in allocations)
        if starting >= max(1, int(budget.max_starting_mrs)):
            return OnlineMrConcurrencyDecision(
                False, "MR_STARTING_CAPACITY_EXHAUSTED", "Online MR 启动并发预算已满"
            )
        finalizing = sum(
            item.operation.phase in _FINALIZING_PHASES for item in allocations
        )
        if automated and finalizing >= max(1, int(budget.max_finalizing_mrs)):
            return OnlineMrConcurrencyDecision(
                False,
                "MR_FINALIZING_CAPACITY_EXHAUSTED",
                "Online MR 最终化并发预算已满",
            )
        return OnlineMrConcurrencyDecision(True)


__all__ = [
    "OnlineMrAllocation",
    "OnlineMrConcurrencyBudget",
    "OnlineMrConcurrencyDecision",
    "OnlineMrConcurrencyPolicy",
]
