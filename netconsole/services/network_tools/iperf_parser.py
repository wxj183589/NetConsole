from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from statistics import quantiles


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


def transfer_to_bytes(value: float, unit: str) -> float:
    factors = {"bytes": 1, "kbytes": 1024, "mbytes": 1024**2, "gbytes": 1024**3}
    return value * factors.get(unit.lower(), 1)


def bitrate_to_mbps(value: float, unit: str) -> float:
    factors = {"bits/sec": 1 / 1_000_000, "kbits/sec": 1 / 1000, "mbits/sec": 1, "gbits/sec": 1000}
    return value * factors.get(unit.lower(), 1)


def parse_iperf_line(line: str, started_at: datetime | None = None, collector_time: datetime | None = None) -> dict[str, object] | None:
    match = INTERVAL_RE.search(line)
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
        "collector_time": (collector_time or datetime.now()).isoformat(sep=" ", timespec="milliseconds"),
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
    }
    udp = UDP_RE.search(line)
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
    return rows


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
