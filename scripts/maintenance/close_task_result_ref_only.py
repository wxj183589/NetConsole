"""Digest-bound closure of verified task-result duplicate JSON.

Only ``task_results.canonical_json`` is cleared. Tasks, events, snapshots,
result rows and Blob rows are never deleted. Blob authority is verified before
and after the write; missing/corrupt/mismatched Blobs fail closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from netconsole.core.paths import PathResolver
from netconsole.repositories.task_result_blob_repository import (
    TaskResultBlobError,
    verify_task_result_authority,
)
from netconsole.services.database_footprint_maintenance import sqlite_quick_profile
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)


PLAN_SCHEMA = "task-result-ref-only-plan/v2"
AUTHORIZATION = "PRODUCTION_MAINTENANCE_AUTHORIZED"
TARGET_SCOPE = "TASK_RESULT_TARGET"


class TaskResultClosureError(RuntimeError):
    """A task-result authority or apply gate failed closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _open(path: Path, *, immutable: bool) -> sqlite3.Connection:
    if immutable:
        uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=30.0)
    else:
        connection = sqlite3.connect(path, timeout=60.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def _state(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise TaskResultClosureError(f"tasks.db is missing or unsafe: {path}")
    wal = path.with_name(f"{path.name}-wal")
    shm = path.with_name(f"{path.name}-shm")
    wal_bytes = int(wal.stat().st_size) if wal.is_file() else 0
    if wal_bytes:
        raise TaskResultClosureError("TASKS_DB_WAL_NONEMPTY: stop writers and re-preview")
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(path),
        "wal_bytes": wal_bytes,
        "shm_bytes": int(shm.stat().st_size) if shm.is_file() else 0,
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _table_digest(connection: sqlite3.Connection, table: str) -> str:
    metadata = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = [str(row[1]) for row in metadata]
    if not columns:
        return ""
    primary = [str(row[1]) for row in metadata if int(row[5] or 0)]
    order = primary or ["rowid"]
    digest = hashlib.sha256()
    cursor = connection.execute(
        f'SELECT * FROM "{table}" ORDER BY '
        + ", ".join(f'"{column}"' for column in order)
    )
    for row in cursor:
        values = [value.hex() if isinstance(value, bytes) else value for value in row]
        digest.update(_canonical_bytes({"table": table, "values": values}))
    return digest.hexdigest()


def _schema_identity(connection: sqlite3.Connection) -> dict[str, Any]:
    digest = hashlib.sha256()
    for row in connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name IS NOT NULL ORDER BY type, name"
    ):
        digest.update(
            _canonical_bytes(
                {
                    "type": row[0],
                    "name": row[1],
                    "tbl_name": row[2],
                    "sql": row[3],
                }
            )
        )
    return {
        "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        "schema_version": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
        "schema_sha256": digest.hexdigest(),
    }


def _authority_digest(connection: sqlite3.Connection) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    result_rows = 0
    blob_rows = (
        int(connection.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0])
        if _table_exists(connection, "task_result_blobs")
        else 0
    )
    for raw in connection.execute("SELECT * FROM task_results ORDER BY result_id"):
        try:
            verified = verify_task_result_authority(connection, dict(raw))
        except (sqlite3.DatabaseError, TaskResultBlobError) as exc:
            raise TaskResultClosureError(
                f"TASK_RESULT_AUTHORITY_INVALID: {raw['result_id']}: {exc}"
            ) from exc
        digest.update(
            _canonical_bytes(
                {
                    "result_id": str(verified.get("result_id") or ""),
                    "task_id": str(verified.get("task_id") or ""),
                    "terminal_event_type": str(
                        verified.get("terminal_event_type") or ""
                    ),
                    "sha256": str(verified.get("sha256") or ""),
                    "byte_size": int(verified.get("byte_size") or 0),
                    "content_sha256": str(raw["content_sha256"] or ""),
                    "blob_codec": str(raw["blob_codec"] or ""),
                    "blob_ready": int(raw["blob_ready"] or 0),
                }
            )
        )
        result_rows += 1
    return digest.hexdigest(), result_rows, blob_rows


