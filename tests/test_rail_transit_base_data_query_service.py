from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from netconsole.models.api.rail_transit_base_data import SectionDTO
from netconsole.core.database import Database
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


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
    assert all(item.manual_override_fields == [] for item in sections.items)
    assert all(item.section_mileage_source == "unavailable" for item in sections.items)
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
    assert {"ap_mac_duplicate", "ap_mileage_invalid", "mr_train_unbound", "section_mileage_unavailable"} <= codes
    assert _fingerprint(db_path) == before


def test_data_quality_reports_ac_base_identity_conflict_without_blocking(
    tmp_path: Path,
) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE ac_fit_ap_resources
            SET ap_name = 'AP-Section',
                ap_mac = 'aabb-ccdd-eeff',
                updated_at = '2026-07-31T00:00:00+00:00'
            WHERE ap_uuid = 'ap-offline'
            """
        )
        connection.commit()
    ApIdentityQueryService(database).rebuild_index("test_sources_saved")

    issues = RailTransitBaseDataQueryService(paths).list_issues(
        "demo",
        page_size=500,
    )
    conflict = next(
        item
        for item in issues.items
        if item.code == "AP_IDENTITY_AC_BASE_CONFLICT"
        and item.field_name == "mac"
    )

    assert conflict.severity == "warning"
    assert conflict.blocking is False
    assert conflict.field_name == "mac"
    assert conflict.original_value == "0000-0000-0002"
    assert "aabb-ccdd-eeff" in conflict.message


def test_base_data_mac_mileage_filters_and_public_dto_have_no_secrets(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataQueryService(paths)

    page = service.list_aps("demo", section="A-B", query="AP-Section", has_issue=True, page_size=200)
    invalid = service.list_issues("demo", severity="error", entity_type="ap", query="里程", page_size=200)
    payload = str(service.list_mrs("demo").model_dump()).casefold()

    assert page.total == 1
    assert page.items[0].mac == "00:00:00:00:00:02"
    assert page.items[0].mileage.normalized == "YDK1+200"
    assert invalid.items[0].code == "ap_mileage_invalid"
    assert "private-user" not in payload
    assert "private-pass" not in payload
    assert "password" not in payload


def test_query_non_destructively_completes_empty_line_side_from_formal_section(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    metadata = {
        "section_code": "SEC-UP",
        "section_kind": "between_stations",
        "path_code": "MAIN",
        "direction_role": "increasing",
        "line_direction": "上行",
        "start_node_type": "legacy",
        "end_node_type": "legacy",
        "source_kind": "manual",
    }
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, section_name, section_start_station,
                section_end_station, line_side, ap_point_code, source_file,
                raw_payload_json, created_at, updated_at
            ) VALUES ('demo', '__base_section__', ?, '高桥西', '高桥', '', '-',
                      'manual-base-data', ?, '2026-07-25', '2026-07-25')
            """,
            ("高桥西-高桥-上行", json.dumps(metadata, ensure_ascii=False)),
        )
        connection.execute(
            """
            UPDATE ap_extension_points
            SET section_name = '高桥西-高桥-上行', line_side = '', raw_payload_json = '{}'
            WHERE ap_name = 'AP-Section'
            """
        )
        connection.commit()
    before = _fingerprint(db_path)

    ap = next(
        item
        for item in RailTransitBaseDataQueryService(paths).list_aps("demo", page_size=200).items
        if item.name == "AP-Section"
    )

    assert (ap.line_side, ap.line_side_source) == ("右线", "section_direction")
    assert ap.base_metadata["section_code"] == "SEC-UP"
    assert ap.line_side_derivation_issue_code == ""
    assert _fingerprint(db_path) == before


def test_trackside_ap_runtime_uses_unique_mac_and_marks_ambiguous_matches(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)

    def detail(ap_id: str, mac: str, name: str, ac_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            ap=SimpleNamespace(
                id=ap_id,
                ac_id=ac_id,
                mac=mac,
                name=name,
                status="online",
                updated_at="2026-07-24T12:00:00",
                ip="192.0.2.10",
                model="WA6638",
            ),
            radios=[],
            optical=SimpleNamespace(optical_status="normal"),
        )

    class FakeAcQuery:
        def list_all_ap_details(self, _site_id: str) -> list[SimpleNamespace]:
            return [
                detail("fit-1", "00:00:00:00:00:01", "AC-REAL-1", "ac-1"),
                detail("fit-2a", "00-00-00-00-00-02", "AC-REAL-2A", "ac-1"),
                detail("fit-2b", "000000000002", "AC-REAL-2B", "ac-1"),
            ]

    class EmptyMeshQuery:
        def list_current_links(self, _site_id: str, *, page: int, page_size: int) -> SimpleNamespace:
            return SimpleNamespace(items=[])

    service = RailTransitBaseDataQueryService(paths, ac_query=FakeAcQuery(), mesh_query=EmptyMeshQuery())  # type: ignore[arg-type]
    items = service.list_aps("demo", page_size=200).items
    by_point_code = {item.point_code: item for item in items}

    assert by_point_code["AP001"].runtime.fit_ap_id == "fit-1"
    assert by_point_code["AP001"].runtime.fit_ap_ac_id == "ac-1"
    assert by_point_code["AP001"].runtime.fit_ap_name == "AC-REAL-1"
    assert by_point_code["AP001"].runtime.fit_ap_match_status == "matched"
    assert by_point_code["AP002"].runtime.fit_ap_id == ""
    assert by_point_code["AP002"].runtime.fit_ap_name == ""
    assert by_point_code["AP002"].runtime.fit_ap_match_status == "conflict"
    assert any(issue.code == "fit_ap_mac_ambiguous" for issue in service.get_ap("demo", by_point_code["AP002"].id).issues)


def test_section_quality_reports_invalid_physical_mileage_shapes(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataQueryService(paths)
    sections = [
        SectionDTO(
            id="section:reversed",
            name="倒置范围",
            section_mileage_start_m=200,
            section_mileage_end_m=100,
            section_mileage_source="manual",
        ),
        SectionDTO(
            id="section:ordinary-open",
            name="普通开放范围",
            section_kind="between_stations",
            section_mileage_start_m=100,
            section_mileage_open_end=True,
            section_mileage_source="manual",
        ),
    ]

    issues = service._section_issues(sections, [])

    invalid_ids = {
        issue.entity_id
        for issue in issues
        if issue.code == "section_mileage_range_invalid"
    }
    assert invalid_ids == {"section:reversed", "section:ordinary-open"}
