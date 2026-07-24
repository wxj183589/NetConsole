from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import configure_sqlite_connection
from netconsole.core.sites import SiteManager
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
    "remark",
    "source_file",
    "source_sheet",
    "source_row",
    "raw_payload_json",
)


class RailTransitBaseDataRollbackConflict(RuntimeError):
    pass


class RailTransitBaseDataRevisionConflict(RuntimeError):
    pass


class RailTransitBaseDataConstraintError(RuntimeError):
    pass


class RailTransitBaseDataCompensationError(RuntimeError):
    pass


class RailTransitBaseDataRepository:
    """轨道交通基础资料受控写入边界；调用方负责开关、预览和审计。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def database_hash(self, site_id: str) -> str:
        """Return the public base-data revision (SQLite plus site metadata)."""
        return self.base_data_revision(site_id)

    def _sqlite_database_hash(self, site_id: str) -> str:
        path = self._database_path(site_id)
        with self._read_connection(path) as connection:
            return hashlib.sha256(connection.serialize()).hexdigest()

    def base_data_revision(self, site_id: str) -> str:
        """Return a revision covering both the SQLite facts and site metadata."""
        database_revision = self._sqlite_database_hash(site_id)
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{database_revision}\n{payload}".encode("utf-8")).hexdigest()

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

    def assert_integrity(self, site_id: str) -> None:
        with self._read_connection(self._database_path(site_id)) as connection:
            self._assert_integrity(connection)

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

    def apply_base_data_changes(
        self,
        site_id: str,
        expected_revision: str,
        changes: Iterable[Mapping[str, Any]],
    ) -> dict[str, int | str]:
        path = self._database_path(site_id)
        changes = list(changes)
        site_manager = SiteManager(self.paths)
        metadata_path = self._metadata_path(site_id)
        metadata_backup = metadata_path.read_bytes() if metadata_path.is_file() else None
        metadata_changes = [
            dict(change.get("values") or {})
            for change in changes
            if str(change.get("entity_type") or "") == "site_metadata"
        ]
        current_metadata = site_manager.load_site_metadata(site_id)
        metadata_applied = False
        connection = sqlite3.connect(path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        counts = {"created_count": 0, "updated_count": 0, "deleted_count": 0}
        try:
            self._require_table(connection)
            connection.execute("BEGIN IMMEDIATE")
            if self.base_data_revision(site_id) != expected_revision:
                raise RailTransitBaseDataRevisionConflict("base data revision changed")
            for change in sorted(changes, key=self._change_apply_order):
                entity_type = str(change.get("entity_type") or "")
                action = str(change.get("action") or "")
                values = dict(change.get("values") or {})
                if entity_type == "site_metadata":
                    if action != "update":
                        raise ValueError("unsupported site metadata action")
                elif entity_type == "station":
                    self._apply_station_change(connection, site_id, action, values)
                elif entity_type == "section":
                    self._apply_section_change(connection, site_id, action, values)
                elif entity_type == "trackside_ap":
                    self._apply_ap_change(connection, site_id, action, change.get("entity_id"), values)
                elif entity_type == "vehicle_mr":
                    self._apply_mr_change(connection, action, change.get("entity_id"), values)
                elif entity_type == "trackside_ap_plan":
                    self._replace_trackside_ap_plan(connection, values.get("rows") or [])
                else:
                    raise ValueError("unsupported base data entity")
                key = {"create": "created_count", "update": "updated_count", "delete": "deleted_count", "replace": "updated_count"}.get(action)
                if key:
                    counts[key] += 1
            self._assert_integrity(connection)
            if metadata_changes:
                metadata = dict(current_metadata)
                metadata.update(metadata_changes[-1])
                metadata_applied = True
                site_manager.save_site_metadata(site_id, metadata)
            connection.commit()
        except Exception as original_error:
            connection.rollback()
            if metadata_applied:
                try:
                    self._restore_metadata_file(metadata_path, metadata_backup)
                except Exception as compensation_error:
                    error = RailTransitBaseDataCompensationError("site metadata compensation failed")
                    error.add_note(f"original_error={type(original_error).__name__}")
                    raise error from compensation_error
            raise
        finally:
            connection.close()
        return {**counts, "revision": self.base_data_revision(site_id)}

    def rollback_changes(self, site_id: str, changes: Iterable[Mapping[str, Any]]) -> None:
        path = self._database_path(site_id)
        connection = sqlite3.connect(path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        try:
            self._require_table(connection)
            connection.execute("BEGIN IMMEDIATE")
            for change in reversed(list(changes)):
                entity_id = self._numeric_id(change.get("entity_id"))
                current = connection.execute(
                    "SELECT * FROM ap_extension_points WHERE id = ?",
                    (entity_id,),
                ).fetchone()
                if current is None:
                    raise RailTransitBaseDataRollbackConflict("rollback target missing")
                expected = self._safe_restore_values(change.get("new_values") or {})
                if any(current[field] != value for field, value in expected.items()):
                    raise RailTransitBaseDataRollbackConflict("rollback target changed")
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

    def _apply_station_change(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        action: str,
        values: Mapping[str, Any],
    ) -> None:
        old_name = str(values.get("old_name") or values.get("name") or "").strip()
        name = str(values.get("name") or "").strip()
        if action == "delete":
            if self._station_reference_count(connection, old_name):
                raise RailTransitBaseDataConstraintError("站点仍被轨旁 AP 或区间引用")
            connection.execute(
                "DELETE FROM ap_extension_points WHERE belong_type = '__base_station__' AND station_name = ?",
                (old_name,),
            )
            return
        if action == "update" and old_name != name:
            now = self._now()
            connection.execute(
                """
                UPDATE ap_extension_points SET station_name = ?, updated_at = ?
                WHERE station_name = ? AND belong_type != '__base_station__'
                """,
                (name, now, old_name),
            )
            connection.execute("UPDATE ap_extension_points SET section_start_station = ?, updated_at = ? WHERE section_start_station = ?", (name, now, old_name))
            connection.execute("UPDATE ap_extension_points SET section_end_station = ?, updated_at = ? WHERE section_end_station = ?", (name, now, old_name))
            connection.execute("UPDATE ac_trackside_ap_plan SET station_name = ?, updated_at = ? WHERE station_name = ?", (name, now, old_name))
        self._replace_metadata_row(connection, site_id, "station", old_name, values)

    def _apply_section_change(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        action: str,
        values: Mapping[str, Any],
    ) -> None:
        old_name = str(values.get("old_name") or values.get("name") or "").strip()
        old_start = str(values.get("old_start_station") or values.get("start_station") or "").strip()
        old_end = str(values.get("old_end_station") or values.get("end_station") or "").strip()
        old_side = str(values.get("old_line_side") or values.get("line_side") or "").strip()
        if action == "delete":
            if self._section_reference_count(connection, old_name, old_start, old_end, old_side):
                raise RailTransitBaseDataConstraintError("区间仍被轨旁 AP 引用")
            connection.execute(
                """
                DELETE FROM ap_extension_points
                WHERE belong_type = '__base_section__' AND section_name = ?
                  AND section_start_station = ? AND section_end_station = ? AND line_side = ?
                """,
                (old_name, old_start, old_end, old_side),
            )
            return
        if action == "update":
            new_name = str(values.get("name") or "").strip()
            now = self._now()
            connection.execute(
                """
                UPDATE ap_extension_points
                SET section_name = ?, section_start_station = ?, section_end_station = ?, line_side = ?, updated_at = ?
                WHERE section_name = ? AND section_start_station = ? AND section_end_station = ? AND line_side = ?
                  AND COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                """,
                (
                    new_name,
                    str(values.get("start_station") or "").strip(),
                    str(values.get("end_station") or "").strip(),
                    str(values.get("line_side") or "").strip(),
                    now,
                    old_name,
                    old_start,
                    old_end,
                    old_side,
                ),
            )
            if new_name != old_name:
                connection.execute(
                    """
                    UPDATE ap_extension_points
                    SET section_name = ?, updated_at = ?
                    WHERE section_name = ?
                      AND COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                    """,
                    (new_name, now, old_name),
                )
        self._replace_metadata_row(connection, site_id, "section", old_name, values)

    def _replace_metadata_row(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        kind: str,
        old_name: str,
        values: Mapping[str, Any],
    ) -> None:
        marker = f"__base_{kind}__"
        name_field = "station_name" if kind == "station" else "section_name"
        now = self._now()
        metadata = {
            key: values.get(key)
            for key in (
                "node_uid",
                "code",
                "sort_order",
                "remark",
                "source_station_value",
                "source_station_key",
                "node_type",
                "path_code",
                "participates_in_direction",
                "structure_type",
                "platform_layout",
                "center_mileage_text",
                "center_mileage_m",
                "is_line_terminal",
                "is_service_terminal",
                "turnback_capable",
                "turnback_type",
                "track_facilities",
                "turnback_direction",
                "terminal_extension_enabled",
                "terminal_endpoint_label",
                "terminal_extension_distance_m",
                "terminal_endpoint_mileage_text",
                "enabled",
                "source_kind",
                "section_code",
                "section_kind",
                "direction_role",
                "line_direction",
                "start_node_type",
                "start_node_uid",
                "end_node_type",
                "end_node_uid",
                "auto_generated",
                "generation_key",
                "manual_override_fields",
                "section_mileage_start_m",
                "section_mileage_end_m",
                "section_mileage_open_end",
                "section_mileage_source",
            )
            if key in values
        }
        payload = {
            "site_id": site_id,
            "belong_type": marker,
            "station_name": str(values.get("name") or "").strip() if kind == "station" else "",
            "section_name": str(values.get("name") or "").strip() if kind == "section" else "",
            "section_start_station": str(values.get("start_station") or "").strip(),
            "section_end_station": str(values.get("end_station") or "").strip(),
            "line_side": str(values.get("line_side") or "").strip(),
            "line_name": str(values.get("line_name") or "").strip(),
            "ap_point_code": "-",
            "remark": str(values.get("remark") or "").strip(),
            "source_file": "manual-base-data",
            "raw_payload_json": json.dumps(metadata, ensure_ascii=False),
            "created_at": now,
            "updated_at": now,
        }
        existing = connection.execute(
            f"SELECT id FROM ap_extension_points WHERE belong_type = ? AND {name_field} = ? ORDER BY id LIMIT 1",
            (marker, old_name),
        ).fetchone()
        if existing is None:
            columns = list(payload)
            connection.execute(
                f"INSERT INTO ap_extension_points ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [payload[column] for column in columns],
            )
            return
        update_payload = dict(payload)
        update_payload.pop("created_at", None)
        assignments = ", ".join(f'"{field}" = ?' for field in update_payload)
        connection.execute(
            f"UPDATE ap_extension_points SET {assignments} WHERE id = ?",
            [*update_payload.values(), int(existing[0])],
        )

    def _apply_ap_change(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        action: str,
        entity_id: Any,
        raw_values: Mapping[str, Any],
    ) -> None:
        if action == "delete":
            cursor = connection.execute("DELETE FROM ap_extension_points WHERE id = ?", (self._numeric_id(entity_id),))
            if cursor.rowcount != 1:
                raise RailTransitBaseDataConstraintError("轨旁 AP 不存在")
            return
        values = self._manual_ap_values(raw_values)
        values.update(site_id=site_id, updated_at=self._now())
        if action == "create":
            values.setdefault("belong_type", "station" if values.get("station_name") else "section")
            values["created_at"] = values["updated_at"]
            columns = list(values)
            connection.execute(
                f"INSERT INTO ap_extension_points ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [values[column] for column in columns],
            )
            return
        entity_id = self._numeric_id(entity_id)
        assignments = ", ".join(f'"{field}" = ?' for field in values)
        cursor = connection.execute(
            f"UPDATE ap_extension_points SET {assignments} WHERE id = ?",
            [*values.values(), entity_id],
        )
        if cursor.rowcount != 1:
            raise RailTransitBaseDataConstraintError("轨旁 AP 不存在")

    def _apply_mr_change(
        self,
        connection: sqlite3.Connection,
        action: str,
        entity_id: Any,
        values: Mapping[str, Any],
    ) -> None:
        safe = {
            "name": str(values.get("name") or "").strip(),
            "station": str(values.get("station") or "").strip(),
            "mac_address": str(values.get("mac_address") or "").strip(),
            "primary_address": str(values.get("primary_address") or "").strip(),
            "protocol": str(values.get("protocol") or "SSH").upper(),
            "port": int(values.get("port") or 22),
            "remark": str(values.get("remark") or "").strip(),
            "updated_at": self._now(),
        }
        if safe["protocol"] == "SSH":
            safe.update(ssh_enabled=1, ssh_port=safe["port"])
        else:
            safe.update(telnet_enabled=1, telnet_port=safe["port"])
        if action == "delete":
            cursor = connection.execute("DELETE FROM devices WHERE device_uuid = ?", (str(entity_id or ""),))
            if cursor.rowcount != 1:
                raise RailTransitBaseDataConstraintError("车载 MR 不存在")
            return
        if action == "create":
            group = connection.execute(
                "SELECT id FROM device_groups WHERE name LIKE '%车载-MR%' ORDER BY id LIMIT 1"
            ).fetchone()
            if group is None:
                raise RailTransitBaseDataConstraintError("当前局点缺少车载-MR设备分组")
            safe.update(
                device_uuid=str(uuid4()),
                group_id=int(group[0]),
                device_vendor="H3C",
                device_type="MR",
                created_at=safe["updated_at"],
            )
            columns = list(safe)
            connection.execute(
                f"INSERT INTO devices ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [safe[column] for column in columns],
            )
            return
        assignments = ", ".join(f'"{field}" = ?' for field in safe)
        cursor = connection.execute(
            f"UPDATE devices SET {assignments} WHERE device_uuid = ?",
            [*safe.values(), str(entity_id or "")],
        )
        if cursor.rowcount != 1:
            raise RailTransitBaseDataConstraintError("车载 MR 不存在")

    def _replace_trackside_ap_plan(self, connection: sqlite3.Connection, rows: Iterable[Mapping[str, Any]]) -> None:
        now = self._now()
        connection.execute("DELETE FROM ac_trackside_ap_plan WHERE mode = 'unified'")
        fields = (
            "mode", "station_name", "ap_count", "ap_start_address", "mask_length",
            "ap_gateway", "ap_management_vlans", "remark", "sort_order", "created_at", "updated_at",
        )
        for index, row in enumerate(rows):
            payload = {
                "mode": "unified",
                "station_name": str(row.get("station_name") or "").strip(),
                "ap_count": int(row.get("ap_count") or 0),
                "ap_start_address": str(row.get("ap_start_address") or "").strip(),
                "mask_length": row.get("mask_length"),
                "ap_gateway": str(row.get("ap_gateway") or "").strip(),
                "ap_management_vlans": str(row.get("ap_management_vlans") or "").strip(),
                "remark": str(row.get("remark") or "").strip(),
                "sort_order": index,
                "created_at": now,
                "updated_at": now,
            }
            connection.execute(
                f"INSERT INTO ac_trackside_ap_plan ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                [payload[field] for field in fields],
            )

    @classmethod
    def _manual_ap_values(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        values = cls._safe_values(raw)
        values["remark"] = str(raw.get("remark") or "").strip()
        if "belong_type" in raw:
            values["belong_type"] = str(raw.get("belong_type") or "").strip()
        return values

    @staticmethod
    def _station_reference_count(connection: sqlite3.Connection, name: str) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM ap_extension_points
            WHERE COALESCE(belong_type, '') != '__base_station__'
              AND (station_name = ? OR section_start_station = ? OR section_end_station = ?)
            """,
            (name, name, name),
        ).fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _section_reference_count(
        connection: sqlite3.Connection,
        name: str,
        start: str,
        end: str,
        line_side: str,
    ) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*) FROM ap_extension_points
            WHERE COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
              AND section_name = ?
            """,
            (name,),
        ).fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _change_apply_order(change: Mapping[str, Any]) -> int:
        entity_type = str(change.get("entity_type") or "")
        action = str(change.get("action") or "")
        if entity_type == "station" and action != "delete":
            return 10
        if entity_type == "section" and action != "delete":
            return 20
        if entity_type == "trackside_ap":
            return 30
        if entity_type == "section" and action == "delete":
            return 40
        if entity_type == "station" and action == "delete":
            return 50
        return 25

    @staticmethod
    def _connection_hash(connection: sqlite3.Connection) -> str:
        return hashlib.sha256(connection.serialize()).hexdigest()

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

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

    def _metadata_path(self, site_id: str) -> Path:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        site_root = self.paths.site_dir(site_id).resolve()
        data_root = self.paths.data_root.resolve()
        if data_root not in site_root.parents:
            raise ValueError("基础资料局点目录越界")
        return site_root / "site_meta.json"

    @staticmethod
    def _restore_metadata_file(path: Path, content: bytes | None) -> None:
        if content is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.rollback")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

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


__all__ = [
    "AP_MERGE_FIELDS",
    "RailTransitBaseDataRepository",
    "RailTransitBaseDataConstraintError",
    "RailTransitBaseDataCompensationError",
    "RailTransitBaseDataRevisionConflict",
    "RailTransitBaseDataRollbackConflict",
]
