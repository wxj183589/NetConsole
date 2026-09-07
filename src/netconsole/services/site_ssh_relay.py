"""Site-scoped SSH Jump Host support.

This module deliberately owns only SSH-over-SSH access.  It does not proxy
ICMP, UDP, SNMP, syslog, or external terminal processes.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.core.sites import SiteManager
from netconsole.core.windows_dpapi import protect_windows_data, unprotect_windows_data
from netconsole.services.host_key_trust_service import (
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    if host_key_code in {
        "DEVICE_FILE_JUMP_HOST_KEY_UNKNOWN",
        "DEVICE_FILE_JUMP_HOST_KEY_MISMATCH",
    }:
        return SiteSSHRelayError(
            host_key_code,
            str(exc),
            details={"host": host, "port": port},
        )
    if isinstance(exc, paramiko.AuthenticationException):
        return SiteSSHRelayError(
            "JUMP_AUTH_FAILED",
            "SSH 中转服务器认证失败",
            details={"host": host, "port": port},
        )
    if isinstance(exc, (socket.timeout, TimeoutError, OSError, paramiko.SSHException)):
        return SiteSSHRelayError(
            "JUMP_CONNECT_FAILED",
            "SSH 中转服务器连接失败",
            details={"host": host, "port": port},
        )
    return SiteSSHRelayError(
        "JUMP_CONNECT_FAILED",
        "SSH 中转服务器连接失败",
        details={"host": host, "port": port},
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
        with self._lock:
            transport = self._ensure_transport_locked()
            try:
                return transport.open_channel(
                    "direct-tcpip",
                    (str(target_host), int(target_port)),
                    ("127.0.0.1", 0),
                )
            except Exception as exc:
                if self._transport is None or not bool(self._transport.is_active()):
                    self._close_locked()
                raise SiteSSHRelayError(
                    "JUMP_CHANNEL_FAILED",
                    f"SSH 中转服务器正常，但无法连接目标设备：{target_host}:{target_port}",
                    details={"target_host": target_host, "target_port": target_port},
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
        except SiteSSHRelayError:
            client.close()
            raise
        except Exception as exc:
            client.close()
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


class DeviceSSHConnectionFactory:
    """Create a normal Netmiko session, optionally over site Jump Host."""

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
        config = self.relay_service.resolve_for_connection(self.site_id)
        manager = _manager_for(self.paths, config)
        normalized.update(
            {
                "ssh_strict": True,
                "alt_host_keys": True,
                "alt_key_file": str(self.paths.global_known_hosts_path),
                "use_keys": False,
                "allow_agent": False,
            }
        )

        def connect_over_channel(**target_params: object) -> Any:
            channel = manager.open_channel(
                str(target_params.get("host") or ""),
                int(target_params.get("port") or DEFAULT_SSH_PORT),
            )
            target_params["sock"] = channel
            try:
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
            except Exception:
                pass
            return connection

        try:
            connection = compatibility_connect(connect_over_channel, normalized)
        except SiteSSHRelayError:
            raise
        except Exception as exc:
            import netmiko

            if isinstance(exc, netmiko.exceptions.NetmikoAuthenticationException):
                code = "TARGET_AUTH_FAILED"
                message = "目标设备 SSH 认证失败"
            else:
                code = "TARGET_CONNECT_FAILED"
                message = "SSH 中转服务器正常，但目标设备 SSH 连接失败"
            raise SiteSSHRelayError(
                code,
                message,
                details={
                    "target_host": normalized.get("host", ""),
                    "target_port": normalized.get("port", DEFAULT_SSH_PORT),
                    "jump_host": f"{config.host}:{config.port}",
                },
            ) from exc
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
