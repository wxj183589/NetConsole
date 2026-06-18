from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy, QTableWidget, QWidget


ROW_HEIGHT = 30
CHECK_COLUMN_WIDTH = 48
ACTION_COLUMN_WIDTH = 220
ACTION_BUTTON_HEIGHT = 24
HEADER_PADDING = 34
MAX_CONTENT_WIDTH = 520
HIGH_PRIORITY_MIN_WIDTH = 180
MEDIUM_PRIORITY_MIN_WIDTH = 128
LOW_PRIORITY_MIN_WIDTH = 96
MEDIUM_PRIORITY_MAX_WIDTH = 190
LOW_PRIORITY_MAX_WIDTH = 150

COLUMN_POLICY = {
    "select": {"width": CHECK_COLUMN_WIDTH, "fixed": True},
    "name": {"min": HIGH_PRIORITY_MIN_WIDTH, "stretch": True},
    "device_name": {"min": HIGH_PRIORITY_MIN_WIDTH, "stretch": True},
    "ap_name": {"min": HIGH_PRIORITY_MIN_WIDTH, "stretch": True},
    "ip_address": {"width": 120, "fixed": True},
    "ap_ip": {"width": 120, "fixed": True},
    "protocols": {"width": 80, "fixed": True},
    "updated_at": {"width": 160, "fixed": True},
    "collected_at": {"width": 160, "fixed": True},
    "actions": {"width": ACTION_COLUMN_WIDTH, "fixed": True},
}

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

LIGHT_WIDGET_STYLESHEET = """
QPushButton {
    background: #ffffff;
    border: 1px solid #cbd5df;
    border-radius: 4px;
    padding: 6px 10px;
    color: #111827;
}
QPushButton:hover { background: #eef5ff; border-color: #8bb7ee; }
QPushButton:pressed { background: #dbeafe; border-color: #2563eb; }
QPushButton:checked { background: #dbeafe; border-color: #2563eb; color: #1e3a8a; font-weight: 600; }
QPushButton:disabled { background: #f3f4f6; border-color: #d1d5db; color: #9ca3af; }
QPushButton#tableActionButton {
    min-height: 22px;
    max-height: 22px;
    padding: 0 8px;
    border-radius: 5px;
    font-size: 12px;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #cbd5df;
    border-radius: 4px;
    padding: 5px;
    color: #111827;
}
QLineEdit:hover, QComboBox:hover { border-color: #93c5fd; }
QLineEdit:focus, QComboBox:focus { border-color: #2563eb; }
QLineEdit:disabled, QComboBox:disabled { background: #f3f4f6; color: #9ca3af; border-color: #d1d5db; }
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    color: #111827;
    border: 1px solid #dde3ea;
    gridline-color: #edf1f5;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background: #dbeafe; color: #111827; }
QHeaderView::section {
    background: #f3f4f6;
    color: #111827;
    font-weight: 600;
    padding: 6px;
    border: 0;
    border-right: 1px solid #dde3ea;
    border-bottom: 1px solid #dde3ea;
}
"""

