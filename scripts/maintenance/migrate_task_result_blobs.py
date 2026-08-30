"""Dry-run/apply migration of task result bodies into shared compressed blobs.

This tool never performs VACUUM, WAL checkpointing, task deletion, or database
splitting.  ``--apply`` is intentionally limited to the DEV data root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from netconsole.repositories.task_result_blob_repository import (
    TASK_RESULT_BLOB_CODEC_ZLIB,
    TaskResultBlobError,
    ensure_blob,
    read_blob,
    verify_task_result_authority,
)


DEV_ROOT = Path(r"D:\NetConsoleData-dev")
ISOLATED_DEV_ROOT_PARENT = Path(r"D:\study\NetConsole-Workspace\test-data\NetConsole")
SCHEMA_COLUMNS = {
    "content_sha256": "TEXT NOT NULL DEFAULT ''",
    "blob_codec": "TEXT NOT NULL DEFAULT ''",
    "blob_ready": "INTEGER NOT NULL DEFAULT 0 CHECK(blob_ready IN (0, 1))",
}


def _quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _db_path(root: Path, site: str) -> Path:
    return root / "sites" / str(site) / "db" / "tasks.db"


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_allowed_apply_root(root: Path) -> bool:
    resolved = root.resolve()
    if resolved == DEV_ROOT.resolve():
        return True
    return (
        resolved.name == "NetConsoleData-dev"
        and _is_under(resolved, ISOLATED_DEV_ROOT_PARENT)
    )


def _open(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    else:
        connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        str(row["name"]) == column
        for row in conn.execute(f"PRAGMA table_info({_quote(table)})")
    )


def _install_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_result_blobs (
            content_sha256 TEXT PRIMARY KEY,
            codec TEXT NOT NULL CHECK(codec IN ('zlib')),
            compressed_blob BLOB NOT NULL,
            uncompressed_bytes INTEGER NOT NULL,
            compressed_bytes INTEGER NOT NULL,
            created_time TEXT NOT NULL,
            verified_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    for column, definition in SCHEMA_COLUMNS.items():
        if not _column_exists(conn, "task_results", column):
            conn.execute(
                f"ALTER TABLE task_results ADD COLUMN {column} {definition}"
            )
    conn.execute("DROP TRIGGER IF EXISTS trg_task_results_immutable")
    conn.execute(
        """
        CREATE TRIGGER trg_task_results_immutable
        BEFORE UPDATE ON task_results
        WHEN NOT (
            OLD.result_id = NEW.result_id
            AND OLD.task_id = NEW.task_id
            AND OLD.terminal_event_type = NEW.terminal_event_type
            AND OLD.canonical_json = NEW.canonical_json
            AND OLD.sha256 = NEW.sha256
            AND OLD.byte_size = NEW.byte_size
            AND OLD.schema_version = NEW.schema_version
            AND OLD.created_time = NEW.created_time
            AND (
                (OLD.content_sha256 = NEW.content_sha256
                 AND OLD.blob_codec = NEW.blob_codec
                 AND OLD.blob_ready = NEW.blob_ready)
                OR (OLD.blob_ready = 0
                    AND NEW.blob_ready = 1
                    AND NEW.content_sha256 = OLD.sha256
                    AND NEW.blob_codec = 'zlib')
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'task_results rows are immutable');
        END;
        """
    )


def _rows(conn: sqlite3.Connection, *, limit: int | None, resume: bool) -> Iterable[sqlite3.Row]:
    if not _table_exists(conn, "task_results"):
        return []
    clauses = []
    has_ready = _column_exists(conn, "task_results", "blob_ready")
    if resume and has_ready:
        clauses.append("COALESCE(blob_ready, 0) <> 1")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit_sql = " LIMIT ?" if limit is not None else ""
    params: tuple[object, ...] = (max(0, int(limit)),) if limit is not None else ()
    content_column = "content_sha256" if _column_exists(conn, "task_results", "content_sha256") else "''"
    codec_column = "blob_codec" if _column_exists(conn, "task_results", "blob_codec") else "''"
    ready_column = "blob_ready" if has_ready else "0"
    return conn.execute(
        "SELECT result_id, task_id, terminal_event_type, canonical_json, sha256, "
        f"byte_size, schema_version, created_time, {content_column} AS content_sha256, "
        f"{codec_column} AS blob_codec, {ready_column} AS blob_ready "
        f"FROM task_results{where} ORDER BY result_id{limit_sql}",
        params,
    )


def _canonical_metrics(rows: Iterable[sqlite3.Row]) -> dict[str, Any]:
    result_ids = 0
    already_blobbed = 0
    candidate_results = 0
    unique_contents: set[str] = set()
    content_counts: Counter[str] = Counter()
    uncompressed_bytes = 0
    compressed_bytes = 0
    failed = 0
    hash_mismatch = 0
    for row in rows:
        result_ids += 1
        if int(row["blob_ready"] or 0) == 1:
            already_blobbed += 1
            continue
        candidate_results += 1
        canonical = str(row["canonical_json"] or "")
        encoded = canonical.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        expected = str(row["sha256"] or "")
        if digest != expected or len(encoded) != int(row["byte_size"] or -1):
            hash_mismatch += 1
            continue
        try:
            parsed = json.loads(canonical)
        except json.JSONDecodeError:
            failed += 1
            continue
        if not isinstance(parsed, dict):
            failed += 1
            continue
        unique_contents.add(digest)
        content_counts[digest] += 1
        uncompressed_bytes += len(encoded)
        compressed_bytes += len(zlib.compress(encoded, level=6))
    duplicate_contents = sum(max(0, count - 1) for count in content_counts.values())
    return {
        "total_results": result_ids,
        "already_blobbed": already_blobbed,
        "candidate_results": candidate_results,
        "unique_contents": len(unique_contents),
        "duplicate_contents": duplicate_contents,
        "uncompressed_bytes": uncompressed_bytes,
        "compressed_bytes": compressed_bytes,
        "estimated_saved_bytes": max(0, uncompressed_bytes - compressed_bytes),
        "written_blobs": 0,
        "verified_blobs": 0,
        "failed": failed,
        "hash_mismatch": hash_mismatch,
        "duplicate_payload_rows": duplicate_contents,
        "obsolete_snapshot_rows": 0,
        "estimated_reclaimable_bytes": max(0, uncompressed_bytes - compressed_bytes),
    }


def _task_row_metrics(conn: sqlite3.Connection) -> dict[str, int]:
    def count(table: str) -> int:
        if not _table_exists(conn, table):
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])

    return {
        "task_rows": count("task_snapshots"),
        "snapshot_rows": count("task_snapshots"),
        "event_rows": count("task_events"),
        "result_rows": count("task_results"),
    }


def _verify_existing(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    if int(row["blob_ready"] or 0) != 1:
        return
    digest = str(row["content_sha256"] or "")
    if digest != str(row["sha256"] or "") or str(row["blob_codec"] or "") != TASK_RESULT_BLOB_CODEC_ZLIB:
        raise TaskResultBlobError("task result blob metadata mismatch")
    read_blob(conn, content_sha256=digest, expected_bytes=int(row["byte_size"] or -1))


def _rollout_state(conn: sqlite3.Connection) -> str:
    if not _table_exists(conn, "task_result_storage_rollout"):
        return "LEGACY_UNTRACKED"
    row = conn.execute(
        "SELECT state FROM task_result_storage_rollout WHERE singleton_id=1"
    ).fetchone()
    return str(row[0] or "LEGACY_UNTRACKED") if row is not None else "LEGACY_UNTRACKED"


def _authority_audit(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return a fail-closed physical/reference audit after migration.

    A rollout flag is only meaningful together with its physical schema.  The
    audit deliberately verifies every ready Blob instead of trusting the
    legacy ``canonical_json`` projection as a fallback.
    """

    required_blob_columns = {
        "content_sha256",
        "codec",
        "compressed_blob",
        "uncompressed_bytes",
        "compressed_bytes",
        "created_time",
        "verified_at",
    }
    required_result_columns = {"content_sha256", "blob_codec", "blob_ready"}
    result_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(task_results)").fetchall()
    } if _table_exists(conn, "task_results") else set()
    blob_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(task_result_blobs)").fetchall()
    } if _table_exists(conn, "task_result_blobs") else set()
    schema_ready = required_result_columns <= result_columns and required_blob_columns <= blob_columns
    audit: dict[str, Any] = {
        "rollout_state": _rollout_state(conn),
        "physical_schema_ready": schema_ready,
        "task_result_blobs_exists": _table_exists(conn, "task_result_blobs"),
        "task_result_columns": sorted(result_columns),
        "task_blob_columns": sorted(blob_columns),
        "task_result_parent_orphans": 0,
        "task_blob_orphans": 0,
        "missing_blob": 0,
        "hash_mismatch": 0,
        "not_ready_rows": 0,
        "invalid_authority_rows": 0,
    }
    if not _table_exists(conn, "task_results"):
        audit["status"] = "PASS"
        return audit
    if not schema_ready:
        audit["status"] = "FAIL"
        return audit

    audit["task_result_parent_orphans"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM task_results r "
            "LEFT JOIN task_snapshots s ON s.task_id=r.task_id "
            "WHERE s.task_id IS NULL"
        ).fetchone()[0]
    ) if _table_exists(conn, "task_snapshots") else int(
        conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
    )
    audit["missing_blob"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM task_results r "
            "LEFT JOIN task_result_blobs b ON b.content_sha256=r.content_sha256 "
            "WHERE r.blob_ready=1 AND (r.content_sha256='' OR b.content_sha256 IS NULL)"
        ).fetchone()[0]
    )
    audit["not_ready_rows"] = int(
        conn.execute("SELECT COUNT(*) FROM task_results WHERE blob_ready<>1").fetchone()[0]
    )
    audit["task_blob_orphans"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM task_result_blobs b "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM task_results r "
            "WHERE r.blob_ready=1 AND r.content_sha256=b.content_sha256)"
        ).fetchone()[0]
    )
    for raw in conn.execute("SELECT * FROM task_results ORDER BY result_id").fetchall():
        row = dict(raw)
        try:
            if int(row.get("blob_ready") or 0) != 1:
                audit["invalid_authority_rows"] += 1
                continue
            if (
                str(row.get("content_sha256") or "") != str(row.get("sha256") or "")
                or str(row.get("blob_codec") or "") != TASK_RESULT_BLOB_CODEC_ZLIB
            ):
                audit["hash_mismatch"] += 1
                continue
            verified = verify_task_result_authority(conn, row)
            if str(verified.get("sha256") or "") != str(row.get("sha256") or ""):
                audit["hash_mismatch"] += 1
        except (TaskResultBlobError, sqlite3.DatabaseError, TypeError, ValueError):
            audit["hash_mismatch"] += 1
    audit["status"] = "PASS" if not any(
        int(audit[key])
        for key in (
            "task_result_parent_orphans",
            "task_blob_orphans",
            "missing_blob",
            "hash_mismatch",
            "not_ready_rows",
            "invalid_authority_rows",
        )
    ) else "FAIL"
    return audit


