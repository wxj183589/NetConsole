from __future__ import annotations

import json
import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from netconsole.core.sources.ap_extension_import import ApExtensionImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService
from netconsole.services.rail_transit.station_import_match import resolve_station_import_match
from netconsole.services.trackside_ap_base_export import (
    TRACKSIDE_AP_BASE_COLUMNS,
    export_trackside_ap_base_xlsx_task,
)
from tests.support.rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


def _station(
    station_id: str,
    name: str,
    *,
    site_id: str = "",
    source_kind: str = "manual",
) -> dict[str, str]:
    return {
        "id": station_id,
        "name": name,
        "canonical_station_name": name,
        "source_station_value": name,
        "source_kind": source_kind,
        "site_id": site_id,
    }


@pytest.mark.parametrize("source_name", ["11观音塘", "观音塘", "观音塘站"])
def test_station_matching_accepts_numbered_and_station_suffix_variants(source_name: str) -> None:
    result = resolve_station_import_match(
        {"station_name": source_name},
        [_station("station:guanyintang", "观音塘站")],
    )

    assert result.status == "resolved"
    assert result.station_id == "station:guanyintang"


def test_station_matching_honors_explicit_id_and_blocks_name_conflict() -> None:
    stations = [_station("station:a", "观音塘站"), _station("station:b", "钱江路站")]

    resolved = resolve_station_import_match(
        {"station_id": "station:a", "station_name": "观音塘站"}, stations
    )
    conflict = resolve_station_import_match(
        {"station_id": "station:a", "station_name": "钱江路"}, stations
    )

    assert resolved.status == "resolved"
    assert resolved.station_id == "station:a"
    assert conflict.status == "ambiguous"
    assert conflict.method == "station_id_name_conflict"


def test_station_matching_reports_ambiguity_and_missing_without_guessing() -> None:
    ambiguous = resolve_station_import_match(
        {"station_name": "观音塘"},
        [_station("station:a", "观音塘站"), _station("station:b", "观音塘")],
    )
    missing = resolve_station_import_match(
        {"station_name": "不存在站"},
        [_station("station:a", "观音塘站")],
    )

    assert ambiguous.status == "ambiguous"
    assert missing.status == "missing"


def test_station_matching_filters_explicit_other_site() -> None:
    result = resolve_station_import_match(
        {"site_id": "hzdt-09", "station_name": "观音塘"},
        [_station("station:other", "观音塘站", site_id="other-site")],
    )

    assert result.status == "missing"


def test_trackside_base_export_has_seven_round_trip_columns(tmp_path: Path) -> None:
    output = tmp_path / "trackside-ap.xlsx"
    count = export_trackside_ap_base_xlsx_task(
        output,
        {
            "draft_rows": [
                {
                    "name": "AP-STATIC-001",
                    "mac": "00:11:22:33:44:55",
                    "station": "观音塘站",
                    "uplink_switch": "SW-01",
                    "uplink_port": "GigabitEthernet1/0/10",
                    "build_phase": "一期",
                    "location_class": "MAINLINE",
                    "runtime": {"fit_ap_name": "FIT-AP-RUNTIME-NAME"},
                }
            ]
        },
    )

    workbook = load_workbook(output, read_only=True, data_only=True)
    sheet = workbook["轨旁AP"]
    headers = [cell.value for cell in next(sheet.iter_rows())]
    values = [cell.value for cell in next(sheet.iter_rows(min_row=2, max_row=2))]
    workbook.close()

    assert count >= 1
    assert headers == [title for title, _key in TRACKSIDE_AP_BASE_COLUMNS]
    assert headers == ["AP名称", "AP MAC", "归属位置", "上联交换机", "上联端口", "建设阶段", "位置类型"]
    assert values == ["AP-STATIC-001", "00:11:22:33:44:55", "观音塘站", "SW-01", "GigabitEthernet1/0/10", "一期", "正线"]

    parsed = ApExtensionImportService().preview_file(output)
    row = parsed.sheets[0].rows[0]
    assert row["ap_name"] == "AP-STATIC-001"
    assert row["station_name"] == "观音塘站"
    assert row["uplink_port"] == "GigabitEthernet1/0/10"
    assert row["location_class"] == "正线"


