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
    "raw_sha256": "TEXT DEFAULT ''",
    "content_sha256": "TEXT DEFAULT ''",
    "source_status": "TEXT DEFAULT ''",
    "file_exists": "INTEGER DEFAULT 1",
    "deleted_at": "TEXT DEFAULT ''",
    "delete_error": "TEXT DEFAULT ''",
    "file_status": "TEXT DEFAULT 'ok'",
    "parsed_deleted_at": "TEXT DEFAULT ''",
    "parsed_delete_error": "TEXT DEFAULT ''",
    "identity_index_revision": "INTEGER DEFAULT 0",
    "identity_mapped_at": "TEXT DEFAULT ''",
    "identity_mapping_status": "TEXT DEFAULT 'unknown'",
    "info_count": "INTEGER DEFAULT 0",
    "warning_count": "INTEGER DEFAULT 0",
    "error_count": "INTEGER DEFAULT 0",
    "issue_severity_version": "INTEGER DEFAULT 0",
}


class MeshSourceIndexRepository:
    """只维护 MESH 索引中的来源元数据，不迁移旧派生业务表。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file():
            raise ValueError("MESH 来源索引不存在")
        with self._connect() as connection:
            initialize_sqlite_wal(connection)
            # Serialize schema compatibility checks across worker processes.
            # The second opener reads columns only after the first migration
            # transaction commits, eliminating PRAGMA/ALTER TOCTOU races.
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_files'"
            ).fetchone():
                raise ValueError("MESH 来源索引缺少 source_files")
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_files)")}
            for name, definition in _SOURCE_COLUMNS.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE source_files ADD COLUMN {name} {definition}")

    def mark_source_broken(
        self,
        source_file_id: int,
        *,
        raw_exists: bool,
        reason_code: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE source_files
                SET source_status = 'BROKEN_SOURCE',
                    file_exists = ?,
                    file_status = 'broken',
                    error_message = ?
                WHERE id = ?
                """,
                (
                    int(raw_exists),
                    str(reason_code or "BROKEN_SOURCE"),
                    int(source_file_id),
                ),
            )

    def restore_raw_archive(
        self,
        source_file_id: int,
        *,
        raw_path: Path,
        raw_relative_path: str,
        raw_sha256: str,
        content_sha256: str,
        archive_sha256: str = "",
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE source_files
                SET archived_path = ?, archived_filename = ?, raw_relative_path = ?,
                    raw_sha256 = ?, content_sha256 = ?, archive_sha256 = ?,
                    file_exists = 1, file_status = 'ok', source_status = 'imported',
                    error_message = '', deleted_at = '', delete_error = ''
                WHERE id = ?
                """,
                (
                    str(raw_path),
                    raw_path.name,
                    str(raw_relative_path or ""),
                    str(raw_sha256 or ""),
                    str(content_sha256 or ""),
                    str(archive_sha256 or ""),
                    int(source_file_id),
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("MESH 来源不存在")

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

    def count_parsed_data_by_source_file(self, source_file_id: int | str) -> dict[str, int]:
        if source_file_id in (None, ""):
            return {"links": 0, "events": 0, "issues": 0, "caches": 0}
        value = int(source_file_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_files WHERE id = ?",
                (value,),
            ).fetchone()
            if row is None:
                return {"links": 0, "events": 0, "issues": 0, "caches": 0}
            parsed_db_path = Path(str(row["parsed_db_path"] or "").strip().strip("'\""))
            if parsed_db_path.is_file():
                counts = self._count_parsed_data_from_detail(parsed_db_path)
                if any(counts.values()):
                    return counts
            counts = self._count_rows_by_source_file(connection, value)
            if not any(counts.values()):
                counts["links"] = int(row["records_parsed"] or 0) if "records_parsed" in row.keys() else 0
                counts["events"] = int(row["event_count"] or 0) if "event_count" in row.keys() else 0
                counts["issues"] = int(row["issue_count"] or 0) if "issue_count" in row.keys() else 0
            return counts

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
        info_count: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
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
                    info_count = ?, warning_count = ?, error_count = ?, issue_severity_version = 1,
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
                    int(info_count),
                    int(warning_count),
                    int(error_count),
                    int(source_file_id),
                ),
            )

    def update_identity_mapping(
        self,
        source_file_id: int,
        *,
        identity_index_revision: int,
        identity_mapped_at: str,
        identity_mapping_status: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE source_files
                SET identity_index_revision = ?, identity_mapped_at = ?,
                    identity_mapping_status = ?
                WHERE id = ?
                """,
                (
                    int(identity_index_revision),
                    str(identity_mapped_at or ""),
                    str(identity_mapping_status or "unknown"),
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

    def mark_parsed_deleted(self, source_file_id: int) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT deleted_at FROM source_files WHERE id = ?",
                (int(source_file_id),),
            ).fetchone()
            if row is None:
                raise ValueError("MESH 来源不存在")
            status = "all_deleted" if str(row["deleted_at"] or "") else "parsed_deleted"
            connection.execute(
                """
                UPDATE source_files
                SET file_status = ?, parsed_deleted_at = datetime('now'),
                    parsed_delete_error = '', parsed_db_size = 0
                WHERE id = ?
                """,
                (status, int(source_file_id)),
            )

    def delete_source_file(self, source_file_id: int) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_files WHERE id = ?",
                (int(source_file_id),),
            ).fetchone()
            if row is None:
                return None
            connection.execute("DELETE FROM source_files WHERE id = ?", (int(source_file_id),))
            return dict(row)

    def restore_source_file(self, row: dict[str, object]) -> None:
        with self._connect() as connection:
            columns = [
                str(item[1])
                for item in connection.execute("PRAGMA table_info(source_files)").fetchall()
            ]
            names = [name for name in columns if name in row]
            connection.execute(
                f"INSERT OR REPLACE INTO source_files ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                [row[name] for name in names],
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
    def _count_parsed_data_from_detail(path: Path) -> dict[str, int]:
        try:
            uri = f"{path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                return {
                    "links": MeshSourceIndexRepository._count_table_rows(connection, "mesh_links"),
                    "events": MeshSourceIndexRepository._count_table_rows(connection, "switch_events"),
                    "issues": MeshSourceIndexRepository._count_table_rows(connection, "parse_issues"),
                    "caches": 0,
                }
        except sqlite3.Error:
            return {"links": 0, "events": 0, "issues": 0, "caches": 0}

    @staticmethod
    def _count_rows_by_source_file(connection: sqlite3.Connection, source_file_id: int) -> dict[str, int]:
        return {
            "links": MeshSourceIndexRepository._count_table_rows(connection, "mesh_links", source_file_id),
            "events": MeshSourceIndexRepository._count_table_rows(connection, "switch_events", source_file_id),
            "issues": MeshSourceIndexRepository._count_table_rows(connection, "parse_issues", source_file_id),
            "caches": 0,
        }

    @staticmethod
    def _count_table_rows(
        connection: sqlite3.Connection,
        table: str,
        source_file_id: int | None = None,
    ) -> int:
        table_row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if table_row is None:
            return 0
        if source_file_id is None:
            query = f"SELECT COUNT(*) AS count FROM {table}"
            params: tuple[object, ...] = ()
        else:
            columns = {str(item[1]) for item in connection.execute(f"PRAGMA table_info({table})")}
            if "source_file_id" not in columns:
                return 0
            query = f"SELECT COUNT(*) AS count FROM {table} WHERE source_file_id = ?"
            params = (int(source_file_id),)
        row = connection.execute(query, params).fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _count(connection: sqlite3.Connection, table: str) -> int:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            return 0
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)


__all__ = ["MeshSourceIndexRepository"]