DARK_WIDGET_STYLESHEET = """
QPushButton {
    background: #1f2937;
    border: 1px solid #4b5563;
    border-radius: 4px;
    padding: 6px 10px;
    color: #f9fafb;
}
QPushButton:hover { background: #374151; border-color: #60a5fa; }
QPushButton:pressed { background: #1d4ed8; border-color: #93c5fd; }
QPushButton:checked { background: #1d4ed8; border-color: #93c5fd; color: #ffffff; font-weight: 600; }
QPushButton:disabled { background: #111827; border-color: #374151; color: #6b7280; }
QPushButton#tableActionButton {
    min-height: 22px;
    max-height: 22px;
    padding: 0 8px;
    border-radius: 5px;
    font-size: 12px;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit {
    background: #111827;
    color: #f9fafb;
    border: 1px solid #4b5563;
    border-radius: 4px;
    padding: 5px;
}
QLineEdit:hover, QComboBox:hover { border-color: #60a5fa; }
QLineEdit:focus, QComboBox:focus { border-color: #93c5fd; }
QLineEdit:disabled, QComboBox:disabled { background: #0f172a; color: #6b7280; border-color: #374151; }
QTableWidget {
    background: #111827;
    alternate-background-color: #172033;
    color: #f9fafb;
    border: 1px solid #374151;
    gridline-color: #263244;
    selection-background-color: #1d4ed8;
    selection-color: #ffffff;
}
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background: #1d4ed8; color: #ffffff; }
QHeaderView::section {
    background: #1f2937;
    color: #f9fafb;
    font-weight: 600;
    padding: 6px;
    border: 0;
    border-right: 1px solid #374151;
    border-bottom: 1px solid #374151;
}
"""


@dataclass(frozen=True)
class ColumnSizing:
    minimum: int
    maximum: int
    fixed: bool = False
    stretch: bool = False


def apply_dark_theme(widget: QWidget) -> None:
    widget.setStyleSheet(DARK_WIDGET_STYLESHEET)


def set_table_column_fields(table: QTableWidget, fields: list[str] | tuple[str, ...]) -> None:
    table.setProperty("netconsole_column_fields", list(fields))


def apply_table_policy(table: QTableWidget) -> None:
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
    apply_action_column(table)


def apply_table_style(table: QTableWidget) -> None:
    apply_table_policy(table)


def apply_action_column(table: QTableWidget) -> None:
    action_column = _field_index(table, "actions")
    if action_column is None:
        return
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(action_column, QHeaderView.Fixed)
    table.setColumnWidth(action_column, ACTION_COLUMN_WIDTH)


def _apply_column_widths(table: QTableWidget) -> None:
    metrics = table.horizontalHeader().fontMetrics()
    fields = _column_fields(table)
    for column in range(table.columnCount()):
        field = fields[column] if column < len(fields) else ""
        sizing = _column_sizing(table, column, field)
        header_item = table.horizontalHeaderItem(column)
        header_text = header_item.text() if header_item else ""
        header_width = metrics.horizontalAdvance(header_text) + HEADER_PADDING
        content_width = 0 if field == "actions" else table.columnWidth(column)
        target = max(sizing.minimum, header_width, content_width)
        table.setColumnWidth(column, min(target, sizing.maximum))
        table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed if sizing.fixed else QHeaderView.Interactive)


def _apply_stretch_column(table: QTableWidget) -> None:
    fields = _column_fields(table)
    stretch_column = _preferred_stretch_column(table, fields)
    header = table.horizontalHeader()
    stretch_field = fields[stretch_column] if stretch_column is not None and stretch_column < len(fields) else ""
    if stretch_column is not None and stretch_field != "actions":
        header.setSectionResizeMode(stretch_column, QHeaderView.Stretch)
    header.setStretchLastSection(_field_index(table, "actions") is None)


def _preferred_stretch_column(table: QTableWidget, fields: list[str]) -> int | None:
    for wanted in ("name", "device_name", "description", "ap_name", "neighbor_device_name", "interface_name"):
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
    policy = COLUMN_POLICY.get(normalized_field)
    if policy and policy.get("fixed"):
        width = int(policy["width"])
        return ColumnSizing(width, width, fixed=True)
    if policy and policy.get("stretch"):
        return ColumnSizing(int(policy["min"]), MAX_CONTENT_WIDTH, stretch=True)
    if _is_high_priority(normalized_field, normalized_header):
        return ColumnSizing(HIGH_PRIORITY_MIN_WIDTH, MAX_CONTENT_WIDTH, stretch=normalized_field in STRETCH_FIELDS)
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


def _field_index(table: QTableWidget, field: str) -> int | None:
    fields = _column_fields(table)
    return fields.index(field) if field in fields else None


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
