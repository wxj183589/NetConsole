from __future__ import annotations

from pathlib import Path

from netconsole.models.api.rail_transit_base_data import (
    SectionDTO,
    SectionGenerationLineMetadataDTO,
    StationDTO,
)
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataRepository,
)
from netconsole.services.rail_transit.section_generation_service import (
    SectionGenerationService,
)
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


def _station(
    name: str,
    order: int,
    uid: str,
    *,
    terminal: bool = False,
    extension: bool = False,
    path_code: str = "MAIN",
    node_type: str = "station",
    participates: bool = True,
    enabled: bool = True,
    center_mileage_m: float | None = None,
    terminal_distance_m: float | None = None,
    terminal_mileage_text: str = "",
) -> StationDTO:
    return StationDTO(
        id=f"station:{uid}",
        node_uid=uid,
        name=name,
        code=str(order),
        sort_order=order,
        path_code=path_code,
        node_type=node_type,  # type: ignore[arg-type]
        participates_in_direction=participates,
        structure_type="underground",
        platform_layout="island",
        center_mileage_m=center_mileage_m,
        is_line_terminal=terminal,
        is_service_terminal=terminal,
        turnback_capable=terminal,
        track_facilities=["turnback_track"] if terminal else [],
        turnback_direction="both" if terminal else "none",
        terminal_extension_enabled=extension,
        terminal_extension_distance_m=terminal_distance_m,
        terminal_endpoint_mileage_text=terminal_mileage_text,
        enabled=enabled,
    )


def _preview(
    tmp_path: Path,
    stations: list[StationDTO],
    current: list[SectionDTO] | None = None,
):
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    return SectionGenerationService(repository).preview(
        site_id="demo",
        base_revision=repository.base_data_revision("demo"),
        line_metadata=SectionGenerationLineMetadataDTO(
            main_path_code="MAIN",
            increasing_direction_name="上行",
            decreasing_direction_name="下行",
        ),
        stations=stations,
        current_sections=current or [],
    )


def test_generates_bidirectional_sections_with_physical_pair_names(tmp_path: Path) -> None:
    result = _preview(
        tmp_path,
        [
            _station("高桥西", 11, "node-low"),
            _station("高桥", 12, "node-high"),
        ],
    )

    sections = {
        item.proposed_section.name: item.proposed_section
        for item in result.generated_sections
        if item.proposed_section
    }
    increasing = sections["高桥西-高桥-上行"]
    decreasing = sections["高桥西-高桥-下行"]
    assert (increasing.start_station, increasing.end_station) == ("高桥西", "高桥")
    assert (decreasing.start_station, decreasing.end_station) == ("高桥", "高桥西")
    assert decreasing.direction_role == "decreasing"
    assert result.create_count == 2


def test_station_order_gaps_and_rename_keep_stable_generation_key(tmp_path: Path) -> None:
    first = _preview(
        tmp_path / "first",
        [
            _station("高桥西", 11, "node-low"),
            _station("梁祝", 15, "node-high"),
        ],
    )
    renamed = _preview(
        tmp_path / "renamed",
        [
            _station("高桥西新", 11, "node-low"),
            _station("梁祝", 15, "node-high"),
        ],
    )

    first_keys = {item.proposed_section.generation_key for item in first.generated_sections if item.proposed_section}
    renamed_keys = {item.proposed_section.generation_key for item in renamed.generated_sections if item.proposed_section}
    assert first_keys == renamed_keys
    assert any(item.proposed_section and item.proposed_section.name == "高桥西新-梁祝-上行" for item in renamed.generated_sections)


def test_generates_each_path_and_skips_special_or_disabled_nodes(
    tmp_path: Path,
) -> None:
    result = _preview(
        tmp_path,
        [
            _station("主线甲", 11, "main-a"),
            _station("主线乙", 20, "main-b"),
            _station("支线甲", 1, "branch-a", path_code="BRANCH"),
            _station("支线乙", 9, "branch-b", path_code="BRANCH"),
            _station(
                "停车场",
                15,
                "parking",
                node_type="parking_lot",
                participates=True,
            ),
            _station("停用站", 16, "disabled", enabled=False),
        ],
    )

    names = {
        item.proposed_section.name
        for item in result.generated_sections
        if item.proposed_section
    }
    assert names == {
        "主线甲-主线乙-上行",
        "主线甲-主线乙-下行",
        "支线甲-支线乙-上行",
        "支线甲-支线乙-下行",
    }


