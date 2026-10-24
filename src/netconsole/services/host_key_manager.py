from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import uuid
from typing import Any

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.host_key_repository import HostKeyRepository, HostKeyRecord
from netconsole.services.host_key_trust_service import (
    HostKeyDetails,
    HostKeyTrustError,
    key_fingerprint_sha256,
)


AUTO_UPDATE = "AUTO_UPDATE"
STRICT = "STRICT"
HOST_KEY_POLICIES = frozenset({AUTO_UPDATE, STRICT})
SUPPORTED_HOST_KEY_ALGORITHMS = frozenset(
    {
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "rsa-sha2-256",
        "rsa-sha2-512",
        # H3C/Comware deployments may still expose ssh-rsa.  This is an
        # algorithm capability check, not permission to lower negotiation
        # policy; the adapter remains responsible for its configured fallback.
        "ssh-rsa",
    }
)
_SHA256_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")


class HostKeyManagerError(HostKeyTrustError):
    """Fail-closed Host Key policy, authorization, or persistence error."""


@dataclass(frozen=True)
class HostKeyObservation:
    details: HostKeyDetails
    action: str
    status: str
    allowed: bool
    pending_token: str = ""
    old_fingerprint_sha256: str = ""
    policy: str = AUTO_UPDATE
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            **self.details.as_dict(),
            "action": self.action,
            "status": self.status,
            "allowed": self.allowed,
            "pending_token": self.pending_token,
            "old_fingerprint_sha256": self.old_fingerprint_sha256,
            "update_policy": self.policy,
            "reason": self.reason,
        }


