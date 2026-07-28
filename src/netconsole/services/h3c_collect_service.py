from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.adapters.h3c.h3c_parser import H3CParser
from netconsole.models.device import Device
from netconsole.parsers.h3c.boot_loader_parser import parse_boot_loader
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.parsers.h3c.sysname_parser import parse_sysname
from netconsole.parsers.zte.vlan import (
    ZTE_VLAN_PARSER_VERSION,
    ZteVlanParseResult,
    merge_interface_vlan_facts,
    parse_switchvlan_running_config,
    parse_vlan_table,
)
from netconsole.parsers.zte.zxr10 import (
    parse_device_identity as parse_zte_device_identity,
    parse_interfaces as parse_zte_interfaces,
    parse_lldp_brief as parse_zte_lldp_brief,
    parse_lldp_entries as parse_zte_lldp_entries,
    parse_optical_summary as parse_zte_optical_summary,
    merge_lldp_neighbors as merge_zte_lldp_neighbors,
)
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import command_guard
from netconsole.services import netmiko_connection
from netconsole.services.device_command_profile_service import (
    DeviceCommandProfile,
    DeviceCommandProfileError,
    DeviceCommandStep,
    device_cli_output_is_unsupported,
    resolve_device_inventory_profile,
    resolve_step_command_candidates,
)
from netconsole.services.netmiko_connection import (
    build_netmiko_params,
    choose_connection_target,
    safe_send_command,
    safe_send_command_with_paging,
    sanitize_sensitive_text,
)
from netconsole.utils.text_encoding import clean_h3c_device_text


ProgressCallback = Callable[[int, str, str, str], None]
CancelCheck = Callable[[], bool]
CLI_FAILURE_MARKERS = (
    "% unrecognized command",
    "% incomplete command",
    "% ambiguous command",
    "% too many parameters",
    "% wrong parameter",
    "% permission denied",
    "permission denied",
    "error:",
    "命令不完整",
    "无法识别",
    "权限不足",
)


