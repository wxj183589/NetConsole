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
from netconsole.services.rail_transit.trackside_ap_location import (
    resolve_trackside_ap_location,
)
from tests.support.rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


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


def test_trackside_ap_lldp_station_suggestion_uses_exact_identity_without_write(
    tmp_path: Path,
) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    now = "2026-08-01T10:00:00+00:00"
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, ap_point_code,
                source_file, created_at, updated_at
            ) VALUES ('demo', '__base_station__', 'station:lldp', 'LLDP 建议站', '-',
                      'manual-base-data', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, ap_name, ap_point_code, ap_mac_norm,
                ap_mac_display, source_file, created_at, updated_at
            ) VALUES ('demo', 'station', 'AP-LLDP-SUGGEST', 'AP099',
                      '001122334455', '0011-2233-4455', 'point-table.xlsx', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, station, station_id, device_type,
                primary_address, created_at, updated_at
            ) VALUES ('switch-lldp', 'SW-LLDP', '旧展示站名', 'station:lldp', 'SWITCH',
                      '10.99.0.1', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO device_lldp_neighbors (
                device_uuid, local_interface, neighbor_mac, collected_at,
                collect_run_uuid, updated_at
            ) VALUES ('switch-lldp', 'GigabitEthernet1/0/9', '0011-2233-4455', ?,
                      'run-lldp', ?)
            """,
            (now, now),
        )
        connection.commit()
    ApIdentityQueryService(database).rebuild_index("test_lldp_suggestion")
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = _fingerprint(db_path)

    item = next(
        row
        for row in RailTransitBaseDataQueryService(paths)
        .list_aps("demo", page_size=200)
        .items
        if row.name == "AP-LLDP-SUGGEST"
    )

    assert item.identity_match_status == "matched"
    assert item.lldp_suggestion_status == "suggested"
    assert item.lldp_suggested_station_id == "station:lldp"
    assert item.lldp_suggested_station_name == "LLDP 建议站"
    assert item.lldp_suggestion_switch_device_id == "switch-lldp"
    assert item.lldp_suggestion_interface == "GigabitEthernet1/0/9"
    assert item.lldp_observed_neighbor_mac == "0011-2233-4455"
    assert _fingerprint(db_path) == before


def test_same_name_different_mac_does_not_report_identity_conflict(
    tmp_path: Path,
) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE ac_fit_ap_resources
            SET ap_uuid = 'ap-new',
                ap_name = 'AP-Section',
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
    section_ap = next(
        item
        for item in RailTransitBaseDataQueryService(paths)
        .list_aps("demo", page_size=500)
        .items
        if item.name == "AP-Section"
    )
    assert not any(
        item.code == "AP_IDENTITY_AC_BASE_CONFLICT"
        and (item.entity_id == section_ap.id or item.entity_name == section_ap.name)
        for item in issues.items
    )


def test_base_data_mac_mileage_filters_and_public_dto_have_no_secrets(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE ap_extension_points SET ap_vendor = 'H3C' WHERE ap_name = 'AP-Section'"
        )
        connection.commit()
    service = RailTransitBaseDataQueryService(paths)

    page = service.list_aps("demo", section="A-B", query="AP-Section", has_issue=True, page_size=200)
    invalid = service.list_issues("demo", severity="error", entity_type="ap", query="里程", page_size=200)
    payload = str(service.list_mrs("demo").model_dump()).casefold()

    assert page.total == 1
    assert page.items[0].mac == "00:00:00:00:00:02"
    assert page.items[0].vendor == "H3C"
    assert page.items[0].base_metadata["ap_vendor"] == "H3C"
    assert page.items[0].mileage.normalized == "YDK1+200"
    assert invalid.items[0].code == "ap_mileage_invalid"
    assert "private-user" not in payload
    assert "private-pass" not in payload
    assert "password" not in payload


def test_trackside_ap_location_read_compatibility_defaults_only_matched_records(
    tmp_path: Path,
) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE ap_extension_points
            SET belong_type='depot', yard_name='云龙车辆段'
            WHERE ap_name='AP-Online'
            """
        )
        connection.execute(
            "ALTER TABLE ap_extension_points DROP COLUMN location_class_source"
        )
        connection.execute(
            "ALTER TABLE ap_extension_points DROP COLUMN participates_in_mainline"
        )
        connection.execute(
            "ALTER TABLE ap_extension_points DROP COLUMN location_class"
        )
        connection.commit()

    rows = RailTransitBaseDataQueryService(paths).list_aps(
        "demo", page_size=200
    ).items
    depot = next(item for item in rows if item.name == "AP-Online")
    defaults = [item for item in rows if item.name != "AP-Online"]

    assert (
        depot.location_class,
        depot.participates_in_mainline,
        depot.location_class_source,
    ) == ("DEPOT", False, "LEGACY_INFERRED")
    assert all(
        (
            item.location_class,
            item.participates_in_mainline,
            item.location_class_source,
        )
        == ("MAINLINE", True, "DEFAULT_MAINLINE")
        for item in defaults
    )


