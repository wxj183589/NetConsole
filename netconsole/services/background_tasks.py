from __future__ import annotations

from typing import Any

from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, CancelCallback, ProgressCallback
from netconsole.services.job_center.job_registry import dispatch_job


def run_background_task(
    job: BackgroundJob,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> dict[str, Any]:
    # 兼容入口：所有后台任务统一委托给 Job Center 注册表。
    return dispatch_job(job, progress_callback, should_cancel)


__all__ = [
    "BackgroundTaskCancelled",
    "CancelCallback",
    "ProgressCallback",
    "run_background_task",
]
