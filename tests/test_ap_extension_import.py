from pathlib import Path

from openpyxl import Workbook

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_extension_import import (
    AP_NAME_MAC_LIST,
    PIS_LAYOUT_TABLE,
    ApExtensionImportService,
    normalize_ap_mac,
    parse_mileage,
)


def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def test_normalize_ap_mac_accepts_common_formats():
    assert normalize_ap_mac("4ce9-e4ef-5c20").normalized == "4ce9e4ef5c20"
    assert normalize_ap_mac("4c:e9:e4:ef:5c:20").normalized == "4ce9e4ef5c20"
    assert normalize_ap_mac("4ce9.e4ef.5c20").normalized == "4ce9e4ef5c20"
    assert normalize_ap_mac("4ce9e4ef5c20").display == "4ce9-e4ef-5c20"
    assert normalize_ap_mac("bad-mac").error == "MAC格式无效"


def test_parse_mileage_keeps_raw_and_parses_common_forms():
    assert parse_mileage("K6+491").meters == 6491
    assert parse_mileage("DK6+491").meters == 6491
    assert parse_mileage("AK0+207.267").meters == 207.267
    assert parse_mileage("6491").meters == 6491
    assert parse_mileage("bad").raw == "bad"
    assert parse_mileage("bad").meters is None
    assert parse_mileage("bad").error == "里程无法解析"


def test_preview_pis_left_right_layout_without_mac(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "PIS点位表"
    sheet.append(["车站", "轨旁AP归属区间", "左线里程", "右线里程", "距上一个AP", "曲线半径", "曲线开始", "曲线终点", "AP编号", "备注"])
    sheet.append(["金家渡", "金家渡-墩祥街", "K6+491", "", "90", "450", "K6+300", "K6+700", "Z01-01", "左线点位"])
    sheet.append(["金家渡", "金家渡-墩祥街", "", "K6+580", "95", "", "", "", "Y01-01", "右线点位"])
    path = tmp_path / "pis.xlsx"
    workbook.save(path)

    preview = ApExtensionImportService().preview_file(path, "smart_design")

    assert preview.template_type == PIS_LAYOUT_TABLE
    assert preview.confidence_score >= 60
    assert preview.summary["missing_mac_rows"] == 2
    assert preview.standard_rows[0]["line_side"] == "左线"
    assert preview.standard_rows[0]["direction"] == "下行"
    assert preview.standard_rows[0]["mileage_m"] == 6491
    assert preview.standard_rows[0]["curve_radius_m"] == 450
    assert preview.standard_rows[1]["line_side"] == "右线"
    assert preview.standard_rows[1]["direction"] == "上行"


def test_preview_ap_name_mac_list_uses_segment_title(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "AP清单"
    sheet.append(["32.金家渡"])
    sheet.append(["AP名称", "MAC"])
    sheet.append(["JJD-AP-01", "4c:e9:e4:ef:5c:20"])
    path = tmp_path / "mac-list.xlsx"
    workbook.save(path)

    preview = ApExtensionImportService().preview_file(path, "smart_design")

    assert preview.template_type == AP_NAME_MAC_LIST
    row = preview.standard_rows[0]
    assert row["station_name"] == "金家渡"
    assert row["ap_name"] == "JJD-AP-01"
    assert row["ap_mac_norm"] == "4ce9e4ef5c20"


def test_preview_scans_multiple_sheets(tmp_path):
    workbook = Workbook()
    workbook.active.title = "说明"
    workbook.active.append(["无数据"])
    sheet = workbook.create_sheet("AP清单")
    sheet.append(["AP名称", "MAC"])
    sheet.append(["AP-01", "4ce9-e4ef-5c20"])
    path = tmp_path / "multi.xlsx"
    workbook.save(path)

    preview = ApExtensionImportService().preview_file(path, "smart_design")

    assert [sheet.sheet_name for sheet in preview.sheets] == ["AP清单"]
    assert preview.summary["total_rows"] == 1


def test_repository_imports_unbound_points_and_matches_resources_by_mac(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "AP-01", "ap_mac": "4ce9-e4ef-5c20"}])
    stats = repository.import_ap_extension_points(
        [
            {
                "station_name": "金家渡",
                "line_side": "左线",
                "direction": "下行",
                "mileage_text": "K6+491",
                "mileage_m": 6491,
                "ap_point_code": "Z01-01",
            },
            {
                "station_name": "金家渡",
                "ap_name": "AP-01",
                "ap_mac_display": "4c:e9:e4:ef:5c:20",
                "power_station": "金家渡变电所",
            },
        ],
        source_file="design.xlsx",
        template_type=PIS_LAYOUT_TABLE,
    )

    assert stats["success_rows"] == 2
    rows = repository.list_ap_extension_points()
    assert {row["match_status"] for row in rows} == {"unbound_no_mac", "matched_by_mac"}
    resource = repository.list_fit_ap_resources_with_metadata("ac-1")[0]
    assert resource["extension_station_name"] == "金家渡"
    assert resource["extension_power_station"] == "金家渡变电所"
    assert resource["site"] in (None, "")
