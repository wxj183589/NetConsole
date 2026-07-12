from __future__ import annotations

from collections.abc import Callable
from typing import Any

from netconsole.services.job_center.job_context import CancelCallback, JobContext, ProgressCallback
from netconsole.services.job_center.job_registry import JobHandler

LegacyHandler = Callable[[dict[str, Any], ProgressCallback | None, CancelCallback | None], dict[str, Any]]


def legacy_handler(function: LegacyHandler) -> JobHandler:
    def handler(context: JobContext) -> dict[str, Any]:
        return function(context.params, context.progress_callback, context.should_cancel)

    handler.__name__ = function.__name__.removeprefix("_")
    handler.__doc__ = f"兼容委托到 {function.__module__}.{function.__name__}。"
    return handler
