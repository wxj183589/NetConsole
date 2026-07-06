from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from statistics import quantiles


NETCONSOLE_LOG_PREFIX_RE = re.compile(
    r"^\[(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\]\s*(?P<rest>.*)$"
)
COMPACT_IPERF_PREFIX_RE = re.compile(
    r"^IPERF\s+\[(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\]\s+\[(?P<mode>[^\]]+)\]\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

IPERF_ERROR_PATTERNS: tuple[tuple[str, str], ...] = (
    ("server_busy", "server is busy running a test"),
    ("unable_to_connect", "unable to connect"),
    ("connection_refused", "connection refused"),
    ("connection_reset", "connection reset"),
    ("timed_out", "timed out"),
    ("interrupted", "interrupt"),
)


INTERVAL_RE = re.compile(
    r"^\s*\[\s*\d+\]\s+"
    r"(?P<start>\d+(?:\.\d+)?)\s*-\s*(?P<end>\d+(?:\.\d+)?)\s+sec\s+"
    r"(?P<transfer>\d+(?:\.\d+)?)\s+(?P<transfer_unit>[KMG]Bytes|Bytes)\s+"
    r"(?P<bitrate>\d+(?:\.\d+)?)\s+(?P<bitrate_unit>[KMG]bits/sec|bits/sec)"
    r"(?:\s+(?P<retransmits>\d+))?"
    r"(?:\s+(?P<cwnd>\d+(?:\.\d+)?\s+[KMG]Bytes|Bytes))?"
    r".*?(?P<role>sender|receiver)?\s*$",
    re.IGNORECASE,
)

UDP_RE = re.compile(
    r"(?P<jitter>\d+(?:\.\d+)?)\s+ms\s+"
    r"(?P<lost>\d+)\s*/\s*(?P<total>\d+)\s+\((?P<loss>\d+(?:\.\d+)?)%\)",
    re.IGNORECASE,
)


def read_iperf_text(path: Path) -> str:
    data = Path(path).read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    return data.decode("utf-8", errors="replace")


def split_iperf_log_prefix(line: str) -> tuple[datetime | None, str]:
    """Return NetConsole collector timestamp and the original iperf payload."""

    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None, ""
    if text.casefold().startswith("iperf:"):
        text = text.split(":", 1)[1].strip()
    compact = COMPACT_IPERF_PREFIX_RE.match(text)
    if compact:
        try:
            collector_time = datetime.fromisoformat(compact.group("stamp").replace("T", " "))
        except ValueError:
            return None, line
        return collector_time, compact.group("rest").lstrip()
    match = NETCONSOLE_LOG_PREFIX_RE.match(text)
    if not match:
        return None, text
    stamp = match.group("stamp").replace("T", " ")
    try:
        collector_time = datetime.fromisoformat(stamp)
    except ValueError:
        return None, line
    rest = match.group("rest").lstrip()
    while rest.startswith("["):
        end = rest.find("]")
        if end <= 0:
            break
        token = rest[1:end]
        if "=" not in token:
            break
        rest = rest[end + 1 :].lstrip()
    return collector_time, rest


def format_iperf_log_line(timestamp: datetime, raw_line: str, context: dict[str, object] | None = None) -> str:
    mode = str((context or {}).get("mode") or "client").strip() or "client"
    raw_text = str(raw_line or "").rstrip()
    error_code = _iperf_error_code(raw_text)
    if error_code:
        return f"IPERF [{timestamp.isoformat(sep=' ', timespec='milliseconds')}] [{mode}] ERROR {error_code}: {raw_text}".rstrip()
    return f"IPERF [{timestamp.isoformat(sep=' ', timespec='milliseconds')}] [{mode}] {raw_text}".rstrip()


def format_iperf_log_header(context: dict[str, object], started_at: datetime) -> list[str]:
    fields: list[tuple[str, object]] = [
        ("NETCONSOLE_IPERF_LOG_VERSION", 2),
        ("run_id", context.get("run_id")),
        ("session_id", context.get("session_id")),
        ("device_id", context.get("device_id")),
        ("device_name", context.get("device_name")),
        ("batch_key_hash", context.get("batch_key_hash")),
        ("batch_key", context.get("batch_key")),
        ("mode", context.get("mode")),
        ("server", context.get("server")),
        ("port", context.get("port")),
        ("protocol", context.get("protocol")),
        ("direction", context.get("direction")),
        ("bandwidth", context.get("bandwidth")),
        ("tcp_block_size", context.get("tcp_block_size")),
        ("duration_mode", context.get("duration_mode")),
        ("duration_seconds", context.get("duration_seconds")),
        ("protection_duration_seconds", context.get("protection_duration_seconds")),
        ("stop_policy", context.get("stop_policy")),
        ("started_at", started_at.isoformat(sep=" ", timespec="milliseconds")),
        ("command", context.get("command")),
    ]
    return [f"# {key}={value}" for key, value in fields if value not in (None, "")]


def format_iperf_log_footer(finished_at: datetime, status: str, return_code: int | None, error_code: str = "") -> list[str]:
    lines = [
        f"# finished_at={finished_at.isoformat(sep=' ', timespec='milliseconds')}",
        f"# status={status}",
    ]
    if return_code is not None:
        lines.append(f"# return_code={return_code}")
    if error_code:
        lines.append(f"# error={error_code}")
    return lines


def parse_iperf_error_line(line: str, started_at: datetime | None = None) -> dict[str, object] | None:
    collector_time, payload_line = split_iperf_log_prefix(line)
    message = _strip_compact_error_prefix(payload_line)
    lowered = message.casefold()
    if "iperf3: error -" not in lowered and not any(text in lowered for _code, text in IPERF_ERROR_PATTERNS):
        return None
    error_code = "iperf_error"
    for code, text in IPERF_ERROR_PATTERNS:
        if text in lowered:
            error_code = code
            break
    timestamp = collector_time or started_at or datetime.now()
    return {
        "event_type": "error",
        "collector_time": timestamp.isoformat(sep=" ", timespec="milliseconds"),
        "error_message": message.strip(),
        "error_code": error_code,
        "raw_line": line,
    }


def parse_iperf_error_lines(lines: list[str], started_at: datetime | None = None) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in lines:
        event = parse_iperf_error_line(line, started_at)
        if event:
            events.append(event)
    return events


def _iperf_error_code(text: str) -> str:
    lowered = str(text or "").casefold()
    if "iperf3: error -" not in lowered and not any(pattern in lowered for _code, pattern in IPERF_ERROR_PATTERNS):
        return ""
    for code, pattern in IPERF_ERROR_PATTERNS:
        if pattern in lowered:
            return code
    return "iperf_error"


def _strip_compact_error_prefix(text: str) -> str:
    match = re.match(r"^ERROR(?:\s+(?P<code>[\w-]+))?:\s*(?P<message>.*)$", str(text or "").strip(), re.IGNORECASE)
    return match.group("message") if match else text


def transfer_to_bytes(value: float, unit: str) -> float:
    factors = {"bytes": 1, "kbytes": 1024, "mbytes": 1024**2, "gbytes": 1024**3}
    return value * factors.get(unit.lower(), 1)


def bitrate_to_mbps(value: float, unit: str) -> float:
    factors = {"bits/sec": 1 / 1_000_000, "kbits/sec": 1 / 1000, "mbits/sec": 1, "gbits/sec": 1000}
    return value * factors.get(unit.lower(), 1)


def parse_iperf_line(line: str, started_at: datetime | None = None, collector_time: datetime | None = None) -> dict[str, object] | None:
    prefix_time, payload_line = split_iperf_log_prefix(line)
    match = INTERVAL_RE.search(payload_line)
    if not match:
        return None
    start = float(match.group("start"))
    end = float(match.group("end"))
    bitrate_mbps = bitrate_to_mbps(float(match.group("bitrate")), match.group("bitrate_unit"))
    transfer_value = float(match.group("transfer"))
    transfer_unit = match.group("transfer_unit")
    row: dict[str, object] = {
        "interval_start_sec": start,
        "interval_end_sec": end,
        "collector_time": (prefix_time or collector_time or datetime.now()).isoformat(sep=" ", timespec="milliseconds"),
        "transfer_value": transfer_value,
        "transfer_unit": transfer_unit,
        "transfer_bytes": transfer_to_bytes(transfer_value, transfer_unit),
        "bitrate_value": float(match.group("bitrate")),
        "bitrate_unit": match.group("bitrate_unit"),
        "bitrate_mbps": bitrate_mbps,
        "retransmits": int(match.group("retransmits") or 0),
        "cwnd": match.group("cwnd") or "",
        "role": (match.group("role") or "interval").lower(),
        "raw_line": line,
        "raw_iperf_line": payload_line,
        "zero_sample": False,
        "zero_sample_type": "",
        "zero_sample_label": "",
    }
    if _is_zero_iperf_sample(row):
        row["zero_sample"] = True
        row["zero_sample_type"] = "unknown"
        row["zero_sample_label"] = "IPERF零带宽样本"
    udp = UDP_RE.search(payload_line)
    if udp:
        row.update(
            {
                "jitter_ms": float(udp.group("jitter")),
                "lost_packets": int(udp.group("lost")),
                "total_packets": int(udp.group("total")),
                "loss_percent": float(udp.group("loss")),
            }
        )
    if started_at is not None:
        center = started_at + timedelta(seconds=(start + end) / 2)
        row["interval_center_time"] = center.isoformat(sep=" ", timespec="milliseconds")
    return row


def parse_iperf_lines(lines: list[str], started_at: datetime | None = None) -> list[dict[str, object]]:
    text = "\n".join(lines).strip()
    if text.startswith("{"):
        rows = parse_iperf_json_text(text, started_at)
        if rows:
            return rows
    rows: list[dict[str, object]] = []
    for line in lines:
        row = parse_iperf_line(line, started_at)
        if row:
            rows.append(row)
    annotate_iperf_zero_samples(rows, parse_iperf_error_lines(lines, started_at))
    return rows


def annotate_iperf_zero_samples(rows: list[dict[str, object]], errors: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    error_count = len(errors or [])
    zero_indexes = [index for index, row in enumerate(rows) if _is_zero_iperf_sample(row)]
    for row in rows:
        row["zero_sample"] = False
        row["zero_sample_type"] = ""
        row["zero_sample_label"] = ""
    if not zero_indexes:
        return rows
    zero_set = set(zero_indexes)
    for index in zero_indexes:
        row = rows[index]
        row["zero_sample"] = True
        previous_positive = index > 0 and _is_positive_iperf_sample(rows[index - 1])
        next_positive = index + 1 < len(rows) and _is_positive_iperf_sample(rows[index + 1])
        consecutive = (index - 1 in zero_set) or (index + 1 in zero_set)
        if consecutive:
            row["zero_sample_type"] = "consecutive_stall"
            row["zero_sample_label"] = "IPERF流量停顿"
        elif previous_positive and next_positive and error_count == 0:
            row["zero_sample_type"] = "isolated_report_gap"
            row["zero_sample_label"] = "IPERF采样空窗"
        else:
            row["zero_sample_type"] = "unknown"
            row["zero_sample_label"] = "IPERF零带宽样本"
    return rows


def summarize_iperf_zero_samples(rows: list[dict[str, object]], errors: list[dict[str, object]] | None = None) -> dict[str, int]:
    annotated = annotate_iperf_zero_samples(rows, errors)
    return {
        "iperf_zero_sample_count": sum(1 for row in annotated if row.get("zero_sample")),
        "iperf_isolated_gap_count": sum(1 for row in annotated if row.get("zero_sample_type") == "isolated_report_gap"),
        "iperf_stall_count": sum(1 for row in annotated if row.get("zero_sample_type") == "consecutive_stall"),
        "iperf_error_count": len(errors or []),
    }


def _is_zero_iperf_sample(row: dict[str, object]) -> bool:
    try:
        return float(row.get("transfer_bytes") or 0) <= 0 and float(row.get("bitrate_mbps") or 0) <= 0
    except (TypeError, ValueError):
        return False


def _is_positive_iperf_sample(row: dict[str, object]) -> bool:
    try:
        return float(row.get("transfer_bytes") or 0) > 0 and float(row.get("bitrate_mbps") or 0) > 0
    except (TypeError, ValueError):
        return False


def parse_iperf_json_text(text: str, started_at: datetime | None = None) -> list[dict[str, object]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, object]] = []
    for interval in payload.get("intervals") or []:
        if not isinstance(interval, dict):
            continue
        streams = interval.get("streams") if isinstance(interval.get("streams"), list) else []
        summary = interval.get("sum") if isinstance(interval.get("sum"), dict) else None
        source = summary or (streams[0] if streams and isinstance(streams[0], dict) else None)
        if not source:
            continue
        row = _iperf_json_row(source, started_at)
        if row:
            rows.append(row)
    end = payload.get("end")
    if isinstance(end, dict):
        for key in ("sum", "sum_sent", "sum_received"):
            source = end.get(key)
            if isinstance(source, dict):
                row = _iperf_json_row(source, started_at, role=key)
                if row:
                    rows.append(row)
                break
    return rows


def _iperf_json_row(source: dict[str, object], started_at: datetime | None, role: str = "interval") -> dict[str, object] | None:
    bps = _float_or_none(source.get("bits_per_second"))
    if bps is None:
        return None
    start = _float_or_none(source.get("start")) or 0.0
    end = _float_or_none(source.get("end"))
    if end is None:
        seconds = _float_or_none(source.get("seconds"))
        end = start + seconds if seconds is not None else start
    row: dict[str, object] = {
        "interval_start_sec": start,
        "interval_end_sec": end,
        "collector_time": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
        "transfer_bytes": _float_or_none(source.get("bytes")),
        "bitrate_mbps": bps / 1_000_000.0,
        "retransmits": int(_float_or_none(source.get("retransmits")) or 0),
        "cwnd": str(source.get("snd_cwnd") or source.get("cwnd") or ""),
        "role": role,
        "jitter_ms": _float_or_none(source.get("jitter_ms")),
        "lost_packets": _int_or_none(source.get("lost_packets")),
        "total_packets": _int_or_none(source.get("packets")),
        "loss_percent": _float_or_none(source.get("lost_percent")),
        "raw_line": json.dumps(source, ensure_ascii=False),
    }
    if started_at is not None:
        center = started_at + timedelta(seconds=(start + end) / 2)
        row["interval_center_time"] = center.isoformat(sep=" ", timespec="milliseconds")
    return row


def _float_or_none(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def aggregate_iperf_for_segment(rows: list[dict[str, object]], segment_start: datetime, segment_end: datetime) -> dict[str, object]:
    selected: list[dict[str, object]] = []
    for row in rows:
        value = row.get("interval_center_time")
        if not value:
            continue
        center = datetime.fromisoformat(str(value))
        if segment_start <= center < segment_end:
            selected.append(row)
    values = [float(row["bitrate_mbps"]) for row in selected if row.get("bitrate_mbps") is not None]
    retransmits = sum(int(row.get("retransmits") or 0) for row in selected)
    p95 = quantiles(values, n=20)[18] if len(values) >= 2 else (values[0] if values else None)
    return {
        "sample_count": len(selected),
        "avg_mbps": sum(values) / len(values) if values else None,
        "max_mbps": max(values) if values else None,
        "min_mbps": min(values) if values else None,
        "p95_mbps": p95,
        "retransmits": retransmits,
        "avg_retransmits_per_sec": retransmits / max(1, len(selected)) if selected else None,
    }
