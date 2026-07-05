from __future__ import annotations

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
                """
            )

    def create_profile(self, profile: MeshMrProfile) -> MeshMrProfile:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mr_profiles (
                    mr_id, display_name, safe_folder_name, relative_folder_path, linked_device_id,
                    earliest_sample_time, latest_sample_time, source_file_count, sample_count,
                    link_record_count, session_count, event_count, last_import_at, created_at,
                    updated_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def update_profile_identity(self, profile: MeshMrProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mr_profiles
                SET display_name = ?, safe_folder_name = ?, relative_folder_path = ?,
                    linked_device_id = ?, updated_at = ?
                WHERE mr_id = ?
                """,
                (
                    profile.display_name,
                    profile.safe_folder_name,
                    profile.relative_folder_path,
                    profile.linked_device_id,
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

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, foreign_keys=True)

    def _profile_values(self, profile: MeshMrProfile) -> tuple[object, ...]:
        return (
            profile.mr_id,
            profile.display_name,
            profile.safe_folder_name,
            profile.relative_folder_path,
            profile.linked_device_id,
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
