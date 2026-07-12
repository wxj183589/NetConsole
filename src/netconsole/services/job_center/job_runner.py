from __future__ import annotations

import traceback

from netconsole.services.job_center.job_context import BackgroundTaskCancelled, CancelCallback, ProgressCallback
from netconsole.services.job_center.job_models import JobResult, JobSpec
from netconsole.services.job_center.job_registry import dispatch_job


class JobRunner:
    def run(
        self,
        job: JobSpec,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> JobResult:
        try:
            result = dispatch_job(job, progress_callback, should_cancel)
            return JobResult(job.job_id, True, dict(result or {}), message="后台任务完成")
        except BackgroundTaskCancelled as exc:
            return JobResult(job.job_id, False, message=str(exc), error=str(exc), cancelled=True)
        except Exception as exc:
            return JobResult(
                job.job_id,
                False,
                message=str(exc) or exc.__class__.__name__,
                error=str(exc) or exc.__class__.__name__,
                traceback=traceback.format_exc(),
            )


def run_job(
    job: JobSpec,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> JobResult:
    return JobRunner().run(job, progress_callback, should_cancel)
