from __future__ import annotations

import json
import re
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services import command_guard

PROFILE_NAME = "device_sftp_command_profiles.json"
OPERATION_ID = "device.sftp.enable"


class SftpCommandProfileError(ValueError):
    pass


def _profile_path(paths: PathResolver | None = None) -> Path:
    resolver = paths or PathResolver()
    return resolver.app_root / "resources" / PROFILE_NAME


def _major(version: str) -> str:
    value = str(version or "").strip().upper()
    match = re.search(r"(?:COMWARE|VERSION\s*)?V?(\d+)", value)
    return f"V{match.group(1)}" if match else ""


def resolve_sftp_enable_commands(
    *,
    vendor: str,
    role: str,
    platform: str,
    software_version: str,
    username: str,
    paths: PathResolver | None = None,
) -> tuple[str, ...]:
    if not all(str(value or "").strip() for value in (vendor, role, platform, software_version, username)):
        raise SftpCommandProfileError("设备厂商、角色、平台、完整版本和用户名必须明确")
    if str(vendor).strip().casefold() != "h3c" or str(role).strip().casefold() != "switch" or str(platform).strip().casefold() != "comware":
        raise SftpCommandProfileError("当前设备不在已验证的 SFTP 启用 Profile 范围内")
    try:
        payload = json.loads(_profile_path(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SftpCommandProfileError("SFTP 启用 Profile 不可用") from exc
    rows = payload.get("profiles") if isinstance(payload, dict) else None
    major = _major(software_version)
    matches = [
        row for row in rows or []
        if isinstance(row, dict)
        and str(row.get("operation_id")) == OPERATION_ID
        and str(row.get("vendor", "")).casefold() == str(vendor).casefold()
        and str(row.get("role", "")).casefold() == str(role).casefold()
        and str(row.get("platform", "")).casefold() == str(platform).casefold()
        and str(row.get("software_major", "")).upper() == major
    ]
    if len(matches) != 1:
        raise SftpCommandProfileError("未找到当前设备版本的 SFTP 启用 Profile")
    commands = tuple(str(item).replace("{username}", str(username).strip()) for item in matches[0].get("commands", []))
    if not commands:
        raise SftpCommandProfileError("SFTP 启用 Profile 没有命令步骤")
    command_guard.validate_command_list(commands, OPERATION_ID)
    return commands


__all__ = ["OPERATION_ID", "SftpCommandProfileError", "resolve_sftp_enable_commands"]
