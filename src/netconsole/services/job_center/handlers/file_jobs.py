from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler

file_management_navigation_refresh = legacy_handler(legacy_tasks._file_management_navigation_refresh)

HANDLERS = {"file_management_navigation_refresh": file_management_navigation_refresh}
