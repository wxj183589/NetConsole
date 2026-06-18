from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget

from netconsole.ui.table.table_autosize_engine import apply_table_autosize


ROW_HEIGHT = 36
CHECK_COLUMN_WIDTH = 48
ACTION_COLUMN_WIDTH = 220
ACTION_BUTTON_HEIGHT = 28
AP_MAC_COLUMN_WIDTH = 140
AP_NAME_MIN_WIDTH = 180
HIGH_PRIORITY_MIN_WIDTH = 180
MEDIUM_PRIORITY_MIN_WIDTH = 120
LOW_PRIORITY_MIN_WIDTH = 96

HIGH_PRIORITY_FIELDS = {
    "ap_name",
    "name",
    "device_name",
    "neighbor_device_name",
    "interface_name",
    "local_interface",
    "neighbor_interface",
    "description",
}
MEDIUM_PRIORITY_FIELDS = {
    "ap_mac",
    "ip_address",
    "ap_ip",
    "vlan",
    "pvid",
    "status",
    "state_display",
    "port_status",
    "link_status",
    "protocol_status",
    "switch_optical_status",
    "ap_optical_status",
    "optical_alarm_status",
}
LOW_PRIORITY_FIELDS = {
    "updated_at",
    "collected_at",
    "online_time",
    "elapsed",
    "rx_power",
    "tx_power",
    "neighbor_rx_power",
    "temperature",
    "voltage",
    "bias_current",
    "apid",
    "total",
    "online",
    "offline",
}


def apply_auto_layout(table: QTableWidget, screen_width: int | None = None) -> None:
    apply_table_autosize(table, screen_width)


def _install_resize_hook(table: QTableWidget) -> None:
    if table.property("netconsole_auto_layout_hooked"):
        return
    original_resize_event = table.resizeEvent

    def resize_event(event):
        original_resize_event(event)
        apply_auto_layout(table)

    table.resizeEvent = resize_event
    table.setProperty("netconsole_auto_layout_hooked", True)


def _available_width(table: QTableWidget, screen_width: int | None) -> int:
    if screen_width is not None and screen_width > 0:
        return screen_width
    viewport_width = table.viewport().width()
    if viewport_width > 0:
        return viewport_width
    table_width = table.width()
    return table_width if table_width > 0 else 1200


def _fixed_width_for(table: QTableWidget, column: int, field: str) -> int:
    normalized = field.casefold()
    if normalized == "select":
        return CHECK_COLUMN_WIDTH
    if normalized == "actions":
        return ACTION_COLUMN_WIDTH
    if normalized == "ap_mac":
        return AP_MAC_COLUMN_WIDTH
    if normalized in {"ip_address", "ap_ip"}:
        return 120
    if normalized in {"vlan", "pvid", "status", "state_display", "port_status", "link_status", "protocol_status"}:
        return 128
    if normalized in {"updated_at", "collected_at", "online_time"}:
        return 160
    if normalized in LOW_PRIORITY_FIELDS or _header_contains(table, column, ("time", "power", "rx", "tx", "temperature", "voltage")):
        return LOW_PRIORITY_MIN_WIDTH
    return MEDIUM_PRIORITY_MIN_WIDTH


def _minimum_width_for_high(field: str) -> int:
    return AP_NAME_MIN_WIDTH if field.casefold() == "ap_name" else HIGH_PRIORITY_MIN_WIDTH


def _is_high_priority(table: QTableWidget, column: int, field: str) -> bool:
    normalized = field.casefold()
    return normalized in HIGH_PRIORITY_FIELDS or _header_contains(
        table,
        column,
        ("ap name", "ap鍚嶇О", "name", "device", "interface", "description", "璁惧鍚嶇О", "鎺ュ彛鍚嶇О", "鎻忚堪"),
    )


def _header_contains(table: QTableWidget, column: int, tokens: tuple[str, ...]) -> bool:
    item = table.horizontalHeaderItem(column)
    header = (item.text() if item else "").strip().casefold()
    return any(token in header for token in tokens)


def _column_fields(table: QTableWidget) -> list[str]:
    fields = table.property("netconsole_column_fields")
    if isinstance(fields, list):
        return [str(field) for field in fields]
    if isinstance(fields, tuple):
        return [str(field) for field in fields]
    return []