def test_historical_null_trackside_ap_location_defaults_to_mainline() -> None:
    assert resolve_trackside_ap_location(
        {
            "location_class": None,
            "participates_in_mainline": None,
            "location_class_source": None,
            "station_name": "正线站",
        }
    ) == ("MAINLINE", True, "DEFAULT_MAINLINE")


def test_trackside_ap_query_exposes_historical_location_conflict(
    tmp_path: Path,
) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE ap_extension_points
            SET location_class='DEPOT',
                participates_in_mainline=1,
                location_class_source='EXPLICIT'
            WHERE ap_name='AP-Online'
            """
        )
        connection.commit()

    row = next(
        item
        for item in RailTransitBaseDataQueryService(paths).list_aps(
            "demo", page_size=200
        ).items
        if item.name == "AP-Online"
    )

    assert row.location_class == "DEPOT"
    assert row.participates_in_mainline is True
    assert row.location_class_conflict is True


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
            optical=SimpleNamespace(
                optical_status="normal",
                ap_rx_status="normal",
                rx_power="-17.80",
                data_freshness="fresh",
                updated_at="2026-07-24T12:00:01",
            ),
        )

    class FakeAcQuery:
        @staticmethod
        def _details() -> list[SimpleNamespace]:
            return [
                detail("fit-1", "00:00:00:00:00:01", "AC-REAL-1", "ac-1"),
                detail("fit-2a", "00-00-00-00-00-02", "AC-REAL-2A", "ac-1"),
                detail("fit-2b", "000000000002", "AC-REAL-2B", "ac-1"),
            ]

        def list_ap_details_for_macs(
            self,
            _site_id: str,
            _macs: list[str],
        ) -> list[SimpleNamespace]:
            return self._details()

        def list_all_ap_details(self, _site_id: str) -> list[SimpleNamespace]:
            return self._details()

    class EmptyMeshQuery:
        def current_link_summaries_for_ap_macs(
            self,
            _site_id: str,
            _macs: list[str],
        ) -> dict[str, dict[str, object]]:
            return {}

        def list_current_links(
            self,
            _site_id: str,
            *,
            page: int,
            page_size: int,
        ) -> SimpleNamespace:
            return SimpleNamespace(items=[])

    service = RailTransitBaseDataQueryService(paths, ac_query=FakeAcQuery(), mesh_query=EmptyMeshQuery())  # type: ignore[arg-type]
    items = service.list_aps("demo", page_size=200).items
    by_point_code = {item.point_code: item for item in items}

    assert by_point_code["AP001"].runtime.fit_ap_id == "fit-1"
    assert by_point_code["AP001"].runtime.fit_ap_ac_id == "ac-1"
    assert by_point_code["AP001"].runtime.fit_ap_name == "AC-REAL-1"
    assert by_point_code["AP001"].runtime.fit_ap_match_status == "matched"
    assert by_point_code["AP001"].runtime.ap_rx_power == "-17.80"
    assert by_point_code["AP001"].runtime.device_optical_status == "normal"
    assert by_point_code["AP001"].runtime.business_optical_status == "abnormal"
    assert by_point_code["AP001"].runtime.optical_status == "abnormal"
    assert by_point_code["AP001"].runtime.business_threshold_dbm == -13.90
    assert "-17.80 dBm 低于业务门限 -13.90 dBm" in by_point_code["AP001"].runtime.business_reason
    assert by_point_code["AP002"].runtime.fit_ap_id == ""
    assert by_point_code["AP002"].runtime.fit_ap_name == ""
    assert by_point_code["AP002"].runtime.fit_ap_match_status == "conflict"
    assert any(issue.code == "fit_ap_mac_ambiguous" for issue in service.get_ap("demo", by_point_code["AP002"].id).issues)


def test_ap_list_pages_before_runtime_and_never_calls_full_scans(
    tmp_path: Path,
) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    rows = []
    for index in range(4, 975):
        mac = f"{index:012x}"
        rows.append(
            (
                "station",
                "车站A",
                "A-B 区间",
                "车站A",
                "车站B",
                "左线",
                "下行",
                f"ZDK{index // 1000}+{index % 1000}",
                float(index),
                f"AP{index:04d}",
                f"AP-{index:04d}",
                mac,
                f"{mac[0:4]}-{mac[4:8]}-{mac[8:12]}",
                "point-table-large.xlsx",
                index,
            )
        )
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO ap_extension_points (
                site_id, line_name, system_type, network_domain, belong_type,
                station_name, section_name, section_start_station,
                section_end_station, line_side, direction, mileage_text,
                mileage_m, ap_point_code, ap_name, ap_mac_norm,
                ap_mac_display, source_file, source_sheet, source_row,
                created_at, updated_at
            ) VALUES (
                'demo', '测试线', 'PIS', 'default', ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, 'AP', ?, '2026-07-31', '2026-07-31'
            )
            """,
            rows,
        )
        connection.executemany(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, source_file, source_sheet, source_row,
                created_at, updated_at
            ) VALUES (
                'demo', 'station', 'placeholder.xlsx', 'AP', ?,
                '2026-07-31', '2026-07-31'
            )
            """,
            [(index,) for index in range(1, 5)],
        )
        connection.commit()

    class PageAcQuery:
        calls: list[list[str]] = []

        def list_ap_details_for_macs(
            self,
            _site_id: str,
            macs: list[str],
        ) -> list[SimpleNamespace]:
            self.calls.append(list(macs))
            return []

        def list_all_ap_details(self, _site_id: str) -> list[SimpleNamespace]:
            raise AssertionError("AP 列表不得调用全量 FIT-AP 详情")

    class PageMeshQuery:
        calls: list[list[str]] = []

        def current_link_summaries_for_ap_macs(
            self,
            _site_id: str,
            macs: list[str],
        ) -> dict[str, dict[str, object]]:
            self.calls.append(list(macs))
            return {}

        def list_current_links(self, *_args, **_kwargs) -> SimpleNamespace:
            raise AssertionError("AP 列表不得构建全量 MESH 链路")

    ac_query = PageAcQuery()
    mesh_query = PageMeshQuery()
    service = RailTransitBaseDataQueryService(
        paths,
        ac_query=ac_query,
        mesh_query=mesh_query,
    )  # type: ignore[arg-type]
    service._issues = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("AP 列表不得执行全局质量扫描")
    )

    page = service.list_aps("demo", page=1, page_size=50)

    assert page.total == 974
    assert len(page.items) == 50
    assert [len(macs) for macs in ac_query.calls] == [50]
    assert [len(macs) for macs in mesh_query.calls] == [50]


def test_ap_list_mac_query_accepts_exact_h3c_radio_alias(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE ap_extension_points
            SET ap_vendor = 'H3C',
                ap_mac_norm = '000000000020',
                ap_mac_display = '0000-0000-0020'
            WHERE ap_name = 'AP-Online'
            """
        )
        connection.commit()
    ApIdentityQueryService(Database(db_path)).rebuild_index("test_radio_alias")

    page = RailTransitBaseDataQueryService(paths).list_aps(
        "demo",
        query="0000-0000-002f",
        page_size=50,
    )

    assert page.total == 1
    assert page.items[0].name == "AP-Online"
    assert page.items[0].mac == "00:00:00:00:00:20"


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
