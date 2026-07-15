from __future__ import annotations

from pathlib import Path

from netconsole.application.desktop import (
    DesktopActionResult,
    DesktopSelectionPurpose,
    RegisteredLaunch,
    RegisteredNotification,
)


class UnavailableDesktopAdapter:
    def __init__(self, code: str = "desktop_unavailable", message: str = "当前宿主不提供桌面能力") -> None:
        self.code = code
        self.message = message

    def _result(self) -> DesktopActionResult:
        return DesktopActionResult(False, self.code, self.message)

    def select_file(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        return self._result()

    def select_files(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        return self._result()

    def select_directory(self, _purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        return self._result()

    def open_controlled_directory(self, _path: Path) -> DesktopActionResult:
        return self._result()

    def open_controlled_artifact(self, _path: Path) -> DesktopActionResult:
        return self._result()

    def launch_registered_terminal(self, _launch: RegisteredLaunch) -> DesktopActionResult:
        return self._result()

    def launch_registered_tool(self, _launch: RegisteredLaunch) -> DesktopActionResult:
        return self._result()

    def show_native_notification(self, _notification: RegisteredNotification) -> DesktopActionResult:
        return self._result()


class BrowserDesktopAdapter(UnavailableDesktopAdapter):
    def __init__(self) -> None:
        super().__init__("desktop_host_required", "该动作需要桌面宿主")


__all__ = ["BrowserDesktopAdapter", "UnavailableDesktopAdapter"]
