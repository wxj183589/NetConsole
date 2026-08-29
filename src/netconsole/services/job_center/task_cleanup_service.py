from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from netconsole.core.paths import PathResolver
from netconsole.models.task_history_policy import (
    ACTIVE_TASK_STATE_VALUES,
    TASK_HISTORY_SCOPE_LIMIT,
    TERMINAL_TASK_STATE_VALUES,
    task_history_scope,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.repositories.task_result_blob_repository import (
    TaskResultBlobError,
)


_GROUND_REFERENCE_COLUMNS = frozenset({"task_id", "controller_task_id"})
_REFERENCE_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_ref",
        "artifact_path",
        "download_ref",
        "output_path",
        "package_path",
        "report_path",
        "result_path",
        "path",
        "online_mr_session_id",
        "online_mr_session_ids",
        "ground_session_id",
        "ground_session_ids",
        "ground_unattended_session_id",
        "ground_unattended_session_ids",
        "ground_run_id",
        "ground_operation_id",
        "mesh_session_id",
        "mesh_session_ids",
        "mesh_source_id",
        "mesh_source_ids",
    }
)


@dataclass(frozen=True)
class CleanupDecision:
    task_id: str
    can_cleanup: bool
    status: str = ""
    reasons: tuple[str, ...] = ()
    protected_resources: tuple[str, ...] = ()
    event_rows: int = 0
    snapshot_rows: int = 0
    result_rows: int = 0
    result_bytes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "can_cleanup": self.can_cleanup,
            "status": self.status,
            "reasons": list(self.reasons),
            "protected_resources": list(self.protected_resources),
            "event_rows": self.event_rows,
            "snapshot_rows": self.snapshot_rows,
            "result_rows": self.result_rows,
            "result_bytes": self.result_bytes,
        }


