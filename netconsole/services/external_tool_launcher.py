from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.tool_path_resolver import resolve_tool_path


@dataclass(frozen=True)
class ExternalToolLaunchResult:
    success: bool
    message: str
    path: Path | None = None


def launch_ipop_as_admin(paths: PathResolver | None = None) -> ExternalToolLaunchResult:
    if sys.platform != "win32":
        return ExternalToolLaunchResult(False, "不支持当前平台")
    executable = resolve_tool_path("ipop", paths or PathResolver())
    if executable is None:
        return ExternalToolLaunchResult(False, "未找到 IPOP.EXE，请确认 tools/IPOP_v4.1/IPOP.EXE 已存在。")
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(executable),
            None,
            str(executable.parent),
            1,
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) in {5, 1223}:
            return ExternalToolLaunchResult(False, "用户取消了管理员权限请求，IPOP 未启动。", executable)
        return ExternalToolLaunchResult(False, f"IPOP v4.1 启动失败：{exc}", executable)
    error_code = int(result)
    if error_code == 5:
        return ExternalToolLaunchResult(False, "用户取消了管理员权限请求，IPOP 未启动。", executable)
    if error_code <= 32:
        return ExternalToolLaunchResult(False, f"IPOP v4.1 启动失败，系统错误码：{error_code}", executable)
    return ExternalToolLaunchResult(True, "已请求以管理员权限启动 IPOP v4.1。", executable)
