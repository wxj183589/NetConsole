from __future__ import annotations

import argparse
import atexit
import ipaddress
import os
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Sequence

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode

if TYPE_CHECKING:
    from netconsole.launcher.runtime_supervisor import RuntimeSupervisor


class ShellMode(StrEnum):
    QT = "qt"
    BROWSER = "browser"
    NONE = "none"


@dataclass(frozen=True)
class LaunchOptions:
    mode: str
    host: str
    port: int
    shell_args: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityReport:
    qt_widgets_available: bool = False
    qt_webengine_available: bool = False
    external_browser_available: bool = False
    qt_detail: str = "not-probed"
    browser_detail: str = "not-probed"


class SingleInstanceGuard:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def parse_launch_options(argv: Sequence[str]) -> LaunchOptions:
    parser = argparse.ArgumentParser(prog="NetConsole")
    parser.add_argument("--mode", choices=("auto", "qt", "web", "server"), default="auto")
    parser.add_argument("--host", type=_loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=_valid_port, default=8000)
    values, shell_args = parser.parse_known_args(list(argv))
    return LaunchOptions(values.mode, values.host, values.port, tuple(shell_args))


def launch(argv: Sequence[str] | None = None) -> int:
    options = parse_launch_options(sys.argv[1:] if argv is None else argv)
    paths = PathResolver()
    instance = SingleInstanceGuard(paths.runtime_dir / "netconsole-launcher.lock")
    if not instance.acquire():
        app_logger.log_error("LAUNCHER_ALREADY_RUNNING", f"mode={options.mode}")
        return 3
    try:
        return _launch_once(options, paths)
    finally:
        instance.release()


def _launch_once(options: LaunchOptions, paths: PathResolver) -> int:
    from netconsole.launcher.runtime_supervisor import RuntimeSupervisor

    capabilities = _capabilities_for(options.mode)
    shell_mode = _resolve_shell_mode(options.mode, capabilities)
    if shell_mode is None:
        app_logger.log_error("LAUNCHER_QT_UNAVAILABLE", capabilities.qt_detail)
        return 2
    host_mode = RuntimeMode.SERVER if shell_mode is ShellMode.NONE else RuntimeMode.DESKTOP
    host = _loopback_host(options.host) if host_mode is RuntimeMode.SERVER else "127.0.0.1"
    port = options.port if host_mode is RuntimeMode.SERVER else None
    app_logger.log_info(
        "LAUNCHER_MODE_SELECTED",
        (
            f"requested={options.mode} host_mode={host_mode.value} shell_mode={shell_mode.value} "
            f"qt_widgets={capabilities.qt_widgets_available} "
            f"qt_webengine={capabilities.qt_webengine_available} "
            f"external_browser={capabilities.external_browser_available}"
        ),
    )
    runtime = RuntimeSupervisor(host_mode, paths=paths, host=host, port=port)
    if not runtime.start():
        runtime.stop()
        return 4
    _log_frontend_status(runtime)
    try:
        if shell_mode is ShellMode.QT:
            return _run_qt_shell(runtime, options, capabilities)
        if shell_mode is ShellMode.BROWSER:
            _open_browser_shell(runtime, paths)
        return runtime.wait()
    finally:
        runtime.stop()


def _run_qt_shell(
    runtime: RuntimeSupervisor,
    options: LaunchOptions,
    capabilities: CapabilityReport,
) -> int:
    webengine_env = "NETCONSOLE_QT_WEBENGINE_AVAILABLE"
    previous_webengine = os.environ.get(webengine_env)
    os.environ[webengine_env] = "1" if capabilities.qt_webengine_available else "0"
    original_argv = sys.argv[:]
    sys.argv = [original_argv[0], *options.shell_args]
    try:
        try:
            from netconsole.app import run
        except (ImportError, OSError) as exc:
            if options.mode != "auto":
                raise
            app_logger.log_error("QT_SHELL_START_FAILED", f"error={exc.__class__.__name__}: {exc}")
            if capabilities.external_browser_available:
                _open_browser_shell(runtime, runtime.paths)
            return runtime.wait()
        return run(web_server=runtime.web_server)
    finally:
        sys.argv = original_argv
        if previous_webengine is None:
            os.environ.pop(webengine_env, None)
        else:
            os.environ[webengine_env] = previous_webengine


