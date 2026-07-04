from __future__ import annotations

import re
from dataclasses import dataclass


EMPTY_MILEAGE_VALUES = {"", "-", "N/A", "NA", "UNKNOWN", "未知", "无", "NONE", "NULL"}
TRACK_MILEAGE_PREFIXES = {"ZDK", "YDK", "CDK", "RDK"}
PREFIX_ALIASES = {
    "左线": "ZDK",
    "左线里程": "ZDK",
    "左": "ZDK",
    "下行": "ZDK",
    "下": "ZDK",
    "Z": "ZDK",
    "ZDK": "ZDK",
    "右线": "YDK",
    "右线里程": "YDK",
    "右": "YDK",
    "上行": "YDK",
    "上": "YDK",
    "Y": "YDK",
    "YDK": "YDK",
    "出段线": "CDK",
    "出段": "CDK",
    "出库线": "CDK",
    "C": "CDK",
    "CDK": "CDK",
    "入段线": "RDK",
    "入段": "RDK",
    "入库线": "RDK",
    "R": "RDK",
    "RDK": "RDK",
}


@dataclass(frozen=True)
class TrackMileage:
    raw: str
    meters: float | None
    prefix: str | None = None
    display: str = "-"
    error: str = ""


def parse_track_mileage(value: object) -> TrackMileage:
    raw = "" if value is None else str(value).strip()
    if _is_empty(raw):
        return TrackMileage(raw=raw, meters=None)
    text = raw.replace(" ", "").upper()
    match = re.fullmatch(r"([A-Z]*K)?(\d+)\+(\d+(?:\.\d+)?)", text)
    if match:
        prefix_text = _normalize_prefix(match.group(1))
        meters = int(match.group(2)) * 1000 + float(match.group(3))
        return TrackMileage(raw=raw, meters=meters, prefix=prefix_text, display=_format_meters(meters, prefix_text))
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        meters = float(text)
        return TrackMileage(raw=raw, meters=meters, display=_format_meters(meters, None))
    return TrackMileage(raw=raw, meters=None, error="里程无法解析")


def parse_mileage_to_meters(value: object) -> int | float | None:
    mileage = parse_track_mileage(value)
    if mileage.meters is None:
        return None
    return _compact_number(mileage.meters)


def normalize_mileage_prefix(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.sub(r"[\s_：:（）()\-/]+", "", text).upper()
    return PREFIX_ALIASES.get(compact) or PREFIX_ALIASES.get(text)


def format_mileage_k(value: object, direction: str | None = None, prefix: str | None = None) -> str:
    return format_track_mileage(value, direction=direction, prefix=prefix)


def format_track_mileage(
    value: object,
    direction: str | None = None,
    mileage_type: str | None = None,
    prefix: str | None = None,
    line_side: str | None = None,
) -> str:
    mileage = parse_track_mileage(value)
    if mileage.meters is None:
        return "-" if _is_empty(mileage.raw) or mileage.error else mileage.raw
    display_prefix = mileage.prefix or _first_prefix(prefix, mileage_type, line_side, direction)
    return _format_meters(mileage.meters, display_prefix)


def mileage_storage_text(value: object) -> str:
    meters = parse_mileage_to_meters(value)
    if meters is None:
        return "" if _is_empty(value) else str(value).strip()
    return str(meters)


def mileage_search_tokens(
    value: object,
    direction: str | None = None,
    mileage_type: str | None = None,
    prefix: str | None = None,
    line_side: str | None = None,
) -> set[str]:
    mileage = parse_track_mileage(value)
    if mileage.meters is None:
        return {str(value or "").strip()} if str(value or "").strip() else set()
    tokens = {
        str(_compact_number(mileage.meters)),
        _format_meters(mileage.meters, None),
        format_track_mileage(value, direction=direction, mileage_type=mileage_type, prefix=prefix, line_side=line_side),
    }
    for item in TRACK_MILEAGE_PREFIXES:
        tokens.add(_format_meters(mileage.meters, item))
    return {token for token in tokens if token}


def _first_prefix(*values: object) -> str | None:
    for value in values:
        prefix = normalize_mileage_prefix(value)
        if prefix:
            return prefix
    return None


def _normalize_prefix(value: object) -> str | None:
    text = str(value or "").strip().upper()
    if text in TRACK_MILEAGE_PREFIXES:
        return text
    return None


def _format_meters(value: object, prefix: str | None) -> str:
    meters = int(float(value))
    kilometer = meters // 1000
    remainder = meters % 1000
    return f"{prefix or 'K'}{kilometer}+{remainder:03d}"


def _compact_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _is_empty(value: object) -> bool:
    return str(value or "").strip().upper() in EMPTY_MILEAGE_VALUES
