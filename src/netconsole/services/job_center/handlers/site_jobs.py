from __future__ import annotations

from pathlib import Path

from netconsole.services.job_center.job_context import JobContext
from netconsole.services.site_lifecycle import (
    DemoSiteSeedService,
    SiteAuditService,
    SiteCleanupApplicationService,
)
from netconsole.services.site_retention import SiteRetentionService
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
)


SITE_STORAGE_OWNER = "site-storage"
SITE_STORAGE_TASK_TYPES = frozenset(
    {
        "site_audit",
        "site_cleanup_apply",
        "site_cleanup_restore",
        "site_data_root_migration",
        "site_demo_rebuild",
        "site_export",
        "site_import",
        "site_migration",
        "site_retention_apply",
        "site_retention_scan",
    }
)
SITE_STORAGE_NONCANCELLABLE_TASK_TYPES = frozenset(
    {
        "site_cleanup_apply",
        "site_cleanup_restore",
        "site_demo_rebuild",
        "site_retention_apply",
    }
)


def site_audit(context: JobContext) -> dict[str, object]:
    result = SiteAuditService(context.paths).audit_all(
        site_id=str(context.params.get("site_id") or "") or None,
        check_cancel=context.check_cancelled,
        progress=lambda current, total, message: context.progress(
            "audit", current, total, message
        ),
    )
    result.pop("data_root", None)
    result.pop("manifest_path", None)
    result.pop("manifest_id", None)
    for site in result.get("sites", []):
        if isinstance(site, dict):
            site.pop("physical_path", None)
            site.pop("file_manifest", None)
    context.progress(
        "audit", int(result["site_count"]), int(result["site_count"]), "局点审计完成"
    )
    return result


def site_cleanup_apply(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = SiteCleanupApplicationService(context.paths).apply_cleanup(
        str(context.params.get("cleanup_token") or "")
    )
    context.progress("recycle", 1, 1, "局点已移入受控回收区")
    return result


def site_cleanup_restore(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = SiteCleanupApplicationService(context.paths).restore_cleanup(
        str(context.params.get("cleanup_token") or "")
    )
    context.progress("restore", 1, 1, "局点已从回收区恢复")
    return result


def site_retention_scan(context: JobContext) -> dict[str, object]:
    return SiteRetentionService(context.paths).scan(
        str(context.params.get("site_id") or ""),
        check_cancel=context.check_cancelled,
        progress=lambda current, total, message: context.progress(
            "retention_scan", current, total, message
        ),
    )


def site_retention_apply(context: JobContext) -> dict[str, object]:
    result = SiteRetentionService(context.paths).apply(
        str(context.params.get("site_id") or ""),
        scan_token=str(context.params.get("scan_token") or ""),
        candidate_ids=[
            str(value)
            for value in context.params.get("candidate_ids", [])
            if str(value).strip()
        ],
        current_job_id=context.job_id,
        check_cancel=context.check_cancelled,
        progress=lambda current, total, message: context.progress(
            "retention_apply", current, total, message
        ),
    )
    context.structured_progress(
        "retention_apply",
        int(result.get("success_count") or 0),
        int(result.get("selected_count") or 0),
        "局点数据清理完成",
        released_bytes=int(result.get("released_bytes") or 0),
    )
    return result


def site_demo_rebuild(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DemoSiteSeedService(context.paths).seed(
        replace=True,
        allow_user_data=bool(context.params.get("allow_user_data")),
        check_cancel=context.check_cancelled,
    )
    context.progress("publish", 1, 1, "演示局点重建完成")
    return result


def site_data_root_migration(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    result = DataRootApplicationService(context.paths).migrate(
        Path(str(context.params.get("destination_root") or "")),
        check_cancel=context.check_cancelled,
    )
    context.progress("verify", 1, 1, "数据根迁移完成")
    return result


def site_export(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    sites = SiteApplicationService(context.paths)
    package_type = str(context.params.get("package_type") or "full_migration")
    destination = str(context.params.get("destination_path") or "")
    if not destination:
        record = sites.registry.get(str(context.params.get("site_id") or ""))
        suffix = ".ncresult" if package_type == "collection_return" else ".zip" if package_type == "lightweight" else ".ncsite"
        destination = str(
            record.root_path / "files" / "exports" / f"{record.site_id}{suffix}"
        )
    result = SitePackageService(context.paths, sites).export_site(
        str(context.params.get("site_id") or ""),
        Path(destination),
        package_type=package_type,
        check_cancel=context.check_cancelled,
    )
    context.progress("publish", 1, 1, "局点数据包导出完成")
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
        raw_only=bool(context.params.get("raw_only")),
        conflict_resolutions=[
            item
            for item in context.params.get("conflict_resolutions", [])
            if isinstance(item, dict)
        ],
    )
    if bool(context.params.get("activate")):
        result["activation"] = sites.switch_site(str(result["site_id"]))
    context.progress("publish", 1, 1, "局点包导入完成")
    return result


HANDLERS = {
    "site_audit": site_audit,
    "site_cleanup_apply": site_cleanup_apply,
    "site_cleanup_restore": site_cleanup_restore,
    "site_data_root_migration": site_data_root_migration,
    "site_demo_rebuild": site_demo_rebuild,
    "site_export": site_export,
    "site_migration": site_migration,
    "site_retention_scan": site_retention_scan,
    "site_retention_apply": site_retention_apply,
    "site_import": site_import,
}


__all__ = [
    "HANDLERS",
    "SITE_STORAGE_NONCANCELLABLE_TASK_TYPES",
    "SITE_STORAGE_OWNER",
    "SITE_STORAGE_TASK_TYPES",
]
