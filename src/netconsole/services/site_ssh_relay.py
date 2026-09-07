"""Site-scoped SSH Jump Host support.

This module owns the site-scoped SSH transport and direct-tcpip channels used
by device connection consumers.  It does not proxy ICMP, UDP, SNMP, syslog,
or external terminal processes.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.core.sites import SiteManager
from netconsole.core.windows_dpapi import protect_windows_data, unprotect_windows_data
from netconsole.services.host_key_trust_service import (
    HostKeyTrustError,
    HostKeyTrustService,
    install_managed_host_key_policy,
)
from netconsole.services.site_storage import SiteRegistryRepository, SiteStorageError


SITE_RELAY_ENABLED_KEY = "ssh_relay_enabled"
SITE_RELAY_HOST_KEY = "ssh_relay_host"
SITE_RELAY_PORT_KEY = "ssh_relay_port"
SITE_RELAY_USERNAME_KEY = "ssh_relay_username"
SITE_RELAY_CREDENTIAL_REF_KEY = "ssh_relay_credential_ref"
SITE_RELAY_REVISION_KEY = "ssh_relay_revision"
SITE_RELAY_CREDENTIAL_DB_NAME = "site_ssh_credentials.sqlite3"
DEFAULT_SSH_PORT = 22
TARGET_HOST_KEY_UNKNOWN_CODE = "TARGET_HOSTKEY_FAILED"
TARGET_HOST_KEY_CHANGED_CODE = "TARGET_HOSTKEY_CHANGED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_relay_stage(
    stage: str,
    result: str,
    *,
    target_host: str = "",
    target_port: int | None = None,
    jump_host: str = "",
    jump_port: int | None = None,
    username: str = "",
    authentication_method: str = "password",
    duration_ms: int | None = None,
    exception: BaseException | None = None,
    host_key_status: str = "",
    fingerprint_sha256: str = "",
) -> None:
    """Write stage diagnostics without ever including either password."""

    values = [
        f"stage={stage}",
        f"result={result}",
        f"target={target_host}:{target_port}" if target_host else "",
        f"jump={jump_host}:{jump_port}" if jump_host else "",
        f"username={username}" if username else "",
        f"authentication_method={authentication_method}",
    ]
    if duration_ms is not None:
        values.append(f"duration_ms={duration_ms}")
    if exception is not None:
        values.append(f"exception={exception.__class__.__name__}")
    if host_key_status:
        values.append(f"host_key_status={host_key_status}")
    if fingerprint_sha256:
        values.append(f"fingerprint_sha256={fingerprint_sha256}")
    app_logger.log_info("ssh_relay_stage", " ".join(value for value in values if value))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _is_authentication_exception(exc: BaseException) -> bool:
    try:
        import paramiko

        if isinstance(exc, paramiko.AuthenticationException):
            return True
    except Exception:
        pass
    return exc.__class__.__name__.casefold() in {
        "authenticationexception",
        "badauthenticationtype",
        "passwordrequiredexception",
    }


def _target_message(summary: str, code: str, details: Mapping[str, object]) -> str:
    return (
        f"{summary}（目标={details.get('target', '')}；"
        f"中转={details.get('jump', '')}；"
        f"用户={details.get('target_username', '')}；"
        f"错误码={code}）"
    )


class SiteSSHRelayError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None) -> None:
        self.code = str(code)
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class SiteSSHRelayConfig:
    site_id: str
    enabled: bool = False
    host: str = ""
    port: int = DEFAULT_SSH_PORT
    username: str = ""
    credential_ref: str = ""
    revision: str = ""
    password_configured: bool = False

    @property
    def complete(self) -> bool:
        return bool(
            self.host
            and self.username
            and self.credential_ref
            and 1 <= int(self.port) <= 65535
            and self.password_configured
        )

    def to_public(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "credential_ref": self.credential_ref,
            "revision": self.revision,
            "password_configured": self.password_configured,
            "complete": self.complete,
        }


@dataclass(frozen=True)
class ResolvedSiteSSHRelayConfig(SiteSSHRelayConfig):
    password: str = ""


class SiteSSHCredentialRepository:
    """Persist only DPAPI ciphertext; plaintext exists only for one call."""

    def __init__(self, database_path: Path) -> None:
        self.path = Path(database_path)
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = connect_sqlite(self.path, timeout=10)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS site_credentials (
                credential_ref TEXT PRIMARY KEY,
                secret_kind TEXT NOT NULL,
                ciphertext BLOB NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        return connection

    @staticmethod
    def _entropy(site_id: str, credential_ref: str) -> bytes:
        return f"NetConsole:SiteSSH:{site_id}:{credential_ref}".encode("utf-8")

    def has(self, site_id: str, credential_ref: str) -> bool:
        if not credential_ref:
            return False
        if not self.path.is_file():
            return False
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT 1 FROM site_credentials WHERE credential_ref = ?",
                    (credential_ref,),
                ).fetchone()
                return row is not None
            finally:
                connection.close()

    def put(self, site_id: str, credential_ref: str, password: str) -> None:
        if not credential_ref:
            raise SiteSSHRelayError("SSH_RELAY_CREDENTIAL_REF_INVALID", "SSH 中转凭据引用无效")
        if not password:
            raise SiteSSHRelayError("SSH_RELAY_PASSWORD_REQUIRED", "SSH 中转密码不能为空")
        ciphertext = protect_windows_data(
            str(password).encode("utf-8"),
            self._entropy(site_id, credential_ref),
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    """
                    INSERT INTO site_credentials (credential_ref, secret_kind, ciphertext, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(credential_ref) DO UPDATE SET
                        secret_kind=excluded.secret_kind,
                        ciphertext=excluded.ciphertext,
                        updated_at=excluded.updated_at
                    """,
                    (credential_ref, "ssh_relay_password", sqlite3.Binary(ciphertext), _now()),
                )
                connection.commit()
            finally:
                connection.close()

    def get(self, site_id: str, credential_ref: str) -> str:
        if not credential_ref:
            return ""
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT ciphertext FROM site_credentials WHERE credential_ref = ?",
                    (credential_ref,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            return ""
        try:
            return unprotect_windows_data(
                bytes(row[0]),
                self._entropy(site_id, credential_ref),
            ).decode("utf-8")
        except Exception as exc:
            raise SiteSSHRelayError(
                "SSH_RELAY_CREDENTIAL_UNAVAILABLE",
                "SSH 中转凭据无法解密，请重新保存中转密码",
            ) from exc


class SiteSSHRelayService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.registry = SiteRegistryRepository(paths)

    def _site_directory(self, site_id: str) -> str:
        try:
            return self.registry.resolve_directory_name(site_id)
        except SiteStorageError as exc:
            raise SiteSSHRelayError("SITE_NOT_FOUND", "局点不存在") from exc

    def _credential_repository(self, site_id: str) -> SiteSSHCredentialRepository:
        directory = self._site_directory(site_id)
        return SiteSSHCredentialRepository(
            self.paths.site_dir(directory) / "db" / SITE_RELAY_CREDENTIAL_DB_NAME
        )

    def load(self, site_id: str) -> SiteSSHRelayConfig:
        directory = self._site_directory(site_id)
        metadata = SiteManager(self.paths).load_site_metadata(directory)
        credential_ref = str(metadata.get(SITE_RELAY_CREDENTIAL_REF_KEY) or "").strip()
        repository = self._credential_repository(site_id)
        try:
            port = int(metadata.get(SITE_RELAY_PORT_KEY) or DEFAULT_SSH_PORT)
        except (TypeError, ValueError):
            port = DEFAULT_SSH_PORT
        return SiteSSHRelayConfig(
            site_id=str(site_id),
            enabled=bool(metadata.get(SITE_RELAY_ENABLED_KEY) is True),
            host=str(metadata.get(SITE_RELAY_HOST_KEY) or "").strip(),
            port=port,
            username=str(metadata.get(SITE_RELAY_USERNAME_KEY) or "").strip(),
            credential_ref=credential_ref,
            revision=str(metadata.get(SITE_RELAY_REVISION_KEY) or "").strip(),
            password_configured=repository.has(site_id, credential_ref),
        )

    def resolve_for_connection(self, site_id: str) -> ResolvedSiteSSHRelayConfig:
        config = self.load(site_id)
        if not config.enabled:
            raise SiteSSHRelayError("SSH_RELAY_DISABLED", "当前局点未启用 SSH 中转")
        if not config.complete:
            raise SiteSSHRelayError(
                "SSH_RELAY_CONFIG_INCOMPLETE",
                "SSH 中转配置不完整，无法启用或连接",
            )
        password = SiteSSHCredentialRepository(
            self.paths.site_dir(self._site_directory(site_id))
            / "db"
            / SITE_RELAY_CREDENTIAL_DB_NAME
        ).get(site_id, config.credential_ref)
        if not password:
            raise SiteSSHRelayError(
                "SSH_RELAY_PASSWORD_REQUIRED",
                "SSH 中转密码未配置，无法连接",
            )
        return ResolvedSiteSSHRelayConfig(**config.__dict__, password=password)

    def save(
        self,
        site_id: str,
        *,
        enabled: bool,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
    ) -> SiteSSHRelayConfig:
        directory = self._site_directory(site_id)
        normalized_host = str(host or "").strip()
        normalized_username = str(username or "").strip()
        try:
            normalized_port = int(port)
        except (TypeError, ValueError) as exc:
            raise SiteSSHRelayError("SSH_RELAY_PORT_INVALID", "SSH 中转端口无效") from exc
        if not 1 <= normalized_port <= 65535:
            raise SiteSSHRelayError("SSH_RELAY_PORT_INVALID", "SSH 中转端口必须在 1 到 65535 之间")
        current = self.load(site_id)
        credential_ref = current.credential_ref or f"site-ssh-relay-{str(site_id).strip()}"
        repository = self._credential_repository(site_id)
        if password is not None and str(password):
            repository.put(site_id, credential_ref, str(password))
        password_configured = repository.has(site_id, credential_ref)
        normalized_enabled = bool(enabled)
        if normalized_enabled and not (normalized_host and normalized_username and password_configured):
            raise SiteSSHRelayError(
                "SSH_RELAY_CONFIG_INCOMPLETE",
                "启用 SSH 中转前必须填写服务器、用户名和密码",
            )
        revision = uuid.uuid4().hex
        SiteManager(self.paths).save_site_metadata(
            directory,
            {
                SITE_RELAY_ENABLED_KEY: normalized_enabled,
                SITE_RELAY_HOST_KEY: normalized_host,
                SITE_RELAY_PORT_KEY: normalized_port,
                SITE_RELAY_USERNAME_KEY: normalized_username,
                SITE_RELAY_CREDENTIAL_REF_KEY: credential_ref,
                SITE_RELAY_REVISION_KEY: revision,
            },
        )
        close_site_jump_sessions(str(site_id), self.paths)
        return SiteSSHRelayConfig(
            site_id=str(site_id),
            enabled=normalized_enabled,
            host=normalized_host,
            port=normalized_port,
            username=normalized_username,
            credential_ref=credential_ref,
            revision=revision,
            password_configured=password_configured,
        )

    def test_jump_host(self, site_id: str) -> dict[str, object]:
        config = self.load(site_id)
        if not config.complete:
            raise SiteSSHRelayError(
                "SSH_RELAY_CONFIG_INCOMPLETE",
                "SSH 中转配置不完整，无法测试连接",
            )
        password = self._credential_repository(site_id).get(site_id, config.credential_ref)
        if not password:
            raise SiteSSHRelayError(
                "SSH_RELAY_PASSWORD_REQUIRED",
                "SSH 中转密码未配置，无法测试连接",
            )
        resolved = ResolvedSiteSSHRelayConfig(**config.__dict__, password=password)
        client = _new_paramiko_client(self.paths, resolved.host, resolved.port, role="jump")
        started = __import__("time").monotonic()
        try:
            client.connect(
                hostname=resolved.host,
                port=resolved.port,
                username=resolved.username,
                password=resolved.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
                auth_timeout=8,
                banner_timeout=8,
            )
            return {
                "success": True,
                "site_id": resolved.site_id,
                "host": resolved.host,
                "port": resolved.port,
                "connection_mode": "jump",
                "duration_ms": max(0, int((__import__("time").monotonic() - started) * 1000)),
                "message": "SSH 中转服务器连接正常",
            }
        except SiteSSHRelayError:
            raise
        except Exception as exc:
            raise _classify_jump_connect_exception(exc, resolved.host, resolved.port) from exc
        finally:
            client.close()


def _new_paramiko_client(paths: PathResolver, host: str, port: int, *, role: str) -> Any:
    import paramiko

    client = paramiko.SSHClient()
    install_managed_host_key_policy(
        client,
        HostKeyTrustService(paths),
        host,
        port,
        role=role,
    )
    return client


def _classify_jump_connect_exception(exc: BaseException, host: str, port: int) -> SiteSSHRelayError:
    import paramiko

    host_key_code = str(getattr(exc, "code", "") or "")
    host_key_exception = any(isinstance(item, HostKeyTrustError) for item in _exception_chain(exc))
    bad_host_key_exception = any(
        isinstance(item, paramiko.BadHostKeyException) for item in _exception_chain(exc)
    )
    if host_key_exception or bad_host_key_exception or host_key_code in {
        "DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN",
        "DEVICE_FILE_JUMP_HOST_KEY_MISMATCH",
    }:
        changed = host_key_code.endswith("MISMATCH") or any(
            str(getattr(item, "code", "") or "").endswith("MISMATCH")
            for item in _exception_chain(exc)
        ) or bad_host_key_exception
        return SiteSSHRelayError(
            "JUMP_HOSTKEY_FAILED",
            "跳板机主机密钥已变更，连接已阻止。" if changed else "首次连接需要确认跳板机主机密钥。",
            details={
                "stage": "JUMP_SSH_HANDSHAKE",
                "host": host,
                "port": port,
                "host_key_event": "changed" if changed else "unknown",
                "exception": exc.__class__.__name__,
            },
        )
    if isinstance(exc, paramiko.AuthenticationException):
        return SiteSSHRelayError(
            "JUMP_AUTH_FAILED",
            "SSH 中转服务器认证失败",
            details={"stage": "JUMP_AUTH", "host": host, "port": port, "exception": exc.__class__.__name__},
        )
    if isinstance(exc, (socket.timeout, TimeoutError, OSError, paramiko.SSHException)):
        return SiteSSHRelayError(
            "JUMP_CONNECT_FAILED",
            "SSH 中转服务器连接失败",
            details={"stage": "JUMP_TCP_CONNECT", "host": host, "port": port, "exception": exc.__class__.__name__},
        )
    return SiteSSHRelayError(
        "JUMP_CONNECT_FAILED",
        "SSH 中转服务器连接失败",
        details={"stage": "JUMP_TCP_CONNECT", "host": host, "port": port, "exception": exc.__class__.__name__},
    )


class SiteJumpSessionManager:
    """One reusable jump transport per site and Python worker process."""

    def __init__(self, paths: PathResolver, config: ResolvedSiteSSHRelayConfig) -> None:
        self.paths = paths
        self.config = config
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._transport: Any | None = None

    def update_config(self, config: ResolvedSiteSSHRelayConfig) -> None:
        with self._lock:
            if config.revision != self.config.revision:
                self._close_locked()
            self.config = config

    def open_channel(self, target_host: str, target_port: int) -> Any:
        started = time.monotonic()
        with self._lock:
            transport = self._ensure_transport_locked()
            _log_relay_stage(
                "DIRECT_TCPIP_OPEN",
                "starting",
                target_host=str(target_host),
                target_port=int(target_port),
                jump_host=self.config.host,
                jump_port=self.config.port,
            )
            try:
                channel = transport.open_channel(
                    "direct-tcpip",
                    (str(target_host), int(target_port)),
                    ("127.0.0.1", 0),
                )
                if channel is None:
                    raise OSError("direct-tcpip channel unavailable")
                _log_relay_stage(
                    "DIRECT_TCPIP_OPEN",
                    "pass",
                    target_host=str(target_host),
                    target_port=int(target_port),
                    jump_host=self.config.host,
                    jump_port=self.config.port,
                    duration_ms=_elapsed_ms(started),
                )
                _log_relay_stage(
                    "TARGET_TCP_READY",
                    "pass",
                    target_host=str(target_host),
                    target_port=int(target_port),
                    jump_host=self.config.host,
                    jump_port=self.config.port,
                    duration_ms=_elapsed_ms(started),
                )
                return channel
            except Exception as exc:
                if self._transport is None or not bool(self._transport.is_active()):
                    self._close_locked()
                _log_relay_stage(
                    "DIRECT_TCPIP_OPEN",
                    "fail",
                    target_host=str(target_host),
                    target_port=int(target_port),
                    jump_host=self.config.host,
                    jump_port=self.config.port,
                    duration_ms=_elapsed_ms(started),
                    exception=exc,
                )
                raise SiteSSHRelayError(
                    "JUMP_CHANNEL_FAILED",
                    f"SSH 中转服务器正常，但无法连接目标设备：{target_host}:{target_port}",
                    details={
                        "stage": "DIRECT_TCPIP_OPEN",
                        "target_host": target_host,
                        "target_port": int(target_port),
                        "jump_host": self.config.host,
                        "jump_port": self.config.port,
                        "exception": exc.__class__.__name__,
                    },
                ) from exc

    def _ensure_transport_locked(self) -> Any:
        if self._transport is not None and bool(self._transport.is_active()):
            return self._transport
        self._close_locked()
        client = _new_paramiko_client(
            self.paths,
            self.config.host,
            self.config.port,
            role="jump",
        )
        started = time.monotonic()
        _log_relay_stage(
            "JUMP_TCP_CONNECT",
            "starting",
            jump_host=self.config.host,
            jump_port=self.config.port,
            username=self.config.username,
        )
        try:
            client.connect(
                hostname=self.config.host,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
                auth_timeout=8,
                banner_timeout=8,
            )
            transport = client.get_transport()
            if transport is None or not bool(transport.is_active()):
                raise OSError("jump transport is inactive")
            _log_relay_stage(
                "JUMP_TCP_CONNECT",
                "pass",
                jump_host=self.config.host,
                jump_port=self.config.port,
                username=self.config.username,
                duration_ms=_elapsed_ms(started),
            )
            _log_relay_stage(
                "JUMP_SSH_HANDSHAKE",
                "pass",
                jump_host=self.config.host,
                jump_port=self.config.port,
                username=self.config.username,
                duration_ms=_elapsed_ms(started),
            )
            _log_relay_stage(
                "JUMP_AUTH",
                "pass",
                jump_host=self.config.host,
                jump_port=self.config.port,
                username=self.config.username,
                authentication_method="password",
                duration_ms=_elapsed_ms(started),
            )
        except SiteSSHRelayError:
            client.close()
            raise
        except Exception as exc:
            client.close()
            stage = "JUMP_AUTH" if _is_authentication_exception(exc) else "JUMP_SSH_HANDSHAKE"
            _log_relay_stage(
                stage,
                "fail",
                jump_host=self.config.host,
                jump_port=self.config.port,
                username=self.config.username,
                duration_ms=_elapsed_ms(started),
                exception=exc,
            )
            raise _classify_jump_connect_exception(exc, self.config.host, self.config.port) from exc
        self._client = client
        self._transport = transport
        return transport

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        client, self._client = self._client, None
        self._transport = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    result: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        result.append(current)
        current = current.__cause__ or current.__context__
    return tuple(result)


def _is_bad_host_key_exception(exc: BaseException) -> bool:
    try:
        import paramiko

        if any(isinstance(item, paramiko.BadHostKeyException) for item in _exception_chain(exc)):
            return True
    except Exception:
        pass
    text = " ".join(str(item or "") for item in _exception_chain(exc)).casefold()
    return any(
        marker in text
        for marker in (
            "badhostkeyexception",
            "bad host key",
            "host key for server",
            "does not match",
            "expected key",
        )
    )


def _is_ssh_handshake_exception(exc: BaseException) -> bool:
    try:
        import paramiko

        if any(
            isinstance(item, paramiko.SSHException) and not isinstance(item, paramiko.AuthenticationException)
            for item in _exception_chain(exc)
        ):
            return True
    except Exception:
        pass
    text = " ".join(str(item or "") for item in _exception_chain(exc)).casefold()
    return "paramiko sshexception" in text or "incompatiblepeer" in text or "negotiation failed" in text


def _target_error(
    exc: BaseException,
    *,
    target_host: str,
    target_port: int,
    target_username: str,
    target_password: str,
    config: ResolvedSiteSSHRelayConfig,
    protocol: str = "SSH",
) -> SiteSSHRelayError:
    """Translate a target-side exception while retaining safe diagnostics."""

    chain = _exception_chain(exc)
    text = " ".join(str(item or "") for item in chain).casefold()
    exception_name = next(
        (item.__class__.__name__ for item in chain if item.__class__.__name__),
        exc.__class__.__name__,
    )
    protocol_label = "Telnet" if str(protocol or "").casefold() == "telnet" else "SSH"
    details = {
        "target": f"{target_host}:{int(target_port)}",
        "target_host": target_host,
        "target_port": int(target_port),
        "target_username": target_username,
        "jump": f"{config.host}:{config.port}",
        "jump_host": config.host,
        "jump_port": config.port,
        "authentication_method": "password",
        "credential_loaded": bool(target_password),
        "protocol": protocol_label,
        "exception": exception_name,
    }

    if any(_is_authentication_exception(item) for item in chain):
        code = "TARGET_AUTH_FAILED"
        return SiteSSHRelayError(code, _target_message(f"目标设备 {protocol_label} 认证失败", code, details), details={**details, "stage": "TARGET_AUTH"})
    if _is_bad_host_key_exception(exc):
        code = TARGET_HOST_KEY_CHANGED_CODE
        return SiteSSHRelayError(
            code,
            _target_message("目标设备主机密钥已变更，连接已阻止", code, details),
            details={**details, "stage": "TARGET_HOST_KEY"},
        )
    if any(isinstance(item, HostKeyTrustError) for item in chain):
        code = TARGET_HOST_KEY_UNKNOWN_CODE
        return SiteSSHRelayError(
            code,
            _target_message("目标设备主机密钥校验失败", code, details),
            details={**details, "stage": "TARGET_HOST_KEY"},
        )
    if any(marker in text for marker in ("error reading ssh protocol banner", "ssh protocol banner")):
        code = "TARGET_SSH_BANNER_FAILED"
        return SiteSSHRelayError(
            code,
            _target_message(f"目标设备 {protocol_label} Banner 获取失败", code, details),
            details={**details, "stage": "TARGET_SSH_BANNER"},
        )
    if _is_ssh_handshake_exception(exc):
        code = "TARGET_SSH_HANDSHAKE_FAILED"
        return SiteSSHRelayError(
            code,
            _target_message(f"目标设备 {protocol_label} 握手失败", code, details),
            details={**details, "stage": "TARGET_SSH_HANDSHAKE"},
        )
    if any(
        marker in text
        for marker in (
            "tcp connection to device failed",
            "connection refused",
            "no route to host",
            "network is unreachable",
            "unable to connect to port",
            "getaddrinfo failed",
        )
    ):
        code = "TARGET_TCP_FAILED"
        return SiteSSHRelayError(
            code,
            _target_message(f"目标设备 {protocol_label} TCP 连接失败", code, details),
            details={**details, "stage": "TARGET_TCP_READY"},
        )
    if "timed out" in text or "timeout" in text:
        code = "CONNECT_TIMEOUT"
        return SiteSSHRelayError(
            code,
            _target_message(f"目标设备连接或 {protocol_label} 握手超时", code, details),
            details={**details, "stage": "TARGET_TCP_READY"},
        )
    code = "TARGET_SESSION_FAILED"
    return SiteSSHRelayError(
        code,
        _target_message(f"目标设备 {protocol_label} 会话建立失败", code, details),
        details={**details, "stage": "TARGET_SESSION_OPEN"},
    )


def _target_server_key(connection: Any) -> Any:
    remote = getattr(connection, "remote_conn_pre", None)
    transport = None
    if remote is not None:
        get_transport = getattr(remote, "get_transport", None)
        transport = get_transport() if callable(get_transport) else remote
    if transport is None:
        transport = getattr(connection, "transport", None)
    getter = getattr(transport, "get_remote_server_key", None)
    key = getter() if callable(getter) else None
    if key is None:
        raise RuntimeError("target remote server key unavailable")
    return key


def _trust_target_server_key(
    paths: PathResolver,
    connection: Any,
    *,
    target_host: str,
    target_port: int,
    config: ResolvedSiteSSHRelayConfig,
    target_username: str,
    target_password: str,
    started: float,
) -> tuple[str, str]:
    trust = HostKeyTrustService(paths)
    try:
        key = _target_server_key(connection)
        details = trust.inspect(target_host, target_port, key, role="target")
        first_use = not trust.is_trusted(target_host, target_port, key, role="target")
        trust.trust(target_host, target_port, key, role="target")
    except HostKeyTrustError as exc:
        changed = str(getattr(exc, "code", "")).endswith("MISMATCH")
        stage = "TARGET_HOST_KEY"
        _log_relay_stage(
            stage,
            "fail",
            target_host=target_host,
            target_port=target_port,
            jump_host=config.host,
            jump_port=config.port,
            username=target_username,
            duration_ms=_elapsed_ms(started),
            exception=exc,
        )
        raise SiteSSHRelayError(
            TARGET_HOST_KEY_CHANGED_CODE if changed else TARGET_HOST_KEY_UNKNOWN_CODE,
            "目标设备主机密钥已变更，连接已阻止" if changed else "目标设备主机密钥校验失败",
            details={
                "stage": stage,
                "target": f"{target_host}:{target_port}",
                "target_host": target_host,
                "target_port": int(target_port),
                "target_username": target_username,
                "jump": f"{config.host}:{config.port}",
                "jump_host": config.host,
                "jump_port": config.port,
                "authentication_method": "password",
                "credential_loaded": bool(target_password),
                "exception": exc.__class__.__name__,
            },
        ) from exc
    except Exception as exc:
        _log_relay_stage(
            "TARGET_HOST_KEY",
            "fail",
            target_host=target_host,
            target_port=target_port,
            jump_host=config.host,
            jump_port=config.port,
            username=target_username,
            duration_ms=_elapsed_ms(started),
            exception=exc,
        )
        raise SiteSSHRelayError(
            TARGET_HOST_KEY_UNKNOWN_CODE,
            "目标设备主机密钥读取或保存失败",
            details={
                "stage": "TARGET_HOST_KEY",
                "target": f"{target_host}:{target_port}",
                "target_host": target_host,
                "target_port": int(target_port),
                "target_username": target_username,
                "jump": f"{config.host}:{config.port}",
                "jump_host": config.host,
                "jump_port": config.port,
                "authentication_method": "password",
                "credential_loaded": bool(target_password),
                "exception": exc.__class__.__name__,
            },
        ) from exc
    status = "first_use_trusted" if first_use else "verified"
    _log_relay_stage(
        "TARGET_HOST_KEY",
        "pass",
        target_host=target_host,
        target_port=target_port,
        jump_host=config.host,
        jump_port=config.port,
        username=target_username,
        duration_ms=_elapsed_ms(started),
        host_key_status=status,
        fingerprint_sha256=details.fingerprint_sha256,
    )
    return status, details.fingerprint_sha256


_MANAGERS: dict[tuple[str, str], SiteJumpSessionManager] = {}
_MANAGERS_LOCK = threading.RLock()


def _manager_for(paths: PathResolver, config: ResolvedSiteSSHRelayConfig) -> SiteJumpSessionManager:
    key = (str(Path(paths.data_root).resolve()).casefold(), str(config.site_id))
    with _MANAGERS_LOCK:
        manager = _MANAGERS.get(key)
        if manager is None:
            manager = SiteJumpSessionManager(paths, config)
            _MANAGERS[key] = manager
        else:
            manager.update_config(config)
        return manager


def close_site_jump_sessions(site_id: str | None = None, paths: PathResolver | None = None) -> None:
    data_root = str(Path(paths.data_root).resolve()).casefold() if paths is not None else None
    with _MANAGERS_LOCK:
        keys = list(_MANAGERS)
        for key in keys:
            if data_root is not None and key[0] != data_root:
                continue
            if site_id is not None and key[1] != str(site_id):
                continue
            manager = _MANAGERS.pop(key)
            manager.close()


def _connect_telnet_over_channel(params: Mapping[str, object], channel: Any) -> Any:
    """Build Netmiko's Telnet driver on an existing Paramiko channel.

    Netmiko's normal Telnet connect path creates a Windows TCP socket.  For a
    site relay that would bypass the Jump Host, so the driver is initialized
    without auto-connect and its telnet socket is bound directly to the
    Paramiko ``direct-tcpip`` channel.  No localhost listener or per-device
    port mapping is created.
    """

    from netmiko._telnetlib import telnetlib
    from netmiko.channel import TelnetChannel
    from netmiko.ssh_dispatcher import ssh_dispatcher

    init_params = dict(params)
    init_params["auto_connect"] = False
    connection_class = ssh_dispatcher(str(init_params.get("device_type") or ""))
    connection = connection_class(**init_params)
    connection._modify_connection_params()

    remote_conn = telnetlib.Telnet()
    remote_conn.host = str(params.get("host") or "")
    remote_conn.port = int(params.get("port") or 23)
    remote_conn.timeout = float(getattr(connection, "conn_timeout", 5))
    remote_conn.sock = channel
    remote_conn.eof = 0
    connection.remote_conn = remote_conn
    connection.channel = TelnetChannel(conn=remote_conn, encoding=connection.encoding)
    try:
        connection.telnet_login()
        connection._try_session_preparation()
    except Exception:
        try:
            connection.disconnect()
        except Exception:
            pass
        raise
    return connection


class DeviceSSHConnectionFactory:
    """Create the single device session used by every site Jump consumer."""

    def __init__(
        self,
        paths: PathResolver,
        site_id: str,
        *,
        relay_service: SiteSSHRelayService | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id)
        self.relay_service = relay_service or SiteSSHRelayService(paths)

    def connect(
        self,
        params: Mapping[str, object],
        *,
        raw_connect_handler: Callable[..., Any],
        compatibility_connect: Callable[[Callable[..., Any], dict[str, object]], Any],
    ) -> Any:
        normalized = dict(params)
        site_config = self.relay_service.load(self.site_id)
        if not site_config.enabled:
            return compatibility_connect(raw_connect_handler, normalized)
        config = self.relay_service.resolve_for_connection(self.site_id)
        manager = _manager_for(self.paths, config)
        is_telnet = "telnet" in str(normalized.get("device_type") or "").casefold()
        # Netmiko's RejectPolicy prevents the application from recording a
        # target key on first use.  The managed known_hosts file still rejects
        # a changed key at Paramiko's BadHostKeyException boundary; after
        # connect we perform the explicit, role-aware TOFU write below.
        if not is_telnet:
            normalized.update(
                {
                    "ssh_strict": False,
                    "alt_host_keys": True,
                    "alt_key_file": str(self.paths.global_known_hosts_path),
                    "use_keys": False,
                    "allow_agent": False,
                }
            )
        started = time.monotonic()
        connection: Any | None = None

        def connect_over_channel(**target_params: object) -> Any:
            target_host = str(target_params.get("host") or "")
            target_port = int(target_params.get("port") or DEFAULT_SSH_PORT)
            channel = manager.open_channel(
                target_host,
                target_port,
            )
            try:
                if is_telnet:
                    connection = _connect_telnet_over_channel(target_params, channel)
                else:
                    target_params["sock"] = channel
                    connection = raw_connect_handler(**target_params)
            except Exception:
                try:
                    channel.close()
                except Exception:
                    pass
                raise
            try:
                setattr(connection, "_netconsole_ssh_mode", "jump")
                setattr(connection, "_netconsole_jump_host", f"{config.host}:{config.port}")
                setattr(connection, "_netconsole_target_host", target_host)
                setattr(connection, "_netconsole_target_port", target_port)
                setattr(connection, "_netconsole_target_username", str(target_params.get("username") or ""))
                setattr(connection, "_netconsole_authentication_method", "password")
            except Exception:
                pass
            return connection

        try:
            connection = compatibility_connect(connect_over_channel, normalized)
            target_host = str(normalized.get("host") or "")
            target_port = int(normalized.get("port") or DEFAULT_SSH_PORT)
            target_username = str(normalized.get("username") or "")
            target_password = str(normalized.get("password") or "")
            _log_relay_stage(
                "TARGET_SSH_BANNER" if not is_telnet else "TARGET_TELNET_READY",
                "pass",
                target_host=target_host,
                target_port=target_port,
                jump_host=config.host,
                jump_port=config.port,
                username=target_username,
                duration_ms=_elapsed_ms(started),
            )
            _log_relay_stage(
                "TARGET_SSH_HANDSHAKE" if not is_telnet else "TARGET_TELNET_READY",
                "pass",
                target_host=target_host,
                target_port=target_port,
                jump_host=config.host,
                jump_port=config.port,
                username=target_username,
                duration_ms=_elapsed_ms(started),
            )
            if not is_telnet:
                _trust_target_server_key(
                    self.paths,
                    connection,
                    target_host=target_host,
                    target_port=target_port,
                    config=config,
                    target_username=target_username,
                    target_password=target_password,
                    started=started,
                )
            _log_relay_stage(
                "TARGET_AUTH",
                "pass",
                target_host=target_host,
                target_port=target_port,
                jump_host=config.host,
                jump_port=config.port,
                username=target_username,
                authentication_method="telnet_password" if is_telnet else "password",
                duration_ms=_elapsed_ms(started),
            )
            _log_relay_stage(
                "TARGET_SESSION_OPEN",
                "pass",
                target_host=target_host,
                target_port=target_port,
                jump_host=config.host,
                jump_port=config.port,
                username=target_username,
                authentication_method="telnet_password" if is_telnet else "password",
                duration_ms=_elapsed_ms(started),
            )
        except SiteSSHRelayError:
            if connection is not None:
                disconnect = getattr(connection, "disconnect", None)
                if callable(disconnect):
                    try:
                        disconnect()
                    except Exception:
                        pass
            raise
        except Exception as exc:
            target_host = str(normalized.get("host") or "")
            target_port = int(normalized.get("port") or DEFAULT_SSH_PORT)
            target_username = str(normalized.get("username") or "")
            target_password = str(normalized.get("password") or "")
            error = _target_error(
                exc,
                target_host=target_host,
                target_port=target_port,
                target_username=target_username,
                target_password=target_password,
                config=config,
                protocol="Telnet" if is_telnet else "SSH",
            )
            _log_relay_stage(
                str(error.details.get("stage") or "TARGET_SESSION_OPEN"),
                "fail",
                target_host=target_host,
                target_port=target_port,
                jump_host=config.host,
                jump_port=config.port,
                username=target_username,
                duration_ms=_elapsed_ms(started),
                exception=exc,
            )
            raise error from exc
        return connection


def active_site_id(paths: PathResolver) -> str:
    manager = SiteManager(paths)
    stable = manager.get_current_site_id()
    if stable:
        try:
            return SiteRegistryRepository(paths).get(stable).site_id
        except SiteStorageError:
            pass
    try:
        return SiteRegistryRepository(paths).get_by_directory_name(manager.get_current_site()).site_id
    except SiteStorageError:
        return manager.get_current_site()


__all__ = [
    "DeviceSSHConnectionFactory",
    "ResolvedSiteSSHRelayConfig",
    "SITE_RELAY_CREDENTIAL_DB_NAME",
    "SiteJumpSessionManager",
    "SiteSSHCredentialRepository",
    "SiteSSHRelayConfig",
    "SiteSSHRelayError",
    "SiteSSHRelayService",
    "active_site_id",
    "close_site_jump_sessions",
]
