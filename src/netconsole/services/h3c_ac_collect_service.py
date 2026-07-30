from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from netconsole.adapters.h3c.h3c_command_profile import H3cAcCommandProfile
from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import Device
from netconsole.parsers.h3c.device_parser import parse_device
from netconsole.parsers.h3c.ac.fit_ap_optical_parser import parse_fit_ap_optical
from netconsole.parsers.h3c.ac.system_usage_parser import parse_cpu_usage, parse_memory
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_connection_record_parser import parse_wlan_ap_connection_records
from netconsole.parsers.h3c.ac.wlan_ap_lldp_parser import parse_wlan_ap_lldp
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list, parse_wlan_ap_summary
from netconsole.parsers.h3c.ac.wlan_ap_radio_parser import parse_wlan_ap_radios
from netconsole.parsers.h3c.ac.wlan_ap_radio_type_parser import parse_wlan_ap_radio_types
from netconsole.parsers.h3c.ac.wlan_ap_radio_verbose_parser import parse_wlan_ap_radio_verbose_bbssid
from netconsole.parsers.h3c.ac.wlan_ap_unauthenticated_parser import parse_wlan_ap_unauthenticated_rows, parse_wlan_ap_unauthenticated_summary
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.fit_ap_optical_concurrency import (
    DEFAULT_FIT_AP_OPTICAL_CONCURRENCY,
    clamp_fit_ap_optical_concurrency,
    fit_ap_optical_platform_concurrency_limit,
)
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
    "display wlan ap all connection-record",
    "display wlan ap all radio type",
    "display wlan ap unauthenticated",
    "display wlan ap all lldp",
)
FIT_AP_RESOURCE_COMMANDS = FIT_AP_RESOURCE_REQUIRED_COMMANDS

AC_OVERVIEW_COMMANDS = (
    "display cpu-usage",
    "display memory",
    "display version",
    "display device",
    "display device manuinfo",
)
RESOURCE_COMMANDS = (*FIT_AP_RESOURCE_REQUIRED_COMMANDS, *FIT_AP_RESOURCE_OPTIONAL_COMMANDS)

HTTPS_PORT_COMMANDS = (
    "display ip https",
    "display ip https | include port",
)

ENABLE_FIT_AP_CONSOLE_COMMANDS = (
    "screen-length disable",
    "system-view",
    "probe",
    "wlan ap-execute all exec-console enable",
    "return",
    "quit",
)
ENABLE_FIT_AP_CONSOLE_TIMEOUTS = {
    "screen-length disable": 15,
    "system-view": 15,
    "probe": 30,
    "wlan ap-execute all exec-console enable": 120,
    "return": 30,
    "quit": 30,
}
ENABLE_FIT_AP_CONSOLE_TAIL_COMMANDS = {"return", "quit"}
ENABLE_FIT_AP_CONSOLE_MAIN_COMMAND = "wlan ap-execute all exec-console enable"
READ_TIMEOUT_MARKERS = (
    "read_channel_timing's absolute timer expired",
    "continually outputting data",
    "readtimeout",
)
CLI_FAILURE_MARKERS = (
    "% Unrecognized command",
    "% Incomplete command",
    "% Ambiguous command",
    "Error:",
    "Failed",
    "Permission denied",
    "Invalid",
    "错误",
    "失败",
    "权限不足",
    "命令不完整",
    "无法识别",
)

FIT_AP_OPTICAL_COMMANDS = (
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
)
BATCH_CONCURRENCY = 50
DEFAULT_FIT_AP_TELNET_CONCURRENCY = DEFAULT_FIT_AP_OPTICAL_CONCURRENCY
ProgressCallback = Callable[[str], None]
FitApOpticalProgressCallback = Callable[[Mapping[str, object]], None]
CancelCheck = Callable[[], bool]


class CollectionCancelled(RuntimeError):
    def __init__(
        self,
        message: str = "用户已取消更新",
        *,
        completed_rows: list[dict[str, object | None]] | None = None,
    ) -> None:
        super().__init__(message)
        self.completed_rows = list(completed_rows or [])


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
    bbssid_rows_parsed: int = 0
    lldp_rows_parsed: int = 0


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
    status: str = ""
    requested_concurrency: int = 0
    effective_concurrency: int = 0
    platform_concurrency_limit: int = 0
    round_summaries: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class AcCommandActionResult:
    success: bool
    ac_device_uuid: str
    collect_run_uuid: str
    raw_log_path: str
    action: str
    commands: tuple[str, ...]
    error_message: str | None
    command_results: list[CommandResult] = field(default_factory=list)


def collect_h3c_ac_resources(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
    refresh_ac_overview: bool = True,
) -> AcResourceCollectResult:
    resource_result = collect_h3c_fit_ap_resources(
        ac_device,
        site_name,
        repository=repository,
        paths=paths,
        progress=progress,
        should_cancel=should_cancel,
    )
    if not refresh_ac_overview or not resource_result.success:
        return resource_result
    info_result = collect_h3c_ac_info(
        ac_device,
        site_name,
        repository=repository,
        paths=paths,
        progress=progress,
        should_cancel=should_cancel,
    )
    return AcResourceCollectResult(
        success=resource_result.success and info_result.success,
        ac_device_uuid=resource_result.ac_device_uuid,
        collect_run_uuid=resource_result.collect_run_uuid,
        raw_log_path=resource_result.raw_log_path,
        summary_updated=resource_result.summary_updated or info_result.summary_updated,
        fit_ap_resources_updated=resource_result.fit_ap_resources_updated,
        https_port=info_result.https_port,
        https_port_collected=info_result.https_port_collected,
        https_port_persisted=info_result.https_port_persisted,
        https_port_error=info_result.https_port_error,
        error_message=info_result.error_message or resource_result.error_message,
        command_results=[*resource_result.command_results, *info_result.command_results],
        unauthenticated_updated=resource_result.unauthenticated_updated,
        unauthenticated_rows_updated=resource_result.unauthenticated_rows_updated,
        unauthenticated_error=resource_result.unauthenticated_error,
        bbssid_rows_parsed=resource_result.bbssid_rows_parsed,
        lldp_rows_parsed=resource_result.lldp_rows_parsed,
    )


