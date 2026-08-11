from __future__ import annotations

import sqlite3
from collections.abc import Iterable


CATALOG_SCHEMA_VERSION = "mesh_catalog_v3_source_lifecycle"

_KNOWN_VERSIONS = (
    "mesh_catalog_v1_device_uuid",
    "mesh_catalog_v2_issue_severity",
    CATALOG_SCHEMA_VERSION,
)

_LATEST_SCHEMA_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """
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
    )
    """,
    """
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
        info_count INTEGER NOT NULL DEFAULT 0,
        warning_count INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        actionable_warning_count INTEGER NOT NULL DEFAULT 0,
        report_count INTEGER NOT NULL DEFAULT 0,
        source_revision TEXT NOT NULL DEFAULT '',
        detail_indexed INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(mr_id, source_file_id),
        FOREIGN KEY(mr_id) REFERENCES mr_profiles(mr_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mesh_session_index_analysis_time ON mesh_session_index(analysis_time DESC, session_id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_mesh_session_index_mr ON mesh_session_index(mr_id, source_file_id)",
    """
    CREATE TABLE IF NOT EXISTS mesh_source_fingerprints (
        content_sha256 TEXT NOT NULL,
        raw_sha256 TEXT NOT NULL DEFAULT '',
        mr_id TEXT NOT NULL,
        source_file_id INTEGER NOT NULL,
        stored_filename TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY(content_sha256, mr_id, source_file_id),
        FOREIGN KEY(mr_id) REFERENCES mr_profiles(mr_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mesh_source_fingerprints_raw ON mesh_source_fingerprints(raw_sha256)",
    """
    CREATE TABLE IF NOT EXISTS mesh_catalog_index_state (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        status TEXT NOT NULL DEFAULT 'pending',
        discovered_session_count INTEGER NOT NULL DEFAULT 0,
        indexed_session_count INTEGER NOT NULL DEFAULT 0,
        detail_indexed_session_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mesh_source_lifecycle (
        session_id TEXT PRIMARY KEY,
        mr_id TEXT NOT NULL,
        source_file_id INTEGER NOT NULL,
        health_status TEXT NOT NULL,
        reason_code TEXT NOT NULL DEFAULT '',
        details_json TEXT NOT NULL DEFAULT '{}',
        checked_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mesh_source_lifecycle_health ON mesh_source_lifecycle(health_status, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS mesh_source_lifecycle_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        mr_id TEXT NOT NULL,
        source_file_id INTEGER NOT NULL,
        previous_status TEXT NOT NULL DEFAULT '',
        health_status TEXT NOT NULL,
        reason_code TEXT NOT NULL DEFAULT '',
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mesh_source_lifecycle_events_session ON mesh_source_lifecycle_events(session_id, event_id DESC)",
)

_REQUIRED_COLUMNS = {
    "mr_profiles": {"mr_id", "safe_folder_name", "linked_device_uuid"},
    "mesh_session_index": {
        "session_id",
        "mr_id",
        "source_file_id",
        "info_count",
        "warning_count",
        "error_count",
        "actionable_warning_count",
    },
    "mesh_source_fingerprints": {"content_sha256", "mr_id", "source_file_id"},
    "mesh_catalog_index_state": {"singleton", "status", "updated_at"},
    "mesh_source_lifecycle": {
        "session_id",
        "health_status",
        "reason_code",
        "details_json",
    },
    "mesh_source_lifecycle_events": {
        "event_id",
        "session_id",
        "health_status",
    },
}


class MeshCatalogSchemaError(RuntimeError):
    pass


def migrate_mesh_catalog(connection: sqlite3.Connection, *, now: str) -> None:
    """Create or upgrade the catalog under one SQLite cross-process write lock."""

    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in _LATEST_SCHEMA_STATEMENTS:
            connection.execute(statement)
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        current = str(row[0]) if row and row[0] not in (None, "") else ""
        if current and current not in _KNOWN_VERSIONS:
            raise MeshCatalogSchemaError(f"不支持的 MESH catalog schema_version：{current}")

        start = _KNOWN_VERSIONS.index(current) + 1 if current else 0
        for version in _KNOWN_VERSIONS[start:]:
            _apply_migration(connection, version)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (version,),
            )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_mesh_session_index_warning "
            "ON mesh_session_index(warning_count, analysis_time DESC)"
        )

        connection.execute(
            """
            INSERT OR IGNORE INTO mesh_catalog_index_state (
                singleton, status, updated_at
            ) VALUES (1, 'pending', ?)
            """,
            (now,),
        )
        _validate_schema(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _apply_migration(connection: sqlite3.Connection, version: str) -> None:
    if version == "mesh_catalog_v1_device_uuid":
        columns = _table_columns(connection, "mr_profiles")
        if "linked_device_uuid" not in columns:
            connection.execute(
                "ALTER TABLE mr_profiles ADD COLUMN linked_device_uuid TEXT NULL"
            )
        return
    if version == "mesh_catalog_v2_issue_severity":
        columns = _table_columns(connection, "mesh_session_index")
        migrated = False
        for column in (
            "info_count",
            "warning_count",
            "error_count",
            "actionable_warning_count",
        ):
            if column in columns:
                continue
            connection.execute(
                f"ALTER TABLE mesh_session_index ADD COLUMN {column} "
                "INTEGER NOT NULL DEFAULT 0"
            )
            columns.add(column)
            migrated = True
        if migrated:
            connection.execute(
                "UPDATE mesh_session_index SET actionable_warning_count = warning_count "
                "WHERE actionable_warning_count = 0 AND warning_count > 0"
            )
            connection.execute(
                "UPDATE mesh_catalog_index_state SET status = 'pending' WHERE singleton = 1"
            )
        return
    if version == CATALOG_SCHEMA_VERSION:
        return
    raise MeshCatalogSchemaError(f"未实现的 MESH catalog migration：{version}")


def _validate_schema(connection: sqlite3.Connection) -> None:
    for table, required in _REQUIRED_COLUMNS.items():
        columns = _table_columns(connection, table)
        missing = sorted(required - columns)
        if missing:
            raise MeshCatalogSchemaError(
                f"MESH catalog 表 {table} 缺少字段：{', '.join(missing)}"
            )
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None or str(row[0]) != CATALOG_SCHEMA_VERSION:
        raise MeshCatalogSchemaError("MESH catalog schema_version 未完成持久化")


def _table_columns(
    connection: sqlite3.Connection,
    table: str,
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def required_catalog_columns() -> Iterable[tuple[str, frozenset[str]]]:
    return tuple((table, frozenset(columns)) for table, columns in _REQUIRED_COLUMNS.items())


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "MeshCatalogSchemaError",
    "migrate_mesh_catalog",
    "required_catalog_columns",
]
