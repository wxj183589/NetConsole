from __future__ import annotations

from pathlib import Path

from netconsole.services.job_center.job_context import JobContext
from netconsole.services.site_storage import DataRootApplicationService, SiteApplicationService, SitePackageService


SITE_STORAGE_OWNER = "site-storage"
SITE_STORAGE_TASK_TYPES = frozenset({"site_data_root_migration", "site_export", "site_import", "site_migration"})


def site_data_root_migration(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DataRootApplicationService(context.paths).migrate(
        Path(str(context.params.get("destination_root") or "")), check_cancel=context.check_cancelled
    )
    context.progress("verify", 1, 1, "数据根迁移完成")
    return result


def site_export(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    sites = SiteApplicationService(context.paths)
    destination = str(context.params.get("destination_path") or "")
    if not destination:
        record = sites.registry.get(str(context.params.get("site_id") or ""))
        destination = str(record.root_path / "files" / "exports" / f"{record.site_id}.ncsite")
    result = SitePackageService(context.paths, sites).export_site(
        str(context.params.get("site_id") or ""), Path(destination), check_cancel=context.check_cancelled
    )
    context.progress("publish", 1, 1, "局点包导出完成")
    return result


def site_migration(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = SiteApplicationService(context.paths).migrate_site(
        str(context.params.get("site_id") or ""),
        Path(str(context.params.get("destination_root") or "")),
        check_cancel=context.check_cancelled,
    )
    context.progress("verify", 1, 1, "局点迁移完成")
    return result


def site_import(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    sites = SiteApplicationService(context.paths)
    result = SitePackageService(context.paths, sites).import_site(
        Path(str(context.params.get("package_path") or "")),
        site_id=str(context.params.get("site_id") or "") or None,
        display_name=str(context.params.get("display_name") or "") or None,
        replace_site_id=str(context.params.get("replace_site_id") or "") or None,
    )
    if bool(context.params.get("activate")):
        result["activation"] = sites.switch_site(str(result["site_id"]))
    context.progress("publish", 1, 1, "局点包导入完成")
    return result


HANDLERS = {
    "site_data_root_migration": site_data_root_migration,
    "site_export": site_export,
    "site_migration": site_migration,
    "site_import": site_import,
}


__all__ = ["HANDLERS", "SITE_STORAGE_OWNER", "SITE_STORAGE_TASK_TYPES"]
