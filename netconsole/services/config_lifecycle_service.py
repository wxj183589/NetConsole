from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Callable
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.config_snapshot_repository import ConfigSnapshot, ConfigSnapshotRepository
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.netmiko_connection import safe_send_command, sanitize_sensitive_text
from netconsole.utils.text_encoding import clean_h3c_device_text


CONFIG_CONTEXT = "config_lifecycle"
RUNNING_COMMAND = "display current-configuration"
SAVED_COMMAND = "display saved-configuration"
SAVE_FORCE_COMMAND = "save force"
SCREEN_LENGTH_COMMAND = "screen-length disable"
DIFF_IGNORED_COMMANDS = {RUNNING_COMMAND.casefold(), SAVED_COMMAND.casefold()}
CONFIG_BODY_START_PATTERN = re.compile(r"^(#|version\b|sysname\b|vlan\b|interface\b)", re.IGNORECASE)
CONFIG_BODY_END_PATTERN = re.compile(r"^(return|quit)\s*$", re.IGNORECASE)
PROMPT_PATTERN = re.compile(r"^\s*(<[^<>]+>|\[[^\[\]]+\])\s*$")


@dataclass(frozen=True)
class ConfigDiffResult:
    added: list[str]
    removed: list[str]
    modified: list[dict[str, str]]
    raw_diff: str


@dataclass(frozen=True)
class ConfigOperationResult:
    success: bool
    device_uuid: str
    timestamp: str
    snapshots: list[ConfigSnapshot]
    diff: ConfigDiffResult | None = None
    raw_log_path: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class BatchConfigItemResult:
    device_name: str
    device_uuid: str
    success: bool
    result_text: str
    timestamp: str
    snapshot_count: int
    elapsed_ms: int
    snapshots: list[ConfigSnapshot]
    raw_log_path: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class MultiDeviceCompareResult:
    device_a: str
    device_b: str
    diff: ConfigDiffResult
    structure_diff: dict[str, list[str]]


