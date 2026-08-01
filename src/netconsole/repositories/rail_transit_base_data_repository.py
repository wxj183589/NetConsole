from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import configure_sqlite_connection
from netconsole.core.sites import SiteManager
from netconsole.models.device_address import normalize_ip_address
from netconsole.repositories.ap_management_vlan_repository import (
    ApManagementVlanRepository,
)
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.rail_transit.trackside_ap_location import (
    default_participates_in_mainline,
    normalize_location_class,
    parse_participates_in_mainline,
    validate_location_participation,
)
from netconsole.utils.mileage import parse_track_mileage


AP_MERGE_FIELDS = (
    "line_name",
    "system_type",
    "network_domain",
    "belong_type",
    "station_id",
    "station_name",
    "section_id",
    "section_name",
    "section_start_station",
    "section_end_station",
    "line_side",
    "direction",
    "location_class",
    "participates_in_mainline",
    "location_class_source",
    "mileage_text",
    "mileage_m",
    "distance_to_prev_m",
    "ap_point_code",
    "ap_name",
    "ap_vendor",
    "ap_mac_norm",
    "ap_mac_display",
    "yard_name",
    "area_name",
    "curve_radius_m",
    "curve_start_text",
    "curve_end_text",
    "install_scene",
    "location_desc",
    "power_station",
    "power_distribution",
    "fiber_access_station",
    "fiber_distribution",
    "uplink_switch",
    "uplink_port",
    "optical_port",
    "remark",
    "source_file",
    "source_sheet",
    "source_row",
    "raw_payload_json",
)
_AP_IDENTITY_DERIVED_TABLES = {
    "ap_identity_entities",
    "ap_identity_mac_aliases",
    "ap_identity_h3c_prefixes",
    "ap_identity_conflicts",
    "ap_identity_index_state",
}

