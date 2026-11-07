"""Owned Windows Electron/Backend/fping/UDP stability validation, no real data.

Run a short preflight first; the final uninterrupted 3600-second run starts only
after the integration owner freezes the source tree. All evidence is preserved.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import traceback
import urllib.request

REPO = Path(__file__).resolve().parents[2]
BASE = REPO.parent / "test-data" / "NetConsole"
PREFIX = "/api/rail-transit/ground-unattended"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def storage_bytes(root):
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            # WAL and atomic temp files may disappear between directory/stat.
            continue
    return total


def fixture(root):
    # Import after setting TEST mode. No machine-level data pointer is consulted.
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    from netconsole.core.database import Database
    from netconsole.core.paths import PathResolver
    from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService

    paths = PathResolver(app_root=REPO, data_root=root)
    paths.ensure_site_dirs("demo")
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        group = conn.execute("INSERT INTO device_groups(site_id,name,sort_order,created_at,updated_at) VALUES('demo','车载-MR',1,?,?)", (now, now)).lastrowid
        rows = []
        for index in range(120):
            train = index // 2 + 1
            role = "CT" if index % 2 == 0 else "CW"
            rows.append((f"test-mr-{index + 1:03}", f"列车{train:03}-MR-{role}", f"MR{train:03}{role}", group,
                         f"127.0.0.{index + 1}", f"127.0.0.{121 + index}" if index < 80 else "", now, now))
        conn.executemany("""INSERT INTO devices(device_uuid,name,system_name,group_id,device_vendor,device_type,
            primary_address,backup_address,protocol,port,created_at,updated_at)
            VALUES(?,?,?,?,'H3C','Cloud-AP',?,?,'ssh',22,?,?)""", rows)
        conn.commit()
    paths.app_config_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(paths.app_config_path, {"current_site": "demo"})
    write_json(paths.site_dir("demo") / "site_meta.json", {
        "display_name": "Ground V2 isolated loopback validation", "line_name": "TEST", "system_type": "PIS",
        "network_domain": "default", "created_at": now, "updated_at": now,
    })
    mrs = RailTransitBaseDataQueryService(paths).list_mrs("demo", page_size=200)
    if mrs.total != 120:
        raise RuntimeError(f"Fixture reconciliation expected 120 MRs; got {mrs.total}")
    return paths.site_db_path("demo")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


class MEMORY(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


def process_tree(roots):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    all_rows = {}
    more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
    while more:
        all_rows[entry.th32ProcessID] = {"pid": entry.th32ProcessID, "ppid": entry.th32ParentProcessID,
                                      "name": entry.szExeFile, "threads": entry.cntThreads}
        more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    kernel.CloseHandle(snapshot)
    owned = set(roots) & all_rows.keys()
    while True:
        expanded = owned | {pid for pid, row in all_rows.items() if row["ppid"] in owned}
        if expanded == owned:
            break
        owned = expanded
    result = []
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MEMORY), wintypes.DWORD]
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    for pid in sorted(owned):
        row = all_rows[pid]
        handle = kernel.OpenProcess(0x410, False, pid)
        if handle:
            mem = MEMORY()
            mem.cb = ctypes.sizeof(mem)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb):
                row["rss_bytes"] = mem.WorkingSetSize
            count = wintypes.DWORD()
            if kernel.GetProcessHandleCount(handle, ctypes.byref(count)):
                row["handles"] = count.value
            times = [wintypes.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                row["cpu_seconds"] = sum((item.dwHighDateTime << 32) + item.dwLowDateTime for item in times[2:]) / 10_000_000
            kernel.CloseHandle(handle)
        result.append(row)
    return result


class Harness:
    def __init__(self, args):
        self.args = args
        self.root = BASE / args.run_id
        if self.root.exists():
            raise RuntimeError("A validation run must use a new root")
        self.root.mkdir(parents=True)
        self.backend_port, self.vite_port, self.cdp_port, self.main_port = [free_port() for _ in range(4)]
        self.udp_port = free_port(socket.SOCK_DGRAM)
        self.token = secrets.token_urlsafe(40)
        self.children = []
        self.logs = []
        self.sent = 0
        self.stop_udp = threading.Event()
        self.started = None
        self.summary = {"status": "PREPARING", "requested_seconds": args.seconds, "root": str(self.root),
                        "scope": "actual Electron Renderer/Main + Python Backend + bundled fping + UDP loopback",
                        "ac_ssh": "NOT_EXERCISED; no simulated observation is counted as device validation",
                        "ports": {"backend": self.backend_port, "vite": self.vite_port, "cdp": self.cdp_port, "main": self.main_port, "udp": self.udp_port}}
        write_json(self.root / "owner.json", {"harness_pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(), "fixture_only": True})
        write_json(self.root / "summary.json", self.summary)

    def launch(self, command, name, env=None, cwd=REPO):
        log = (self.root / f"{name}.log").open("w", encoding="utf-8")
        self.logs.append(log)
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        self.children.append(child)
        return child

    def http(self, path):
        request = urllib.request.Request(f"http://127.0.0.1:{self.backend_port}{path}", headers={"X-NetConsole-Session": self.token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def cdp(self, expression, *, main=False):
        self.bridge.stdin.write(json.dumps({"port": self.main_port if main else self.cdp_port, "main": main, "expression": expression}) + "\n")
        self.bridge.stdin.flush()
        line = self.bridge.stdout.readline()
        data = json.loads(line)
        if not data["ok"]:
            raise RuntimeError(data["error"])
        return data["result"].get("result", {}).get("value")

    def api(self, path, method="GET", payload=None):
        # Actual renderer fetch, its desktop cookie, actual loopback Backend.
        expression = f"(async()=>{{const r=await fetch('http://127.0.0.1:{self.backend_port}{PREFIX}{path}',{{method:{json.dumps(method)},credentials:'include',headers:{{'Content-Type':'application/json','X-NetConsole-Session':{json.dumps(self.token)}}},body:{json.dumps(json.dumps(payload)) if payload is not None else 'undefined'}}});return {{status:r.status,data:await r.json()}}}})()"
        value = self.cdp(expression)
        if value["status"] >= 400:
            raise RuntimeError(f"{method} {path}: {value}")
        return value["data"]

    def wait(self, probe, timeout=90):
        limit = time.monotonic() + timeout
        error = None
        while time.monotonic() < limit:
            try:
                value = probe()
                if value:
                    return value
            except Exception as exc:
                error = str(exc)
            time.sleep(0.5)
        raise RuntimeError(f"Readiness timeout: {error}")

    def udp_sender(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            while not self.stop_udp.is_set():
                stamp = datetime.now().strftime("%b %d %H:%M:%S %Y")
                for index in range(20):
                    train, role = index // 2 + 1, "CT" if index % 2 == 0 else "CW"
                    message = f"<189>{stamp} MR{train:03}{role} %%10WMESH/5/MESH_LINKUP: Mesh Link on the interface WLAN-MeshLink841 is up: peer MAC = 0200-0000-0001, peer radio mode = 3, RSSI = 25 validation_seq={self.sent} " + "x" * 600
                    sock.sendto(message.encode(), ("127.0.0.1", self.udp_port))
                    self.sent += 1
                self.stop_udp.wait(0.2)

    def run(self):
        db_path = fixture(self.root)
        self.summary["fixture"] = {"trains": 60, "mrs": 120, "ips": 200, "dual_ip_mrs": 80, "single_ip_mrs": 40}
        env = os.environ.copy()
        env.pop("ELECTRON_RUN_AS_NODE", None)
        env.update({"NETCONSOLE_RUNTIME_MODE": "test", "NETCONSOLE_STORAGE_MODE": "isolated_test", "NETCONSOLE_DEV_TEMP_DATA_ROOT": "1",
                    "NETCONSOLE_DATA_ROOT": str(self.root), "NETCONSOLE_PROJECT_ROOT": str(REPO), "NETCONSOLE_DEV_MODE": "1",
                    "NETCONSOLE_PYTHON": str(REPO / ".venv/Scripts/python.exe"), "NETCONSOLE_DEV_BACKEND_PORT": str(self.backend_port),
                    "NETCONSOLE_DEV_SESSION_TOKEN": self.token, "NETCONSOLE_RENDERER_DEV_URL": f"http://127.0.0.1:{self.vite_port}",
                    "VITE_API_BASE": f"http://127.0.0.1:{self.backend_port}", "VITE_DEV_SESSION_TOKEN": self.token})
        node = shutil.which("node")
        self.launch([node, str(REPO / "apps/desktop_renderer/node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", str(self.vite_port), "--strictPort"], "vite", env, REPO / "apps/desktop_renderer")
        self.wait(lambda: urllib.request.urlopen(f"http://127.0.0.1:{self.vite_port}", timeout=2).status == 200)
        electron = self.launch([str(REPO / "apps/desktop_electron/node_modules/electron/dist/electron.exe"),
                                f"--remote-debugging-port={self.cdp_port}", f"--inspect={self.main_port}", str(REPO / "apps/desktop_electron")], "electron", env)
        self.electron = electron
        self.bridge = subprocess.Popen([node, str(REPO / "scripts/dev/ground_v2_cdp.mjs")], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        self.children.append(self.bridge)
        self.wait(lambda: (item if (item := self.http("/api/health")).get("runtime_services_status") == "ready" else None))
        runtime = self.wait(lambda: self.http("/api/dev/runtime-status"))
        if runtime.get("storage_mode") != "isolated_test" or runtime.get("persistent") is not False:
            raise RuntimeError(f"Isolation assertion failed: {runtime}")
        self.summary["runtime"] = runtime
        self.wait(lambda: self.cdp("document.readyState==='complete' && !!document.querySelector('#app')"))
        self.summary["renderer"] = self.cdp("({url:location.href,title:document.title,ready:document.readyState})")
        # An isolated runtime creates/selects the synthetic demo site from config.
        profile = self.api("/profile")
        local_ips = [row[4][0] for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                     if not ipaddress.ip_address(row[4][0]).is_loopback]
        if not local_ips:
            raise RuntimeError("No existing unicast local adapter address for the profile validation")
        profile.update({"enabled": True, "schedule_start_time": "00:00", "schedule_end_time": "23:59", "deep_collection_master_enabled": False,
                        "udp_listen_host": "127.0.0.1", "udp_listen_port": self.udp_port, "syslog_server_ip": local_ips[0],
                        "syslog_server_port": self.udp_port, "syslog_auto_repair_enabled": False, "fleet_ping_interval_ms": 1000,
                        "fleet_ping_timeout_ms": 4000, "fleet_ping_packet_size": 64, "fleet_ping_shard_size": 32})
        self.api("/profile", "PUT", profile)
        self.summary["inventory"] = self.api("/inventory/sync", "POST")
        self.api("/start", "POST")
        health = self.wait(lambda: (item if (item := self.api("/health")).get("ping_target_count") == 200 and item.get("udp_running") else None), 60)
        self.summary["initial_health"] = health
        quick_targets = [{"target_ip": f"127.0.0.{i + 1}", "mr_id": f"test-mr-{i + 1:03}"} for i in range(8)]
        quick = self.api("/quick-ping", "POST", {"targets": quick_targets, "interval_ms": 200, "timeout_ms": 1000, "packet_size": 64, "duration_seconds": None})
        self.summary["quick_ping"] = quick
        # Keep the real Ground route mounted without triggering a document reload.
        self.cdp("history.pushState({},'', '/rail-transit/ground-unattended');dispatchEvent(new PopStateEvent('popstate'));true")
        self.wait(lambda: self.cdp("location.pathname==='/rail-transit/ground-unattended'"))
        self.udp_thread = threading.Thread(target=self.udp_sender, daemon=True)
        self.udp_thread.start()
        self.started = time.monotonic()
        self.summary["status"] = "RUNNING"
        self.summary["continuous_started_at"] = datetime.now(timezone.utc).isoformat()
        write_json(self.root / "summary.json", self.summary)
        print(f"SYSTEM_VALIDATION_RUNNING root={self.root} seconds={self.args.seconds}", flush=True)
        previous = {}
        with (self.root / "metrics.ndjson").open("w", encoding="utf-8") as metrics:
            while time.monotonic() - self.started < self.args.seconds:
                sample_start = time.monotonic()
                rows = process_tree([child.pid for child in self.children])
                for row in rows:
                    old = previous.get(row["pid"])
                    row["cpu_percent_one_core"] = max(0, (row.get("cpu_seconds", 0) - old[1]) / (sample_start - old[0]) * 100) if old else None
                    previous[row["pid"]] = (sample_start, row.get("cpu_seconds", 0))
                health = self.http(PREFIX + "/health")
                heartbeat = self.http(PREFIX + "/heartbeat?page_size=200")
                item = {"utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": sample_start - self.started,
                        "processes": rows, "fping_process_count": sum(row["name"].lower() == "fping.exe" for row in rows),
                        "health": health, "heartbeat_mr_counts": heartbeat.get("mr_counts"), "heartbeat_train_counts": heartbeat.get("train_counts"),
                        "udp_sent": self.sent, "storage_bytes": storage_bytes(self.root)}
                metrics.write(json.dumps(item, ensure_ascii=False) + "\n")
                metrics.flush()
                if electron.poll() is not None or health.get("ping_target_count") != 200:
                    raise RuntimeError("Owned Electron exited or heartbeat lost targets")
                time.sleep(min(10, max(0, self.args.seconds - (time.monotonic() - self.started))))
        self.summary["continuous_elapsed_seconds"] = time.monotonic() - self.started
        self.stop_udp.set()
        self.udp_thread.join(3)
        self.summary["udp_sent"] = self.sent
        self.summary["final_health_before_stop"] = self.api("/health")
        self.summary["final_heartbeat"] = self.api("/heartbeat?page_size=200")
        self.summary["quick_ping_stop"] = self.api(f"/quick-ping/{quick['run_id']}/stop", "POST")
        self.summary["stop"] = self.api("/stop", "POST")
        # FINALIZING is still active: accepting it previously hid blocked
        # writers and allowed shutdown to race the resource drain.
        self.wait(lambda: not self.api("/status").get("active_run_id"), 90)
        self.summary["final_health_after_stop"] = self.api("/health")
        final_health = self.summary["final_health_after_stop"]
        if final_health.get("ping_target_count") or final_health.get("udp_running"):
            raise RuntimeError("Ground stop left Ping or UDP resources active")
        self.summary["status"] = "COMPLETED"
        self.summary["db_path"] = str(db_path)

    def close(self):
        self.stop_udp.set()
        if hasattr(self, "bridge"):
            try:
                self.cdp("setTimeout(()=>process.emit('SIGTERM'),100);true", main=True)
            except Exception as exc:
                self.summary["graceful_quit_error"] = str(exc)
        if hasattr(self, "electron"):
            try:
                self.electron.wait(timeout=30)
                self.summary["electron_graceful_exit_code"] = self.electron.returncode
            except subprocess.TimeoutExpired:
                self.summary["electron_graceful_exit_timeout"] = True
                self.summary["status"] = "FAILED"
        owned = process_tree([child.pid for child in self.children])
        self.summary["owned_before_cleanup"] = owned
        # Each PID is a verified descendant of a process launched by this run.
        for row in reversed(owned):
            if row["pid"] == getattr(getattr(self, "bridge", None), "pid", None):
                continue
            subprocess.run(["taskkill", "/PID", str(row["pid"]), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if hasattr(self, "bridge"):
            self.bridge.terminate()
        for log in self.logs:
            log.close()
        self.summary["owned_after_cleanup"] = process_tree([child.pid for child in self.children])
        checks = {}
        database_paths = {
            path
            for pattern in ("*.sqlite", "*.db")
            for path in self.root.rglob(pattern)
        }
        for path in sorted(database_paths):
            with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
                checks[str(path.relative_to(self.root))] = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        self.summary["sqlite_integrity"] = checks
        gzip_checks = {}
        for path in self.root.rglob("*.gz"):
            try:
                with gzip.open(path, "rb") as stream:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                gzip_checks[str(path.relative_to(self.root))] = {"crc": "PASS", "uncompressed_sha256": digest.hexdigest()}
            except Exception as exc:
                gzip_checks[str(path.relative_to(self.root))] = {"error": str(exc)}
        self.summary["gzip_integrity"] = gzip_checks
        write_json(self.root / "summary.json", self.summary)
        print(f"SYSTEM_VALIDATION_{self.summary['status']} root={self.root}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id or args.seconds < 1:
        parser.error("run-id must be one directory name; seconds must be positive")
    harness = Harness(args)
    try:
        harness.run()
    except BaseException as exc:
        harness.summary.update({"status": "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED", "error": str(exc), "traceback": traceback.format_exc()})
        if harness.started:
            harness.summary["continuous_elapsed_seconds"] = time.monotonic() - harness.started
        raise
    finally:
        harness.close()


if __name__ == "__main__":
    main()
