from __future__ import annotations

import traceback

from netconsole.services.job_center.job_context import BackgroundTaskCancelled, CancelCallback, ProgressCallback
from netconsole.services.job_center.job_models import JobResult, JobSpec
from netconsole.services.job_center.job_registry import dispatch_job
from netconsole.services.job_center.sensitive_bootstrap import SensitiveBootstrap, redact_sensitive_values


class JobRunner:
    def run(
        self,
        job: JobSpec,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        sensitive_bootstrap: SensitiveBootstrap | None = None,
    ) -> JobResult:
        secret_values: tuple[str, ...] = ()
        if sensitive_bootstrap is not None:
            values = sensitive_bootstrap.consume()
            secret_values = tuple(values.values())
            sensitive_bootstrap = SensitiveBootstrap(values)
        try:
            result = dispatch_job(job, progress_callback, should_cancel, sensitive_bootstrap)
            safe_result = redact_sensitive_values(dict(result or {}), secret_values)
            terminal_state = str(safe_result.pop("terminal_state", "") or "").strip().upper()
            completion_message = str(
                safe_result.pop("completion_message", "") or ""
            ).strip()
            return JobResult(
                job.job_id,
                True,
                safe_result,
                message=completion_message or _terminal_message(terminal_state),
                terminal_state=terminal_state,
            )
        except BackgroundTaskCancelled as exc:
            message = str(redact_sensitive_values(str(exc), secret_values))
            return JobResult(job.job_id, False, message=message, error=message, cancelled=True)
        except Exception as exc:
            message = str(redact_sensitive_values(str(exc) or exc.__class__.__name__, secret_values))
            return JobResult(
                job.job_id,
                False,
                message=message,
                error=message,
                traceback=str(redact_sensitive_values(traceback.format_exc(), secret_values)),
            )
        finally:
            if sensitive_bootstrap is not None:
                sensitive_bootstrap.clear()


def run_job(
    job: JobSpec,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    sensitive_bootstrap: SensitiveBootstrap | None = None,
) -> JobResult:
    return JobRunner().run(job, progress_callback, should_cancel, sensitive_bootstrap)


def _terminal_message(terminal_state: str) -> str:
    if terminal_state == "FAILED":
        return "后台任务失败"
    if terminal_state == "CANCELLED":
        return "后台任务已取消"
    return "后台任务完成"
