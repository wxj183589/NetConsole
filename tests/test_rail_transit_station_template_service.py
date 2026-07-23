from __future__ import annotations

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook

from netconsole.models.api.rail_transit_base_data import SectionDTO, StationDTO
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.station_template_service import (
    LINE_PARAM_HEADERS,
    SECTION_HEADERS,
    STATION_HEADERS,
    StationTemplateService,
)
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


def _service(tmp_path: Path) -> StationTemplateService:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    return StationTemplateService(paths, RailTransitBaseDataQueryService(paths))


def test_new_template_has_four_sheets_and_round_trips_station_and_section_fields(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    stations = [
        StationDTO(
            id="station:low",
            node_uid="node-low",
            name="高桥西",
            code="11",
            sort_order=11,
            path_code="MAIN",
            structure_type="underground",
            platform_layout="island",
            center_mileage_text="K12+345.5",
            center_mileage_m=12345.5,
            is_line_terminal=True,
            is_service_terminal=True,
            turnback_capable=True,
            track_facilities=["turnback_track", "storage_track"],
            turnback_direction="both",
            terminal_extension_enabled=True,
            terminal_endpoint_label="端点",
            terminal_extension_distance_m=180,
            terminal_endpoint_mileage_text="K12+165.5",
            source_kind="manual",
        ),
        StationDTO(
            id="station:high",
            node_uid="node-high",
            name="高桥",
            code="12",
            sort_order=12,
            path_code="MAIN",
            structure_type="underground",
            platform_layout="island",
            source_kind="manual",
        ),
    ]
    sections = [
        SectionDTO(
            id="section:auto",
            name="高桥西-高桥-上行",
            section_code="AUTO-1",
            section_kind="between_stations",
            path_code="MAIN",
            direction_role="increasing",
            line_direction="上行",
            start_node_type="station",
            start_node_uid="node-low",
            start_station="高桥西",
            end_node_type="station",
            end_node_uid="node-high",
            end_station="高桥",
            line_side="上行",
            auto_generated=True,
            generation_key="MAIN|between|node-low|node-high|increasing",
            source_kind="generated",
            ap_count=4,
            mileage_min=12360,
            mileage_max=12980,
            remark="保留备注",
        )
    ]
    content = service._workbook_bytes(
        {
            "line_name": "测试线",
            "system_type": "PIS",
            "network_domain": "default",
            "main_path_code": "MAIN",
            "increasing_direction_name": "上行",
            "decreasing_direction_name": "下行",
            "station_source_group_name": "车站",
        },
        stations,
        sections,
    )
    workbook = load_workbook(BytesIO(content))
    assert workbook.sheetnames == ["01_线路参数", "02_线路节点", "03_区间配置", "字段说明"]
    assert tuple(cell.value for cell in workbook["02_线路节点"][1]) == STATION_HEADERS
    assert tuple(cell.value for cell in workbook["03_区间配置"][1]) == SECTION_HEADERS
    assert workbook["02_线路节点"]["H2"].value == "K12+345.5"
    assert workbook["02_线路节点"]["N2"].value == "折返线、存车线"

    # AP 数量和里程范围是只读导出字段，导入修改必须被忽略。
    workbook["03_区间配置"]["N2"] = 9
    workbook["03_区间配置"]["O2"] = "0–99999 m"
    stream = BytesIO()
    workbook.save(stream)
    preview = service.preview("demo", stream.getvalue(), "基础资料.xlsx")

    station = next(row.proposed_station for row in preview.rows if row.name == "高桥西")
    section = preview.section_rows[0].proposed_section
    assert station is not None
    assert station.track_facilities == ["turnback_track", "storage_track"]
    assert station.center_mileage_text == "K12+345.5"
    assert station.center_mileage_m == 12345.5
    assert section is not None
    assert section.generation_key == "MAIN|between|node-low|node-high|increasing"
    assert section.ap_count == 0
    assert section.mileage_min is None
    assert section.mileage_max is None


def test_old_three_sheet_template_imports_without_deleting_sections(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workbook = Workbook()
    line_sheet = workbook.active
    line_sheet.title = "01_线路参数"
    line_sheet.append(list(LINE_PARAM_HEADERS))
    line_sheet.append(["测试线", "PIS", "default", "MAIN", "上行", "下行", "车站", "station", ""])
    station_sheet = workbook.create_sheet("02_线路节点")
    station_sheet.append([
        "来源站点值",
        "节点编码",
        "节点名称",
        "节点类型",
        "所属路径",
        "主线顺序",
        "参与方向判断",
        "车站结构",
        "站台形式",
        "线路端点",
        "运营终点",
        "可折返",
        "折返类型",
        "折返方向",
        "启用",
        "备注",
    ])
    station_sheet.append([
        "11-高桥西",
        "11",
        "高桥西",
        "普通车站",
        "MAIN",
        11,
        "是",
        "",
        "",
        "是",
        "是",
        "是",
        "中间折返线/存车线",
        "双向",
        "是",
        "",
    ])
    workbook.create_sheet("字段说明")
    stream = BytesIO()
    workbook.save(stream)

    preview = service.preview("demo", stream.getvalue(), "旧模板.xlsx")

    assert preview.valid is True
    assert preview.section_sheet_present is False
    assert preview.section_rows == []
    assert any(issue.code == "station_template_sections_missing" for issue in preview.issues)
    station = preview.rows[0].proposed_station
    assert station is not None
    assert station.structure_type == "underground"
    assert station.platform_layout == "island"
    assert station.track_facilities == ["turnback_track", "storage_track"]
