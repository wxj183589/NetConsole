from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.device_management_web_service import (
    run_device_connection_test,
    run_device_csv_import,
    run_device_diagnostic_download,
    run_device_optical_refresh,
)
from netconsole.services.device_operation_service import run_device_inventory_refresh

device_csv_import = run_device_csv_import
device_list_page = legacy_handler(legacy_tasks._device_list_page)
device_object_history_page = legacy_handler(legacy_tasks._device_object_history_page)
device_detail_load_all = legacy_handler(legacy_tasks._device_detail_load_all)
fit_ap_detail_load = legacy_handler(legacy_tasks._fit_ap_detail_load)
fit_ap_metadata_save = legacy_handler(legacy_tasks._fit_ap_metadata_save)
device_mutation = legacy_handler(legacy_tasks._device_mutation)
device_lookup = legacy_handler(legacy_tasks._device_lookup)
device_group_refresh = legacy_handler(legacy_tasks._device_group_refresh)
device_group_create = legacy_handler(legacy_tasks._device_group_create)
device_group_rename = legacy_handler(legacy_tasks._device_group_rename)
device_group_count_devices = legacy_handler(legacy_tasks._device_group_count_devices)
device_group_delete = legacy_handler(legacy_tasks._device_group_delete)

HANDLERS = {
    "device_csv_import": device_csv_import,
    "device_list_page": device_list_page,
    "device_object_history_page": device_object_history_page,
    "device_detail_load_all": device_detail_load_all,
    "fit_ap_detail_load": fit_ap_detail_load,
    "fit_ap_metadata_save": fit_ap_metadata_save,
    "device_mutation": device_mutation,
    "device_lookup": device_lookup,
    "device_group_refresh": device_group_refresh,
    "device_group_create": device_group_create,
    "device_group_rename": device_group_rename,
    "device_group_count_devices": device_group_count_devices,
    "device_group_delete": device_group_delete,
    "device_connection_test": run_device_connection_test,
    "device_detail_collect": run_device_inventory_refresh,
    "device_optical_refresh": run_device_optical_refresh,
    "device_diagnostic_download": run_device_diagnostic_download,
}
