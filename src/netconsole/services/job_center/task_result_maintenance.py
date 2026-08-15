from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.task_result_rollout import TaskResultStorageState
from netconsole.repositories.task_repository import (
    TASK_RESULT_SCHEMA_VERSION,
    TERMINAL_RESULT_EVENT_TYPES,
    TaskRepository,
)
from netconsole.services.database_footprint_maintenance import (
    DEVELOPMENT_ROOT,
    assert_development_path,
)
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)


BACKFILL_CLASSIFICATIONS = frozenset(
    {"MATCHED", "SNAPSHOT_ONLY", "EVENT_ONLY", "CONFLICT", "INVALID"}
)
_TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")


@dataclass(frozen=True)
class _BackfillCandidate:
    task_id: str
    classification: str
    terminal_event_type: str
    created_time: str
    canonical_json: str
    result: dict[str, Any]
    event_rows: tuple[dict[str, Any], ...]


class TaskResultMaintenanceService:
    """Development-root-only historical result migration and ref authority."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        tasks_database: str | Path,
        development_root: str | Path = DEVELOPMENT_ROOT,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id or "").strip()
        if not self.site_id:
            raise ValueError("site_id is required")
        self.development_root = Path(development_root).resolve()
        self.tasks_database = assert_development_path(
            tasks_database, development_root=self.development_root
        )
        self.repository = TaskRepository(self.tasks_database)

    def analyze_backfill(self) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        canonical_bytes = 0
        samples: dict[str, list[str]] = {
            classification: [] for classification in BACKFILL_CLASSIFICATIONS
        }
        with self.repository._connect() as connection:
            for row in self._terminal_snapshots(connection):
                candidate = self._classify(connection, row)
                counts[candidate.classification] += 1
                canonical_bytes += len(candidate.canonical_json.encode("utf-8"))
                selected = samples[candidate.classification]
                if len(selected) < 50:
                    selected.append(candidate.task_id)
        return {
            "database": str(self.tasks_database),
            "classifications": {
                name: int(counts[name]) for name in sorted(BACKFILL_CLASSIFICATIONS)
            },
            "canonical_result_bytes": canonical_bytes,
            "samples": samples,
        }

    def backfill(
        self,
        *,
        apply: bool = False,
        allow_development_root_only: bool = False,
        batch_rows: int = 250,
    ) -> dict[str, Any]:
        self._assert_apply(apply, allow_development_root_only)
        safe_batch = max(1, min(int(batch_rows), 1000))
        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            counts: Counter[str] = Counter()
            created = 0
            referenced = 0
            processed = 0
            with self.repository._connect() as connection:
                rows = self._terminal_snapshots(connection)
                for row in rows:
                    candidate = self._classify(connection, row)
                    counts[candidate.classification] += 1
                    if candidate.classification in {"CONFLICT", "INVALID"}:
                        continue
                    inserted, updated = self._persist_candidate(connection, candidate)
                    created += inserted
                    referenced += updated
                    processed += 1
                    if processed % safe_batch == 0:
                        connection.commit()
                connection.commit()
        return {
            "database": str(self.tasks_database),
            "classifications": {
                name: int(counts[name]) for name in sorted(BACKFILL_CLASSIFICATIONS)
            },
            "new_result_rows": created,
            "referenced_tasks": referenced,
            "task_results_rows": self.repository.task_result_count(),
            "idempotent": created == 0,
        }

    def enable_ref_authority(
        self,
        *,
        expected_revision: int,
        reason: str,
        updated_by: str,
        apply: bool = False,
        allow_development_root_only: bool = False,
        batch_rows: int = 500,
    ) -> dict[str, Any]:
        self._assert_apply(apply, allow_development_root_only)
        safe_batch = max(1, min(int(batch_rows), 1000))
        lock_key = site_database_maintenance_key(self.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            current = self.repository.task_result_rollout_status()
            if current.revision != int(expected_revision):
                raise ValueError("task result rollout revision mismatch")
            if current.state == TaskResultStorageState.TASK_RESULTS_DUAL_WRITE:
                verified = self.repository.compare_and_set_task_result_rollout(
                    expected_state=current.state,
                    expected_revision=current.revision,
                    target_state=TaskResultStorageState.TASK_RESULTS_VERIFIED,
                    updated_by=updated_by,
                    reason=reason,
                    allow_advanced=True,
                )
                if verified is None:
                    raise ValueError("task result verified transition conflict")
                current = verified
            if current.state not in {
                TaskResultStorageState.TASK_RESULTS_VERIFIED,
                TaskResultStorageState.RESULT_REF_AUTHORITY,
            }:
                raise ValueError("ref authority requires TASK_RESULTS_DUAL_WRITE")
            strip = self._strip_full_result_copies(batch_rows=safe_batch)
            if current.state == TaskResultStorageState.TASK_RESULTS_VERIFIED:
                ref = self.repository.compare_and_set_task_result_rollout(
                    expected_state=current.state,
                    expected_revision=current.revision,
                    target_state=TaskResultStorageState.RESULT_REF_AUTHORITY,
                    updated_by=updated_by,
                    reason=reason,
                    allow_advanced=True,
                )
                if ref is None:
                    raise ValueError("task result ref authority transition conflict")
                current = ref
        return {
            "database": str(self.tasks_database),
            "state": current.state.value,
            "revision": current.revision,
            **strip,
        }

    def _strip_full_result_copies(self, *, batch_rows: int) -> dict[str, int]:
        snapshot_rows = 0
        event_rows = 0
        released_json_bytes = 0
        with self.repository._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, result_id, result_hash, result_json "
                "FROM task_snapshots WHERE result_id <> '' ORDER BY task_id"
            ).fetchall()
            for row in rows:
                verified = self._verified_reference(connection, dict(row))
                legacy = str(row["result_json"] or "")
                if legacy not in {"", "{}", "null"}:
                    if self._canonical_object(legacy) != str(verified["canonical_json"]):
                        raise sqlite3.DatabaseError("snapshot result ref content mismatch")
                    cursor = connection.execute(
                        "UPDATE task_snapshots SET result_json='{}' WHERE task_id=?",
                        (str(row["task_id"]),),
                    )
                    snapshot_rows += int(cursor.rowcount or 0)
                    released_json_bytes += max(0, len(legacy.encode("utf-8")) - 2)
                    if snapshot_rows % batch_rows == 0:
                        connection.commit()
            event_candidates = connection.execute(
                "SELECT sequence, payload_json FROM task_events "
                "WHERE payload_json LIKE '%\"result_id\"%' ORDER BY sequence"
            ).fetchall()
            for row in event_candidates:
                payload = self._json_object(str(row["payload_json"] or ""))
                result_id = str(payload.get("result_id") or "")
                if not result_id:
                    continue
                verified = self._result_by_id(connection, result_id)
                if str(payload.get("result_hash") or "") not in {
                    "",
                    str(verified["sha256"]),
                }:
                    raise sqlite3.DatabaseError("event result ref hash mismatch")
                full = payload.get("result")
                if not isinstance(full, dict):
                    continue
                if self._canonical_json(full) != str(verified["canonical_json"]):
                    raise sqlite3.DatabaseError("event result ref content mismatch")
                released_json_bytes += len(self._canonical_json(full).encode("utf-8"))
                payload.pop("result", None)
                connection.execute(
                    "UPDATE task_events SET payload_json=? WHERE sequence=?",
                    (
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        int(row["sequence"]),
                    ),
                )
                event_rows += 1
                if event_rows % batch_rows == 0:
                    connection.commit()
            connection.commit()
        return {
            "snapshot_full_results_removed": snapshot_rows,
            "event_full_results_removed": event_rows,
            "logical_result_bytes_removed": released_json_bytes,
        }

    def _persist_candidate(
        self, connection: sqlite3.Connection, candidate: _BackfillCandidate
    ) -> tuple[int, int]:
        encoded = candidate.canonical_json.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        result_id = self._result_id(
            candidate.task_id, candidate.terminal_event_type, digest
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO task_results
                (result_id, task_id, terminal_event_type, canonical_json,
                 sha256, byte_size, schema_version, created_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                candidate.task_id,
                candidate.terminal_event_type,
                candidate.canonical_json,
                digest,
                len(encoded),
                TASK_RESULT_SCHEMA_VERSION,
                candidate.created_time,
            ),
        )
        created = int(cursor.rowcount or 0)
        verified = self._result_by_id(connection, result_id)
        if (
            str(verified["task_id"]) != candidate.task_id
            or str(verified["terminal_event_type"]) != candidate.terminal_event_type
            or str(verified["canonical_json"]) != candidate.canonical_json
        ):
            raise sqlite3.IntegrityError("task result backfill identity conflict")
        summary = self.repository._result_summary(
            candidate.result, byte_size=len(encoded)
        )
        summary_json = json.dumps(
            summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        snapshot_cursor = connection.execute(
            """
            UPDATE task_snapshots
            SET result_id=?, result_hash=?, result_summary_json=?
            WHERE task_id=? AND (
                result_id<>? OR result_hash<>? OR result_summary_json<>?
            )
            """,
            (
                result_id,
                digest,
                summary_json,
                candidate.task_id,
                result_id,
                digest,
                summary_json,
            ),
        )
        for event_row in candidate.event_rows:
            payload = self._json_object(str(event_row.get("payload_json") or ""))
            payload.update(
                {"result_id": result_id, "result_hash": digest, "result_summary": summary}
            )
            connection.execute(
                "UPDATE task_events SET payload_json=? WHERE sequence=?",
                (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    int(event_row["sequence"]),
                ),
            )
        return created, int(snapshot_cursor.rowcount or 0)

    def _classify(
        self, connection: sqlite3.Connection, snapshot: dict[str, Any]
    ) -> _BackfillCandidate:
        task_id = str(snapshot["task_id"])
        events = [
            dict(row)
            for row in connection.execute(
                "SELECT sequence, event_type, event_time, payload_json "
                "FROM task_events WHERE task_id=? "
                f"AND event_type IN ({','.join('?' for _ in TERMINAL_RESULT_EVENT_TYPES)}) "
                "ORDER BY sequence",
                (task_id, *sorted(TERMINAL_RESULT_EVENT_TYPES)),
            ).fetchall()
        ]
        snapshot_result = self._nonempty_object(str(snapshot.get("result_json") or ""))
        event_results: dict[str, dict[str, Any]] = {}
        for event in events:
            payload = self._json_object(str(event.get("payload_json") or ""))
            result = payload.get("result")
            if isinstance(result, dict) and result:
                event_results.setdefault(self._canonical_json(result), result)

        referenced: dict[str, Any] | None = None
        result_id = str(snapshot.get("result_id") or "")
        if result_id:
            referenced = self._result_by_id(connection, result_id)
        snapshot_canonical = (
            self._canonical_json(snapshot_result) if snapshot_result is not None else ""
        )
        if referenced is not None:
            referenced_canonical = str(referenced["canonical_json"])
            if snapshot_canonical and snapshot_canonical != referenced_canonical:
                return self._candidate(snapshot, events, "CONFLICT", "", {})
            snapshot_canonical = referenced_canonical
            snapshot_result = dict(referenced["result"])
        if len(event_results) > 1:
            return self._candidate(snapshot, events, "CONFLICT", "", {})
        event_canonical = next(iter(event_results), "")
        event_result = event_results.get(event_canonical)
        if snapshot_canonical and event_canonical:
            if snapshot_canonical != event_canonical:
                return self._candidate(snapshot, events, "CONFLICT", "", {})
            return self._candidate(
                snapshot, events, "MATCHED", snapshot_canonical, snapshot_result or {}
            )
        if snapshot_canonical:
            return self._candidate(
                snapshot,
                events,
                "SNAPSHOT_ONLY",
                snapshot_canonical,
                snapshot_result or {},
            )
        if event_canonical:
            return self._candidate(
                snapshot,
                events,
                "EVENT_ONLY",
                event_canonical,
                event_result or {},
            )
        return self._candidate(snapshot, events, "INVALID", "", {})

    def _candidate(
        self,
        snapshot: dict[str, Any],
        events: list[dict[str, Any]],
        classification: str,
        canonical: str,
        result: dict[str, Any],
    ) -> _BackfillCandidate:
        latest = events[-1] if events else {}
        event_type = str(latest.get("event_type") or self._status_event(snapshot["status"]))
        created = str(
            latest.get("event_time")
            or snapshot.get("finished_time")
            or snapshot.get("updated_time")
            or snapshot.get("created_time")
            or ""
        )
        return _BackfillCandidate(
            task_id=str(snapshot["task_id"]),
            classification=classification,
            terminal_event_type=event_type,
            created_time=created,
            canonical_json=canonical,
            result=result,
            event_rows=tuple(events),
        )

    def _verified_reference(
        self, connection: sqlite3.Connection, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._result_by_id(connection, str(snapshot.get("result_id") or ""))
        if str(snapshot.get("result_hash") or "") not in {"", str(result["sha256"])}:
            raise sqlite3.DatabaseError("snapshot result ref hash mismatch")
        return result

    def _result_by_id(
        self, connection: sqlite3.Connection, result_id: str
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM task_results WHERE result_id=?", (result_id,)
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("task result reference is missing")
        return self.repository._verified_result_row(dict(row))

    def _terminal_snapshots(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT task_id, status, created_time, finished_time, updated_time, "
            "result_json, result_id, result_hash FROM task_snapshots "
            f"WHERE status IN ({','.join('?' for _ in _TERMINAL_STATUSES)}) "
            "ORDER BY task_id",
            _TERMINAL_STATUSES,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _result_id(task_id: str, event_type: str, digest: str) -> str:
        identity = f"{task_id}\0{event_type}\0{digest}".encode("utf-8")
        return "tr-" + hashlib.sha256(identity).hexdigest()

    @staticmethod
    def _canonical_json(value: dict[str, Any]) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def _canonical_object(cls, value: str) -> str:
        parsed = cls._json_object(value)
        return cls._canonical_json(parsed)

    @staticmethod
    def _json_object(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @classmethod
    def _nonempty_object(cls, value: str) -> dict[str, Any] | None:
        result = cls._json_object(value)
        return result or None

    @staticmethod
    def _status_event(status: object) -> str:
        return {
            "COMPLETED": "finished",
            "FAILED": "error",
            "CANCELLED": "cancelled",
        }.get(str(status).upper(), "finished")

    @staticmethod
    def _assert_apply(apply: bool, allow_development_root_only: bool) -> None:
        if not apply or not allow_development_root_only:
            raise ValueError(
                "task result maintenance requires --apply and "
                "--allow-development-root-only"
            )


__all__ = ["BACKFILL_CLASSIFICATIONS", "TaskResultMaintenanceService"]