def test_seven_column_import_resolves_station_id_before_merge(tmp_path: Path) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, ap_point_code,
                raw_payload_json, source_file, created_at, updated_at
            ) VALUES ('demo', '__base_station__', 'station:guanyintang', '观音塘站', '-', ?,
                      'manual-base-data', '2026-11-16', '2026-11-16')
            """,
            (json.dumps({"sort_order": 11, "node_type": "station"}, ensure_ascii=False),),
        )
        connection.commit()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "轨旁AP"
    sheet.append(["AP名称", "AP MAC", "归属位置", "上联交换机", "上联端口", "建设阶段", "位置类型"])
    sheet.append(["AP-IMPORT-001", "00:11:22:33:44:66", "11观音塘", "SW-01", "GigabitEthernet1/0/10", "一期", "正线"])
    content = BytesIO()
    workbook.save(content)

    result = RailTransitImportPreviewService(
        RailTransitBaseDataQueryService(paths), temp_root=tmp_path / "preview-temp"
    ).preview(
        site_id="demo",
        file_name="trackside-ap-7-column.xlsx",
        content=content.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    row = result.rows[0]
    assert result.template_type == "trackside_ap_base_template"
    assert row.values["station_id"] == "station:guanyintang"
    assert row.values["station_name"] == "观音塘站"
    assert row.values["_station_match_status"] == "resolved"
    assert row.values["build_phase"] == "一期"
    assert row.values["uplink_port"] == "GigabitEthernet1/0/10"
    assert result.merge_plan is not None
    assert result.merge_plan.items[0].station_match_status == "resolved"


def test_seven_column_export_reimport_keeps_yard_rows_importable(tmp_path: Path) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM ap_extension_points WHERE belong_type != '__base_station__'"
        )
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, ap_name,
                ap_mac_norm, ap_mac_display, uplink_switch, uplink_port,
                location_class, participates_in_mainline, raw_payload_json,
                created_at, updated_at
            ) VALUES
                ('demo', 'station', 'station:guanyintang', '观音塘站', 'AP-MAIN',
                 '001122334401', '00:11:22:33:44:01', 'SW-01', 'GigabitEthernet1/0/1',
                 'MAINLINE', 1, '{}', '2026-11-16', '2026-11-16'),
                ('demo', 'depot', '', '昌达车辆段', 'AP-DEPOT',
                 '001122334402', '00:11:22:33:44:02', 'SW-02', 'GigabitEthernet1/0/2',
                 'DEPOT', 0, '{}', '2026-11-16', '2026-11-16'),
                ('demo', 'parking_yard', '', '四堡停车场', 'AP-PARKING',
                 '001122334403', '00:11:22:33:44:03', 'SW-03', 'GigabitEthernet1/0/3',
                 'PARKING_YARD', 0, '{}', '2026-11-16', '2026-11-16')
            """
        )
        connection.commit()
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, raw_payload_json,
                created_at, updated_at
            ) VALUES ('demo', '__base_station__', 'station:guanyintang', '观音塘站',
                      ?, '2026-11-16', '2026-11-16')
            """,
            (json.dumps({"sort_order": 11, "node_type": "station"}, ensure_ascii=False),),
        )
        connection.commit()

    exported = tmp_path / "trackside-ap-yard-round-trip.xlsx"
    export_trackside_ap_base_xlsx_task(
        exported,
        {"app_root": str(paths.app_root), "data_root": str(paths.data_root), "site_id": "demo"},
    )
    result = RailTransitImportPreviewService(
        RailTransitBaseDataQueryService(paths), temp_root=tmp_path / "preview-temp"
    ).preview(
        site_id="demo",
        file_name=exported.name,
        content=exported.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert result.total_rows == 3
    exported_rows = {
        row.values["ap_name"]: row
        for row in result.rows
        if row.values["ap_name"] in {"AP-MAIN", "AP-DEPOT", "AP-PARKING"}
    }
    assert len(exported_rows) == 3
    assert result.statistics["invalid_rows"] == 0
    assert result.statistics["importable_rows"] == result.total_rows
    assert result.merge_plan is not None
    assert all(item.result == "UNCHANGED" for item in result.merge_plan.items)
    assert exported_rows["AP-MAIN"].values["station_id"] == "station:guanyintang"
    assert exported_rows["AP-DEPOT"].values["station_id"] == ""
    assert exported_rows["AP-PARKING"].values["station_id"] == ""
    assert not any(
        issue.blocking
        for name in ("AP-DEPOT", "AP-PARKING")
        for issue in exported_rows[name].issues
    )


def test_seven_column_export_reimport_preserves_section_only_ap(tmp_path: Path) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, section_id, section_name,
                section_start_station, section_end_station, source_file,
                created_at, updated_at
            ) VALUES ('demo', '__base_section__', 'section:ab', 'A-B 区间',
                      '车站A', '车站B', 'manual-base-data', '2026-11-16', '2026-11-16')
            """
        )
        connection.execute(
            """
            UPDATE ap_extension_points
            SET section_id = 'section:ab'
            WHERE ap_name = 'AP-Section'
            """
        )
        connection.commit()

    exported = tmp_path / "trackside-ap-section-round-trip.xlsx"
    export_trackside_ap_base_xlsx_task(
        exported,
        {"app_root": str(paths.app_root), "data_root": str(paths.data_root), "site_id": "demo"},
    )
    workbook = load_workbook(exported, read_only=True, data_only=True)
    sheet = workbook["轨旁AP"]
    exported_rows = {
        row[0].value: [cell.value for cell in row]
        for row in sheet.iter_rows(min_row=2)
    }
    workbook.close()
    assert exported_rows["AP-Section"][2] == "A-B 区间"

    result = RailTransitImportPreviewService(
        RailTransitBaseDataQueryService(paths), temp_root=tmp_path / "preview-temp"
    ).preview(
        site_id="demo",
        file_name=exported.name,
        content=exported.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    imported = next(row for row in result.rows if row.values["ap_name"] == "AP-Section")
    assert imported.values["station_name"] == ""
    assert imported.values["section_id"] == "section:ab"
    assert imported.values["section_name"] == "A-B 区间"
    assert not any(issue.code == "station_location_required" for issue in imported.issues)
    assert not any(issue.blocking for issue in imported.issues)


def test_seven_column_export_with_field_notes_round_trips_only_data_rows(tmp_path: Path) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, raw_payload_json,
                created_at, updated_at
            ) VALUES ('demo', '__base_station__', 'station:guanyintang', '观音塘站', ?,
                      '2026-11-16', '2026-11-16')
            """,
            (json.dumps({"sort_order": 11, "node_type": "station"}, ensure_ascii=False),),
        )
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name, ap_name, ap_mac_norm,
                ap_mac_display, raw_payload_json, created_at, updated_at
            ) VALUES ('demo', 'station', 'station:guanyintang', '观音塘站', 'AP-STATIC-001',
                      '001122334455', '00:11:22:33:44:55', ?, '2026-11-16', '2026-11-16')
            """,
            (
                json.dumps(
                    {
                        "sort_order": 11,
                        "node_type": "station",
                        "uplink_switch": "SW-01",
                        "uplink_port": "GigabitEthernet1/0/10",
                        "build_phase": "一期",
                        "location_class": "MAINLINE",
                        "participates_in_mainline": True,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        connection.commit()

    exported = tmp_path / "trackside-ap-export-with-field-notes.xlsx"
    export_trackside_ap_base_xlsx_task(
        exported,
        {"app_root": str(paths.app_root), "data_root": str(paths.data_root), "site_id": "demo"},
    )
    result = RailTransitImportPreviewService(
        RailTransitBaseDataQueryService(paths), temp_root=tmp_path / "preview-temp"
    ).preview(
        site_id="demo",
        file_name=exported.name,
        content=exported.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert result.template_type == "trackside_ap_base_template"
    assert result.total_rows == 4  # Three fixture rows plus the exported AP.
    imported = next(row for row in result.rows if row.values["ap_name"] == "AP-STATIC-001")
    assert imported.values["station_id"] == "station:guanyintang"
