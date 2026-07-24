from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


DEFAULT_INCREASING_DIRECTION_NAME = "上行"
DEFAULT_DECREASING_DIRECTION_NAME = "下行"
DEFAULT_INCREASING_DIRECTION_LINE_SIDE = "右线"
DEFAULT_DECREASING_DIRECTION_LINE_SIDE = "左线"
LINE_SIDE_SOURCES = {"section_direction", "manual", "import", "legacy", "unavailable"}


@dataclass(frozen=True)
class LineSideConfig:
    increasing_direction_name: str = DEFAULT_INCREASING_DIRECTION_NAME
    decreasing_direction_name: str = DEFAULT_DECREASING_DIRECTION_NAME
    increasing_direction_line_side: str = DEFAULT_INCREASING_DIRECTION_LINE_SIDE
    decreasing_direction_line_side: str = DEFAULT_DECREASING_DIRECTION_LINE_SIDE

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> LineSideConfig:
        source = values or {}
        return cls(
            increasing_direction_name=str(
                source.get("increasing_direction_name") or DEFAULT_INCREASING_DIRECTION_NAME
            ).strip(),
            decreasing_direction_name=str(
                source.get("decreasing_direction_name") or DEFAULT_DECREASING_DIRECTION_NAME
            ).strip(),
            increasing_direction_line_side=str(
                source.get("increasing_direction_line_side")
                or DEFAULT_INCREASING_DIRECTION_LINE_SIDE
            ).strip(),
            decreasing_direction_line_side=str(
                source.get("decreasing_direction_line_side")
                or DEFAULT_DECREASING_DIRECTION_LINE_SIDE
            ).strip(),
        )

    def side_for_role(self, role: str) -> str:
        if role == "increasing":
            return self.increasing_direction_line_side
        if role == "decreasing":
            return self.decreasing_direction_line_side
        return ""

    def role_for_direction(self, direction: object) -> str:
        value = _normalized_text(direction)
        if not value:
            return "unknown"
        if value == _normalized_text(self.increasing_direction_name):
            return "increasing"
        if value == _normalized_text(self.decreasing_direction_name):
            return "decreasing"
        if value == _normalized_text(DEFAULT_INCREASING_DIRECTION_NAME):
            return "increasing"
        if value == _normalized_text(DEFAULT_DECREASING_DIRECTION_NAME):
            return "decreasing"
        return "unknown"


@dataclass(frozen=True)
class ApLineSideDerivation:
    line_side: str
    source: str
    matched_section: Any | None = None
    issue_code: str = ""
    issue_message: str = ""

    @property
    def section_code(self) -> str:
        return str(_value(self.matched_section, "section_code") or "")

    @property
    def section_generation_key(self) -> str:
        return str(_value(self.matched_section, "generation_key") or "")


