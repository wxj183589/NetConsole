from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService

mesh_log_import = legacy_handler(legacy_tasks._mesh_log_import)
mesh_derived_rebuild = legacy_handler(legacy_tasks._mesh_derived_rebuild)
mesh_mr_profiles_refresh = legacy_handler(legacy_tasks._mesh_mr_profiles_refresh)


def mesh_schema_rebuild(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    return MeshParsedRebuildService(context.paths).rebuild(
        str(context.params.get("site_name") or ""),
        str(context.params.get("mr_id") or ""),
        progress=context.progress,
        should_cancel=context.should_cancel,
    )

HANDLERS = {
    "mesh_log_import": mesh_log_import,
    "mesh_derived_rebuild": mesh_derived_rebuild,
    "mesh_mr_profiles_refresh": mesh_mr_profiles_refresh,
    "mesh_schema_rebuild": mesh_schema_rebuild,
}
