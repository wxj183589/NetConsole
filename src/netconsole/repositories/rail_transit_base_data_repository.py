from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import configure_sqlite_connection
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.utils.mileage import parse_track_mileage


AP_MERGE_FIELDS = (
    "line_name",
    "system_type",
    "network_domain",
    "belong_type",
    "station_name",
    "section_name",
    "section_start_station",
    "section_end_station",
    "line_side",
    "direction",
    "mileage_text",
    "mileage_m",
    "ap_point_code",
    "ap_name",
    "ap_mac_norm",
    "ap_mac_display",
    "uplink_switch",
    "uplink_port",
    "source_file",
    "source_sheet",
    "source_row",
)


class RailTransitBaseDataRepository:
    """轨道交通基础资料受控写入边界；调用方负责开关、预览和审计。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def database_hash(self, site_id: str) -> str:
        path = self._database_path(site_id)
        with self._read_connection(path) as connection:
            return hashlib.sha256(connection.serialize()).hexdigest()

    def list_ap_records(self, site_id: str) -> list[dict[str, Any]]:
        path = self._database_path(site_id)
        fields = ("id", *AP_MERGE_FIELDS, "created_at", "updated_at", "import_batch_id")
        with self._read_connection(path) as connection:
            self._require_table(connection)
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(ap_extension_points)")}
            selected = [field for field in fields if field in columns]
            sql = ", ".join(f'"{field}"' for field in selected)
            return [dict(row) for row in connection.execute(f"SELECT {sql} FROM ap_extension_points")]

    def backup_database(self, site_id: str, target: Path) -> None:
        source_path = self._database_path(site_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(target.name)
        with self._read_connection(source_path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
            row = destination.execute("PRAGMA integrity_check").fetchone()
            if row is None or str(row[0]).casefold() != "ok":
                raise sqlite3.DatabaseError("backup integrity check failed")

    def apply_operations(self, site_id: str, operation_id: str, operations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        path = self._database_path(site_id)
        connection = sqlite3.connect(path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        changes: list[dict[str, Any]] = []
        try:
            self._require_table(connection)
            connection.execute("BEGIN IMMEDIATE")
            for operation in operations:
                changes.append(self._apply_operation(connection, site_id, operation_id, operation))
            self._assert_integrity(connection)
            connection.commit()
            return changes
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def rollback_changes(self, site_id: str, changes: Iterable[Mapping[str, Any]]) -> None:
        path = self._database_path(site_id)
        connection = sqlite3.connect(path, timeout=30.0)
        configure_sqlite_connection(connection, foreign_keys=True)
        try:
            self._require_table(connection)
            connection.execute("BEGIN IMMEDIATE")
            for change in reversed(list(changes)):
                entity_id = self._numeric_id(change.get("entity_id"))
                if change.get("kind") == "create":
                    connection.execute("DELETE FROM ap_extension_points WHERE id = ?", (entity_id,))
                    continue
                old_values = self._safe_restore_values(change.get("old_values") or {})
                if not old_values:
                    continue
                assignments = ", ".join(f'"{field}" = ?' for field in old_values)
                cursor = connection.execute(
                    f"UPDATE ap_extension_points SET {assignments} WHERE id = ?",
                    [*old_values.values(), entity_id],
                )
                if cursor.rowcount != 1:
                    raise sqlite3.DatabaseError("rollback target missing")
            self._assert_integrity(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _apply_operation(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        operation_id: str,
        operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(operation.get("kind") or "")
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        values = self._safe_values(operation.get("values") or {})
        values["site_id"] = site_id
        values["import_batch_id"] = operation_id
        values["updated_at"] = now
        if kind == "create":
            values["created_at"] = now
            columns = list(values)
            placeholders = ", ".join("?" for _ in columns)
            cursor = connection.execute(
                f"INSERT INTO ap_extension_points ({', '.join(columns)}) VALUES ({placeholders})",
                [values[field] for field in columns],
            )
            return {"kind": "create", "entity_id": f"ap:{cursor.lastrowid}", "old_values": {}, "new_values": values}
        if kind != "update":
            raise ValueError("unsupported merge operation")
        entity_id = self._numeric_id(operation.get("entity_id"))
        old_row = connection.execute("SELECT * FROM ap_extension_points WHERE id = ?", (entity_id,)).fetchone()
        if old_row is None:
            raise sqlite3.DatabaseError("merge target missing")
        old_values = {field: old_row[field] for field in values if field in old_row.keys()}
        assignments = ", ".join(f'"{field}" = ?' for field in values)
        connection.execute(
            f"UPDATE ap_extension_points SET {assignments} WHERE id = ?",
            [*values.values(), entity_id],
        )
        return {"kind": "update", "entity_id": f"ap:{entity_id}", "old_values": old_values, "new_values": values}

    @staticmethod
    def _safe_values(raw: Mapping[str, Any]) -> dict[str, Any]:
        values = {field: raw.get(field) for field in AP_MERGE_FIELDS if field in raw}
        mac = normalize_ap_mac(values.get("ap_mac_norm") or values.get("ap_mac_display"))
        if mac.raw:
            values["ap_mac_norm"] = mac.normalized
            values["ap_mac_display"] = mac.display or mac.raw
        mileage = parse_track_mileage(values.get("mileage_text") or values.get("mileage_m"))
        if mileage.meters is not None:
            values["mileage_m"] = mileage.meters
        if "source_file" in values:
            values["source_file"] = Path(str(values["source_file"] or "")).name
        return values

    def _database_path(self, site_id: str) -> Path:
        path = self.paths.site_db_path(site_id).resolve()
        sites_root = self.paths.sites_dir.resolve()
        expected_parent = (self.paths.site_dir(site_id) / "db").resolve()
        if path.parent != expected_parent or sites_root not in path.parents or not path.is_file():
            raise FileNotFoundError("基础资料数据库不存在")
        return path

    @staticmethod
    def _safe_restore_values(raw: Mapping[str, Any]) -> dict[str, Any]:
        allowed = (*AP_MERGE_FIELDS, "site_id", "import_batch_id", "created_at", "updated_at")
        values = {field: raw.get(field) for field in allowed if field in raw}
        if "source_file" in values:
            values["source_file"] = Path(str(values["source_file"] or "")).name
        return values

    @staticmethod
    def _read_connection(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _require_table(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ap_extension_points'"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("ap_extension_points table missing")

    @staticmethod
    def _assert_integrity(connection: sqlite3.Connection) -> None:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or str(row[0]).casefold() != "ok":
            raise sqlite3.DatabaseError("database integrity check failed")

    @staticmethod
    def _numeric_id(value: Any) -> int:
        text = str(value or "").removeprefix("ap:")
        if not text.isdigit():
            raise ValueError("invalid AP entity id")
        return int(text)


__all__ = ["AP_MERGE_FIELDS", "RailTransitBaseDataRepository"]
