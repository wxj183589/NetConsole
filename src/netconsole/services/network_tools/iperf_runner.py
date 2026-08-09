from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import subprocess
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.core.shutdown_manager import shutdown_manager
from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal, run_sqlite_with_retry
from netconsole.services.network_tools.iperf_parser import format_iperf_log_footer, format_iperf_log_header, format_iperf_log_line, parse_iperf_error_line, parse_iperf_error_lines, parse_iperf_line


FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS = 86400


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
    tcp_block_size: str | None = None
    packet_length: int | None = None
    tcp_report_threshold_mbps: float | None = None
    tcp_pacing_enabled: bool = False
    tcp_pacing_mbps: float | None = None
    udp_bitrate_mbps: float | None = None
    udp_report_threshold_mbps: float | None = None
    debug_output_enabled: bool = False

    def normalized(self) -> "IperfClientConfig":
        protocol = str(self.protocol or "TCP").upper()
        bandwidth = normalize_bandwidth_text(self.target_bandwidth)
        if protocol == "UDP" and not bandwidth:
            bandwidth = "10M"
        tcp_block_size = normalize_block_size_text(self.tcp_block_size)
        if protocol == "TCP" and not tcp_block_size and _bandwidth_mbps(bandwidth) is not None and _bandwidth_mbps(bandwidth) <= 2:
            tcp_block_size = "16K"
        follow_collection = bool(self.follow_collection)
        duration_seconds = max(1, int(self.duration_seconds or 10))
        if follow_collection:
            duration_seconds = max(duration_seconds, FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS)
        return IperfClientConfig(
            server_ip=str(self.server_ip or "").strip(),
            port=max(1, min(65535, int(self.port or 5201))),
            protocol=protocol if protocol in {"TCP", "UDP"} else "TCP",
            duration_seconds=duration_seconds,
            interval_seconds=max(1, int(self.interval_seconds or 1)),
            parallel=max(1, int(self.parallel or 1)),
            direction=str(self.direction or "upload").lower(),
            target_bandwidth=bandwidth,
            follow_collection=follow_collection,
            tcp_block_size=tcp_block_size,
            packet_length=max(1, int(self.packet_length)) if self.packet_length else None,
            tcp_report_threshold_mbps=_optional_float(self.tcp_report_threshold_mbps),
            tcp_pacing_enabled=bool(self.tcp_pacing_enabled),
            tcp_pacing_mbps=_optional_float(self.tcp_pacing_mbps),
            udp_bitrate_mbps=_optional_float(self.udp_bitrate_mbps),
            udp_report_threshold_mbps=_optional_float(self.udp_report_threshold_mbps),
            debug_output_enabled=bool(self.debug_output_enabled),
        )

    def as_dict(self) -> dict[str, object]:
        config = self.normalized()
        return dict(config.__dict__)


@dataclass(frozen=True)
class IperfPreflightResult:
    ok: bool
    error_code: str = ""
    message: str = ""
    command: list[str] | None = None
    output: str = ""


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


def normalize_block_size_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    suffix = text[-1:].upper()
    if suffix in {"K", "M"}:
        numeric_text = text[:-1].strip()
    else:
        suffix = "K"
        numeric_text = text
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", numeric_text):
        raise ValueError("invalid block size value")
    numeric = float(numeric_text)
    if numeric <= 0:
        raise ValueError("invalid block size value")
    return f"{numeric:g}{suffix}"


