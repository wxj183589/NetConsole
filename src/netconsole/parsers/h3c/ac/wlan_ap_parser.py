from __future__ import annotations

import re

from netconsole.parsers.h3c.ac.state_mapper import (
    classify_fit_ap_state,
    map_fit_ap_state,
)


def parse_wlan_ap_summary(output: str) -> dict[str, object | None]:
    total_aps = _int_after(output, r"Total\s+number\s+of\s+APs\s*:\s*(\d+)")
    online_aps = _int_after(output, r"Total\s+number\s+of\s+connected\s+APs\s*:\s*(\d+)")
    total_licenses = _int_after(output, r"Total\s+AP\s+licenses\s*:\s*(\d+)")
    local_licenses = _int_after(output, r"Local\s+AP\s+licenses\s*:\s*(\d+)")
    remaining_licenses = _int_after(output, r"Remaining\s+local\s+AP\s+licenses\s*:\s*(\d+)")
    ap_rows = parse_wlan_ap_list(output)
    offline_from_rows = sum(
        1
        for row in ap_rows
        if classify_fit_ap_state(
            row.get("state"),
            row.get("state_raw"),
            row.get("state_display"),
        )
        == "offline"
    )
    if online_aps is None and total_aps is not None:
        online_aps = max(total_aps - offline_from_rows, 0)
    if total_aps is not None and online_aps is not None:
        offline_aps = max(total_aps - online_aps, 0)
    else:
        offline_aps = offline_from_rows if ap_rows else None
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
    text = _state_token(value)
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
    if len(tokens) < 2:
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
        return _parse_ap_row_without_apid(tokens, stripped)
    ap_name = " ".join(tokens[:apid_index]).strip()
    state = _state_token(tokens[apid_index + 1])
    model_index = apid_index + 2
    serial_index = apid_index + 3
    if not ap_name:
        return None
    model = tokens[model_index] if model_index < len(tokens) else None
    serial_number = tokens[serial_index] if serial_index < len(tokens) else None
    tail = tokens[serial_index + 1 :]
    group_name, online_time = _parse_group_and_online_time(tail)
    return {
        "ap_name": ap_name,
        "apid": tokens[apid_index],
        "state": state,
        "state_raw": state,
        "state_display": map_fit_ap_state(state),
        "model": _empty_if_na(model),
        "serial_number": _empty_if_na(serial_number),
        "group_name": group_name,
        "online_time": online_time,
        "raw_line": stripped,
    }


def _parse_ap_row_without_apid(tokens: list[str], stripped: str) -> dict[str, object | None] | None:
    state_index = next((index for index in range(1, len(tokens)) if _looks_like_state(tokens[index])), -1)
    if state_index < 1:
        return None
    ap_name = " ".join(tokens[:state_index]).strip()
    state = _state_token(tokens[state_index])
    model = tokens[state_index + 1] if state_index + 1 < len(tokens) else None
    serial_number = tokens[state_index + 2] if state_index + 2 < len(tokens) else None
    group_name, online_time = _parse_group_and_online_time(tokens[state_index + 3 :])
    return {
        "ap_name": ap_name,
        "apid": None,
        "state": state,
        "state_raw": state,
        "state_display": map_fit_ap_state(state),
        "model": _empty_if_na(model),
        "serial_number": _empty_if_na(serial_number),
        "group_name": group_name,
        "online_time": online_time,
        "raw_line": stripped,
    }


def _state_token(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split("=", 1)[0].strip().upper()


def _empty_if_na(value: object) -> object | None:
    text = str(value or "").strip()
    return None if text.casefold() in {"", "n/a", "na", "-", "--", "none", "null", "unknown"} else value


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
