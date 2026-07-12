from __future__ import annotations

import re

from netconsole.services.fit_ap_link_info import format_h3c_mac, normalize_interface_key
from netconsole.utils.interface_normalize import normalize_interface_name


MAC_RE = re.compile(r"\b(?:[0-9a-f]{4}[-.:]){2}[0-9a-f]{4}\b|\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b|\b[0-9a-f]{12}\b", re.IGNORECASE)


def parse_fit_ap_lldp_neighbors(output: str) -> list[dict[str, object | None]]:
    rows: list[dict[str, object | None]] = []
    in_table = False
    for line in (output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("<", "-", "=")):
            continue
        lower = stripped.casefold()
        if lower.startswith(("chassis id :", "# --", "default --")):
            continue
        compact = " ".join(stripped.split()).casefold()
        if compact.startswith("system name local interface chassis id port id"):
            in_table = True
            continue
        if not in_table:
            continue
        mac_match = MAC_RE.search(stripped)
        if not mac_match:
            continue
        before = stripped[: mac_match.start()].strip()
        after = stripped[mac_match.end() :].strip()
        parts = before.split()
        if len(parts) < 2:
            continue
        local_interface = parts[-1]
        neighbor_name = " ".join(parts[:-1]).strip()
        rows.append(
            {
                "lldp_neighbor_name": neighbor_name,
                "lldp_local_interface": normalize_interface_name(local_interface),
                "lldp_local_interface_normalized": normalize_interface_key(local_interface),
                "lldp_neighbor_mac": format_h3c_mac(mac_match.group(0)) or mac_match.group(0),
                "lldp_neighbor_mac_normalized": re.sub(r"[^0-9a-fA-F]", "", mac_match.group(0)).casefold(),
                "lldp_neighbor_interface": normalize_interface_name(after) if after else "",
                "lldp_source": "ap_direct_lldp",
            }
        )
    return rows


def parse_fit_ap_lldp_neighbor(output: str, preferred_interface: object = None) -> dict[str, object | None]:
    rows = parse_fit_ap_lldp_neighbors(output)
    preferred_key = normalize_interface_key(preferred_interface)
    if preferred_key:
        for row in rows:
            if row.get("lldp_local_interface_normalized") == preferred_key:
                return row
    return rows[0] if rows else {
        "lldp_neighbor_name": None,
        "lldp_local_interface": None,
        "lldp_local_interface_normalized": None,
        "lldp_neighbor_mac": None,
        "lldp_neighbor_mac_normalized": None,
        "lldp_neighbor_interface": None,
        "lldp_source": "ap_direct_lldp",
    }