def _capabilities_for(mode: str) -> CapabilityReport:
    browser_available, browser_detail = _probe_external_browser() if mode in {"auto", "web"} else (False, "not-probed")
    if mode not in {"auto", "qt"}:
        return CapabilityReport(
            external_browser_available=browser_available,
            browser_detail=browser_detail,
        )
    widgets, widgets_detail = _probe_qt_component("widgets")
    webengine, webengine_detail = _probe_qt_component("webengine") if widgets else (False, "widgets-unavailable")
    return CapabilityReport(
        qt_widgets_available=widgets,
        qt_webengine_available=webengine,
        external_browser_available=browser_available,
        qt_detail=f"widgets={widgets_detail}; webengine={webengine_detail}",
        browser_detail=browser_detail,
    )


def _resolve_shell_mode(mode: str, capabilities: CapabilityReport) -> ShellMode | None:
    if mode == "qt":
        return ShellMode.QT if capabilities.qt_widgets_available else None
    if mode == "web":
        return ShellMode.BROWSER
    if mode == "server":
        return ShellMode.NONE
    if capabilities.qt_widgets_available:
        return ShellMode.QT
    return ShellMode.BROWSER if capabilities.external_browser_available else ShellMode.NONE


def _probe_qt_component(component: str) -> tuple[bool, str]:
    command = _qt_probe_command(component)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{exc.__class__.__name__}: {exc}"
    detail = (result.stdout or result.stderr or f"exit={result.returncode}").strip()[-500:]
    return result.returncode == 0, detail


def _qt_probe_command(component: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--qt-probe", component]
    project_root = Path(__file__).resolve().parents[3]
    return [sys.executable, str(project_root / "main.py"), "--qt-probe", component]


def _probe_external_browser() -> tuple[bool, str]:
    try:
        controller = webbrowser.get()
    except (OSError, webbrowser.Error) as exc:
        return False, str(exc)
    return True, controller.__class__.__name__


def _open_browser_shell(runtime: RuntimeSupervisor, paths: PathResolver) -> bool:
    try:
        paths.runtime_cache_dir.mkdir(parents=True, exist_ok=True)
        bootstrap_path = paths.runtime_cache_dir / f"web-console-{runtime.web_server.port}.html"
        bootstrap_path.write_text(runtime.web_server.bootstrap_html(), encoding="utf-8")
    except OSError as exc:
        app_logger.log_error("BROWSER_SHELL_BOOTSTRAP_FAILED", f"error={exc}")
        return False
    try:
        opened = bool(webbrowser.open_new_tab(bootstrap_path.as_uri()))
    except (OSError, webbrowser.Error) as exc:
        app_logger.log_error("BROWSER_SHELL_OPEN_FAILED", f"error={exc}")
        opened = False
    if opened:
        app_logger.log_info("BROWSER_SHELL_OPENED", f"base_url={runtime.base_url}")
    else:
        app_logger.log_warning("BROWSER_SHELL_OPEN_FAILED", f"base_url={runtime.base_url}")
    atexit.register(_remove_bootstrap_file, bootstrap_path)
    cleanup = threading.Timer(60, _remove_bootstrap_file, args=(bootstrap_path,))
    cleanup.daemon = True
    cleanup.start()
    return opened


def _remove_bootstrap_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        app_logger.log_warning("BROWSER_SHELL_BOOTSTRAP_CLEANUP_FAILED", str(exc))


def _log_frontend_status(runtime: RuntimeSupervisor) -> None:
    app = runtime.web_server.app
    ready = (app.state.frontend_root / "index.html").is_file()
    mismatch = bool(app.state.frontend_build_mismatch)
    log = app_logger.log_info if ready and not mismatch else app_logger.log_warning
    log(
        "LAUNCHER_WEB_RESOURCE_CHECK",
        (
            f"ready={ready} mismatch={mismatch} "
            f"frontend_build_id={app.state.frontend_build_id or 'missing'} "
            f"backend_build_id={app.state.backend_build_id}"
        ),
    )


def _valid_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _loopback_host(value: str) -> str:
    if value.casefold() == "localhost":
        return "localhost"
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("host must be a loopback address") from exc
    if not address.is_loopback:
        raise argparse.ArgumentTypeError("host must be a loopback address")
    return value


__all__ = [
    "CapabilityReport",
    "LaunchOptions",
    "ShellMode",
    "SingleInstanceGuard",
    "launch",
    "parse_launch_options",
]
