from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core.paths import PathResolver
from netconsole.core.windows_dpapi import protect_windows_data, unprotect_windows_data
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.netmiko_connection import ConnectionTarget, connection_targets


FitApTerminalProtocol = Literal["ssh", "telnet"]
FitApTerminalProfileScope = Literal["ac", "site"]


@dataclass(frozen=True)
class FitApRemoteTerminalProfile:
    site_id: str
    ac_id: str
    scope: FitApTerminalProfileScope
    protocol: FitApTerminalProtocol
    port: int
    username: str
    password: str
    source: str

    @property
    def password_configured(self) -> bool:
        return bool(self.password)


@dataclass(frozen=True)
class ResolvedFitApRemoteTerminal:
    device: Device
    target: ConnectionTarget
    source: str


class FitApRemoteTerminalProfileStore:
    """保存局点/AC 级 FIT-AP 登录资料；密码仅以 Windows DPAPI 密文落盘。"""

    SCHEMA_VERSION = 1

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.path = paths.config_dir / "fit_ap_remote_terminal_profiles.json"

    def resolve(self, site_id: str, ac_id: str) -> FitApRemoteTerminalProfile | None:
        data = self._read()
        profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
        for key, scope in ((self._key(site_id, ac_id), "ac"), (self._key(site_id, "*"), "site")):
            raw = profiles.get(key)
            if not isinstance(raw, dict):
                continue
            profile = self._profile(site_id, ac_id, scope, raw)
            if profile is not None:
                return profile
        return None

    def describe(self, site_id: str, ac_id: str) -> FitApRemoteTerminalProfile | None:
        return self.resolve(site_id, ac_id)

    def save(
        self,
        site_id: str,
        ac_id: str,
        *,
        scope: FitApTerminalProfileScope,
        protocol: FitApTerminalProtocol,
        port: int,
        username: str,
        password: str | None,
        clear_password: bool = False,
    ) -> FitApRemoteTerminalProfile:
        normalized_site = self._identifier(site_id, "局点")
        normalized_ac = self._identifier(ac_id, "AC")
        if scope not in {"ac", "site"}:
            raise ValueError("FIT-AP 登录配置范围无效")
        if protocol not in {"ssh", "telnet"}:
            raise ValueError("FIT-AP 登录协议只支持 SSH 或 Telnet")
        if not 1 <= int(port) <= 65535:
            raise ValueError("FIT-AP 登录端口必须在 1~65535 之间")
        key = self._key(normalized_site, normalized_ac if scope == "ac" else "*")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(self.path):
            data = self._read()
            profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
            profiles = dict(profiles)
            current = profiles.get(key) if isinstance(profiles.get(key), dict) else {}
            protected_password = str(current.get("password_protected") or "")
            if clear_password:
                protected_password = ""
            elif password is not None:
                protected_password = self._protect(normalized_site, key, password)
            profiles[key] = {
                "site_id": normalized_site,
                "ac_id": normalized_ac if scope == "ac" else "",
                "scope": scope,
                "protocol": protocol,
                "port": int(port),
                "username": str(username or "").strip(),
                "password_protected": protected_password,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            payload = {
                "schema_version": self.SCHEMA_VERSION,
                "profiles": profiles,
            }
            atomic_write_bytes(
                self.path,
                (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                replace=os.replace,
            )
        profile = self.resolve(normalized_site, normalized_ac)
        if profile is None:
            raise RuntimeError("FIT-AP 远程登录配置保存后无法读取")
        return profile

    def _profile(
        self,
        site_id: str,
        ac_id: str,
        scope: str,
        raw: dict[str, object],
    ) -> FitApRemoteTerminalProfile | None:
        protocol = str(raw.get("protocol") or "").casefold()
        if protocol not in {"ssh", "telnet"}:
            return None
        try:
            port = int(raw.get("port") or (22 if protocol == "ssh" else 23))
        except (TypeError, ValueError):
            return None
        if not 1 <= port <= 65535:
            return None
        key = self._key(site_id, ac_id if scope == "ac" else "*")
        protected = str(raw.get("password_protected") or "")
        password = self._unprotect(site_id, key, protected) if protected else ""
        return FitApRemoteTerminalProfile(
            site_id=site_id,
            ac_id=ac_id,
            scope="ac" if scope == "ac" else "site",
            protocol=protocol,
            port=port,
            username=str(raw.get("username") or "").strip(),
            password=password,
            source="ac_profile" if scope == "ac" else "site_profile",
        )

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": self.SCHEMA_VERSION, "profiles": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("FIT-AP 远程登录配置文件不可读，已保留原文件") from exc
        if not isinstance(value, dict):
            raise ValueError("FIT-AP 远程登录配置文件格式无效，已保留原文件")
        return value

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 128 or any(char in normalized for char in "\0\r\n"):
            raise ValueError(f"{label}标识无效")
        return normalized

    @classmethod
    def _key(cls, site_id: str, ac_id: str) -> str:
        return f"{cls._identifier(site_id, '局点')}::{cls._identifier(ac_id, 'AC')}"

    @staticmethod
    def _entropy(site_id: str, key: str) -> bytes:
        return f"netconsole\0fit-ap-remote-terminal\0{site_id}\0{key}".encode("utf-8")

    def _protect(self, site_id: str, key: str, password: str) -> str:
        protected = protect_windows_data(str(password).encode("utf-8"), self._entropy(site_id, key))
        return base64.urlsafe_b64encode(protected).decode("ascii")

    def _unprotect(self, site_id: str, key: str, value: str) -> str:
        try:
            protected = base64.urlsafe_b64decode(value.encode("ascii"))
            plain = unprotect_windows_data(protected, self._entropy(site_id, key))
            return plain.decode("utf-8")
        except (ValueError, UnicodeError, OSError, binascii.Error) as exc:
            raise ValueError("FIT-AP 远程登录凭据无法解密，请重新配置") from exc


class FitApRemoteTerminalProfileResolver:
    """按 AC Profile、局点 Profile、设备精确匹配的顺序解析 FIT-AP 登录资料。"""

    def __init__(
        self,
        profile_store: FitApRemoteTerminalProfileStore,
        device_repository: DeviceRepository,
    ) -> None:
        self.profile_store = profile_store
        self.device_repository = device_repository

    def resolve(self, site_id: str, ac_id: str, ap_ip: str, ap_name: str = "") -> ResolvedFitApRemoteTerminal | None:
        address = str(ap_ip or "").strip()
        profile = self.profile_store.resolve(site_id, ac_id)
        if profile is not None and profile.password_configured:
            device = self._profile_device(profile, address, ap_name)
            target = next(
                (item for item in connection_targets(device) if item.host == address and not item.via_tunnel),
                None,
            )
            if target is not None:
                return ResolvedFitApRemoteTerminal(device=device, target=target, source=profile.source)

        candidates = [
            device
            for device in self.device_repository.list()
            if address in {
                str(device.primary_address or "").strip(),
                str(device.backup_address or "").strip(),
            }
        ]
        if len(candidates) != 1:
            return None
        device = candidates[0]
        target = next(
            (
                item
                for item in connection_targets(device)
                if item.host == address and not item.via_tunnel and bool(str(item.password or ""))
            ),
            None,
        )
        if target is None:
            return None
        return ResolvedFitApRemoteTerminal(device=device, target=target, source="device_exact_ip_fallback")

    @staticmethod
    def _profile_device(profile: FitApRemoteTerminalProfile, address: str, ap_name: str) -> Device:
        ssh = profile.protocol == "ssh"
        return Device(
            name=str(ap_name or address),
            primary_address=address,
            device_type="Cloud-AP",
            protocol=profile.protocol,
            port=profile.port,
            username=profile.username,
            password=profile.password,
            ssh_enabled=int(ssh),
            ssh_port=profile.port if ssh else 22,
            ssh_username=profile.username if ssh else "",
            ssh_password=profile.password if ssh else "",
            telnet_enabled=int(not ssh),
            telnet_port=profile.port if not ssh else 23,
            telnet_username=profile.username if not ssh else "",
            telnet_password=profile.password if not ssh else "",
        )


__all__ = [
    "FitApRemoteTerminalProfile",
    "FitApRemoteTerminalProfileResolver",
    "FitApRemoteTerminalProfileStore",
    "ResolvedFitApRemoteTerminal",
]
