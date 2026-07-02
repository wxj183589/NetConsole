from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import Device
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.parsers.h3c.ac.fit_ap_optical_parser import parse_fit_ap_optical
from netconsole.parsers.h3c.ac.system_usage_parser import parse_cpu_usage, parse_memory
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list, parse_wlan_ap_summary
from netconsole.parsers.h3c.ac.wlan_ap_radio_parser import parse_wlan_ap_radios
from netconsole.parsers.h3c.ac.wlan_ap_unauthenticated_parser import parse_wlan_ap_unauthenticated_rows, parse_wlan_ap_unauthenticated_summary
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import command_guard
from netconsole.services import netmiko_connection
from netconsole.services.device_web_service import matching_https_port_lines, parse_https_port
from netconsole.services.h3c_collect_service import CommandResult
from netconsole.services.neighbor_matcher import find_neighbor_optical_module, match_ap_from_device_lldp, match_neighbor_device
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, sanitize_sensitive_text
from netconsole.services.offline_ap_ledger import is_fit_ap_offline


FIT_AP_RESOURCE_REQUIRED_COMMANDS = (
    "display wlan ap all",
    "display wlan ap all address",
    "display wlan ap all radio",
)
FIT_AP_RESOURCE_OPTIONAL_COMMANDS = (
    "display wlan ap unauthenticated",
)
FIT_AP_RESOURCE_COMMANDS = FIT_AP_RESOURCE_REQUIRED_COMMANDS

AC_OVERVIEW_COMMANDS = (
    "display cpu-usage",
    "display memory",
    "display version",
    "display device",
    "display device manuinfo",
)
RESOURCE_COMMANDS = (*FIT_AP_RESOURCE_REQUIRED_COMMANDS, *FIT_AP_RESOURCE_OPTIONAL_COMMANDS, *AC_OVERVIEW_COMMANDS)

HTTPS_PORT_COMMANDS = (
    "display ip https",
    "display ip https | include port",
)

ENABLE_FIT_AP_CONSOLE_COMMANDS = (
    "screen-length disable",
    "display wlan ap all address",
    "system-view",
    "probe",
    "wlan ap-execute all exec-console enable",
    "return",
    "quit",
)

FIT_AP_OPTICAL_COMMANDS = (
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
    "display interface brief",
)
BATCH_CONCURRENCY = 50
DEFAULT_FIT_AP_TELNET_CONCURRENCY = 1000
ProgressCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]


class CollectionCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class AcResourceCollectResult:
    success: bool
    ac_device_uuid: str
    collect_run_uuid: str
    raw_log_path: str
    summary_updated: bool
    fit_ap_resources_updated: int
    https_port: int | None
    https_port_collected: bool
    https_port_persisted: bool
    https_port_error: str | None
    error_message: str | None
    command_results: list[CommandResult] = field(default_factory=list)
    unauthenticated_updated: bool = False
    unauthenticated_rows_updated: int = 0
    unauthenticated_error: str | None = None


