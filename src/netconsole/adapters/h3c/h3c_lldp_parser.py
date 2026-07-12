from __future__ import annotations

import re

from netconsole.adapters.h3c.h3c_interface_parser import normalize_interface
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors


def normalize_mac(value: object) -> str | None:
    text = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    if len(text) != 12:
        return str(value or "").strip() or None
    return ":".join(text[index : index + 2] for index in range(0, 12, 2)).lower()


def parse_lldp(raw: str, verbose: str = "") -> list[dict[str, object | None]]:
    rows = parse_lldp_neighbors(raw, verbose)
    for row in rows:
        if row.get("local_interface"):
            row["local_interface"] = normalize_interface(str(row["local_interface"]))
        if row.get("neighbor_interface"):
            row["neighbor_interface"] = normalize_interface(str(row["neighbor_interface"]))
        if row.get("neighbor_mac"):
            row["neighbor_mac"] = normalize_mac(row.get("neighbor_mac"))
    return rows
