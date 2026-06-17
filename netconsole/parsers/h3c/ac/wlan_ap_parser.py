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
        if _is_noise_line(stripped):
            continue
        parsed = _parse_ap_row(stripped)
        if parsed:
            rows.append(parsed)
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
    text = value.strip().upper()
    if text in {"I", "J", "JA", "IL", "C", "DC", "R", "R/M", "R/B", "RUN", "ONLINE", "OFFLINE", "IDLE"}:
        return True
    states = {part for part in re.split(r"[/,]", text) if part}
    return bool(states) and states <= {"R", "I", "J", "JA", "IL", "C", "DC", "M", "B", "RUN", "ONLINE", "OFFLINE", "IDLE"}


def _looks_like_apid(value: str) -> bool:
    return value.isdigit()


def _is_noise_line(stripped: str) -> bool:
    lower = stripped.lower()
    return (
        not stripped
        or stripped.startswith(("-", "="))
        or lower.startswith(("total ", "maximum ", "remaining ", "server ", "sync ", "state :", "online time :", "ap name", "apname"))
        or lower.startswith(("c = ", "i = "))
        or stripped.startswith("<")
        or stripped in {"(MHz) (%)   (dBm)"}
    )


def _parse_ap_row(stripped: str) -> dict[str, object | None] | None:
    tokens = stripped.split()
    if len(tokens) < 5:
        return None
    apid_index = next(
        (
            index
            for index in range(1, len(tokens) - 3)
            if _looks_like_apid(tokens[index]) and _looks_like_state(tokens[index + 1])
        ),
        -1,
    )
    if apid_index < 1:
        return None
    ap_name = " ".join(tokens[:apid_index]).strip()
    state = tokens[apid_index + 1]
    model_index = apid_index + 2
    serial_index = apid_index + 3
    if not ap_name or serial_index >= len(tokens):
        return None
    tail = tokens[serial_index + 1 :]
    group_name, online_time = _parse_group_and_online_time(tail)
    return {
        "ap_name": ap_name,
        "apid": tokens[apid_index],
        "state": state,
        "state_raw": state,
        "state_display": map_fit_ap_state(state),
        "model": tokens[model_index],
        "serial_number": tokens[serial_index],
        "group_name": group_name,
        "online_time": online_time,
        "raw_line": stripped,
    }


def _parse_group_and_online_time(tail: list[str]) -> tuple[str | None, str | None]:
    if not tail:
        return None, None
    time_index = next((index for index, token in enumerate(tail) if _looks_like_online_time(token)), -1)
    if time_index >= 0:
        group = " ".join(tail[:time_index]).strip() or None
        return group, tail[time_index]
    if len(tail) >= 2 and tail[-2].isdigit() and tail[-1].lower() in {"days", "day", "hours", "hour", "mins", "minutes", "seconds"}:
        return " ".join(tail[:-2]).strip() or None, " ".join(tail[-2:])
    return tail[0], " ".join(tail[1:]).strip() or None


def _looks_like_online_time(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?::\d+){2,3}", value) or re.fullmatch(r"\d+[dhmsDHMS]", value))
