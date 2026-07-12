from __future__ import annotations

import ctypes
import os
import platform
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from netconsole.ui.shell.theme import FRAME_RESIZE_BORDER
from netconsole.ui.shell.title_bar import AppTitleBar
from netconsole.ui.shell.window_effects import WindowEffectState, apply_window_effect


WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17


class AppFramelessMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._frameless_enabled = self._should_enable_frameless()
        if self._frameless_enabled:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.title_bar = AppTitleBar(self)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_restore_requested.connect(self.toggle_max_restore)
        self.title_bar.close_requested.connect(self.close)

        self._shell = QWidget()
        self._shell.setObjectName("appShell")
        self._shell_layout = QVBoxLayout(self._shell)
        self._shell_layout.setContentsMargins(1, 1, 1, 1)
        self._shell_layout.setSpacing(0)
        self._shell_layout.addWidget(self.title_bar)
        self._content_widget: QWidget | None = None
        QMainWindow.setCentralWidget(self, self._shell)
        self._window_effect_state = WindowEffectState(requested="none", applied="none")

    @staticmethod
    def _should_enable_frameless() -> bool:
        if os.environ.get("NETCONSOLE_FRAMELESS", "1").strip() == "0":
            return False
        return platform.system().lower() == "windows"

    @property
    def frameless_enabled(self) -> bool:
        return self._frameless_enabled

    @property
    def window_effect_state(self) -> WindowEffectState:
        return self._window_effect_state

    def setCentralWidget(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        if self._content_widget is not None:
            self._shell_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)
        widget.setObjectName(widget.objectName() or "appContent")
        self._content_widget = widget
        self._shell_layout.addWidget(widget, 1)

    def contentWidget(self) -> QWidget | None:
        return self._content_widget

    def setWindowTitle(self, title: str) -> None:
        super().setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.title_label.setText(title)

    def set_title_bar_context(self, *, site_name: str, status: str = "就绪") -> None:
        self.title_bar.set_context(site_name, status)

    def set_title_bar_theme(self, theme: str) -> None:
        self.title_bar.set_theme(theme)

    def toggle_max_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.title_bar.set_maximized(self.isMaximized())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._window_effect_state.requested == "none" and self._window_effect_state.applied == "none":
            self._window_effect_state = apply_window_effect(self)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self.title_bar.set_maximized(self.isMaximized())
            margin = 0 if self.isMaximized() else 1
            self._shell_layout.setContentsMargins(margin, margin, margin, margin)
        super().changeEvent(event)

    def nativeEvent(self, event_type, message):
        if not self._frameless_enabled or "windows" not in str(event_type).lower():
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message != WM_NCHITTEST:
            return False, 0
        hit_test = self._hit_test(_point_from_lparam(msg.lParam))
        if hit_test == HTCLIENT:
            return False, 0
        return True, hit_test

    def _hit_test(self, global_pos: QPoint) -> int:
        if self.isMaximized() or self.isFullScreen():
            return HTCAPTION if self.title_bar.is_drag_area(global_pos) else HTCLIENT

        rect = self.geometry()
        border = FRAME_RESIZE_BORDER
        left = global_pos.x() <= rect.left() + border
        right = global_pos.x() >= rect.right() - border
        top = global_pos.y() <= rect.top() + border
        bottom = global_pos.y() >= rect.bottom() - border

        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM
        if self.title_bar.is_drag_area(global_pos):
            return HTCAPTION
        return HTCLIENT


def _point_from_lparam(lparam: int) -> QPoint:
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    return QPoint(x, y)
