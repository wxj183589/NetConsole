from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication


MAIN_WINDOW_MIN_WIDTH = 1280
MAIN_WINDOW_MIN_HEIGHT = 760
MAIN_WINDOW_DEFAULT_SCREEN_RATIO = 0.75
MAIN_WINDOW_MIN_AREA_RATIO = 0.45


@dataclass(frozen=True)
class WindowSize:
    width: int
    height: int


@dataclass(frozen=True)
class WindowGeometryDecision:
    rect: QRect
    status: str


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


def available_screen_geometry() -> QRect:
    screen = QApplication.primaryScreen()
    if screen is None:
        return QRect(0, 0, 1600, 900)
    return screen.availableGeometry()


def calculate_default_main_window_geometry(available: QRect | None = None) -> QRect:
    available = QRect(available or available_screen_geometry())
    width = int(available.width() * MAIN_WINDOW_DEFAULT_SCREEN_RATIO)
    height = int(available.height() * MAIN_WINDOW_DEFAULT_SCREEN_RATIO)

    width = min(max(width, MAIN_WINDOW_MIN_WIDTH), max(available.width(), MAIN_WINDOW_MIN_WIDTH))
    height = min(max(height, MAIN_WINDOW_MIN_HEIGHT), max(available.height(), MAIN_WINDOW_MIN_HEIGHT))
    x = available.x() + max(0, (available.width() - width) // 2)
    y = available.y() + max(0, (available.height() - height) // 2)
    return QRect(x, y, width, height)


def format_geometry(rect: QRect) -> str:
    return f"{rect.width()}x{rect.height()}+{rect.x()}+{rect.y()}"


def main_window_geometry_issue(rect: QRect | None, available: QRect | None = None) -> str | None:
    available = QRect(available or available_screen_geometry())
    if rect is None or rect.isNull() or not rect.isValid():
        return "invalid"
    if rect.width() < MAIN_WINDOW_MIN_WIDTH or rect.height() < MAIN_WINDOW_MIN_HEIGHT:
        return "too-small"
    if not available.intersects(rect):
        return "offscreen"
    available_area = max(1, available.width() * available.height())
    rect_area = rect.width() * rect.height()
    if rect_area < int(available_area * MAIN_WINDOW_MIN_AREA_RATIO):
        return "area-too-small"
    return None


def normalize_restored_main_window_geometry(restored: QRect | None, available: QRect | None = None) -> WindowGeometryDecision:
    available = QRect(available or available_screen_geometry())
    default_rect = calculate_default_main_window_geometry(available)
    if restored is None or restored.isNull() or not restored.isValid():
        return WindowGeometryDecision(default_rect, "default")
    if restored.width() < MAIN_WINDOW_MIN_WIDTH or restored.height() < MAIN_WINDOW_MIN_HEIGHT:
        return WindowGeometryDecision(default_rect, "invalid-small")
    if not available.intersects(restored):
        return WindowGeometryDecision(default_rect, "invalid-offscreen")
    available_area = max(1, available.width() * available.height())
    if restored.width() * restored.height() < int(available_area * MAIN_WINDOW_MIN_AREA_RATIO):
        return WindowGeometryDecision(default_rect, "invalid-area-small")

    rect = QRect(restored)
    rect.setWidth(min(rect.width(), max(available.width(), MAIN_WINDOW_MIN_WIDTH)))
    rect.setHeight(min(rect.height(), max(available.height(), MAIN_WINDOW_MIN_HEIGHT)))
    status = "restored"
    if rect.left() < available.left():
        rect.moveLeft(available.left())
        status = "clamped"
    if rect.top() < available.top():
        rect.moveTop(available.top())
        status = "clamped"
    if rect.right() > available.right():
        rect.moveRight(available.right())
        status = "clamped"
    if rect.bottom() > available.bottom():
        rect.moveBottom(available.bottom())
        status = "clamped"
    return WindowGeometryDecision(rect, status)


def apply_startup_main_window_geometry(
    window,
    restored: QRect | None = None,
    available: QRect | None = None,
) -> WindowGeometryDecision:
    available = QRect(available or available_screen_geometry())
    decision = normalize_restored_main_window_geometry(restored, available)
    window.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
    window.setGeometry(decision.rect)
    return decision


def should_save_main_window_geometry(rect: QRect | None, available: QRect | None = None, *, minimized: bool = False) -> tuple[bool, str]:
    if minimized:
        return False, "minimized"
    issue = main_window_geometry_issue(rect, available)
    if issue is not None:
        return False, issue
    return True, "ok"


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
