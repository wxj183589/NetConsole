from __future__ import annotations

import re


def parse_wlan_ap_radios(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith(("ap name", "apname")):
            continue
        parts = re.split(r"\s{2,}|\t+|\s+", stripped)
        if len(parts) < 3 or not _is_rid(parts[1]):
            continue
        ap_name = parts[0]
        rid = int(re.sub(r"\D", "", parts[1]))
        if rid not in (1, 2, 3):
            continue
        has_state_column = len(parts) >= 7 and parts[2].lower() in {"up", "down", "disable", "disabled", "enable", "enabled"}
        channel_index = 3 if has_state_column else 2
        bandwidth_index = 4 if has_state_column else 3
        tx_power_index = 6 if has_state_column and len(parts) > 6 else 4
        row = rows.setdefault(ap_name, {"ap_name": ap_name})
        row[f"rid{rid}_channel"] = _first_value(parts, ("channel", "chan"), channel_index)
        row[f"rid{rid}_bandwidth"] = _first_value(parts, ("bandwidth", "width", "bw"), bandwidth_index)
        row[f"rid{rid}_tx_power"] = _first_value(parts, ("power", "txpower"), tx_power_index)
    return rows


def _is_rid(value: str) -> bool:
    return value.upper().startswith("RID") or value in {"1", "2", "3"}


def _first_value(parts: list[str], names: tuple[str, ...], fallback_index: int) -> str | None:
    for index, part in enumerate(parts):
        clean = part.rstrip(":").lower()
        if clean in names and index + 1 < len(parts):
            return parts[index + 1]
    return parts[fallback_index] if len(parts) > fallback_index else None
