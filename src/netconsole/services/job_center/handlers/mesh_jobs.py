from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.core.runtime_environment import production_write_allowed
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
from netconsole.services.mesh_write_authority import (
    MESH_DERIVED_REBUILD_OPERATION,
    MESH_IDENTITY_REMAP_OPERATION,
    MESH_SOURCE_DELETE_OPERATION,
    MeshProductionAuthorizationError,
    build_mesh_write_plan,
    mesh_operation_lock,
    mesh_source_revisions,
    mesh_source_plan_facts,
    require_mesh_write_authority,
    resolve_mesh_production_scope,
    validate_mesh_write_plan,
)
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryService,
)

mesh_log_import = legacy_handler(legacy_tasks._mesh_log_import)
mesh_derived_rebuild = legacy_handler(legacy_tasks._mesh_derived_rebuild)
mesh_mr_profiles_refresh = legacy_handler(legacy_tasks._mesh_mr_profiles_refresh)


def _mesh_worker_preflight(
    context: JobContext,
    *,
    operation: str,
    session_id: str,
    maintenance_kind: str = "",
    force_reparse: bool = False,
    delete_raw_archive: bool = False,
    delete_parsed_data: bool = True,
    delete_generated_reports: bool = True,
    expected_plan: dict[str, object] | None = None,
) -> tuple[object, dict[str, object], dict[str, object]]:
    params = dict(context.params)
    supplied_plan = (
        expected_plan if expected_plan is not None else params.get("mesh_write_plan")
    )
    plan = dict(supplied_plan) if isinstance(supplied_plan, dict) else None
    site_ref = str(
        (plan or {}).get("canonical_site_id")
        or params.get("mesh_canonical_site_id")
        or params.get("site_name")
        or ""
    )
    scope = resolve_mesh_production_scope(context.paths, site_ref)
    authorization_token = str(params.get("mesh_authorization_token") or "")
    if (
        ("explicit_confirmation" not in params and scope.is_production)
        or (
            "explicit_confirmation" in params
            and not bool(params.get("explicit_confirmation"))
        )
    ):
        raise MeshProductionAuthorizationError("MESH_SOURCE_CONFIRMATION_REQUIRED")
    require_mesh_write_authority(
        context.paths,
        scope.canonical_site_id,
        operation=operation,
        allow_production_write=production_write_allowed(),
        authorization_token=authorization_token,
    )
    if scope.is_production and delete_raw_archive:
        raise MeshProductionAuthorizationError(
            "MESH_PRODUCTION_RAW_DELETE_UNSUPPORTED"
        )

    query = MeshAnalysisQueryService(context.paths, schedule_catalog_index=False)
    current = query._context(scope.directory_name, session_id)
    revisions = mesh_source_revisions(
        current.mr_id,
        current.source_id,
        current.source,
    )
    facts = mesh_source_plan_facts(context.paths, scope, current)
    raw_sha256 = str(facts["raw_sha256"])
    content_sha256 = str(current.source.get("content_sha256") or "")
    identity_index_revision = int(current.source.get("identity_index_revision") or 0)
    peer_set_digest = (
        str(facts["peer_set_digest"])
        if operation == MESH_IDENTITY_REMAP_OPERATION
        else ""
    )
    identity_snapshot_revision = (
        int(facts["identity_snapshot_revision"])
        if operation == MESH_IDENTITY_REMAP_OPERATION
        else 0
    )
    if scope.is_production and operation == MESH_DERIVED_REBUILD_OPERATION and not raw_sha256:
        raise MeshProductionAuthorizationError("MESH_PRODUCTION_RAW_SOURCE_REQUIRED")
    if operation == MESH_IDENTITY_REMAP_OPERATION and not str(facts["parsed_sha256"]):
        raise MeshProductionAuthorizationError("MESH_IDENTITY_DETAIL_REQUIRED")
    if plan is None:
        if scope.is_production:
            raise MeshProductionAuthorizationError("MESH_SOURCE_PLAN_REQUIRED")
        plan = build_mesh_write_plan(
            scope,
            profile_id=current.mr_id,
            source_id=current.source_id,
            operation=operation,
            explicit_confirmation=True,
            **revisions,
            safe_folder_name=str(facts["safe_folder_name"]),
            source_index_sha256=str(facts["source_index_sha256"]),
            parsed_sha256=str(facts["parsed_sha256"]),
            peer_set_digest=peer_set_digest,
            identity_snapshot_revision=identity_snapshot_revision,
            raw_sha256=raw_sha256,
            content_sha256=content_sha256,
            identity_index_revision=identity_index_revision,
            maintenance_kind=maintenance_kind,
            force_reparse=force_reparse,
            delete_raw_archive=delete_raw_archive,
            delete_parsed_data=delete_parsed_data,
            delete_generated_reports=delete_generated_reports,
        )
    else:
        validate_mesh_write_plan(
            plan,
            scope,
            operation=operation,
            profile_id=current.mr_id,
            source_id=current.source_id,
            explicit_confirmation=True,
            **revisions,
            safe_folder_name=str(facts["safe_folder_name"]),
            source_index_sha256=str(facts["source_index_sha256"]),
            parsed_sha256=str(facts["parsed_sha256"]),
            peer_set_digest=peer_set_digest,
            identity_snapshot_revision=identity_snapshot_revision,
            raw_sha256=raw_sha256,
            content_sha256=content_sha256,
            identity_index_revision=identity_index_revision,
            maintenance_kind=maintenance_kind,
            force_reparse=force_reparse,
            delete_raw_archive=delete_raw_archive,
            delete_parsed_data=delete_parsed_data,
            delete_generated_reports=delete_generated_reports,
        )
    aliases = {
        "mesh_plan_digest": plan["plan_digest"],
        "mesh_canonical_site_id": plan["canonical_site_id"],
        "mesh_profile_id": plan["profile_id"],
        "mesh_source_id": plan["source_id"],
        "mesh_operation": plan["operation"],
    }
    for key, expected in aliases.items():
        if (
            key not in params and scope.is_production
        ) or (
            key in params and str(params.get(key) or "") != str(expected)
        ):
            raise MeshProductionAuthorizationError("MESH_SOURCE_TASK_BINDING_INVALID")
    return scope, plan, facts


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
    session_id = str(context.params.get("session_id") or "")
    scope, plan, _facts = _mesh_worker_preflight(
        context,
        operation=MESH_DERIVED_REBUILD_OPERATION,
        session_id=session_id,
        force_reparse=True,
    )
    with mesh_operation_lock(
        context.paths,
        scope,
        MESH_DERIVED_REBUILD_OPERATION,
        profile_id=str(plan["profile_id"]),
        source_id=str(plan["source_id"]),
    ):
        scope, plan, _facts = _mesh_worker_preflight(
            context,
            operation=MESH_DERIVED_REBUILD_OPERATION,
            session_id=session_id,
            force_reparse=True,
            expected_plan=plan,
        )
        context.check_cancelled()
        try:
            result = MeshSourceRebuildService(context.paths).rebuild_source(
                scope.directory_name,
                session_id,
                force_reparse=True,
                allow_raw_recovery=not scope.is_production,
                progress=context.progress,
                should_cancel=context.should_cancel,
            )
        except MeshSourceRebuildCancelled as exc:
            raise BackgroundTaskCancelled(str(exc)) from exc
        MeshCatalogRepository(
            context.paths.mesh_catalog_path(scope.directory_name)
        ).mark_session_index_dirty(session_id)
    return result


