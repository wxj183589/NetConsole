from pathlib import Path

from openpyxl import Workbook

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_extension_import import (
    AP_NAME_MAC_LIST,
    PIS_LAYOUT_TABLE,
    SIGNAL_AB_NETWORK_TABLE,
    ApExtensionImportService,
    normalize_ap_mac,
    parse_mileage,
    standard_export_row,
    standard_template_headers,
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
    assert parse_mileage("ZDK0+035").meters == 35
    assert parse_mileage("YDK1+020").meters == 1020
    assert parse_mileage("CDK1+170").meters == 1170
    assert parse_mileage("RDK12+345").meters == 12345
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


def test_standard_export_row_formats_mileage_with_line_prefix():
    row = {
        "station_name": "金家渡",
        "line_side": "左线",
        "direction": "下行",
        "mileage_text": "K0+035",
        "mileage_m": 35,
    }

    values = standard_export_row(row)
    headers = list(standard_template_headers())

    assert values[headers.index("里程原文")] == "ZDK0+035"
    assert values[headers.index("里程米")] == 35


def test_preview_signal_ab_network_sheet_recognizes_section_and_yard(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "A网"
    sheet.append(["3.中医药大学", "", "", "", "3.中医药大学", "", ""])
    sheet.append(["", "", "", "", "", "ap0201_a", "5866-bab3-1111"])
    sheet.append(["4.联庄", "", "", "", "4.联庄", "", ""])
    sheet.append(["", "", "", "", "", "ap0303_a", "5866-bab3-0a40"])
    sheet.append(["88.勾庄车辆段(库内）", "ap8841_a", "4ce9-e4ef-7b80", "", "", "", ""])
    sheet.append(["90.七堡停车场（库内）", "ap8020_a", "4ce9-e4f1-29a0", "", "", "", ""])
    path = tmp_path / "杭4AP布点表 - 副本A.xlsx"
    workbook.save(path)

    preview = ApExtensionImportService().preview_file(path, "smart_design")
    rows = {row["ap_name"]: row for row in preview.standard_rows}

    assert preview.template_type == SIGNAL_AB_NETWORK_TABLE
    assert rows["ap0303_a"]["line_name"] == "杭州地铁4号线"
    assert rows["ap0303_a"]["system_type"] == "信号"
    assert rows["ap0303_a"]["network_domain"] == "A网"
    assert rows["ap0303_a"]["belong_type"] == "section"
    assert rows["ap0303_a"]["station_name"] == ""
    assert rows["ap0303_a"]["section_name"] == "联庄-中医药大学"
    assert rows["ap0303_a"]["section_start_station"] == "中医药大学"
    assert rows["ap0303_a"]["section_end_station"] == "联庄"
    assert rows["ap8841_a"]["belong_type"] == "yard"
    assert rows["ap8841_a"]["station_name"] == "勾庄车辆段"
    assert rows["ap8841_a"]["yard_name"] == "勾庄车辆段"
    assert rows["ap8841_a"]["area_name"] == "库内"
    assert rows["ap8020_a"]["station_name"] == "七堡停车场"


def test_preview_signal_b_network_sheet_keeps_network_domain(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "B网"
    sheet.append(["3.中医药大学", "", "", "", "3.中医药大学", "", ""])
    sheet.append(["4.联庄", "", "", "", "4.联庄", "", ""])
    sheet.append(["", "", "", "", "", "ap0303_b", "5866-bab2-77c0"])
    path = tmp_path / "杭4AP布点表 - 副本b.xlsx"
    workbook.save(path)

    preview = ApExtensionImportService().preview_file(path, "smart_design")

    assert preview.template_type == SIGNAL_AB_NETWORK_TABLE
    assert preview.standard_rows[0]["network_domain"] == "B网"
    assert preview.standard_rows[0]["ap_name"] == "ap0303_b"
    assert preview.standard_rows[0]["section_name"] == "联庄-中医药大学"


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
                "belong_type": "station",
                "ap_name": "AP-01",
                "ap_mac_display": "4c:e9:e4:ef:5c:20",
                "power_station": "金家渡变电所",
            },
            {
                "belong_type": "section",
                "section_name": "联庄-中医药大学",
                "section_start_station": "中医药大学",
                "section_end_station": "联庄",
                "ap_name": "AP-02",
                "ap_mac_display": "5866-bab3-0a40",
            },
        ],
        source_file="design.xlsx",
        template_type=PIS_LAYOUT_TABLE,
    )

    assert stats["success_rows"] == 3
    rows = repository.list_ap_extension_points()
    assert {row["match_status"] for row in rows} == {"unbound_no_mac", "matched_by_mac", "extension_not_online"}
    section_row = next(row for row in rows if row["ap_name"] == "AP-02")
    assert section_row["belong_type"] == "section"
    assert section_row["section_name"] == "联庄-中医药大学"
    resource = repository.list_fit_ap_resources_with_metadata("ac-1")[0]
    assert resource["extension_station_name"] == "金家渡"
    assert resource["extension_belong_type"] == "station"
    assert resource["extension_power_station"] == "金家渡变电所"
    assert resource["site"] in (None, "")


def test_repository_extension_search_matches_prefixed_mileage(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.import_ap_extension_points(
        [
            {
                "station_name": "金家渡",
                "line_side": "左线",
                "direction": "下行",
                "mileage_text": "K0+035",
                "mileage_m": 35,
                "ap_point_code": "Z01-01",
            }
        ],
        source_file="design.xlsx",
        template_type=PIS_LAYOUT_TABLE,
    )

    rows = repository.list_ap_extension_points(search="ZDK0+035")

    assert len(rows) == 1
    assert rows[0]["ap_point_code"] == "Z01-01"
