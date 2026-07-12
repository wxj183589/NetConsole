from __future__ import annotations

import re

from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.text_encoding import safe_decode


INTERFACE_PATTERN = re.compile(
    r"^(?:"
    r"(?:[A-Za-z][A-Za-z-]*Ethernet|FortyGigE|Twenty-FiveGigE|HundredGigE|XGE|GE|Ten-GE|Ten)\d+(?:/\d+){0,4}"
    r"|M-GigabitEthernet\d+/\d+/\d+"
    r"|InLoopBack\d+"
    r"|LoopBack\d+"
    r"|Vlan-interface\d+"
    r"|Bridge-Aggregation\d+"
    r"|NULL\d+"
    r")$",
    re.IGNORECASE,
)


def normalize_interface(name: str) -> str:
    text = safe_decode(name).strip().rstrip(":")
    bracket = re.search(r"\[([^\]]+)\]", text)
    if bracket:
        text = bracket.group(1).strip()
    return normalize_interface_name(text)


def classify_interface(name: str) -> str:
    normalized = normalize_interface(name)
    lowered = normalized.lower()
    if lowered.startswith(("inloopback", "loopback", "null")):
        return "loopback"
    if lowered.startswith(("vlan-interface", "bridge-aggregation")):
        return "logical"
    return "physical"


def is_supported_interface(name: str) -> bool:
    return bool(INTERFACE_PATTERN.match(normalize_interface(name)))

