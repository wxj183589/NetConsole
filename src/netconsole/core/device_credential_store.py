from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

DEVICE_SECRET_FIELDS = (
    "ssh_password",
    "telnet_password",
    "tunnel1_password",
    "tunnel2_password",
    "snmp_ro_community",
)
DEVICE_SECRET_STORAGE_FIELDS = ("password", *DEVICE_SECRET_FIELDS)
DEVICE_CREDENTIAL_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_credential_states (
    device_uuid TEXT NOT NULL,
    credential_field TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_uuid, credential_field),
    FOREIGN KEY (device_uuid) REFERENCES devices(device_uuid) ON DELETE CASCADE
);
"""

_STATUS_PRIORITY = {
    "needs_reentry": 60,
    "key_file_missing": 30,
    "missing": 20,
    "available": 10,
}


@dataclass(frozen=True)
class CredentialFieldResolution:
    status: str
    source: str
    error_code: str = ""


@dataclass(frozen=True)
class DeviceCredentialResolution:
    status: str
    source: str
    error_code: str
    fields: dict[str, CredentialFieldResolution]


def ensure_device_credential_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(DEVICE_CREDENTIAL_STATE_SCHEMA)


def resolve_device_credentials(
    record: Mapping[str, object],
    persisted_states: Mapping[str, CredentialFieldResolution] | None = None,
) -> tuple[dict[str, object], DeviceCredentialResolution]:
    values = dict(record)
    if not values.get("ssh_username") and values.get("username"):
        values["ssh_username"] = values["username"]
    if not values.get("ssh_password") and values.get("password"):
        values["ssh_password"] = values["password"]
    persisted = dict(persisted_states or {})
    fields: dict[str, CredentialFieldResolution] = {}

    for field in DEVICE_SECRET_FIELDS:
        raw = _secret_value(values, field)
        if raw is None or raw == "":
            fields[field] = persisted.get(
                field,
                CredentialFieldResolution("missing", "none", "CREDENTIAL_MISSING"),
            )
            continue
        if not credential_is_complete(values, field):
            fields[field] = persisted.get(
                field,
                CredentialFieldResolution("missing", "none", "CREDENTIAL_INCOMPLETE"),
            )
            continue
        fields[field] = CredentialFieldResolution("available", "local_database")

    for field in DEVICE_SECRET_FIELDS:
        fields.setdefault(
            field,
            persisted.get(
                field,
                CredentialFieldResolution("missing", "none", "CREDENTIAL_MISSING"),
            ),
        )

    relevant = _relevant_fields(values)
    selected = max(
        (fields[field] for field in relevant),
        key=lambda item: _STATUS_PRIORITY.get(item.status, 0),
        default=CredentialFieldResolution("missing", "none", "CREDENTIAL_MISSING"),
    )
    return values, DeviceCredentialResolution(
        status=selected.status,
        source=selected.source,
        error_code=selected.error_code,
        fields=fields,
    )


def read_device_credential_states(
    connection: sqlite3.Connection,
    device_uuids: list[str] | None = None,
) -> dict[str, dict[str, CredentialFieldResolution]]:
    if not _table_exists(connection, "device_credential_states"):
        return {}
    params: list[object] = []
    where = ""
    if device_uuids:
        placeholders = ", ".join("?" for _ in device_uuids)
        where = f" WHERE device_uuid IN ({placeholders})"
        params.extend(device_uuids)
    rows = connection.execute(
        "SELECT device_uuid, credential_field, status, source, error_code "
        f"FROM device_credential_states{where}",
        params,
    ).fetchall()
    result: dict[str, dict[str, CredentialFieldResolution]] = {}
    for row in rows:
        values = _row_mapping(row)
        result.setdefault(str(values["device_uuid"]), {})[
            str(values["credential_field"])
        ] = CredentialFieldResolution(
            str(values["status"]),
            str(values["source"]),
            str(values.get("error_code") or ""),
        )
    return result


def replace_device_credential_state(
    connection: sqlite3.Connection,
    device_uuid: str,
    field: str,
    resolution: CredentialFieldResolution | None,
) -> None:
    ensure_device_credential_schema(connection)
    if resolution is None or resolution.status == "missing":
        connection.execute(
            "DELETE FROM device_credential_states WHERE device_uuid = ? AND credential_field = ?",
            (device_uuid, field),
        )
        return
    now = datetime.now().isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO device_credential_states (
            device_uuid, credential_field, status, source, error_code, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_uuid, credential_field) DO UPDATE SET
            status = excluded.status,
            source = excluded.source,
            error_code = excluded.error_code,
            updated_at = excluded.updated_at
        """,
        (
            device_uuid,
            field,
            resolution.status,
            resolution.source,
            resolution.error_code,
            now,
        ),
    )


