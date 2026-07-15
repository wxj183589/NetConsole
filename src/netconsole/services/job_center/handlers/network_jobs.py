from __future__ import annotations

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.network_tools.job_handlers import HANDLERS as NETWORK_TOOL_HANDLERS

network_profile_store = legacy_handler(legacy_tasks._network_profile_store)

HANDLERS = {"network_profile_store": network_profile_store, **NETWORK_TOOL_HANDLERS}
