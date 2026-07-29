from __future__ import annotations

import re
from typing import TypeAlias


NaturalToken: TypeAlias = tuple[int, int | str]
InterfaceSortKey: TypeAlias = tuple[
    int,
    int,
    str,
    tuple[int, ...],
    tuple[NaturalToken, ...],
    str,
]

_PREFIX_ALIASES = {
    "vlanif": "vlan-interface",
    "bridge-aggregation": "link-aggregation",
    "eth-trunk": "link-aggregation",
    "port-channel": "link-aggregation",
    "route-aggregation": "route-aggregation",
    "loopback": "loopback",
    "ethernet": "ethernet",
    "ge": "gigabitethernet",
    "gei": "gigabitethernet",
    "gigabitethernet": "gigabitethernet",
    "xge": "ten-gigabitethernet",
    "xgigabitethernet": "ten-gigabitethernet",
    "tengigabitethernet": "ten-gigabitethernet",
    "ten-gigabitethernet": "ten-gigabitethernet",
}

_PREFIX_ORDER = {
    "vlan-interface": 10,
    "link-aggregation": 20,
    "route-aggregation": 21,
    "loopback": 30,
    "ethernet": 90,
    "gigabitethernet": 100,
    "ten-gigabitethernet": 110,
    "twenty-fivegige": 120,
    "fortygige": 130,
    "hundredgige": 140,
}

_INTERFACE_RE = re.compile(
    r"^(?P<prefix>[a-z][a-z-]*[a-z])[-_ ]?"
    r"(?P<number>\d+(?:[/.:-]\d+)*)$",
    re.IGNORECASE,
)
_NATURAL_TEXT_RE = re.compile(r"\d+|\D+")


def _natural_text_key(value: str) -> tuple[NaturalToken, ...]:
    return tuple(
        (1, int(token)) if token.isdigit() else (0, token)
        for token in _NATURAL_TEXT_RE.findall(value.casefold())
    )


def interface_sort_key(name: object) -> InterfaceSortKey:
    """Return a stable logical-port key without changing the display name."""

    text = str(name or "").strip()
    if not text:
        return (2, 0, "", (), (), "")

    normalized = text.casefold()
    match = _INTERFACE_RE.fullmatch(normalized)
    if match is None:
        return (1, 0, "", (), _natural_text_key(normalized), normalized)

    raw_prefix = match.group("prefix").rstrip("-")
    canonical_prefix = _PREFIX_ALIASES.get(raw_prefix, raw_prefix)
    numbers = tuple(int(value) for value in re.findall(r"\d+", match.group("number")))
    return (
        0,
        _PREFIX_ORDER.get(canonical_prefix, 500),
        canonical_prefix,
        numbers,
        (),
        "",
    )