def sanitize_device_credentials_for_package(
    connection: sqlite3.Connection,
    *,
    infer_missing: bool = False,
) -> int:
    """Remove secrets and preserve only a non-secret re-entry marker."""

    if not _table_exists(connection, "devices"):
        return 0
    ensure_device_credential_schema(connection)
    columns = _table_columns(connection, "devices")
    selected = [
        name
        for name in (
            "device_uuid",
            "password",
            *DEVICE_SECRET_FIELDS,
            "ssh_enabled",
            "ssh_username",
            "telnet_enabled",
            "telnet_username",
            "snmp_enabled",
            "tunnel1_enabled",
            "tunnel1_host",
            "tunnel2_enabled",
            "tunnel2_host",
        )
        if name in columns
    ]
    if "device_uuid" not in selected:
        return 0
    rows = connection.execute(
        f"SELECT {', '.join(_quote(name) for name in selected)} FROM devices"
    ).fetchall()
    existing = read_device_credential_states(connection)
    connection.execute("DELETE FROM device_credential_states")
    affected: set[str] = set()
    for row in rows:
        values = _row_mapping(row, selected)
        device_uuid = str(values.get("device_uuid") or "")
        if not device_uuid:
            continue
        for field in DEVICE_SECRET_FIELDS:
            had_secret = bool(values.get(field))
            if field == "ssh_password" and not had_secret:
                had_secret = bool(values.get("password")) and bool(
                    values.get("ssh_enabled", 1)
                )
            prior = existing.get(device_uuid, {}).get(field)
            needs_reentry = had_secret or bool(
                prior and prior.status == "needs_reentry"
            )
            if infer_missing and not needs_reentry:
                needs_reentry = _field_was_configured(values, field)
            if not needs_reentry:
                continue
            affected.add(device_uuid)
            replace_device_credential_state(
                connection,
                device_uuid,
                field,
                CredentialFieldResolution(
                    "needs_reentry",
                    "imported_reference",
                    "CREDENTIAL_REENTRY_REQUIRED",
                ),
            )
    secret_columns = [
        field for field in DEVICE_SECRET_STORAGE_FIELDS if field in columns
    ]
    if secret_columns:
        connection.execute(
            "UPDATE devices SET "
            + ", ".join(f"{_quote(field)} = NULL" for field in secret_columns)
        )
    return len(affected)


def credential_reentry_count(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "device_credential_states"):
        return 0
    row = connection.execute(
        "SELECT COUNT(DISTINCT device_uuid) FROM device_credential_states "
        "WHERE status = 'needs_reentry'"
    ).fetchone()
    return int(row[0] if row else 0)


def credential_is_complete(values: Mapping[str, object], field: str) -> bool:
    if not _secret_value(values, field):
        return False
    if field == "ssh_password":
        return bool(values.get("ssh_username") or values.get("username"))
    if field == "telnet_password":
        return bool(values.get("telnet_username") or values.get("username"))
    if field == "snmp_ro_community":
        return True
    prefix = field.removesuffix("_password")
    return bool(values.get(f"{prefix}_username"))


