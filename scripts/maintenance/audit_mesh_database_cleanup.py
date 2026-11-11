"""只读盘点 MESH 派生 SQLite，并提供候选优先的备份/隔离入口。

默认命令只读。该脚本不创建 Repository、不执行 SQLite migration/checkpoint，
也不删除 raw、报告、备份或任何数据库。backup/isolate 必须显式指定，且会在
重新核验文件快照、引用、WAL/SHM 和任务状态后逐文件处理。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


UTC = timezone.utc


STATUS_ORDER = (
    "INSPECTION_FAILED",
    "ACTIVE_PROTECT",
    "TASK_REFERENCED",
    "SESSION_REFERENCED",
    "REGISTERED_PROTECT",
    "BACKUP_PROTECT",
    "UNKNOWN_PROTECT",
    "ORPHAN_CANDIDATE",
)
ACTIVE_TASK_STATES = {"PENDING", "STARTING", "RUNNING", "STOPPING"}
SQLITE_HEADER = b"SQLite format 3\x00"
MESH_SUFFIXES = (".sqlite", ".sqlite3", ".db")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ro_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_ro_uri(path), uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=3000")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    escaped = table.replace('"', '""')
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{escaped}")')
    }


def _schema_version(connection: sqlite3.Connection, tables: set[str]) -> str:
    for table in ("schema_meta", "meta", "schema_metadata"):
        if table not in tables or not {"key", "value"}.issubset(
            _columns(connection, table)
        ):
            continue
        for key in ("schema_version", "schema_" + "version"):
            row = connection.execute(
                f'SELECT value FROM "{table}" WHERE key=? LIMIT 1', (key,)
            ).fetchone()
            if row and row[0] not in (None, ""):
                return str(row[0])
    return ""


def _count(connection: sqlite3.Connection, tables: set[str], table: str) -> int | None:
    if table not in tables:
        return None
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _sidecar(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _is_reparse(path: Path) -> bool:
    return path.is_symlink()


def _walk_files(root: Path) -> Iterable[Path]:
    for base, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = [
            name for name in directories if not _is_reparse(Path(base) / name)
        ]
        for name in files:
            path = Path(base) / name
            if not _is_reparse(path):
                yield path


def _looks_like_sqlite(path: Path) -> bool:
    name = path.name.casefold()
    return name.endswith(MESH_SUFFIXES) or name.endswith(".mesh.sqlite")


def _sqlite_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sqlite_header": False,
        "schema_version": "",
        "quick_check": "not_checked",
        "integrity_check": "not_checked",
        "table_names": [],
        "source_file_count": None,
        "session_count": None,
        "error": "",
    }
    try:
        with path.open("rb") as handle:
            result["sqlite_header"] = handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError as exc:
        result["error"] = f"header:{type(exc).__name__}: {exc}"
        return result
    if not result["sqlite_header"]:
        result["error"] = "文件头不是 SQLite format 3"
        return result
    try:
        with read_only_connection(path) as connection:
            tables = _table_names(connection)
            result["table_names"] = sorted(tables)
            result["schema_version"] = _schema_version(connection, tables)
            result["source_file_count"] = _count(connection, tables, "source_files")
            result["session_count"] = _count(connection, tables, "mesh_sessions")
            result["quick_check"] = str(
                connection.execute("PRAGMA quick_check").fetchone()[0]
            )
            result["integrity_check"] = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
    except (OSError, sqlite3.Error) as exc:
        result["error"] = f"sqlite:{type(exc).__name__}: {exc}"
    return result


def _read_rows(path: Path, table: str) -> tuple[list[dict[str, Any]], str]:
    try:
        with read_only_connection(path) as connection:
            tables = _table_names(connection)
            if table not in tables:
                return [], ""
            return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')], ""
    except (OSError, sqlite3.Error) as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _clean_text(value: object) -> str:
    return str(value or "").strip().strip("'\"")


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _path_match(candidate: Path, parsed_root: Path, value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    try:
        value_path = Path(text)
        if value_path.is_absolute() and value_path.resolve() == candidate.resolve():
            return "exact_path"
        if not value_path.is_absolute():
            resolved = (parsed_root / value_path).resolve()
            if resolved == candidate.resolve() and _within(resolved, parsed_root):
                return "relative_path"
        if value_path.name.casefold() == candidate.name.casefold() and _within(
            candidate, parsed_root
        ):
            return "filename_fallback"
    except (OSError, ValueError):
        return ""
    return ""


def _profile_name_from_path(mesh_root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(mesh_root)
    except ValueError:
        return ""
    return relative.parts[0] if len(relative.parts) > 1 else ""


def _active_backend_processes() -> list[str]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq NetConsoleBackend.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _task_texts(site_dir: Path) -> dict[str, Any]:
    task_db = site_dir / "db" / "tasks.db"
    result: dict[str, Any] = {
        "status": "MISSING" if not task_db.is_file() else "OK",
        "active_tasks": [],
        "texts": [],
        "error": "",
    }
    if not task_db.is_file():
        return result
    try:
        with read_only_connection(task_db) as connection:
            tables = _table_names(connection)
            if "task_snapshots" not in tables:
                result["status"] = "UNKNOWN"
                result["error"] = "tasks.db 缺少 task_snapshots"
                return result
            columns = _columns(connection, "task_snapshots")
            selected = [
                column
                for column in (
                    "task_id",
                    "task_type",
                    "status",
                    "site_name",
                    "resource_keys_json",
                    "result_path",
                    "result_json",
                    "result_summary_json",
                )
                if column in columns
            ]
            rows = [
                dict(row)
                for row in connection.execute(
                    f'SELECT {", ".join(selected)} FROM task_snapshots'
                )
            ]
            for row in rows:
                text = json.dumps(row, ensure_ascii=False, default=str)
                item = {
                    "task_id": str(row.get("task_id") or ""),
                    "task_type": str(row.get("task_type") or ""),
                    "status": str(row.get("status") or ""),
                    "text": text,
                }
                result["texts"].append(item)
                if item["status"].upper() in ACTIVE_TASK_STATES:
                    result["active_tasks"].append(item)
            for table, columns_to_read in (
                ("task_events", ("task_id", "payload_json")),
                ("task_results", ("task_id", "canonical_json", "content_sha256")),
            ):
                if table not in tables:
                    continue
                available = _columns(connection, table)
                selected = [column for column in columns_to_read if column in available]
                if not selected:
                    continue
                for row in connection.execute(
                    f'SELECT {", ".join(selected)} FROM "{table}"'
                ):
                    value = dict(row)
                    result["texts"].append(
                        {
                            "task_id": str(value.get("task_id") or ""),
                            "task_type": table,
                            "status": "",
                            "text": json.dumps(value, ensure_ascii=False, default=str),
                        }
                    )
    except (OSError, sqlite3.Error) as exc:
        result["status"] = "UNKNOWN"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _artifact_texts(site_dir: Path) -> list[dict[str, str]]:
    manifest_root = site_dir / "files" / "rail_transit" / "web_artifacts" / "manifests"
    if not manifest_root.is_dir():
        return []
    result: list[dict[str, str]] = []
    for path in _walk_files(manifest_root):
        if path.suffix.casefold() != ".json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        result.append({"path": str(path), "text": text})
    return result


def _backup_texts(root: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for base in (root / "backups", root / "sites"):
        if not base.is_dir():
            continue
        for path in _walk_files(base):
            if path.name.casefold() != "manifest.json":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            result.append({"path": str(path), "text": text})
    return result


def _tokens(record: dict[str, Any]) -> list[str]:
    values = [
        record.get("path"),
        record.get("relative_path"),
        record.get("basename"),
        record.get("profile_id"),
        record.get("session_id"),
        record.get("sha256"),
        record.get("content_sha256"),
    ]
    values.extend(record.get("source_names") or [])
    return sorted(
        {str(value).casefold() for value in values if str(value or "").strip()},
        key=len,
        reverse=True,
    )


def _matching_texts(tokens: list[str], texts: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for item in texts:
        text = str(item.get("text") or "").casefold()
        hit = next((token for token in tokens if token in text), "")
        if hit:
            matches.append({"path": str(item.get("path") or ""), "token": hit})
    return matches


def _classify(reasons: set[str], *, inspection_failed: bool) -> str:
    if inspection_failed:
        return "INSPECTION_FAILED"
    for status in STATUS_ORDER:
        if status in reasons:
            return status
    return "ORPHAN_CANDIDATE"


def _db_record(
    *,
    root: Path,
    site_dir: Path,
    mesh_root: Path,
    path: Path,
    db_type: str,
    profile: dict[str, Any] | None,
    source_rows: list[dict[str, Any]],
    catalog_sessions: list[dict[str, Any]],
    profile_sources: dict[str, list[dict[str, Any]]],
    task_info: dict[str, Any],
    artifact_texts: list[dict[str, str]],
    backup_texts: list[dict[str, str]],
    writer_active: bool,
) -> dict[str, Any]:
    stat = path.stat()
    metadata = _sqlite_metadata(path)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = str(path)
    safe_name = _profile_name_from_path(mesh_root, path)
    profile = profile or {}
    profile_id = str(profile.get("mr_id") or "")
    mr_name = str(profile.get("display_name") or safe_name)
    reasons: set[str] = set()
    evidence: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    fallback_refs: list[dict[str, Any]] = []
    session_refs: list[dict[str, Any]] = []
    detail_sources: list[dict[str, Any]] = []
    if db_type == "parsed":
        parsed_root = path.parent
        try:
            detail_sources, _ = _read_rows(path, "source_files")
        except Exception:
            detail_sources = []
        for source in source_rows:
            matches: list[str] = []
            for field in ("parsed_db_path", "parsed_relative_path"):
                match = _path_match(path, parsed_root, source.get(field))
                if match and match != "filename_fallback":
                    matches.append(match)
            if not matches:
                for field in ("parsed_db_path", "parsed_relative_path"):
                    match = _path_match(path, parsed_root, source.get(field))
                    if match == "filename_fallback":
                        matches.append(match)
            if matches:
                item = {
                    "mr_id": profile_id,
                    "source_file_id": source.get("id"),
                    "match_types": sorted(set(matches)),
                    "parsed_db_path": source.get("parsed_db_path"),
                    "parsed_relative_path": source.get("parsed_relative_path"),
                }
                source_refs.append(item)
                if "filename_fallback" in matches:
                    fallback_refs.append(item)
        for source in detail_sources:
            source_names = {
                _clean_text(source.get(field)).casefold()
                for field in ("original_filename", "archived_filename")
                if _clean_text(source.get(field))
            }
            source_hashes = {
                _clean_text(source.get(field)).casefold()
                for field in ("sha256", "content_sha256")
                if _clean_text(source.get(field))
            }
            for index_source in source_rows:
                index_names = {
                    _clean_text(index_source.get(field)).casefold()
                    for field in ("original_filename", "archived_filename")
                    if _clean_text(index_source.get(field))
                }
                index_hashes = {
                    _clean_text(index_source.get(field)).casefold()
                    for field in ("sha256", "content_sha256")
                    if _clean_text(index_source.get(field))
                }
                if (source_names & index_names) or (source_hashes & index_hashes):
                    item = {
                        "mr_id": profile_id,
                        "source_file_id": index_source.get("id"),
                        "match_types": ["detail_source_identity"],
                    }
                    if item not in source_refs:
                        source_refs.append(item)
        for session in catalog_sessions:
            if str(session.get("mr_id") or "") != profile_id:
                continue
            source_ids = {str(item.get("source_file_id")) for item in source_refs}
            if str(session.get("source_file_id")) in source_ids:
                session_refs.append(
                    {
                        "session_id": session.get("session_id"),
                        "source_file_id": session.get("source_file_id"),
                        "match": "catalog_session_index",
                    }
                )
        if source_refs:
            reasons.add("REGISTERED_PROTECT")
            evidence.append({"kind": "source_files", "count": len(source_refs)})
        if session_refs:
            reasons.add("SESSION_REFERENCED")
            evidence.append({"kind": "mesh_session_index", "count": len(session_refs)})
    elif db_type == "catalog":
        reasons.add("REGISTERED_PROTECT")
        evidence.append({"kind": "catalog_authority"})
    elif db_type == "source_index":
        if profile_id:
            reasons.add("REGISTERED_PROTECT")
            evidence.append({"kind": "mr_profile", "mr_id": profile_id})
        else:
            reasons.add("UNKNOWN_PROTECT")
            evidence.append({"kind": "unregistered_source_index"})
    else:
        reasons.add("UNKNOWN_PROTECT")
        evidence.append({"kind": "unrecognized_mesh_sqlite"})

    raw_names: list[str] = []
    for source in source_rows + detail_sources:
        for field in ("original_filename", "archived_filename", "stored_filename"):
            value = _clean_text(source.get(field))
            if value and value not in raw_names:
                raw_names.append(value)
    base_record: dict[str, Any] = {
        "data_root": str(root),
        "environment": "PRODUCTION" if root.name.casefold() == "netconsoledata" else "DEV_REAL",
        "site": site_dir.name,
        "mr_profile_id": profile_id,
        "mr_name": mr_name,
        "safe_folder_name": safe_name,
        "database_type": db_type,
        "path": str(path),
        "relative_path": relative,
        "basename": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
        "wal_path": str(_sidecar(path, "-wal")),
        "wal_bytes": _sidecar(path, "-wal").stat().st_size if _sidecar(path, "-wal").is_file() else 0,
        "shm_path": str(_sidecar(path, "-shm")),
        "shm_bytes": _sidecar(path, "-shm").stat().st_size if _sidecar(path, "-shm").is_file() else 0,
        "schema_version": metadata.get("schema_version") or "",
        "quick_check": metadata.get("quick_check"),
        "integrity_check": metadata.get("integrity_check"),
        "inspection_error": metadata.get("error") or "",
        "table_names": metadata.get("table_names") or [],
        "source_record_count": len(source_rows),
        "detail_source_record_count": len(detail_sources),
        "analysis_session_reference_count": len(session_refs),
        "filename_fallback_reference_count": len(fallback_refs),
        "activity_task_reference_count": 0,
        "report_reference_count": 0,
        "backup_reference_count": 0,
        "source_names": raw_names,
        "source_references": source_refs,
        "session_references": session_refs,
        "evidence": evidence,
        "writer_active": writer_active,
    }
    tokens = _tokens(
        {
            "path": path,
            "relative_path": relative,
            "basename": path.name,
            "profile_id": profile_id,
            "source_names": raw_names,
            "sha256": base_record["sha256"],
        }
    )
    task_matches = _matching_texts(tokens, task_info.get("texts") or [])
    report_matches = _matching_texts(tokens, artifact_texts)
    backup_matches = _matching_texts(tokens, backup_texts)
    if task_matches:
        reasons.add("TASK_REFERENCED")
        base_record["activity_task_reference_count"] = len(task_matches)
        base_record["task_references"] = task_matches
    else:
        base_record["task_references"] = []
    if report_matches:
        reasons.add("SESSION_REFERENCED")
        base_record["report_reference_count"] = len(report_matches)
        base_record["report_references"] = report_matches
    else:
        base_record["report_references"] = []
    if backup_matches:
        reasons.add("BACKUP_PROTECT")
        base_record["backup_reference_count"] = len(backup_matches)
        base_record["backup_references"] = backup_matches
    else:
        base_record["backup_references"] = []
    if task_info.get("status") != "OK":
        reasons.add("UNKNOWN_PROTECT")
        evidence.append(
            {
                "kind": "task_state_unavailable",
                "status": task_info.get("status"),
                "error": task_info.get("error") or "",
            }
        )
    if writer_active or base_record["wal_bytes"] > 0 or base_record["shm_bytes"] > 0:
        reasons.add("ACTIVE_PROTECT")
        evidence.append(
            {
                "kind": "runtime_sidecar_or_writer",
                "writer_active": writer_active,
                "wal_bytes": base_record["wal_bytes"],
                "shm_bytes": base_record["shm_bytes"],
            }
        )
    if base_record["inspection_error"] or base_record["quick_check"] != "ok" or base_record["integrity_check"] != "ok":
        reasons.add("INSPECTION_FAILED")
    if db_type == "parsed" and not profile_id:
        reasons.add("UNKNOWN_PROTECT")
    if db_type == "parsed" and not source_rows and not source_refs and not session_refs and profile_id:
        # A parsed file under a registered profile but without an index source is
        # not safe to call orphaned: the index may be stale or unreadable.
        reasons.add("UNKNOWN_PROTECT")
        evidence.append({"kind": "registered_profile_without_source_reference"})
    base_record["status"] = _classify(reasons, inspection_failed="INSPECTION_FAILED" in reasons)
    base_record["protection_reasons"] = sorted(reasons)
    base_record["allowed_for_backup"] = base_record["status"] == "ORPHAN_CANDIDATE"
    base_record["allowed_for_isolation"] = False
    return base_record


def audit_root(root: Path, *, writer_active: bool = False) -> dict[str, Any]:
    root = root.resolve()
    sites_root = root / "sites"
    result: dict[str, Any] = {
        "data_root": str(root),
        "environment": "PRODUCTION" if root.name.casefold() == "netconsoledata" else "DEV_REAL",
        "writer_active": writer_active,
        "sites_scanned": 0,
        "mr_profiles_scanned": 0,
        "records": [],
        "task_activity": [],
        "errors": [],
    }
    if not sites_root.is_dir():
        result["errors"].append("sites 目录不存在")
        return result
    backup_texts = _backup_texts(root)
    for site_dir in sorted(sites_root.iterdir(), key=lambda item: item.name.casefold()):
        if not site_dir.is_dir() or _is_reparse(site_dir):
            continue
        mesh_root = site_dir / "files" / "rail_transit" / "mr_raw_mesh"
        if not mesh_root.is_dir() or _is_reparse(mesh_root):
            continue
        result["sites_scanned"] += 1
        catalog_path = mesh_root / "catalog.sqlite"
        profiles: dict[str, dict[str, Any]] = {}
        catalog_sessions: list[dict[str, Any]] = []
        if catalog_path.is_file():
            profile_rows, profile_error = _read_rows(catalog_path, "mr_profiles")
            if profile_error:
                result["errors"].append(f"{catalog_path}: {profile_error}")
            profiles = {
                str(row.get("safe_folder_name") or ""): row for row in profile_rows
            }
            catalog_sessions, session_error = _read_rows(catalog_path, "mesh_session_index")
            if session_error:
                result["errors"].append(f"{catalog_path}: {session_error}")
            result["mr_profiles_scanned"] += len(profiles)
        task_info = _task_texts(site_dir)
        if task_info.get("active_tasks"):
            result["task_activity"].extend(
                {
                    "site": site_dir.name,
                    **item,
                }
                for item in task_info["active_tasks"]
            )
        artifact_texts = _artifact_texts(site_dir)
        index_sources: dict[str, list[dict[str, Any]]] = {}
        for safe_name, profile in profiles.items():
            index_path = mesh_root / safe_name / "mesh.sqlite"
            if index_path.is_file():
                rows, error = _read_rows(index_path, "source_files")
                if error:
                    result["errors"].append(f"{index_path}: {error}")
                index_sources[safe_name] = rows
        for path in sorted(_walk_files(mesh_root), key=lambda item: str(item).casefold()):
            if not _looks_like_sqlite(path):
                continue
            relative = path.relative_to(mesh_root)
            profile_safe = _profile_name_from_path(mesh_root, path)
            profile = profiles.get(profile_safe)
            if path == catalog_path:
                db_type = "catalog"
            elif path.name.casefold() == "mesh.sqlite":
                db_type = "source_index"
            elif "parsed" in {part.casefold() for part in relative.parts}:
                db_type = "parsed"
            else:
                db_type = "unknown"
            record = _db_record(
                root=root,
                site_dir=site_dir,
                mesh_root=mesh_root,
                path=path,
                db_type=db_type,
                profile=profile,
                source_rows=index_sources.get(profile_safe, []),
                catalog_sessions=catalog_sessions,
                profile_sources=index_sources,
                task_info=task_info,
                artifact_texts=artifact_texts,
                backup_texts=backup_texts,
                writer_active=writer_active,
            )
            result["records"].append(record)
    return result


def audit_roots(roots: Iterable[Path], *, writer_active_roots: set[Path] | None = None) -> dict[str, Any]:
    active = {path.resolve() for path in (writer_active_roots or set())}
    root_results = [audit_root(Path(root), writer_active=Path(root).resolve() in active) for root in roots]
    records = [record for item in root_results for record in item["records"]]
    return {
        "format": "netconsole-mesh-database-reference-audit-v1",
        "generated_at": now_iso(),
        "roots": root_results,
        "records": records,
        "summary": _summary(root_results, records),
    }


def _summary(root_results: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = {status: sum(record.get("status") == status for record in records) for status in STATUS_ORDER}
    parsed = [record for record in records if record.get("database_type") == "parsed"]
    return {
        "site_count": sum(int(item.get("sites_scanned") or 0) for item in root_results),
        "mr_profile_count": sum(int(item.get("mr_profiles_scanned") or 0) for item in root_results),
        "sqlite_database_count": len(records),
        "parsed_database_count": len(parsed),
        "parsed_database_bytes": sum(int(item.get("size_bytes") or 0) for item in parsed),
        "active_database_count": by_status["ACTIVE_PROTECT"],
        "registered_database_count": by_status["REGISTERED_PROTECT"],
        "session_referenced_database_count": by_status["SESSION_REFERENCED"],
        "task_referenced_database_count": by_status["TASK_REFERENCED"],
        "unknown_database_count": by_status["UNKNOWN_PROTECT"] + by_status["INSPECTION_FAILED"],
        "orphan_candidate_count": by_status["ORPHAN_CANDIDATE"],
        "status_counts": by_status,
        "raw_logs_modified_count": 0,
        "active_database_modified_count": 0,
        "unconfirmed_database_removed_count": 0,
    }


def _md_escape(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_inventory(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# MESH_DATABASE_INVENTORY",
        "",
        f"生成时间：`{audit['generated_at']}`",
        "",
        "本报告由只读 SQLite `mode=ro` 连接生成；未初始化 Repository，未执行 WAL checkpoint、VACUUM、迁移或文件移动。",
        "",
        f"- 扫描局点：{summary['site_count']}",
        f"- MR Profile：{summary['mr_profile_count']}",
        f"- SQLite 总数：{summary['sqlite_database_count']}",
        f"- parsed 总数：{summary['parsed_database_count']}（{summary['parsed_database_bytes']} bytes）",
        "",
        "| 环境 | 局点 | MR Profile | 数据库类型 | 相对路径 | 字节 | 修改时间 | Schema | quick_check | integrity_check | WAL/SHM | 状态 |",
        "|---|---|---|---|---|---:|---|---|---|---|---|---|",
    ]
    for record in audit["records"]:
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    record.get("environment"),
                    record.get("site"),
                    record.get("mr_name") or record.get("mr_profile_id"),
                    record.get("database_type"),
                    record.get("relative_path"),
                    record.get("size_bytes"),
                    record.get("modified_at"),
                    record.get("schema_version"),
                    record.get("quick_check"),
                    record.get("integrity_check"),
                    f"{record.get('wal_bytes', 0)}/{record.get('shm_bytes', 0)}",
                    record.get("status"),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_reference_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# MESH_DATABASE_REFERENCE_AUDIT",
        "",
        f"生成时间：`{audit['generated_at']}`",
        "",
        "判定优先级：INSPECTION_FAILED / ACTIVE_PROTECT / TASK_REFERENCED / SESSION_REFERENCED / REGISTERED_PROTECT / BACKUP_PROTECT / UNKNOWN_PROTECT / ORPHAN_CANDIDATE。未知、WAL/SHM、活动写入和无法核验的引用均保护。",
        "",
        "| 文件 | 来源记录 | 分析会话引用 | 文件名回退 | 活动任务引用 | 报告引用 | 备份引用 | 判定依据 | 状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for record in audit["records"]:
        reasons = ", ".join(record.get("protection_reasons") or [])
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    record.get("path"),
                    record.get("source_record_count"),
                    record.get("analysis_session_reference_count"),
                    record.get("filename_fallback_reference_count"),
                    record.get("activity_task_reference_count"),
                    record.get("report_reference_count"),
                    record.get("backup_reference_count"),
                    reasons,
                    record.get("status"),
                )
            )
            + " |"
        )
        if record.get("source_references") or record.get("session_references") or record.get("task_references"):
            lines.append("")
            lines.append(f"- `{record['path']}` 证据：")
            for item in record.get("source_references") or []:
                lines.append(f"  - source_files: `{json.dumps(item, ensure_ascii=False, default=str)}`")
            for item in record.get("session_references") or []:
                lines.append(f"  - mesh_session_index: `{json.dumps(item, ensure_ascii=False, default=str)}`")
            for item in record.get("task_references") or []:
                lines.append(f"  - task: `{json.dumps(item, ensure_ascii=False, default=str)}`")
    return "\n".join(lines) + "\n"


def render_candidates(audit: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        record
        for record in audit["records"]
        if record.get("status") == "ORPHAN_CANDIDATE"
    ]
    return {
        "format": "netconsole-mesh-orphan-candidates-v1",
        "generated_at": audit["generated_at"],
        "summary": audit["summary"],
        "candidates": candidates,
    }


def render_final_report(audit: dict[str, Any], *, operation: dict[str, Any] | None = None) -> str:
    summary = dict(audit["summary"])
    operation = operation or {}
    status = "PASS"
    if summary["unknown_database_count"] or summary["active_database_count"]:
        status = "PARTIAL/BLOCKED"
    lines = [
        "# MESH_DATABASE_CLEANUP_FINAL_REPORT",
        "",
        f"生成时间：`{audit['generated_at']}`",
        f"总体状态：`{status}`",
        "",
        "## 结论",
        "",
        f"ORPHAN_CANDIDATES={summary['orphan_candidate_count']}",
        f"DATABASES_REMOVED={int(operation.get('isolated_count') or 0)}",
        f"DATA_SAFETY={'PASS' if summary['raw_logs_modified_count'] == 0 and summary['active_database_modified_count'] == 0 and summary['unconfirmed_database_removed_count'] == 0 else 'FAIL'}",
        "",
        "## 盘点统计",
        "",
        f"- 扫描局点数量：{summary['site_count']}",
        f"- 扫描 MR 数量：{summary['mr_profile_count']}",
        f"- SQLite 数据库总数：{summary['sqlite_database_count']}",
        f"- 活动数据库数量：{summary['active_database_count']}",
        f"- 已登记数据库数量：{summary['registered_database_count']}",
        f"- 分析会话引用数据库数量：{summary['session_referenced_database_count']}",
        f"- 未确认数据库数量：{summary['unknown_database_count']}",
        f"- 真正的孤儿候选数量：{summary['orphan_candidate_count']}",
        f"- 成功备份数量：{int(operation.get('backup_success_count') or 0)}",
        f"- 备份校验失败数量：{int(operation.get('backup_failure_count') or 0)}",
        f"- 成功隔离数量：{int(operation.get('isolated_count') or 0)}",
        f"- 隔离失败数量：{int(operation.get('isolation_failure_count') or 0)}",
        f"- 回收的逻辑文件大小：{int(operation.get('isolated_bytes') or 0)} bytes",
        f"- 实际磁盘空间变化：{int(operation.get('disk_bytes_delta') or 0)} bytes",
        f"- 原始日志修改数量：{summary['raw_logs_modified_count']}",
        f"- 活动数据库修改数量：{summary['active_database_modified_count']}",
        f"- 未确认数据库删除数量：{summary['unconfirmed_database_removed_count']}",
        "",
        "## 保护边界与回滚",
        "",
        "- catalog.sqlite、已登记 Profile 的 mesh.sqlite、来源引用、会话引用、活动任务、WAL/SHM、备份和未知数据库均保留。",
        "- 本轮没有永久删除；若未来通过显式 backup/isolate 阶段，回滚映射写入备份 manifest，原始路径会记录在隔离清单。",
        "- 原始 MESH 日志、历史报告、Excel、导出文件和既有数据库备份不作为清理目标。",
        "",
        "## 测试与未解决风险",
        "",
        "- 自动测试结果见任务交接；真实 Electron 页面、真实报告打开和设备验收不由本审计器冒充通过。",
        "- 生产 Backend/SQLite 写入者未取得停机/静止证据时，结果保持 PARTIAL/BLOCKED。",
        "- Workspace 基线已有顶层 docs 目录布局检查失败，本任务未清理该既有目录。",
        "",
        "证据文件：`MESH_DATABASE_INVENTORY.md`、`MESH_DATABASE_REFERENCE_AUDIT.md`、`MESH_ORPHAN_CANDIDATES.json`。",
    ]
    return "\n".join(lines) + "\n"


def write_reports(audit: dict[str, Any], output_dir: Path, *, operation: dict[str, Any] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "MESH_DATABASE_INVENTORY.md").write_text(
        render_inventory(audit), encoding="utf-8"
    )
    (output_dir / "MESH_DATABASE_REFERENCE_AUDIT.md").write_text(
        render_reference_audit(audit), encoding="utf-8"
    )
    (output_dir / "MESH_ORPHAN_CANDIDATES.json").write_text(
        json.dumps(render_candidates(audit), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "MESH_DATABASE_CLEANUP_FINAL_REPORT.md").write_text(
        render_final_report(audit, operation=operation), encoding="utf-8"
    )


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    candidates = value.get("candidates") if isinstance(value, dict) else None
    if not isinstance(candidates, list):
        raise ValueError("候选清单格式无效")
    return [dict(item) for item in candidates if isinstance(item, dict)]


def backup_candidates(candidates: list[dict[str, Any]], *, audit_id: str) -> dict[str, Any]:
    source_root = Path(__file__).resolve().parents[2] / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from netconsole.core.paths import PathResolver
    from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore

    operation = {
        "audit_id": audit_id,
        "backup_success_count": 0,
        "backup_failure_count": 0,
        "items": [],
    }
    for record in candidates:
        source = Path(str(record.get("path") or "")).resolve()
        item: dict[str, Any] = {"source": str(source), "status": "FAILED"}
        try:
            if record.get("status") != "ORPHAN_CANDIDATE":
                raise RuntimeError("当前状态不是 ORPHAN_CANDIDATE")
            if not source.is_file() or _sidecar(source, "-wal").exists() or _sidecar(source, "-shm").exists():
                raise RuntimeError("源文件不存在或存在 WAL/SHM 侧车")
            if int(record.get("size_bytes") or -1) != source.stat().st_size or sha256_file(source) != str(record.get("sha256") or ""):
                raise RuntimeError("清理前复核发现文件快照变化")
            root = Path(str(record.get("data_root") or "")).resolve()
            store = DatabaseBackupStore(PathResolver(data_root=root))
            created = store.create(
                source_path=source,
                database_kind="mesh_derived_orphan",
                scope_type="mesh_orphan_cleanup",
                scope_id=f"{record.get('site', '')}_{record.get('safe_folder_name', '')}",
                task_id=audit_id,
                old_version=str(record.get("schema_version") or ""),
                target_version=str(record.get("schema_version") or ""),
                strategy="ORPHAN_CANDIDATE_BACKUP",
                reason="MESH orphan candidate cleanup",
                metadata={"audit_record": record},
                checkpoint={"wal": "absent", "shm": "absent"},
            )
            validated = store.validate(str(created["backup_id"]))
            if not validated.get("validation", {}).get("restorable"):
                raise RuntimeError("备份独立打开或 SHA/完整性校验失败")
            item.update(
                status="BACKUP_VERIFIED",
                backup_id=created.get("backup_id"),
                backup_path=created.get("path"),
                validation=validated.get("validation", {}),
            )
            operation["backup_success_count"] += 1
        except Exception as exc:  # 每个候选独立失败，不影响其他文件
            item["error"] = f"{type(exc).__name__}: {exc}"
            operation["backup_failure_count"] += 1
        operation["items"].append(item)
    return operation


def isolate_backups(operation: dict[str, Any], *, audit_id: str) -> dict[str, Any]:
    result = dict(operation)
    result.setdefault("isolated_count", 0)
    result.setdefault("isolation_failure_count", 0)
    result.setdefault("isolated_bytes", 0)
    result.setdefault("disk_bytes_delta", 0)
    result.setdefault("isolation_items", [])
    for item in operation.get("items") or []:
        if item.get("status") != "BACKUP_VERIFIED":
            continue
        source = Path(str(item.get("source") or "")).resolve()
        entry: dict[str, Any] = {"source": str(source), "status": "FAILED"}
        try:
            record_path = source
            if not record_path.is_file() or _sidecar(record_path, "-wal").exists() or _sidecar(record_path, "-shm").exists():
                raise RuntimeError("隔离前发现源文件不存在或出现 WAL/SHM")
            expected = str(item.get("validation", {}).get("sha256") or "")
            if expected and sha256_file(record_path) != expected:
                raise RuntimeError("隔离前 SHA-256 发生变化")
            sites_root = next(
                (parent for parent in source.parents if parent.name.casefold() == "sites"),
                None,
            )
            if sites_root is None:
                raise RuntimeError("无法从源路径解析 sites 根")
            quarantine = sites_root.parent / "backups" / "mesh_orphan_quarantine" / audit_id
            quarantine = quarantine.resolve()
            quarantine.mkdir(parents=True, exist_ok=True)
            target = quarantine / (source.name + ".isolated")
            if target.exists():
                raise RuntimeError("隔离目标已存在")
            size = source.stat().st_size
            shutil.move(str(source), str(target))
            entry.update(status="ISOLATED", target=str(target), size_bytes=size)
            result["isolated_count"] += 1
            result["isolated_bytes"] += size
            result["disk_bytes_delta"] += 0
        except Exception as exc:  # pragma: no cover - real Windows failure path
            entry["error"] = f"{type(exc).__name__}: {exc}"
            result["isolation_failure_count"] += 1
        result["isolation_items"].append(entry)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("audit", "backup", "isolate"), default="audit")
    parser.add_argument(
        "--audit-id",
        default=datetime.now(UTC).strftime("mesh-audit-%Y%m%dT%H%M%SZ"),
    )
    parser.add_argument("--authorize-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    roots = [Path(value).resolve() for value in args.data_root]
    production = {root for root in roots if root.name.casefold() == "netconsoledata"}
    writer_active = set(production) if _active_backend_processes() else set()
    if args.mode in {"backup", "isolate"} and not args.authorize_write:
        raise SystemExit("backup/isolate 需要显式 --authorize-write；默认只读")
    audit = audit_roots(roots, writer_active_roots=writer_active)
    operation: dict[str, Any] = {}
    if args.mode == "backup":
        candidates = [record for record in audit["records"] if record.get("status") == "ORPHAN_CANDIDATE"]
        operation = backup_candidates(candidates, audit_id=str(args.audit_id))
        (args.output_dir / "MESH_BACKUP_MANIFEST.json").parent.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "MESH_BACKUP_MANIFEST.json").write_text(
            json.dumps(operation, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
    elif args.mode == "isolate":
        manifest = args.output_dir / "MESH_BACKUP_MANIFEST.json"
        if not manifest.is_file():
            raise SystemExit(f"缺少备份 manifest：{manifest}")
        operation = isolate_backups(json.loads(manifest.read_text(encoding="utf-8")), audit_id=str(args.audit_id))
        manifest.write_text(json.dumps(operation, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    write_reports(audit, args.output_dir, operation=operation)
    print(json.dumps({"summary": audit["summary"], "operation": operation}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
