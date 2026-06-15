from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class WindowManager:
    def __init__(self) -> None:
        self.main_window: QWidget | None = None
        self.child_windows: list[QWidget] = []
        self.child_on_top: dict[QWidget, bool] = {}

    def set_main_window(self, window: QWidget) -> None:
        self.main_window = window

    def register_child_window(self, window: QWidget, always_on_top: bool = False) -> None:
        if window not in self.child_windows:
            self.child_windows.append(window)
        self.child_on_top[window] = always_on_top

    def unregister_child_window(self, window: QWidget) -> None:
        if window in self.child_windows:
            self.child_windows.remove(window)
        self.child_on_top.pop(window, None)

    def set_child_on_top(self, window: QWidget, enabled: bool) -> None:
        self.register_child_window(window, enabled)
        if self.main_window is not None and self.main_window.windowFlags() & Qt.WindowStaysOnTopHint:
            enabled = False
        window.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        window.show()

    def apply_main_window_on_top(self, enabled: bool) -> None:
        if self.main_window is None:
            return
        self.main_window.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        if enabled:
            for child in list(self.child_windows):
                child.setWindowFlag(Qt.WindowStaysOnTopHint, False)
                child.show()
        else:
            self.restore_child_window_flags()
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def restore_child_window_flags(self) -> None:
        for child in list(self.child_windows):
            child.setWindowFlag(Qt.WindowStaysOnTopHint, self.child_on_top.get(child, False))
            child.show()


window_manager = WindowManager()
