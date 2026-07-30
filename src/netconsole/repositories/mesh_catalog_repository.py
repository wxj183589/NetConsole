from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.models.mesh_log_models import MeshMrProfile


def dt_text(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="milliseconds") if value else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class MeshCatalogRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            initialize_sqlite_wal(conn)
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS mr_profiles (
                    mr_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL UNIQUE,
                    safe_folder_name TEXT NOT NULL UNIQUE,
                    relative_folder_path TEXT NOT NULL,
                    linked_device_id INTEGER NULL,
                    linked_device_uuid TEXT NULL,
                    earliest_sample_time TEXT NULL,
                    latest_sample_time TEXT NULL,
                    source_file_count INTEGER DEFAULT 0,
                    sample_count INTEGER DEFAULT 0,
                    link_record_count INTEGER DEFAULT 0,
                    session_count INTEGER DEFAULT 0,
                    event_count INTEGER DEFAULT 0,
                    last_import_at TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notes TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS mesh_session_index (
                    session_id TEXT PRIMARY KEY,
                    mr_id TEXT NOT NULL,
                    source_file_id INTEGER NOT NULL,
                    train_name TEXT NOT NULL DEFAULT '',
                    mr_name TEXT NOT NULL,
                    mr_role TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'raw_mesh_log',
                    original_filename TEXT NOT NULL DEFAULT '',
                    analysis_time TEXT NULL,
                    first_sample_time TEXT NULL,
                    last_sample_time TEXT NULL,
                    link_record_count INTEGER NULL,
                    active_link_count INTEGER NULL,
                    standby_link_count INTEGER NULL,
                    event_count INTEGER NULL,
                    link_up_event_count INTEGER NULL,
                    link_down_event_count INTEGER NULL,
                    switch_event_count INTEGER NULL,
                    short_link_count INTEGER NULL,
                    pingpong_count INTEGER NULL,
                    rssi_anomaly_count INTEGER NULL,
                    channel_busy_anomaly_count INTEGER NULL,
                    unmatched_ap_count INTEGER NULL,
                    data_integrity TEXT NOT NULL DEFAULT 'partial',
                    analysis_status TEXT NOT NULL DEFAULT 'unknown',
                    parsed_status TEXT NOT NULL DEFAULT 'indexing',
                    parsed_message TEXT NOT NULL DEFAULT '',
                    schema_version TEXT NULL,
                    available_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    missing_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    report_count INTEGER NOT NULL DEFAULT 0,
                    source_revision TEXT NOT NULL DEFAULT '',
                    detail_indexed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mr_id, source_file_id),
                    FOREIGN KEY(mr_id) REFERENCES mr_profiles(mr_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_mesh_session_index_analysis_time
                    ON mesh_session_index(analysis_time DESC, session_id DESC);
                CREATE INDEX IF NOT EXISTS idx_mesh_session_index_mr
                    ON mesh_session_index(mr_id, source_file_id);
                CREATE INDEX IF NOT EXISTS idx_mesh_session_index_warning
                    ON mesh_session_index(warning_count, analysis_time DESC);
                CREATE TABLE IF NOT EXISTS mesh_source_fingerprints (
                    content_sha256 TEXT NOT NULL,
                    raw_sha256 TEXT NOT NULL DEFAULT '',
                    mr_id TEXT NOT NULL,
                    source_file_id INTEGER NOT NULL,
                    stored_filename TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(content_sha256, mr_id, source_file_id),
                    FOREIGN KEY(mr_id) REFERENCES mr_profiles(mr_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_mesh_source_fingerprints_raw
                    ON mesh_source_fingerprints(raw_sha256);
                CREATE TABLE IF NOT EXISTS mesh_catalog_index_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    status TEXT NOT NULL DEFAULT 'pending',
                    discovered_session_count INTEGER NOT NULL DEFAULT 0,
                    indexed_session_count INTEGER NOT NULL DEFAULT 0,
                    detail_indexed_session_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(mr_profiles)")}
            if "linked_device_uuid" not in columns:
                conn.execute("ALTER TABLE mr_profiles ADD COLUMN linked_device_uuid TEXT NULL")
            conn.execute(
                """
                INSERT OR IGNORE INTO mesh_catalog_index_state (
                    singleton, status, updated_at
                ) VALUES (1, 'pending', ?)
                """,
                (datetime.now().isoformat(sep=" ", timespec="milliseconds"),),
            )

    def create_profile(self, profile: MeshMrProfile) -> MeshMrProfile:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mr_profiles (
                    mr_id, display_name, safe_folder_name, relative_folder_path, linked_device_id, linked_device_uuid,
                    earliest_sample_time, latest_sample_time, source_file_count, sample_count,
                    link_record_count, session_count, event_count, last_import_at, created_at,
                    updated_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._profile_values(profile),
            )
        return profile

    def list_profiles(self) -> list[MeshMrProfile]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM mr_profiles ORDER BY display_name COLLATE NOCASE").fetchall()
        return [self._row_to_profile(row) for row in rows]

    def get_profile(self, mr_id: str) -> MeshMrProfile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mr_profiles WHERE mr_id = ?", (mr_id,)).fetchone()
        return self._row_to_profile(row) if row else None

    def get_by_display_name(self, display_name: str) -> MeshMrProfile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mr_profiles WHERE display_name = ?", (display_name,)).fetchone()
        return self._row_to_profile(row) if row else None

    def get_by_linked_device_id(self, linked_device_id: int) -> MeshMrProfile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mr_profiles WHERE linked_device_id = ? LIMIT 1", (int(linked_device_id),)).fetchone()
        return self._row_to_profile(row) if row else None

    def get_by_linked_device_uuid(self, linked_device_uuid: str) -> MeshMrProfile | None:
        value = str(linked_device_uuid or "").strip()
        if not value:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mr_profiles WHERE linked_device_uuid = ? LIMIT 1", (value,)).fetchone()
        return self._row_to_profile(row) if row else None

    def update_profile_identity(self, profile: MeshMrProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mr_profiles
                SET display_name = ?, safe_folder_name = ?, relative_folder_path = ?,
                    linked_device_id = ?, linked_device_uuid = ?, updated_at = ?
                WHERE mr_id = ?
                """,
                (
                    profile.display_name,
                    profile.safe_folder_name,
                    profile.relative_folder_path,
                    profile.linked_device_id,
                    profile.linked_device_uuid,
                    dt_text(profile.updated_at) or datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                    profile.mr_id,
                ),
            )

    def safe_folder_exists(self, safe_folder_name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM mr_profiles WHERE safe_folder_name = ?", (safe_folder_name,)).fetchone()
        return row is not None

    def update_summary(self, mr_id: str, summary: dict[str, object]) -> None:
        fields = [
            "earliest_sample_time",
            "latest_sample_time",
            "source_file_count",
            "sample_count",
            "link_record_count",
            "session_count",
            "event_count",
            "last_import_at",
        ]
        values = [summary.get(field) for field in fields]
        values.append(datetime.now().isoformat(sep=" ", timespec="milliseconds"))
        values.append(mr_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE mr_profiles SET {', '.join(field + ' = ?' for field in fields)}, updated_at = ? WHERE mr_id = ?",
                values,
            )

    def upsert_session_index(self, row: dict[str, object]) -> None:
        self.upsert_session_indexes([row])

    def upsert_session_indexes(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        fields = (
            "session_id", "mr_id", "source_file_id", "train_name", "mr_name", "mr_role",
            "source_type", "original_filename", "analysis_time", "first_sample_time",
            "last_sample_time", "link_record_count", "active_link_count",
            "standby_link_count", "event_count", "link_up_event_count",
            "link_down_event_count", "switch_event_count", "short_link_count",
            "pingpong_count", "rssi_anomaly_count", "channel_busy_anomaly_count",
            "unmatched_ap_count", "data_integrity", "analysis_status", "parsed_status",
            "parsed_message", "schema_version", "available_capabilities_json",
            "missing_capabilities_json", "warning_count", "report_count",
            "source_revision", "detail_indexed", "updated_at",
        )
        values = [[row.get(field) for field in fields] for row in rows]
        assignments = ", ".join(
            f"{field}=excluded.{field}" for field in fields if field != "session_id"
        )
        with self._connect() as conn:
            conn.executemany(
                f"""
                INSERT INTO mesh_session_index ({", ".join(fields)})
                VALUES ({", ".join("?" for _ in fields)})
                ON CONFLICT(session_id) DO UPDATE SET {assignments}
                """,
                values,
            )

    def upsert_source_fingerprint(
        self,
        *,
        content_sha256: str,
        raw_sha256: str,
        mr_id: str,
        source_file_id: int,
        stored_filename: str,
    ) -> None:
        content = str(content_sha256 or "").strip().casefold()
        raw = str(raw_sha256 or "").strip().casefold()
        if not content and not raw:
            return
        self.upsert_source_fingerprints(
            [
                {
                    "content_sha256": content,
                    "raw_sha256": raw,
                    "mr_id": mr_id,
                    "source_file_id": int(source_file_id),
                    "stored_filename": stored_filename,
                }
            ]
        )

    def upsert_source_fingerprints(self, rows: list[dict[str, object]]) -> None:
        prepared: list[tuple[str, str, str, int, str, str]] = []
        now = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        for row in rows:
            content = str(row.get("content_sha256") or "").strip().casefold()
            raw = str(row.get("raw_sha256") or "").strip().casefold()
            if not content and not raw:
                continue
            prepared.append(
                (
                    content or f"raw:{raw}",
                    raw,
                    str(row["mr_id"]),
                    int(row["source_file_id"]),
                    str(row.get("stored_filename") or ""),
                    now,
                )
            )
        if not prepared:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                DELETE FROM mesh_source_fingerprints
                WHERE mr_id = ? AND source_file_id = ? AND content_sha256 <> ?
                """,
                ((mr_id, source_file_id, content) for content, _raw, mr_id, source_file_id, _name, _now in prepared),
            )
            conn.executemany(
                """
                INSERT INTO mesh_source_fingerprints (
                    content_sha256, raw_sha256, mr_id, source_file_id,
                    stored_filename, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_sha256, mr_id, source_file_id) DO UPDATE SET
                    raw_sha256=excluded.raw_sha256,
                    stored_filename=excluded.stored_filename,
                    updated_at=excluded.updated_at
                """,
                prepared,
            )

    def find_source_fingerprints(
        self,
        *,
        content_sha256: str,
        raw_sha256: str = "",
    ) -> list[dict[str, object]]:
        content = str(content_sha256 or "").strip().casefold()
        raw = str(raw_sha256 or "").strip().casefold()
        if not content and not raw:
            return []
        clauses: list[str] = []
        values: list[object] = []
        if content:
            clauses.append("f.content_sha256 = ?")
            values.append(content)
        if raw:
            clauses.append("f.raw_sha256 = ?")
            values.append(raw)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT f.mr_id, f.source_file_id, f.stored_filename,
                       p.display_name AS profile_name
                FROM mesh_source_fingerprints f
                JOIN mr_profiles p ON p.mr_id = f.mr_id
                WHERE {" OR ".join(clauses)}
                ORDER BY f.updated_at, f.mr_id, f.source_file_id
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_stale_session_index(self, active_session_ids: set[str]) -> None:
        with self._connect() as conn:
            if not active_session_ids:
                conn.execute("DELETE FROM mesh_session_index")
                conn.execute("DELETE FROM mesh_source_fingerprints")
                return
            conn.execute("CREATE TEMP TABLE active_mesh_sessions(session_id TEXT PRIMARY KEY)")
            conn.executemany(
                "INSERT INTO active_mesh_sessions(session_id) VALUES (?)",
                ((session_id,) for session_id in active_session_ids),
            )
            conn.execute(
                "DELETE FROM mesh_session_index WHERE session_id NOT IN (SELECT session_id FROM active_mesh_sessions)"
            )
            conn.execute(
                """
                DELETE FROM mesh_source_fingerprints
                WHERE NOT EXISTS (
                    SELECT 1 FROM mesh_session_index s
                    WHERE s.mr_id = mesh_source_fingerprints.mr_id
                      AND s.source_file_id = mesh_source_fingerprints.source_file_id
                )
                """
            )

    def session_index_revisions(self) -> dict[str, tuple[str, bool]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, source_revision, detail_indexed FROM mesh_session_index"
            ).fetchall()
        return {
            str(row["session_id"]): (
                str(row["source_revision"] or ""),
                bool(row["detail_indexed"]),
            )
            for row in rows
        }

    def update_index_state(
        self,
        *,
        status: str,
        discovered: int,
        indexed: int,
        detail_indexed: int,
        last_error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mesh_catalog_index_state
                SET status = ?, discovered_session_count = ?,
                    indexed_session_count = ?, detail_indexed_session_count = ?,
                    last_error = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (
                    status,
                    int(discovered),
                    int(indexed),
                    int(detail_indexed),
                    str(last_error or "")[:500],
                    datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                ),
            )

    def mark_index_pending(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mesh_catalog_index_state
                SET status = 'pending', updated_at = ?
                WHERE singleton = 1
                """,
                (datetime.now().isoformat(sep=" ", timespec="milliseconds"),),
            )

    def mark_session_index_dirty(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mesh_session_index
                SET source_revision = '', detail_indexed = 0
                WHERE session_id = ?
                """,
                (session_id,),
            )
            conn.execute(
                """
                UPDATE mesh_catalog_index_state
                SET status = 'pending', updated_at = ?
                WHERE singleton = 1
                """,
                (datetime.now().isoformat(sep=" ", timespec="milliseconds"),),
            )

    def mark_index_failed(self, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mesh_catalog_index_state
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (
                    str(error or "")[:500],
                    datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                ),
            )

    @staticmethod
    def session_index_row(
        *,
        dto: object,
        mr_id: str,
        source_file_id: int,
        stats: dict[str, object],
        source_revision: str,
        detail_indexed: bool,
    ) -> dict[str, object]:
        return {
            **{
                field: getattr(dto, field)
                for field in (
                    "session_id", "train_name", "mr_name", "mr_role", "source_type",
                    "original_filename", "analysis_time", "first_sample_time",
                    "last_sample_time", "link_record_count", "active_link_count",
                    "standby_link_count", "event_count", "data_integrity",
                    "analysis_status", "parsed_status", "parsed_message", "schema_version",
                    "warning_count", "report_count",
                )
            },
            "mr_id": mr_id,
            "source_file_id": int(source_file_id),
            "link_up_event_count": stats.get("link_up"),
            "link_down_event_count": stats.get("link_down"),
            "switch_event_count": stats.get("switches"),
            "short_link_count": stats.get("short"),
            "pingpong_count": stats.get("pingpong"),
            "rssi_anomaly_count": stats.get("rssi_anomalies"),
            "channel_busy_anomaly_count": stats.get("busy_anomalies"),
            "unmatched_ap_count": stats.get("unmatched"),
            "available_capabilities_json": json.dumps(
                getattr(dto, "available_capabilities"), ensure_ascii=False
            ),
            "missing_capabilities_json": json.dumps(
                getattr(dto, "missing_capabilities"), ensure_ascii=False
            ),
            "source_revision": source_revision,
            "detail_indexed": int(detail_indexed),
            "updated_at": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
        }

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, foreign_keys=True)

    def _profile_values(self, profile: MeshMrProfile) -> tuple[object, ...]:
        return (
            profile.mr_id,
            profile.display_name,
            profile.safe_folder_name,
            profile.relative_folder_path,
            profile.linked_device_id,
            profile.linked_device_uuid,
            dt_text(profile.earliest_sample_time),
            dt_text(profile.latest_sample_time),
            profile.source_file_count,
            profile.sample_count,
            profile.link_record_count,
            profile.session_count,
            profile.event_count,
            dt_text(profile.last_import_at),
            dt_text(profile.created_at) or datetime.now().isoformat(sep=" ", timespec="milliseconds"),
            dt_text(profile.updated_at) or datetime.now().isoformat(sep=" ", timespec="milliseconds"),
            profile.notes,
        )

    def _row_to_profile(self, row: sqlite3.Row) -> MeshMrProfile:
        return MeshMrProfile(
            mr_id=row["mr_id"],
            display_name=row["display_name"],
            safe_folder_name=row["safe_folder_name"],
            relative_folder_path=row["relative_folder_path"],
            linked_device_id=row["linked_device_id"],
            linked_device_uuid=row["linked_device_uuid"] if "linked_device_uuid" in row.keys() else None,
            earliest_sample_time=parse_dt(row["earliest_sample_time"]),
            latest_sample_time=parse_dt(row["latest_sample_time"]),
            source_file_count=row["source_file_count"],
            sample_count=row["sample_count"],
            link_record_count=row["link_record_count"],
            session_count=row["session_count"],
            event_count=row["event_count"],
            last_import_at=parse_dt(row["last_import_at"]),
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            notes=row["notes"] or "",
        )
