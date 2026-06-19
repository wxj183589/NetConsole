from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Callable

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, safe_send_command, sanitize_sensitive_text
from netconsole.utils.text_encoding import clean_h3c_device_text


DIAGNOSTIC_CONTEXT = "diagnostic_download"
DIAGNOSTIC_COMMANDS = ("screen-length disable", "display diagnostic-information", "n")
DIAGNOSTIC_CONCURRENCY = 50


@dataclass(frozen=True)
class DiagnosticDownloadResult:
    device_id: int | None
    device_name: str
    timestamp: str
    file_path: str | None
    status: str
    error_message: str | None = None
    elapsed_ms: int | None = None

    @property
    def success(self) -> bool:
        return self.status == "success"


class DiagnosticDownloadService:
    def __init__(self, site_name: str, paths: PathResolver | None = None) -> None:
        self.site_name = site_name
        self.paths = paths or PathResolver()

    def download(self, device: Device) -> DiagnosticDownloadResult:
        timestamp = diagnostic_timestamp()
        started = monotonic()
        output_parts: list[str] = []
        target = choose_connection_target(device)
        file_path: Path | None = None
        connection = None
        if target is None:
            message = "No SSH or Telnet connection is enabled."
            app_logger.log_error("DIAGNOSTIC_DOWNLOAD_FAILED", self._detail(device, timestamp, error=message))
            return DiagnosticDownloadResult(device.id, str(device.name or ""), timestamp, None, "failed", message, elapsed_ms(started))
        try:
            command_guard.validate_command_list(DIAGNOSTIC_COMMANDS, DIAGNOSTIC_CONTEXT)
            connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
            output_parts.append(self._run_command(connection, "screen-length disable", device, read_timeout=60))
            output_parts.append(self._run_command(connection, "display diagnostic-information", device, read_timeout=120))
            output_parts.append(self._run_command(connection, "n", device, read_timeout=600))
            connection.disconnect()
            connection = None
            file_path = self._write_diagnostic_file(device, timestamp, "\n".join(output_parts))
            app_logger.log_info("DIAGNOSTIC_DOWNLOAD_SUCCESS", self._detail(device, timestamp, file_path=file_path))
            return DiagnosticDownloadResult(
                device.id,
                str(device.name or ""),
                timestamp,
                self._relative_to_site(file_path),
                "success",
                None,
                elapsed_ms(started),
            )
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc), device)
            app_logger.log_error("DIAGNOSTIC_DOWNLOAD_FAILED", self._detail(device, timestamp, error=message, file_path=file_path))
            return DiagnosticDownloadResult(device.id, str(device.name or ""), timestamp, self._relative_to_site(file_path) if file_path else None, "failed", message, elapsed_ms(started))
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def _run_command(self, connection, command: str, device: Device, read_timeout: int) -> str:
        return clean_h3c_device_text(
            safe_send_command(
                connection,
                command,
                read_timeout=read_timeout,
                strip_prompt=False,
                strip_command=False,
                use_timing=True,
            )
        )

    def _write_diagnostic_file(self, device: Device, timestamp: str, text: str) -> Path:
        directory = self.paths.ensure_site_dirs(self.site_name) / "raw" / "diagnostic"
        directory.mkdir(parents=True, exist_ok=True)
        path = unique_path(directory / f"{safe_device_name(device.name or device.sysname or 'device')}_diag_{timestamp}.txt")
        path.write_text(clean_h3c_device_text(text), encoding="utf-8")
        return path

    def _relative_to_site(self, path: Path) -> str:
        return path.resolve().relative_to(self.paths.site_dir(self.site_name).resolve()).as_posix()

    @staticmethod
    def _detail(device: Device, timestamp: str, error: str = "", file_path: Path | None = None) -> str:
        parts = [f"device={device.name}", f"ip={device.ip_address}", f"timestamp={timestamp}"]
        if file_path:
            parts.append(f"file_path={file_path}")
        if error:
            parts.append(f"error={error}")
        return ", ".join(parts)


def run_batch_diagnostic_download(
    devices: list[Device],
    service_factory: Callable[[], DiagnosticDownloadService],
    max_workers: int = DIAGNOSTIC_CONCURRENCY,
) -> list[DiagnosticDownloadResult]:
    worker_count = max(1, min(int(max_workers or 1), DIAGNOSTIC_CONCURRENCY, len(devices) or 1))
    results: list[DiagnosticDownloadResult] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(service_factory().download, device): device for device in devices}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
            device = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                message = sanitize_sensitive_text(str(exc), device)
                app_logger.log_error("DIAGNOSTIC_DOWNLOAD_FAILED", f"device={device.name}, ip={device.ip_address}, error={message}")
                results.append(
                    DiagnosticDownloadResult(
                        device.id,
                        str(device.name or ""),
                        diagnostic_timestamp(),
                        None,
                        "failed",
                        message,
                        elapsed_ms(started_at[future]),
                    )
                )
    return results


def diagnostic_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def safe_device_name(name: str) -> str:
    value = str(name or "device").strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value.strip("._ ") or "device"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot allocate unique diagnostic path: {path}")