class TaskCleanupService:
    """Own explicit Task Center cleanup without deleting business authorities.

    The service is deliberately conservative.  It only removes the three
    task-owned current tables after a terminal task has no active mapping,
    durable artifact/session reference, or unrecognised resource key.  Sealed
    history, Ground data, Online MR data, and files are outside this service's
    deletion boundary.
    """

    def __init__(
        self,
        repository: TaskRepository,
        *,
        paths: PathResolver | None = None,
        site_name: str = "",
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.site_name = str(site_name or "")

    def can_cleanup(self, task_id: str) -> dict[str, object]:
        with self.repository._connect() as conn:
            decision = self._decision(conn, str(task_id or ""))
        return decision.to_dict()

    def preview_cleanup(self, task_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, object]:
        ids = self._normalize_ids(task_ids)
        with self.repository._connect() as conn:
            decisions = [self._decision(conn, task_id) for task_id in ids]
        return self._preview_payload(ids, decisions)

    def cleanup_tasks(
        self,
        task_ids: list[str] | tuple[str, ...] | set[str],
    ) -> dict[str, object]:
        ids = self._normalize_ids(task_ids)
        decisions: list[CleanupDecision] = []
        deleted_ids: list[str] = []
        deleted = {"task_events": 0, "task_snapshots": 0, "task_results": 0}
        orphan_blobs_removed = 0
        orphan_blob_bytes_removed = 0
        quick_check = "not_run"

        with self.repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            decisions = [self._decision(conn, task_id) for task_id in ids]
            eligible = [item.task_id for item in decisions if item.can_cleanup]
            if eligible:
                for start in range(0, len(eligible), 500):
                    chunk = eligible[start : start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    if self._table_exists(conn, "task_events"):
                        cursor = conn.execute(
                            f"DELETE FROM task_events WHERE task_id IN ({placeholders})",
                            chunk,
                        )
                        deleted["task_events"] += max(0, int(cursor.rowcount))
                    if self._table_exists(conn, "task_results"):
                        cursor = conn.execute(
                            f"DELETE FROM task_results WHERE task_id IN ({placeholders})",
                            chunk,
                        )
                        deleted["task_results"] += max(0, int(cursor.rowcount))
                    if self._table_exists(conn, "task_snapshots"):
                        cursor = conn.execute(
                            f"DELETE FROM task_snapshots WHERE task_id IN ({placeholders})",
                            chunk,
                        )
                        deleted["task_snapshots"] += max(0, int(cursor.rowcount))
                    if self._table_exists(conn, "task_retention_tombstones"):
                        conn.executemany(
                            "INSERT OR IGNORE INTO task_retention_tombstones"
                            "(task_id, retired_at, reason) VALUES (?, ?, ?)",
                            [
                                (task_id, self._now(), "explicit_task_cleanup")
                                for task_id in chunk
                            ],
                        )
                deleted_ids = eligible
                orphan_blobs_removed, orphan_blob_bytes_removed = self._gc_blobs(conn)
            conn.commit()
            quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])

        return {
            "requested_task_ids": ids,
            "deleted_task_ids": deleted_ids,
            "skipped": [item.to_dict() for item in decisions if not item.can_cleanup],
            "deleted": deleted,
            "orphan_blobs_removed": orphan_blobs_removed,
            "orphan_blob_bytes_removed": orphan_blob_bytes_removed,
            "external_bytes_created": 0,
            "quick_check": quick_check,
            "counts": {
                "task_events": deleted["task_events"],
                "task_snapshots": deleted["task_snapshots"],
                "task_results": deleted["task_results"],
            },
        }

    def dismiss_task(self, task_id: str, *, dismissed_by: str = "local-user") -> dict[str, object]:
        """Keep the existing reversible UI dismissal under this service boundary."""

        return self.repository.dismiss_task(task_id, dismissed_by=dismissed_by)

    def dismiss_history(
        self,
        cleanup_type: str,
        *,
        include_states: list[str] | None = None,
        exclude_states: list[str] | None = None,
        dismissed_by: str = "local-user",
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Run the current Task Center soft-hide contract, without file deletion."""

        return self.repository.cleanup_history(
            cleanup_type,
            include_states=include_states,
            exclude_states=exclude_states,
            dismissed_by=dismissed_by,
            dry_run=dry_run,
        )

    def cleanup_terminal_retention(self) -> dict[str, object]:
        """Retain the configured ordinary history window and delete only safe rows."""

        deleted = {"task_snapshots": 0, "task_events": 0, "task_results": 0}
        protected = {
            "active": 0,
            "online_mr_mapping": 0,
            "long_term_reference": 0,
            "unreadable_metadata": 0,
        }
        result: dict[str, object] = {
            "limit_per_scope": TASK_HISTORY_SCOPE_LIMIT,
            "scopes": 0,
            "retained_terminal": 0,
            "deleted_task_ids": [],
            "deleted": deleted,
            "protected": protected,
        }
        with self.repository._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._table_exists(conn, "task_snapshots"):
                conn.rollback()
                return result
            tables = self._tables(conn)
            mapped = self.repository._online_mr_mapped_task_ids(conn, tables)
            authorities = self.repository._task_result_authority_by_id(conn, tables)
            rows = conn.execute(
                "SELECT task_id, task_type, site_name, status, finished_time, "
                "updated_time, result_json, result_id, result_summary_json, "
                "resource_keys_json FROM task_snapshots"
                " ORDER BY site_name, task_type, finished_time DESC, "
                "updated_time DESC, task_id DESC"
            ).fetchall()
            by_scope: dict[tuple[str, str], list[tuple[str, str]]] = {}
            for raw in rows:
                row = dict(raw)
                protection = self.repository._terminal_retention_protection(
                    row, mapped, authorities
                )
                if protection:
                    protected[protection] += 1
                    continue
                if str(row.get("status") or "").upper() not in TERMINAL_TASK_STATE_VALUES:
                    continue
                scope = task_history_scope(row.get("site_name"), row.get("task_type"))
                timestamp = str(row.get("finished_time") or row.get("updated_time") or "")
                by_scope.setdefault(scope, []).append((timestamp, str(row["task_id"])))

            result["scopes"] = len(by_scope)
            retained: set[str] = set()
            delete_ids: list[str] = []
            for candidates in by_scope.values():
                ordered = [task_id for _stamp, task_id in sorted(candidates, reverse=True)]
                retained.update(ordered[:TASK_HISTORY_SCOPE_LIMIT])
                delete_ids.extend(ordered[TASK_HISTORY_SCOPE_LIMIT:])
            result["retained_terminal"] = len(retained)
            for start in range(0, len(delete_ids), 500):
                chunk = delete_ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                if self._table_exists(conn, "task_events"):
                    cursor = conn.execute(
                        f"DELETE FROM task_events WHERE task_id IN ({placeholders})",
                        chunk,
                    )
                    deleted["task_events"] += max(0, int(cursor.rowcount))
                if self._table_exists(conn, "task_results"):
                    cursor = conn.execute(
                        f"DELETE FROM task_results WHERE task_id IN ({placeholders})",
                        chunk,
                    )
                    deleted["task_results"] += max(0, int(cursor.rowcount))
                cursor = conn.execute(
                    f"DELETE FROM task_snapshots WHERE task_id IN ({placeholders})",
                    chunk,
                )
                deleted["task_snapshots"] += max(0, int(cursor.rowcount))
                if self._table_exists(conn, "task_retention_tombstones"):
                    conn.executemany(
                        "INSERT OR IGNORE INTO task_retention_tombstones"
                        "(task_id, retired_at, reason) VALUES (?, ?, ?)",
                        [(task_id, self._now(), "terminal_history_retention") for task_id in chunk],
                    )
            result["deleted_task_ids"] = delete_ids
            if delete_ids:
                removed, removed_bytes = self._gc_blobs(conn)
                result["orphan_blobs_removed"] = removed
                result["orphan_blob_bytes_removed"] = removed_bytes
            conn.commit()
        return result

    def _decision(self, conn: sqlite3.Connection, task_id: str) -> CleanupDecision:
        if not task_id or not self._table_exists(conn, "task_snapshots"):
            return CleanupDecision(task_id, False, reasons=("TASK_NOT_FOUND",))
        row = conn.execute(
            "SELECT * FROM task_snapshots WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            return CleanupDecision(task_id, False, reasons=("TASK_NOT_FOUND",))
        values = dict(row)
        status = str(values.get("status") or "").upper()
        reasons: list[str] = []
        protected: list[str] = []
        if status in ACTIVE_TASK_STATE_VALUES:
            reasons.append("ACTIVE_TASK")
        elif status not in TERMINAL_TASK_STATE_VALUES:
            reasons.append("UNKNOWN_OR_NON_TERMINAL_STATUS")

        if self._has_online_mapping(conn, task_id):
            reasons.append("ONLINE_MR_MAPPING")
            protected.append("online_mr_task_sessions")
        ground_refs = self._ground_references(values, task_id)
        if ground_refs:
            reasons.append("GROUND_CURRENT_MAPPING")
            protected.extend(ground_refs)

        resource_keys, valid = self._json_list(values.get("resource_keys_json"))
        if not valid:
            reasons.append("RESOURCE_METADATA_UNREADABLE")
        elif resource_keys:
            reasons.append("RESOURCE_REFERENCE")
            protected.extend(str(value) for value in resource_keys)

        result, result_valid = self._task_result(conn, values)
        if not result_valid:
            reasons.append("RESULT_METADATA_UNREADABLE")
        elif result is None and str(values.get("result_id") or ""):
            reasons.append("RESULT_AUTHORITY_UNREADABLE")
        if result_valid and result is not None and self._contains_reference(result):
            reasons.append("DURABLE_RESULT_REFERENCE")
            protected.extend(self._reference_names(result))
        summary, summary_valid = self._json_object(values.get("result_summary_json"))
        if not summary_valid:
            reasons.append("RESULT_SUMMARY_UNREADABLE")
        elif self._contains_reference(summary):
            reasons.append("DURABLE_RESULT_SUMMARY_REFERENCE")
            protected.extend(self._reference_names(summary))
        if str(values.get("result_path") or "").strip():
            reasons.append("RESULT_ARTIFACT_REFERENCE")
            protected.append(str(values["result_path"]))
        if "online_mr" in str(values.get("task_type") or "").casefold():
            reasons.append("ONLINE_MR_TASK")
        if "ground_unattended" in str(values.get("task_type") or "").casefold():
            reasons.append("GROUND_TASK")

        reasons = list(dict.fromkeys(reasons))
        protected = list(dict.fromkeys(protected))
        event_rows = self._count(conn, "task_events", task_id)
        result_rows, result_bytes = self._result_counts(conn, task_id)
        return CleanupDecision(
            task_id=task_id,
            can_cleanup=not reasons,
            status=status,
            reasons=tuple(reasons),
            protected_resources=tuple(protected),
            event_rows=event_rows,
            snapshot_rows=1,
            result_rows=result_rows,
            result_bytes=result_bytes,
        )

    def _task_result(
        self, conn: sqlite3.Connection, row: dict[str, object]
    ) -> tuple[dict[str, object] | None, bool]:
        result_id = str(row.get("result_id") or "")
        if not result_id:
            return self._json_object(row.get("result_json"))
        authority = conn.execute(
            "SELECT * FROM task_results WHERE result_id=?", (result_id,)
        ).fetchone() if self._table_exists(conn, "task_results") else None
        if authority is None:
            return None, False
        try:
            return (
                self.repository._verified_result_for_read(
                    dict(authority), conn=conn
                ).get("result"),
                True,
            )
        except (sqlite3.DatabaseError, TaskResultBlobError):
            return None, False

    def _ground_references(self, row: dict[str, object], task_id: str) -> list[str]:
        if self.paths is None:
            return []
        site = str(row.get("site_name") or self.site_name or "demo")
        db_path = self.paths.ground_unattended_db_path(site)
        if not db_path.is_file():
            return []
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                names = [str(item[0]) for item in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]
                refs: list[str] = []
                for table in names:
                    columns = {
                        str(item[1]) for item in conn.execute(
                            f"PRAGMA table_info(\"{table.replace(chr(34), chr(34) * 2)}\")"
                        ).fetchall()
                    }
                    for column in sorted(columns & _GROUND_REFERENCE_COLUMNS):
                        hit = conn.execute(
                            f"SELECT 1 FROM \"{table.replace(chr(34), chr(34) * 2)}\" "
                            f"WHERE \"{column}\"=? LIMIT 1",
                            (task_id,),
                        ).fetchone()
                        if hit is not None:
                            refs.append(f"{table}.{column}")
                return refs
        except (OSError, sqlite3.DatabaseError):
            return ["ground_unreadable"]

    @staticmethod
    def _has_online_mapping(conn: sqlite3.Connection, task_id: str) -> bool:
        try:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='online_mr_task_sessions'"
            ).fetchone()
            if table is None:
                return False
            return conn.execute(
                "SELECT 1 FROM online_mr_task_sessions "
                "WHERE controller_task_id=? LIMIT 1",
                (task_id,),
            ).fetchone() is not None
        except sqlite3.DatabaseError:
            return True

    @staticmethod
    def _contains_reference(value: object) -> bool:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key or "").casefold()
                if normalized in _REFERENCE_KEYS and TaskCleanupService._has_value(nested):
                    return True
                if TaskCleanupService._contains_reference(nested):
                    return True
        elif isinstance(value, (list, tuple, set)):
            return any(TaskCleanupService._contains_reference(item) for item in value)
        return False

    @classmethod
    def _reference_names(cls, value: object) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key or "").casefold() in _REFERENCE_KEYS and cls._has_value(nested):
                    found.append(str(key))
                found.extend(cls._reference_names(nested))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                found.extend(cls._reference_names(item))
        return list(dict.fromkeys(found))

    @staticmethod
    def _has_value(value: object) -> bool:
        return bool(value) if isinstance(value, (str, list, tuple, set, dict)) else value is not None

    @staticmethod
    def _json_object(value: object) -> tuple[dict[str, object], bool]:
        raw = str(value or "").strip()
        if raw in {"", "null"}:
            return {}, True
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, False
        return (dict(parsed), True) if isinstance(parsed, dict) else ({}, False)

    @staticmethod
    def _json_list(value: object) -> tuple[list[object], bool]:
        raw = str(value or "").strip()
        if raw in {"", "null"}:
            return [], True
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [], False
        return (list(parsed), True) if isinstance(parsed, list) else ([], False)

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str, task_id: str) -> int:
        if not TaskCleanupService._table_exists(conn, table):
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE task_id=?", (task_id,)).fetchone()[0])

    @staticmethod
    def _result_counts(conn: sqlite3.Connection, task_id: str) -> tuple[int, int]:
        if not TaskCleanupService._table_exists(conn, "task_results"):
            return 0, 0
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM task_results WHERE task_id=?",
            (task_id,),
        ).fetchone()
        return int(row[0]), int(row[1])

    @staticmethod
    def _gc_blobs(conn: sqlite3.Connection) -> tuple[int, int]:
        if not TaskCleanupService._table_exists(conn, "task_result_blobs"):
            return 0, 0
        rows = conn.execute(
            "SELECT content_sha256, compressed_bytes FROM task_result_blobs "
            "WHERE NOT EXISTS (SELECT 1 FROM task_results "
            "WHERE blob_ready=1 AND content_sha256=task_result_blobs.content_sha256)"
        ).fetchall()
        if not rows:
            return 0, 0
        conn.executemany(
            "DELETE FROM task_result_blobs WHERE content_sha256=?",
            [(str(row[0]),) for row in rows],
        )
        return len(rows), sum(int(row[1] or 0) for row in rows)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    @classmethod
    def _tables(cls, conn: sqlite3.Connection) -> set[str]:
        return {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    @staticmethod
    def _normalize_ids(task_ids: list[str] | tuple[str, ...] | set[str]) -> list[str]:
        return list(dict.fromkeys(str(task_id).strip() for task_id in task_ids if str(task_id).strip()))

    @staticmethod
    def _now() -> str:
        from netconsole.models.task_snapshot import utc_now_iso

        return utc_now_iso()

    @staticmethod
    def _preview_payload(ids: list[str], decisions: list[CleanupDecision]) -> dict[str, object]:
        eligible = [item for item in decisions if item.can_cleanup]
        return {
            "requested_task_ids": ids,
            "decisions": [item.to_dict() for item in decisions],
            "eligible_count": len(eligible),
            "protected_count": len(decisions) - len(eligible),
            "estimated_reclaimable_bytes": sum(item.result_bytes for item in eligible),
            "estimated_reclaimable_rows": {
                "task_events": sum(item.event_rows for item in eligible),
                "task_snapshots": sum(item.snapshot_rows for item in eligible),
                "task_results": sum(item.result_rows for item in eligible),
            },
        }


__all__ = ["CleanupDecision", "TaskCleanupService"]
