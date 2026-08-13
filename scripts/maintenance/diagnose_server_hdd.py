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


def _db_report(path: Path) -> dict[str, Any]:
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
            report["history_tables"] = {
                name: int(conn.execute(f"SELECT COUNT(*) FROM \"{name}\"").fetchone()[0])
                for name in history_tables
            }
            if _table_exists(conn, "history_outbox"):
                report["history_pending"] = int(
                    conn.execute("SELECT COUNT(*) FROM history_outbox WHERE drained_at IS NULL").fetchone()[0]
                )
                oldest = conn.execute(
                    "SELECT MIN(collected_at) FROM history_outbox WHERE drained_at IS NULL"
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


def _startup_events(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"source": str(path) if path else None, "events": [], "status": "not_provided"}
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and ("startup_stage" in item or item.get("event") == "netconsole.electron_backend.startup_stage"):
                events.append(item)
    except OSError:
        return {"source": str(path), "events": [], "status": "unreadable"}
    return {"source": str(path), "events": events, "status": "ready"}


def collect_report(*, database: Path, disk_path: Path, startup_log: Path | None = None) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "diagnose_server_hdd",
        "readonly": True,
        "host": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "disk": _disk_report(disk_path),
        "processes": _processes(),
        "database": _db_report(database),
        "startup": _startup_events(startup_log),
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
    parser.add_argument("--startup-log", type=Path, default=None, help="可选的 JSONL 启动日志")
    parser.add_argument("--output", type=Path, default=None, help="输出 JSON；不指定时打印到 stdout")
    args = parser.parse_args(argv)
    report = collect_report(
        database=args.database,
        disk_path=args.disk_path or args.database,
        startup_log=args.startup_log,
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
