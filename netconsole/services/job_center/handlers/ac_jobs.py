from __future__ import annotations

from pathlib import Path

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.ac import (
    AcCommandCancelled,
    AcCommandRequest,
    AcCommandService,
    AcOpticalRefreshCancelled,
    AcOpticalRefreshRequest,
    AcOpticalService,
    AcResourceRefreshRequest,
    AcResourceService,
    AcService,
)
from netconsole.services.ac.ac_resource_service import AcResourceRefreshCancelled
from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.snmp.snmp_collection_service import SnmpCollectionService
from netconsole.services.snmp_query_service import SnmpQueryService


def _string_list(value: object, fallback: object = None) -> list[str]:
    if value in (None, "", []):
        value = [] if fallback in (None, "") else [fallback]
    elif isinstance(value, (str, int)):
        value = [value]
    return [str(item) for item in value if str(item or "").strip()]


fit_ap_metadata_import = legacy_handler(legacy_tasks._fit_ap_metadata_import)
fit_ap_extension_preview = legacy_handler(legacy_tasks._fit_ap_extension_preview)
fit_ap_extension_commit = legacy_handler(legacy_tasks._fit_ap_extension_commit)
ac_overview_refresh = legacy_handler(legacy_tasks._ac_overview_refresh)
ac_ap_extensions_refresh = legacy_handler(legacy_tasks._ac_ap_extensions_refresh)
omnipeek_name_table_preview = legacy_handler(legacy_tasks._omnipeek_name_table_preview)
ac_overview_history_snapshot = legacy_handler(legacy_tasks._ac_overview_history_snapshot)
ac_station_online_history_page = legacy_handler(legacy_tasks._ac_station_online_history_page)
ac_ap_history_page = legacy_handler(legacy_tasks._ac_ap_history_page)
ac_trackside_business_refresh = legacy_handler(legacy_tasks._ac_trackside_business_refresh)
ac_devices_refresh = legacy_handler(legacy_tasks._ac_devices_refresh)
ac_fit_ap_delete_many = legacy_handler(legacy_tasks._ac_fit_ap_delete_many)
ac_ap_extension_save = legacy_handler(legacy_tasks._ac_ap_extension_save)
ac_ap_extension_delete = legacy_handler(legacy_tasks._ac_ap_extension_delete)
ac_ap_extension_clear = legacy_handler(legacy_tasks._ac_ap_extension_clear)
ac_station_overview_value_save = legacy_handler(legacy_tasks._ac_station_overview_value_save)


