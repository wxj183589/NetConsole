from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy, QTableWidget


ROW_HEIGHT = 30
CHECK_COLUMN_WIDTH = 48
HIGH_PRIORITY_MIN_WIDTH = 180
MEDIUM_PRIORITY_MIN_WIDTH = 128
LOW_PRIORITY_MIN_WIDTH = 96
ACTION_COLUMN_MIN_WIDTH = 220
HEADER_PADDING = 34
MAX_CONTENT_WIDTH = 520
MEDIUM_PRIORITY_MAX_WIDTH = 190
LOW_PRIORITY_MAX_WIDTH = 150

HIGH_PRIORITY_FIELDS = {
    "ap_name",
    "ap_mac",
    "name",
    "device_name",
    "neighbor_device_name",
    "interface_name",
    "local_interface",
    "neighbor_interface",
    "description",
}
MEDIUM_PRIORITY_FIELDS = {
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
STRETCH_FIELDS = {
    "description",
    "name",
    "device_name",
    "ap_name",
    "neighbor_device_name",
    "interface_name",
}


@dataclass(frozen=True)
class ColumnSizing:
    minimum: int
    maximum: int
    stretch: bool = False


def set_table_column_fields(table: QTableWidget, fields: list[str] | tuple[str, ...]) -> None:
    table.setProperty("netconsole_column_fields", list(fields))


def apply_table_style(table: QTableWidget) -> None:
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setMinimumHeight(34)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(True)
    table.resizeColumnsToContents()
    _apply_column_widths(table)
    _apply_stretch_column(table)


def _apply_column_widths(table: QTableWidget) -> None:
    metrics = table.horizontalHeader().fontMetrics()
    fields = _column_fields(table)
    for column in range(table.columnCount()):
        sizing = _column_sizing(table, column, fields[column] if column < len(fields) else "")
        header_item = table.horizontalHeaderItem(column)
        header_text = header_item.text() if header_item else ""
        header_width = metrics.horizontalAdvance(header_text) + HEADER_PADDING
        content_width = table.columnWidth(column)
        target = max(sizing.minimum, header_width, content_width)
        table.setColumnWidth(column, min(target, sizing.maximum))


def _apply_stretch_column(table: QTableWidget) -> None:
    fields = _column_fields(table)
    stretch_column = _preferred_stretch_column(table, fields)
    header = table.horizontalHeader()
    for column in range(table.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.Interactive)
    if stretch_column is not None:
        header.setSectionResizeMode(stretch_column, QHeaderView.Stretch)
    header.setStretchLastSection(True)


def _preferred_stretch_column(table: QTableWidget, fields: list[str]) -> int | None:
    for wanted in ("description", "name", "device_name", "ap_name", "neighbor_device_name", "interface_name"):
        if wanted in fields:
            return fields.index(wanted)
    for column in range(table.columnCount()):
        header = _normalized_header(table, column)
        if any(token in header for token in ("description", "name", "设备名称", "接口名称", "描述", "ap名称")):
            return column
    return table.columnCount() - 1 if table.columnCount() else None


def _column_sizing(table: QTableWidget, column: int, field: str) -> ColumnSizing:
    normalized_header = _normalized_header(table, column)
    normalized_field = field.casefold()
    if normalized_field == "select":
        return ColumnSizing(CHECK_COLUMN_WIDTH, CHECK_COLUMN_WIDTH)
    if normalized_field == "actions":
        return ColumnSizing(ACTION_COLUMN_MIN_WIDTH, MAX_CONTENT_WIDTH, True)
    if _is_high_priority(normalized_field, normalized_header):
        return ColumnSizing(HIGH_PRIORITY_MIN_WIDTH, MAX_CONTENT_WIDTH, normalized_field in STRETCH_FIELDS)
    if _is_medium_priority(normalized_field, normalized_header):
        return ColumnSizing(MEDIUM_PRIORITY_MIN_WIDTH, MEDIUM_PRIORITY_MAX_WIDTH)
    if _is_low_priority(normalized_field, normalized_header):
        return ColumnSizing(LOW_PRIORITY_MIN_WIDTH, LOW_PRIORITY_MAX_WIDTH)
    return ColumnSizing(MEDIUM_PRIORITY_MIN_WIDTH, MAX_CONTENT_WIDTH)


def _is_high_priority(field: str, header: str) -> bool:
    return field in HIGH_PRIORITY_FIELDS or any(
        token in header
        for token in (
            "ap_mac",
            "ap mac",
            "mac",
            "ap名称",
            "设备名称",
            "接口名称",
            "description",
            "描述",
            "interface",
            "device name",
            "ap name",
        )
    )


def _is_medium_priority(field: str, header: str) -> bool:
    return field in MEDIUM_PRIORITY_FIELDS or any(token in header for token in ("ip", "vlan", "pvid", "status", "状态"))


def _is_low_priority(field: str, header: str) -> bool:
    return field in LOW_PRIORITY_FIELDS or any(token in header for token in ("time", "时间", "power", "rx", "tx", "temperature", "voltage"))


def _column_fields(table: QTableWidget) -> list[str]:
    fields = table.property("netconsole_column_fields")
    if isinstance(fields, list):
        return [str(field) for field in fields]
    if isinstance(fields, tuple):
        return [str(field) for field in fields]
    return []


def _normalized_header(table: QTableWidget, column: int) -> str:
    item = table.horizontalHeaderItem(column)
    return (item.text() if item else "").strip().casefold()
