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
    )
}