def test_generates_four_distinct_terminal_extension_directions(tmp_path: Path) -> None:
    result = _preview(
        tmp_path,
        [
            _station("高桥西", 11, "node-low", terminal=True, extension=True),
            _station("高桥", 12, "node-middle"),
            _station("霞浦", 39, "node-high", terminal=True, extension=True),
        ],
    )

    terminal_items = [
        item.proposed_section
        for item in result.generated_sections
        if item.proposed_section and item.proposed_section.section_kind == "terminal_extension"
    ]
    assert {section.name for section in terminal_items} == {
        "端点-高桥西-上行",
        "端点-高桥西-下行",
        "霞浦-端点-上行",
        "霞浦-端点-下行",
    }
    low_sections = [section for section in terminal_items if "endpoint:MAIN:low" in {section.start_node_uid, section.end_node_uid}]
    high_sections = [section for section in terminal_items if "endpoint:MAIN:high" in {section.start_node_uid, section.end_node_uid}]
    assert {(section.start_station, section.end_station) for section in low_sections} == {("端点", "高桥西")}
    assert {(section.start_station, section.end_station) for section in high_sections} == {("霞浦", "端点")}
    assert all("（" not in section.start_station + section.end_station for section in terminal_items)
    endpoint_uids = {
        uid
        for section in terminal_items
        for uid in (section.start_node_uid, section.end_node_uid)
        if uid.startswith("endpoint:")
    }
    assert endpoint_uids == {"endpoint:MAIN:low", "endpoint:MAIN:high"}


def test_generates_physical_mileage_ranges_for_between_and_terminal_sections(
    tmp_path: Path,
) -> None:
    result = _preview(
        tmp_path,
        [
            _station(
                "高桥西",
                11,
                "node-low",
                terminal=True,
                extension=True,
                center_mileage_m=152,
            ),
            _station("高桥", 12, "node-middle", center_mileage_m=1801),
            _station(
                "霞浦",
                39,
                "node-high",
                terminal=True,
                extension=True,
                center_mileage_m=45574,
            ),
        ],
    )

    sections = {
        item.proposed_section.name: item.proposed_section
        for item in result.generated_sections
        if item.proposed_section
    }
    for name in ("端点-高桥西-上行", "端点-高桥西-下行"):
        section = sections[name]
        assert (section.section_mileage_start_m, section.section_mileage_end_m) == (0, 152)
        assert section.section_mileage_open_end is False
        assert section.section_mileage_source == "generated"
    for name in ("高桥西-高桥-上行", "高桥西-高桥-下行"):
        section = sections[name]
        assert (section.section_mileage_start_m, section.section_mileage_end_m) == (152, 1801)
        assert section.section_mileage_open_end is False
        assert section.section_mileage_source == "generated"
    for name in ("霞浦-端点-上行", "霞浦-端点-下行"):
        section = sections[name]
        assert section.section_mileage_start_m == 45574
        assert section.section_mileage_end_m is None
        assert section.section_mileage_open_end is True
        assert section.section_mileage_source == "generated"


def test_terminal_explicit_mileage_precedes_extension_distance(tmp_path: Path) -> None:
    result = _preview(
        tmp_path,
        [
            _station("低端", 1, "low", center_mileage_m=100),
            _station(
                "高端",
                2,
                "high",
                terminal=True,
                extension=True,
                center_mileage_m=1000,
                terminal_distance_m=200,
                terminal_mileage_text="K1+500",
            ),
        ],
    )

    terminal_sections = [
        item.proposed_section
        for item in result.generated_sections
        if item.proposed_section and item.proposed_section.section_kind == "terminal_extension"
    ]
    assert terminal_sections
    assert all(
        (section.section_mileage_start_m, section.section_mileage_end_m) == (1000, 1500)
        for section in terminal_sections
    )
    assert all(section.section_mileage_open_end is False for section in terminal_sections)


def test_missing_duplicate_and_reversed_station_mileages_warn_without_blocking_sections(
    tmp_path: Path,
) -> None:
    result = _preview(
        tmp_path,
        [
            _station("甲", 1, "a", center_mileage_m=200),
            _station("乙", 2, "b", center_mileage_m=100),
            _station("丙", 3, "c", center_mileage_m=100),
            _station("丁", 4, "d"),
        ],
    )

    sections = {
        item.proposed_section.name: item.proposed_section
        for item in result.generated_sections
        if item.proposed_section
    }
    assert (
        sections["甲-乙-上行"].section_mileage_start_m,
        sections["甲-乙-上行"].section_mileage_end_m,
    ) == (100, 200)
    assert sections["乙-丙-上行"].section_mileage_source == "unavailable"
    assert sections["丙-丁-上行"].section_mileage_source == "unavailable"
    assert result.blocking_count == 0
    assert {issue.code for issue in result.issues} >= {
        "section_generation_station_mileage_duplicate",
        "section_generation_station_mileage_reversed",
        "section_generation_mileage_unavailable",
    }


