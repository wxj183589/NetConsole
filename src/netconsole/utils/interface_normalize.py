"""Interface name normalisation — shared by all layers.

This utility lives outside both ``core/`` and ``services/`` so that
``switch_source`` (core) and ``trackside_ap_business`` (services) can
import it without creating circular dependencies.
"""
from __future__ import annotations

import re


_DISPLAY_PREFIXES = (
    (re.compile(r"^(?:HundredGigE|Hundred-?GigabitEthernet|100GigabitEthernet)\s*", re.IGNORECASE), "100GE"),
    (re.compile(r"^(?:FortyGigE|Forty-?GigabitEthernet|40GigabitEthernet)\s*", re.IGNORECASE), "40GE"),
    (re.compile(r"^(?:Twenty-?FiveGigE|Twenty-?Five-?GigabitEthernet|25GigabitEthernet)\s*", re.IGNORECASE), "25GE"),
    (re.compile(r"^(?:Ten-GigabitEthernet|TenGigabitEthernet|XGigabitEthernet)\s*", re.IGNORECASE), "XGE"),
    (re.compile(r"^GigabitEthernet\s*", re.IGNORECASE), "GE"),
)

_SPACED_INTERFACE_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z][A-Za-z-]*)\s+(?P<suffix>\d+(?:[/.:]\d+)*)$"
)
_SPACED_PREFIX_REPLACEMENTS = {
    "ten-gigabitethernet": "Ten-GigabitEthernet",
    "tengigabitethernet": "Ten-GigabitEthernet",
    "xgigabitethernet": "Ten-GigabitEthernet",
    "ten-ge": "Ten-GigabitEthernet",
    "ten": "Ten-GigabitEthernet",
    "xge": "Ten-GigabitEthernet",
    "gigabitethernet": "GigabitEthernet",
    "ge": "GigabitEthernet",
    "bridge-aggregation": "Bridge-Aggregation",
    "bagg": "Bridge-Aggregation",
    "vlan-interface": "Vlan-interface",
    "vlan": "Vlan-interface",
}


def normalize_interface_name(value: object) -> str:
    """Expand abbreviated interface names (GE, XGE, …) to their canonical form.

    Examples
    ~~~~~~~~
    >>> normalize_interface_name("GE1/0/1")
    'GigabitEthernet1/0/1'
    >>> normalize_interface_name("XGE1/0/1")
    'Ten-GigabitEthernet1/0/1'
    >>> normalize_interface_name("GigabitEthernet1/0/1")
    'GigabitEthernet1/0/1'
    """
    text = str(value or "").strip().rstrip(":")
    if not text:
        return ""
    spaced_match = _SPACED_INTERFACE_PATTERN.fullmatch(text)
    if spaced_match:
        replacement = _SPACED_PREFIX_REPLACEMENTS.get(
            spaced_match.group("prefix").casefold()
        )
        if replacement:
            return replacement + spaced_match.group("suffix")
    lower = text.casefold()
    if lower == "null0":
        return "NULL0"
    if lower.startswith("ten-gigabitethernet"):
        return "Ten-GigabitEthernet" + text[len("Ten-GigabitEthernet") :]
    replacements = (
        ("xgigabitethernet", "Ten-GigabitEthernet"),
        ("tengigabitethernet", "Ten-GigabitEthernet"),
        ("ten-ge", "Ten-GigabitEthernet"),
        ("ten", "Ten-GigabitEthernet"),
        ("xge", "Ten-GigabitEthernet"),
        ("gigabitethernet", "GigabitEthernet"),
        ("ge", "GigabitEthernet"),
        ("bagg", "Bridge-Aggregation"),
        ("vlan", "Vlan-interface"),
    )
    for prefix, full in replacements:
        if lower.startswith(prefix):
            suffix = text[len(prefix):]
            if suffix and suffix[0].isdigit():
                return full + suffix
    return text


def display_interface_name(value: object) -> str:
    """Shorten common physical interface prefixes without changing the port path."""

    text = str(value or "").strip()
    for pattern, replacement in _DISPLAY_PREFIXES:
        match = pattern.match(text)
        if match:
            return f"{replacement}{text[match.end():]}"
    return text
