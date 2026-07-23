from __future__ import annotations

import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from netconsole.core.runtime_environment import app_root


DEFAULT_ELECTRON_DEV_PORT = 5173
ELECTRON_DEV_PORT_SEARCH_COUNT = 20


class ElectronDesktopLaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ElectronDesktopLaunchPlan:
    executable: Path
    arguments: tuple[str, ...]
    working_directory: Path
    environment: dict[str, str]


def build_electron_desktop_launch_plan(
    *,
    project_root: Path | None = None,
    python_executable: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> ElectronDesktopLaunchPlan:
    root = Path(project_root or app_root()).resolve()
    desktop_root = root / "apps" / "desktop_electron"
    dev_script = desktop_root / "scripts" / "dev.mjs"
    electron_executable = _electron_executable(desktop_root)
    required = (
        dev_script,
        electron_executable,
        desktop_root / "node_modules" / "typescript" / "bin" / "tsc",
        root / "apps" / "web" / "node_modules" / "vite" / "bin" / "vite.js",
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise ElectronDesktopLaunchError(
            "Electron 开发依赖不完整，请先在 apps/desktop_electron 和 apps/web 执行 "
            "pnpm install --frozen-lockfile。缺少："
            + ", ".join(path.name for path in missing)
        )

    inherited = dict(os.environ if environment is None else environment)
    configured_node = inherited.get("NETCONSOLE_NODE", "").strip()
    if configured_node:
        executable = _validated_local_executable(Path(configured_node), "NETCONSOLE_NODE")
        inherited.pop("ELECTRON_RUN_AS_NODE", None)
    else:
        executable = electron_executable
        inherited["ELECTRON_RUN_AS_NODE"] = "1"

    python = _validated_local_executable(
        Path(python_executable or sys.executable),
        "Python 运行时",
    )
    inherited["NETCONSOLE_PROJECT_ROOT"] = str(root)
    inherited["NETCONSOLE_PYTHON"] = str(python)
    inherited.setdefault("PYTHONUNBUFFERED", "1")
    if not inherited.get("NETCONSOLE_DEV_PORT", "").strip():
        inherited["NETCONSOLE_DEV_PORT"] = str(_select_available_dev_port())
    return ElectronDesktopLaunchPlan(
        executable=executable,
        arguments=(str(dev_script),),
        working_directory=desktop_root,
        environment=inherited,
    )


def launch_electron_desktop() -> int:
    try:
        plan = build_electron_desktop_launch_plan()
    except ElectronDesktopLaunchError as exc:
        print(f"NetConsole Electron 启动失败：{exc}", file=sys.stderr)
        return 2

    selected_dev_port = plan.environment.get("NETCONSOLE_DEV_PORT", "").strip()
    if (
        selected_dev_port
        and selected_dev_port != str(DEFAULT_ELECTRON_DEV_PORT)
        and not os.environ.get("NETCONSOLE_DEV_PORT", "").strip()
    ):
        print(
            f"NetConsole 检测到开发端口 {DEFAULT_ELECTRON_DEV_PORT} 已占用，"
            f"已自动改用 {selected_dev_port}。"
        )

    try:
        process = subprocess.Popen(
            [str(plan.executable), *plan.arguments],
            cwd=str(plan.working_directory),
            env=plan.environment,
            shell=False,
        )
    except OSError as exc:
        print(f"NetConsole Electron 启动失败：{exc}", file=sys.stderr)
        return 2

    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 130


def _select_available_dev_port(
    start_port: int = DEFAULT_ELECTRON_DEV_PORT,
    search_count: int = ELECTRON_DEV_PORT_SEARCH_COUNT,
) -> int:
    if not 1 <= start_port <= 65535:
        raise ElectronDesktopLaunchError(f"Electron 开发端口无效：{start_port}")
    if search_count < 1:
        raise ElectronDesktopLaunchError("Electron 开发端口搜索次数必须大于 0")

    end_port = min(65535, start_port + search_count - 1)
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise ElectronDesktopLaunchError(
        f"Electron 开发端口 {start_port}-{end_port} 均已占用，"
        "请关闭残留的 NetConsole/Vite 开发进程后重试。"
    )


def _electron_executable(desktop_root: Path) -> Path:
    if sys.platform == "win32":
        relative = Path("node_modules/electron/dist/electron.exe")
    elif sys.platform == "darwin":
        relative = Path("node_modules/electron/dist/Electron.app/Contents/MacOS/Electron")
    else:
        relative = Path("node_modules/electron/dist/electron")
    return (desktop_root / relative).resolve()


def _validated_local_executable(path: Path, label: str) -> Path:
    if not path.is_absolute() or str(path).startswith("\\\\"):
        raise ElectronDesktopLaunchError(f"{label} 必须是本机绝对路径")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ElectronDesktopLaunchError(f"{label} 不存在：{resolved}")
    return resolved


__all__ = [
    "DEFAULT_ELECTRON_DEV_PORT",
    "ELECTRON_DEV_PORT_SEARCH_COUNT",
    "ElectronDesktopLaunchError",
    "ElectronDesktopLaunchPlan",
    "build_electron_desktop_launch_plan",
    "launch_electron_desktop",
]
