from __future__ import annotations

from datetime import datetime

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.raw_lifecycle import (
    GroundRawDataLifecycleService,
    GroundRawLifecycleError,
    GroundSyslogDeletionPlan,
)
from netconsole.services.job_center.job_context import JobContext


def ground_syslog_delete(context: JobContext) -> dict[str, object]:
    site_id = str(context.params.get("site_id") or "").strip()
    operation_id = str(
        context.params.get("operation_id") or ""
    ).strip()
    if not site_id or not operation_id:
        raise ValueError("Syslog 删除任务缺少局点或操作编号")
    repository = GroundUnattendedRepository(
        context.paths.ground_unattended_db_path(site_id),
        site_id=site_id,
    )
    plan = GroundSyslogDeletionPlan.from_dict(
        dict(context.params.get("plan") or {})
    )
    lifecycle = GroundRawDataLifecycleService(repository)

    def progress(
        stage: str,
        current: int,
        total: int,
        message: str,
    ) -> None:
        repository.update_delete_operation(
            operation_id,
            status=stage,
        )
        context.progress(stage, current, total, message)

    try:
        result = lifecycle.execute_syslog_deletion(
            plan,
            operation_id=operation_id,
            progress=progress,
            check_cancelled=context.check_cancelled,
        )
    except GroundRawLifecycleError as exc:
        repository.update_delete_operation(
            operation_id,
            status="FAILED",
            completed_at=_now(),
            failure_code=exc.code,
            failure_message=str(exc)[:500],
        )
        raise
    except Exception as exc:
        code = (
            str(exc)
            if str(exc).startswith("RAW_")
            else exc.__class__.__name__
        )
        repository.update_delete_operation(
            operation_id,
            status="FAILED",
            completed_at=_now(),
            failure_code=code[:100],
            failure_message=str(exc)[:500],
        )
        raise
    repository.update_delete_operation(
        operation_id,
        status="COMPLETED",
        completed_at=_now(),
        deleted_record_count=int(result["deleted_record_count"]),
        deleted_event_count=int(result["deleted_event_count"]),
        revision_after=result["revision_after"],
    )
    context.progress(
        "COMPLETED",
        int(result["affected_file_count"]),
        int(result["affected_file_count"]),
        "Syslog 原始记录与派生事件清理完成",
    )
    return {
        **result,
        "operation_id": operation_id,
        "run_id": plan.run_id,
    }


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


HANDLERS = {
    "ground_syslog_delete": ground_syslog_delete,
}


__all__ = ["HANDLERS", "ground_syslog_delete"]