def collect_h3c_fit_ap_resources(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
    target_ap_uuid: str = "",
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

    deep_refresh = bool(str(target_ap_uuid or "").strip())
    target_resource = (
        repository.get_fit_ap_resource_by_uuid(str(ac_device.device_uuid), str(target_ap_uuid))
        if deep_refresh
        else None
    )
    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "fit_ap_detail" if deep_refresh else "fit_ap_resources",
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
    if deep_refresh and target_resource is None:
        message = "FIT-AP target does not exist in the selected AC"
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)

    try:
        profile = H3cAcCommandProfile(ac_device)
        command_results, outputs = _execute_h3c_ac_command_list(
            ac_device,
            collect_run_uuid,
            profile.fit_ap_detail_commands if deep_refresh else profile.fit_ap_resource_commands,
            "ac_fit_ap_detail_collect" if deep_refresh else "ac_fit_ap_resource_collect",
            progress,
            should_cancel,
        )
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results)
        _raise_if_cancelled(should_cancel)
        progress("正在解析FIT-AP资源...")
        summary, resources = parse_ac_resource_outputs(outputs, str(ac_device.device_uuid), collect_run_uuid, relative_raw_log_path)
        if target_resource is not None:
            target_name = str(target_resource.get("ap_name") or "").strip().casefold()
            resources = [row for row in resources if str(row.get("ap_name") or "").strip().casefold() == target_name]
        dynamic_summary_updated = _can_update_dynamic_summary(command_results, summary)
        progress("正在写入数据库...")
        if dynamic_summary_updated:
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
        resource_commands_ok = all(
            result.success
            for result in command_results
            if result.command in FIT_AP_RESOURCE_REQUIRED_COMMANDS
        )
        resources_persisted = bool(resource_commands_ok and resources)
        if resources_persisted:
            if deep_refresh:
                repository.upsert_fit_ap_resource(str(ac_device.device_uuid), resources[0])
            else:
                repository.replace_fit_ap_resources(str(ac_device.device_uuid), resources)
        unauth_result = next((result for result in command_results if result.command == "display wlan ap unauthenticated"), None)
        unauthenticated_updated = False
        unauthenticated_rows_updated = 0
        unauthenticated_error = None
        if not deep_refresh and unauth_result and unauth_result.success:
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
        elif not deep_refresh and unauth_result:
            unauthenticated_error = unauth_result.error_message or "display wlan ap unauthenticated failed"
            app_logger.log_warning("FIT_AP_UNAUTHENTICATED_FAILED", _detail(ac_device, collect_run_uuid, error=unauthenticated_error))
        bbssid = parse_wlan_ap_radio_verbose_bbssid(outputs.get("display wlan ap all radio verbose filter bbssid", ""))
        lldp = parse_wlan_ap_lldp(outputs.get("display wlan ap all lldp", ""))
        if target_resource is not None:
            target_name = str(target_resource.get("ap_name") or "")
            bbssid_rows = int(target_name in bbssid)
            lldp_rows = int(target_name in lldp)
        else:
            bbssid_rows = len(bbssid)
            lldp_rows = len(lldp)
        status = "success" if (resources_persisted if deep_refresh else dynamic_summary_updated or resources_persisted) else "failed"
        error_message = _command_error_summary([result for result in command_results if result.command not in FIT_AP_RESOURCE_OPTIONAL_COMMANDS])
        if deep_refresh and not resources_persisted and not error_message:
            error_message = "目标 FIT-AP 未从 AC 回显中解析到"
        fact_repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        if status == "success":
            app_logger.log_info("FIT_AP_RESOURCE_UPDATED", _detail(ac_device, collect_run_uuid, count=len(resources)))
            app_logger.log_info("AC_COLLECT_SUCCESS", _detail(ac_device, collect_run_uuid))
            app_logger.log_info("REAL_DEVICE_COLLECT_SUCCESS", _detail(ac_device, collect_run_uuid))
        else:
            app_logger.log_error("AC_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no data parsed"))
            app_logger.log_error("REAL_DEVICE_COLLECT_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no data parsed"))
        label = "FIT-AP深度更新" if deep_refresh else "FIT-AP资源更新"
        progress(f"{label}完成：AP {len(resources) if resources_persisted else 0} 条，未认证AP {unauthenticated_rows_updated} 条，BSSID {bbssid_rows} 条，LLDP {lldp_rows} 条")
        return AcResourceCollectResult(
            status == "success",
            str(ac_device.device_uuid),
            collect_run_uuid,
            result_raw_log_path,
            dynamic_summary_updated,
            len(resources) if resources_persisted else 0,
            None,
            False,
            False,
            None,
            error_message or None,
            command_results,
            unauthenticated_updated,
            unauthenticated_rows_updated,
            unauthenticated_error,
            bbssid_rows,
            lldp_rows,
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


def collect_h3c_ac_info(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
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
    command_results: list[CommandResult] = []

    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": "ac_info",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"files/rail_transit/trackside_ap/raw/ac/{collect_run_uuid}" if persist_raw_logs else None,
            "created_at": started_at,
        }
    )
    progress("正在连接AC...")
    if str(ac_device.device_type or "").upper() != "AC" or str(ac_device.device_vendor or "").upper() != "H3C":
        message = "AC information collection only supports H3C AC devices"
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)

    try:
        profile = H3cAcCommandProfile(ac_device)
        command_results, outputs = _execute_h3c_ac_command_list(
            ac_device,
            collect_run_uuid,
            profile.ac_info_commands,
            "ac_info_collect",
            progress,
            should_cancel,
        )
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results)
        progress("正在解析AC信息...")
        summary, _resources = parse_ac_resource_outputs(outputs, str(ac_device.device_uuid), collect_run_uuid, relative_raw_log_path)
        https_port = _parse_https_port_outputs(outputs, command_results, ac_device, collect_run_uuid)
        progress("正在写入数据库...")
        summary_updated = any(summary.get(field) is not None for field in ("cpu_usage", "memory_usage", "model", "serial_number", "software_version"))
        if summary_updated:
            repository.upsert_ac_ap_static_summary(str(ac_device.device_uuid), summary)
        persistence = _update_https_port(repository.database, ac_device, collect_run_uuid, https_port)
        error_message = _command_error_summary(command_results)
        status = "success" if summary_updated or https_port is not None else "failed"
        fact_repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message or None)
        progress(f"AC信息更新完成：HTTPS端口 {https_port or '未解析'}")
        return AcResourceCollectResult(
            status == "success",
            str(ac_device.device_uuid),
            collect_run_uuid,
            result_raw_log_path,
            summary_updated,
            0,
            https_port,
            https_port is not None,
            persistence.persisted,
            persistence.error_message,
            error_message or None,
            command_results,
        )
    except CollectionCancelled:
        message = "用户已取消更新"
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        progress("已取消")
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        return AcResourceCollectResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, False, 0, None, False, False, None, message, command_results)


