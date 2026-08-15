"""Durable COPY-only journal for legacy device history migration."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netconsole.core.sqlite_utils import connect_sqlite


MIGRATION_STATUSES = frozenset({"PENDING", "COPYING", "VERIFYING", "VERIFIED", "FAILED"})
AUTHORITY_STATES = frozenset(
    {
        "LEGACY_AUTHORITY",
        "SHARD_VERIFIED",
        "SHARD_AUTHORITY",
        "SOURCE_DELETE_ELIGIBLE",
        "SOURCE_DELETED",
    }
)
SHARD_QUERY_AUTHORITY_STATES = frozenset(
    {"SHARD_AUTHORITY", "SOURCE_DELETE_ELIGIBLE", "SOURCE_DELETED"}
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS legacy_history_migrations (
    migration_id TEXT PRIMARY KEY,
    source_database_identity TEXT NOT NULL,
    source_schema_version TEXT NOT NULL,
    site_id TEXT NOT NULL,
    requested_state TEXT NOT NULL DEFAULT 'PAUSED',
    status TEXT NOT NULL,
    chunk_rows INTEGER NOT NULL,
    copied_count INTEGER NOT NULL DEFAULT 0,
    verified_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    target_commits INTEGER NOT NULL DEFAULT 0,
    checkpoint_commits INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS legacy_history_migration_tables (
    migration_id TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_range TEXT NOT NULL,
    last_source_key INTEGER NOT NULL DEFAULT 0,
    copied_count INTEGER NOT NULL DEFAULT 0,
    verified_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    authority_state TEXT NOT NULL DEFAULT 'LEGACY_AUTHORITY',
    cutover_at TEXT NOT NULL DEFAULT '',
    cutover_revision INTEGER NOT NULL DEFAULT 0,
    authority_reason TEXT NOT NULL DEFAULT '',
    rollback_at TEXT NOT NULL DEFAULT '',
    rollback_reason TEXT NOT NULL DEFAULT '',
    delete_eligible_at TEXT NOT NULL DEFAULT '',
    delete_plan_digest TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(migration_id, source_table),
    FOREIGN KEY(migration_id) REFERENCES legacy_history_migrations(migration_id)
);
CREATE TABLE IF NOT EXISTS legacy_history_migration_ranges (
    migration_id TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_start_key INTEGER NOT NULL,
    source_end_key INTEGER NOT NULL,
    target_month TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    copied_count INTEGER NOT NULL,
    verified_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    source_digest TEXT NOT NULL,
    target_digest TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    budget_exceeded INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(migration_id, source_table, source_start_key, source_end_key, target_month),
    FOREIGN KEY(migration_id, source_table)
        REFERENCES legacy_history_migration_tables(migration_id, source_table)
);
CREATE INDEX IF NOT EXISTS idx_legacy_history_ranges_status
    ON legacy_history_migration_ranges(migration_id, status, source_table, source_start_key);
CREATE TABLE IF NOT EXISTS legacy_history_authority_transitions (
    migration_id TEXT NOT NULL,
    source_table TEXT NOT NULL,
    revision INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    transitioned_at TEXT NOT NULL,
    PRIMARY KEY(migration_id, source_table, revision),
    FOREIGN KEY(migration_id, source_table)
        REFERENCES legacy_history_migration_tables(migration_id, source_table)
);
"""


@dataclass(frozen=True)
class MigrationRecord:
    migration_id: str
    source_database_identity: str
    source_schema_version: str
    site_id: str
    requested_state: str
    status: str
    chunk_rows: int
    copied_count: int = 0
    verified_count: int = 0
    duplicate_count: int = 0
    error_count: int = 0
    target_commits: int = 0
    checkpoint_commits: int = 0
    started_at: str = ""
    updated_at: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class TableCheckpoint:
    migration_id: str
    source_table: str
    source_range: str
    last_source_key: int
    copied_count: int
    verified_count: int
    duplicate_count: int
    error_count: int
    status: str
    updated_at: str
    last_error: str = ""
    authority_state: str = "LEGACY_AUTHORITY"
    cutover_at: str = ""
    cutover_revision: int = 0
    authority_reason: str = ""
    rollback_at: str = ""
    rollback_reason: str = ""
    delete_eligible_at: str = ""
    delete_plan_digest: str = ""


