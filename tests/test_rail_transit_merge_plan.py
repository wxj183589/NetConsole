from __future__ import annotations

from pathlib import Path

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.models.api.rail_transit_base_data import ImportPreviewRowDTO
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


def _row(row_number: int, **values: object) -> ImportPreviewRowDTO:
    return ImportPreviewRowDTO(row_number=row_number, values=values)


def test_merge_plan_distinguishes_create_update_unchanged_and_conflict(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataImportService(paths)
    plan = service.build_merge_plan(
        site_id="demo",
        source_file_name="official.xlsx",
        source_file_sha256="a" * 64,
        rows=[
            _row(1, ap_name="AP-New", ap_mac_norm="001122334499", station_name="车站A"),
            _row(2, ap_name="AP-Section", ap_mac_norm="000000000002", uplink_switch="SW-01"),
            _row(3, ap_name="AP-Section", ap_mac_norm="000000000002", section_name="A-B 区间"),
            _row(4, ap_name="AP-Online", ap_mac_norm="000000000099"),
            _row(5),
        ],
    )

    assert [item.result for item in plan.items] == [
        "CREATE",
        "UPDATE",
        "UNCHANGED",
        "CONFLICT",
        "SKIP",
    ]
    assert plan.items[1].field_diffs[0].action == "fill_missing"
    assert plan.items[3].blocking is True
    assert plan.write_enabled is False


def test_section_without_station_is_valid_and_quality_groups_are_entity_scoped(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    query = RailTransitBaseDataQueryService(paths)
    issues = query.list_issues("demo", page=1, page_size=200).items
    groups = query.list_issue_groups("demo", page=1, page_size=200)

    section_ap = next(item for item in query.list_aps("demo", page_size=200).items if item.name == "AP-Section")
    assert not any(issue.entity_id == section_ap.id and issue.code == "ap_location_missing" for issue in issues)
    duplicate_group = next(group for group in groups.items if group.display_name == "AP-Duplicate")
    assert duplicate_group.issue_count >= 2
    assert duplicate_group.blocking is True
    assert groups.total < groups.issue_total
