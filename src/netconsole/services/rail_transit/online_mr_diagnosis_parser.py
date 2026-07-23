from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.core.ping.fping_v5_parser import parse_fping_v5_json_line
from netconsole.repositories.online_mr_diagnosis_repository import (
    OnlineMrDatabaseError,
    OnlineMrDiagnosisRepository,
)
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.fping_legacy_parser import parse_fping_lines
from netconsole.services.network_tools.iperf_parser import parse_iperf_error_lines, parse_iperf_lines, read_iperf_text, summarize_iperf_zero_samples
from netconsole.services.ap_radio_mapping_service import ApRadioMappingService
from netconsole.services.online_mr_parser import parse_ap_radio_statistics_text, parse_channel_busy_text, parse_interface_rate_text, parse_mesh_link_text, parse_switch_history_text
from netconsole.services.online_mr_terminal_log_parser import ActiveLinkSwitchLog, parse_active_link_switch_logs
from netconsole.utils.text_encoding import read_text_with_fallback


RAW_BLOCK_RE = re.compile(r"(?m)^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) >>> (?P<command>.+)$")
STREAM_START_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[collector=(?P<collector>[^\]]+)\] START commands:\s*$")
RX_LINE_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?) \[collector=[^\]]+\] RX ?(?P<text>.*)$")
FPING_V5_RAW_JSON_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(?P<payload>\{.*\})\s*$")
RX_COMMAND_RE = re.compile(
    r"(display\s+clock|display\s+wlan\s+mesh-link(?:\s+switch-history)?|display\s+ar5drv\s+\d+\s+(?:channelbusy|statistics)|dis\s+counters\s+rate\s+(?:inbound|outbound)\s+interface)\b",
    re.IGNORECASE,
)
DEVICE_CLOCK_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}\s+\S+\s+\w+\s+\d{1,2}/\d{1,2}/\d{4}\b", re.IGNORECASE)
PARSER_VERSION = "online_mr_sampling_model_v8_iperf_time_alignment"
ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]

_XGE_PREFIXES = ("xge", "xgigabitethernet", "ten-gigabitethernet", "tengigabitethernet")


def strip_stream_rx_prefix(line: str) -> str:
    match = RX_LINE_RE.match(line)
    return match.group("text") if match else line


def read_text_with_retry(path: Path, retries: int = 10, interval: float = 0.3) -> str:
    last_exc: PermissionError | None = None
    for _ in range(max(1, retries)):
        try:
            return read_text_with_fallback(path)
        except PermissionError as exc:
            last_exc = exc
            time.sleep(interval)
    if last_exc is not None:
        raise last_exc
    return read_text_with_fallback(path)


@dataclass
class RawBlock:
    collected_at: datetime
    command: str
    text: str
    offset_start: int
    offset_end: int
    clock_collected_at: datetime | None = None


@dataclass(frozen=True)
class TimeSyncSample:
    collector_time: datetime
    device_time: datetime
    offset_ms: float
    source: str = "mesh_link_display_clock"


@dataclass
class OnlineMrParseSummary:
    mesh_samples: int = 0
    channel_samples: int = 0
    radio_stats_samples: int = 0
    interface_samples: int = 0
    ping_samples: int = 0
    iperf_samples: int = 0
    iperf_zero_sample_count: int = 0
    iperf_isolated_gap_count: int = 0
    iperf_stall_count: int = 0
    iperf_error_count: int = 0
    switch_history_samples: int = 0
    active_link_switch_logs: int = 0
    active_segments: int = 0
    issues: int = 0
    cache_used: bool = False


def estimate_device_time_from_local(local_time: datetime, sync_samples: list[TimeSyncSample]) -> tuple[datetime | None, float | None, str]:
    if not sync_samples:
        return None, None, "none"
    samples = sorted(sync_samples, key=lambda item: item.collector_time)
    if local_time <= samples[0].collector_time:
        sample = samples[0]
        source = "first_sample"
    elif local_time >= samples[-1].collector_time:
        sample = samples[-1]
        source = "last_sample"
    else:
        sample = min(samples, key=lambda item: abs((item.collector_time - local_time).total_seconds()))
        source = "nearest_sample"
    return local_time + timedelta(milliseconds=float(sample.offset_ms)), float(sample.offset_ms), source


def _float_or_none(*values: object) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _interface_key(value: object) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip()).casefold()


def _is_excluded_xge_interface(value: object) -> bool:
    key = _interface_key(value)
    return any(key.startswith(prefix.replace("-", "")) for prefix in _XGE_PREFIXES)


def _normalize_ge_interface(value: object) -> str:
    text = str(value or "").strip()
    key = _interface_key(text)
    if key.startswith("gigabitethernet"):
        return "GE" + text[len("GigabitEthernet") :]
    if key.startswith("ge"):
        return text.upper().replace("G E", "GE")
    return text


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
                    clock_collected_at=None,
                )
            )
        return blocks

    def _split_rx_stream(self, text: str) -> list[RawBlock]:
        blocks: list[RawBlock] = []
        current_lines: list[str] = []
        current_stamp: datetime | None = None
        current_sample_stamp: datetime | None = None
        current_offset = 0
        current_commands: list[str] = []
        current_primary_command = ""
        position = 0

        def append_current(offset_end: int) -> None:
            nonlocal current_lines, current_stamp, current_sample_stamp, current_offset, current_commands, current_primary_command
            if not current_lines or current_stamp is None:
                return
            command_text = "\n".join(current_commands) if current_commands else "repeat stream"
            blocks.append(
                RawBlock(
                    collected_at=current_sample_stamp or current_stamp,
                    command=command_text,
                    text="\n".join(current_lines).strip(),
                    offset_start=current_offset,
                    offset_end=max(current_offset, offset_end),
                    clock_collected_at=current_stamp,
                )
            )
            current_lines = []
            current_stamp = None
            current_sample_stamp = None
            current_offset = 0
            current_commands = []
            current_primary_command = ""

        for raw_line in text.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")
            line_start = position
            line_end = position + len(raw_line)
            position = line_end
            match = RX_LINE_RE.match(line)
            if not match:
                continue
            clean = match.group("text")
            command = self._rx_command(clean)
            is_clock = command == "display clock"
            is_primary = self._is_primary_rx_command(command)
            starts_new_block = bool(current_lines and (is_clock or (is_primary and current_primary_command == command)))
            if starts_new_block:
                append_current(line_start)
            if current_stamp is None:
                stamp = match.group("stamp").replace("T", " ")
                current_stamp = datetime.fromisoformat(stamp)
                current_offset = line_start
            if command:
                if command not in current_commands:
                    current_commands.append(command)
                if is_primary and not current_primary_command:
                    current_primary_command = command
                    current_sample_stamp = datetime.fromisoformat(match.group("stamp").replace("T", " "))
            current_lines.append(clean)
        append_current(len(text))
        return blocks

    @staticmethod
    def _rx_command(text: str) -> str:
        matches = list(RX_COMMAND_RE.finditer(text.strip()))
        if not matches:
            return ""
        return re.sub(r"\s+", " ", matches[-1].group(1).strip().lower())

    @staticmethod
    def _is_primary_rx_command(command: str) -> bool:
        return (
            command == "display wlan mesh-link"
            or command == "display wlan mesh-link switch-history"
            or command.startswith("display ar5drv ")
            or command == "dis counters rate inbound interface"
        )


