from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from netconsole.core.paths import PathResolver
from netconsole.services.job_center.job_models import JobSpec

ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class BackgroundTaskCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class JobContext:
    job_id: str
    task_type: str
    params: dict[str, Any]
    progress_callback: ProgressCallback | None
    should_cancel: CancelCallback | None
    paths: PathResolver

    @classmethod
    def from_job(
        cls,
        job: JobSpec,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> "JobContext":
        params = dict(job.params or {})
        app_root = str(params.get("app_root") or "").strip()
        data_root = str(params.get("data_root") or "").strip()
        paths = PathResolver(
            app_root=Path(app_root) if app_root else None,
            data_root=Path(data_root) if data_root else None,
        )
        return cls(job.job_id, job.task_type, params, progress_callback, should_cancel, paths)

    def progress(self, stage: str, current: int, total: int, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(stage, int(current or 0), int(total or 0), message)

    def check_cancelled(self) -> None:
        if self.should_cancel is not None and self.should_cancel():
            raise BackgroundTaskCancelled("后台任务已取消")
