from __future__ import annotations

import re


_ROW = re.compile(
    r"^(?P<name>.+?)\s+(?P<ip>\S+)\s+(?P<state>Discovery|Join|Offline|Run)\s+"
    r"(?P<time>\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})$",
    re.IGNORECASE,
)


def parse_wlan_ap_connection_records(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    for line in output.splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        name = match.group("name").strip()
        rows[name] = {
            "ap_name": name,
            "connection_ip": _value(match.group("ip")),
            "connection_state": match.group("state"),
            "connection_time": match.group("time"),
        }
    return rows


def _value(value: str) -> str | None:
    return None if value.upper() in {"N/A", "NA", "-"} else value
