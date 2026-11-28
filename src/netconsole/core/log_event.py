from __future__ import annotations

import re


_DETAIL_TOKEN_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)=(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;]+)")

_EVENT_PREFIXES = {
    "startup": ("APP_START", "BOOT_", "STARTUP", "UI_STARTUP", "HOST_ENVIRONMENT", "DATA_ROOT_CONTEXT", "BUILD_IDENTITY", "FEATURE_GATE_LOADED", "RUNTIME_CAPABILITY_POLICY", "FULL_EDITION_FEATURE_GATE_ACTIVATED", "PACKAGED_FEATURE_POLICY_LOADED"),
    "api_error": ("API_REQUEST_FAILED", "API_EXCEPTION", "HTTP_ERROR"),
    "api_request": ("API_", "HTTP_REQUEST"),
    "ssh": ("SSH_",),
    "telnet": ("TELNET_",),
    "serial": ("COM_", "SERIAL_"),
    "connection": ("TEST_CONNECTION_", "DEVICE_CONNECTION_"),
    "collection": ("DEVICE_COLLECT", "FIT_AP_", "AP_OPTICAL_", "TRACKSIDE_AP_", "GROUND_", "MESH_", "ONLINE_MR_"),
    "task": ("TASK_", "BACKGROUND_TASK_", "JOB_", "WEB_EXPORT_"),
    "database": ("DATABASE_", "DB_", "SQLITE_", "DEVICE_TYPE_MIGRATION_"),
    "files": ("FILE_", "DEVICE_FILE_", "SFTP_"),
    "syslog": ("SYSLOG_",),
    "heartbeat": ("HEARTBEAT_",),
    "network": ("NETWORK_SERVICE_", "LOCAL_SERVICE_", "LOCAL_NETWORK_SERVICE_"),
    "security": ("SECURITY_", "COMMAND_ALLOWED", "HOST_KEY_"),
    "update": ("UPDATE_", "INSTALL_", "INSTALLER_"),
    "application": ("APP_", "LOGS_", "UI_", "PAGE_", "DESKTOP_", "SYSTEM_", "OPEN_SOURCE_"),
}
_CONTEXT_KEYS = {
    "source": ("source",),
    "module": ("module",),
    "site_id": ("site_id", "site_name", "site", "current_site"),
    "device_id": ("device_id", "device_uuid"),
    "request_id": ("request_id",),
    "task_id": ("task_id", "job_id"),
}


def log_context(row: dict[str, str]) -> dict[str, str]:
    event = row.get("event", "").partition(":")[0].upper()
    category = next((name for name, prefixes in _EVENT_PREFIXES.items() if event.startswith(prefixes)), "other")
    tokens = {match["key"].lower(): strip_detail_quotes(match["value"]) for match in _DETAIL_TOKEN_RE.finditer(row.get("detail", ""))}
    context = {
        key: row.get(key) or next((tokens[alias] for alias in aliases if tokens.get(alias)), "")
        for key, aliases in _CONTEXT_KEYS.items()
    }
    stored_category = row.get("category")
    return {**context, "category": stored_category if stored_category and stored_category != "other" else category, "event_code": row.get("event_code") or event, "source": context["source"] or "backend"}



def strip_detail_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
