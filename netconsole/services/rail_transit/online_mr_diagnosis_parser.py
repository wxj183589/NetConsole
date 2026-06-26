from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from netconsole.services.fping_v3 import parse_fping_lines
from netconsole.services.network_tools.iperf_parser import parse_iperf_lines
from netconsole.services.network_tools.iperf_runner import IperfResultStore
from netconsole.services.online_mr_parser import parse_channel_busy_text, parse_mesh_link_text
from netconsole.services.online_mr_session_store import OnlineMrSession


RAW_BLOCK_RE = re.compile(r"(?m)^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) >>> (?P<command>.+)$")
STREAM_START_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[collector=(?P<collector>[^\]]+)\] START commands:\s*$")
RX_LINE_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?) \[collector=[^\]]+\] RX ?(?P<text>.*)$")


def strip_stream_rx_prefix(line: str) -> str:
    match = RX_LINE_RE.match(line)
    return match.group("text") if match else line


def read_text_with_retry(path: Path, retries: int = 10, interval: float = 0.3) -> str:
    last_exc: PermissionError | None = None
    for _ in range(max(1, retries)):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except PermissionError as exc:
            last_exc = exc
            time.sleep(interval)
    if last_exc is not None:
        raise last_exc
    return path.read_text(encoding="utf-8", errors="replace")


@dataclass
class RawBlock:
    collected_at: datetime
    command: str
    text: str
    offset_start: int
    offset_end: int


@dataclass
class OnlineMrParseSummary:
    mesh_samples: int = 0
    channel_samples: int = 0
    interface_samples: int = 0
    ping_samples: int = 0
    iperf_samples: int = 0
    active_segments: int = 0
    issues: int = 0


class OnlineMrRawBlockSplitter:
    def split(self, raw_path: Path) -> list[RawBlock]:
        if not raw_path.exists():
            return []
        text = read_text_with_retry(raw_path, retries=2, interval=0.05)
        matches = list(RAW_BLOCK_RE.finditer(text))
        blocks: list[RawBlock] = []
        if not matches:
            return self._split_rx_stream(text)
        for index, match in enumerate(matches):
            body_start = match.end() + 1
            body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            blocks.append(
                RawBlock(
                    collected_at=datetime.fromisoformat(match.group("stamp")),
                    command=match.group("command").strip(),
                    text=text[body_start:body_end].strip(),
                    offset_start=match.start(),
                    offset_end=body_end,
                )
            )
        return blocks

    def _split_rx_stream(self, text: str) -> list[RawBlock]:
        blocks: list[RawBlock] = []
        current_lines: list[str] = []
        current_stamp: datetime | None = None
        current_offset = 0
        current_command = "repeat stream"
        position = 0
        for line in text.splitlines():
            line_start = text.find(line, position)
            if line_start < 0:
                line_start = position
            position = line_start + len(line) + 1
            match = RX_LINE_RE.match(line)
            if not match:
                continue
            clean = match.group("text")
            normalized = clean.strip().lower()
            is_cycle_start = normalized == "display clock" or normalized.endswith("]display clock")
            if is_cycle_start and current_lines and current_stamp is not None:
                blocks.append(
                    RawBlock(
                        collected_at=current_stamp,
                        command=current_command,
                        text="\n".join(current_lines).strip(),
                        offset_start=current_offset,
                        offset_end=max(current_offset, line_start),
                    )
                )
                current_lines = []
            if current_stamp is None or is_cycle_start:
                stamp = match.group("stamp").replace("T", " ")
                current_stamp = datetime.fromisoformat(stamp)
                current_offset = line_start
                current_command = "repeat stream"
            if normalized.startswith("display ") or "]display " in normalized:
                current_command = clean.strip()
            current_lines.append(clean)
        if current_lines and current_stamp is not None:
            blocks.append(
                RawBlock(
                    collected_at=current_stamp,
                    command=current_command,
                    text="\n".join(current_lines).strip(),
                    offset_start=current_offset,
                    offset_end=len(text),
                )
            )
        return blocks