def migrate_database(
    site: str,
    db_path: Path,
    *,
    apply: bool,
    limit: int | None,
    batch_size: int,
    verify: bool,
    resume: bool,
) -> dict[str, Any]:
    connection = _open(db_path, read_only=not apply)
    try:
        if not _table_exists(connection, "task_results"):
            return {"site": site, "db_path": str(db_path), "total_results": 0, "status": "NO_TASK_RESULTS"}
        if not apply:
            metrics = _canonical_metrics(_rows(connection, limit=limit, resume=resume))
            authority = _authority_audit(connection)
            return {
                "site": site,
                "db_path": str(db_path),
                "mode": "DRY_RUN",
                **_task_row_metrics(connection),
                **metrics,
                "status": "PASS" if authority["status"] == "PASS" else "FAIL",
                "authority": authority,
            }

        connection.execute("BEGIN IMMEDIATE")
        _install_schema(connection)
        connection.commit()
        metrics = _canonical_metrics(_rows(connection, limit=limit, resume=resume))
        metrics.update(_task_row_metrics(connection))
        metrics.update({"written_blobs": 0, "verified_blobs": 0})
        processed = 0
        batch: list[sqlite3.Row] = []
        for row in _rows(connection, limit=limit, resume=resume):
            batch.append(row)
            if len(batch) < max(1, int(batch_size)):
                continue
            _apply_batch(connection, batch, metrics, verify=verify)
            processed += len(batch)
            batch = []
        if batch:
            _apply_batch(connection, batch, metrics, verify=verify)
            processed += len(batch)
        authority = _authority_audit(connection)
        metrics["processed_rows"] = processed
        metrics["mode"] = "APPLY"
        metrics["status"] = "PASS" if authority["status"] == "PASS" else "FAIL"
        return {"site": site, "db_path": str(db_path), **metrics, "authority": authority}
    finally:
        connection.close()


