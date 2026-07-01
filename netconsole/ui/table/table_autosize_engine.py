from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget


DEFAULT_PADDING = 28
DEFAULT_CHAR_PIXEL = 8
MIN_COLUMN_WIDTH = 72
MAX_COLUMN_WIDTH = 520
HIGH_PRIORITY_MIN_WIDTH = 180
MEDIUM_PRIORITY_MIN_WIDTH = 112
LOW_PRIORITY_MIN_WIDTH = 82
MEDIUM_PRIORITY_MAX_WIDTH = 190
LOW_PRIORITY_MAX_WIDTH = 150
ACTION_COLUMN_WIDTH = 320
CHECK_COLUMN_WIDTH = 48

HIGH_PRIORITY_FIELDS = {
    "ap_name",
    "name",
    "device_name",
    "neighbor_device_name",
    "interface_name",
    "local_interface",
    "neighbor_interface",
    "description",
    "site",
}
MEDIUM_PRIORITY_FIELDS = {
    "ap_mac",
    "mac_address",
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
    "id",
    "total",
    "online",
    "offline",
}


@dataclass(frozen=True)
class AutosizeColumn:
    width: int
    priority: str


def weighted_text_length(value: object) -> int:
    length = 0
    for char in str(value or ""):
        length += 2 if _is_wide_char(char) else 1
    return length


def weighted_text_pixel_width(value: object, char_pixel: int = DEFAULT_CHAR_PIXEL) -> int:
    return weighted_text_length(value) * char_pixel


def calculate_column_widths(table: QTableWidget, screen_width: int | None = None) -> dict[int, int]:
    if table.columnCount() <= 0:
        return {}

    fields = _column_fields(table)
    table.resizeColumnsToContents()
    base: dict[int, AutosizeColumn] = {}
    for column in range(table.columnCount()):
        field = fields[column] if column < len(fields) else ""
        priority = _column_priority(field, _header_text(table, column))
        width = _base_column_width(table, column, priority)
        base[column] = AutosizeColumn(width=width, priority=priority)

    available_width = _available_width(table, screen_width)
    target = {column: sizing.width for column, sizing in base.items()}
    used = sum(target.values())
    high_columns = [column for column, sizing in base.items() if sizing.priority == "high"]
    remaining = available_width - used
    if remaining > 0 and high_columns:
        per_column = remaining // len(high_columns)
        extra = remaining - per_column * len(high_columns)
        for index, column in enumerate(high_columns):
            target[column] += per_column + (extra if index == len(high_columns) - 1 else 0)
    elif remaining < 0:
        target = _compress_columns(target, base, abs(remaining))
    return target


def apply_table_autosize(table: QTableWidget, screen_width: int | None = None) -> dict[int, int]:
    widths = calculate_column_widths(table, screen_width)
    if not widths:
        return {}

    _install_resize_hook(table)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(True)
    for column, width in widths.items():
        field = _field_for(table, column)
        if field == "actions":
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            table.setColumnWidth(column, ACTION_COLUMN_WIDTH)
            widths[column] = ACTION_COLUMN_WIDTH
        elif field == "select":
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            table.setColumnWidth(column, CHECK_COLUMN_WIDTH)
            widths[column] = CHECK_COLUMN_WIDTH
        else:
            table.setColumnWidth(column, width)
            if _column_priority(field, _header_text(table, column)) == "high":
                header.setSectionResizeMode(column, QHeaderView.Stretch)
    table.setProperty("netconsole_auto_layout_widths", widths)
    return widths


def excel_column_width(value: object, minimum: float = 8.0, maximum: float = 60.0) -> float:
    width = weighted_text_length(value) * 1.15 + 2
    return max(minimum, min(width, maximum))


def calculate_excel_column_widths(
    headers: Sequence[object],
    rows: Iterable[Mapping[str, object | None] | Sequence[object]],
    fields: Sequence[str] | None = None,
) -> list[float]:
    widths = [excel_column_width(header) for header in headers]
    for row in rows:
        for index in range(len(widths)):
            value: object | None
            if isinstance(row, Mapping):
                field = fields[index] if fields and index < len(fields) else str(headers[index])
                value = row.get(field)
            else:
                value = row[index] if index < len(row) else None
            widths[index] = max(widths[index], excel_column_width(value))
    return widths


