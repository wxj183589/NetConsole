from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.core.database import Database
from netconsole.services.ac.fit_ap_resource_export import (
    export_fit_ap_resource_xlsx,
    make_fit_ap_resource_filename,
)


def _export(
    tmp_path: Path,
    *,
    scope: str,
    selected_ap_ids: list[str] | None = None,
    filters: dict[str, str] | None = None,
) -> tuple[Path, dict[str, int]]:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    output = tmp_path / f"{scope}.xlsx"
    result = export_fit_ap_resource_xlsx(
        output,
        {
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "site_name": "demo",
            "ac_uuid": "ac-1",
            "scope": scope,
            "selected_ap_ids": selected_ap_ids or [],
            "filters": filters or {},
            "requested_at": "2026-07-29T00:42:15+08:00",
        },
    )
    return output, result


def test_fit_ap_resource_export_keeps_one_ap_per_row_and_radio_details(tmp_path: Path) -> None:
    output, result = _export(tmp_path, scope="all")
    workbook = load_workbook(output, data_only=True)

    assert result == {"row_count": 3, "ap_count": 3, "radio_count": 6, "warning_count": 1}
    assert workbook.sheetnames == ["AP资源清单", "Radio明细", "导出说明"]
    ap_sheet = workbook["AP资源清单"]
    radio_sheet = workbook["Radio明细"]
    assert ap_sheet.max_row == 4
    assert radio_sheet.max_row == 7
    assert ap_sheet.freeze_panes == "A2"
    assert radio_sheet.freeze_panes == "A2"
    assert ap_sheet.auto_filter.ref
    assert not ap_sheet.merged_cells.ranges

    headers = {cell.value: cell.column for cell in ap_sheet[1]}
    ap_names = [ap_sheet.cell(row, headers["AP名称"]).value for row in range(2, ap_sheet.max_row + 1)]
    assert len(ap_names) == len(set(ap_names)) == 3
    sort_rows = [
        tuple(str(ap_sheet.cell(row, headers[name]).value or "") for name in ("归属站点", "归属区间", "点位编号", "AP名称", "AP MAC"))
        for row in range(2, ap_sheet.max_row + 1)
    ]
    assert sort_rows == sorted(
        sort_rows,
        key=lambda row: tuple((not bool(value), value.casefold()) for value in row[:3]) + (row[3].casefold(), row[4].casefold()),
    )
    assert ap_sheet.cell(2, headers["AP IP"]).number_format == "@"
    assert ap_sheet.cell(2, headers["AP MAC"]).number_format == "@"
    assert ap_sheet.cell(2, headers["AC软件版本"]).number_format == "@"
    unauth_row = next(row for row in range(2, ap_sheet.max_row + 1) if ap_sheet.cell(row, headers["AP名称"]).value == "AP-Unauth")
    assert "缺少光衰" in str(ap_sheet.cell(unauth_row, headers["数据完整性"]).value)


def test_fit_ap_resource_export_scopes_are_not_limited_by_page(tmp_path: Path) -> None:
    filtered, filtered_result = _export(tmp_path / "filtered", scope="filtered", filters={"status": "offline"})
    selected, selected_result = _export(
        tmp_path / "selected",
        scope="selected",
        selected_ap_ids=["ap-online", "ap-offline"],
    )

    filtered_book = load_workbook(filtered, read_only=True, data_only=True)
    selected_book = load_workbook(selected, read_only=True, data_only=True)
    assert filtered_result["ap_count"] == 1
    assert filtered_book["AP资源清单"].max_row == 2
    assert selected_result["ap_count"] == 2
    assert selected_book["AP资源清单"].max_row == 3


def test_fit_ap_resource_export_rejects_foreign_selection_and_empty_scope(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    payload = {
        "app_root": str(paths.app_root),
        "data_root": str(paths.data_root),
        "site_name": "demo",
        "ac_uuid": "ac-1",
        "scope": "selected",
        "filters": {},
    }
    with pytest.raises(ValueError, match="不属于当前 AC"):
        export_fit_ap_resource_xlsx(
            tmp_path / "foreign.xlsx",
            {**payload, "selected_ap_ids": ["ap-online", "foreign-ap"]},
        )
    with pytest.raises(ValueError, match="没有可导出"):
        export_fit_ap_resource_xlsx(
            tmp_path / "empty.xlsx",
            {**payload, "selected_ap_ids": [], "filters": {"query": "不存在的AP"}},
        )


def test_fit_ap_resource_export_deduplicates_by_normalized_mac(tmp_path: Path) -> None:
    paths, db_path, _files = build_ac_management_fixture(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_ip, ap_mac, model,
                state, collected_at, updated_at
            ) VALUES (
                'ac-1', 'ap-duplicate', 'AP-Duplicate', '10.0.1.99',
                '000000000001', 'WA-Test', 'R/M',
                '2026-07-29T00:42:15+08:00', '2026-07-29T00:42:15+08:00'
            )
            """
        )
        conn.commit()
    output = tmp_path / "deduplicated.xlsx"
    result = export_fit_ap_resource_xlsx(
        output,
        {
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "site_name": "demo",
            "ac_uuid": "ac-1",
            "scope": "all",
            "filters": {},
            "selected_ap_ids": [],
        },
    )
    workbook = load_workbook(output, read_only=True, data_only=True)
    assert result["ap_count"] == 3
    assert workbook["AP资源清单"].max_row == 4


def test_fit_ap_resource_filename_is_windows_safe_and_keeps_chinese() -> None:
    name = make_fit_ap_resource_filename("宁波:10号线", "251/无线*控制器")
    assert name.startswith("FIT-AP资源_宁波_10号线_251_无线_控制器_")
    assert name.endswith(".xlsx")
    assert not any(value in name for value in '<>:"/\\|?*')
