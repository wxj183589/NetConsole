from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.parsers.h3c.interface_parser import parse_interfaces
from netconsole.parsers.h3c.transceiver_parser import parse_transceiver_diagnosis
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.h3c_collect_service import CommandResult
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, safe_send_command, sanitize_sensitive_text
from netconsole.utils.text_encoding import clean_h3c_device_text


OPTICAL_REFRESH_COMMANDS = (
    "screen-length disable",
    "display interface",
    "display transceiver diagnosis interface",
)

BASE_OPTICAL_FIELDS = (
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
)


@dataclass(frozen=True)
class OpticalRefreshResult:
    success: bool
    device_uuid: str
    collect_run_uuid: str
    raw_log_path: str
    interfaces_updated: int
    optical_modules_updated: int
    error_message: str | None
    command_results: list[CommandResult] = field(default_factory=list)


def refresh_h3c_device_optical(
    device: Device,
    site_name: str,
    repository: DeviceFactRepository | None = None,
    paths: PathResolver | None = None,
) -> OpticalRefreshResult:
    paths = paths or PathResolver()
    repository = repository or DeviceFactRepository(Database(paths.site_db_path(site_name)))
    device.ensure_device_uuid()
    collect_run_uuid = str(uuid4())
    started_at = _now()
    run_dir = paths.ensure_site_dirs(site_name) / "raw" / "collect" / collect_run_uuid
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_log_file = run_dir / f"{device.device_uuid}.log"
    commands_file = run_dir / f"{device.device_uuid}_commands.jsonl"
    relative_raw_log_path = f"raw/collect/{collect_run_uuid}/{device.device_uuid}.log"

    repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "optical_refresh",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"raw/collect/{collect_run_uuid}",
            "created_at": started_at,
        }
    )
    app_logger.log_info("OPTICAL_REFRESH_STARTED", _detail(device, collect_run_uuid, raw_log_path=relative_raw_log_path))

    command_results: list[CommandResult] = []
    connection = None
    target = choose_connection_target(device)
    if target is None:
        message = "未启用连接方式"
        _write_raw_files(raw_log_file, commands_file, device, "", collect_run_uuid, command_results, fatal_error=message)
        repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("OPTICAL_REFRESH_FAILED", _detail(device, collect_run_uuid, error=message, raw_log_path=relative_raw_log_path))
        return OpticalRefreshResult(False, str(device.device_uuid), collect_run_uuid, str(raw_log_file), 0, 0, message, command_results)

    try:
        command_guard.validate_command_list(OPTICAL_REFRESH_COMMANDS, "optical_refresh")
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        outputs: dict[str, str] = {}
        for command in OPTICAL_REFRESH_COMMANDS:
            result = _run_command(connection, command, device, collect_run_uuid)
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        _write_raw_files(raw_log_file, commands_file, device, target.protocol, collect_run_uuid, command_results)
        write_result = _parse_and_write(repository, device, collect_run_uuid, relative_raw_log_path, outputs)
        error_message = _command_error_summary(command_results) or "; ".join(write_result["parse_errors"])
        status = "partial_success" if error_message else "success"
        if not write_result["interfaces"] and not write_result["optical_modules"]:
            status = "failed"
        repository.update_latest_raw_log_path(str(device.device_uuid), collect_run_uuid, relative_raw_log_path)
        repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        detail = _detail(
            device,
            collect_run_uuid,
            error=error_message or "",
            raw_log_path=relative_raw_log_path,
            interface_count=int(write_result["interfaces"]),
            optical_count=int(write_result["optical_modules"]),
        )
        (app_logger.log_info if status != "failed" else app_logger.log_error)(
            "OPTICAL_REFRESH_SUCCESS" if status != "failed" else "OPTICAL_REFRESH_FAILED",
            detail,
        )
        return OpticalRefreshResult(
            status != "failed",
            str(device.device_uuid),
            collect_run_uuid,
            str(raw_log_file),
            int(write_result["interfaces"]),
            int(write_result["optical_modules"]),
            error_message or None,
            command_results,
        )
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        _write_raw_files(raw_log_file, commands_file, device, target.protocol if target else "", collect_run_uuid, command_results, fatal_error=message)
        repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("OPTICAL_REFRESH_FAILED", _detail(device, collect_run_uuid, error=message, raw_log_path=relative_raw_log_path))
        return OpticalRefreshResult(False, str(device.device_uuid), collect_run_uuid, str(raw_log_file), 0, 0, message, command_results)
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass


def _run_command(connection, command: str, device: Device, collect_run_uuid: str) -> CommandResult:
    started_at = _now()
    reason = command_guard.command_reject_reason(command, "optical_refresh")
    if reason:
        command_guard.log_command_rejected(command, "optical_refresh", reason)
        return CommandResult(command=command, success=False, error_message=reason, started_at=started_at, ended_at=_now())
    try:
        output = safe_send_command(connection, command, read_timeout=120, strip_prompt=False, strip_command=False, use_timing=True)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        app_logger.log_error("OPTICAL_REFRESH_COMMAND_FAILED", _detail(device, collect_run_uuid, command=command, error=message))
        return CommandResult(command=command, success=False, error_message=message, started_at=started_at, ended_at=_now())
    app_logger.log_info("OPTICAL_REFRESH_COMMAND_SUCCESS", _detail(device, collect_run_uuid, command=command))
    return CommandResult(command=command, success=True, output=clean_h3c_device_text(output), started_at=started_at, ended_at=_now())


