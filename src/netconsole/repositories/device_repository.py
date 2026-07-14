from __future__ import annotations

from datetime import datetime

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.utils.natural_sort import natural_text_key


SEARCH_COLUMNS = ("d.name", "d.system_name", "d.primary_address", "d.backup_address", "d.station", "d.remark", "d.device_type", "d.device_vendor", "g.name")


class DeviceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, device: Device) -> Device:
        now = datetime.now().isoformat(timespec="seconds")
        device.ensure_device_uuid()
        record = device.to_record()
        record["created_at"] = now
        record["updated_at"] = now
        record.pop("id", None)
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO devices ({', '.join(columns)}) VALUES ({placeholders})"
        with self.database.connect() as conn:
            cursor = conn.execute(sql, [record[column] for column in columns])
            conn.commit()
            return self.get(int(cursor.lastrowid))

    def get(self, device_id: int) -> Device:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            raise KeyError(f"Device not found: {device_id}")
        return Device.from_mapping(dict(row))

    def get_by_uuid(self, device_uuid: str) -> Device | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()
        return Device.from_mapping(dict(row)) if row is not None else None

    def update(self, device: Device) -> Device:
        if device.id is None:
            raise ValueError("Device id is required for update")
        record = device.to_record()
        record["updated_at"] = datetime.now().isoformat(timespec="seconds")
        record.pop("created_at", None)
        record.pop("device_uuid", None)
        device_id = record.pop("id")
        assignments = ", ".join(f"{column} = ?" for column in record)
        with self.database.connect() as conn:
            conn.execute(
                f"UPDATE devices SET {assignments} WHERE id = ?",
                [record[column] for column in record] + [device_id],
            )
            conn.commit()
        return self.get(int(device_id))

    def delete(self, device_id: int) -> None:
        with self.database.connect() as conn:
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            conn.commit()

    def exists_by_uuid(self, device_uuid: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute("SELECT 1 FROM devices WHERE device_uuid = ? LIMIT 1", (device_uuid,)).fetchone()
        return row is not None

    def list(
        self,
        search: str | None = None,
        vendor: str | None = None,
        device_type: str | None = None,
        group_filter: int | str | None = None,
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
        devices = [Device.from_mapping(dict(row)) for row in rows]
        return sorted(devices, key=_device_natural_sort_key)

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


def _device_natural_sort_key(device: Device) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], int]:
    return (
        natural_text_key(device.name),
        natural_text_key(device.system_name),
        natural_text_key(device.primary_address),
        int(device.id or 0),
    )
