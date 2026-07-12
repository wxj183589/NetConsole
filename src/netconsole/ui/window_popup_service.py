from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget

from netconsole.ui.dialogs.dialog_style import center_dialog
from netconsole.ui.window_registry import window_registry


def show_non_focus_window(
    parent: QWidget | None,
    window: QWidget,
    *,
    key: str | None = None,
    center: bool = True,
    resize_to_screen: bool = True,
    activate: bool = False,
    raise_window: bool = False,
) -> QWidget:
    _ = key, resize_to_screen
    window.setWindowModality(Qt.WindowModality.NonModal)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
    window_registry.register(window, key)
    if center and not window.property("_ncCenteredOnce"):
        QTimer.singleShot(0, lambda w=window, p=parent: center_dialog(w, p))
    window.show()
    if raise_window:
        window.raise_()
    if activate:
        window.activateWindow()
    if parent is not None:
        QTimer.singleShot(0, lambda p=parent: p.setFocus(Qt.FocusReason.OtherFocusReason))
    return window
