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
        is_line_terminal=terminal,
        is_service_terminal=terminal,
        turnback_capable=terminal,
        track_facilities=["turnback_track"] if terminal else [],
        turnback_direction="both" if terminal else "none",
        terminal_extension_enabled=extension,
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
        "高桥西-端点-下行",
        "霞浦-端点-上行",
        "端点-霞浦-下行",
    }
    endpoint_uids = {
        uid
        for section in terminal_items
        for uid in (section.start_node_uid, section.end_node_uid)
        if uid.startswith("endpoint:")
    }
    assert endpoint_uids == {"endpoint:MAIN:low", "endpoint:MAIN:high"}


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
