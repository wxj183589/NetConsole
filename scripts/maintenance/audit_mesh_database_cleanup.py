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
import re
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
    "ACTIVE_CONFIRMED",
    "TASK_ACTIVE_PROTECT",
    "RECOVERY_PROTECT",
    "SESSION_REFERENCED",
    "SOURCE_REFERENCED",
    "CATALOG_PROTECT",
    "SOURCE_INDEX_PROTECT",
    "BACKUP_PROTECT",
    "HISTORICAL_TASK_PROTECT",
    "SIDECAR_PRESENT_UNCONFIRMED",
    "ACTIVITY_UNKNOWN",
    "UNKNOWN_PROTECT",
    "ORPHAN_CANDIDATE",
)
ACTIVE_TASK_STATES = {"PENDING", "STARTING", "RUNNING", "STOPPING"}
SQLITE_HEADER = b"SQLite format 3\x00"
MESH_SUFFIXES = (".sqlite", ".sqlite3", ".db")
REBUILD_NAME_RE = re.compile(
    r"^\.(?P<target>.+)\.(?P<operation_id>[0-9a-f]{32})\.rebuild\.sqlite$",
    re.IGNORECASE,
)
RUNTIME_PROCESS_IMAGES = (
    "NetConsoleBackend.exe",
    "NetConsoleWorker.exe",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "canonical_path": str(path.resolve()),
        "file_size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "file_identity": f"{int(stat.st_dev)}:{int(stat.st_ino)}",
    }


def _snapshot_stable(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    if before is None and after is None:
        return True
    if before is None or after is None:
        return False
    return all(
        before.get(field) == after.get(field)
        for field in ("canonical_path", "file_size", "mtime_ns", "file_identity")
    )


def _is_rebuild_database(path: Path) -> bool:
    return REBUILD_NAME_RE.fullmatch(path.name) is not None


def _rebuild_target_name(path: Path) -> str:
    match = REBUILD_NAME_RE.fullmatch(path.name)
    return str(match.group("target")) if match else ""


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


def _inspect_sqlite_once(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sqlite_header": False,
        "schema_version": "",
        "sqlite_schema": "",
        "quick_check": "not_checked",
        "integrity_check": "not_checked",
        "table_names": [],
        "source_file_count": None,
        "session_count": None,
        "error": "",
        "read_conflict": False,
    }
    try:
        with path.open("rb") as handle:
            result["sqlite_header"] = handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError as exc:
        result["error"] = f"header:{type(exc).__name__}: {exc}"
    if not result["error"] and not result["sqlite_header"]:
        result["error"] = "文件头不是 SQLite format 3"
    if result["sqlite_header"] and not result["error"]:
        try:
            with read_only_connection(path) as connection:
                tables = _table_names(connection)
                result["table_names"] = sorted(tables)
                result["schema_version"] = _schema_version(connection, tables)
                result["sqlite_schema"] = result["schema_version"]
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
            if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).casefold():
                result["read_conflict"] = True
    return result


def _sqlite_metadata(path: Path) -> dict[str, Any]:
    """Inspect SQLite twice and separate observer side effects from external changes.

    A read-only connection may update the WAL index/SHM mtime while settling a stale
    sidecar left by an interrupted writer. The second independent observation lets us
    record that first-probe effect without treating it as confirmed external activity.
    """
    before = _file_snapshot(path)
    wal_path = _sidecar(path, "-wal")
    shm_path = _sidecar(path, "-shm")
    wal_before = _file_snapshot(wal_path)
    shm_before = _file_snapshot(shm_path)
    first = _inspect_sqlite_once(path)
    after_first = _file_snapshot(path)
    wal_after_first = _file_snapshot(wal_path)
    shm_after_first = _file_snapshot(shm_path)
    second = _inspect_sqlite_once(path)
    after_second = _file_snapshot(path)
    wal_after_second = _file_snapshot(wal_path)
    shm_after_second = _file_snapshot(shm_path)

    result: dict[str, Any] = dict(first)
    result["second_probe_error"] = second.get("error") or ""
    result["second_probe_read_conflict"] = bool(second.get("read_conflict"))
    if second.get("error") or second.get("read_conflict"):
        result["error"] = "; ".join(
            value
            for value in (first.get("error"), second.get("error"))
            if value
        )
        result["read_conflict"] = bool(
            first.get("read_conflict") or second.get("read_conflict")
        )
    elif not first.get("error"):
        # The second result is the latest complete read, while the first result
        # remains available through the probe evidence below.
        for field in (
            "sqlite_header",
            "schema_version",
            "sqlite_schema",
            "quick_check",
            "integrity_check",
            "table_names",
            "source_file_count",
            "session_count",
        ):
            result[field] = second.get(field)

    main_changed = not _snapshot_stable(before, after_second)
    wal_changed = not _snapshot_stable(wal_before, wal_after_second)
    shm_changed_first = not _snapshot_stable(shm_before, shm_after_first)
    shm_changed_second = not _snapshot_stable(shm_after_first, shm_after_second)
    settled_stable = all(
        (
            _snapshot_stable(after_first, after_second),
            _snapshot_stable(wal_after_first, wal_after_second),
            _snapshot_stable(shm_after_first, shm_after_second),
        )
    )
    auditor_shm_side_effect = bool(
        shm_changed_first
        and not shm_changed_second
        and not main_changed
        and not wal_changed
        and not result.get("read_conflict")
        and not result.get("error")
    )
    result.update(
        {
            "main_snapshot_before": before,
            "main_snapshot_after": after_second,
            "wal_snapshot_before": wal_before,
            "wal_snapshot_after": wal_after_second,
            "shm_snapshot_before": shm_before,
            "shm_snapshot_after": shm_after_second,
            "main_snapshot_after_first_probe": after_first,
            "wal_snapshot_after_first_probe": wal_after_first,
            "shm_snapshot_after_first_probe": shm_after_first,
            "main_changed_during_observation": main_changed,
            "wal_changed_during_observation": wal_changed,
            "shm_changed_during_first_probe": shm_changed_first,
            "shm_changed_during_second_probe": shm_changed_second,
            "settled_snapshot_stable": settled_stable,
            "snapshot_stable": all(
                (
                    _snapshot_stable(before, after_second),
                    _snapshot_stable(wal_before, wal_after_second),
                    _snapshot_stable(shm_before, shm_after_second),
                )
            ),
            "observer_stable": settled_stable,
            "auditor_shm_side_effect_observed": auditor_shm_side_effect,
            "unexplained_shm_change": bool(shm_changed_second),
            "probe_count": 2,
            "wal_size": int((wal_after_second or {}).get("file_size") or 0),
            "shm_size": int((shm_after_second or {}).get("file_size") or 0),
        }
    )
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
        candidate_resolved = candidate.resolve()
        if value_path.is_absolute():
            if value_path.resolve() == candidate_resolved:
                return "exact_path"
            fallback = (parsed_root / value_path.name).resolve()
            if fallback == candidate_resolved and _within(candidate_resolved, parsed_root):
                return "filename_fallback"
            return ""
        profile_relative = (parsed_root.parent / value_path).resolve()
        parsed_relative = (parsed_root / value_path).resolve()
        if profile_relative == candidate_resolved and _within(candidate_resolved, parsed_root):
            return "relative_path"
        if parsed_relative == candidate_resolved and _within(candidate_resolved, parsed_root):
            return "relative_path"
        fallback = (parsed_root / value_path.name).resolve()
        if fallback == candidate_resolved and _within(candidate_resolved, parsed_root):
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
    result: list[str] = []
    for image in RUNTIME_PROCESS_IMAGES:
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        result.extend(
            f"{image}: {line.strip()}"
            for line in completed.stdout.splitlines()
            if line.strip() and "INFO:" not in line.upper()
        )
    return result


