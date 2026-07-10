from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QWidget

from netconsole.core.paths import PathResolver
from netconsole.models.snmp_models import SnmpCollectionRequest
from netconsole.services.background_job import BackgroundJob
from netconsole.services.snmp.request_builder import collection_request_to_payload
from netconsole.ui.job_action_helper import submit_background_job


EventCallback = Callable[[dict[str, Any]], None]


def submit_snmp_collection(
    parent: QWidget,
    request: SnmpCollectionRequest,
    *,
    site_name: str,
    paths: PathResolver,
    on_progress: EventCallback | None = None,
    on_finished: EventCallback | None = None,
    on_failed: EventCallback | None = None,
    on_cancelled: EventCallback | None = None,
) -> str:
    cancel_grace_ms = max(1500, min(60000, int(request.timeout_ms) + 1000))
    return submit_background_job(
        parent,
        BackgroundJob(
            task_type="snmp_collection_execute",
            params={
                "site_name": site_name,
                "request": collection_request_to_payload(request),
                "cache_result": True,
                "_cancel_grace_ms": cancel_grace_ms,
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        ),
        success_title="SNMP 批量采集完成",
        progress_title="正在执行 SNMP 批量采集",
        paths=paths,
        on_progress=on_progress,
        on_finished=on_finished,
        on_failed=on_failed,
        on_cancelled=on_cancelled,
    )
