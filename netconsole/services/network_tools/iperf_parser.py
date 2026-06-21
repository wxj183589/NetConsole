from __future__ import annotations

import re
from datetime import datetime, timedelta
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
    rows: list[dict[str, object]] = []
    for line in lines:
        row = parse_iperf_line(line, started_at)
        if row:
            rows.append(row)
    return rows


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
