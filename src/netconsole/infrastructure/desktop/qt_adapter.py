from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon

from netconsole.application.desktop import (
    DesktopActionResult,
    DesktopSelectionPurpose,
    RegisteredLaunch,
    RegisteredNotification,
)


class QtDesktopAdapter:
    def __init__(self, notification_icon: QSystemTrayIcon | None = None) -> None:
        self._notification_icon = notification_icon

    def select_file(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        try:
            path, _selected_filter = QFileDialog.getOpenFileName(None, "选择导入文件")
            return _selection_result(path)
        except (OSError, RuntimeError):
            return DesktopActionResult(False, "selection_failed", "系统文件选择器不可用")

    def select_files(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        try:
            paths, _selected_filter = QFileDialog.getOpenFileNames(None, "选择导入文件")
            return _selection_result(*paths)
        except (OSError, RuntimeError):
            return DesktopActionResult(False, "selection_failed", "系统文件选择器不可用")

    def select_directory(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        try:
            return _selection_result(QFileDialog.getExistingDirectory(None, "选择导入目录"))
        except (OSError, RuntimeError):
            return DesktopActionResult(False, "selection_failed", "系统目录选择器不可用")

    def open_controlled_directory(self, path: Path) -> DesktopActionResult:
        return _open_local_path(path)

    def open_controlled_artifact(self, path: Path) -> DesktopActionResult:
        return _open_local_path(path)

    def launch_registered_terminal(self, launch: RegisteredLaunch) -> DesktopActionResult:
        return _launch(launch)

    def launch_registered_tool(self, launch: RegisteredLaunch) -> DesktopActionResult:
        return _launch(launch)

    def show_native_notification(self, notification: RegisteredNotification) -> DesktopActionResult:
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return DesktopActionResult(False, "notification_unavailable", "系统通知不可用")
            icon = self._notification_icon
            if icon is None:
                app = QApplication.instance()
                if app is None:
                    return DesktopActionResult(False, "qt_application_unavailable", "Qt 应用尚未初始化")
                icon = QSystemTrayIcon(app)
                icon.show()
                self._notification_icon = icon
            icon.showMessage(notification.title, notification.message)
            return DesktopActionResult(True, "completed")
        except (OSError, RuntimeError):
            return DesktopActionResult(False, "notification_failed", "系统通知发送失败")


def _selection_result(*values: str) -> DesktopActionResult:
    paths = tuple(Path(value).resolve() for value in values if value)
    return DesktopActionResult(bool(paths), "completed" if paths else "cancelled", paths=paths)


def _open_local_path(path: Path) -> DesktopActionResult:
    try:
        opened = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
    except (OSError, RuntimeError):
        opened = False
    return DesktopActionResult(opened, "completed" if opened else "open_failed", "" if opened else "系统未能打开目标")


def _launch(launch: RegisteredLaunch) -> DesktopActionResult:
    try:
        result = QProcess.startDetached(str(launch.executable), list(launch.arguments), str(launch.working_directory))
    except (OSError, RuntimeError):
        result = False
    started = bool(result[0]) if isinstance(result, tuple) else bool(result)
    return DesktopActionResult(started, "completed" if started else "launch_failed", "" if started else "系统未能启动登记程序")


__all__ = ["QtDesktopAdapter"]