class ConfigLifecycleService:
    def __init__(
        self,
        site_name: str,
        database: Database,
        paths: PathResolver | None = None,
        repository: ConfigSnapshotRepository | None = None,
    ) -> None:
        self.site_name = site_name
        self.paths = paths or PathResolver()
        self.repository = repository or ConfigSnapshotRepository(database)

    def save_force(self, device: Device) -> ConfigOperationResult:
        device.ensure_device_uuid()
        timestamp = snapshot_timestamp()
        collect_uuid = str(uuid4())
        raw_log_file = self._raw_log_file(device, timestamp, collect_uuid)
        command_results: list[dict[str, object]] = []
        protocol = ""
        try:
            command_guard.validate_command_list([SAVE_FORCE_COMMAND], CONFIG_CONTEXT)
            def operation(connection, target):
                nonlocal protocol
                protocol = target.protocol
                return self._run_command(connection, SAVE_FORCE_COMMAND, device, read_timeout=180)

            save_result = netmiko_connection.run_netmiko_with_retry(device, operation)
            command_results.append(save_result)
            self._write_raw_log(raw_log_file, device, timestamp, protocol, command_results)
            if not bool(save_result["success"]):
                message = str(save_result.get("error_message") or "save force failed")
                app_logger.log_error("CONFIG_SAVE_FAILED", self._detail(device, error=message, raw_log_path=raw_log_file))
                return ConfigOperationResult(False, str(device.device_uuid), timestamp, [], raw_log_path=str(raw_log_file), error_message=message)
            relative_raw_log_path = self._relative_to_site(raw_log_file)
            saved_snapshot = self._write_snapshot(device, "saved", timestamp, save_status_snapshot_text(device, timestamp, str(save_result.get("output") or "")), raw_log_path=relative_raw_log_path)
            app_logger.log_info("CONFIG_SAVE_SUCCESS", self._detail(device, raw_log_path=raw_log_file))
            return ConfigOperationResult(True, str(device.device_uuid), timestamp, [saved_snapshot], raw_log_path=str(raw_log_file))
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc), device)
            self._write_raw_log(raw_log_file, device, timestamp, protocol, command_results, message)
            app_logger.log_error("CONFIG_SAVE_FAILED", self._detail(device, error=message, raw_log_path=raw_log_file))
            return ConfigOperationResult(False, str(device.device_uuid), timestamp, [], raw_log_path=str(raw_log_file), error_message=message)

    def fetch_configs(self, device: Device) -> ConfigOperationResult:
        device.ensure_device_uuid()
        timestamp = snapshot_timestamp()
        collect_uuid = str(uuid4())
        raw_log_file = self._raw_log_file(device, timestamp, collect_uuid)
        command_results: list[dict[str, object]] = []
        protocol = ""
        try:
            command_guard.validate_command_list([SCREEN_LENGTH_COMMAND, RUNNING_COMMAND, SAVED_COMMAND], CONFIG_CONTEXT)
            def operation(connection, target):
                nonlocal protocol
                protocol = target.protocol
                screen_result = self._run_command(connection, SCREEN_LENGTH_COMMAND, device)
                running = self._run_command(connection, RUNNING_COMMAND, device, read_timeout=180)
                saved = self._run_command(connection, SAVED_COMMAND, device, read_timeout=180)
                return screen_result, running, saved

            screen_result, running_result, saved_result = netmiko_connection.run_netmiko_with_retry(device, operation)
            command_results.append(screen_result)
            command_results.extend([running_result, saved_result])
            self._write_raw_log(raw_log_file, device, timestamp, protocol, command_results)
            if not bool(running_result["success"]) or not bool(saved_result["success"]):
                message = "; ".join(str(item.get("error_message") or item["command"]) for item in (running_result, saved_result) if not bool(item["success"]))
                app_logger.log_error("CONFIG_FETCH_FAILED", self._detail(device, error=message, raw_log_path=raw_log_file))
                return ConfigOperationResult(False, str(device.device_uuid), timestamp, [], raw_log_path=str(raw_log_file), error_message=message)
            relative_raw_log_path = self._relative_to_site(raw_log_file)
            running_snapshot = self._write_snapshot(device, "running", timestamp, str(running_result["output"]), raw_log_path=relative_raw_log_path)
            saved_snapshot = self._write_snapshot(device, "saved", timestamp, str(saved_result["output"]), raw_log_path=relative_raw_log_path)
            diff = compare_config_text(str(running_result["output"]), str(saved_result["output"]))
            diff_snapshot = self._write_snapshot(device, "diff", timestamp, diff.raw_diff, raw_log_path=relative_raw_log_path)
            app_logger.log_info("CONFIG_FETCH_SUCCESS", self._detail(device, raw_log_path=raw_log_file))
            return ConfigOperationResult(True, str(device.device_uuid), timestamp, [running_snapshot, saved_snapshot, diff_snapshot], diff, str(raw_log_file))
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc), device)
            self._write_raw_log(raw_log_file, device, timestamp, protocol, command_results, message)
            app_logger.log_error("CONFIG_FETCH_FAILED", self._detail(device, error=message, raw_log_path=raw_log_file))
            return ConfigOperationResult(False, str(device.device_uuid), timestamp, [], raw_log_path=str(raw_log_file), error_message=message)

    def compare_snapshots(self, running_snapshot: ConfigSnapshot, saved_snapshot: ConfigSnapshot) -> ConfigDiffResult:
        running_text = self.snapshot_text(running_snapshot)
        saved_text = self.snapshot_text(saved_snapshot)
        return compare_config_text(running_text, saved_text)

    def compare_latest_running_between_devices(self, device_a: Device, device_b: Device) -> MultiDeviceCompareResult:
        running_a = self.list_device_snapshots(device_a, "running")
        running_b = self.list_device_snapshots(device_b, "running")
        if not running_a or not running_b:
            raise ValueError("Both devices must have running snapshots before comparison.")
        text_a = self.snapshot_text(running_a[0])
        text_b = self.snapshot_text(running_b[0])
        diff = compare_named_config_text(text_a, text_b, str(device_a.name or "device_a"), str(device_b.name or "device_b"))
        return MultiDeviceCompareResult(
            device_a=str(device_a.name or ""),
            device_b=str(device_b.name or ""),
            diff=diff,
            structure_diff=structure_diff(text_a, text_b),
        )

    def list_device_snapshots(self, device: Device, snapshot_type: str | None = None) -> list[ConfigSnapshot]:
        device.ensure_device_uuid()
        snapshots = self.repository.list_for_device(str(device.device_uuid), snapshot_type)
        return [snapshot for snapshot in snapshots if self._absolute_snapshot_path(snapshot).exists()]

    def snapshot_text(self, snapshot: ConfigSnapshot) -> str:
        path = self._absolute_snapshot_path(snapshot)
        return path.read_text(encoding="utf-8")

    def copy_snapshot(self, snapshot: ConfigSnapshot, target_path: Path) -> None:
        source = self._absolute_snapshot_path(snapshot)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target_path)

    def export_batch_zip(self, batch_results: list[BatchConfigItemResult], target_zip_path: Path) -> None:
        target_zip_path.parent.mkdir(parents=True, exist_ok=True)
        failures: list[str] = []
        used_folders: dict[str, int] = {}
        with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in batch_results:
                if not item.success:
                    message = item.error_message or item.result_text or "failed"
                    failures.append(f"{item.device_name or item.device_uuid}\t{message}")
                    continue
                folder = unique_export_folder_name(item.device_name, item.device_uuid, used_folders)
                for snapshot in item.snapshots:
                    source = self._absolute_snapshot_path(snapshot)
                    if not source.exists():
                        continue
                    suffix = "diff" if snapshot.type == "diff" else "txt"
                    archive.write(source, f"{folder}/{snapshot.type}_{snapshot.timestamp}.{suffix}")
                for log_path in self._batch_log_paths(item):
                    archive.write(log_path, f"{folder}/logs/{log_path.name}")
            if failures:
                archive.writestr("failed_devices.txt", "\n".join(failures) + "\n")

    def delete_snapshot(self, snapshot: ConfigSnapshot) -> None:
        path = self._absolute_snapshot_path(snapshot)
        if path.exists():
            path.unlink()
        if snapshot.id is not None:
            self.repository.delete(int(snapshot.id))

    def device_config_dir(self, device: Device) -> Path:
        return self._device_config_dir(device)

    def _write_snapshot(self, device: Device, snapshot_type: str, timestamp: str, text: str, raw_log_path: str | None = None) -> ConfigSnapshot:
        directory = self._device_config_dir(device) / snapshot_type
        directory.mkdir(parents=True, exist_ok=True)
        suffix = "diff" if snapshot_type == "diff" else "txt"
        path = unique_snapshot_path(directory / f"{timestamp}.{suffix}")
        normalized_text = clean_h3c_device_text(text)
        path.write_text(normalized_text, encoding="utf-8")
        relative_path = self._relative_to_site(path)
        return self.repository.create(
            ConfigSnapshot(
                id=None,
                device_id=device.id,
                device_uuid=str(device.device_uuid),
                timestamp=timestamp,
                type=snapshot_type,
                file_path=relative_path,
                hash=sha256_text(normalized_text),
                raw_log_path=raw_log_path,
            )
        )

    def _run_command(self, connection, command: str, device: Device, read_timeout: int = 60) -> dict[str, object]:
        started_at = datetime.now().isoformat(timespec="seconds")
        try:
            output = safe_send_command(
                connection,
                command,
                read_timeout=read_timeout,
                strip_prompt=False,
                strip_command=False,
                use_timing=True,
            )
        except Exception as exc:
            message = sanitize_sensitive_text(str(exc), device)
            return {"command": command, "success": False, "output": "", "error_message": message, "started_at": started_at, "ended_at": datetime.now().isoformat(timespec="seconds")}
        return {"command": command, "success": True, "output": clean_h3c_device_text(output), "error_message": None, "started_at": started_at, "ended_at": datetime.now().isoformat(timespec="seconds")}

    def _write_raw_log(
        self,
        raw_log_file: Path,
        device: Device,
        timestamp: str,
        protocol: str,
        command_results: list[dict[str, object]],
        fatal_error: str | None = None,
    ) -> None:
        raw_log_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"Config Snapshot Time: {timestamp}",
            f"Device Name: {device.name}",
            f"Primary Address: {device.primary_address}",
            f"Protocol: {protocol}",
            "",
        ]
        for result in command_results:
            lines.extend(
                [
                    f"===== COMMAND: {result.get('command', '')} =====",
                    f"Success: {result.get('success', False)}",
                    f"Started At: {result.get('started_at', '')}",
                    f"Ended At: {result.get('ended_at', '')}",
                    f"Error: {result.get('error_message') or ''}",
                    str(result.get("output") or ""),
                    "",
                ]
            )
        if fatal_error:
            lines.extend(["===== FATAL ERROR =====", fatal_error, ""])
        raw_log_file.write_text("\n".join(lines), encoding="utf-8")
        commands_file = raw_log_file.with_suffix(".jsonl")
        with commands_file.open("w", encoding="utf-8") as file:
            for result in command_results:
                file.write(json.dumps({key: result.get(key) for key in ("command", "success", "error_message", "started_at", "ended_at")}, ensure_ascii=False) + "\n")

    def _raw_log_file(self, device: Device, timestamp: str, collect_uuid: str) -> Path:
        date_name = timestamp.split("_", 1)[0] if "_" in timestamp else timestamp[:8]
        return self.paths.config_center_raw_logs_dir(self.site_name, date_name, device_config_dir_name(device)) / f"{timestamp}_{collect_uuid}.log"

    def _device_config_dir(self, device: Device) -> Path:
        return self.paths.config_center_device_snapshots_dir(self.site_name, device_config_dir_name(device))

    def _absolute_snapshot_path(self, snapshot: ConfigSnapshot) -> Path:
        return self.paths.site_dir(self.site_name) / snapshot.file_path

    def _batch_log_paths(self, item: BatchConfigItemResult) -> list[Path]:
        paths: list[Path] = []
        candidates = [item.raw_log_path]
        candidates.extend(snapshot.raw_log_path for snapshot in item.snapshots)
        for raw in candidates:
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = self.paths.site_dir(self.site_name) / path
            for candidate in (path, path.with_suffix(".jsonl")):
                if candidate.exists() and candidate not in paths:
                    paths.append(candidate)
        return paths

    def _relative_to_site(self, path: Path) -> str:
        return path.resolve().relative_to(self.paths.site_dir(self.site_name).resolve()).as_posix()

    @staticmethod
    def _detail(device: Device, error: str = "", raw_log_path: Path | str | None = None) -> str:
        parts = [f"device={device.name}", f"primary_address={device.primary_address}"]
        if error:
            parts.append(f"error={error}")
        if raw_log_path:
            parts.append(f"raw_log_path={raw_log_path}")
        return ", ".join(parts)


