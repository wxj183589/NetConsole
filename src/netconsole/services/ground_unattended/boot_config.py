from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import (
    Device,
    is_device_eligible_for_automatic_collection,
)
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.parsers.h3c.info_center_parser import (
    InfoCenterRuntime,
    parse_info_center_runtime,
)
from netconsole.parsers.h3c.device_clock_parser import parse_h3c_device_clock
from netconsole.parsers.h3c.version_parser import parse_version
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.command_guard import validate_command_list
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.online_mr_collector import NetmikoShellConnection


READ_COMMANDS = (
    "screen-length disable",
    "display clock",
    "display version",
    "display clock",
    "display info-center",
    "display current-configuration | include info-center",
)
CONFIG_FAILURE_MARKERS = (
    "% unrecognized command",
    "% incomplete command",
    "% wrong parameter",
    "% error",
    "error:",
    "permission denied",
)
SOURCE_RULE_COMMANDS = (
    "info-center source default loghost deny",
    "info-center source wmesh loghost level notification",
    "info-center source ifnet loghost level notification",
    "info-center source cfgman loghost level notification",
)
MANAGED_PROFILE_VERSION = 2
RUNTIME_REQUIREMENTS = (
    "information_center_enabled",
    "loghost_enabled",
    "loghost_target",
)
SENSITIVE_EVIDENCE_LINE_RE = re.compile(
    r"\b(?:password|passwd|secret|community|token|private[-_ ]?key|cipher)\b",
    re.IGNORECASE,
)


class MrCommandConnection(Protocol):
    def send_command(self, command: str, timeout: int) -> str: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SyslogConfigDiff:
    complete: bool
    source_rule_missing: tuple[str, ...]
    source_rules: tuple[str, ...]

    @property
    def missing_commands(self) -> tuple[str, ...]:
        """Compatibility alias for callers that inspect source-rule differences."""

        return self.source_rule_missing


@dataclass(frozen=True)
class SyslogProfileVerification:
    complete: bool
    config: SyslogConfigDiff
    runtime_missing: tuple[str, ...]
    source_rule_missing: tuple[str, ...]
    repair_commands: tuple[str, ...]
    runtime: InfoCenterRuntime
    target_statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class MrConfigCheckResult:
    device_uuid: str
    boot_session_id: str
    new_boot_session: bool
    uptime_seconds: int
    estimated_boot_time: str
    config_status: str
    audit_id: str
    applied_commands: tuple[str, ...]


