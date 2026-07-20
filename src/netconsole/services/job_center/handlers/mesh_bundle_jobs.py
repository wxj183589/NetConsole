from __future__ import annotations

from collections.abc import Mapping

from netconsole.services.job_center.job_context import JobContext
from netconsole.services.mesh_bundle_import_service import MeshBundleImportService


def mesh_bundle_import(context: JobContext) -> dict[str, object]:
    site_name = str(context.params.get("site_name") or "")
    preview_id = str(context.params.get("preview_id") or "")
    raw_mappings = context.params.get("mappings") or ()
    mappings = tuple(dict(item) for item in raw_mappings if isinstance(item, Mapping))
    context.check_cancelled()
    context.progress("mesh_bundle_validate", 0, len(mappings), "正在复验 MESH ZIP 与人工映射")
    result = MeshBundleImportService(site_name, context.paths).import_approved_preview(
        preview_id,
        mappings,
        job_id=context.job_id,
        should_cancel=lambda: bool(context.should_cancel and context.should_cancel()),
        progress=context.progress,
    )
    context.check_cancelled()
    return result


HANDLERS = {"mesh_bundle_import": mesh_bundle_import}


__all__ = ["HANDLERS", "mesh_bundle_import"]
