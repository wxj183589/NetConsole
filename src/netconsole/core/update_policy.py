from __future__ import annotations

import re
from typing import Any


_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def should_offer_update(current: str, candidate: dict[str, Any]) -> bool:
    """Only published higher ProductVersion values may trigger an update."""

    if candidate.get("published") is not True:
        return False
    current_version = _parse_version(current)
    candidate_version = _parse_version(candidate.get("version"))
    return candidate_version is not None and current_version is not None and candidate_version > current_version


def _parse_version(value: object) -> tuple[int, int, int] | None:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


__all__ = ["should_offer_update"]