class MrBootSessionService:
    def __init__(
        self,
        *,
        repository: GroundUnattendedRepository,
        tolerance_seconds: int = 120,
    ) -> None:
        self.repository = repository
        self.tolerance_seconds = max(10, int(tolerance_seconds))

    def observe(
        self,
        *,
        device_uuid: str,
        device_id: int | None,
        train_id: str,
        mr_role: str,
        checked_at: datetime,
        uptime_seconds: int,
        evidence_path: str,
        device_clock_before: datetime | None = None,
        device_clock_after: datetime | None = None,
        boot_time_uncertainty_seconds: int = 60,
        reboot_reason: str = "",
        timezone_name: str = "",
        utc_offset_seconds: int | None = None,
        time_quality: str = "LOCAL_FALLBACK",
    ) -> tuple[dict[str, Any], bool]:
        if device_clock_before is not None and device_clock_after is not None:
            midpoint = device_clock_before + (
                device_clock_after - device_clock_before
            ) / 2
            estimated = midpoint - timedelta(seconds=uptime_seconds)
        else:
            estimated = checked_at - timedelta(seconds=uptime_seconds)
            time_quality = "LOCAL_FALLBACK"
        current = self.repository.latest_boot_session(device_uuid)
        same_boot = False
        clock_jump_seconds: float | None = None
        if current is not None:
            previous_estimated = _datetime_or_none(str(current.get("estimated_boot_time") or ""))
            previous_checked = _datetime_or_none(
                str(current.get("last_checked_at") or "")
            )
            previous_uptime = int(current.get("last_uptime_seconds") or 0)
            estimated_delta_seconds = (
                (estimated - previous_estimated).total_seconds()
                if previous_estimated is not None
                else None
            )
            uptime_rolled_back = (
                uptime_seconds + self.tolerance_seconds < previous_uptime
            )
            elapsed_seconds = (
                max(0.0, (checked_at - previous_checked).total_seconds())
                if previous_checked is not None
                else 0.0
            )
            uptime_reset_during_gap = (
                elapsed_seconds > self.tolerance_seconds
                and uptime_seconds + self.tolerance_seconds
                < previous_uptime + elapsed_seconds
            )
            boot_estimate_changed = (
                estimated_delta_seconds is not None
                and abs(estimated_delta_seconds) > self.tolerance_seconds
            )
            same_boot = bool(
                previous_estimated
                and not uptime_rolled_back
                and not (uptime_reset_during_gap and boot_estimate_changed)
            )
            if same_boot and previous_estimated is not None:
                clock_jump_seconds = estimated_delta_seconds
                if (
                    time_quality == "DEVICE_CLOCK"
                    and clock_jump_seconds is not None
                    and abs(clock_jump_seconds) > self.tolerance_seconds
                ):
                    time_quality = "CLOCK_JUMP"
                    self.repository.add_event(
                        event_type="device_clock_jump",
                        severity="warning",
                        train_id=train_id,
                        mr_id=device_uuid,
                        title="检测到设备时钟跳变",
                        message="uptime 连续增长，保持原 Boot Session，不将 NTP 校时误判为重启。",
                        details={
                            "clock_jump_seconds": round(clock_jump_seconds, 3),
                            "previous_uptime_seconds": previous_uptime,
                            "current_uptime_seconds": uptime_seconds,
                        },
                    )
        now_text = checked_at.isoformat(timespec="milliseconds")
        clock_before_text = (
            device_clock_before.isoformat(timespec="milliseconds")
            if device_clock_before is not None
            else ""
        )
        clock_after_text = (
            device_clock_after.isoformat(timespec="milliseconds")
            if device_clock_after is not None
            else ""
        )
        time_values = {
            "device_clock_before": clock_before_text,
            "device_clock_after": clock_after_text,
            "boot_time_uncertainty_seconds": max(
                1, int(boot_time_uncertainty_seconds)
            ),
            "reboot_reason": str(reboot_reason or ""),
            "timezone_name": str(timezone_name or ""),
            "utc_offset_seconds": utc_offset_seconds,
            "time_quality": time_quality,
            "clock_jump_seconds": clock_jump_seconds,
        }
        if same_boot and current is not None:
            row = dict(current)
            row.update(
                {
                    "last_checked_at": now_text,
                    "estimated_boot_time": estimated.isoformat(timespec="milliseconds"),
                    "last_uptime_seconds": uptime_seconds,
                    "version_evidence_path": evidence_path,
                    **time_values,
                }
            )
            created = False
        else:
            row = {
                "boot_session_id": f"boot_{uuid.uuid4().hex}",
                "device_uuid": device_uuid,
                "device_id": device_id,
                "train_id": train_id,
                "mr_role": mr_role,
                "first_detected_at": now_text,
                "last_checked_at": now_text,
                "estimated_boot_time": estimated.isoformat(timespec="milliseconds"),
                "first_uptime_seconds": uptime_seconds,
                "last_uptime_seconds": uptime_seconds,
                **time_values,
                "version_evidence_path": evidence_path,
                "config_status": "NOT_CHECKED",
                "config_checked_at": "",
                "config_applied_at": "",
                "first_syslog_received_at": "",
                "last_syslog_received_at": "",
                "config_fingerprint": "",
                "info_center_metrics": {},
            }
            created = True
        self.repository.upsert_boot_session(row)
        return row, created