def compare_config_text(running_config_text: str, saved_config_text: str) -> ConfigDiffResult:
    return compare_named_config_text(saved_config_text, running_config_text, "saved", "running")


def compare_named_config_text(from_config_text: str, to_config_text: str, from_name: str, to_name: str) -> ConfigDiffResult:
    from_lines = clean_config_for_diff(from_config_text).splitlines()
    to_lines = clean_config_for_diff(to_config_text).splitlines()
    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=from_name,
            tofile=to_name,
            lineterm="",
        )
    )
    added = [line[1:] for line in diff_lines if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff_lines if line.startswith("-") and not line.startswith("---")]
    return ConfigDiffResult(added=added, removed=removed, modified=[], raw_diff="\n".join(diff_lines))


def snapshot_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def unique_snapshot_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index:03d}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot allocate unique snapshot path: {path}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_config_for_diff(text: str) -> str:
    body_lines: list[str] = []
    in_body = False
    for line in clean_h3c_device_text(text).splitlines():
        stripped = line.strip()
        normalized = stripped.casefold()
        if not stripped or normalized in DIFF_IGNORED_COMMANDS:
            continue
        if PROMPT_PATTERN.match(stripped):
            if in_body:
                break
            continue
        if not in_body:
            if not CONFIG_BODY_START_PATTERN.match(stripped):
                continue
            in_body = True
        if CONFIG_BODY_END_PATTERN.match(stripped):
            break
        body_lines.append(line.rstrip())
    return "\n".join(body_lines)