def apply_worksheet_column_widths(
    sheet,
    headers: Sequence[object],
    rows: Iterable[Mapping[str, object | None] | Sequence[object]],
    fields: Sequence[str] | None = None,
    maximum: float = 60.0,
) -> None:
    from openpyxl.utils import get_column_letter

    for index, width in enumerate(calculate_excel_column_widths(headers, rows, fields), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = min(width, maximum)


def apply_worksheet_autofit(sheet, maximum: float = 60.0) -> None:
    from openpyxl.utils import get_column_letter

    for column_index in range(1, sheet.max_column + 1):
        width = 0.0
        for cell in sheet[get_column_letter(column_index)]:
            width = max(width, excel_column_width(cell.value, maximum=maximum))
        sheet.column_dimensions[get_column_letter(column_index)].width = min(width, maximum)


def _install_resize_hook(table: QTableWidget) -> None:
    if table.property("netconsole_table_autosize_hooked"):
        return
    original_resize_event = table.resizeEvent

    def resize_event(event):
        original_resize_event(event)
        apply_table_autosize(table)

    table.resizeEvent = resize_event
    table.setProperty("netconsole_table_autosize_hooked", True)


def _base_column_width(table: QTableWidget, column: int, priority: str) -> int:
    header_width = max(_font_width(table, _header_text(table, column)), weighted_text_pixel_width(_header_text(table, column))) + DEFAULT_PADDING
    content_width = 0
    for row in range(table.rowCount()):
        item = table.item(row, column)
        text = item.text() if item else ""
        content_width = max(content_width, _font_width(table, text), weighted_text_pixel_width(text))
    width = max(header_width, content_width + DEFAULT_PADDING, table.columnWidth(column))
    if priority == "high":
        return max(HIGH_PRIORITY_MIN_WIDTH, min(width, MAX_COLUMN_WIDTH))
    if priority == "medium":
        return max(MEDIUM_PRIORITY_MIN_WIDTH, min(width, MEDIUM_PRIORITY_MAX_WIDTH))
    if priority == "low":
        return max(LOW_PRIORITY_MIN_WIDTH, min(width, LOW_PRIORITY_MAX_WIDTH))
    return max(MIN_COLUMN_WIDTH, min(width, MAX_COLUMN_WIDTH))


def _compress_columns(target: dict[int, int], base: dict[int, AutosizeColumn], overflow: int) -> dict[int, int]:
    result = dict(target)
    for priority, minimum in (("low", LOW_PRIORITY_MIN_WIDTH), ("medium", MEDIUM_PRIORITY_MIN_WIDTH), ("normal", MIN_COLUMN_WIDTH), ("high", HIGH_PRIORITY_MIN_WIDTH)):
        columns = [column for column, sizing in base.items() if sizing.priority == priority]
        for column in columns:
            if overflow <= 0:
                return result
            reducible = max(result[column] - minimum, 0)
            reduction = min(reducible, overflow)
            result[column] -= reduction
            overflow -= reduction
    return result


def _available_width(table: QTableWidget, screen_width: int | None) -> int:
    if screen_width and screen_width > 0:
        return screen_width
    width = table.viewport().width() or table.width()
    return width if width > 0 else 1200


def _column_priority(field: str, header: str) -> str:
    normalized_field = field.casefold()
    normalized_header = header.casefold()
    if normalized_field in {"actions", "select"}:
        return "utility"
    if normalized_field in HIGH_PRIORITY_FIELDS or any(token in normalized_header for token in ("ap名称", "ap name", "设备名称", "device name", "接口名称", "interface", "描述", "description", "车站", "station")):
        return "high"
    if normalized_field in MEDIUM_PRIORITY_FIELDS or any(token in normalized_header for token in ("mac", "ip", "vlan", "pvid", "状态", "status")):
        return "medium"
    if normalized_field in LOW_PRIORITY_FIELDS or any(token in normalized_header for token in ("time", "时间", "id", "rx", "tx", "power", "功率")):
        return "low"
    return "normal"


def _font_width(table: QTableWidget, value: object) -> int:
    return table.fontMetrics().horizontalAdvance(str(value or ""))


def _header_text(table: QTableWidget, column: int) -> str:
    item = table.horizontalHeaderItem(column)
    return item.text() if item else ""


def _field_for(table: QTableWidget, column: int) -> str:
    fields = _column_fields(table)
    return fields[column] if column < len(fields) else ""


def _column_fields(table: QTableWidget) -> list[str]:
    fields = table.property("netconsole_column_fields")
    if isinstance(fields, list):
        return [str(field) for field in fields]
    if isinstance(fields, tuple):
        return [str(field) for field in fields]
    return []


def _is_wide_char(char: str) -> bool:
    return ord(char) > 127
