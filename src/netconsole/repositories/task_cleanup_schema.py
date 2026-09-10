"""Read-only contract and explicit upgrade for Task Center cleanup storage.

The cleanup contract is deliberately separate from Operational GC.  Preview
may inspect a legacy database, but apply is allowed only after every required
table, column and index is present.  The only schema mutation exposed here is
an explicit, transactional upgrade of the cleanup tombstone table; cleanup
never creates it as a side effect of deleting task rows.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


TASK_CLEANUP_SCHEMA_CONTRACT: dict[str, Any] = {
    "contract_id": "task-cleanup-schema",
    "contract_version": 1,
    "task_schema_version": "5",
    "preview": {
        "tables": {
            "task_snapshots": [
                "task_id",
                "status",
                "created_time",
                "finished_time",
                "updated_time",
                "dismissed_at",
                "site_name",
                "result_path",
                "result_json",
                "result_id",
                "result_summary_json",
                "resource_keys_json",
                "error_message",
            ],
            "task_events": ["task_id", "payload_json"],
            "task_results": [
                "result_id",
                "task_id",
                "canonical_json",
                "sha256",
                "byte_size",
                "schema_version",
                "created_time",
                "content_sha256",
                "blob_codec",
                "blob_ready",
            ],
        },
        "indexes": {
            "idx_task_snapshots_visible_updated": {
                "table": "task_snapshots",
                "columns": ["dismissed_at", "updated_time"],
            },
            "idx_task_events_task_sequence": {
                "table": "task_events",
                "columns": ["task_id", "sequence"],
            },
            "idx_task_results_task_created": {
                "table": "task_results",
                "columns": ["task_id", "created_time", "result_id"],
            },
        },
    },
    "apply": {
        "tables": {
            "task_retention_tombstones": ["task_id", "retired_at", "reason"],
        },
        "indexes": {},
    },
}

_TOMBSTONE_COLUMN_DEFINITIONS = {
    "task_id": "TEXT",
    "retired_at": "TEXT NOT NULL DEFAULT ''",
    "reason": "TEXT NOT NULL DEFAULT 'legacy_schema_upgrade'",
}
_REQUIRED_PRIMARY_KEYS = {
    "task_snapshots": ["task_id"],
    "task_results": ["result_id"],
    "task_retention_tombstones": ["task_id"],
}


class TaskCleanupSchemaError(RuntimeError):
    """Raised when cleanup is attempted without its storage contract."""


@dataclass(frozen=True)
class TaskCleanupSchemaProfile:
    database: str
    schema_version: str
    user_version: int
    tables: dict[str, dict[str, Any]]
    indexes: dict[str, dict[str, Any]]
    preview_compatible: bool
    apply_compatible: bool

    @property
    def migration_required(self) -> bool:
        return not self.apply_compatible

    @property
    def cleanup_ready(self) -> bool:
        return self.apply_compatible

    @property
    def status(self) -> str:
        return "PASS" if self.apply_compatible else "SAFE_BUT_SCHEMA_BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": {
                "contract_id": TASK_CLEANUP_SCHEMA_CONTRACT["contract_id"],
                "contract_version": TASK_CLEANUP_SCHEMA_CONTRACT["contract_version"],
                "task_schema_version": TASK_CLEANUP_SCHEMA_CONTRACT[
                    "task_schema_version"
                ],
            },
            "database": self.database,
            "schema_version": self.schema_version,
            "user_version": self.user_version,
            "tables": self.tables,
            "indexes": self.indexes,
            "preview_compatible": self.preview_compatible,
            "apply_compatible": self.apply_compatible,
            "cleanup_ready": self.cleanup_ready,
            "migration_required": self.migration_required,
            "status": self.status,
        }


def _quoted(identifier: str) -> str:
    if not identifier or not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQLite identifier: {identifier}")
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _table_info(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    keys = ("cid", "name", "type", "notnull", "default", "pk")
    return [
        dict(zip(keys, tuple(row), strict=True))
        for row in connection.execute(f"PRAGMA table_info({_quoted(table)})").fetchall()
    ]


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in _table_info(connection, table)}


def _index_columns(connection: sqlite3.Connection, index: str) -> list[str]:
    return [
        str(row[2])
        for row in connection.execute(f"PRAGMA index_info({_quoted(index)})").fetchall()
        if row[2] is not None
    ]


def _index_rows(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for table in _table_names(connection):
        for row in connection.execute(f"PRAGMA index_list({_quoted(table)})").fetchall():
            name = str(row[1])
            result[name] = {
                "name": name,
                "table": table,
                "columns": _index_columns(connection, name),
                "unique": bool(row[2]),
                "origin": str(row[3]) if len(row) > 3 else "",
            }
    return result


def _profile_connection(
    connection: sqlite3.Connection,
    *,
    database: str,
) -> TaskCleanupSchemaProfile:
    tables_present = _table_names(connection)
    index_rows = _index_rows(connection)
    all_table_requirements: dict[str, tuple[str, ...]] = {}
    preview_tables = TASK_CLEANUP_SCHEMA_CONTRACT["preview"]["tables"]
    apply_tables = TASK_CLEANUP_SCHEMA_CONTRACT["apply"]["tables"]
    all_table_requirements.update(
        {str(table): tuple(columns) for table, columns in preview_tables.items()}
    )
    all_table_requirements.update(
        {str(table): tuple(columns) for table, columns in apply_tables.items()}
    )
    table_profiles: dict[str, dict[str, Any]] = {}
    for table, required_columns in all_table_requirements.items():
        present = table in tables_present
        actual_columns = sorted(_columns(connection, table)) if present else []
        missing = sorted(set(required_columns) - set(actual_columns))
        primary_key_columns = (
            [
                str(item["name"])
                for item in sorted(
                    _table_info(connection, table), key=lambda item: int(item["pk"] or 0)
                )
                if int(item["pk"] or 0)
            ]
            if present
            else []
        )
        required_primary_key = list(_REQUIRED_PRIMARY_KEYS.get(table, ()))
        table_profiles[table] = {
            "present": present,
            "columns": actual_columns,
            "required_columns": list(required_columns),
            "missing_columns": missing,
            "primary_key_columns": primary_key_columns,
            "required_primary_key": required_primary_key,
            "primary_key_matches": primary_key_columns == required_primary_key
            if required_primary_key
            else True,
            "required_for_preview": table in preview_tables,
            "required_for_apply": table in preview_tables or table in apply_tables,
            "status": "PASS"
            if present
            and not missing
            and (not required_primary_key or primary_key_columns == required_primary_key)
            else "MISSING",
        }
    index_profiles: dict[str, dict[str, Any]] = {}
    for index, requirement in TASK_CLEANUP_SCHEMA_CONTRACT["preview"]["indexes"].items():
        actual = index_rows.get(index)
        expected_columns = [str(item) for item in requirement["columns"]]
        index_profiles[index] = {
            "present": actual is not None,
            "table": str(requirement["table"]),
            "columns": list(actual["columns"]) if actual else [],
            "required_columns": expected_columns,
            "matches": bool(
                actual is not None
                and actual["table"] == requirement["table"]
                and actual["columns"] == expected_columns
            ),
            "required_for_preview": True,
            "required_for_apply": True,
            "status": "PASS"
            if actual is not None
            and actual["table"] == requirement["table"]
            and actual["columns"] == expected_columns
            else "MISSING_OR_MISMATCHED",
        }
    preview_ready = all(
        item["present"]
        and not item["missing_columns"]
        and bool(item["primary_key_matches"])
        for item in table_profiles.values()
        if item["required_for_preview"]
    ) and all(item["matches"] for item in index_profiles.values())
    apply_ready = preview_ready and all(
        item["present"]
        and not item["missing_columns"]
        and bool(item["primary_key_matches"])
        for item in table_profiles.values()
        if item["required_for_apply"] and not item["required_for_preview"]
    )
    schema_version = "unknown"
    if "task_schema_meta" in tables_present:
        row = connection.execute(
            "SELECT value FROM task_schema_meta WHERE key='schema_version' LIMIT 1"
        ).fetchone()
        if row is not None:
            schema_version = str(row[0] or "unknown")
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0] or 0)
    return TaskCleanupSchemaProfile(
        database=database,
        schema_version=schema_version,
        user_version=user_version,
        tables=table_profiles,
        indexes=index_profiles,
        preview_compatible=preview_ready,
        apply_compatible=apply_ready,
    )


def inspect_task_cleanup_schema(
    database: str | Path,
    *,
    immutable: bool = False,
) -> dict[str, Any]:
    """Inspect the cleanup contract without creating or changing the database."""

    path = Path(database).resolve()
    if not path.is_file() or path.is_symlink():
        return TaskCleanupSchemaProfile(
            database=str(path),
            schema_version="unknown",
            user_version=0,
            tables={},
            indexes={},
            preview_compatible=False,
            apply_compatible=False,
        ).as_dict()
    query = "mode=ro&immutable=1" if immutable else "mode=ro"
    uri = f"{path.as_uri()}?{query}"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.execute("PRAGMA query_only=ON")
        return _profile_connection(connection, database=str(path)).as_dict()


def inspect_task_cleanup_schema_connection(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    """Inspect a connection already protected by the caller's transaction."""

    return _profile_connection(connection, database="<active-connection>").as_dict()


