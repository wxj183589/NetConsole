from __future__ import annotations

from pathlib import Path

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.ac import (
    AcApIdentityAdapter,
    AcApIdentityShadowReport,
    AcCommandCancelled,
    AcCommandRequest,
    AcCommandService,
    AcFitApDetailRefreshRequest,
    AcOpticalRefreshCancelled,
    AcOpticalIdentityAdapter,
    AcOpticalIdentityShadowReport,
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
from netconsole.services.fit_ap_import_export import FitApImportExportService
from netconsole.services.ac.mesh_link_refresh_service import run_ac_mesh_link_refresh


def _string_list(value: object, fallback: object = None) -> list[str]:
    if value in (None, "", []):
        value = [] if fallback in (None, "") else [fallback]
    elif isinstance(value, (str, int)):
        value = [value]
    return [str(item) for item in value if str(item or "").strip()]


fit_ap_metadata_import = legacy_handler(legacy_tasks._fit_ap_metadata_import)
ac_overview_refresh = legacy_handler(legacy_tasks._ac_overview_refresh)
omnipeek_name_table_preview = legacy_handler(legacy_tasks._omnipeek_name_table_preview)
ac_overview_history_snapshot = legacy_handler(legacy_tasks._ac_overview_history_snapshot)
ac_station_online_history_page = legacy_handler(legacy_tasks._ac_station_online_history_page)
ac_ap_history_page = legacy_handler(legacy_tasks._ac_ap_history_page)
ac_trackside_business_refresh = legacy_handler(legacy_tasks._ac_trackside_business_refresh)
ac_devices_refresh = legacy_handler(legacy_tasks._ac_devices_refresh)
ac_fit_ap_delete_many = legacy_handler(legacy_tasks._ac_fit_ap_delete_many)
ac_ap_extension_delete = legacy_handler(legacy_tasks._ac_ap_extension_delete)
ac_ap_extension_clear = legacy_handler(legacy_tasks._ac_ap_extension_clear)
ac_station_overview_value_save = legacy_handler(legacy_tasks._ac_station_overview_value_save)


def fit_ap_extension_preview(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    service = FitApImportExportService(repository)
    context.progress("fit_ap_extension_preview", 0, 1, "正在解析 AP 扩展信息预览")
    preview = service.preview_ap_extension_import(
        Path(str(params.get("path") or "")),
        str(params.get("import_mode") or "standard_template"),
    )
    context.check_cancelled()
    result: dict[str, object] = {
        "file_name": preview.file_name,
        "template_type": preview.template_type,
        "confidence_score": preview.confidence_score,
        "sheet_count": len(preview.sheets),
        "summary": dict(preview.summary),
        "low_confidence": bool(preview.low_confidence),
        "identity_shadow": _identity_shadow_payload(repository, preview.standard_rows, params),
    }
    context.progress("fit_ap_extension_preview", 1, 1, "AP 扩展信息预览完成")
    return result


def fit_ap_extension_commit(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    service = FitApImportExportService(repository)
    context.progress("fit_ap_extension_commit", 0, 2, "正在解析 AP 扩展信息")
    preview = service.preview_ap_extension_import(
        Path(str(params.get("path") or "")),
        str(params.get("import_mode") or "standard_template"),
    )
    identity_shadow = _identity_shadow_payload(repository, preview.standard_rows, params)
    context.progress("fit_ap_extension_commit", 1, 2, "正在写入 AP 扩展信息")
    context.check_cancelled()
    result = dict(
        service.commit_ap_extension_import(
            preview,
            duplicate_strategy=str(params.get("duplicate_strategy") or "update_by_priority"),
        )
    )
    result["identity_shadow"] = identity_shadow
    context.progress("fit_ap_extension_commit", 2, 2, "AP 扩展信息导入完成")
    return result


def ac_ap_extensions_refresh(context: JobContext) -> dict[str, object]:
    result = legacy_tasks._ac_ap_extensions_refresh(context.params, context.progress_callback, context.should_cancel)
    rows = [dict(row) for row in result.get("rows") or [] if isinstance(row, dict)]
    repository = AcRepository(Database(Path(str(context.params.get("db_path") or ""))))
    return {**result, "identity_shadow": _identity_shadow_payload(repository, rows, context.params)}


def ac_ap_extension_save(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    row = dict(context.params.get("row") or {})
    repository = AcRepository(Database(Path(str(context.params.get("db_path") or ""))))
    identity_shadow = _identity_shadow_payload(repository, [row], context.params)
    result = legacy_tasks._ac_ap_extension_save(context.params, context.progress_callback, context.should_cancel)
    return {**result, "identity_shadow": identity_shadow}


def _identity_shadow_payload(
    repository: AcRepository,
    extension_rows: list[dict[str, object | None]],
    params: dict[str, object],
) -> dict[str, object]:
    try:
        ac_uuid = str(params.get("ac_uuid") or params.get("device_uuid") or "").strip()
        fit_ap_rows = (
            repository.list_fit_ap_resources_with_metadata(ac_uuid)
            if ac_uuid
            else repository.list_all_fit_ap_resources_with_metadata()
        )
        return AcApIdentityAdapter().shadow_compare_extension_match(extension_rows, fit_ap_rows).to_payload()
    except Exception as exc:
        return AcApIdentityShadowReport(
            total=len(extension_rows),
            available=False,
            warnings=(f"identity shadow 不可用：{type(exc).__name__}: {exc}",),
        ).to_payload()


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


def ac_info_refresh(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    site_name = str(params.get("site_name") or "demo")
    database = Database(Path(str(params.get("db_path") or context.paths.site_db_path(site_name))))
    service = AcService(AcResourceService(DeviceRepository(database), AcRepository(database), context.paths))
    request = AcResourceRefreshRequest(
        device_uuid=str(params.get("device_uuid") or params.get("ac_uuid") or ""),
        site_name=site_name,
        source="cli",
    )
    try:
        result = service.refresh_ac_info(
            request,
            progress_callback=context.progress,
            should_cancel=context.should_cancel,
        )
    except AcResourceRefreshCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    if not result.success:
        raise RuntimeError(result.error_message or "AC 信息更新失败")
    return result.to_payload()


def ac_fit_ap_detail_refresh(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    site_name = str(params.get("site_name") or "demo")
    database = Database(Path(str(params.get("db_path") or context.paths.site_db_path(site_name))))
    service = AcService(AcResourceService(DeviceRepository(database), AcRepository(database), context.paths))
    request = AcFitApDetailRefreshRequest(
        device_uuid=str(params.get("device_uuid") or params.get("ac_uuid") or ""),
        ap_uuid=str(params.get("ap_uuid") or ""),
        site_name=site_name,
    )
    try:
        result = service.refresh_ap_detail(
            request,
            progress_callback=context.progress,
            should_cancel=context.should_cancel,
        )
    except AcResourceRefreshCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    if not result.success:
        raise RuntimeError(result.error_message or "FIT-AP 深度更新失败")
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
        payload = service.load_optical_snapshot(
            ac_uuid,
            progress_callback=context.progress,
            should_cancel=context.should_cancel,
        ).to_payload()
        return _append_optical_identity_shadow(payload, ac_uuid)

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
    return _append_optical_identity_shadow(result.to_payload(), ac_uuid)


def _append_optical_identity_shadow(payload: dict[str, object], ac_uuid: str) -> dict[str, object]:
    result = dict(payload)
    optical_rows = [dict(row) for row in payload.get("optical_rows") or [] if isinstance(row, dict)]
    fit_ap_rows = [dict(row) for row in payload.get("resources") or [] if isinstance(row, dict)]
    try:
        shadow = AcOpticalIdentityAdapter().shadow_compare_optical_binding(
            optical_rows,
            fit_ap_rows,
            ac_uuid=ac_uuid or None,
        )
    except Exception as exc:
        shadow = AcOpticalIdentityShadowReport(
            total=len(optical_rows),
            available=False,
            warnings=(f"optical identity shadow 不可用：{type(exc).__name__}: {exc}",),
        )
    result["identity_shadow"] = shadow.to_payload()
    return result


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


def ac_mesh_link_refresh(context: JobContext) -> dict[str, object]:
    return run_ac_mesh_link_refresh(context)

HANDLERS = {
    name: globals()[name]
    for name in (
        "fit_ap_metadata_import",
        "fit_ap_extension_preview",
        "fit_ap_extension_commit",
        "ac_overview_refresh",
        "ac_fit_ap_resources_refresh",
        "ac_info_refresh",
        "ac_fit_ap_detail_refresh",
        "ac_fit_ap_optical_refresh",
        "ac_command_action_execute",
        "ac_mesh_link_refresh",
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