def repair_device_credential_states(connection: sqlite3.Connection) -> int:
    """Clear stale re-entry markers only when the actual credential is complete."""

    if not _table_exists(connection, "devices"):
        return 0
    ensure_device_credential_schema(connection)
    columns = _table_columns(connection, "devices")
    selected = [
        name
        for name in (
            "device_uuid",
            "username",
            "password",
            "ssh_username",
            "ssh_password",
            "telnet_username",
            "telnet_password",
            "tunnel1_username",
            "tunnel1_password",
            "tunnel2_username",
            "tunnel2_password",
            "snmp_ro_community",
        )
        if name in columns
    ]
    if "device_uuid" not in selected:
        return 0
    states = read_device_credential_states(connection)
    repaired_devices: set[str] = set()
    for row in connection.execute(
        f"SELECT {', '.join(_quote(name) for name in selected)} FROM devices"
    ):
        values = _row_mapping(row, selected)
        device_uuid = str(values.get("device_uuid") or "")
        for field in DEVICE_SECRET_FIELDS:
            state = states.get(device_uuid, {}).get(field)
            if (
                state is None
                or state.status != "needs_reentry"
                or not credential_is_complete(values, field)
            ):
                continue
            replace_device_credential_state(
                connection,
                device_uuid,
                field,
                CredentialFieldResolution("available", "local_database"),
            )
            repaired_devices.add(device_uuid)
    return len(repaired_devices)


def _secret_value(values: Mapping[str, object], field: str) -> object:
    value = values.get(field)
    if field == "ssh_password" and not value:
        return values.get("password")
    return value


def _relevant_fields(values: Mapping[str, object]) -> tuple[str, ...]:
    fields: list[str] = []
    if bool(values.get("ssh_enabled")):
        fields.append("ssh_password")
    elif bool(values.get("telnet_enabled")):
        fields.append("telnet_password")
    elif bool(values.get("snmp_enabled")):
        fields.append("snmp_ro_community")
    for prefix in ("tunnel1", "tunnel2"):
        if bool(values.get(f"{prefix}_enabled")) or bool(values.get(f"{prefix}_host")):
            fields.append(f"{prefix}_password")
    return tuple(fields or ("ssh_password",))


def _field_was_configured(values: Mapping[str, object], field: str) -> bool:
    if field == "ssh_password":
        return bool(values.get("ssh_enabled")) and bool(values.get("ssh_username"))
    if field == "telnet_password":
        return bool(values.get("telnet_enabled")) and bool(
            values.get("telnet_username")
        )
    if field == "snmp_ro_community":
        return bool(values.get("snmp_enabled"))
    prefix = field.removesuffix("_password")
    return bool(values.get(f"{prefix}_enabled")) or bool(values.get(f"{prefix}_host"))


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
    }


def _row_mapping(
    row: object,
    columns: list[str] | None = None,
) -> dict[str, object]:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    values = tuple(row)  # type: ignore[arg-type]
    names = columns or [
        "device_uuid",
        "credential_field",
        "status",
        "source",
        "error_code",
    ]
    return dict(zip(names, values, strict=False))


def _quote(identifier: str) -> str:
    if not str(identifier).replace("_", "").isalnum():
        raise ValueError("invalid SQLite identifier")
    return f'"{identifier}"'


__all__ = [
    "CredentialFieldResolution",
    "DEVICE_CREDENTIAL_STATE_SCHEMA",
    "DEVICE_SECRET_FIELDS",
    "DEVICE_SECRET_STORAGE_FIELDS",
    "DeviceCredentialResolution",
    "credential_reentry_count",
    "credential_is_complete",
    "ensure_device_credential_schema",
    "read_device_credential_states",
    "repair_device_credential_states",
    "replace_device_credential_state",
    "resolve_device_credentials",
    "sanitize_device_credentials_for_package",
]
