from __future__ import annotations

from collections.abc import Mapping


STATION_ALIASES = ("station", "site", "site_name", "ap_station", "ownership_station", "metadata_station", "归属站点")
EMPTY_STATION_VALUES = {"", "-", "N/A", "n/a", "none", "None", "未归属"}


def normalize_station_value(record: Mapping[str, object | None] | None) -> str:
    if not record:
        return ""
    for key in STATION_ALIASES:
        value = record.get(key)
        text = str(value or "").strip()
        if text and text not in EMPTY_STATION_VALUES:
            return text
    return ""
