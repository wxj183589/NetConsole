"""Candidate-first physical compaction for an authorized production tasks.db.

This is deliberately separate from the development-root compactor. It accepts
one digest-bound plan for one registered site, creates an external recovery
copy before replacement, validates every user table and task-result authority
on the candidate, and restores the recovery copy if post-replace verification
fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
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
from scripts.maintenance.audit_task_storage_integrity import audit_database


PLAN_SCHEMA = "task-result-production-compaction-plan/v1"
TARGET_SCOPE = "TASK_DB_PHYSICAL_COMPACTION_TARGET"
AUTHORIZATION = "PRODUCTION_MAINTENANCE_AUTHORIZED"
PRODUCTION_ROOT = Path(r"D:\NetConsoleData")
MIN_FREELIST_BYTES = 16 * 1024 * 1024
MIN_FREELIST_PERCENT = 5.0


class TaskResultCompactionError(RuntimeError):
    """A production compaction gate failed closed."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open(path: Path, *, immutable: bool) -> sqlite3.Connection:
    if immutable:
        uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=60.0)
    else:
        connection = sqlite3.connect(path, timeout=60.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _table_digest(connection: sqlite3.Connection, table: str) -> str:
    columns = [
        (str(row[1]), int(row[5] or 0))
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
    ]
    if not columns:
        return ""
    order = [name for name, primary in columns if primary] or ["rowid"]
    digest = hashlib.sha256()
    for row in connection.execute(
        f"SELECT * FROM {_quote(table)} ORDER BY "
        + ", ".join(_quote(column) for column in order)
    ):
        values = [value.hex() if isinstance(value, bytes) else value for value in row]
        digest.update(_canonical({"table": table, "values": values}))
    return digest.hexdigest()


def _schema_identity(connection: sqlite3.Connection) -> dict[str, Any]:
    schema = [
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name IS NOT NULL ORDER BY type, name"
        )
    ]
    return {
        "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        "schema_version": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
        "schema_sha256": _digest(schema),
    }


def _authority_digest(connection: sqlite3.Connection) -> tuple[str, int, int, int]:
    digest = hashlib.sha256()
    result_rows = 0
    canonical_bytes = 0
    blob_rows = int(
        connection.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0]
    )
    for raw in connection.execute("SELECT * FROM task_results ORDER BY result_id"):
        row = dict(raw)
        try:
            verified = verify_task_result_authority(connection, row)
        except (sqlite3.DatabaseError, TaskResultBlobError) as exc:
            raise TaskResultCompactionError(
                f"TASK_RESULT_AUTHORITY_INVALID: {row.get('result_id')}: {exc}"
            ) from exc
        canonical = str(row.get("canonical_json") or "")
        canonical_bytes += len(canonical.encode("utf-8"))
        digest.update(
            _canonical(
                {
                    "result_id": str(verified.get("result_id") or ""),
                    "task_id": str(verified.get("task_id") or ""),
                    "terminal_event_type": str(verified.get("terminal_event_type") or ""),
                    "sha256": str(verified.get("sha256") or ""),
                    "byte_size": int(verified.get("byte_size") or 0),
                    "content_sha256": str(row.get("content_sha256") or ""),
                    "blob_codec": str(row.get("blob_codec") or ""),
                    "blob_ready": int(row.get("blob_ready") or 0),
                }
            )
        )
        result_rows += 1
    return digest.hexdigest(), result_rows, blob_rows, canonical_bytes


def _state(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise TaskResultCompactionError(f"tasks.db is missing or unsafe: {path}")
    wal = path.with_name(f"{path.name}-wal")
    shm = path.with_name(f"{path.name}-shm")
    wal_bytes = int(wal.stat().st_size) if wal.is_file() else 0
    if wal_bytes:
        raise TaskResultCompactionError("TASKS_DB_WAL_NONEMPTY: stop writers")
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(path),
        "wal_bytes": wal_bytes,
        "shm_bytes": int(shm.stat().st_size) if shm.is_file() else 0,
    }


def _physical_bytes(path: Path) -> int:
    return sum(
        int(item.stat().st_size)
        for item in (
            path,
            path.with_name(f"{path.name}-wal"),
            path.with_name(f"{path.name}-shm"),
        )
        if item.is_file()
    )


