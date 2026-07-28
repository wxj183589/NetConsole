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

    def __init__(
        self,
        message: str,
        details: dict[str, Any],
        *,
        key: Any | None = None,
        code: str | None = None,
    ) -> None:
        if code:
            self.code = str(code)
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
    role: str = "target"

    def as_dict(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "algorithm": self.algorithm,
            "fingerprint_sha256": self.fingerprint_sha256,
            "host_key_role": self.role,
        }


@dataclass(frozen=True)
class HostKeyTrustGrant:
    host: str
    port: int
    algorithm: str
    key_bytes: bytes

    @classmethod
    def from_key(cls, host: str, port: int, key: Any) -> HostKeyTrustGrant:
        return cls(
            host=str(host or "").strip(),
            port=int(port or 22),
            algorithm=str(key.get_name()),
            key_bytes=bytes(key.asbytes()),
        )

    def matches(self, host: str, port: int, key: Any) -> bool:
        return (
            self.host.casefold() == str(host or "").strip().casefold()
            and self.port == int(port or 22)
            and self.algorithm == str(key.get_name())
            and self.key_bytes == bytes(key.asbytes())
        )


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

    def inspect(
        self,
        host: str,
        port: int,
        key: Any,
        *,
        role: str = "target",
    ) -> HostKeyDetails:
        return HostKeyDetails(
            host=str(host),
            port=int(port or 22),
            algorithm=str(key.get_name()),
            fingerprint_sha256=key_fingerprint_sha256(key),
            role=_normalize_role(role),
        )

    def verify(
        self,
        host: str,
        port: int,
        key: Any,
        *,
        role: str = "target",
    ) -> None:
        details = self.inspect(host, port, key, role=role)
        known = self._lookup(self._load(), details.host, details.port)
        if known is None:
            raise HostKeyChallengeError(
                _unknown_key_message(details.role),
                details.as_dict(),
                key=key,
                code=(
                    "DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN"
                    if details.role == "jump"
                    else "DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN"
                ),
            )
        expected = known.get(details.algorithm)
        if expected is None or expected.asbytes() != key.asbytes():
            raise HostKeyMismatchError(
                _mismatch_key_message(details.role),
                details.as_dict(),
                key=key,
                code=(
                    "DEVICE_FILE_JUMP_HOST_KEY_MISMATCH"
                    if details.role == "jump"
                    else "DEVICE_FILE_TARGET_HOST_KEY_MISMATCH"
                ),
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


def install_managed_host_key_policy(
    client: Any,
    trust: HostKeyTrustService,
    host: str,
    port: int,
    *,
    role: str = "target",
    grant: HostKeyTrustGrant | tuple[HostKeyTrustGrant, ...] | None = None,
) -> None:
    import paramiko

    checked_host = str(host or "").strip()
    checked_port = int(port or 22)
    if trust.path.is_file():
        client.load_host_keys(str(trust.path))

    service = trust

    class _ManagedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, host_client, _hostname, key):
            grants = (
                grant
                if isinstance(grant, tuple)
                else (() if grant is None else (grant,))
            )
            if any(
                item.matches(checked_host, checked_port, key)
                for item in grants
            ):
                host_client._host_keys.add(
                    host_key_name(checked_host, checked_port),
                    key.get_name(),
                    key,
                )
                return
            service.verify(
                checked_host,
                checked_port,
                key,
                role=role,
            )

    client.set_missing_host_key_policy(_ManagedHostKeyPolicy())


def host_key_mismatch_error(
    trust: HostKeyTrustService,
    host: str,
    port: int,
    key: Any | None,
    *,
    role: str = "target",
) -> HostKeyMismatchError:
    normalized_role = _normalize_role(role)
    details = (
        trust.inspect(host, port, key, role=normalized_role).as_dict()
        if key is not None
        else {
            "host": str(host or ""),
            "port": int(port or 22),
            "host_key_role": normalized_role,
        }
    )
    return HostKeyMismatchError(
        _mismatch_key_message(normalized_role),
        details,
        key=key,
        code=(
            "DEVICE_FILE_JUMP_HOST_KEY_MISMATCH"
            if normalized_role == "jump"
            else "DEVICE_FILE_TARGET_HOST_KEY_MISMATCH"
        ),
    )


def _normalize_role(role: str) -> str:
    return "jump" if str(role or "").casefold() == "jump" else "target"


def _unknown_key_message(role: str) -> str:
    if _normalize_role(role) == "jump":
        return "首次连接需要确认跳板机主机密钥。"
    return "首次连接需要确认目标设备主机密钥。"


def _mismatch_key_message(role: str) -> str:
    if _normalize_role(role) == "jump":
        return "跳板机主机密钥已变更，连接已阻止。"
    return "目标设备主机密钥已变更，连接已阻止。"


__all__ = [
    "HostKeyChallengeError",
    "HostKeyDetails",
    "HostKeyMismatchError",
    "HostKeyTrustGrant",
    "HostKeyTrustError",
    "HostKeyTrustService",
    "host_key_mismatch_error",
    "host_key_name",
    "install_managed_host_key_policy",
    "key_fingerprint_sha256",
]
