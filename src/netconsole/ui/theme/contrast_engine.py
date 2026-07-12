from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem

from netconsole.ui.render.table_render_engine import STATUS_COLOR_MAP


DARK_TEXT = "#111827"
LIGHT_TEXT = "#ffffff"

STATUS_BACKGROUND_COLORS = STATUS_COLOR_MAP


def get_contrast_text_color(background_color: str | QColor) -> str:
    color = _to_qcolor(background_color)
    if not color.isValid():
        return LIGHT_TEXT
    red = _linear_channel(color.red())
    green = _linear_channel(color.green())
    blue = _linear_channel(color.blue())
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return DARK_TEXT if luminance > 0.55 else LIGHT_TEXT


def status_background_color(status: object | None) -> str | None:
    return STATUS_BACKGROUND_COLORS.get(str(status or ""))


def apply_item_contrast(item: QTableWidgetItem, background_color: str | QColor) -> None:
    background = _to_qcolor(background_color)
    item.setBackground(background)
    item.setForeground(QColor(get_contrast_text_color(background)))


def apply_status_item_contrast(item: QTableWidgetItem, status: object | None) -> None:
    color = status_background_color(status)
    if color:
        apply_item_contrast(item, color)


def _to_qcolor(color: str | QColor) -> QColor:
    if isinstance(color, QColor):
        return QColor(color)
    value = color.strip()
    if value and not value.startswith("#"):
        value = f"#{value}"
    return QColor(value)


def _linear_channel(value: int) -> float:
    channel = value / 255
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4
