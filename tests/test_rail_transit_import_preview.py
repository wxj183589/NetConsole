from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3

from openpyxl import Workbook

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_import_preview_sanitizes_json_and_cleans_temporary_files(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    temp_root = tmp_path / "preview-temp"
    service = RailTransitImportPreviewService(RailTransitBaseDataQueryService(paths), temp_root=temp_root)
    tasks_db = paths.site_tasks_db_path("demo")
    before = _fingerprint(db_path)
    payload = json.dumps(
        [
            {
                "ap_name": "AP-Preview",
                "ap_mac_display": "0011-2233-4455",
                "section_name": "A-B 区间",
                "mileage_text": "ZDK1+300",
                "line_side": "左线",
                "username": "must-not-return",
                "password": "must-not-return",
                "token": "must-not-return",
            }
        ],
        ensure_ascii=False,
    ).encode("utf-8")

    result = service.preview(site_id="demo", file_name="preview.json", content=payload, content_type="application/json")

    assert result.total_rows == 1
    assert result.valid_rows == 1
    assert result.message == "当前仅支持校验和合并预览。正式写入功能默认关闭。"
    assert result.merge_plan is not None
    assert result.merge_plan.summary.create_count == 1
    assert result.write_enabled is False
    text = str(result.model_dump()).casefold()
    assert "must-not-return" not in text
    assert "password" not in text
    assert _fingerprint(db_path) == before
    assert not tasks_db.exists()
    assert not temp_root.exists() or not any(temp_root.iterdir())


def test_import_preview_supports_existing_csv_template_without_persistence(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    temp_root = tmp_path / "preview-temp"
    service = RailTransitImportPreviewService(RailTransitBaseDataQueryService(paths), temp_root=temp_root)
    content = "AP名称,AP MAC,归属区间,线别,里程\nAP-X,0011-2233-44ZZ,A-B 区间,右线,ZDK1+100\n".encode("utf-8-sig")
    before = _fingerprint(db_path)

    result = service.preview(site_id="demo", file_name="preview.csv", content=content, content_type="text/csv")

    assert result.total_rows == 1
    assert result.error_count >= 1
    assert any(issue.code in {"invalid_mac", "ap_mac_invalid"} for issue in result.rows[0].issues)
    assert any(issue.code == "mileage_direction_mismatch" for issue in result.rows[0].issues)
    assert _fingerprint(db_path) == before
    assert not temp_root.exists() or not any(temp_root.iterdir())


def test_import_preview_accepts_ap_switch_port_table_and_skips_placeholders(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitImportPreviewService(RailTransitBaseDataQueryService(paths), temp_root=tmp_path / "preview-temp")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "轨旁AP业务"
    sheet.append(["归属站点", "室内交换机", "接口名称", "AP_MAC", "AP名称", "区间", "AP编号"])
    sheet.append(["11-高桥西", "11-高桥西1", "GE1/0/1", "1c94-6876-8ee0", "1c94-6876-8ee0", "高桥西-高桥-上行", "AP0127"])
    sheet.append(["11-高桥西", "11-高桥西1", "GE1/0/2", "-", "-", "", ""])
    content = BytesIO()
    workbook.save(content)
    before = _fingerprint(db_path)

    result = service.preview(
        site_id="demo",
        file_name="AP点表宁波1.xlsx",
        content=content.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert result.template_type == "ap_switch_port_point_table"
    assert result.total_rows == 2
    assert result.valid_rows == 1
    assert result.error_count == 1
    assert result.sheet_names == ["轨旁AP业务"]
    assert result.statistics == {
        "valid_ap_rows": 1,
        "placeholder_rows": 1,
        "section_rows": 1,
        "without_section_rows": 1,
        "missing_mileage_rows": 1,
        "unmatched_fit_ap_rows": 1,
        "up_direction_rows": 1,
        "down_direction_rows": 0,
        "importable_rows": 1,
        "warning_rows": 2,
        "conflict_rows": 0,
        "invalid_rows": 1,
    }
    assert result.merge_plan is not None
    assert result.merge_plan.summary.create_count == 1
    assert result.merge_plan.summary.invalid_count == 1
    assert result.merge_plan.items[0].source_values["ap_name"] == ""
    assert result.merge_plan.items[0].source_values["ap_point_code"] == "AP0127"
    assert result.merge_plan.items[0].source_values["uplink_switch"] == "11-高桥西1"
    assert json.loads(result.merge_plan.items[0].source_values["raw_payload_json"]) == {
        "import_source": {"station_name": "11-高桥西"},
        "line_side_source": "unavailable",
    }
    assert result.merge_plan.items[1].result == "INVALID"
    assert result.merge_plan.items[1].issues[0].code == "ap_mac_placeholder"
    assert _fingerprint(db_path) == before


def test_import_preview_derives_line_side_and_warns_on_explicit_conflict(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    section_metadata = {
        "section_code": "SEC-UP",
        "section_kind": "between_stations",
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
            ) VALUES ('demo', '__base_section__', '高桥西-高桥-上行', '高桥西',
                      '高桥', '', '-', 'manual-base-data', ?, '2026-07-25', '2026-07-25')
            """,
            (json.dumps(section_metadata, ensure_ascii=False),),
        )
        connection.commit()
    service = RailTransitImportPreviewService(RailTransitBaseDataQueryService(paths))
    content = json.dumps(
        [
            {
                "ap_name": "AP-AUTO",
                "ap_mac_display": "0011-2233-4491",
                "section_name": "高桥西-高桥-上行",
            },
            {
                "ap_name": "AP-CONFLICT",
                "ap_mac_display": "0011-2233-4492",
                "section_name": "高桥西-高桥-上行",
                "line_side": "左线",
            },
        ],
        ensure_ascii=False,
    ).encode("utf-8")

    result = service.preview(
        site_id="demo",
        file_name="line-side.json",
        content=content,
        content_type="application/json",
    )

    assert result.rows[0].values["line_side"] == "右线"
    assert json.loads(result.rows[0].values["raw_payload_json"])["line_side_source"] == "section_direction"
    assert result.rows[1].values["line_side"] == "左线"
    conflict = next(issue for issue in result.rows[1].issues if issue.code == "ap_line_side_section_conflict")
    assert conflict.blocking is False


def test_import_preview_allows_624_offline_trackside_aps_without_fit_ap_runtime(tmp_path: Path) -> None:
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    service = RailTransitImportPreviewService(RailTransitBaseDataQueryService(paths))
    rows = [
        {
            "ap_name": "",
            "ap_point_code": f"OFFLINE-{index:04d}",
            "ap_mac_display": f"aa00{index:08x}",
            "station_name": "车站A",
            "section_name": "A-B 区间",
            "mileage_text": f"ZDK{index}+000",
        }
        for index in range(1, 625)
    ]

    result = service.preview(
        site_id="demo",
        file_name="offline-trackside.json",
        content=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )

    assert result.merge_plan is not None
    assert result.merge_plan.summary.create_count == 624
    assert result.merge_plan.summary.importable_count == 624
    assert result.merge_plan.summary.invalid_count == 0
    assert result.merge_plan.summary.conflict_count == 0
    assert result.merge_plan.summary.unmatched_fit_ap_count == 624
    assert result.merge_plan.summary.blocking_count == 0
    assert all(
        not issue.blocking
        for item in result.merge_plan.items
        for issue in item.issues
        if issue.code == "fit_ap_unmatched"
    )
