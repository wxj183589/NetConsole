from __future__ import annotations

import errno
import ipaddress
import json
import locale
import logging
import os
import re
import socket
import secrets
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Empty, Queue
from threading import Event, RLock, Thread
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netconsole.core.atomic_file import atomic_write_bytes
from netconsole.services.job_center.local_process_adapter import _windows_process_tree_factory
from netconsole.services.local_network_services.protocols import shared_path
from netconsole.services.windows_network_manager import NetworkManagerError, WindowsNetworkManager
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

try:
    from netconsole.services.local_network_services.ftp import FTP_USERNAME, LocalFtpServer
except ModuleNotFoundError as exc:
    if exc.name not in {"pyftpdlib", "pyasynchat", "pyasyncore"}:
        raise
    LocalFtpServer = None
    FTP_USERNAME = ""

ServiceId = Literal["dhcp", "dns", "ntp", "tftp", "ftp", "sftp", "http", "https", "ssh", "telnet", "nfs", "vnc", "scheduler", "iperf", "syslog"]
FILE_SHARES = {"ftp", "http", "https", "tftp"}


@dataclass(frozen=True)
class ServiceDefinition:
    group: str
    port: int
    transport: str = "TCP"
    source: str = "external"
    dependency: str = ""
    enabled: bool = True


