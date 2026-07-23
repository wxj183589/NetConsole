from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable, Mapping

from openpyxl import Workbook, load_workbook

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_base_data import (
    StationDTO,
    StationSourceIssueDTO,
    StationTemplatePreviewDTO,
    StationTemplatePreviewRowDTO,
)
from netconsole.services.excel_report_utils import apply_standard_sheet_style
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.station_source_utils import (
    DEFAULT_MAIN_PATH_CODE,
    DEFAULT_STATION_SOURCE_GROUP,
    NODE_TYPE_LABELS,
    PLATFORM_LAYOUT_LABELS,
    STATION_SOURCE_FIELD,
    STRUCTURE_TYPE_LABELS,
    TURNBACK_DIRECTION_LABELS,
    TURNBACK_TYPE_LABELS,
    bool_from_template,
    bool_label,
    label_for,
    normalize_station_source_value,
    parse_station_source_value,
    value_from_label,
)


LINE_PARAM_HEADERS = (
    "线路名称",
    "项目类型",
    "网络类型",
    "主线路径编码",
    "站序递增方向名称",
    "站序递减方向名称",
    "设备来源分组",
    "设备来源字段",
    "备注",
)
STATION_HEADERS = (
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
)


class StationTemplateService:
    """线路与站点基础资料 XLSX 模板、导出和导入预览。"""

    def __init__(self, paths: PathResolver, query_service: RailTransitBaseDataQueryService) -> None:
        self.paths = paths
        self.query_service = query_service

    def build_blank_template(self, site_id: str) -> bytes:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        metadata = self._line_metadata(site_id)
        return self._workbook_bytes(metadata, [])

    def export_current(self, site_id: str) -> bytes:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        metadata = self._line_metadata(site_id)
        stations = self._all_stations(site_id)
        return self._workbook_bytes(metadata, stations)

    def preview(self, site_id: str, content: bytes, file_name: str = "") -> StationTemplatePreviewDTO:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("站点模板文件不能超过 10 MiB")
        if file_name and not file_name.casefold().endswith(".xlsx"):
            raise ValueError("站点模板仅支持 XLSX")
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
        try:
            line_sheet = workbook["01_线路参数"]
            node_sheet = workbook["02_线路节点"]
        except KeyError as exc:
            raise ValueError("站点模板必须包含 01_线路参数 和 02_线路节点 工作表") from exc
        issues: list[StationSourceIssueDTO] = []
        line_metadata = self._parse_line_metadata(line_sheet)
        if str(line_metadata.get("station_source_field") or "") != STATION_SOURCE_FIELD:
            issues.append(self._issue("error", "station_source_field_invalid", "设备来源字段只能为 station", "设备来源字段", blocking=True))
        existing = self._all_stations(site_id)
        existing_by_key = {row.source_station_key: row for row in existing if row.source_station_key}
        existing_by_identity = {(row.code.casefold(), row.name.casefold()): row for row in existing if row.code}
        rows: list[StationTemplatePreviewRowDTO] = []
        seen_source_keys: set[str] = set()
        for row_number, raw in self._iter_node_rows(node_sheet):
            row_issues: list[StationSourceIssueDTO] = []
            try:
                proposed = self._row_to_station(raw, line_metadata=line_metadata)
            except ValueError as exc:
                row_issues.append(self._issue("error", "station_template_invalid_enum", str(exc), blocking=True))
                proposed = None
            if proposed is not None:
                if not proposed.name:
                    row_issues.append(self._issue("error", "station_name_required", "节点名称不能为空", "节点名称", blocking=True))
                if proposed.source_station_key:
                    if proposed.source_station_key in seen_source_keys:
                        row_issues.append(self._issue("error", "station_source_duplicate", "模板中同一来源站点重复", "来源站点值", blocking=True))
                    seen_source_keys.add(proposed.source_station_key)
                matched = (
                    existing_by_key.get(proposed.source_station_key)
                    or existing_by_identity.get((proposed.code.casefold(), proposed.name.casefold()))
                )
                action = "update" if matched and self._station_payload(matched) != self._station_payload(proposed) else "unchanged" if matched else "create"
            else:
                action = "conflict"
            valid = not any(issue.blocking for issue in row_issues)
            rows.append(
                StationTemplatePreviewRowDTO(
                    row_number=row_number,
                    source_station_value=proposed.source_station_value if proposed else str(raw.get("来源站点值") or ""),
                    source_station_key=proposed.source_station_key if proposed else "",
                    code=proposed.code if proposed else str(raw.get("节点编码") or ""),
                    name=proposed.name if proposed else str(raw.get("节点名称") or ""),
                    node_type=proposed.node_type if proposed else "unknown",
                    path_code=proposed.path_code if proposed else "",
                    sort_order=proposed.sort_order if proposed else None,
                    participates_in_direction=proposed.participates_in_direction if proposed else False,
                    proposed_station=proposed,
                    action="conflict" if not valid else action,  # type: ignore[arg-type]
                    valid=valid,
                    issues=row_issues,
                )
            )
            issues.extend(row_issues)
        return StationTemplatePreviewDTO(
            valid=not any(issue.blocking for issue in issues),
            line_metadata=line_metadata,
            rows=rows,
            create_count=sum(row.action == "create" for row in rows),
            update_count=sum(row.action == "update" for row in rows),
            unchanged_count=sum(row.action == "unchanged" for row in rows),
            conflict_count=sum(row.action == "conflict" for row in rows),
            blocking_count=sum(issue.blocking for issue in issues),
            issues=issues,
        )

    def _workbook_bytes(self, metadata: Mapping[str, Any], stations: Iterable[StationDTO]) -> bytes:
        workbook = Workbook()
        line_sheet = workbook.active
        line_sheet.title = "01_线路参数"
        line_sheet.append(list(LINE_PARAM_HEADERS))
        line_sheet.append(
            [
                metadata.get("line_name") or "",
                metadata.get("system_type") or "",
                metadata.get("network_domain") or "",
                metadata.get("main_path_code") or DEFAULT_MAIN_PATH_CODE,
                metadata.get("increasing_direction_name") or "上行",
                metadata.get("decreasing_direction_name") or "下行",
                metadata.get("station_source_group_name") or DEFAULT_STATION_SOURCE_GROUP,
                STATION_SOURCE_FIELD,
                metadata.get("remark") or "",
            ]
        )
        apply_standard_sheet_style(line_sheet)

        node_sheet = workbook.create_sheet("02_线路节点")
        node_sheet.append(list(STATION_HEADERS))
        for station in stations:
            node_sheet.append(
                [
                    station.source_station_value,
                    station.code,
                    station.name,
                    label_for(NODE_TYPE_LABELS, station.node_type),
                    station.path_code,
                    station.sort_order if station.sort_order is not None else "",
                    bool_label(station.participates_in_direction),
                    label_for(STRUCTURE_TYPE_LABELS, station.structure_type),
                    label_for(PLATFORM_LAYOUT_LABELS, station.platform_layout),
                    bool_label(station.is_line_terminal),
                    bool_label(station.is_service_terminal),
                    bool_label(station.turnback_capable),
                    label_for(TURNBACK_TYPE_LABELS, station.turnback_type),
                    label_for(TURNBACK_DIRECTION_LABELS, station.turnback_direction),
                    bool_label(station.enabled),
                    station.remark,
                ]
            )
        apply_standard_sheet_style(node_sheet)
        self._append_field_description(workbook)
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def _parse_line_metadata(self, sheet) -> dict[str, Any]:
        row = [cell.value for cell in next(sheet.iter_rows(min_row=2, max_row=2))]
        values = {header: row[index] if index < len(row) else "" for index, header in enumerate(LINE_PARAM_HEADERS)}
        return {
            "line_name": str(values.get("线路名称") or "").strip(),
            "system_type": str(values.get("项目类型") or "").strip(),
            "network_domain": str(values.get("网络类型") or "default").strip() or "default",
            "main_path_code": str(values.get("主线路径编码") or DEFAULT_MAIN_PATH_CODE).strip() or DEFAULT_MAIN_PATH_CODE,
            "increasing_direction_name": str(values.get("站序递增方向名称") or "上行").strip() or "上行",
            "decreasing_direction_name": str(values.get("站序递减方向名称") or "下行").strip() or "下行",
            "station_source_group_name": str(values.get("设备来源分组") or DEFAULT_STATION_SOURCE_GROUP).strip() or DEFAULT_STATION_SOURCE_GROUP,
            "station_source_field": str(values.get("设备来源字段") or STATION_SOURCE_FIELD).strip() or STATION_SOURCE_FIELD,
            "remark": str(values.get("备注") or "").strip(),
        }

    def _iter_node_rows(self, sheet) -> Iterable[tuple[int, dict[str, Any]]]:
        headers = [str(cell.value or "").strip() for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        for row_number, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            values = {header: cells[index] if index < len(cells) else "" for index, header in enumerate(headers)}
            if any(str(value or "").strip() for value in values.values()):
                yield row_number, values

    def _row_to_station(self, raw: Mapping[str, Any], *, line_metadata: Mapping[str, Any]) -> StationDTO:
        source_value = str(raw.get("来源站点值") or "").strip()
        code = str(raw.get("节点编码") or "").strip()
        name = str(raw.get("节点名称") or "").strip()
        if source_value and (not code or not name):
            parsed = parse_station_source_value(source_value, main_path_code=str(line_metadata.get("main_path_code") or DEFAULT_MAIN_PATH_CODE))
            code = code or parsed.code
            name = name or parsed.name
        source_display, source_key = normalize_station_source_value(source_value or (f"{code}-{name}" if code else name))
        node_type = value_from_label(NODE_TYPE_LABELS, raw.get("节点类型"), default="station")
        if node_type not in NODE_TYPE_LABELS:
            raise ValueError(f"节点类型无效：{raw.get('节点类型')}")
        structure_type = value_from_label(STRUCTURE_TYPE_LABELS, raw.get("车站结构"), default="unknown")
        if structure_type not in STRUCTURE_TYPE_LABELS:
            raise ValueError(f"车站结构无效：{raw.get('车站结构')}")
        platform_layout = value_from_label(PLATFORM_LAYOUT_LABELS, raw.get("站台形式"), default="unknown")
        if platform_layout not in PLATFORM_LAYOUT_LABELS:
            raise ValueError(f"站台形式无效：{raw.get('站台形式')}")
        turnback_type = value_from_label(TURNBACK_TYPE_LABELS, raw.get("折返类型"), default="none")
        if turnback_type not in TURNBACK_TYPE_LABELS:
            raise ValueError(f"折返类型无效：{raw.get('折返类型')}")
        turnback_direction = value_from_label(TURNBACK_DIRECTION_LABELS, raw.get("折返方向"), default="none")
        if turnback_direction not in TURNBACK_DIRECTION_LABELS:
            raise ValueError(f"折返方向无效：{raw.get('折返方向')}")
        sort_order = self._int_or_none(raw.get("主线顺序"))
        participates = bool_from_template(raw.get("参与方向判断"), default=node_type == "station")
        if not bool_from_template(raw.get("可折返"), default=False):
            turnback_type = "none"
        return StationDTO(
            id=f"new:template:{source_key or name.casefold()}",
            name=name,
            code=code,
            line_name=str(line_metadata.get("line_name") or ""),
            sort_order=sort_order,
            remark=str(raw.get("备注") or "").strip(),
            source_station_value=source_display,
            source_station_key=source_key,
            node_type=node_type,  # type: ignore[arg-type]
            path_code=str(raw.get("所属路径") or (DEFAULT_MAIN_PATH_CODE if node_type == "station" else "UNASSIGNED")).strip(),
            participates_in_direction=participates,
            structure_type=structure_type,  # type: ignore[arg-type]
            platform_layout=platform_layout,  # type: ignore[arg-type]
            is_line_terminal=bool_from_template(raw.get("线路端点"), default=False),
            is_service_terminal=bool_from_template(raw.get("运营终点"), default=False),
            turnback_capable=bool_from_template(raw.get("可折返"), default=False),
            turnback_type=turnback_type,  # type: ignore[arg-type]
            turnback_direction=turnback_direction,  # type: ignore[arg-type]
            enabled=bool_from_template(raw.get("启用"), default=True),
            source_kind="template",
            source_sync_status="manual",
        )

    def _append_field_description(self, workbook: Workbook) -> None:
        sheet = workbook.create_sheet("字段说明")
        sheet.append(["字段名称", "是否必填", "含义", "允许值", "默认值", "示例"])
        rows = [
            ("来源站点值", "否", "设备管理 station 字段原始业务值", "文本", "", "32-五乡"),
            ("节点编码", "否", "官方节点编码，保留前导零", "文本", "", "01"),
            ("节点名称", "是", "线路节点显示名称", "文本", "", "五乡"),
            ("节点类型", "是", "普通车站或特殊节点", "、".join(NODE_TYPE_LABELS.values()), "普通车站", "停车场"),
            ("所属路径", "是", "主线路径或后续接轨路径", "文本", "MAIN/UNASSIGNED", "MAIN"),
            ("主线顺序", "参与方向判断时必填", "同一路径内方向判断顺序", "整数", "", "32"),
            ("参与方向判断", "是", "是否纳入站序递增/递减方向判断", "是/否、true/false、1/0", "普通车站为是，特殊节点为否", "是"),
            ("车站结构", "否", "土建结构类型", "、".join(STRUCTURE_TYPE_LABELS.values()), "未填写", "地下"),
            ("站台形式", "否", "站台布局类型", "、".join(PLATFORM_LAYOUT_LABELS.values()), "未填写", "岛式"),
            ("折返类型", "可折返时必填", "折返能力类型", "、".join(TURNBACK_TYPE_LABELS.values()), "无", "渡线"),
            ("折返方向", "否", "折返方向边界", "、".join(TURNBACK_DIRECTION_LABELS.values()), "无", "双向"),
        ]
        for row in rows:
            sheet.append(list(row))
        apply_standard_sheet_style(sheet)

    def _line_metadata(self, site_id: str) -> dict[str, Any]:
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        return {
            "line_name": str(metadata.get("line_name") or ""),
            "system_type": str(metadata.get("system_type") or ""),
            "network_domain": str(metadata.get("network_domain") or "default"),
            "main_path_code": str(metadata.get("main_path_code") or DEFAULT_MAIN_PATH_CODE),
            "increasing_direction_name": str(metadata.get("increasing_direction_name") or "上行"),
            "decreasing_direction_name": str(metadata.get("decreasing_direction_name") or "下行"),
            "station_source_group_name": str(metadata.get("station_source_group_name") or DEFAULT_STATION_SOURCE_GROUP),
            "station_source_field": STATION_SOURCE_FIELD,
            "remark": str(metadata.get("remark") or ""),
        }

    def _all_stations(self, site_id: str) -> list[StationDTO]:
        result: list[StationDTO] = []
        page = 1
        while True:
            data = self.query_service.list_stations(site_id, page=page, page_size=200)
            result.extend(data.items)
            if len(result) >= data.total or not data.items:
                return result
            page += 1

    @staticmethod
    def _station_payload(station: StationDTO) -> dict[str, Any]:
        return {
            key: getattr(station, key)
            for key in (
                "name",
                "code",
                "line_name",
                "sort_order",
                "remark",
                "source_station_value",
                "source_station_key",
                "node_type",
                "path_code",
                "participates_in_direction",
                "structure_type",
                "platform_layout",
                "is_line_terminal",
                "is_service_terminal",
                "turnback_capable",
                "turnback_type",
                "turnback_direction",
                "enabled",
            )
        }

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        return int(float(text))

    @staticmethod
    def _issue(
        severity: str,
        code: str,
        message: str,
        field_name: str = "",
        *,
        blocking: bool = False,
    ) -> StationSourceIssueDTO:
        return StationSourceIssueDTO(
            severity=severity,  # type: ignore[arg-type]
            code=code,
            message=message,
            field_name=field_name,
            blocking=blocking,
        )


__all__ = ["StationTemplateService"]
