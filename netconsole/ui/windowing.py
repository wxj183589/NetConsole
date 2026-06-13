from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowSize:
    width: int
    height: int


def fit_default_window_size(
    available_width: int,
    available_height: int,
    default_width: int,
    default_height: int,
    scale: float = 0.9,
) -> WindowSize:
    max_width = int(available_width * scale)
    max_height = int(available_height * scale)
    return WindowSize(width=min(default_width, max_width), height=min(default_height, max_height))


class DeviceDialogRegistry:
    def __init__(self) -> None:
        self.add_window: object | None = None
        self.edit_windows: dict[str, object] = {}

    def get_add_window(self) -> object | None:
        return self.add_window

    def set_add_window(self, window: object) -> None:
        self.add_window = window

    def remove_add_window(self, window: object) -> None:
        if self.add_window is window:
            self.add_window = None

    def get_edit_window(self, device_uuid: str) -> object | None:
        return self.edit_windows.get(device_uuid)

    def set_edit_window(self, device_uuid: str, window: object) -> None:
        self.edit_windows[device_uuid] = window

    def remove_edit_window(self, device_uuid: str, window: object) -> None:
        if self.edit_windows.get(device_uuid) is window:
            self.edit_windows.pop(device_uuid, None)
