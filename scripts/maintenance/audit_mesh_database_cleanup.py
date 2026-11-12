"""只读盘点 MESH 派生 SQLite，并提供候选优先的备份/隔离入口。

默认命令只读。该脚本不创建 Repository、不执行 SQLite migration/checkpoint，
也不删除 raw、报告、备份或任何数据库。backup/isolate 必须显式指定，且会在
重新核验文件快照、引用、WAL/SHM 和任务状态后逐文件处理。
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


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
V41_EXECUTION_MODES = ("AUDIT_ONLY", "BACKUP_ONLY", "ISOLATE_APPROVED")
HANDLE_FREE_CONFIRMED = "HANDLE_FREE_CONFIRMED"
HANDLE_OCCUPIED = "HANDLE_OCCUPIED"
HANDLE_UNCONFIRMED = "HANDLE_UNCONFIRMED"
HANDLE_PROBE_FAILED = "HANDLE_PROBE_FAILED"
ERROR_MORE_DATA = 234
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _RmUniqueProcess(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]


class _RmProcessInfo(ctypes.Structure):
    _fields_ = [
        ("Process", _RmUniqueProcess),
        ("strAppName", wintypes.WCHAR * 257),
        ("strServiceShortName", wintypes.WCHAR * 65),
        ("ApplicationType", wintypes.DWORD),
        ("AppStatus", wintypes.DWORD),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


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


@contextmanager
def read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(_ro_uri(path), uri=True, timeout=3)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=3000")
        yield connection
    finally:
        connection.close()


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


def _runtime_process_evidence() -> dict[str, Any]:
    """Collect read-only process evidence without stopping or attaching to processes."""
    evidence: dict[str, Any] = {
        "backend_worker": _active_backend_processes(),
        "electron": [],
        "python_mesh": [],
        "handle_probe": "UNAVAILABLE",
        "notes": [],
    }
    if os.name != "nt":
        evidence["notes"].append("Windows process evidence is unavailable on this host")
        return evidence
    for image in ("electron.exe",):
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            evidence["notes"].append(f"{image} tasklist failed: {type(exc).__name__}")
            continue
        evidence["electron"].extend(
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip() and "INFO:" not in line.upper()
        )

    # Command-line evidence is limited to Python processes that identify a
    # NetConsole/MESH path. The current V4 audit process is excluded.
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
        "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        raw = completed.stdout.strip()
        if raw:
            values = json.loads(raw)
            rows = values if isinstance(values, list) else [values]
            current_pid = os.getpid()
            for row in rows:
                text = str(row.get("CommandLine") or "")
                pid = int(row.get("ProcessId") or 0)
                lowered = text.casefold()
                if pid == current_pid or "audit_mesh_database_cleanup.py" in lowered:
                    continue
                if any(token in lowered for token in ("netconsole", "mesh", "rail_transit")):
                    evidence["python_mesh"].append(
                        {"pid": pid, "command_line": text}
                    )
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        evidence["notes"].append(f"Python command-line probe failed: {type(exc).__name__}")
    if shutil.which("handle.exe"):
        evidence["handle_probe"] = "TOOL_AVAILABLE_NOT_RUN"
        evidence["notes"].append("handle.exe detected but not executed to avoid external handle-tool side effects")
    else:
        evidence["notes"].append("handle.exe unavailable; Windows file-handle ownership is unconfirmed")
    return evidence


def _restart_manager_probe(paths: list[Path]) -> dict[str, Any]:
    """Use Windows Restart Manager only as one part of a read-only handle probe."""
    result: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "processes": [],
        "error_code": 0,
        "error": "",
        "coverage": "Restart Manager resource registration and process listing only",
    }
    if os.name != "nt":
        result["error"] = "Windows API unavailable on this host"
        return result
    existing = [path for path in paths if path.is_file()]
    if not existing:
        result.update(status="NO_FILES", coverage="No existing file required registration")
        return result
    try:
        dll = ctypes.WinDLL("rstrtmgr.dll", use_last_error=True)
        start = dll.RmStartSession
        start.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
        start.restype = wintypes.DWORD
        register = dll.RmRegisterResources
        register.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            ctypes.POINTER(wintypes.LPWSTR),
            wintypes.UINT,
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        register.restype = wintypes.DWORD
        get_list = dll.RmGetList
        get_list.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(_RmProcessInfo),
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_list.restype = wintypes.DWORD
        end = dll.RmEndSession
        end.argtypes = [wintypes.DWORD]
        end.restype = wintypes.DWORD
    except (AttributeError, OSError) as exc:
        result.update(status="FAILED", error=f"Restart Manager load failed: {type(exc).__name__}: {exc}")
        return result

    session = wintypes.DWORD(0)
    session_key = ctypes.create_unicode_buffer(33)
    code = int(start(ctypes.byref(session), 0, session_key))
    if code != 0:
        result.update(status="FAILED", error_code=code, error=f"RmStartSession failed: {code}")
        return result
    try:
        buffers = [ctypes.create_unicode_buffer(str(path.resolve())) for path in existing]
        resource_paths = (wintypes.LPWSTR * len(buffers))()
        for index, buffer in enumerate(buffers):
            resource_paths[index] = ctypes.cast(buffer, wintypes.LPWSTR)
        code = int(register(session, len(buffers), resource_paths, 0, None, 0, None))
        if code != 0:
            result.update(status="FAILED", error_code=code, error=f"RmRegisterResources failed: {code}")
            return result
        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reason = wintypes.DWORD(0)
        code = int(get_list(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason)))
        if code not in (0, ERROR_MORE_DATA):
            result.update(status="FAILED", error_code=code, error=f"RmGetList sizing failed: {code}")
            return result
        capacity = max(int(needed.value), int(count.value), 1)
        info_array = (_RmProcessInfo * capacity)()
        count = wintypes.UINT(capacity)
        code = int(
            get_list(
                session,
                ctypes.byref(needed),
                ctypes.byref(count),
                info_array,
                ctypes.byref(reason),
            )
        )
        if code not in (0, ERROR_MORE_DATA):
            result.update(status="FAILED", error_code=code, error=f"RmGetList failed: {code}")
            return result
        result["processes"] = [
            {
                "pid": int(info_array[index].Process.dwProcessId),
                "application": str(info_array[index].strAppName),
                "service": str(info_array[index].strServiceShortName),
                "application_type": int(info_array[index].ApplicationType),
                "session_id": int(info_array[index].TSSessionId),
            }
            for index in range(min(int(count.value), capacity))
        ]
        result["status"] = "OCCUPIED" if result["processes"] else "EMPTY"
        result["restart_reason"] = int(reason.value)
        return result
    finally:
        end_code = int(end(session))
        if end_code and not result.get("error"):
            result["error_code"] = end_code
            result["error"] = f"RmEndSession failed: {end_code}"


def _exclusive_open_probe(path: Path) -> dict[str, Any]:
    """Attempt a short read-only Windows sharing conflict probe and release immediately."""
    result = {
        "status": "UNAVAILABLE",
        "error_code": 0,
        "error": "",
        "operation": "CreateFileW(GENERIC_READ, share=0) then CloseHandle",
    }
    if not path.is_file():
        result["status"] = "NOT_PRESENT"
        return result
    if os.name != "nt":
        result["error"] = "Windows API unavailable on this host"
        return result
    try:
        kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
    except (AttributeError, OSError) as exc:
        result["status"] = "FAILED"
        result["error"] = f"CreateFileW load failed: {type(exc).__name__}: {exc}"
        return result
    handle = create_file(str(path.resolve()), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE_VALUE:
        code = int(ctypes.get_last_error())
        result["error_code"] = code
        if code in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
            result["status"] = "OCCUPIED"
        elif code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            result["status"] = "NOT_PRESENT"
        elif code == ERROR_ACCESS_DENIED:
            result["status"] = "UNCONFIRMED"
        else:
            result["status"] = "FAILED"
        result["error"] = f"CreateFileW failed: {code}"
        return result
    try:
        result["status"] = "FREE"
        return result
    finally:
        if not close_handle(handle):
            result["status"] = "FAILED"
            result["error"] = f"CloseHandle failed: {ctypes.get_last_error()}"


def _handle_group_audit(paths: Iterable[Path]) -> dict[str, Any]:
    unique_paths = sorted({Path(path).resolve() for path in paths}, key=lambda item: str(item).casefold())
    restart = _restart_manager_probe(unique_paths)
    restart_processes = restart.get("processes") or []
    files: list[dict[str, Any]] = []
    for path in unique_paths:
        sharing = _exclusive_open_probe(path)
        if sharing["status"] == "OCCUPIED" or restart_processes:
            status = HANDLE_OCCUPIED
        elif sharing["status"] == "FAILED":
            status = HANDLE_PROBE_FAILED
        elif sharing["status"] in {"UNCONFIRMED", "UNAVAILABLE"}:
            status = HANDLE_UNCONFIRMED
        elif sharing["status"] == "NOT_PRESENT":
            status = "NOT_PRESENT"
        elif restart["status"] == "EMPTY":
            status = HANDLE_FREE_CONFIRMED
        else:
            status = HANDLE_UNCONFIRMED
        files.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "restart_manager": restart,
                "sharing_probe": sharing,
                "status": status,
            }
        )
    present_statuses = [item["status"] for item in files if item["status"] != "NOT_PRESENT"]
    if any(status == HANDLE_OCCUPIED for status in present_statuses):
        overall = HANDLE_OCCUPIED
    elif any(status == HANDLE_PROBE_FAILED for status in present_statuses):
        overall = HANDLE_PROBE_FAILED
    elif any(status == HANDLE_UNCONFIRMED for status in present_statuses):
        overall = HANDLE_UNCONFIRMED
    elif all(status in {HANDLE_FREE_CONFIRMED, "NOT_PRESENT"} for status in (item["status"] for item in files)):
        overall = HANDLE_FREE_CONFIRMED
    else:
        overall = HANDLE_UNCONFIRMED
    return {
        "status": overall,
        "paths": [str(path) for path in unique_paths],
        "files": files,
        "restart_manager": restart,
        "limitations": [
            "Restart Manager 仅列出可识别的注册资源进程，不穷尽所有句柄来源。",
            "HANDLE_FREE_CONFIRMED 仅在 Restart Manager 空结果与短时 share=0 读取探针同时通过时给出。",
            "未执行第三方 handle.exe，不终止进程、不关闭其他进程句柄、不修改 SQLite。",
        ],
    }


def _handle_groups_for_targets(target_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for target in target_results:
        rebuild = Path(str(target.get("path") or "")).resolve()
        formal = Path(str(target.get("formal_database_path") or "")).resolve()
        key = (str(rebuild), str(formal))
        if key in seen:
            continue
        seen.add(key)
        groups.append(
            {
                "rebuild_path": str(rebuild),
                "formal_database_path": str(formal),
                "paths": [
                    str(rebuild),
                    str(_sidecar(rebuild, "-wal")),
                    str(_sidecar(rebuild, "-shm")),
                    str(formal),
                    str(_sidecar(formal, "-wal")),
                    str(_sidecar(formal, "-shm")),
                ],
            }
        )
    return groups


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
    selected_paths: set[Path] | None = None,
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
        "selected_paths": sorted(str(path.resolve()) for path in (selected_paths or set())),
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
        site_selected_paths = {
            path.resolve()
            for path in (selected_paths or set())
            if _within(path, mesh_root)
        }
        if selected_paths is not None and not site_selected_paths:
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
        profile_names = (
            {
                _profile_name_from_path(mesh_root, path)
                for path in site_selected_paths
            }
            if selected_paths is not None
            else set(profiles)
        )
        for safe_name in profile_names:
            index_path = mesh_root / safe_name / "mesh.sqlite"
            if index_path.is_file():
                rows, error = _read_rows(index_path, "source_files")
                if error:
                    result["errors"].append(f"{index_path}: {error}")
                    result["source_index_query_errors"].append(str(index_path))
                index_source_query_ok[safe_name] = not bool(error)
                index_sources[safe_name] = rows
        paths = (
            sorted(site_selected_paths, key=lambda item: str(item).casefold())
            if selected_paths is not None
            else sorted(_walk_files(mesh_root), key=lambda item: str(item).casefold())
        )
        for path in paths:
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
    selected_paths_by_root: dict[Path, set[Path]] | None = None,
) -> dict[str, Any]:
    active = {path.resolve() for path in (writer_active_roots or set())}
    process_map = {path.resolve(): value for path, value in (runtime_processes_by_root or {}).items()}
    selected_map = {
        path.resolve(): {item.resolve() for item in values}
        for path, values in (selected_paths_by_root or {}).items()
    }
    root_results = [
        audit_root(
            Path(root),
            writer_active=Path(root).resolve() in active,
            runtime_processes=process_map.get(Path(root).resolve(), []),
            maintenance_window_authorized=maintenance_window_authorized,
            selected_paths=(selected_map.get(Path(root).resolve()) if selected_paths_by_root is not None else None),
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


def _load_v3_rebuild_scope(report_dir: Path) -> dict[str, Any]:
    candidate_path = report_dir / "MESH_ORPHAN_CANDIDATES_V3.json"
    result: dict[str, Any] = {
        "report_path": str(candidate_path),
        "records": [],
        "selected_paths_by_root": {},
        "validation_errors": [],
    }
    try:
        payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result["validation_errors"].append(
            f"无法读取 V3 rebuild_review：{type(exc).__name__}: {exc}"
        )
        return result
    reviews = payload.get("rebuild_review") if isinstance(payload, dict) else None
    if not isinstance(reviews, list) or len(reviews) != 7:
        result["validation_errors"].append(
            f"V3 rebuild_review 必须恰好包含 7 个文件，实际为 {len(reviews or [])}"
        )
        return result
    seen_paths: set[Path] = set()
    for item in reviews:
        if not isinstance(item, dict):
            result["validation_errors"].append("V3 rebuild_review 存在非对象条目")
            continue
        rebuild_review = item.get("rebuild_review") or {}
        raw_path = _clean_text(item.get("canonical_path") or item.get("path"))
        raw_target = _clean_text(rebuild_review.get("formal_database_path"))
        raw_data_root = _clean_text(item.get("data_root"))
        path = Path(raw_path).resolve() if raw_path else Path("__missing_v3_rebuild__.sqlite").resolve()
        target = Path(raw_target).resolve() if raw_target else Path("__missing_v3_formal__.sqlite").resolve()
        data_root = Path(raw_data_root).resolve() if raw_data_root else Path("__missing_v3_root__").resolve()
        identity = _file_snapshot(path)
        actual_hash = ""
        if path.is_file():
            try:
                actual_hash = sha256_file(path)
            except OSError as exc:
                result["validation_errors"].append(f"无法计算 {path} SHA-256：{exc}")
        checks = {
            "path_inside_data_root": bool(raw_path and raw_data_root and _within(path, data_root)),
            "is_rebuild_name": _is_rebuild_database(path),
            "path_unique": path not in seen_paths,
            "target_path_valid": bool(
                raw_target and raw_data_root and _within(target, data_root)
            ),
            "file_exists": identity is not None,
            "file_size_match": bool(identity and identity["file_size"] == item.get("file_size")),
            "sha256_match": bool(actual_hash and actual_hash == item.get("sha256")),
            "file_identity_match": bool(
                identity and identity.get("file_identity") == item.get("file_identity")
            ),
            "target_path_present": bool(raw_target),
            "target_inside_same_root": bool(raw_target and raw_data_root and _within(target, data_root)),
        }
        seen_paths.add(path)
        errors = [name for name, passed in checks.items() if not passed]
        if errors:
            result["validation_errors"].append(
                f"{path}: V3 精确身份校验失败：{', '.join(errors)}"
            )
        if raw_data_root and raw_path and raw_target:
            root_key = data_root
            result["selected_paths_by_root"].setdefault(root_key, set()).update(
                {path, target}
            )
        result["records"].append(
            {
                "v3_record": item,
                "v3_rebuild_review": rebuild_review,
                "path": str(path),
                "formal_database_path": str(target),
                "data_root": str(data_root),
                "mr_profile_id": item.get("mr_profile_id"),
                "mr_name": item.get("mr_name"),
                "identity_checks": checks,
                "identity_errors": errors,
                "actual_snapshot_before_audit": identity,
                "actual_sha256_before_audit": actual_hash,
            }
        )
    if len(seen_paths) != 7:
        result["validation_errors"].append("V3 rebuild 临时库存在重复路径")
    return result


def _v4_target_results(
    scope: dict[str, Any],
    targeted_audit: dict[str, Any],
    *,
    maintenance_authorized: bool,
    runtime_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    records_by_path = {
        str(record.get("canonical_path")): record
        for record in targeted_audit.get("records") or []
    }
    handle_confirmed = runtime_evidence.get("handle_probe") == "CONFIRMED_NO_ACTIVE_HANDLES"
    results: list[dict[str, Any]] = []
    for item in scope.get("records") or []:
        path = str(Path(item["path"]).resolve())
        record = records_by_path.get(path)
        review = (record or {}).get("rebuild_review") or {}
        blockers: list[str] = []
        if item.get("identity_errors"):
            blockers.append("V3_IDENTITY_DRIFT")
        if record is None:
            blockers.append("TARGETED_AUDIT_RECORD_MISSING")
        else:
            if record.get("mr_profile_id") != item.get("mr_profile_id"):
                blockers.append("MR_PROFILE_MISMATCH")
            if str(Path(record.get("rebuild_target_path") or "").resolve()) != item.get(
                "formal_database_path"
            ):
                blockers.append("FORMAL_DATABASE_PATH_MISMATCH")
            if record.get("source_reference_count"):
                blockers.append("PHYSICAL_SOURCE_REFERENCE")
            if record.get("session_reference_count"):
                blockers.append("PHYSICAL_SESSION_REFERENCE")
            if record.get("fallback_reference_count"):
                blockers.append("FILENAME_FALLBACK_REFERENCE")
            if record.get("active_task_reference_count") or record.get(
                "historical_task_reference_count"
            ) or record.get("unknown_task_reference_count"):
                blockers.append("TASK_REFERENCE")
            if record.get("recovery_reference_count"):
                blockers.append("RECOVERY_REFERENCE")
            if record.get("backup_reference_count"):
                blockers.append("BACKUP_REFERENCE")
            if not record.get("source_index_query_ok"):
                blockers.append("SOURCE_INDEX_QUERY_INCOMPLETE")
            if (record.get("activity_probe") or {}).get("task_query_status") != "OK":
                blockers.append("TASK_QUERY_INCOMPLETE")
            if not (record.get("activity_probe") or {}).get("catalog_available"):
                blockers.append("CATALOG_QUERY_INCOMPLETE")
            if record.get("activity_state") != "IDLE_CONFIRMED":
                blockers.append(str(record.get("activity_state") or "ACTIVITY_UNKNOWN"))
            if not review.get("formal_database_healthy"):
                blockers.append("FORMAL_DATABASE_UNHEALTHY")
            if not int(review.get("formal_database_session_reference_count") or 0):
                blockers.append("FORMAL_DATABASE_SESSION_NOT_TAKEN")
        if not maintenance_authorized:
            blockers.append("MAINTENANCE_AUTHORIZED_NO")
        if not handle_confirmed:
            blockers.append("WINDOWS_HANDLE_UNCONFIRMED")
        reference_ok = bool(
            record
            and not any(
                reason in blockers
                for reason in (
                    "V3_IDENTITY_DRIFT",
                    "TARGETED_AUDIT_RECORD_MISSING",
                    "PHYSICAL_SOURCE_REFERENCE",
                    "PHYSICAL_SESSION_REFERENCE",
                    "FILENAME_FALLBACK_REFERENCE",
                    "TASK_REFERENCE",
                    "RECOVERY_REFERENCE",
                    "BACKUP_REFERENCE",
                    "SOURCE_INDEX_QUERY_INCOMPLETE",
                    "TASK_QUERY_INCOMPLETE",
                    "CATALOG_QUERY_INCOMPLETE",
                )
            )
        )
        candidate = bool(
            maintenance_authorized
            and handle_confirmed
            and reference_ok
            and record
            and record.get("activity_state") == "IDLE_CONFIRMED"
            and review.get("formal_database_healthy")
            and int(review.get("formal_database_session_reference_count") or 0) > 0
        )
        results.append(
            {
                "path": path,
                "formal_database_path": item.get("formal_database_path"),
                "mr_profile_id": item.get("mr_profile_id"),
                "mr_name": item.get("mr_name"),
                "v3_identity_checks": item.get("identity_checks"),
                "v3_identity_errors": item.get("identity_errors"),
                "record": record,
                "rebuild_review": review,
                "reference_check": "PASS" if reference_ok else "FAIL",
                "activity_state": (record or {}).get("activity_state", "ACTIVITY_UNKNOWN"),
                "maintenance_authorized": maintenance_authorized,
                "windows_handle_confirmed": handle_confirmed,
                "orphan_candidate": candidate,
                "blockers": sorted(set(blockers)),
            }
        )
    return results


def audit_v4(
    roots: Iterable[Path],
    *,
    previous_report_dir: Path,
    maintenance_authorized: bool = False,
) -> dict[str, Any]:
    scope = _load_v3_rebuild_scope(previous_report_dir)
    runtime_evidence = _runtime_process_evidence()
    runtime_processes = list(runtime_evidence.get("backend_worker") or [])
    runtime_processes.extend(runtime_evidence.get("electron") or [])
    runtime_processes.extend(
        str(item.get("command_line") or "")
        for item in runtime_evidence.get("python_mesh") or []
    )
    root_paths = {Path(root).resolve() for root in roots}
    selected = {
        root: paths
        for root, paths in (scope.get("selected_paths_by_root") or {}).items()
        if root in root_paths
    }
    missing_roots = sorted(
        str(root)
        for root in (scope.get("selected_paths_by_root") or {})
        if root not in root_paths
    )
    if missing_roots:
        scope["validation_errors"].append(
            "V3 目标数据根未包含在本轮 --data-root：" + ", ".join(missing_roots)
        )
    runtime_by_root = {root: runtime_processes for root in selected}
    targeted_audit = audit_roots(
        selected.keys(),
        runtime_processes_by_root=runtime_by_root,
        maintenance_window_authorized=maintenance_authorized,
        selected_paths_by_root=selected,
    ) if selected else {
        "format": "netconsole-mesh-database-reference-audit-v3",
        "generated_at": now_iso(),
        "records": [],
        "roots": [],
        "summary": _summary([], []),
    }
    target_results = _v4_target_results(
        scope,
        targeted_audit,
        maintenance_authorized=maintenance_authorized,
        runtime_evidence=runtime_evidence,
    )
    candidates = [item for item in target_results if item.get("orphan_candidate")]
    reference_status = (
        "PASS"
        if target_results
        and not scope.get("validation_errors")
        and all(item.get("reference_check") == "PASS" for item in target_results)
        else "PARTIAL"
    )
    activity_status = (
        "PASS"
        if target_results
        and all(item.get("activity_state") == "IDLE_CONFIRMED" for item in target_results)
        and maintenance_authorized
        and runtime_evidence.get("handle_probe") == "CONFIRMED_NO_ACTIVE_HANDLES"
        else "PARTIAL"
    )
    return {
        "format": "netconsole-mesh-database-reference-audit-v4",
        "generated_at": now_iso(),
        "roots": [str(root) for root in selected],
        "previous_report_dir": str(previous_report_dir.resolve()),
        "maintenance_authorized": maintenance_authorized,
        "runtime_evidence": runtime_evidence,
        "scope": scope,
        "targeted_audit": targeted_audit,
        "target_results": target_results,
        "candidates": candidates,
        "v3_baseline_summary": _load_previous_summary(previous_report_dir),
        "git": _git_evidence(),
        "validation": {},
        "status": {
            "activity_verification": activity_status,
            "reference_check": reference_status,
            "backup_verification": "NOT_EXECUTED",
            "isolation": "NOT_EXECUTED",
        "production_isolation": "NOT_EXECUTED",
            "rollback_ready": "NO",
            "data_safety": "PASS",
            "orphan_candidates": len(candidates),
            "databases_isolated": 0,
            "databases_removed": 0,
            "logical_isolation_bytes": 0,
            "actual_released_bytes": 0,
            "raw_logs_modified": 0,
            "formal_databases_modified": 0,
            "overall_status": "PASS" if candidates else "BLOCKED",
        },
    }


def _empty_v4_backup_manifest(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "netconsole-mesh-v4-backup-manifest",
        "generated_at": audit["generated_at"],
        "maintenance_authorized": bool(audit.get("maintenance_authorized")),
        "backup_verification": "NOT_EXECUTED",
        "backup_success_count": 0,
        "entries": [],
        "reason": "没有同时满足维护授权、静止、句柄、引用和正式库接管门槛；未创建备份路径。",
    }


def _empty_v4_isolation_manifest(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "netconsole-mesh-v4-isolation-manifest",
        "generated_at": audit["generated_at"],
        "maintenance_authorized": bool(audit.get("maintenance_authorized")),
        "isolation": "NOT_EXECUTED",
        "isolated_count": 0,
        "logical_isolation_bytes": 0,
        "actual_released_bytes": 0,
        "entries": [],
        "reason": "没有确认孤儿候选；未移动任何生产文件。",
    }


def render_v4_final_report(audit: dict[str, Any]) -> str:
    status = audit["status"]
    runtime = audit.get("runtime_evidence") or {}
    baseline = audit.get("v3_baseline_summary") or {}
    targeted = audit.get("targeted_audit", {}).get("summary") or {}
    lines = [
        "# MESH_DATABASE_V4_FINAL_REPORT",
        "",
        f"生成时间：`{audit['generated_at']}`",
        f"MAINTENANCE_AUTHORIZED={'YES' if audit.get('maintenance_authorized') else 'NO'}",
        f"ACTIVITY_VERIFICATION={status['activity_verification']}",
        f"REFERENCE_CHECK={status['reference_check']}",
        f"BACKUP_VERIFICATION={status['backup_verification']}",
        f"ISOLATION={status['isolation']}",
        f"PRODUCTION_ISOLATION={status['production_isolation']}",
        f"ROLLBACK_READY={status['rollback_ready']}",
        f"DATA_SAFETY={status['data_safety']}",
        f"ORPHAN_CANDIDATES={status['orphan_candidates']}",
        f"DATABASES_ISOLATED={status['databases_isolated']}",
        f"DATABASES_REMOVED={status['databases_removed']}",
        f"OVERALL_STATUS={status['overall_status']}",
        "",
        "## 维护窗口与运行状态",
        "",
        "- 本轮没有获得用户/运维维护授权证据；未停止或强制结束任何进程。",
        f"- Backend/Worker：`{json.dumps(runtime.get('backend_worker') or [], ensure_ascii=False)}`",
        f"- Electron：`{json.dumps(runtime.get('electron') or [], ensure_ascii=False)}`",
        f"- 相关 Python/MESH 进程：`{json.dumps(runtime.get('python_mesh') or [], ensure_ascii=False)}`",
        f"- Windows 文件句柄探针：`{runtime.get('handle_probe', 'UNAVAILABLE')}`；句柄所有权未确认时禁止隔离。",
        f"- SQLite 只读活动状态（本轮目标）：{targeted.get('activity_counts', {})}；这不替代 Windows 句柄级证明。",
        "",
        "## V3 / V4 范围",
        "",
        f"- V3 全量基线：SQLite {baseline.get('sqlite_database_count', '未提供')}、parsed {baseline.get('parsed_database_count', '未提供')}、rebuild {baseline.get('rebuild_database_count', '未提供')}。",
        "- V3 的 27 个正式 parsed 数据库全部保留保护；catalog.sqlite、mesh.sqlite、raw 日志及其他数据库均未纳入隔离目标。",
        "- V4 只精确复查 V3 rebuild_review 中的 7 个临时库及其对应正式库映射；多个 rebuild 映射同一正式库时仍逐文件核验。",
        f"- V4 目标记录：{len(audit.get('target_results') or [])} 个 rebuild；候选 {status['orphan_candidates']}；逻辑隔离 {status['logical_isolation_bytes']} bytes；实际释放 {status['actual_released_bytes']} bytes。",
        "",
        "## 7 个 rebuild 逐文件复核",
        "",
        "| 文件 | 对应正式库 | 身份校验 | SHA-256/大小 | 物理来源 | 物理会话 | 内部身份 | 活动状态 | 正式库健康 | 最终判定 | 阻断原因 |",
        "|---|---|---|---|---:|---:|---:|---|---|---|---|",
    ]
    for item in audit.get("target_results") or []:
        record = item.get("record") or {}
        review = item.get("rebuild_review") or {}
        identity = item.get("v3_identity_checks") or {}
        identity_text = "PASS" if identity and all(identity.values()) else "FAIL"
        size_hash = f"{record.get('file_size', '')} / {record.get('sha256', '')}"
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    Path(item.get("path", "")).name,
                    item.get("formal_database_path"),
                    identity_text,
                    size_hash,
                    record.get("source_reference_count", 0),
                    record.get("session_reference_count", 0),
                    record.get("internal_source_identity_count", 0),
                    item.get("activity_state"),
                    f"{review.get('formal_database_quick_check', '')}/{review.get('formal_database_integrity_check', '')}",
                    "ORPHAN_CANDIDATE" if item.get("orphan_candidate") else "PROTECTED",
                    ", ".join(item.get("blockers") or []),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 引用、备份、隔离与回滚",
            "",
            f"- 来源物理引用：{sum(int((item.get('record') or {}).get('source_reference_count') or 0) for item in audit.get('target_results') or [])}",
            f"- 物理会话引用：{sum(int((item.get('record') or {}).get('session_reference_count') or 0) for item in audit.get('target_results') or [])}",
            f"- 活动任务/恢复依赖：{sum(int((item.get('record') or {}).get('active_task_reference_count') or 0) for item in audit.get('target_results') or [])}/{sum(int((item.get('record') or {}).get('recovery_reference_count') or 0) for item in audit.get('target_results') or [])}",
            "- 成功备份数量：0；备份验证：NOT_EXECUTED；没有伪造备份路径。",
            "- 成功隔离数量：0；隔离 Manifest 为空；没有移动正式 parsed、catalog、mesh.sqlite、raw 或其他数据库。",
            "- 回滚位置：未创建隔离，无需回滚；Rollback Manifest 明确记录 ROLLBACK_READY=NO。",
            f"- 原始日志修改数量：{status['raw_logs_modified']}；正式数据库修改数量：{status['formal_databases_modified']}。",
            "",
            "## 测试与未解决阻断",
            "",
            f"- 测试结果：{audit.get('validation', {}).get('test_result', '待任务交接填写')}。",
            "- 真实 Electron/MESH 历史分析、Excel 导出和现场设备回归：NOT_EXECUTED。",
            "- 5 个 V3 未解释 SHM 变化和 1 个 DEV_REAL ACTIVITY_UNKNOWN 继续保护，不属于本轮 7 个目标的清理授权。",
            "- Windows 句柄级证据不可用或未确认；维护授权缺失；因此不执行 Backup API 或隔离。",
            "",
            f"Git：branch=`{audit.get('git', {}).get('branch', '未提供')}`；HEAD=`{audit.get('git', {}).get('head', '未提供')}`；status=`{audit.get('git', {}).get('status', '未提供')}`。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_v4_rollback(audit: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# MESH_DATABASE_V4_ROLLBACK",
            "",
            "ROLLBACK_READY=NO",
            "",
            "本轮未执行备份或隔离，未创建回滚目录和回滚文件。没有可恢复的移动操作。",
            "下一阶段必须先用 SQLite Backup API 创建并验证独立备份，再执行逐文件同卷隔离；任何失败按 Manifest 恢复。",
            "",
            f"生成时间：`{audit['generated_at']}`",
        ]
    ) + "\n"


def write_v4_reports(audit: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "MESH_DATABASE_V4_FINAL_REPORT.md").write_text(
        render_v4_final_report(audit), encoding="utf-8"
    )
    (output_dir / "MESH_DATABASE_V4_CANDIDATES.json").write_text(
        json.dumps(
            {
                "format": "netconsole-mesh-v4-candidates",
                "generated_at": audit["generated_at"],
                "summary": audit["status"],
                "v3_baseline_summary": audit.get("v3_baseline_summary"),
                "runtime_evidence": audit.get("runtime_evidence"),
                "target_results": audit.get("target_results"),
                "candidates": audit.get("candidates"),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "MESH_DATABASE_V4_BACKUP_MANIFEST.json").write_text(
        json.dumps(_empty_v4_backup_manifest(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "MESH_DATABASE_V4_ISOLATION_MANIFEST.json").write_text(
        json.dumps(_empty_v4_isolation_manifest(audit), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "MESH_DATABASE_V4_ROLLBACK.md").write_text(
        render_v4_rollback(audit), encoding="utf-8"
    )


def _write_v41_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _v41_load_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(value, dict):
        return None, "JSON 根必须是对象"
    return value, ""


def _v41_candidate_manifest_scope(payload: dict[str, Any]) -> dict[str, set[str]]:
    candidates = payload.get("candidates") or []
    roots: set[str] = set()
    sites: set[str] = set()
    mr_profiles: set[str] = set()
    paths: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        record = item.get("record") or {}
        path = item.get("path") or record.get("canonical_path")
        if path:
            paths.add(str(Path(str(path)).resolve()))
        if record.get("data_root"):
            roots.add(str(Path(str(record["data_root"])).resolve()))
        if record.get("site"):
            sites.add(str(record["site"]))
        if item.get("mr_profile_id") or record.get("mr_profile_id"):
            mr_profiles.add(str(item.get("mr_profile_id") or record.get("mr_profile_id")))
    return {"data_roots": roots, "sites": sites, "mr_profiles": mr_profiles, "paths": paths}


def _v41_parse_window(value: object) -> tuple[datetime, datetime] | None:
    if not isinstance(value, dict):
        return None
    try:
        start = datetime.fromisoformat(str(value.get("start") or "").replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(value.get("end") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return start.astimezone(UTC), end.astimezone(UTC)


def _v41_validate_authorization(
    authorization_path: Path | None,
    *,
    requested_mode: str,
    candidate_manifest_path: Path,
    candidate_manifest: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "NOT_PROVIDED" if authorization_path is None else "FAIL",
        "path": str(authorization_path.resolve()) if authorization_path else "",
        "errors": [],
        "payload": {},
    }
    if requested_mode == "AUDIT_ONLY":
        result["status"] = "NOT_REQUIRED"
        return result
    if authorization_path is None:
        result["errors"].append("未提供实际操作人员授权文件")
        return result
    payload, error = _v41_load_json(authorization_path)
    if payload is None:
        result["errors"].append(error)
        return result
    result["payload"] = payload
    if payload.get("format") != "netconsole-mesh-maintenance-authorization-v1":
        result["errors"].append("授权文件 format 不匹配")
    if payload.get("mode") != requested_mode:
        result["errors"].append(f"授权 mode 必须为 {requested_mode}")
    if payload.get("authorized") is not True:
        result["errors"].append("authorized 必须由实际操作人员明确设置为 true")
    confirmation = payload.get("confirmation")
    if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
        result["errors"].append("缺少显式 confirmation.confirmed=true")
    if not isinstance(confirmation, dict) or not confirmation.get("operator"):
        result["errors"].append("缺少 confirmation.operator")
    if not isinstance(confirmation, dict) or not confirmation.get("confirmed_at"):
        result["errors"].append("缺少 confirmation.confirmed_at")
    if not str(payload.get("operation_scope") or "").strip():
        result["errors"].append("缺少 operation_scope")
    window = _v41_parse_window(payload.get("maintenance_window"))
    if window is None:
        result["errors"].append("maintenance_window 必须包含有效 start/end")
    elif not window[0] <= datetime.now(UTC) <= window[1]:
        result["errors"].append("当前时间不在维护窗口内")
    scope = _v41_candidate_manifest_scope(candidate_manifest)
    declared_roots = {
        str(Path(str(item)).resolve()) for item in payload.get("data_roots") or []
    }
    declared_sites = {str(item) for item in payload.get("sites") or []}
    declared_mr_profiles = {str(item) for item in payload.get("mr_profiles") or []}
    declared_paths = {
        str(Path(str(item)).resolve()) for item in payload.get("candidate_paths") or []
    }
    if declared_roots != scope["data_roots"]:
        result["errors"].append("授权 data_roots 与候选 Manifest 不一致")
    if declared_sites != scope["sites"]:
        result["errors"].append("授权 sites 与候选 Manifest 不一致")
    if declared_mr_profiles != scope["mr_profiles"]:
        result["errors"].append("授权 mr_profiles 与候选 Manifest 不一致")
    if declared_paths != scope["paths"]:
        result["errors"].append("授权 candidate_paths 与候选 Manifest 不一致")
    declared_manifest = Path(str(payload.get("candidate_manifest") or "")).resolve()
    if declared_manifest != candidate_manifest_path.resolve():
        result["errors"].append("授权 candidate_manifest 不是本轮 V4 Manifest")
    else:
        actual_hash = sha256_file(candidate_manifest_path)
        if actual_hash != str(payload.get("candidate_manifest_sha256") or ""):
            result["errors"].append("候选 Manifest SHA-256 不匹配")
    if requested_mode == "ISOLATE_APPROVED":
        if not payload.get("backup_manifest") or not payload.get("backup_manifest_sha256"):
            result["errors"].append("ISOLATE_APPROVED 必须绑定已验证 Backup Manifest")
    if not result["errors"]:
        result["status"] = "PASS"
    return result


def _v41_file_group_snapshot(paths: Iterable[Path]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in sorted({Path(item).resolve() for item in paths}, key=lambda item: str(item).casefold()):
        snapshot = _file_snapshot(path)
        item = {"path": str(path), "exists": bool(snapshot)}
        if snapshot:
            item.update(snapshot, sha256=sha256_file(path))
        else:
            item.update(canonical_path=str(path), file_size=0, mtime_ns=0, file_identity="", sha256="")
        snapshots.append(item)
    return snapshots


def _v41_group_snapshot_matches(expected: list[dict[str, Any]], paths: Iterable[Path]) -> bool:
    actual = {item["path"]: item for item in _v41_file_group_snapshot(paths)}
    for item in expected:
        current = actual.get(str(Path(str(item.get("path") or "")).resolve()))
        if current is None:
            return False
        for field in ("exists", "file_size", "file_identity", "sha256"):
            if current.get(field) != item.get(field):
                return False
    return True


def _v41_target_record(item: dict[str, Any]) -> dict[str, Any]:
    record = dict(item.get("record") or {})
    if not record:
        record = dict(item)
    return record


def _v41_backup_candidates(
    candidates: list[dict[str, Any]],
    *,
    audit_id: str,
    authorization: dict[str, Any],
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    source_root = Path(__file__).resolve().parents[2] / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from netconsole.core.paths import PathResolver
    from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore

    result: dict[str, Any] = {
        "format": "netconsole-mesh-v4-1-backup-manifest",
        "audit_id": audit_id,
        "execution_mode": "BACKUP_ONLY",
        "authorization": authorization,
        "created_at": now_iso(),
        "backup_success_count": 0,
        "backup_failure_count": 0,
        "entries": [],
    }
    for candidate in candidates:
        record = _v41_target_record(candidate)
        source = Path(str(candidate.get("path") or record.get("canonical_path") or "")).resolve()
        entry: dict[str, Any] = {
            "state": "PENDING",
            "source": str(source),
            "formal_database_path": candidate.get("formal_database_path") or record.get("rebuild_target_path"),
            "file_group": candidate.get("file_group") or _v41_file_group_snapshot(
                [source, _sidecar(source, "-wal"), _sidecar(source, "-shm")]
            ),
        }
        try:
            if candidate.get("orphan_candidate") is not True:
                raise RuntimeError("当前文件不是 ORPHAN_CANDIDATE")
            if record.get("activity_state") != "IDLE_CONFIRMED":
                raise RuntimeError("活动状态不是 IDLE_CONFIRMED")
            if candidate.get("reference_check") != "PASS":
                raise RuntimeError("引用检查不是 PASS")
            if candidate.get("windows_handle_status") != HANDLE_FREE_CONFIRMED:
                raise RuntimeError("文件组句柄不是 HANDLE_FREE_CONFIRMED")
            review = candidate.get("rebuild_review") or {}
            if not review.get("formal_database_healthy") or not int(
                review.get("formal_database_session_reference_count") or 0
            ):
                raise RuntimeError("正式库健康或会话接管门槛未通过")
            if not source.is_file() or not _is_rebuild_database(source):
                raise RuntimeError("源文件不存在或不是精确 rebuild 文件")
            if not _v41_group_snapshot_matches(entry["file_group"], [Path(item["path"]) for item in entry["file_group"]]):
                raise RuntimeError("隔离前文件组快照已变化")
            root = Path(str(record.get("data_root") or "")).resolve()
            if not _within(source, root) or _is_reparse(source):
                raise RuntimeError("源路径越界或为符号链接")
            store = DatabaseBackupStore(PathResolver(data_root=root))
            entry["state"] = "BACKUP_CREATING"
            created = store.create(
                source_path=source,
                database_kind="mesh_derived_orphan",
                scope_type="mesh_orphan_cleanup_v4_1",
                scope_id=f"{record.get('site', '')}_{record.get('safe_folder_name', '')}",
                task_id=audit_id,
                old_version=str(record.get("schema_version") or ""),
                target_version=str(record.get("schema_version") or ""),
                strategy="MESH_V4_1_SQLITE_BACKUP_API",
                reason="MESH V4.1 authorized orphan candidate backup",
                metadata={
                    "formal_database_path": entry["formal_database_path"],
                    "source_file_identity": (entry["file_group"][0] or {}).get("file_identity", ""),
                    "source_sha256": (entry["file_group"][0] or {}).get("sha256", ""),
                    "authorization": authorization,
                },
                checkpoint={"wal": "verified_absent_or_zero", "shm": "verified_by_handle_probe"},
            )
            validated = store.validate(str(created["backup_id"]))
            validation = validated.get("validation") or {}
            if not validation.get("restorable") or validation.get("quick_check") != "ok" or validation.get("integrity_check") != "ok":
                raise RuntimeError("SQLite Backup API 备份独立完整性校验失败")
            if not _v41_group_snapshot_matches(entry["file_group"], [Path(item["path"]) for item in entry["file_group"]]):
                raise RuntimeError("备份期间源文件组发生变化")
            entry.update(
                {
                    "state": "BACKUP_VERIFIED",
                    "backup_id": created.get("backup_id"),
                    "backup_path": created.get("path"),
                    "backup_database_path": validation.get("path"),
                    "backup_size": validation.get("size_bytes", 0),
                    "backup_sha256": validation.get("sha256", ""),
                    "backup_schema": validation.get("schema_version", ""),
                    "backup_validation": validation,
                    "verified_at": now_iso(),
                }
            )
            result["backup_success_count"] += 1
        except Exception as exc:
            entry.update(state="FAILED", error=f"{type(exc).__name__}: {exc}")
            result["backup_failure_count"] += 1
        result["entries"].append(entry)
        if manifest_path:
            _write_v41_json(manifest_path, result)
    result["backup_workflow"] = (
        "PASS"
        if result["backup_success_count"] == len(candidates) and not result["backup_failure_count"]
        else "FAIL"
        if result["backup_failure_count"]
        else "NOT_EXECUTED"
    )
    if manifest_path:
        _write_v41_json(manifest_path, result)
    return result


def _v41_isolation_target(quarantine: Path, source: Path, main_source: Path) -> Path:
    suffix = source.name[len(main_source.name) :] if source.name.startswith(main_source.name) else ""
    return quarantine / f"{main_source.name}.isolated{suffix}"


def _v41_isolate_backup_manifest(
    backup_manifest: dict[str, Any],
    *,
    audit_id: str,
    handle_groups: dict[str, dict[str, Any]],
    authorization: dict[str, Any],
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    result = {
        "format": "netconsole-mesh-v4-1-isolation-manifest",
        "audit_id": audit_id,
        "execution_mode": "ISOLATE_APPROVED",
        "authorization": authorization,
        "created_at": now_iso(),
        "isolated_count": 0,
        "logical_isolation_bytes": 0,
        "actual_released_bytes": 0,
        "entries": [],
    }
    entries = backup_manifest.get("entries") or []
    for backup_entry in entries:
        if backup_entry.get("state") != "BACKUP_VERIFIED":
            continue
        source = Path(str(backup_entry.get("source") or "")).resolve()
        entry = {
            "state": "PENDING",
            "source": str(source),
            "formal_database_path": backup_entry.get("formal_database_path"),
            "backup_id": backup_entry.get("backup_id"),
            "backup_path": backup_entry.get("backup_path"),
            "file_group": backup_entry.get("file_group") or [],
            "moved_files": [],
        }
        try:
            group = handle_groups.get(str(source)) or {}
            if group.get("status") != HANDLE_FREE_CONFIRMED:
                raise RuntimeError(f"隔离前句柄状态不是 HANDLE_FREE_CONFIRMED：{group.get('status')}")
            root = next(
                (
                    parent
                    for parent in source.parents
                    if parent.name.casefold() == "sites"
                ),
                None,
            )
            if root is None:
                raise RuntimeError("无法从源路径解析 sites 根")
            data_root = root.parent.resolve()
            quarantine = (data_root / "backups" / "mesh_orphan_quarantine" / audit_id).resolve()
            if quarantine.drive.casefold() != source.drive.casefold():
                raise RuntimeError("隔离目录与源文件不在同一卷")
            main_source = source
            group_paths = [Path(str(item["path"])).resolve() for item in entry["file_group"]]
            if not _v41_group_snapshot_matches(entry["file_group"], group_paths):
                raise RuntimeError("隔离前文件组快照已变化")
            quarantine.mkdir(parents=True, exist_ok=True)
            targets: list[tuple[Path, Path, dict[str, Any]]] = []
            for item in entry["file_group"]:
                current = Path(str(item["path"])).resolve()
                if not item.get("exists"):
                    continue
                target = _v41_isolation_target(quarantine, current, main_source)
                if target.exists():
                    raise RuntimeError(f"隔离目标已存在：{target}")
                targets.append((current, target, item))
            entry["state"] = "ISOLATING"
            result["entries"].append(entry)
            if manifest_path:
                _write_v41_json(manifest_path, result)
            for current, target, snapshot in targets:
                if target.exists():
                    raise RuntimeError(f"隔离目标在移动前出现：{target}")
                current.rename(target)
                entry["moved_files"].append(
                    {
                        "source": str(current),
                        "target": str(target),
                        "file_size": snapshot.get("file_size", 0),
                        "file_identity": snapshot.get("file_identity", ""),
                        "sha256": snapshot.get("sha256", ""),
                    }
                )
                entry["logical_isolation_bytes"] = int(entry.get("logical_isolation_bytes") or 0) + int(
                    snapshot.get("file_size") or 0
                )
                if manifest_path:
                    _write_v41_json(manifest_path, result)
            entry.update(state="ISOLATED", isolated_at=now_iso())
            result["isolated_count"] += 1
            result["logical_isolation_bytes"] += int(entry.get("logical_isolation_bytes") or 0)
        except Exception as exc:
            entry.update(state="ROLLBACK_REQUIRED" if entry.get("moved_files") else "FAILED")
            entry["error"] = f"{type(exc).__name__}: {exc}"
        if entry not in result["entries"]:
            result["entries"].append(entry)
        if manifest_path:
            _write_v41_json(manifest_path, result)
        if entry.get("state") == "ROLLBACK_REQUIRED":
            result["workflow"] = "PARTIAL"
            break
    result["workflow"] = result.get("workflow") or (
        "PASS"
        if result["isolated_count"] == len([item for item in entries if item.get("state") == "BACKUP_VERIFIED"])
        and not any(item.get("state") in {"FAILED", "ROLLBACK_REQUIRED"} for item in result.get("entries") or [])
        else "NOT_EXECUTED"
        if not entries
        else "FAIL"
    )
    if manifest_path:
        _write_v41_json(manifest_path, result)
    return result


def _v41_rollback_isolation(
    isolation_manifest: dict[str, Any],
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    result = dict(isolation_manifest)
    result["rollback_started_at"] = now_iso()
    entries = result.get("entries") or []
    for entry in entries:
        if entry.get("state") == "ROLLED_BACK":
            continue
        moved = entry.get("moved_files") or []
        try:
            for item in reversed(moved):
                source = Path(str(item.get("source") or "")).resolve()
                target = Path(str(item.get("target") or "")).resolve()
                if source.exists() and target.exists():
                    raise RuntimeError(f"回滚路径冲突：源和隔离目标同时存在：{source}")
                if source.exists() and not target.exists():
                    continue
                if not target.is_file():
                    raise RuntimeError(f"回滚目标不存在：{target}")
                if sha256_file(target) != str(item.get("sha256") or ""):
                    raise RuntimeError(f"隔离文件 SHA-256 变化：{target}")
                source.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    raise RuntimeError(f"回滚不得覆盖新文件：{source}")
                target.rename(source)
            entry["state"] = "ROLLED_BACK"
            entry["rolled_back_at"] = now_iso()
        except Exception as exc:
            entry["state"] = "ROLLBACK_REQUIRED"
            entry["rollback_error"] = f"{type(exc).__name__}: {exc}"
            if manifest_path:
                _write_v41_json(manifest_path, result)
            break
        if manifest_path:
            _write_v41_json(manifest_path, result)
    result["rollback_workflow"] = (
        "PASS"
        if entries and all(item.get("state") == "ROLLED_BACK" for item in entries)
        else "NOT_EXECUTED"
        if not entries
        else "FAIL"
    )
    if manifest_path:
        _write_v41_json(manifest_path, result)
    return result


def audit_v41(
    roots: Iterable[Path],
    *,
    previous_report_dir: Path,
    v4_report_dir: Path,
    output_dir: Path,
    execution_mode: str = "AUDIT_ONLY",
    authorization_file: Path | None = None,
    audit_id: str = "mesh-v4-1",
    backup_manifest: Path | None = None,
    test_workflow_status: str = "NOT_EXECUTED",
) -> dict[str, Any]:
    if execution_mode not in V41_EXECUTION_MODES:
        raise ValueError(f"不支持的 V4.1 execution mode：{execution_mode}")
    candidate_manifest_path = v4_report_dir / "MESH_DATABASE_V4_CANDIDATES.json"
    candidate_manifest, manifest_error = _v41_load_json(candidate_manifest_path)
    if candidate_manifest is None:
        candidate_manifest = {"candidates": [], "target_results": []}
    authorization = _v41_validate_authorization(
        authorization_file,
        requested_mode=execution_mode,
        candidate_manifest_path=candidate_manifest_path,
        candidate_manifest=candidate_manifest,
    )
    authorized = authorization.get("status") == "PASS"
    base = audit_v4(
        roots,
        previous_report_dir=previous_report_dir,
        maintenance_authorized=authorized,
    )
    target_results = list(base.get("target_results") or [])
    handle_groups = _handle_groups_for_targets(target_results)
    group_results: dict[str, dict[str, Any]] = {}
    for group in handle_groups:
        group_audit = _handle_group_audit(Path(path) for path in group["paths"])
        group_result = {**group, **group_audit}
        group_results[group["rebuild_path"]] = group_result
    handle_statuses = [item.get("status") for item in group_results.values()]
    for item in target_results:
        rebuild_path = str(Path(str(item.get("path") or "")).resolve())
        group_result = group_results.get(rebuild_path) or {}
        handle_status = str(group_result.get("status") or HANDLE_UNCONFIRMED)
        item["handle_group_status"] = handle_status
        item["handle_group"] = group_result
        item["windows_handle_status"] = handle_status
        blockers = set(item.get("blockers") or [])
        if handle_status == HANDLE_FREE_CONFIRMED:
            # V4's runtime evidence cannot prove this after the native probe
            # runs.  Remove only that stale derived blocker; preserve every
            # independent activity/reference/formal-database blocker.
            blockers.discard("WINDOWS_HANDLE_UNCONFIRMED")
        else:
            item["orphan_candidate"] = False
            blockers.add(handle_status)
        item["blockers"] = sorted(blockers)
    candidates = [item for item in target_results if item.get("orphan_candidate")]
    handle_detection = (
        "PASS"
        if os.name == "nt" and handle_statuses and HANDLE_PROBE_FAILED not in handle_statuses
        else "PARTIAL"
        if handle_statuses
        else "FAIL"
    )
    if handle_statuses and all(status == HANDLE_FREE_CONFIRMED for status in handle_statuses):
        handle_detection = "PASS"
    windows_runtime = (
        "PASS"
        if authorized
        and base["status"].get("activity_verification") == "PASS"
        and handle_statuses
        and all(status == HANDLE_FREE_CONFIRMED for status in handle_statuses)
        and not base["runtime_evidence"].get("backend_worker")
        and not base["runtime_evidence"].get("electron")
        and not base["runtime_evidence"].get("python_mesh")
        else "FAIL"
        if HANDLE_PROBE_FAILED in handle_statuses
        else "PARTIAL"
    )
    backup_result: dict[str, Any] = {
        "format": "netconsole-mesh-v4-1-backup-manifest",
        "execution_mode": execution_mode,
        "authorization": authorization,
        "backup_success_count": 0,
        "backup_failure_count": 0,
        "entries": [],
        "backup_workflow": "NOT_EXECUTED",
        "reason": "未同时满足授权、静止、引用、正式库和句柄门禁；未创建生产备份。",
    }
    isolation_result: dict[str, Any] = {
        "format": "netconsole-mesh-v4-1-isolation-manifest",
        "execution_mode": execution_mode,
        "authorization": authorization,
        "isolated_count": 0,
        "logical_isolation_bytes": 0,
        "actual_released_bytes": 0,
        "entries": [],
        "workflow": "NOT_EXECUTED",
        "reason": "未同时满足授权、备份和隔离前复核门禁；未移动生产文件。",
    }
    if execution_mode == "BACKUP_ONLY" and authorized and candidates:
        backup_result = _v41_backup_candidates(
            candidates,
            audit_id=audit_id,
            authorization=authorization,
            manifest_path=output_dir / "MESH_DATABASE_V4_1_BACKUP_MANIFEST.json",
        )
    elif execution_mode == "ISOLATE_APPROVED" and authorized:
        payload = authorization.get("payload") or {}
        supplied_backup = backup_manifest or Path(str(payload.get("backup_manifest") or ""))
        supplied_backup = supplied_backup.resolve()
        supplied_payload, supplied_error = _v41_load_json(supplied_backup)
        if supplied_payload is not None and not supplied_error:
            expected_hash = str(payload.get("backup_manifest_sha256") or "")
            if expected_hash and sha256_file(supplied_backup) == expected_hash:
                isolation_result = _v41_isolate_backup_manifest(
                    supplied_payload,
                    audit_id=audit_id,
                    handle_groups=group_results,
                    authorization=authorization,
                    manifest_path=output_dir / "MESH_DATABASE_V4_1_ISOLATION_MANIFEST.json",
                )
            else:
                isolation_result["reason"] = "Backup Manifest SHA-256 不匹配，禁止隔离。"
        else:
            isolation_result["reason"] = f"无法读取 Backup Manifest：{supplied_error}"
    elif execution_mode == "AUDIT_ONLY":
        backup_result["reason"] = "AUDIT_ONLY：只读检查，不创建生产备份。"
        isolation_result["reason"] = "AUDIT_ONLY：只读检查，不执行隔离。"
    if not (output_dir / "MESH_DATABASE_V4_1_BACKUP_MANIFEST.json").is_file():
        _write_v41_json(output_dir / "MESH_DATABASE_V4_1_BACKUP_MANIFEST.json", backup_result)
    if not (output_dir / "MESH_DATABASE_V4_1_ISOLATION_MANIFEST.json").is_file():
        _write_v41_json(output_dir / "MESH_DATABASE_V4_1_ISOLATION_MANIFEST.json", isolation_result)
    production_backup = (
        "PASS"
        if backup_result.get("backup_workflow") == "PASS"
        else "FAIL"
        if backup_result.get("backup_failure_count")
        else "NOT_EXECUTED"
    )
    production_isolation = (
        "PASS"
        if isolation_result.get("workflow") == "PASS"
        else "FAIL"
        if isolation_result.get("workflow") in {"FAIL", "PARTIAL"}
        else "NOT_EXECUTED"
    )
    workflow_status = test_workflow_status if test_workflow_status in {"PASS", "PARTIAL", "FAIL"} else "PARTIAL"
    overall = (
        "FAIL"
        if production_backup == "FAIL" or production_isolation == "FAIL"
        else "BLOCKED"
        if not authorized
        else "PASS"
        if production_isolation == "PASS"
        else "PARTIAL"
    )
    base.update(
        {
            "format": "netconsole-mesh-database-reference-audit-v4-1",
            "execution_mode": execution_mode,
            "authorization": authorization,
            "target_results": target_results,
            "candidates": candidates,
            "handle_groups": list(group_results.values()),
            "handle_audit": {
                "status": "HANDLE_OCCUPIED"
                if HANDLE_OCCUPIED in handle_statuses
                else HANDLE_PROBE_FAILED
                if HANDLE_PROBE_FAILED in handle_statuses
                else HANDLE_UNCONFIRMED
                if HANDLE_UNCONFIRMED in handle_statuses
                else HANDLE_FREE_CONFIRMED
                if handle_statuses
                else HANDLE_PROBE_FAILED,
                "groups": list(group_results.values()),
            },
            "backup_manifest": backup_result,
            "isolation_manifest": isolation_result,
            "test_workflow_status": workflow_status,
            "status": {
                "handle_detection": handle_detection,
                "windows_runtime_verification": windows_runtime,
                "maintenance_authorized": "YES" if authorized else "NO",
                "activity_verification": "PASS"
                if windows_runtime == "PASS"
                else "FAIL"
                if windows_runtime == "FAIL"
                else "PARTIAL",
                "reference_check": base["status"].get("reference_check", "PARTIAL"),
                "backup_workflow": workflow_status,
                "isolation_workflow": workflow_status,
                "rollback_workflow": workflow_status,
                "production_backup": production_backup,
                "production_isolation": production_isolation,
                "data_safety": "PASS" if overall != "FAIL" else "FAIL",
                "databases_removed": 0,
                "orphan_candidates": len(candidates),
                "databases_isolated": int(isolation_result.get("isolated_count") or 0),
                "logical_isolation_bytes": int(isolation_result.get("logical_isolation_bytes") or 0),
                "actual_released_bytes": 0,
                "raw_logs_modified": 0,
                "formal_databases_modified": 0,
                "overall_status": overall,
            },
        }
    )
    if manifest_error:
        base["scope_error"] = manifest_error
        base["status"]["overall_status"] = "BLOCKED"
    return base


def render_v41_final_report(audit: dict[str, Any]) -> str:
    status = audit["status"]
    lines = [
        "# MESH_DATABASE_V4_1_FINAL_REPORT",
        "",
        f"生成时间：`{audit['generated_at']}`",
        f"HANDLE_DETECTION={status['handle_detection']}",
        f"WINDOWS_RUNTIME_VERIFICATION={status['windows_runtime_verification']}",
        f"MAINTENANCE_AUTHORIZED={status['maintenance_authorized']}",
        f"ACTIVITY_VERIFICATION={status['activity_verification']}",
        f"REFERENCE_CHECK={status['reference_check']}",
        f"BACKUP_WORKFLOW={status['backup_workflow']}",
        f"ISOLATION_WORKFLOW={status['isolation_workflow']}",
        f"ROLLBACK_WORKFLOW={status['rollback_workflow']}",
        f"PRODUCTION_BACKUP={status['production_backup']}",
        f"PRODUCTION_ISOLATION={status['production_isolation']}",
        f"DATA_SAFETY={status['data_safety']}",
        f"DATABASES_REMOVED={status['databases_removed']}",
        f"OVERALL_STATUS={status['overall_status']}",
        "",
        "## 维护授权与运行状态",
        "",
        f"- Execution mode：`{audit.get('execution_mode')}`；授权文件：`{audit.get('authorization', {}).get('status')}`。",
        f"- Backend/Worker：`{json.dumps(audit.get('runtime_evidence', {}).get('backend_worker') or [], ensure_ascii=False)}`",
        f"- Electron：`{json.dumps(audit.get('runtime_evidence', {}).get('electron') or [], ensure_ascii=False)}`",
        f"- Python/MESH：`{json.dumps(audit.get('runtime_evidence', {}).get('python_mesh') or [], ensure_ascii=False)}`",
        "- 未终止进程、未关闭外部句柄、未删除 WAL/SHM、未 checkpoint、未 VACUUM。",
        "",
        "## Windows 文件句柄检测",
        "",
        "- 采用 Windows Restart Manager 资源登记 + `CreateFileW(GENERIC_READ, share=0)` 短时访问冲突探针；完成后立即 CloseHandle。",
        "- Restart Manager 空结果不单独作为无句柄证明；只有与短时共享冲突探针共同通过时才给出 `HANDLE_FREE_CONFIRMED`。",
        f"- 文件组总状态：`{audit.get('handle_audit', {}).get('status')}`；目标组数量：{len(audit.get('handle_groups') or [])}。",
        "- handle.exe 为可选辅助工具，本轮未自动安装或执行第三方工具；权限不足、未知句柄来源和 API 失败均保持保护。",
        "",
        "## 7 个 rebuild 最新结论",
        "",
        "| rebuild | formal DB | 句柄组 | 活动 | 引用 | 正式库 | 判定 | 阻断 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in audit.get("target_results") or []:
        record = item.get("record") or {}
        review = item.get("rebuild_review") or {}
        refs = f"source={record.get('source_reference_count', 0)}, session={record.get('session_reference_count', 0)}, task={record.get('active_task_reference_count', 0)}/{record.get('historical_task_reference_count', 0)}/{record.get('unknown_task_reference_count', 0)}, recovery={record.get('recovery_reference_count', 0)}"
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    Path(str(item.get("path") or "")).name,
                    item.get("formal_database_path"),
                    item.get("handle_group_status"),
                    item.get("activity_state"),
                    refs,
                    f"{review.get('formal_database_quick_check', '')}/{review.get('formal_database_integrity_check', '')}",
                    "ORPHAN_CANDIDATE" if item.get("orphan_candidate") else "PROTECTED",
                    ", ".join(item.get("blockers") or []),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 备份、隔离、回滚与数据影响",
            "",
            f"- 候选：{status['orphan_candidates']}；备份成功：{audit.get('backup_manifest', {}).get('backup_success_count', 0)}；隔离成功：{status['databases_isolated']}。",
            f"- 逻辑隔离大小：{status['logical_isolation_bytes']} bytes；实际释放磁盘空间：{status['actual_released_bytes']} bytes。",
            f"- 原始日志修改：{status['raw_logs_modified']}；正式数据库修改：{status['formal_databases_modified']}；永久删除：{status['databases_removed']}。",
            "- 隔离包含主库/WAL/SHM 文件组的逐文件映射；任何组内变化、目标冲突或失败都会进入 ROLLBACK_REQUIRED 并停止后续危险操作。",
            "",
            "## 测试证据与剩余阻断",
            "",
            f"- 测试工作流状态：`{audit.get('test_workflow_status')}`；验证摘要：{audit.get('validation', {}).get('test_result', '未提供')}。",
            "- 真实生产备份/隔离：没有授权时保持 NOT_EXECUTED；不能用 TEST 根通过替代生产授权。",
            "- V3 的 5 个未解释 SHM 变化和 1 个 DEV_REAL ACTIVITY_UNKNOWN 继续保护。",
            f"- Git：branch=`{audit.get('git', {}).get('branch', '未提供')}`；HEAD=`{audit.get('git', {}).get('head', '未提供')}`；status=`{audit.get('git', {}).get('status', '未提供')}`。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_v41_handle_report(audit: dict[str, Any]) -> str:
    lines = [
        "# MESH_WINDOWS_HANDLE_AUDIT",
        "",
        f"HANDLE_DETECTION={audit['status']['handle_detection']}",
        f"WINDOWS_RUNTIME_VERIFICATION={audit['status']['windows_runtime_verification']}",
        f"整体句柄状态：`{audit.get('handle_audit', {}).get('status')}`",
        "",
        "## 探测实现",
        "",
        "- Windows Restart Manager：RmStartSession / RmRegisterResources / RmGetList / RmEndSession。",
        "- Windows 共享冲突：CreateFileW 只读、share=0，成功后立即 CloseHandle。",
        "- 探测对象：每个 rebuild 主库、WAL、SHM 及对应正式数据库文件组。",
        "- 不执行终止进程、关闭外部句柄、checkpoint、VACUUM、Journal Mode 修改或第三方工具安装。",
        "",
        "## 文件组结果",
        "",
        "| rebuild | formal | overall | 文件探针 | Restart Manager 进程 |",
        "|---|---|---|---|---|",
    ]
    for group in audit.get("handle_groups") or []:
        statuses = ", ".join(f"{Path(item['path']).name}={item['status']}" for item in group.get("files") or [])
        processes = group.get("restart_manager", {}).get("processes") or []
        lines.append(
            "| "
            + " | ".join(
                _md_escape(value)
                for value in (
                    Path(group["rebuild_path"]).name,
                    Path(group["formal_database_path"]).name,
                    group.get("status"),
                    statuses,
                    json.dumps(processes, ensure_ascii=False),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 覆盖范围与盲区",
            "",
            "- Restart Manager 只报告能够注册/识别的资源占用者，不等价于系统级句柄枚举。",
            "- share=0 访问冲突可识别常见不兼容共享模式，但不能证明所有允许共享读取的句柄都不存在。",
            "- 权限不足、路径失效、网络路径、符号链接和未知内核/服务句柄均失败关闭；不得因检测失败放行隔离。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_v41_reports(audit: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "MESH_DATABASE_V4_1_FINAL_REPORT.md").write_text(
        render_v41_final_report(audit), encoding="utf-8"
    )
    (output_dir / "MESH_WINDOWS_HANDLE_AUDIT.md").write_text(
        render_v41_handle_report(audit), encoding="utf-8"
    )
    readiness = {
        "format": "netconsole-mesh-maintenance-readiness-v4-1",
        "generated_at": audit["generated_at"],
        "execution_mode": audit.get("execution_mode"),
        "authorization": audit.get("authorization"),
        "status": audit.get("status"),
        "target_count": len(audit.get("target_results") or []),
        "handle_groups": audit.get("handle_groups"),
        "backup_manifest_path": str(output_dir / "MESH_DATABASE_V4_1_BACKUP_MANIFEST.json"),
        "isolation_manifest_path": str(output_dir / "MESH_DATABASE_V4_1_ISOLATION_MANIFEST.json"),
        "validation": audit.get("validation"),
    }
    _write_v41_json(output_dir / "MESH_MAINTENANCE_READINESS.json", readiness)
    backup_report = {
        "format": "netconsole-mesh-backup-isolation-test-report-v4-1",
        "generated_at": audit["generated_at"],
        "workflow_status": audit.get("test_workflow_status"),
        "production_backup": audit["status"].get("production_backup"),
        "production_isolation": audit["status"].get("production_isolation"),
        "backup_manifest": audit.get("backup_manifest"),
        "validation": audit.get("validation"),
        "test_scope": "仅允许隔离 TEST 数据根；不得把 TEST 通过升级为生产授权。",
    }
    (output_dir / "MESH_BACKUP_ISOLATION_TEST_REPORT.md").write_text(
        "# MESH_BACKUP_ISOLATION_TEST_REPORT\n\n"
        + json.dumps(backup_report, ensure_ascii=False, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    rollback_report = {
        "format": "netconsole-mesh-rollback-test-report-v4-1",
        "generated_at": audit["generated_at"],
        "workflow_status": audit.get("test_workflow_status"),
        "rollback_manifest": audit.get("isolation_manifest"),
        "rollback_rule": "原路径出现新文件、目标冲突或哈希变化时报告冲突，不删除文件解决。",
        "validation": audit.get("validation"),
    }
    (output_dir / "MESH_ROLLBACK_TEST_REPORT.md").write_text(
        "# MESH_ROLLBACK_TEST_REPORT\n\n"
        + json.dumps(rollback_report, ensure_ascii=False, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
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
    parser.add_argument("--mode", choices=("audit", "backup", "isolate", "v4", "v4.1"), default="audit")
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
        "--maintenance-authorized",
        action="store_true",
        help="V4 专用：明确提供维护授权证据后才允许进入候选门禁；默认只读阻断",
    )
    parser.add_argument(
        "--execution-mode",
        choices=V41_EXECUTION_MODES,
        default="AUDIT_ONLY",
        help="V4.1 执行模式；AUDIT_ONLY 不写生产，其他模式必须提供实际操作人员授权文件",
    )
    parser.add_argument("--authorization-file", type=Path)
    parser.add_argument("--v4-report-dir", type=Path)
    parser.add_argument("--backup-manifest", type=Path)
    parser.add_argument(
        "--test-workflow-status",
        choices=("PASS", "PARTIAL", "FAIL", "NOT_EXECUTED"),
        default="NOT_EXECUTED",
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
    if args.mode == "v4.1":
        if args.previous_report_dir is None:
            raise SystemExit("v4.1 需要 --previous-report-dir 指向 V3 报告目录")
        if args.v4_report_dir is None:
            raise SystemExit("v4.1 需要 --v4-report-dir 指向 V4 报告目录")
        audit = audit_v41(
            roots,
            previous_report_dir=args.previous_report_dir,
            v4_report_dir=args.v4_report_dir,
            output_dir=args.output_dir,
            execution_mode=args.execution_mode,
            authorization_file=args.authorization_file,
            audit_id=str(args.audit_id),
            backup_manifest=args.backup_manifest,
            test_workflow_status=args.test_workflow_status,
        )
        audit["validation"] = {"test_result": args.validation_summary}
        write_v41_reports(audit, args.output_dir)
        print(
            json.dumps(
                {"summary": audit["status"], "handle_audit": audit["handle_audit"]},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    if args.mode == "v4":
        if args.previous_report_dir is None:
            raise SystemExit("v4 需要 --previous-report-dir 指向 V3 报告目录")
        audit = audit_v4(
            roots,
            previous_report_dir=args.previous_report_dir,
            maintenance_authorized=args.maintenance_authorized,
        )
        audit["validation"] = {"test_result": args.validation_summary}
        write_v4_reports(audit, args.output_dir)
        print(
            json.dumps(
                {"summary": audit["status"], "runtime_evidence": audit["runtime_evidence"]},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
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
