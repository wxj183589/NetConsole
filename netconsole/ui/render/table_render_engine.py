from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy, QTableWidget, QWidget

from netconsole.ui.table.table_auto_layout_engine import (
    ACTION_BUTTON_HEIGHT,
    ACTION_COLUMN_WIDTH,
    AP_MAC_COLUMN_WIDTH,
    AP_NAME_MIN_WIDTH,
    CHECK_COLUMN_WIDTH,
    HIGH_PRIORITY_FIELDS,
    HIGH_PRIORITY_MIN_WIDTH,
    LOW_PRIORITY_FIELDS,
    LOW_PRIORITY_MIN_WIDTH,
    MEDIUM_PRIORITY_FIELDS,
    MEDIUM_PRIORITY_MIN_WIDTH,
    ROW_HEIGHT,
    apply_auto_layout,
)
from netconsole.ui.theme.qt_theme_engine import DARK_APP_STYLESHEET, LIGHT_APP_STYLESHEET, apply_dark_theme


STATUS_COLOR_MAP = {
    "normal": "#22c55e",
    "notice": "#fbbf24",
    "warning": "#fbbf24",
    "alarm": "#f87171",
    "link_abnormal": "#fb7185",
    "link_down": "#fb7185",
    "no_light": "#6b7280",
    "no_module": "#9ca3af",
    "skipped": "#374151",
    "not_collected": "#374151",
    "unknown": "#374151",
}

HEADER_PADDING = 34
MAX_CONTENT_WIDTH = 520
MEDIUM_PRIORITY_MAX_WIDTH = 190
LOW_PRIORITY_MAX_WIDTH = 150

COLUMN_POLICY = {
    "select": {"width": CHECK_COLUMN_WIDTH, "fixed": True},
    "name": {"min": HIGH_PRIORITY_MIN_WIDTH, "stretch": True},
    "device_name": {"min": HIGH_PRIORITY_MIN_WIDTH, "stretch": True},
    "ap_name": {"min": AP_NAME_MIN_WIDTH, "stretch": True},
    "ap_mac": {"width": AP_MAC_COLUMN_WIDTH, "fixed": True},
    "ip_address": {"width": 120, "fixed": True},
    "ap_ip": {"width": 120, "fixed": True},
    "protocols": {"width": 80, "fixed": True},
    "updated_at": {"width": 160, "fixed": True},
    "collected_at": {"width": 160, "fixed": True},
    "actions": {"width": ACTION_COLUMN_WIDTH, "fixed": True},
}

STRETCH_FIELDS = {
    "description",
    "name",
    "device_name",
    "ap_name",
    "neighbor_device_name",
    "interface_name",
}

LIGHT_WIDGET_STYLESHEET = LIGHT_APP_STYLESHEET
DARK_WIDGET_STYLESHEET = DARK_APP_STYLESHEET


@dataclass(frozen=True)
class ColumnSizing:
    minimum: int
    maximum: int
    fixed: bool = False
    stretch: bool = False


def set_table_column_fields(table: QTableWidget, fields: list[str] | tuple[str, ...]) -> None:
    table.setProperty("netconsole_column_fields", list(fields))


def apply_table_policy(table: QTableWidget) -> None:
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.verticalHeader().setVisible(False)
    apply_row_height(table)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setMinimumHeight(34)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    if not table.property("netconsole_manual_column_widths"):
        apply_auto_layout(table)


def apply_table_style(table: QTableWidget) -> None:
    apply_table_policy(table)


def apply_table_render(table: QTableWidget) -> None:
    apply_table_policy(table)


def apply_row_height(table: QTableWidget) -> None:
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    for row in range(table.rowCount()):
        table.setRowHeight(row, ROW_HEIGHT)


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
    if stretch_column is not None:
        header.setSectionResizeMode(stretch_column, QHeaderView.Interactive)
    header.setStretchLastSection(False)


def _preferred_stretch_column(table: QTableWidget, fields: list[str]) -> int | None:
    for wanted in ("name", "device_name", "ap_name", "interface_name", "neighbor_device_name", "description"):
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
        return ColumnSizing(MEDIUM_PRIORITY_MIN_WIDTH, MEDIUM_PRIORITY_MAX_WIDTH, fixed=True)
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
