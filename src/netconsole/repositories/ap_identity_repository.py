from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sqlite3
from time import monotonic

from netconsole.core.database import Database
from netconsole.models.ap_identity_index import (
    ApIdentityBuildResult,
    ApIdentityIndexBuild,
)


IndexBuilder = Callable[
    [Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]],
    ApIdentityIndexBuild,
]


class ApIdentityRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def rebuild_index(
        self,
        builder: Callable[..., ApIdentityIndexBuild],
        *,
        site_id: str = "current",
        reason: str,
    ) -> ApIdentityBuildResult:
        started = monotonic()
        built_at = _now()
        with self.database.connect_readonly() as connection:
            connection.execute("BEGIN")
            source_revision = self._source_revision(connection, site_id=site_id)
            base_rows = self._load_base_rows(connection)
            ac_rows = self._load_ac_rows(connection)
            connection.commit()
        build = builder(base_rows, ac_rows, site_id=site_id)
        diagnostics = _build_diagnostics(build)
        build_duration_ms = round((monotonic() - started) * 1000, 3)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current_source_revision = self._source_revision(
                    connection,
                    site_id=site_id,
                )
                if current_source_revision != source_revision:
                    raise RuntimeError(
                        "AP Identity sources changed while the index was being built"
                    )
                state_row = connection.execute(
                    """
                    SELECT revision
                    FROM ap_identity_index_state
                    WHERE site_id = ?
                    """,
                    (site_id,),
                ).fetchone()
                current_revision = int(state_row["revision"] or 0) if state_row else 0
                revision = current_revision + 1
                self._replace_index(
                    connection,
                    build,
                    site_id=site_id,
                    reason=reason,
                    revision=revision,
                    built_at=built_at,
                    source_revision=source_revision,
                    diagnostics=diagnostics,
                    build_duration_ms=build_duration_ms,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return ApIdentityBuildResult(
            site_id=site_id,
            revision=revision,
            reason=reason,
            built_at=built_at,
            base_record_count=build.base_record_count,
            ac_record_count=build.ac_record_count,
            entity_count=len(build.entities),
            alias_count=len(build.aliases),
            prefix_count=len(build.prefixes),
            conflict_count=len(build.conflicts),
            source_revision=source_revision,
            actual_radio_alias_count=diagnostics["actual_radio_alias_count"],
            actual_bssid_alias_count=diagnostics["actual_bssid_alias_count"],
            actual_bbssid_alias_count=diagnostics["actual_bbssid_alias_count"],
            derived_alias_count=diagnostics["derived_alias_count"],
            ambiguous_alias_count=diagnostics["ambiguous_alias_count"],
            build_duration_ms=build_duration_ms,
        )

    def index_state(self, *, site_id: str = "current") -> dict[str, object] | None:
        with self.database.connect_readonly() as connection:
            row = connection.execute(
                "SELECT * FROM ap_identity_index_state WHERE site_id = ?",
                (site_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def source_revision(self, *, site_id: str = "current") -> int:
        with self.database.connect_readonly() as connection:
            return self._source_revision(connection, site_id=site_id)

    def index_health(
        self,
        *,
        site_id: str = "current",
    ) -> tuple[dict[str, object] | None, int]:
        with self.database.connect_readonly() as connection:
            state = connection.execute(
                "SELECT * FROM ap_identity_index_state WHERE site_id = ?",
                (site_id,),
            ).fetchone()
            source_revision = self._source_revision(connection, site_id=site_id)
        return (dict(state) if state is not None else None, source_revision)

    @staticmethod
    def _source_revision(
        connection: sqlite3.Connection,
        *,
        site_id: str,
    ) -> int:
        row = connection.execute(
            "SELECT revision FROM ap_identity_source_state WHERE site_id = ?",
            (site_id,),
        ).fetchone()
        return int(row["revision"] or 0) if row is not None else 0

    def has_source_rows(self) -> bool:
        with self.database.connect_readonly() as connection:
            row = connection.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM ap_extension_points
                    UNION ALL
                    SELECT 1 FROM ac_fit_ap_resources
                    UNION ALL
                    SELECT 1 FROM ap_entities
                    UNION ALL
                    SELECT 1 FROM ac_fit_ap_optical
                    UNION ALL
                    SELECT 1 FROM trackside_ap_view_cache
                ) AS has_rows
                """
            ).fetchone()
        return bool(row and row["has_rows"])

    def exact_alias_rows(
        self,
        mac_key: str,
        *,
        site_id: str = "current",
    ) -> list[dict[str, object]]:
        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT a.*, e.*
                FROM ap_identity_mac_aliases a
                JOIN ap_identity_entities e ON e.entity_id = a.entity_id
                WHERE a.site_id = ?
                  AND a.mac_key = ?
                  AND a.is_active = 1
                ORDER BY a.match_priority DESC, a.alias_id
                """,
                (site_id, mac_key),
            ).fetchall()
        return [dict(row) for row in rows]

    def prefix_rows(
        self,
        mac_key: str,
        *,
        site_id: str = "current",
        prefix_bits: int = 36,
    ) -> list[dict[str, object]]:
        prefix_key = _normalized_prefix(mac_key, prefix_bits)
        if not prefix_key:
            return []
        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT p.*, e.*
                FROM ap_identity_h3c_prefixes p
                JOIN ap_identity_entities e ON e.entity_id = p.entity_id
                WHERE p.site_id = ?
                  AND p.prefix_bits = ?
                  AND p.prefix_key = ?
                  AND p.is_active = 1
                ORDER BY p.match_priority DESC, p.prefix_id
                """,
                (site_id, prefix_bits, prefix_key),
            ).fetchall()
        return [dict(row) for row in rows]

    def exact_name_rows(
        self,
        name: str,
        *,
        site_id: str = "current",
    ) -> list[dict[str, object]]:
        key = str(name or "").strip().casefold()
        if not key:
            return []
        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM ap_identity_entities
                WHERE site_id = ?
                  AND (
                    lower(trim(effective_ap_name)) = ?
                    OR lower(trim(effective_point_code)) = ?
                    OR lower(trim(ac_ap_name)) = ?
                    OR lower(trim(base_ap_name)) = ?
                  )
                ORDER BY effective_source = 'ac_runtime' DESC, entity_id
                """,
                (site_id, key, key, key, key),
            ).fetchall()
        return [dict(row) for row in rows]

    def entity_row(
        self,
        entity_id: str,
        *,
        site_id: str = "current",
    ) -> dict[str, object] | None:
        with self.database.connect_readonly() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM ap_identity_entities
                WHERE site_id = ? AND entity_id = ?
                """,
                (site_id, str(entity_id or "")),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_entity_rows(
        self,
        *,
        site_id: str = "current",
    ) -> list[dict[str, object]]:
        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM ap_identity_entities
                WHERE site_id = ?
                ORDER BY effective_station, effective_ap_name, entity_id
                """,
                (site_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_entity_rows(
        self,
        query: str,
        *,
        site_id: str = "current",
        limit: int = 200,
    ) -> list[dict[str, object]]:
        text = str(query or "").strip()
        like = f"%{text}%"
        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM ap_identity_entities
                WHERE site_id = ?
                  AND (
                    effective_ap_name LIKE ?
                    OR effective_point_code LIKE ?
                    OR effective_station LIKE ?
                    OR effective_section LIKE ?
                    OR ac_ap_name LIKE ?
                    OR base_ap_name LIKE ?
                  )
                ORDER BY effective_station, effective_ap_name, entity_id
                LIMIT ?
                """,
                (site_id, like, like, like, like, like, like, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def conflict_rows(
        self,
        *,
        site_id: str = "current",
        active_only: bool = True,
    ) -> list[dict[str, object]]:
        resolved_clause = "AND c.resolved_at IS NULL" if active_only else ""
        with self.database.connect_readonly() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, e.effective_ap_name, e.effective_ap_mac_display,
                       e.effective_station, e.ac_ap_mac_key, e.base_ap_mac_key,
                       e.base_record_id
                FROM ap_identity_conflicts c
                JOIN ap_identity_entities e ON e.entity_id = c.entity_id
                WHERE c.site_id = ?
                {resolved_clause}
                ORDER BY c.detected_at DESC, c.conflict_id DESC
                """,
                (site_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _load_base_rows(connection: sqlite3.Connection) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM ap_extension_points
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        ]

    @staticmethod
    def _load_ac_rows(connection: sqlite3.Connection) -> list[dict[str, object]]:
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT r.*,
                       d.device_vendor AS vendor,
                       f.model AS ac_model,
                       f.software_version AS ac_software_version,
                       COALESCE(NULLIF(m.site_name, ''), r.site) AS site_name,
                       m.belong_type AS metadata_belong_type,
                       m.belong_section AS metadata_belong_section,
                       m.section_start_station AS metadata_section_start_station,
                       m.section_end_station AS metadata_section_end_station,
                       m.mileage AS metadata_mileage,
                       m.location_note AS metadata_location_note,
                       m.direction AS metadata_direction
                FROM ac_fit_ap_resources r
                LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid
                LEFT JOIN devices d ON d.device_uuid = r.ac_device_uuid
                LEFT JOIN device_facts f ON f.device_uuid = r.ac_device_uuid
                ORDER BY r.updated_at DESC, r.id DESC
                """
            ).fetchall()
        ]
        by_uuid = {
            str(row.get("ap_uuid") or ""): row
            for row in rows
            if row.get("ap_uuid")
        }
        history_rows = connection.execute(
            """
            SELECT h.ap_uuid, h.rid, h.bbssid
            FROM ac_fit_ap_radio_history h
            JOIN (
                SELECT ap_uuid, rid, MAX(id) AS latest_id
                FROM ac_fit_ap_radio_history
                WHERE bbssid IS NOT NULL AND trim(bbssid) != ''
                GROUP BY ap_uuid, rid
            ) latest ON latest.latest_id = h.id
            """
        ).fetchall()
        for history in history_rows:
            row = by_uuid.get(str(history["ap_uuid"] or ""))
            rid = int(history["rid"] or 0)
            if row is not None and rid > 0:
                row[f"rid{rid}_bbssid_history"] = history["bbssid"]
        rows.extend(
            ApIdentityRepository._load_legacy_rows(
                connection,
                table="ap_entities",
                columns=(
                    "id",
                    "ap_uuid",
                    "ac_device_uuid",
                    "ap_name",
                    "ap_mac",
                    "serial_number",
                    "station",
                    "milestone",
                    "direction",
                    "location_note",
                    "last_resource_update_at",
                    "updated_at",
                ),
                aliases={
                    "station": "site_name",
                    "milestone": "mileage",
                    "last_resource_update_at": "collected_at",
                },
            )
        )
        rows.extend(
            ApIdentityRepository._load_legacy_rows(
                connection,
                table="ac_fit_ap_optical",
                columns=(
                    "id",
                    "ap_uuid",
                    "ac_device_uuid",
                    "ap_name",
                    "ap_mac",
                    "site",
                    "collected_at",
                    "updated_at",
                ),
                aliases={"site": "site_name"},
            )
        )
        rows.extend(
            ApIdentityRepository._load_legacy_rows(
                connection,
                table="trackside_ap_view_cache",
                columns=(
                    "id",
                    "ap_uuid",
                    "ap_name",
                    "ap_mac",
                    "station",
                    "last_collected_at",
                    "updated_at",
                ),
                aliases={
                    "station": "site_name",
                    "last_collected_at": "collected_at",
                },
            )
        )
        return rows

    @staticmethod
    def _load_legacy_rows(
        connection: sqlite3.Connection,
        *,
        table: str,
        columns: Sequence[str],
        aliases: Mapping[str, str],
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for row in connection.execute(
            f"SELECT {', '.join(columns)} FROM {table}"
        ).fetchall():
            payload = dict(row)
            for source, target in aliases.items():
                if payload.get(source) not in (None, ""):
                    payload[target] = payload[source]
            payload["_identity_source"] = "legacy_cache"
            payload["_identity_source_id"] = f"{table}:{payload.get('id')}"
            payload["_identity_legacy_table"] = table
            result.append(payload)
        return result

    @staticmethod
    def _replace_index(
        connection: sqlite3.Connection,
        build: ApIdentityIndexBuild,
        *,
        site_id: str,
        reason: str,
        revision: int,
        built_at: str,
        source_revision: int,
        diagnostics: Mapping[str, int],
        build_duration_ms: float,
    ) -> None:
        for table in (
            "ap_identity_conflicts",
            "ap_identity_mac_aliases",
            "ap_identity_h3c_prefixes",
            "ap_identity_entities",
        ):
            connection.execute(f"DELETE FROM {table} WHERE site_id = ?", (site_id,))

        entity_columns = tuple(ApIdentityEntityRecordColumns)
        for entity in build.entities:
            values = asdict(entity)
            values["created_at"] = built_at
            values["updated_at"] = built_at
            _insert(connection, "ap_identity_entities", (*entity_columns, "created_at", "updated_at"), values)

        for alias in build.aliases:
            values = asdict(alias)
            values["is_exact"] = int(bool(values["is_exact"]))
            values["is_active"] = 1
            values["created_at"] = built_at
            values["updated_at"] = built_at
            _insert(
                connection,
                "ap_identity_mac_aliases",
                (
                    "site_id",
                    "entity_id",
                    "mac_key",
                    "mac_display",
                    "alias_type",
                    "source",
                    "match_priority",
                    "confidence",
                    "radio_id",
                    "derivation_rule",
                    "is_exact",
                    "is_active",
                    "created_at",
                    "updated_at",
                ),
                values,
            )

        for prefix in build.prefixes:
            values = asdict(prefix)
            values["is_active"] = 1
            values["created_at"] = built_at
            values["updated_at"] = built_at
            _insert(
                connection,
                "ap_identity_h3c_prefixes",
                (
                    "site_id",
                    "entity_id",
                    "base_mac_key",
                    "prefix_key",
                    "prefix_bits",
                    "derivation_rule",
                    "source",
                    "match_priority",
                    "confidence",
                    "is_active",
                    "created_at",
                    "updated_at",
                ),
                values,
            )

        for conflict in build.conflicts:
            values = asdict(conflict)
            values["detected_at"] = built_at
            values["resolved_at"] = None
            values["details_json"] = json.dumps(
                values.pop("details"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            _insert(
                connection,
                "ap_identity_conflicts",
                (
                    "site_id",
                    "entity_id",
                    "conflict_type",
                    "ac_value",
                    "base_value",
                    "effective_source",
                    "detected_at",
                    "resolved_at",
                    "details_json",
                ),
                values,
            )

        connection.execute(
            """
            INSERT INTO ap_identity_index_state (
                site_id, revision, source_revision,
                base_record_count, ac_record_count,
                entity_count, alias_count, prefix_count, conflict_count,
                actual_radio_alias_count, actual_bssid_alias_count,
                actual_bbssid_alias_count, derived_alias_count,
                ambiguous_alias_count, build_duration_ms, diagnostics_json,
                build_reason, built_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site_id) DO UPDATE SET
                revision = excluded.revision,
                source_revision = excluded.source_revision,
                base_record_count = excluded.base_record_count,
                ac_record_count = excluded.ac_record_count,
                entity_count = excluded.entity_count,
                alias_count = excluded.alias_count,
                prefix_count = excluded.prefix_count,
                conflict_count = excluded.conflict_count,
                actual_radio_alias_count = excluded.actual_radio_alias_count,
                actual_bssid_alias_count = excluded.actual_bssid_alias_count,
                actual_bbssid_alias_count = excluded.actual_bbssid_alias_count,
                derived_alias_count = excluded.derived_alias_count,
                ambiguous_alias_count = excluded.ambiguous_alias_count,
                build_duration_ms = excluded.build_duration_ms,
                diagnostics_json = excluded.diagnostics_json,
                build_reason = excluded.build_reason,
                built_at = excluded.built_at
            """,
            (
                site_id,
                revision,
                source_revision,
                build.base_record_count,
                build.ac_record_count,
                len(build.entities),
                len(build.aliases),
                len(build.prefixes),
                len(build.conflicts),
                diagnostics["actual_radio_alias_count"],
                diagnostics["actual_bssid_alias_count"],
                diagnostics["actual_bbssid_alias_count"],
                diagnostics["derived_alias_count"],
                diagnostics["ambiguous_alias_count"],
                build_duration_ms,
                json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")),
                reason,
                built_at,
            ),
        )


ApIdentityEntityRecordColumns = (
    "entity_id",
    "site_id",
    "effective_ap_name",
    "effective_ap_mac_key",
    "effective_ap_mac_display",
    "effective_station",
    "effective_section",
    "effective_point_code",
    "effective_serial_number",
    "effective_location",
    "effective_mileage",
    "effective_direction",
    "effective_belong_type",
    "ac_ap_uuid",
    "ac_device_uuid",
    "ac_ap_name",
    "ac_ap_mac_key",
    "ac_station",
    "ac_section",
    "ac_updated_at",
    "base_record_id",
    "base_ap_name",
    "base_ap_mac_key",
    "base_station",
    "base_section",
    "base_updated_at",
    "effective_source",
    "identity_status",
    "data_quality_warning",
)


def _normalized_prefix(value: object, bits: int) -> str | None:
    key = str(value or "").strip().casefold()
    if (
        len(key) != 12
        or any(char not in "0123456789abcdef" for char in key)
        or bits <= 0
        or bits > 48
        or bits % 4
    ):
        return None
    return key[: bits // 4]


def _insert(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    values: Mapping[str, object],
) -> None:
    names = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
        [values.get(column) for column in columns],
    )


def _build_diagnostics(build: ApIdentityIndexBuild) -> dict[str, int]:
    counts = {
        "actual_radio_alias_count": 0,
        "actual_bssid_alias_count": 0,
        "actual_bbssid_alias_count": 0,
        "derived_alias_count": 0,
        "ambiguous_alias_count": 0,
    }
    entities_by_mac: dict[str, set[str]] = {}
    for alias in build.aliases:
        if alias.alias_type == "ac_radio_mac":
            counts["actual_radio_alias_count"] += 1
        elif alias.alias_type == "ac_bssid":
            counts["actual_bssid_alias_count"] += 1
        elif alias.alias_type == "ac_bbssid":
            counts["actual_bbssid_alias_count"] += 1
        elif alias.alias_type in {"h3c_r1_derived", "h3c_r2_derived"}:
            counts["derived_alias_count"] += 1
        if alias.alias_type in {
            "ac_radio_mac",
            "ac_bssid",
            "ac_bbssid",
            "h3c_r1_derived",
            "h3c_r2_derived",
        }:
            entities_by_mac.setdefault(alias.mac_key, set()).add(alias.entity_id)
    counts["ambiguous_alias_count"] = sum(
        1 for entities in entities_by_mac.values() if len(entities) > 1
    )
    return counts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


__all__ = ["ApIdentityRepository"]
