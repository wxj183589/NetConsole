from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QScrollArea, QVBoxLayout, QWidget


def install_scrollable_widget_content(
    container: QWidget,
    content: QWidget,
    *,
    minimum_width: int,
    minimum_height: int,
    content_minimum_width: int | None = None,
) -> QScrollArea:
    """Wrap top-level widget content so narrow or short windows remain usable."""

    container.setMinimumSize(minimum_width, minimum_height)
    content.setMinimumWidth(content_minimum_width or max(320, minimum_width - 40))

    scroll_area = QScrollArea(container)
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setWidget(content)

    outer_layout = QVBoxLayout(container)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.addWidget(scroll_area)
    return scroll_area


def install_scrollable_dialog_content(
    dialog: QDialog,
    content: QWidget,
    *,
    minimum_width: int,
    minimum_height: int,
    content_minimum_width: int | None = None,
) -> QScrollArea:
    """Wrap dialog content so narrow or short windows scroll instead of clipping controls."""
    return install_scrollable_widget_content(
        dialog,
        content,
        minimum_width=minimum_width,
        minimum_height=minimum_height,
        content_minimum_width=content_minimum_width,
    )
