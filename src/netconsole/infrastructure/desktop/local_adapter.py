from __future__ import annotations

import os
import subprocess
from pathlib import Path

from netconsole.application.desktop import (
    DesktopActionResult,
    DesktopSelectionPurpose,
    RegisteredLaunch,
    RegisteredNotification,
)
from netconsole.core.shutdown_manager import shutdown_manager


class LocalDesktopAdapter:
    """不依赖 Qt 的 Windows 桌面动作适配器。"""

    def select_file(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        return _host_required()

    def select_files(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        return _host_required()

    def select_directory(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        return _host_required()

    def open_controlled_directory(self, path: Path) -> DesktopActionResult:
        return _open_path(path)

    def open_controlled_artifact(self, path: Path) -> DesktopActionResult:
        return _open_path(path)

    def launch_registered_terminal(self, launch: RegisteredLaunch) -> DesktopActionResult:
        return _launch(launch, "external_terminal")

    def launch_registered_tool(self, launch: RegisteredLaunch) -> DesktopActionResult:
        return _launch(launch, "external_tool")

    def show_native_notification(
        self, _notification: RegisteredNotification
    ) -> DesktopActionResult:
        return _host_required()


def _host_required() -> DesktopActionResult:
    return DesktopActionResult(False, "desktop_host_required", "该动作需要桌面宿主")


def _open_path(path: Path) -> DesktopActionResult:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except (OSError, RuntimeError):
        return DesktopActionResult(False, "open_failed", "系统未能打开目标")
    return DesktopActionResult(True, "completed")


def _launch(launch: RegisteredLaunch, label: str) -> DesktopActionResult:
    try:
        process = subprocess.Popen(
            [str(launch.executable), *launch.arguments],
            cwd=str(launch.working_directory),
            shell=False,
        )
        shutdown_manager.register_process(
            process,
            label,
            kind="external_tool",
            shutdown_policy="ignore",
        )
    except (OSError, RuntimeError):
        return DesktopActionResult(False, "launch_failed", "系统未能启动登记程序")
    return DesktopActionResult(True, "launched", "外部程序已启动")


__all__ = ["LocalDesktopAdapter"]