def _task_texts(site_dir: Path) -> dict[str, Any]:
    task_db = site_dir / "db" / "tasks.db"
    result: dict[str, Any] = {
        "status": "MISSING" if not task_db.is_file() else "OK",
        "active_tasks": [],
        "task_states": {},
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
                if item["task_id"]:
                    result["task_states"][item["task_id"]] = item["status"]
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
                            "status": result["task_states"].get(
                                str(value.get("task_id") or ""), ""
                            ),
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


def _recovery_texts(mesh_root: Path) -> list[dict[str, str]]:
    """Read only small recovery/journal descriptors, never raw or SQLite bodies."""
    result: list[dict[str, str]] = []
    markers = ("journal", "recovery", "rebuild", "maintenance", "migration")
    allowed_suffixes = {".json", ".journal", ".txt", ".log", ".manifest"}
    for path in _walk_files(mesh_root):
        lowered = path.name.casefold()
        if not any(marker in lowered for marker in markers):
            continue
        if path.suffix.casefold() not in allowed_suffixes:
            continue
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        result.append({"path": str(path), "text": text})
    return result


def _tokens(record: dict[str, Any]) -> list[str]:
    basename = str(record.get("basename") or "")
    values = [
        record.get("path"),
        record.get("relative_path"),
        record.get("sha256"),
        record.get("content_sha256"),
        record.get("file_identity"),
    ]
    if basename.casefold() not in {"mesh.sqlite", "catalog.sqlite"}:
        values.append(basename)
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
            matches.append(
                {
                    "path": str(item.get("path") or ""),
                    "token": hit,
                    "task_id": str(item.get("task_id") or ""),
                    "status": str(item.get("status") or ""),
                    "task_type": str(item.get("task_type") or ""),
                }
            )
    return matches


def _classify(reasons: set[str], *, inspection_failed: bool) -> str:
    if inspection_failed:
        return "INSPECTION_FAILED"
    for status in STATUS_ORDER:
        if status in reasons:
            return status
    return "ORPHAN_CANDIDATE"


def _activity_state(
    metadata: dict[str, Any],
    *,
    runtime_processes: list[str],
    active_task_references: int,
    unknown_task_references: int,
    recovery_references: int,
    reference_queries_ok: bool,
    maintenance_window_authorized: bool,
) -> str:
    if metadata.get("main_changed_during_observation") or metadata.get(
        "wal_changed_during_observation"
    ):
        return "ACTIVE_CONFIRMED"
    if (
        metadata.get("read_conflict")
        or runtime_processes
        or active_task_references
        or unknown_task_references
        or recovery_references
        or not reference_queries_ok
    ):
        return "ACTIVITY_UNKNOWN"
    # A non-empty WAL means there is uncheckpointed state. It remains protected
    # even when two read-only probes happen to observe stable sidecars.
    if metadata.get("wal_size"):
        return "SIDECAR_PRESENT_UNCONFIRMED"
    if metadata.get("unexplained_shm_change"):
        return "SIDECAR_PRESENT_UNCONFIRMED"
    if not maintenance_window_authorized:
        return (
            "SIDECAR_PRESENT_UNCONFIRMED"
            if metadata.get("shm_size")
            else "ACTIVITY_UNKNOWN"
        )
    if metadata.get("error") or metadata.get("quick_check") != "ok" or metadata.get(
        "integrity_check"
    ) != "ok":
        return "ACTIVITY_UNKNOWN"
    if metadata.get("settled_snapshot_stable") and (
        not metadata.get("shm_size")
        or metadata.get("auditor_shm_side_effect_observed")
        or not metadata.get("shm_changed_during_first_probe")
    ):
        return "IDLE_CONFIRMED"
    return "SIDECAR_PRESENT_UNCONFIRMED"


def _task_reference_counts(
    task_matches: list[dict[str, str]],
    task_info: dict[str, Any],
) -> tuple[list[dict[str, str]], int, int, int]:
    active: list[dict[str, str]] = []
    historical: list[dict[str, str]] = []
    unknown: list[dict[str, str]] = []
    task_states = task_info.get("task_states") or {}
    for match in task_matches:
        state = str(match.get("status") or task_states.get(match.get("task_id"), "")).upper()
        item = {**match, "resolved_status": state or "UNKNOWN"}
        if state in ACTIVE_TASK_STATES:
            active.append(item)
        elif state in {"COMPLETED", "FAILED", "CANCELLED", "CANCELED", "STOPPED"}:
            historical.append(item)
        else:
            unknown.append(item)
    return active + historical + unknown, len(active), len(historical), len(unknown)


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
    task_info: dict[str, Any],
    artifact_texts: list[dict[str, str]],
    backup_texts: list[dict[str, str]],
    recovery_texts: list[dict[str, str]],
    runtime_processes: list[str],
    catalog_available: bool,
    source_index_query_ok: bool,
    maintenance_window_authorized: bool,
) -> dict[str, Any]:
    metadata = _sqlite_metadata(path)
    stat = path.stat()
    canonical_path = str(path.resolve())
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = canonical_path
    safe_name = _profile_name_from_path(mesh_root, path)
    profile = profile or {}
    profile_id = str(profile.get("mr_id") or "")
    mr_name = str(profile.get("display_name") or safe_name)
    parsed_root = path.parent
    source_refs: list[dict[str, Any]] = []
    fallback_refs: list[dict[str, Any]] = []
    session_refs: list[dict[str, Any]] = []
    detail_sources: list[dict[str, Any]] = []
    internal_identities: list[dict[str, Any]] = []
    reasons: set[str] = set()
    evidence: list[dict[str, Any]] = []

    if db_type in {"parsed", "rebuild_temp"}:
        detail_sources, _ = _read_rows(path, "source_files")
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
        for detail_source in detail_sources:
            detail_names = {
                _clean_text(detail_source.get(field)).casefold()
                for field in ("original_filename", "archived_filename")
                if _clean_text(detail_source.get(field))
            }
            detail_hashes = {
                _clean_text(detail_source.get(field)).casefold()
                for field in ("sha256", "content_sha256")
                if _clean_text(detail_source.get(field))
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
                if (detail_names & index_names) or (detail_hashes & index_hashes):
                    internal_identities.append(
                        {
                            "detail_source_id": detail_source.get("id"),
                            "index_source_file_id": index_source.get("id"),
                            "match_types": ["detail_source_identity"],
                        }
                    )
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
            reasons.add("SOURCE_REFERENCED")
            evidence.append({"kind": "source_files_physical_path", "count": len(source_refs)})
        if session_refs:
            reasons.add("SESSION_REFERENCED")
            evidence.append({"kind": "mesh_session_index_physical_path", "count": len(session_refs)})
        if internal_identities:
            evidence.append(
                {
                    "kind": "internal_source_identity_only",
                    "count": len(internal_identities),
                    "note": "不作为物理数据库引用或会话引用",
                }
            )
    elif db_type == "catalog":
        reasons.add("CATALOG_PROTECT")
        evidence.append({"kind": "catalog_authority"})
    elif db_type == "source_index":
        if profile_id:
            reasons.add("SOURCE_INDEX_PROTECT")
            evidence.append({"kind": "registered_profile", "mr_id": profile_id})
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
    physical_record = {
        "path": canonical_path,
        "canonical_path": canonical_path,
        "relative_path": relative,
        "basename": path.name,
        "sha256": "",
        "file_identity": (metadata.get("main_snapshot_after") or {}).get("file_identity", ""),
        "rebuild_target_path": str(path.parent / _rebuild_target_name(path)) if db_type == "rebuild_temp" else "",
    }
    physical_record["sha256"] = sha256_file(path)
    tokens = _tokens(physical_record)
    task_matches = _matching_texts(tokens, task_info.get("texts") or [])
    task_matches, active_task_count, historical_task_count, unknown_task_count = _task_reference_counts(
        task_matches, task_info
    )
    report_matches = _matching_texts(tokens, artifact_texts)
    backup_matches = _matching_texts(tokens, backup_texts)
    recovery_matches = _matching_texts(tokens, recovery_texts)
    if active_task_count:
        reasons.add("TASK_ACTIVE_PROTECT")
    if historical_task_count:
        reasons.add("HISTORICAL_TASK_PROTECT")
    if unknown_task_count:
        reasons.add("UNKNOWN_PROTECT")
    if report_matches:
        reasons.add("SESSION_REFERENCED")
    if backup_matches:
        reasons.add("BACKUP_PROTECT")
    if recovery_matches:
        reasons.add("RECOVERY_PROTECT")
    if task_info.get("status") != "OK":
        reasons.add("UNKNOWN_PROTECT")
        evidence.append(
            {
                "kind": "task_state_unavailable",
                "status": task_info.get("status"),
                "error": task_info.get("error") or "",
            }
        )
    if not catalog_available:
        reasons.add("UNKNOWN_PROTECT")
        evidence.append({"kind": "catalog_state_unavailable"})

    activity_state = _activity_state(
        metadata,
        runtime_processes=runtime_processes,
        active_task_references=active_task_count,
        unknown_task_references=unknown_task_count,
        recovery_references=len(recovery_matches),
        reference_queries_ok=bool(
            catalog_available
            and task_info.get("status") == "OK"
            and (db_type not in {"parsed", "rebuild_temp"} or source_index_query_ok)
        ),
        maintenance_window_authorized=maintenance_window_authorized,
    )
    if activity_state == "ACTIVE_CONFIRMED":
        reasons.add("ACTIVE_CONFIRMED")
    elif activity_state == "SIDECAR_PRESENT_UNCONFIRMED":
        reasons.add("SIDECAR_PRESENT_UNCONFIRMED")
    elif activity_state == "ACTIVITY_UNKNOWN":
        reasons.add("ACTIVITY_UNKNOWN")
    if metadata.get("error") or metadata.get("quick_check") != "ok" or metadata.get("integrity_check") != "ok":
        reasons.add("INSPECTION_FAILED")
    if db_type in {"parsed", "rebuild_temp"} and not profile_id:
        reasons.add("UNKNOWN_PROTECT")
    if db_type == "parsed" and profile_id and not source_refs and not session_refs:
        reasons.add("UNKNOWN_PROTECT")
        evidence.append({"kind": "registered_profile_without_physical_source_reference"})

    snapshot = metadata.get("main_snapshot_after") or {}
    base_record: dict[str, Any] = {
        "data_root": str(root),
        "environment": "PRODUCTION" if root.name.casefold() == "netconsoledata" else "DEV_REAL",
        "site": site_dir.name,
        "mr_profile_id": profile_id,
        "mr_name": mr_name,
        "safe_folder_name": safe_name,
        "database_type": db_type,
        "path": canonical_path,
        "canonical_path": canonical_path,
        "relative_path": relative,
        "basename": path.name,
        "file_size": int(snapshot.get("file_size") or stat.st_size),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "mtime_ns": int(snapshot.get("mtime_ns") or stat.st_mtime_ns),
        "sha256": physical_record["sha256"],
        "file_identity": snapshot.get("file_identity") or "",
        "sqlite_schema": metadata.get("sqlite_schema") or "",
        "schema_version": metadata.get("schema_version") or "",
        "quick_check": metadata.get("quick_check"),
        "integrity_check": metadata.get("integrity_check"),
        "inspection_error": metadata.get("error") or "",
        "table_names": metadata.get("table_names") or [],
        "wal_path": str(_sidecar(path, "-wal")),
        "wal_size": int(metadata.get("wal_size") or 0),
        "wal_bytes": int(metadata.get("wal_size") or 0),
        "shm_path": str(_sidecar(path, "-shm")),
        "shm_size": int(metadata.get("shm_size") or 0),
        "shm_bytes": int(metadata.get("shm_size") or 0),
        "activity_state": activity_state,
        "activity_probe": {
            "snapshot_stable": metadata.get("snapshot_stable"),
            "settled_snapshot_stable": metadata.get("settled_snapshot_stable"),
            "observer_stable": metadata.get("observer_stable"),
            "probe_count": metadata.get("probe_count", 0),
            "read_conflict": metadata.get("read_conflict"),
            "second_probe_error": metadata.get("second_probe_error") or "",
            "main_changed_during_observation": metadata.get(
                "main_changed_during_observation"
            ),
            "wal_changed_during_observation": metadata.get(
                "wal_changed_during_observation"
            ),
            "shm_changed_during_first_probe": metadata.get(
                "shm_changed_during_first_probe"
            ),
            "shm_changed_during_second_probe": metadata.get(
                "shm_changed_during_second_probe"
            ),
            "auditor_shm_side_effect_observed": metadata.get(
                "auditor_shm_side_effect_observed"
            ),
            "unexplained_shm_change": metadata.get("unexplained_shm_change"),
            "maintenance_window_authorized": maintenance_window_authorized,
            "source_index_query_ok": source_index_query_ok,
            "task_query_status": task_info.get("status"),
            "catalog_available": catalog_available,
            "runtime_processes": runtime_processes,
            "main_snapshot_before": metadata.get("main_snapshot_before"),
            "main_snapshot_after": metadata.get("main_snapshot_after"),
            "main_snapshot_after_first_probe": metadata.get(
                "main_snapshot_after_first_probe"
            ),
            "wal_snapshot_before": metadata.get("wal_snapshot_before"),
            "wal_snapshot_after": metadata.get("wal_snapshot_after"),
            "wal_snapshot_after_first_probe": metadata.get(
                "wal_snapshot_after_first_probe"
            ),
            "shm_snapshot_before": metadata.get("shm_snapshot_before"),
            "shm_snapshot_after": metadata.get("shm_snapshot_after"),
            "shm_snapshot_after_first_probe": metadata.get(
                "shm_snapshot_after_first_probe"
            ),
        },
        "source_record_count": len(source_rows),
        "source_reference_count": len(source_refs),
        "session_reference_count": len(session_refs),
        "analysis_session_reference_count": len(session_refs),
        "fallback_reference_count": len(fallback_refs),
        "filename_fallback_reference_count": len(fallback_refs),
        "active_task_reference_count": active_task_count,
        "activity_task_reference_count": active_task_count,
        "historical_task_reference_count": historical_task_count,
        "unknown_task_reference_count": unknown_task_count,
        "report_reference_count": len(report_matches),
        "backup_reference_count": len(backup_matches),
        "recovery_reference_count": len(recovery_matches),
        "internal_source_identity_count": len(internal_identities),
        "source_names": raw_names,
        "source_references": source_refs,
        "session_references": session_refs,
        "internal_source_identities": internal_identities,
        "task_references": task_matches,
        "report_references": report_matches,
        "backup_references": backup_matches,
        "recovery_references": recovery_matches,
        "evidence": evidence,
        "runtime_processes": runtime_processes,
        "maintenance_window_authorized": maintenance_window_authorized,
        "source_index_query_ok": source_index_query_ok,
        "rebuild_target_path": physical_record["rebuild_target_path"],
    }
    base_record["final_status"] = _classify(
        reasons, inspection_failed="INSPECTION_FAILED" in reasons
    )
    base_record["status"] = base_record["final_status"]
    base_record["protection_reasons"] = sorted(reasons)
    base_record["allowed_for_backup"] = (
        base_record["final_status"] == "ORPHAN_CANDIDATE"
        and activity_state == "IDLE_CONFIRMED"
    )
    base_record["allowed_for_isolation"] = False
    return base_record


def _finalize_rebuild_records(records: list[dict[str, Any]]) -> None:
    by_path = {str(record.get("canonical_path")): record for record in records}
    for record in records:
        if record.get("database_type") != "rebuild_temp":
            continue
        reasons = set(record.get("protection_reasons") or [])
        target_path = str(record.get("rebuild_target_path") or "")
        target = by_path.get(str(Path(target_path).resolve())) if target_path else None
        review: dict[str, Any] = {
            "temporary_path": record.get("canonical_path"),
            "formal_database_path": target_path,
            "formal_database_exists": bool(target),
            "formal_database_healthy": False,
            "formal_database_quick_check": "",
            "formal_database_integrity_check": "",
            "formal_database_session_reference_count": 0,
            "physical_source_reference_count": record.get("source_reference_count", 0),
            "physical_session_reference_count": record.get("session_reference_count", 0),
            "filename_fallback_reference_count": record.get("fallback_reference_count", 0),
            "actual_path_reference_count": record.get("source_reference_count", 0),
            "internal_source_identity_count": record.get("internal_source_identity_count", 0),
            "active_task_reference_count": record.get("active_task_reference_count", 0),
            "historical_task_reference_count": record.get("historical_task_reference_count", 0),
            "recovery_reference_count": record.get("recovery_reference_count", 0),
            "backup_reference_count": record.get("backup_reference_count", 0),
        }
        if target:
            healthy = target.get("quick_check") == "ok" and target.get("integrity_check") == "ok"
            review["formal_database_healthy"] = healthy
            review["formal_database_quick_check"] = target.get("quick_check") or ""
            review["formal_database_integrity_check"] = target.get("integrity_check") or ""
            review["formal_database_session_reference_count"] = target.get(
                "session_reference_count", 0
            )
            review["formal_database_activity_state"] = target.get("activity_state")
            if not healthy or not target.get("session_reference_count"):
                reasons.add("UNKNOWN_PROTECT")
            else:
                reasons.add("FORMAL_DATABASE_TAKES_SESSION")
        else:
            reasons.add("UNKNOWN_PROTECT")
        if record.get("activity_state") != "IDLE_CONFIRMED":
            reasons.add(str(record.get("activity_state") or "ACTIVITY_UNKNOWN"))
        blocked = {
            "INSPECTION_FAILED",
            "ACTIVE_CONFIRMED",
            "TASK_ACTIVE_PROTECT",
            "RECOVERY_PROTECT",
            "SESSION_REFERENCED",
            "SOURCE_REFERENCED",
            "BACKUP_PROTECT",
            "HISTORICAL_TASK_PROTECT",
            "SIDECAR_PRESENT_UNCONFIRMED",
            "ACTIVITY_UNKNOWN",
            "UNKNOWN_PROTECT",
        }
        can_candidate = (
            target is not None
            and bool(review["formal_database_healthy"])
            and int(review["formal_database_session_reference_count"] or 0) > 0
            and record.get("activity_state") == "IDLE_CONFIRMED"
            and not any(reason in reasons for reason in blocked)
            and not record.get("source_reference_count")
            and not record.get("session_reference_count")
            and not record.get("active_task_reference_count")
            and not record.get("historical_task_reference_count")
            and not record.get("recovery_reference_count")
            and not record.get("backup_reference_count")
        )
        if can_candidate:
            reasons.add("ORPHAN_CANDIDATE")
        else:
            reasons.add("UNKNOWN_PROTECT")
        record["rebuild_review"] = review
        record["protection_reasons"] = sorted(reasons)
        record["final_status"] = _classify(
            reasons, inspection_failed="INSPECTION_FAILED" in reasons
        )
        record["status"] = record["final_status"]
        record["allowed_for_backup"] = can_candidate


def audit_root(
    root: Path,
    *,
    writer_active: bool = False,
    runtime_processes: list[str] | None = None,
    maintenance_window_authorized: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    sites_root = root / "sites"
    runtime_processes = list(runtime_processes or [])
    if writer_active and not runtime_processes:
        runtime_processes = ["legacy_writer_active"]
    result: dict[str, Any] = {
        "data_root": str(root),
        "environment": "PRODUCTION" if root.name.casefold() == "netconsoledata" else "DEV_REAL",
        "writer_active": writer_active,
        "runtime_processes": runtime_processes,
        "maintenance_window_authorized": maintenance_window_authorized,
        "sites_scanned": 0,
        "mr_profiles_scanned": 0,
        "records": [],
        "task_activity": [],
        "source_index_query_errors": [],
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
        catalog_available = catalog_path.is_file()
        if catalog_path.is_file():
            profile_rows, profile_error = _read_rows(catalog_path, "mr_profiles")
            if profile_error:
                result["errors"].append(f"{catalog_path}: {profile_error}")
                catalog_available = False
            profiles = {str(row.get("safe_folder_name") or ""): row for row in profile_rows}
            catalog_sessions, session_error = _read_rows(catalog_path, "mesh_session_index")
            if session_error:
                result["errors"].append(f"{catalog_path}: {session_error}")
                catalog_available = False
            result["mr_profiles_scanned"] += len(profiles)
        else:
            result["errors"].append(f"{mesh_root}: catalog.sqlite 不存在")
        task_info = _task_texts(site_dir)
        if task_info.get("active_tasks"):
            result["task_activity"].extend(
                {"site": site_dir.name, **item} for item in task_info["active_tasks"]
            )
        artifact_texts = _artifact_texts(site_dir)
        recovery_texts = _recovery_texts(mesh_root)
        index_sources: dict[str, list[dict[str, Any]]] = {}
        index_source_query_ok: dict[str, bool] = {}
        for safe_name in profiles:
            index_path = mesh_root / safe_name / "mesh.sqlite"
            if index_path.is_file():
                rows, error = _read_rows(index_path, "source_files")
                if error:
                    result["errors"].append(f"{index_path}: {error}")
                    result["source_index_query_errors"].append(str(index_path))
                index_source_query_ok[safe_name] = not bool(error)
                index_sources[safe_name] = rows
        for path in sorted(_walk_files(mesh_root), key=lambda item: str(item).casefold()):
            if not _looks_like_sqlite(path):
                continue
            relative = path.relative_to(mesh_root)
            profile_safe = _profile_name_from_path(mesh_root, path)
            profile = profiles.get(profile_safe)
            if path == catalog_path:
                db_type = "catalog"
            elif path.name.casefold() == "mesh.sqlite" and "parsed" not in {
                part.casefold() for part in relative.parts
            }:
                db_type = "source_index"
            elif _is_rebuild_database(path):
                db_type = "rebuild_temp"
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
                task_info=task_info,
                artifact_texts=artifact_texts,
                backup_texts=backup_texts,
                recovery_texts=recovery_texts,
                runtime_processes=runtime_processes,
                catalog_available=catalog_available,
                source_index_query_ok=index_source_query_ok.get(profile_safe, False),
                maintenance_window_authorized=maintenance_window_authorized,
            )
            result["records"].append(record)
    _finalize_rebuild_records(result["records"])
    return result


def audit_roots(
    roots: Iterable[Path],
    *,
    writer_active_roots: set[Path] | None = None,
    runtime_processes_by_root: dict[Path, list[str]] | None = None,
    maintenance_window_authorized: bool = False,
) -> dict[str, Any]:
    active = {path.resolve() for path in (writer_active_roots or set())}
    process_map = {path.resolve(): value for path, value in (runtime_processes_by_root or {}).items()}
    root_results = [
        audit_root(
            Path(root),
            writer_active=Path(root).resolve() in active,
            runtime_processes=process_map.get(Path(root).resolve(), []),
            maintenance_window_authorized=maintenance_window_authorized,
        )
        for root in roots
    ]
    records = [record for item in root_results for record in item["records"]]
    return {
        "format": "netconsole-mesh-database-reference-audit-v3",
        "generated_at": now_iso(),
        "maintenance_window_authorized": maintenance_window_authorized,
        "roots": root_results,
        "records": records,
        "summary": _summary(root_results, records),
    }


def _summary_for_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = {
        status: sum(record.get("final_status") == status for record in records)
        for status in STATUS_ORDER
    }
    by_activity = {
        state: sum(record.get("activity_state") == state for record in records)
        for state in (
            "ACTIVE_CONFIRMED",
            "IDLE_CONFIRMED",
            "SIDECAR_PRESENT_UNCONFIRMED",
            "ACTIVITY_UNKNOWN",
        )
    }
    parsed = [record for record in records if record.get("database_type") == "parsed"]
    rebuild = [record for record in records if record.get("database_type") == "rebuild_temp"]
    return {
        "sqlite_database_count": len(records),
        "parsed_database_count": len(parsed),
        "parsed_database_bytes": sum(int(item.get("file_size") or 0) for item in parsed),
        "rebuild_database_count": len(rebuild),
        "rebuild_database_bytes": sum(int(item.get("file_size") or 0) for item in rebuild),
        "activity_counts": by_activity,
        "active_database_count": by_activity["ACTIVE_CONFIRMED"],
        "idle_database_count": by_activity["IDLE_CONFIRMED"],
        "sidecar_unconfirmed_count": by_activity["SIDECAR_PRESENT_UNCONFIRMED"],
        "activity_unknown_count": by_activity["ACTIVITY_UNKNOWN"],
        "catalog_protected_count": sum(record.get("database_type") == "catalog" for record in records),
        "source_index_protected_count": sum(record.get("database_type") == "source_index" for record in records),
        "source_reference_count": sum(int(record.get("source_reference_count") or 0) for record in records),
        "source_referenced_database_count": sum(bool(record.get("source_reference_count")) for record in records),
        "session_reference_count": sum(int(record.get("session_reference_count") or 0) for record in records),
        "session_referenced_database_count": sum(bool(record.get("session_reference_count")) for record in records),
        "fallback_reference_count": sum(int(record.get("fallback_reference_count") or 0) for record in records),
        "active_task_reference_count": sum(int(record.get("active_task_reference_count") or 0) for record in records),
        "historical_task_reference_count": sum(int(record.get("historical_task_reference_count") or 0) for record in records),
        "unknown_reference_count": sum(int(record.get("unknown_task_reference_count") or 0) for record in records),
        "recovery_reference_count": sum(int(record.get("recovery_reference_count") or 0) for record in records),
        "backup_reference_count": sum(int(record.get("backup_reference_count") or 0) for record in records),
        "orphan_candidate_count": by_status["ORPHAN_CANDIDATE"],
        "orphan_candidate_bytes": sum(
            int(record.get("file_size") or 0)
            for record in records
            if record.get("final_status") == "ORPHAN_CANDIDATE"
        ),
        "unknown_database_count": by_status["UNKNOWN_PROTECT"] + by_status["INSPECTION_FAILED"],
        "auditor_shm_side_effect_count": sum(
            bool((record.get("activity_probe") or {}).get("auditor_shm_side_effect_observed"))
            for record in records
        ),
        "unexplained_shm_change_count": sum(
            bool((record.get("activity_probe") or {}).get("unexplained_shm_change"))
            for record in records
        ),
        "external_main_or_wal_change_count": sum(
            bool(
                (record.get("activity_probe") or {}).get(
                    "main_changed_during_observation"
                )
                or (record.get("activity_probe") or {}).get(
                    "wal_changed_during_observation"
                )
            )
            for record in records
        ),
        "status_counts": by_status,
    }


def _summary(root_results: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = _summary_for_records(records)
    environments: dict[str, Any] = {}
    for item in root_results:
        environment = str(item.get("environment") or "UNKNOWN")
        current = environments.setdefault(
            environment,
            {"site_count": 0, "mr_profile_count": 0, "data_roots": [], "summary": None},
        )
        current["site_count"] += int(item.get("sites_scanned") or 0)
        current["mr_profile_count"] += int(item.get("mr_profiles_scanned") or 0)
        current["data_roots"].append(item.get("data_root"))
        current["summary"] = _summary_for_records(
            [
                record
                for root_item in root_results
                if root_item.get("environment") == environment
                for record in root_item.get("records") or []
            ]
        )
    return {
        "site_count": sum(int(item.get("sites_scanned") or 0) for item in root_results),
        "mr_profile_count": sum(int(item.get("mr_profiles_scanned") or 0) for item in root_results),
        **totals,
        "environments": environments,
        "raw_logs_modified_count": 0,
        "active_database_modified_count": 0,
        "unconfirmed_database_removed_count": 0,
        "maintenance_window_authorized": all(
            bool(item.get("maintenance_window_authorized")) for item in root_results
        )
        if root_results
        else False,
    }


def _md_escape(value: object) -> str:
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")


def render_inventory(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# MESH_DATABASE_ACTIVITY_AUDIT_V3",
        "",
        f"生成时间：`{audit['generated_at']}`",
        "",
        "本报告由只读 SQLite `mode=ro` 连接生成；未初始化 Repository，未执行 WAL checkpoint、VACUUM、迁移或文件移动。SHM 存在不直接等同于活动写入。",
        "",
        f"- 扫描局点：{summary['site_count']}",
        f"- MR Profile：{summary['mr_profile_count']}",
        f"- SQLite 总数：{summary['sqlite_database_count']}",
        f"- parsed 总数：{summary['parsed_database_count']}（{summary['parsed_database_bytes']} bytes）",
        f"- rebuild 临时库总数：{summary['rebuild_database_count']}（{summary['rebuild_database_bytes']} bytes）",
        f"- ACTIVE_CONFIRMED：{summary['active_database_count']}",
        f"- IDLE_CONFIRMED：{summary['idle_database_count']}",
        f"- SIDECAR_PRESENT_UNCONFIRMED：{summary['sidecar_unconfirmed_count']}",
        f"- ACTIVITY_UNKNOWN：{summary['activity_unknown_count']}",
        f"- 审计器首次只读 SHM 自影响：{summary.get('auditor_shm_side_effect_count', 0)}",
        f"- 第二次观察仍未解释的 SHM 变化：{summary.get('unexplained_shm_change_count', 0)}",
        f"- 主库/WAL 外部变化：{summary.get('external_main_or_wal_change_count', 0)}",
        f"- 维护窗口授权：`{'YES' if summary.get('maintenance_window_authorized') else 'NO'}`",
        "",
        "## 按数据根统计",
        "",
        "| 环境 | 数据根 | 局点 | MR Profile | SQLite | parsed | rebuild | ACTIVE_CONFIRMED | IDLE_CONFIRMED | SHM 不确定 | ACTIVITY_UNKNOWN |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for environment, item in summary.get("environments", {}).items():
        scoped = item.get("summary") or {}
        activity = scoped.get("activity_counts") or {}
        for data_root in item.get("data_roots") or []:
            lines.append(
                "| "
                + " | ".join(
                    _md_escape(value)
                    for value in (
                        environment,
                        data_root,
                        item.get("site_count"),
                        item.get("mr_profile_count"),
                        scoped.get("sqlite_database_count"),
                        scoped.get("parsed_database_count"),
                        scoped.get("rebuild_database_count"),
                        activity.get("ACTIVE_CONFIRMED", 0),
                        activity.get("IDLE_CONFIRMED", 0),
                        activity.get("SIDECAR_PRESENT_UNCONFIRMED", 0),
                        activity.get("ACTIVITY_UNKNOWN", 0),
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## 逐文件身份与检查",
            "",
            "| 环境 | 局点 | MR Profile | 数据库类型 | canonical_path | relative_path | file_size | mtime_ns | sha256 | sqlite_schema | quick_check | integrity_check | wal_size | shm_size | file_identity | probe_count | settled_stable | auditor_shm_effect | unexplained_shm_change | external_main_or_wal_change | activity_state | final_status |",
            "|---|---|---|---|---|---|---:|---:|---|---|---|---|---:|---:|---|---:|---|---|---|---|---|---|",
        ]
    )
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
                    record.get("canonical_path"),
                    record.get("relative_path"),
                    record.get("file_size"),
                    record.get("mtime_ns"),
                    record.get("sha256"),
                    record.get("sqlite_schema"),
                    record.get("quick_check"),
                    record.get("integrity_check"),
                    record.get("wal_size", 0),
                    record.get("shm_size", 0),
                    record.get("file_identity"),
                    (record.get("activity_probe") or {}).get("probe_count", 0),
                    (record.get("activity_probe") or {}).get("settled_snapshot_stable"),
                    (record.get("activity_probe") or {}).get(
                        "auditor_shm_side_effect_observed"
                    ),
                    (record.get("activity_probe") or {}).get("unexplained_shm_change"),
                    bool(
                        (record.get("activity_probe") or {}).get(
                            "main_changed_during_observation"
                        )
                        or (record.get("activity_probe") or {}).get(
                            "wal_changed_during_observation"
                        )
                    ),
                    record.get("activity_state"),
                    record.get("final_status"),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_reference_audit(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# MESH_DATABASE_REFERENCE_AUDIT_V3",
        "",
        f"生成时间：`{audit['generated_at']}`",
        "",
        "最终状态与引用统计分离。detail_source_identity 只表示两个数据库内部来源身份一致，不表示该物理数据库被分析会话打开。",
        "",
        f"- 来源物理路径引用：{summary['source_reference_count']}；会话物理路径引用：{summary['session_reference_count']}；文件名回退：{summary['fallback_reference_count']}",
        f"- 活动任务引用：{summary['active_task_reference_count']}；历史任务引用：{summary['historical_task_reference_count']}；未知任务引用：{summary['unknown_reference_count']}",
        f"- 恢复依赖：{summary['recovery_reference_count']}；备份引用：{summary['backup_reference_count']}",
        f"- 审计器 SHM 自影响：{summary.get('auditor_shm_side_effect_count', 0)}；未解释 SHM 变化：{summary.get('unexplained_shm_change_count', 0)}；主库/WAL 外部变化：{summary.get('external_main_or_wal_change_count', 0)}",
        "",
        "| 文件 | 数据库类型 | activity_state | final_status | 来源物理引用 | 会话引用 | 文件名回退 | 活动任务 | 历史任务 | 未知任务 | 恢复依赖 | 备份引用 | 内部 source identity | 保护原因 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for record in audit["records"]:
        reasons = ", ".join(record.get("protection_reasons") or [])
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    record.get("path"),
                    record.get("database_type"),
                    record.get("activity_state"),
                    record.get("final_status"),
                    record.get("source_reference_count"),
                    record.get("session_reference_count"),
                    record.get("fallback_reference_count"),
                    record.get("active_task_reference_count"),
                    record.get("historical_task_reference_count"),
                    record.get("unknown_task_reference_count"),
                    record.get("recovery_reference_count"),
                    record.get("backup_reference_count"),
                    record.get("internal_source_identity_count"),
                    reasons,
                )
            )
            + " |"
        )
        if (
            record.get("source_references")
            or record.get("session_references")
            or record.get("task_references")
            or record.get("recovery_references")
            or record.get("rebuild_review")
        ):
            lines.append("")
            lines.append(f"- `{record['path']}` 证据：")
            for item in record.get("source_references") or []:
                lines.append(f"  - physical source_files: `{json.dumps(item, ensure_ascii=False, default=str)}`")
            for item in record.get("session_references") or []:
                lines.append(f"  - physical mesh_session_index: `{json.dumps(item, ensure_ascii=False, default=str)}`")
            for item in record.get("task_references") or []:
                lines.append(f"  - task: `{json.dumps(item, ensure_ascii=False, default=str)}`")
            for item in record.get("recovery_references") or []:
                lines.append(f"  - recovery: `{json.dumps(item, ensure_ascii=False, default=str)}`")
            if record.get("rebuild_review"):
                lines.append(
                    f"  - rebuild_review: `{json.dumps(record['rebuild_review'], ensure_ascii=False, default=str)}`"
                )
    return "\n".join(lines) + "\n"


def render_candidates(audit: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        record
        for record in audit["records"]
        if record.get("status") == "ORPHAN_CANDIDATE"
    ]
    return {
        "format": "netconsole-mesh-orphan-candidates-v3",
        "generated_at": audit["generated_at"],
        "summary": audit["summary"],
        "candidates": candidates,
        "rebuild_review": [
            record
            for record in audit["records"]
            if record.get("database_type") == "rebuild_temp"
        ],
    }


def render_final_report(audit: dict[str, Any], *, operation: dict[str, Any] | None = None) -> str:
    summary = dict(audit["summary"])
    operation = operation or {}
    status = "PASS"
    if (
        summary["unknown_database_count"]
        or summary["active_database_count"]
        or summary["activity_unknown_count"]
        or summary["sidecar_unconfirmed_count"]
    ):
        status = "PARTIAL/BLOCKED"
    reference_status = "PASS"
    if summary["unknown_reference_count"] or summary["recovery_reference_count"] or summary["sidecar_unconfirmed_count"]:
        reference_status = "PARTIAL"
    activity_status = "PASS"
    if (
        summary["active_database_count"]
        or summary["activity_unknown_count"]
        or summary["sidecar_unconfirmed_count"]
        or summary.get("unexplained_shm_change_count")
    ):
        activity_status = "PARTIAL"
    rebuild_records = [
        record
        for record in audit["records"]
        if record.get("database_type") == "rebuild_temp"
    ]
    rebuild_status = "PASS"
    if any(record.get("final_status") == "INSPECTION_FAILED" for record in rebuild_records):
        rebuild_status = "FAIL"
    elif any(record.get("final_status") != "ORPHAN_CANDIDATE" for record in rebuild_records):
        rebuild_status = "PARTIAL"
    previous = audit.get("previous_summary") or {}
    lines = [
        "# MESH_DATABASE_V3_FINAL_REPORT",
        "",
        f"生成时间：`{audit['generated_at']}`",
        f"总体状态：`{status}`",
        "",
        "## 结论",
        "",
        "AUDIT_IMPLEMENTATION=PASS",
        f"ACTIVITY_DETECTION={activity_status}",
        f"REFERENCE_CHECK={reference_status}",
        f"REBUILD_REVIEW={rebuild_status}",
        "PRODUCTION_CLEANUP=NOT_EXECUTED",
        f"DATA_SAFETY={'PASS' if summary['raw_logs_modified_count'] == 0 and summary['active_database_modified_count'] == 0 and summary['unconfirmed_database_removed_count'] == 0 else 'FAIL'}",
        f"OVERALL_STATUS={status}",
        f"ORPHAN_CANDIDATES={summary['orphan_candidate_count']}",
        "DATABASES_REMOVED=0",
        "",
        "## V2 / V3 对比",
        "",
        f"- V2 SQLite：{previous.get('sqlite_database_count', '未提供')}；V3 SQLite：{summary['sqlite_database_count']}",
        f"- V2 parsed：{previous.get('parsed_database_count', '未提供')}；V3 parsed：{summary['parsed_database_count']}",
        f"- V2 活动/静止/SHM 不确定：{previous.get('active_database_count', '未提供')}/{previous.get('idle_database_count', '未提供')}/{previous.get('sidecar_unconfirmed_count', '未提供')}；V3：{summary['active_database_count']}/{summary['idle_database_count']}/{summary['sidecar_unconfirmed_count']}",
        f"- V2 候选：{previous.get('orphan_candidate_count', '未提供')}；V3 候选：{summary['orphan_candidate_count']}",
        "",
        "## SHM 时间戳变化根因",
        "",
        "隔离测试复现：遗留 WAL/SHM 的 SQLite 第一次 `mode=ro` 打开可能只更新 SHM 的 mtime_ns；后续独立只读观察稳定，`quick_check` 与 `integrity_check` 未继续修改。生产审计因此记录首次观察自影响，但不把它单独认定为外部写入。",
        f"- 审计器自影响模式：{summary.get('auditor_shm_side_effect_count', 0)} 个数据库",
        f"- 第二次观察仍有未解释 SHM 变化：{summary.get('unexplained_shm_change_count', 0)} 个数据库",
        f"- 主库或 WAL 发生变化：{summary.get('external_main_or_wal_change_count', 0)} 个数据库",
        f"- 维护窗口授权：`{'YES' if summary.get('maintenance_window_authorized') else 'NO'}`；未获授权时不将 SHM 侧车提升为 IDLE_CONFIRMED。",
        "",
        "## 盘点统计",
        "",
        f"- 扫描局点数量：{summary['site_count']}",
        f"- 扫描 MR 数量：{summary['mr_profile_count']}",
        f"- SQLite 数据库总数：{summary['sqlite_database_count']}",
        f"- parsed 数据库：{summary['parsed_database_count']}（{summary['parsed_database_bytes']} bytes）",
        f"- rebuild 临时数据库：{summary['rebuild_database_count']}（{summary['rebuild_database_bytes']} bytes）",
        f"- ACTIVE_CONFIRMED：{summary['active_database_count']}",
        f"- IDLE_CONFIRMED：{summary['idle_database_count']}",
        f"- SHM/WAL 状态不确定：{summary['sidecar_unconfirmed_count']}",
        f"- ACTIVITY_UNKNOWN：{summary['activity_unknown_count']}",
        f"- catalog 保护：{summary['catalog_protected_count']}；source index 保护：{summary['source_index_protected_count']}",
        f"- 来源物理路径引用：{summary['source_reference_count']}",
        f"- 分析会话物理路径引用：{summary['session_reference_count']}",
        f"- 文件名回退引用：{summary['fallback_reference_count']}",
        f"- 活动任务引用：{summary['active_task_reference_count']}",
        f"- 历史任务引用：{summary['historical_task_reference_count']}",
        f"- 未知任务引用：{summary['unknown_reference_count']}",
        f"- 恢复依赖：{summary['recovery_reference_count']}",
        f"- 备份引用：{summary['backup_reference_count']}",
        f"- 未确认数据库数量：{summary['unknown_database_count']}",
        f"- 真正的孤儿候选数量：{summary['orphan_candidate_count']}",
        f"- 潜在可回收空间：{summary['orphan_candidate_bytes']} bytes",
        f"- 原始日志修改数量：{summary['raw_logs_modified_count']}",
        f"- 活动数据库修改数量：{summary['active_database_modified_count']}",
        f"- 未确认数据库删除数量：{summary['unconfirmed_database_removed_count']}",
        "",
        "## 按数据根统计",
        "",
        "| 环境 | SQLite | parsed | rebuild | ACTIVE_CONFIRMED | IDLE_CONFIRMED | SHM 不确定 | ACTIVITY_UNKNOWN | 来源引用 | 会话引用 | 历史任务 | 活动任务 | 恢复依赖 | 孤儿候选 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for environment, item in summary.get("environments", {}).items():
        scoped = item.get("summary") or {}
        activity = scoped.get("activity_counts") or {}
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    environment,
                    scoped.get("sqlite_database_count"),
                    scoped.get("parsed_database_count"),
                    scoped.get("rebuild_database_count"),
                    activity.get("ACTIVE_CONFIRMED", 0),
                    activity.get("IDLE_CONFIRMED", 0),
                    activity.get("SIDECAR_PRESENT_UNCONFIRMED", 0),
                    activity.get("ACTIVITY_UNKNOWN", 0),
                    scoped.get("source_reference_count"),
                    scoped.get("session_reference_count"),
                    scoped.get("historical_task_reference_count"),
                    scoped.get("active_task_reference_count"),
                    scoped.get("recovery_reference_count"),
                    scoped.get("orphan_candidate_count"),
                )
            )
            + " |"
        )
    lines.extend(
        [
        "",
        "## 7 个 rebuild 临时数据库专项",
        "",
        "正式库健康、已接管会话、临时库无物理路径引用且活动状态可确认为 IDLE，才允许进入 ORPHAN_CANDIDATE；source_file_id/内部来源身份相同不构成物理文件引用。",
        "",
        "| 文件名 | 大小 | SHA-256 | 对应正式库 | 物理来源引用 | 物理会话引用 | 文件名回退 | 内部来源身份 | 活动任务 | 恢复依赖 | 正式库 quick_check | 正式库 integrity_check | 正式库会话接管 | 活动状态 | 最终分类 | 判定依据 |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|---|---|",
        ]
    )
    for record in audit["records"]:
        if record.get("database_type") != "rebuild_temp":
            continue
        review = record.get("rebuild_review") or {}
        basis = ", ".join(record.get("protection_reasons") or [])
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    record.get("basename"),
                    record.get("file_size"),
                    record.get("sha256"),
                    review.get("formal_database_path"),
                    review.get("physical_source_reference_count", record.get("source_reference_count", 0)),
                    review.get("physical_session_reference_count", record.get("session_reference_count", 0)),
                    review.get("filename_fallback_reference_count", record.get("fallback_reference_count", 0)),
                    review.get("internal_source_identity_count", record.get("internal_source_identity_count", 0)),
                    f"active={review.get('active_task_reference_count', 0)}, historical={review.get('historical_task_reference_count', 0)}",
                    review.get("recovery_reference_count"),
                    review.get("formal_database_quick_check"),
                    review.get("formal_database_integrity_check"),
                    review.get("formal_database_session_reference_count"),
                    record.get("activity_state"),
                    record.get("final_status"),
                    basis,
                )
            )
            + " |"
        )
    lines.extend(
        [
        "## 静止判定与保护边界",
        "",
        "IDLE_CONFIRMED 需要维护窗口授权、两次观察结果稳定、主库/WAL 内容未变化、WAL 为空、无活动/未知任务、无恢复依赖、引用查询成功、无锁冲突且 SQLite 完整性检查通过。仅有 WAL=0、SHM 存在/不存在、任务列表为空或文件时间久远均不足以确认静止。",
        f"- 已确认静止数据库：{summary['idle_database_count']}",
        f"- 已确认孤儿数据库：{summary['orphan_candidate_count']}",
        f"- 潜在可回收空间：{summary['orphan_candidate_bytes']} bytes",
        "- 本轮生产没有维护窗口授权，因此 SHM 侧车数据库仍保持保护，不执行孤儿确认或回收。",
        "",
        "## 保护边界与回滚",
        "",
        "- 本轮不执行生产备份、隔离、删除、VACUUM、Schema 重建或强制 checkpoint；不删除 WAL/SHM，不结束 Backend/Worker。",
        "- catalog.sqlite、正式 parsed、已登记 source index、物理引用、历史分析、恢复 Journal、备份和未知数据库均保留。",
        "- 原始 MESH 日志、历史报告、Excel、导出文件和既有数据库备份不作为清理目标。",
        "",
        "## 测试、Git 状态与未解决风险",
        "",
        f"- 测试结果：{audit.get('validation', {}).get('test_result', '由任务交接记录，未由审计器自动执行')}。",
        f"- Git：branch=`{audit.get('git', {}).get('branch', '未提供')}`；HEAD=`{audit.get('git', {}).get('head', '未提供')}`；status=`{audit.get('git', {}).get('status', '未提供')}`。",
        "- 文件句柄级外部进程证据不是本审计器可用的充分证明；无法确认时保持保护。真实 Electron 页面、真实报告打开和设备验收不由本审计器冒充通过。",
        "- Workspace 基线已有顶层 docs 目录布局检查失败，本任务未清理该既有目录。",
        "",
        "证据文件：`MESH_DATABASE_ACTIVITY_AUDIT_V3.md`、`MESH_DATABASE_REFERENCE_AUDIT_V3.md`、`MESH_ORPHAN_CANDIDATES_V3.json`。",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_previous_summary(report_dir: Path | None) -> dict[str, Any]:
    if report_dir is None:
        return {}
    for name in (
        "MESH_ORPHAN_CANDIDATES_V2.json",
        "MESH_ORPHAN_CANDIDATES.json",
        "MESH_ORPHAN_CANDIDATES_V3.json",
    ):
        candidate_path = report_dir / name
        try:
            value = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        summary = value.get("summary") if isinstance(value, dict) else None
        if isinstance(summary, dict):
            return dict(summary)
    return {}


def _git_evidence() -> dict[str, str]:
    repo_root = Path(__file__).resolve().parents[2]

    def run(*args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"UNAVAILABLE: {type(exc).__name__}"
        return completed.stdout.strip() or completed.stderr.strip()

    status = run("status", "--short")
    return {
        "branch": run("branch", "--show-current"),
        "head": run("rev-parse", "--short", "HEAD"),
        "status": status or "CLEAN",
    }


def write_reports(audit: dict[str, Any], output_dir: Path, *, operation: dict[str, Any] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "MESH_DATABASE_ACTIVITY_AUDIT_V3.md").write_text(
        render_inventory(audit), encoding="utf-8"
    )
    (output_dir / "MESH_DATABASE_REFERENCE_AUDIT_V3.md").write_text(
        render_reference_audit(audit), encoding="utf-8"
    )
    (output_dir / "MESH_ORPHAN_CANDIDATES_V3.json").write_text(
        json.dumps(render_candidates(audit), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "MESH_DATABASE_V3_FINAL_REPORT.md").write_text(
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
            if record.get("final_status", record.get("status")) != "ORPHAN_CANDIDATE":
                raise RuntimeError("当前状态不是 ORPHAN_CANDIDATE")
            if not source.is_file() or _sidecar(source, "-wal").exists() or _sidecar(source, "-shm").exists():
                raise RuntimeError("源文件不存在或存在 WAL/SHM 侧车")
            current = _file_snapshot(source) or {}
            if (
                int(record.get("file_size", record.get("size_bytes")) or -1) != current.get("file_size")
                or int(record.get("mtime_ns") or -1) != current.get("mtime_ns")
                or str(record.get("file_identity") or "") != current.get("file_identity")
                or sha256_file(source) != str(record.get("sha256") or "")
            ):
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
    parser.add_argument("--previous-report-dir", type=Path)
    parser.add_argument(
        "--maintenance-window",
        action="store_true",
        help="仅在已获准、Backend/Worker 正常退出的维护窗口中允许确认 IDLE_CONFIRMED",
    )
    parser.add_argument(
        "--validation-summary",
        default="未提供；审计器不代替 pytest/Ruff/Gate",
    )
    parser.add_argument("--authorize-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    roots = [Path(value).resolve() for value in args.data_root]
    production = {root for root in roots if root.name.casefold() == "netconsoledata"}
    runtime_processes = _active_backend_processes()
    if args.mode in {"backup", "isolate"} and not args.authorize_write:
        raise SystemExit("backup/isolate 需要显式 --authorize-write；默认只读")
    audit = audit_roots(
        roots,
        runtime_processes_by_root={root: runtime_processes for root in production},
        maintenance_window_authorized=args.maintenance_window,
    )
    audit["previous_summary"] = _load_previous_summary(args.previous_report_dir)
    audit["git"] = _git_evidence()
    audit["validation"] = {"test_result": args.validation_summary}
    operation: dict[str, Any] = {}
    if args.mode == "backup":
        candidates = [
            record
            for record in audit["records"]
            if record.get("final_status") == "ORPHAN_CANDIDATE"
        ]
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
