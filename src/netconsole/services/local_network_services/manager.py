from __future__ import annotations

import errno
import ipaddress
import locale
import logging
import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netconsole.core.atomic_file import atomic_write_bytes
from netconsole.services.job_center.local_process_adapter import _windows_process_tree_factory
from netconsole.services.local_network_services.protocols import create_server, shared_path
from netconsole.services.windows_network_manager import NetworkManagerError, WindowsNetworkManager

try:
    from netconsole.services.local_network_services.ftp import FTP_USERNAME, LocalFtpServer
except ModuleNotFoundError as exc:
    if exc.name not in {"pyftpdlib", "pyasynchat", "pyasyncore"}:
        raise
    LocalFtpServer = None
    FTP_USERNAME = ""

ServiceId = Literal["dhcp", "dns", "ntp", "tftp", "ftp", "sftp", "http", "https", "ssh", "telnet", "nfs", "vnc", "scheduler", "iperf", "syslog"]
FILE_SHARES = {"ftp", "http", "tftp"}


@dataclass(frozen=True)
class ServiceDefinition:
    group: str
    port: int
    transport: str = "TCP"
    source: str = "external"
    dependency: str = ""


SERVICES = {
    "dhcp": ServiceDefinition("core", 67, "UDP", dependency="Isolated DHCP adapter"),
    "dns": ServiceDefinition("core", 53, "UDP", "built_in"),
    "ntp": ServiceDefinition("core", 123, "UDP", "built_in"),
    "syslog": ServiceDefinition("core", 514, "UDP/TCP", "built_in"),
    "tftp": ServiceDefinition("files", 69, "UDP", "built_in"),
    "ftp": ServiceDefinition("files", 2121, source="built_in", dependency="pyftpdlib"),
    "sftp": ServiceDefinition("files", 2222, dependency="Managed SFTP server"),
    "http": ServiceDefinition("files", 8080, source="built_in"),
    "https": ServiceDefinition("files", 8443, dependency="TLS server and certificate"),
    "ssh": ServiceDefinition("remote", 22, dependency="Windows OpenSSH Server"),
    "telnet": ServiceDefinition("remote", 23, dependency="Telnet server"),
    "nfs": ServiceDefinition("remote", 2049, dependency="Windows Server for NFS"),
    "vnc": ServiceDefinition("remote", 5900, dependency="VNC server"),
    "scheduler": ServiceDefinition("remote", 0, "", "system", "Windows Task Scheduler"),
    "iperf": ServiceDefinition("remote", 5201, source="managed_tool", dependency="iPerf3"),
}


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    max_connections: int = Field(default=8, ge=1, le=32)
    timeout: int = Field(default=3, ge=1, le=30)
    log_level: Literal["INFO", "WARNING"] = "INFO"
    allow_upload: bool = False
    dns_records: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        return str(ipaddress.IPv4Address(value))

    @field_validator("dns_records")
    @classmethod
    def validate_records(cls, records: dict[str, str]) -> dict[str, str]:
        result = {}
        for name, address in records.items():
            name = name.rstrip(".").lower()
            if len(name) > 253 or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in name.split(".")
            ):
                raise ValueError("invalid DNS name")
            result[name] = str(ipaddress.IPv4Address(address))
        return result


def windows_bind_addresses() -> dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        adapters = WindowsNetworkManager().list_adapters()
    except (NetworkManagerError, OSError, ValueError):
        return {}
    addresses = {}
    for adapter in adapters:
        has_gateway = any(gateway.strip().lower() not in {"", "none", "0.0.0.0"} for gateway in adapter.gateways)
        if adapter.hardware_interface or has_gateway or adapter.status.lower() != "up":
            continue
        if "host-only" not in f"{adapter.name} {adapter.description}".lower():
            continue
        for address in adapter.ipv4_addresses:
            try:
                ip = ipaddress.IPv4Interface(address).ip
            except ValueError:
                continue
            if ip.is_private and not (ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_unspecified):
                addresses[str(ip)] = adapter.name
    return addresses


