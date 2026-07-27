from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_MAIN_PATH_CODE = "MAIN"
UNASSIGNED_PATH_CODE = "UNASSIGNED"
DEFAULT_STATION_SOURCE_GROUP = "车站"
STATION_SOURCE_FIELD = "station"

NODE_TYPE_LABELS = {
    "station": "普通车站",
    "parking_lot": "停车场",
    "depot": "车辆段",
    "connection_point": "接轨点",
    "other": "其他",
    "unknown": "待确认",
}
STRUCTURE_TYPE_LABELS = {
    "underground": "地下",
    "elevated": "高架",
    "at_grade": "地面",
    "cutting": "路堑",
    "mixed": "混合",
    "unknown": "未填写",
}
PLATFORM_LAYOUT_LABELS = {
    "island": "岛式",
    "side": "侧式",
    "mixed": "混合式",
    "stacked_island": "叠岛式",
    "stacked_side": "叠侧式",
    "separated": "分离式",
    "unknown": "未填写",
}
TURNBACK_TYPE_LABELS = {
    "none": "无",
    "crossover": "渡线",
    "pocket_track": "中间折返线/存车线",
    "tail_track": "站后折返线",
    "loop": "环形折返",
    "depot_connection": "出入段线",
    "other": "其他",
    "unknown": "类型未知",
}
TURNBACK_DIRECTION_LABELS = {
    "none": "无",
    "both": "双向",
    "increasing_to_decreasing": "递增转递减",
    "decreasing_to_increasing": "递减转递增",
    "unknown": "未知",
}
TRACK_FACILITY_LABELS = {
    "turnback_track": "折返线",
    "crossover": "渡线",
    "storage_track": "存车线",
    "depot_connection": "出入段线",
    "tail_track": "站后折返线",
    "loop": "环形折返",
    "siding": "其他侧线",
    "other": "其他",
}
TRACK_FACILITY_ORDER = tuple(TRACK_FACILITY_LABELS)
LEGACY_TURNBACK_FACILITIES = {
    "none": (),
    "crossover": ("crossover",),
    "pocket_track": ("turnback_track", "storage_track"),
    "tail_track": ("tail_track",),
    "loop": ("loop",),
    "depot_connection": ("depot_connection",),
    "other": ("other",),
    "unknown": ("other",),
}

_DASH_TRANSLATION = str.maketrans({char: "-" for char in "－—–‐‑‒﹣"})
_EXPLICIT_CODE_RE = re.compile(
    r"^\s*(\d{1,3})(?:\s*[-_.、:]\s*|\s+)(.+?)\s*$"
)
_BATCH_CODE_RE = re.compile(r"^(\d{2})(?![\d号])(.+)$")


@dataclass(frozen=True)
class ParsedStationSource:
    source_station_value: str
    source_station_key: str
    code: str
    name: str
    canonical_name: str
    source_order: int | None
    sort_order: int | None
    node_type: str
    path_code: str
    participates_in_direction: bool
    order_parse_method: str = "none"
    parse_confidence: str = "manual_review"
    parse_warning: str = ""


def normalize_station_source_value(value: Any) -> tuple[str, str]:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.translate(_DASH_TRANSLATION)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s*_\s*", "_", text)
    return text, text.casefold()


def canonical_station_name(
    value: Any,
    *,
    allow_inferred_two_digit_prefix: bool = True,
) -> str:
    text, _key = normalize_station_source_value(value)
    explicit = _EXPLICIT_CODE_RE.match(text)
    if explicit:
        text = explicit.group(2).strip()
    elif allow_inferred_two_digit_prefix:
        inferred = _BATCH_CODE_RE.match(text)
        if inferred and not inferred.group(2).startswith("号"):
            text = inferred.group(2).strip()
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def station_identity_key(name: Any, node_type: Any, path_code: Any) -> str:
    return "|".join(
        (
            "station",
            canonical_station_name(name).casefold(),
            str(node_type or "station").strip().casefold(),
            str(path_code or DEFAULT_MAIN_PATH_CODE).strip().casefold(),
        )
    )