def save_status_snapshot_text(device: Device, timestamp: str, output: str) -> str:
    lines = [
        "save_force_status: success",
        f"device: {device.name or ''}",
        f"timestamp: {timestamp}",
    ]
    cleaned_output = clean_h3c_device_text(output).strip()
    if cleaned_output:
        lines.extend(["", cleaned_output])
    return "\n".join(lines) + "\n"


def structure_diff(config_a: str, config_b: str) -> dict[str, list[str]]:
    sections_a = set(config_structure_keys(config_a))
    sections_b = set(config_structure_keys(config_b))
    return {
        "only_in_a": sorted(sections_a - sections_b),
        "only_in_b": sorted(sections_b - sections_a),
    }


def config_structure_keys(text: str) -> list[str]:
    keys: list[str] = []
    for line in clean_config_for_diff(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and not line.startswith("\t"):
            keys.append(stripped)
    return keys


def device_config_dir_name(device: Device) -> str:
    device.ensure_device_uuid()
    name = safe_device_name(device.name or device.system_name or "device")
    unique_id = safe_device_id(str(device.device_uuid or device.id or "unknown"))
    return f"{name}__{unique_id}"


def safe_device_name(name: str) -> str:
    value = str(name or "device").strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = value.strip("._ ")
    return value or "device"


def safe_device_id(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value or "unknown")).strip("._ ") or "unknown"


