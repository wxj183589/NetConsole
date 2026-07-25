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
from netconsole.models.device import Device
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
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
    "display version",
    "display current-configuration | include info-center",
)
CONFIG_FAILURE_MARKERS = (
    "% unrecognized command",
    "% incomplete command",
    "% wrong parameter",
    "permission denied",
)


class MrCommandConnection(Protocol):
    def send_command(self, command: str, timeout: int) -> str: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SyslogConfigDiff:
    complete: bool
    missing_commands: tuple[str, ...]
    target_present: bool


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
    ) -> tuple[dict[str, Any], bool]:
        estimated = checked_at - timedelta(seconds=uptime_seconds)
        current = self.repository.latest_boot_session(device_uuid)
        same_boot = False
        if current is not None:
            previous_estimated = _datetime_or_none(str(current.get("estimated_boot_time") or ""))
            previous_uptime = int(current.get("last_uptime_seconds") or 0)
            same_boot = bool(
                previous_estimated
                and abs((estimated - previous_estimated).total_seconds()) <= self.tolerance_seconds
                and uptime_seconds + self.tolerance_seconds >= previous_uptime
            )
        now_text = checked_at.isoformat(timespec="milliseconds")
        if same_boot and current is not None:
            row = dict(current)
            row.update(
                {
                    "last_checked_at": now_text,
                    "estimated_boot_time": estimated.isoformat(timespec="milliseconds"),
                    "last_uptime_seconds": uptime_seconds,
                    "version_evidence_path": evidence_path,
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
                "version_evidence_path": evidence_path,
                "config_status": "NOT_CHECKED",
                "config_checked_at": "",
                "config_applied_at": "",
                "first_syslog_received_at": "",
                "last_syslog_received_at": "",
                "config_fingerprint": "",
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
        if str(device.device_vendor or "H3C").casefold() != "h3c":
            raise ValueError("当前 Syslog Profile 仅适配 H3C MR")
        config = _connection_config(self.site_id, device)
        validate_command_list(READ_COMMANDS, "ground_unattended_syslog_read")
        checked_at = self.now_provider()
        audit_id = f"sysaudit_{uuid.uuid4().hex}"
        connection: MrCommandConnection | None = None
        version_output = ""
        config_output = ""
        applied: tuple[str, ...] = ()
        boot: dict[str, Any] | None = None
        created = False
        evidence_path = ""
        try:
            connection = self.connection_factory(config)
            connection.send_command(READ_COMMANDS[0], config.command_timeout)
            version_output = str(connection.send_command(READ_COMMANDS[1], config.command_timeout) or "")
            parsed_version = parse_version(version_output)
            uptime_seconds = parsed_version.get("uptime_seconds")
            if not isinstance(uptime_seconds, int):
                raise ValueError("display version 未解析到有效 uptime")
            evidence_path = self._write_evidence(
                run_date,
                device_uuid,
                audit_id,
                {"display_version": version_output},
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
            )
            config_output = str(connection.send_command(READ_COMMANDS[2], config.command_timeout) or "")
            if _command_failed(config_output):
                validate_command_list(
                    ("display current-configuration",),
                    "ground_unattended_syslog_read",
                )
                config_output = str(
                    connection.send_command("display current-configuration", config.command_timeout) or ""
                )
            diff = analyze_syslog_config(config_output, target_ip=target_ip, target_port=target_port)
            status = "CONFIG_PRESENT"
            if not diff.complete:
                applied = build_syslog_config_commands(diff.missing_commands)
                _validate_syslog_write_commands(applied, target_ip=target_ip, target_port=target_port)
                for command in applied:
                    connection.send_command(command, config.command_timeout)
                status = "CONFIG_SENT" if len(diff.missing_commands) == 4 else "CONFIG_REPAIRED"
            evidence_path = self._write_evidence(
                run_date,
                device_uuid,
                audit_id,
                {
                    "display_version": version_output,
                    "display_current_configuration": config_output,
                    "applied_commands": list(applied),
                },
            )
            fingerprint = hashlib.sha256(
                f"{target_ip}:{target_port}\n{config_output}".encode("utf-8")
            ).hexdigest()
            boot.update(
                {
                    "config_status": "LOG_ACTIVE"
                    if boot.get("last_syslog_received_at")
                    else "WAITING_FIRST_LOG",
                    "config_checked_at": checked_at.isoformat(timespec="milliseconds"),
                    "config_applied_at": checked_at.isoformat(timespec="milliseconds") if applied else str(boot.get("config_applied_at") or ""),
                    "config_fingerprint": fingerprint,
                }
            )
            self.repository.upsert_boot_session(boot)
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
                    "missing_commands": list(diff.missing_commands),
                    "applied_commands": list(applied),
                    "evidence_path": evidence_path,
                    "evidence_sha256": _sha256(self.repository.db_path.parent / evidence_path),
                }
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
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def _write_evidence(
        self, run_date: str, device_uuid: str, audit_id: str, payload: dict[str, Any]
    ) -> str:
        root = self.paths.ground_unattended_active_dir(self.site_id, run_date)
        path = root / "evidence" / _safe_component(device_uuid) / f"{audit_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_suffix(".json.part")
        staging.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        staging.replace(path)
        return path.relative_to(self.repository.db_path.parent).as_posix()


def analyze_syslog_config(output: str, *, target_ip: str, target_port: int) -> SyslogConfigDiff:
    lines = {_normalize(line) for line in str(output or "").splitlines() if line.strip()}
    required = (
        "info-center enable",
        f"info-center loghost {target_ip} port {target_port}",
        "info-center source default loghost deny",
        "info-center source wmesh loghost level notification",
    )
    missing = tuple(command for command in required if _normalize(command) not in lines)
    return SyslogConfigDiff(
        complete=not missing,
        missing_commands=missing,
        target_present=required[1] not in missing,
    )


def build_syslog_config_commands(missing_commands: tuple[str, ...]) -> tuple[str, ...]:
    if not missing_commands:
        return ()
    return ("system-view", *missing_commands, "return")


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
    }
    if not commands or commands[0] != "system-view" or commands[-1] != "return":
        raise ValueError("Syslog 写入 Profile 缺少受控视图边界")
    if any(_normalize(command) not in allowed for command in commands):
        raise ValueError("Syslog 写入命令不在固定 Profile 白名单中")
    if any(re.search(r"\b(?:save|reboot|delete|reset|undo)\b", command, re.I) for command in commands):
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


__all__ = [
    "MrBootSessionService",
    "MrConfigCheckResult",
    "MrSyslogConfigService",
    "SyslogConfigDiff",
    "analyze_syslog_config",
    "build_syslog_config_commands",
]