@dataclass(frozen=True)
class HttpsPortPersistenceResult:
    persisted_port: int | None
    persisted: bool
    error_message: str | None = None


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
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
    refresh_ac_overview: bool = True,
) -> AcResourceCollectResult:
    progress = progress or (lambda _message: None)
    should_cancel = should_cancel or (lambda: False)
    paths = paths or PathResolver()
    repository = repository or AcRepository(Database(paths.site_db_path(site_name)))
    fact_repository = DeviceFactRepository(repository.database)
    ac_device.ensure_device_uuid()
    collect_run_uuid = str(uuid4())
    started_at = _now()
    persist_raw_logs = _persist_raw_logs()
    run_dir = paths.trackside_ap_raw_dir(site_name) / "ac" / collect_run_uuid
    raw_log_file = run_dir / f"{ac_device.device_uuid}.log"
    commands_file = run_dir / f"{ac_device.device_uuid}_commands.jsonl"
    relative_raw_log_path = f"files/rail_transit/trackside_ap/raw/ac/{collect_run_uuid}/{ac_device.device_uuid}.log" if persist_raw_logs else ""
    result_raw_log_path = str(raw_log_file) if persist_raw_logs else ""

    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "ac_resources",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"files/rail_transit/trackside_ap/raw/ac/{collect_run_uuid}" if persist_raw_logs else None,
            "created_at": started_at,
        }
    )
    app_logger.log_info("AC_COLLECT_STARTED", _detail(ac_device, collect_run_uuid))
    app_logger.log_info("REAL_DEVICE_COLLECT_STARTED", _detail(ac_device, collect_run_uuid))
    progress("正在连接AC...")
    command_results: list[CommandResult] = []
    if str(ac_device.device_type or "").upper() != "AC" or str(ac_device.device_vendor or "").upper() != "H3C":
        message = "AC resource collection only supports H3C AC devices"
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)

    target = choose_connection_target(ac_device)
    if target is None:
        message = "未启用连接方式"
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)

    connection = None
    try:
        commands = [*FIT_AP_RESOURCE_REQUIRED_COMMANDS, *FIT_AP_RESOURCE_OPTIONAL_COMMANDS]
        if refresh_ac_overview:
            commands.extend(AC_OVERVIEW_COMMANDS)
        validate_commands = ["screen-length disable", *commands]
        if refresh_ac_overview:
            validate_commands.extend(HTTPS_PORT_COMMANDS)
        command_guard.validate_command_list(validate_commands, "ac_collect")
        _raise_if_cancelled(should_cancel)
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        command_results.append(_run_command(connection, "screen-length disable", ac_device, collect_run_uuid, context="ac_collect"))
        outputs: dict[str, str] = {}
        for command in commands:
            _raise_if_cancelled(should_cancel)
            progress(f"正在执行 {command}...")
            result = _run_command(connection, command, ac_device, collect_run_uuid, context="ac_collect")
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        https_port = None
        if refresh_ac_overview:
            progress("正在采集 HTTPS 端口...")
            https_port, https_results = collect_https_port(connection, ac_device, collect_run_uuid)
            command_results.extend(https_results)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results)
        _raise_if_cancelled(should_cancel)
        progress("正在解析FIT-AP资源...")
        summary, resources = parse_ac_resource_outputs(outputs, str(ac_device.device_uuid), collect_run_uuid, relative_raw_log_path)
        dynamic_summary_updated = _can_update_dynamic_summary(command_results, summary)
        summary_updated = refresh_ac_overview and any(value is not None for key, value in summary.items() if key != "ac_device_uuid")
        progress("正在写入数据库...")
        if summary_updated:
            repository.upsert_ac_ap_summary(summary)
        elif dynamic_summary_updated:
            repository.upsert_ac_ap_dynamic_summary(str(ac_device.device_uuid), _dynamic_summary_payload(summary))
        if dynamic_summary_updated:
            app_logger.log_info(
                "AC_AP_SUMMARY_DYNAMIC_UPDATED",
                _detail(
                    ac_device,
                    collect_run_uuid,
                    error=(
                        f"total={summary.get('total_aps')}, online={summary.get('online_aps')}, "
                        f"offline={summary.get('offline_aps')}"
                    ),
                ),
            )
        persistence = _update_https_port(repository.database, ac_device, collect_run_uuid, https_port) if refresh_ac_overview else HttpsPortPersistenceResult(None, False)
        resource_commands_ok = all(
            result.success
            for result in command_results
            if result.command in FIT_AP_RESOURCE_REQUIRED_COMMANDS
        )
        resources_persisted = bool(resource_commands_ok and resources)
        if resources_persisted:
            repository.replace_fit_ap_resources(str(ac_device.device_uuid), resources)
        unauth_result = next((result for result in command_results if result.command == "display wlan ap unauthenticated"), None)
        unauthenticated_updated = False
        unauthenticated_rows_updated = 0
        unauthenticated_error = None
        if unauth_result and unauth_result.success:
            unauth_summary = parse_wlan_ap_unauthenticated_summary(unauth_result.output)
            unauth_rows = parse_wlan_ap_unauthenticated_rows(unauth_result.output)
            metadata = {
                "collect_run_uuid": collect_run_uuid,
                "raw_log_path": relative_raw_log_path,
                "collected_at": started_at,
                "updated_at": _now(),
            }
            repository.replace_fit_ap_unauthenticated(
                str(ac_device.device_uuid),
                {**unauth_summary, **metadata},
                [{**row, **metadata} for row in unauth_rows],
            )
            unauthenticated_updated = True
            unauthenticated_rows_updated = len(unauth_rows)
            app_logger.log_info("FIT_AP_UNAUTHENTICATED_UPDATED", _detail(ac_device, collect_run_uuid, count=len(unauth_rows)))
        elif unauth_result:
            unauthenticated_error = unauth_result.error_message or "display wlan ap unauthenticated failed"
            app_logger.log_warning("FIT_AP_UNAUTHENTICATED_FAILED", _detail(ac_device, collect_run_uuid, error=unauthenticated_error))
        status = "success" if summary_updated or dynamic_summary_updated or resources_persisted else "failed"
        error_message = _command_error_summary([result for result in command_results if result.command not in FIT_AP_RESOURCE_OPTIONAL_COMMANDS])
        fact_repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        if status == "success":
            app_logger.log_info("FIT_AP_RESOURCE_UPDATED", _detail(ac_device, collect_run_uuid, count=len(resources)))
            app_logger.log_info("AC_COLLECT_SUCCESS", _detail(ac_device, collect_run_uuid))
            app_logger.log_info("REAL_DEVICE_COLLECT_SUCCESS", _detail(ac_device, collect_run_uuid))
        else:
            app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no data parsed"))
            app_logger.log_error("REAL_DEVICE_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no data parsed"))
        progress(f"更新完成：FIT-AP资源 {len(resources) if resources_persisted else 0} 条")
        return AcResourceCollectResult(
            status == "success",
            str(ac_device.device_uuid),
            collect_run_uuid,
            result_raw_log_path,
            summary_updated or dynamic_summary_updated,
            len(resources) if resources_persisted else 0,
            https_port,
            https_port is not None,
            persistence.persisted,
            persistence.error_message,
            error_message or None,
            command_results,
            unauthenticated_updated,
            unauthenticated_rows_updated,
            unauthenticated_error,
        )
    except CollectionCancelled:
        message = "用户已取消更新"
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        app_logger.log_warning("AC_COLLECT_CANCELLED", _detail(ac_device, collect_run_uuid))
        progress("已取消")
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        app_logger.log_error("REAL_DEVICE_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)
    finally:
        if connection is not None:
            _disconnect(connection)


def collect_h3c_fit_ap_optical(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    max_workers: int = DEFAULT_FIT_AP_TELNET_CONCURRENCY,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
    target_ap_uuids: list[str] | None = None,
    target_ap_macs: list[str] | None = None,
    target_ap_names: list[str] | None = None,
    target_stations: list[str] | None = None,
) -> FitApOpticalCollectResult:
    progress = progress or (lambda _message: None)
    should_cancel = should_cancel or (lambda: False)
    paths = paths or PathResolver()
    repository = repository or AcRepository(Database(paths.site_db_path(site_name)))
    fact_repository = DeviceFactRepository(repository.database)
    ac_device.ensure_device_uuid()
    collect_run_uuid = str(uuid4())
    started_at = _now()
    persist_raw_logs = _persist_raw_logs()
    run_dir = paths.trackside_ap_raw_dir(site_name) / "ac" / collect_run_uuid
    fit_ap_dir = run_dir / "fit_ap"
    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "fit_ap_optical",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"files/rail_transit/trackside_ap/raw/ac/{collect_run_uuid}" if persist_raw_logs else None,
            "created_at": started_at,
        }
    )
    app_logger.log_info("FIT_AP_OPTICAL_STARTED", _detail(ac_device, collect_run_uuid))
    progress("\u51c6\u5907\u66f4\u65b0FIT-AP\u5149\u8870...")
    try:
        app_logger.log_info("FIT_AP_OPTICAL_AC_ENABLE_STARTED", _detail(ac_device, collect_run_uuid))
        _raise_if_cancelled(should_cancel)
        progress("\u6b63\u5728\u8fde\u63a5AC\u5e76\u542f\u7528AP\u63a7\u5236\u53f0...")
        enable_results = _enable_fit_ap_console(ac_device, collect_run_uuid)
        _write_raw_files(run_dir / f"{ac_device.device_uuid}.log", run_dir / f"{ac_device.device_uuid}_commands.jsonl", ac_device, collect_run_uuid, enable_results)
        if any(not result.success for result in enable_results):
            raise RuntimeError(_command_error_summary(enable_results) or "AC enable AP console failed")
        app_logger.log_info("FIT_AP_OPTICAL_AC_ENABLE_SUCCESS", _detail(ac_device, collect_run_uuid))
    except CollectionCancelled:
        message = "\u7528\u6237\u5df2\u53d6\u6d88\u66f4\u65b0"
        app_logger.log_warning("FIT_AP_OPTICAL_CANCELLED", _detail(ac_device, collect_run_uuid))
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        progress("\u5df2\u53d6\u6d88")
        return FitApOpticalCollectResult(False, False, str(ac_device.device_uuid), collect_run_uuid, 0, 0, message)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        app_logger.log_error("FIT_AP_OPTICAL_AC_ENABLE_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        app_logger.log_error("FIT_AP_OPTICAL_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        return FitApOpticalCollectResult(False, False, str(ac_device.device_uuid), collect_run_uuid, 0, 0, message)

    progress("\u6b63\u5728\u7b5b\u9009\u5728\u7ebfAP...")
    scoped_refresh = _is_scoped_fit_ap_refresh(target_ap_uuids, target_ap_macs, target_ap_names, target_stations)
    all_resources = repository.list_fit_ap_resources_with_metadata(str(ac_device.device_uuid))
    resources = _filter_fit_ap_optical_targets(
        all_resources,
        target_ap_uuids=target_ap_uuids,
        target_ap_macs=target_ap_macs,
        target_ap_names=target_ap_names,
        target_stations=target_stations,
    )
    resources = [row for row in resources if row.get("ap_ip") and not is_fit_ap_offline(row)]
    rows: list[dict[str, object | None]] = []
    settings = _fit_ap_optical_collect_settings(paths)
    worker_count = max(1, int(max_workers or settings["max_fit_ap_concurrency"] or DEFAULT_FIT_AP_TELNET_CONCURRENCY))
    total = len(resources)
    if scoped_refresh and total == 0:
        fact_repository.update_collect_run_status(collect_run_uuid, "success", error_message=None)
        app_logger.log_info("FIT_AP_OPTICAL_SKIPPED_NO_CONNECTABLE_TARGET", _detail(ac_device, collect_run_uuid))
        progress("\u66f4\u65b0\u5b8c\u6210\uff1a\u6210\u529f 0\uff0c\u5931\u8d25 0\uff0c\u79bb\u7ebf 0")
        return FitApOpticalCollectResult(True, False, str(ac_device.device_uuid), collect_run_uuid, 0, 0, None)
    completed = 0
    progress(f"\u6b63\u5728\u91c7\u96c6 AP\u4fa7\u5149\u8870\uff1a0/{total}")
    try:
        round_summaries: list[dict[str, object]] = []
        first_round_rows = _collect_fit_ap_optical_round(
            ac_device,
            resources,
            site_name,
            collect_run_uuid,
            fit_ap_dir,
            paths,
            worker_count,
            should_cancel,
            lambda done, total_count: progress(f"\u6b63\u5728\u91c7\u96c6 AP\u4fa7\u5149\u8870\uff1a{done}/{total_count}"),
        )
        rows.extend(first_round_rows)
        completed = len(rows)
        round_summaries.append(_fit_ap_optical_round_summary(1, worker_count, first_round_rows))
        retry_targets = _retry_fit_ap_optical_targets(resources, first_round_rows)
        retry_count = int(settings["retry_count"]) if settings["adaptive_retry_enabled"] else 0
        previous_concurrency = worker_count
        for round_index in range(2, retry_count + 2):
            if not retry_targets:
                break
            retry_concurrency = (
                retry_fit_ap_optical_concurrency(
                    previous_concurrency,
                    floor=int(settings["retry_concurrency_floor"]),
                    ratio=float(settings["retry_concurrency_ratio"]),
                )
                if settings["adaptive_concurrency_enabled"]
                else previous_concurrency
            )
            app_logger.log_info("FIT_AP_OPTICAL_RETRY_STARTED", _detail(ac_device, collect_run_uuid, count=len(retry_targets), error=f"round={round_index}, concurrency={retry_concurrency}"))
            retry_rows = _collect_fit_ap_optical_round(
                ac_device,
                retry_targets,
                site_name,
                collect_run_uuid,
                fit_ap_dir,
                paths,
                retry_concurrency,
                should_cancel,
                lambda done, total_count, r=round_index: progress(f"\u6b63\u5728\u91cd\u8bd5 AP\u4fa7\u5149\u8870\uff08第{r}轮\uff09\uff1a{done}/{total_count}"),
            )
            rows.extend(retry_rows)
            round_summaries.append(_fit_ap_optical_round_summary(round_index, retry_concurrency, retry_rows))
            retry_targets = _retry_fit_ap_optical_targets(retry_targets, retry_rows)
            previous_concurrency = retry_concurrency
        app_logger.log_info("FIT_AP_OPTICAL_ADAPTIVE_SUMMARY", f"ac_device_uuid={ac_device.device_uuid}, rounds={round_summaries}")
        progress("\u6b63\u5728\u89e3\u6790\u5149\u6a21\u5757\u6570\u636e...")
        _raise_if_cancelled(should_cancel)
        progress("\u6b63\u5728\u5199\u5165\u6570\u636e\u5e93...")
        existing_rows = repository.list_fit_ap_optical(str(ac_device.device_uuid))
        rows_to_save = _merge_fit_ap_optical_rows(existing_rows, rows)
        successful_rows = [row for row in rows if _is_fit_ap_optical_success_row(row)]
        if successful_rows:
            repository.replace_fit_ap_optical(str(ac_device.device_uuid), rows_to_save)
        else:
            app_logger.log_warning("FIT_AP_OPTICAL_DB_SAVE_SKIPPED", _detail(ac_device, collect_run_uuid, error="no successful AP optical rows; keeping previous data"))
    except CollectionCancelled:
        message = "\u7528\u6237\u5df2\u53d6\u6d88\u66f4\u65b0"
        app_logger.log_warning("FIT_AP_OPTICAL_CANCELLED", _detail(ac_device, collect_run_uuid))
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        progress("\u5df2\u53d6\u6d88")
        return FitApOpticalCollectResult(False, False, str(ac_device.device_uuid), collect_run_uuid, len(rows), 0, message)
    app_logger.log_info("FIT_AP_OPTICAL_DB_SAVED", _detail(ac_device, collect_run_uuid, count=len(rows)))
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
    progress(f"\u66f4\u65b0\u5b8c\u6210\uff1a\u6210\u529f {len(rows) - failed}\uff0c\u5931\u8d25 {failed}\uff0c\u79bb\u7ebf 0")
    return FitApOpticalCollectResult(status != "failed", status == "partial_success", str(ac_device.device_uuid), collect_run_uuid, len(rows), failed, error_message)


def _is_scoped_fit_ap_refresh(*scopes: list[str] | None) -> bool:
    return any(bool(scope) for scope in scopes)


def _fit_ap_optical_collect_settings(paths: PathResolver) -> dict[str, object]:
    defaults = {
        "max_fit_ap_concurrency": DEFAULT_FIT_AP_TELNET_CONCURRENCY,
        "adaptive_concurrency_enabled": True,
        "adaptive_retry_enabled": True,
        "retry_count": 2,
        "retry_concurrency_floor": 100,
        "retry_concurrency_ratio": 0.5,
    }
    try:
        store = SettingsStore(paths)
    except Exception:
        return defaults
    return {
        "max_fit_ap_concurrency": _int_setting(store.get_value("trackside_ap/max_fit_ap_concurrency", defaults["max_fit_ap_concurrency"]), defaults["max_fit_ap_concurrency"], minimum=1),
        "adaptive_concurrency_enabled": bool(store.get_value("trackside_ap/adaptive_concurrency_enabled", defaults["adaptive_concurrency_enabled"])),
        "adaptive_retry_enabled": bool(store.get_value("trackside_ap/adaptive_retry_enabled", defaults["adaptive_retry_enabled"])),
        "retry_count": _int_setting(store.get_value("trackside_ap/retry_count", defaults["retry_count"]), defaults["retry_count"], minimum=0),
        "retry_concurrency_floor": _int_setting(store.get_value("trackside_ap/retry_concurrency_floor", defaults["retry_concurrency_floor"]), defaults["retry_concurrency_floor"], minimum=1),
        "retry_concurrency_ratio": _float_setting(store.get_value("trackside_ap/retry_concurrency_ratio", defaults["retry_concurrency_ratio"]), defaults["retry_concurrency_ratio"], minimum=0.01),
    }


def retry_fit_ap_optical_concurrency(previous_concurrency: int, *, floor: int = 100, ratio: float = 0.5) -> int:
    return max(max(1, int(floor or 1)), int(max(1, previous_concurrency) * max(0.01, float(ratio or 0.01))))


def _int_setting(value: object, default: object, *, minimum: int) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return max(minimum, int(default))


def _float_setting(value: object, default: object, *, minimum: float) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return max(minimum, float(default))


def _filter_fit_ap_optical_targets(
    resources: list[dict[str, object | None]],
    *,
    target_ap_uuids: list[str] | None = None,
    target_ap_macs: list[str] | None = None,
    target_ap_names: list[str] | None = None,
    target_stations: list[str] | None = None,
) -> list[dict[str, object | None]]:
    uuid_set = {str(value or "").strip() for value in target_ap_uuids or [] if str(value or "").strip()}
    mac_set = {_normalize_mac_text(value) for value in target_ap_macs or [] if _normalize_mac_text(value)}
    name_set = {str(value or "").strip().casefold() for value in target_ap_names or [] if str(value or "").strip()}
    station_set = {str(value or "").strip().casefold() for value in target_stations or [] if str(value or "").strip()}
    if not any((uuid_set, mac_set, name_set, station_set)):
        return list(resources)
    result: list[dict[str, object | None]] = []
    for row in resources:
        if uuid_set and str(row.get("ap_uuid") or "").strip() in uuid_set:
            result.append(row)
            continue
        if mac_set and _normalize_mac_text(row.get("ap_mac")) in mac_set:
            result.append(row)
            continue
        if name_set and str(row.get("ap_name") or "").strip().casefold() in name_set:
            result.append(row)
            continue
        row_station = str(row.get("site") or row.get("site_name") or row.get("station") or "").strip().casefold()
        if station_set and row_station in station_set:
            result.append(row)
    return result


def _collect_fit_ap_optical_round(
    ac_device: Device,
    resources: list[dict[str, object | None]],
    site_name: str,
    collect_run_uuid: str,
    fit_ap_dir: Path,
    paths: PathResolver,
    concurrency: int,
    should_cancel: CancelCheck,
    progress_round: Callable[[int, int], None],
) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    total = len(resources)
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, int(concurrency or 1))) as executor:
        futures = {
            executor.submit(_collect_single_fit_ap_optical, ac_device, row, site_name, collect_run_uuid, fit_ap_dir, paths): row
            for row in resources
        }
        for future in as_completed(futures):
            if should_cancel():
                for pending in futures:
                    pending.cancel()
                raise CollectionCancelled()
            rows.append(future.result())
            completed += 1
            progress_round(completed, total)
    return rows


