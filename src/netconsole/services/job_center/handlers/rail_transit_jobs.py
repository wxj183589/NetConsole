from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.rail_transit.car_network_diagnostic_job import run_car_network_diagnostic
from netconsole.services.rail_transit.switch_vendor_sample_job import (
    run_switch_vendor_sample_collect,
)
from netconsole.services.rail_transit.trackside_ap_update_job import run_trackside_ap_optical_update
from netconsole.services.rail_transit.vehicle_mr_online_collection_job import run_vehicle_mr_online_collection

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