def _profile(path: Path) -> dict[str, Any]:
    profile = sqlite_quick_profile(path, immutable=True)
    if not profile.get("valid"):
        raise TaskResultCompactionError(f"SQLite quick_check failed: {path}")
    with closing(_open(path, immutable=True)) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {
            table: {
                "row_count": int(
                    connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
                ),
                "digest": _table_digest(connection, table),
            }
            for table in _table_names(connection)
        }
        schema = _schema_identity(connection)
        authority = _authority_digest(connection)
    if integrity != "ok":
        raise TaskResultCompactionError(f"SQLite integrity_check failed: {path}")
    return {
        "physical_bytes": _physical_bytes(path),
        "page_size": int(profile["page_size"]),
        "page_count": int(profile["page_count"]),
        "freelist_count": int(profile["freelist_count"]),
        "freelist_bytes": int(profile["freelist_count"]) * int(profile["page_size"]),
        "freelist_percent": round(
            int(profile["freelist_count"]) * 100 / max(1, int(profile["page_count"])),
            4,
        ),
        "quick_check": str(profile["quick_check"]),
        "integrity_check": integrity,
        "schema": schema,
        "tables": tables,
        "authority_digest": authority[0],
        "task_result_rows": authority[1],
        "task_result_blob_rows": authority[2],
        "canonical_bytes": authority[3],
    }


def _audit_summary(site_id: str, path: Path, data_root: Path) -> dict[str, Any]:
    report = audit_database(site_id, path, data_root=data_root)
    return {
        "status": str(report.get("status")),
        "task_count": int(report.get("task_count") or 0),
        "event_count": int(report.get("event_count") or 0),
        "snapshot_count": int(report.get("snapshot_count") or 0),
        "result_count": int(report.get("result_count") or 0),
        "blob_count": int(report.get("blob_count") or 0),
        "task_result_parent_orphans": int(report.get("task_result_parent_orphans") or 0),
        "task_blob_orphans": int(report.get("task_blob_orphans") or 0),
        "missing_blob": int(report.get("missing_blob") or 0),
        "hash_mismatch": int(report.get("hash_mismatch") or 0),
        "online_mr_orphans": len(report.get("online_mr_orphan_task_ids") or []),
        "ground_orphans": len(report.get("ground_references") or []),
        "artifact_orphans": len(report.get("artifact_manifest_orphans") or []),
        "issues": list(report.get("issues") or []),
    }


def _snapshot(site_id: str, path: Path, data_root: Path) -> dict[str, Any]:
    state = _state(path)
    profile = _profile(path)
    audit = _audit_summary(site_id, path, data_root)
    if audit["status"] != "PASS":
        raise TaskResultCompactionError(f"task storage audit failed: {audit}")
    return {"state": state, "profile": profile, "audit": audit}


def _logical(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    profile = snapshot["profile"]
    return {
        "schema": profile["schema"],
        "tables": profile["tables"],
        "authority_digest": profile["authority_digest"],
        "task_result_rows": profile["task_result_rows"],
        "task_result_blob_rows": profile["task_result_blob_rows"],
        "canonical_bytes": profile["canonical_bytes"],
        "audit": snapshot["audit"],
    }


def _candidate_path(root: Path, operation_id: str) -> Path:
    if not operation_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for char in operation_id
    ):
        raise TaskResultCompactionError("unsafe compaction operation id")
    return (
        root
        / "staging"
        / "production-maintenance"
        / "task-result-compact"
        / operation_id
        / "tasks.db.candidate"
    )