class OnlineMrDiagnosisParser:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = Path(session_dir)
        self.raw_dir = self.session_dir / "raw"
        self.db_path = self.session_dir / "parsed" / "online_diagnosis.sqlite"
        self.repository = OnlineMrDiagnosisRepository(self.db_path)
        self.meta = self._load_meta()
        self.splitter = OnlineMrRawBlockSplitter()
        self._peer_resolver: MeshPeerMappingService | None = None
        self._progress: ProgressCallback | None = None
        self._should_cancel: CancelCallback | None = None

    def parse(
        self,
        *,
        force: bool = True,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> OnlineMrParseSummary:
        self._progress = progress
        self._should_cancel = should_cancel
        self._emit_progress("扫描 session 文件", 0, 12, "准备解析")
        if force and self.db_path.exists():
            self._discard_existing_database()
        self._ensure_tables()
        if not force:
            cached = self.cached_summary_if_valid()
            if cached is not None:
                self._emit_progress("完成", 12, 12, "使用已解析缓存")
                return cached
            if self.db_path.exists():
                self._discard_existing_database()
            self._ensure_tables()
        self._check_cancel()
        self._emit_progress("写入 sqlite", 1, 12, "重建轻量解析数据库")
        self._reset_parsed_tables()
        summary = OnlineMrParseSummary()
        self._emit_progress("解析 mesh_link_raw.log", 2, 12, "解析主链路采样")
        summary.mesh_samples = self._parse_mesh()
        self._check_cancel()
        self._emit_progress("解析 channel_busy_raw.log", 3, 12, "解析信道繁忙度")
        summary.channel_samples = self._parse_channel_busy()
        self._check_cancel()
        self._emit_progress("解析 ap_radio_statistics_raw.log", 4, 12, "解析 AP 射频统计")
        summary.radio_stats_samples = self._parse_radio_statistics()
        self._check_cancel()
        self._emit_progress("解析 terminal_monitor_raw.log", 5, 12, "解析主链路切换日志")
        summary.active_link_switch_logs = self._parse_terminal_monitor_switch_logs()
        self._check_cancel()
        self._emit_progress("解析 interface_rate_raw.log", 6, 12, "解析接口速率")
        summary.interface_samples = self._parse_interface_rate()
        self._check_cancel()
        self._emit_progress("生成主链路切换日志", 7, 12, "解析 switch-history")
        summary.switch_history_samples = self._parse_switch_history()
        self._check_cancel()
        self._emit_progress("解析 fping", 8, 12, "解析 Ping 采样")
        summary.ping_samples = self._parse_fping()
        self._check_cancel()
        self._emit_progress("解析 iperf", 9, 12, "解析打流采样")
        summary.iperf_samples = self._parse_iperf()
        summary.iperf_zero_sample_count = getattr(self, "_last_iperf_zero_sample_count", 0)
        summary.iperf_isolated_gap_count = getattr(self, "_last_iperf_isolated_gap_count", 0)
        summary.iperf_stall_count = getattr(self, "_last_iperf_stall_count", 0)
        summary.iperf_error_count = getattr(self, "_last_iperf_error_count", 0)
        self._check_cancel()
        self._emit_progress("生成主链路采样点", 10, 12, "融合统一时间轴")
        summary.active_segments = OnlineMrTimelineFusionService(self.db_path, self.meta.session_id).rebuild()
        if summary.active_segments == 0 and self._has_any_valid_data(summary):
            summary.active_segments = self._insert_normal_data_segment(summary)
        self._emit_progress("生成诊断结果", 11, 12, "写入解析元信息")
        summary.issues = self._issue_count()
        self._write_parse_metadata(summary, "OK", "")
        self._emit_progress("完成", 12, 12, "解析完成")
        return summary

    def _emit_progress(self, stage: str, current: int, total: int, message: str = "") -> None:
        if self._progress is not None:
            self._progress(stage, current, total, message or stage)

    def _check_cancel(self) -> None:
        if self._should_cancel is not None and self._should_cancel():
            raise RuntimeError("解析已取消")

    def cached_summary_if_valid(self) -> OnlineMrParseSummary | None:
        if not self.db_path.exists():
            return None
        self._ensure_tables()
        fingerprint = self.raw_fingerprint()
        row = self.repository.cached_parse_metadata(
            self.meta.session_id,
            PARSER_VERSION,
            fingerprint,
        )
        if not row or row[1] != "OK":
            return None
        try:
            counts = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            return None
        if self._parsed_health_issue():
            return None
        summary = OnlineMrParseSummary()
        for key, value in counts.items():
            if hasattr(summary, key):
                try:
                    setattr(summary, key, int(value))
                except (TypeError, ValueError):
                    pass
        summary.cache_used = True
        return summary

    def cache_status(self) -> str:
        if not self.db_path.exists():
            return "missing"
        try:
            return "valid" if self.cached_summary_if_valid() is not None else "stale"
        except OnlineMrDatabaseError:
            return "broken"

    def raw_fingerprint(self) -> str:
        raw_root = self.raw_dir
        items: list[dict[str, object]] = []
        if raw_root.exists():
            for path in sorted(raw_root.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                items.append(
                    {
                        "path": path.relative_to(raw_root).as_posix(),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
        return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _parsed_health_issue(self) -> str:
        raw_path = self.raw_dir / "mesh_link_raw.log"
        raw_blocks = self.splitter.split(raw_path)
        raw_block_count = len(raw_blocks)
        raw_text = read_text_with_retry(raw_path, retries=2, interval=0.05) if raw_path.exists() else ""
        health = self.repository.parsed_health_snapshot(self.meta.session_id)
        if not health.get("required_tables_present"):
            return "required parsed tables are missing"
        mesh_sample_count = int(health["mesh_sample_count"])
        mesh_link_count = int(health["mesh_link_count"])
        active_link_count = int(health["active_link_count"])
        distinct_time_count = int(health["distinct_time_count"])
        if raw_block_count > 1 and mesh_sample_count <= 1:
            return "raw has multiple mesh-link blocks but parsed mesh_link samples <= 1"
        if ("Active(" in raw_text or "ACTIVE" in raw_text.upper()) and mesh_link_count == 0:
            return "raw has active mesh-link rows but parsed main_link_samples is empty"
        if raw_block_count > 1 and active_link_count > 1 and distinct_time_count <= 1:
            return "mesh-link collected_at values collapsed to one timestamp"
        if health["has_bad_segment"]:
            return "active_segments active_peer_mac looks concatenated"
        return ""

    def _main_link_metadata(self) -> dict[str, object]:
        return self.repository.main_link_metadata(self.meta.session_id)

    def _write_parse_metadata(self, summary: OnlineMrParseSummary, status: str, error_summary: str) -> None:
        row_counts = {
            key: value
            for key, value in summary.__dict__.items()
            if isinstance(value, (int, float)) and key != "cache_used"
        }
        row_counts.update(self._main_link_metadata())
        self.repository.replace_parse_metadata(
            (
                self.meta.session_id,
                datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                PARSER_VERSION,
                self.raw_fingerprint(),
                json.dumps(row_counts, ensure_ascii=False, sort_keys=True),
                status,
                error_summary,
            )
        )

    def _load_meta(self):
        from netconsole.models.online_mr_models import OnlineMrSessionMeta

        data = json.loads((self.session_dir / "session_meta.json").read_text(encoding="utf-8"))
        data["started_at"] = datetime.fromisoformat(data["started_at"])
        if data.get("ended_at"):
            data["ended_at"] = datetime.fromisoformat(data["ended_at"])
        data["session_dir"] = self.session_dir
        return OnlineMrSessionMeta(**data)

    def _parse_mesh(self) -> int:
        count = 0
        blocks = self.splitter.split(self.raw_dir / "mesh_link_raw.log")
        if not blocks and (self.raw_dir / "mesh_link_raw.log").exists():
            self._issue("mesh_link_raw.log", "mesh-link", "no parseable raw blocks found", "")
        for block in blocks:
            records, status, error = parse_mesh_link_text(block.text, block.collected_at)
            self._enrich_mesh_records(records)
            device_clock = self._extract_device_clock(block.text)
            if device_clock:
                self._write_time_sync_sample(block, device_clock, source="mesh_link_display_clock")
            if records:
                self._write_main_link_samples(block, records, device_clock=device_clock)
                count += 1
            elif error:
                self._issue("mesh_link_raw.log", "mesh-link", error, block.text[:500])
        return count

    def _write_time_sync_sample(self, block: RawBlock, device_clock: str, *, source: str) -> None:
        device_dt = self._parse_device_clock_value(device_clock)
        if device_dt is None:
            return
        collector_dt = block.clock_collected_at or block.collected_at
        offset_ms = (device_dt - collector_dt).total_seconds() * 1000.0
        self.repository.insert_rows(
            "time_sync_samples",
            [
                (
                    self.meta.session_id,
                    collector_dt.isoformat(sep=" ", timespec="milliseconds"),
                    device_dt.isoformat(sep=" ", timespec="milliseconds"),
                    offset_ms,
                    source,
                    "raw/mesh_link_raw.log",
                    block.offset_start,
                    block.offset_end,
                )
            ],
        )

    def _enrich_mesh_records(self, records) -> None:
        if not records:
            return
        resolver = self._get_peer_resolver()
        for record in records:
            metrics = record.metrics
            peer_name = str(metrics.get("peer_name") or "").strip()
            peer_mac = record.peer_mac_raw or record.peer_mac_normalized or ""
            resolved = resolver.resolve(peer_mac, peer_name=peer_name) if resolver is not None else None
            resolved = resolved or {}
            resolved_name = peer_name or str(resolved.get("peer_ap_name") or "").strip() or peer_mac
            metrics["resolved_peer_name"] = resolved_name
            metrics["belong_station"] = resolved.get("peer_site") or metrics.get("peer_station") or metrics.get("peer_site") or ""
            metrics["belong_section"] = resolved.get("peer_section") or metrics.get("belong_section") or ""
            metrics["belong_type"] = resolved.get("belong_type") or metrics.get("belong_type") or "unknown"
            metrics["belonging_source"] = resolved.get("belonging_source") or resolved.get("match_rule") or metrics.get("belonging_source") or ""

    def _get_peer_resolver(self) -> MeshPeerMappingService | None:
        if self._peer_resolver is not None:
            return self._peer_resolver
        site = str(getattr(self.meta, "site", "") or "")
        if not site:
            return None
        self._peer_resolver = MeshPeerMappingService(site, PathResolver())
        return self._peer_resolver

    @staticmethod
    def _extract_device_clock(text: str) -> str | None:
        for line in text.splitlines():
            match = DEVICE_CLOCK_RE.search(strip_stream_rx_prefix(line).strip())
            if match:
                return match.group(0)
        return None

    @staticmethod
    def _parse_device_clock_value(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        match = re.search(r"(?P<hms>\d{2}:\d{2}:\d{2})\s+\S+\s+\w+\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})", text)
        if match:
            for fmt in ("%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(f"{match.group('date')} {match.group('hms')}", fmt)
                except ValueError:
                    continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_iso_datetime(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("T", " "))
        except ValueError:
            return None

    def _device_record_time(self, fallback_time: datetime, block_device_clock: str | None, record_time_device: object) -> str:
        block_device_dt = self._parse_device_clock_value(block_device_clock)
        hms_match = re.search(r"\b(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\b", str(record_time_device or ""))
        if hms_match and block_device_dt is not None:
            record_time = dt_time(int(hms_match.group("h")), int(hms_match.group("m")), int(hms_match.group("s")))
            record_dt = datetime.combine(block_device_dt.date(), record_time)
            if record_dt - block_device_dt > timedelta(hours=12):
                record_dt -= timedelta(days=1)
            elif block_device_dt - record_dt > timedelta(hours=12):
                record_dt += timedelta(days=1)
            return record_dt.isoformat(sep=" ", timespec="seconds")
        record_dt = self._parse_iso_datetime(record_time_device)
        if record_dt is not None and block_device_dt is not None:
            return datetime.combine(block_device_dt.date(), record_dt.time()).isoformat(sep=" ", timespec="seconds")
        if record_dt is not None:
            return record_dt.isoformat(sep=" ", timespec="seconds")
        if block_device_dt is not None:
            return block_device_dt.isoformat(sep=" ", timespec="seconds")
        return fallback_time.isoformat(sep=" ", timespec="milliseconds")

    def _write_main_link_samples(
        self,
        block: RawBlock,
        records: list[object],
        *,
        device_clock: str | None,
    ) -> None:
        if not records:
            return
        rows: list[tuple[object, ...]] = []
        for record in records:
            metrics = record.metrics
            device_time = self._device_record_time(block.collected_at, device_clock, device_clock)
            rows.append(
                (
                    self.meta.session_id,
                    block.collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    device_time,
                    device_clock,
                    "device_clock" if device_clock else "collector_prefix",
                    record.radio,
                    record.link_state,
                    str(metrics.get("peer_name") or ""),
                    record.peer_mac_raw,
                    record.peer_mac_normalized,
                    str(metrics.get("resolved_peer_name") or metrics.get("peer_name") or record.peer_mac_raw or ""),
                    metrics.get("local_rssi_db"),
                    metrics.get("bssid") or "",
                    metrics.get("interface") or "",
                    metrics.get("belong_station") or "",
                    metrics.get("belong_section") or "",
                    metrics.get("belong_type") or "unknown",
                    metrics.get("belonging_source") or "",
                    metrics.get("online_time") or record.duration_text or record.duration_seconds,
                    "raw/mesh_link_raw.log",
                    block.offset_start,
                    block.offset_end,
                )
            )
        self.repository.insert_rows("main_link_samples", rows)

    def _write_channel_busy_records(self, block: RawBlock, rows: list[dict[str, object]], *, device_clock: str | None) -> None:
        if not rows:
            return
        values: list[tuple[object, ...]] = []
        for row in rows:
            record_time_device = row.get("sample_time")
            values.append(
                (
                    self.meta.session_id,
                    self._device_record_time(block.collected_at, device_clock, record_time_device),
                    device_clock,
                    "device_record_time" if record_time_device or device_clock else "collector_prefix",
                    row.get("radio"),
                    row.get("ctl_channel"),
                    row.get("bandwidth"),
                    row.get("record_interval"),
                    row.get("row_index") or row.get("idx") or 1,
                    row.get("ctl_busy"),
                    row.get("tx_busy"),
                    row.get("rx_busy"),
                    "raw/channel_busy_raw.log",
                    block.offset_start,
                    block.offset_end,
                )
            )
        self.repository.insert_rows("channel_busy_records", values)

    def _write_radio_statistics_samples(self, block: RawBlock, counters: dict[str, object], *, device_clock: str | None) -> None:
        if not counters:
            return
        self.repository.insert_rows(
            "radio_statistics_samples",
            [
                (
                    self.meta.session_id,
                    block.collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    device_clock,
                    "collector_prefix",
                    1,
                    key,
                    value,
                    "",
                    "raw/ap_radio_statistics_raw.log",
                    block.offset_start,
                    block.offset_end,
                )
                for key, value in counters.items()
                if isinstance(value, (int, float))
            ],
        )

    def _write_interface_rate_samples(self, block: RawBlock, rows: list[dict[str, object]], *, device_clock: str | None) -> int:
        if not rows:
            return 0
        device_time = self._device_record_time(block.collected_at, device_clock, None)
        values: list[tuple[object, ...]] = []
        for row in rows:
            interface_name = str(row.get("interface_name") or "").strip()
            if _is_excluded_xge_interface(interface_name):
                continue
            values.append(
                (
                    self.meta.session_id,
                    device_time,
                    device_clock,
                    "device_clock" if device_clock else "collector_prefix",
                    interface_name,
                    _normalize_ge_interface(interface_name),
                    row.get("direction"),
                    row.get("total_pps"),
                    row.get("broadcast_pps"),
                    row.get("multicast_pps"),
                    row.get("usage_percent"),
                    "raw/interface_rate_raw.log",
                    block.offset_start,
                    block.offset_end,
                )
            )
        if not values:
            return 0
        self.repository.insert_rows("interface_rate_samples", values)
        return len(values)

    def _parse_channel_busy(self) -> int:
        seen: set[tuple[object, ...]] = set()
        count = 0
        for block in self.splitter.split(self.raw_dir / "channel_busy_raw.log"):
            rows = [
                row
                for row in parse_channel_busy_text(block.text, collected_at=block.collected_at)
                if int(row.get("row_index") or row.get("idx") or 1) == 1
            ]
            device_clock = self._extract_device_clock(block.text)
            unique = []
            for row in rows:
                key = (
                    row.get("radio"),
                    row.get("sample_time") or block.collected_at.isoformat(),
                    row.get("row_index"),
                    row.get("ctl_busy"),
                    row.get("tx_busy"),
                    row.get("rx_busy"),
                )
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            if unique:
                self._write_channel_busy_records(block, unique, device_clock=device_clock)
                count += len(unique)
        return count

    def _parse_radio_statistics(self) -> int:
        count = 0
        for block in self.splitter.split(self.raw_dir / "ap_radio_statistics_raw.log"):
            parsed = parse_ap_radio_statistics_text(block.text)
            counters = parsed.get("counters") if isinstance(parsed, dict) else {}
            device_clock = self._extract_device_clock(block.text)
            if not counters:
                continue
            self._write_radio_statistics_samples(block, counters, device_clock=device_clock)
            count += 1
        return count

    def _parse_interface_rate(self) -> int:
        count = 0
        for block in self.splitter.split(self.raw_dir / "interface_rate_raw.log"):
            device_clock = self._extract_device_clock(block.text)
            rows = parse_interface_rate_text(block.text)
            count += self._write_interface_rate_samples(block, rows, device_clock=device_clock)
        return count

    def _parse_switch_history(self) -> int:
        path = self._find_switch_history_file()
        if not path.exists():
            return 0
        text = read_text_with_retry(path, retries=2, interval=0.05)
        collected_at = datetime.fromtimestamp(path.stat().st_mtime)
        rows = parse_switch_history_text(text, collected_at)
        if not rows:
            self._issue("switch_history_latest.log", "switch-history", "no switch-history rows parsed", text[:500])
            return 0
        resolver = ApRadioMappingService(str(self.meta.site or ""), self._path_resolver())
        enriched_rows = [self._enrich_switch_history_row(row, resolver) for row in rows]
        self._write_switch_history_events(enriched_rows, collected_at, path)
        return len(enriched_rows)

    def _write_switch_history_events(self, rows: list[dict[str, object]], snapshot_collector_time: datetime, path: Path) -> None:
        if not rows:
            return
        rel_path = f"raw/{path.name}" if path.parent == self.raw_dir else str(path)
        values: list[tuple[object, ...]] = []
        for row in rows:
            values.append(
                (
                    self.meta.session_id,
                    snapshot_collector_time.isoformat(sep=" ", timespec="milliseconds"),
                    None,
                    row.get("switch_time"),
                    row.get("switch_time"),
                    "device_clock",
                    int(row.get("radio") or 1),
                    row.get("from_peer_name") or "-",
                    row.get("from_peer_mac") or "-",
                    row.get("out_rssi"),
                    row.get("from_peer_site") or "-",
                    row.get("from_peer_section") or "-",
                    row.get("to_peer_name") or "-",
                    row.get("to_peer_mac") or "-",
                    row.get("in_rssi"),
                    row.get("to_peer_site") or "-",
                    row.get("to_peer_section") or "-",
                    row.get("peer_quantity"),
                    row.get("link_quantity"),
                    row.get("switch_reason_code"),
                    row.get("reason") or row.get("role") or "-",
                    row.get("active_time") or "-",
                    rel_path,
                    0,
                    0,
                )
            )
        self.repository.insert_rows("switch_history_events", values)

    def _enrich_switch_history_row(self, row: dict[str, object], resolver: ApRadioMappingService) -> dict[str, object]:
        enriched = dict(row)
        from_info = self._resolve_switch_endpoint(str(row.get("from_peer_name") or ""), str(row.get("from_peer_mac") or ""), False, resolver)
        to_info = self._resolve_switch_endpoint(str(row.get("to_peer_name") or ""), str(row.get("to_peer_mac") or ""), False, resolver)
        if not enriched.get("from_peer_name") and from_info.get("ap_name"):
            enriched["from_peer_name"] = from_info["ap_name"]
        if not enriched.get("to_peer_name") and to_info.get("ap_name"):
            enriched["to_peer_name"] = to_info["ap_name"]
        enriched["from_peer_site"] = enriched.get("from_peer_site") or from_info["station"]
        enriched["to_peer_site"] = enriched.get("to_peer_site") or to_info["station"]
        enriched["from_peer_section"] = enriched.get("from_peer_section") or from_info["section"]
        enriched["to_peer_section"] = enriched.get("to_peer_section") or to_info["section"]
        enriched["from_belong_type"] = enriched.get("from_belong_type") or from_info["belong_type"]
        enriched["to_belong_type"] = enriched.get("to_belong_type") or to_info["belong_type"]
        enriched["from_resolve_rule"] = enriched.get("from_resolve_rule") or from_info["resolve_rule"]
        enriched["to_resolve_rule"] = enriched.get("to_resolve_rule") or to_info["resolve_rule"]
        return enriched

    def _parse_terminal_monitor_switch_logs(self) -> int:
        path = self.raw_dir / "terminal_monitor_raw.log"
        if not path.exists():
            self._issue("terminal_monitor_raw.log", "terminal-monitor", "当前会话没有 terminal_monitor_raw.log，无法解析 WMESH 主链路切换日志。", "")
            return 0
        text = read_text_with_retry(path, retries=2, interval=0.05)
        if "WMESH/5/MESH_ACTIVELINK_SWITCH" not in text:
            self._issue("terminal_monitor_raw.log", "terminal-monitor", "terminal_monitor_raw.log 中未发现 WMESH/5/MESH_ACTIVELINK_SWITCH。", "")
            return 0
        rows = parse_active_link_switch_logs(text, device_name=str(self.meta.device_name or ""), fallback_year=self.meta.started_at.year)
        if not rows:
            self._issue("terminal_monitor_raw.log", "terminal-monitor", "WMESH 主链路切换日志格式未匹配。", text[:500])
            return 0
        resolver = ApRadioMappingService(str(self.meta.site or ""), self._path_resolver())
        enriched = [self._enrich_switch_log(row, resolver) for row in rows]
        self._write_active_link_switch_logs(enriched, "terminal_monitor")
        return len(enriched)

    def _enrich_switch_log(self, row: ActiveLinkSwitchLog, resolver: ApRadioMappingService) -> ActiveLinkSwitchLog:
        from_info = self._resolve_switch_endpoint(row.from_peer_name, row.from_peer_mac, row.from_is_empty_link, resolver)
        to_info = self._resolve_switch_endpoint(row.to_peer_name, row.to_peer_mac, row.to_is_empty_link, resolver)
        return ActiveLinkSwitchLog(
            log_time=row.log_time,
            device_name=row.device_name,
            raw_line=row.raw_line,
            from_peer_name=from_info["ap_name"] or row.from_peer_name or row.from_peer_mac,
            from_peer_mac=row.from_peer_mac,
            from_peer_rssi=row.from_peer_rssi,
            to_peer_name=to_info["ap_name"] or row.to_peer_name or row.to_peer_mac,
            to_peer_mac=row.to_peer_mac,
            to_peer_rssi=row.to_peer_rssi,
            peer_quantity=row.peer_quantity,
            link_quantity=row.link_quantity,
            switch_reason_code=row.switch_reason_code,
            switch_reason_text=row.switch_reason_text,
            from_station=from_info["station"],
            to_station=to_info["station"],
            from_section=from_info["section"],
            to_section=to_info["section"],
            from_belong_type=from_info["belong_type"],
            to_belong_type=to_info["belong_type"],
            from_serial_number=from_info["serial_number"],
            to_serial_number=to_info["serial_number"],
            from_resolve_rule=from_info["resolve_rule"],
            to_resolve_rule=to_info["resolve_rule"],
            source=row.source,
            from_is_empty_link=row.from_is_empty_link,
            to_is_empty_link=row.to_is_empty_link,
        )

    def _resolve_switch_endpoint(self, peer_name: str, radio_mac: str, is_empty_link: bool, resolver: ApRadioMappingService) -> dict[str, str]:
        if is_empty_link:
            return {"ap_name": "", "station": "-", "section": "-", "belong_type": "empty", "serial_number": "-", "resolve_rule": "empty_link"}
        for candidate in (radio_mac, peer_name):
            text = str(candidate or "").strip()
            if not text or text == "0000-0000-0000":
                continue
            try:
                resolved = resolver.resolve_peer_mac(text, peer_name=peer_name or None)
            except Exception:
                continue
            if str(resolved.source or "").lower() == "unresolved":
                continue
            if any((resolved.ap_name, resolved.site, resolved.section, resolved.serial_number, resolved.radio_mac)):
                return {
                    "ap_name": str(resolved.ap_name or ""),
                    "station": str(resolved.site or "-"),
                    "section": str(resolved.section or "-"),
                    "belong_type": str(resolved.belong_type or "unknown"),
                    "serial_number": str(resolved.serial_number or "-"),
                    "resolve_rule": str(resolved.source or ""),
                }
        return {"ap_name": "", "station": "-", "section": "-", "belong_type": "unknown", "serial_number": "-", "resolve_rule": "unresolved"}

    @staticmethod
    def _radio_statistics_summary(parsed: dict[str, object]) -> str:
        counters = parsed.get("counters") if isinstance(parsed, dict) else {}
        if not isinstance(counters, dict) or not counters:
            return "display ar5drv statistics | no counters parsed"
        keys = ("TxFrameAllCnt", "RxFrameAllCnt", "TxRetryFrmCnt", "TxErrFrmCnt", "TxDiscardFrmCnt")
        parts = [f"{key}={counters.get(key)}" for key in keys if counters.get(key) is not None]
        return "display ar5drv statistics | " + " ".join(parts)

    def _write_active_link_switch_logs(self, rows: list[ActiveLinkSwitchLog], source: str) -> None:
        _ = source
        self.repository.replace_switch_realtime_events(
            self.meta.session_id,
            [
                (
                        self.meta.session_id,
                        row.log_time.isoformat(sep=" ", timespec="milliseconds"),
                        "device_event_time",
                        row.device_name,
                        "空链路" if row.from_is_empty_link else row.from_peer_name,
                        None if row.from_is_empty_link else row.from_peer_mac,
                        None if row.from_is_empty_link else row.from_peer_rssi,
                        row.from_station,
                        row.from_section,
                        "空链路" if row.to_is_empty_link else row.to_peer_name,
                        None if row.to_is_empty_link else row.to_peer_mac,
                        None if row.to_is_empty_link else row.to_peer_rssi,
                        row.to_station,
                        row.to_section,
                        row.peer_quantity,
                        row.link_quantity,
                        row.switch_reason_code,
                        row.switch_reason_text,
                        "raw/terminal_monitor_raw.log",
                        0,
                        0,
                )
                for row in rows
            ],
        )

    def _path_resolver(self):
        from netconsole.core.paths import PathResolver

        resolved = self.session_dir.resolve()
        parts = resolved.parts
        if "data" in parts:
            data_index = parts.index("data")
            if data_index > 0:
                return PathResolver(Path(*parts[:data_index]))
        return PathResolver()

    def _find_switch_history_file(self) -> Path:
        preferred = self.raw_dir / "switch_history_latest.log"
        if preferred.exists() and preferred.stat().st_size > 0:
            return preferred
        candidates: list[Path] = []
        for path in self.raw_dir.iterdir() if self.raw_dir.exists() else []:
            name = path.name.casefold()
            if path == preferred or path.stat().st_size <= 0:
                continue
            if path.is_file() and ("switch-history" in name or "switch_history" in name or "mesh-link switch-history" in name or "主链路切换历史" in name):
                candidates.append(path)
        return sorted(candidates, key=lambda item: item.name.casefold())[0] if candidates else preferred

    def _parse_fping(self) -> int:
        v5_path = self.raw_dir / "fping_v5_samples.jsonl"
        if v5_path.exists():
            count = self._parse_fping_v5_jsonl(v5_path)
            if count > 0:
                return count
        raw_v5_path = self.raw_dir / "fping_v5_raw.log"
        if raw_v5_path.exists():
            count = self._parse_fping_v5_raw_log(raw_v5_path)
            if count > 0:
                return count
        legacy_path = self.raw_dir / "Fping.txt"
        if not legacy_path.exists():
            self._issue("fping", "fping", "fping v5 samples/raw log and legacy Fping.txt were not found", "")
            return 0
        try:
            text = read_text_with_retry(legacy_path, retries=10, interval=0.3)
        except PermissionError as exc:
            self._issue("Fping.txt", "fping", f"legacy Fping.txt is locked; ping parsing was skipped: {exc}", "", severity="ERROR")
            return 0
        rows = parse_fping_lines(text.splitlines(), self.meta.started_at, default_target=str(self.meta.fping.get("target") or ""))
        if rows:
            for row in rows:
                row["raw_line"] = self._fping_sample_summary({"target": row.get("target_ip"), "seq": row.get("seq"), "ok": row.get("success"), "rtt_ms": row.get("latency_ms")})
            self._write_fping_sampling_tables(rows)
        return len(rows)

    def _parse_fping_v5_jsonl(self, path: Path) -> int:
        return self._parse_fping_v5_lines(path, read_text_with_fallback(path).splitlines())

    def _parse_fping_v5_raw_log(self, path: Path) -> int:
        try:
            lines = read_text_with_retry(path, retries=10, interval=0.3).splitlines()
        except PermissionError as exc:
            self._issue("fping_v5_raw.log", "fping", f"fping_v5_raw.log is locked; ping parsing was skipped: {exc}", "", severity="ERROR")
            return 0
        return self._parse_fping_v5_lines(path, lines)

    def _parse_fping_v5_lines(self, path: Path, lines: list[str]) -> int:
        rows: list[dict[str, object]] = []
        fping = self.meta.fping
        timeout_ms = int(fping.get("loss_threshold_ms") or fping.get("timeout_ms") or 100)
        for line in lines:
            raw_line = line.strip()
            if not raw_line:
                continue
            stamp = ""
            payload_text = raw_line
            match = FPING_V5_RAW_JSON_RE.match(raw_line)
            if match:
                stamp = match.group("stamp")
                payload_text = match.group("payload")
            try:
                sample = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            if not isinstance(sample, dict):
                continue
            normalized = self._normalize_fping_v5_sample(sample, payload_text, stamp, timeout_ms)
            if normalized is None:
                continue
            target_ip = str(normalized.get("target") or fping.get("target") or "")
            row = {
                "collected_at": normalized.get("ts") or self.meta.started_at.isoformat(sep=" ", timespec="milliseconds"),
                "seq": normalized.get("seq"),
                "target_ip": target_ip,
                "success": bool(normalized.get("ok")),
                "latency_ms": normalized.get("rtt_ms"),
                "ttl": None,
                "bytes": normalized.get("size"),
                "raw_line": self._fping_sample_summary(normalized),
            }
            rows.append(row)
        if rows:
            self._write_fping_sampling_tables(rows)
        return len(rows)

    @staticmethod
    def _fping_sample_summary(sample: dict[str, object]) -> str:
        target = str(sample.get("target") or "")
        seq = sample.get("seq")
        if sample.get("ok"):
            return f"fping {target} seq={seq} rtt={sample.get('rtt_ms')}ms"
        return f"fping {target} seq={seq} timeout"

    def _write_fping_sampling_tables(self, rows: list[dict[str, object]]) -> None:
        sample_values: list[tuple[object, ...]] = []
        buckets: dict[tuple[str, str], dict[str, object]] = {}
        sync_samples = self._load_time_sync_samples()
        for row in rows:
            local_time = str(row.get("collected_at") or "")
            target_ip = str(row.get("target_ip") or "")
            success = 1 if row.get("success") else 0
            latency = row.get("latency_ms")
            loss_percent = 0.0 if success else 100.0
            local_dt = self._parse_iso_datetime(local_time) or self.meta.started_at
            device_dt, clock_offset_ms, offset_source = estimate_device_time_from_local(local_dt, sync_samples)
            device_time = device_dt.isoformat(sep=" ", timespec="milliseconds") if device_dt is not None else None
            local_time = local_dt.isoformat(sep=" ", timespec="milliseconds")
            sample_values.append(
                (
                    self.meta.session_id,
                    local_time,
                    local_time,
                    device_time,
                    clock_offset_ms,
                    offset_source,
                    "local_tool",
                    target_ip,
                    "",
                    row.get("seq"),
                    success,
                    latency,
                    loss_percent,
                    "OK" if success else "TIMEOUT",
                )
            )
            local_bucket_time = local_dt.replace(microsecond=0).isoformat(sep=" ", timespec="seconds")
            device_bucket_time = device_dt.replace(microsecond=0).isoformat(sep=" ", timespec="seconds") if device_dt is not None else None
            bucket_time = device_bucket_time or local_bucket_time
            bucket = buckets.setdefault(
                (bucket_time, target_ip),
                {
                    "local_bucket_time": local_bucket_time,
                    "device_bucket_time": device_bucket_time,
                    "offsets": [],
                    "sent": 0,
                    "received": 0,
                    "latencies": [],
                },
            )
            if str(local_bucket_time) < str(bucket.get("local_bucket_time") or local_bucket_time):
                bucket["local_bucket_time"] = local_bucket_time
            if device_bucket_time is not None:
                bucket["device_bucket_time"] = device_bucket_time
            if clock_offset_ms is not None:
                bucket["offsets"].append(float(clock_offset_ms))  # type: ignore[union-attr]
            bucket["sent"] = int(bucket["sent"]) + 1
            bucket["received"] = int(bucket["received"]) + success
            if success and latency is not None:
                bucket["latencies"].append(float(latency))  # type: ignore[union-attr]
        summary_values: list[tuple[object, ...]] = []
        for (bucket_time, target_ip), item in sorted(buckets.items()):
            sent = int(item["sent"])
            received = int(item["received"])
            lost = sent - received
            latencies = list(item["latencies"])  # type: ignore[arg-type]
            avg_latency = (sum(latencies) / len(latencies)) if latencies else None
            min_latency = min(latencies) if latencies else None
            max_latency = max(latencies) if latencies else None
            jitter = (max_latency - min_latency) if min_latency is not None and max_latency is not None else None
            offsets = list(item.get("offsets") or [])
            avg_offset = (sum(offsets) / len(offsets)) if offsets else None
            summary_values.append(
                (
                    self.meta.session_id,
                    bucket_time,
                    item.get("local_bucket_time"),
                    item.get("device_bucket_time"),
                    avg_offset,
                    target_ip,
                    "",
                    sent,
                    received,
                    lost,
                    (lost / sent * 100.0) if sent else 0.0,
                    avg_latency,
                    min_latency,
                    max_latency,
                    jitter,
                    "OK" if lost == 0 else "LOSS",
                )
            )
        self.repository.insert_fping_sampling_rows(sample_values, summary_values)

    def _load_time_sync_samples(self) -> list[TimeSyncSample]:
        if not self.db_path.exists():
            return []
        rows = self.repository.load_time_sync_rows(self.meta.session_id)
        samples: list[TimeSyncSample] = []
        for collector_time, device_time, offset_ms, source in rows:
            collector_dt = self._parse_iso_datetime(collector_time)
            device_dt = self._parse_iso_datetime(device_time)
            if collector_dt is None or device_dt is None:
                continue
            try:
                offset = float(offset_ms)
            except (TypeError, ValueError):
                offset = (device_dt - collector_dt).total_seconds() * 1000.0
            samples.append(TimeSyncSample(collector_dt, device_dt, offset, str(source or "mesh_link_display_clock")))
        return samples

    def _iperf_run_metadata(self) -> dict[str, object]:
        config = self.meta.iperf if isinstance(self.meta.iperf, dict) else {}
        protocol = str(config.get("protocol") or "").upper()
        server_ip = str(config.get("server_ip") or "")
        direction = str(config.get("direction") or "").lower()
        target_bandwidth = str(config.get("target_bandwidth") or "").strip() or None
        if protocol == "TCP":
            tcp_rate_limit = _float_or_none(config.get("tcp_rate_limit_mbps"))
            if tcp_rate_limit is None and config.get("tcp_pacing_enabled"):
                tcp_rate_limit = _float_or_none(config.get("tcp_pacing_mbps"))
            target_bandwidth = f"{tcp_rate_limit:g}M" if tcp_rate_limit is not None and tcp_rate_limit > 0 else None
        elif protocol == "UDP" and not target_bandwidth:
            udp_bitrate = _float_or_none(config.get("udp_bitrate_mbps"))
            target_bandwidth = f"{udp_bitrate:g}M" if udp_bitrate is not None and udp_bitrate > 0 else None
        try:
            port = int(config.get("port")) if config.get("port") not in (None, "") else None
        except (TypeError, ValueError):
            port = None
        try:
            parallel = int(config.get("parallel")) if config.get("parallel") not in (None, "") else None
        except (TypeError, ValueError):
            parallel = None
        return {
            "protocol": protocol,
            "server_ip": server_ip,
            "port": port,
            "direction": direction,
            "parallel": parallel,
            "target_bandwidth": target_bandwidth,
        }

    def _normalize_fping_v5_sample(self, sample: dict[str, object], payload_text: str, stamp: str, timeout_ms: int) -> dict[str, object] | None:
        raw_type = sample.get("raw_type")
        if raw_type is not None and raw_type not in {"resp", "timeout"}:
            return None
        if raw_type is None and not any(key in sample for key in ("ok", "rtt_ms", "target", "seq", "error", "timeout_ms", "resp", "timeout")):
            return None
        if "resp" in sample or "timeout" in sample:
            parsed = parse_fping_v5_json_line(payload_text, stamp or self.meta.started_at.isoformat(sep=" ", timespec="milliseconds"), timeout_ms)
            if parsed is None or parsed.raw_type not in {"resp", "timeout"}:
                return None
            return {
                "ts": parsed.ts,
                "target": parsed.target,
                "seq": parsed.seq,
                "ok": parsed.ok,
                "rtt_ms": parsed.rtt_ms,
                "size": parsed.size,
                "raw": parsed.raw,
            }
        return {
            "ts": sample.get("ts") or stamp,
            "target": sample.get("target"),
            "seq": sample.get("seq"),
            "ok": sample.get("ok"),
            "rtt_ms": sample.get("rtt_ms"),
            "size": sample.get("size"),
            "raw": sample.get("raw") or sample,
        }

    def _parse_iperf(self) -> int:
        candidates = (
            self.raw_dir / "iperf3.json",
            self.raw_dir / "iperf_client_raw.json",
            self.raw_dir / "iperf_client_raw.log",
        )
        path: Path | None = None
        rows: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []
        for candidate in candidates:
            if not candidate.exists():
                continue
            lines = read_iperf_text(candidate).splitlines()
            candidate_rows = parse_iperf_lines(lines, self.meta.started_at)
            candidate_errors = parse_iperf_error_lines(lines, self.meta.started_at)
            if candidate_rows or candidate_errors:
                path = candidate
                rows = candidate_rows
                errors = candidate_errors
                break
        self._last_iperf_error_count = len(errors)
        zero_summary = summarize_iperf_zero_samples(rows, errors)
        self._last_iperf_zero_sample_count = zero_summary["iperf_zero_sample_count"]
        self._last_iperf_isolated_gap_count = zero_summary["iperf_isolated_gap_count"]
        self._last_iperf_stall_count = zero_summary["iperf_stall_count"]
        if path is None:
            return 0
        if errors:
            self._write_iperf_error_events(errors, path)
            for error in errors:
                self._issue(path.name, "iperf", str(error.get("error_message") or "iperf error"), str(error.get("raw_line") or ""), severity="ERROR")
        if not rows:
            return 0
        run_id = f"parsed_{self.meta.session_id}"
        command = ["iperf3", "parsed"]
        run_metadata = self._iperf_run_metadata()
        self.repository.start_iperf_run(
            run_id,
            mode="client",
            command=command,
            log_file=path,
            started_at=self.meta.started_at,
            session_id=self.meta.session_id,
            device_id=self.meta.device_id,
            **run_metadata,
        )
        sync_samples = self._load_time_sync_samples()
        for row in rows:
            local_time = self._parse_iso_datetime(row.get("interval_center_time") or row.get("collector_time")) or self.meta.started_at
            device_dt, clock_offset_ms, offset_source = estimate_device_time_from_local(local_time, sync_samples)
            device_time = device_dt.isoformat(sep=" ", timespec="milliseconds") if device_dt is not None else None
            row["device_interval_center_time"] = device_time
            row["device_aligned_time"] = device_time
            row["clock_offset_ms"] = clock_offset_ms
            row["offset_source"] = offset_source
            row["time_source"] = "mr_device_clock_aligned" if device_dt is not None else "local_tool"
            row["raw_line"] = self._iperf_interval_summary(row)
            self.repository.append_iperf_interval(run_id, row, self.meta.session_id)
        self.repository.finish_iperf_run(run_id, "PARSED")
        return len(rows)

    @staticmethod
    def _iperf_interval_summary(row: dict[str, object]) -> str:
        return (
            f"iperf interval {row.get('interval_start_sec')}-{row.get('interval_end_sec')}s "
            f"bitrate={row.get('bitrate_mbps')}Mbps retrans={row.get('retransmits')} "
            f"loss={row.get('loss_percent')}"
        )

    def _write_iperf_error_events(self, errors: list[dict[str, object]], path: Path) -> None:
        self.repository.insert_rows(
            "analysis_events",
            [
                (
                    self.meta.session_id,
                    str(error.get("collector_time") or self.meta.started_at.isoformat(sep=" ", timespec="milliseconds")),
                    "IPERF_ERROR",
                    "ERROR",
                    str(error.get("error_message") or "iperf error"),
                    json.dumps({"raw_file": path.name, **error}, ensure_ascii=False, default=str),
                    path.name,
                    None,
                    None,
                )
                for error in errors
            ],
        )

    def _ensure_tables(self) -> None:
        self.repository.initialize()

    def _reset_parsed_tables(self) -> None:
        self.repository.reset_parsed_tables()

    def _discard_existing_database(self) -> None:
        self.repository.discard_existing_database()

    def _drop_all_tables(self) -> None:
        self.repository.drop_all_tables()

    def _issue(self, raw_file: str, issue_type: str, message: str, raw_text: str, severity: str = "WARNING") -> None:
        self.repository.append_issue(
            self.meta.session_id,
            raw_file,
            issue_type,
            severity,
            message,
            raw_text,
        )

    def _issue_count(self) -> int:
        return self.repository.issue_count()

    @staticmethod
    def _has_any_valid_data(summary: OnlineMrParseSummary) -> bool:
        return any(
            value > 0
            for value in (
                summary.mesh_samples,
                summary.channel_samples,
                summary.radio_stats_samples,
                summary.interface_samples,
                summary.switch_history_samples,
                summary.ping_samples,
                summary.iperf_samples,
                summary.iperf_error_count,
            )
        )

    def _insert_normal_data_segment(self, summary: OnlineMrParseSummary) -> int:
        start = getattr(self.meta, "started_at", datetime.now())
        end = getattr(self.meta, "ended_at", None) or start
        metrics = self._normal_fallback_metrics()
        details = {
            "source": "parsed_data_fallback",
            "status": "正常",
            "mesh_samples": summary.mesh_samples,
            "channel_samples": summary.channel_samples,
            "radio_stats_samples": summary.radio_stats_samples,
            "interface_samples": summary.interface_samples,
            "switch_history_samples": summary.switch_history_samples,
            "ping_samples": summary.ping_samples,
            "iperf_samples": summary.iperf_samples,
            "interface_rate": metrics["interface_rate"],
            "ap_radio_statistics": metrics["ap_radio_statistics"],
        }
        self.repository.insert_active_segment(
            (
                self.meta.session_id,
                None,
                metrics["active_peer_mac"] or "",
                start.isoformat(sep=" ", timespec="milliseconds"),
                end.isoformat(sep=" ", timespec="milliseconds"),
                summary.mesh_samples
                + summary.channel_samples
                + summary.radio_stats_samples
                + summary.interface_samples
                + summary.switch_history_samples
                + summary.ping_samples
                + summary.iperf_samples,
                metrics["avg_mr_rssi"],
                metrics["min_mr_rssi"],
                metrics["max_mr_rssi"],
                "NORMAL",
                json.dumps(details, ensure_ascii=False),
            ),
            (
                metrics["ping_sent"],
                metrics["ping_success"],
                metrics["ping_lost"],
                metrics["ping_loss_percent"],
                metrics["avg_latency_ms"],
                metrics["max_latency_ms"],
                metrics["iperf_sample_count"],
                metrics["avg_mbps"],
                metrics["min_mbps"],
                metrics["max_mbps"],
                metrics["p95_mbps"],
                metrics["total_retransmits"],
                metrics["avg_tx_busy"],
                metrics["max_tx_busy"],
                metrics["avg_rx_busy"],
                metrics["max_rx_busy"],
            ),
        )
        return 1

    def _normal_fallback_metrics(self) -> dict[str, object]:
        return self.repository.normal_fallback_metrics()

class OnlineMrTimelineFusionService:
    def __init__(self, db_path: Path, session_id: str) -> None:
        self.db_path = Path(db_path)
        self.session_id = session_id
        self.repository = OnlineMrDiagnosisRepository(self.db_path)

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
                current = {
                    **sample,
                    "key": key,
                    "start_time": sample["collected_at"],
                    "end_time": sample["collected_at"],
                    "rssis": [],
                }
            current["end_time"] = sample["collected_at"]
            current["sample_count"] = int(current.get("sample_count") or 0) + 1
            if sample.get("mr_rssi") is not None:
                current["rssis"].append(int(sample["mr_rssi"]))
        if current is not None:
            segments.append(current)
        return self.repository.insert_timeline_segments(self.session_id, segments)

    def _active_samples(self) -> list[dict[str, object]]:
        rows = self.repository.load_main_link_rows(self.session_id)
        grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(
                (str(row["collector_time"]), int(row["radio"] or 1)),
                [],
            ).append(row)
        samples: list[dict[str, object]] = []
        for (collected_at, radio), group in sorted(grouped.items()):
            active = [row for row in group if str(row["link_state"]).upper() == "ACTIVE"]
            if len(active) == 1:
                event_type = "ACTIVE"
                peer = active[0]["peer_mac_normalized"] or active[0]["peer_mac"]
                mr_rssi = active[0]["mr_rssi"]
            elif not active:
                event_type = "NO_ACTIVE"
                peer = ""
                mr_rssi = None
            else:
                event_type = "MULTI_ACTIVE"
                peer = ",".join(
                    str(row["peer_mac_normalized"] or row["peer_mac"])
                    for row in active
                )
                mr_rssi = None
            samples.append(
                {
                    "collected_at": collected_at,
                    "radio": radio,
                    "event_type": event_type,
                    "active_peer_mac": peer,
                    "mr_rssi": mr_rssi,
                    "sample_count": 0,
                }
            )
        return samples