def parse_station_source_value(
    value: Any, *, main_path_code: str = DEFAULT_MAIN_PATH_CODE
) -> ParsedStationSource:
    source_value, _source_key = normalize_station_source_value(value)
    code = ""
    name = source_value
    source_order: int | None = None
    warning = ""
    method = "none"
    confidence = "manual_review"
    match = _EXPLICIT_CODE_RE.match(source_value)
    if match:
        code = match.group(1)
        name = match.group(2).strip()
        source_order = int(code)
        method = "explicit_separator"
        confidence = "explicit"
    elif source_value:
        warning = "无法自动提取顺序"
    return _parsed_station_source(
        source_station_value=source_value,
        code=code,
        name=name,
        source_order=source_order,
        order_parse_method=method,
        parse_confidence=confidence,
        parse_warning=warning,
        main_path_code=main_path_code,
    )


def parse_station_source_values(
    values: list[Any], *, main_path_code: str = DEFAULT_MAIN_PATH_CODE
) -> dict[str, ParsedStationSource]:
    normalized = [
        normalize_station_source_value(value)
        for value in values
        if normalize_station_source_value(value)[1]
    ]
    parsed = {
        key: parse_station_source_value(value, main_path_code=main_path_code)
        for value, key in normalized
    }
    unresolved = {
        key: _BATCH_CODE_RE.match(value)
        for value, key in normalized
        if parsed[key].order_parse_method == "none"
    }
    candidates = {
        key: match
        for key, match in unresolved.items()
        if match is not None and match.group(2).strip()
    }
    numbers = [int(match.group(1)) for match in candidates.values()]
    if (
        len(candidates) >= 3
        and len(candidates) >= max(3, int(len(unresolved) * 0.8 + 0.999))
        and len(set(numbers)) == len(numbers)
        and _mostly_continuous(set(numbers))
    ):
        for key, match in candidates.items():
            code = match.group(1)
            parsed[key] = _parsed_station_source(
                source_station_value=parsed[key].source_station_value,
                code=code,
                name=match.group(2).strip(),
                source_order=int(code),
                order_parse_method="batch_inferred",
                parse_confidence="batch_inferred",
                parse_warning="",
                main_path_code=main_path_code,
            )
    return parsed


def _parsed_station_source(
    *,
    source_station_value: str,
    code: str,
    name: str,
    source_order: int | None,
    order_parse_method: str,
    parse_confidence: str,
    parse_warning: str,
    main_path_code: str,
) -> ParsedStationSource:
    canonical_name = canonical_station_name(
        name, allow_inferred_two_digit_prefix=False
    )
    node_type = infer_station_node_type(canonical_name)
    special = node_type in {"parking_lot", "depot"}
    path_code = (
        UNASSIGNED_PATH_CODE
        if special
        else (main_path_code or DEFAULT_MAIN_PATH_CODE)
    )
    return ParsedStationSource(
        source_station_value=source_station_value,
        source_station_key=station_identity_key(
            canonical_name, node_type, path_code
        ),
        code=code,
        name=canonical_name,
        canonical_name=canonical_name,
        source_order=source_order,
        sort_order=None if special else source_order,
        node_type=node_type,
        path_code=path_code,
        participates_in_direction=not special,
        order_parse_method=order_parse_method,
        parse_confidence=parse_confidence,
        parse_warning=parse_warning,
    )


