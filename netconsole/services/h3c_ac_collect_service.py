from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.parsers.h3c.ac.fit_ap_optical_parser import parse_fit_ap_optical
from netconsole.parsers.h3c.ac.system_usage_parser import parse_cpu_usage, parse_memory
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list, parse_wlan_ap_summary
from netconsole.parsers.h3c.ac.wlan_ap_radio_parser import parse_wlan_ap_radios
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services import netmiko_connection
from netconsole.services.h3c_collect_service import CommandResult
from netconsole.services.neighbor_matcher import find_neighbor_rx_power, match_neighbor_device
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, sanitize_sensitive_text


RESOURCE_COMMANDS = (
    "display wlan ap all",
    "display wlan ap all address",
    "display wlan ap all radio",
    "display cpu-usage",
    "display memory",
    "display version",
    "display device",
    "display device manuinfo",
)

ENABLE_FIT_AP_CONSOLE_COMMANDS = (
    "system-view",
    "probe",
    "wlan ap-execute all exec-console enable",
    "return",
    "quit",
)

FIT_AP_OPTICAL_COMMANDS = (
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
)


@dataclass(frozen=True)
class AcResourceCollectResult:
    success: bool
    ac_device_uuid: str
    collect_run_uuid: str
    raw_log_path: str
    summary_updated: bool
    fit_ap_resources_updated: int
    error_message: str | None
    command_results: list[CommandResult] = field(default_factory=list)


@dataclass(frozen=True)
class FitApOpticalCollectResult:
    success: bool
    partial_success: bool
    ac_device_uuid: str
    collect_run_uuid: str
    optical_rows_updated: int
    failed_aps: int
    error_message: str | None


def collect_h3c_ac_resources(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
) -> AcResourceCollectResult:
    paths = paths or PathResolver()
    repository = repository or AcRepository(Database(paths.site_db_path(site_name)))
    fact_repository = DeviceFactRepository(repository.database)
    ac_device.ensure_device_uuid()
    collect_run_uuid = str(uuid4())
    started_at = _now()
    run_dir = paths.ensure_site_dirs(site_name) / "raw" / "ac" / collect_run_uuid
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_log_file = run_dir / f"{ac_device.device_uuid}.log"
    commands_file = run_dir / f"{ac_device.device_uuid}_commands.jsonl"
    relative_raw_log_path = f"raw/ac/{collect_run_uuid}/{ac_device.device_uuid}.log"

    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "ac_resources",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"raw/ac/{collect_run_uuid}",
            "created_at": started_at,
        }
    )
    app_logger.log_info("AC_COLLECT_STARTED", _detail(ac_device, collect_run_uuid))
    command_results: list[CommandResult] = []
    target = choose_connection_target(ac_device)
    if target is None:
        message = "未启用连接方式"
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, str(raw_log_file), False, 0, message, command_results)

    connection = None
    try:
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        command_results.append(_run_command(connection, "screen-length disable", ac_device, collect_run_uuid))
        outputs: dict[str, str] = {}
        for command in RESOURCE_COMMANDS:
            result = _run_command(connection, command, ac_device, collect_run_uuid)
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results)
        summary, resources = parse_ac_resource_outputs(outputs, str(ac_device.device_uuid), collect_run_uuid, relative_raw_log_path)
        summary_updated = any(value is not None for key, value in summary.items() if key != "ac_device_uuid")
        if summary_updated:
            repository.upsert_ac_ap_summary(summary)
        repository.replace_fit_ap_resources(str(ac_device.device_uuid), resources)
        status = "success" if summary_updated or resources else "failed"
        error_message = _command_error_summary(command_results)
        fact_repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        if status == "success":
            app_logger.log_info("FIT_AP_RESOURCE_UPDATED", _detail(ac_device, collect_run_uuid, count=len(resources)))
            app_logger.log_info("AC_COLLECT_SUCCESS", _detail(ac_device, collect_run_uuid))
        else:
            app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no data parsed"))
        return AcResourceCollectResult(status == "success", str(ac_device.device_uuid), collect_run_uuid, str(raw_log_file), summary_updated, len(resources), error_message or None, command_results)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, str(raw_log_file), False, 0, message, command_results)
    finally:
        if connection is not None:
            _disconnect(connection)


