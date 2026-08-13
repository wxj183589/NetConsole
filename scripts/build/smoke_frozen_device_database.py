from __future__ import annotations

import argparse
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen


SITE_NAME = "legacy-device-site"
TOKEN = "netconsole-device-database-smoke-session-token"
OLD_SCHEMA_VERSION = "2026.07.29.device_primary_address_identity"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    database_path = _create_legacy_database(data_root)
    first = _run_backend(args.backend.resolve(), data_root, database_path)
    if first["status_code"] != 200:
        raise RuntimeError(f"首次冻结 Backend 设备列表失败: {first}")
    if first["total"] != 1 or first["project_phase"] != "unspecified":
        raise RuntimeError(f"旧设备迁移后的列表契约不正确: {first}")

    backup_dir = database_path.parent.parent / "files" / "backups" / "database-migrations"
    backups_after_first = sorted(backup_dir.glob("devices-site-*-before-*.sqlite"))
    if len(backups_after_first) != 1:
        raise RuntimeError(f"旧库迁移备份数量不正确: {backups_after_first}")

    second = _run_backend(args.backend.resolve(), data_root, database_path)
    if second["status_code"] != 200 or second["total"] != 1:
        raise RuntimeError(f"重启后冻结 Backend 设备列表失败: {second}")
    backups_after_second = sorted(backup_dir.glob("devices-site-*-before-*.sqlite"))
    if backups_after_second != backups_after_first:
        raise RuntimeError(
            "重启后产生了重复迁移备份: "
            f"before={backups_after_first}, after={backups_after_second}"
        )

    print(
        json.dumps(
            {
                "database_path": str(database_path),
                "status_code": second["status_code"],
                "total": second["total"],
                "project_phase": second["project_phase"],
                "work_scope_status": second["work_scope_status"],
                "backup_count": len(backups_after_second),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _create_legacy_database(data_root: Path) -> Path:
    database_path = data_root / "sites" / SITE_NAME / "db" / "devices.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                system_name TEXT,
                mac_address TEXT,
                station TEXT,
                location TEXT,
                group_id INTEGER,
                device_vendor TEXT NOT NULL DEFAULT 'H3C',
                device_type TEXT,
                primary_address TEXT NOT NULL,
                normalized_primary_address TEXT,
                backup_address TEXT,
                protocol TEXT DEFAULT 'SSH',
                port INTEGER DEFAULT 22,
                username TEXT,
                password TEXT,
                ssh_enabled INTEGER DEFAULT 1,
                ssh_port INTEGER DEFAULT 22,
                telnet_enabled INTEGER DEFAULT 0,
                telnet_port INTEGER DEFAULT 23,
                ssh_username TEXT,
                ssh_password TEXT,
                telnet_username TEXT,
                telnet_password TEXT,
                snmp_enabled INTEGER DEFAULT 1,
                snmp_v1_enabled INTEGER DEFAULT 0,
                snmp_v2c_enabled INTEGER DEFAULT 1,
                snmp_port INTEGER DEFAULT 161,
                snmp_ro_community TEXT,
                snmp_timeout_ms INTEGER DEFAULT 2000,
                snmp_retries INTEGER DEFAULT 1,
                https_port INTEGER,
                tunnel_enabled INTEGER DEFAULT 0,
                tunnel1_enabled INTEGER DEFAULT 0,
                tunnel1_host TEXT,
                tunnel1_port INTEGER DEFAULT 22,
                tunnel1_username TEXT,
                tunnel1_password TEXT,
                tunnel1_local_port_mode TEXT DEFAULT 'auto',
                tunnel1_local_port INTEGER,
                tunnel2_enabled INTEGER DEFAULT 0,
                tunnel2_host TEXT,
                tunnel2_port INTEGER DEFAULT 22,
                tunnel2_username TEXT,
                tunnel2_password TEXT,
                tunnel2_local_port_mode TEXT DEFAULT 'auto',
                tunnel2_local_port INTEGER,
                remark TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE device_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(site_id, name)
            );
            CREATE TABLE ac_fit_ap_resources (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE ap_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT,
                ac_device_uuid TEXT,
                ap_id TEXT,
                ap_name TEXT,
                ap_mac TEXT,
                serial_number TEXT
            );
            CREATE UNIQUE INDEX uq_devices_normalized_primary_address
                ON devices(normalized_primary_address)
                WHERE normalized_primary_address IS NOT NULL
                  AND normalized_primary_address <> '';
            INSERT INTO schema_metadata (key, value, created_at, updated_at)
            VALUES (
                'schema_version',
                '2026.07.29.device_primary_address_identity',
                '2026-07-29T00:00:00',
                '2026-07-29T00:00:00'
            );
            INSERT INTO device_groups (
                site_id, name, sort_order, created_at, updated_at
            ) VALUES (
                'legacy-device-site', '交换机', 0,
                '2026-07-29T00:00:00', '2026-07-29T00:00:00'
            );
            INSERT INTO devices (
                device_uuid, name, group_id, device_vendor, device_type,
                primary_address, normalized_primary_address, username,
                password, ssh_username, ssh_password, created_at, updated_at
            ) VALUES (
                'frozen-device-uuid', '冻结旧设备', 1, 'H3C', 'SW',
                '198.51.100.101', '198.51.100.101', 'admin',
                'frozen-secret', 'admin', 'frozen-secret',
                '2026-07-29T00:00:00', '2026-07-29T00:00:00'
            );
            """
        )
        connection.commit()
    return database_path


def _run_backend(
    executable: Path, data_root: Path, database_path: Path
) -> dict[str, object]:
    environment = {
        **os.environ,
        "NETCONSOLE_DATA_ROOT": str(data_root),
        "NETCONSOLE_RUNTIME_MODE": "test",
        "NETCONSOLE_STORAGE_MODE": "isolated_test",
    }
    process = subprocess.Popen(
        [str(executable), "--electron-backend", "--port", "0"],
        cwd=executable.parent,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        output: queue.Queue[str] = queue.Queue()
        stderr: list[str] = []
        assert process.stdout is not None
        assert process.stderr is not None
        threading.Thread(
            target=_read_lines,
            args=(process.stdout, output),
            daemon=True,
        ).start()
        threading.Thread(
            target=_read_lines,
            args=(process.stderr, stderr),
            daemon=True,
        ).start()
        assert process.stdin is not None
        process.stdin.write(json.dumps({"session_token": TOKEN}) + "\n")
        process.stdin.flush()
        port = _wait_for_port(output, process, stderr)
        response = _device_list(port)
        process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
        process.stdin.flush()
        _wait_for_shutdown_complete(output, process)
        process.stdin.write(json.dumps({"command": "exit"}) + "\n")
        process.stdin.flush()
        process.wait(timeout=15)
        if process.returncode != 0:
            raise RuntimeError(
                f"冻结 Backend 退出异常: code={process.returncode}, "
                f"stderr={''.join(stderr)}"
            )
        with sqlite3.connect(database_path) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"迁移后数据库完整性异常: {integrity}")
        return response
    finally:
        _reap_backend(process)


def _reap_backend(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if process.stdin is not None:
        try:
            process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
            process.stdin.write(json.dumps({"command": "exit"}) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _read_lines(stream, target) -> None:
    for line in stream:
        if isinstance(target, queue.Queue):
            target.put(line)
        else:
            target.append(line)


def _wait_for_port(
    output: queue.Queue[str],
    process: subprocess.Popen[str],
    stderr: list[str],
) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"冻结 Backend 未监听: code={process.returncode}, "
                f"stderr={''.join(stderr)}"
            )
        try:
            line = output.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            payload.get("event") == "netconsole.electron_backend.listening"
            and int(payload.get("port") or 0) > 0
        ):
            return int(payload["port"])
    raise TimeoutError("冻结 Backend 监听超时")


def _wait_for_event(
    output: queue.Queue[str], event: str, process: subprocess.Popen[str]
) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"冻结 Backend 提前退出: code={process.returncode}")
        try:
            line = output.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == event:
            return
    raise TimeoutError(f"等待冻结 Backend 事件超时: {event}")


def _wait_for_shutdown_complete(
    output: queue.Queue[str], process: subprocess.Popen[str]
) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"冻结 Backend 提前退出: code={process.returncode}")
        try:
            line = output.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") in {
            "netconsole.electron_backend.shutdown_complete",
            "netconsole.electron_backend.shutdown_ack",
        }:
            return
    raise TimeoutError("等待冻结 Backend shutdown_complete 事件超时")


def _device_list(port: int) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}/api/device-management/devices",
        headers={"X-NetConsole-Session": TOKEN},
    )
    with urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(
                f"设备列表接口状态错误: HTTP {response.status}"
            )
        payload = json.loads(response.read().decode("utf-8"))
    item = (payload.get("items") or [{}])[0]
    return {
        "status_code": response.status,
        "total": payload.get("total"),
        "project_phase": item.get("project_phase"),
        "work_scope_status": item.get("work_scope_status"),
    }


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"冻结 Backend 设备数据库 smoke 失败: {exc}", file=sys.stderr)
        raise
