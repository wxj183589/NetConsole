from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from netconsole.services.job_center.job_context import CancelCallback, JobContext, ProgressCallback
from netconsole.services.job_center.job_models import JobSpec
from netconsole.services.job_center.sensitive_bootstrap import SensitiveBootstrap

JobHandler = Callable[[JobContext], dict[str, Any]]
_REGISTRY: dict[str, JobHandler] = {}
_DEFAULTS_LOADED = False


def register_handler(task_type: str, handler: JobHandler) -> None:
    key = str(task_type or "").strip()
    if not key:
        raise ValueError("注册后台任务时缺少 task_type")
    existing = _REGISTRY.get(key)
    if existing is not None and existing is not handler:
        raise ValueError(f"后台任务类型重复注册：{key}")
    _REGISTRY[key] = handler


def register_handlers(handlers: Mapping[str, JobHandler]) -> None:
    for task_type, handler in handlers.items():
        register_handler(task_type, handler)


def job_handler(task_type: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(handler: JobHandler) -> JobHandler:
        register_handler(task_type, handler)
        return handler

    return decorator


def _load_defaults() -> None:
    global _DEFAULTS_LOADED
    if _DEFAULTS_LOADED:
        return
    from netconsole.services.job_center.handlers import builtin_handlers

    register_handlers(builtin_handlers())
    _DEFAULTS_LOADED = True


def get_handler(task_type: str) -> JobHandler:
    _load_defaults()
    key = str(task_type or "")
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise ValueError(f"不支持的后台任务类型：{key}") from exc


def registered_task_types() -> tuple[str, ...]:
    _load_defaults()
    return tuple(sorted(_REGISTRY))


def dispatch_job(
    job: JobSpec,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    sensitive_bootstrap: SensitiveBootstrap | None = None,
) -> dict[str, Any]:
    job.validate()
    context = JobContext.from_job(job, progress_callback, should_cancel, sensitive_bootstrap)
    return get_handler(job.task_type)(context)