def mesh_analysis_source_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    session_id = str(params.get("session_id") or "")
    delete_raw_archive = bool(params.get("delete_raw_archive"))
    delete_parsed_data = bool(params.get("delete_parsed_data", True))
    delete_generated_reports = bool(params.get("delete_generated_reports", True))
    scope, plan, _facts = _mesh_worker_preflight(
        context,
        operation=MESH_SOURCE_DELETE_OPERATION,
        session_id=session_id,
        delete_raw_archive=delete_raw_archive,
        delete_parsed_data=delete_parsed_data,
        delete_generated_reports=delete_generated_reports,
    )
    with mesh_operation_lock(
        context.paths,
        scope,
        MESH_SOURCE_DELETE_OPERATION,
        profile_id=str(plan["profile_id"]),
        source_id=str(plan["source_id"]),
    ):
        scope, plan, _facts = _mesh_worker_preflight(
            context,
            operation=MESH_SOURCE_DELETE_OPERATION,
            session_id=session_id,
            delete_raw_archive=delete_raw_archive,
            delete_parsed_data=delete_parsed_data,
            delete_generated_reports=delete_generated_reports,
            expected_plan=plan,
        )
        context.check_cancelled()
        result = MeshSourceDeleteService(context.paths).delete_source(
            scope.directory_name,
            session_id,
            delete_raw_archive=bool(plan["delete_raw_archive"]),
            delete_parsed_data=bool(plan["delete_parsed_data"]),
            delete_generated_reports=bool(plan["delete_generated_reports"]),
        )
    context.progress("mesh_analysis_source_delete", 1, 1, "MESH 来源删除完成")
    return result