def test_regeneration_preserves_manually_overridden_physical_mileage(tmp_path: Path) -> None:
    stations = [
        _station("高桥西", 11, "node-low", center_mileage_m=160),
        _station("高桥", 12, "node-high", center_mileage_m=1801),
    ]
    current = SectionDTO(
        id="section:mileage-adjusted",
        name="高桥西-高桥-上行",
        section_kind="between_stations",
        path_code="MAIN",
        direction_role="increasing",
        line_direction="上行",
        start_node_type="station",
        start_node_uid="node-low",
        start_station="高桥西",
        end_node_type="station",
        end_node_uid="node-high",
        end_station="高桥",
        line_side="上行",
        auto_generated=True,
        generation_key="MAIN|between|node-low|node-high|increasing",
        manual_override_fields=[
            "section_mileage_start_m",
            "section_mileage_end_m",
            "section_mileage_source",
        ],
        section_mileage_start_m=155,
        section_mileage_end_m=1800,
        section_mileage_source="manual",
        source_kind="generated",
    )

    item = next(
        item
        for item in _preview(tmp_path, stations, [current]).generated_sections
        if item.current_section
    )

    assert item.proposed_section is not None
    assert (
        item.proposed_section.section_mileage_start_m,
        item.proposed_section.section_mileage_end_m,
        item.proposed_section.section_mileage_source,
    ) == (155, 1800, "manual")
    assert item.selected_by_default is False
    assert item.issues[0].code == "section_generation_manual_override"


def test_station_center_mileage_change_updates_unadjusted_generated_range(
    tmp_path: Path,
) -> None:
    current = SectionDTO(
        id="section:generated",
        name="高桥西-高桥-上行",
        section_kind="between_stations",
        path_code="MAIN",
        direction_role="increasing",
        line_direction="上行",
        start_node_type="station",
        start_node_uid="node-low",
        start_station="高桥西",
        end_node_type="station",
        end_node_uid="node-high",
        end_station="高桥",
        line_side="上行",
        auto_generated=True,
        generation_key="MAIN|between|node-low|node-high|increasing",
        section_mileage_start_m=152,
        section_mileage_end_m=1801,
        section_mileage_source="generated",
        source_kind="generated",
    )

    item = next(
        item
        for item in _preview(
            tmp_path,
            [
                _station("高桥西", 11, "node-low", center_mileage_m=160),
                _station("高桥", 12, "node-high", center_mileage_m=1801),
            ],
            [current],
        ).generated_sections
        if item.current_section
    )

    assert item.result == "UPDATE"
    assert item.selected_by_default is True
    assert item.proposed_section is not None
    assert (
        item.proposed_section.section_mileage_start_m,
        item.proposed_section.section_mileage_end_m,
    ) == (160, 1801)


def test_existing_terminal_generation_keys_are_updated_without_duplicates(tmp_path: Path) -> None:
    stations = [
        _station("高桥西", 11, "node-low", terminal=True, extension=True),
        _station("霞浦", 39, "node-high", terminal=True, extension=True),
    ]
    current = SectionDTO(
        id="section:old-low-decreasing",
        name="高桥西-端点-下行",
        section_kind="terminal_extension",
        path_code="MAIN",
        direction_role="decreasing",
        line_direction="下行",
        start_node_type="station",
        start_node_uid="node-low",
        start_station="高桥西",
        end_node_type="terminal_endpoint",
        end_node_uid="endpoint:MAIN:low",
        end_station="端点（高桥西端）",
        line_side="下行",
        auto_generated=True,
        generation_key="MAIN|terminal|endpoint:MAIN:low|node-low|decreasing",
        source_kind="generated",
    )

    result = _preview(tmp_path, stations, [current])

    matched = next(item for item in result.generated_sections if item.current_section)
    assert matched.result == "UPDATE"
    assert matched.proposed_section is not None
    assert matched.proposed_section.id == current.id
    assert matched.proposed_section.generation_key == current.generation_key
    assert matched.proposed_section.name == "端点-高桥西-下行"
    assert (matched.proposed_section.start_station, matched.proposed_section.end_station) == ("端点", "高桥西")