def _parse_and_write(
    repository: DeviceFactRepository,
    device: Device,
    collect_run_uuid: str,
    raw_log_path: str,
    outputs: dict[str, str],
) -> dict[str, object]:
    collected_at = _now()
    metadata = {"collected_at": collected_at, "updated_at": collected_at, "collect_run_uuid": collect_run_uuid, "raw_log_path": raw_log_path}
    parse_errors: list[str] = []
    interfaces: list[dict[str, object | None]] = []
    modules: list[dict[str, object | None]] = []
    try:
        interfaces = [{**item, **metadata} for item in parse_interfaces(outputs.get("display interface", ""))]
        repository.replace_device_interfaces(str(device.device_uuid), interfaces)
    except Exception as exc:
        parse_errors.append(f"interfaces parse failed: {sanitize_sensitive_text(str(exc), device)}")

    try:
        diagnostics = parse_transceiver_diagnosis(outputs.get("display transceiver diagnosis interface", ""))
        modules = merge_existing_optical_modules(
            repository.list_optical_modules(str(device.device_uuid)),
            diagnostics,
            interfaces,
            metadata,
        )
        repository.replace_optical_modules(str(device.device_uuid), modules)
    except Exception as exc:
        parse_errors.append(f"optical parse failed: {sanitize_sensitive_text(str(exc), device)}")

    return {"interfaces": len(interfaces), "optical_modules": len(modules), "parse_errors": parse_errors}


def merge_existing_optical_modules(
    existing: list[dict[str, object | None]],
    diagnostics: list[dict[str, object | None]],
    interfaces: list[dict[str, object | None]],
    metadata: dict[str, object | None],
) -> list[dict[str, object | None]]:
    by_interface = {str(item.get("interface_name") or ""): dict(item) for item in existing if item.get("interface_name")}
    interfaces_by_name = {str(item.get("interface_name") or ""): item for item in interfaces}
    for diagnostic in diagnostics:
        interface_name = str(diagnostic.get("interface_name") or "")
        if not interface_name:
            continue
        merged = dict(by_interface.get(interface_name, {"interface_name": interface_name}))
        preserved = {field: merged.get(field) for field in BASE_OPTICAL_FIELDS if merged.get(field)}
        merged.update({key: value for key, value in diagnostic.items() if value is not None})
        merged.update(preserved)
        merged.update(metadata)
        by_interface[interface_name] = merged
    return list(by_interface.values())


def _write_raw_files(
    raw_log_file: Path,
    commands_file: Path,
    device: Device,
    protocol: str,
    collect_run_uuid: str,
    command_results: list[CommandResult],
    fatal_error: str | None = None,
) -> None:
    lines = [
        f"Collect Type: optical_refresh",
        f"Collect Time: {_now()}",
        f"Collect Run UUID: {collect_run_uuid}",
        f"Device Name: {device.name}",
        f"Device IP: {device.ip_address}",
        f"Protocol: {protocol}",
        "",
    ]
    for result in command_results:
        lines.extend(
            [
                f"===== COMMAND: {result.command} =====",
                f"Success: {result.success}",
                f"Started At: {result.started_at or ''}",
                f"Ended At: {result.ended_at or ''}",
                f"Error: {result.error_message or ''}",
                result.output or "",
                "",
            ]
        )
    if fatal_error:
        lines.extend(["===== FATAL ERROR =====", fatal_error, ""])
    lines.extend([f"Disconnected At: {_now()}", ""])
    raw_log_file.write_text("\n".join(lines), encoding="utf-8")
    with commands_file.open("w", encoding="utf-8") as file:
        for result in command_results:
            file.write(
                json.dumps(
                    {
                        "command": result.command,
                        "success": result.success,
                        "error_message": result.error_message,
                        "started_at": result.started_at,
                        "ended_at": result.ended_at,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _command_error_summary(command_results: list[CommandResult]) -> str:
    return "; ".join(f"{item.command}: {item.error_message}" for item in command_results if not item.success)


def _detail(
    device: Device,
    collect_run_uuid: str,
    command: str = "",
    error: str = "",
    raw_log_path: str = "",
    interface_count: int | None = None,
    optical_count: int | None = None,
) -> str:
    parts = [f"device={device.name}", f"ip={device.ip_address}", f"collect_run_uuid={collect_run_uuid}"]
    if command:
        parts.append(f"command={command}")
    if raw_log_path:
        parts.append(f"raw_log_path={raw_log_path}")
    if interface_count is not None:
        parts.append(f"interface_count={interface_count}")
    if optical_count is not None:
        parts.append(f"optical_count={optical_count}")
    if error:
        parts.append(f"error={error}")
    return ", ".join(parts)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
