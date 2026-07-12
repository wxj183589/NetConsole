from __future__ import annotations

import os
import platform
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class WindowEffectState:
    requested: str
    applied: str
    reason: str = ""


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def requested_effect() -> str:
    value = os.environ.get("NETCONSOLE_WINDOW_EFFECT", "none").strip().lower()
    return value if value in {"none", "mica", "acrylic"} else "none"


def apply_window_effect(window: QWidget, effect: str | None = None) -> WindowEffectState:
    requested = (effect or requested_effect()).strip().lower()
    if requested not in {"none", "mica", "acrylic"}:
        requested = "none"
    if requested == "none":
        return WindowEffectState(requested=requested, applied="none")
    if not is_windows():
        return WindowEffectState(requested=requested, applied="none", reason="unsupported_platform")
    try:
        return _apply_windows_backdrop(window, requested)
    except Exception as exc:
        return WindowEffectState(requested=requested, applied="none", reason=exc.__class__.__name__)


def _apply_windows_backdrop(window: QWidget, effect: str) -> WindowEffectState:
    import ctypes

    hwnd = int(window.winId())
    if hwnd == 0:
        return WindowEffectState(requested=effect, applied="none", reason="missing_hwnd")
    build = int(platform.version().split(".")[-1]) if platform.version() else 0
    if effect == "mica" and build >= 22000:
        backdrop_type = ctypes.c_int(2)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop_type), ctypes.sizeof(backdrop_type))
        if result == 0:
            return WindowEffectState(requested=effect, applied="mica")
    return WindowEffectState(requested=effect, applied="none", reason="unsupported_windows_version")
