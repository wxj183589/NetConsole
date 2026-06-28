from __future__ import annotations

import re


def natural_text_key(value: object) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", str(value or "").strip().casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)
