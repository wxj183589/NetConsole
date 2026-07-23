from __future__ import annotations

import hashlib
from pathlib import Path

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_base_data_queries_relations_and_quality_are_read_only(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataQueryService(paths)
    before = _fingerprint(db_path)

    summary = service.get_summary("demo")
    stations = service.list_stations("demo")
    sections = service.list_sections("demo")
    aps = service.list_aps("demo", page=1, page_size=2, sort_by="mileage")
    ap_locations = service.list_ap_location_items("demo")
    mrs = service.list_mrs("demo")
    trains = service.list_trains("demo")
    issues = service.list_issues("demo", page_size=200)

    assert summary.station_count == 3
    assert summary.section_count == 3
    assert summary.ap_count == 3
    assert summary.train_count == 1
    assert summary.mr_count == 2
    assert stations.total == 3
    assert sections.total == 3
    assert aps.total == 3
    assert len(aps.items) == 2
    assert len(ap_locations) == 3
    assert {item.name for item in ap_locations} == {
        item.name for item in service.list_aps("demo", page_size=200).items
    }
    assert any(not item.station and item.section == "A-B 区间" for item in service.list_aps("demo", page_size=200).items)
    assert [item.role for item in mrs.items] == ["CT", "CW"]
    assert [(item.mr_position_code, item.physical_end, item.car_number) for item in mrs.items] == [
        ("CT", "car_1_end", 1),
        ("CW", "car_6_end", 6),
    ]
    assert summary.increasing_direction_leading_end == "unknown"
    assert trains.items[0].mr_count == 2
    codes = {item.code for item in issues.items}
    assert {"ap_mac_duplicate", "ap_mileage_invalid", "static_ip_duplicate", "mr_train_unbound"} <= codes
    assert _fingerprint(db_path) == before


def test_base_data_mac_mileage_filters_and_public_dto_have_no_secrets(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataQueryService(paths)

    page = service.list_aps("demo", section="A-B", has_issue=False, page_size=200)
    invalid = service.list_issues("demo", severity="error", entity_type="ap", query="里程", page_size=200)
    payload = str(service.list_mrs("demo").model_dump()).casefold()

    assert page.total == 1
    assert page.items[0].mac == "00:00:00:00:00:02"
    assert page.items[0].mileage.normalized == "YDK1+200"
    assert invalid.items[0].code == "ap_mileage_invalid"
    assert "private-user" not in payload
    assert "private-pass" not in payload
    assert "password" not in payload