class MrSyslogConfigService:
    """固定 Profile 的 MR 临时 Syslog 检查；不执行 save，也不在停止时撤销。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundUnattendedRepository,
        connection_factory: Callable[[OnlineMrConnectionConfig], MrCommandConnection] = NetmikoShellConnection,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.connection_factory = connection_factory
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())

    def check(
        self,
        *,
        run_id: str,
        run_date: str,
        device_uuid: str,
        target_ip: str,
        target_port: int,
        boot_tolerance_seconds: int,
        repair_enabled: bool = True,
        allow_target_port_change: bool = False,
    ) -> MrConfigCheckResult:
        target_ip = str(ipaddress.ip_address(str(target_ip).strip()))
        target_port = int(target_port)
        if not 1 <= target_port <= 65_535:
            raise ValueError("Syslog 目标端口必须在 1～65535 之间")
        endpoint = self.repository.get_inventory_endpoint(device_uuid)
        if endpoint is None or endpoint.get("binding_status") != "ACTIVE":
            raise ValueError("MR 不在当前无人值守设备清单中")
        device = DeviceRepository(Database(self.paths.site_db_path(self.site_id))).get_by_uuid(device_uuid)
        if device is None:
            raise ValueError("设备管理中已找不到 MR")
        if not is_device_eligible_for_automatic_collection(device):
            raise ValueError("MR 当前不参与本次调试，已退出无人值守自动任务")
        if str(device.device_vendor or "H3C").casefold() != "h3c":
            raise ValueError("当前 Syslog Profile 仅适配 H3C MR")
        config = _connection_config(self.site_id, device)
        validate_command_list(READ_COMMANDS, "ground_unattended_syslog_read")
        checked_at = self.now_provider()
        audit_id = f"sysaudit_{uuid.uuid4().hex}"
        connection: MrCommandConnection | None = None
        evidence: dict[str, Any] = {
            "display_clock_before": "",
            "display_version": "",
            "display_clock_after": "",
            "device_time_quality": "",
            "device_time_error": "",
            "display_info_center_before": "",
            "configuration_before": "",
            "configuration_before_command": "",
            "configuration_before_fallback_used": False,
            "repair_commands": [],
            "applied_commands": [],
            "command_results": [],
            "display_info_center_after": "",
            "configuration_after": "",
            "configuration_after_command": "",
            "configuration_after_fallback_used": False,
            "missing_before": {},
            "missing_after": {},
            "checked_at": checked_at.isoformat(timespec="milliseconds"),
            "verified_at": "",
            "allow_target_port_change": bool(allow_target_port_change),
            "syslog_auto_repair_enabled": bool(repair_enabled),
            "managed_profile_version": MANAGED_PROFILE_VERSION,
        }
        applied: tuple[str, ...] = ()
        boot: dict[str, Any] | None = None
        created = False
        evidence_path = ""
        status = "CONFIG_FAILED"
        try:
            connection = self.connection_factory(config)
            screen_output = str(connection.send_command(READ_COMMANDS[0], config.command_timeout) or "")
            if _command_failed(screen_output):
                raise RuntimeError("screen-length disable 执行失败")
            clock_before_output = str(
                connection.send_command(READ_COMMANDS[1], config.command_timeout)
                or ""
            )
            if _command_failed(clock_before_output):
                raise RuntimeError("第一次 display clock 执行失败")
            evidence["display_clock_before"] = clock_before_output
            version_output = str(connection.send_command(READ_COMMANDS[2], config.command_timeout) or "")
            if _command_failed(version_output):
                raise RuntimeError("display version 执行失败")
            evidence["display_version"] = version_output
            clock_after_output = str(
                connection.send_command(READ_COMMANDS[3], config.command_timeout)
                or ""
            )
            if _command_failed(clock_after_output):
                raise RuntimeError("第二次 display clock 执行失败")
            evidence["display_clock_after"] = clock_after_output
            parsed_version = parse_version(version_output)
            uptime_seconds = parsed_version.get("uptime_seconds")
            if not isinstance(uptime_seconds, int):
                raise ValueError("display version 未解析到有效 uptime")
            uptime_precision = int(
                parsed_version.get("uptime_precision_seconds") or 60
            )
            clock_before = None
            clock_after = None
            timezone_name = ""
            utc_offset_seconds: int | None = None
            time_quality = "DEVICE_CLOCK"
            try:
                parsed_clock_before = parse_h3c_device_clock(clock_before_output)
                parsed_clock_after = parse_h3c_device_clock(clock_after_output)
                if (
                    parsed_clock_before.utc_offset_seconds
                    != parsed_clock_after.utc_offset_seconds
                ):
                    raise ValueError("两次 display clock 的 UTC 偏移不一致")
                clock_window_seconds = (
                    parsed_clock_after.timestamp
                    - parsed_clock_before.timestamp
                ).total_seconds()
                if clock_window_seconds < 0 or clock_window_seconds > 600:
                    raise ValueError("两次 display clock 的设备时间窗口异常")
                clock_before = parsed_clock_before.timestamp
                clock_after = parsed_clock_after.timestamp
                timezone_name = (
                    parsed_clock_after.timezone_name
                    or parsed_clock_before.timezone_name
                )
                utc_offset_seconds = parsed_clock_after.utc_offset_seconds
                boot_uncertainty = max(
                    uptime_precision,
                    int(abs(clock_window_seconds) / 2 + 0.999),
                )
            except ValueError as exc:
                time_quality = "LOCAL_FALLBACK"
                boot_uncertainty = max(uptime_precision, boot_tolerance_seconds)
                evidence["device_time_error"] = str(exc)
            evidence["device_time_quality"] = time_quality
            evidence_path = self._write_evidence(
                run_date,
                device_uuid,
                audit_id,
                evidence,
            )
            boot, created = MrBootSessionService(
                repository=self.repository,
                tolerance_seconds=boot_tolerance_seconds,
            ).observe(
                device_uuid=device_uuid,
                device_id=device.id,
                train_id=str(endpoint.get("train_id") or ""),
                mr_role=str(endpoint.get("mr_role") or ""),
                checked_at=checked_at,
                uptime_seconds=uptime_seconds,
                evidence_path=evidence_path,
                device_clock_before=clock_before,
                device_clock_after=clock_after,
                boot_time_uncertainty_seconds=boot_uncertainty,
                reboot_reason=str(parsed_version.get("last_reboot_reason") or ""),
                timezone_name=timezone_name,
                utc_offset_seconds=utc_offset_seconds,
                time_quality=time_quality,
            )

            info_before = str(connection.send_command(READ_COMMANDS[4], config.command_timeout) or "")
            if _command_failed(info_before):
                raise RuntimeError("display info-center 执行失败")
            evidence["display_info_center_before"] = info_before
            config_before, before_command, before_fallback = self._read_configuration(
                connection, config.command_timeout
            )
            evidence["configuration_before"] = config_before
            evidence["configuration_before_command"] = before_command
            evidence["configuration_before_fallback_used"] = before_fallback
            before = verify_syslog_profile(
                info_before,
                config_before,
                target_ip=target_ip,
                target_port=target_port,
                allow_target_port_change=allow_target_port_change,
            )
            evidence["missing_before"] = _verification_evidence(before)
            evidence["repair_commands"] = list(before.repair_commands)

            info_after = info_before
            config_after = config_before
            after_command = before_command
            after_fallback = before_fallback
            verified = before.complete
            if before.complete:
                status = "CONFIG_PRESENT"
            elif (
                "TARGET_PORT_CONFLICT" in before.target_statuses
                and not allow_target_port_change
            ):
                status = "TARGET_PORT_CONFLICT"
            elif not repair_enabled:
                status = "AUTO_REPAIR_DISABLED"
            else:
                applied = build_syslog_config_commands(before.repair_commands)
                evidence["applied_commands"] = list(applied)
                if applied:
                    _validate_syslog_write_commands(applied, target_ip=target_ip, target_port=target_port)
                    expected_until = self.now_provider() + timedelta(seconds=15)
                    self.repository.mark_expected_config_change(
                        device_uuid=device_uuid,
                        operation_id=audit_id,
                        expected_started_at=self.now_provider().isoformat(
                            timespec="milliseconds"
                        ),
                        expected_until=expected_until.isoformat(
                            timespec="milliseconds"
                        ),
                    )
                    evidence["expected_change_until"] = (
                        expected_until.isoformat(timespec="milliseconds")
                    )
                    for command in applied:
                        output = str(connection.send_command(command, config.command_timeout) or "")
                        command_result = {
                            "command": command,
                            "output": output,
                            "failed": _command_failed(output),
                        }
                        evidence["command_results"].append(command_result)
                        if command_result["failed"]:
                            raise RuntimeError(f"Syslog 配置命令执行失败：{command}")
                info_after = str(connection.send_command(READ_COMMANDS[4], config.command_timeout) or "")
                if _command_failed(info_after):
                    raise RuntimeError("display info-center 复查失败")
                config_after, after_command, after_fallback = self._read_configuration(
                    connection, config.command_timeout
                )
                after = verify_syslog_profile(
                    info_after,
                    config_after,
                    target_ip=target_ip,
                    target_port=target_port,
                    allow_target_port_change=allow_target_port_change,
                )
                verified = after.complete
                if verified:
                    status = "CONFIG_SENT" if _profile_fully_missing(before) else "CONFIG_REPAIRED"
                else:
                    status = "CONFIG_VERIFY_FAILED"

            after = verify_syslog_profile(
                info_after,
                config_after,
                target_ip=target_ip,
                target_port=target_port,
                allow_target_port_change=allow_target_port_change,
            )
            evidence["display_info_center_after"] = info_after
            evidence["configuration_after"] = config_after
            evidence["configuration_after_command"] = after_command
            evidence["configuration_after_fallback_used"] = after_fallback
            evidence["missing_after"] = _verification_evidence(after)
            if verified:
                evidence["verified_at"] = self.now_provider().isoformat(timespec="milliseconds")
            evidence_path = self._write_evidence(
                run_date,
                device_uuid,
                audit_id,
                evidence,
            )
            fingerprint = _syslog_config_fingerprint(
                after,
                target_ip=target_ip,
                target_port=target_port,
            )
            metrics = after.runtime.as_dict()
            metrics["managed_target"] = {
                "ip": target_ip,
                "port": target_port,
                "statuses": list(after.target_statuses),
            }
            previous_metrics = dict(boot.get("info_center_metrics") or {})
            boot_status = _verified_boot_status(boot) if verified else status
            boot.update(
                {
                    "config_status": boot_status,
                    "config_checked_at": checked_at.isoformat(timespec="milliseconds"),
                    "config_applied_at": checked_at.isoformat(timespec="milliseconds") if applied else str(boot.get("config_applied_at") or ""),
                    "config_fingerprint": fingerprint,
                    "version_evidence_path": evidence_path,
                    "info_center_metrics": metrics,
                }
            )
            self.repository.upsert_boot_session(boot)
            self._record_info_center_metric_changes(
                run_id=run_id,
                device_uuid=device_uuid,
                previous=previous_metrics,
                current=metrics,
            )
            self.repository.save_syslog_config_audit(
                {
                    "audit_id": audit_id,
                    "boot_session_id": boot["boot_session_id"],
                    "device_uuid": device_uuid,
                    "train_id": endpoint.get("train_id", ""),
                    "mr_role": endpoint.get("mr_role", ""),
                    "checked_at": checked_at.isoformat(timespec="milliseconds"),
                    "target_ip": target_ip,
                    "target_port": target_port,
                    "status": status,
                    "missing_commands": list(before.repair_commands),
                    "applied_commands": list(applied),
                    "evidence_path": evidence_path,
                    "evidence_sha256": _sha256(self.repository.db_path.parent / evidence_path),
                    "managed_profile_version": MANAGED_PROFILE_VERSION,
                }
            )
            if status == "CONFIG_VERIFY_FAILED":
                self.repository.add_health_event(
                    run_id=run_id,
                    component="mr_syslog_config",
                    severity="warning",
                    code="CONFIG_VERIFY_FAILED",
                    message="MR Syslog 配置写入后未通过运行态和配置规则复查",
                    details={"device_uuid": device_uuid, "missing_after": evidence["missing_after"]},
                )
            if status == "TARGET_PORT_CONFLICT":
                self.repository.add_health_event(
                    run_id=run_id,
                    component="mr_syslog_config",
                    severity="warning",
                    code="TARGET_PORT_CONFLICT",
                    message="设备已存在同 IP 的其他 Syslog 端口，配置检查保持只读",
                    details={
                        "device_uuid": device_uuid,
                        "target_statuses": list(before.target_statuses),
                    },
                )
            if (
                allow_target_port_change
                and "TARGET_PORT_CONFLICT" in before.target_statuses
                and applied
            ):
                self.repository.add_event(
                    run_id=run_id,
                    event_type="mr_loghost_port_changed",
                    severity="warning",
                    train_id=str(endpoint.get("train_id") or ""),
                    mr_id=device_uuid,
                    title="用户确认修改 MR 日志目标端口",
                    message="已按明确确认修改 NetConsole 管理目标的端口；其他 IP 的日志目标保持不变。",
                    details={
                        "audit_id": audit_id,
                        "target_ip": target_ip,
                        "target_port": target_port,
                        "risk_level": "high",
                    },
                )
            self.repository.add_event(
                run_id=run_id,
                event_type="mr_boot_session_created" if created else "mr_config_checked",
                train_id=str(endpoint.get("train_id") or ""),
                mr_id=device_uuid,
                title="MR 新上电周期已确认" if created else "MR Syslog 配置已检查",
                message=status,
                details={"boot_session_id": boot["boot_session_id"], "config_status": status},
            )
            return MrConfigCheckResult(
                device_uuid=device_uuid,
                boot_session_id=str(boot["boot_session_id"]),
                new_boot_session=created,
                uptime_seconds=uptime_seconds,
                estimated_boot_time=str(boot["estimated_boot_time"]),
                config_status=status,
                audit_id=audit_id,
                applied_commands=applied,
            )
        except Exception as exc:
            evidence["error_code"] = exc.__class__.__name__
            evidence["error_message"] = str(exc)
            try:
                evidence_path = self._write_evidence(run_date, device_uuid, audit_id, evidence)
            except OSError:
                pass
            if boot is not None:
                boot.update(
                    {
                        "config_status": "CONFIG_FAILED",
                        "config_checked_at": checked_at.isoformat(timespec="milliseconds"),
                        "version_evidence_path": evidence_path or str(boot.get("version_evidence_path") or ""),
                    }
                )
                self.repository.upsert_boot_session(boot)
            self.repository.save_syslog_config_audit(
                {
                    "audit_id": audit_id,
                    "boot_session_id": str((boot or {}).get("boot_session_id") or ""),
                    "device_uuid": device_uuid,
                    "train_id": endpoint.get("train_id", ""),
                    "mr_role": endpoint.get("mr_role", ""),
                    "checked_at": checked_at.isoformat(timespec="milliseconds"),
                    "target_ip": target_ip,
                    "target_port": target_port,
                    "status": "CONFIG_FAILED",
                    "applied_commands": list(applied),
                    "evidence_path": evidence_path,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "managed_profile_version": MANAGED_PROFILE_VERSION,
                }
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="mr_config_check_failed",
                severity="error",
                train_id=str(endpoint.get("train_id") or ""),
                mr_id=device_uuid,
                title="MR Syslog 配置检查失败",
                message=f"{exc.__class__.__name__}: {exc}",
            )
            self.repository.add_health_event(
                run_id=run_id,
                component="mr_syslog_config",
                severity="error",
                code="CONFIG_FAILED",
                message=f"{exc.__class__.__name__}: {exc}",
                details={"device_uuid": device_uuid, "audit_id": audit_id},
            )
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _read_configuration(
        connection: MrCommandConnection, timeout: int
    ) -> tuple[str, str, bool]:
        command = "display current-configuration | include info-center"
        output = str(connection.send_command(command, timeout) or "")
        if not _command_failed(output):
            return output, command, False
        fallback = "display current-configuration"
        validate_command_list((fallback,), "ground_unattended_syslog_read")
        output = str(connection.send_command(fallback, timeout) or "")
        if _command_failed(output):
            raise RuntimeError("display current-configuration 执行失败")
        return output, fallback, True

    def _record_info_center_metric_changes(
        self,
        *,
        run_id: str,
        device_uuid: str,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> None:
        previous = previous or {}
        for metric, code, severity, message in (
            (
                "dropped_messages",
                "INFO_CENTER_DROPPED_MESSAGES_INCREASED",
                "warning",
                "设备 Information Center dropped messages 计数增长，可能影响日志数据完整性",
            ),
            (
                "overwritten_messages",
                "INFO_CENTER_BUFFER_OVERWRITTEN_INCREASED",
                "info",
                "设备本地 Information Center 环形缓冲覆盖计数增长，不等同于 UDP 网络丢包",
            ),
        ):
            before = _int_or_none(previous.get(metric))
            after = _int_or_none(current.get(metric))
            if before is not None and after is not None and after > before:
                self.repository.add_health_event(
                    run_id=run_id,
                    component="mr_info_center",
                    severity=severity,
                    code=code,
                    message=message,
                    details={
                        "device_uuid": device_uuid,
                        "metric": metric,
                        "previous": before,
                        "current": after,
                        "increase": after - before,
                    },
                )

    def _write_evidence(
        self, run_date: str, device_uuid: str, audit_id: str, payload: dict[str, Any]
    ) -> str:
        root = self.paths.ground_unattended_active_dir(self.site_id, run_date)
        path = root / "evidence" / _safe_component(device_uuid) / f"{audit_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_suffix(".json.part")
        staging.write_text(
            json.dumps(sanitize_syslog_evidence(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging.replace(path)
        return path.relative_to(self.repository.db_path.parent).as_posix()


def analyze_syslog_config(output: str, *, target_ip: str, target_port: int) -> SyslogConfigDiff:
    """Inspect only source rules whose authority is current-configuration.

    Information Center enablement and the effective loghost target are runtime facts
    reported by ``display info-center``. Comware may omit their default command forms
    from current-configuration, so they must not participate in this diff.
    """

    lines = {_normalize(line) for line in str(output or "").splitlines() if line.strip()}
    _ = str(ipaddress.ip_address(str(target_ip).strip()))
    port = int(target_port)
    if not 1 <= port <= 65_535:
        raise ValueError("Syslog 目标端口必须在 1～65535 之间")
    present = tuple(command for command in SOURCE_RULE_COMMANDS if command in lines)
    missing = tuple(command for command in SOURCE_RULE_COMMANDS if command not in lines)
    return SyslogConfigDiff(
        complete=not missing,
        source_rule_missing=missing,
        source_rules=present,
    )


def verify_syslog_profile(
    info_center_output: str,
    configuration_output: str,
    *,
    target_ip: str,
    target_port: int,
    allow_target_port_change: bool = False,
) -> SyslogProfileVerification:
    """Require both runtime delivery state and the fixed source rules."""

    target_ip = str(ipaddress.ip_address(str(target_ip).strip()))
    target_port = int(target_port)
    runtime = parse_info_center_runtime(info_center_output)
    missing_runtime: list[str] = []
    if runtime.information_center_enabled is not True:
        missing_runtime.append("information_center_enabled")
    if runtime.loghost_enabled is not True:
        missing_runtime.append("loghost_enabled")
    exact_target = any(
        host.ip == target_ip and host.port == target_port
        for host in runtime.log_hosts
    )
    same_ip_other_port = any(
        host.ip == target_ip and host.port != target_port
        for host in runtime.log_hosts
    )
    target_statuses = [
        "TARGET_PRESENT"
        if exact_target
        else "TARGET_PORT_CONFLICT"
        if same_ip_other_port
        else "TARGET_MISSING"
    ]
    if any(host.ip != target_ip for host in runtime.log_hosts):
        target_statuses.append("OTHER_TARGETS_PRESENT")
    if not exact_target:
        missing_runtime.append("loghost_target")
    config = analyze_syslog_config(
        configuration_output,
        target_ip=target_ip,
        target_port=target_port,
    )
    runtime_missing = tuple(missing_runtime)
    repair_commands: list[str] = []
    port_conflict_blocked = same_ip_other_port and not allow_target_port_change
    if not port_conflict_blocked:
        if "information_center_enabled" in runtime_missing:
            repair_commands.append("info-center enable")
        if {"loghost_enabled", "loghost_target"}.intersection(runtime_missing):
            repair_commands.append(
                f"info-center loghost {target_ip} port {target_port}"
            )
        repair_commands.extend(config.source_rule_missing)
    return SyslogProfileVerification(
        complete=config.complete and not runtime_missing,
        config=config,
        runtime_missing=runtime_missing,
        source_rule_missing=config.source_rule_missing,
        repair_commands=tuple(repair_commands),
        runtime=runtime,
        target_statuses=tuple(target_statuses),
    )


def _verification_evidence(verification: SyslogProfileVerification) -> dict[str, Any]:
    return {
        "runtime": list(verification.runtime_missing),
        "source_rules": list(verification.source_rule_missing),
        "target_statuses": list(verification.target_statuses),
    }


def _profile_fully_missing(verification: SyslogProfileVerification) -> bool:
    return (
        set(verification.runtime_missing) == set(RUNTIME_REQUIREMENTS)
        and set(verification.source_rule_missing) == set(SOURCE_RULE_COMMANDS)
    )


def _syslog_config_fingerprint(
    verification: SyslogProfileVerification,
    *,
    target_ip: str,
    target_port: int,
) -> str:
    runtime = verification.runtime
    payload = {
        "managed_profile_version": MANAGED_PROFILE_VERSION,
        "target": {"ip": target_ip, "port": target_port},
        "runtime": {
            "information_center_enabled": runtime.information_center_enabled,
            "loghost_enabled": runtime.loghost_enabled,
            "log_hosts": sorted(
                (
                    {
                        "ip": host.ip,
                        "port": host.port,
                        "facility": host.facility.casefold(),
                    }
                    for host in runtime.log_hosts
                ),
                key=lambda item: (item["ip"], item["port"], item["facility"]),
            ),
            "loghost_timestamp_format": _normalize(runtime.loghost_timestamp_format),
            "other_output_timestamp_format": _normalize(
                runtime.other_output_timestamp_format
            ),
        },
        "source_rules": list(verification.config.source_rules),
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verified_boot_status(boot: dict[str, Any]) -> str:
    return "LOG_ACTIVE" if boot.get("last_syslog_received_at") else "WAITING_FIRST_LOG"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_syslog_config_commands(repair_commands: tuple[str, ...]) -> tuple[str, ...]:
    if not repair_commands:
        return ()
    return ("system-view", *repair_commands, "return")


def _validate_syslog_write_commands(
    commands: tuple[str, ...], *, target_ip: str, target_port: int
) -> None:
    allowed = {
        "system-view",
        "return",
        "info-center enable",
        f"info-center loghost {target_ip} port {target_port}",
        "info-center source default loghost deny",
        "info-center source wmesh loghost level notification",
        "info-center source ifnet loghost level notification",
        "info-center source cfgman loghost level notification",
    }
    if not commands or commands[0] != "system-view" or commands[-1] != "return":
        raise ValueError("Syslog 写入 Profile 缺少受控视图边界")
    if any(_normalize(command) not in allowed for command in commands):
        raise ValueError("Syslog 写入命令不在固定 Profile 白名单中")
    if any(
        re.search(
            r"\b(?:save|reboot|delete|reset|undo|shutdown|restart|startup|copy|format)\b",
            command,
            re.I,
        )
        for command in commands
    ):
        raise ValueError("Syslog 写入 Profile 包含禁止命令")


def _connection_config(site_id: str, device: Device) -> OnlineMrConnectionConfig:
    targets = tuple(connection_targets(device))
    if not targets:
        raise ValueError("设备没有可用的 SSH/Telnet 连接配置")
    first = targets[0]
    return OnlineMrConnectionConfig(
        site=site_id,
        mr_id=str(device.device_uuid or ""),
        mr_name=str(device.name or "MR"),
        safe_mr_name=_safe_component(str(device.name or device.device_uuid or "mr")),
        device_id=device.id,
        device_name=str(device.name or "MR"),
        host=first.host,
        protocol=first.protocol,
        port=first.port,
        username=first.username,
        password=first.password,
        command_timeout=20,
        connection_targets=targets,
    )


def _command_failed(output: str) -> bool:
    lowered = str(output or "").casefold()
    return any(marker in lowered for marker in CONFIG_FAILURE_MARKERS)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")[:100] or "mr"


def _datetime_or_none(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.astimezone()
    except (TypeError, ValueError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_syslog_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact credential-like lines before writing configuration audit evidence."""

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if not isinstance(value, str):
            return value
        return "\n".join(
            "[REDACTED sensitive configuration line]"
            if SENSITIVE_EVIDENCE_LINE_RE.search(line)
            else line
            for line in value.splitlines()
        )

    return redact(payload)


__all__ = [
    "MrBootSessionService",
    "MrConfigCheckResult",
    "MrSyslogConfigService",
    "MANAGED_PROFILE_VERSION",
    "SyslogConfigDiff",
    "SyslogProfileVerification",
    "analyze_syslog_config",
    "build_syslog_config_commands",
    "sanitize_syslog_evidence",
    "verify_syslog_profile",
]