def _row_fingerprint(row: Mapping[str, Any]) -> str:
    canonical = str(row.get("canonical_json") or "")
    return _digest(
        {
            "result_id": str(row.get("result_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "terminal_event_type": str(row.get("terminal_event_type") or ""),
            "sha256": str(row.get("sha256") or ""),
            "byte_size": int(row.get("byte_size") or 0),
            "schema_version": int(row.get("schema_version") or 0),
            "created_time": str(row.get("created_time") or ""),
            "content_sha256": str(row.get("content_sha256") or ""),
            "blob_codec": str(row.get("blob_codec") or ""),
            "blob_ready": int(row.get("blob_ready") or 0),
            "canonical_bytes": len(canonical.encode("utf-8")),
            "canonical_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
    )


def _collect(path: Path) -> dict[str, Any]:
    source = _state(path)
    with closing(_open(path, immutable=True)) as connection:
        if not _table_exists(connection, "task_results") or not _table_exists(
            connection, "task_result_blobs"
        ):
            raise TaskResultClosureError("tasks.db lacks task-result authority tables")
        result_ids: list[str] = []
        candidates: list[dict[str, Any]] = []
        for raw in connection.execute("SELECT * FROM task_results ORDER BY result_id"):
            row = dict(raw)
            result_ids.append(str(row["result_id"]))
            ready = int(row.get("blob_ready") or 0)
            canonical = str(row.get("canonical_json") or "")
            try:
                verified = verify_task_result_authority(connection, row)
            except (sqlite3.DatabaseError, TaskResultBlobError) as exc:
                raise TaskResultClosureError(
                    f"TASK_RESULT_AUTHORITY_INVALID: {row['result_id']}: {exc}"
                ) from exc
            if ready and canonical:
                if str(verified.get("canonical_json") or "") != canonical:
                    raise TaskResultClosureError(
                        f"TASK_RESULT_CANONICAL_MISMATCH: {row['result_id']}"
                    )
                candidates.append(
                    {
                        "result_id": str(row["result_id"]),
                        "task_id": str(row["task_id"]),
                        "terminal_event_type": str(row["terminal_event_type"]),
                        "sha256": str(row["sha256"]),
                        "byte_size": int(row["byte_size"]),
                        "row_fingerprint": _row_fingerprint(row),
                        "canonical_bytes": len(canonical.encode("utf-8")),
                    }
                )
        authority_digest, result_rows, blob_rows = _authority_digest(connection)
        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in ("task_snapshots", "task_events", "task_results", "task_result_blobs")
            if _table_exists(connection, table)
        }
        return {
            "source": source,
            "target_scope": {
                "scope_type": TARGET_SCOPE,
                "target_database": str(path.name),
                "result_ids": result_ids,
                "authority_fields": [
                    "result_id",
                    "task_id",
                    "terminal_event_type",
                    "sha256",
                    "byte_size",
                    "content_sha256",
                    "blob_codec",
                    "blob_ready",
                ],
                "authority_tables": [
                    "task_results",
                    "task_result_blobs",
                    "task_events",
                    "task_snapshots",
                ],
                "schema": _schema_identity(connection),
            },
            "candidates": candidates,
            "candidate_count": len(candidates),
            "candidate_bytes": sum(int(item["canonical_bytes"]) for item in candidates),
            "task_result_rows": result_rows,
            "task_result_blob_rows": blob_rows,
            "authority_digest": authority_digest,
            "table_counts": counts,
            "task_snapshots_digest": (
                _table_digest(connection, "task_snapshots")
                if _table_exists(connection, "task_snapshots")
                else ""
            ),
            "task_events_digest": (
                _table_digest(connection, "task_events")
                if _table_exists(connection, "task_events")
                else ""
            ),
            "task_results_digest": _table_digest(connection, "task_results"),
            "task_result_blobs_digest": _table_digest(
                connection, "task_result_blobs"
            ),
        }


def build_ref_only_plan(
    tasks_db: str | Path,
    *,
    site_id: str,
    data_root: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    path = Path(tasks_db).resolve(strict=True)
    collected = _collect(path)
    body: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "site_id": str(site_id),
        "data_root": str(Path(data_root).resolve(strict=True)),
        "digest_scope": TARGET_SCOPE,
        **collected,
    }
    body["plan_digest"] = _digest(body)
    return body


def write_ref_only_plan(plan: Mapping[str, Any], output: str | Path) -> Path:
    destination = Path(output).resolve()
    if destination.exists():
        raise TaskResultClosureError(f"refusing to overwrite ref-only plan: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_canonical_bytes(plan))
    return destination


def _backup_database(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise TaskResultClosureError(f"backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(_open(source, immutable=True)) as source_connection, closing(
        sqlite3.connect(destination)
    ) as target_connection:
        source_connection.backup(target_connection)
        target_connection.commit()
    profile = sqlite_quick_profile(destination, immutable=True)
    if not profile.get("valid") or str(profile.get("quick_check")) != "ok":
        raise TaskResultClosureError("maintenance backup quick_check failed")
    return {
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256(destination),
        "quick_check": "ok",
    }


def _restore_database(backup: Path, destination: Path) -> None:
    """Restore a committed write from the external backup after a post-check failure."""

    with closing(_open(backup, immutable=True)) as backup_connection, closing(
        _open(destination, immutable=False)
    ) as destination_connection:
        backup_connection.backup(destination_connection)
        destination_connection.commit()
    _checkpoint_wal(destination)
    profile = sqlite_quick_profile(destination, immutable=True)
    if not profile.get("valid") or str(profile.get("quick_check")) != "ok":
        raise TaskResultClosureError("maintenance backup restore quick_check failed")


def _checkpoint_wal(path: Path) -> None:
    """Flush a maintenance connection's WAL before the immutable post-check."""

    with sqlite3.connect(path, timeout=60.0) as connection:
        connection.execute("PRAGMA busy_timeout=60000")
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is not None and int(result[0] or 0) != 0:
            raise TaskResultClosureError("TASKS_DB_WAL_CHECKPOINT_FAILED")


def _verify_expected_candidate(
    connection: sqlite3.Connection, item: Mapping[str, Any]
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM task_results WHERE result_id=?", (str(item["result_id"]),)
    ).fetchone()
    if row is None:
        raise TaskResultClosureError(
            f"RETIRE_SOURCE_CHANGED: missing result {item['result_id']}"
        )
    raw = dict(row)
    if _row_fingerprint(raw) != str(item["row_fingerprint"]):
        raise TaskResultClosureError(
            f"RETIRE_SOURCE_CHANGED: result {item['result_id']}"
        )
    if int(raw.get("blob_ready") or 0) != 1 or not str(
        raw.get("canonical_json") or ""
    ):
        raise TaskResultClosureError(f"candidate is no longer dual: {item['result_id']}")
    try:
        verified = verify_task_result_authority(connection, raw)
    except (sqlite3.DatabaseError, TaskResultBlobError) as exc:
        raise TaskResultClosureError(
            f"TASK_RESULT_AUTHORITY_INVALID: {item['result_id']}: {exc}"
        ) from exc
    if str(verified.get("canonical_json") or "") != str(
        raw.get("canonical_json") or ""
    ):
        raise TaskResultClosureError(
            f"TASK_RESULT_CANONICAL_MISMATCH: {item['result_id']}"
        )
    return raw


def _already_applied(path: Path, plan: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recognize a completed application without weakening stale-plan checks."""

    after = _collect(path)
    if (
        after["candidate_count"] != 0
        or not _same_target_scope(after["target_scope"], plan.get("target_scope"))
        or after["authority_digest"] != plan.get("authority_digest")
        or after["task_snapshots_digest"] != plan.get("task_snapshots_digest")
        or after["task_events_digest"] != plan.get("task_events_digest")
        or after["task_result_rows"] != plan.get("task_result_rows")
        or after["task_result_blob_rows"] != plan.get("task_result_blob_rows")
    ):
        return None
    return after


def _same_target_scope(left: object, right: object) -> bool:
    """Compare the target contract while allowing the maintenance trigger DDL."""

    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    actual = json.loads(json.dumps(left))
    expected = json.loads(json.dumps(right))
    actual_schema = actual.get("schema")
    expected_schema = expected.get("schema")
    if isinstance(actual_schema, dict) and isinstance(expected_schema, dict):
        # SQLite increments schema_version when the immutable trigger is
        # dropped/recreated.  user_version and the normalized schema digest
        # remain the protected contract.
        actual_schema.pop("schema_version", None)
        expected_schema.pop("schema_version", None)
    return actual == expected


def apply_ref_only_plan(
    plan_path: str | Path,
    *,
    expected_plan_digest: str,
    backup_path: str | Path,
    authorization: str,
) -> dict[str, Any]:
    if authorization != AUTHORIZATION:
        raise TaskResultClosureError("explicit production authorization is required")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not isinstance(plan, Mapping) or plan.get("schema") != PLAN_SCHEMA:
        raise TaskResultClosureError("unsupported ref-only plan")
    body = dict(plan)
    actual_digest = str(body.pop("plan_digest") or "")
    if actual_digest != expected_plan_digest or _digest(body) != actual_digest:
        raise TaskResultClosureError("TASK_RESULT_PLAN_DIGEST_MISMATCH")
    source = Path(str(plan["source"]["path"])).resolve(strict=True)
    data_root = Path(str(plan["data_root"])).resolve(strict=True)
    if (
        not source.is_relative_to(data_root)
        or source.name != "tasks.db"
        or source.parent.name != "db"
    ):
        raise TaskResultClosureError("ref-only target is not a registered site tasks.db")
    backup = Path(backup_path).resolve()
    if backup.is_relative_to(data_root):
        raise TaskResultClosureError("maintenance backup must be outside production data root")
    try:
        current_state = _state(source)
    except TaskResultClosureError:
        raise
    if current_state != dict(plan["source"]):
        already_applied = _already_applied(source, plan)
        if already_applied is None:
            raise TaskResultClosureError("STALE_SOURCE: tasks.db changed after preview")
        current_profile = sqlite_quick_profile(source, immutable=True)
        return {
            "status": "PASS",
            "mode": "LOGICAL_RETIREMENT_ALREADY_APPLIED",
            "no_op": True,
            "plan_digest": actual_digest,
            "database": str(source),
            "released_rows": 0,
            "logical_bytes_reclaimed": 0,
            "task_result_rows": already_applied["task_result_rows"],
            "task_result_blob_rows": already_applied["task_result_blob_rows"],
            "task_result_authority": "PASS",
            "task_event_snapshot_parity": "PASS",
            "physical_bytes_before": int(plan["source"]["size_bytes"]),
            "physical_bytes_after": int(current_state["size_bytes"]),
            "freelist_after": int(current_profile["freelist_count"]),
            "quick_check": str(current_profile["quick_check"]),
            "backup": None,
            "vacuum": "NOT_PERFORMED",
        }
    backup_record = _backup_database(source, backup)
    resolver = PathResolver(data_root=data_root)
    committed = False
    released = 0
    with database_maintenance_lock(
        resolver, site_database_maintenance_key(str(plan["site_id"]))
    ):
        if _state(source) != dict(plan["source"]):
            raise TaskResultClosureError("STALE_SOURCE: tasks.db changed before apply")
        with closing(_open(source, immutable=False)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                candidates = plan.get("candidates")
                if not isinstance(candidates, list):
                    raise TaskResultClosureError("ref-only candidates are invalid")
                for item in candidates:
                    if not isinstance(item, Mapping):
                        raise TaskResultClosureError("ref-only candidate is invalid")
                    _verify_expected_candidate(connection, item)
                trigger = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_task_results_immutable'"
                ).fetchone()
                if trigger is None or not str(trigger[0] or "").strip():
                    raise TaskResultClosureError("task_results immutable trigger is missing")
                connection.execute("DROP TRIGGER trg_task_results_immutable")
                for item in candidates:
                    cursor = connection.execute(
                        "UPDATE task_results SET canonical_json='' "
                        "WHERE result_id=? AND blob_ready=1 AND canonical_json<>''",
                        (str(item["result_id"]),),
                    )
                    if int(cursor.rowcount or 0) != 1:
                        raise TaskResultClosureError(
                            f"candidate update was not exact: {item['result_id']}"
                        )
                    released += int(item["canonical_bytes"])
                connection.execute(str(trigger[0]))
                connection.commit()
                committed = True
            except Exception:
                connection.rollback()
                raise
        try:
            _checkpoint_wal(source)
            after = _collect(source)
            if after["authority_digest"] != plan["authority_digest"]:
                raise TaskResultClosureError("TASK_RESULT_SEMANTIC_PARITY_FAILED")
            if (
                after["task_snapshots_digest"] != plan["task_snapshots_digest"]
                or after["task_events_digest"] != plan["task_events_digest"]
            ):
                raise TaskResultClosureError("TASK_EVENT_OR_SNAPSHOT_CHANGED")
            if (
                after["task_result_rows"] != plan["task_result_rows"]
                or after["task_result_blob_rows"] != plan["task_result_blob_rows"]
            ):
                raise TaskResultClosureError("TASK_RESULT_OR_BLOB_ROW_COUNT_CHANGED")
            if not _same_target_scope(after["target_scope"], plan["target_scope"]):
                raise TaskResultClosureError("TASK_RESULT_TARGET_SCOPE_CHANGED")
            profile = sqlite_quick_profile(source, immutable=True)
        except Exception as exc:
            if committed:
                try:
                    _restore_database(backup, source)
                except Exception as restore_error:
                    raise TaskResultClosureError(
                        f"TASK_RESULT_POSTCHECK_FAILED_AND_RESTORE_FAILED: {restore_error}"
                    ) from restore_error
            raise exc
    return {
        "status": "PASS",
        "mode": "LOGICAL_RETIREMENT",
        "plan_digest": actual_digest,
        "database": str(source),
        "released_rows": int(plan["candidate_count"]),
        "logical_bytes_reclaimed": released,
        "task_result_rows": after["task_result_rows"],
        "task_result_blob_rows": after["task_result_blob_rows"],
        "task_result_authority": "PASS",
        "task_event_snapshot_parity": "PASS",
        "physical_bytes_before": int(plan["source"]["size_bytes"]),
        "physical_bytes_after": int(_state(source)["size_bytes"]),
        "freelist_after": int(profile["freelist_count"]),
        "quick_check": str(profile["quick_check"]),
        "backup": backup_record,
        "vacuum": "NOT_PERFORMED",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("--tasks-db", type=Path, required=True)
    preview.add_argument("--site-id", required=True)
    preview.add_argument("--data-root", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--expected-plan-digest", required=True)
    apply.add_argument("--backup", type=Path, required=True)
    apply.add_argument("--authorization", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preview":
        plan = build_ref_only_plan(
            args.tasks_db,
            site_id=args.site_id,
            data_root=args.data_root,
        )
        output = write_ref_only_plan(plan, args.output)
        print(
            json.dumps(
                {"status": "PASS", "plan": str(output), **plan},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            apply_ref_only_plan(
                args.plan,
                expected_plan_digest=args.expected_plan_digest,
                backup_path=args.backup,
                authorization=args.authorization,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
