from __future__ import annotations

from netconsole.services import config_collection_job_handlers
from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler

config_compare_latest_running_between_devices = legacy_handler(legacy_tasks._config_compare_latest_running_between_devices)
config_compare_latest_snapshots = legacy_handler(legacy_tasks._config_compare_latest_snapshots)
config_compare_snapshot_pair = legacy_handler(legacy_tasks._config_compare_snapshot_pair)
config_snapshot_load_content = legacy_handler(legacy_tasks._config_snapshot_load_content)
config_snapshot_copy = legacy_handler(legacy_tasks._config_snapshot_copy)
config_snapshot_pair_load_content = legacy_handler(legacy_tasks._config_snapshot_pair_load_content)


def config_snapshot_delete_many(context):
    context.check_cancelled()
    repository, service = legacy_tasks._config_snapshot_service(context.params)
    snapshot_ids = [int(value) for value in context.params.get("snapshot_ids") or [] if int(value or 0) > 0]
    total = len(snapshot_ids)
    completed_items = []
    failed_items = []
    config_collection_job_handlers.write_irreversible_checkpoint(
        context,
        {
            "operation": "delete_snapshots",
            "status": "running",
            "total": total,
            "completed_items": completed_items,
            "failed_items": failed_items,
            "current_item": None,
            "pending_items": snapshot_ids,
        },
    )
    for index, snapshot_id in enumerate(snapshot_ids, start=1):
        context.progress("config_snapshot_delete_irreversible", index - 1, max(total, 1), f"正在删除配置快照 {index}/{total}")
        config_collection_job_handlers.write_irreversible_checkpoint(
            context,
            {
                "operation": "delete_snapshots",
                "status": "running",
                "total": total,
                "completed_items": completed_items,
                "failed_items": failed_items,
                "current_item": {"snapshot_id": snapshot_id},
                "pending_items": snapshot_ids[index:],
            },
        )
        try:
            service.delete_snapshot(repository.get(snapshot_id))
            completed_items.append({"snapshot_id": snapshot_id})
        except Exception as exc:
            failed_items.append({"snapshot_id": snapshot_id, "error": str(exc)})
        config_collection_job_handlers.write_irreversible_checkpoint(
            context,
            {
                "operation": "delete_snapshots",
                "status": "running",
                "total": total,
                "completed_items": completed_items,
                "failed_items": failed_items,
                "current_item": None,
                "pending_items": snapshot_ids[index:],
            },
        )
    context.progress("config_snapshot_delete_many", max(total, 1), max(total, 1), "配置快照删除完成")
    result = {
        "total": total,
        "deleted": len(completed_items),
        "failed": len(failed_items),
        "failed_items": failed_items,
        "deleted_snapshot_ids": [int(item["snapshot_id"]) for item in completed_items],
        "partial_success": bool(failed_items),
        "cancel_policy": "before_batch_only",
    }
    config_collection_job_handlers.write_irreversible_checkpoint(
        context,
        {
            "operation": "delete_snapshots",
            "status": "completed",
            "total": total,
            "completed_items": completed_items,
            "failed_items": failed_items,
            "current_item": None,
            "pending_items": [],
            "result": result,
        },
    )
    if failed_items and len(completed_items) == 0:
        details = "；".join(f"{item['snapshot_id']}: {item['error']}" for item in failed_items)
        raise RuntimeError(f"配置快照删除全部失败：{details}")
    return result


def config_web_snapshot_fetch(context):
    context.progress("config_collection", 0, 1, "正在连接设备")
    context.check_cancelled()
    params = dict(context.params)
    repository, service = legacy_tasks._config_snapshot_service(params)
    device = legacy_tasks._device_by_uuid(repository.database, str(params.get("device_uuid") or ""))
    result = service.fetch_configs(device)
    if not result.success:
        raise RuntimeError(result.error_message or "配置采集失败")
    context.progress("config_collection", 1, 1, "配置采集完成")
    return {
        "action": "fetch",
        "device_uuid": result.device_uuid,
        "timestamp": result.timestamp,
        "snapshot_ids": [snapshot.id for snapshot in result.snapshots if snapshot.id is not None],
        "snapshot_types": [snapshot.type for snapshot in result.snapshots],
        "warning_message": result.warning_message or "",
    }


HANDLERS = {
    name: globals()[name]
    for name in (
        "config_compare_latest_running_between_devices",
        "config_compare_latest_snapshots",
        "config_compare_snapshot_pair",
        "config_snapshot_load_content",
        "config_snapshot_copy",
        "config_snapshot_pair_load_content",
        "config_snapshot_delete_many",
        "config_web_snapshot_fetch",
    )
}
HANDLERS.update(config_collection_job_handlers.HANDLERS)