def mesh_analysis_maintenance(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    session_id = str(context.params.get("session_id") or "")
    params = dict(context.params)
    kind = str(params.get("maintenance_kind") or "")
    if kind not in {"identity_projection_refresh", "parser_rebuild"}:
        raise ValueError("不支持的 MESH 来源维护类型")
    expected_force_reparse = kind == "parser_rebuild"
    if bool(params.get("force_reparse")) != expected_force_reparse:
        raise ValueError("MESH_MAINTENANCE_PARAMS_INVALID")
    operation = (
        MESH_IDENTITY_REMAP_OPERATION
        if kind == "identity_projection_refresh"
        else MESH_DERIVED_REBUILD_OPERATION
    )
    scope, plan, _facts = _mesh_worker_preflight(
        context,
        operation=operation,
        session_id=session_id,
        maintenance_kind=kind,
        force_reparse=expected_force_reparse,
    )
    with mesh_operation_lock(
        context.paths,
        scope,
        operation,
        profile_id=str(plan["profile_id"]),
        source_id=str(plan["source_id"]),
    ):
        scope, plan, facts = _mesh_worker_preflight(
            context,
            operation=operation,
            session_id=session_id,
            maintenance_kind=kind,
            force_reparse=expected_force_reparse,
            expected_plan=plan,
        )
        context.check_cancelled()
        try:
            if operation == MESH_IDENTITY_REMAP_OPERATION:
                result = MeshSourceRebuildService(context.paths).remap_identity_only(
                    scope.directory_name,
                    session_id,
                    expected_identity_index_revision=int(
                        plan["identity_snapshot_revision"]
                    ),
                    expected_peer_keys=set(facts["peer_keys"]),
                    progress=context.progress,
                    should_cancel=context.should_cancel,
                )
            else:
                result = MeshSourceRebuildService(context.paths).rebuild_source(
                    scope.directory_name,
                    session_id,
                    force_reparse=True,
                    allow_raw_recovery=not scope.is_production,
                    progress=context.progress,
                    should_cancel=context.should_cancel,
                )
        except MeshSourceRebuildCancelled as exc:
            raise BackgroundTaskCancelled(str(exc)) from exc
        MeshCatalogRepository(
            context.paths.mesh_catalog_path(scope.directory_name)
        ).mark_session_index_dirty(session_id)
    return {**result, "maintenance_kind": kind}


def mesh_analysis_sources_delete(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    params = dict(context.params)
    scope = resolve_mesh_production_scope(
        context.paths,
        str(params.get("site_name") or ""),
    )
    if scope.is_production:
        raise MeshProductionAuthorizationError(
            "MESH_PRODUCTION_BATCH_DELETE_UNSUPPORTED"
        )
    raw_session_ids = params.get("session_ids")
    session_ids = (
        [str(item) for item in raw_session_ids]
        if isinstance(raw_session_ids, (list, tuple))
        else []
    )
    try:
        return MeshSourcesDeleteService(context.paths).delete_sources(
            scope.directory_name,
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