def _retry_fit_ap_optical_targets(
    resources: list[dict[str, object | None]],
    round_rows: list[dict[str, object | None]],
) -> list[dict[str, object | None]]:
    result_by_key = {_fit_ap_optical_identity(row): row for row in round_rows if _fit_ap_optical_identity(row)}
    retry: list[dict[str, object | None]] = []
    for resource in resources:
        key = _fit_ap_optical_identity(resource)
        row = result_by_key.get(key)
        if row is None or fit_ap_optical_prefer_score(row)[0] < 80:
            retry.append(resource)
    return retry


def _fit_ap_optical_round_summary(round_index: int, concurrency: int, rows: list[dict[str, object | None]]) -> dict[str, object]:
    failed = sum(1 for row in rows if not _is_fit_ap_optical_success_row(row))
    empty = sum(1 for row in rows if _is_fit_ap_optical_success_row(row) and not _has_fit_ap_optical_data(row))
    return {
        "round_index": round_index,
        "planned": len(rows),
        "success": len(rows) - failed,
        "failed": failed,
        "empty_output": empty,
        "concurrency": concurrency,
        "success_rate": 0 if not rows else round((len(rows) - failed) / len(rows), 4),
    }


def _merge_fit_ap_optical_rows(
    existing_rows: list[dict[str, object | None]],
    updated_rows: list[dict[str, object | None]],
) -> list[dict[str, object | None]]:
    merged: dict[str, dict[str, object | None]] = {}
    passthrough: list[dict[str, object | None]] = []
    for row in existing_rows:
        key = _fit_ap_optical_identity(row)
        if key:
            merged[key] = dict(row)
        else:
            passthrough.append(dict(row))
    for row in updated_rows:
        key = _fit_ap_optical_identity(row)
        if key:
            current = merged.get(key)
            if current is not None and fit_ap_optical_prefer_score(current) > fit_ap_optical_prefer_score(row):
                merged[key] = _merge_failed_fit_ap_optical_row(current, row)
            elif _is_fit_ap_optical_success_row(row):
                merged[key] = dict(row)
            elif key in merged:
                merged[key] = _merge_failed_fit_ap_optical_row(merged[key], row)
            else:
                merged[key] = dict(row)
        else:
            passthrough.append(dict(row))
    return [*merged.values(), *passthrough]


