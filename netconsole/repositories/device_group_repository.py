from __future__ import annotations

from datetime import datetime

from netconsole.core.database import Database
from netconsole.models.device_group import DeviceGroup


DEFAULT_DEVICE_GROUPS: tuple[tuple[str, int], ...] = (
    ("COCC", 10),
    ("BOCC", 20),
    ("车站", 30),
    ("车载", 40),
)
LEGACY_CUSTOM_GROUP_NAME = "自定义"


class DuplicateGroupName(ValueError):
    pass


class DeviceGroupRepository:
    def __init__(self, database: Database, site_id: str) -> None:
        self.database = database
        self.site_id = site_id

    def list(self) -> list[DeviceGroup]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM device_groups
                WHERE site_id = ?
                ORDER BY
                    CASE
                        WHEN LOWER(name) = LOWER('COCC') THEN 10
                        WHEN LOWER(name) = LOWER('BOCC') THEN 20
                        WHEN name = '车站' THEN 30
                        WHEN name = '车载' THEN 40
                        ELSE 100000 + sort_order
                    END ASC,
                    name COLLATE NOCASE ASC
                """,
                (self.site_id,),
            ).fetchall()
        return [DeviceGroup(**dict(row)) for row in rows]

    def get(self, group_id: int) -> DeviceGroup:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM device_groups WHERE id = ? AND site_id = ?", (group_id, self.site_id)).fetchone()
        if row is None:
            raise KeyError(f"Device group not found: {group_id}")
        return DeviceGroup(**dict(row))

    def create(self, name: str, sort_order: int = 100) -> DeviceGroup:
        clean = normalize_group_name(name)
        now = datetime.now().isoformat(timespec="seconds")
        with self.database.connect() as conn:
            if self.exists_name(clean):
                raise DuplicateGroupName(clean)
            cursor = conn.execute(
                "INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.site_id, clean, sort_order, now, now),
            )
            conn.commit()
            return self.get(int(cursor.lastrowid))

    def rename(self, group_id: int, name: str) -> DeviceGroup:
        clean = normalize_group_name(name)
        now = datetime.now().isoformat(timespec="seconds")
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT id FROM device_groups WHERE site_id = ? AND LOWER(name) = LOWER(?) AND id <> ?",
                (self.site_id, clean, group_id),
            ).fetchone()
            if row is not None:
                raise DuplicateGroupName(clean)
            conn.execute(
                "UPDATE device_groups SET name = ?, updated_at = ? WHERE id = ? AND site_id = ?",
                (clean, now, group_id, self.site_id),
            )
            conn.commit()
        return self.get(group_id)

    def delete(self, group_id: int) -> None:
        with self.database.connect() as conn:
            conn.execute("UPDATE devices SET group_id = NULL WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM device_groups WHERE id = ? AND site_id = ?", (group_id, self.site_id))
            conn.commit()

    def count_devices(self, group_id: int) -> int:
        with self.database.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM devices WHERE group_id = ?", (group_id,)).fetchone()
        return int(row["count"] if row else 0)

    def counts(self) -> dict[int, int]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT group_id, COUNT(*) AS count FROM devices WHERE group_id IS NOT NULL GROUP BY group_id").fetchall()
        return {int(row["group_id"]): int(row["count"]) for row in rows if row["group_id"] is not None}

    def exists_name(self, name: str) -> bool:
        clean = normalize_group_name(name)
        with self.database.connect() as conn:
            row = conn.execute("SELECT 1 FROM device_groups WHERE site_id = ? AND LOWER(name) = LOWER(?) LIMIT 1", (self.site_id, clean)).fetchone()
        return row is not None

    def find_by_name(self, name: str) -> DeviceGroup | None:
        clean = normalize_group_name(name)
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM device_groups WHERE site_id = ? AND LOWER(name) = LOWER(?) LIMIT 1",
                (self.site_id, clean),
            ).fetchone()
        return DeviceGroup(**dict(row)) if row is not None else None

    def ensure_default_groups(self) -> list[DeviceGroup]:
        created: list[DeviceGroup] = []
        for name, sort_order in DEFAULT_DEVICE_GROUPS:
            if not self.exists_name(name):
                created.append(self.create(name, sort_order=sort_order))
        self._delete_empty_legacy_custom_group()
        return created

    def _delete_empty_legacy_custom_group(self) -> None:
        group = self.find_by_name(LEGACY_CUSTOM_GROUP_NAME)
        if group is None or group.id is None:
            return
        if self.count_devices(int(group.id)) == 0:
            self.delete(int(group.id))


def normalize_group_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("empty group name")
    if len(value) > 64:
        raise ValueError("group name is too long")
    return value
