from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.device_credential_store import (
    CredentialFieldResolution,
    DEVICE_SECRET_FIELDS,
    DEVICE_SECRET_STORAGE_FIELDS,
    credential_is_complete,
    ensure_device_credential_schema,
    read_device_credential_states,
    replace_device_credential_state,
    resolve_device_credentials,
)
from netconsole.models.device import (
    Device,
    normalize_operation_status,
    normalize_project_phase,
)
from netconsole.models.device_address import (
    DevicePrimaryAddressConflictError,
    normalize_ip_address,
)
from netconsole.utils.natural_sort import natural_text_key


SEARCH_COLUMNS = ("d.name", "d.system_name", "d.primary_address", "d.backup_address", "d.station", "d.remark", "d.device_type", "d.device_vendor", "g.name")


class DeviceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def backup_to(self, target: Path) -> None:
        """Create and validate a consistent SQLite backup at *target*."""

        source_path = self.database.path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError("设备数据库不存在")
        target = Path(target).resolve()
        with closing(self.database.connect()) as source, closing(
            Database(target).connect()
        ) as destination:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("设备数据库备份完整性校验失败")

    def create(self, device: Device) -> Device:
        now = datetime.now().isoformat(timespec="seconds")
        device.ensure_device_uuid()
        self._normalize_primary_address(device)
        conflict = self.find_by_primary_address(device.primary_address)
        if conflict is not None:
            raise self._primary_address_conflict(device.primary_address, conflict)
        record = device.to_record()
        record["created_at"] = now
        record["updated_at"] = now
        record.pop("id", None)
        credential_states: dict[str, CredentialFieldResolution | None] = {}
        for field in DEVICE_SECRET_FIELDS:
            credential_states[field] = (
                CredentialFieldResolution("available", "local_database")
                if record.get(field)
                else None
            )
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO devices ({', '.join(columns)}) VALUES ({placeholders})"
        with self.database.connect() as conn:
            ensure_device_credential_schema(conn)
            try:
                cursor = conn.execute(sql, [record[column] for column in columns])
            except sqlite3.IntegrityError as exc:
                if self._is_primary_address_integrity_error(exc):
                    conflict = self.find_by_primary_address(device.primary_address)
                    raise self._primary_address_conflict(
                        device.primary_address, conflict
                    ) from exc
                raise
            for field, state in credential_states.items():
                replace_device_credential_state(
                    conn, str(device.device_uuid), field, state
                )
            conn.commit()
            return self.get(int(cursor.lastrowid))

    def get(self, device_id: int) -> Device:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            states = read_device_credential_states(conn)
        if row is None:
            raise KeyError(f"Device not found: {device_id}")
        return self._device_from_row(row, states)

    def get_by_uuid(self, device_uuid: str) -> Device | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()
            states = read_device_credential_states(conn, [device_uuid])
        return self._device_from_row(row, states) if row is not None else None

    def update(self, device: Device) -> Device:
        if device.id is None:
            raise ValueError("Device id is required for update")
        self._normalize_primary_address(device)
        conflict = self.find_by_primary_address(
            device.primary_address, exclude_device_id=device.id
        )
        if conflict is not None:
            raise self._primary_address_conflict(device.primary_address, conflict)
        record = device.to_record()
        record["updated_at"] = datetime.now().isoformat(timespec="seconds")
        record.pop("created_at", None)
        record.pop("device_uuid", None)
        device_id = record.pop("id")
        clear_fields = {
            str(value)
            for value in getattr(device, "credential_clear_fields", ())
            if str(value) in DEVICE_SECRET_FIELDS
        }
        with self.database.connect() as conn:
            ensure_device_credential_schema(conn)
            current = conn.execute(
                "SELECT * FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if current is None:
                raise KeyError(f"Device not found: {device_id}")
            current_values = dict(current)
            current_states = read_device_credential_states(
                conn, [str(device.device_uuid or current_values.get("device_uuid") or "")]
            ).get(str(device.device_uuid or current_values.get("device_uuid") or ""), {})
            state_updates: dict[str, CredentialFieldResolution | None] = {}
            for field in DEVICE_SECRET_STORAGE_FIELDS:
                canonical = self._canonical_secret_field(field, device)
                if canonical in clear_fields:
                    record[field] = None
                    if field in DEVICE_SECRET_FIELDS:
                        state_updates[field] = None
                    continue
                value = record.get(field)
                if value:
                    if field in DEVICE_SECRET_FIELDS and credential_is_complete(
                        record, field
                    ):
                        state_updates[field] = CredentialFieldResolution(
                            "available", "local_database"
                        )
                    continue
                persisted_state = current_states.get(canonical)
                if current_values.get(field) or (
                    persisted_state
                    and persisted_state.status
                    == "needs_reentry"
                ):
                    record.pop(field, None)
                    continue
                record[field] = None
                if field in DEVICE_SECRET_FIELDS:
                    state_updates[field] = None
            assignments = ", ".join(f"{column} = ?" for column in record)
            try:
                conn.execute(
                    f"UPDATE devices SET {assignments} WHERE id = ?",
                    [record[column] for column in record] + [device_id],
                )
            except sqlite3.IntegrityError as exc:
                if self._is_primary_address_integrity_error(exc):
                    conflict = self.find_by_primary_address(
                        device.primary_address, exclude_device_id=int(device_id)
                    )
                    raise self._primary_address_conflict(
                        device.primary_address, conflict
                    ) from exc
                raise
            device_uuid = str(device.device_uuid or current_values.get("device_uuid") or "")
            for field, state in state_updates.items():
                replace_device_credential_state(conn, device_uuid, field, state)
            persisted = conn.execute(
                "SELECT * FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if persisted is None:
                raise sqlite3.DatabaseError("设备凭据保存后复核失败")
            for field in DEVICE_SECRET_STORAGE_FIELDS:
                if field in record and record[field] and persisted[field] != record[field]:
                    raise sqlite3.DatabaseError(f"{field} 保存后复核失败")
            for field in clear_fields:
                if field in persisted.keys() and persisted[field] not in {None, ""}:
                    raise sqlite3.DatabaseError(f"{field} 清除后复核失败")
            conn.commit()
        return self.get(int(device_id))

    def delete(self, device_id: int) -> None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT device_uuid FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if row is not None and self._table_exists(conn, "device_credential_states"):
                conn.execute(
                    "DELETE FROM device_credential_states WHERE device_uuid = ?",
                    (str(row["device_uuid"]),),
                )
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            conn.commit()

    def delete_many_by_uuid(self, device_uuids: list[str]) -> list[str]:
        """在一个事务中校验并删除整批设备。"""

        values = list(
            dict.fromkeys(
                str(value or "").strip()
                for value in device_uuids
                if str(value or "").strip()
            )
        )
        if not values:
            return []
        placeholders = ", ".join("?" for _ in values)
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT device_uuid FROM devices WHERE device_uuid IN ({placeholders})",
                values,
            ).fetchall()
            found = {str(row["device_uuid"]) for row in rows}
            missing = [value for value in values if value not in found]
            if missing:
                conn.rollback()
                raise KeyError(missing[0])
            conn.execute(
                f"DELETE FROM devices WHERE device_uuid IN ({placeholders})", values
            )
            if self._table_exists(conn, "device_credential_states"):
                conn.execute(
                    f"DELETE FROM device_credential_states WHERE device_uuid IN ({placeholders})",
                    values,
                )
            conn.commit()
        return values

    def exists_by_uuid(self, device_uuid: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute("SELECT 1 FROM devices WHERE device_uuid = ? LIMIT 1", (device_uuid,)).fetchone()
        return row is not None

    def find_by_primary_address(
        self,
        primary_address: object,
        *,
        exclude_device_id: int | None = None,
    ) -> Device | None:
        normalized = normalize_ip_address(primary_address)
        if normalized is None:
            return None
        clauses = ["normalized_primary_address = ?"]
        params: list[object] = [normalized]
        if exclude_device_id is not None:
            clauses.append("id <> ?")
            params.append(int(exclude_device_id))
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM devices
                WHERE {' AND '.join(clauses)}
                ORDER BY id
                LIMIT 2
                """,
                params,
            ).fetchall()
            states = read_device_credential_states(
                conn, [str(row["device_uuid"]) for row in rows]
            )
        if len(rows) > 1:
            first = rows[0]
            raise DevicePrimaryAddressConflictError(
                normalized,
                device_id=int(first["id"]),
                device_name=str(first["name"] or ""),
                site_name=self._site_name(),
            )
        return self._device_from_row(rows[0], states) if rows else None

    def list(
        self,
        search: str | None = None,
        vendor: str | None = None,
        device_type: str | None = None,
        group_filter: int | str | None = None,
        project_phase: str | None = None,
        operation_status: str | None = None,
    ) -> list[Device]:
        clauses: list[str] = []
        params: list[object] = []
        if search:
            like = f"%{search}%"
            clauses.append("(" + " OR ".join(f"{column} LIKE ?" for column in SEARCH_COLUMNS) + ")")
            params.extend([like] * len(SEARCH_COLUMNS))
        if vendor:
            clauses.append("d.device_vendor = ?")
            params.append(vendor)
        if device_type:
            clauses.append("d.device_type = ?")
            params.append(device_type)
        if project_phase and project_phase != "all":
            clauses.append("d.project_phase = ?")
            params.append(normalize_project_phase(project_phase))
        if operation_status and operation_status != "all":
            clauses.append("d.operation_status = ?")
            params.append(normalize_operation_status(operation_status))
        if group_filter == "__ungrouped__":
            clauses.append("d.group_id IS NULL")
        elif group_filter is not None:
            clauses.append("d.group_id = ?")
            params.append(int(group_filter))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT d.*
                FROM devices d
                LEFT JOIN device_groups g ON g.id = d.group_id
                {where}
                ORDER BY d.name ASC, d.system_name ASC, d.primary_address ASC, d.id ASC
                """,
                params,
            ).fetchall()
            states = read_device_credential_states(
                conn, [str(row["device_uuid"]) for row in rows]
            )
        devices = [self._device_from_row(row, states) for row in rows]
        return sorted(devices, key=_device_natural_sort_key)

    def update_lifecycle_many(
        self,
        device_uuids: list[str],
        *,
        project_phase: str | None = None,
        operation_status: str | None = None,
        reason: str | None = None,
        updated_by: str | None = None,
    ) -> int:
        unique_uuids = list(dict.fromkeys(str(value).strip() for value in device_uuids))
        if not unique_uuids:
            raise ValueError("至少选择一台设备")
        assignments: list[str] = []
        params: list[object] = []
        now = datetime.now().isoformat(timespec="seconds")
        if project_phase is not None:
            assignments.append("project_phase = ?")
            params.append(normalize_project_phase(project_phase))
        if operation_status is not None:
            assignments.extend(
                (
                    "operation_status = ?",
                    "operation_status_reason = ?",
                    "operation_status_updated_at = ?",
                    "operation_status_updated_by = ?",
                )
            )
            params.extend(
                (
                    normalize_operation_status(operation_status),
                    str(reason or "").strip() or None,
                    now,
                    str(updated_by or "").strip() or None,
                )
            )
        if not assignments:
            raise ValueError("未提供要修改的建设阶段或投运状态")
        assignments.append("updated_at = ?")
        params.append(now)
        placeholders = ", ".join("?" for _ in unique_uuids)
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM devices WHERE device_uuid IN ({placeholders})",
                    unique_uuids,
                ).fetchone()[0]
            )
            if count != len(unique_uuids):
                raise KeyError("部分设备不存在，未修改任何设备")
            cursor = conn.execute(
                f"""
                UPDATE devices
                SET {', '.join(assignments)}
                WHERE device_uuid IN ({placeholders})
                """,
                [*params, *unique_uuids],
            )
            conn.commit()
        return int(cursor.rowcount or 0)

    def update_group(self, device_id: int, group_id: int | None) -> Device:
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE devices SET group_id = ?, updated_at = ? WHERE id = ?",
                (group_id, datetime.now().isoformat(timespec="seconds"), device_id),
            )
            conn.commit()
        return self.get(device_id)

    def update_https_port(self, device_id: int, https_port: int | None) -> Device:
        if https_port is not None and not 1 <= int(https_port) <= 65535:
            raise ValueError(f"Invalid HTTPS port: {https_port}")
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE devices SET https_port = ?, updated_at = ? WHERE id = ?",
                (https_port, datetime.now().isoformat(timespec="seconds"), device_id),
            )
            conn.commit()
        return self.get(device_id)

    def update_system_name_by_uuid(self, device_uuid: str, system_name: str) -> bool:
        value = str(system_name or "").strip()
        if not device_uuid or not value:
            return False
        with self.database.connect() as conn:
            cursor = conn.execute(
                "UPDATE devices SET system_name = ?, updated_at = ? WHERE device_uuid = ?",
                (value, datetime.now().isoformat(timespec="seconds"), device_uuid),
            )
            conn.commit()
        return cursor.rowcount > 0

    def update_sysname_by_uuid(self, device_uuid: str, sysname: str) -> bool:
        return self.update_system_name_by_uuid(device_uuid, sysname)

    def update_mac_address_by_uuid(self, device_uuid: str, mac_address: str) -> bool:
        value = str(mac_address or "").strip()
        if not device_uuid or not value:
            return False
        with self.database.connect() as conn:
            cursor = conn.execute(
                "UPDATE devices SET mac_address = ?, updated_at = ? WHERE device_uuid = ?",
                (value, datetime.now().isoformat(timespec="seconds"), device_uuid),
            )
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _canonical_secret_field(field: str, device: Device) -> str:
        if field != "password":
            return field
        return "telnet_password" if bool(device.telnet_enabled) and not bool(device.ssh_enabled) else "ssh_password"

    @staticmethod
    def _normalize_primary_address(device: Device) -> None:
        normalized = normalize_ip_address(device.primary_address)
        device.primary_address = normalized or ""
        device.normalized_primary_address = normalized

    def _primary_address_conflict(
        self, primary_address: object, conflict: Device | None
    ) -> DevicePrimaryAddressConflictError:
        normalized = normalize_ip_address(primary_address) or ""
        return DevicePrimaryAddressConflictError(
            normalized,
            device_id=int(conflict.id) if conflict and conflict.id is not None else None,
            device_name=str(conflict.name or "") if conflict else "",
            site_name=self._site_name(),
        )

    def _site_name(self) -> str:
        return self.database.path.parent.parent.name

    @staticmethod
    def _is_primary_address_integrity_error(exc: sqlite3.IntegrityError) -> bool:
        message = str(exc).casefold()
        return (
            "uq_devices_normalized_primary_address" in message
            or "devices.normalized_primary_address" in message
        )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone() is not None

    @staticmethod
    def _device_from_row(
        row: sqlite3.Row,
        states: dict[str, dict[str, CredentialFieldResolution]],
    ) -> Device:
        raw = dict(row)
        device_uuid = str(raw.get("device_uuid") or "")
        values, resolution = resolve_device_credentials(
            raw, states.get(device_uuid, {})
        )
        device = Device.from_mapping(values)
        device.credential_status = resolution.status
        device.credential_source = resolution.source
        device.credential_error_code = resolution.error_code
        device.credential_field_statuses = {
            field: state.status for field, state in resolution.fields.items()
        }
        device.credential_field_sources = {
            field: state.source for field, state in resolution.fields.items()
        }
        device.credential_field_errors = {
            field: state.error_code for field, state in resolution.fields.items()
        }
        return device


def _device_natural_sort_key(device: Device) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], int]:
    return (
        natural_text_key(device.name),
        natural_text_key(device.system_name),
        natural_text_key(device.primary_address),
        int(device.id or 0),
    )
