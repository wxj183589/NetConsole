from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler

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
