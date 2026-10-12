"""Shared task contract constants for system-maintenance consumers."""

SYSTEM_MAINTENANCE_WEB_OWNER = "web_system_maintenance"
SYSTEM_MAINTENANCE_TASK_TYPES = frozenset(
    {
        "system_maintenance_cleanup",
        "open_source_notice_scan",
        "web_export_app_logs_csv",
        "web_export_open_source_notices",
        "web_export_field_diagnostic_bundle",
    }
)
