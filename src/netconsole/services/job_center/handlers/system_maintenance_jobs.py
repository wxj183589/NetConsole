from __future__ import annotations

from netconsole.core import app_logger
from netconsole.services.app_auto_cleanup import (
    APP_CLEANUP_RETENTION_DAYS,
    AUTO_CLEANUP_ITEM_IDS,
    AppCleanupService,
    finish_auto_cleanup,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.open_source_notice_service import OpenSourceNoticeService


def system_maintenance_cleanup(context: JobContext) -> dict[str, object]:
    automatic = bool(context.params.get("automatic"))
    manual_history = bool(context.params.get("manual_history"))
    retention_value = context.params.get("retention_days", APP_CLEANUP_RETENTION_DAYS)
    days = int(retention_value)
    if not 1 <= days <= 365:
        raise ValueError("保留天数必须在 1 到 365 之间")
    dry_run = bool(context.params.get("dry_run"))
    selected_item_ids = context.params.get("selected_item_ids")
    if not isinstance(selected_item_ids, list):
        raise ValueError("清理项目格式无效")
    if automatic and selected_item_ids != list(AUTO_CLEANUP_ITEM_IDS):
        raise ValueError("自动清理只允许软件运行日志")
    if manual_history and (automatic or selected_item_ids != ["runtime_logs"]):
        raise ValueError("manual history cleanup only permits runtime_logs")
    if dry_run:
        if selected_item_ids or bool(context.params.get("confirmed")):
            raise ValueError("扫描请求不能包含清理选择或确认")
    else:
        if context.params.get("confirmed") is not True:
            raise ValueError("正式清理必须明确确认")
    context.check_cancelled()
    context.progress("scan", 0, 1, "正在扫描受控日志与缓存")
    service = AppCleanupService(context.paths)
    items = service.scan_cleanup_items(days, manual_history=manual_history)
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
    if dry_run:
        context.progress("scan", 1, 1, "白名单扫描完成")
        return result
    selected = service.validate_item_ids(selected_item_ids)
    context.check_cancelled()
    context.progress("clean", 0, 0, "正在重新扫描所选白名单项目")

    def report_progress(current: int, expected_total: int, partial) -> None:
        context.structured_progress(
            "clean",
            current,
            expected_total,
            (
                f"已处理 {partial.processed_files} 项，已删除 {partial.deleted_files} 项，"
                f"失败 {partial.failed_count} 项，释放 {partial.freed_bytes} 字节"
            ),
            processed_files=partial.processed_files,
            deleted_files=partial.deleted_files,
            failed_count=partial.failed_count,
            freed_bytes=partial.freed_bytes,
            deleted_log_records=partial.deleted_log_records,
            scanned_log_records=partial.scanned_log_records,
            malformed_log_records=partial.malformed_log_records,
            rewritten_log_files=partial.rewritten_log_files,
        )

    try:
        rescanned_items, cleaned = service.cleanup_selected(
            selected,
            days,
            should_cancel=context.check_cancelled,
            progress_callback=report_progress,
            manual_history=manual_history,
        )
    except Exception:
        if automatic:
            finish_auto_cleanup(context.paths, context.job_id, succeeded=False)
        raise
    result.update(
        cleanup_items=[
            {
                "item_id": item.item_id,
                "title": item.title,
                "description": item.description,
                "retention_policy": item.retention_policy,
                "status": item.status,
                "file_count": item.file_count,
                "total_bytes": item.total_bytes,
            }
            for item in rescanned_items
        ],
        processed_files=cleaned.processed_files,
        deleted_files=cleaned.deleted_files,
        failed_count=cleaned.failed_count,
        freed_bytes=cleaned.freed_bytes,
        deleted_log_records=cleaned.deleted_log_records,
        scanned_log_records=cleaned.scanned_log_records,
        malformed_log_records=cleaned.malformed_log_records,
        rewritten_log_files=cleaned.rewritten_log_files,
        cutoff=cleaned.cutoff.isoformat(timespec="seconds"),
        automatic=automatic,
    )
    if automatic:
        finish_auto_cleanup(context.paths, context.job_id, succeeded=cleaned.failed_count == 0)
    log = app_logger.log_warning if cleaned.failed_count else app_logger.log_info
    log("APP_AUTO_CLEANUP_PARTIAL_FAILED" if cleaned.failed_count else "APP_AUTO_CLEANUP_COMPLETED", cleaned.summary_detail(), log_path=context.paths.app_log_path)
    context.progress("clean", cleaned.processed_files, cleaned.processed_files, "安全清理完成")
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
