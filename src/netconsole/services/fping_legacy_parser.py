from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable


SUCCESS_RE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2}\.\d{1,3})\s*:\s*Reply\[(?P<seq>\d+)\]\s+from\s+"
    r"(?P<target>[^:]+):\s*bytes=(?P<bytes>\d+)\s+time=(?P<latency>[0-9.]+)\s*ms\s+TTL=(?P<ttl>\d+)",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2}\.\d{1,3})")
FAIL_RE = re.compile(r"(request timed out|timeout|error|lost|no reply)", re.IGNORECASE)
SUMMARY_PACKETS_RE = re.compile(
    r"Packets:\s*Sent\s*=\s*(?P<sent>\d+),\s*Received\s*=\s*(?P<received>\d+),\s*Lost\s*=\s*(?P<lost>\d+)\s*\((?P<loss>[0-9.]+)%\s*loss\)",
    re.IGNORECASE,
)
SUMMARY_LATENCY_RE = re.compile(
    r"Minimum\s*=\s*(?P<min>[0-9.]+)\s*ms,\s*Maximum\s*=\s*(?P<max>[0-9.]+)\s*ms,\s*Average\s*=\s*(?P<avg>[0-9.]+)\s*ms",
    re.IGNORECASE,
)


@dataclass
class FpingSampleClock:
    session_date: date
    last_time: time | None = None
    day_offset: int = 0

    def resolve(self, text: str) -> datetime:
        current = datetime.strptime(text, "%H:%M:%S.%f").time()
        if self.last_time is not None and current < self.last_time:
            previous_seconds = self.last_time.hour * 3600 + self.last_time.minute * 60 + self.last_time.second
            current_seconds = current.hour * 3600 + current.minute * 60 + current.second
            if previous_seconds - current_seconds > 12 * 3600:
                self.day_offset += 1
        self.last_time = current
        return datetime.combine(self.session_date + timedelta(days=self.day_offset), current)


def parse_fping_line(raw_line: str, clock: FpingSampleClock, default_target: str = "") -> dict[str, object] | None:
    line = raw_line.strip()
    success = SUCCESS_RE.match(line)
    if success:
        collected_at = clock.resolve(success.group("time"))
        return {
            "local_time_text": success.group("time"),
            "collected_at": collected_at.isoformat(sep=" ", timespec="milliseconds"),
            "seq": int(success.group("seq")),
            "target_ip": success.group("target"),
            "success": True,
            "latency_ms": float(success.group("latency")),
            "ttl": int(success.group("ttl")),
            "bytes": int(success.group("bytes")),
            "raw_line": raw_line,
        }
    if FAIL_RE.search(line):
        match = TIME_RE.match(line)
        collected_at = clock.resolve(match.group("time")) if match else datetime.combine(clock.session_date + timedelta(days=clock.day_offset), datetime.now().time())
        return {
            "local_time_text": match.group("time") if match else "",
            "collected_at": collected_at.isoformat(sep=" ", timespec="milliseconds"),
            "seq": None,
            "target_ip": default_target,
            "success": False,
            "latency_ms": None,
            "ttl": None,
            "bytes": None,
            "raw_line": raw_line,
        }
    return None


def parse_fping_lines(lines: Iterable[str], session_started_at: datetime, default_target: str = "") -> list[dict[str, object]]:
    clock = FpingSampleClock(session_started_at.date())
    rows: list[dict[str, object]] = []
    for line in lines:
        parsed = parse_fping_line(line, clock, default_target=default_target)
        if parsed is not None:
            rows.append(parsed)
    return rows


def parse_fping_summary(text: str, target_ip: str = "") -> dict[str, object]:
    packets = SUMMARY_PACKETS_RE.search(text)
    latency = SUMMARY_LATENCY_RE.search(text)
    result: dict[str, object] = {"target_ip": target_ip}
    if packets:
        result.update(
            {
                "sent": int(packets.group("sent")),
                "received": int(packets.group("received")),
                "lost": int(packets.group("lost")),
                "loss_percent": float(packets.group("loss")),
            }
        )
    if latency:
        result.update(
            {
                "min_latency_ms": float(latency.group("min")),
                "max_latency_ms": float(latency.group("max")),
                "avg_latency_ms": float(latency.group("avg")),
            }
        )
    return result


def aggregate_ping_for_active_segment(samples: list[dict[str, object]], segment_start: datetime, segment_end: datetime) -> dict[str, object]:
    in_window = [
        sample
        for sample in samples
        if segment_start <= datetime.fromisoformat(str(sample["collected_at"])) < segment_end
    ]
    sent = len(in_window)
    lost_samples = [sample for sample in in_window if not sample.get("success")]
    success_samples = [sample for sample in in_window if sample.get("success")]
    latencies = [float(sample["latency_ms"]) for sample in success_samples if sample.get("latency_ms") is not None]
    max_consecutive = 0
    current = 0
    for sample in in_window:
        if sample.get("success"):
            current = 0
        else:
            current += 1
            max_consecutive = max(max_consecutive, current)
    sorted_latencies = sorted(latencies)
    return {
        "ping_sent": sent,
        "ping_success": len(success_samples),
        "ping_lost": len(lost_samples),
        "ping_loss_percent": (len(lost_samples) / sent * 100) if sent else None,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "p95_latency_ms": _percentile(sorted_latencies, 95),
        "p99_latency_ms": _percentile(sorted_latencies, 99),
        "max_consecutive_loss": max_consecutive,
        "first_loss_time": lost_samples[0]["collected_at"] if lost_samples else None,
        "last_loss_time": lost_samples[-1]["collected_at"] if lost_samples else None,
    }


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] + (values[upper] - values[lower]) * fraction
