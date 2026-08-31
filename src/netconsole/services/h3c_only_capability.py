from __future__ import annotations

from typing import Any


H3C_ONLY_DIAGNOSTIC_MESSAGE = "设备诊断当前仅支持 H3C 设备"
H3C_ONLY_FILE_DOWNLOAD_MESSAGE = "设备文件下载当前仅支持 H3C 设备"


def is_h3c_device(device: Any) -> bool:
    return str(getattr(device, "vendor_key", "") or "").casefold() == "h3c"


def require_h3c_device(device: Any, message: str) -> None:
    if not is_h3c_device(device):
        raise ValueError(message)


__all__ = [
    "H3C_ONLY_DIAGNOSTIC_MESSAGE",
    "H3C_ONLY_FILE_DOWNLOAD_MESSAGE",
    "is_h3c_device",
    "require_h3c_device",
]