def build_compaction_plan(
    tasks_db: str | Path,
    *,
    site_id: str,
    data_root: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(data_root).resolve(strict=True)
    path = Path(tasks_db).resolve(strict=True)
    if root != PRODUCTION_ROOT.resolve():
        raise TaskResultCompactionError("production compaction requires D:\\NetConsoleData")
    sites_root = (root / "sites").resolve(strict=True)
    site_directory = path.parent.parent
    if (
        path.name != "tasks.db"
        or site_directory.parent != sites_root
        or path.parent.name != "db"
    ):
        raise TaskResultCompactionError("target is not a registered direct-child tasks.db")
    snapshot = _snapshot(site_id, path, root)
    profile = snapshot["profile"]
    recommended = bool(
        int(profile["freelist_bytes"]) >= MIN_FREELIST_BYTES
        or float(profile["freelist_percent"]) >= MIN_FREELIST_PERCENT
    )
    body: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "site_id": str(site_id),
        "site_directory": site_directory.name,
        "data_root": str(root),
        "digest_scope": TARGET_SCOPE,
        "database": str(path),
        "source": snapshot,
        "threshold": {
            "freelist_bytes": MIN_FREELIST_BYTES,
            "freelist_percent": MIN_FREELIST_PERCENT,
        },
        "physical_compaction_recommended": recommended,
    }
    body["plan_digest"] = _digest(body)
    return body


