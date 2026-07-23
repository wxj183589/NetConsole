from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from pydantic import SecretStr

from netconsole.models.agent import AgentAuthenticationType
from netconsole.models.online_mr_agent import OnlineMrAgentConnectionConfig
from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.agent_controller_service import OnlineMrAgentControllerService
from netconsole.services.online_mr.agent_download_service import OnlineMrAgentDownloadImportResult
from netconsole.services.online_mr.agent_http_client import OnlineMrAgentHttpClient
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.collection_models import collection_config_from_payload
from netconsole.services.online_mr.collection_packager import OnlineMrCollectionPackager
from netconsole.services.online_mr.collection_service import OnlineMrCollectionService
from netconsole.services.online_mr.session_lifecycle import OnlineMrSessionLifecycleService
from netconsole.services.online_mr_session_store import OnlineMrSessionStore

ONLINE_MR_AGENT_TOKEN_ENV = "NETCONSOLE_JOB_SECRET_ONLINE_MR_AGENT_TOKEN"


def online_mr_collection_start(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    config = collection_config_from_payload(dict(context.params.get("config") or {}), context.paths)
    service = OnlineMrCollectionService(OnlineMrSessionStore(context.paths))
    return service.run(
        config,
        progress=context.progress,
        should_cancel=context.should_cancel,
        package_on_stop=bool(context.params.get("package_on_stop", True)),
        controller_task_id=context.job_id,
        manage_traffic=bool(context.params.get("manage_traffic", False)),
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


def online_mr_mark_stale_sessions(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    site_name = str(context.params.get("site_name") or "")
    if not site_name:
        raise ValueError("Online MR 遗留会话核对缺少 site_name")
    if not context.paths.site_dir(site_name).is_dir():
        return {"changed_count": 0}
    # 当前进程本身就是受管 Worker，不能在读取映射时把父进程持有的任务
    # 误判成遗留任务。遗留任务核对只由宿主启动路径执行。
    task_service = TaskApplicationService(
        context.paths,
        site_name=site_name,
        reconcile_on_start=False,
    )
    service = OnlineMrApplicationService(
        context.paths,
        site_name=site_name,
        task_service=task_service,
    )
    try:
        changed = service.recover_mappings(site_id=site_name)
    finally:
        service.close()
    return {"changed_count": len(changed)}


def online_mr_session_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    service = OnlineMrSessionLifecycleService(context.paths)
    result = service.delete_session(
        site_id=_required_text(context, "site_id"),
        session_id=_required_text(context, "session_id"),
        session_dir=_required_text(context, "session_dir"),
        artifact_items=list(context.params.get("artifact_items") or []),
        related_task_ids=list(context.params.get("related_task_ids") or []),
        current_task_id=context.job_id,
        progress=context.progress,
    )
    return result


def online_mr_agent_packages_sync(context: JobContext) -> dict[str, object]:
    """只读查询 Agent 状态、工具和采集包，不控制远端任务。"""

    context.check_cancelled()
    context.progress("agent_connect", 0, 1, "正在连接 Agent 并同步采集包")
    result = asyncio.run(
        _online_mr_agent_service(context).sync_agent_packages(
            site_id=_required_text(context, "site_id"),
        )
    )
    context.check_cancelled()
    context.progress("agent_connect", 1, 1, "Agent 采集包同步完成")
    payload = result.model_dump(mode="json")
    payload["profile_id"] = str(context.params.get("profile_id") or "")
    return payload


def online_mr_agent_package_import(context: JobContext) -> dict[str, object]:
    """下载并导入一个既有 Agent 包；不启动、停止或删除远端任务。"""

    context.check_cancelled()
    context.progress("agent_package_import", 0, 1, "正在下载并导入 Agent 采集包")
    manual = bool(context.params.get("manual_override", False))
    result = asyncio.run(
        _online_mr_agent_service(context).download_import_agent_package(
            _required_text(context, "package_id"),
            site_id=_required_text(context, "site_id"),
            site_name=str(context.params.get("site_name") or context.params.get("site_id") or ""),
            device_id=context.params.get("device_id", "") if manual else "",
            device_name=str(context.params.get("device_name") or "") if manual else "",
            mr_id=str(context.params.get("mr_id") or "") if manual else "",
            mr_name=str(context.params.get("mr_name") or "") if manual else "",
            owner="legacy_qt_agent_package_import",
            identity_match_policy="manual_override" if manual else "strict",
            expected_host=str(context.params.get("expected_host") or "") if manual else "",
            allow_identity_override=manual,
            auto_resolve_by_ip=not manual,
            cancel_check=context.should_cancel,
        )
    )
    context.check_cancelled()
    if not result.success:
        detail = "；".join(result.errors or result.warnings) or result.error_code or "Agent 采集包导入失败"
        raise RuntimeError(detail)
    context.progress("agent_package_import", 1, 1, "Agent 采集包导入完成")
    return _download_import_result_payload(result)


def _online_mr_agent_service(context: JobContext) -> OnlineMrAgentControllerService:
    authentication_type = AgentAuthenticationType(
        str(context.params.get("authentication_type") or AgentAuthenticationType.NONE.value)
    )
    token = os.environ.get(ONLINE_MR_AGENT_TOKEN_ENV, "") if authentication_type is AgentAuthenticationType.TOKEN else ""
    if authentication_type is AgentAuthenticationType.TOKEN and not token:
        raise ValueError("Agent Token 未填写或未加载")
    client = OnlineMrAgentHttpClient(
        OnlineMrAgentConnectionConfig(
            base_url=_required_text(context, "base_url"),
            token=SecretStr(token),
        )
    )
    return OnlineMrAgentControllerService(context.paths, client=client)


def _download_import_result_payload(result: OnlineMrAgentDownloadImportResult) -> dict[str, object]:
    return {
        "success": result.success,
        "downloaded": result.downloaded,
        "imported": result.imported,
        "already_imported": result.already_imported,
        "conflict": result.conflict,
        "task_id": result.task_id,
        "session_id": result.session_id,
        "session_dir": str(result.session_dir or ""),
        "downloaded_path": str(result.downloaded_path or ""),
        "sha256": result.sha256,
        "error_code": result.error_code,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
    }


def _required_text(context: JobContext, key: str) -> str:
    value = str(context.params.get(key) or "").strip()
    if not value:
        raise ValueError(f"Online MR Agent 任务缺少 {key}")
    return value

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
        "online_mr_session_delete",
        "online_mr_collection_start",
        "online_mr_collection_status",
        "online_mr_collection_package",
        "online_mr_agent_packages_sync",
        "online_mr_agent_package_import",
    )
}
