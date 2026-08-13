"""在隔离数据根验证 Phase 2.1 旧库兼容性；不触碰现场数据。"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.runtime_environment import WINDOWS_TEST_DATA_ROOT
from netconsole.services.history_store import HistoryStore

LEGACY_HISTORY_TABLES = (
    "device_facts_history",
    "device_interfaces_history",
    "device_optical_modules_history",
    "device_lldp_neighbors_history",
    "ac_fit_ap_resource_history",
    "ac_fit_ap_radio_history",
    "ac_fit_ap_optical_history",
    "ac_fit_ap_lldp_history",
    "ap_resource_snapshots",
    "ap_lldp_history",
    "ap_optical_history",
)


def _backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)


def _run_isolated_backend(root: Path) -> dict[str, object]:
    """Run the real Electron backend runtime against only the isolated root."""
    resolved_root = root.resolve()
    if resolved_root.is_relative_to(Path(r"D:\NetConsoleData").resolve()):
        return {"status": "NOT_EXECUTED", "reason": "REAL_DATA_ROOT_REJECTED"}
    if sys.platform == "win32":
        test_root = WINDOWS_TEST_DATA_ROOT.resolve()
        if resolved_root == test_root or not resolved_root.is_relative_to(test_root):
            return {"status": "NOT_EXECUTED", "reason": "TEST_DATA_ROOT_REQUIRED"}
    token = "validation-token-abcdefghijklmnopqrstuvwxyz-0123456789"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            "NETCONSOLE_DATA_ROOT": str(resolved_root),
            "NETCONSOLE_RUNTIME_MODE": "test",
            "NETCONSOLE_ACTIVE_SITE_ID": "snapshot",
        }
    )
    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-m", "netconsole.backend.electron_runtime", "--port", "0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({"session_token": token}) + "\n")
    process.stdin.flush()
    port = None
    lines: list[str] = []
    deadline = time.perf_counter() + 30
    while time.perf_counter() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        lines.append(line.rstrip())
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("event") == "netconsole.electron_backend.listening":
            port = int(item["port"])
            break
    if port is None:
        process.kill()
        _stdout, stderr = process.communicate(timeout=5)
        return {
            "status": "FAIL",
            "reason": "BACKEND_LISTENER_NOT_READY",
            "exit_code": process.returncode,
            "output": lines,
            "stderr_tail": stderr[-2000:],
        }
    health = None
    while time.perf_counter() < deadline:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/health",
                    headers={"x-netconsole-session": token},
                ),
                timeout=2,
            ) as response:
                health = json.loads(response.read().decode("utf-8"))
            if isinstance(health, dict) and health.get("status"):
                break
        except (OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.1)
    if not isinstance(health, dict):
        process.kill()
        _stdout, stderr = process.communicate(timeout=5)
        return {
            "status": "FAIL",
            "reason": "BACKEND_HEALTH_NOT_READY",
            "exit_code": process.returncode,
            "output": lines,
            "stderr_tail": stderr[-2000:],
        }
    ready_ms = round((time.perf_counter() - started) * 1000, 2)
    process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
    process.stdin.write(json.dumps({"command": "exit"}) + "\n")
    process.stdin.flush()
    process.wait(timeout=30)
    return {"status": "PASS", "backend_ready_ms": ready_ms, "health_status": health.get("status"), "exit_code": process.returncode}


def _default_work_root() -> Path:
    if sys.platform == "win32":
        base = WINDOWS_TEST_DATA_ROOT
        try:
            base.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="phase21-", dir=str(base)))
        except OSError:
            # Offline DB validation remains useful when the prescribed test volume is unavailable;
            # the optional Backend smoke will report that its test-root contract cannot be met.
            pass
    return Path(tempfile.mkdtemp(prefix="netconsole-phase21-"))


def validate_snapshot(source: Path | None, *, work_root: Path | None = None) -> dict[str, object]:
    if source is None or not source.is_file():
        return {"status": "NOT_EXECUTED", "reason": "OFFLINE_SNAPSHOT_NOT_AVAILABLE", "source": str(source) if source else None}
    root = Path(work_root) if work_root else _default_work_root()
    target = root / "sites" / "snapshot" / "db" / "devices.db"
    _backup(source, target)
    before = target.stat().st_size
    started = time.perf_counter()
    database = Database(target)
    database.initialize()
    first_ms = round((time.perf_counter() - started) * 1000, 2)
    first_size = target.stat().st_size
    started = time.perf_counter()
    database.initialize()
    second_ms = round((time.perf_counter() - started) * 1000, 2)
    second_size = target.stat().st_size
    store = HistoryStore(target, site_id="snapshot")
    with database.connect_readonly() as connection:
        legacy_counts = {
            table: int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
            )
            for table in LEGACY_HISTORY_TABLES
        }
        for table, exists in tuple(legacy_counts.items()):
            legacy_counts[table] = (
                int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                if exists
                else 0
            )
    shard_files = sorted(path.name for path in store.history_root.glob("devices-*.db")) if store.history_root.is_dir() else []
    with database.connect() as connection:
        recorded = store.record_event(
            connection,
            kind="device_interface",
            entity_key="validation-device:GE1/0/1",
            payload={
                "device_uuid": "validation-device",
                "interface_name": "GE1/0/1",
                "link_status": "up",
            },
            collected_at="2026-08-01T00:00:00",
            meaningful_fields=("device_uuid", "interface_name", "link_status"),
        )
        connection.commit()
    drained = store.drain(limit=10)
    shard_files = sorted(path.name for path in store.history_root.glob("devices-*.db")) if store.history_root.is_dir() else []
    return {
        "status": "PASS",
        "source": str(source),
        "isolated_copy": str(target),
        "source_bytes": before,
        "database_initialize_first_ms": first_ms,
        "database_initialize_second_ms": second_ms,
        "copy_bytes_after_first": first_size,
        "copy_bytes_after_second": second_size,
        "size_stable_after_fast_path": first_size == second_size,
        "legacy_history_counts": legacy_counts,
        "fake_current_event_recorded": recorded,
        "fake_current_event_drained": drained.written,
        "history_pending_after_drain": drained.pending,
        "history_shard_files": shard_files,
        "migration_invoked": False,
        "destructive_operations": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔离副本 Phase 2.1 fast-path 验证")
    parser.add_argument("--source", type=Path, default=None, help="离线 devices.db 副本；不指定则明确跳过")
    parser.add_argument("--work-root", type=Path, default=None, help="隔离验证根；不得指向现场数据根")
    parser.add_argument("--backend-smoke", action="store_true", help="在隔离副本上启动真实 Backend listener/health 并记录 backend_ready_ms")
    args = parser.parse_args(argv)
    if args.work_root and args.work_root.resolve().is_relative_to(Path(r"D:\NetConsoleData").resolve()):
        raise SystemExit("拒绝使用真实 D:\\NetConsoleData 作为验证根")
    result = validate_snapshot(args.source, work_root=args.work_root)
    if args.backend_smoke and result.get("status") == "PASS":
        result["backend_integration"] = _run_isolated_backend(Path(str(result["isolated_copy"])).parents[3])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