def run_h3c_ac_action(
    ac_device: Device,
    site_name: str,
    action: str,
    commands: tuple[str, ...] | None = None,
    context: str | None = None,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> AcCommandActionResult:
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
    result_raw_log_path = str(raw_log_file) if persist_raw_logs else ""
    command_results: list[CommandResult] = []
    profile = H3cAcCommandProfile(ac_device)
    action_commands = commands or getattr(profile, f"{action}_commands")
    action_context = context or f"ac_{action}"

    fact_repository.create_collect_run(
        {
            "collect_run_uuid": collect_run_uuid,
            "collect_type": f"ac_action:{action}",
            "status": "running",
            "started_at": started_at,
            "raw_log_dir": f"files/rail_transit/trackside_ap/raw/ac/{collect_run_uuid}" if persist_raw_logs else None,
            "created_at": started_at,
        }
    )
    if str(ac_device.device_type or "").upper() != "AC" or str(ac_device.device_vendor or "").upper() != "H3C":
        message = "AC action only supports H3C AC devices"
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        return AcCommandActionResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, action, tuple(action_commands), message, command_results)
    try:
        per_command_read_timeout = ENABLE_FIT_AP_CONSOLE_TIMEOUTS if action == "enable_ap_remote_login" else None
        command_results, _outputs = _execute_h3c_ac_command_list(
            ac_device,
            collect_run_uuid,
            action_commands,
            action_context,
            progress,
            should_cancel,
            read_timeout=10,
            per_command_read_timeout=per_command_read_timeout,
            detect_cli_failures=action == "enable_ap_remote_login",
        )
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results)
        error_message = _command_error_summary(command_results)
        success = not error_message and bool(command_results)
        fact_repository.update_collect_run_status(collect_run_uuid, "success" if success else "failed", error_message=error_message or None)
        progress("AC动作执行完成" if success else "AC动作执行失败")
        return AcCommandActionResult(success, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, action, tuple(action_commands), error_message or None, command_results)
    except CollectionCancelled:
        message = "用户已取消更新"
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        return AcCommandActionResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, action, tuple(action_commands), message, command_results)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        _write_raw_files(raw_log_file, commands_file, ac_device, collect_run_uuid, command_results, fatal_error=message)
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        return AcCommandActionResult(False, str(ac_device.device_uuid), collect_run_uuid, result_raw_log_path, action, tuple(action_commands), message, command_results)