def test_regeneration_preserves_manual_overrides_and_updates_other_fields(tmp_path: Path) -> None:
    stations = [_station("高桥西新", 11, "node-low"), _station("高桥", 12, "node-high")]
    current = SectionDTO(
        id="section:adjusted",
        name="现场专用名称",
        section_code="AUTO-OLD",
        section_kind="between_stations",
        path_code="MAIN",
        direction_role="increasing",
        line_direction="旧上行",
        start_node_type="station",
        start_node_uid="node-low",
        start_station="高桥西",
        end_node_type="station",
        end_node_uid="node-high",
        end_station="高桥",
        line_side="旧上行",
        auto_generated=True,
        generation_key="MAIN|between|node-low|node-high|increasing",
        manual_override_fields=["name"],
        source_kind="generated",
        ap_count=3,
        mileage_min=100.0,
        mileage_max=200.0,
        remark="保留备注",
    )

    item = next(item for item in _preview(tmp_path, stations, [current]).generated_sections if item.current_section)

    assert item.result == "UPDATE"
    assert item.selected_by_default is False
    assert item.proposed_section is not None
    assert item.proposed_section.name == "现场专用名称"
    assert item.proposed_section.start_station == "高桥西新"
    assert item.proposed_section.line_direction == "上行"
    assert item.proposed_section.manual_override_fields == ["name"]
    assert item.proposed_section.auto_generated is True
    assert item.proposed_section.source_kind == "generated"
    assert (item.proposed_section.ap_count, item.proposed_section.mileage_min, item.proposed_section.mileage_max) == (3, 100.0, 200.0)
    assert item.proposed_section.remark == "保留备注"
    assert item.issues[0].code == "section_generation_manual_override"


def test_stale_adjusted_generated_section_is_retained_with_specific_warning(tmp_path: Path) -> None:
    stale = SectionDTO(
        id="section:stale-adjusted",
        name="人工保留区间",
        auto_generated=True,
        generation_key="MAIN|between|missing-a|missing-b|increasing",
        manual_override_fields=["name"],
        source_kind="generated",
    )

    item = next(item for item in _preview(tmp_path, [], [stale]).generated_sections if item.result == "STALE")

    assert item.selected_by_default is False
    assert "含人工修改" in item.issues[0].message


def test_missing_manually_overridden_node_blocks_regeneration(tmp_path: Path) -> None:
    current = SectionDTO(
        id="section:invalid-node",
        name="人工节点区间",
        section_kind="between_stations",
        path_code="MAIN",
        direction_role="increasing",
        line_direction="上行",
        start_node_type="station",
        start_node_uid="removed-node",
        start_station="已删除站",
        end_node_type="station",
        end_node_uid="node-high",
        end_station="高桥",
        line_side="上行",
        auto_generated=True,
        generation_key="MAIN|between|node-low|node-high|increasing",
        manual_override_fields=["start_node_uid", "start_station"],
        source_kind="generated",
    )

    result = _preview(
        tmp_path,
        [_station("高桥西", 11, "node-low"), _station("高桥", 12, "node-high")],
        [current],
    )
    item = next(item for item in result.generated_sections if item.current_section)

    assert item.result == "CONFLICT"
    assert item.selectable is False
    assert item.issues[0].code == "section_generation_manual_node_missing"
    assert item.issues[0].field_name == "start_node_uid"
    assert result.blocking_count == 1


def test_manual_section_is_protected_and_old_generated_section_is_stale(tmp_path: Path) -> None:
    stations = [
        _station("高桥西", 11, "node-low"),
        _station("高桥", 12, "node-high"),
    ]
    manual = SectionDTO(
        id="section:manual",
        name="高桥西-高桥-上行",
        section_kind="manual",
        path_code="MAIN",
        direction_role="increasing",
        line_direction="上行",
        start_node_type="station",
        start_node_uid="node-low",
        start_station="高桥西",
        end_node_type="station",
        end_node_uid="node-high",
        end_station="高桥",
        line_side="上行",
        source_kind="manual",
    )
    stale = SectionDTO(
        id="section:stale",
        name="旧区间-上行",
        section_kind="between_stations",
        path_code="MAIN",
        direction_role="increasing",
        line_direction="上行",
        start_node_type="station",
        start_node_uid="old-a",
        start_station="旧A",
        end_node_type="station",
        end_node_uid="old-b",
        end_station="旧B",
        line_side="上行",
        auto_generated=True,
        generation_key="MAIN|between|old-a|old-b|increasing",
        source_kind="generated",
        remark="人工备注保留",
    )

    result = _preview(tmp_path, stations, [manual, stale])

    conflict = next(item for item in result.generated_sections if item.result == "CONFLICT")
    stale_item = next(item for item in result.generated_sections if item.result == "STALE")
    assert conflict.selectable is False
    assert stale_item.selected_by_default is False
    assert stale_item.current_section.remark == "人工备注保留"


def test_duplicate_order_blocks_generation_for_path(tmp_path: Path) -> None:
    result = _preview(
        tmp_path,
        [
            _station("高桥西", 11, "node-low"),
            _station("高桥", 11, "node-high"),
        ],
    )

    assert result.blocking_count == 1
    assert not result.generated_sections
    assert result.issues[0].code == "section_generation_station_order_duplicate"
