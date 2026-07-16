from __future__ import annotations

from netconsole.core import app_logger
from netconsole.services.app_auto_cleanup import APP_CLEANUP_RETENTION_DAYS, AppCleanupService
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.open_source_notice_service import OpenSourceNoticeService


def system_maintenance_cleanup(context: JobContext) -> dict[str, object]:
    days = max(1, int(context.params.get("retention_days") or APP_CLEANUP_RETENTION_DAYS))
    context.check_cancelled()
    context.progress("scan", 0, 1, "正在扫描受控日志与缓存")
    service = AppCleanupService(context.paths)
    items = service.scan_cleanup_items(days)
    result: dict[str, object] = {
        "cleanup_items": [
            {
                "item_id": item.item_id,
                "title": item.title,
                "description": item.description,
                "retention_policy": item.retention_policy,
                "status": item.status,
                "file_count": item.file_count,
                "total_bytes": item.total_bytes,
            }
            for item in items
        ]
    }
    if bool(context.params.get("dry_run")):
        context.progress("scan", 1, 1, "白名单扫描完成")
        return result
    context.check_cancelled()
    total = sum(item.file_count for item in items)
    context.progress("clean", 0, total, "正在清理受控日志与缓存")
    cleaned = service.cleanup_items(items, days, should_cancel=context.check_cancelled)
    result.update(
        deleted_files=cleaned.deleted_files,
        failed_count=cleaned.failed_count,
        freed_bytes=cleaned.freed_bytes,
    )
    log = app_logger.log_warning if cleaned.failed_count else app_logger.log_info
    log("APP_AUTO_CLEANUP_PARTIAL_FAILED" if cleaned.failed_count else "APP_AUTO_CLEANUP_COMPLETED", cleaned.summary_detail(), log_path=context.paths.app_log_path)
    context.progress("clean", total, total, "安全清理完成")
    return result


def open_source_notice_scan(context: JobContext) -> dict[str, object]:
    context.check_cancelled()
    context.progress("scan", 0, 1, "正在扫描运行依赖")
    components = OpenSourceNoticeService(context.paths.app_root).list_components()
    context.check_cancelled()
    context.progress("scan", 1, 1, f"已扫描 {len(components)} 个第三方组件")
    return {"components": [component.__dict__ for component in components]}


HANDLERS = {
    "system_maintenance_cleanup": system_maintenance_cleanup,
    "open_source_notice_scan": open_source_notice_scan,
}


__all__ = ["HANDLERS"]