def collect_h3c_fit_ap_optical(
    ac_device: Device,
    site_name: str,
    repository: AcRepository | None = None,
    paths: PathResolver | None = None,
    max_workers: int | None = None,
    progress: ProgressCallback | None = None,
    item_progress: FitApOpticalProgressCallback | None = None,
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
    settings = _fit_ap_optical_collect_settings(paths)
    requested_concurrency = _fit_ap_optical_requested_concurrency(max_workers, settings)
    platform_concurrency_limit = fit_ap_optical_platform_concurrency_limit()
    round_summaries: list[dict[str, object]] = []
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
    _safe_log_info("FIT_AP_OPTICAL_STARTED", _detail(ac_device, collect_run_uuid))
    progress("\u51c6\u5907\u66f4\u65b0FIT-AP\u5149\u8870...")
    try:
        _safe_log_info("FIT_AP_OPTICAL_AC_ENABLE_STARTED", _detail(ac_device, collect_run_uuid))
        _raise_if_cancelled(should_cancel)
        progress("\u6b63\u5728\u8fde\u63a5AC\u5e76\u542f\u7528AP\u63a7\u5236\u53f0...")
        enable_results = _enable_fit_ap_console(ac_device, collect_run_uuid)
        _write_raw_files(run_dir / f"{ac_device.device_uuid}.log", run_dir / f"{ac_device.device_uuid}_commands.jsonl", ac_device, collect_run_uuid, enable_results)
        if any(not result.success for result in enable_results):
            raise RuntimeError(_command_error_summary(enable_results) or "AC enable AP console failed")
        _safe_log_info("FIT_AP_OPTICAL_AC_ENABLE_SUCCESS", _detail(ac_device, collect_run_uuid))
    except CollectionCancelled:
        message = "\u7528\u6237\u5df2\u53d6\u6d88\u66f4\u65b0"
        _safe_log_warning("FIT_AP_OPTICAL_CANCELLED", _detail(ac_device, collect_run_uuid))
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        progress("\u5df2\u53d6\u6d88")
        return _fit_ap_optical_result(
            success=False,
            partial_success=False,
            ac_device_uuid=str(ac_device.device_uuid),
            collect_run_uuid=collect_run_uuid,
            optical_rows_updated=0,
            failed_aps=0,
            error_message=message,
            status="cancelled",
            requested_concurrency=requested_concurrency,
            platform_concurrency_limit=platform_concurrency_limit,
            round_summaries=round_summaries,
        )
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), ac_device)
        trace = _sanitized_traceback(exc, ac_device)
        _safe_log_error("FIT_AP_OPTICAL_AC_ENABLE_FAILED", _detail(ac_device, collect_run_uuid, error=f"{message}; traceback={trace}"))
        _safe_log_error("FIT_AP_OPTICAL_FAILED", _detail(ac_device, collect_run_uuid, error=message))
        fact_repository.update_collect_run_status(collect_run_uuid, "failed", error_message=message)
        return _fit_ap_optical_result(
            success=False,
            partial_success=False,
            ac_device_uuid=str(ac_device.device_uuid),
            collect_run_uuid=collect_run_uuid,
            optical_rows_updated=0,
            failed_aps=0,
            error_message=message,
            status="failed",
            requested_concurrency=requested_concurrency,
            platform_concurrency_limit=platform_concurrency_limit,
            round_summaries=round_summaries,
        )

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
    total = len(resources)
    worker_count = clamp_fit_ap_optical_concurrency(
        requested_concurrency,
        total,
        platform_limit=platform_concurrency_limit,
    )
    _emit_fit_ap_optical_progress(
        item_progress,
        _fit_ap_optical_plan_progress(
            ac_device,
            collect_run_uuid,
            total=total,
            requested_concurrency=requested_concurrency,
            effective_concurrency=worker_count,
            platform_concurrency_limit=platform_concurrency_limit,
        ),
    )
    if scoped_refresh and total == 0:
        fact_repository.update_collect_run_status(collect_run_uuid, "success", error_message=None)
        _safe_log_info("FIT_AP_OPTICAL_SKIPPED_NO_CONNECTABLE_TARGET", _detail(ac_device, collect_run_uuid))
        progress("\u66f4\u65b0\u5b8c\u6210\uff1a\u6210\u529f 0\uff0c\u5931\u8d25 0\uff0c\u79bb\u7ebf 0")
        return _fit_ap_optical_result(
            success=True,
            partial_success=False,
            ac_device_uuid=str(ac_device.device_uuid),
            collect_run_uuid=collect_run_uuid,
            optical_rows_updated=0,
            failed_aps=0,
            error_message=None,
            status="success",
            requested_concurrency=requested_concurrency,
            effective_concurrency=worker_count,
            platform_concurrency_limit=platform_concurrency_limit,
            round_summaries=round_summaries,
        )
    progress(f"\u6b63\u5728\u91c7\u96c6 AP\u4fa7\u5149\u8870\uff1a0/{total}")
    try:
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
            round_index=1,
            item_progress=item_progress,
        )
        rows.extend(first_round_rows)
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
            retry_concurrency = clamp_fit_ap_optical_concurrency(
                retry_concurrency,
                len(retry_targets),
                platform_limit=platform_concurrency_limit,
            )
            _safe_log_info(
                "FIT_AP_OPTICAL_RETRY_STARTED",
                _detail(ac_device, collect_run_uuid, count=len(retry_targets), error=f"round={round_index}, concurrency={retry_concurrency}"),
            )
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
                round_index=round_index,
                item_progress=item_progress,
                retry=True,
            )
            rows.extend(retry_rows)
            round_summaries.append(_fit_ap_optical_round_summary(round_index, retry_concurrency, retry_rows))
            retry_targets = _retry_fit_ap_optical_targets(retry_targets, retry_rows)
            previous_concurrency = retry_concurrency
        _safe_log_info("FIT_AP_OPTICAL_ADAPTIVE_SUMMARY", f"ac_device_uuid={ac_device.device_uuid}, rounds={round_summaries}")
        progress("\u6b63\u5728\u89e3\u6790\u5149\u6a21\u5757\u6570\u636e...")
        _raise_if_cancelled(should_cancel)
        rows = _final_fit_ap_optical_rows(rows)
        progress("\u6b63\u5728\u5199\u5165\u6570\u636e\u5e93...")
        if not _persist_successful_fit_ap_optical_rows(repository, str(ac_device.device_uuid), rows):
            _safe_log_warning("FIT_AP_OPTICAL_DB_SAVE_SKIPPED", _detail(ac_device, collect_run_uuid, error="no successful AP optical rows; keeping previous data"))
    except CollectionCancelled as exc:
        rows.extend(exc.completed_rows)
        rows = _final_fit_ap_optical_rows(rows)
        message = "\u7528\u6237\u5df2\u53d6\u6d88\u66f4\u65b0"
        _safe_log_warning("FIT_AP_OPTICAL_CANCELLED", _detail(ac_device, collect_run_uuid))
        failed = sum(1 for row in rows if row.get("status") != "success")
        try:
            if _persist_successful_fit_ap_optical_rows(repository, str(ac_device.device_uuid), rows):
                _safe_log_info("FIT_AP_OPTICAL_CANCELLED_PARTIAL_DB_SAVED", _detail(ac_device, collect_run_uuid, count=len(rows)))
        except Exception as save_exc:
            save_message = sanitize_sensitive_text(str(save_exc), ac_device)
            _safe_log_error("FIT_AP_OPTICAL_CANCELLED_DB_SAVE_FAILED", _detail(ac_device, collect_run_uuid, error=save_message))
        fact_repository.update_collect_run_status(collect_run_uuid, "cancelled", error_message=message)
        progress("\u5df2\u53d6\u6d88")
        return _fit_ap_optical_result(
            success=False,
            partial_success=bool(rows),
            ac_device_uuid=str(ac_device.device_uuid),
            collect_run_uuid=collect_run_uuid,
            optical_rows_updated=len(rows),
            failed_aps=failed,
            error_message=message,
            status="cancelled",
            requested_concurrency=requested_concurrency,
            effective_concurrency=worker_count,
            platform_concurrency_limit=platform_concurrency_limit,
            round_summaries=round_summaries,
        )
    _safe_log_info("FIT_AP_OPTICAL_DB_SAVED", _detail(ac_device, collect_run_uuid, count=len(rows)))
    failed = sum(1 for row in rows if row.get("status") != "success")
    status = "failed" if rows and failed == len(rows) else "partial_success" if failed else "success"
    if not rows:
        status = "failed"
    error_message = f"failed_aps={failed}" if failed else None
    fact_repository.update_collect_run_status(collect_run_uuid, status, error_message=error_message)
    if status == "success":
        _safe_log_info("FIT_AP_OPTICAL_SUCCESS", _detail(ac_device, collect_run_uuid, count=len(rows)))
    elif status == "partial_success":
        _safe_log_warning("FIT_AP_OPTICAL_PARTIAL_SUCCESS", _detail(ac_device, collect_run_uuid, count=len(rows), error=error_message or ""))
    else:
        _safe_log_error("FIT_AP_OPTICAL_FAILED", _detail(ac_device, collect_run_uuid, error=error_message or "no AP resources"))
    progress(f"\u66f4\u65b0\u5b8c\u6210\uff1a\u6210\u529f {len(rows) - failed}\uff0c\u5931\u8d25 {failed}\uff0c\u79bb\u7ebf 0")
    return _fit_ap_optical_result(
        success=status != "failed",
        partial_success=status == "partial_success",
        ac_device_uuid=str(ac_device.device_uuid),
        collect_run_uuid=collect_run_uuid,
        optical_rows_updated=len(rows),
        failed_aps=failed,
        error_message=error_message,
        status=status,
        requested_concurrency=requested_concurrency,
        effective_concurrency=worker_count,
        platform_concurrency_limit=platform_concurrency_limit,
        round_summaries=round_summaries,
    )


def _is_scoped_fit_ap_refresh(*scopes: list[str] | None) -> bool:
    return any(bool(scope) for scope in scopes)


