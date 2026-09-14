from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core import app_logger
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
    """Legacy import compatibility; production connections never create challenges."""

    code = "DEVICE_FILE_HOST_KEY_UNKNOWN"


class HostKeyMismatchError(HostKeyTrustError):
    """Legacy import compatibility; production connections auto-replace mismatches."""

    code = "DEVICE_FILE_HOST_KEY_MISMATCH"


class HostKeyPolicy(str, Enum):
    """统一的 managed known_hosts 处理策略。

    ``STRICT`` 和 ``TOFU`` 保留为旧调用方的可解析值，但生产连接统一
    使用 ``AUTO_REPLACE``：未知自动登记、相同继续、变化原子替换后继续。
    """

    STRICT = "STRICT"
    TOFU = "TOFU"
    AUTO_REPLACE = "AUTO_REPLACE"


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
class HostKeyTrustResult:
    details: HostKeyDetails
    action: str
    old_fingerprint_sha256: str = ""

    @property
    def status(self) -> str:
        return {
            "ADD": "HOST_KEY_AUTO_ADDED",
            "KEEP": "HOST_KEY_VERIFIED",
            "REPLACE": "HOST_KEY_AUTO_UPDATED",
        }.get(self.action, "HOST_KEY_UNKNOWN")


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
            try:
                keys.load(str(self.path))
            except Exception as exc:
                # known_hosts 是可重建的缓存事实源。逐行保留仍然有效的
                # 记录，避免一条损坏记录让其它设备的 SSH/SFTP 全部失效。
                recovered = paramiko.HostKeys()
                try:
                    from paramiko.hostkeys import HostKeyEntry

                    for line_number, line in enumerate(
                        self.path.read_text(encoding="utf-8", errors="replace").splitlines(),
                        start=1,
                    ):
                        if not line.strip() or line.lstrip().startswith("#"):
                            continue
                        try:
                            entry = HostKeyEntry.from_line(line, line_number)
                        except Exception:
                            continue
                        if entry is not None:
                            recovered._entries.append(entry)
                except Exception:
                    recovered = paramiko.HostKeys()
                keys = recovered
                app_logger.log_warning(
                    "MANAGED_KNOWN_HOSTS_RECOVERED",
                    f"path={self.path.name} exception={exc.__class__.__name__}",
                )
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
        # Compatibility entry point: verification is now the same automatic
        # add/keep/replace operation used by every SSH/SFTP consumer.
        self.trust_or_replace(host, port, key, role=role)

    def is_trusted(
        self,
        host: str,
        port: int,
        key: Any,
        *,
        role: str = "target",
    ) -> bool:
        """Return whether the exact managed key is already trusted.

        This is intentionally a read-only probe for diagnostics and tests.
        Normal connection paths use ``trust_or_replace`` so a mismatch is
        repaired instead of being turned into a user-facing challenge.
        """

        details = self.inspect(host, port, key, role=role)
        known = self._lookup(self._load(), details.host, details.port)
        if known is None:
            return False
        expected = known.get(details.algorithm)
        return expected is not None and expected.asbytes() == key.asbytes()

    def trust(
        self,
        host: str,
        port: int,
        key: Any,
        *,
        role: str = "target",
    ) -> HostKeyDetails:
        # ``trust`` is retained for older callers, but it is no longer a
        # strict confirmation operation.  All writes go through the same
        # atomic add/keep/replace implementation as normal connections.
        return self.trust_or_replace(host, port, key, role=role).details

    def trust_or_replace(
        self,
        host: str,
        port: int,
        key: Any,
        *,
        role: str = "target",
    ) -> HostKeyTrustResult:
        """Atomically add, keep, or replace one managed host entry."""

        details = self.inspect(host, port, key, role=role)
        names = _host_key_names(details.host, details.port)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(self.path):
            keys = self._load()
            known = self._lookup(keys, details.host, details.port)
            expected = known.get(details.algorithm) if known is not None else None
            if expected is not None and expected.asbytes() == key.asbytes():
                return HostKeyTrustResult(details, "KEEP", key_fingerprint_sha256(expected))

            old_fingerprint = ""
            if known is not None:
                old_keys = [known[name] for name in known.keys()]
                if old_keys:
                    old_fingerprint = ",".join(
                        key_fingerprint_sha256(old_key) for old_key in old_keys
                    )

            # Remove only the current host:port aliases.  Other Jump Hosts,
            # target devices, and other known_hosts entries remain untouched.
            for name in names:
                while True:
                    try:
                        del keys[name]
                    except KeyError:
                        break
            keys.add(names[0], details.algorithm, key)
            self._save(keys)
        return HostKeyTrustResult(
            details,
            "REPLACE" if known is not None else "ADD",
            old_fingerprint,
        )

    def remove(self, host: str, port: int) -> bool:
        """Delete exactly one managed ``host:port`` entry.

        This is used only by the operator-facing Jump Host maintenance action;
        it never touches another host or port.
        """

        names = _host_key_names(str(host or "").strip(), int(port or 22))
        if not names or not names[0]:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(self.path):
            keys = self._load()
            removed = False
            for name in names:
                try:
                    del keys[name]
                    removed = True
                except KeyError:
                    continue
            if not removed:
                return False
            self._save(keys)
            return True

    def _save(self, keys: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=".known_hosts.",
            suffix=".tmp",
            delete=False,
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


def install_managed_host_key_policy(
    client: Any,
    trust: HostKeyTrustService,
    host: str,
    port: int,
    *,
    role: str = "target",
    host_key_policy: HostKeyPolicy | str = HostKeyPolicy.AUTO_REPLACE,
) -> None:
    import paramiko

    checked_host = str(host or "").strip()
    checked_port = int(port or 22)
    selected_policy = (
        host_key_policy
        if isinstance(host_key_policy, HostKeyPolicy)
        else HostKeyPolicy(str(host_key_policy).upper())
    )
    service = trust

    # A few embedded/test Paramiko facades expose SSHClient but not the base
    # policy class.  The real Paramiko package always provides it; using
    # ``object`` as a fallback keeps the managed policy installable without
    # introducing an unmanaged missing-key fallback.
    missing_policy_base = getattr(paramiko, "MissingHostKeyPolicy", object)

    class _ManagedHostKeyPolicy(missing_policy_base):
        def missing_host_key(self, host_client, _hostname, key):
            # Every connection uses the same persisted managed fact.
            if selected_policy in {
                HostKeyPolicy.AUTO_REPLACE,
                HostKeyPolicy.STRICT,
                HostKeyPolicy.TOFU,
            }:
                result = service.trust_or_replace(
                    checked_host,
                    checked_port,
                    key,
                    role=role,
                )
                host_client._host_keys.add(
                    host_key_name(checked_host, checked_port),
                    key.get_name(),
                    key,
                )
                setattr(
                    host_client,
                    "_netconsole_host_key_event",
                    {
                        "status": result.status,
                        "action": result.action,
                        "host": result.details.host,
                        "port": result.details.port,
                        "algorithm": result.details.algorithm,
                        "fingerprint_sha256": result.details.fingerprint_sha256,
                        "old_fingerprint_sha256": result.old_fingerprint_sha256,
                    },
                )
                return
            raise ValueError(f"不支持的 managed Host Key policy: {selected_policy}")

    client.set_missing_host_key_policy(_ManagedHostKeyPolicy())


def _host_key_names(host: str, port: int) -> tuple[str, ...]:
    canonical = host_key_name(host, port)
    if int(port or 22) == 22 and str(host).strip() != canonical:
        return canonical, str(host).strip()
    return (canonical,)


def host_key_mismatch_error(
    trust: HostKeyTrustService,
    host: str,
    port: int,
    key: Any | None,
    *,
    role: str = "target",
) -> HostKeyMismatchError:
    """Build a legacy diagnostic for old integrations only.

    The managed Paramiko policy never calls this helper.  Keeping it avoids
    breaking older plugins while making the automatic policy the only normal
    connection behavior.
    """

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
        return "首次连接将自动登记跳板机主机密钥。"
    return "首次连接将自动登记目标设备主机密钥。"


def _mismatch_key_message(role: str) -> str:
    if _normalize_role(role) == "jump":
        return "跳板机主机密钥已变化，系统将自动更新记录。"
    return "目标设备主机密钥已变化，系统将自动更新记录。"


__all__ = [
    "HostKeyChallengeError",
    "HostKeyDetails",
    "HostKeyMismatchError",
    "HostKeyPolicy",
    "HostKeyTrustResult",
    "HostKeyTrustError",
    "HostKeyTrustService",
    "host_key_mismatch_error",
    "host_key_name",
    "install_managed_host_key_policy",
    "key_fingerprint_sha256",
]