@dataclass
class ServiceRuntime:
    phase: str = "stopped"
    error_code: str = ""
    lock: RLock = field(default_factory=RLock)
    stopping: Event = field(default_factory=Event)
    server: object | None = None
    worker: Thread | None = None
    process: subprocess.Popen | None = None
    job_handle: int | None = None
    logger: logging.Logger | None = None


class LocalNetworkServiceManager:
    def __init__(self, runtime_root: Path, *, iperf_path: Path | None = None, adapters=windows_bind_addresses):
        self.runtime_root = runtime_root
        self.iperf_path = iperf_path
        self.detect_adapters = adapters
        self.runtimes = {kind: ServiceRuntime() for kind in SERVICES}
        self.closing = Event()
        self._address_lock = RLock()
        self._addresses: dict[str, str] = {}
        self._address_time = -60.0

    def bind_addresses(self, *, refresh: bool = False) -> dict[str, str]:
        with self._address_lock:
            if refresh or time.monotonic() - self._address_time > 30:
                self._addresses = self.detect_adapters()
                self._address_time = time.monotonic()
            return {"127.0.0.1": "", **self._addresses}

    def _directory(self, kind: str) -> Path:
        base = shared_path(self.runtime_root.parent, self.runtime_root.name)
        return shared_path(base, kind)

    def _available(self, kind: str) -> bool:
        if kind == "ftp":
            return LocalFtpServer is not None
        return SERVICES[kind].source == "built_in" or (
            kind == "iperf" and self.iperf_path is not None and self.iperf_path.is_file()
        )

    def _config(self, kind: str) -> ServiceConfig | None:
        if not self._available(kind):
            return None
        config_file = shared_path(self._directory(kind), "config.json")
        try:
            return ServiceConfig.model_validate_json(config_file.read_bytes())
        except FileNotFoundError:
            return None

    def snapshot(self, kind: str) -> dict:
        definition = SERVICES[kind]
        runtime = self.runtimes[kind]
        with runtime.lock:
            if runtime.phase == "running" and self._has_exited(runtime):
                runtime.phase, runtime.error_code = "error", "service_exited"
                self._log(kind).warning("Service exited")
            available = self._available(kind)
            phase = runtime.phase if available else "dependency_missing"
            config = None
            if available:
                try:
                    config = self._config(kind)
                except (OSError, ValueError):
                    if runtime.phase not in {"starting", "running", "stopping"}:
                        phase = "error"
                    runtime.error_code = "invalid_config"
                else:
                    if config is None and phase == "stopped":
                        phase = "uninitialized"
            config_port = config.port if config is not None else definition.port
            return {
                "id": kind, "group": definition.group, "source": definition.source, "status": phase,
                "available": available, "dependency": definition.dependency, "transport": definition.transport,
                "installed": self._installed(kind),
                "error_code": runtime.error_code,
                "config": config or (ServiceConfig(port=definition.port) if available else None),
                "listeners": [
                    {"address": config.address if config else "127.0.0.1", "port": config_port, "transport": "UDP"},
                    {"address": config.address if config else "127.0.0.1", "port": config_port + 1, "transport": "TCP"},
                ] if kind == "syslog" and config_port < 65535 else [],
                "root": str(self._directory(kind) / "files") if kind in FILE_SHARES else None,
            }

    def _installed(self, kind: str) -> bool:
        if self._available(kind):
            return True
        if kind == "ssh" and os.name == "nt":
            system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "OpenSSH"
            return (system / "sshd.exe").is_file()
        if kind == "scheduler" and os.name == "nt":
            system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
            return (system / "schtasks.exe").is_file()
        return False

    def configure(self, kind: str, config: ServiceConfig) -> dict:
        runtime = self.runtimes[kind]
        if not self._available(kind):
            raise ValueError("dependency_missing")
        if config.address not in self.bind_addresses(refresh=config.address != "127.0.0.1"):
            raise ValueError("unsupported_bind_address")
        if config.allow_upload and kind != "tftp" or config.dns_records and kind != "dns":
            raise ValueError("unsupported_service_option")
        if kind == "syslog" and config.port >= 65535:
            raise ValueError("syslog_udp_port_has_no_tcp_pair")
        with runtime.lock:
            if runtime.phase in {"starting", "running", "stopping"}:
                raise ValueError("service_active")
            directory = self._directory(kind)
            _ensure_private_directory(directory)
            config_path = shared_path(directory, "config.json")
            previous = config_path.read_bytes() if config_path.is_file() else None
            if kind in FILE_SHARES:
                _ensure_private_directory(shared_path(directory, "files"))
            try:
                atomic_write_bytes(config_path, config.model_dump_json().encode("utf-8"))
            except OSError:
                if previous is not None:
                    atomic_write_bytes(config_path, previous)
                raise
            runtime.phase, runtime.error_code = "stopped", ""
            self._log(kind).setLevel(config.log_level)
            self._log(kind).info("Configuration saved")
            return self.snapshot(kind)

    def action(self, kind: str, action: str) -> dict:
        if self.closing.is_set():
            raise ValueError("manager_closing")
        runtime = self.runtimes[kind]
        with runtime.lock:
            state = self.snapshot(kind)
            if not state["available"]:
                raise ValueError("dependency_missing")
            if runtime.phase in {"starting", "stopping"}:
                raise ValueError("service_active")
            if action == "initialize":
                if state["status"] != "uninitialized":
                    raise ValueError("already_initialized")
                return self.configure(kind, state["config"])
            if action in {"stop", "restart"}:
                self._stop(kind)
            started = False
            if action in {"start", "restart"} and runtime.phase != "running":
                config = self._config(kind)
                if config is None:
                    raise ValueError("not_initialized")
                self._start(kind, config)
                started = runtime.phase == "running"
            state = self.snapshot(kind)
            if started and kind == "ftp":
                state["session_credential"] = {"username": FTP_USERNAME, "password": runtime.server.password}
            return state

    def _start(self, kind: str, config: ServiceConfig):
        runtime = self.runtimes[kind]
        runtime.phase, runtime.error_code = "starting", ""
        runtime.stopping = Event()
        try:
            logger = self._log(kind)
            logger.setLevel(config.log_level)
            if config.address not in self.bind_addresses(refresh=config.address != "127.0.0.1"):
                raise ValueError("unsupported_bind_address")
            if kind == "iperf":
                self._start_iperf(runtime, config, logger)
            else:
                root = shared_path(self._directory(kind), "files") if kind in FILE_SHARES else None
                if kind == "ftp":
                    runtime.server = LocalFtpServer(config, root, logger, runtime.stopping)
                else:
                    runtime.server = create_server(kind, config, root, logger, runtime.stopping)
                runtime.worker = Thread(target=runtime.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
                runtime.worker.start()
            runtime.phase = "running"
            logger.info("Started on %s:%s", config.address, config.port)
        except (OSError, ValueError, RuntimeError) as exc:
            self._release(runtime)
            conflict = isinstance(exc, OSError) and (exc.errno in {errno.EADDRINUSE, 10048} or getattr(exc, "winerror", None) == 10048)
            runtime.phase = "port_conflict" if conflict else "error"
            runtime.error_code = "address_in_use" if conflict else "start_failed"
            if runtime.logger:
                runtime.logger.warning("Start failed: %s", exc)
                self._audit(
                    kind,
                    "LOCAL_NETWORK_SERVICE_START_FAILED",
                    f"code={runtime.error_code} type={exc.__class__.__name__}",
                )

    def _start_iperf(self, runtime: ServiceRuntime, config: ServiceConfig, logger: logging.Logger):
        with socket.socket() as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((config.address, config.port))
        assert self.iperf_path is not None
        runtime.process = subprocess.Popen(
            [str(self.iperf_path), "-s", "-B", config.address, "-p", str(config.port)],
            cwd=self.iperf_path.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if os.name == "nt":
            runtime.job_handle = _windows_process_tree_factory(runtime.process)
        # Drain output throughout the process lifetime so a busy service cannot block on its pipe.
        Thread(target=self._process_output, args=(runtime.process, logger), daemon=True).start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if runtime.process.poll() is not None:
                raise RuntimeError(f"iPerf exited with code {runtime.process.returncode}")
            with socket.socket() as probe:
                probe.settimeout(0.1)
                if probe.connect_ex((config.address, config.port)) == 0:
                    return
            time.sleep(0.05)
        raise RuntimeError("iPerf health check timed out")

    @staticmethod
    def _process_output(process: subprocess.Popen, logger: logging.Logger):
        assert process.stdout is not None
        with process.stdout:
            for line in process.stdout:
                if isinstance(line, bytes):
                    line = line.decode(locale.getpreferredencoding(False), errors="replace")
                logger.info("%s", line.strip())

    @staticmethod
    def _has_exited(runtime: ServiceRuntime) -> bool:
        if runtime.process is not None:
            return runtime.process.poll() is not None
        return runtime.worker is None or not runtime.worker.is_alive()

    def _stop(self, kind: str):
        runtime = self.runtimes[kind]
        runtime.phase = "stopping"
        self._release(runtime)
        runtime.phase, runtime.error_code = "stopped", ""
        if runtime.logger:
            runtime.logger.info("Stopped")
        self._audit(kind, "LOCAL_NETWORK_SERVICE_STOPPED")

    @staticmethod
    def _release(runtime: ServiceRuntime):
        runtime.stopping.set()
        if runtime.server is not None:
            if runtime.worker is not None and runtime.worker.is_alive():
                runtime.server.shutdown()
                runtime.worker.join(timeout=getattr(runtime.server, "request_timeout", 3) + 2)
            runtime.server.server_close()
            if runtime.worker is not None:
                runtime.worker.join(timeout=1)
            runtime.server, runtime.worker = None, None
        if runtime.process is not None:
            if runtime.process.poll() is None:
                runtime.process.terminate()
                try:
                    runtime.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    runtime.process.kill()
                    runtime.process.wait(timeout=2)
            runtime.process = None
        if runtime.job_handle is not None:
            runtime.job_handle.close()
            runtime.job_handle = None

    def close(self):
        self.closing.set()
        for kind, runtime in self.runtimes.items():
            with runtime.lock:
                try:
                    if runtime.server is not None or runtime.process is not None:
                        self._stop(kind)
                except (OSError, subprocess.TimeoutExpired):
                    logging.getLogger(__name__).exception("Could not stop %s", kind)
                finally:
                    if runtime.logger:
                        for handler in list(runtime.logger.handlers):
                            runtime.logger.removeHandler(handler)
                            handler.close()

    def _log(self, kind: str) -> logging.Logger:
        runtime = self.runtimes[kind]
        if runtime.logger is None:
            directory = self._directory(kind)
            _ensure_private_directory(directory)
            handler = RotatingFileHandler(shared_path(directory, "service.log"), maxBytes=256_000, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger = logging.Logger(f"local_network_services.{kind}", logging.INFO)
            logger.propagate = False
            logger.addHandler(handler)
            runtime.logger = logger
        return runtime.logger

    def _audit(self, kind: str, event: str, detail: str = "") -> None:
        suffix = f" {detail}" if detail else ""
        self._log(kind).info("AUDIT service=%s event=%s%s", kind, event, suffix)

    def logs(self, kind: str) -> list[str]:
        with self.runtimes[kind].lock:
            path = shared_path(self._directory(kind), "service.log")
            try:
                with path.open("rb") as stream:
                    stream.seek(max(0, os.fstat(stream.fileno()).st_size - 32_768))
                    return stream.read(32_768).decode("utf-8", errors="replace").splitlines()[-150:]
            except FileNotFoundError:
                return []


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    username = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    identity = f"{domain}\\{username}" if domain else username
    if not identity:
        raise OSError("interactive user identity is unavailable")
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(OI)(CI)F"],
        check=False,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError("could not restrict service directory permissions")