def _fit_ap_optical_collect_settings(paths: PathResolver) -> dict[str, object]:
    defaults = {
        "max_fit_ap_concurrency": DEFAULT_FIT_AP_TELNET_CONCURRENCY,
        "adaptive_concurrency_enabled": True,
        "adaptive_retry_enabled": True,
        "retry_count": 2,
        "retry_concurrency_floor": 16,
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


def _fit_ap_optical_requested_concurrency(max_workers: object, settings: dict[str, object]) -> int:
    configured = settings.get("max_fit_ap_concurrency") or DEFAULT_FIT_AP_TELNET_CONCURRENCY
    requested = max_workers if str(max_workers or "").strip() else configured
    return _int_setting(requested, configured, minimum=1)


def retry_fit_ap_optical_concurrency(previous_concurrency: int, *, floor: int = 16, ratio: float = 0.5) -> int:
    previous = max(1, int(previous_concurrency or 1))
    if previous <= 1:
        return 1
    candidate = max(1, int(previous * max(0.01, float(ratio or 0.01))))
    retry_floor = int(floor or 1)
    if 1 <= retry_floor < previous:
        candidate = max(candidate, retry_floor)
    return max(1, min(previous - 1, candidate))


def _fit_ap_optical_result(
    *,
    success: bool,
    partial_success: bool,
    ac_device_uuid: str,
    collect_run_uuid: str,
    optical_rows_updated: int,
    failed_aps: int,
    error_message: str | None,
    status: str,
    requested_concurrency: int = 0,
    effective_concurrency: int = 0,
    platform_concurrency_limit: int = 0,
    round_summaries: list[dict[str, object]] | None = None,
) -> FitApOpticalCollectResult:
    return FitApOpticalCollectResult(
        success,
        partial_success,
        ac_device_uuid,
        collect_run_uuid,
        optical_rows_updated,
        failed_aps,
        error_message,
        status,
        requested_concurrency,
        effective_concurrency,
        platform_concurrency_limit,
        list(round_summaries or []),
    )


def _safe_app_log(log_fn: Callable[[str, str], None], level: str, event: str, detail: str) -> None:
    try:
        log_fn(event, detail)
    except Exception as exc:
        try:
            trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        except Exception:
            trace = f"{type(exc).__name__}: {exc}"
        message = app_logger.sanitize_detail(
            f"fit_ap_optical_log_failed level={level} event={event} detail={detail} "
            f"error_type={type(exc).__name__} error={exc} traceback={trace}"
        )
        try:
            sys.stderr.write(message + "\n")
            sys.stderr.flush()
        except Exception:
            pass


def _safe_log_info(event: str, detail: str) -> None:
    _safe_app_log(app_logger.log_info, "INFO", event, detail)


def _safe_log_warning(event: str, detail: str) -> None:
    _safe_app_log(app_logger.log_warning, "WARNING", event, detail)


def _safe_log_error(event: str, detail: str) -> None:
    _safe_app_log(app_logger.log_error, "ERROR", event, detail)


def _sanitized_traceback(exc: BaseException, device: Device | None = None) -> str:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if device is not None:
        return sanitize_sensitive_text(text, device)
    return app_logger.sanitize_detail(text)


def _fit_ap_optical_error_category(message: object) -> str:
    text = str(message or "").casefold()
    if not text:
        return "unexpected_error"
    if "fit_ap_optical_log_failed" in text or "app-log.lock" in text or "resource deadlock" in text:
        return "log_write_failed"
    if "cancel" in text or "取消" in text:
        return "cancelled"
    if "timeout" in text or "timed out" in text or "read timeout" in text:
        return "connect_timeout"
    if "auth" in text or "password" in text or "login" in text or "认证" in text or "密码" in text:
        return "auth_failed"
    if "parse" in text or "解析" in text or "no optical data parsed" in text:
        return "parse_failed"
    if "command" in text or "命令" in text or "cli" in text:
        return "command_failed"
    return "unexpected_error"


def _fit_ap_optical_error_message(category: str, message: object) -> str:
    text = str(message or "").strip()
    if not text:
        return category
    prefix = f"{category}:".casefold()
    return text if text.casefold().startswith(prefix) else f"{category}: {text}"


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
        row_station = str(row.get("site") or row.get("site_name") or row.get("station") or "").strip().casefold()
        if station_set and row_station in station_set:
            result.append(row)
    return result


def _emit_fit_ap_optical_progress(
    callback: FitApOpticalProgressCallback | None,
    payload: Mapping[str, object],
) -> None:
    if callback is None:
        return
    callback(dict(payload))


def _fit_ap_optical_plan_progress(
    ac_device: Device,
    collect_run_uuid: str,
    *,
    total: int,
    requested_concurrency: int,
    effective_concurrency: int,
    platform_concurrency_limit: int,
) -> dict[str, object]:
    ac_name = str(ac_device.name or ac_device.system_name or ac_device.device_uuid or "")
    return {
        "message": f"{ac_name} 可采集 AP 数量：{int(total or 0)}",
        "phase": "fit_ap_optical",
        "event": "plan_ready",
        "collect_run_uuid": collect_run_uuid,
        "ac_device_uuid": str(ac_device.device_uuid or ""),
        "ac_name": ac_name,
        "total": int(total or 0),
        "completed": 0,
        "requested_concurrency": int(requested_concurrency or 0),
        "effective_concurrency": int(effective_concurrency or 0),
        "platform_concurrency_limit": int(platform_concurrency_limit or 0),
    }


def _fit_ap_identity_for_progress(row: Mapping[str, object | None]) -> str:
    identity = _fit_ap_optical_identity(dict(row))
    if identity:
        return identity
    return str(row.get("ap_uuid") or row.get("ap_mac") or row.get("ap_name") or row.get("ap_ip") or "").strip()


def _fit_ap_progress_base(
    ac_device: Device,
    resource: Mapping[str, object | None],
    collect_run_uuid: str,
) -> dict[str, object]:
    ap_name = str(resource.get("ap_name") or resource.get("ap_ip") or "FIT-AP")
    return {
        "phase": "fit_ap_optical",
        "collect_run_uuid": collect_run_uuid,
        "ac_device_uuid": str(ac_device.device_uuid or ""),
        "ac_name": str(ac_device.name or ac_device.system_name or ac_device.device_uuid or ""),
        "ap_identity": _fit_ap_identity_for_progress(resource),
        "ap_uuid": str(resource.get("ap_uuid") or ""),
        "ap_name": ap_name,
        "ap_mac": str(resource.get("ap_mac") or ""),
        "ap_ip": str(resource.get("ap_ip") or ""),
        "station": str(resource.get("site") or resource.get("site_name") or resource.get("station") or ""),
    }


def _fit_ap_optical_started_progress(
    ac_device: Device,
    resource: Mapping[str, object | None],
    collect_run_uuid: str,
    *,
    round_index: int,
    index: int,
    total: int,
    retry: bool,
    effective_concurrency: int,
) -> dict[str, object]:
    base = _fit_ap_progress_base(ac_device, resource, collect_run_uuid)
    ap_name = str(base["ap_name"])
    ap_ip = str(base["ap_ip"])
    if retry:
        message = f"第 {round_index} 轮重试 {index}/{total}：{ap_name}"
        event = "ap_retry_started"
        status = "retrying"
    else:
        suffix = f"（{ap_ip}）" if ap_ip else ""
        message = f"开始采集 AP {index}/{total}：{ap_name}{suffix}"
        event = "ap_started"
        status = "running"
    return {
        **base,
        "message": message,
        "event": event,
        "round": int(round_index),
        "index": int(index),
        "total": int(total),
        "completed": 0,
        "status": status,
        "previous_reason": str(resource.get("error_message") or resource.get("reason_code") or ""),
        "effective_concurrency": int(effective_concurrency or 0),
    }


def _fit_ap_optical_completed_progress(
    ac_device: Device,
    resource: Mapping[str, object | None],
    row: Mapping[str, object | None],
    collect_run_uuid: str,
    *,
    round_index: int,
    completed: int,
    total: int,
    success_count: int,
    failed_count: int,
    elapsed_ms: int,
    effective_concurrency: int,
) -> dict[str, object]:
    merged = {**dict(resource), **dict(row)}
    base = _fit_ap_progress_base(ac_device, merged, collect_run_uuid)
    status = str(row.get("status") or "failed").strip().casefold() or "failed"
    reason_code = ""
    error_message = ""
    if status != "success":
        error_message = str(row.get("error_message") or "FIT-AP 光衰采集失败")
        reason_code = _fit_ap_optical_error_category(error_message)
    rx_power = str(row.get("rx_power") or "")
    tx_power = str(row.get("tx_power") or "")
    seconds = elapsed_ms / 1000
    if status == "success":
        optical = f"，Rx {rx_power} dBm" if rx_power else ""
        message = f"AP {completed}/{total} 成功：{base['ap_name']}{optical}，耗时 {seconds:.2f} 秒"
    else:
        message = f"AP {completed}/{total} 失败：{base['ap_name']}，{error_message}，耗时 {seconds:.2f} 秒"
    return {
        **base,
        "message": message,
        "event": "ap_completed",
        "round": int(round_index),
        "index": int(completed),
        "total": int(total),
        "completed": int(completed),
        "success_count": int(success_count),
        "failed_count": int(failed_count),
        "status": "success" if status == "success" else "failed",
        "reason_code": reason_code,
        "error_message": error_message,
        "rx_power": rx_power,
        "tx_power": tx_power,
        "elapsed_ms": int(elapsed_ms),
        "effective_concurrency": int(effective_concurrency or 0),
    }


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
    *,
    round_index: int = 1,
    item_progress: FitApOpticalProgressCallback | None = None,
    retry: bool = False,
) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    total = len(resources)
    if total <= 0:
        return rows
    completed = 0
    success_count = 0
    failed_count = 0
    worker_count = max(1, min(total, int(concurrency or 1)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        started_at: dict[object, float] = {}
        for index, row in enumerate(resources, start=1):
            _emit_fit_ap_optical_progress(
                item_progress,
                _fit_ap_optical_started_progress(
                    ac_device,
                    row,
                    collect_run_uuid,
                    round_index=round_index,
                    index=index,
                    total=total,
                    retry=retry,
                    effective_concurrency=worker_count,
                ),
            )
            future = executor.submit(_collect_single_fit_ap_optical, ac_device, row, site_name, collect_run_uuid, fit_ap_dir, paths)
            futures[future] = row
            started_at[future] = time.monotonic()
        for future in as_completed(futures):
            if should_cancel():
                for pending in futures:
                    pending.cancel()
                raise CollectionCancelled(completed_rows=rows)
            resource = futures[future]
            try:
                row = future.result()
            except CollectionCancelled as exc:
                for pending in futures:
                    pending.cancel()
                raise CollectionCancelled(completed_rows=[*rows, *exc.completed_rows]) from exc
            except Exception as exc:
                message = sanitize_sensitive_text(str(exc), ac_device)
                category = _fit_ap_optical_error_category(message)
                trace = _sanitized_traceback(exc, ac_device)
                _safe_log_error(
                    "FIT_AP_OPTICAL_AP_FUTURE_FAILED",
                    _detail(
                        ac_device,
                        collect_run_uuid,
                        ap=str(resource.get("ap_name") or resource.get("ap_ip") or "FIT-AP"),
                        error=f"category={category}, error={message}, traceback={trace}",
                    ),
                )
                row = _failed_fit_ap_optical_row(ac_device, resource, collect_run_uuid, category, message)
            rows.append(row)
            completed += 1
            elapsed_ms = max(0, int((time.monotonic() - started_at.get(future, time.monotonic())) * 1000))
            if str(row.get("status") or "").casefold() == "success":
                success_count += 1
            else:
                failed_count += 1
            _emit_fit_ap_optical_progress(
                item_progress,
                _fit_ap_optical_completed_progress(
                    ac_device,
                    resource,
                    row,
                    collect_run_uuid,
                    round_index=round_index,
                    completed=completed,
                    total=total,
                    success_count=success_count,
                    failed_count=failed_count,
                    elapsed_ms=elapsed_ms,
                    effective_concurrency=worker_count,
                ),
            )
            progress_round(completed, total)
    return rows


def _failed_fit_ap_optical_row(
    ac_device: Device,
    ap_row: dict[str, object | None],
    collect_run_uuid: str,
    category: str,
    message: str,
    raw_log_path: str = "",
) -> dict[str, object | None]:
    ap_name = str(ap_row.get("ap_name") or ap_row.get("ap_ip") or "FIT-AP")
    collected_at = _now()
    error_message = _fit_ap_optical_error_message(category, message)
    return {
        "ac_device_uuid": ac_device.device_uuid,
        "ap_uuid": ap_row.get("ap_uuid"),
        "ap_name": ap_name,
        "ap_mac": ap_row.get("ap_mac"),
        "serial_number": ap_row.get("serial_number"),
        "apid": ap_row.get("apid"),
        "ap_ip": ap_row.get("ap_ip"),
        "site": ap_row.get("site") or ap_row.get("site_name") or ap_row.get("station"),
        "collected_at": collected_at,
        "updated_at": collected_at,
        "collect_run_uuid": collect_run_uuid,
        "raw_log_path": raw_log_path,
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
        "error_message": error_message,
    }


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


def _final_fit_ap_optical_rows(
    rows: list[dict[str, object | None]],
) -> list[dict[str, object | None]]:
    final_by_identity: dict[str, dict[str, object | None]] = {}
    passthrough: list[dict[str, object | None]] = []
    for row in rows:
        current = dict(row)
        key = _fit_ap_optical_identity(current)
        if not key:
            passthrough.append(current)
            continue
        previous = final_by_identity.get(key)
        if previous is None or fit_ap_optical_prefer_score(current) >= fit_ap_optical_prefer_score(previous):
            final_by_identity[key] = current
    return [*final_by_identity.values(), *passthrough]


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


def _persist_successful_fit_ap_optical_rows(
    repository: AcRepository,
    ac_device_uuid: str,
    rows: list[dict[str, object | None]],
) -> bool:
    successful_rows = [row for row in rows if _is_fit_ap_optical_success_row(row)]
    if not successful_rows:
        return False
    existing_rows = repository.list_fit_ap_optical(ac_device_uuid)
    repository.replace_fit_ap_optical(ac_device_uuid, _merge_fit_ap_optical_rows(existing_rows, rows))
    return True


def _fit_ap_optical_identity(row: dict[str, object | None]) -> str:
    ac_uuid = str(row.get("ac_device_uuid") or "").strip().casefold()
    apid = str(row.get("apid") or row.get("ap_id") or "").strip().casefold()
    if ac_uuid and apid and apid not in {"-", "n/a"}:
        return f"apid:{ac_uuid}:{apid}"
    for field_name in ("ap_uuid", "serial_number", "ap_mac", "ap_name"):
        if field_name == "ap_mac":
            text = _normalize_mac_text(row.get(field_name))
        else:
            text = str(row.get(field_name) or "").strip().casefold()
        if text:
            return f"{field_name}:{text}"
    return ""


def _merge_failed_fit_ap_optical_row(
    old: dict[str, object | None],
    new: dict[str, object | None],
) -> dict[str, object | None]:
    merged = dict(new) if not old else {**new, **old}
    if old:
        merged["status"] = new.get("status") or "failed"
        merged["error_message"] = new.get("error_message") or old.get("error_message")
        merged["collect_run_uuid"] = new.get("collect_run_uuid") or old.get("collect_run_uuid")
        merged["raw_log_path"] = new.get("raw_log_path") or old.get("raw_log_path")
        merged["collected_at"] = old.get("collected_at") or new.get("collected_at")
        merged["updated_at"] = old.get("updated_at") or old.get("collected_at") or new.get("updated_at")
    merged["ap_optical_data_source"] = "沿用历史" if _has_fit_ap_optical_data(old) else "本轮失败"
    merged["ap_last_valid_rx_power"] = old.get("rx_power") if not _is_empty_fit_ap_value(old.get("rx_power")) else old.get("ap_last_valid_rx_power")
    merged["ap_last_valid_collected_at"] = old.get("collected_at") if not _is_empty_fit_ap_value(old.get("rx_power")) else old.get("ap_last_valid_collected_at")
    merged["ap_optical_missing_reason"] = _fit_ap_optical_missing_reason(new)
    for field_name in (
        "ap_mac",
        "ap_name",
        "serial_number",
        "neighbor_device_name",
        "neighbor_interface",
        "rx_power",
        "tx_power",
    ):
        if _is_empty_fit_ap_value(new.get(field_name)) and not _is_empty_fit_ap_value(old.get(field_name)):
            merged[field_name] = old.get(field_name)
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
    category = _fit_ap_optical_error_category(message)
    if category != "unexpected_error":
        return category
    if str(row.get("status") or "").strip().casefold() in {"failed", "timeout"}:
        return "unexpected_error"
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
    connection_rows = parse_wlan_ap_connection_records(outputs.get("display wlan ap all connection-record", ""))
    radio_type_rows = parse_wlan_ap_radio_types(outputs.get("display wlan ap all radio type", ""))
    bbssid_rows = parse_wlan_ap_radio_verbose_bbssid(outputs.get("display wlan ap all radio verbose filter bbssid", ""))
    lldp_rows = parse_wlan_ap_lldp(outputs.get("display wlan ap all lldp", ""))
    resources: list[dict[str, object | None]] = []
    for row in ap_rows:
        ap_name = str(row.get("ap_name") or "")
        resources.append(
            {
                "ac_device_uuid": ac_device_uuid,
                **row,
                **address_rows.get(ap_name, {}),
                **radio_rows.get(ap_name, {}),
                **connection_rows.get(ap_name, {}),
                **radio_type_rows.get(ap_name, {}),
                **bbssid_rows.get(ap_name, {}),
                **lldp_rows.get(ap_name, {}),
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


def _parse_https_port_outputs(outputs: dict[str, str], command_results: list[CommandResult], ac_device: Device, collect_run_uuid: str) -> int | None:
    for command in HTTPS_PORT_COMMANDS:
        result = next((item for item in command_results if item.command == command), None)
        if result is None or not result.success:
            continue
        app_logger.log_info("AC_HTTPS_PORT_COMMAND_RESULT", _detail(ac_device, collect_run_uuid, command=command, error=f"output_length={len(outputs.get(command, ''))}"))
        for line in matching_https_port_lines(outputs.get(command, "")):
            app_logger.log_info("AC_HTTPS_PORT_MATCHED_LINE", _detail(ac_device, collect_run_uuid, error=f'matched_line="{line}"'))
        port = parse_https_port(outputs.get(command, ""))
        app_logger.log_info("AC_HTTPS_PORT_PARSED", _detail(ac_device, collect_run_uuid, command=command, error=f"parsed_port={port if port is not None else 'none'}"))
        if port is not None:
            return port
    app_logger.log_info("AC_HTTPS_PORT_NOT_COLLECTED", _detail(ac_device, collect_run_uuid, error="no valid HTTPS port parsed"))
    return None


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
            result = _run_command(
                connection,
                command,
                ac_device,
                collect_run_uuid,
                read_timeout=ENABLE_FIT_AP_CONSOLE_TIMEOUTS.get(command, 30),
                context="ac_enable_ap_console",
                preserve_echo=True,
                detect_cli_failures=True,
            )
            if _should_treat_enable_console_timeout_as_success(results, result):
                result = _success_with_read_timeout_warning(result, ac_device, collect_run_uuid)
            results.append(result)
        return results
    finally:
        if connection is not None:
            _disconnect(connection)


def _execute_h3c_ac_command_list(
    ac_device: Device,
    collect_run_uuid: str,
    commands: tuple[str, ...],
    context: str,
    progress: ProgressCallback,
    should_cancel: CancelCheck,
    read_timeout: int = 30,
    per_command_read_timeout: dict[str, int] | None = None,
    detect_cli_failures: bool = False,
) -> tuple[list[CommandResult], dict[str, str]]:
    target = choose_connection_target(ac_device)
    if target is None:
        raise RuntimeError("未启用连接方式")
    command_guard.validate_command_list(commands, context)
    _raise_if_cancelled(should_cancel)
    connection = None
    command_results: list[CommandResult] = []
    outputs: dict[str, str] = {}
    try:
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        for command in commands:
            _raise_if_cancelled(should_cancel)
            progress(f"正在执行 {command}...")
            timeout = per_command_read_timeout.get(command, read_timeout) if per_command_read_timeout else read_timeout
            result = _run_command(
                connection,
                command,
                ac_device,
                collect_run_uuid,
                read_timeout=timeout,
                context=context,
                preserve_echo=bool(per_command_read_timeout),
                detect_cli_failures=detect_cli_failures,
            )
            if _should_treat_enable_console_timeout_as_success(command_results, result):
                result = _success_with_read_timeout_warning(result, ac_device, collect_run_uuid)
            command_results.append(result)
            if result.success:
                outputs[command] = result.output
        return command_results, outputs
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
    try:
        _safe_log_info("FIT_AP_OPTICAL_AP_STARTED", _detail(ac_device, collect_run_uuid, ap=ap_name))
        target = choose_connection_target(temp_device)
        if target is None:
            raise RuntimeError("AP Telnet target unavailable")
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(target))
        command_guard.validate_command_list(FIT_AP_OPTICAL_COMMANDS, "fit_ap_optical_collect")
        outputs: dict[str, str] = {}
        for command in FIT_AP_OPTICAL_COMMANDS:
            result = _run_command(connection, command, temp_device, collect_run_uuid, read_timeout=15, context="fit_ap_optical_collect")
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
            _safe_log_info("FIT_AP_OPTICAL_NEIGHBOR_MATCHED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=f"matched_by={match.matched_by}"))
        else:
            _safe_log_warning("FIT_AP_OPTICAL_NEIGHBOR_MATCH_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name))
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
        error_message = None if success else _command_error_summary(command_results) or "no optical data parsed"
        if error_message:
            error_message = _fit_ap_optical_error_message(_fit_ap_optical_error_category(error_message), error_message)
        _safe_log_info("FIT_AP_OPTICAL_AP_SUCCESS" if success else "FIT_AP_OPTICAL_AP_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name, error="" if success else error_message or "no optical data parsed"))
        return {**base, **parsed, "status": status, "error_message": error_message}
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), temp_device)
        category = _fit_ap_optical_error_category(message)
        trace = _sanitized_traceback(exc, temp_device)
        try:
            _write_raw_files(raw_log_file, commands_file, temp_device, collect_run_uuid, command_results, fatal_error=message)
        except Exception as raw_exc:
            raw_message = sanitize_sensitive_text(str(raw_exc), temp_device)
            _safe_log_warning("FIT_AP_OPTICAL_RAW_LOG_WRITE_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=raw_message))
        _safe_log_error("FIT_AP_OPTICAL_AP_FAILED", _detail(ac_device, collect_run_uuid, ap=ap_name, error=f"category={category}, error={message}, traceback={trace}"))
        return {**base, **_failed_fit_ap_optical_row(ac_device, ap_row, collect_run_uuid, category, message, raw_log_path=relative_raw_log_path)}
    finally:
        if connection is not None:
            _disconnect(connection)


def _run_command(
    connection,
    command: str,
    device: Device,
    collect_run_uuid: str,
    read_timeout: int = 30,
    context: str = "ac_collect",
    preserve_echo: bool = False,
    detect_cli_failures: bool = False,
) -> CommandResult:
    reason = command_guard.command_reject_reason(command, context)
    if reason:
        command_guard.log_command_rejected(command, context, reason)
        return CommandResult(command=command, success=False, error_message=reason)
    _safe_log_info("COMMAND_ALLOWED", _detail(device, collect_run_uuid, command=command))
    try:
        output = netmiko_connection.safe_send_command(
            connection,
            command,
            read_timeout=read_timeout,
            strip_prompt=False if preserve_echo else None,
            strip_command=False if preserve_echo else None,
            use_timing=True,
            encoding=netmiko_connection.encoding_for_vendor(device.device_vendor),
        )
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), device)
        return CommandResult(command=command, success=False, error_message=message)
    output_text = str(output or "")
    if detect_cli_failures and _contains_cli_failure(output_text):
        return CommandResult(command=command, success=False, output=output_text, error_message=_cli_failure_summary(output_text))
    return CommandResult(command=command, success=True, output=output_text)


def _should_treat_enable_console_timeout_as_success(previous_results: list[CommandResult], result: CommandResult) -> bool:
    if result.success or result.command not in ENABLE_FIT_AP_CONSOLE_TAIL_COMMANDS:
        return False
    if not _is_read_timeout_message(result.error_message or ""):
        return False
    combined_text = "\n".join([*(item.output or "" for item in previous_results), result.output or "", result.error_message or ""])
    if _contains_cli_failure(combined_text):
        return False
    return any(item.command == ENABLE_FIT_AP_CONSOLE_MAIN_COMMAND and item.success for item in previous_results)


def _success_with_read_timeout_warning(result: CommandResult, device: Device, collect_run_uuid: str) -> CommandResult:
    warning = "warning: read timeout after command, treated as success because key commands completed"
    _safe_log_warning(
        "AC_ENABLE_AP_CONSOLE_READ_TIMEOUT_TREATED_SUCCESS",
        _detail(device, collect_run_uuid, command=result.command, error=warning),
    )
    output = "\n".join(part for part in (result.output, warning) if part)
    return CommandResult(command=result.command, success=True, output=output, error_message=warning)


def _is_read_timeout_message(message: str) -> bool:
    normalized = str(message or "").casefold()
    return any(marker in normalized for marker in READ_TIMEOUT_MARKERS)


def _contains_cli_failure(text: str) -> bool:
    return any(marker.casefold() in str(text or "").casefold() for marker in CLI_FAILURE_MARKERS)


def _cli_failure_summary(output: str) -> str:
    for line in str(output or "").splitlines():
        if _contains_cli_failure(line):
            return line.strip()[:200] or "命令执行失败"
    return "命令执行失败"


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
