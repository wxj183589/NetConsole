from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.snmp.request_builder import build_collection_request, build_query_request, build_set_request, normalize_operation, operation_key
from netconsole.services.snmp.result_formatter import (
    collection_result_to_payload,
    format_browser_rows,
    format_query_rows,
    query_result_to_payload,
    set_result_to_payload,
)
from netconsole.services.snmp.result_cache import SnmpCollectionResultCache, SnmpQueryResultCache
from netconsole.services.snmp.snmp_collection_service import SnmpCollectionService
from netconsole.services.snmp_query_service import SnmpQueryService


def snmp_query_execute(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    site_name = str(params.get("site_name") or "demo")
    repository = SiteSnmpRepository(context.paths.site_snmp_db_path(site_name))
    repository.initialize()
    service = SnmpQueryService(repository)
    operation = normalize_operation(params.get("operation") or dict(params.get("request") or {}).get("method"))
    if operation == "Set":
        request = build_set_request(params)
        result = service.set_value(
            request,
            cancel_checker=context.should_cancel,
            progress_callback=context.progress,
        )
        if context.should_cancel is not None and context.should_cancel():
            context.check_cancelled()
        return {
            "kind": "set",
            "operation": operation_key(operation),
            "set_result": set_result_to_payload(result),
        }

    request = build_query_request(params)
    result = service.run(
        request,
        cancel_checker=context.should_cancel,
        progress_callback=context.progress,
    )
    if context.should_cancel is not None and context.should_cancel():
        context.check_cancelled()
    result_file = ""
    if bool(params.get("cache_result", False)):
        result_file = str(SnmpQueryResultCache(context.paths).write(result, cache_key=f"snmp_query_{context.job_id}"))
    return {
        "kind": "query",
        "operation": operation_key(operation),
        "query_result": query_result_to_payload(result),
        "browser_rows": format_browser_rows(result),
        "query_rows": format_query_rows(result),
        "result_file": result_file,
    }


def snmp_collection_execute(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    request = build_collection_request(params)
    site_name = str(params.get("site_name") or "demo")
    database_path = context.paths.site_snmp_db_path(site_name)
    SiteSnmpRepository(database_path).initialize()

    def create_query_service(_target) -> SnmpQueryService:
        return SnmpQueryService(SiteSnmpRepository(database_path))

    result = SnmpCollectionService(create_query_service).execute(
        request,
        progress_callback=context.progress,
        should_cancel=context.should_cancel,
    )
    if result.cancelled:
        raise BackgroundTaskCancelled("SNMP 批量采集已取消")
    result_file = ""
    if bool(params.get("cache_result", True)):
        result_file = str(
            SnmpCollectionResultCache(context.paths).write(
                result,
                cache_key=f"snmp_collection_{context.job_id}",
            )
        )
    return {
        "kind": "collection",
        "operation": result.request.operation,
        "collection_result": collection_result_to_payload(result),
        "result_file": result_file,
    }

snmp_mib_resource_refresh = legacy_handler(legacy_tasks._snmp_mib_resource_refresh)
snmp_product_references_refresh = legacy_handler(legacy_tasks._snmp_product_references_refresh)
snmp_center_data_refresh = legacy_handler(legacy_tasks._snmp_center_data_refresh)
snmp_center_data_action = legacy_handler(legacy_tasks._snmp_center_data_action)

HANDLERS = {
    "snmp_query_execute": snmp_query_execute,
    "snmp_collection_execute": snmp_collection_execute,
    "snmp_mib_resource_refresh": snmp_mib_resource_refresh,
    "snmp_product_references_refresh": snmp_product_references_refresh,
    "snmp_center_data_refresh": snmp_center_data_refresh,
    "snmp_center_data_action": snmp_center_data_action,
}
