from __future__ import annotations

import hashlib
import gc
import os
import sqlite3
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