def derive_ap_line_side(
    ap: Mapping[str, Any],
    sections: Iterable[Any],
    site_metadata: Mapping[str, Any] | None = None,
    *,
    imported_line_side: bool = False,
) -> ApLineSideDerivation:
    config = LineSideConfig.from_mapping(site_metadata)
    metadata = ap.get("base_metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    current = str(ap.get("line_side") or "").strip()
    source = str(metadata.get("line_side_source") or "").strip()
    if source not in LINE_SIDE_SOURCES:
        source = "legacy" if current else "unavailable"
    if imported_line_side and current:
        source = "import"

    match, match_issue = match_formal_section(ap, sections, config)
    if match is None:
        return ApLineSideDerivation(
            line_side=current,
            source=source,
            issue_code=match_issue,
            issue_message=(
                "无法唯一匹配正式区间，线路方向保持原值"
                if match_issue == "ap_line_side_section_ambiguous"
                else "找不到对应的正式区间，无法自动推导线路方向"
                if match_issue
                else ""
            ),
        )

    role = section_direction_role(match, config)
    expected = config.side_for_role(role)
    if not expected:
        return ApLineSideDerivation(
            line_side=current,
            source=source,
            matched_section=match,
            issue_code="ap_line_side_direction_unavailable",
            issue_message="正式区间缺少可识别的结构化方向，无法自动推导线路方向",
        )

    if current and source in {"manual", "import", "legacy"}:
        if _normalized_text(current) != _normalized_text(expected):
            return ApLineSideDerivation(
                line_side=current,
                source=source,
                matched_section=match,
                issue_code="ap_line_side_section_conflict",
                issue_message=f"现有线路方向“{current}”与区间推导值“{expected}”不一致",
            )
        return ApLineSideDerivation(current, source, match)

    return ApLineSideDerivation(expected, "section_direction", match)


def match_formal_section(
    ap: Mapping[str, Any],
    sections: Iterable[Any],
    config: LineSideConfig,
) -> tuple[Any | None, str]:
    candidates = [section for section in sections if bool(_value(section, "enabled", True))]
    if not str(ap.get("section") or ap.get("section_name") or "").strip():
        return None, ""
    metadata = ap.get("base_metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    section_name = _normalized_section_name(ap.get("section") or ap.get("section_name"))
    name_matches = [
        section
        for section in candidates
        if section_name and _normalized_section_name(_value(section, "name")) == section_name
    ]
    if len(name_matches) > 1:
        return None, "ap_line_side_section_ambiguous"

    metadata_section_name = _normalized_section_name(metadata.get("section_name"))
    identity_matches_current_name = not metadata_section_name or metadata_section_name == section_name
    identities = (
        ("id", metadata.get("section_id")),
        ("section_code", metadata.get("section_code")),
        (
            "generation_key",
            metadata.get("section_generation_key") or metadata.get("generation_key"),
        ),
    )
    for field, identity in identities if identity_matches_current_name else ():
        normalized = _normalized_text(identity)
        if not normalized:
            continue
        matches = [
            section
            for section in candidates
            if _normalized_text(_value(section, field)) == normalized
        ]
        if len(matches) == 1:
            if len(name_matches) == 1 and name_matches[0] is not matches[0]:
                return name_matches[0], ""
            return matches[0], ""
        if len(matches) > 1:
            return None, "ap_line_side_section_ambiguous"

    if len(name_matches) == 1:
        return name_matches[0], ""

    start = _normalized_text(ap.get("section_start_station"))
    end = _normalized_text(ap.get("section_end_station"))
    requested_role = config.role_for_direction(ap.get("direction"))
    if requested_role == "unknown":
        requested_role = _role_from_name(section_name, config)
    if start and end and requested_role in {"increasing", "decreasing"}:
        matches = [
            section
            for section in candidates
            if _normalized_text(_value(section, "start_station")) == start
            and _normalized_text(_value(section, "end_station")) == end
            and section_direction_role(section, config) == requested_role
        ]
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, "ap_line_side_section_ambiguous"
        endpoint_pair = {start, end}
        matches = [
            section
            for section in candidates
            if {
                _normalized_text(_value(section, "start_station")),
                _normalized_text(_value(section, "end_station")),
            }
            == endpoint_pair
            and section_direction_role(section, config) == requested_role
        ]
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, "ap_line_side_section_ambiguous"

    return None, "ap_line_side_section_unmatched"


def section_direction_role(section: Any, config: LineSideConfig) -> str:
    role = str(_value(section, "direction_role") or "").strip().casefold()
    line_direction_role = config.role_for_direction(_value(section, "line_direction"))
    if line_direction_role in {"increasing", "decreasing"}:
        return line_direction_role
    if role in {"increasing", "decreasing"}:
        return role
    return _role_from_name(_value(section, "name"), config)


def line_side_metadata(
    metadata: Mapping[str, Any] | None,
    derivation: ApLineSideDerivation,
) -> dict[str, Any]:
    result = dict(metadata or {})
    result["line_side_source"] = derivation.source
    if derivation.matched_section is not None:
        section_id = str(_value(derivation.matched_section, "id") or "")
        if section_id:
            result["section_id"] = section_id
        section_name = str(_value(derivation.matched_section, "name") or "")
        if section_name:
            result["section_name"] = section_name
        if derivation.section_code:
            result["section_code"] = derivation.section_code
        if derivation.section_generation_key:
            result["section_generation_key"] = derivation.section_generation_key
    return result


def _role_from_name(value: object, config: LineSideConfig) -> str:
    text = _normalized_section_name(value)
    for direction, role in (
        (config.increasing_direction_name, "increasing"),
        (config.decreasing_direction_name, "decreasing"),
        (DEFAULT_INCREASING_DIRECTION_NAME, "increasing"),
        (DEFAULT_DECREASING_DIRECTION_NAME, "decreasing"),
    ):
        suffix = _normalized_text(direction)
        if suffix and text.endswith(f"-{suffix}"):
            return role
    return "unknown"


def _normalized_section_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = text.translate(str.maketrans({"—": "-", "–": "-", "－": "-"}))
    return re.sub(r"\s+", "", text)


def _normalized_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _value(source: Any, field: str, default: Any = "") -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(field, default)
    return getattr(source, field, default)


__all__ = [
    "ApLineSideDerivation",
    "DEFAULT_DECREASING_DIRECTION_LINE_SIDE",
    "DEFAULT_INCREASING_DIRECTION_LINE_SIDE",
    "LineSideConfig",
    "derive_ap_line_side",
    "line_side_metadata",
    "match_formal_section",
    "section_direction_role",
]
