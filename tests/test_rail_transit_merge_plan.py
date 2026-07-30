from __future__ import annotations

import sqlite3
from pathlib import Path

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.models.api.rail_transit_base_data import ImportPreviewRowDTO
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.repositories.rail_transit_base_data_repository import RailTransitBaseDataRepository


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
            _row(3, ap_point_code="AP001"),
            _row(4, ap_point_code="AP002", ap_mac_norm="000000000099"),
            _row(5),
        ],
    )

    assert [item.result for item in plan.items] == [
        "CREATE",
        "UPDATE",
        "UNCHANGED",
        "CONFLICT",
        "INVALID",
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


def test_merge_plan_uses_point_code_identity_and_keeps_empty_fields_out_of_update(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataImportService(paths)
    plan = service.build_merge_plan(
        site_id="demo",
        source_file_name="AP点表宁波1.xlsx",
        source_file_sha256="b" * 64,
        rows=[
            _row(2, ap_name="", ap_point_code="AP0127", ap_mac_norm="1c9468768ee0", mileage_text="", remark=""),
            _row(3, ap_name="", ap_point_code="", ap_mac_display="-"),
        ],
    )

    assert plan.items[0].result == "CREATE"
    assert plan.items[0].source_identity["ap_name"] == "AP0127"
    assert not any(diff.field_name in {"mileage_text", "remark"} for diff in plan.items[0].field_diffs)
    assert plan.items[1].result == "INVALID"


def test_merge_plan_imports_valid_rows_and_skips_only_identity_conflicts(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataImportService(paths)
    plan = service.build_merge_plan(
        site_id="demo",
        source_file_name="partial.xlsx",
        source_file_sha256="c" * 64,
        rows=[
            _row(1, ap_point_code="NEW-01", ap_mac_norm="001122334401"),
            _row(2, ap_point_code="NEW-02", ap_mac_norm="001122334402"),
            _row(3, ap_point_code="AP002", ap_mac_norm="001122334403"),
            _row(4, ap_point_code="NEW-04", ap_mac_display="invalid"),
        ],
    )

    assert [item.result for item in plan.items] == [
        "CREATE",
        "CREATE",
        "CONFLICT",
        "INVALID",
    ]
    assert plan.summary.importable_count == 2
    assert plan.summary.conflict_count == 1
    assert plan.summary.invalid_count == 1


def test_merge_plan_deduplicates_identical_rows_and_conflicts_only_related_rows(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitBaseDataImportService(paths)
    plan = service.build_merge_plan(
        site_id="demo",
        source_file_name="duplicates.xlsx",
        source_file_sha256="d" * 64,
        rows=[
            _row(1, ap_point_code="NEW-01", ap_mac_norm="001122334411", station_name="A站"),
            _row(2, ap_point_code="NEW-01", ap_mac_norm="001122334411", station_name="A站"),
            _row(3, ap_point_code="NEW-03", ap_mac_norm="001122334413"),
            _row(4, ap_point_code="NEW-04", ap_mac_norm="001122334413"),
            _row(5, ap_point_code="NEW-05", ap_mac_norm="001122334415"),
            _row(6, ap_point_code="NEW-05", ap_mac_norm="001122334416"),
            _row(7, ap_point_code="NEW-07", ap_mac_norm="001122334417"),
        ],
    )

    assert [item.result for item in plan.items] == [
        "CREATE",
        "UNCHANGED",
        "CONFLICT",
        "CONFLICT",
        "CONFLICT",
        "CONFLICT",
        "CREATE",
    ]
    assert plan.summary.importable_count == 3
    assert plan.summary.unchanged_count == 1
    assert plan.summary.conflict_count == 4


def test_repository_row_savepoint_keeps_other_import_rows(tmp_path: Path, monkeypatch) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    original = repository._apply_operation

    def flaky_apply(connection, site_id, operation_id, operation):
        if operation.get("row_number") == 2:
            raise sqlite3.IntegrityError("simulated row failure")
        return original(connection, site_id, operation_id, operation)

    monkeypatch.setattr(repository, "_apply_operation", flaky_apply)
    changes, failures = repository.apply_operations_partially(
        "demo",
        "operation-1",
        [
            {
                "kind": "create",
                "row_number": 1,
                "values": {"ap_point_code": "SAVEPOINT-1", "ap_mac_display": "aa00-0000-0101"},
            },
            {
                "kind": "create",
                "row_number": 2,
                "values": {"ap_point_code": "SAVEPOINT-2", "ap_mac_display": "aa00-0000-0102"},
            },
            {
                "kind": "create",
                "row_number": 3,
                "values": {"ap_point_code": "SAVEPOINT-3", "ap_mac_display": "aa00-0000-0103"},
            },
        ],
    )

    assert [change["row_number"] for change in changes] == [1, 3]
    assert failures == [{"row_number": 2, "kind": "create", "error_type": "IntegrityError"}]
    point_codes = sorted(
        row["ap_point_code"]
        for row in repository.list_ap_records("demo")
        if str(row["ap_point_code"]).startswith("SAVEPOINT-")
    )
    assert point_codes == ["SAVEPOINT-1", "SAVEPOINT-3"]