def _apply_batch(
    connection: sqlite3.Connection,
    rows: list[sqlite3.Row],
    metrics: dict[str, Any],
    *,
    verify: bool,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    first_error: Exception | None = None
    try:
        for row in rows:
            try:
                if int(row["blob_ready"] or 0) == 1:
                    if verify:
                        _verify_existing(connection, row)
                        metrics["verified_blobs"] += 1
                    continue
                canonical = str(row["canonical_json"] or "")
                encoded = canonical.encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
                if digest != str(row["sha256"] or "") or len(encoded) != int(row["byte_size"] or -1):
                    metrics["hash_mismatch"] += 1
                    first_error = first_error or TaskResultBlobError(
                        f"task result hash/size mismatch: {row['result_id']}"
                    )
                    continue
                parsed = json.loads(canonical)
                if not isinstance(parsed, dict):
                    metrics["failed"] += 1
                    first_error = first_error or TaskResultBlobError(
                        f"task result JSON is not an object: {row['result_id']}"
                    )
                    continue
                ensure_blob(
                    connection,
                    canonical_json=canonical,
                    content_sha256=digest,
                    created_time=str(row["created_time"] or ""),
                    verified_at=str(row["created_time"] or ""),
                )
                connection.execute(
                    "UPDATE task_results SET content_sha256=?, blob_codec=?, blob_ready=1 "
                    "WHERE result_id=? AND blob_ready<>1",
                    (digest, TASK_RESULT_BLOB_CODEC_ZLIB, str(row["result_id"])),
                )
                metrics["verified_blobs"] += 1
                if verify:
                    read_blob(connection, content_sha256=digest, expected_bytes=len(encoded))
                metrics["written_blobs"] += 1
            except (TaskResultBlobError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
                metrics["failed"] += 1
                first_error = first_error or exc
        if first_error is not None:
            connection.rollback()
            raise TaskResultBlobError(
                f"task result Blob migration batch failed: {first_error}"
            ) from first_error
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _resolve(root: Path, site: str | None, all_sites: bool) -> list[tuple[str, Path]]:
    registry_path = root / "config" / "site_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"局点 Registry 不可读，拒绝扫描未登记目录: {registry_path}") from exc
    raw_sites = registry.get("sites") if isinstance(registry, dict) else None
    if not isinstance(raw_sites, list):
        raise SystemExit("局点 Registry 缺少 sites，拒绝扫描未登记目录")
    sites_root = (root / "sites").resolve()
    registered: dict[str, Path] = {}
    for item in raw_sites:
        if not isinstance(item, dict):
            continue
        site_id = str(item.get("site_id") or "").strip().casefold()
        relative = Path(str(item.get("relative_path") or f"sites/{site_id}"))
        if not site_id or relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("局点 Registry 存在越界或空 site_id，拒绝迁移扫描")
        site_root = (root / relative).resolve()
        raw_root = root / relative
        if (
            raw_root.is_symlink()
            or site_root.parent != sites_root
            or not site_root.is_dir()
        ):
            raise SystemExit(f"局点 Registry 路径无效，拒绝迁移扫描: {site_id}")
        if site_id in registered:
            raise SystemExit(f"局点 Registry 存在重复 site_id: {site_id}")
        task_db = site_root / "db" / "tasks.db"
        if task_db.is_file() and not task_db.is_symlink():
            registered[site_id] = task_db
    if site:
        wanted = str(site).strip().casefold()
        if wanted not in registered:
            raise SystemExit(f"site 未登记或缺少 tasks.db，拒绝扫描: {site}")
        return [(wanted, registered[wanted])]
    if not all_sites:
        raise SystemExit("必须指定 --site 或 --all-sites")
    return sorted(registered.items(), key=lambda item: item[0])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="task_results -> task_result_blobs 迁移")
    parser.add_argument("--data-root", type=Path, default=DEV_ROOT)
    parser.add_argument("--site")
    parser.add_argument("--all-sites", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="显式选择默认的只读模式")
    parser.add_argument("--apply", action="store_true", help="显式写入 DEV tasks.db；默认 dry-run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.apply and args.dry_run:
        raise SystemExit("--apply 与 --dry-run 不能同时使用")
    root = args.data_root.resolve()
    if args.apply and not _is_allowed_apply_root(root):
        raise SystemExit(
            "--apply 只允许 D:\\NetConsoleData-dev 或 D:\\study\\NetConsole-Workspace\\test-data\\NetConsole 下的隔离 NetConsoleData-dev 副本"
        )
    targets = _resolve(root, args.site, args.all_sites)
    reports: list[dict[str, Any]] = []
    for site, path in targets:
        if not path.is_file():
            reports.append({"site": site, "db_path": str(path), "status": "MISSING"})
            continue
        reports.append(
            migrate_database(
                site,
                path,
                apply=bool(args.apply),
                limit=args.limit if args.limit is None else max(0, int(args.limit)),
                batch_size=max(1, int(args.batch_size)),
                verify=bool(args.verify),
                resume=bool(args.resume),
            )
        )
    status = "PASS" if all(
        str(report.get("status") or "PASS") in {"PASS", "NO_TASK_RESULTS"}
        for report in reports
    ) else "FAIL"
    print(json.dumps({"schema": "task-result-blobs-migration/v1", "apply": bool(args.apply), "status": status, "reports": reports}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