def _mostly_continuous(numbers: set[int]) -> bool:
    if not numbers:
        return False
    span = max(numbers) - min(numbers) + 1
    allowed_missing = max(1, len(numbers) // 5)
    return (
        min(numbers) >= 1
        and max(numbers) <= 99
        and span - len(numbers) <= allowed_missing
    )


def infer_station_node_type(name: str) -> str:
    text = str(name or "").strip()
    if text.endswith("车辆段"):
        return "depot"
    if text.endswith("停车场"):
        return "parking_lot"
    if text.endswith("车场") and not text.endswith("车站"):
        return "parking_lot"
    return "station"


def default_station_metadata(raw: Mapping[str, Any], *, line_name: str = "", main_path_code: str = DEFAULT_MAIN_PATH_CODE) -> dict[str, Any]:
    node_type = str(raw.get("node_type") or "station")
    special = node_type in {"parking_lot", "depot"}
    turnback_capable = bool(raw.get("turnback_capable", False))
    turnback_type = str(raw.get("turnback_type") or ("unknown" if turnback_capable else "none"))
    if not turnback_capable:
        turnback_type = "none"
    path_code = str(raw.get("path_code") or (UNASSIGNED_PATH_CODE if special else main_path_code or DEFAULT_MAIN_PATH_CODE))
    structure_default, platform_default = station_structure_defaults(node_type, path_code, main_path_code)
    facilities = normalize_track_facilities(raw.get("track_facilities"), legacy_turnback_type=turnback_type)
    return {
        "source_station_value": str(raw.get("source_station_value") or ""),
        "source_station_key": str(raw.get("source_station_key") or ""),
        "node_type": node_type,
        "path_code": path_code,
        "sort_order": raw.get("sort_order"),
        "participates_in_direction": bool(raw.get("participates_in_direction", not special)),
        "structure_type": str(raw.get("structure_type") or structure_default),
        "platform_layout": str(raw.get("platform_layout") or platform_default),
        "is_line_terminal": bool(raw.get("is_line_terminal", False)),
        "is_service_terminal": bool(raw.get("is_service_terminal", False)),
        "turnback_capable": turnback_capable,
        "turnback_type": turnback_type,
        "track_facilities": facilities,
        "turnback_direction": str(raw.get("turnback_direction") or "none"),
        "enabled": bool(raw.get("enabled", True)),
        "source_kind": str(raw.get("source_kind") or "manual"),
        "line_name": str(raw.get("line_name") or line_name),
        "remark": str(raw.get("remark") or ""),
    }


def station_structure_defaults(
    node_type: Any,
    path_code: Any,
    main_path_code: Any = DEFAULT_MAIN_PATH_CODE,
) -> tuple[str, str]:
    if (
        str(node_type or "station") == "station"
        and str(path_code or "").casefold() == str(main_path_code or DEFAULT_MAIN_PATH_CODE).casefold()
    ):
        return "underground", "island"
    return "unknown", "unknown"


def normalize_track_facilities(
    value: Any,
    *,
    legacy_turnback_type: Any = "none",
) -> list[str]:
    if value is None:
        items: list[Any] = list(LEGACY_TURNBACK_FACILITIES.get(str(legacy_turnback_type or "none"), ()))
    elif isinstance(value, str):
        items = re.split(r"[、，,;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raise ValueError("轨道设施格式无效")
    reverse = {label.casefold(): key for key, label in TRACK_FACILITY_LABELS.items()}
    normalized: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text if text in TRACK_FACILITY_LABELS else reverse.get(text.casefold(), text)
        if key not in TRACK_FACILITY_LABELS:
            raise ValueError(f"轨道设施无效：{text}")
        normalized.add(key)
    return [key for key in TRACK_FACILITY_ORDER if key in normalized]


def legacy_turnback_type_for_facilities(value: Any) -> str:
    facilities = set(normalize_track_facilities(value))
    if not facilities:
        return "none"
    if facilities == {"crossover"}:
        return "crossover"
    if facilities == {"turnback_track", "storage_track"}:
        return "pocket_track"
    if facilities == {"tail_track"}:
        return "tail_track"
    if facilities == {"loop"}:
        return "loop"
    if facilities == {"depot_connection"}:
        return "depot_connection"
    if facilities == {"other"}:
        return "other"
    return "other"


def track_facilities_label(value: Any) -> str:
    return "、".join(TRACK_FACILITY_LABELS[key] for key in normalize_track_facilities(value))


def label_for(enum_map: Mapping[str, str], value: Any) -> str:
    text = str(value or "").strip()
    return enum_map.get(text, text)


def value_from_label(enum_map: Mapping[str, str], value: Any, *, default: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if text in enum_map:
        return text
    reverse = {label.casefold(): key for key, label in enum_map.items()}
    return reverse.get(text.casefold(), text)


def bool_from_template(value: Any, *, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    text = str(value).strip().casefold()
    if text in {"是", "true", "1", "yes", "y"}:
        return True
    if text in {"否", "false", "0", "no", "n"}:
        return False
    raise ValueError("布尔字段仅支持 是/否、true/false、1/0")


def bool_label(value: bool) -> str:
    return "是" if value else "否"