class OnlineMrDiagnosisParser:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = Path(session_dir)
        self.raw_dir = self.session_dir / "raw"
        self.db_path = self.session_dir / "parsed" / "online_diagnosis.sqlite"
        self.meta = self._load_meta()
        self.splitter = OnlineMrRawBlockSplitter()

    def parse(self) -> OnlineMrParseSummary:
        self._ensure_tables()
        self._reset_parsed_tables()
        summary = OnlineMrParseSummary()
        session = OnlineMrSession(self.session_dir, self.meta)
        summary.mesh_samples = self._parse_mesh(session)
        summary.channel_samples = self._parse_channel_busy(session)
        summary.interface_samples = self._parse_interface_rate(session)
        summary.ping_samples = self._parse_fping(session)
        summary.iperf_samples = self._parse_iperf()
        summary.active_segments = OnlineMrTimelineFusionService(self.db_path, self.meta.session_id).rebuild()
        summary.issues = self._issue_count()
        return summary

    def _load_meta(self):
        from netconsole.models.online_mr_models import OnlineMrSessionMeta

        data = json.loads((self.session_dir / "session_meta.json").read_text(encoding="utf-8"))
        data["started_at"] = datetime.fromisoformat(data["started_at"])
        if data.get("ended_at"):
            data["ended_at"] = datetime.fromisoformat(data["ended_at"])
        data["session_dir"] = self.session_dir
        return OnlineMrSessionMeta(**data)

    def _parse_mesh(self, session: OnlineMrSession) -> int:
        count = 0
        blocks = self.splitter.split(self.raw_dir / "mesh_link_raw.log")
        if not blocks and (self.raw_dir / "mesh_link_raw.log").exists():
            self._issue("mesh_link_raw.log", "mesh-link", "no parseable raw blocks found", "")
        for block in blocks:
            records, status, error = parse_mesh_link_text(block.text, block.collected_at)
            sample_id = session.append_sample("mesh_link", block.collected_at, block.command, "raw/mesh_link_raw.log", block.offset_start, block.offset_end, status, error)
            if records:
                session.append_mesh_links(sample_id, records)
                count += 1
            elif error:
                self._issue("mesh_link_raw.log", "mesh-link", error, block.text[:500])
        return count

    def _parse_channel_busy(self, session: OnlineMrSession) -> int:
        seen: set[tuple[object, ...]] = set()
        count = 0
        for block in self.splitter.split(self.raw_dir / "channel_busy_raw.log"):
            rows = parse_channel_busy_text(block.text)
            unique = []
            for row in rows:
                key = (row.get("radio"), block.collected_at.isoformat(), row.get("tx_busy"), row.get("rx_busy"), row.get("raw_text"))
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            sample_id = session.append_sample("channel_busy", block.collected_at, block.command, "raw/channel_busy_raw.log", block.offset_start, block.offset_end, "OK")
            if unique:
                session.append_channel_busy(sample_id, unique)
                count += len(unique)
        return count

    def _parse_interface_rate(self, session: OnlineMrSession) -> int:
        count = 0
        for block in self.splitter.split(self.raw_dir / "interface_rate_raw.log"):
            sample_id = session.append_sample("interface_rate", block.collected_at, block.command, "raw/interface_rate_raw.log", block.offset_start, block.offset_end, "PARTIAL")
            session.append_interface_rates(sample_id, block.collected_at, block.text)
            count += 1
        return count

    def _parse_fping(self, session: OnlineMrSession) -> int:
        path = self.raw_dir / "Fping.txt"
        if not path.exists():
            self._issue("Fping.txt", "fping", "Fping.txt was not found", "")
            return 0
        try:
            text = read_text_with_retry(path, retries=10, interval=0.3)
        except PermissionError as exc:
            self._issue("Fping.txt", "fping", f"Fping.txt is locked by Fping_v3.exe; ping parsing was skipped: {exc}", "", severity="ERROR")
            return 0
        rows = parse_fping_lines(text.splitlines(), self.meta.started_at, default_target=str(self.meta.fping.get("target") or ""))
        if rows:
            fping = self.meta.fping
            session.append_ping_samples(rows, int(fping.get("packet_size") or 64), int(fping.get("interval_ms") or 10), int(fping.get("loss_threshold_ms") or 100))
        return len(rows)

    def _parse_iperf(self) -> int:
        path = self.raw_dir / "iperf_client_raw.log"
        if not path.exists():
            return 0
        rows = parse_iperf_lines(path.read_text(encoding="utf-8", errors="replace").splitlines(), self.meta.started_at)
        if not rows:
            return 0
        store = IperfResultStore(self.db_path)
        run_id = f"parsed_{self.meta.session_id}"
        command = ["iperf3", "parsed"]
        store.start_run(run_id, mode="client", command=command, log_file=path, started_at=self.meta.started_at, session_id=self.meta.session_id, device_id=self.meta.device_id)
        for row in rows:
            store.append_interval(run_id, row, self.meta.session_id)
        store.finish_run(run_id, "PARSED")
        return len(rows)

    def _ensure_tables(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS online_parse_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    raw_file TEXT,
                    line_number INTEGER,
                    issue_type TEXT,
                    severity TEXT,
                    message TEXT,
                    raw_text TEXT
                );
                CREATE TABLE IF NOT EXISTS active_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    radio INTEGER,
                    active_peer_mac TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    sample_count INTEGER,
                    avg_mr_rssi REAL,
                    min_mr_rssi INTEGER,
                    max_mr_rssi INTEGER,
                    event_type TEXT,
                    details_json TEXT
                );
                CREATE TABLE IF NOT EXISTS active_segment_metrics (
                    segment_id INTEGER PRIMARY KEY,
                    ping_sent INTEGER,
                    ping_success INTEGER,
                    ping_lost INTEGER,
                    ping_loss_percent REAL,
                    avg_latency_ms REAL,
                    max_latency_ms REAL,
                    iperf_sample_count INTEGER,
                    avg_mbps REAL,
                    min_mbps REAL,
                    max_mbps REAL,
                    p95_mbps REAL,
                    total_retransmits INTEGER,
                    avg_tx_busy REAL,
                    max_tx_busy REAL,
                    avg_rx_busy REAL,
                    max_rx_busy REAL
                );
                """
            )

    def _reset_parsed_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for table in (
                "live_samples",
                "live_mesh_links",
                "live_channel_busy",
                "live_interface_rates",
                "ping_samples",
                "ping_summary",
                "iperf_runs",
                "iperf_intervals",
                "active_segments",
                "active_segment_metrics",
                "online_parse_issues",
            ):
                conn.execute(f"DELETE FROM {table}")

    def _issue(self, raw_file: str, issue_type: str, message: str, raw_text: str, severity: str = "WARNING") -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO online_parse_issues (session_id, raw_file, line_number, issue_type, severity, message, raw_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.meta.session_id, raw_file, 0, issue_type, severity, message, raw_text),
            )

    def _issue_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM online_parse_issues").fetchone()[0])


class OnlineMrTimelineFusionService:
    def __init__(self, db_path: Path, session_id: str) -> None:
        self.db_path = Path(db_path)
        self.session_id = session_id

    def rebuild(self) -> int:
        samples = self._active_samples()
        segments: list[dict[str, object]] = []
        current: dict[str, object] | None = None
        for sample in samples:
            key = (sample["radio"], sample["event_type"], sample["active_peer_mac"])
            if current is None or current["key"] != key:
                if current is not None:
                    current["end_time"] = sample["collected_at"]
                    segments.append(current)
                current = {**sample, "key": key, "start_time": sample["collected_at"], "end_time": sample["collected_at"], "rssis": []}
            current["end_time"] = sample["collected_at"]
            current["sample_count"] = int(current.get("sample_count") or 0) + 1
            if sample.get("mr_rssi") is not None:
                current["rssis"].append(int(sample["mr_rssi"]))
        if current is not None:
            segments.append(current)
        with sqlite3.connect(self.db_path) as conn:
            for segment in segments:
                rssis = segment.get("rssis") or []
                cursor = conn.execute(
                    """
                    INSERT INTO active_segments (
                        session_id, radio, active_peer_mac, start_time, end_time, sample_count,
                        avg_mr_rssi, min_mr_rssi, max_mr_rssi, event_type, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.session_id,
                        segment.get("radio"),
                        segment.get("active_peer_mac"),
                        segment.get("start_time"),
                        segment.get("end_time"),
                        segment.get("sample_count", 0),
                        sum(rssis) / len(rssis) if rssis else None,
                        min(rssis) if rssis else None,
                        max(rssis) if rssis else None,
                        segment.get("event_type"),
                        "{}",
                    ),
                )
                self._insert_metrics(conn, int(cursor.lastrowid), str(segment.get("start_time")), str(segment.get("end_time")))
        return len(segments)

    def _active_samples(self) -> list[dict[str, object]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT s.collected_at, l.radio, l.link_state, l.peer_mac_raw, l.peer_mac_normalized, l.local_rssi_db
                FROM live_samples s
                JOIN live_mesh_links l ON l.sample_id = s.id
                WHERE s.session_id = ?
                ORDER BY s.collected_at ASC, l.radio ASC
                """,
                (self.session_id,),
            ).fetchall()
        grouped: dict[tuple[str, int], list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault((row["collected_at"], int(row["radio"] or 1)), []).append(row)
        samples: list[dict[str, object]] = []
        for (collected_at, radio), group in sorted(grouped.items()):
            active = [row for row in group if str(row["link_state"]).upper() == "ACTIVE"]
            if len(active) == 1:
                event_type = "ACTIVE"
                peer = active[0]["peer_mac_normalized"] or active[0]["peer_mac_raw"]
                mr_rssi = active[0]["local_rssi_db"]
            elif not active:
                event_type = "NO_ACTIVE"
                peer = ""
                mr_rssi = None
            else:
                event_type = "MULTI_ACTIVE"
                peer = ",".join(str(row["peer_mac_normalized"] or row["peer_mac_raw"]) for row in active)
                mr_rssi = None
            samples.append({"collected_at": collected_at, "radio": radio, "event_type": event_type, "active_peer_mac": peer, "mr_rssi": mr_rssi, "sample_count": 0})
        return samples

    def _insert_metrics(self, conn: sqlite3.Connection, segment_id: int, start_time: str, end_time: str) -> None:
        ping = conn.execute(
            """
            SELECT COUNT(*) sent, SUM(success) success, AVG(latency_ms) avg_latency, MAX(latency_ms) max_latency
            FROM ping_samples WHERE collected_at >= ? AND collected_at < ?
            """,
            (start_time, end_time),
        ).fetchone()
        iperf = conn.execute(
            """
            SELECT COUNT(*) sample_count, AVG(bitrate_mbps), MIN(bitrate_mbps), MAX(bitrate_mbps), SUM(retransmits)
            FROM iperf_intervals WHERE interval_center_time >= ? AND interval_center_time < ?
            """,
            (start_time, end_time),
        ).fetchone()
        busy = conn.execute(
            """
            SELECT AVG(tx_busy), MAX(tx_busy), AVG(rx_busy), MAX(rx_busy)
            FROM live_channel_busy cb
            JOIN live_samples s ON s.id = cb.sample_id
            WHERE s.collected_at >= ? AND s.collected_at < ?
            """,
            (start_time, end_time),
        ).fetchone()
        sent = int(ping[0] or 0)
        success = int(ping[1] or 0)
        lost = sent - success
        conn.execute(
            """
            INSERT OR REPLACE INTO active_segment_metrics (
                segment_id, ping_sent, ping_success, ping_lost, ping_loss_percent, avg_latency_ms,
                max_latency_ms, iperf_sample_count, avg_mbps, min_mbps, max_mbps, p95_mbps,
                total_retransmits, avg_tx_busy, max_tx_busy, avg_rx_busy, max_rx_busy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment_id,
                sent,
                success,
                lost,
                (lost / sent * 100) if sent else None,
                ping[2],
                ping[3],
                iperf[0],
                iperf[1],
                iperf[2],
                iperf[3],
                iperf[3],
                iperf[4],
                busy[0],
                busy[1],
                busy[2],
                busy[3],
            ),
        )
