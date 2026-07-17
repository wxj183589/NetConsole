from __future__ import annotations

from pathlib import Path
from typing import Literal


SettingsToolId = Literal["iperf3", "fping", "ipop", "securecrt", "xshell", "putty"]

TOOL_EXECUTABLE_NAMES: dict[SettingsToolId, tuple[str, ...]] = {
    "iperf3": ("iperf3.exe",),
    "fping": ("fping.exe", "Fping_v3.exe"),
    "ipop": ("IPOP.EXE",),
    "securecrt": ("SecureCRT.exe",),
    "xshell": ("Xshell.exe",),
    "putty": ("putty.exe",),
}


class SettingsToolPathError(ValueError):
    pass


def validate_settings_tool_path(tool_id: SettingsToolId, value: str | Path) -> Path:
    """Validate a configured executable without accepting a program or argv contract."""
    expected_names = TOOL_EXECUTABLE_NAMES.get(tool_id)
    if expected_names is None:
        raise SettingsToolPathError("不支持的工具标识")
    path = Path(str(value).strip().strip('"').strip("'"))
    if not path.is_absolute():
        raise SettingsToolPathError(f"{tool_id} 路径必须是绝对路径")
    if path.name.casefold() not in {name.casefold() for name in expected_names} or path.suffix.casefold() != ".exe":
        raise SettingsToolPathError(f"{tool_id} 必须选择 {' / '.join(expected_names)}")
    try:
        if path.is_symlink():
            raise SettingsToolPathError(f"{tool_id} 路径不能是符号链接")
        if not path.exists():
            raise SettingsToolPathError(f"{tool_id} 文件不存在")
        if not path.is_file():
            raise SettingsToolPathError(f"{tool_id} 路径必须是普通文件")
        return path.resolve(strict=True)
    except OSError as exc:
        raise SettingsToolPathError(f"{tool_id} 路径不可访问：{exc}") from exc


__all__ = ["SettingsToolId", "SettingsToolPathError", "TOOL_EXECUTABLE_NAMES", "validate_settings_tool_path"]
