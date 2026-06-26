from __future__ import annotations

import re
from datetime import datetime

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, MeshLogRecord
from netconsole.parsers.mesh_log_parser import parse_mesh_link_table


CHANNEL_BUSY_RE = re.compile(r"(?P<key>txbusy|rxbusy|tx\s*busy|rx\s*busy)\D+(?P<value>\d+)", re.IGNORECASE)
CHANNEL_BUSY_ROW_RE = re.compile(
    r"^\s*\d+\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<ctl>\d+|-)\s+"
    r"(?P<tx>\d+|-)\s+"
    r"(?P<rx>\d+|-)\s+"
    r"(?P<ext>\d+|-)"
)
CHANNEL_BUSY_DATE_RE = re.compile(r"Date/Month/Year:\s*(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})", re.IGNORECASE)


def parse_mesh_link_text(raw_text: str, collected_at: datetime) -> tuple[list[MeshLogRecord], str, str]:
    records, issues = parse_mesh_link_table(raw_text, source_label="online", sample_time=collected_at, radio=1)
    if not records:
        message = "; ".join(issue.message for issue in issues[:3]) or "no mesh link records parsed"
        return [], "FAILED", message
    if issues:
        return records, "PARTIAL", "; ".join(issue.message for issue in issues[:3])
    return records, "OK", ""


def parse_channel_busy_text(raw_text: str) -> list[dict[str, int | str | None]]:
    table_rows: list[dict[str, int | str | None]] = []
    sample_date = ""
    date_match = CHANNEL_BUSY_DATE_RE.search(raw_text)
    if date_match:
        sample_date = f"{int(date_match.group('year')):04d}-{int(date_match.group('month')):02d}-{int(date_match.group('day')):02d}"
    for line in raw_text.splitlines():
        row = CHANNEL_BUSY_ROW_RE.match(line)
        if not row:
            continue
        raw_time = row.group("time")
        sample_time = f"{sample_date} {raw_time}" if sample_date else raw_time
        table_rows.append(
            {
                "radio": 1,
                "tx_busy": _busy_int(row.group("tx")),
                "rx_busy": _busy_int(row.group("rx")),
                "raw_text": line.strip(),
                "sample_time": sample_time,
                "ctl_busy": _busy_int(row.group("ctl")),
            }
        )
    if table_rows:
        return table_rows
    values: dict[str, int] = {}
    for match in CHANNEL_BUSY_RE.finditer(raw_text):
        key = match.group("key").lower().replace(" ", "")
        normalized = "tx_busy" if key == "txbusy" else "rx_busy"
        values[normalized] = int(match.group("value"))
    return [{"radio": 1, "tx_busy": values.get("tx_busy"), "rx_busy": values.get("rx_busy"), "raw_text": raw_text}]


def _busy_int(value: str) -> int | None:
    return None if value == "-" else int(value)


def summarize_active(records: list[MeshLogRecord]) -> MeshLogRecord | None:
    active = [record for record in records if record.link_state == LINK_STATE_ACTIVE]
    return active[0] if len(active) == 1 else None