def collect_h3c_fit_ap_optical(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    max_workers: int = 5,
) -> FitApOpticalCollectResult:
    paths = paths or PathResolver()
    repository = repository or AcRepository(Database(paths.site_db_path(site_name)))
    fact_repository = DeviceFactRepository(repository.database)
    ac_device.ensure_device_uuid()
    collect_run_uuid = str(uuid4())
    started_at = _now()
    run_dir = paths.ensure_site_dirs(site_name) / "raw" / "ac" / collect_run_uuid
    fit_ap_dir = run_dir / "fit_ap"
    fit_ap_dir.mkdir(parents=True, exist_ok=True)
    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "fit_ap_optical",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"raw/ac/{collect_run_uuid}",
            "created_at": started_at,
        }
    )
    app_logger.log_info("FIT_AP_OPTICAL_STARTED", _detail(ac_device, collect_run_uuid))
    try:
        enable_results = _enable_fit_ap_console(ac_device, collect_run_uuid)
        _write_raw_files(run_dir / f"{ac_device.device_uuid}.log", run_dir / f"{ac_device.device_uuid}_commands.jsonl", ac_device, collect_run_uuid, enable_results)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        app_logger.log_error("FIT_AP_OPTICAL_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        return FitApOpticalCollectResult(False, False, str(ac_device.device_uuid), collect_run_uuid, 0, 0, message)

    resources = [row for row in repository.list_fit_ap_resources_with_metadata(str(ac_device.device_uuid)) if row.get("ap_ip")]
    rows: list[dict[str, object | None]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_collect_single_fit_ap_optical, ac_device, row, site_name, collect_run_uuid, fit_ap_dir, paths): row
            for row in resources
        }
        for future in as_completed(futures):
            rows.append(future.result())
    repository.replace_fit_ap_optical(str(ac_device.device_uuid), rows)
    failed = sum(1 for row in rows if row.get("status") != "success")
    status = "failed" if rows and failed == len(rows) else "partial_success" if failed else "success"
    if not rows:
        status = "failed"
    error_message = f"failed_aps={failed}" if failed else None
    fact_repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message)
    if status == "success":
        app_logger.log_info("FIT_AP_OPTICAL_SUCCESS", _detail(ac_device, collect_run_uuid, count=len(rows)))
    elif status == "partial_success":
        app_logger.log_warning("FIT_AP_OPTICAL_PARTIAL_SUCCESS", _detail(ac_device, collect_run_uuid, count=len(rows), error=error_message or ""))
    else:
        app_logger.log_error("FIT_AP_OPTICAL_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no AP resources"))
    return FitApOpticalCollectResult(status != "failed", status == "partial_success", str(ac_device.device_uuid), collect_run_uuid, len(rows), failed, error_message)


def parse_ac_resource_outputs(
    outputs: dict[str, str],
    ac_device_uuid: str,
    collect_run_uuid: str,
    raw_log_path: str,
) -> tuple[dict[str, object | None], list[dict[str, object | None]]]:
    collected_at = _now()
    metadata = {"collected_at": collected_at, "updated_at": collected_at, "collect_run_uuid": collect_run_uuid, "raw_log_path": raw_log_path}
    ap_all = outputs.get("display wlan ap all", "")
    device_facts = parse_device(
        outputs.get("display version", ""),
        outputs.get("display device", ""),
        outputs.get("display device manuinfo", ""),
    )
    summary = {
        "ac_device_uuid": ac_device_uuid,
        **parse_wlan_ap_summary(ap_all),
        **parse_cpu_usage(outputs.get("display cpu-usage", "")),
        **parse_memory(outputs.get("display memory", "")),
        "model": device_facts.get("model"),
        "serial_number": device_facts.get("serial_number"),
        "software_version": device_facts.get("software_version"),
        **metadata,
    }
    ap_rows = parse_wlan_ap_list(ap_all)
    address_rows = parse_wlan_ap_addresses(outputs.get("display wlan ap all address", ""))
    radio_rows = parse_wlan_ap_radios(outputs.get("display wlan ap all radio", ""))
    resources: list[dict[str, object | None]] = []
    for row in ap_rows:
        ap_name = str(row.get("ap_name") or "")
        resources.append(
            {
                "ac_device_uuid": ac_device_uuid,
                **row,
                **address_rows.get(ap_name, {}),
                **radio_rows.get(ap_name, {}),
                **metadata,
            }
        )
    return summary, resources


def _enable_fit_ap_console(ac_device: Device, collect_run_uuid: str) -> list[CommandResult]:
    target = choose_connection_target(ac_device)
    if target is None:
        raise RuntimeError("未启用连接方式")
    connection = None
    results: list[CommandResult] = []
    try:
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        for command in ENABLE_FIT_AP_CONSOLE_COMMANDS:
            results.append(_run_command(connection, command, ac_device, collect_run_uuid, read_timeout=10))
        return results
    finally:
        if connection is not None:
            _disconnect(connection)