def ac_fit_ap_resources_refresh(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    site_name = str(params.get("site_name") or "demo")
    database_path = Path(str(params.get("db_path") or context.paths.site_db_path(site_name)))
    database = Database(database_path)
    ac_repository = AcRepository(database)
    device_repository = DeviceRepository(database)
    snmp_database_path = context.paths.site_snmp_db_path(site_name)

    def create_snmp_query_service(_target) -> SnmpQueryService:
        return SnmpQueryService(SiteSnmpRepository(snmp_database_path))

    resource_service = AcResourceService(
        device_repository,
        ac_repository,
        context.paths,
        snmp_collection_service=SnmpCollectionService(create_snmp_query_service),
    )
    ac_service = AcService(resource_service)
    ac_uuid = str(params.get("device_uuid") or params.get("ac_uuid") or params.get("device_id") or params.get("ac_id") or "")
    if str(params.get("mode") or "load").lower() != "collect":
        context.progress("ac_fit_ap_resources_refresh", 0, 1, "正在读取 FIT-AP 资源")
        payload = resource_service.load_snapshot(ac_uuid).to_payload()
        context.progress("ac_fit_ap_resources_refresh", 1, 1, "FIT-AP 资源刷新完成")
        return payload

    request = AcResourceRefreshRequest(
        device_uuid=ac_uuid,
        site_name=site_name,
        source=str(params.get("source") or "auto"),
        snmp_oids=[str(value) for value in params.get("snmp_oids") or [] if str(value).strip()],
        snmp_operation=str(params.get("snmp_operation") or "WALK"),
        snmp_concurrency=int(params.get("snmp_concurrency") or 10),
        snmp_timeout_ms=int(params.get("snmp_timeout_ms") or 2000),
        snmp_retries=int(params.get("snmp_retries") or 1),
        snmp_max_repetitions=int(params.get("snmp_max_repetitions") or 10),
        snmp_max_rows=int(params.get("snmp_max_rows") or 500),
    )
    try:
        result = ac_service.refresh_ap_resources(
            request,
            progress_callback=context.progress,
            should_cancel=context.should_cancel,
        )
    except AcResourceRefreshCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    if not result.success:
        raise RuntimeError(result.error_message or "FIT-AP 资源更新失败")
    return result.to_payload()


def ac_fit_ap_optical_refresh(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    site_name = str(params.get("site_name") or "demo")
    database_path = Path(str(params.get("db_path") or context.paths.site_db_path(site_name)))
    database = Database(database_path)
    service = AcOpticalService(
        DeviceRepository(database),
        AcRepository(database),
        DeviceFactRepository(database),
        context.paths,
    )
    ac_uuid = str(params.get("device_uuid") or params.get("ac_uuid") or params.get("device_id") or params.get("ac_id") or "")
    if str(params.get("mode") or "load").lower() != "collect":
        return service.load_optical_snapshot(
            ac_uuid,
            progress_callback=context.progress,
            should_cancel=context.should_cancel,
        ).to_payload()

    refresh_scope = str(params.get("refresh_scope") or "all").lower()
    request = AcOpticalRefreshRequest(
        device_uuid=ac_uuid,
        site_name=site_name,
        refresh_scope=refresh_scope,
        source=str(params.get("source") or "auto"),
        max_workers=int(params.get("concurrency") or params.get("max_workers") or 200),
        timeout=int(params.get("timeout") or 15),
        retry=int(params.get("retry") or 2),
        target_ap_uuids=_string_list(params.get("target_ap_uuids"), params.get("ap_uuid") or params.get("ap_id")),
        target_ap_macs=_string_list(params.get("target_ap_macs"), params.get("ap_mac")),
        target_ap_names=_string_list(params.get("target_ap_names"), params.get("ap_name")),
    )
    try:
        if refresh_scope == "single":
            result = service.refresh_single_ap_optical(
                request,
                progress_callback=context.progress,
                should_cancel=context.should_cancel,
            )
        else:
            result = service.refresh_fit_ap_optical(
                request,
                progress_callback=context.progress,
                should_cancel=context.should_cancel,
            )
    except AcOpticalRefreshCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    if not result.success:
        raise RuntimeError(result.error_message or "FIT-AP 光衰更新失败")
    return result.to_payload()


def ac_command_action_execute(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    site_name = str(params.get("site_name") or "demo")
    database_path = Path(str(params.get("db_path") or context.paths.site_db_path(site_name)))
    database = Database(database_path)
    service = AcCommandService(
        DeviceRepository(database),
        AcRepository(database),
        context.paths,
    )
    device_uuid = str(params.get("device_uuid") or params.get("ac_uuid") or params.get("device_id") or params.get("ac_id") or "")
    request = AcCommandRequest(
        device_uuid=device_uuid,
        site_name=site_name,
        action=str(params.get("action") or ""),
        command_sequence=_string_list(params.get("command_sequence")),
        confirm_required=bool(params.get("confirm_required", True)),
        timeout=int(params.get("timeout") or 10),
        retry=int(params.get("retry") or 0),
        source=str(params.get("source") or "auto"),
    )
    try:
        result = service.execute_action(
            request,
            progress_callback=context.progress,
            should_cancel=context.should_cancel,
        )
    except AcCommandCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    if not result.success:
        raise RuntimeError(result.error_message or "AC 命令动作执行失败")
    return result.to_payload()

HANDLERS = {
    name: globals()[name]
    for name in (
        "fit_ap_metadata_import",
        "fit_ap_extension_preview",
        "fit_ap_extension_commit",
        "ac_overview_refresh",
        "ac_fit_ap_resources_refresh",
        "ac_fit_ap_optical_refresh",
        "ac_command_action_execute",
        "ac_ap_extensions_refresh",
        "omnipeek_name_table_preview",
        "ac_overview_history_snapshot",
        "ac_station_online_history_page",
        "ac_ap_history_page",
        "ac_trackside_business_refresh",
        "ac_devices_refresh",
        "ac_fit_ap_delete_many",
        "ac_ap_extension_save",
        "ac_ap_extension_delete",
        "ac_ap_extension_clear",
        "ac_station_overview_value_save",
    )
}