_BASE_DATA_REFERENCE_METADATA_KEYS = {
    "line_side_source",
    "line_side_derivation_issue_code",
    "line_side_derivation_issue_message",
    "station_id",
    "station_node_uid",
    "section_id",
    "section_name",
    "section_code",
    "section_generation_key",
    "section_start_node_uid",
    "section_end_node_uid",
}
_BASE_DATA_REVISION_KEY = "base_data_revision"


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
            try:
                revision = connection.execute(
                    """
                    SELECT value
                    FROM schema_metadata
                    WHERE key = ?
                    LIMIT 1
                    """,
                    (_BASE_DATA_REVISION_KEY,),
                ).fetchone()
            except sqlite3.Error:
                revision = None
            if revision is not None:
                payload = f"base-data-counter-v1\n{str(revision['value'] or '0')}"
                return hashlib.sha256(payload.encode("utf-8")).hexdigest()

            # Databases created before the counter schema remain readable.  The
            # fallback deliberately fingerprints only SQLite metadata and file
            # state; it never scans the historical rows that caused the timeout.
            schema_rows = connection.execute(
                """
                SELECT type, name, COALESCE(sql, '')
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                  AND name NOT IN (?, ?, ?, ?, ?)
                ORDER BY type, name
                """,
                tuple(sorted(_AP_IDENTITY_DERIVED_TABLES)),
            ).fetchall()
            pragmas = {
                key: connection.execute(f"PRAGMA {key}").fetchone()[0]
                for key in (
                    "journal_mode",
                    "page_count",
                    "freelist_count",
                    "schema_version",
                    "user_version",
                )
            }
        try:
            database_stat = path.stat()
        except OSError:
            database_stat = None
        wal_path = path.with_name(f"{path.name}-wal")
        try:
            wal_stat = wal_path.stat()
        except OSError:
            wal_stat = None
        try:
            with path.open("rb") as handle:
                header = handle.read(28).hex()
        except OSError:
            header = ""
        payload = {
            "schema": [tuple(row) for row in schema_rows],
            "pragmas": pragmas,
            "database": (
                database_stat.st_size,
                database_stat.st_mtime_ns,
            )
            if database_stat
            else None,
            "wal": (
                wal_stat.st_size,
                wal_stat.st_mtime_ns,
            )
            if wal_stat
            else None,
            "header": header,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

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

    def station_reference_summary(
        self,
        site_id: str,
        station_name: str,
        *,
        station_id: str = "",
    ) -> dict[str, int]:
        """Return a read-only, explainable station dependency summary."""
        name = str(station_name or "").strip()
        stable_id = str(station_id or "").strip()
        path = self._database_path(site_id)
        with self._read_connection(path) as connection:
            self._require_table(connection)
            return self._station_reference_summary(
                connection,
                name,
                station_id=stable_id,
            )

    def preview_clear_station_section_base_data(self, site_id: str) -> dict[str, int | str]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        with self._read_connection(self._database_path(site_id)) as connection:
            self._require_table(connection)
            counts = self._clear_impact_counts(connection)
        return {"site_id": site_id, "base_revision": self.base_data_revision(site_id), **counts}

    def clear_station_section_base_data(
        self, site_id: str, expected_revision: str
    ) -> dict[str, int | str]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        connection = sqlite3.connect(self._database_path(site_id), timeout=30.0)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        plan_deleted_count = 0
        try:
            self._require_table(connection)
            connection.execute("BEGIN IMMEDIATE")
            if self.base_data_revision(site_id) != expected_revision:
                raise RailTransitBaseDataRevisionConflict("base data revision changed")
            counts = self._clear_impact_counts(connection)
            now = self._now()
            rows = connection.execute(
                """
                SELECT id, raw_payload_json FROM ap_extension_points
                WHERE COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                  AND (
                    COALESCE(station_name, '') != '' OR COALESCE(section_name, '') != '' OR
                    COALESCE(section_start_station, '') != '' OR COALESCE(section_end_station, '') != '' OR
                    COALESCE(line_side, '') != '' OR COALESCE(direction, '') != ''
                  )
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE ap_extension_points
                    SET station_name = '', section_name = '', section_start_station = '',
                        section_end_station = '', line_side = '', direction = '',
                        raw_payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        self._reference_free_metadata(row["raw_payload_json"]),
                        now,
                        int(row["id"]),
                    ),
                )
            connection.execute("DELETE FROM ap_extension_points WHERE belong_type = '__base_section__'")
            connection.execute("DELETE FROM ap_extension_points WHERE belong_type = '__base_station__'")
            plan_cursor = connection.execute("DELETE FROM ac_trackside_ap_plan")
            plan_deleted_count = max(0, int(plan_cursor.rowcount))
            remaining = connection.execute(
                """
                SELECT COUNT(*) FROM ap_extension_points
                WHERE (
                  belong_type IN ('__base_station__', '__base_section__') OR
                  (COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__') AND (
                    COALESCE(station_name, '') != '' OR COALESCE(section_name, '') != '' OR
                    COALESCE(section_start_station, '') != '' OR COALESCE(section_end_station, '') != '' OR
                    COALESCE(line_side, '') != '' OR COALESCE(direction, '') != ''
                  ))
                )
                """
            ).fetchone()
            if remaining is None or int(remaining[0]) != 0:
                raise sqlite3.DatabaseError("base data clear verification failed")
            self._assert_integrity(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {
            "revision": self.base_data_revision(site_id),
            "deleted_station_count": int(counts["station_count"]),
            "deleted_section_count": int(counts["section_count"]),
            "unlinked_trackside_ap_count": int(counts["affected_trackside_ap_count"]),
            "deleted_trackside_ap_plan_count": plan_deleted_count,
        }

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

    def apply_operations_partially(
        self,
        site_id: str,
        operation_id: str,
        operations: Iterable[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Apply importable rows in one transaction while isolating row-level failures."""
        path = self._database_path(site_id)
        connection = sqlite3.connect(path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(connection, foreign_keys=True)
        changes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        try:
            self._require_table(connection)
            connection.execute("BEGIN IMMEDIATE")
            for index, operation in enumerate(operations):
                savepoint = f"trackside_import_row_{index}"
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    change = self._apply_operation(
                        connection,
                        site_id,
                        operation_id,
                        operation,
                    )
                    change["row_number"] = int(operation.get("row_number") or 0)
                    changes.append(change)
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                except (
                    sqlite3.IntegrityError,
                    ValueError,
                    RailTransitBaseDataConstraintError,
                ) as exc:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    failures.append(
                        {
                            "row_number": int(operation.get("row_number") or 0),
                            "kind": str(operation.get("kind") or ""),
                            "error_type": type(exc).__name__,
                        }
                    )
            self._assert_integrity(connection)
            connection.commit()
            return changes, failures
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
        counts = {
            "created_count": 0,
            "updated_count": 0,
            "deleted_count": 0,
            "device_binding_count": 0,
            "planning_row_count": 0,
            "station_id_repaired_count": 0,
        }
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
                    self._apply_station_change(
                        connection, site_id, action, change.get("entity_id"), values
                    )
                elif entity_type == "device_station_binding":
                    counts["device_binding_count"] += self._replace_device_station_bindings(
                        connection, values
                    )
                elif entity_type == "section":
                    self._apply_section_change(
                        connection, site_id, action, change.get("entity_id"), values
                    )
                elif entity_type == "trackside_ap":
                    self._apply_ap_change(connection, site_id, action, change.get("entity_id"), values)
                elif entity_type == "vehicle_mr":
                    self._apply_mr_change(connection, action, change.get("entity_id"), values)
                elif entity_type == "trackside_ap_plan":
                    plan_result = self._replace_trackside_ap_plan(
                        connection, site_id, values
                    )
                    counts["planning_row_count"] = plan_result["row_count"]
                    counts["station_id_repaired_count"] += plan_result[
                        "station_id_repaired_count"
                    ]
                else:
                    raise ValueError("unsupported base data entity")
                key = {"create": "created_count", "update": "updated_count", "delete": "deleted_count", "replace": "updated_count"}.get(action)
                if key:
                    counts[key] += 1
                if entity_type == "station" and action == "replace":
                    counts["deleted_count"] += len(
                        {
                            str(value).strip()
                            for value in values.get("merge_source_names") or []
                            if str(value).strip()
                        }
                    )
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
        entity_id: Any,
        values: Mapping[str, Any],
    ) -> None:
        station_id = str(values.get("station_id") or entity_id or "").strip()
        old_name = str(values.get("old_name") or values.get("name") or "").strip()
        name = str(values.get("name") or "").strip()
        if action == "delete":
            formal_station = connection.execute(
                """
                SELECT 1 FROM ap_extension_points
                WHERE belong_type = '__base_station__'
                  AND ((? != '' AND station_id = ?) OR (? = '' AND station_name = ?))
                LIMIT 1
                """,
                (station_id, station_id, station_id, old_name),
            ).fetchone()
            if formal_station is None:
                self._delete_station_and_unlink_references(connection, old_name)
                return
            if self._station_reference_count(
                connection,
                old_name,
                station_id=station_id,
            ):
                raise RailTransitBaseDataConstraintError("站点仍被区间、轨旁 AP、关系或规划引用")
            if station_id:
                connection.execute(
                    "DELETE FROM ac_trackside_ap_plan WHERE station_id = ?",
                    (station_id,),
                )
                connection.execute(
                    "DELETE FROM ap_extension_points "
                    "WHERE belong_type = '__base_station__' AND station_id = ?",
                    (station_id,),
                )
            else:
                connection.execute(
                    "DELETE FROM ac_trackside_ap_plan WHERE station_name = ?",
                    (old_name,),
                )
                connection.execute(
                    "DELETE FROM ap_extension_points "
                    "WHERE belong_type = '__base_station__' AND station_name = ?",
                    (old_name,),
                )
            return
        if action in {"update", "replace"} and old_name != name:
            self._migrate_station_name_references(
                connection,
                old_name,
                name,
                source_station_id=station_id,
                target_station_id=station_id,
            )
        if action == "replace":
            source_names = [
                str(value).strip()
                for value in values.get("merge_source_names") or []
                if str(value).strip() and str(value).strip() != old_name
            ]
            target_uid = str(values.get("node_uid") or "").strip()
            source_uids = [
                str(value).strip()
                for value in values.get("merge_source_node_uids") or []
                if str(value).strip() and str(value).strip() != target_uid
            ]
            source_ids = [
                str(value).strip()
                for value in values.get("merge_source_ids") or []
                if str(value).strip() and str(value).strip() != station_id
            ]
            source_rows: list[tuple[str, str]] = []
            if source_ids:
                placeholders = ", ".join("?" for _ in source_ids)
                source_rows = [
                    (str(row["station_id"] or ""), str(row["station_name"] or ""))
                    for row in connection.execute(
                        f"""
                        SELECT station_id, station_name FROM ap_extension_points
                        WHERE belong_type = '__base_station__'
                          AND station_id IN ({placeholders})
                        """,
                        list(dict.fromkeys(source_ids)),
                    ).fetchall()
                ]
            else:
                source_rows = [("", source_name) for source_name in dict.fromkeys(source_names)]
            for source_id, source_name in source_rows:
                self._migrate_station_name_references(
                    connection,
                    source_name,
                    name,
                    source_station_id=source_id,
                    target_station_id=station_id,
                )
            if source_uids:
                self._migrate_section_node_uids(
                    connection,
                    source_uids=source_uids,
                    target_uid=target_uid,
                )
            self._assert_no_section_self_loops(connection)
            if source_ids:
                placeholders = ", ".join("?" for _ in source_ids)
                connection.execute(
                    f"""
                    DELETE FROM ap_extension_points
                    WHERE belong_type = '__base_station__'
                      AND station_id IN ({placeholders})
                    """,
                    list(dict.fromkeys(source_ids)),
                )
            elif source_names:
                placeholders = ", ".join("?" for _ in source_names)
                connection.execute(
                    f"""
                    DELETE FROM ap_extension_points
                    WHERE belong_type = '__base_station__'
                      AND station_name IN ({placeholders})
                    """,
                    list(dict.fromkeys(source_names)),
                )
        self._replace_metadata_row(
            connection,
            site_id,
            "station",
            old_name,
            {**dict(values), "station_id": station_id},
        )

    def _migrate_station_name_references(
        self,
        connection: sqlite3.Connection,
        old_name: str,
        new_name: str,
        *,
        source_station_id: str = "",
        target_station_id: str = "",
    ) -> None:
        if not old_name:
            return
        if old_name == new_name and (
            not target_station_id or source_station_id == target_station_id
        ):
            return
        now = self._now()
        if source_station_id:
            connection.execute(
                """
                UPDATE ap_extension_points
                SET station_id = ?, station_name = ?, updated_at = ?
                WHERE belong_type != '__base_station__'
                  AND (station_id = ? OR (station_id = '' AND station_name = ?))
                """,
                (
                    target_station_id or source_station_id,
                    new_name,
                    now,
                    source_station_id,
                    old_name,
                ),
            )
            connection.execute(
                "UPDATE devices SET station_id = ?, station = ?, updated_at = ? "
                "WHERE station_id = ? OR (station_id = '' AND station = ?)",
                (
                    target_station_id or source_station_id,
                    new_name,
                    now,
                    source_station_id,
                    old_name,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE ap_extension_points
                SET station_id = ?, station_name = ?, updated_at = ?
                WHERE station_name = ? AND belong_type != '__base_station__'
                """,
                (target_station_id, new_name, now, old_name),
            )
            if target_station_id:
                connection.execute(
                    "UPDATE devices SET station_id = ?, station = ?, updated_at = ? "
                    "WHERE station_id = '' AND station = ?",
                    (target_station_id, new_name, now, old_name),
                )
        connection.execute(
            "UPDATE ap_extension_points SET section_start_station = ?, updated_at = ? WHERE section_start_station = ?",
            (new_name, now, old_name),
        )
        connection.execute(
            "UPDATE ap_extension_points SET section_end_station = ?, updated_at = ? WHERE section_end_station = ?",
            (new_name, now, old_name),
        )
        if source_station_id:
            effective_target_id = target_station_id or source_station_id
            target_plan_exists = (
                effective_target_id != source_station_id
                and connection.execute(
                    "SELECT 1 FROM ac_trackside_ap_plan "
                    "WHERE mode = 'unified' AND station_id = ? LIMIT 1",
                    (effective_target_id,),
                ).fetchone()
                is not None
            )
            if target_plan_exists:
                connection.execute(
                    "DELETE FROM ac_trackside_ap_plan "
                    "WHERE mode = 'unified' "
                    "AND (station_id = ? OR (station_id = '' AND station_name = ?))",
                    (source_station_id, old_name),
                )
            else:
                connection.execute(
                    "UPDATE ac_trackside_ap_plan "
                    "SET station_id = ?, station_name = ?, updated_at = ? "
                    "WHERE station_id = ? OR (station_id = '' AND station_name = ?)",
                    (
                        effective_target_id,
                        new_name,
                        now,
                        source_station_id,
                        old_name,
                    ),
                )
        else:
            target_plan_exists = bool(
                target_station_id
                and connection.execute(
                    "SELECT 1 FROM ac_trackside_ap_plan "
                    "WHERE mode = 'unified' AND station_id = ? LIMIT 1",
                    (target_station_id,),
                ).fetchone()
            )
            if target_plan_exists:
                connection.execute(
                    "DELETE FROM ac_trackside_ap_plan "
                    "WHERE mode = 'unified' AND station_id = '' AND station_name = ?",
                    (old_name,),
                )
            else:
                connection.execute(
                    "UPDATE ac_trackside_ap_plan "
                    "SET station_id = ?, station_name = ?, updated_at = ? "
                    "WHERE station_name = ?",
                    (target_station_id, new_name, now, old_name),
                )

    def _migrate_section_node_uids(
        self,
        connection: sqlite3.Connection,
        *,
        source_uids: Iterable[str],
        target_uid: str,
    ) -> None:
        if not target_uid:
            raise RailTransitBaseDataConstraintError("合并目标缺少稳定节点标识")
        source_uid_set = {str(value).strip() for value in source_uids if str(value).strip()}
        rows = connection.execute(
            """
            SELECT id, raw_payload_json FROM ap_extension_points
            WHERE belong_type = '__base_section__'
            """
        ).fetchall()
        now = self._now()
        for row in rows:
            try:
                metadata = json.loads(str(row["raw_payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            changed = False
            for key in ("start_node_uid", "end_node_uid"):
                if str(metadata.get(key) or "") in source_uid_set:
                    metadata[key] = target_uid
                    changed = True
            if changed:
                connection.execute(
                    """
                    UPDATE ap_extension_points
                    SET raw_payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps(metadata, ensure_ascii=False),
                        now,
                        int(row["id"]),
                    ),
                )

    @staticmethod
    def _assert_no_section_self_loops(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT section_name, section_start_station, section_end_station, raw_payload_json
            FROM ap_extension_points
            WHERE COALESCE(section_name, '') != ''
              AND COALESCE(section_start_station, '') != ''
              AND COALESCE(section_end_station, '') != ''
            """
        ).fetchall()
        for row in rows:
            start_name = str(row["section_start_station"] or "").strip()
            end_name = str(row["section_end_station"] or "").strip()
            try:
                metadata = json.loads(str(row["raw_payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            start_uid = str(metadata.get("start_node_uid") or "").strip()
            end_uid = str(metadata.get("end_node_uid") or "").strip()
            if (start_name and start_name == end_name) or (
                start_uid and start_uid == end_uid
            ):
                raise RailTransitBaseDataConstraintError(
                    f"合并后区间“{row['section_name']}”将形成自环"
                )

    def _apply_section_change(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        action: str,
        entity_id: Any,
        values: Mapping[str, Any],
    ) -> None:
        section_id = str(values.get("section_id") or entity_id or "").strip()
        old_name = str(values.get("old_name") or values.get("name") or "").strip()
        old_start = str(values.get("old_start_station") or values.get("start_station") or "").strip()
        old_end = str(values.get("old_end_station") or values.get("end_station") or "").strip()
        old_side = str(values.get("old_line_side") or values.get("line_side") or "").strip()
        if action == "delete":
            self._delete_section_and_unlink_references(
                connection, old_name, old_start, old_end, old_side, section_id
            )
            return
        if action == "update":
            new_name = str(values.get("name") or "").strip()
            now = self._now()
            if section_id:
                connection.execute(
                    """
                    UPDATE ap_extension_points
                    SET section_name = ?, section_start_station = ?,
                        section_end_station = ?, updated_at = ?
                    WHERE section_id = ?
                      AND COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                    """,
                    (
                        new_name,
                        str(values.get("start_station") or "").strip(),
                        str(values.get("end_station") or "").strip(),
                        now,
                        section_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE ap_extension_points
                    SET section_name = ?, section_start_station = ?, section_end_station = ?, updated_at = ?
                    WHERE section_name = ? AND section_start_station = ? AND section_end_station = ?
                      AND COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                    """,
                    (
                        new_name,
                        str(values.get("start_station") or "").strip(),
                        str(values.get("end_station") or "").strip(),
                        now,
                        old_name,
                        old_start,
                        old_end,
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
        self._replace_metadata_row(
            connection,
            site_id,
            "section",
            old_name,
            {**dict(values), "section_id": section_id},
        )

    def _delete_station_and_unlink_references(
        self, connection: sqlite3.Connection, station_name: str
    ) -> None:
        if not station_name:
            raise RailTransitBaseDataConstraintError("站点名称为空，无法删除")
        now = self._now()
        affected_sections = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT section_name FROM ap_extension_points
                WHERE (section_start_station = ? OR section_end_station = ?)
                  AND COALESCE(section_name, '') != ''
                """,
                (station_name, station_name),
            ).fetchall()
        }
        rows = connection.execute(
            """
            SELECT id, station_name, section_name, section_start_station,
                   section_end_station, line_side, direction, raw_payload_json
            FROM ap_extension_points
            WHERE COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
              AND (
                station_name = ? OR section_start_station = ? OR section_end_station = ?
                OR section_name IN (
                  SELECT section_name FROM ap_extension_points
                  WHERE (section_start_station = ? OR section_end_station = ?)
                    AND COALESCE(section_name, '') != ''
                )
              )
            """,
            (station_name, station_name, station_name, station_name, station_name),
        ).fetchall()
        for row in rows:
            clear_section = (
                str(row["section_start_station"] or "") == station_name
                or str(row["section_end_station"] or "") == station_name
                or str(row["section_name"] or "") in affected_sections
            )
            connection.execute(
                """
                UPDATE ap_extension_points
                SET station_name = ?, section_name = ?, section_start_station = ?,
                    section_end_station = ?, line_side = ?, direction = ?,
                    raw_payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    "" if str(row["station_name"] or "") == station_name else str(row["station_name"] or ""),
                    "" if clear_section else str(row["section_name"] or ""),
                    "" if clear_section else str(row["section_start_station"] or ""),
                    "" if clear_section else str(row["section_end_station"] or ""),
                    "" if clear_section else str(row["line_side"] or ""),
                    "" if clear_section else str(row["direction"] or ""),
                    self._reference_free_metadata(
                        row["raw_payload_json"], clear_section=clear_section
                    ),
                    now,
                    int(row["id"]),
                ),
            )
        connection.execute(
            """
            DELETE FROM ap_extension_points
            WHERE belong_type = '__base_section__'
              AND (section_start_station = ? OR section_end_station = ?)
            """,
            (station_name, station_name),
        )
        connection.execute(
            "DELETE FROM ap_extension_points WHERE belong_type = '__base_station__' AND station_name = ?",
            (station_name,),
        )
        connection.execute(
            "DELETE FROM ac_trackside_ap_plan WHERE station_name = ?",
            (station_name,),
        )

    def _delete_section_and_unlink_references(
        self,
        connection: sqlite3.Connection,
        section_name: str,
        start_station: str,
        end_station: str,
        line_side: str,
        section_id: str = "",
    ) -> None:
        if not section_name:
            raise RailTransitBaseDataConstraintError("区间名称为空，无法删除")
        now = self._now()
        rows = connection.execute(
            """
            SELECT id, raw_payload_json FROM ap_extension_points
            WHERE COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
              AND ((? != '' AND section_id = ?) OR (? = '' AND section_name = ?))
            """,
            (section_id, section_id, section_id, section_name),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                UPDATE ap_extension_points
                SET section_id = '', section_name = '', section_start_station = '', section_end_station = '',
                    line_side = '', direction = '', raw_payload_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    self._reference_free_metadata(row["raw_payload_json"]),
                    now,
                    int(row["id"]),
                ),
            )
        connection.execute(
            """
            DELETE FROM ap_extension_points
            WHERE belong_type = '__base_section__'
              AND ((? != '' AND section_id = ?) OR (? = '' AND section_name = ?
              AND section_start_station = ? AND section_end_station = ? AND line_side = ?))
            """,
            (
                section_id,
                section_id,
                section_id,
                section_name,
                start_station,
                end_station,
                line_side,
            ),
        )

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
                "source_order_text",
                "source_order",
                "canonical_station_name",
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
            "station_id": (
                str(values.get("station_id") or "").strip()
                if kind == "station"
                else ""
            ),
            "station_name": str(values.get("name") or "").strip() if kind == "station" else "",
            "section_id": (
                str(values.get("section_id") or "").strip()
                if kind == "section"
                else ""
            ),
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
        identity_field = "station_id" if kind == "station" else "section_id"
        identity_value = str(values.get(identity_field) or "").strip()
        if identity_value:
            existing = connection.execute(
                f"SELECT id FROM ap_extension_points WHERE belong_type = ? AND {identity_field} = ? ORDER BY id LIMIT 1",
                (marker, identity_value),
            ).fetchone()
            if existing is None and old_name:
                existing = connection.execute(
                    f"SELECT id FROM ap_extension_points WHERE belong_type = ? AND {name_field} = ? ORDER BY id LIMIT 1",
                    (marker, old_name),
                ).fetchone()
        else:
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
        station_id = str(values.get("station_id") or "").strip()
        section_id = str(values.get("section_id") or "").strip()
        if station_id:
            station = connection.execute(
                """
                SELECT station_name FROM ap_extension_points
                WHERE belong_type = '__base_station__' AND station_id = ?
                LIMIT 1
                """,
                (station_id,),
            ).fetchone()
            if station is None:
                raise RailTransitBaseDataConstraintError(
                    "轨旁 AP 引用的 station_id 不存在"
                )
            values["station_name"] = str(station["station_name"] or "")
        if section_id:
            section = connection.execute(
                """
                SELECT section_name, section_start_station, section_end_station
                FROM ap_extension_points
                WHERE belong_type = '__base_section__' AND section_id = ?
                LIMIT 1
                """,
                (section_id,),
            ).fetchone()
            if section is None:
                raise RailTransitBaseDataConstraintError(
                    "轨旁 AP 引用的 section_id 不存在"
                )
            values.update(
                section_name=str(section["section_name"] or ""),
                section_start_station=str(section["section_start_station"] or ""),
                section_end_station=str(section["section_end_station"] or ""),
            )
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

    def _replace_device_station_bindings(
        self,
        connection: sqlite3.Connection,
        values: Mapping[str, Any],
    ) -> int:
        bindings = values.get("bindings")
        if not isinstance(bindings, list):
            raise RailTransitBaseDataConstraintError("设备站点绑定格式无效")
        updated = 0
        seen: set[str] = set()
        for raw in bindings:
            if not isinstance(raw, Mapping):
                raise RailTransitBaseDataConstraintError("设备站点绑定格式无效")
            device_id = str(raw.get("device_id") or "").strip()
            station_id = str(raw.get("station_id") or "").strip()
            if not device_id or device_id in seen:
                raise RailTransitBaseDataConstraintError("设备站点绑定包含重复或空设备 ID")
            seen.add(device_id)
            station = connection.execute(
                """
                SELECT station_name FROM ap_extension_points
                WHERE belong_type = '__base_station__' AND station_id = ?
                LIMIT 1
                """,
                (station_id,),
            ).fetchone()
            if station is None:
                raise RailTransitBaseDataConstraintError(
                    "设备绑定引用的 station_id 不存在"
                )
            cursor = connection.execute(
                """
                UPDATE devices
                SET station_id = ?, station = ?, updated_at = ?
                WHERE device_uuid = ? OR CAST(id AS TEXT) = ?
                """,
                (
                    station_id,
                    str(station["station_name"] or ""),
                    self._now(),
                    device_id,
                    device_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RailTransitBaseDataConstraintError(
                    f"来源设备不存在: {device_id}"
                )
            updated += 1
        return updated

    def _apply_mr_change(
        self,
        connection: sqlite3.Connection,
        action: str,
        entity_id: Any,
        values: Mapping[str, Any],
    ) -> None:
        if action == "delete":
            cursor = connection.execute(
                "DELETE FROM devices WHERE device_uuid = ?",
                (str(entity_id or ""),),
            )
            if cursor.rowcount != 1:
                raise RailTransitBaseDataConstraintError("车载 MR 不存在")
            return
        try:
            primary_address = normalize_ip_address(
                values.get("primary_address"),
                field="车载 MR 管理地址",
                allow_empty=False,
            )
        except ValueError as exc:
            raise RailTransitBaseDataConstraintError(str(exc)) from exc
        assert primary_address is not None
        safe = {
            "name": str(values.get("name") or "").strip(),
            "station": str(values.get("station") or "").strip(),
            "mac_address": str(values.get("mac_address") or "").strip(),
            "primary_address": primary_address,
            "normalized_primary_address": primary_address,
            "protocol": str(values.get("protocol") or "SSH").upper(),
            "port": int(values.get("port") or 22),
            "remark": str(values.get("remark") or "").strip(),
            "updated_at": self._now(),
        }
        if safe["protocol"] == "SSH":
            safe.update(ssh_enabled=1, ssh_port=safe["port"])
        else:
            safe.update(telnet_enabled=1, telnet_port=safe["port"])
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
            try:
                connection.execute(
                    f"INSERT INTO devices ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [safe[column] for column in columns],
                )
            except sqlite3.IntegrityError as exc:
                if "normalized_primary_address" in str(exc):
                    raise RailTransitBaseDataConstraintError(
                        f"车载 MR 管理地址 {primary_address} 在当前局点内已被其他设备使用"
                    ) from exc
                raise
            return
        assignments = ", ".join(f'"{field}" = ?' for field in safe)
        try:
            cursor = connection.execute(
                f"UPDATE devices SET {assignments} WHERE device_uuid = ?",
                [*safe.values(), str(entity_id or "")],
            )
        except sqlite3.IntegrityError as exc:
            if "normalized_primary_address" in str(exc):
                raise RailTransitBaseDataConstraintError(
                    f"车载 MR 管理地址 {primary_address} 在当前局点内已被其他设备使用"
                ) from exc
            raise
        if cursor.rowcount != 1:
            raise RailTransitBaseDataConstraintError("车载 MR 不存在")

    def _replace_trackside_ap_plan(
        self,
        connection: sqlite3.Connection,
        site_id: str,
        values: Mapping[str, Any],
    ) -> dict[str, int]:
        rows = values.get("rows")
        if isinstance(rows, list):
            now = self._now()
            existing_created_at = {
                (
                    str(row["station_id"] or ""),
                    str(row["station_name"] or "").casefold(),
                ): str(row["created_at"] or now)
                for row in connection.execute(
                    """
                    SELECT station_id, station_name, created_at
                    FROM ac_trackside_ap_plan
                    WHERE mode = 'unified'
                    """
                )
            }
            connection.execute(
                "DELETE FROM ac_trackside_ap_plan WHERE mode = 'unified'"
            )
            fields = (
                "mode",
                "station_id",
                "sequence_no",
                "station_name",
                "ap_count",
                "ap_start_address",
                "subnet_mask",
                "mask_length",
                "ap_gateway",
                "management_vlan",
                "ap_management_vlans",
                "remark",
                "sort_order",
                "created_at",
                "updated_at",
            )
            repaired_count = 0
            for row in rows:
                if not isinstance(row, Mapping):
                    raise RailTransitBaseDataConstraintError(
                        "轨旁 AP 规划行格式无效"
                    )
                station_id = str(row.get("station_id") or "")
                station, repaired = self._resolve_plan_station(
                    connection,
                    site_id=site_id,
                    station_id=station_id,
                    station_name=str(row.get("station_name") or ""),
                )
                repaired_count += int(repaired)
                if station is None:
                    raise RailTransitBaseDataConstraintError(
                        "轨旁 AP 规划引用的 station_id 不存在："
                        f"{station_id or '<empty>'}（展示名：{str(row.get('station_name') or '<empty>')}）"
                    )
                station_name = str(station["station_name"] or "")
                sequence_no = int(row.get("sequence_no") or 0)
                raw_management_vlan = row.get("management_vlan")
                management_vlan = (
                    None
                    if raw_management_vlan in (None, "")
                    else int(raw_management_vlan)
                )
                created_at = existing_created_at.get(
                    (station_id, station_name.casefold()),
                    now,
                )
                connection.execute(
                    f"""
                    INSERT INTO ac_trackside_ap_plan ({", ".join(fields)})
                    VALUES ({", ".join("?" for _ in fields)})
                    """,
                    (
                        "unified",
                        station_id,
                        sequence_no,
                        station_name,
                        int(row.get("ap_count") or 0),
                        str(row.get("ap_start_address") or ""),
                        str(row.get("subnet_mask") or ""),
                        row.get("mask_length"),
                        str(row.get("ap_gateway") or ""),
                        management_vlan,
                        "" if management_vlan is None else str(management_vlan),
                        str(row.get("remark") or ""),
                        sequence_no - 1,
                        created_at,
                        now,
                    ),
                )
            return {
                "row_count": len(rows),
                "station_id_repaired_count": repaired_count,
            }
        planning = values.get("planning")
        if not isinstance(planning, Mapping):
            raise RailTransitBaseDataConstraintError(
                "轨旁 AP 管理 VLAN 规划缺少线路级设置"
            )
        expected_revision = int(planning.get("revision") or 0)
        ApManagementVlanRepository.replace_with_connection(
            connection,
            values,
            expected_revision=expected_revision,
        )
        return {"row_count": 0, "station_id_repaired_count": 0}

    def _resolve_plan_station(
        self,
        connection: sqlite3.Connection,
        *,
        site_id: str,
        station_id: str,
        station_name: str,
    ) -> tuple[sqlite3.Row | None, bool]:
        row = connection.execute(
            """
            SELECT station_name FROM ap_extension_points
            WHERE belong_type = '__base_station__' AND station_id = ?
            LIMIT 1
            """,
            (station_id,),
        ).fetchone()
        if row is not None:
            return row, False
        name = str(station_name or "").strip()
        if not station_id or not name:
            return None, False
        references = connection.execute(
            """
            SELECT COUNT(*) FROM ap_extension_points
            WHERE station_name = ? OR section_start_station = ? OR section_end_station = ?
            """,
            (name, name, name),
        ).fetchone()
        if references is None or int(references[0] or 0) <= 0:
            return None, False
        node_uid = str(
            uuid5(
                NAMESPACE_URL,
                f"netconsole:{site_id}:station:legacy:{name}",
            )
        )
        expected_id = f"station:{hashlib.sha1(node_uid.encode('utf-8')).hexdigest()[:12]}"
        if station_id != expected_id:
            return None, False
        now = self._now()
        metadata = {
            "node_uid": node_uid,
            "canonical_station_name": name,
            "node_type": "station",
            "path_code": "MAIN",
            "participates_in_direction": True,
            "enabled": True,
            "source_kind": "legacy_ap_derived",
        }
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, ap_point_code,
                source_file, raw_payload_json, created_at, updated_at
            ) VALUES (?, '__base_station__', ?, ?, '-', 'legacy-plan-repair', ?, ?, ?)
            """,
            (
                site_id,
                station_id,
                name,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return connection.execute(
            """
            SELECT station_name FROM ap_extension_points
            WHERE belong_type = '__base_station__' AND station_id = ?
            LIMIT 1
            """,
            (station_id,),
        ).fetchone(), True

    @classmethod
    def _manual_ap_values(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        values = cls._safe_values(raw)
        values["remark"] = str(raw.get("remark") or "").strip()
        if "belong_type" in raw:
            values["belong_type"] = str(raw.get("belong_type") or "").strip()
        return values

    @staticmethod
    def _station_reference_count(
        connection: sqlite3.Connection,
        name: str,
        *,
        station_id: str = "",
    ) -> int:
        return RailTransitBaseDataRepository._station_reference_summary(
            connection,
            name,
            station_id=station_id,
        )["total_count"]

    @staticmethod
    def _station_reference_summary(
        connection: sqlite3.Connection,
        name: str,
        *,
        station_id: str = "",
    ) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT belong_type, station_name, section_name, section_start_station,
                   section_end_station, line_side, raw_payload_json
            FROM ap_extension_points
            WHERE COALESCE(belong_type, '') != '__base_station__'
              AND (
                station_name = ?
                OR section_start_station = ?
                OR section_end_station = ?
              )
            """,
            (name, name, name),
        ).fetchall()
        section_start_refs = {
            (
                str(row["section_name"] or "").strip(),
                str(row["section_start_station"] or "").strip(),
                str(row["section_end_station"] or "").strip(),
                str(row["line_side"] or "").strip(),
            )
            for row in rows
            if str(row["section_name"] or "").strip()
            and str(row["section_start_station"] or "") == name
        }
        section_end_refs = {
            (
                str(row["section_name"] or "").strip(),
                str(row["section_start_station"] or "").strip(),
                str(row["section_end_station"] or "").strip(),
                str(row["line_side"] or "").strip(),
            )
            for row in rows
            if str(row["section_name"] or "").strip()
            and str(row["section_end_station"] or "") == name
        }
        section_start_count = len(section_start_refs)
        section_end_count = len(section_end_refs)
        if station_id:
            ap_row = connection.execute(
                """
                SELECT COUNT(*) FROM ap_extension_points
                WHERE belong_type NOT IN ('__base_station__', '__base_section__')
                  AND (
                    station_id = ?
                    OR (station_id = '' AND station_name = ?)
                  )
                """,
                (station_id, name),
            ).fetchone()
            ap_count = int(ap_row[0] if ap_row else 0)
            device_row = connection.execute(
                "SELECT COUNT(*) FROM devices WHERE station_id = ?",
                (station_id,),
            ).fetchone()
            device_count = int(device_row[0] if device_row else 0)
            plan_row = connection.execute(
                "SELECT COUNT(*) FROM ac_trackside_ap_plan "
                "WHERE mode = 'unified' AND station_id = ?",
                (station_id,),
            ).fetchone()
        else:
            ap_count = sum(
                row["belong_type"] not in {"__base_station__", "__base_section__"}
                and str(row["station_name"] or "") == name
                for row in rows
            )
            device_count = 0
            plan_row = connection.execute(
                "SELECT COUNT(*) FROM ac_trackside_ap_plan "
                "WHERE mode = 'unified' AND station_name = ? AND station_id = ''",
                (name,),
            ).fetchone()
        endpoint_extension_refs: set[tuple[str, str, str, str]] = set()
        for row in rows:
            if row["belong_type"] != "__base_section__":
                continue
            try:
                metadata = json.loads(str(row["raw_payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            if (
                str(metadata.get("section_kind") or "") == "terminal_extension"
                and name
                in {
                    str(row["section_start_station"] or ""),
                    str(row["section_end_station"] or ""),
                }
            ):
                endpoint_extension_refs.add(
                    (
                        str(row["section_name"] or "").strip(),
                        str(row["section_start_station"] or "").strip(),
                        str(row["section_end_station"] or "").strip(),
                        str(row["line_side"] or "").strip(),
                    )
                )
        endpoint_extension_count = len(endpoint_extension_refs)
        plan_count = int(plan_row[0] if plan_row else 0)
        relation_count = 0
        total_count = (
            section_start_count
            + section_end_count
            + ap_count
            + device_count
            + plan_count
            + relation_count
        )
        return {
            "section_start_count": section_start_count,
            "section_end_count": section_end_count,
            "ap_count": ap_count,
            "device_count": device_count,
            "relation_count": relation_count,
            "endpoint_extension_count": endpoint_extension_count,
            "plan_count": plan_count,
            "total_count": total_count,
        }

    @staticmethod
    def _clear_impact_counts(connection: sqlite3.Connection) -> dict[str, int]:
        row = connection.execute(
            """
            SELECT
              SUM(CASE WHEN belong_type = '__base_station__' THEN 1 ELSE 0 END),
              SUM(CASE WHEN belong_type = '__base_section__' THEN 1 ELSE 0 END),
              SUM(CASE WHEN COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                AND (
                  COALESCE(station_name, '') != '' OR COALESCE(section_name, '') != '' OR
                  COALESCE(section_start_station, '') != '' OR COALESCE(section_end_station, '') != '' OR
                  COALESCE(line_side, '') != '' OR COALESCE(direction, '') != ''
                ) THEN 1 ELSE 0 END)
            FROM ap_extension_points
            """
        ).fetchone()
        return {
            "station_count": int(row[0] or 0),
            "section_count": int(row[1] or 0),
            "affected_trackside_ap_count": int(row[2] or 0),
        }

    @staticmethod
    def _reference_free_metadata(raw: Any, *, clear_section: bool = True) -> str:
        if raw in (None, ""):
            return "{}"
        try:
            metadata = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise sqlite3.DatabaseError("轨旁 AP 派生元数据格式无效，无法安全清空") from exc
        if not isinstance(metadata, dict):
            raise sqlite3.DatabaseError("轨旁 AP 派生元数据格式无效，无法安全清空")
        keys = _BASE_DATA_REFERENCE_METADATA_KEYS
        if not clear_section:
            keys = {"station_id", "station_node_uid"}
        for key in keys:
            metadata.pop(key, None)
        return json.dumps(metadata, ensure_ascii=False, sort_keys=True)

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
        if entity_type == "device_station_binding":
            return 15
        if entity_type == "section" and action != "delete":
            return 20
        if entity_type == "trackside_ap":
            return 30
        if entity_type == "trackside_ap_plan":
            return 40
        if entity_type == "vehicle_mr":
            return 50
        if entity_type == "section" and action == "delete":
            return 60
        if entity_type == "station" and action == "delete":
            return 70
        return 5

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
        if (
            "location_class" in values
            or "participates_in_mainline" in values
            or "location_class_source" in values
        ):
            if "location_class" not in values:
                raise RailTransitBaseDataConstraintError(
                    "设置正线参与状态时必须同时提供位置类型"
                )
            try:
                location_class = normalize_location_class(
                    values.get("location_class")
                )
                participates = parse_participates_in_mainline(
                    values.get("participates_in_mainline"),
                    default=default_participates_in_mainline(location_class),
                )
                validate_location_participation(location_class, participates)
            except ValueError as exc:
                raise RailTransitBaseDataConstraintError(str(exc)) from exc
            source = str(
                values.get("location_class_source") or "EXPLICIT"
            ).strip().upper()
            if source not in {
                "DEFAULT_MAINLINE",
                "IMPORT_EXPLICIT",
                "MANUAL_EXPLICIT",
                "LEGACY_INFERRED",
                "EXPLICIT",
            }:
                source = "EXPLICIT"
            values["location_class"] = location_class
            values["participates_in_mainline"] = int(participates)
            values["location_class_source"] = source
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