def _assert_profile_ready(profile: TaskCleanupSchemaProfile, *, apply: bool) -> None:
    ready = profile.apply_compatible if apply else profile.preview_compatible
    if ready:
        return
    stage = "apply" if apply else "preview"
    raise TaskCleanupSchemaError(
        f"TASK_SCHEMA_COMPATIBILITY {stage} blocked: "
        f"schema_version={profile.schema_version} database={profile.database}"
    )


def upgrade_task_cleanup_schema(
    database: str | Path,
    *,
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Explicitly upgrade cleanup schema in one transaction.

    The operation only repairs the tombstone table and the cleanup indexes.
    It never deletes task rows.  SQLite transactional DDL plus ``BEGIN
    IMMEDIATE`` makes failure restart-safe: a failed upgrade leaves the
    original schema untouched and a repeated successful upgrade is a no-op.
    """

    path = Path(database).resolve()
    if not path.is_file() or path.is_symlink():
        raise TaskCleanupSchemaError(f"tasks database is not a regular file: {path}")
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        before = _profile_connection(connection, database=str(path))
        _assert_profile_ready(before, apply=False)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_retention_tombstones (
                task_id TEXT PRIMARY KEY,
                retired_at TEXT NOT NULL,
                reason TEXT NOT NULL
            )
            """
        )
        if fault_injector:
            fault_injector("after_tombstone_table")
        existing = _columns(connection, "task_retention_tombstones")
        for column, definition in _TOMBSTONE_COLUMN_DEFINITIONS.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE task_retention_tombstones ADD COLUMN {_quoted(column)} {definition}"
                )
        for index, requirement in TASK_CLEANUP_SCHEMA_CONTRACT["preview"]["indexes"].items():
            columns = ", ".join(_quoted(str(column)) for column in requirement["columns"])
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {_quoted(index)} "
                f"ON {_quoted(str(requirement['table']))} ({columns})"
            )
        if fault_injector:
            fault_injector("before_commit")
        after = _profile_connection(connection, database=str(path))
        _assert_profile_ready(after, apply=True)
        connection.commit()
        return after.as_dict()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


__all__ = [
    "TASK_CLEANUP_SCHEMA_CONTRACT",
    "TaskCleanupSchemaError",
    "TaskCleanupSchemaProfile",
    "inspect_task_cleanup_schema",
    "inspect_task_cleanup_schema_connection",
    "upgrade_task_cleanup_schema",
]