class HostKeyManager:
    """Device-bound Host Key authority with a pending/effective state split.

    A key is never promoted to ``current_fingerprint_sha256`` before the
    caller reports a successful authenticated SSH connection.  The manager
    deliberately stores fingerprints and metadata only, never key bytes or
    credentials.
    """

    def __init__(self, paths: Any, *, repository: HostKeyRepository | None = None) -> None:
        self.paths = paths
        self.repository = repository or HostKeyRepository(paths.host_key_database_path)
        self.repository.ensure_schema()

    def register_target(
        self,
        device_id: str,
        management_ip: str,
        ssh_port: int = 22,
        *,
        authorized: bool,
        update_policy: str = AUTO_UPDATE,
    ) -> dict[str, object]:
        self._assert_authorized(device_id, authorized)
        policy = self._normalize_policy(update_policy)
        host, port = self._normalize_endpoint(management_ip, ssh_port)
        now = _now()
        with self.repository.write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO host_key_records(
                    device_id, management_ip, ssh_port, update_policy,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, management_ip, ssh_port) DO UPDATE SET
                    update_policy = excluded.update_policy,
                    updated_at = excluded.updated_at
                """,
                (str(device_id).strip(), host, port, policy, now, now),
            )
        record = self.repository.get(str(device_id).strip(), host, port)
        return _record_dict(record)

    def set_policy(
        self,
        device_id: str,
        management_ip: str,
        ssh_port: int,
        update_policy: str,
        *,
        authorized: bool,
    ) -> dict[str, object]:
        self._assert_authorized(device_id, authorized)
        policy = self._normalize_policy(update_policy)
        host, port = self._normalize_endpoint(management_ip, ssh_port)
        now = _now()
        with self.repository.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE host_key_records
                SET update_policy = ?, updated_at = ?
                WHERE device_id = ? AND management_ip = ? AND ssh_port = ?
                """,
                (policy, now, str(device_id).strip(), host, port),
            )
            if cursor.rowcount != 1:
                raise HostKeyManagerError(
                    "设备尚未登记 Host Key 目标，不能单独修改策略。",
                    {"device_id": str(device_id), "host": host, "port": port},
                    code="HOST_KEY_TARGET_NOT_REGISTERED",
                )
        record = self.repository.get(str(device_id).strip(), host, port)
        return _record_dict(record)

    def stage_connection(
        self,
        device_id: str,
        management_ip: str,
        ssh_port: int,
        key: Any,
        *,
        authorized: bool,
        update_policy: str | None = None,
        reason: str = "ssh_connection",
    ) -> HostKeyObservation:
        self._assert_authorized(device_id, authorized)
        details = self._inspect(management_ip, ssh_port, key)
        host, port = self._normalize_endpoint(details.host, details.port)
        checked_device_id = str(device_id or "").strip()
        now = _now()
        with self.repository.write_transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM host_key_records
                WHERE device_id = ? AND management_ip = ? AND ssh_port = ?
                """,
                (checked_device_id, host, port),
            ).fetchone()
            record = self.repository.record_from_row(row)
            policy = self._normalize_policy(
                update_policy or (record.update_policy if record else AUTO_UPDATE)
            )
            if record is None:
                connection.execute(
                    """
                    INSERT INTO host_key_records(
                        device_id, management_ip, ssh_port, update_policy,
                        pending_token, pending_fingerprint_sha256,
                        pending_key_type, pending_status, pending_observed_at,
                        revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_TRUST', ?, 0, ?, ?)
                    """,
                    (
                        checked_device_id,
                        host,
                        port,
                        policy,
                        _token(),
                        details.fingerprint_sha256,
                        details.algorithm,
                        now,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT * FROM host_key_records
                    WHERE device_id = ? AND management_ip = ? AND ssh_port = ?
                    """,
                    (checked_device_id, host, port),
                ).fetchone()
                record = self.repository.record_from_row(row)
                assert record is not None
                self._append_history(
                    connection,
                    record,
                    details,
                    event_type="PENDING_TRUST",
                    old_fingerprint="",
                    new_fingerprint=details.fingerprint_sha256,
                    reason=reason,
                    result="PENDING",
                    pending_token=record.pending_token,
                )
                return HostKeyObservation(
                    details,
                    "ADD",
                    "HOST_KEY_AUTO_ADDED",
                    True,
                    record.pending_token or "",
                    "",
                    policy,
                    reason,
                )

            if update_policy and record.update_policy != policy:
                connection.execute(
                    "UPDATE host_key_records SET update_policy = ?, updated_at = ? WHERE id = ?",
                    (policy, now, record.id),
                )

            current = record.current_fingerprint_sha256 or ""
            if current and (
                not _SHA256_FINGERPRINT_RE.fullmatch(current)
                or record.key_type not in SUPPORTED_HOST_KEY_ALGORITHMS
            ):
                self._append_history(
                    connection,
                    record,
                    details,
                    event_type="HOST_KEY_INVALID_RECORD",
                    old_fingerprint=current,
                    new_fingerprint=details.fingerprint_sha256,
                    reason="stored current Host Key metadata is invalid",
                    result="REJECTED",
                )
                self._append_event(
                    connection,
                    record,
                    details,
                    event_type="HOST_KEY_INVALID_RECORD",
                    old_fingerprint=current,
                    new_fingerprint=details.fingerprint_sha256,
                    policy=policy,
                    result="REJECTED",
                    reason="stored current Host Key metadata is invalid",
                )
                return HostKeyObservation(
                    details,
                    "REJECT",
                    "HOST_KEY_INVALID_RECORD",
                    False,
                    "",
                    current,
                    policy,
                    reason,
                )
            if record.pending_token and record.pending_fingerprint_sha256 != details.fingerprint_sha256:
                self._append_event(
                    connection,
                    record,
                    details,
                    event_type="HOST_KEY_UPDATE_CONFLICT",
                    old_fingerprint=current,
                    new_fingerprint=details.fingerprint_sha256,
                    policy=policy,
                    result="REJECTED",
                    reason="another connection has a pending Host Key update",
                )
                return HostKeyObservation(
                    details,
                    "CONFLICT",
                    "HOST_KEY_UPDATE_CONFLICT",
                    False,
                    "",
                    current,
                    policy,
                    reason,
                )
            if record.pending_token:
                return HostKeyObservation(
                    details,
                    "ADD" if not current else "REPLACE" if current != details.fingerprint_sha256 else "KEEP",
                    "HOST_KEY_AUTO_ADDED"
                    if not current
                    else "HOST_KEY_CHANGED"
                    if current != details.fingerprint_sha256
                    else "HOST_KEY_VERIFIED",
                    True,
                    record.pending_token,
                    current,
                    policy,
                    reason,
                )
            if current == details.fingerprint_sha256 and record.key_type == details.algorithm:
                pending_token = record.pending_token or _token()
                connection.execute(
                    """
                    UPDATE host_key_records
                    SET pending_token = ?, pending_fingerprint_sha256 = ?,
                        pending_key_type = ?, pending_status = 'VERIFYING',
                        pending_observed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        pending_token,
                        details.fingerprint_sha256,
                        details.algorithm,
                        now,
                        now,
                        record.id,
                    ),
                )
                return HostKeyObservation(
                    details,
                    "KEEP",
                    "HOST_KEY_VERIFIED",
                    True,
                    pending_token,
                    current,
                    policy,
                    reason,
                )

            if not current:
                pending_token = _token()
                update_cursor = connection.execute(
                    """
                    UPDATE host_key_records
                    SET pending_token = ?, pending_fingerprint_sha256 = ?,
                        pending_key_type = ?, pending_status = 'PENDING_TRUST',
                        pending_observed_at = ?, update_policy = ?, updated_at = ?
                    WHERE id = ? AND revision = ? AND pending_token IS NULL
                    """,
                    (
                        pending_token,
                        details.fingerprint_sha256,
                        details.algorithm,
                        now,
                        policy,
                        now,
                        record.id,
                        record.revision,
                    ),
                )
                if update_cursor.rowcount != 1:
                    raise HostKeyManagerError(
                        "Host Key 首次信任并发冲突，连接被拒绝。",
                        details.as_dict(),
                        key=key,
                        code="HOST_KEY_UPDATE_CONFLICT",
                    )
                self._append_history(
                    connection,
                    record,
                    details,
                    event_type="PENDING_TRUST",
                    old_fingerprint="",
                    new_fingerprint=details.fingerprint_sha256,
                    reason=reason,
                    result="PENDING",
                    pending_token=pending_token,
                )
                self._append_event(
                    connection,
                    record,
                    details,
                    event_type="HOST_KEY_TRUST_PENDING",
                    old_fingerprint="",
                    new_fingerprint=details.fingerprint_sha256,
                    policy=policy,
                    result="PENDING",
                    reason=reason,
                    pending_token=pending_token,
                )
                return HostKeyObservation(
                    details,
                    "ADD",
                    "HOST_KEY_AUTO_ADDED",
                    True,
                    pending_token,
                    "",
                    policy,
                    reason,
                )

            if policy == STRICT:
                self._append_history(
                    connection,
                    record,
                    details,
                    event_type="STRICT_REJECTED",
                    old_fingerprint=current,
                    new_fingerprint=details.fingerprint_sha256,
                    reason=reason,
                    result="REJECTED",
                )
                self._append_event(
                    connection,
                    record,
                    details,
                    event_type="HOST_KEY_CHANGED",
                    old_fingerprint=current,
                    new_fingerprint=details.fingerprint_sha256,
                    policy=policy,
                    result="REJECTED",
                    reason=reason,
                )
                return HostKeyObservation(
                    details,
                    "REJECT",
                    "HOST_KEY_STRICT_REJECTED",
                    False,
                    "",
                    current,
                    policy,
                    reason,
                )

            pending_token = _token()
            update_cursor = connection.execute(
                """
                UPDATE host_key_records
                SET pending_token = ?, pending_fingerprint_sha256 = ?,
                    pending_key_type = ?, pending_status = 'PENDING_UPDATE',
                    pending_observed_at = ?, update_policy = ?, updated_at = ?
                WHERE id = ? AND revision = ? AND pending_token IS NULL
                """,
                (
                    pending_token,
                    details.fingerprint_sha256,
                    details.algorithm,
                    now,
                    policy,
                    now,
                    record.id,
                    record.revision,
                ),
            )
            if update_cursor.rowcount != 1:
                raise HostKeyManagerError(
                    "Host Key 并发更新冲突，连接被拒绝。",
                    details.as_dict(),
                    key=key,
                    code="HOST_KEY_UPDATE_CONFLICT",
                )
            self._append_history(
                connection,
                record,
                details,
                event_type="PENDING_UPDATE",
                old_fingerprint=current,
                new_fingerprint=details.fingerprint_sha256,
                reason=reason,
                result="PENDING",
                pending_token=pending_token,
            )
            return HostKeyObservation(
                details,
                "REPLACE",
                "HOST_KEY_CHANGED",
                True,
                pending_token,
                current,
                policy,
                reason,
            )

    def commit_success(self, pending_token: str) -> HostKeyObservation:
        token = str(pending_token or "").strip()
        if not token:
            raise ValueError("pending Host Key token is required")
        now = _now()
        with self.repository.write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM host_key_records WHERE pending_token = ?", (token,)
            ).fetchone()
            record = self.repository.record_from_row(row)
            if record is None:
                applied = connection.execute(
                    """
                    SELECT device_id, management_ip, ssh_port, key_type,
                           new_fingerprint_sha256, update_policy, event_type
                    FROM host_key_events
                    WHERE pending_token = ? AND result = 'APPLIED'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (token,),
                ).fetchone()
                if applied is not None:
                    details = HostKeyDetails(
                        str(applied["management_ip"]),
                        int(applied["ssh_port"]),
                        str(applied["key_type"]),
                        str(applied["new_fingerprint_sha256"] or ""),
                    )
                    event_type = str(applied["event_type"])
                    return HostKeyObservation(
                        details,
                        "ADD" if event_type == "HOST_KEY_AUTO_ADDED" else "REPLACE",
                        event_type,
                        True,
                        "",
                        "",
                        str(applied["update_policy"]),
                        "authenticated_connection_succeeded",
                    )
                raise HostKeyManagerError(
                    "Host Key pending 状态不存在或已完成。",
                    {"pending_token": token},
                    code="HOST_KEY_PENDING_NOT_FOUND",
                )
            fingerprint = record.pending_fingerprint_sha256 or ""
            key_type = record.pending_key_type or ""
            old = record.current_fingerprint_sha256 or ""
            if record.pending_status == "VERIFYING":
                event_type = "VERIFIED"
                status = "HOST_KEY_VERIFIED"
                action = "KEEP"
                first_seen = record.first_seen_at or now
                last_changed = record.last_changed_at
            elif not old:
                event_type = "TRUSTED"
                status = "HOST_KEY_AUTO_ADDED"
                action = "ADD"
                first_seen = now
                last_changed = record.last_changed_at
            else:
                event_type = "REPLACED"
                status = "HOST_KEY_AUTO_UPDATED"
                action = "REPLACE"
                first_seen = record.first_seen_at or now
                last_changed = now
            connection.execute(
                """
                UPDATE host_key_records
                SET key_type = ?, current_fingerprint_sha256 = ?,
                    first_seen_at = ?, last_verified_at = ?, last_changed_at = ?,
                    pending_token = NULL, pending_fingerprint_sha256 = NULL,
                    pending_key_type = NULL, pending_status = NULL,
                    pending_observed_at = NULL, revision = revision + 1,
                    updated_at = ?
                WHERE id = ? AND pending_token = ?
                """,
                (
                    key_type,
                    fingerprint,
                    first_seen,
                    now,
                    last_changed,
                    now,
                    record.id,
                    token,
                ),
            )
            details = HostKeyDetails(
                record.management_ip,
                record.ssh_port,
                key_type,
                fingerprint,
            )
            self._append_history(
                connection,
                record,
                details,
                event_type=event_type,
                old_fingerprint=old,
                new_fingerprint=fingerprint,
                reason="authenticated_connection_succeeded",
                result="APPLIED",
                pending_token=token,
            )
            self._append_event(
                connection,
                record,
                details,
                event_type=status,
                old_fingerprint=old,
                new_fingerprint=fingerprint,
                policy=record.update_policy,
                result="APPLIED",
                reason="authenticated_connection_succeeded",
                pending_token=token,
            )
            return HostKeyObservation(
                details,
                action,
                status,
                True,
                "",
                old,
                record.update_policy,
                "authenticated_connection_succeeded",
            )

    def reject_pending(self, pending_token: str, *, reason: str) -> None:
        token = str(pending_token or "").strip()
        if not token:
            return
        now = _now()
        with self.repository.write_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM host_key_records WHERE pending_token = ?", (token,)
            ).fetchone()
            record = self.repository.record_from_row(row)
            if record is None:
                return
            fingerprint = record.pending_fingerprint_sha256 or ""
            details = HostKeyDetails(
                record.management_ip,
                record.ssh_port,
                record.pending_key_type or record.key_type,
                fingerprint,
            )
            self._append_history(
                connection,
                record,
                details,
                event_type="UPDATE_FAILED",
                old_fingerprint=record.current_fingerprint_sha256 or "",
                new_fingerprint=fingerprint,
                reason=reason,
                result="FAILED",
                pending_token=token,
            )
            self._append_event(
                connection,
                record,
                details,
                event_type="HOST_KEY_UPDATE_FAILED",
                old_fingerprint=record.current_fingerprint_sha256 or "",
                new_fingerprint=fingerprint,
                policy=record.update_policy,
                result="FAILED",
                reason=reason,
                pending_token=token,
            )
            connection.execute(
                """
                UPDATE host_key_records
                SET pending_token = NULL, pending_fingerprint_sha256 = NULL,
                    pending_key_type = NULL, pending_status = NULL,
                    pending_observed_at = NULL, updated_at = ?
                WHERE id = ? AND pending_token = ?
                """,
                (now, record.id, token),
            )

    def observe_successful_connection(
        self,
        device_id: str,
        management_ip: str,
        ssh_port: int,
        key: Any,
        *,
        authorized: bool,
        update_policy: str | None = None,
        reason: str = "ssh_connection",
    ) -> HostKeyObservation:
        observation = self.stage_connection(
            device_id,
            management_ip,
            ssh_port,
            key,
            authorized=authorized,
            update_policy=update_policy,
            reason=reason,
        )
        if not observation.allowed:
            message = (
                "SSH Host Key 与 STRICT 策略不一致，连接已拒绝。"
                if observation.status == "HOST_KEY_STRICT_REJECTED"
                else "SSH Host Key 记录或并发状态无效，连接已拒绝。"
            )
            raise HostKeyManagerError(
                message,
                observation.as_dict(),
                key=key,
                code="HOST_KEY_STRICT_REJECTED",
            )
        try:
            return self.commit_success(observation.pending_token)
        except Exception as exc:
            self.reject_pending(observation.pending_token, reason=str(exc) or "Host Key commit failed")
            raise

    def get_record(self, device_id: str, management_ip: str, ssh_port: int = 22) -> dict[str, object] | None:
        host, port = self._normalize_endpoint(management_ip, ssh_port)
        return _record_dict(self.repository.get(str(device_id).strip(), host, port))

    def list_history(self, device_id: str, management_ip: str | None = None, ssh_port: int | None = None, *, limit: int = 100) -> list[dict[str, object]]:
        return self.repository.list_history(str(device_id).strip(), management_ip, ssh_port, limit=limit)

    def list_events(self, device_id: str, management_ip: str | None = None, ssh_port: int | None = None, *, limit: int = 100) -> list[dict[str, object]]:
        return self.repository.list_events(str(device_id).strip(), management_ip, ssh_port, limit=limit)

    def is_registered_device(self, site_id: str, device_id: str) -> bool:
        """Return whether the target belongs to the caller's registered site.

        Automatic trust is deliberately gated by the device resource table,
        not by the presence of a caller-supplied UUID alone.  When an
        application context has no site id, the legacy demo site is the only
        fallback; a specified site never falls through to another site.
        """

        checked_device_id = str(device_id or "").strip()
        checked_site_id = str(site_id or "").strip()
        if not checked_device_id:
            return False
        sites = [checked_site_id] if checked_site_id else ["demo"]
        for site in sites:
            database_path = self.paths.site_db_path(site)
            if not database_path.is_file():
                continue
            try:
                return DeviceRepository(Database(database_path)).exists_by_uuid(
                    checked_device_id
                )
            except Exception:
                return False
        return False

    def has_device_resource_authority(self, site_id: str) -> bool:
        """Return whether the site database is available for authz checks."""

        checked_site_id = str(site_id or "").strip() or "demo"
        return self.paths.site_db_path(checked_site_id).is_file()

    @staticmethod
    def _inspect(host: str, port: int, key: Any) -> HostKeyDetails:
        algorithm = str(getattr(key, "get_name", lambda: "")() or "").strip()
        if algorithm not in SUPPORTED_HOST_KEY_ALGORITHMS:
            raise HostKeyManagerError(
                "SSH Host Key 算法不受支持，连接已拒绝。",
                {"host": str(host), "port": int(port or 22), "algorithm": algorithm},
                key=key,
                code="HOST_KEY_UNSUPPORTED_ALGORITHM",
            )
        try:
            fingerprint = key_fingerprint_sha256(key)
        except Exception as exc:
            raise HostKeyManagerError(
                "无法计算 SSH Host Key SHA-256 指纹，连接已拒绝。",
                {"host": str(host), "port": int(port or 22), "algorithm": algorithm},
                key=key,
                code="HOST_KEY_FINGERPRINT_INVALID",
            ) from exc
        if not _SHA256_FINGERPRINT_RE.fullmatch(fingerprint):
            raise HostKeyManagerError(
                "SSH Host Key SHA-256 指纹格式无效，连接已拒绝。",
                {"host": str(host), "port": int(port or 22), "algorithm": algorithm},
                key=key,
                code="HOST_KEY_FINGERPRINT_INVALID",
            )
        checked_host, checked_port = HostKeyManager._normalize_endpoint(host, port)
        return HostKeyDetails(checked_host, checked_port, algorithm, fingerprint)

    @staticmethod
    def _normalize_endpoint(host: str, port: int) -> tuple[str, int]:
        checked_host = str(host or "").strip()
        checked_port = int(port or 22)
        if not checked_host or not 1 <= checked_port <= 65535:
            raise ValueError("SSH Host Key endpoint is invalid")
        return checked_host, checked_port

    @staticmethod
    def _normalize_policy(policy: str) -> str:
        value = str(policy or AUTO_UPDATE).strip().upper()
        if value == "AUTO_REPLACE":
            value = AUTO_UPDATE
        if value not in HOST_KEY_POLICIES:
            raise ValueError(f"不支持的 Host Key 更新策略：{value}")
        return value

    @staticmethod
    def _assert_authorized(device_id: str, authorized: bool) -> None:
        if not str(device_id or "").strip() or not bool(authorized):
            raise HostKeyManagerError(
                "未知或未授权设备不得自动建立 Host Key 信任。",
                {"device_id": str(device_id or "")},
                code="HOST_KEY_TARGET_UNAUTHORIZED",
            )

    @staticmethod
    def _append_history(
        connection: Any,
        record: HostKeyRecord,
        details: HostKeyDetails,
        *,
        event_type: str,
        old_fingerprint: str,
        new_fingerprint: str,
        reason: str,
        result: str,
        pending_token: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO host_key_history(
                record_id, device_id, management_ip, ssh_port, key_type,
                fingerprint_sha256, event_type, old_fingerprint_sha256,
                new_fingerprint_sha256, observed_at, reason, result, pending_token
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.device_id,
                details.host,
                details.port,
                details.algorithm,
                details.fingerprint_sha256,
                event_type,
                old_fingerprint or None,
                new_fingerprint or None,
                _now(),
                str(reason or ""),
                str(result or ""),
                pending_token,
            ),
        )

    @staticmethod
    def _append_event(
        connection: Any,
        record: HostKeyRecord,
        details: HostKeyDetails,
        *,
        event_type: str,
        old_fingerprint: str,
        new_fingerprint: str,
        policy: str,
        result: str,
        reason: str,
        pending_token: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO host_key_events(
                event_id, record_id, device_id, management_ip, ssh_port,
                key_type, event_type, old_fingerprint_sha256,
                new_fingerprint_sha256, update_policy, result, reason,
                pending_token, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _token(),
                record.id,
                record.device_id,
                details.host,
                details.port,
                details.algorithm,
                event_type,
                old_fingerprint or None,
                new_fingerprint or None,
                policy,
                result,
                str(reason or ""),
                pending_token,
                _now(),
            ),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _token() -> str:
    return uuid.uuid4().hex


def _record_dict(record: HostKeyRecord | None) -> dict[str, object] | None:
    if record is None:
        return None
    return {
        "id": record.id,
        "device_id": record.device_id,
        "management_ip": record.management_ip,
        "ssh_port": record.ssh_port,
        "key_type": record.key_type,
        "current_fingerprint_sha256": record.current_fingerprint_sha256,
        "first_seen_at": record.first_seen_at,
        "last_verified_at": record.last_verified_at,
        "last_changed_at": record.last_changed_at,
        "update_policy": record.update_policy,
        "pending_token": record.pending_token,
        "pending_fingerprint_sha256": record.pending_fingerprint_sha256,
        "pending_key_type": record.pending_key_type,
        "pending_status": record.pending_status,
        "pending_observed_at": record.pending_observed_at,
        "revision": record.revision,
    }


__all__ = [
    "AUTO_UPDATE",
    "STRICT",
    "HOST_KEY_POLICIES",
    "SUPPORTED_HOST_KEY_ALGORITHMS",
    "HostKeyManager",
    "HostKeyManagerError",
    "HostKeyObservation",
]
