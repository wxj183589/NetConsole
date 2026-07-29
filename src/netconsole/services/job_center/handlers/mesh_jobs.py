from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService
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

HANDLERS = {
    "mesh_log_import": mesh_log_import,
    "mesh_derived_rebuild": mesh_derived_rebuild,
    "mesh_mr_profiles_refresh": mesh_mr_profiles_refresh,
    "mesh_schema_rebuild": mesh_schema_rebuild,
    "mesh_source_rebuild": mesh_source_rebuild,
}
