"""Interface name normalisation — shared by all layers.

This utility lives outside both ``core/`` and ``services/`` so that
``switch_source`` (core) and ``trackside_ap_business`` (services) can
import it without creating circular dependencies.
"""
from __future__ import annotations


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
