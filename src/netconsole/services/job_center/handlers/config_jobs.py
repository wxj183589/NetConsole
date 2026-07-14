from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler

config_compare_latest_running_between_devices = legacy_handler(legacy_tasks._config_compare_latest_running_between_devices)
config_compare_latest_snapshots = legacy_handler(legacy_tasks._config_compare_latest_snapshots)
config_compare_snapshot_pair = legacy_handler(legacy_tasks._config_compare_snapshot_pair)
config_snapshot_load_content = legacy_handler(legacy_tasks._config_snapshot_load_content)
config_snapshot_copy = legacy_handler(legacy_tasks._config_snapshot_copy)
config_snapshot_pair_load_content = legacy_handler(legacy_tasks._config_snapshot_pair_load_content)
config_snapshot_delete_many = legacy_handler(legacy_tasks._config_snapshot_delete_many)


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