def _collect_single_fit_ap_optical(
    ac_device: Device,
    ap_row: dict[str, object | None],
    site_name: str,
    collect_run_uuid: str,
    fit_ap_dir: Path,
    paths: PathResolver,
) -> dict[str, object | None]:
    ap_name = str(ap_row.get("ap_name") or ap_row.get("ap_ip") or "fit_ap")
    ap_ip = str(ap_row.get("ap_ip") or "")
    raw_log_file = fit_ap_dir / f"{_safe_filename(ap_name)}.log"
    commands_file = fit_ap_dir / f"{_safe_filename(ap_name)}_commands.jsonl"
    relative_raw_log_path = f"raw/ac/{collect_run_uuid}/fit_ap/{_safe_filename(ap_name)}.log"
    collected_at = _now()
    base = {
        "ac_device_uuid": ac_device.device_uuid,
        "ap_name": ap_name,
        "ap_ip": ap_ip,
        "site": ap_row.get("site"),
        "collected_at": collected_at,
        "updated_at": collected_at,
        "collect_run_uuid": collect_run_uuid,
        "raw_log_path": relative_raw_log_path,
    }
    temp_device = Device(
        name=ap_name,
        device_uuid=ac_device.device_uuid,
        ip_address=ap_ip,
        ssh_enabled=0,
        telnet_enabled=1,
        telnet_port=23,
        telnet_username="",
        telnet_password="h3capadmin",
    )
    command_results: list[CommandResult] = []
    connection = None
    try:
        target = choose_connection_target(temp_device)
        if target is None:
            raise RuntimeError("AP Telnet target unavailable")
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        outputs: dict[str, str] = {}
        for command in FIT_AP_OPTICAL_COMMANDS:
            result = _run_command(connection, command, temp_device, collect_run_uuid, read_timeout=15)
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        _write_raw_files(raw_log_file, commands_file, temp_device, collect_run_uuid, command_results)
        parsed = parse_fit_ap_optical(
            outputs.get("display lldp neighbor-information list", ""),
            outputs.get("display transceiver diagnosis interface", ""),
        )
        match = match_neighbor_device(
            site_name,
            neighbor_mac=str(parsed.get("neighbor_mac") or ""),
            neighbor_sysname=str(parsed.get("lldp_neighbor") or ""),
            neighbor_interface=str(parsed.get("neighbor_interface") or ""),
            paths=paths,
        )
        if match.device_uuid:
            app_logger.log_info("FIT_AP_NEIGHBOR_MATCHED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=f"matched_by={match.matched_by}"))
        else:
            app_logger.log_warning("FIT_AP_NEIGHBOR_MATCH_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name))
        parsed["neighbor_device_name"] = match.device_name or parsed.get("lldp_neighbor")
        parsed["neighbor_rx_power"] = find_neighbor_rx_power(site_name, match.device_uuid, str(parsed.get("neighbor_interface") or ""), paths=paths)
        success = any(parsed.values()) and all(result.success for result in command_results)
        return {**base, **parsed, "status": "success" if success else "failed", "error_message": None if success else _command_error_summary(command_results) or "no optical data parsed"}
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), temp_device)
        _write_raw_files(raw_log_file, commands_file, temp_device, collect_run_uuid, command_results, fatal_error=message)
        app_logger.log_error("FIT_AP_TELNET_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=message))
        return {
            **base,
            "lldp_neighbor": None,
            "neighbor_interface": None,
            "neighbor_mac": None,
            "neighbor_device_name": None,
            "neighbor_rx_power": None,
            "interface_name": None,
            "temperature": None,
            "tx_power": None,
            "rx_power": None,
            "status": "failed",
            "error_message": message,
        }
    finally:
        if connection is not None:
            _disconnect(connection)


def _run_command(connection, command: str, device: Device, collect_run_uuid: str, read_timeout: int = 30) -> CommandResult:
    try:
        output = connection.send_command(command, read_timeout=read_timeout)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        return CommandResult(command=command, success=False, error_message=message)
    return CommandResult(command=command, success=True, output=str(output or ""))


def _write_raw_files(
    raw_log_file: Path,
    commands_file: Path,
    device: Device,
    collect_run_uuid: str,
    command_results: list[CommandResult],
    fatal_error: str | None = None,
) -> None:
    raw_log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Collect Time: {_now()}",
        f"Collect Run UUID: {collect_run_uuid}",
        f"Device Name: {device.name}",
        f"Device IP: {device.ip_address}",
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


def _command_error_summary(command_results: list[CommandResult]) -> str:
    return "; ".join(f"{item.command}: {item.error_message}" for item in command_results if not item.success)


def _disconnect(connection) -> None:
    try:
        connection.disconnect()
    except Exception:
        pass


def _detail(device: Device, collect_run_uuid: str, command: str = "", error: str = "", count: int | None = None, ap: str = "") -> str:
    parts = [f"device={device.name}", f"ip={device.ip_address}", f"collect_run_uuid={collect_run_uuid}"]
    if ap:
        parts.append(f"ap={ap}")
    if command:
        parts.append(f"command={command}")
    if count is not None:
        parts.append(f"count={count}")
    if error:
        parts.append(f"error={error}")
    return ", ".join(parts)


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)[:120] or "fit_ap"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