class HistoryLegacyMigrationRepository:
    """Owns only migration metadata in the existing history catalog."""

    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = Path(catalog_path)

    def ensure_schema(self) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.executescript(_SCHEMA)
            columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(legacy_history_migration_tables)"
                )
            }
            for name, definition in {
                "authority_state": "TEXT NOT NULL DEFAULT 'LEGACY_AUTHORITY'",
                "cutover_at": "TEXT NOT NULL DEFAULT ''",
                "cutover_revision": "INTEGER NOT NULL DEFAULT 0",
                "authority_reason": "TEXT NOT NULL DEFAULT ''",
                "rollback_at": "TEXT NOT NULL DEFAULT ''",
                "rollback_reason": "TEXT NOT NULL DEFAULT ''",
                "delete_eligible_at": "TEXT NOT NULL DEFAULT ''",
                "delete_plan_digest": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE legacy_history_migration_tables "
                        f"ADD COLUMN {name} {definition}"
                    )
            conn.commit()

    def create_or_load(
        self,
        *,
        migration_id: str,
        source_database_identity: str,
        source_schema_version: str,
        site_id: str,
        chunk_rows: int,
        now: str,
    ) -> MigrationRecord:
        self.ensure_schema()
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO legacy_history_migrations
                    (migration_id, source_database_identity, source_schema_version, site_id,
                     requested_state, status, chunk_rows, started_at, updated_at)
                VALUES (?, ?, ?, ?, 'PAUSED', 'PENDING', ?, ?, ?)
                """,
                (
                    migration_id,
                    source_database_identity,
                    source_schema_version,
                    site_id,
                    chunk_rows,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM legacy_history_migrations WHERE migration_id=?",
                (migration_id,),
            ).fetchone()
            conn.commit()
        assert row is not None
        record = self._migration(dict(row))
        if record.source_database_identity != source_database_identity:
            raise ValueError("migration checkpoint belongs to a different source database")
        if record.site_id != site_id or record.source_schema_version != source_schema_version:
            raise ValueError("migration checkpoint source metadata does not match")
        return record

    def get(self, migration_id: str) -> MigrationRecord | None:
        if not self.catalog_path.is_file():
            return None
        try:
            with closing(self._connect_readonly()) as conn:
                if not self._table_exists(conn, "legacy_history_migrations"):
                    return None
                row = conn.execute(
                    "SELECT * FROM legacy_history_migrations WHERE migration_id=?",
                    (migration_id,),
                ).fetchone()
        except (OSError, sqlite3.Error):
            return None
        return self._migration(dict(row)) if row is not None else None

    def list_table_checkpoints(self, migration_id: str) -> list[TableCheckpoint]:
        if not self.catalog_path.is_file():
            return []
        try:
            with closing(self._connect_readonly()) as conn:
                if not self._table_exists(conn, "legacy_history_migration_tables"):
                    return []
                rows = conn.execute(
                    "SELECT * FROM legacy_history_migration_tables "
                    "WHERE migration_id=? ORDER BY source_table",
                    (migration_id,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return []
        return [self._table_checkpoint(dict(row)) for row in rows]

    def table_checkpoint(self, migration_id: str, source_table: str) -> TableCheckpoint | None:
        for checkpoint in self.list_table_checkpoints(migration_id):
            if checkpoint.source_table == source_table:
                return checkpoint
        return None

    def set_requested_state(self, migration_id: str, requested_state: str, *, now: str) -> None:
        state = str(requested_state).upper()
        if state not in {"RUNNING", "PAUSED"}:
            raise ValueError(f"invalid requested migration state: {requested_state}")
        self.ensure_schema()
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            cursor = conn.execute(
                "UPDATE legacy_history_migrations SET requested_state=?, updated_at=? "
                "WHERE migration_id=?",
                (state, now, migration_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown migration: {migration_id}")
            conn.commit()

    def upsert_table_checkpoint(self, checkpoint: TableCheckpoint) -> None:
        self._validate_status(checkpoint.status)
        self._validate_authority_state(checkpoint.authority_state)
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.execute(
                """
                INSERT INTO legacy_history_migration_tables
                    (migration_id, source_table, source_range, last_source_key,
                     copied_count, verified_count, duplicate_count, error_count,
                     status, updated_at, last_error, authority_state, cutover_at,
                     cutover_revision, authority_reason, rollback_at,
                     rollback_reason, delete_eligible_at, delete_plan_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(migration_id, source_table) DO UPDATE SET
                    source_range=excluded.source_range,
                    last_source_key=excluded.last_source_key,
                    copied_count=excluded.copied_count,
                    verified_count=excluded.verified_count,
                    duplicate_count=excluded.duplicate_count,
                    error_count=excluded.error_count,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    last_error=excluded.last_error
                """,
                (
                    checkpoint.migration_id,
                    checkpoint.source_table,
                    checkpoint.source_range,
                    checkpoint.last_source_key,
                    checkpoint.copied_count,
                    checkpoint.verified_count,
                    checkpoint.duplicate_count,
                    checkpoint.error_count,
                    checkpoint.status,
                    checkpoint.updated_at,
                    checkpoint.last_error,
                    checkpoint.authority_state,
                    checkpoint.cutover_at,
                    checkpoint.cutover_revision,
                    checkpoint.authority_reason,
                    checkpoint.rollback_at,
                    checkpoint.rollback_reason,
                    checkpoint.delete_eligible_at,
                    checkpoint.delete_plan_digest,
                ),
            )
            conn.commit()

    def transition_authority(
        self,
        migration_id: str,
        source_table: str,
        *,
        to_state: str,
        expected_revision: int,
        reason: str,
        now: str,
    ) -> TableCheckpoint:
        target = str(to_state or "").upper()
        self._validate_authority_state(target)
        explanation = str(reason or "").strip()
        if not explanation:
            raise ValueError("authority transition reason is required")
        allowed = {
            "LEGACY_AUTHORITY": {"SHARD_VERIFIED"},
            "SHARD_VERIFIED": {"SHARD_AUTHORITY", "LEGACY_AUTHORITY"},
            "SHARD_AUTHORITY": {"SOURCE_DELETE_ELIGIBLE", "LEGACY_AUTHORITY"},
            "SOURCE_DELETE_ELIGIBLE": {"LEGACY_AUTHORITY", "SOURCE_DELETED"},
            "SOURCE_DELETED": set(),
        }
        self.ensure_schema()
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM legacy_history_migration_tables "
                "WHERE migration_id=? AND source_table=?",
                (migration_id, source_table),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError(f"unknown migration source table: {source_table}")
            current = self._table_checkpoint(dict(row))
            if current.cutover_revision != int(expected_revision):
                conn.rollback()
                raise ValueError("cutover revision mismatch")
            if target not in allowed[current.authority_state]:
                conn.rollback()
                raise ValueError(
                    f"invalid authority transition: {current.authority_state} -> {target}"
                )
            if target == "SHARD_VERIFIED" and (
                current.status != "VERIFIED" or current.error_count != 0
            ):
                conn.rollback()
                raise ValueError("source table copy verification is incomplete")
            revision = current.cutover_revision + 1
            rollback = target == "LEGACY_AUTHORITY"
            conn.execute(
                """
                UPDATE legacy_history_migration_tables
                SET authority_state=?, cutover_revision=?, authority_reason=?,
                    cutover_at=CASE WHEN ?='SHARD_AUTHORITY' THEN ? ELSE cutover_at END,
                    rollback_at=CASE WHEN ? THEN ? ELSE rollback_at END,
                    rollback_reason=CASE WHEN ? THEN ? ELSE rollback_reason END,
                    delete_eligible_at=CASE WHEN ?='SOURCE_DELETE_ELIGIBLE' THEN ? ELSE '' END,
                    delete_plan_digest='', updated_at=?
                WHERE migration_id=? AND source_table=?
                """,
                (
                    target,
                    revision,
                    explanation,
                    target,
                    now,
                    int(rollback),
                    now,
                    int(rollback),
                    explanation,
                    target,
                    now,
                    now,
                    migration_id,
                    source_table,
                ),
            )
            conn.execute(
                """
                INSERT INTO legacy_history_authority_transitions
                    (migration_id, source_table, revision, from_state, to_state,
                     reason, transitioned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    migration_id,
                    source_table,
                    revision,
                    current.authority_state,
                    target,
                    explanation,
                    now,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM legacy_history_migration_tables "
                "WHERE migration_id=? AND source_table=?",
                (migration_id, source_table),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return self._table_checkpoint(dict(updated))

    def set_delete_plan_digest(
        self,
        migration_id: str,
        source_table: str,
        *,
        expected_revision: int,
        digest: str,
        now: str,
    ) -> TableCheckpoint:
        value = str(digest or "").strip().lower()
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("invalid delete plan digest")
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE legacy_history_migration_tables
                SET delete_plan_digest=?, updated_at=?
                WHERE migration_id=? AND source_table=?
                  AND authority_state='SOURCE_DELETE_ELIGIBLE'
                  AND cutover_revision=?
                """,
                (value, now, migration_id, source_table, int(expected_revision)),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                raise ValueError("delete plan authority or revision is stale")
            row = conn.execute(
                "SELECT * FROM legacy_history_migration_tables "
                "WHERE migration_id=? AND source_table=?",
                (migration_id, source_table),
            ).fetchone()
            conn.commit()
        assert row is not None
        return self._table_checkpoint(dict(row))

    def authority_transitions(
        self, migration_id: str, source_table: str
    ) -> list[dict[str, Any]]:
        if not self.catalog_path.is_file():
            return []
        with closing(self._connect_readonly()) as conn:
            if not self._table_exists(conn, "legacy_history_authority_transitions"):
                return []
            rows = conn.execute(
                "SELECT * FROM legacy_history_authority_transitions "
                "WHERE migration_id=? AND source_table=? ORDER BY revision",
                (migration_id, source_table),
            ).fetchall()
        return [dict(row) for row in rows]

    def effective_authority_state(self, source_table: str) -> str:
        if not self.catalog_path.is_file():
            return "LEGACY_AUTHORITY"
        try:
            with closing(self._connect_readonly()) as conn:
                if not self._table_exists(conn, "legacy_history_migration_tables"):
                    return "LEGACY_AUTHORITY"
                rows = conn.execute(
                    """
                    SELECT authority_state
                    FROM legacy_history_migration_tables
                    WHERE source_table=?
                    ORDER BY cutover_revision DESC, updated_at DESC, migration_id DESC
                    """,
                    (source_table,),
                ).fetchall()
        except (OSError, sqlite3.Error):
            return "LEGACY_AUTHORITY"
        states = [str(row[0] or "LEGACY_AUTHORITY") for row in rows]
        authoritative = [
            state for state in states if state in SHARD_QUERY_AUTHORITY_STATES
        ]
        return authoritative[0] if len(authoritative) == 1 else "LEGACY_AUTHORITY"

    def record_range(self, values: dict[str, Any]) -> None:
        self._validate_status(str(values["status"]))
        columns = (
            "migration_id", "source_table", "source_start_key", "source_end_key",
            "target_month", "source_count", "copied_count", "verified_count",
            "duplicate_count", "error_count", "source_digest", "target_digest",
            "sample_count", "elapsed_ms", "budget_exceeded", "status",
            "started_at", "updated_at", "last_error",
        )
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO legacy_history_migration_ranges "
                f"({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(values.get(column, "") for column in columns),
            )
            conn.commit()

    def update_migration(
        self,
        migration_id: str,
        *,
        status: str,
        requested_state: str | None,
        totals: dict[str, int],
        now: str,
        last_error: str = "",
        target_commits: int | None = None,
        checkpoint_commits: int | None = None,
    ) -> MigrationRecord:
        self._validate_status(status)
        assignments = [
            "status=?", "copied_count=?", "verified_count=?", "duplicate_count=?",
            "error_count=?", "updated_at=?", "last_error=?",
        ]
        params: list[Any] = [
            status,
            totals.get("copied_count", 0),
            totals.get("verified_count", 0),
            totals.get("duplicate_count", 0),
            totals.get("error_count", 0),
            now,
            str(last_error)[:2000],
        ]
        if requested_state is not None:
            assignments.append("requested_state=?")
            params.append(requested_state)
        if target_commits is not None:
            assignments.append("target_commits=?")
            params.append(target_commits)
        if checkpoint_commits is not None:
            assignments.append("checkpoint_commits=?")
            params.append(checkpoint_commits)
        params.append(migration_id)
        with closing(connect_sqlite(self.catalog_path, foreign_keys=True)) as conn:
            conn.execute(
                "UPDATE legacy_history_migrations SET " + ", ".join(assignments) + " WHERE migration_id=?",
                params,
            )
            row = conn.execute(
                "SELECT * FROM legacy_history_migrations WHERE migration_id=?",
                (migration_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise ValueError(f"unknown migration: {migration_id}")
        return self._migration(dict(row))

    def range_records(self, migration_id: str) -> list[dict[str, Any]]:
        if not self.catalog_path.is_file():
            return []
        with closing(self._connect_readonly()) as conn:
            if not self._table_exists(conn, "legacy_history_migration_ranges"):
                return []
            rows = conn.execute(
                "SELECT * FROM legacy_history_migration_ranges WHERE migration_id=? "
                "ORDER BY source_table, source_start_key, target_month",
                (migration_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect_readonly(self) -> sqlite3.Connection:
        uri = f"{self.catalog_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in MIGRATION_STATUSES:
            raise ValueError(f"invalid migration status: {status}")

    @staticmethod
    def _validate_authority_state(state: str) -> None:
        if state not in AUTHORITY_STATES:
            raise ValueError(f"invalid history authority state: {state}")

    @staticmethod
    def _migration(row: dict[str, Any]) -> MigrationRecord:
        return MigrationRecord(**{field: row[field] for field in MigrationRecord.__dataclass_fields__})

    @staticmethod
    def _table_checkpoint(row: dict[str, Any]) -> TableCheckpoint:
        return TableCheckpoint(**{field: row[field] for field in TableCheckpoint.__dataclass_fields__})


class LegacyHistorySourceRepository:
    """Read-only access to one resolved legacy devices database."""

    def __init__(self, database_path: Path, *, immutable: bool = False) -> None:
        self.database_path = Path(database_path)
        self.immutable = bool(immutable)

    def history_tables(self) -> list[str]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' "
                "AND name LIKE '%_history' ORDER BY name"
            ).fetchall()
        return [str(row[0]) for row in rows if self._safe_identifier(str(row[0]))]

    def table_columns(self, table: str) -> list[dict[str, Any]]:
        name = self._validated_table(table)
        with closing(self.connect()) as conn:
            rows = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        keys = ("cid", "name", "type", "notnull", "default", "pk")
        return [dict(zip(keys, tuple(row), strict=True)) for row in rows]

    def table_indexes(self, table: str) -> list[dict[str, Any]]:
        name = self._validated_table(table)
        with closing(self.connect()) as conn:
            rows = conn.execute(f'PRAGMA index_list("{name}")').fetchall()
        keys = ("seq", "name", "unique", "origin", "partial")
        return [dict(zip(keys, tuple(row), strict=True)) for row in rows]

    def table_profile(self, table: str, timestamp_column: str) -> dict[str, Any]:
        name = self._validated_table(table)
        timestamp = self._validated_column(timestamp_column)
        with closing(self.connect()) as conn:
            row = conn.execute(
                f'SELECT COUNT(*) AS rows, MIN("{timestamp}") AS min_time, '
                f'MAX("{timestamp}") AS max_time, MIN(id) AS min_id, MAX(id) AS max_id '
                f'FROM "{name}"'
            ).fetchone()
        return dict(row) if row is not None else {}

    def id_range(self, table: str) -> tuple[int, int]:
        name = self._validated_table(table)
        with closing(self.connect()) as conn:
            row = conn.execute(
                f'SELECT COALESCE(MIN(id), 0), COALESCE(MAX(id), 0) FROM "{name}"'
            ).fetchone()
        return (int(row[0]), int(row[1])) if row is not None else (0, 0)

    def fetch_after(self, table: str, last_source_key: int, limit: int) -> list[dict[str, Any]]:
        name = self._validated_table(table)
        with closing(self.connect()) as conn:
            rows = conn.execute(
                f'SELECT * FROM "{name}" WHERE id > ? ORDER BY id ASC LIMIT ?',
                (max(0, int(last_source_key)), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_range(
        self, table: str, source_start_key: int, source_end_key: int
    ) -> list[dict[str, Any]]:
        name = self._validated_table(table)
        start = int(source_start_key)
        end = int(source_end_key)
        if start > end:
            raise ValueError("invalid source key range")
        with closing(self.connect()) as conn:
            rows = conn.execute(
                f'SELECT * FROM "{name}" WHERE id BETWEEN ? AND ? ORDER BY id ASC',
                (start, end),
            ).fetchall()
        return [dict(row) for row in rows]

    def anchor_rows(self, table: str) -> list[dict[str, Any]]:
        name = self._validated_table(table)
        with closing(self.connect()) as conn:
            rows = conn.execute(
                f'SELECT * FROM "{name}" WHERE id IN '
                f'(SELECT MIN(id) FROM "{name}" UNION SELECT MAX(id) FROM "{name}") '
                "ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def projection_matches(
        self,
        projection_table: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any] | None]:
        """Resolve retired AP projection rows to authoritative legacy rows."""

        if projection_table == "ap_lldp_history":
            canonical_table = "ac_fit_ap_lldp_history"
            fields = ("ap_uuid", "collected_at", "ap_mac", "ap_name", "neighbor_interface")
        elif projection_table == "ap_optical_history":
            canonical_table = "ac_fit_ap_optical_history"
            fields = ("ap_uuid", "collected_at", "interface_name", "rx_power", "tx_power")
        else:
            raise ValueError(f"not a supported projection table: {projection_table}")
        self._validated_table(canonical_table)
        if not rows:
            return []
        ap_values = sorted({str(row.get("ap_uuid") or "") for row in rows})
        placeholders = ", ".join("?" for _ in ap_values)
        timestamps = [str(row.get("collected_at") or "") for row in rows]
        minimum_time, maximum_time = min(timestamps), max(timestamps)
        with closing(self.connect()) as conn:
            candidates = conn.execute(
                f'SELECT * FROM "{canonical_table}" WHERE ap_uuid IN ({placeholders}) '
                "AND collected_at BETWEEN ? AND ? ORDER BY id",
                [*ap_values, minimum_time, maximum_time],
            ).fetchall()

        def key(row: dict[str, Any]) -> tuple[str, ...]:
            return tuple(str(row.get(field) or "").strip().casefold() for field in fields)

        matched: dict[tuple[str, ...], dict[str, Any]] = {}
        for candidate in candidates:
            value = dict(candidate)
            matched.setdefault(key(value), value)
        return [matched.get(key(row)) for row in rows]

    def schema_version(self) -> str:
        with closing(self.connect()) as conn:
            if not self._table_exists(conn, "schema_metadata"):
                return str(conn.execute("PRAGMA user_version").fetchone()[0])
            row = conn.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()
            return str(row[0] if row is not None else conn.execute("PRAGMA user_version").fetchone()[0])

    def physical_profile(self) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
            freelist_count = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
        return {
            "database_size": self.database_path.stat().st_size,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "journal_mode": journal_mode,
            "wal_size": self._sidecar_size("-wal"),
            "shm_size": self._sidecar_size("-shm"),
        }

    def connect(self) -> sqlite3.Connection:
        query = "mode=ro&immutable=1" if self.immutable else "mode=ro"
        uri = f"{self.database_path.resolve().as_uri()}?{query}"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _validated_table(self, table: str) -> str:
        name = str(table or "")
        if not self._safe_identifier(name) or name not in self.history_tables():
            raise ValueError(f"unknown legacy history table: {name}")
        return name

    @staticmethod
    def _validated_column(column: str) -> str:
        value = str(column or "")
        if not LegacyHistorySourceRepository._safe_identifier(value):
            raise ValueError(f"invalid column: {value}")
        return value

    @staticmethod
    def _safe_identifier(value: str) -> bool:
        return bool(value) and value.replace("_", "").isalnum() and value[0].isalpha()

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    def _sidecar_size(self, suffix: str) -> int:
        path = self.database_path.with_name(self.database_path.name + suffix)
        return path.stat().st_size if path.is_file() else 0


__all__ = [
    "AUTHORITY_STATES",
    "HistoryLegacyMigrationRepository",
    "LegacyHistorySourceRepository",
    "MIGRATION_STATUSES",
    "MigrationRecord",
    "SHARD_QUERY_AUTHORITY_STATES",
    "TableCheckpoint",
]
