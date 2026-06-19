from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceGroup:
    id: int | None = None
    site_id: str = ""
    name: str = ""
    sort_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None
