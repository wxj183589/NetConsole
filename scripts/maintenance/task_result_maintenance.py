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
    sqlite_quick_profile,
)
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)


BACKFILL_CLASSIFICATIONS = frozenset(
    {"MATCHED", "SNAPSHOT_ONLY", "EVENT_ONLY", "CONFLICT", "INVALID"}
)
_PRODUCTION_ROLLOUT_PERMIT = object()
_TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")
_POST_TERMINAL_RESULT_EVENT_TYPES = frozenset(
    {"artifact_finalized", "artifact_rejected"}
)
_RESULT_EVENT_TYPES = TERMINAL_RESULT_EVENT_TYPES | _POST_TERMINAL_RESULT_EVENT_TYPES


def _production_profile(path: Path) -> dict[str, Any]:
    """Checkpoint WAL created by our bounded writes before immutable verification."""

    with sqlite3.connect(path, timeout=60) as connection:
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return sqlite_quick_profile(path, immutable=True)


@dataclass(frozen=True)
class _BackfillCandidate:
    task_id: str
    classification: str
    terminal_event_type: str
    created_time: str
    canonical_json: str
    result: dict[str, Any]
    event_rows: tuple[dict[str, Any], ...]
    bind_snapshot: bool


class TaskResultMaintenanceService:
    """Development-root-only historical result migration and ref authority."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        tasks_database: str | Path,
        development_root: str | Path = DEVELOPMENT_ROOT,
        _production_permit: object | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = str(site_id or "").strip()
        if not self.site_id:
            raise ValueError("site_id is required")
        self.development_root = Path(development_root).resolve()
        self._production_mode = _production_permit is _PRODUCTION_ROLLOUT_PERMIT
        if self._production_mode:
            target = Path(tasks_database).resolve()
            if target.name != "tasks.db" or target.parent.name != "db":
                raise ValueError("production task rollout requires the registered tasks.db")
            self.tasks_database = target
        else:
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

    def profile(self) -> dict[str, Any]:
        """Return a deep, read-only storage profile for one tasks rehearsal DB."""

        physical = sqlite_quick_profile(self.tasks_database)
        with self.repository._connect() as connection:
            snapshots = [
                dict(row)
                for row in connection.execute(
                    "SELECT status, task_type, substr(updated_time, 1, 7) AS month, "
                    "COUNT(*) AS rows, SUM(LENGTH(result_json)) AS result_json_bytes "
                    "FROM task_snapshots GROUP BY status, task_type, month "
                    "ORDER BY status, task_type, month"
                ).fetchall()
            ]
            events = [
                dict(row)
                for row in connection.execute(
                    "SELECT event_type, substr(event_time, 1, 7) AS month, "
                    "COUNT(*) AS rows, SUM(LENGTH(payload_json)) AS payload_bytes "
                    "FROM task_events GROUP BY event_type, month "
                    "ORDER BY event_type, month"
                ).fetchall()
            ]
            results_row = connection.execute(
                "SELECT COUNT(*) AS rows, COALESCE(SUM(byte_size), 0) AS bytes "
                "FROM task_results"
            ).fetchone()
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
            sessions = (
                int(
                    connection.execute(
                        "SELECT COUNT(*) FROM online_mr_task_sessions"
                    ).fetchone()[0]
                )
                if "online_mr_task_sessions" in tables
                else 0
            )
            classifications: Counter[str] = Counter()
            duplicate_bytes = 0
            for row in self._terminal_snapshots(connection):
                candidate = self._classify(connection, row)
                classifications[candidate.classification] += 1
                if candidate.classification == "MATCHED":
                    duplicate_bytes += len(candidate.canonical_json.encode("utf-8"))
        return {
            "database": str(self.tasks_database),
            "physical": physical,
            "task_snapshots": {
                "rows": int(physical["table_counts"].get("task_snapshots", 0)),
                "result_json_bytes": sum(
                    int(row.get("result_json_bytes") or 0) for row in snapshots
                ),
                "breakdown": snapshots,
            },
            "task_events": {
                "rows": int(physical["table_counts"].get("task_events", 0)),
                "payload_bytes": sum(
                    int(row.get("payload_bytes") or 0) for row in events
                ),
                "progress_payload_bytes": sum(
                    int(row.get("payload_bytes") or 0)
                    for row in events
                    if str(row.get("event_type") or "") == "progress"
                ),
                "log_payload_bytes": sum(
                    int(row.get("payload_bytes") or 0)
                    for row in events
                    if str(row.get("event_type") or "") == "log"
                ),
                "breakdown": events,
            },
            "task_results": {
                "rows": int(results_row["rows"] if results_row else 0),
                "canonical_bytes": int(results_row["bytes"] if results_row else 0),
            },
            "online_mr_task_sessions": {"rows": sessions},
            "terminal_result_semantic_duplication": {
                "matched_tasks": int(classifications["MATCHED"]),
                "removable_bytes": duplicate_bytes,
                "classifications": {
                    name: int(classifications[name])
                    for name in sorted(BACKFILL_CLASSIFICATIONS)
                },
            },
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
            repaired_snapshot_refs = 0
            repaired_event_refs = 0
            processed = 0
            with self.repository._connect() as connection:
                rows = self._terminal_snapshots(connection)
                for row in rows:
                    snapshot_repairs, event_repairs = self._remove_invalid_bindings(
                        connection, row
                    )
                    repaired_snapshot_refs += snapshot_repairs
                    repaired_event_refs += event_repairs
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
            "invalid_snapshot_refs_removed": repaired_snapshot_refs,
            "invalid_event_refs_removed": repaired_event_refs,
            "task_results_rows": self.repository.task_result_count(),
            "idempotent": (
                created == 0
                and referenced == 0
                and repaired_snapshot_refs == 0
                and repaired_event_refs == 0
            ),
        }

    def backfill_production(
        self,
        *,
        authorization: str,
        expected_source_revision: str,
        batch_rows: int = 250,
    ) -> dict[str, Any]:
        """Run the existing idempotent backfill through the production permit.

        The constructor permit is intentionally private and is only issued by
        ``ProductionTaskRolloutExecutor``.  The development API above keeps
        its original root guard and remains the supported local rehearsal API.
        """

        if not self._production_mode:
            raise ValueError("production task rollout requires the production permit")
        if authorization != "PRODUCTION_MAINTENANCE_AUTHORIZED":
            raise ValueError("explicit production authorization is required")
        profile = sqlite_quick_profile(self.tasks_database, immutable=True)
        if not profile.get("valid") or str(profile.get("sha256")) != str(expected_source_revision):
            raise ValueError("STALE_SOURCE: tasks.db revision changed before backfill")
        result = self.backfill(
            apply=True,
            allow_development_root_only=True,
            batch_rows=batch_rows,
        )
        after = _production_profile(self.tasks_database)
        if not after.get("valid"):
            raise ValueError("tasks.db verification failed after backfill")
        return {**result, "source_revision_before": str(expected_source_revision), "source_revision_after": str(after.get("sha256"))}

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

    def enable_ref_authority_production(
        self,
        *,
        authorization: str,
        expected_source_revision: str,
        expected_revision: int,
        reason: str,
        updated_by: str,
        batch_rows: int = 500,
    ) -> dict[str, Any]:
        if not self._production_mode:
            raise ValueError("production task rollout requires the production permit")
        if authorization != "PRODUCTION_MAINTENANCE_AUTHORIZED":
            raise ValueError("explicit production authorization is required")
        before = _production_profile(self.tasks_database)
        if not before.get("valid") or str(before.get("sha256")) != str(expected_source_revision):
            raise ValueError("STALE_SOURCE: tasks.db revision changed before authority transition")
        result = self.enable_ref_authority(
            expected_revision=expected_revision,
            reason=reason,
            updated_by=updated_by,
            apply=True,
            allow_development_root_only=True,
            batch_rows=batch_rows,
        )
        after = _production_profile(self.tasks_database)
        if not after.get("valid"):
            raise ValueError("tasks.db verification failed after authority transition")
        return {**result, "source_revision_before": str(expected_source_revision), "source_revision_after": str(after.get("sha256"))}

    def _strip_full_result_copies(self, *, batch_rows: int) -> dict[str, int]:
        snapshot_rows = 0
        event_rows = 0
        released_json_bytes = 0
        with self.repository._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, status, result_id, result_hash, result_json "
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
                "SELECT sequence, task_id, event_type, payload_json FROM task_events "
                "WHERE payload_json LIKE '%\"result_id\"%' ORDER BY sequence"
            ).fetchall()
            for row in event_candidates:
                payload = self._json_object(str(row["payload_json"] or ""))
                result_id = str(payload.get("result_id") or "")
                if not result_id:
                    continue
                verified = self._result_by_id(connection, result_id)
                self._assert_result_binding(
                    verified,
                    task_id=str(row["task_id"]),
                    terminal_event_type=str(row["event_type"]),
                    owner="event",
                )
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
        self._validate_candidate_bindings(connection, candidate)
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
        snapshot_rows = 0
        if candidate.bind_snapshot:
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
            snapshot_rows = int(snapshot_cursor.rowcount or 0)
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
        return created, snapshot_rows

    def _classify(
        self, connection: sqlite3.Connection, snapshot: dict[str, Any]
    ) -> _BackfillCandidate:
        task_id = str(snapshot["task_id"])
        status_event_type = self._status_event(snapshot["status"])
        result_event_types = sorted(_RESULT_EVENT_TYPES)
        events = [
            dict(row)
            for row in connection.execute(
                "SELECT sequence, task_id, event_type, event_time, payload_json "
                "FROM task_events WHERE task_id=? "
                f"AND event_type IN ({','.join('?' for _ in result_event_types)}) "
                "ORDER BY sequence",
                (task_id, *result_event_types),
            ).fetchall()
        ]
        snapshot_result = self._nonempty_object(str(snapshot.get("result_json") or ""))
        event_results: dict[str, dict[str, Any]] = {}
        event_rows_by_result: dict[str, list[dict[str, Any]]] = {}
        event_types_by_result: dict[str, set[str]] = {}
        event_reference_conflict = False
        for event in events:
            event_type = str(event.get("event_type") or "")
            payload = self._json_object(str(event.get("payload_json") or ""))
            result = payload.get("result")
            full_canonical = (
                self._canonical_json(result)
                if isinstance(result, dict) and result
                else ""
            )
            referenced_canonical = ""
            result_id = str(payload.get("result_id") or "")
            if result_id:
                referenced = self._result_by_id(connection, result_id)
                if (
                    str(referenced["task_id"]) == task_id
                    and str(referenced["terminal_event_type"]) == event_type
                ):
                    referenced_canonical = str(referenced["canonical_json"])
                    if full_canonical and full_canonical != referenced_canonical:
                        event_reference_conflict = True
                else:
                    event_reference_conflict = True
            canonical = full_canonical or referenced_canonical
            if not canonical:
                continue
            event_result = (
                dict(result)
                if full_canonical
                else dict(self._result_by_id(connection, result_id)["result"])
            )
            event_results.setdefault(canonical, event_result)
            event_rows_by_result.setdefault(canonical, []).append(event)
            event_types_by_result.setdefault(canonical, set()).add(event_type)

        referenced: dict[str, Any] | None = None
        result_id = str(snapshot.get("result_id") or "")
        if result_id:
            referenced = self._result_by_id(connection, result_id)
        snapshot_canonical = (
            self._canonical_json(snapshot_result) if snapshot_result is not None else ""
        )
        if referenced is not None:
            if str(referenced["task_id"]) != task_id:
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
            if str(snapshot.get("result_hash") or "") not in {
                "",
                str(referenced["sha256"]),
            }:
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
            referenced_canonical = str(referenced["canonical_json"])
            if snapshot_canonical and snapshot_canonical != referenced_canonical:
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
            snapshot_canonical = referenced_canonical
            snapshot_result = dict(referenced["result"])
        if event_reference_conflict:
            return self._candidate(snapshot, events, (), "CONFLICT", "", {})

        # Artifact finalization is a deliberate post-terminal authority
        # transition: the worker first emits a pending result, then the
        # artifact store adds the verified filename/digest/size.  Prefer that
        # later result when it is internally unambiguous, while still failing
        # closed on multiple post-terminal payloads or artifact identities.
        post_terminal_canonicals = {
            canonical
            for canonical, rows in event_rows_by_result.items()
            if any(
                str(row.get("event_type") or "")
                in _POST_TERMINAL_RESULT_EVENT_TYPES
                for row in rows
            )
        }
        if len(post_terminal_canonicals) > 1:
            return self._candidate(snapshot, events, (), "CONFLICT", "", {})
        if post_terminal_canonicals:
            event_canonical = next(iter(post_terminal_canonicals))
            post_rows = tuple(
                row
                for row in event_rows_by_result.get(event_canonical, ())
                if str(row.get("event_type") or "")
                in _POST_TERMINAL_RESULT_EVENT_TYPES
            )
            post_event_types = {
                str(row.get("event_type") or "") for row in post_rows
            }
            if len(post_event_types) != 1:
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
            event_result = event_results.get(event_canonical)
            bound_event_rows = post_rows
            event_type = next(iter(post_event_types))
            artifact_ids = {
                str(value.get("artifact_id") or "")
                for value in (snapshot_result or {}, event_result or {})
                if str(value.get("artifact_id") or "")
            }
            for canonical, values in event_results.items():
                if canonical == event_canonical:
                    continue
                for value in (values or {},):
                    artifact_id = str(value.get("artifact_id") or "")
                    if artifact_id:
                        artifact_ids.add(artifact_id)
            if len(artifact_ids) > 1:
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
        else:
            if len(event_results) > 1 or any(
                len(event_types) > 1 for event_types in event_types_by_result.values()
            ):
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
            event_canonical = next(iter(event_results), "")
            event_result = event_results.get(event_canonical)
            bound_event_rows = tuple(event_rows_by_result.get(event_canonical, ()))
            event_type = next(iter(event_types_by_result.get(event_canonical, ())), "")
        if snapshot_canonical and event_canonical:
            if snapshot_canonical != event_canonical:
                return self._candidate(snapshot, events, (), "CONFLICT", "", {})
            return self._candidate(
                snapshot,
                events,
                bound_event_rows,
                "MATCHED",
                snapshot_canonical,
                snapshot_result or {},
                terminal_event_type=event_type,
            )
        if snapshot_canonical:
            return self._candidate(
                snapshot,
                events,
                (),
                "SNAPSHOT_ONLY",
                snapshot_canonical,
                snapshot_result or {},
                terminal_event_type=(
                    str(referenced["terminal_event_type"])
                    if referenced is not None
                    else status_event_type
                ),
            )
        if event_canonical:
            return self._candidate(
                snapshot,
                events,
                bound_event_rows,
                "EVENT_ONLY",
                event_canonical,
                event_result or {},
                terminal_event_type=event_type,
            )
        return self._candidate(snapshot, events, (), "INVALID", "", {})

    def _candidate(
        self,
        snapshot: dict[str, Any],
        expected_events: list[dict[str, Any]],
        bound_event_rows: tuple[dict[str, Any], ...],
        classification: str,
        canonical: str,
        result: dict[str, Any],
        *,
        terminal_event_type: str = "",
    ) -> _BackfillCandidate:
        latest = bound_event_rows[-1] if bound_event_rows else (
            expected_events[-1] if expected_events else {}
        )
        event_type = terminal_event_type or self._status_event(snapshot["status"])
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
            event_rows=bound_event_rows,
            bind_snapshot=classification in {"MATCHED", "SNAPSHOT_ONLY"},
        )

    def _validate_candidate_bindings(
        self, connection: sqlite3.Connection, candidate: _BackfillCandidate
    ) -> None:
        if candidate.terminal_event_type not in _RESULT_EVENT_TYPES:
            raise sqlite3.IntegrityError("task result backfill terminal type is invalid")
        if not candidate.result or self._canonical_json(candidate.result) != (
            candidate.canonical_json
        ):
            raise sqlite3.IntegrityError("task result backfill canonical content mismatch")
        for event in candidate.event_rows:
            if str(event.get("task_id") or "") != candidate.task_id:
                raise sqlite3.IntegrityError("task result backfill event task mismatch")
            if str(event.get("event_type") or "") != candidate.terminal_event_type:
                raise sqlite3.IntegrityError("task result backfill event type mismatch")
            payload = self._json_object(str(event.get("payload_json") or ""))
            full = payload.get("result")
            full_matches = isinstance(full, dict) and bool(full) and (
                self._canonical_json(full) == candidate.canonical_json
            )
            ref_matches = False
            result_id = str(payload.get("result_id") or "")
            if result_id:
                referenced = self._result_by_id(connection, result_id)
                self._assert_result_binding(
                    referenced,
                    task_id=candidate.task_id,
                    terminal_event_type=candidate.terminal_event_type,
                    owner="event",
                )
                ref_matches = str(referenced["canonical_json"]) == (
                    candidate.canonical_json
                )
            if not full_matches and not ref_matches:
                raise sqlite3.IntegrityError(
                    "task result backfill event provenance mismatch"
                )

    def _remove_invalid_bindings(
        self, connection: sqlite3.Connection, snapshot: dict[str, Any]
    ) -> tuple[int, int]:
        task_id = str(snapshot["task_id"])
        snapshot_repairs = 0
        snapshot_result_id = str(snapshot.get("result_id") or "")
        if snapshot_result_id:
            referenced = self._result_by_id(connection, snapshot_result_id)
            snapshot_hash = str(snapshot.get("result_hash") or "")
            snapshot_result = self._nonempty_object(
                str(snapshot.get("result_json") or "")
            )
            content_mismatch = snapshot_result is not None and (
                self._canonical_json(snapshot_result)
                != str(referenced["canonical_json"])
            )
            ambiguous_status_binding = (
                snapshot_result is None
                and str(referenced["terminal_event_type"])
                != self._status_event(snapshot["status"])
                and self._has_different_status_event_result(
                    connection,
                    task_id=task_id,
                    event_type=self._status_event(snapshot["status"]),
                    canonical_json=str(referenced["canonical_json"]),
                )
            )
            if (
                str(referenced["task_id"]) != task_id
                or snapshot_hash not in {"", str(referenced["sha256"])}
                or content_mismatch
                or ambiguous_status_binding
            ):
                connection.execute(
                    "UPDATE task_snapshots SET result_id='', result_hash='', "
                    "result_summary_json='{}' WHERE task_id=?",
                    (task_id,),
                )
                snapshot.update(
                    {"result_id": "", "result_hash": "", "result_summary_json": "{}"}
                )
                snapshot_repairs = 1

        event_repairs = 0
        rows = connection.execute(
            "SELECT sequence, task_id, event_type, payload_json FROM task_events "
            "WHERE task_id=? AND payload_json LIKE '%\"result_id\"%'",
            (task_id,),
        ).fetchall()
        for raw_row in rows:
            row = dict(raw_row)
            payload = self._json_object(str(row.get("payload_json") or ""))
            result_id = str(payload.get("result_id") or "")
            if not result_id:
                continue
            referenced = self._result_by_id(connection, result_id)
            if (
                str(referenced["task_id"]) == str(row["task_id"])
                and str(referenced["terminal_event_type"]) == str(row["event_type"])
            ):
                continue
            payload.pop("result_id", None)
            payload.pop("result_hash", None)
            payload.pop("result_summary", None)
            connection.execute(
                "UPDATE task_events SET payload_json=? WHERE sequence=?",
                (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    int(row["sequence"]),
                ),
            )
            event_repairs += 1
        return snapshot_repairs, event_repairs

    def _has_different_status_event_result(
        self,
        connection: sqlite3.Connection,
        *,
        task_id: str,
        event_type: str,
        canonical_json: str,
    ) -> bool:
        rows = connection.execute(
            "SELECT payload_json FROM task_events WHERE task_id=? AND event_type=?",
            (task_id, event_type),
        ).fetchall()
        for row in rows:
            payload = self._json_object(str(row["payload_json"] or ""))
            full = payload.get("result")
            if isinstance(full, dict) and full:
                if self._canonical_json(full) != canonical_json:
                    return True
                continue
            result_id = str(payload.get("result_id") or "")
            if not result_id:
                continue
            referenced = self._result_by_id(connection, result_id)
            if (
                str(referenced["task_id"]) == task_id
                and str(referenced["terminal_event_type"]) == event_type
                and str(referenced["canonical_json"]) != canonical_json
            ):
                return True
        return False

    @staticmethod
    def _assert_result_binding(
        result: dict[str, Any],
        *,
        task_id: str,
        terminal_event_type: str | None,
        owner: str,
    ) -> None:
        if str(result["task_id"]) != task_id:
            raise sqlite3.DatabaseError(f"task {owner} result task binding mismatch")
        if terminal_event_type is not None and (
            str(result["terminal_event_type"]) != terminal_event_type
        ):
            raise sqlite3.DatabaseError(
                f"task {owner} result terminal event binding mismatch"
            )

    def _verified_reference(
        self, connection: sqlite3.Connection, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        result = self._result_by_id(connection, str(snapshot.get("result_id") or ""))
        self._assert_result_binding(
            result,
            task_id=str(snapshot["task_id"]),
            terminal_event_type=None,
            owner="snapshot",
        )
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
