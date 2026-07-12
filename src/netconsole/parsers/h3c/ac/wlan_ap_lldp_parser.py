from __future__ import annotations

import re

from netconsole.services.fit_ap_link_info import format_h3c_mac, normalize_interface_key, normalize_mac
from netconsole.utils.interface_normalize import normalize_interface_name


MAC_RE = re.compile(r"\b[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}\b", re.IGNORECASE)


def parse_wlan_ap_lldp(output: str) -> dict[str, dict[str, object | None]]:
    rows: dict[str, dict[str, object | None]] = {}
    in_table = False
    for line in output.splitlines():
        stripped = line.strip()
        lower = stripped.casefold()
        if not stripped or stripped.startswith(("<", "-", "=")) or "---- more ----" in lower:
            continue
        if not in_table:
            compact = " ".join(stripped.split()).casefold()
            if compact.startswith("ap name local interface neighbor name neighbor mac neighbor interface"):
                in_table = True
            continue
        if lower.startswith("ap name"):
            continue
        mac_matches = list(MAC_RE.finditer(stripped))
        if not mac_matches:
            continue
        mac_match = mac_matches[-1]
        before = stripped[: mac_match.start()].strip()
        after = stripped[mac_match.end() :].strip()
        parts = before.split()
        if len(parts) < 3 or not after:
            continue
        local_interface = parts[-2]
        neighbor_name = parts[-1]
        ap_name = " ".join(parts[:-2]).strip()
        if not ap_name:
            continue
        rows[ap_name] = {
            "ap_name": ap_name,
            "lldp_source": "ac_bulk_lldp",
            "lldp_confidence": 60,
            "lldp_local_interface": normalize_interface_name(local_interface),
            "lldp_local_interface_normalized": normalize_interface_key(local_interface),
            "lldp_neighbor_name": neighbor_name,
            "lldp_neighbor_mac": format_h3c_mac(mac_match.group(0)) or mac_match.group(0),
            "lldp_neighbor_mac_normalized": normalize_mac(mac_match.group(0)),
            "lldp_neighbor_interface": normalize_interface_name(after),
            "lldp_match_status": "matched",
        }
    return rows