def _fit_ap_optical_identity(row: dict[str, object | None]) -> str:
    ac_uuid = str(row.get("ac_device_uuid") or "").strip().casefold()
    apid = str(row.get("apid") or row.get("ap_id") or "").strip().casefold()
    if ac_uuid and apid and apid not in {"-", "n/a"}:
        return f"apid:{ac_uuid}:{apid}"
    for field in ("ap_uuid", "serial_number", "ap_mac", "ap_name"):
        if field == "ap_mac":
            text = _normalize_mac_text(row.get(field))
        else:
            text = str(row.get(field) or "").strip().casefold()
        if text:
            return f"{field}:{text}"
    return ""


def _merge_failed_fit_ap_optical_row(
    old: dict[str, object | None],
    new: dict[str, object | None],
) -> dict[str, object | None]:
    merged = {**old, **new}
    merged["ap_optical_data_source"] = "沿用历史" if _has_fit_ap_optical_data(old) else "本轮失败"
    merged["ap_last_valid_rx_power"] = old.get("rx_power") if not _is_empty_fit_ap_value(old.get("rx_power")) else old.get("ap_last_valid_rx_power")
    merged["ap_last_valid_collected_at"] = old.get("collected_at") if not _is_empty_fit_ap_value(old.get("rx_power")) else old.get("ap_last_valid_collected_at")
    merged["ap_optical_missing_reason"] = _fit_ap_optical_missing_reason(new)
    for field in (
        "ap_mac",
        "ap_name",
        "serial_number",
        "neighbor_device_name",
        "neighbor_interface",
        "rx_power",
        "tx_power",
    ):
        if _is_empty_fit_ap_value(new.get(field)) and not _is_empty_fit_ap_value(old.get(field)):
            merged[field] = old.get(field)
    return merged


