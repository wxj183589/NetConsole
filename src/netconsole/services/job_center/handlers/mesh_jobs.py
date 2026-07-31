from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService
from netconsole.services.mesh_source_delete_service import MeshSourceDeleteService
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository

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
    result = MeshSourceRebuildService(context.paths).rebuild_source(
        site_name,
        session_id,
        progress=context.progress,
        should_cancel=context.should_cancel,
    )
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

HANDLERS = {
    "mesh_log_import": mesh_log_import,
    "mesh_derived_rebuild": mesh_derived_rebuild,
    "mesh_mr_profiles_refresh": mesh_mr_profiles_refresh,
    "mesh_schema_rebuild": mesh_schema_rebuild,
    "mesh_source_rebuild": mesh_source_rebuild,
    "mesh_analysis_source_delete": mesh_analysis_source_delete,
}
