from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
