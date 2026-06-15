from __future__ import annotations

import re

from netconsole.parsers.h3c.ac.state_mapper import map_fit_ap_state


def parse_wlan_ap_summary(output: str) -> dict[str, object | None]:
    total_aps = _int_after(output, r"Total\s+number\s+of\s+APs\s*:\s*(\d+)")
    online_aps = _int_after(output, r"Total\s+number\s+of\s+connected\s+APs\s*:\s*(\d+)")
    total_licenses = _int_after(output, r"Total\s+AP\s+licenses\s*:\s*(\d+)")
    local_licenses = _int_after(output, r"Local\s+AP\s+licenses\s*:\s*(\d+)")
    remaining_licenses = _int_after(output, r"Remaining\s+local\s+AP\s+licenses\s*:\s*(\d+)")
    ap_rows = parse_wlan_ap_list(output)
    offline_from_rows = sum(1 for row in ap_rows if str(row.get("state") or "").upper() == "I")
    if online_aps is None and total_aps is not None:
        online_aps = max(total_aps - offline_from_rows, 0)
    offline_aps = offline_from_rows if ap_rows else (total_aps - online_aps if total_aps is not None and online_aps is not None else None)
    return {
        "total_aps": total_aps,
        "online_aps": online_aps,
        "offline_aps": offline_aps,
        "total_ap_licenses": total_licenses,
        "local_ap_licenses": local_licenses,
        "remaining_local_ap_licenses": remaining_licenses,
        "cpu_usage": _percent_after(output, r"CPU\s+(?:usage|utilization)\s*[:=]\s*([\d.]+%?)"),
        "memory_usage": _percent_after(output, r"Memory\s+(?:usage|utilization)\s*[:=]\s*([\d.]+%?)"),
    }


def parse_wlan_ap_list(output: str) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith(("total ", "ap name", "apname")):
            continue
        compact = stripped.split()
        if len(compact) >= 5 and _looks_like_apid(compact[1]) and _looks_like_state(compact[2]):
            online_time = compact[6] if len(compact) >= 9 and compact[-2].lower() in {"fit", "fat"} else " ".join(compact[6:]) if len(compact) > 6 else None
            rows.append(
                {
                    "ap_name": compact[0],
                    "apid": compact[1],
                    "state": compact[2],
                    "state_raw": compact[2],
                    "state_display": map_fit_ap_state(compact[2]),
                    "model": compact[3],
                    "serial_number": compact[4],
                    "group_name": compact[5] if len(compact) > 5 else None,
                    "online_time": online_time,
                }
            )
            continue
        parts = re.split(r"\s{2,}|\t+", stripped)
        if len(parts) >= 5 and _looks_like_apid(parts[1]) and _looks_like_state(parts[2]):
            rows.append(
                {
                    "ap_name": parts[0],
                    "apid": parts[1],
                    "state": parts[2],
                    "state_raw": parts[2],
                    "state_display": map_fit_ap_state(parts[2]),
                    "model": parts[3],
                    "serial_number": parts[4],
                    "group_name": parts[5] if len(parts) > 5 else None,
                    "online_time": parts[6] if len(parts) > 6 else None,
                }
            )
            continue
    return rows


def _int_after(output: str, pattern: str) -> int | None:
    match = re.search(pattern, output, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _percent_after(output: str, pattern: str) -> str | None:
    match = re.search(pattern, output, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1)
    return value if value.endswith("%") else f"{value}%"


def _looks_like_state(value: str) -> bool:
    states = {part for part in re.split(r"[/,]", value.upper()) if part}
    return bool(states) and states <= {"R", "I", "M", "B", "RUN", "ONLINE", "OFFLINE", "IDLE"}


def _looks_like_apid(value: str) -> bool:
    return value.isdigit()
