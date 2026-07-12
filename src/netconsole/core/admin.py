from __future__ import annotations

import ctypes
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.runtime_environment import app_root as default_app_root


ADMIN_NETWORK_MANAGER_ARG = "--admin-network-manager"


@dataclass(frozen=True)
class AdminLaunchPlan:
    executable: str
    parameters: str
    working_dir: str


@dataclass(frozen=True)
class AdminLaunchResult:
    success: bool
    code: int
    message: str
    plan: AdminLaunchPlan | None = None


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(args: Sequence[str] | None = None, *, show: int = 1) -> bool:
    if sys.platform != "win32":
        return False
    arguments = subprocess.list2cmdline(list(args or sys.argv[1:]))
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, arguments, None, show)
    return int(result) > 32


def build_network_manager_admin_launch_plan(
    *,
    app_root: Path | None = None,
    frozen: bool | None = None,
    executable: str | None = None,
) -> AdminLaunchPlan:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable_path = executable or sys.executable
    if is_frozen:
        exe_path = Path(executable_path).resolve()
        return AdminLaunchPlan(
            executable=str(exe_path),
            parameters=ADMIN_NETWORK_MANAGER_ARG,
            working_dir=str(exe_path.parent),
        )

    root = Path(app_root).resolve() if app_root is not None else default_app_root()
    main_py = root / "main.py"
    executable_file = Path(executable_path).resolve()
    pythonw = executable_file.with_name("pythonw.exe")
    if pythonw.exists():
        executable_file = pythonw
    return AdminLaunchPlan(
        executable=str(executable_file),
        parameters=f"{_quote_windows_arg(str(main_py))} {ADMIN_NETWORK_MANAGER_ARG}",
        working_dir=str(root),
    )


def open_network_manager_as_admin(
    *,
    app_root: Path | None = None,
    shell_execute=None,
    show: int = 1,
) -> AdminLaunchResult:
    if sys.platform != "win32":
        return AdminLaunchResult(False, 0, "当前平台不支持Windows管理员权限启动。")
    plan = build_network_manager_admin_launch_plan(app_root=app_root)
    execute = shell_execute or ctypes.windll.shell32.ShellExecuteW
    try:
        result = int(execute(None, "runas", plan.executable, plan.parameters, plan.working_dir, show))
    except Exception as exc:
        return AdminLaunchResult(False, -1, f"管理员权限启动失败：{exc}", plan)
    if result > 32:
        return AdminLaunchResult(True, result, "已请求管理员权限，请在弹出的 UAC 窗口中确认。", plan)
    return AdminLaunchResult(False, result, _shell_execute_error_message(result), plan)


def _quote_windows_arg(value: str) -> str:
    return '"' + value.replace('"', r'\"') + '"'


def _shell_execute_error_message(code: int) -> str:
    messages = {
        0: "系统内存或资源不足，无法启动管理员进程。",
        2: "无法找到程序文件，请检查程序路径。",
        3: "无法找到程序目录，请检查程序路径。",
        5: "管理员权限启动被拒绝或已取消。",
        8: "系统内存不足，无法启动管理员进程。",
        26: "共享冲突，无法启动管理员进程。",
        27: "文件关联不完整，无法启动管理员进程。",
        28: "DDE事务超时，无法启动管理员进程。",
        29: "DDE事务失败，无法启动管理员进程。",
        30: "DDE正忙，无法启动管理员进程。",
        31: "没有可用于打开该文件的关联程序。",
        32: "动态链接库加载失败，无法启动管理员进程。",
    }
    return messages.get(code, f"管理员权限启动失败，ShellExecute返回码：{code}")
