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
    text = str(value or "").strip()
    lower = text.casefold()
    replacements = (
        ("xge", "Ten-GigabitEthernet"),
        ("ge", "GigabitEthernet"),
        ("bagg", "Bridge-Aggregation"),
        ("vlan", "Vlan-interface"),
    )
    for prefix, full in replacements:
        if lower.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)].isdigit():
            return full + text[len(prefix):]
    return text
