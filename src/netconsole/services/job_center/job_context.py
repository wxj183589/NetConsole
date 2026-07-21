from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from netconsole.core.paths import PathResolver
from netconsole.services.job_center.job_models import JobSpec
from netconsole.services.job_center.sensitive_bootstrap import SensitiveBootstrap

ProgressMessage = str | Mapping[str, object]
ProgressCallback = Callable[[str, int, int, ProgressMessage], None]
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
    sensitive_bootstrap: SensitiveBootstrap | None = None

    @classmethod
    def from_job(
        cls,
        job: JobSpec,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        sensitive_bootstrap: SensitiveBootstrap | None = None,
    ) -> "JobContext":
        params = dict(job.params or {})
        app_root = str(params.get("app_root") or "").strip()
        data_root = str(params.get("data_root") or "").strip()
        paths = PathResolver(
            app_root=Path(app_root) if app_root else None,
            data_root=Path(data_root) if data_root else None,
        )
        return cls(
            job.job_id,
            job.task_type,
            params,
            progress_callback,
            should_cancel,
            paths,
            sensitive_bootstrap,
        )

    def progress(self, stage: str, current: int, total: int, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(stage, int(current or 0), int(total or 0), message)

    def structured_progress(
        self,
        stage: str,
        current: int,
        total: int,
        message: str,
        **details: object,
    ) -> None:
        payload: dict[str, object] = {"message": str(message or stage or "")}
        payload.update(details)
        if self.progress_callback is not None:
            self.progress_callback(stage, int(current or 0), int(total or 0), payload)

    def check_cancelled(self) -> None:
        if self.should_cancel is not None and self.should_cancel():
            raise BackgroundTaskCancelled("后台任务已取消")

    def consume_sensitive_bootstrap(self) -> dict[str, str]:
        if self.sensitive_bootstrap is None:
            raise RuntimeError("此任务没有敏感启动数据")
        return self.sensitive_bootstrap.consume()

    def consume_runtime_bootstrap(self) -> bytearray:
        values = self.consume_sensitive_bootstrap()
        if set(values) != {"runtime_bootstrap"}:
            raise RuntimeError("运行时启动数据类型不匹配")
        return bytearray(values["runtime_bootstrap"].encode("utf-8"))