def unique_export_folder_name(device_name: str, device_uuid: str, used: dict[str, int]) -> str:
    base = safe_device_name(device_name or device_uuid or "device")
    count = used.get(base, 0)
    used[base] = count + 1
    if count == 0:
        return base
    suffix = safe_device_id(device_uuid)[:8] or f"{count + 1:02d}"
    candidate = f"{base}_{suffix}"
    if candidate not in used:
        used[candidate] = 1
        return candidate
    return f"{base}_{count + 1:02d}"


def run_batch_config_download(
    devices: list[Device],
    service_factory: Callable[[], ConfigLifecycleService],
    max_workers: int = 50,
) -> list[BatchConfigItemResult]:
    results: list[BatchConfigItemResult] = []
    worker_count = max(1, min(int(max_workers or 1), 50, len(devices) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(service_factory().fetch_configs, device): device for device in devices}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
            device = futures[future]
            elapsed_ms = int((monotonic() - started_at[future]) * 1000)
            try:
                result = future.result()
                item = BatchConfigItemResult(
                    device_name=str(device.name or ""),
                    device_uuid=str(device.device_uuid or ""),
                    success=result.success,
                    result_text=result.error_message or ("成功" if result.success else "失败"),
                    timestamp=result.timestamp,
                    snapshot_count=len(result.snapshots),
                    elapsed_ms=elapsed_ms,
                    snapshots=result.snapshots,
                    raw_log_path=result.raw_log_path,
                    error_message=result.error_message,
                )
            except Exception as exc:
                message = sanitize_sensitive_text(str(exc), device)
                item = BatchConfigItemResult(
                    device_name=str(device.name or ""),
                    device_uuid=str(device.device_uuid or ""),
                    success=False,
                    result_text=message,
                    timestamp="",
                    snapshot_count=0,
                    elapsed_ms=elapsed_ms,
                    snapshots=[],
                    error_message=message,
                )
            results.append(item)
    return results
