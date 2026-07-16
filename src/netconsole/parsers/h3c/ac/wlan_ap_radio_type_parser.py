from __future__ import annotations

import re


_BAND = re.compile(r"\((2\.4|5|6)\s*GHz\)", re.IGNORECASE)


def parse_wlan_ap_radio_types(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    for line in output.splitlines():
        parts = line.strip().split()
        rid_index = next((index for index, value in enumerate(parts[1:], start=1) if value in {"1", "2", "3"}), -1)
        if rid_index < 1 or len(parts) < rid_index + 4:
            continue
        ap_name = " ".join(parts[:rid_index]).strip()
        radio_type = " ".join(parts[rid_index + 3 :]).strip()
        if not ap_name or not radio_type:
            continue
        rid = int(parts[rid_index])
        band_match = _BAND.search(radio_type)
        row = rows.setdefault(ap_name, {"ap_name": ap_name})
        row[f"rid{rid}_status"] = parts[rid_index + 2]
        row[f"rid{rid}_mode"] = _BAND.sub("", radio_type).strip()
        row[f"rid{rid}_band"] = f"{band_match.group(1)}GHz" if band_match else None
    return rows
