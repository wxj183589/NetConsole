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
from netconsole.parsers.h3c.boot_loader_parser import parse_boot_loader
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.parsers.h3c.interface_parser import parse_interfaces
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.sysname_parser import parse_sysname
from netconsole.parsers.h3c.transceiver_parser import merge_transceiver_data, parse_transceiver_diagnosis, parse_transceivers
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services import netmiko_connection
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, sanitize_sensitive_text


COLLECT_COMMANDS = (
    "display current-configuration | in sysname",
    "display version",
    "display device",
    "display device manuinfo",
    "display boot-loader",
    "display interface",
    "display transceiver interface",
    "display transceiver diagnosis interface",
    "display lldp neighbor-information list",
    "display lldp neighbor-information verbose",
)


@dataclass(frozen=True)
class CommandResult:
    command: str
    success: bool
    output: str = ""
    error_message: str | None = None


@dataclass(frozen=True)
class CollectDeviceResult:
    success: bool
    device_uuid: str
    collect_run_uuid: str
    raw_log_path: str
    facts_updated: bool
    interfaces_updated: int
    optical_modules_updated: int
    lldp_neighbors_updated: int
    error_message: str | None
    command_results: list[CommandResult] = field(default_factory=list)


def collect_h3c_device_details(
    device: Device,
    site_name: str,
    repository: DeviceFactRepository | None = None,
    paths: PathResolver | None = None,
) -> CollectDeviceResult:
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
            "collect_type": "device_details",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"raw/collect/{collect_run_uuid}",
            "created_at": started_at,
        }
    )
    app_logger.log_info("COLLECT_STARTED", _detail(device, collect_run_uuid))

    command_results: list[CommandResult] = []
    connection = None
    target = choose_connection_target(device)
    if target is None:
        message = "未启用连接方式"
        _finalize_failed(repository, collect_run_uuid, message)
        app_logger.log_error("COLLECT_FAILED", _detail(device, collect_run_uuid, error=message))
        _write_raw_files(raw_log_file, commands_file, device, "", collect_run_uuid, command_results, target_protocol="")
        return CollectDeviceResult(False, str(device.device_uuid), collect_run_uuid, str(raw_log_file), False, 0, 0, 0, message, command_results)

    try:
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        screen_result = _run_command(connection, "screen-length disable", device, collect_run_uuid)
        command_results.append(screen_result)
        outputs: dict[str, str] = {}
        for command in COLLECT_COMMANDS:
            result = _run_command(connection, command, device, collect_run_uuid)
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        _write_raw_files(raw_log_file, commands_file, device, target.protocol, collect_run_uuid, command_results, target_protocol=target.protocol)
        write_result = _parse_and_write(repository, device, collect_run_uuid, relative_raw_log_path, outputs)
        command_failed = any(not result.success for result in command_results)
        status = "partial_success" if command_failed or write_result["parse_errors"] else "success"
        if not any((write_result["facts"], write_result["interfaces"], write_result["optical_modules"], write_result["lldp_neighbors"])):
            status = "failed"
        error_message = "; ".join(write_result["parse_errors"]) or _command_error_summary(command_results)
        repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        event = "COLLECT_SUCCESS" if status == "success" else "COLLECT_PARTIAL_SUCCESS" if status == "partial_success" else "COLLECT_FAILED"
        (app_logger.log_info if status != "failed" else app_logger.log_error)(event, _detail(device, collect_run_uuid, error=error_message or ""))
        return CollectDeviceResult(
            status != "failed",
            str(device.device_uuid),
            collect_run_uuid,
            str(raw_log_file),
            bool(write_result["facts"]),
            int(write_result["interfaces"]),
            int(write_result["optical_modules"]),
            int(write_result["lldp_neighbors"]),
            error_message or None,
            command_results,
        )
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        _write_raw_files(raw_log_file, commands_file, device, target.protocol, collect_run_uuid, command_results, target_protocol=target.protocol, fatal_error=message)
        _finalize_failed(repository, collect_run_uuid, message)
        app_logger.log_error("COLLECT_FAILED", _detail(device, collect_run_uuid, error=message))
        return CollectDeviceResult(False, str(device.device_uuid), collect_run_uuid, str(raw_log_file), False, 0, 0, 0, message, command_results)
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass


def _run_command(connection, command: str, device: Device, collect_run_uuid: str) -> CommandResult:
    try:
        output = connection.send_command(command, read_timeout=30)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        app_logger.log_error("COLLECT_COMMAND_FAILED", _detail(device, collect_run_uuid, command=command, error=message))
        return CommandResult(command=command, success=False, error_message=message)
    app_logger.log_info("COLLECT_COMMAND_SUCCESS", _detail(device, collect_run_uuid, command=command))
    return CommandResult(command=command, success=True, output=str(output or ""))


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
    facts_updated = False
    interfaces_updated = 0
    optical_modules_updated = 0
    lldp_neighbors_updated = 0
    try:
        facts = parse_device(outputs.get("display version", ""), outputs.get("display device", ""), outputs.get("display device manuinfo", ""))
        facts["sysname"] = (
            parse_sysname(outputs.get("display current-configuration | in sysname", ""))
            or facts.get("sysname")
            or _prompt_sysname(outputs)
        )
        facts["bootrom_version"] = parse_boot_loader(outputs.get("display boot-loader", "")) or facts.get("bootrom_version")
        if any(value for key, value in facts.items() if key != "vendor"):
            repository.upsert_device_fact({"device_uuid": device.device_uuid, **facts, **metadata})
            facts_updated = True
    except Exception as exc:
        message = f"facts parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    try:
        if "display interface" in outputs:
            interfaces = [_with_metadata(item, metadata) for item in parse_interfaces(outputs.get("display interface", ""))]
            repository.replace_device_interfaces(str(device.device_uuid), interfaces)
            interfaces_updated = len(interfaces)
    except Exception as exc:
        message = f"interfaces parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    try:
        if "display transceiver interface" in outputs or "display transceiver diagnosis interface" in outputs:
            modules = merge_transceiver_data(
                parse_transceivers(outputs.get("display transceiver interface", "")),
                parse_transceiver_diagnosis(outputs.get("display transceiver diagnosis interface", "")),
            )
            modules = [_with_metadata(item, metadata) for item in modules]
            repository.replace_optical_modules(str(device.device_uuid), modules)
            optical_modules_updated = len(modules)
    except Exception as exc:
        message = f"transceiver parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    try:
        if "display lldp neighbor-information list" in outputs or "display lldp neighbor-information verbose" in outputs:
            neighbors = parse_lldp_neighbors(
                outputs.get("display lldp neighbor-information list", ""),
                outputs.get("display lldp neighbor-information verbose", ""),
            )
            neighbors = [_with_metadata(item, metadata) for item in neighbors]
            repository.replace_lldp_neighbors(str(device.device_uuid), neighbors)
            lldp_neighbors_updated = len(neighbors)
    except Exception as exc:
        message = f"lldp parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    return {
        "facts": facts_updated,
        "interfaces": interfaces_updated,
        "optical_modules": optical_modules_updated,
        "lldp_neighbors": lldp_neighbors_updated,
        "parse_errors": parse_errors,
    }


def _write_raw_files(
    raw_log_file: Path,
    commands_file: Path,
    device: Device,
    protocol: str,
    collect_run_uuid: str,
    command_results: list[CommandResult],
    target_protocol: str,
    fatal_error: str | None = None,
) -> None:
    lines = [
        f"Collect Time: {_now()}",
        f"Collect Run UUID: {collect_run_uuid}",
        f"Device Name: {device.name}",
        f"Device IP: {device.ip_address}",
        f"Protocol: {protocol or target_protocol}",
        "",
    ]
    for result in command_results:
        lines.extend(
            [
                f"===== COMMAND: {result.command} =====",
                f"Success: {result.success}",
                f"Error: {result.error_message or ''}",
                result.output or "",
                "",
            ]
        )
    if fatal_error:
        lines.extend(["===== FATAL ERROR =====", fatal_error, ""])
    raw_log_file.write_text("\n".join(lines), encoding="utf-8")
    with commands_file.open("w", encoding="utf-8") as file:
        for result in command_results:
            file.write(json.dumps({"command": result.command, "success": result.success, "error_message": result.error_message}, ensure_ascii=False) + "\n")


def _with_metadata(item: dict[str, object | None], metadata: dict[str, object | None]) -> dict[str, object | None]:
    return {**item, **metadata}


def _command_error_summary(command_results: list[CommandResult]) -> str:
    failures = [f"{item.command}: {item.error_message}" for item in command_results if not item.success]
    return "; ".join(failures)


def _prompt_sysname(outputs: dict[str, str]) -> str | None:
    for output in outputs.values():
        for line in output.splitlines():
            if line.startswith("<") and ">" in line:
                return line[1 : line.index(">")].strip() or None
    return None


def _finalize_failed(repository: DeviceFactRepository, collect_run_uuid: str, message: str) -> None:
    repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)


def _detail(device: Device, collect_run_uuid: str, command: str = "", error: str = "") -> str:
    parts = [f"device={device.name}", f"ip={device.ip_address}", f"collect_run_uuid={collect_run_uuid}"]
    if command:
        parts.append(f"command={command}")
    if error:
        parts.append(f"error={error}")
    return ", ".join(parts)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