def _bandwidth_mbps(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(r"(?P<num>(?:0|[1-9]\d*)(?:\.\d+)?)(?P<unit>[KMG])", str(value).strip(), re.IGNORECASE)
    if not match:
        return None
    numeric = float(match.group("num"))
    unit = match.group("unit").upper()
    if unit == "K":
        return numeric / 1000.0
    if unit == "G":
        return numeric * 1000.0
    return numeric


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    args.extend(["-P", str(cfg.parallel)])
    if cfg.direction == "download":
        args.append("-R")
    elif cfg.direction == "bidirectional":
        args.append("--bidir")
    if cfg.target_bandwidth:
        args.extend(["-b", cfg.target_bandwidth])
    if cfg.debug_output_enabled:
        args.append("-d")
    if cfg.protocol == "TCP" and cfg.tcp_block_size:
        args.extend(["-l", cfg.tcp_block_size])
    if cfg.protocol == "UDP" and cfg.packet_length:
        args.extend(["-l", str(cfg.packet_length)])
    return args


def build_iperf_client_preflight_args(iperf_path: Path, config: IperfClientConfig) -> list[str]:
    cfg = config.normalized()
    preflight = IperfClientConfig(
        server_ip=cfg.server_ip,
        port=cfg.port,
        protocol=cfg.protocol,
        duration_seconds=1,
        interval_seconds=1,
        parallel=cfg.parallel,
        direction=cfg.direction,
        target_bandwidth=cfg.target_bandwidth,
        follow_collection=False,
        tcp_block_size=cfg.tcp_block_size,
        packet_length=cfg.packet_length,
        tcp_report_threshold_mbps=cfg.tcp_report_threshold_mbps,
        tcp_pacing_enabled=cfg.tcp_pacing_enabled,
        tcp_pacing_mbps=cfg.tcp_pacing_mbps,
        udp_bitrate_mbps=cfg.udp_bitrate_mbps,
        udp_report_threshold_mbps=cfg.udp_report_threshold_mbps,
        debug_output_enabled=cfg.debug_output_enabled,
    )
    return build_iperf_client_args(iperf_path, preflight)


def run_iperf_client_preflight(iperf_path: Path, config: IperfClientConfig, timeout_seconds: float = 8.0) -> IperfPreflightResult:
    cfg = config.normalized()
    if not cfg.server_ip:
        return IperfPreflightResult(False, "server_required", "server address is required")
    if not Path(iperf_path).exists():
        return IperfPreflightResult(False, "tool_missing", f"iperf3 not found: {iperf_path}")
    command = build_iperf_client_preflight_args(iperf_path, cfg)
    try:
        completed = subprocess.run(
            command,
            cwd=Path(iperf_path).parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(2.0, float(timeout_seconds)),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = str(exc.output or "")
        return IperfPreflightResult(False, "timed_out", "iperf preflight timed out", command, output)
    except Exception as exc:
        return IperfPreflightResult(False, "runner_exception", str(exc), command, "")
    output = completed.stdout or ""
    if completed.returncode == 0:
        return IperfPreflightResult(True, "", "iperf preflight succeeded", command, output)
    error = _classify_iperf_preflight_error(output)
    return IperfPreflightResult(False, error.get("error_code", "iperf_error"), str(error.get("error_message") or output.strip() or f"iperf exited with code {completed.returncode}"), command, output)


def _classify_iperf_preflight_error(output: str) -> dict[str, object]:
    events = parse_iperf_error_lines(str(output or "").splitlines(), datetime.now())
    if events:
        return events[0]
    text = str(output or "").strip()
    lowered = text.casefold()
    if "no route to host" in lowered:
        return {"error_code": "no_route_to_host", "error_message": text}
    if "network is unreachable" in lowered:
        return {"error_code": "network_unreachable", "error_message": text}
    if "connection refused" in lowered:
        return {"error_code": "connection_refused", "error_message": text}
    if "timed out" in lowered:
        return {"error_code": "timed_out", "error_message": text}
    return {"error_code": "iperf_error", "error_message": text}


class IperfResultStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        def operation() -> None:
            with connect_sqlite(self.db_path) as conn:
                initialize_sqlite_wal(conn)
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
                    device_aligned_time TEXT,
                    device_interval_center_time TEXT,
                    clock_offset_ms REAL,
                    offset_source TEXT,
                    time_source TEXT,
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
                self._ensure_interval_alignment_columns(conn)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(iperf_intervals)").fetchall()}
                if "source_event_key" not in columns:
                    conn.execute("ALTER TABLE iperf_intervals ADD COLUMN source_event_key TEXT NOT NULL DEFAULT ''")
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_iperf_intervals_source_event
                    ON iperf_intervals(run_id, source_event_key)
                    WHERE source_event_key <> ''
                    """
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    @staticmethod
    def _ensure_interval_alignment_columns(conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(iperf_intervals)").fetchall()}
        for column, definition in {
            "device_aligned_time": "TEXT",
            "device_interval_center_time": "TEXT",
            "clock_offset_ms": "REAL",
            "offset_source": "TEXT",
            "time_source": "TEXT",
        }.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE iperf_intervals ADD COLUMN {column} {definition}")

    def start_run(self, run_id: str, *, mode: str, command: list[str], log_file: Path, started_at: datetime, session_id: str = "", device_id: int | None = None, config: IperfClientConfig | None = None) -> None:
        cfg = config.normalized() if config else None
        def operation() -> None:
            with connect_sqlite(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
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
                conn.commit()

        run_sqlite_with_retry(operation)

    def finish_run(self, run_id: str, status: str, ended_at: datetime | None = None) -> None:
        def operation() -> None:
            with connect_sqlite(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE iperf_runs SET status = ?, ended_at = ? WHERE run_id = ?",
                    (status, (ended_at or datetime.now()).isoformat(sep=" ", timespec="milliseconds"), run_id),
                )
                conn.commit()

        run_sqlite_with_retry(operation)

    def append_interval(
        self,
        run_id: str,
        row: dict[str, object],
        session_id: str = "",
        *,
        source_event_key: str = "",
    ) -> bool:
        def operation() -> bool:
            with connect_sqlite(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                """
                INSERT INTO iperf_intervals (
                    run_id, session_id, collector_time, interval_start_sec, interval_end_sec, interval_center_time,
                    device_aligned_time, device_interval_center_time, clock_offset_ms, offset_source, time_source,
                    transfer_bytes, bitrate_mbps, retransmits, cwnd, role, jitter_ms, lost_packets,
                    total_packets, loss_percent, raw_line, source_event_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_event_key) WHERE source_event_key <> '' DO NOTHING
                """,
                    (
                    run_id,
                    session_id,
                    row.get("collector_time"),
                    row.get("interval_start_sec"),
                    row.get("interval_end_sec"),
                    row.get("interval_center_time"),
                    row.get("device_aligned_time"),
                    row.get("device_interval_center_time"),
                    row.get("clock_offset_ms"),
                    row.get("offset_source"),
                    row.get("time_source"),
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
                        str(source_event_key or ""),
                    ),
                )
                conn.commit()
                return cursor.rowcount == 1

        return run_sqlite_with_retry(operation)


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
        line_callback: Callable[..., None] | None = None,
        config: IperfClientConfig | None = None,
        mode: str = "client",
        mirror_log_files: list[Path] | None = None,
        context: dict[str, object] | None = None,
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
        self.mirror_contexts: dict[Path, dict[str, object]] = {}
        self.context: dict[str, object] = {"mode": mode, "run_id": self.run_id}
        if session_id:
            self.context.setdefault("session_id", session_id)
        if device_id is not None:
            self.context.setdefault("device_id", device_id)
        self.context.update(context or {})
        self.context.setdefault("command", " ".join(str(part) for part in self.command))
        if self.config is not None:
            cfg = self.config.normalized()
            self.context.setdefault("server", cfg.server_ip)
            self.context.setdefault("port", cfg.port)
            self.context.setdefault("protocol", cfg.protocol)
            self.context.setdefault("direction", cfg.direction)
            self.context.setdefault("bandwidth", cfg.target_bandwidth or "")
            self.context.setdefault("tcp_block_size", cfg.tcp_block_size or "")
            if cfg.follow_collection:
                self.context.setdefault("duration_mode", "follow_collection")
                self.context.setdefault("protection_duration_seconds", cfg.duration_seconds)
                self.context.setdefault("stop_policy", "stop_with_collection")
            else:
                self.context.setdefault("duration_seconds", cfg.duration_seconds)
        batch_key = self.context.get("batch_key") or self.context.get("batch_id")
        if batch_key and not self.context.get("batch_key_hash"):
            self.context["batch_key_hash"] = hashlib.sha1(str(batch_key).encode("utf-8")).hexdigest()[:8]
        for path in mirror_log_files or []:
            mirror = Path(path)
            if mirror != self.log_file:
                self.mirror_contexts[mirror] = dict(self.context)
        self.process: subprocess.Popen | None = None
        self.stop_requested = False
        self.stop_status = "STOPPED"
        self.last_status = "CREATED"
        self.last_error_code = ""
        self.last_error = ""
        self.stderr_tail = ""
        self.last_exit_at: datetime | None = None
        self.last_data_at: datetime | None = None
        self.heartbeat_at: datetime | None = None
        self.bytes_written = 0
        self.stop_reason = ""
        self.exception_stage = ""
        self.exception_type = ""
        self.exception_message = ""
        self.traceback_tail = ""
        self.degraded = False
        self.degraded_warnings: list[str] = []
        self._log_lock = threading.RLock()

    def diagnostics(self) -> dict[str, object]:
        process = self.process
        exit_code = process.poll() if process is not None else None
        return {
            "pid": process.pid if process is not None else None,
            "parent_pid": os.getpid(),
            "cwd": str(self.iperf_path.parent),
            "command": list(self.command),
            "alive": bool(process is not None and exit_code is None),
            "exit_code": exit_code,
            "last_exit_at": self.last_exit_at.isoformat(sep=" ", timespec="milliseconds") if self.last_exit_at else None,
            "heartbeat": self.heartbeat_at.isoformat(sep=" ", timespec="milliseconds") if self.heartbeat_at else None,
            "last_data_at": self.last_data_at.isoformat(sep=" ", timespec="milliseconds") if self.last_data_at else None,
            "bytes_written": self.bytes_written,
            "last_error": self.last_error or self.last_error_code,
            "stderr_tail": self.stderr_tail,
            "stop_reason": self.stop_reason,
            "exception_stage": self.exception_stage,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "traceback_tail": self.traceback_tail,
            "degraded": self.degraded,
            "degraded_warnings": list(self.degraded_warnings),
        }

    def add_mirror_log_file(self, log_file: Path, context: dict[str, object] | None = None) -> None:
        log_file = Path(log_file)
        if log_file == self.log_file:
            return
        with self._log_lock:
            if log_file in self.mirror_contexts:
                return
            log_file.parent.mkdir(parents=True, exist_ok=True)
            mirror_context = dict(self.context)
            mirror_context.update(context or {})
            batch_key = mirror_context.get("batch_key") or mirror_context.get("batch_id")
            if batch_key and not mirror_context.get("batch_key_hash"):
                mirror_context["batch_key_hash"] = hashlib.sha1(str(batch_key).encode("utf-8")).hexdigest()[:8]
            prior_lines: list[str] = []
            if self.log_file.exists():
                prior_lines = [
                    line
                    for line in self.log_file.read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#")
                ]
            with log_file.open("w", encoding="utf-8") as file:
                for line in self._start_header_lines(self.started_at, mirror_context):
                    file.write(line + "\n")
                for line in prior_lines:
                    file.write(line + "\n")
            self.mirror_contexts[log_file] = mirror_context

    def start(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.last_status = "RUNNING"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return_code: int | None = None
        status = "DONE"
        stage = "startup"
        try:
            stage = "sqlite_start_run"
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
            stage = "header_write"
            self._write_headers()
            if self.stop_requested:
                status = self.stop_status
                return
            stage = "spawn"
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
            shutdown_manager.register_process(self.process, "iperf3", kind="internal_tool", shutdown_policy="terminate")
            assert self.process.stdout is not None
            self.heartbeat_at = datetime.now()
            for line in self.process.stdout:
                raw_line = line.rstrip("\r\n")
                now = datetime.now()
                self.heartbeat_at = now
                self.last_data_at = now
                stamped_line = format_iperf_log_line(now, raw_line, self.context)
                stage = "raw_write"
                self._write_line(stamped_line)
                try:
                    stage = "parse"
                    row = parse_iperf_line(stamped_line, self.started_at, collector_time=now)
                    error = parse_iperf_error_line(stamped_line, self.started_at)
                except Exception as exc:
                    self._record_degraded(stage, exc)
                    row = None
                    error = None
                if error:
                    self.last_error_code = str(error.get("error_code") or "")
                    self.last_error = str(error.get("error_message") or self.last_error_code)
                    self.stderr_tail = "\n".join(
                        (self.stderr_tail + "\n" + raw_line).strip().splitlines()[-20:]
                    )
                if row and self.store:
                    try:
                        stage = "sqlite_append"
                        self.store.append_interval(self.run_id, row, self.session_id)
                    except Exception as exc:
                        self._record_degraded(stage, exc)
                stage = "callback"
                self._emit_line(stamped_line, row, error)
            return_code = self.process.wait()
            if self.stop_requested:
                status = self.stop_status
            elif return_code != 0:
                status = f"FAILED:{return_code}"
        except Exception as exc:
            status = "FAILED"
            self._record_exception(stage, exc)
            self._write_line(
                format_iperf_log_line(
                    datetime.now(),
                    f"iperf run finished, status=FAILED, error=runner_exception, stage={self.exception_stage}, "
                    f"type={self.exception_type}, message={self.exception_message}",
                    self.context,
                )
            )
            raise
        finally:
            if self.stop_requested:
                self._write_line(format_iperf_log_line(datetime.now(), "stopped by collection stop", self.context))
            if return_code is not None and return_code != 0:
                self._write_line(format_iperf_log_line(datetime.now(), f"iperf process exited with code {return_code}", self.context))
            stage = "footer_write"
            self._write_footers(status, return_code)
            try:
                self.bytes_written = self.log_file.stat().st_size
            except OSError:
                pass
            if self.process is not None:
                shutdown_manager.unregister_process(self.process)
            self.last_status = status
            self.last_exit_at = datetime.now()
            self.stop_reason = self.stop_status if self.stop_requested else "process_exit"
            if self.store:
                self.store.finish_run(self.run_id, status)

    def stop(self, status: str = "STOPPED_BY_USER") -> None:
        self.stop_requested = True
        self.stop_status = str(status or "STOPPED_BY_USER")
        if self.process is None:
            self.stop_reason = "not_started"
            return
        if self.process.poll() is not None:
            self.stop_reason = "already_exited"
            return
        self.stop_reason = self.stop_status
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)

    def _start_header_lines(self, timestamp: datetime, context: dict[str, object]) -> list[str]:
        return format_iperf_log_header(context, timestamp)

    def _write_headers(self) -> None:
        with self._log_lock:
            targets = [(self.log_file, self.context), *sorted(self.mirror_contexts.items())]
            for path, context in targets:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as file:
                    for line in self._start_header_lines(self.started_at, context):
                        file.write(line + "\n")

    def _write_footers(self, status: str, return_code: int | None) -> None:
        lines = format_iperf_log_footer(datetime.now(), status, return_code, self.last_error_code)
        with self._log_lock:
            for path in [self.log_file, *sorted(self.mirror_contexts)]:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as file:
                    for line in lines:
                        file.write(line + "\n")
                    file.flush()

    def _write_lines(self, lines: list[str]) -> None:
        for line in lines:
            self._write_line(line)

    def _write_line(self, line: str) -> None:
        with self._log_lock:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
                file.flush()
            for path in sorted(self.mirror_contexts):
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as file:
                        file.write(line + "\n")
                        file.flush()
                except Exception as exc:
                    self._record_degraded("mirror_write", exc)

    def _emit_line(self, line: str, row: dict[str, object] | None, error: dict[str, object] | None) -> None:
        if self.line_callback is None:
            return
        try:
            self.line_callback(line, row, error)
        except TypeError:
            try:
                self.line_callback(line, row)
            except Exception as exc:
                self._record_degraded("callback", exc)
        except Exception as exc:
            self._record_degraded("callback", exc)

    def _record_degraded(self, stage: str, exc: BaseException) -> None:
        self.degraded = True
        warning = f"{stage}: {type(exc).__name__}: {exc}"
        if warning not in self.degraded_warnings:
            self.degraded_warnings.append(warning)

    def _record_exception(self, stage: str, exc: BaseException) -> None:
        self.exception_stage = str(stage or "unknown")
        self.exception_type = type(exc).__name__
        self.exception_message = str(exc)
        self.traceback_tail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).splitlines()[-20:]
        self.traceback_tail = "\n".join(self.traceback_tail)
