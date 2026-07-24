from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path

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
    assert result.error_count == 0
    assert result.sheet_names == ["轨旁AP业务"]
    assert result.statistics == {
        "valid_ap_rows": 1,
        "placeholder_rows": 1,
        "section_rows": 1,
        "without_section_rows": 1,
        "missing_mileage_rows": 1,
        "up_direction_rows": 1,
        "down_direction_rows": 0,
    }
    assert result.merge_plan is not None
    assert result.merge_plan.summary.create_count == 1
    assert result.merge_plan.summary.skip_count == 1
    assert result.merge_plan.items[0].source_values["ap_name"] == ""
    assert result.merge_plan.items[0].source_values["ap_point_code"] == "AP0127"
    assert result.merge_plan.items[0].source_values["uplink_switch"] == "11-高桥西1"
    assert json.loads(result.merge_plan.items[0].source_values["raw_payload_json"]) == {
        "import_source": {"station_name": "11-高桥西"}
    }
    assert result.merge_plan.items[1].issues[0].code == "ap_mac_placeholder"
    assert _fingerprint(db_path) == before
