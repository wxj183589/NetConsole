from __future__ import annotations

import re


def parse_wlan_ap_radios(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if _is_noise_line(stripped):
            continue
        parts = re.split(r"\s{2,}|\t+|\s+", stripped)
        rid_index = next((index for index, part in enumerate(parts[1:], start=1) if _is_rid(part)), -1)
        if len(parts) < 3 or rid_index < 1:
            continue
        ap_name = " ".join(parts[:rid_index]).strip()
        rid = int(re.sub(r"\D", "", parts[rid_index]))
        if rid not in (1, 2, 3):
            continue
        values = parts[rid_index + 1 :]
        has_state_column = len(values) >= 5 and values[0].lower() in {"up", "down", "disable", "disabled", "enable", "enabled"}
        channel_index = 1 if has_state_column else 0
        bandwidth_index = 2 if has_state_column else 1
        usage_index = 3 if has_state_column else -1
        tx_power_index = 4 if has_state_column and len(values) > 4 else 2
        clients_index = 5 if has_state_column else -1
        row = rows.setdefault(ap_name, {"ap_name": ap_name})
        row[f"rid{rid}_status"] = values[0] if has_state_column else None
        row[f"rid{rid}_channel"] = _first_value(values, ("channel", "chan"), channel_index)
        row[f"rid{rid}_bandwidth"] = _first_value(values, ("bandwidth", "width", "bw"), bandwidth_index)
        row[f"rid{rid}_usage"] = _first_value(values, ("usage",), usage_index)
        row[f"rid{rid}_tx_power"] = _first_value(values, ("power", "txpower"), tx_power_index)
        row[f"rid{rid}_clients"] = _first_value(values, ("clients",), clients_index)
    return rows


def _is_rid(value: str) -> bool:
    return value.upper().startswith("RID") or value in {"1", "2", "3"}


def _first_value(parts: list[str], names: tuple[str, ...], fallback_index: int) -> str | None:
    for index, part in enumerate(parts):
        clean = part.rstrip(":").lower()
        if clean in names and index + 1 < len(parts):
            return parts[index + 1]
    return parts[fallback_index] if fallback_index >= 0 and len(parts) > fallback_index else None


def _is_noise_line(stripped: str) -> bool:
    lower = stripped.lower()
    return (
        not stripped
        or stripped.startswith(("-", "=", "<"))
        or lower.startswith(("total ", "maximum ", "remaining ", "server ", "sync ", "ap name", "apname"))
        or stripped.startswith("(")
    )
