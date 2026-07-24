from __future__ import annotations

import pytest

from netconsole.models.api.rail_transit_base_data import SectionDTO
from netconsole.services.rail_transit.ap_line_side_service import derive_ap_line_side


def _section(
    name: str,
    role: str,
    direction: str,
    *,
    start: str = "高桥西",
    end: str = "高桥",
    code: str = "",
    generation_key: str = "",
) -> SectionDTO:
    return SectionDTO(
        id=f"section:{name}",
        name=name,
        section_code=code,
        direction_role=role,  # type: ignore[arg-type]
        line_direction=direction,
        start_node_type="station",
        start_station=start,
        end_node_type="station",
        end_station=end,
        generation_key=generation_key,
        enabled=True,
        source_kind="generated",
    )


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        (_section("高桥西-高桥-上行", "increasing", "上行"), "右线"),
        (_section("高桥西-高桥-下行", "decreasing", "下行"), "左线"),
        (
            _section(
                "端点-高桥西-上行",
                "increasing",
                "上行",
                start="端点",
                end="高桥西",
            ),
            "右线",
        ),
        (
            _section(
                "霞浦-端点-下行",
                "decreasing",
                "下行",
                start="霞浦",
                end="端点",
            ),
            "左线",
        ),
    ],
)
def test_formal_section_direction_derives_line_side(section: SectionDTO, expected: str) -> None:
    result = derive_ap_line_side({"section": section.name}, [section])

    assert result.line_side == expected
    assert result.source == "section_direction"
    assert result.issue_code == ""


def test_section_direction_source_is_recalculated_after_section_change() -> None:
    up = _section("高桥西-高桥-上行", "increasing", "上行", code="UP")
    down = _section("高桥西-高桥-下行", "decreasing", "下行", code="DOWN")

    result = derive_ap_line_side(
        {
            "section": down.name,
            "line_side": "右线",
            "base_metadata": {"line_side_source": "section_direction", "section_code": "DOWN"},
        },
        [up, down],
    )

    assert result.line_side == "左线"
    assert result.source == "section_direction"


def test_manual_line_side_is_not_overwritten() -> None:
    section = _section("高桥西-高桥-上行", "increasing", "上行")

    result = derive_ap_line_side(
        {
            "section": section.name,
            "line_side": "左线",
            "base_metadata": {"line_side_source": "manual"},
        },
        [section],
    )

    assert result.line_side == "左线"
    assert result.source == "manual"
    assert result.issue_code == "ap_line_side_section_conflict"


def test_legacy_value_is_preserved_and_empty_value_is_completed() -> None:
    section = _section("高桥西-高桥-上行", "increasing", "上行")

    existing = derive_ap_line_side(
        {"section": section.name, "line_side": "右线"},
        [section],
    )
    missing = derive_ap_line_side({"section": section.name, "line_side": ""}, [section])

    assert (existing.line_side, existing.source) == ("右线", "legacy")
    assert (missing.line_side, missing.source) == ("右线", "section_direction")


def test_import_conflict_is_reported_without_silent_override() -> None:
    section = _section("高桥西-高桥-上行", "increasing", "上行")

    result = derive_ap_line_side(
        {"section": section.name, "line_side": "左线"},
        [section],
        imported_line_side=True,
    )

    assert result.line_side == "左线"
    assert result.source == "import"
    assert result.issue_code == "ap_line_side_section_conflict"


def test_same_station_pair_never_matches_the_other_direction() -> None:
    up = _section("高桥西-高桥-上行", "increasing", "上行", code="UP")
    down = _section("高桥西-高桥-下行", "decreasing", "下行", code="DOWN")

    result = derive_ap_line_side(
        {
            "section": "旧区间名称-下行",
            "section_start_station": "高桥西",
            "section_end_station": "高桥",
            "direction": "下行",
        },
        [up, down],
    )

    assert result.matched_section is down
    assert result.line_side == "左线"


def test_site_mapping_can_be_reversed() -> None:
    section = _section("高桥西-高桥-上行", "increasing", "上行")

    result = derive_ap_line_side(
        {"section": section.name},
        [section],
        {
            "increasing_direction_name": "上行",
            "decreasing_direction_name": "下行",
            "increasing_direction_line_side": "左线",
            "decreasing_direction_line_side": "右线",
        },
    )

    assert result.line_side == "左线"


def test_ambiguous_formal_section_does_not_guess() -> None:
    first = _section("高桥西-高桥-上行", "increasing", "上行")
    second = first.model_copy(update={"id": "section:duplicate"})

    result = derive_ap_line_side({"section": first.name}, [first, second])

    assert result.line_side == ""
    assert result.issue_code == "ap_line_side_section_ambiguous"


def test_changed_unknown_section_name_does_not_reuse_stale_section_identity() -> None:
    section = _section("高桥西-高桥-上行", "increasing", "上行", code="UP")

    result = derive_ap_line_side(
        {
            "section": "尚未建模区间-上行",
            "line_side": "右线",
            "base_metadata": {
                "line_side_source": "section_direction",
                "section_name": section.name,
                "section_code": "UP",
            },
        },
        [section],
    )

    assert result.matched_section is None
    assert result.line_side == "右线"
    assert result.issue_code == "ap_line_side_section_unmatched"
