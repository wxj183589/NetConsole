from __future__ import annotations

from pathlib import Path

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


def test_quality_issues_group_by_entity_and_keep_warning_semantics(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataQueryService(paths)
    groups = service.list_issue_groups("demo", page=1, page_size=200)

    duplicate = next(group for group in groups.items if group.display_name == "AP-Duplicate")
    assert duplicate.blocking is True
    assert {issue.code for issue in duplicate.issues} >= {"ap_mac_duplicate", "ap_mileage_invalid"}
    assert next(issue for issue in duplicate.issues if issue.code == "ap_mac_duplicate").blocking is True
    assert next(issue for issue in duplicate.issues if issue.code == "ap_mileage_invalid").blocking is False
    section = next(item for item in service.list_aps("demo", page_size=200).items if item.name == "AP-Section")
    assert not any(issue.code == "ap_location_missing" for issue in service.get_ap("demo", section.id).issues)


def test_missing_formal_ap_identity_is_warning_not_blocking(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with __import__("sqlite3").connect(db_path) as connection:
        connection.execute("UPDATE ap_extension_points SET ap_name = '', ap_mac_norm = '', ap_mac_display = '' WHERE id = 2")
        connection.commit()
    service = RailTransitBaseDataQueryService(paths)
    group = next(item for item in service.list_issue_groups("demo", page_size=200).items if item.entity_id == "ap:2")

    assert {issue.code for issue in group.issues} >= {"ap_name_missing", "ap_mac_missing"}
    assert all(issue.severity == "warning" for issue in group.issues if issue.code in {"ap_name_missing", "ap_mac_missing"})
    assert group.blocking is False
