from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.repositories.mesh_catalog_repository import dt_text
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION


_SOURCE_COLUMNS = {
    "parsed_db_path": "TEXT DEFAULT ''",
    "parsed_db_size": "INTEGER DEFAULT 0",
    "db_schema_version": "TEXT DEFAULT ''",
    "analysis_params_json": "TEXT DEFAULT ''",
    "raw_relative_path": "TEXT DEFAULT ''",
    "parsed_relative_path": "TEXT DEFAULT ''",
    "archive_sha256": "TEXT DEFAULT ''",
    "bundle_member_id": "TEXT DEFAULT ''",
    "bundle_member_sha256": "TEXT DEFAULT ''",
    "file_exists": "INTEGER DEFAULT 1",
    "file_status": "TEXT DEFAULT 'ok'",
    "parsed_deleted_at": "TEXT DEFAULT ''",
    "parsed_delete_error": "TEXT DEFAULT ''",
}


class MeshSourceIndexRepository:
    """只维护 MESH 索引中的来源元数据，不迁移旧派生业务表。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file():
            raise ValueError("MESH 来源索引不存在")
        with self._connect() as connection:
            initialize_sqlite_wal(connection)
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_files'"
            ).fetchone():
                raise ValueError("MESH 来源索引缺少 source_files")
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_files)")}
            for name, definition in _SOURCE_COLUMNS.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE source_files ADD COLUMN {name} {definition}")

    def get_source_file(self, source_file_id: int) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_files WHERE id = ?",
                (int(source_file_id),),
            ).fetchone()
        return dict(row) if row else None

    def list_source_files(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM source_files ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def update_source_provenance(
        self,
        source_file_id: int,
        *,
        raw_relative_path: str,
        parsed_relative_path: str,
        archive_sha256: str = "",
        bundle_member_id: str = "",
        bundle_member_sha256: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE source_files
                SET raw_relative_path = ?, parsed_relative_path = ?, archive_sha256 = ?,
                    bundle_member_id = ?, bundle_member_sha256 = ?
                WHERE id = ?
                """,
                (
                    raw_relative_path,
                    parsed_relative_path,
                    archive_sha256,
                    bundle_member_id,
                    bundle_member_sha256,
                    int(source_file_id),
                ),
            )

    def update_rebuilt_source(
        self,
        source_file_id: int,
        *,
        raw_path: Path,
        raw_relative_path: str,
        parsed_path: Path,
        parsed_relative_path: str,
        parser_version: str,
        first_sample_time: datetime | None,
        last_sample_time: datetime | None,
        lines_read: int,
        records_parsed: int,
        records_skipped: int,
        issue_count: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE source_files
                SET archived_path = ?, archived_filename = ?, raw_relative_path = ?,
                    parsed_db_path = ?, parsed_relative_path = ?, parsed_db_size = ?,
                    db_schema_version = ?, parser_version = ?, parse_status = 'imported',
                    first_sample_time = ?, last_sample_time = ?, lines_read = ?,
                    records_parsed = ?, records_skipped = ?, issue_count = ?,
                    error_message = '', file_exists = 1, file_status = 'ok',
                    parsed_deleted_at = '', parsed_delete_error = ''
                WHERE id = ?
                """,
                (
                    str(raw_path),
                    raw_path.name,
                    raw_relative_path,
                    str(parsed_path),
                    parsed_relative_path,
                    parsed_path.stat().st_size,
                    SCHEMA_VERSION,
                    parser_version,
                    dt_text(first_sample_time),
                    dt_text(last_sample_time),
                    int(lines_read),
                    int(records_parsed),
                    int(records_skipped),
                    int(issue_count),
                    int(source_file_id),
                ),
            )

    def restore_source_metadata(self, source_file_id: int, snapshot: dict[str, object]) -> None:
        with self._connect() as connection:
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_files)")}
            fields = tuple(
                field
                for field in (
                    "archived_path",
                    "archived_filename",
                    "raw_relative_path",
                    "parsed_db_path",
                    "parsed_relative_path",
                    "parsed_db_size",
                    "db_schema_version",
                    "parser_version",
                    "parse_status",
                    "first_sample_time",
                    "last_sample_time",
                    "lines_read",
                    "records_parsed",
                    "records_skipped",
                    "issue_count",
                    "error_message",
                    "file_exists",
                    "file_status",
                    "parsed_deleted_at",
                    "parsed_delete_error",
                    "archive_sha256",
                    "bundle_member_id",
                    "bundle_member_sha256",
                )
                if field in columns
            )
            connection.execute(
                f"UPDATE source_files SET {', '.join(f'{field} = ?' for field in fields)} WHERE id = ?",
                [*(snapshot.get(field) for field in fields), int(source_file_id)],
            )

    def aggregate_summary(self) -> dict[str, object]:
        rows = self.list_source_files()
        link_count = 0
        session_count = 0
        event_count = 0
        for row in rows:
            path = Path(str(row.get("parsed_db_path") or "").strip().strip("'\""))
            if not path.is_file():
                continue
            try:
                with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as detail:
                    link_count += self._count(detail, "mesh_links")
                    session_count += self._count(detail, "mesh_sessions")
                    event_count += self._count(detail, "switch_events")
            except sqlite3.Error:
                continue
        first_values = [str(row.get("first_sample_time") or "") for row in rows if row.get("first_sample_time")]
        last_values = [str(row.get("last_sample_time") or "") for row in rows if row.get("last_sample_time")]
        imported = [str(row.get("imported_at") or "") for row in rows if row.get("imported_at")]
        return {
            "earliest_sample_time": min(first_values) if first_values else None,
            "latest_sample_time": max(last_values) if last_values else None,
            "source_file_count": len(rows),
            "sample_count": sum(int(row.get("records_parsed") or 0) for row in rows),
            "link_record_count": link_count,
            "session_count": session_count,
            "event_count": event_count,
            "last_import_at": max(imported) if imported else None,
        }

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, foreign_keys=True)

    @staticmethod
    def _count(connection: sqlite3.Connection, table: str) -> int:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            return 0
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)


__all__ = ["MeshSourceIndexRepository"]
