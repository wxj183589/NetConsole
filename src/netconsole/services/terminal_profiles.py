from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.core.windows_dpapi import protect_windows_data, unprotect_windows_data


_ENCODINGS = {"utf-8", "gbk", "ansi", "big5", "gb2312", "gb18030"}
_PROTOCOLS = {"SSH", "TELNET"}


class TerminalProfileError(ValueError):
    pass


class TerminalProfileStore:
    """Persist SecureCRT-style connection metadata and optional DPAPI secrets."""

    def __init__(self, paths: PathResolver) -> None:
        self.root = paths.config_dir / "terminal"
        self.path = self.root / "saved-sessions.json"
        self.secret_path = self.root / "saved-session-secrets.json"
        self._lock = threading.RLock()

    def document(self) -> dict[str, Any]:
        with self._lock:
            value = self._read_json(
                self.path,
                {"schema_version": 1, "folders": [], "profiles": []},
            )
            folders = [self._folder(item) for item in value.get("folders", [])]
            folder_ids = {item["folder_id"] for item in folders}
            secrets = self._read_secrets()
            profiles = [
                self._profile(item, folder_ids=folder_ids, password_configured=str(item.get("profile_id") or "") in secrets)
                for item in value.get("profiles", [])
            ]
            return {"schema_version": 1, "folders": folders, "profiles": profiles}

    def save_profile(
        self,
        values: dict[str, Any],
        *,
        profile_id: str = "",
        password: str | None = None,
        remember_password: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            document = self.document()
            existing = next(
                (item for item in document["profiles"] if item["profile_id"] == profile_id),
                None,
            )
            now = int(time.time() * 1000)
            raw = {
                **(existing or {}),
                **deepcopy(values),
                "profile_id": profile_id or uuid.uuid4().hex,
                "created_at_ms": int((existing or {}).get("created_at_ms") or now),
                "updated_at_ms": now,
            }
            folder_ids = {item["folder_id"] for item in document["folders"]}
            profile = self._profile(raw, folder_ids=folder_ids, password_configured=False)
            secrets = self._read_secrets()
            if remember_password is False:
                secrets.pop(profile["profile_id"], None)
            elif remember_password is True:
                if not password:
                    raise TerminalProfileError("保存密码不能为空")
                secrets[profile["profile_id"]] = self._protect(profile["profile_id"], password)
            profile["password_configured"] = profile["profile_id"] in secrets
            profiles = [
                item for item in document["profiles"] if item["profile_id"] != profile["profile_id"]
            ]
            profiles.append(profile)
            profiles.sort(key=lambda item: (not item["favorite"], item["name"].casefold()))
            self._write_document({**document, "profiles": profiles})
            self._write_json(self.secret_path, {"schema_version": 1, "secrets": secrets})
            return deepcopy(profile)

    def delete_profile(self, profile_id: str) -> None:
        value = self._id(profile_id, "会话")
        with self._lock:
            document = self.document()
            profiles = [item for item in document["profiles"] if item["profile_id"] != value]
            if len(profiles) == len(document["profiles"]):
                raise KeyError("保存会话不存在")
            secrets = self._read_secrets()
            secrets.pop(value, None)
            self._write_document({**document, "profiles": profiles})
            self._write_json(self.secret_path, {"schema_version": 1, "secrets": secrets})

    def resolve(self, profile_id: str, password_override: str = "") -> tuple[dict[str, Any], str]:
        value = self._id(profile_id, "会话")
        with self._lock:
            document = self.document()
            profile = next(
                (item for item in document["profiles"] if item["profile_id"] == value),
                None,
            )
            if profile is None:
                raise KeyError("保存会话不存在")
            if password_override:
                return deepcopy(profile), str(password_override)
            encrypted = self._read_secrets().get(value, "")
            if not encrypted:
                raise TerminalProfileError("该会话未保存密码，请输入密码后连接")
            return deepcopy(profile), self._unprotect(value, encrypted)

    def create_folder(self, name: str) -> dict[str, Any]:
        with self._lock:
            document = self.document()
            folder = self._folder({"folder_id": uuid.uuid4().hex, "name": name})
            if any(item["name"].casefold() == folder["name"].casefold() for item in document["folders"]):
                raise TerminalProfileError("会话文件夹名称已存在")
            document["folders"].append(folder)
            document["folders"].sort(key=lambda item: item["name"].casefold())
            self._write_document(document)
            return deepcopy(folder)

    def rename_folder(self, folder_id: str, name: str) -> dict[str, Any]:
        value = self._id(folder_id, "文件夹")
        with self._lock:
            document = self.document()
            folder = next((item for item in document["folders"] if item["folder_id"] == value), None)
            if folder is None:
                raise KeyError("会话文件夹不存在")
            candidate = self._folder({"folder_id": value, "name": name})
            if any(
                item["folder_id"] != value and item["name"].casefold() == candidate["name"].casefold()
                for item in document["folders"]
            ):
                raise TerminalProfileError("会话文件夹名称已存在")
            folder["name"] = candidate["name"]
            self._write_document(document)
            return deepcopy(folder)

    def delete_folder(self, folder_id: str) -> None:
        value = self._id(folder_id, "文件夹")
        with self._lock:
            document = self.document()
            folders = [item for item in document["folders"] if item["folder_id"] != value]
            if len(folders) == len(document["folders"]):
                raise KeyError("会话文件夹不存在")
            for profile in document["profiles"]:
                if profile["folder_id"] == value:
                    profile["folder_id"] = ""
            self._write_document({**document, "folders": folders})

    @staticmethod
    def connection_values(values: dict[str, Any]) -> dict[str, Any]:
        protocol = str(values.get("protocol") or "SSH").strip().upper()
        if protocol not in _PROTOCOLS:
            raise TerminalProfileError("快速连接协议只支持 SSH 或 TELNET")
        host = str(values.get("host") or "").strip()
        if not host or len(host) > 255 or any(char.isspace() or char in "/\\" for char in host):
            raise TerminalProfileError("快速连接主机无效")
        port = int(values.get("port") or (22 if protocol == "SSH" else 23))
        if port < 1 or port > 65535:
            raise TerminalProfileError("快速连接端口无效")
        username = str(values.get("username") or "").strip()
        if not username or len(username) > 256:
            raise TerminalProfileError("快速连接用户名无效")
        encoding = str(values.get("encoding") or "utf-8").strip().casefold()
        if encoding not in _ENCODINGS:
            raise TerminalProfileError("快速连接编码无效")
        return {
            "name": str(values.get("name") or host).strip()[:160] or host,
            "host": host,
            "port": port,
            "protocol": protocol,
            "username": username,
            "encoding": encoding,
            "vendor": str(values.get("vendor") or "Other").strip()[:80] or "Other",
            "device_type": str(values.get("device_type") or "Other").strip()[:40] or "Other",
        }

    def _profile(
        self,
        value: Any,
        *,
        folder_ids: set[str],
        password_configured: bool,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TerminalProfileError("保存会话格式无效")
        connection = self.connection_values(value)
        folder_id = str(value.get("folder_id") or "").strip()
        if folder_id and folder_id not in folder_ids:
            raise TerminalProfileError("保存会话引用的文件夹不存在")
        return {
            "profile_id": self._id(str(value.get("profile_id") or ""), "会话"),
            **connection,
            "folder_id": folder_id,
            "favorite": bool(value.get("favorite", False)),
            "password_configured": bool(password_configured),
            "created_at_ms": max(0, int(value.get("created_at_ms") or 0)),
            "updated_at_ms": max(0, int(value.get("updated_at_ms") or 0)),
        }

    @staticmethod
    def _folder(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            raise TerminalProfileError("会话文件夹格式无效")
        folder_id = TerminalProfileStore._id(str(value.get("folder_id") or ""), "文件夹")
        name = str(value.get("name") or "").strip()
        if not name or len(name) > 120:
            raise TerminalProfileError("会话文件夹名称无效")
        return {"folder_id": folder_id, "name": name}

    @staticmethod
    def _id(value: str, label: str) -> str:
        normalized = str(value or "").strip().casefold()
        if len(normalized) != 32 or re.fullmatch(r"[0-9a-f]{32}", normalized) is None:
            raise TerminalProfileError(f"{label} ID 无效")
        return normalized

    def _read_secrets(self) -> dict[str, str]:
        value = self._read_json(self.secret_path, {"schema_version": 1, "secrets": {}})
        secrets = value.get("secrets")
        if not isinstance(secrets, dict):
            raise TerminalProfileError("保存会话凭据格式无效")
        return {str(key): str(item) for key, item in secrets.items() if key and item}

    @staticmethod
    def _entropy(profile_id: str) -> bytes:
        return f"NetConsole:TerminalProfile:{profile_id}".encode("utf-8")

    def _protect(self, profile_id: str, password: str) -> str:
        encrypted = protect_windows_data(str(password).encode("utf-8"), self._entropy(profile_id))
        return base64.b64encode(encrypted).decode("ascii")

    def _unprotect(self, profile_id: str, encrypted: str) -> str:
        try:
            payload = base64.b64decode(encrypted, validate=True)
            return unprotect_windows_data(payload, self._entropy(profile_id)).decode("utf-8")
        except (ValueError, OSError, UnicodeError) as exc:
            raise TerminalProfileError("保存会话密码无法解密，请重新输入") from exc

    def _write_document(self, value: dict[str, Any]) -> None:
        self._write_json(
            self.path,
            {
                "schema_version": 1,
                "folders": value.get("folders", []),
                "profiles": [
                    {key: item for key, item in profile.items() if key != "password_configured"}
                    for profile in value.get("profiles", [])
                ],
            },
        )

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.is_file():
            return deepcopy(default)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise TerminalProfileError(f"无法读取终端会话配置: {path.name}") from exc
        if not isinstance(value, dict):
            raise TerminalProfileError(f"终端会话配置格式无效: {path.name}")
        return value

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


__all__ = ["TerminalProfileError", "TerminalProfileStore"]
