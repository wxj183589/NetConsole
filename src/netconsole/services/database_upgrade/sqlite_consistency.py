from __future__ import annotations

import hashlib
import gc
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_wal(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        return {"status": "NOT_PRESENT", "busy": 0, "log_frames": 0, "checkpointed_frames": 0}
    connection: sqlite3.Connection | None = None
    checkpoint_result: tuple[int, int, int] = (0, 0, 0)
    journal_mode = ""
    try:
        connection = sqlite3.connect(path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        row = connection.execute("PRAGMA wal_checkpoint(FULL)").fetchone() or (0, 0, 0)
        checkpoint_result = tuple(int(row[index] or 0) for index in range(3))
        busy, log_frames, checkpointed_frames = checkpoint_result
        if busy:
            raise RuntimeError(f"SQLite WAL checkpoint 未完成：busy={busy}")
        # TRUNCATE keeps the database's configured journal mode intact while
        # ensuring WAL frames are not left beside a file that will be copied.
        truncate_row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() or (0, 0, 0)
        truncate_busy = int(truncate_row[0] or 0)
        if truncate_busy:
            raise RuntimeError(f"SQLite WAL truncate checkpoint 未完成：busy={truncate_busy}")
        mode_row = connection.execute("PRAGMA journal_mode").fetchone()
        journal_mode = str(mode_row[0] if mode_row else "").casefold()
    finally:
        if connection is not None:
            connection.close()
            gc.collect()
    wal_path = path.with_name(path.name + "-wal")
    shm_path = path.with_name(path.name + "-shm")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    if wal_size:
        raise RuntimeError(f"SQLite WAL checkpoint 后仍有未清理数据：{wal_path.name} ({wal_size} bytes)")
    # These are runtime sidecars, never part of a database backup. They may
    # remain as zero-length files on Windows after the last connection closes.
    wal_sidecar = _try_remove_runtime_sidecar(wal_path)
    # SQLite's shared-memory file can remain locked by the Windows VFS even
    # after the last Python connection is closed. It is runtime state, not
    # database content, so retaining it is safe when Windows refuses unlink.
    shm_sidecar = _try_remove_runtime_sidecar(shm_path, tolerate_in_use=True)
    return {
        "status": "OK",
        "busy": checkpoint_result[0],
        "log_frames": checkpoint_result[1],
        "checkpointed_frames": checkpoint_result[2],
        "journal_mode": journal_mode,
        "wal_sidecar": wal_sidecar,
        "shm_sidecar": shm_sidecar,
    }


def _try_remove_runtime_sidecar(path: Path, *, tolerate_in_use: bool = False) -> str:
    """清理已无数据的 SQLite 运行侧车；Windows 句柄暂未释放时保留空文件。"""

    if not path.exists():
        return "absent"
    try:
        path.unlink()
        return "cleared"
    except OSError:
        try:
            size = path.stat().st_size
        except OSError:
            if tolerate_in_use:
                return "retained_in_use"
            raise
        if size > 0 and not tolerate_in_use:
            raise
        return "retained_in_use" if tolerate_in_use else "retained_empty_in_use"


def sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError("源 SQLite 数据库不存在或为空")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(source, timeout=30)
        source_connection.execute("PRAGMA busy_timeout = 30000")
        target_connection = sqlite3.connect(temporary)
        source_connection.backup(target_connection)
        target_connection.commit()
        target_connection.close()
        target_connection = None
        with temporary.open("rb") as handle:
            handle.seek(0, 2)
            if handle.tell() <= 0:
                raise ValueError("SQLite Backup API 生成了空数据库")
        os.replace(temporary, destination)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        temporary.unlink(missing_ok=True)


_IDENTITY_SNAPSHOT_PREFIX = "netconsole-sqlite-identity-"
_IDENTITY_SNAPSHOT_MAX_AGE_SECONDS = 24 * 60 * 60
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _assert_no_reparse_points(path: Path) -> None:
    current = Path(path)
    while True:
        if _is_reparse_point(current):
            raise ValueError("SQLite logical identity temp path must not contain a reparse point")
        if current.parent == current:
            return
        current = current.parent


def _prepare_identity_temp_root(temp_dir: Path | None, source: Path) -> Path:
    root = Path(temp_dir) if temp_dir is not None else source.parent / ".netconsole-sqlite-identity"
    root = root.absolute()
    _assert_no_reparse_points(root)
    root.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_points(root)
    try:
        return root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("SQLite logical identity temp root is not accessible") from exc


def _cleanup_stale_identity_snapshots(root: Path) -> None:
    cutoff = time.time() - _IDENTITY_SNAPSHOT_MAX_AGE_SECONDS
    for candidate in root.glob(f"{_IDENTITY_SNAPSHOT_PREFIX}*"):
        try:
            _assert_no_reparse_points(candidate)
            if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate)
        except OSError:
            continue


def _stream_canonical_sqlite_identity(
    connection: sqlite3.Connection,
    metadata: dict[str, Any],
) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0

    def update(value: str) -> None:
        nonlocal size_bytes
        encoded = value.encode("utf-8")
        digest.update(encoded)
        size_bytes += len(encoded)

    update('{"dump":"')
    first_line = True
    for line in connection.iterdump():
        if not first_line:
            update(r"\n")
        first_line = False
        escaped = json.dumps(line, ensure_ascii=False)[1:-1]
        update(escaped)
    update(r"\n")
    update('","metadata":')
    update(json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    update("}")
    return size_bytes, digest.hexdigest()


def sqlite_logical_identity(path: Path, *, temp_dir: Path | None = None) -> dict[str, Any]:
    """Return a stable identity for the logical SQLite contents.

    The source is opened read-only and copied through SQLite's Backup API into
    an isolated temporary file.  Hashing a canonical dump of that snapshot
    deliberately avoids treating WAL/checkpoint layout as database content.
    """

    source = path.resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError("源 SQLite 数据库不存在或为空")
    temporary_root = _prepare_identity_temp_root(temp_dir, source)
    _cleanup_stale_identity_snapshots(temporary_root)
    with tempfile.TemporaryDirectory(
        dir=temporary_root,
        prefix=_IDENTITY_SNAPSHOT_PREFIX,
    ) as temporary_dir:
        temporary_path = Path(temporary_dir)
        _assert_no_reparse_points(temporary_path)
        if temporary_path.resolve(strict=True).parent != temporary_root:
            raise ValueError("SQLite logical identity snapshot escaped its managed temp root")
        snapshot = Path(temporary_dir) / "snapshot.sqlite"
        source_connection: sqlite3.Connection | None = None
        target_connection: sqlite3.Connection | None = None
        try:
            source_uri = f"{source.as_uri()}?mode=ro"
            source_connection = sqlite3.connect(source_uri, uri=True, timeout=30)
            source_connection.execute("PRAGMA query_only = ON")
            target_connection = sqlite3.connect(snapshot)
            source_connection.backup(target_connection)
            target_connection.commit()
        finally:
            if target_connection is not None:
                target_connection.close()
            if source_connection is not None:
                source_connection.close()
        validation = validate_sqlite(snapshot)
        if not validation.get("valid"):
            raise ValueError(str(validation.get("error") or "SQLite logical snapshot 校验失败"))
        connection: sqlite3.Connection | None = None
        try:
            snapshot_uri = f"{snapshot.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(snapshot_uri, uri=True, timeout=30)
            connection.execute("PRAGMA query_only = ON")
            metadata = {
                "application_id": int(connection.execute("PRAGMA application_id").fetchone()[0] or 0),
                "encoding": str(connection.execute("PRAGMA encoding").fetchone()[0] or ""),
                "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0] or 0),
            }
            size_bytes, digest = _stream_canonical_sqlite_identity(connection, metadata)
        finally:
            if connection is not None:
                connection.close()
    return {
        "identity_format": "sqlite-logical-v1",
        "size_bytes": size_bytes,
        "sha256": digest,
    }


def validate_sqlite(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() and path.stat().st_size > 0 else "",
        "quick_check": "missing",
        "integrity_check": "missing",
        "schema_version": "unknown",
        "parser_version": "unknown",
        "page_count": 0,
        "page_size": 0,
        "freelist_count": 0,
        "table_names": [],
        "index_names": [],
        "source_file_count": 0,
        "session_count": 0,
        "link_record_count": 0,
        "switch_event_count": 0,
        "rssi_record_count": 0,
        "valid": False,
        "error": "",
    }
    if not result["exists"] or not result["size_bytes"]:
        result["error"] = "数据库不存在或为空"
        return result
    connection: sqlite3.Connection | None = None
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=30)
        connection.execute("PRAGMA query_only = ON")
        result["quick_check"] = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        result["integrity_check"] = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        result["page_count"] = int(connection.execute("PRAGMA page_count").fetchone()[0] or 0)
        result["page_size"] = int(connection.execute("PRAGMA page_size").fetchone()[0] or 0)
        result["freelist_count"] = int(connection.execute("PRAGMA freelist_count").fetchone()[0] or 0)
        result["table_names"] = sorted(
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        )
        result["index_names"] = sorted(
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        )
        for table in ("schema_meta", "meta"):
            try:
                row = connection.execute(
                    f"SELECT value FROM {table} WHERE key IN ('schema_version', 'schema_' || 'version') LIMIT 1"
                ).fetchone()
            except sqlite3.Error:
                continue
            if row:
                result["schema_version"] = str(row[0] or "unknown")
                break
        if "meta" in result["table_names"]:
            parser_row = connection.execute("SELECT value FROM meta WHERE key = 'parser_version' LIMIT 1").fetchone()
            if parser_row:
                result["parser_version"] = str(parser_row[0] or "unknown")
        count_tables = {
            "source_file_count": "source_files",
            "session_count": "mesh_sessions",
            "link_record_count": "mesh_links",
            "switch_event_count": "switch_events",
            "rssi_record_count": "rssi_stats",
        }
        for field, table in count_tables.items():
            if table in result["table_names"]:
                result[field] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
        result["valid"] = result["quick_check"] == "ok" and result["integrity_check"] == "ok"
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    finally:
        if connection is not None:
            connection.close()
    return result


def fsync_file(path: Path) -> None:
    # Windows rejects FlushFileBuffers for a descriptor opened without write access.
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())