def write_compaction_plan(plan: Mapping[str, Any], output: str | Path) -> Path:
    target = Path(output).resolve()
    if target.exists():
        raise TaskResultCompactionError(f"refusing to overwrite plan: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical(plan))
    return target


def _backup(source: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise TaskResultCompactionError(f"backup destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(_open(source, immutable=True)) as source_connection, closing(
        sqlite3.connect(destination)
    ) as target_connection:
        source_connection.backup(target_connection)
        target_connection.commit()
    profile = _profile(destination)
    return {
        "path": str(destination),
        "size_bytes": int(destination.stat().st_size),
        "sha256": _sha256(destination),
        "quick_check": profile["quick_check"],
        "integrity_check": profile["integrity_check"],
    }


def _build_candidate(source: Path, candidate: Path) -> None:
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists():
        raise TaskResultCompactionError(f"candidate already exists: {candidate}")
    with closing(_open(source, immutable=True)) as source_connection, closing(
        sqlite3.connect(candidate)
    ) as target_connection:
        source_connection.backup(target_connection)
        target_connection.commit()
    vacuumed = candidate.with_name(f"{candidate.name}.vacuum")
    try:
        with closing(_open(candidate, immutable=False)) as connection:
            connection.execute(f"VACUUM INTO {_quote(str(vacuumed))}")
        candidate.unlink()
        os.replace(vacuumed, candidate)
    finally:
        vacuumed.unlink(missing_ok=True)


def _remove_zero_sidecars(path: Path) -> None:
    for sidecar in (
        path.with_name(f"{path.name}-wal"),
        path.with_name(f"{path.name}-shm"),
    ):
        if sidecar.is_file():
            if sidecar.stat().st_size:
                raise TaskResultCompactionError(f"non-empty SQLite sidecar: {sidecar}")
            sidecar.unlink()


def _restore(backup: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.production-restore")
    temporary.unlink(missing_ok=True)
    with closing(_open(backup, immutable=True)) as source_connection, closing(
        sqlite3.connect(temporary)
    ) as target_connection:
        source_connection.backup(target_connection)
        target_connection.commit()
    _remove_zero_sidecars(destination)
    os.replace(temporary, destination)
    temporary.unlink(missing_ok=True)


def apply_compaction_plan(
    plan_path: str | Path,
    *,
    expected_plan_digest: str,
    backup_path: str | Path,
    authorization: str,
) -> dict[str, Any]:
    if authorization != AUTHORIZATION:
        raise TaskResultCompactionError("explicit production authorization is required")
    raw = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema") != PLAN_SCHEMA:
        raise TaskResultCompactionError("unsupported compaction plan")
    body = dict(raw)
    actual_digest = str(body.pop("plan_digest") or "")
    if actual_digest != expected_plan_digest or _digest(body) != actual_digest:
        raise TaskResultCompactionError("TASK_RESULT_COMPACTION_PLAN_DIGEST_MISMATCH")
    root = Path(str(raw["data_root"])).resolve(strict=True)
    source = Path(str(raw["database"])).resolve(strict=True)
    sites_root = (root / "sites").resolve(strict=True)
    expected_source = (sites_root / str(raw["site_directory"]) / "db" / "tasks.db").resolve()
    if (
        root != PRODUCTION_ROOT.resolve()
        or source.name != "tasks.db"
        or source.parent.parent.parent != sites_root
        or source != expected_source
    ):
        raise TaskResultCompactionError("invalid production tasks.db target")
    if not bool(raw.get("physical_compaction_recommended")):
        return {
            "status": "PASS",
            "mode": "SKIPPED_BELOW_THRESHOLD",
            "plan_digest": actual_digest,
            "database": str(source),
            "compacted": False,
            "reclaimed_bytes": 0,
        }
    backup = Path(backup_path).resolve()
    if backup.is_relative_to(root):
        raise TaskResultCompactionError("compaction backup must be outside production root")
    expected_snapshot = raw.get("source")
    if not isinstance(expected_snapshot, Mapping):
        raise TaskResultCompactionError("compaction source snapshot is missing")
    current = _snapshot(str(raw["site_id"]), source, root)
    if current != expected_snapshot:
        raise TaskResultCompactionError("STALE_SOURCE: target tasks.db changed after preview")
    backup_record = _backup(source, backup)
    operation_id = (
        f"task-result-compact-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    candidate = _candidate_path(root, operation_id)
    resolver = PathResolver(data_root=root)
    switched = False
    try:
        with database_maintenance_lock(
            resolver, site_database_maintenance_key(str(raw["site_id"]))
        ):
            current = _snapshot(str(raw["site_id"]), source, root)
            if current != expected_snapshot:
                raise TaskResultCompactionError("STALE_SOURCE: target changed before candidate build")
            _build_candidate(source, candidate)
            candidate_snapshot = _snapshot(str(raw["site_id"]), candidate, root)
            if _logical(candidate_snapshot) != _logical(expected_snapshot):
                raise TaskResultCompactionError("TASK_COMPACT_LOGICAL_PARITY_FAILED")
            if int(candidate_snapshot["profile"]["physical_bytes"]) >= int(
                expected_snapshot["profile"]["physical_bytes"]
            ):
                raise TaskResultCompactionError("TASK_COMPACT_NO_PHYSICAL_RECLAIM")
            _remove_zero_sidecars(source)
            os.replace(candidate, source)
            switched = True
            after = _snapshot(str(raw["site_id"]), source, root)
            if _logical(after) != _logical(expected_snapshot):
                raise TaskResultCompactionError("TASK_COMPACT_POSTCHECK_FAILED")
    except Exception as exc:
        if switched:
            try:
                _restore(backup, source)
            except Exception as restore_error:
                raise TaskResultCompactionError(
                    f"TASK_COMPACT_POSTCHECK_FAILED_AND_RESTORE_FAILED: {restore_error}"
                ) from restore_error
        raise exc
    finally:
        candidate.unlink(missing_ok=True)
        try:
            candidate.parent.rmdir()
        except OSError:
            pass
    return {
        "status": "PASS",
        "mode": "PRODUCTION_CANDIDATE_ATOMIC_REPLACE",
        "plan_digest": actual_digest,
        "database": str(source),
        "compacted": True,
        "backup": backup_record,
        "physical_bytes_before": int(expected_snapshot["profile"]["physical_bytes"]),
        "physical_bytes_after": int(after["profile"]["physical_bytes"]),
        "reclaimed_bytes": int(expected_snapshot["profile"]["physical_bytes"])
        - int(after["profile"]["physical_bytes"]),
        "page_size": int(after["profile"]["page_size"]),
        "page_count": int(after["profile"]["page_count"]),
        "freelist_count": int(after["profile"]["freelist_count"]),
        "freelist_bytes": int(after["profile"]["freelist_bytes"]),
        "freelist_percent": float(after["profile"]["freelist_percent"]),
        "quick_check": after["profile"]["quick_check"],
        "integrity_check": after["profile"]["integrity_check"],
        "task_count_unchanged": True,
        "event_count_unchanged": True,
        "result_count_unchanged": True,
        "blob_count_unchanged": True,
        "authority_verify": "PASS",
        "orphan_verify": "PASS",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("--tasks-db", type=Path, required=True)
    preview.add_argument("--site-id", required=True)
    preview.add_argument("--data-root", type=Path, default=PRODUCTION_ROOT)
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
        plan = build_compaction_plan(
            args.tasks_db,
            site_id=args.site_id,
            data_root=args.data_root,
        )
        output = write_compaction_plan(plan, args.output)
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
            apply_compaction_plan(
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
