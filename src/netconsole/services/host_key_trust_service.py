from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core.paths import PathResolver


class HostKeyTrustError(RuntimeError):
    """结构化、可安全返回给 API 的主机密钥错误。"""

    code = "DEVICE_FILE_HOST_KEY_UNKNOWN"

    def __init__(self, message: str, details: dict[str, Any], *, key: Any | None = None) -> None:
        super().__init__(message)
        self.details = details
        self.key = key


class HostKeyChallengeError(HostKeyTrustError):
    code = "DEVICE_FILE_HOST_KEY_UNKNOWN"


class HostKeyMismatchError(HostKeyTrustError):
    code = "DEVICE_FILE_HOST_KEY_MISMATCH"


@dataclass(frozen=True)
class HostKeyDetails:
    host: str
    port: int
    algorithm: str
    fingerprint_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "algorithm": self.algorithm,
            "fingerprint_sha256": self.fingerprint_sha256,
        }


def host_key_name(host: str, port: int) -> str:
    value = str(host or "").strip()
    return value if int(port or 22) == 22 else f"[{value}]:{int(port)}"


def key_fingerprint_sha256(key: Any) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class HostKeyTrustService:
    """NetConsole 自己管理的 known_hosts，避免依赖管理员修改用户 SSH 文件。"""

    def __init__(self, paths: PathResolver) -> None:
        self.path = paths.global_known_hosts_path

    def _load(self):
        import paramiko

        keys = paramiko.HostKeys()
        if self.path.is_file():
            keys.load(str(self.path))
        return keys

    @staticmethod
    def _lookup(keys: Any, host: str, port: int):
        names = [host_key_name(host, port)]
        if int(port or 22) == 22:
            names.append(str(host).strip())
        for name in names:
            found = keys.lookup(name)
            if found:
                return found
        return None

    def inspect(self, host: str, port: int, key: Any) -> HostKeyDetails:
        return HostKeyDetails(
            host=str(host),
            port=int(port or 22),
            algorithm=str(key.get_name()),
            fingerprint_sha256=key_fingerprint_sha256(key),
        )

    def verify(self, host: str, port: int, key: Any) -> None:
        details = self.inspect(host, port, key)
        known = self._lookup(self._load(), details.host, details.port)
        if known is None:
            raise HostKeyChallengeError(
                "首次连接需要确认设备主机密钥。",
                details.as_dict(),
                key=key,
            )
        expected = known.get(details.algorithm)
        if expected is None or expected.asbytes() != key.asbytes():
            raise HostKeyMismatchError(
                "设备主机密钥已变更，连接已阻止。",
                details.as_dict(),
                key=key,
            )

    def trust(self, host: str, port: int, key: Any) -> HostKeyDetails:
        details = self.inspect(host, port, key)
        with locked_file(self.path):
            keys = self._load()
            name = host_key_name(details.host, details.port)
            known = self._lookup(keys, details.host, details.port)
            if known is not None:
                expected = known.get(details.algorithm)
                if expected is not None and expected.asbytes() == key.asbytes():
                    return details
                raise HostKeyMismatchError("设备主机密钥已变更，连接已阻止。", details.as_dict())
            keys.add(name, details.algorithm, key)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=".known_hosts.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_name = Path(temporary.name)
            try:
                keys.save(str(temporary_name))
                atomic_write_bytes(self.path, temporary_name.read_bytes())
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
            finally:
                temporary_name.unlink(missing_ok=True)
        return details


__all__ = [
    "HostKeyChallengeError",
    "HostKeyDetails",
    "HostKeyMismatchError",
    "HostKeyTrustError",
    "HostKeyTrustService",
    "host_key_name",
    "key_fingerprint_sha256",
]
