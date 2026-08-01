from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Literal


TracksideApLocationClass = Literal[
    "MAINLINE",
    "DEPOT",
    "PARKING_YARD",
    "STABLING",
    "DEPOT_CONNECTION",
    "TEST_TRACK",
    "NON_MAINLINE",
    "UNKNOWN",
]

LOCATION_CLASSES: tuple[TracksideApLocationClass, ...] = (
    "MAINLINE",
    "DEPOT",
    "PARKING_YARD",
    "STABLING",
    "DEPOT_CONNECTION",
    "TEST_TRACK",
    "NON_MAINLINE",
    "UNKNOWN",
)
NON_MAINLINE_LOCATION_CLASSES = frozenset(
    {
        "DEPOT",
        "PARKING_YARD",
        "STABLING",
        "DEPOT_CONNECTION",
        "TEST_TRACK",
        "NON_MAINLINE",
        "UNKNOWN",
    }
)
DEPOT_PING_LOCATION_CLASSES = frozenset(
    {"DEPOT", "PARKING_YARD", "STABLING"}
)
DEFAULT_LOCATION_SOURCE = "DEFAULT_MAINLINE"

_ALIASES: dict[str, TracksideApLocationClass] = {
    "mainline": "MAINLINE",
    "正线": "MAINLINE",
    "主线": "MAINLINE",
    "depot": "DEPOT",
    "车辆段": "DEPOT",
    "场段": "DEPOT",
    "parking_yard": "PARKING_YARD",
    "parking_lot": "PARKING_YARD",
    "停车场": "PARKING_YARD",
    "stabling": "STABLING",
    "storage_track": "STABLING",
    "存车线": "STABLING",
    "存车场": "STABLING",
    "depot_connection": "DEPOT_CONNECTION",
    "出入段线": "DEPOT_CONNECTION",
    "出段线": "DEPOT_CONNECTION",
    "入段线": "DEPOT_CONNECTION",
    "出场线": "DEPOT_CONNECTION",
    "入场线": "DEPOT_CONNECTION",
    "test_track": "TEST_TRACK",
    "试车线": "TEST_TRACK",
    "non_mainline": "NON_MAINLINE",
    "非正线": "NON_MAINLINE",
    "unknown": "UNKNOWN",
    "未知": "UNKNOWN",
}


def normalize_location_class(
    value: object,
    *,
    default: TracksideApLocationClass = "MAINLINE",
) -> TracksideApLocationClass:
    text = _text(value)
    if not text:
        return default
    normalized = _ALIASES.get(text.casefold())
    if normalized is None:
        raise ValueError(f"不支持的轨旁 AP 位置类型：{text}")
    return normalized


def default_participates_in_mainline(
    location_class: TracksideApLocationClass,
) -> bool:
    return location_class == "MAINLINE"


def parse_participates_in_mainline(
    value: object,
    *,
    default: bool,
) -> bool:
    if value is None or _text(value) == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _text(value).casefold()
    if text in {"1", "true", "yes", "y", "是", "参与", "启用"}:
        return True
    if text in {"0", "false", "no", "n", "否", "不参与", "停用"}:
        return False
    raise ValueError("是否参与正线判断必须为是/否")


def validate_location_participation(
    location_class: TracksideApLocationClass,
    participates_in_mainline: bool,
) -> None:
    if location_class in NON_MAINLINE_LOCATION_CLASSES and participates_in_mainline:
        raise ValueError(
            f"{location_class} 不能同时设置为参与正线判断"
        )


def resolve_trackside_ap_location(
    row: Mapping[str, object],
) -> tuple[TracksideApLocationClass, bool, str]:
    raw_class = _text(row.get("location_class"))
    raw_source = _text(row.get("location_class_source"))
    if raw_class:
        try:
            location_class = normalize_location_class(raw_class)
        except ValueError:
            location_class = "UNKNOWN"
        source = raw_source or (
            DEFAULT_LOCATION_SOURCE
            if location_class == "MAINLINE"
            else "LEGACY_INFERRED"
        )
    else:
        location_class = infer_legacy_location_class(row)
        source = (
            DEFAULT_LOCATION_SOURCE
            if location_class == "MAINLINE"
            else "LEGACY_INFERRED"
        )
    participates = parse_participates_in_mainline(
        row.get("participates_in_mainline"),
        default=default_participates_in_mainline(location_class),
    )
    return location_class, participates, source


def infer_legacy_location_class(
    row: Mapping[str, object],
) -> TracksideApLocationClass:
    belong_type = _text(row.get("belong_type")).casefold()
    if belong_type in _ALIASES:
        resolved = _ALIASES[belong_type]
        if resolved != "MAINLINE":
            return resolved

    text = " ".join(
        _text(row.get(field))
        for field in (
            "yard_name",
            "area_name",
            "station_name",
            "section_name",
            "location_desc",
            "install_scene",
        )
    )
    if any(token in text for token in ("出入段线", "出段线", "入段线", "出场线", "入场线")):
        return "DEPOT_CONNECTION"
    if "试车线" in text:
        return "TEST_TRACK"
    if "存车线" in text or "存车场" in text:
        return "STABLING"
    if "停车场" in text:
        return "PARKING_YARD"
    if "车辆段" in text:
        return "DEPOT"
    if "非正线" in text:
        return "NON_MAINLINE"
    return "MAINLINE"


def location_class_is_explicit(source: object) -> bool:
    return _text(source).upper() not in {
        "",
        DEFAULT_LOCATION_SOURCE,
        "LEGACY_DEFAULT_MAINLINE",
    }


def _text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


__all__ = [
    "DEFAULT_LOCATION_SOURCE",
    "DEPOT_PING_LOCATION_CLASSES",
    "LOCATION_CLASSES",
    "NON_MAINLINE_LOCATION_CLASSES",
    "TracksideApLocationClass",
    "default_participates_in_mainline",
    "infer_legacy_location_class",
    "location_class_is_explicit",
    "normalize_location_class",
    "parse_participates_in_mainline",
    "resolve_trackside_ap_location",
    "validate_location_participation",
]
