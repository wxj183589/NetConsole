from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.services.network_tools.iperf_parser import parse_iperf_line


@dataclass(frozen=True)
class IperfClientConfig:
    server_ip: str
    port: int = 5201
    protocol: str = "TCP"
    duration_seconds: int = 10
    interval_seconds: int = 1
    parallel: int = 1
    direction: str = "upload"
    target_bandwidth: str | None = None
    follow_collection: bool = False

    def normalized(self) -> "IperfClientConfig":
        protocol = str(self.protocol or "TCP").upper()
        bandwidth = normalize_bandwidth_text(self.target_bandwidth)
        if protocol == "UDP" and not bandwidth:
            bandwidth = "10M"
        return IperfClientConfig(
            server_ip=str(self.server_ip or "").strip(),
            port=max(1, min(65535, int(self.port or 5201))),
            protocol=protocol if protocol in {"TCP", "UDP"} else "TCP",
            duration_seconds=max(1, int(self.duration_seconds or 10)),
            interval_seconds=max(1, int(self.interval_seconds or 1)),
            parallel=max(1, int(self.parallel or 1)),
            direction=str(self.direction or "upload").lower(),
            target_bandwidth=bandwidth,
            follow_collection=bool(self.follow_collection),
        )

    def as_dict(self) -> dict[str, object]:
        config = self.normalized()
        return dict(config.__dict__)


@dataclass(frozen=True)
class IperfServerConfig:
    bind_ip: str = ""
    port: int = 5201
    interval_seconds: int = 1
    one_off: bool = False


def normalize_bandwidth_text(value: object, unit: str = "M") -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    unit = str(unit or "M").strip().upper()
    if unit not in {"K", "M", "G"}:
        raise ValueError("invalid bandwidth unit")
    if text[-1:].upper() in {"K", "M", "G"}:
        unit = text[-1:].upper()
        text = text[:-1].strip()
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", text):
        raise ValueError("invalid bandwidth value")
    numeric = float(text)
    if numeric < 0:
        raise ValueError("invalid bandwidth value")
    return f"{numeric:g}{unit}"


def build_iperf_server_args(iperf_path: Path, config: IperfServerConfig) -> list[str]:
    args = [str(iperf_path), "-s", "-p", str(int(config.port)), "-i", str(max(1, int(config.interval_seconds))), "--forceflush"]
    if config.bind_ip.strip():
        args[2:2] = ["-B", config.bind_ip.strip()]
    if config.one_off:
        args.append("-1")
    return args


def build_iperf_client_args(iperf_path: Path, config: IperfClientConfig) -> list[str]:
    cfg = config.normalized()
    args = [
        str(iperf_path),
        "-c",
        cfg.server_ip,
        "-p",
        str(cfg.port),
        "-i",
        str(cfg.interval_seconds),
        "-t",
        str(cfg.duration_seconds),
        "--forceflush",
    ]
    if cfg.protocol == "UDP":
        args.append("-u")
    if cfg.parallel > 1:
        args.extend(["-P", str(cfg.parallel)])
    if cfg.direction == "download":
        args.append("-R")
    elif cfg.direction == "bidirectional":
        args.append("--bidir")
    if cfg.target_bandwidth:
        args.extend(["-b", cfg.target_bandwidth])
    return args


class IperfResultStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS iperf_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    device_id INTEGER,
                    mode TEXT NOT NULL,
                    protocol TEXT,
                    server_ip TEXT,
                    port INTEGER,
                    direction TEXT,
                    parallel INTEGER,
                    target_bandwidth TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    status TEXT,
                    command_json TEXT,
                    log_file TEXT,
                    raw_file TEXT
                );
                CREATE TABLE IF NOT EXISTS iperf_intervals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    session_id TEXT,
                    collector_time TEXT,
                    interval_start_sec REAL,
                    interval_end_sec REAL,
                    interval_center_time TEXT,
                    transfer_bytes REAL,
                    bitrate_mbps REAL,
                    retransmits INTEGER,
                    cwnd TEXT,
                    role TEXT,
                    jitter_ms REAL,
                    lost_packets INTEGER,
                    total_packets INTEGER,
                    loss_percent REAL,
                    raw_line TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_iperf_intervals_time ON iperf_intervals(interval_center_time);
                CREATE INDEX IF NOT EXISTS idx_iperf_intervals_run ON iperf_intervals(run_id);
                """
            )

    def start_run(self, run_id: str, *, mode: str, command: list[str], log_file: Path, started_at: datetime, session_id: str = "", device_id: int | None = None, config: IperfClientConfig | None = None) -> None:
        cfg = config.normalized() if config else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO iperf_runs (
                    run_id, session_id, device_id, mode, protocol, server_ip, port, direction, parallel,
                    target_bandwidth, started_at, status, command_json, log_file, raw_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    device_id,
                    mode,
                    cfg.protocol if cfg else "",
                    cfg.server_ip if cfg else "",
                    cfg.port if cfg else None,
                    cfg.direction if cfg else "",
                    cfg.parallel if cfg else None,
                    cfg.target_bandwidth if cfg else None,
                    started_at.isoformat(sep=" ", timespec="milliseconds"),
                    "RUNNING",
                    json.dumps(command, ensure_ascii=False),
                    str(log_file),
                    str(log_file),
                ),
            )

    def finish_run(self, run_id: str, status: str, ended_at: datetime | None = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE iperf_runs SET status = ?, ended_at = ? WHERE run_id = ?",
                (status, (ended_at or datetime.now()).isoformat(sep=" ", timespec="milliseconds"), run_id),
            )

    def append_interval(self, run_id: str, row: dict[str, object], session_id: str = "") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO iperf_intervals (
                    run_id, session_id, collector_time, interval_start_sec, interval_end_sec, interval_center_time,
                    transfer_bytes, bitrate_mbps, retransmits, cwnd, role, jitter_ms, lost_packets,
                    total_packets, loss_percent, raw_line
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    row.get("collector_time"),
                    row.get("interval_start_sec"),
                    row.get("interval_end_sec"),
                    row.get("interval_center_time"),
                    row.get("transfer_bytes"),
                    row.get("bitrate_mbps"),
                    row.get("retransmits"),
                    row.get("cwnd"),
                    row.get("role"),
                    row.get("jitter_ms"),
                    row.get("lost_packets"),
                    row.get("total_packets"),
                    row.get("loss_percent"),
                    row.get("raw_line"),
                ),
            )


class IperfProcessRunner:
    def __init__(
        self,
        iperf_path: Path,
        command: list[str],
        log_file: Path,
        store: IperfResultStore | None = None,
        run_id: str | None = None,
        session_id: str = "",
        device_id: int | None = None,
        started_at: datetime | None = None,
        line_callback: Callable[[str, dict[str, object] | None], None] | None = None,
        config: IperfClientConfig | None = None,
        mode: str = "client",
    ) -> None:
        self.iperf_path = iperf_path
        self.command = command
        self.log_file = log_file
        self.store = store
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.session_id = session_id
        self.device_id = device_id
        self.started_at = started_at or datetime.now()
        self.line_callback = line_callback
        self.config = config
        self.mode = mode
        self.process: subprocess.Popen | None = None
        self.stop_requested = False
        self.last_status = "CREATED"

    def start(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if self.store:
            self.store.start_run(
                self.run_id,
                mode=self.mode,
                command=self.command,
                log_file=self.log_file,
                started_at=self.started_at,
                session_id=self.session_id,
                device_id=self.device_id,
                config=self.config,
            )
        self.last_status = "RUNNING"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            cwd=self.iperf_path.parent,
        )
        status = "DONE"
        try:
            assert self.process.stdout is not None
            with self.log_file.open("a", encoding="utf-8") as file:
                for line in self.process.stdout:
                    file.write(line)
                    file.flush()
                    row = parse_iperf_line(line.rstrip(), self.started_at)
                    if row and self.store:
                        self.store.append_interval(self.run_id, row, self.session_id)
                    if self.line_callback:
                        self.line_callback(line.rstrip(), row)
            return_code = self.process.wait()
            if self.stop_requested:
                status = "STOPPED"
            elif return_code != 0:
                status = f"FAILED:{return_code}"
        except Exception:
            status = "FAILED"
            raise
        finally:
            self.last_status = status
            if self.store:
                self.store.finish_run(self.run_id, status)

    def stop(self) -> None:
        self.stop_requested = True
        if self.process is None:
            return
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
