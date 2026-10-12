from __future__ import annotations

import re


def parse_vlan_set(value: object) -> set[int]:
    if value in (None, ""):
        return set()
    tokens = [item for item in re.split(r"[,，;；\s]+", str(value).strip()) if item]
    vlans: set[int] = set()
    for token in tokens:
        if "-" in token:
            parts = token.split("-", 1)
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"invalid VLAN range: {token}")
            start = int(parts[0])
            end = int(parts[1])
            if start > end:
                raise ValueError(f"invalid VLAN range: {token}")
            for vlan in range(start, end + 1):
                _validate_vlan(vlan)
                vlans.add(vlan)
            continue
        if not token.isdigit():
            raise ValueError(f"invalid VLAN: {token}")
        vlan = int(token)
        _validate_vlan(vlan)
        vlans.add(vlan)
    return vlans


def _validate_vlan(vlan: int) -> None:
    if vlan < 1 or vlan > 4094:
        raise ValueError(f"VLAN out of range: {vlan}")


__all__ = ["parse_vlan_set"]
