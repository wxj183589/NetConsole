from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshLogRecord
from netconsole.models.online_mr_models import (
    ACTIVE_SESSION_STATES,
    TASK_AP_RADIO_STATISTICS,
    TASK_CHANNEL_BUSY,
    TASK_FPING,
    TASK_CONFIG_COLLECT,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
    TASK_TERMINAL_MONITOR,
    OnlineMrConnectionConfig,
    OnlineMrSessionMeta,
)
from netconsole.services.online_mr_parser import parse_interface_rate_text


RAW_FILES = {
    "init": "init_raw.log",
    TASK_CONFIG_COLLECT: "config_collect_raw.log",
    TASK_TERMINAL_MONITOR: "terminal_monitor_raw.log",
    TASK_MESH_LINK: "mesh_link_raw.log",
    TASK_CHANNEL_BUSY: "channel_busy_raw.log",
    TASK_AP_RADIO_STATISTICS: "ap_radio_statistics_raw.log",
    TASK_SWITCH_HISTORY: "switch_history_latest.log",
    TASK_INTERFACE_RATE: "interface_rate_raw.log",
    TASK_FPING: "fping_v5_raw.log",
    "reconnect": "reconnect.log",
}


class OnlineMrSessionStore:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def create_session(
        self,
        config: OnlineMrConnectionConfig,
        now: datetime | None = None,
        *,
        session_type: str = "realtime",
        config_collect_enabled: bool | None = None,
    ) -> "OnlineMrSession":
        started = now or datetime.now()
        session_id = f"{started:%Y%m%d_%H%M%S}_{id(config) & 0xFFFFFF:06x}"
        session_dir = self.paths.online_mr_session_dir(config.site, config.safe_mr_name, session_id)
        for relative in ("raw", "parsed", "view", "logs", "outputs"):
            (session_dir / relative).mkdir(parents=True, exist_ok=True)
        enabled = bool(config.collect_config_on_start) if config_collect_enabled is None else bool(config_collect_enabled)
        meta = OnlineMrSessionMeta(
            session_id=session_id,
            site=config.site,
            mr_id=config.mr_id,
            mr_name=config.mr_name,
            device_id=config.device_id,
            device_name=config.device_name,
            host=config.host,
            protocol=config.protocol,
            port=int(config.port),
            connection_method=config.connection_method,
            started_at=started,
            intervals=config.intervals.as_dict(),
            radio=config.radio.as_dict(),
            fping=config.fping.as_dict(),
            iperf=config.iperf.as_dict(),
            stats={},
            session_dir=session_dir,
            session_type=session_type,
            config_collect_enabled=enabled,
            config_collect_status="skipped" if not enabled else "pending",
            raw_log_path=str(session_dir / "raw" / "terminal_monitor_raw.txt"),
        )
        session = OnlineMrSession(session_dir, meta)
        session.initialize_database()
        session.ensure_raw_files()
        session.write_meta()
        return session

    def mark_stale_sessions_aborted(self, site_name: str) -> list[Path]:
        changed: list[Path] = []
        root = self.paths.online_mr_root(site_name)
        if not root.exists():
            return changed
        for meta_path in root.glob("*/sessions/*/session_meta.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("status") not in ACTIVE_SESSION_STATES:
                continue
            data["status"] = "ABORTED"
            data["ended_at"] = data.get("ended_at") or datetime.now().isoformat(sep=" ", timespec="seconds")
            meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            changed.append(meta_path)
        return changed

    def list_sessions(self, site_name: str, safe_mr_name: str | None = None) -> list[dict[str, object]]:
        roots = [self.paths.online_mr_sessions_root(site_name, safe_mr_name)] if safe_mr_name else list(self.paths.online_mr_root(site_name).glob("*/sessions"))
        rows: list[dict[str, object]] = []
        for root in roots:
            if not root.exists():
                continue
            for meta_path in root.glob("*/session_meta.json"):
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                data["session_dir"] = str(meta_path.parent)
                rows.append(data)
        return sorted(rows, key=lambda item: str(item.get("started_at") or ""), reverse=True)


class OnlineMrSession:
    def __init__(self, session_dir: Path, meta: OnlineMrSessionMeta) -> None:
        self.session_dir = session_dir
        self.meta = meta
        self.db_path = session_dir / "parsed" / "online_diagnosis.sqlite"

    def initialize_database(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS live_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    device_clock TEXT,
                    command_group TEXT NOT NULL,
                    raw_file TEXT NOT NULL,
                    raw_offset_start INTEGER NOT NULL,
                    raw_offset_end INTEGER NOT NULL,
                    parse_status TEXT NOT NULL,
                    error_message TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS live_mesh_links (
                    sample_id INTEGER NOT NULL,
                    radio INTEGER,
                    link_state TEXT,
                    peer_mac_raw TEXT,
                    peer_mac_normalized TEXT,
                    establish_time TEXT,
                    duration_seconds INTEGER,
                    link_count INTEGER,
                    local_rssi_db INTEGER,
                    peer_rssi_db INTEGER,
                    local_noise_dbm INTEGER,
                    peer_noise_dbm INTEGER,
                    local_signal_dbm INTEGER,
                    peer_signal_dbm INTEGER,
                    local_tx_busy INTEGER,
                    peer_tx_busy INTEGER,
                    local_rx_busy INTEGER,
                    peer_rx_busy INTEGER,
                    local_rate_raw INTEGER,
                    peer_rate_raw INTEGER,
                    local_retry INTEGER,
                    peer_retry INTEGER,
                    local_err INTEGER,
                    peer_err INTEGER
                );
                CREATE TABLE IF NOT EXISTS live_channel_busy (
                    sample_id INTEGER NOT NULL,
                    radio INTEGER,
                    tx_busy INTEGER,
                    rx_busy INTEGER,
                    raw_text TEXT
                );
                CREATE TABLE IF NOT EXISTS live_radio_statistics_raw_index (
                    sample_id INTEGER NOT NULL,
                    raw_text TEXT
                );
                CREATE TABLE IF NOT EXISTS live_switch_history_latest (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collected_at TEXT NOT NULL,
                    device_clock TEXT,
                    raw_file TEXT,
                    raw_offset_start INTEGER,
                    raw_offset_end INTEGER,
                    record_count INTEGER DEFAULT 0,
                    parse_status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS live_interface_rates (
                    sample_id INTEGER NOT NULL,
                    collected_at TEXT,
                    device_clock TEXT,
                    direction TEXT,
                    interface_name TEXT,
                    usage_percent REAL,
                    total_pps INTEGER,
                    broadcast_pps INTEGER,
                    multicast_pps INTEGER,
                    raw_line TEXT,
                    raw_text TEXT
                );
                CREATE TABLE IF NOT EXISTS live_terminal_events (
                    sample_id INTEGER,
                    collected_at TEXT,
                    raw_text TEXT
                );
                CREATE TABLE IF NOT EXISTS ping_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    target_ip TEXT,
                    seq INTEGER,
                    success INTEGER NOT NULL,
                    latency_ms REAL,
                    ttl INTEGER,
                    packet_size INTEGER,
                    interval_ms INTEGER,
                    loss_threshold_ms INTEGER,
                    raw_line TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ping_summary (
                    session_id TEXT NOT NULL,
                    target_ip TEXT,
                    sent INTEGER,
                    received INTEGER,
                    lost INTEGER,
                    loss_percent REAL,
                    min_latency_ms REAL,
                    max_latency_ms REAL,
                    latest_latency_ms REAL,
                    avg_latency_ms REAL,
                    created_at TEXT NOT NULL
                );
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
                CREATE TABLE IF NOT EXISTS live_events (
                    event_time TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    radio INTEGER,
                    from_peer_mac TEXT,
                    to_peer_mac TEXT,
                    details_json TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS collector_logs (
                    log_time TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ping_samples_time ON ping_samples(collected_at);
                CREATE INDEX IF NOT EXISTS idx_ping_samples_seq ON ping_samples(seq);
                CREATE INDEX IF NOT EXISTS idx_ping_samples_success ON ping_samples(success);
                CREATE INDEX IF NOT EXISTS idx_iperf_intervals_time ON iperf_intervals(interval_center_time);
                CREATE INDEX IF NOT EXISTS idx_iperf_intervals_run ON iperf_intervals(run_id);
                """
            )

    def ensure_raw_files(self) -> None:
        for raw_name in set(RAW_FILES.values()) | {"fping_v5_samples.jsonl", "fping_v5_final_summary.json"}:
            path = self.session_dir / "raw" / raw_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        (self.session_dir / "raw" / "terminal_monitor_raw.txt").touch(exist_ok=True)

    def update_status(self, status: str) -> None:
        self.meta.status = status
        self.log("INFO", f"state={status}")
        self.write_meta()

    def finish(self, status: str, stats: dict[str, int]) -> None:
        self.meta.status = status
        self.meta.ended_at = datetime.now()
        self.meta.stats = dict(stats)
        self.write_meta()

    def write_fping_final_summary(self, message: str) -> Path:
        path = self.session_dir / "raw" / "fping_v5_final_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = str(message or "").strip() or "未采集到 fping 数据"
        path.write_text(f"{text}\n", encoding="utf-8")
        return path

    def write_current_configuration(self, raw_text: str) -> Path:
        path = self.session_dir / "outputs" / "current_configuration.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw_text.rstrip() + "\n", encoding="utf-8", errors="replace")
        return path

    def update_config_collect(
        self,
        *,
        enabled: bool | None = None,
        status: str | None = None,
        file_path: Path | str | None = None,
        error: str | None = None,
    ) -> None:
        if enabled is not None:
            self.meta.config_collect_enabled = bool(enabled)
        if status is not None:
            self.meta.config_collect_status = status
        if file_path is not None:
            self.meta.config_file_path = str(file_path)
        self.meta.config_error = error
        self.write_meta()

    def write_meta(self) -> None:
        path = self.session_dir / "session_meta.json"
        path.write_text(json.dumps(self.meta.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def log(self, level: str, message: str) -> None:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        line = f"{now} [{level}] {message}\n"
        with (self.session_dir / "logs" / "collector.log").open("a", encoding="utf-8") as file:
            file.write(line)
            file.flush()
        with self._connect() as conn:
            conn.execute("INSERT INTO collector_logs (log_time, level, message) VALUES (?, ?, ?)", (now, level, message))

    def append_raw(self, task_type: str, command: str, raw_text: str, collected_at: datetime | None = None) -> tuple[str, int, int]:
        raw_name = RAW_FILES[task_type]
        path = self.session_dir / "raw" / raw_name
        offset_start = path.stat().st_size if path.exists() else 0
        stamp = (collected_at or datetime.now()).isoformat(sep=" ", timespec="seconds")
        payload = f"{stamp} >>> {command}\n{raw_text.rstrip()}\n"
        with path.open("a", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
        self.append_terminal_monitor_raw(payload)
        return f"raw/{raw_name}", offset_start, offset_start + len(payload.encode("utf-8"))

    def append_terminal_monitor_raw(self, text: str, collected_at: datetime | None = None) -> Path:
        path = self.session_dir / "raw" / "terminal_monitor_raw.txt"
        stamp = (collected_at or datetime.now()).isoformat(sep=" ", timespec="milliseconds")
        payload = text if text.endswith("\n") else f"{text}\n"
        with path.open("a", encoding="utf-8", errors="replace") as file:
            file.write(f"{stamp} {payload}")
            file.flush()
        return path

    def append_sample(
        self,
        task_type: str,
        collected_at: datetime,
        command: str,
        raw_file: str,
        raw_offset_start: int,
        raw_offset_end: int,
        parse_status: str,
        error_message: str = "",
        device_clock: str | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO live_samples (
                    session_id, task_type, collected_at, device_clock, command_group, raw_file, raw_offset_start,
                    raw_offset_end, parse_status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.meta.session_id,
                    task_type,
                    collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    device_clock,
                    command,
                    raw_file,
                    raw_offset_start,
                    raw_offset_end,
                    parse_status,
                    error_message,
                ),
            )
            return int(cursor.lastrowid)

    def append_mesh_links(self, sample_id: int, records: list[MeshLogRecord]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO live_mesh_links (
                    sample_id, radio, link_state, peer_mac_raw, peer_mac_normalized, establish_time,
                    duration_seconds, link_count, local_rssi_db, peer_rssi_db, local_noise_dbm,
                    peer_noise_dbm, local_signal_dbm, peer_signal_dbm, local_tx_busy, peer_tx_busy,
                    local_rx_busy, peer_rx_busy, local_rate_raw, peer_rate_raw, local_retry,
                    peer_retry, local_err, peer_err
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._mesh_values(sample_id, record) for record in records],
            )

    def append_channel_busy(self, sample_id: int, rows: list[dict[str, object]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO live_channel_busy (sample_id, radio, tx_busy, rx_busy, raw_text) VALUES (?, ?, ?, ?, ?)",
                [(sample_id, row.get("radio"), row.get("tx_busy"), row.get("rx_busy"), row.get("raw_text")) for row in rows],
            )

    def append_raw_index(self, table: str, sample_id: int, raw_text: str) -> None:
        if table not in {"live_radio_statistics_raw_index"}:
            raise ValueError(table)
        with self._connect() as conn:
            conn.execute(f"INSERT INTO {table} (sample_id, raw_text) VALUES (?, ?)", (sample_id, raw_text))

    def replace_switch_history_latest(
        self,
        collected_at: datetime,
        raw_text: str,
        raw_file: str,
        raw_offset_start: int,
        raw_offset_end: int,
        parse_status: str = "OK",
        device_clock: str | None = None,
    ) -> None:
        latest_path = self.session_dir / "raw" / "switch_history_latest.log"
        tmp_path = self.session_dir / "raw" / "switch_history_latest.tmp"
        tmp_path.write_text(raw_text.rstrip() + "\n", encoding="utf-8")
        tmp_path.replace(latest_path)
        with self._connect() as conn:
            conn.execute("DELETE FROM live_switch_history_latest")
            conn.execute(
                """
                INSERT INTO live_switch_history_latest (
                    collected_at, device_clock, raw_file, raw_offset_start, raw_offset_end, record_count, parse_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    device_clock,
                    raw_file,
                    raw_offset_start,
                    raw_offset_end,
                    len([line for line in raw_text.splitlines() if line.strip()]),
                    parse_status,
                ),
            )

    def append_interface_rates(self, sample_id: int, collected_at: datetime, raw_text: str) -> None:
        rows = parse_interface_rate_text(raw_text)
        with self._connect() as conn:
            if rows:
                conn.executemany(
                    """
                    INSERT INTO live_interface_rates (
                        sample_id, collected_at, device_clock, direction, interface_name, usage_percent,
                        total_pps, broadcast_pps, multicast_pps, raw_line, raw_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            sample_id,
                            collected_at.isoformat(sep=" ", timespec="milliseconds"),
                            None,
                            row.get("direction"),
                            row.get("interface_name"),
                            row.get("usage_percent"),
                            row.get("total_pps"),
                            row.get("broadcast_pps"),
                            row.get("multicast_pps"),
                            row.get("raw_line"),
                            raw_text,
                        )
                        for row in rows
                    ],
                )
                return
            conn.execute(
                """
                INSERT INTO live_interface_rates (
                    sample_id, collected_at, device_clock, direction, interface_name, usage_percent,
                    total_pps, broadcast_pps, multicast_pps, raw_line, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sample_id, collected_at.isoformat(sep=" ", timespec="milliseconds"), None, None, None, None, None, None, None, None, raw_text),
            )

    def append_ping_samples(self, rows: list[dict[str, object]], packet_size: int, interval_ms: int, loss_threshold_ms: int) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO ping_samples (
                    session_id, collected_at, target_ip, seq, success, latency_ms, ttl,
                    packet_size, interval_ms, loss_threshold_ms, raw_line
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        self.meta.session_id,
                        row["collected_at"],
                        row.get("target_ip"),
                        row.get("seq"),
                        1 if row.get("success") else 0,
                        row.get("latency_ms"),
                        row.get("ttl"),
                        packet_size,
                        interval_ms,
                        loss_threshold_ms,
                        row.get("raw_line", ""),
                    )
                    for row in rows
                ],
            )

    def append_ping_summary(self, summary: dict[str, object]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ping_summary (
                    session_id, target_ip, sent, received, lost, loss_percent, min_latency_ms,
                    max_latency_ms, latest_latency_ms, avg_latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.meta.session_id,
                    summary.get("target_ip"),
                    summary.get("sent"),
                    summary.get("received"),
                    summary.get("lost"),
                    summary.get("loss_percent"),
                    summary.get("min_latency_ms"),
                    summary.get("max_latency_ms"),
                    summary.get("latest_latency_ms"),
                    summary.get("avg_latency_ms"),
                    datetime.now().isoformat(sep=" ", timespec="seconds"),
                ),
            )

    def append_event(self, event_type: str, radio: int | None = None, from_peer: str | None = None, to_peer: str | None = None, details_json: str = "{}") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO live_events (event_time, event_type, radio, from_peer_mac, to_peer_mac, details_json) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(sep=" ", timespec="milliseconds"), event_type, radio, from_peer, to_peer, details_json),
            )

    def append_reconnect(self, message: str) -> None:
        path = self.session_dir / "raw" / RAW_FILES["reconnect"]
        with path.open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now().isoformat(sep=' ', timespec='seconds')} {message}\n")
            file.flush()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return conn

    def _mesh_values(self, sample_id: int, record: MeshLogRecord) -> tuple[object, ...]:
        metrics = record.metrics
        return (
            sample_id,
            record.radio,
            record.link_state,
            record.peer_mac_raw,
            record.peer_mac_normalized,
            record.establish_time.isoformat(sep=" ", timespec="seconds") if record.establish_time else None,
            record.duration_seconds,
            record.link_count,
            metrics.get("local_rssi_db"),
            metrics.get("peer_rssi_db"),
            record.local_noise_dbm,
            record.peer_noise_dbm,
            record.local_signal_dbm,
            record.peer_signal_dbm,
            metrics.get("local_tx_busy"),
            metrics.get("peer_tx_busy"),
            metrics.get("local_rx_busy"),
            metrics.get("peer_rx_busy"),
            metrics.get("local_rate_raw"),
            metrics.get("peer_rate_raw"),
            metrics.get("local_retry"),
            metrics.get("peer_retry"),
            metrics.get("local_err"),
            metrics.get("peer_err"),
        )
