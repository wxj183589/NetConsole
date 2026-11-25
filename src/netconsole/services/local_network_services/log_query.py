"""Read-only queries over the supervisor's bounded log tail."""

import re
from datetime import datetime

_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?)\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(.*)$")


def query_service_logs(
    lines: list[str],
    *,
    keyword: str = "",
    level: str = "",
    since: datetime | None = None,
    until: datetime | None = None,
    history: bool = False,
) -> dict:
    """Keep original lines and preserve unparsed provider output for display."""
    entries = []
    needle = keyword.casefold()
    for index, line in enumerate(lines):
        match = _LINE.match(line)
        stamp = None
        if match:
            try:
                stamp = datetime.fromisoformat(match[1].replace(",", ".")).astimezone()
            except ValueError:
                pass
        severity = match[2] if match else ""
        if level and severity != level:
            continue
        if needle and needle not in line.casefold():
            continue
        if since and (stamp is None or stamp < since.astimezone()):
            continue
        if until and (stamp is None or stamp > until.astimezone()):
            continue
        entries.append({
            "index": index,
            "time": stamp.isoformat() if stamp else "",
            "level": severity,
            "message": match[3] if match else line,
            "raw": line,
        })
    return {
        "lines": [entry["raw"] for entry in entries],
        "entries": entries,
        "bounded_tail": True,
        "scanned_lines": len(lines),
        "history": history,
        "line_limit": 1500 if history else 150,
    }
