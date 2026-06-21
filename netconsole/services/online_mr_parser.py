from __future__ import annotations

import re
from datetime import datetime

from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, MeshLogRecord
from netconsole.parsers.mesh_log_parser import parse_mesh_link_table


CHANNEL_BUSY_RE = re.compile(r"(?P<key>txbusy|rxbusy|tx\s*busy|rx\s*busy)\D+(?P<value>\d+)", re.IGNORECASE)


def parse_mesh_link_text(raw_text: str, collected_at: datetime) -> tuple[list[MeshLogRecord], str, str]:
    records, issues = parse_mesh_link_table(raw_text, source_label="online", sample_time=collected_at, radio=1)
    if not records:
        message = "; ".join(issue.message for issue in issues[:3]) or "no mesh link records parsed"
        return [], "FAILED", message
    if issues:
        return records, "PARTIAL", "; ".join(issue.message for issue in issues[:3])
    return records, "OK", ""


def parse_channel_busy_text(raw_text: str) -> list[dict[str, int | str | None]]:
    values: dict[str, int] = {}
    for match in CHANNEL_BUSY_RE.finditer(raw_text):
        key = match.group("key").lower().replace(" ", "")
        normalized = "tx_busy" if key == "txbusy" else "rx_busy"
        values[normalized] = int(match.group("value"))
    return [{"radio": 1, "tx_busy": values.get("tx_busy"), "rx_busy": values.get("rx_busy"), "raw_text": raw_text}]


def summarize_active(records: list[MeshLogRecord]) -> MeshLogRecord | None:
    active = [record for record in records if record.link_state == LINK_STATE_ACTIVE]
    return active[0] if len(active) == 1 else None
