from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService
from netconsole.services.mesh_derived_data_maintenance_service import (
    MeshDerivedDataMaintenanceService,
    MeshDerivedDatabaseIncompatible,
)
from netconsole.repositories.mesh_mr_repository import MeshSchemaRebuildRequired
from netconsole.services.mesh_source_rebuild_service import (
    MeshSourceRebuildCancelled,
    MeshSourceRebuildService,
)
from netconsole.services.mesh_source_delete_service import MeshSourceDeleteService
from netconsole.services.mesh_sources_delete_service import (
    MeshSourcesDeleteCancelled,
    MeshSourcesDeleteService,
)
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.services.mesh_local_scan_service import MeshLocalScanService

mesh_log_import = legacy_handler(legacy_tasks._mesh_log_import)
mesh_derived_rebuild = legacy_handler(legacy_tasks._mesh_derived_rebuild)
mesh_mr_profiles_refresh = legacy_handler(legacy_tasks._mesh_mr_profiles_refresh)


def mesh_schema_rebuild(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = MeshParsedRebuildService(context.paths).rebuild(
        str(context.params.get("site_name") or ""),
        str(context.params.get("mr_id") or ""),
        progress=context.progress,
        should_cancel=context.should_cancel,
    )
    MeshCatalogRepository(
        context.paths.mesh_catalog_path(str(context.params.get("site_name") or ""))
    ).mark_index_pending()
    return result


def mesh_source_rebuild(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    site_name = str(context.params.get("site_name") or "")
    session_id = str(context.params.get("session_id") or "")
    try:
        result = MeshSourceRebuildService(context.paths).rebuild_source(
            site_name,
            session_id,
            force_reparse=True,
            progress=context.progress,
            should_cancel=context.should_cancel,
        )
    except MeshSourceRebuildCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    MeshCatalogRepository(
        context.paths.mesh_catalog_path(site_name)
    ).mark_session_index_dirty(session_id)
    return result


def mesh_analysis_source_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    result = MeshSourceDeleteService(context.paths).delete_source(
        str(params.get("site_name") or ""),
        str(params.get("session_id") or ""),
        delete_raw_archive=bool(params.get("delete_raw_archive")),
        delete_parsed_data=bool(params.get("delete_parsed_data", True)),
        delete_generated_reports=bool(params.get("delete_generated_reports", True)),
    )
    context.progress("mesh_analysis_source_delete", 1, 1, "MESH 来源删除完成")
    return result


def mesh_analysis_maintenance(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    site_name = str(context.params.get("site_name") or "")
    session_id = str(context.params.get("session_id") or "")
    kind = str(context.params.get("maintenance_kind") or "")
    if kind not in {"identity_projection_refresh", "parser_rebuild"}:
        raise ValueError("不支持的 MESH 来源维护类型")
    try:
        result = MeshSourceRebuildService(context.paths).rebuild_source(
            site_name,
            session_id,
            force_reparse=bool(context.params.get("force_reparse")),
            progress=context.progress,
            should_cancel=context.should_cancel,
        )
    except MeshSourceRebuildCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc
    MeshCatalogRepository(
        context.paths.mesh_catalog_path(site_name)
    ).mark_session_index_dirty(session_id)
    return {**result, "maintenance_kind": kind}


def mesh_analysis_sources_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    raw_session_ids = params.get("session_ids")
    session_ids = (
        [str(item) for item in raw_session_ids]
        if isinstance(raw_session_ids, (list, tuple))
        else []
    )
    try:
        return MeshSourcesDeleteService(context.paths).delete_sources(
            str(params.get("site_name") or ""),
            session_ids,
            delete_raw_archive=bool(params.get("delete_raw_archive")),
            delete_parsed_data=bool(params.get("delete_parsed_data", True)),
            delete_generated_reports=bool(
                params.get("delete_generated_reports", True)
            ),
            progress=context.progress,
            should_cancel=context.should_cancel,
        )
    except MeshSourcesDeleteCancelled as exc:
        raise BackgroundTaskCancelled(str(exc)) from exc


def mesh_local_scan(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    site_name = str(context.params.get("site_name") or "")
    scan_id = str(context.params.get("scan_id") or "")
    result = MeshLocalScanService(site_name, context.paths).scan(
        scan_id,
        should_cancel=context.should_cancel,
        progress=context.progress,
    )
    context.check_cancelled()
    return result


def mesh_local_scan_import(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    site_name = str(context.params.get("site_name") or "")
    scan_id = str(context.params.get("scan_id") or "")
    raw_mappings = context.params.get("mappings") or ()
    mappings = tuple(dict(item) for item in raw_mappings if isinstance(item, dict))
    result = MeshLocalScanService(site_name, context.paths).import_candidates(
        scan_id,
        mappings,
        job_id=context.job_id,
        should_cancel=context.should_cancel,
        progress=context.progress,
    )
    context.check_cancelled()
    return result


def mesh_derived_data_repair(context: JobContext) -> dict[str, object]:
    """修复局点派生库后，在同一受管 Job 内恢复等待的导入操作。"""

    context.check_cancelled()
    site_name = str(context.params.get("site_name") or "")
    maintenance = MeshDerivedDataMaintenanceService(context.paths)
    operations = maintenance.pending_operations(site_name)
    requested_profile_ids = [
        str(value)
        for value in context.params.get("profile_ids") or ()
        if str(value)
    ]
    for operation in operations:
        operation_profile_ids = _operation_profile_ids(operation)
        if not operation_profile_ids:
            raise ValueError("等待导入的 MESH 操作缺少 Profile 标识，已停止自动修复")
        requested_profile_ids.extend(operation_profile_ids)
    requested_profile_ids = list(dict.fromkeys(requested_profile_ids))
    if not requested_profile_ids:
        raise ValueError("MESH 自动修复缺少当前请求的 Profile 标识")
    operation_ids = [str(item.get("operation_id") or "") for item in operations]
    maintenance.mark_operations_repairing(site_name, operation_ids)
    for operation in operations:
        _set_local_scan_repair_status(maintenance, site_name, operation, "repairing", "正在升级分析数据库。")

    def should_cancel() -> bool:
        context.check_cancelled()
        return False

    try:
        repair_result = maintenance.repair(
            site_name,
            profile_ids=requested_profile_ids,
            progress=context.progress,
            should_cancel=should_cancel,
        )
    except Exception:
        message = "MESH 分析数据库自动修复失败，原始日志和旧派生数据均已保留"
        for operation in operations:
            operation_id = str(operation.get("operation_id") or "")
            maintenance.fail_operation(site_name, operation_id, message, repair_failed=True)
            _set_local_scan_repair_status(
                maintenance,
                site_name,
                operation,
                "repair_failed",
                message,
            )
        raise

    resumed: list[dict[str, object]] = []
    created_session_ids: list[str] = []
    total = max(len(operations), 1)
    for index, operation in enumerate(operations, start=1):
        context.check_cancelled()
        operation_id = str(operation.get("operation_id") or "")
        _set_local_scan_repair_status(maintenance, site_name, operation, "queued", "等待自动导入。")
        try:
            result = _resume_mesh_operation(context, operation)
        except MeshSchemaRebuildRequired as exc:
            message = "MESH 分析数据库仍需自动修复，请重试自动修复"
            maintenance.fail_operation(site_name, operation_id, message, repair_failed=True)
            _set_local_scan_repair_status(maintenance, site_name, operation, "repair_failed", message)
            raise RuntimeError(message) from exc
        except Exception as exc:
            message = _safe_continuation_error(exc)
            maintenance.fail_operation(site_name, operation_id, message, repair_failed=False)
            _set_local_scan_repair_status(maintenance, site_name, operation, "parse_failed", message)
            resumed.append({"operation_id": operation_id, "status": "parse_failed", "error": message})
        else:
            maintenance.complete_operation(site_name, operation_id, result)
            sessions = result.get("created_session_ids") if isinstance(result, dict) else None
            if isinstance(sessions, list):
                created_session_ids.extend(str(item) for item in sessions if str(item))
            resumed.append({"operation_id": operation_id, "status": "completed"})
        context.progress(
            "mesh_derived_repair_resume",
            95 + int(index * 5 / total),
            100,
            f"正在继续导入等待中的 MESH 日志：{index} / {total}",
        )
    return {
        **repair_result,
        "resumed_operations": resumed,
        "resumed_count": sum(item["status"] == "completed" for item in resumed),
        "created_session_ids": list(dict.fromkeys(created_session_ids)),
    }


def _resume_mesh_operation(context: JobContext, operation: dict[str, object]) -> dict[str, object]:
    from netconsole.services.job_center.handlers import legacy_tasks
    from netconsole.services.mesh_bundle_import_service import MeshBundleImportService

    kind = str(operation.get("kind") or "")
    payload = dict(operation.get("payload") or {})
    site_name = str(context.params.get("site_name") or "")

    def should_cancel() -> bool:
        context.check_cancelled()
        return False

    if kind == "mesh_log_import":
        result = legacy_tasks._mesh_log_import(
            {
                **payload,
                "site_name": site_name,
                "app_root": str(context.paths.app_root),
                "data_root": str(context.paths.data_root),
            },
            lambda stage, current, total, message: context.progress(stage, current, total, message),
            should_cancel,
        )
        MeshDerivedDataMaintenanceService(context.paths).cleanup_manual_staging(site_name, payload.get("files") or ())
        return result
    if kind == "mesh_bundle_import":
        result = MeshBundleImportService(site_name, context.paths).import_approved_preview(
            str(payload.get("preview_id") or ""),
            payload.get("mappings") or (),
            job_id=context.job_id,
            should_cancel=should_cancel,
            progress=lambda stage, current, total, message: context.progress(stage, current, total, message),
        )
        return result
    if kind == "mesh_local_scan_import":
        result = MeshLocalScanService(site_name, context.paths).import_candidates(
            str(payload.get("scan_id") or ""),
            payload.get("mappings") or (),
            job_id=context.job_id,
            should_cancel=should_cancel,
            progress=lambda stage, current, total, message: context.progress(stage, current, total, message),
        )
        return result
    raise ValueError("不支持的 MESH 等待导入操作")


def _set_local_scan_repair_status(
    _maintenance: MeshDerivedDataMaintenanceService,
    site_name: str,
    operation: dict[str, object],
    status: str,
    message: str,
) -> None:
    if str(operation.get("kind") or "") != "mesh_local_scan_import":
        return
    payload = dict(operation.get("payload") or {})
    try:
        MeshLocalScanService(site_name, _maintenance.paths).set_repair_status(
            str(payload.get("scan_id") or ""),
            (str(item.get("candidate_id") or "") for item in payload.get("mappings") or () if isinstance(item, dict)),
            status,
            message,
        )
    except Exception:
        # The repair journal remains authoritative even if an expired scan manifest cannot be updated.
        return


def _safe_continuation_error(exc: Exception) -> str:
    if isinstance(exc, MeshDerivedDatabaseIncompatible):
        return "MESH 分析数据库仍需自动修复"
    return str(exc) or "MESH 日志解析失败"


def _operation_profile_ids(operation: dict[str, object]) -> tuple[str, ...]:
    payload = operation.get("payload")
    if not isinstance(payload, dict):
        return ()
    values: list[str] = []
    profile = payload.get("profile")
    if isinstance(profile, dict):
        mr_id = str(profile.get("mr_id") or "").strip()
        if mr_id:
            values.append(mr_id)
    mappings = payload.get("mappings")
    if isinstance(mappings, (list, tuple)):
        for item in mappings:
            if not isinstance(item, dict):
                continue
            profile_id = str(item.get("profile_id") or "").strip()
            if profile_id:
                values.append(profile_id)
    return tuple(dict.fromkeys(values))

HANDLERS = {
    "mesh_log_import": mesh_log_import,
    "mesh_derived_rebuild": mesh_derived_rebuild,
    "mesh_mr_profiles_refresh": mesh_mr_profiles_refresh,
    "mesh_schema_rebuild": mesh_schema_rebuild,
    "mesh_source_rebuild": mesh_source_rebuild,
    "mesh_analysis_maintenance": mesh_analysis_maintenance,
    "mesh_derived_data_repair": mesh_derived_data_repair,
    "mesh_analysis_source_delete": mesh_analysis_source_delete,
    "mesh_analysis_sources_delete": mesh_analysis_sources_delete,
    "mesh_local_scan": mesh_local_scan,
    "mesh_local_scan_import": mesh_local_scan_import,
}
