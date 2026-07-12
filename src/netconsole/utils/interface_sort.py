from __future__ import annotations

import re


PREFIX_ORDER = {
    "vlan-interface": 10,
    "bridge-aggregation": 20,
    "route-aggregation": 21,
    "loopback": 30,
    "ge": 100,
    "gigabitethernet": 100,
    "xge": 110,
    "ten-gigabitethernet": 110,
    "twenty-fivegige": 120,
    "fortygige": 130,
    "hundredgige": 140,
}


def interface_sort_key(name: object) -> tuple[int, str, tuple[int, ...], str]:
    text = str(name or "").strip()
    if not text:
        return (9999, "", (), "")
    normalized = text.lower()
    prefix_match = re.match(r"([a-z-]+)", normalized)
    prefix = prefix_match.group(1) if prefix_match else normalized
    numbers = tuple(int(value) for value in re.findall(r"\d+", normalized))
    return (PREFIX_ORDER.get(prefix, 500), prefix, numbers, normalized)
