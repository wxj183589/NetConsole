"""只读采集 Windows Server/HDD 现场验收所需的 NetConsole 诊断信息。

该脚本不启动 Backend、不修改 SQLite、不执行 checkpoint/VACUUM/迁移，也不
周期性启动 PowerShell。Windows Server 2012/2012 R2 缺少部分性能计数器时，
相关字段明确返回 ``unknown``。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.runtime_profile import read_host_environment_profile

DEFAULT_STARTUP_LOG = Path(r"D:\NetConsoleData\runtime\logs\electron.log")
STARTUP_EVENTS = {
    "ELECTRON_BACKEND_FIRST_STDOUT",
    "ELECTRON_BACKEND_STARTUP_STAGE",
    "ELECTRON_BACKEND_READY",
}


def _sqlite_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _db_report(path: Path, *, deep: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
        if path.is_file()
        else None,
        "wal_bytes": path.with_name(path.name + "-wal").stat().st_size
        if path.with_name(path.name + "-wal").is_file()
        else 0,
        "shm_bytes": path.with_name(path.name + "-shm").stat().st_size
        if path.with_name(path.name + "-shm").is_file()
        else 0,
    }
    if not path.is_file():
        return report
    try:
        with _sqlite_readonly(path) as conn:
            report["journal_mode"] = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
            report["page_size"] = int(conn.execute("PRAGMA page_size").fetchone()[0])
            report["page_count"] = int(conn.execute("PRAGMA page_count").fetchone()[0])
            report["freelist_count"] = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            report["schema_version"] = (
                conn.execute(
                    "SELECT value FROM schema_metadata WHERE key='schema_version'"
                ).fetchone()[0]
                if _table_exists(conn, "schema_metadata")
                and conn.execute(
                    "SELECT 1 FROM pragma_table_info('schema_metadata') WHERE name='value'"
                ).fetchone()
                else None
            )
            tables = [
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            report["table_count"] = len(tables)
            report["index_count"] = int(
                conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'").fetchone()[0]
            )
            history_tables = [
                name
                for name in tables
                if "history" in name or name in {"history_outbox", "history_state"}
            ]
            report["history_tables"] = history_tables
            if deep:
                report["history_table_counts"] = {
                    name: int(conn.execute(f"SELECT COUNT(*) FROM \"{name}\"").fetchone()[0])
                    for name in history_tables
                }
            if _table_exists(conn, "history_outbox"):
                report["history_pending"] = int(conn.execute("SELECT COUNT(*) FROM history_outbox").fetchone()[0])
                oldest = conn.execute(
                    "SELECT MIN(created_at) FROM history_outbox"
                ).fetchone()[0]
                report["history_oldest_pending"] = oldest
            else:
                report["history_pending"] = 0
                report["history_oldest_pending"] = None
    except (OSError, sqlite3.Error, ValueError) as exc:
        report["read_error"] = type(exc).__name__
    return report


def _processes() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    command = "Get-CimInstance Win32_Process | Where-Object {$_.Name -match 'NetConsole'} | Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        value = json.loads(completed.stdout)
        return value if isinstance(value, list) else [value]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def _disk_report(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path if path.exists() else path.anchor)
        return {"total_bytes": usage.total, "free_bytes": usage.free, "used_bytes": usage.used}
    except OSError:
        return {"total_bytes": None, "free_bytes": None, "used_bytes": None}


def _parse_json_startup_line(line: str) -> dict[str, Any] | None:
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict):
        return None
    event_name = str(item.get("event") or item.get("EVENT") or "")
    if event_name == "netconsole.electron_backend.startup_stage":
        return {
            "format": "python_json",
            "event": "ELECTRON_BACKEND_STARTUP_STAGE",
            "timestamp": item.get("timestamp") or item.get("ts"),
            "level": item.get("level", "INFO"),
            "detail": item.get("stage") or item.get("detail") or "",
            "elapsed_ms": item.get("elapsed_ms"),
        }
    normalized = event_name.upper().replace(".", "_")
    if normalized.endswith(("ELECTRON_BACKEND_READY", "BACKEND_READY")):
        event = "ELECTRON_BACKEND_READY"
    elif normalized.endswith(("ELECTRON_BACKEND_FIRST_STDOUT", "BACKEND_FIRST_STDOUT")):
        event = "ELECTRON_BACKEND_FIRST_STDOUT"
    elif "STARTUP" in normalized or "READY" in normalized:
        event = normalized
    else:
        return None
    return {
        "format": "python_json",
        "event": event,
        "timestamp": item.get("timestamp") or item.get("ts"),
        "level": item.get("level", "INFO"),
        "detail": item.get("detail") or item.get("message") or item.get("stage") or "",
        "elapsed_ms": item.get("elapsed_ms"),
    }


def _parse_pipe_startup_line(line: str) -> dict[str, Any] | None:
    parts = [part.strip() for part in line.split("|", 3)]
    if len(parts) != 4:
        return None
    timestamp, level, event, detail = parts
    event = event.upper()
    if event not in STARTUP_EVENTS and not ("STARTUP" in event or "READY" in event):
        return None
    return {
        "format": "electron_pipe",
        "event": event,
        "timestamp": timestamp,
        "level": level,
        "detail": detail,
    }


def _startup_events(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"source": str(path) if path else None, "events": [], "status": "not_provided"}
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            item = _parse_json_startup_line(line) or _parse_pipe_startup_line(line)
            if item is not None:
                events.append(item)
    except OSError:
        return {"source": str(path), "events": [], "status": "unreadable"}
    return {"source": str(path), "events": events, "timeline": events, "status": "ready"}


def _default_host_profile(database: Path) -> Path:
    parts = database.resolve().parts
    if len(parts) >= 5 and parts[-4].casefold() == "sites":
        return Path(*parts[:-4]) / "runtime" / "environment" / "host-profile.json"
    return Path(r"D:\NetConsoleData\runtime\environment\host-profile.json")


def _host_report(database: Path, profile_path: Path | None) -> dict[str, Any]:
    target = profile_path or _default_host_profile(database)
    profile = read_host_environment_profile(target)
    if profile is None:
        return {"profile_path": str(target), "profile_status": "not_available", "memory": {"bytes": "unknown"}}
    memory = profile.memory.get("bytes")
    return {
        "profile_path": str(target),
        "profile_status": "ready",
        "profile_collected_at": profile.collected_at,
        "memory": {
            "bytes": getattr(memory, "value", "unknown"),
            "source": getattr(memory, "source", "unavailable"),
            "confidence": getattr(memory, "confidence", "unknown"),
        },
    }


def collect_report(
    *,
    database: Path,
    disk_path: Path,
    startup_log: Path | None = None,
    host_profile: Path | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "diagnose_server_hdd",
        "readonly": True,
        "host": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            **_host_report(database, host_profile),
        },
        "disk": _disk_report(disk_path),
        "processes": _processes(),
        "database": {**_db_report(database, deep=deep), "deep": deep},
        "startup": _startup_events(startup_log or DEFAULT_STARTUP_LOG),
        "disk_counters": {
            "active_time_percent": "unknown",
            "queue_length": "unknown",
            "latency_ms": "unknown",
            "reason": "best_effort_only; use Resource Monitor/PerfMon for现场 A/B",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读采集 NetConsole Windows Server/HDD 诊断信息")
    parser.add_argument("--database", type=Path, required=True, help="devices.db 路径；只读打开")
    parser.add_argument("--disk-path", type=Path, default=None, help="用于统计容量的卷或目录")
    parser.add_argument("--startup-log", type=Path, default=None, help="可选的 electron.log；默认 D:\\NetConsoleData\\runtime\\logs\\electron.log")
    parser.add_argument("--host-profile", type=Path, default=None, help="可选安装期 host-profile.json")
    parser.add_argument("--deep", action="store_true", help="显式精确统计全部 legacy history 表；默认不扫描")
    parser.add_argument("--output", type=Path, default=None, help="输出 JSON；不指定时打印到 stdout")
    args = parser.parse_args(argv)
    report = collect_report(
        database=args.database,
        disk_path=args.disk_path or args.database,
        startup_log=args.startup_log,
        host_profile=args.host_profile,
        deep=args.deep,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
