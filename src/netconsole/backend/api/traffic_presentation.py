from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from netconsole.models.api.traffic import TrafficExecutionTargetRequest, TrafficRunDTO
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import ExecutionTargetDTO
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


_ACTIVE_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING}


def traffic_run_dto(run: object) -> TrafficRunDTO:
    return TrafficRunDTO(
        id=run.traffic_run_id,
        traffic_run_id=run.traffic_run_id,
        controller_task_id=run.controller_task_id,
        test_type=run.test_type,
        role=run.role,
        executor_kind=run.executor_kind,
        agent_id=run.agent_id,
        normalized_config=dict(run.normalized_config),
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        updated_at=run.updated_at,
        summary=dict(run.summary),
        error_code=run.error_code,
        error_message=run.error_message,
        raw_reference=_public_reference(run.raw_reference),
        result_reference=_public_reference(run.result_reference),
        retry_of_traffic_run_id=run.retry_of_traffic_run_id,
        parent_task_id=run.parent_task_id,
        correlation_id=run.correlation_id,
        last_event_sequence=run.last_event_sequence,
        sync_state=run.sync_state,
        cancellable=run.status in _ACTIVE_STATES,
    )


def execution_target_from_request(value: TrafficExecutionTargetRequest) -> ExecutionTargetDTO:
    try:
        return ExecutionTargetDTO(
            kind=value.kind,
            agent_id=value.agent_id.strip(),
            display_name=value.display_name.strip(),
        )
    except ValueError as exc:
        raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, str(exc)) from exc


def _public_reference(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if (
        text.casefold().startswith("file://")
        or PureWindowsPath(text).is_absolute()
        or PurePosixPath(text).is_absolute()
    ):
        return ""
    return text


__all__ = ["execution_target_from_request", "traffic_run_dto"]