SERVICES = {
    "dhcp": ServiceDefinition("core", 67, "UDP", "deferred", enabled=False),
    "dns": ServiceDefinition("core", 53, "UDP", "deferred", enabled=False),
    "ntp": ServiceDefinition("core", 123, "UDP", "deferred", enabled=False),
    "syslog": ServiceDefinition("core", 514, "UDP/TCP", "built_in"),
    "tftp": ServiceDefinition("files", 69, "UDP", "built_in"),
    "ftp": ServiceDefinition("files", 2121, source="built_in", dependency="pyftpdlib"),
    "sftp": ServiceDefinition("files", 2222, dependency="Managed SFTP server"),
    "http": ServiceDefinition("files", 8080, source="built_in"),
    "https": ServiceDefinition("files", 8443, source="built_in"),
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
    tls_enabled: bool = False
    auto_restart: bool = False
    ftp_username: str = Field(default="netconsole", pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    passive_ports: tuple[int, int] | None = None
    dns_records: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        return str(ipaddress.IPv4Address(value))

    @field_validator("passive_ports")
    @classmethod
    def validate_passive_ports(cls, value):
        if value is not None and not 1024 <= value[0] <= value[1] <= 65535:
            raise ValueError("invalid passive port range")
        return value

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
    started_at: float | None = None
    started_iso: str = ""
    restart_times: deque[float] = field(default_factory=lambda: deque(maxlen=3))
    process_cpu_sample: tuple[float, float] | None = None
    metrics_handle: int | None = None
    worker_pid: int | None = None
    session_password: str = ""
    output_workers: list[Thread] = field(default_factory=list)


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
        self._openssh_time = -60.0
        self._openssh_inventory: dict = {}
        self.supervisor = Thread(target=self._supervisor_loop, name="network-service-supervisor", daemon=True)
        self.supervisor.start()

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
        if not SERVICES[kind].enabled:
            return False
        if kind == "ftp":
            return LocalFtpServer is not None
        definition = SERVICES[kind]
        return definition.enabled and (definition.source == "built_in" or (
            kind == "iperf" and self.iperf_path is not None and self.iperf_path.is_file()
        ))

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
            available = self._available(kind)
            phase = runtime.phase if available else "dependency_missing" if definition.enabled else "deferred"
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
            running = phase == "running"
            pid = (runtime.worker_pid or runtime.process.pid) if runtime.process is not None else os.getpid() if running else None
            fingerprint = self._certificate_fingerprint(kind) if kind in {"ftp", "https"} else ""
            cpu_percent, memory_bytes = self._process_metrics(runtime) if runtime.process is not None else (None, None)
            return {
                "id": kind, "group": definition.group, "source": definition.source, "status": phase,
                "available": available, "dependency": definition.dependency, "transport": definition.transport,
                "installed": self._installed(kind),
                "capabilities": self._openssh_probe() if kind in {"ssh", "sftp"} else {},
                "error_code": runtime.error_code,
                "enabled": definition.enabled,
                "pid": pid,
                "process_owner": "service" if runtime.process is not None else "backend" if running else "",
                "started_at": runtime.started_iso if running else "",
                "uptime_seconds": max(0, int(time.monotonic() - runtime.started_at)) if running and runtime.started_at else 0,
                "health": "unhealthy" if runtime.phase == "error" or running and self._has_exited(runtime) else "healthy" if running else "stopped",
                "cpu_percent": cpu_percent,
                "memory_bytes": memory_bytes,
                "restart_attempts": len(runtime.restart_times),
                "tls_supported": self._tls_supported(kind),
                "certificate_fingerprint": fingerprint,
                "config": config or (ServiceConfig(port=definition.port, tls_enabled=kind == "https") if available else None),
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

    def _openssh_probe(self) -> dict:
        with self._address_lock:
            if time.monotonic() - self._openssh_time < 30:
                return self._openssh_inventory
            system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "OpenSSH"
            inventory = {
                "ssh_client": (system / "ssh.exe").is_file(),
                "sftp_client": (system / "sftp.exe").is_file(),
                "ssh_server": (system / "sshd.exe").is_file(),
                "sftp_server": (system / "sftp-server.exe").is_file(),
                "service_state": "unknown", "pid": None, "listeners": [], "version": "",
            }
            if os.name == "nt":
                script = (
                    "$s=Get-CimInstance Win32_Service -Filter \"Name='sshd'\" -ErrorAction Stop; "
                    "$l=@(); if($s.ProcessId -gt 0){$l=@(Get-NetTCPConnection -State Listen -OwningProcess $s.ProcessId -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort)}; "
                    "$v=(Get-Item ($env:SystemRoot+'\\System32\\OpenSSH\\sshd.exe') -ErrorAction SilentlyContinue).VersionInfo.FileVersion; "
                    "@{service_state=if($s){$s.State}else{'not_installed'};pid=$s.ProcessId;listeners=$l;version=$v}|ConvertTo-Json -Compress -Depth 4"
                )
                try:
                    result = subprocess.run(
                        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                        capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if result.returncode == 0:
                        inventory.update(json.loads(result.stdout.decode("utf-8-sig")))
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            self._openssh_inventory = inventory
            self._openssh_time = time.monotonic()
            return inventory

    @staticmethod
    def _tls_supported(kind: str) -> bool:
        if kind == "https":
            return True
        if kind != "ftp":
            return False
        try:
            from pyftpdlib.handlers import TLS_FTPHandler
        except ImportError:
            return False
        return TLS_FTPHandler is not None

    def _certificate_paths(self, kind: str) -> tuple[Path, Path]:
        directory = self._directory(kind)
        return shared_path(directory, "server.crt"), shared_path(directory, "server.key")

    def _ensure_certificate(self, kind: str, address: str) -> tuple[Path, Path]:
        certificate_path, key_path = self._certificate_paths(kind)
        if certificate_path.is_file() and key_path.is_file():
            try:
                certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
                private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
                names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                encoding = serialization.Encoding.DER
                key_format = serialization.PublicFormat.SubjectPublicKeyInfo
                matches_key = certificate.public_key().public_bytes(encoding, key_format) == private_key.public_key().public_bytes(encoding, key_format)
                if (
                    matches_key
                    and ipaddress.ip_address(address) in names.get_values_for_type(x509.IPAddress)
                    and certificate.not_valid_before_utc <= datetime.now(timezone.utc)
                    and certificate.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=7)
                ):
                    return certificate_path, key_path
            except (ValueError, TypeError, x509.ExtensionNotFound):
                pass
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, address)]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, address)]))
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.ip_address(address)),
                    x509.DNSName("localhost"),
                ]),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )
        atomic_write_bytes(certificate_path, certificate.public_bytes(serialization.Encoding.PEM))
        atomic_write_bytes(key_path, private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        return certificate_path, key_path

    def _certificate_fingerprint(self, kind: str) -> str:
        certificate_path, _key_path = self._certificate_paths(kind)
        try:
            certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        except (OSError, ValueError):
            return ""
        return certificate.fingerprint(hashes.SHA256()).hex()

    @staticmethod
    def _process_metrics(runtime: ServiceRuntime) -> tuple[float | None, int | None]:
        if os.name != "nt" or runtime.process is None or runtime.process.poll() is not None:
            return None, None
        import ctypes
        from ctypes import wintypes

        class FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        process_handle = runtime.metrics_handle or runtime.process._handle
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        file_time_pointer = ctypes.POINTER(FileTime)
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, file_time_pointer, file_time_pointer, file_time_pointer, file_time_pointer]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        creation, exit_time, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
        memory = ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        if not kernel32.GetProcessTimes(process_handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return None, None
        if not psapi.GetProcessMemoryInfo(process_handle, ctypes.byref(memory), memory.cb):
            return None, None
        cpu_ticks = (kernel_time.high << 32 | kernel_time.low) + (user_time.high << 32 | user_time.low)
        now = time.monotonic()
        previous = runtime.process_cpu_sample
        runtime.process_cpu_sample = (now, cpu_ticks)
        if previous is None or now <= previous[0]:
            return None, int(memory.WorkingSetSize)
        cpu_percent = max(0.0, (cpu_ticks - previous[1]) / 10_000_000 / (now - previous[0]) * 100)
        return round(cpu_percent, 1), int(memory.WorkingSetSize)

    def configure(self, kind: str, config: ServiceConfig) -> dict:
        if self.closing.is_set():
            raise ValueError("manager_closed")
        runtime = self.runtimes[kind]
        if not self._available(kind):
            raise ValueError("dependency_missing")
        if config.address not in self.bind_addresses(refresh=config.address != "127.0.0.1"):
            raise ValueError("unsupported_bind_address")
        if config.allow_upload and kind not in {"tftp", "ftp"} or config.dns_records and kind != "dns":
            raise ValueError("unsupported_service_option")
        if kind != "ftp" and (config.passive_ports is not None or config.ftp_username != "netconsole"):
            raise ValueError("unsupported_service_option")
        if config.tls_enabled and kind not in {"ftp", "https"} or kind == "https" and not config.tls_enabled:
            raise ValueError("unsupported_tls_option")
        if kind == "ftp" and config.tls_enabled and not self._tls_supported(kind):
            raise ValueError("tls_dependency_missing")
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
                if action == "restart":
                    runtime.restart_times.clear()
            started = False
            if action in {"start", "restart"} and runtime.phase != "running":
                config = self._config(kind)
                if config is None:
                    raise ValueError("not_initialized")
                self._start(kind, config)
                started = runtime.phase == "running"
            state = self.snapshot(kind)
            if started and kind == "ftp":
                state["session_credential"] = {"username": config.ftp_username, "password": runtime.session_password}
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
                certificate = self._ensure_certificate(kind, config.address) if kind == "https" or kind == "ftp" and config.tls_enabled else None
                self._start_service_process(kind, config, root, certificate, logger)
            runtime.phase = "running"
            runtime.started_at = time.monotonic()
            runtime.started_iso = datetime.now(timezone.utc).isoformat()
            logger.info("Started on %s:%s", config.address, config.port)
        except (OSError, ValueError, RuntimeError) as exc:
            self._release(runtime)
            conflict = isinstance(exc, OSError) and (exc.errno in {errno.EADDRINUSE, 10048} or getattr(exc, "winerror", None) == 10048)
            runtime.phase = "port_conflict" if conflict else "error"
            runtime.error_code = "address_in_use" if conflict else "start_failed"
            runtime.started_at = None
            runtime.started_iso = ""
            if runtime.logger:
                runtime.logger.warning("Start failed: %s", exc)
                self._audit(
                    kind,
                    "LOCAL_NETWORK_SERVICE_START_FAILED",
                    f"code={runtime.error_code} type={exc.__class__.__name__}",
                )

    @staticmethod
    def _bind_worker_metrics(runtime: ServiceRuntime, worker_pid: int) -> None:
        if type(worker_pid) is not int or worker_pid <= 0:
            raise RuntimeError("Invalid worker readiness PID")
        if os.name != "nt":
            runtime.worker_pid = worker_pid
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        # Keep this query-only handle to the authenticated process object, avoiding PID reuse.
        handle = kernel32.OpenProcess(0x1000 | 0x0010, False, worker_pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Cannot query network service worker")
        try:
            in_job = wintypes.BOOL()
            job = getattr(runtime.job_handle, "_handle", None)
            if not job or not kernel32.IsProcessInJob(handle, job, ctypes.byref(in_job)) or not in_job.value:
                raise RuntimeError("Worker readiness PID is outside owned Job Object")
        except BaseException:
            kernel32.CloseHandle(handle)
            raise
        runtime.metrics_handle = handle
        runtime.worker_pid = worker_pid

    def _start_service_process(self, kind, config, root, certificate, logger):
        runtime = self.runtimes[kind]
        command = [sys.executable, "--local-network-service-worker"] if getattr(sys, "frozen", False) else [
            sys.executable, "-m", "netconsole.services.local_network_services.worker",
        ]
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        if not getattr(sys, "frozen", False):
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
        runtime.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if os.name == "nt":
            runtime.job_handle = _windows_process_tree_factory(runtime.process)
        if kind == "ftp" and not runtime.session_password:
            runtime.session_password = secrets.token_urlsafe(18)
        bootstrap = {
            "kind": kind, "config": config.model_dump(), "root": str(root) if root else None,
            "certificate": [str(path) for path in certificate] if certificate else None,
            "password": runtime.session_password,
        }
        ready = Queue(maxsize=1)
        process = runtime.process

        def drain_output():
            with process.stdout:
                first = process.stdout.readline()
                try:
                    ready.put(json.loads(first))
                except (ValueError, UnicodeError):
                    ready.put({"ready": False})
                for line in process.stdout:
                    message = line.decode("utf-8", errors="replace").strip()
                    level_name, separator, detail = message.partition(" ")
                    severity = logging.getLevelNamesMapping().get(level_name)
                    logger.log(severity or logging.INFO, "%s", detail if separator and severity is not None else message)

        def drain_errors():
            with process.stderr:
                for line in process.stderr:
                    logger.warning("%s", line.decode("utf-8", errors="replace").strip())

        runtime.output_workers = [
            Thread(target=drain_output, name=f"network-service-{kind}-stdout", daemon=True),
            Thread(target=drain_errors, name=f"network-service-{kind}-stderr", daemon=True),
        ]
        for worker in runtime.output_workers:
            worker.start()
        process.stdin.write(json.dumps(bootstrap).encode("utf-8") + b"\n")
        process.stdin.flush()
        try:
            result = ready.get(timeout=15)
        except Empty as exc:
            raise RuntimeError("Service readiness timed out") from exc
        if not result.get("ready"):
            if result.get("errno") in {errno.EADDRINUSE, 10048}:
                raise OSError(errno.EADDRINUSE, "address_in_use")
            raise RuntimeError("Service initialization failed")
        self._bind_worker_metrics(runtime, result.get("pid"))

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
        runtime.process_cpu_sample = None
        if os.name == "nt":
            runtime.job_handle = _windows_process_tree_factory(runtime.process)
        # Drain output throughout the process lifetime so a busy service cannot block on its pipe.
        runtime.output_workers = [
            Thread(target=self._process_output, args=(runtime.process, logger), name="network-service-iperf-stdout", daemon=True),
        ]
        runtime.output_workers[0].start()
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
        runtime.started_at = None
        runtime.started_iso = ""
        runtime.session_password = ""
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
        try:
            if runtime.process is not None:
                if runtime.process.poll() is None:
                    if runtime.process.stdin is not None:
                        try:
                            runtime.process.stdin.write(b"stop\n")
                            runtime.process.stdin.flush()
                        except OSError:
                            pass
                        try:
                            runtime.process.stdin.close()
                        except OSError:
                            pass
                    else:
                        runtime.process.terminate()
                    try:
                        runtime.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        runtime.process.kill()
                        runtime.process.wait(timeout=2)
                elif runtime.process.stdin is not None:
                    try:
                        runtime.process.stdin.close()
                    except OSError:
                        pass
                runtime.process = None
        finally:
            if runtime.metrics_handle is not None:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                kernel32.CloseHandle(runtime.metrics_handle)
                runtime.metrics_handle = None
            runtime.worker_pid = None
            if runtime.job_handle is not None:
                runtime.job_handle.close()
                runtime.job_handle = None
        for worker in runtime.output_workers:
            worker.join(timeout=2)
        runtime.output_workers.clear()
        runtime.process_cpu_sample = None

    def close(self):
        self.closing.set()
        self.supervisor.join(timeout=2)
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

    def _supervisor_loop(self) -> None:
        while not self.closing.wait(0.5):
            for kind in SERVICES:
                try:
                    self._supervise(kind)
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                    logging.getLogger(__name__).exception("Could not supervise %s", kind)

    def _supervise(self, kind: str) -> None:
        runtime = self.runtimes[kind]
        with runtime.lock:
            if self.closing.is_set() or runtime.phase != "running" or not self._has_exited(runtime):
                return
            runtime.phase, runtime.error_code = "error", "service_exited"
            runtime.started_at = None
            runtime.started_iso = ""
            self._release(runtime)
            self._log(kind).warning("Service exited unexpectedly")
            self._audit(kind, "LOCAL_NETWORK_SERVICE_EXITED")
            config = self._config(kind)
            now = time.monotonic()
            while runtime.restart_times and now - runtime.restart_times[0] > 300:
                runtime.restart_times.popleft()
            if config is None or not config.auto_restart:
                return
            if len(runtime.restart_times) >= 3:
                runtime.error_code = "auto_restart_limit"
                self._audit(kind, "LOCAL_NETWORK_SERVICE_AUTO_RESTART_LIMIT")
                return
            runtime.restart_times.append(now)
            self._log(kind).warning("Attempting bounded service recovery %d/3", len(runtime.restart_times))
            self._start(kind, config)

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

    def logs(self, kind: str, *, history: bool = False) -> list[str]:
        with self.runtimes[kind].lock:
            directory = self._directory(kind)
            names = ["service.log.2", "service.log.1", "service.log"] if history else ["service.log"]
            lines = []
            for name in names:
                path = shared_path(directory, name)
                try:
                    with path.open("rb") as stream:
                        offset = max(0, os.fstat(stream.fileno()).st_size - 256_000)
                        stream.seek(offset)
                        if offset:
                            stream.readline()
                        lines.extend(stream.read(256_000).decode("utf-8", errors="replace").splitlines())
                except FileNotFoundError:
                    continue
            return lines[-1500:] if history else lines[-150:]



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