def _is_empty_fit_ap_value(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text in {"-", "N/A", "n/a"}


def _is_fit_ap_optical_success_row(row: dict[str, object | None]) -> bool:
    status = str(row.get("status") or "").strip().casefold()
    if status == "success":
        return _has_fit_ap_optical_data(row) or _has_fit_ap_lldp_data(row)
    if status:
        return False
    return any(not _is_empty_fit_ap_value(row.get(field)) for field in ("ap_name", "ap_mac", "neighbor_device_name", "neighbor_interface", "rx_power", "tx_power", "interface_name", "site"))


def fit_ap_optical_prefer_score(row: dict[str, object | None]) -> tuple[int, str, str, int]:
    status = str(row.get("status") or "").strip().casefold()
    optical_status = str(row.get("optical_alarm_status") or row.get("raw_status") or "").strip().casefold()
    if status == "success" and not _is_empty_fit_ap_value(row.get("rx_power")):
        base = 100
    elif status == "success" and _has_fit_ap_optical_data(row):
        base = 90
    elif status == "success" and _has_fit_ap_lldp_data(row):
        base = 80
    elif "no_light" in optical_status or "无光" in optical_status:
        base = 50
    elif status in {"failed", "timeout", "parse_failed", "unknown"}:
        base = 10
    else:
        base = 0
    return (base, str(row.get("collected_at") or ""), str(row.get("updated_at") or ""), _int_value(row.get("id")))


def _has_fit_ap_optical_data(row: dict[str, object | None]) -> bool:
    return any(not _is_empty_fit_ap_value(row.get(field)) for field in ("rx_power", "tx_power", "module_model", "module_serial_number", "module_vendor", "temperature", "voltage"))


def _has_fit_ap_lldp_data(row: dict[str, object | None]) -> bool:
    return any(not _is_empty_fit_ap_value(row.get(field)) for field in ("neighbor_device_name", "neighbor_interface", "lldp_neighbor", "neighbor_mac"))


def _fit_ap_optical_missing_reason(row: dict[str, object | None]) -> str:
    message = str(row.get("error_message") or "").casefold()
    if "timeout" in message:
        return "connect_timeout"
    if "auth" in message or "password" in message:
        return "auth_failed"
    if str(row.get("status") or "").strip().casefold() in {"failed", "timeout"}:
        return "connect_timeout"
    return "unknown"


def _int_value(value: object) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _normalize_mac_text(value: object) -> str:
    import re

    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    return hex_text.casefold() if len(hex_text) == 12 else ""


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


def _can_update_dynamic_summary(command_results: list[CommandResult], summary: dict[str, object | None]) -> bool:
    ap_all_success = any(result.command == "display wlan ap all" and result.success for result in command_results)
    if not ap_all_success:
        return False
    return any(
        summary.get(field) is not None
        for field in (
            "total_aps",
            "online_aps",
            "offline_aps",
            "total_ap_licenses",
            "local_ap_licenses",
            "remaining_local_ap_licenses",
        )
    )


def _dynamic_summary_payload(summary: dict[str, object | None]) -> dict[str, object | None]:
    return {
        field: summary.get(field)
        for field in (
            "total_aps",
            "online_aps",
            "offline_aps",
            "total_ap_licenses",
            "local_ap_licenses",
            "remaining_local_ap_licenses",
            "collected_at",
            "collect_run_uuid",
            "raw_log_path",
            "updated_at",
        )
    }


def collect_https_port(connection, ac_device: Device, collect_run_uuid: str) -> tuple[int | None, list[CommandResult]]:
    app_logger.log_info("AC_HTTPS_PORT_COMMAND_STARTED", _detail(ac_device, collect_run_uuid, error="command_executed=true"))
    results: list[CommandResult] = []
    for command in HTTPS_PORT_COMMANDS:
        result = _run_command(connection, command, ac_device, collect_run_uuid, context="ac_collect")
        results.append(result)
        output_length = len(result.output or "")
        app_logger.log_info("AC_HTTPS_PORT_COMMAND_RESULT", _detail(ac_device, collect_run_uuid, command=command, error=f"output_length={output_length}"))
        if not result.success:
            continue
        for line in matching_https_port_lines(result.output):
            app_logger.log_info("AC_HTTPS_PORT_MATCHED_LINE", _detail(ac_device, collect_run_uuid, error=f'matched_line="{line}"'))
        port = parse_https_port(result.output)
        app_logger.log_info("AC_HTTPS_PORT_PARSED", _detail(ac_device, collect_run_uuid, command=command, error=f"parsed_port={port if port is not None else 'none'}"))
        if port is not None:
            return port, results
    return None, results


def _update_https_port(database: Database, ac_device: Device, collect_run_uuid: str, port: int | None) -> HttpsPortPersistenceResult:
    if port is None:
        app_logger.log_info("AC_HTTPS_PORT_NOT_COLLECTED", _detail(ac_device, collect_run_uuid, error="no valid HTTPS port parsed"))
        return HttpsPortPersistenceResult(None, False)
    if ac_device.id is None:
        message = f"device_id_missing, parsed_port={port}"
        app_logger.log_info("AC_HTTPS_PORT_NOT_SAVED", _detail(ac_device, collect_run_uuid, error=message))
        return HttpsPortPersistenceResult(None, False, message)
    try:
        repository = DeviceRepository(database)
        old_port = repository.get(int(ac_device.id)).https_port
        app_logger.log_info("AC_HTTPS_PORT_DB_BEFORE", _detail(ac_device, collect_run_uuid, error=f"old_db_port={old_port}"))
        repository.update_https_port(int(ac_device.id), port)
        saved_device = repository.get(int(ac_device.id))
        if saved_device.https_port != port:
            message = f"persistence verification failed, parsed_port={port}, persisted_port={saved_device.https_port}"
            app_logger.log_warning("AC_HTTPS_PORT_SAVE_FAILED", _detail(ac_device, collect_run_uuid, error=message))
            return HttpsPortPersistenceResult(saved_device.https_port, False, message)
        ac_device.https_port = saved_device.https_port
        app_logger.log_info(
            "AC_HTTPS_PORT_UPDATED",
            _detail(ac_device, collect_run_uuid, error=f"parsed_port={port}, persisted_port={saved_device.https_port}, persistence_verified=true"),
        )
        return HttpsPortPersistenceResult(saved_device.https_port, True)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        app_logger.log_warning("AC_HTTPS_PORT_SAVE_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        return HttpsPortPersistenceResult(None, False, message)


def _enable_fit_ap_console(ac_device: Device, collect_run_uuid: str) -> list[CommandResult]:
    target = choose_connection_target(ac_device)
    if target is None:
        raise RuntimeError("未启用连接方式")
    connection = None
    results: list[CommandResult] = []
    try:
        command_guard.validate_command_list(ENABLE_FIT_AP_CONSOLE_COMMANDS, "ac_enable_ap_console")
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        for command in ENABLE_FIT_AP_CONSOLE_COMMANDS:
            results.append(_run_command(connection, command, ac_device, collect_run_uuid, read_timeout=10, context="ac_enable_ap_console"))
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
    relative_raw_log_path = f"files/rail_transit/trackside_ap/raw/ac/{collect_run_uuid}/fit_ap/{_safe_filename(ap_name)}.log" if _persist_raw_logs() else ""
    collected_at = _now()
    base = {
        "ac_device_uuid": ac_device.device_uuid,
        "ap_uuid": ap_row.get("ap_uuid"),
        "ap_name": ap_name,
        "ap_mac": ap_row.get("ap_mac"),
        "serial_number": ap_row.get("serial_number"),
        "apid": ap_row.get("apid"),
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
        primary_address=ap_ip,
        ssh_enabled=0,
        telnet_enabled=1,
        telnet_port=23,
        telnet_username="",
        telnet_password="h3capadmin",
    )
    command_results: list[CommandResult] = []
    connection = None
    app_logger.log_info("FIT_AP_OPTICAL_AP_STARTED", _detail(ac_device, collect_run_uuid, ap=ap_name))
    try:
        target = choose_connection_target(temp_device)
        if target is None:
            raise RuntimeError("AP Telnet target unavailable")
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        command_guard.validate_command_list(FIT_AP_OPTICAL_COMMANDS, "fit_ap_collect")
        outputs: dict[str, str] = {}
        for command in FIT_AP_OPTICAL_COMMANDS:
            result = _run_command(connection, command, temp_device, collect_run_uuid, read_timeout=15, context="fit_ap_collect")
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        _write_raw_files(raw_log_file, commands_file, temp_device, collect_run_uuid, command_results)
        parsed = parse_fit_ap_optical(
            outputs.get("display lldp neighbor-information list", ""),
            outputs.get("display transceiver diagnosis interface", ""),
            "",
            "",
        )
        if _is_invalid_lldp_neighbor(parsed.get("lldp_neighbor")):
            parsed["lldp_neighbor"] = None
            parsed["neighbor_device_name"] = None
        reverse_match = match_ap_from_device_lldp(site_name, ap_mac=str(ap_row.get("ap_mac") or ""), ap_name=ap_name, paths=paths)
        match = reverse_match if reverse_match.device_uuid else match_neighbor_device(
            site_name,
            neighbor_mac=str(parsed.get("neighbor_mac") or ""),
            neighbor_sysname=str(parsed.get("lldp_neighbor") or ""),
            neighbor_interface=str(parsed.get("neighbor_interface") or ""),
            paths=paths,
        )
        if match.device_uuid:
            app_logger.log_info("FIT_AP_OPTICAL_NEIGHBOR_MATCHED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=f"matched_by={match.matched_by}"))
        else:
            app_logger.log_warning("FIT_AP_OPTICAL_NEIGHBOR_MATCH_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name))
        if match.station:
            base["site"] = match.station
        if match.matched_by == "device_lldp":
            parsed["neighbor_device_name"] = match.device_name
            parsed["neighbor_interface"] = match.local_interface
            parsed["interface_name"] = match.ap_interface or parsed.get("interface_name")
        else:
            parsed["neighbor_device_name"] = match.device_name or parsed.get("lldp_neighbor")
        if _is_invalid_lldp_neighbor(parsed.get("neighbor_device_name")):
            parsed["neighbor_device_name"] = None
        neighbor_optical = find_neighbor_optical_module(site_name, match.device_uuid, str(parsed.get("neighbor_interface") or ""), paths=paths)
        parsed["neighbor_rx_power"] = str(neighbor_optical.get("rx_power")) if neighbor_optical and neighbor_optical.get("rx_power") else None
        # optical_alarm_status is no longer stored — computed real-time by optical_severity_engine
        success = any(parsed.values()) and all(result.success for result in command_results)
        status = "success" if success else "failed"
        app_logger.log_info("FIT_AP_OPTICAL_AP_SUCCESS" if success else "FIT_AP_OPTICAL_AP_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name, error="" if success else _command_error_summary(command_results) or "no optical data parsed"))
        return {**base, **parsed, "status": status, "error_message": None if success else _command_error_summary(command_results) or "no optical data parsed"}
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), temp_device)
        _write_raw_files(raw_log_file, commands_file, temp_device, collect_run_uuid, command_results, fatal_error=message)
        app_logger.log_error("FIT_AP_OPTICAL_AP_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=message))
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


def _run_command(connection, command: str, device: Device, collect_run_uuid: str, read_timeout: int = 30, context: str = "ac_collect") -> CommandResult:
    reason = command_guard.command_reject_reason(command, context)
    if reason:
        command_guard.log_command_rejected(command, context, reason)
        return CommandResult(command=command, success=False, error_message=reason)
    app_logger.log_info("COMMAND_ALLOWED", _detail(device, collect_run_uuid, command=command))
    try:
        output = netmiko_connection.safe_send_command(
            connection,
            command,
            read_timeout=read_timeout,
            use_timing=True,
            encoding=netmiko_connection.encoding_for_vendor(device.device_vendor),
        )
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
    if not _persist_raw_logs():
        return
    raw_log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Collect Time: {_now()}",
        f"Collect Run UUID: {collect_run_uuid}",
        f"Device Name: {device.name}",
        f"Primary Address: {device.primary_address}",
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


def _persist_raw_logs() -> bool:
    return str(os.environ.get("NETCONSOLE_PERSIST_RAW_LOGS") or "").strip().lower() in {"1", "true", "yes", "on"}


def _raise_if_cancelled(should_cancel: CancelCheck) -> None:
    if should_cancel():
        raise CollectionCancelled()


def _command_error_summary(command_results: list[CommandResult]) -> str:
    return "; ".join(f"{item.command}: {item.error_message}" for item in command_results if not item.success)


def _disconnect(connection) -> None:
    try:
        connection.disconnect()
    except Exception:
        pass


def _detail(device: Device, collect_run_uuid: str, command: str = "", error: str = "", count: int | None = None, ap: str = "") -> str:
    parts = [f"device={device.name}", f"primary_address={device.primary_address}", f"collect_run_uuid={collect_run_uuid}"]
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


def _evaluate_neighbor_optical_status(rx_power: object, neighbor_optical: dict[str, object | None] | None) -> str:
    from netconsole.core.optical_severity_engine import compute_optical_severity

    if neighbor_optical:
        return compute_optical_severity(
            {
                "switch_rx_power": neighbor_optical.get("rx_power"),
                "switch_port_status": neighbor_optical.get("port_status"),
                "alarm_low": neighbor_optical.get("rx_low_alarm"),
                "alarm_high": neighbor_optical.get("rx_high_alarm"),
                "warning_low": neighbor_optical.get("rx_low_warning"),
            }
        ).severity
    return compute_optical_severity({"switch_rx_power": rx_power}).severity


def _worse_optical_status(left: str, right: str) -> str:
    from netconsole.core.optical_severity_engine import worse_optical_severity

    return worse_optical_severity(left, right)


def _to_float(value: object) -> float | None:
    import re

    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _is_invalid_lldp_neighbor(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in ("Nearest", "Chassis ID", "Default", "customer bridge", "nontpmr"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
