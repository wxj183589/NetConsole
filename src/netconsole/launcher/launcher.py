from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Sequence

from netconsole.core import app_logger
from netconsole.core.backend_instance_lock import BackendInstanceInUseError, BackendInstanceLock
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import data_environment
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.storage_manifest import prepare_storage_manifest

if TYPE_CHECKING:
    from netconsole.launcher.runtime_supervisor import RuntimeSupervisor

@dataclass(frozen=True)
class LaunchOptions:
    mode: str
    host: str
    port: int
    allow_production_write: bool = False


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
    parser.add_argument("--mode", choices=("server",), default="server")
    parser.add_argument("--host", type=_loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=_valid_port, default=8000)
    parser.add_argument("--allow-production-write", action="store_true")
    values = parser.parse_args(list(argv))
    if values.allow_production_write:
        os.environ["NETCONSOLE_ALLOW_PRODUCTION_WRITE"] = "1"
    return LaunchOptions(values.mode, values.host, values.port, values.allow_production_write)


def launch(argv: Sequence[str] | None = None) -> int:
    options = parse_launch_options(sys.argv[1:] if argv is None else argv)
    paths = PathResolver()
    data_environment(paths.data_root)
    instance = BackendInstanceLock(paths)
    try:
        instance.acquire()
    except BackendInstanceInUseError as exc:
        app_logger.log_error("LAUNCHER_ALREADY_RUNNING", str(exc))
        return 3
    try:
        prepare_storage_manifest(paths)
        return _launch_once(options, paths)
    finally:
        instance.release()


def _launch_once(options: LaunchOptions, paths: PathResolver) -> int:
    from netconsole.launcher.runtime_supervisor import RuntimeSupervisor

    host_mode = RuntimeMode.SERVER
    host = _loopback_host(options.host)
    port = options.port
    app_logger.log_info(
        "LAUNCHER_MODE_SELECTED",
        f"requested={options.mode} host_mode={host_mode.value}",
    )
    runtime = RuntimeSupervisor(host_mode, paths=paths, host=host, port=port)
    if not runtime.start():
        runtime.stop()
        return 4
    _log_frontend_status(runtime)
    try:
        return runtime.wait()
    finally:
        runtime.stop()


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
    "LaunchOptions",
    "SingleInstanceGuard",
    "launch",
    "parse_launch_options",
]
