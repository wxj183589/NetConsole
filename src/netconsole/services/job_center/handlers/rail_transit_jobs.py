from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.rail_transit.car_network_diagnostic_job import run_car_network_diagnostic
from netconsole.services.rail_transit.switch_vendor_sample_job import (
    run_switch_vendor_sample_collect,
)
from netconsole.services.rail_transit.trackside_ap_update_job import run_trackside_ap_optical_update
from netconsole.services.rail_transit.vehicle_mr_online_collection_job import run_vehicle_mr_online_collection
from netconsole.services.wps_trackside_ap_sync import TracksideApWpsSyncService, WPS_SYNC_TASK_TYPE

trackside_interface_history_page = legacy_handler(legacy_tasks._trackside_interface_history_page)
car_network_point_table_import = legacy_handler(legacy_tasks._car_network_point_table_import)
car_network_point_table_load = legacy_handler(legacy_tasks._car_network_point_table_load)
car_network_refresh_all = legacy_handler(legacy_tasks._car_network_refresh_all)
car_network_generate_point_table = legacy_handler(legacy_tasks._car_network_generate_point_table)
car_network_save_point_table = legacy_handler(legacy_tasks._car_network_save_point_table)
trackside_ap_plan_import = legacy_handler(legacy_tasks._trackside_ap_plan_import)
trackside_ap_plan_refresh = legacy_handler(legacy_tasks._trackside_ap_plan_refresh)
trackside_ap_plan_save = legacy_handler(legacy_tasks._trackside_ap_plan_save)
trackside_device_detail_resolve = legacy_handler(legacy_tasks._trackside_device_detail_resolve)
trackside_fit_ap_detail_resolve = legacy_handler(legacy_tasks._trackside_fit_ap_detail_resolve)

HANDLERS = {
    name: globals()[name]
    for name in (
        "trackside_interface_history_page",
        "car_network_point_table_import",
        "car_network_point_table_load",
        "car_network_refresh_all",
        "car_network_generate_point_table",
        "car_network_save_point_table",
        "trackside_ap_plan_import",
        "trackside_ap_plan_refresh",
        "trackside_ap_plan_save",
        "trackside_device_detail_resolve",
        "trackside_fit_ap_detail_resolve",
    )
}
HANDLERS.update(
    {
        "car_network_diagnostic": run_car_network_diagnostic,
        "switch_vendor_sample_collect": run_switch_vendor_sample_collect,
        "trackside_ap_optical_update": run_trackside_ap_optical_update,
        "vehicle_mr_online_collection_start": run_vehicle_mr_online_collection,
    }
)


def trackside_ap_wps_sync(context):
    """在 Job Center Worker 中冻结一次快照并同步 WPS 云文档。"""

    context.check_cancelled()
    target_codes = tuple(
        str(value)
        for value in (context.params.get("target_codes") or ())
        if str(value).strip()
    )
    service = TracksideApWpsSyncService(context.paths)
    result = service.sync(
        str(context.params.get("site_name") or ""),
        target_codes=target_codes,
        expected_revision=str(context.params.get("expected_revision") or ""),
        initialize_binding=bool(context.params.get("initialize_binding")),
        progress=context.progress,
        should_cancel=context.check_cancelled,
    )
    context.check_cancelled()
    return result


HANDLERS[WPS_SYNC_TASK_TYPE] = trackside_ap_wps_sync
