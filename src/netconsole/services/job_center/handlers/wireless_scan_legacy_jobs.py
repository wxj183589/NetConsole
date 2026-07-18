from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler


wireless_scan_history_refresh = legacy_handler(
    legacy_tasks._wireless_scan_history_refresh
)
wireless_scan_result_load = legacy_handler(legacy_tasks._wireless_scan_result_load)

HANDLERS = {
    "wireless_scan_history_refresh": wireless_scan_history_refresh,
    "wireless_scan_result_load": wireless_scan_result_load,
}
