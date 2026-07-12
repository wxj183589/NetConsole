from __future__ import annotations

import json
from pathlib import Path

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.online_mr.collection_models import collection_config_from_payload
from netconsole.services.online_mr.collection_packager import OnlineMrCollectionPackager
from netconsole.services.online_mr.collection_service import OnlineMrCollectionService
from netconsole.services.online_mr_session_store import OnlineMrSessionStore


def online_mr_collection_start(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    config = collection_config_from_payload(dict(context.params.get("config") or {}), context.paths)
    service = OnlineMrCollectionService(OnlineMrSessionStore(context.paths))
    return service.run(
        config,
        progress=context.progress,
        should_cancel=context.should_cancel,
        package_on_stop=bool(context.params.get("package_on_stop", True)),
    )


def online_mr_collection_status(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    session_dir = Path(str(context.params.get("session_dir") or ""))
    meta_path = session_dir / "session_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"在线 MR 会话状态不存在：{meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def online_mr_collection_package(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    session_dir = Path(str(context.params.get("session_dir") or ""))
    context.progress("online_mr_package", 0, 1, "正在打包在线 MR 会话")
    output = OnlineMrCollectionPackager().package(session_dir, should_cancel=context.should_cancel)
    context.progress("online_mr_package", 1, 1, "在线 MR 会话打包完成")
    return {"session_dir": str(session_dir), "package_path": str(output)}

vehicle_mr_mapping_import = legacy_handler(legacy_tasks._vehicle_mr_mapping_import)
vehicle_mr_mapping_load = legacy_handler(legacy_tasks._vehicle_mr_mapping_load)
vehicle_mr_mapping_save = legacy_handler(legacy_tasks._vehicle_mr_mapping_save)
vehicle_mr_online_refresh_all = legacy_handler(legacy_tasks._vehicle_mr_online_refresh_all)
vehicle_mr_ap_mapping_refresh = legacy_handler(legacy_tasks._vehicle_mr_ap_mapping_refresh)
vehicle_mr_event_page = legacy_handler(legacy_tasks._vehicle_mr_event_page)
vehicle_mr_history_query = legacy_handler(legacy_tasks._vehicle_mr_history_query)
online_mr_parse = legacy_handler(legacy_tasks._online_mr_parse)
online_mr_report_export = legacy_handler(legacy_tasks._online_mr_report_export)
online_mr_collection_devices_refresh = legacy_handler(legacy_tasks._online_mr_collection_devices_refresh)
online_mr_mark_stale_sessions = legacy_handler(legacy_tasks._online_mr_mark_stale_sessions)

HANDLERS = {
    name: globals()[name]
    for name in (
        "vehicle_mr_mapping_import",
        "vehicle_mr_mapping_load",
        "vehicle_mr_mapping_save",
        "vehicle_mr_online_refresh_all",
        "vehicle_mr_ap_mapping_refresh",
        "vehicle_mr_event_page",
        "vehicle_mr_history_query",
        "online_mr_parse",
        "online_mr_report_export",
        "online_mr_collection_devices_refresh",
        "online_mr_mark_stale_sessions",
        "online_mr_collection_start",
        "online_mr_collection_status",
        "online_mr_collection_package",
    )
}
