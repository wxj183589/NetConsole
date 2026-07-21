from __future__ import annotations

import re

from netconsole.utils.mileage import parse_track_mileage


EMPTY_VALUES = {"", "-", "--", "n/a", "na", "none", "null", "unknown", "未知", "无"}
_MAC_COLON_OR_HYPHEN = re.compile(r"^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
_MAC_DOTTED = re.compile(r"^(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4}$")
_MAC_H3C_HYPHEN = re.compile(r"^(?:[0-9a-fA-F]{4}-){2}[0-9a-fA-F]{4}$")
_MAC_PLAIN = re.compile(r"^[0-9a-fA-F]{12}$")


def normalize_mac(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    if not (
        _MAC_COLON_OR_HYPHEN.fullmatch(text)
        or _MAC_DOTTED.fullmatch(text)
        or _MAC_H3C_HYPHEN.fullmatch(text)
        or _MAC_PLAIN.fullmatch(text)
    ):
        return None
    compact = re.sub(r"[-:.]", "", text).casefold()
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def normalize_ap_name(value: object) -> str | None:
    text = _clean_text(value)
    return re.sub(r"\s+", " ", text) if text is not None else None


def is_mac_like(value: object) -> bool:
    return normalize_mac(value) is not None


def same_mac(left: object, right: object) -> bool:
    left_mac = normalize_mac(left)
    right_mac = normalize_mac(right)
    return bool(left_mac and right_mac and left_mac == right_mac)


def normalize_mileage(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    parsed = parse_track_mileage(text.replace("!", ""))
    return parsed.display if parsed.meters is not None else None


def parse_line_direction(value: object) -> tuple[str | None, str | None]:
    text = _clean_text(value)
    if text is None:
        return None, None
    compact = re.sub(r"[!\s_:\-/]", "", text).upper()
    if compact.startswith("ZDK") or text in {"左线", "左", "下行", "下"}:
        return "左线", "下行"
    if compact.startswith("YDK") or text in {"右线", "右", "上行", "上"}:
        return "右线", "上行"
    if compact.startswith("CDK") or text in {"出段线", "出段", "出库线"}:
        return "出段线", "出段"
    if compact.startswith("RDK") or text in {"入段线", "入段", "入库线"}:
        return "入段线", "入段"
    return None, None


def normalize_identifier(value: object) -> str | None:
    return _clean_text(value)


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in EMPTY_VALUES else text
