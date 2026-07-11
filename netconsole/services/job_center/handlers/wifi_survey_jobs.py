from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler

wireless_scan_history_refresh = legacy_handler(legacy_tasks._wireless_scan_history_refresh)
wireless_scan_result_load = legacy_handler(legacy_tasks._wireless_scan_result_load)
wifi_survey_refresh = legacy_handler(legacy_tasks._wifi_survey_refresh)
wifi_survey_floor_import = legacy_handler(legacy_tasks._wifi_survey_floor_import)
wifi_survey_create_session = legacy_handler(legacy_tasks._wifi_survey_create_session)
wifi_survey_update_scale = legacy_handler(legacy_tasks._wifi_survey_update_scale)
wifi_survey_save_sample = legacy_handler(legacy_tasks._wifi_survey_save_sample)
wifi_survey_heatmap_render = legacy_handler(legacy_tasks._wifi_survey_heatmap_render)

HANDLERS = {
    name: globals()[name]
    for name in (
        "wireless_scan_history_refresh",
        "wireless_scan_result_load",
        "wifi_survey_refresh",
        "wifi_survey_floor_import",
        "wifi_survey_create_session",
        "wifi_survey_update_scale",
        "wifi_survey_save_sample",
        "wifi_survey_heatmap_render",
    )
}