@dataclass(frozen=True)
class CommandResult:
    command: str
    success: bool
    selector: str = ""
    output: str = ""
    error_message: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    raw_output: str = ""
    page_count: int = 0
    output_size: int = 0


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
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> CollectDeviceResult:
    paths = paths or PathResolver()
    repository = repository or DeviceFactRepository(Database(paths.site_db_path(site_name)))
    device.ensure_device_uuid()
    collect_run_uuid = str(uuid4())
    started_at = _now()
    persist_raw_logs = _persist_raw_logs() or str(device.device_vendor).casefold() == "zte"
    run_dir = paths.config_center_raw_logs_root(site_name) / "collect" / collect_run_uuid
    raw_log_file = run_dir / f"{device.device_uuid}.log"
    commands_file = run_dir / f"{device.device_uuid}_commands.jsonl"
    relative_raw_log_path = f"files/config_center/raw_logs/collect/{collect_run_uuid}/{device.device_uuid}.log" if persist_raw_logs else ""
    result_raw_log_path = str(raw_log_file) if persist_raw_logs else ""

    repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "device_details",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"files/config_center/raw_logs/collect/{collect_run_uuid}" if persist_raw_logs else None,
            "created_at": started_at,
        }
    )
    app_logger.log_info("COLLECT_STARTED", _detail(device, collect_run_uuid, raw_log_path=relative_raw_log_path))
    app_logger.log_info("REAL_DEVICE_COLLECT_STARTED", _detail(device, collect_run_uuid, raw_log_path=relative_raw_log_path))

    command_results: list[CommandResult] = []
    connection = None
    try:
        profile = resolve_device_inventory_profile(device, paths=paths)
        command_guard.validate_operation_commands(
            profile.commands,
            context="device_collect",
            operation_id=profile.operation_id,
        )
    except (DeviceCommandProfileError, command_guard.CommandRejected) as exc:
        message = str(exc)
        _emit_progress(progress_callback, 100, "batch_collect.stage.failed", message=message)
        _write_raw_files(
            raw_log_file,
            commands_file,
            device,
            "",
            collect_run_uuid,
            command_results,
            target_protocol="",
            fatal_error=message,
            disconnected_at=_now(),
        )
        _finalize_failed(repository, collect_run_uuid, message)
        app_logger.log_error(
            "COMMAND_PROFILE_REJECTED",
            _detail(device, collect_run_uuid, error=message),
        )
        app_logger.log_error(
            "COLLECT_FAILED",
            _detail(
                device,
                collect_run_uuid,
                error=message,
                raw_log_path=relative_raw_log_path,
            ),
        )
        app_logger.log_error(
            "REAL_DEVICE_COLLECT_FAILED",
            _detail(
                device,
                collect_run_uuid,
                error=message,
                raw_log_path=relative_raw_log_path,
            ),
        )
        return CollectDeviceResult(
            False,
            str(device.device_uuid),
            collect_run_uuid,
            result_raw_log_path,
            False,
            0,
            0,
            0,
            message,
            command_results,
        )
    app_logger.log_info(
        "COMMAND_PROFILE_RESOLVED",
        _detail(
            device,
            collect_run_uuid,
            metadata=(
                f"operation_id={profile.operation_id}, profile_id={profile.profile_id}, "
                f"compatibility={profile.compatibility}"
            ),
        ),
    )
    target = choose_connection_target(device)
    if target is None:
        message = "未启用连接方式"
        _emit_progress(progress_callback, 100, "batch_collect.stage.failed", message=message)
        _finalize_failed(repository, collect_run_uuid, message)
        app_logger.log_error("COLLECT_FAILED", _detail(device, collect_run_uuid, error=message, raw_log_path=relative_raw_log_path))
        _write_raw_files(raw_log_file, commands_file, device, "", collect_run_uuid, command_results, target_protocol="", disconnected_at=_now())
        return CollectDeviceResult(False, str(device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, 0, 0, message, command_results)

    try:
        _emit_progress(progress_callback, 5, "batch_collect.stage.connecting")
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        _emit_progress(progress_callback, 10, "batch_collect.stage.login_success")
        outputs: dict[str, str] = {}
        collect_steps = profile.steps
        if (
            profile.steps
            and profile.steps[0].step_id == "terminal.pagination.disable"
        ):
            pagination_step = profile.steps[0]
            _emit_progress(
                progress_callback,
                15,
                "batch_collect.stage.init_terminal",
                pagination_step.command,
            )
            screen_result = _run_step_candidates(
                connection,
                pagination_step,
                profile,
                device,
                collect_run_uuid,
                target.encoding,
                cancel_check=cancel_check,
            )
            command_results.append(screen_result)
            collect_steps = profile.steps[1:]
        total_commands = len(collect_steps)
        for index, step in enumerate(collect_steps, start=1):
            command = step.command
            percent = 20 + int(index / total_commands * 60)
            _emit_progress(progress_callback, percent, f"batch_collect.stage.collecting_command|{index}|{total_commands}", command)
            result = _run_step_candidates(
                connection,
                step,
                profile,
                device,
                collect_run_uuid,
                target.encoding,
                cancel_check=cancel_check,
            )
            command_results.append(result)
            if (
                str(device.device_vendor or "").strip().casefold() == "zte"
                and not result.success
                and step.selector
                in {
                    "inventory.version",
                    "inventory.interface_brief",
                    "inventory.optical_brief",
                }
            ):
                raise ValueError(result.error_message or "ZTE_COMMAND_FAILED")
            if result.success:
                outputs[step.selector] = result.output
                if (
                    str(device.device_vendor or "").strip().casefold() == "zte"
                    and step.selector == "inventory.version"
                    and parse_zte_device_identity(result.output).status != "OK"
                ):
                    raise ValueError("ZTE_DEVICE_NOT_RECOGNIZED")
        _write_raw_files(raw_log_file, commands_file, device, target.protocol, collect_run_uuid, command_results, target_protocol=target.protocol)
        write_result = _parse_and_write(repository, device, collect_run_uuid, relative_raw_log_path, outputs, progress_callback=progress_callback)
        if str(device.device_vendor or "").strip().casefold() == "zte":
            _write_zte_vlan_artifacts(
                run_dir,
                command_results,
                write_result.get("zte_vlan_manifest"),
            )
        command_failed = any(not result.success for result in command_results)
        status = "partial_success" if command_failed or write_result["parse_errors"] else "success"
        if not any((write_result["facts"], write_result["interfaces"], write_result["optical_modules"], write_result["lldp_neighbors"])):
            status = "failed"
        error_message = "; ".join(write_result["parse_errors"]) or _command_error_summary(command_results)
        repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        event = "COLLECT_SUCCESS" if status == "success" else "COLLECT_PARTIAL_SUCCESS" if status == "partial_success" else "COLLECT_FAILED"
        (app_logger.log_info if status != "failed" else app_logger.log_error)(event, _detail(device, collect_run_uuid, error=error_message or "", raw_log_path=relative_raw_log_path))
        if status != "failed":
            app_logger.log_info("REAL_DEVICE_COLLECT_SUCCESS", _detail(device, collect_run_uuid, error=error_message or "", raw_log_path=relative_raw_log_path))
        else:
            app_logger.log_error("REAL_DEVICE_COLLECT_FAILED", _detail(device, collect_run_uuid, error=error_message or "", raw_log_path=relative_raw_log_path))
        _emit_progress(
            progress_callback,
            100,
            "batch_collect.stage.completed" if status != "failed" else "batch_collect.stage.failed",
            message=error_message or "",
        )
        return CollectDeviceResult(
            status != "failed",
            str(device.device_uuid),
            collect_run_uuid,
            result_raw_log_path,
            bool(write_result["facts"]),
            int(write_result["interfaces"]),
            int(write_result["optical_modules"]),
            int(write_result["lldp_neighbors"]),
            error_message or None,
            command_results,
        )
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        _emit_progress(progress_callback, 100, "batch_collect.stage.failed", message=message)
        _write_raw_files(raw_log_file, commands_file, device, target.protocol, collect_run_uuid, command_results, target_protocol=target.protocol, fatal_error=message, disconnected_at=_now())
        _finalize_failed(repository, collect_run_uuid, message)
        app_logger.log_error("COLLECT_FAILED", _detail(device, collect_run_uuid, error=message, raw_log_path=relative_raw_log_path))
        app_logger.log_error("REAL_DEVICE_COLLECT_FAILED", _detail(device, collect_run_uuid, error=message, raw_log_path=relative_raw_log_path))
        return CollectDeviceResult(False, str(device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, 0, 0, message, command_results)
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass


def _run_command(
    connection,
    step: DeviceCommandStep,
    profile: DeviceCommandProfile,
    device: Device,
    collect_run_uuid: str,
    *,
    command_override: str = "",
    encoding: str = "gb2312",
    cancel_check: CancelCheck | None = None,
) -> CommandResult:
    command = command_override or step.command
    started_at = _now()
    reason = command_guard.command_reject_reason(command, profile.operation_id)
    if reason:
        command_guard.log_command_rejected(command, profile.operation_id, reason)
        return CommandResult(
            command=command,
            success=False,
            selector=step.selector,
            error_message=reason,
            started_at=started_at,
            ended_at=_now(),
        )
    app_logger.log_info("COMMAND_ALLOWED", _detail(device, collect_run_uuid, command=command))
    try:
        if str(device.device_vendor or "").strip().casefold() == "zte":
            paged_output = safe_send_command_with_paging(
                connection,
                command,
                max_pages=256,
                max_output_bytes=4 * 1024 * 1024,
                command_timeout=120,
                idle_timeout=10,
                encoding=encoding,
                cancel_check=cancel_check,
            )
            raw_output = paged_output.raw_output
            output = paged_output.output
        else:
            output = safe_send_command(
                connection,
                command,
                read_timeout=120,
                strip_prompt=False,
                strip_command=False,
                use_timing=True,
                encoding=encoding,
            )
            raw_output = output
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        app_logger.log_error("COLLECT_COMMAND_FAILED", _detail(device, collect_run_uuid, command=command, error=message))
        return CommandResult(
            command=command,
            success=False,
            selector=step.selector,
            error_message=message,
            started_at=started_at,
            ended_at=_now(),
        )
    output_text = clean_h3c_device_text(output)
    cli_failure = (
        "设备返回不支持或无效命令"
        if device_cli_output_is_unsupported(device, output_text)
        else _cli_failure_summary(output_text)
    )
    if cli_failure:
        message = sanitize_sensitive_text(cli_failure, device)
        app_logger.log_error(
            "COLLECT_COMMAND_FAILED",
            _detail(device, collect_run_uuid, command=command, error=message),
        )
        return CommandResult(
            command=command,
            success=False,
            selector=step.selector,
            output=output_text,
            raw_output=raw_output,
            error_message=message,
            started_at=started_at,
            ended_at=_now(),
            page_count=(
                paged_output.page_count
                if str(device.device_vendor or "").strip().casefold() == "zte"
                else 1
            ),
            output_size=len(raw_output.encode("utf-8", errors="replace")),
        )
    app_logger.log_info("COLLECT_COMMAND_SUCCESS", _detail(device, collect_run_uuid, command=command))
    return CommandResult(
        command=command,
        success=True,
        selector=step.selector,
        output=output_text,
        raw_output=raw_output,
        started_at=started_at,
        ended_at=_now(),
        page_count=(
            paged_output.page_count
            if str(device.device_vendor or "").strip().casefold() == "zte"
            else 1
        ),
        output_size=len(raw_output.encode("utf-8", errors="replace")),
    )


def _run_step_candidates(
    connection,
    step: DeviceCommandStep,
    profile: DeviceCommandProfile,
    device: Device,
    collect_run_uuid: str,
    encoding: str,
    *,
    cancel_check: CancelCheck | None = None,
) -> CommandResult:
    last_result: CommandResult | None = None
    for command in resolve_step_command_candidates(device, step):
        result = _run_command(
            connection,
            step,
            profile,
            device,
            collect_run_uuid,
            command_override=command,
            encoding=encoding,
            cancel_check=cancel_check,
        )
        last_result = result
        if result.success and result.output.strip():
            return result
    return last_result or CommandResult(
        command=step.command,
        success=False,
        selector=step.selector,
        error_message="命令没有返回有效内容",
        started_at=_now(),
        ended_at=_now(),
    )


def _emit_progress(
    callback: ProgressCallback | None,
    percent: int,
    stage: str,
    command: str = "",
    message: str = "",
) -> None:
    if callback is None:
        return
    try:
        callback(percent, stage, command, message)
    except Exception:
        pass


def _parse_and_write(
    repository: DeviceFactRepository,
    device: Device,
    collect_run_uuid: str,
    raw_log_path: str,
    outputs: dict[str, str],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    _emit_progress(progress_callback, 85, "batch_collect.stage.parsing")
    collected_at = _now()
    metadata = {"collected_at": collected_at, "updated_at": collected_at, "collect_run_uuid": collect_run_uuid, "raw_log_path": raw_log_path}
    if str(device.device_vendor or "").strip().casefold() == "zte":
        return _parse_zte_and_write(
            repository,
            device,
            collect_run_uuid,
            outputs,
            metadata,
            progress_callback,
        )
    parse_errors: list[str] = []
    facts_updated = False
    interfaces_updated = 0
    optical_modules_updated = 0
    lldp_neighbors_updated = 0
    parser = H3CParser()
    writing_progress_emitted = False

    def emit_writing_progress() -> None:
        nonlocal writing_progress_emitted
        if not writing_progress_emitted:
            writing_progress_emitted = True
            _emit_progress(progress_callback, 95, "batch_collect.stage.saving")

    try:
        facts = parse_device(
            outputs.get("inventory.version", ""),
            outputs.get("inventory.device", ""),
            outputs.get("inventory.manuinfo", ""),
        )
        facts["sysname"] = (
            parse_sysname(outputs.get("inventory.sysname", ""))
            or facts.get("sysname")
            or _prompt_sysname(outputs)
        )
        facts["bootrom_version"] = (
            parse_boot_loader(outputs.get("inventory.boot_loader", ""))
            or facts.get("bootrom_version")
        )
        if any(value for key, value in facts.items() if key != "vendor"):
            emit_writing_progress()
            repository.upsert_device_fact({"device_uuid": device.device_uuid, **facts, **metadata})
            device_repository = DeviceRepository(repository.database)
            if facts.get("sysname"):
                device_repository.update_system_name_by_uuid(str(device.device_uuid or ""), str(facts["sysname"]))
            if facts.get("mac_address"):
                device_repository.update_mac_address_by_uuid(str(device.device_uuid or ""), str(facts["mac_address"]))
            facts_updated = True
            app_logger.log_info("COLLECT_SAVE_FACTS", _detail(device, collect_run_uuid, error=f"sysname={facts.get('sysname') or ''}, raw_log_path={raw_log_path}"))
    except Exception as exc:
        message = f"facts parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    try:
        if "inventory.interfaces" in outputs:
            interfaces = [
                _with_metadata(item, metadata)
                for item in parser.parse_interfaces(outputs.get("inventory.interfaces", ""))
            ]
            emit_writing_progress()
            repository.replace_device_interfaces(str(device.device_uuid), interfaces)
            interfaces_updated = len(interfaces)
            app_logger.log_info("COLLECT_SAVE_INTERFACES", _detail(device, collect_run_uuid, error=f"interface_count={interfaces_updated}, raw_log_path={raw_log_path}"))
    except Exception as exc:
        message = f"interfaces parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    try:
        if any(
            selector in outputs
            for selector in (
                "inventory.transceivers",
                "inventory.transceiver_manuinfo",
                "inventory.transceiver_diagnosis",
            )
        ):
            modules = parser.parse_optical_repository(
                "\n".join(
                    [
                        outputs.get("inventory.transceivers", ""),
                        outputs.get("inventory.transceiver_manuinfo", ""),
                        outputs.get("inventory.transceiver_diagnosis", ""),
                    ]
                )
            )
            modules = [_with_metadata(item, metadata) for item in modules]
            emit_writing_progress()
            repository.replace_optical_modules(str(device.device_uuid), modules)
            optical_modules_updated = len(modules)
            app_logger.log_info("COLLECT_SAVE_OPTICAL", _detail(device, collect_run_uuid, error=f"optical_count={optical_modules_updated}, raw_log_path={raw_log_path}"))
    except Exception as exc:
        message = f"transceiver parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    try:
        if "inventory.lldp_list" in outputs or "inventory.lldp_verbose" in outputs:
            neighbors = parser.parse_lldp(
                outputs.get("inventory.lldp_list", ""),
                outputs.get("inventory.lldp_verbose", ""),
            )
            neighbors = [_with_metadata(item, metadata) for item in neighbors]
            emit_writing_progress()
            repository.replace_lldp_neighbors(str(device.device_uuid), neighbors)
            lldp_neighbors_updated = len(neighbors)
            app_logger.log_info("COLLECT_SAVE_LLDP", _detail(device, collect_run_uuid, error=f"lldp_count={lldp_neighbors_updated}, raw_log_path={raw_log_path}"))
    except Exception as exc:
        message = f"lldp parse failed: {sanitize_sensitive_text(str(exc), device)}"
        parse_errors.append(message)
        app_logger.log_error("COLLECT_PARSE_FAILED", _detail(device, collect_run_uuid, error=message))
    emit_writing_progress()
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
    disconnected_at: str | None = None,
) -> None:
    if not _persist_raw_logs() and str(device.device_vendor).casefold() != "zte":
        return
    raw_log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Collect Time: {_now()}",
        f"Collect Run UUID: {collect_run_uuid}",
        f"Device Name: {device.name}",
        f"Primary Address: {device.primary_address}",
        f"Protocol: {protocol or target_protocol}",
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
                result.raw_output or result.output or "",
                "",
            ]
        )
    if fatal_error:
        lines.extend(["===== FATAL ERROR =====", fatal_error, ""])
    lines.extend([f"Disconnected At: {disconnected_at or _now()}", ""])
    raw_log_file.write_text("\n".join(lines), encoding="utf-8")
    with commands_file.open("w", encoding="utf-8") as file:
        for result in command_results:
            file.write(
                json.dumps(
                    {
                        "command": result.command,
                        "selector": result.selector,
                        "success": result.success,
                        "error_message": result.error_message,
                        "started_at": result.started_at,
                        "ended_at": result.ended_at,
                        "page_count": result.page_count,
                        "output_size": result.output_size,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _persist_raw_logs() -> bool:
    return str(os.environ.get("NETCONSOLE_PERSIST_RAW_LOGS") or "").strip().lower() in {"1", "true", "yes", "on"}


def _with_metadata(item: dict[str, object | None], metadata: dict[str, object | None]) -> dict[str, object | None]:
    return {**item, **metadata}


def _command_error_summary(command_results: list[CommandResult]) -> str:
    failures = [f"{item.command}: {item.error_message}" for item in command_results if not item.success]
    return "; ".join(failures)


def _cli_failure_summary(output: str) -> str:
    for line in str(output or "").splitlines():
        normalized = line.strip().casefold()
        if normalized and any(marker in normalized for marker in CLI_FAILURE_MARKERS):
            return line.strip()
    return ""


def _prompt_sysname(outputs: dict[str, str]) -> str | None:
    for output in outputs.values():
        for line in output.splitlines():
            if line.startswith("<") and ">" in line:
                return line[1 : line.index(">")].strip() or None
            zte_prompt = re.fullmatch(
                r"\s*([A-Za-z0-9_.:/()-]{1,128})[>#]\s*", line
            )
            if zte_prompt:
                return zte_prompt.group(1)
    return None


def _parse_zte_and_write(
    repository: DeviceFactRepository,
    device: Device,
    collect_run_uuid: str,
    outputs: dict[str, str],
    metadata: dict[str, object | None],
    progress_callback: ProgressCallback | None,
) -> dict[str, object]:
    version_output = outputs.get("inventory.version", "")
    identity_result = parse_zte_device_identity(version_output)
    interface_result = parse_zte_interfaces(outputs.get("inventory.interface_brief", ""))
    optical_result = parse_zte_optical_summary(outputs.get("inventory.optical_brief", ""))
    parse_errors = [*identity_result.warnings]
    if identity_result.status == "NOT_RECOGNIZED":
        parse_errors.append("ZTE_DEVICE_NOT_RECOGNIZED")
    for label, result in (
        ("ZTE_INTERFACE", interface_result),
        ("ZTE_OPTICAL", optical_result),
    ):
        parse_errors.extend(result.warnings)
        if result.status != "OK":
            parse_errors.append(f"{label}_{result.status}")
    switchvlan_result = (
        parse_switchvlan_running_config(outputs["inventory.switchvlan_config"])
        if "inventory.switchvlan_config" in outputs
        else None
    )
    vlan_table_result = (
        parse_vlan_table(outputs["inventory.vlan_table"])
        if "inventory.vlan_table" in outputs
        else None
    )
    for label, result in (
        ("ZTE_SWITCHVLAN", switchvlan_result),
        ("ZTE_VLAN_TABLE", vlan_table_result),
    ):
        if result is None:
            continue
        parse_errors.extend(result.warnings)
        if result.status not in {"OK", "EMPTY"}:
            parse_errors.append(f"{label}_{result.status}")
    identity = identity_result.value
    hostname = _prompt_sysname(outputs)
    facts = {
        "device_uuid": device.device_uuid,
        "sysname": hostname,
        "model": identity.get("model"),
        "software_version": identity.get("software_version"),
        "vendor": "ZTE",
        "uptime": identity.get("uptime"),
        **metadata,
    }
    _emit_progress(progress_callback, 95, "batch_collect.stage.saving")
    repository.upsert_device_fact(facts)
    device_repository = DeviceRepository(repository.database)
    if hostname:
        device_repository.update_system_name_by_uuid(
            str(device.device_uuid or ""), hostname
        )
    interfaces = [{**item, **metadata} for item in interface_result.value]
    previous_interfaces = repository.list_device_interfaces(
        str(device.device_uuid)
    )
    vlan_merge = merge_interface_vlan_facts(
        interfaces,
        switchvlan_result,
        vlan_table_result,
        previous_interfaces,
    )
    interfaces = vlan_merge.interfaces
    for warning in vlan_merge.warnings:
        parse_errors.append(
            json.dumps(warning, ensure_ascii=False, separators=(",", ":"))
        )
    interfaces_updated = 0
    if interface_result.status == "OK" and interfaces:
        repository.replace_device_interfaces(str(device.device_uuid), interfaces)
        interfaces_updated = len(interfaces)
    optical_modules = [{**item, **metadata} for item in optical_result.value]
    optical_modules_updated = 0
    if optical_result.status == "OK" and optical_modules:
        repository.replace_optical_modules(
            str(device.device_uuid), optical_modules
        )
        optical_modules_updated = len(optical_modules)

    lldp_neighbors_updated = 0
    brief_result = (
        parse_zte_lldp_brief(outputs["inventory.lldp_list"])
        if "inventory.lldp_list" in outputs
        else None
    )
    detail_result = (
        parse_zte_lldp_entries(outputs["inventory.lldp_verbose"])
        if "inventory.lldp_verbose" in outputs
        else None
    )
    for label, result in (
        ("ZTE_LLDP_BRIEF", brief_result),
        ("ZTE_LLDP_ENTRY", detail_result),
    ):
        if result is None:
            continue
        parse_errors.extend(result.warnings)
        if result.status not in {"OK", "NO_NEIGHBOR"}:
            parse_errors.append(f"{label}_{result.status}")

    lldp_snapshot: list[dict[str, object | None]] | None = None
    if brief_result is not None and brief_result.status == "OK":
        detail_rows = (
            detail_result.value
            if detail_result is not None and detail_result.status == "OK"
            else []
        )
        lldp_snapshot = merge_zte_lldp_neighbors(
            brief_result.value,
            detail_rows,
        )
    elif detail_result is not None and detail_result.status == "OK":
        lldp_snapshot = detail_result.value
    elif any(
        result is not None and result.status == "NO_NEIGHBOR"
        for result in (brief_result, detail_result)
    ):
        lldp_snapshot = []

    if lldp_snapshot is not None:
        lldp_rows = [{**item, **metadata} for item in lldp_snapshot]
        repository.replace_lldp_neighbors(
            str(device.device_uuid),
            lldp_rows,
            preserve_existing=False,
        )
        lldp_neighbors_updated = len(lldp_rows)
    app_logger.log_info(
        "COLLECT_ZTE_FIXTURE_PARSE",
        _detail(
            device,
            collect_run_uuid,
            metadata=(
                f"facts_updated=True, interfaces_updated={interfaces_updated}, "
                f"optical_modules_updated={optical_modules_updated}, "
                f"lldp_neighbors_updated={lldp_neighbors_updated}, "
                f"vlan_conflicts={vlan_merge.stats['conflict_count']}, "
                f"vlan_inherited={vlan_merge.stats['inherited_count']}, "
                f"lldp_snapshot={'replaced' if lldp_snapshot is not None else 'preserved'}"
            ),
        ),
    )
    return {
        "facts": True,
        "interfaces": interfaces_updated,
        "optical_modules": optical_modules_updated,
        "lldp_neighbors": lldp_neighbors_updated,
        "parse_errors": parse_errors,
        "zte_vlan_manifest": {
            "parser_version": ZTE_VLAN_PARSER_VERSION,
            "collected_at": str(metadata.get("collected_at") or ""),
            "switchvlan": _zte_vlan_parse_manifest(
                switchvlan_result,
                pvid_field="pvid",
            ),
            "vlan_table": _zte_vlan_parse_manifest(
                vlan_table_result,
                pvid_field="pvid_ports",
            ),
            "parsed_interface_count": interfaces_updated,
            "pvid_count": sum(
                1 for item in interfaces if item.get("pvid") not in (None, "")
            ),
            "warning_count": len(vlan_merge.warnings),
            "conflict_count": vlan_merge.stats["conflict_count"],
            "merge_stats": vlan_merge.stats,
        },
    }


def _zte_vlan_parse_manifest(
    result: ZteVlanParseResult[list[dict[str, object | None]]] | None,
    *,
    pvid_field: str,
) -> dict[str, object]:
    if result is None:
        return {
            "parse_status": "MISSING",
            "parsed_record_count": 0,
            "pvid_count": 0,
            "warning_count": 0,
        }
    if pvid_field == "pvid_ports":
        pvid_count = sum(
            len(item.get("pvid_ports") or [])
            for item in result.value
            if isinstance(item.get("pvid_ports"), list)
        )
    else:
        pvid_count = sum(
            1 for item in result.value if item.get(pvid_field) not in (None, "")
        )
    return {
        "parse_status": result.status,
        "parsed_record_count": len(result.value),
        "pvid_count": pvid_count,
        "warning_count": len(result.warnings),
    }


def _write_zte_vlan_artifacts(
    run_dir: Path,
    command_results: list[CommandResult],
    parse_manifest: object,
) -> None:
    command_map = {
        "inventory.switchvlan_config": (
            "switchvlan-config.txt",
            "switchvlan",
        ),
        "inventory.vlan_table": ("vlan-table.txt", "vlan_table"),
    }
    result_by_selector = {
        result.selector: result
        for result in command_results
        if result.selector in command_map
    }
    if not result_by_selector:
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    parsed = dict(parse_manifest) if isinstance(parse_manifest, dict) else {}
    commands: list[dict[str, object]] = []
    for selector, (filename, parse_key) in command_map.items():
        result = result_by_selector.get(selector)
        if result is None:
            continue
        (run_dir / filename).write_text(
            result.raw_output or result.output or "",
            encoding="utf-8",
        )
        parse_details = parsed.get(parse_key)
        commands.append(
            {
                "command": result.command,
                "selector": selector,
                "artifact": filename,
                "success": result.success,
                "parser_version": parsed.get(
                    "parser_version", ZTE_VLAN_PARSER_VERSION
                ),
                "parse_status": (
                    parse_details.get("parse_status")
                    if isinstance(parse_details, dict)
                    else "MISSING"
                ),
                "page_count": result.page_count,
                "output_size": result.output_size,
                "parsed_interface_count": (
                    parse_details.get("parsed_record_count", 0)
                    if isinstance(parse_details, dict)
                    else 0
                ),
                "pvid_count": (
                    parse_details.get("pvid_count", 0)
                    if isinstance(parse_details, dict)
                    else 0
                ),
                "warning_count": (
                    parse_details.get("warning_count", 0)
                    if isinstance(parse_details, dict)
                    else 0
                ),
                "conflict_count": int(parsed.get("conflict_count") or 0),
                "collected_at": parsed.get("collected_at") or "",
            }
        )
    manifest = {**parsed, "commands": commands}
    (run_dir / "zte-vlan-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _finalize_failed(repository: DeviceFactRepository, collect_run_uuid: str, message: str) -> None:
    repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)


def _detail(
    device: Device,
    collect_run_uuid: str,
    command: str = "",
    error: str = "",
    raw_log_path: str = "",
    metadata: str = "",
) -> str:
    parts = [f"device={device.name}", f"primary_address={device.primary_address}", f"collect_run_uuid={collect_run_uuid}"]
    if command:
        parts.append(f"command={command}")
    if error:
        parts.append(f"error={error}")
    if raw_log_path:
        parts.append(f"raw_log_path={raw_log_path}")
    if metadata:
        parts.append(f"metadata={metadata}")
    return ", ".join(parts)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
