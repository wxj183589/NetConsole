from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning
from netconsole.utils.mileage import format_track_mileage, parse_track_mileage


STANDARD_TEMPLATE_TYPE = "netconsole_standard_template"
PIS_LAYOUT_TABLE = "pis_layout_table"
NINGBO_PIS_LAYOUT_LIKE = "ningbo_pis_layout_like"
AP_NAME_MAC_LIST = "ap_name_mac_list"
SIGNAL_AB_NETWORK_TABLE = "signal_ab_network_table"
GENERIC_MAPPING = "generic_mapping"
UNKNOWN_TEMPLATE = "unknown"

LOW_CONFIDENCE_THRESHOLD = 60

AP_NAME_RE = re.compile(r"^ap\d+_[A-Za-z]$", re.IGNORECASE)
H3C_MAC_RE = re.compile(r"^[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}$")
TITLE_RE = re.compile(r"^\s*(\d+)\s*[.、\-]?\s*(.+?)\s*$")
YARD_KEYWORDS = ("车辆段", "停车场", "库内", "基地", "出入段", "出段", "入段", "出场线", "入场线")


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "line_name": ("线路名称", "线路", "line_name"),
    "system_type": ("系统类型", "系统", "system_type"),
    "network_domain": ("网络域", "网络", "A网", "B网", "红网", "蓝网", "network_domain"),
    "belong_type": ("归属类型", "归属类别", "belong_type"),
    "station_name": ("车站", "站点", "归属站点", "站名", "station_name"),
    "section_name": ("归属区间", "轨旁AP归属区间", "区间", "section_name"),
    "section_start_station": ("区间起点站", "起点站", "section_start_station"),
    "section_end_station": ("区间终点站", "终点站", "section_end_station"),
    "yard_name": ("场段", "车辆段", "停车场", "yard_name"),
    "area_name": ("区域", "area_name"),
    "left_mileage": ("左线里程", "左线", "left_mileage"),
    "right_mileage": ("右线里程", "右线", "right_mileage"),
    "start_mileage": ("起点里程", "起始里程", "start_mileage"),
    "mileage_text": ("里程", "里程原文", "mileage_text", "mileage"),
    "distance_to_prev_m": ("距上一个AP", "距上一个 AP", "AP间距", "间隔", "distance_to_prev_m"),
    "ap_point_code": ("AP编号", "点位编号", "AP点位", "轨旁AP编号", "ap_point_code"),
    "ap_name": ("AP名称", "AP名", "AP命名", "AP Name", "ap_name"),
    "ap_mac_display": ("AP MAC", "MAC", "MAC地址", "AP_MAC", "ap_mac", "ap_mac_display"),
    "curve_radius_m": ("曲线半径", "半径", "curve_radius_m"),
    "curve_start_text": ("曲线开始", "曲线起点", "curve_start_text"),
    "curve_end_text": ("曲线终点", "曲线结束", "curve_end_text"),
    "install_scene": ("安装场景", "安装位置", "install_scene"),
    "power_station": ("供电站", "AP供电站", "power_station"),
    "power_distribution": ("电源分配", "供电分配", "power_distribution"),
    "fiber_access_station": ("光缆接入站", "AP光缆接入站", "fiber_access_station"),
    "fiber_distribution": ("光缆分配", "光交分配", "fiber_distribution"),
    "uplink_switch": ("上联交换机", "上联设备", "uplink_switch"),
    "uplink_port": ("上联端口", "交换机端口", "uplink_port"),
    "optical_port": ("光模块端口", "光口", "optical_port"),
    "location_desc": ("点位说明", "安装位置说明", "location_desc"),
    "remark": ("备注", "remark"),
    "extension_id": ("extension_id", "扩展ID"),
}

STANDARD_TEMPLATE_HEADERS = (
    "extension_id",
    "线路名称",
    "系统类型",
    "网络域",
    "归属类型",
    "车站",
    "归属区间",
    "区间起点站",
    "区间终点站",
    "场段",
    "区域",
    "线别",
    "方向",
    "AP编号",
    "AP名称",
    "AP MAC",
    "里程原文",
    "里程米",
    "距上一个AP米",
    "曲线半径",
    "曲线开始",
    "曲线终点",
    "安装场景",
    "点位说明",
    "供电站",
    "电源分配",
    "光缆接入站",
    "光缆分配",
    "上联交换机",
    "上联端口",
    "光模块端口",
    "备注",
    "来源文件",
    "来源工作表",
    "来源行号",
    "更新时间",
)

STANDARD_HEADER_TO_FIELD = {
    "extension_id": "id",
    "线路名称": "line_name",
    "系统类型": "system_type",
    "网络域": "network_domain",
    "归属类型": "belong_type",
    "车站": "station_name",
    "归属区间": "section_name",
    "区间起点站": "section_start_station",
    "区间终点站": "section_end_station",
    "场段": "yard_name",
    "区域": "area_name",
    "线别": "line_side",
    "方向": "direction",
    "AP编号": "ap_point_code",
    "AP名称": "ap_name",
    "AP MAC": "ap_mac_display",
    "里程原文": "mileage_text",
    "里程米": "mileage_m",
    "距上一个AP米": "distance_to_prev_m",
    "曲线半径": "curve_radius_m",
    "曲线开始": "curve_start_text",
    "曲线终点": "curve_end_text",
    "安装场景": "install_scene",
    "点位说明": "location_desc",
    "供电站": "power_station",
    "电源分配": "power_distribution",
    "光缆接入站": "fiber_access_station",
    "光缆分配": "fiber_distribution",
    "上联交换机": "uplink_switch",
    "上联端口": "uplink_port",
    "光模块端口": "optical_port",
    "备注": "remark",
    "来源文件": "source_file",
    "来源工作表": "source_sheet",
    "来源行号": "source_row",
    "更新时间": "updated_at",
}


@dataclass(frozen=True)
class MacNormalizeResult:
    raw: str
    normalized: str = ""
    display: str = ""
    error: str = ""

    @property
    def valid(self) -> bool:
        return bool(self.normalized)


@dataclass(frozen=True)
class MileageParseResult:
    raw: str
    meters: float | None
    error: str = ""


@dataclass
class SheetPreview:
    sheet_name: str
    template_type: str
    confidence_score: int
    header_row: int
    data_start_row: int
    field_mapping: dict[str, int]
    unrecognized_headers: list[str]
    default_direction_rules: dict[str, str]
    rows: list[dict[str, object | None]]
    issues: list[dict[str, object | None]]
    duplicate_records: list[dict[str, object | None]]
    merged_ranges: list[str] = field(default_factory=list)
    segment_titles: list[dict[str, object | None]] = field(default_factory=list)


@dataclass
class ImportPreview:
    file_name: str
    import_mode: str
    template_type: str
    confidence_score: int
    low_confidence: bool
    sheets: list[SheetPreview]
    summary: dict[str, int]

    @property
    def standard_rows(self) -> list[dict[str, object | None]]:
        rows: list[dict[str, object | None]] = []
        for sheet in self.sheets:
            rows.extend(sheet.rows)
        return rows


def normalize_ap_mac(value: object) -> MacNormalizeResult:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return MacNormalizeResult(raw=raw)
    hex_text = re.sub(r"[-:.\s]", "", raw)
    if not re.fullmatch(r"[0-9a-fA-F]{12}", hex_text or ""):
        return MacNormalizeResult(raw=raw, error="MAC格式无效")
    normalized = hex_text.casefold()
    return MacNormalizeResult(raw=raw, normalized=normalized, display=f"{normalized[0:4]}-{normalized[4:8]}-{normalized[8:12]}")


def parse_mileage(value: object) -> MileageParseResult:
    parsed = parse_track_mileage(value)
    return MileageParseResult(raw=parsed.raw, meters=parsed.meters, error=parsed.error)


class ApExtensionImportService:
    def preview_file(self, path: Path, import_mode: str = "smart_design") -> ImportPreview:
        suffix = Path(path).suffix.casefold()
        if suffix == ".xlsx":
            sheets = self._read_xlsx(path)
        elif suffix == ".csv":
            sheets = [self._read_csv(path)]
        else:
            raise ValueError("仅支持 xlsx/csv 文件")
        previews = [self._preview_sheet(Path(path).name, sheet, import_mode) for sheet in sheets]
        previews = [preview for preview in previews if preview.rows or preview.field_mapping or import_mode == "standard_template"]
        template_type = _dominant_template_type(previews)
        confidence = max((sheet.confidence_score for sheet in previews), default=0)
        summary = self._summary(previews)
        return ImportPreview(
            file_name=Path(path).name,
            import_mode=import_mode,
            template_type=template_type,
            confidence_score=confidence,
            low_confidence=confidence < LOW_CONFIDENCE_THRESHOLD,
            sheets=previews,
            summary=summary,
        )

    def _read_xlsx(self, path: Path) -> list[dict[str, object]]:
        workbook = load_workbook_without_unsupported_image_warning(path, data_only=True)
        result: list[dict[str, object]] = []
        for sheet in workbook.worksheets:
            rows = [[_cell_text(cell.value) for cell in row] for row in sheet.iter_rows()]
            merged_context: dict[tuple[int, int], str] = {}
            for merged in sheet.merged_cells.ranges:
                value = _cell_text(sheet.cell(merged.min_row, merged.min_col).value)
                for row_index in range(merged.min_row, merged.max_row + 1):
                    for col_index in range(merged.min_col, merged.max_col + 1):
                        merged_context[(row_index - 1, col_index - 1)] = value
            result.append(
                {
                    "name": sheet.title,
                    "rows": rows,
                    "merged_context": merged_context,
                    "merged_ranges": [str(item) for item in sheet.merged_cells.ranges],
                }
            )
        return result

    def _read_csv(self, path: Path) -> dict[str, object]:
        with Path(path).open("r", newline="", encoding="utf-8-sig") as file:
            rows = [[_cell_text(value) for value in row] for row in csv.reader(file)]
        return {"name": Path(path).stem, "rows": rows, "merged_context": {}, "merged_ranges": []}

    def _preview_sheet(self, file_name: str, sheet: dict[str, object], import_mode: str) -> SheetPreview:
        rows: list[list[str]] = sheet["rows"]  # type: ignore[assignment]
        merged_context: dict[tuple[int, int], str] = sheet.get("merged_context", {})  # type: ignore[assignment]
        header_row, mapping, header_labels = _detect_header(rows, merged_context)
        template_type, confidence = _detect_template_type(sheet["name"], rows, mapping, header_labels, import_mode)  # type: ignore[arg-type]
        data_start = header_row + 1 if header_row >= 0 else 0
        titles = _segment_titles(rows)
        if import_mode != "standard_template" and _is_signal_ab_network_sheet(sheet["name"], rows):  # type: ignore[arg-type]
            template_type = SIGNAL_AB_NETWORK_TABLE
            confidence = max(confidence, 88)
            standard_rows, issues = _convert_signal_ab_network_rows(file_name, str(sheet["name"]), rows)
        else:
            standard_rows, issues = _convert_rows(file_name, str(sheet["name"]), rows, data_start, mapping, titles)
        duplicates = _duplicate_records(standard_rows)
        for duplicate in duplicates:
            issues.append({"type": "duplicate_mac", **duplicate})
        return SheetPreview(
            sheet_name=str(sheet["name"]),
            template_type=template_type,
            confidence_score=confidence,
            header_row=header_row + 1 if header_row >= 0 else 0,
            data_start_row=data_start + 1,
            field_mapping={field: index + 1 for field, index in mapping.items()},
            unrecognized_headers=[label for label in header_labels if label and not _field_for_header(label)],
            default_direction_rules={"左线": "下行", "右线": "上行", "车辆段/停车场/出入线": "未知"},
            rows=standard_rows,
            issues=issues,
            duplicate_records=duplicates,
            merged_ranges=list(sheet.get("merged_ranges", [])),
            segment_titles=titles,
        )

    @staticmethod
    def _summary(previews: Iterable[SheetPreview]) -> dict[str, int]:
        sheets = list(previews)
        rows = [row for sheet in sheets for row in sheet.rows]
        return {
            "total_rows": len(rows),
            "new_rows": len(rows),
            "updated_rows": 0,
            "error_rows": sum(1 for sheet in sheets for issue in sheet.issues if issue.get("severity") == "error"),
            "missing_mac_rows": sum(1 for row in rows if not row.get("ap_mac_norm")),
            "invalid_mac_rows": sum(1 for sheet in sheets for issue in sheet.issues if issue.get("type") == "invalid_mac"),
            "duplicate_mac_rows": sum(1 for sheet in sheets for issue in sheet.issues if issue.get("type") == "duplicate_mac"),
            "unbound_rows": sum(1 for row in rows if not row.get("ap_mac_norm")),
        }


def standard_template_headers() -> tuple[str, ...]:
    return STANDARD_TEMPLATE_HEADERS


def standard_export_row(row: dict[str, object | None]) -> list[object | None]:
    values: list[object | None] = []
    for header in STANDARD_TEMPLATE_HEADERS:
        field_name = STANDARD_HEADER_TO_FIELD.get(header, "")
        if header == "AP MAC":
            values.append(row.get("ap_mac_display") or _mac_display(row.get("ap_mac_norm")))
        elif header == "里程原文":
            values.append(
                format_track_mileage(
                    row.get("mileage_m") if row.get("mileage_m") is not None else row.get("mileage_text"),
                    direction=str(row.get("direction") or ""),
                    line_side=str(row.get("line_side") or ""),
                )
            )
        elif header == "更新时间":
            values.append(row.get("updated_at") or datetime.now().isoformat(timespec="seconds"))
        else:
            values.append(row.get(field_name) if field_name else "")
    return values


def _detect_header(rows: list[list[str]], merged_context: dict[tuple[int, int], str]) -> tuple[int, dict[str, int], list[str]]:
    best_row = -1
    best_mapping: dict[str, int] = {}
    best_score = 0
    best_labels: list[str] = []
    for row_index, row in enumerate(rows[:30]):
        labels = []
        for col_index, value in enumerate(row):
            context = merged_context.get((row_index, col_index), "")
            label = " ".join(part for part in (context, value) if part).strip()
            labels.append(label)
        mapping = _mapping_for_labels(labels)
        score = len(mapping)
        if score > best_score:
            best_row = row_index
            best_mapping = mapping
            best_score = score
            best_labels = labels
    return best_row, best_mapping, best_labels


def _mapping_for_labels(labels: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, label in enumerate(labels):
        field_name = _field_for_header(label)
        if field_name and field_name not in mapping:
            mapping[field_name] = index
    return mapping


def _field_for_header(label: str) -> str:
    normalized = _normalize_header(label)
    if not normalized:
        return ""
    for header, field_name in STANDARD_HEADER_TO_FIELD.items():
        if _normalize_header(header) == normalized:
            return field_name
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalize_header(alias)
            if alias_norm and (alias_norm == normalized or alias_norm in normalized):
                return field_name
    return ""


def _detect_template_type(
    sheet_name: object,
    rows: list[list[str]],
    mapping: dict[str, int],
    headers: list[str],
    import_mode: str,
) -> tuple[str, int]:
    header_set = {_normalize_header(value) for value in headers if value}
    standard_matches = sum(1 for header in STANDARD_TEMPLATE_HEADERS if _normalize_header(header) in header_set)
    if import_mode == "standard_template" or standard_matches >= 10:
        return STANDARD_TEMPLATE_TYPE, min(100, 65 + standard_matches)
    fields = set(mapping)
    name = str(sheet_name or "")
    if {"left_mileage", "right_mileage"} & fields and {"ap_point_code", "section_name"} & fields:
        confidence = 86 if "宁波" in name or "PIS" in name.upper() else 78
        return (NINGBO_PIS_LAYOUT_LIKE if "宁波" in name else PIS_LAYOUT_TABLE), confidence
    if {"ap_name", "ap_mac_display"} <= fields and len(fields) <= 4:
        return AP_NAME_MAC_LIST, 82
    if {"ap_mac_display", "network_domain"} <= fields or _contains_any(rows, ("A网", "B网", "红网", "蓝网")):
        return SIGNAL_AB_NETWORK_TABLE, 72
    if fields:
        return GENERIC_MAPPING, min(70, 35 + len(fields) * 5)
    return UNKNOWN_TEMPLATE, 0


def _convert_rows(
    file_name: str,
    sheet_name: str,
    rows: list[list[str]],
    data_start: int,
    mapping: dict[str, int],
    segment_titles: list[dict[str, object | None]],
) -> tuple[list[dict[str, object | None]], list[dict[str, object | None]]]:
    result: list[dict[str, object | None]] = []
    issues: list[dict[str, object | None]] = []
    if not mapping:
        return result, [{"type": "low_confidence", "severity": "warning", "message": "识别置信度较低，请手动映射字段"}]
    for row_index, values in enumerate(rows[data_start:], start=data_start + 1):
        if not any(str(value or "").strip() for value in values):
            continue
        if _is_segment_title_row(values):
            continue
        converted = _convert_row(file_name, sheet_name, row_index, values, mapping, segment_titles)
        if not _has_business_value(converted):
            continue
        if converted.get("ap_mac_display") and not converted.get("ap_mac_norm"):
            issues.append({"type": "invalid_mac", "severity": "error", "source_row": row_index, "message": "MAC格式无效"})
        if converted.get("mileage_text") and converted.get("mileage_m") is None:
            issues.append({"type": "invalid_mileage", "severity": "warning", "source_row": row_index, "message": "里程无法解析"})
        result.append(converted)
    return result, issues


def _convert_row(
    file_name: str,
    sheet_name: str,
    row_index: int,
    values: list[str],
    mapping: dict[str, int],
    segment_titles: list[dict[str, object | None]],
) -> dict[str, object | None]:
    source = {field_name: _value_at(values, index) for field_name, index in mapping.items()}
    line_side = _value_at(values, mapping.get("line_side", -1))
    mileage_text = source.get("mileage_text") or source.get("mileage_m") or source.get("left_mileage") or source.get("right_mileage") or source.get("start_mileage")
    if source.get("left_mileage"):
        line_side = line_side or "左线"
    elif source.get("right_mileage"):
        line_side = line_side or "右线"
    direction = _default_direction(line_side)
    mac = normalize_ap_mac(source.get("ap_mac_display"))
    mileage = parse_mileage(mileage_text)
    curve_start = parse_mileage(source.get("curve_start_text"))
    curve_end = parse_mileage(source.get("curve_end_text"))
    station = source.get("station_name") or _nearest_segment_title(row_index, segment_titles)
    section = source.get("section_name")
    yard_name = source.get("yard_name")
    area_name = source.get("area_name")
    belong_type = _normalize_belong_type(source.get("belong_type"))
    if not belong_type:
        belong_type = _infer_belong_type(station, section, yard_name, area_name)
    row = {
        "id": _int_or_none(source.get("id") or source.get("extension_id")),
        "line_name": source.get("line_name"),
        "system_type": source.get("system_type"),
        "network_domain": source.get("network_domain"),
        "belong_type": belong_type,
        "station_name": station,
        "section_name": section,
        "section_start_station": source.get("section_start_station"),
        "section_end_station": source.get("section_end_station"),
        "yard_name": yard_name,
        "area_name": area_name,
        "line_side": line_side,
        "direction": source.get("direction") or direction,
        "mileage_text": mileage.raw,
        "mileage_m": mileage.meters,
        "distance_to_prev_m": _float_or_none(source.get("distance_to_prev_m")),
        "ap_point_code": source.get("ap_point_code"),
        "ap_name": source.get("ap_name"),
        "ap_mac_norm": mac.normalized,
        "ap_mac_display": mac.display or mac.raw,
        "curve_radius_m": _float_or_none(source.get("curve_radius_m")),
        "curve_start_text": source.get("curve_start_text"),
        "curve_start_m": curve_start.meters,
        "curve_end_text": source.get("curve_end_text"),
        "curve_end_m": curve_end.meters,
        "curve_flag": 1 if source.get("curve_radius_m") or source.get("curve_start_text") or source.get("curve_end_text") else 0,
        "install_scene": source.get("install_scene"),
        "power_station": source.get("power_station"),
        "power_distribution": source.get("power_distribution"),
        "fiber_access_station": source.get("fiber_access_station"),
        "fiber_distribution": source.get("fiber_distribution"),
        "uplink_switch": source.get("uplink_switch"),
        "uplink_port": source.get("uplink_port"),
        "optical_port": source.get("optical_port"),
        "location_desc": source.get("location_desc"),
        "remark": source.get("remark"),
        "source_file": file_name,
        "source_sheet": sheet_name,
        "source_row": row_index,
        "raw_payload_json": json.dumps({"values": values, "mapping": mapping}, ensure_ascii=False),
    }
    row["curve_impact_level"] = _curve_impact_level(row.get("curve_radius_m"))
    row["interval_risk_level"], row["interval_risk_reason"] = _interval_risk(row.get("distance_to_prev_m"), row.get("curve_radius_m"))
    return row


def _is_signal_ab_network_sheet(sheet_name: object, rows: list[list[str]]) -> bool:
    name = str(sheet_name or "").strip()
    if name not in {"A网", "B网"} and not re.fullmatch(r"[AB]网", name, re.IGNORECASE):
        return False
    ap_count = 0
    mac_count = 0
    title_count = 0
    for row in rows:
        for value in row:
            text = _cell_text(value)
            if AP_NAME_RE.fullmatch(text):
                ap_count += 1
            if H3C_MAC_RE.fullmatch(text):
                mac_count += 1
            if _parse_signal_title(text) is not None:
                title_count += 1
    return ap_count >= 1 and mac_count >= 1 and title_count >= 1


def _convert_signal_ab_network_rows(
    file_name: str,
    sheet_name: str,
    rows: list[list[str]],
) -> tuple[list[dict[str, object | None]], list[dict[str, object | None]]]:
    title_index = _signal_title_index(rows)
    line_name = _infer_line_name(file_name)
    result: list[dict[str, object | None]] = []
    issues: list[dict[str, object | None]] = []
    for row_number, values in enumerate(rows, start=1):
        for column_index, value in enumerate(values):
            ap_name = _cell_text(value)
            if not AP_NAME_RE.fullmatch(ap_name):
                continue
            mac_text = _signal_row_mac(values, column_index)
            mac = normalize_ap_mac(mac_text)
            if mac_text and not mac.valid:
                issues.append({"type": "invalid_mac", "severity": "error", "source_row": row_number, "message": "MAC格式无效"})
            title = _nearest_signal_title(rows, title_index, row_number, column_index)
            belonging = _signal_belonging(title, title_index)
            remark = "信号A/B网布点表识别"
            if belonging["belong_type"] == "unknown":
                remark = "未识别到相邻站点，请人工确认"
                issues.append({"type": "unknown_belonging", "severity": "warning", "source_row": row_number, "message": remark})
            result.append(
                {
                    "line_name": line_name,
                    "system_type": "信号",
                    "network_domain": sheet_name,
                    "belong_type": belonging["belong_type"],
                    "station_name": belonging["station_name"],
                    "section_name": belonging["section_name"],
                    "section_start_station": belonging["section_start_station"],
                    "section_end_station": belonging["section_end_station"],
                    "yard_name": belonging["yard_name"],
                    "area_name": belonging["area_name"],
                    "ap_name": ap_name,
                    "ap_mac_norm": mac.normalized,
                    "ap_mac_display": mac.display or mac.raw,
                    "location_desc": belonging["location_desc"],
                    "remark": remark,
                    "source_file": file_name,
                    "source_sheet": sheet_name,
                    "source_row": row_number,
                    "raw_payload_json": json.dumps({"row": values, "source_column": column_index + 1}, ensure_ascii=False),
                }
            )
    return result, issues


def _signal_title_index(rows: list[list[str]]) -> dict[int, list[dict[str, object]]]:
    titles: dict[int, list[dict[str, object]]] = {}
    for row_number, values in enumerate(rows, start=1):
        for column_index, value in enumerate(values):
            parsed = _parse_signal_title(value)
            if parsed is None:
                continue
            titles.setdefault(column_index, []).append({"row": row_number, "column": column_index, **parsed})
    for items in titles.values():
        items.sort(key=lambda item: int(item["row"]))
    return titles


def _nearest_signal_title(
    rows: list[list[str]],
    title_index: dict[int, list[dict[str, object]]],
    row_number: int,
    ap_column_index: int,
) -> dict[str, object] | None:
    candidates: list[tuple[int, int, dict[str, object]]] = []
    for title_column in range(max(0, ap_column_index - 2), ap_column_index + 1):
        for title in title_index.get(title_column, []):
            title_row = int(title["row"])
            if title_row <= row_number:
                candidates.append((row_number - title_row, abs(ap_column_index - title_column), title))
    if candidates:
        return min(candidates, key=lambda item: (item[0], item[1]))[2]
    for title_column in range(max(0, ap_column_index - 2), ap_column_index + 1):
        for title in title_index.get(title_column, []):
            title_row = int(title["row"])
            if title_row > row_number:
                candidates.append((title_row - row_number, abs(ap_column_index - title_column), title))
    return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _signal_belonging(
    title: dict[str, object] | None,
    title_index: dict[int, list[dict[str, object]]],
) -> dict[str, str]:
    empty = {
        "belong_type": "unknown",
        "station_name": "",
        "section_name": "",
        "section_start_station": "",
        "section_end_station": "",
        "yard_name": "",
        "area_name": "",
        "location_desc": "",
    }
    if title is None:
        return empty
    name = str(title.get("name") or "").strip()
    kind = str(title.get("kind") or "")
    if kind == "yard":
        yard_name, area_name = _split_yard_area(name)
        return {
            **empty,
            "belong_type": "yard",
            "station_name": yard_name,
            "yard_name": yard_name,
            "area_name": area_name,
            "location_desc": area_name,
        }
    number = int(title.get("number") or 0)
    previous = _previous_normal_signal_title(title, title_index)
    if previous is None:
        return {**empty, "location_desc": name}
    previous_name = str(previous.get("name") or "").strip()
    section_name = f"{name}-{previous_name}" if name and previous_name else ""
    return {
        **empty,
        "belong_type": "section" if section_name else "unknown",
        "section_name": section_name,
        "section_start_station": previous_name,
        "section_end_station": name,
        "location_desc": f"{number}号站区间" if section_name else name,
    }


def _previous_normal_signal_title(
    title: dict[str, object],
    title_index: dict[int, list[dict[str, object]]],
) -> dict[str, object] | None:
    number = int(title.get("number") or 0)
    title_column = int(title.get("column") or 0)
    candidates = [
        item
        for item in title_index.get(title_column, [])
        if str(item.get("kind") or "") == "station" and int(item.get("number") or 0) == number - 1
    ]
    if candidates:
        return candidates[0]
    return None


def _parse_signal_title(value: object) -> dict[str, object] | None:
    text = _cell_text(value)
    if not text:
        return None
    match = TITLE_RE.fullmatch(text)
    if not match:
        return None
    name = _clean_signal_title_name(match.group(2))
    if not name or AP_NAME_RE.fullmatch(name) or H3C_MAC_RE.fullmatch(name):
        return None
    kind = "yard" if any(keyword in name for keyword in YARD_KEYWORDS) else "station"
    return {"number": int(match.group(1)), "name": name, "kind": kind}


def _signal_row_mac(values: list[str], ap_column_index: int) -> str:
    for index in (ap_column_index + 1, ap_column_index - 1):
        if 0 <= index < len(values):
            text = _cell_text(values[index])
            if H3C_MAC_RE.fullmatch(text):
                return text
    for index in range(ap_column_index + 1, min(len(values), ap_column_index + 4)):
        text = _cell_text(values[index])
        if H3C_MAC_RE.fullmatch(text):
            return text
    return ""


def _clean_signal_title_name(value: object) -> str:
    text = _cell_text(value).replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", text)


def _split_yard_area(value: object) -> tuple[str, str]:
    text = _clean_signal_title_name(value)
    area_match = re.search(r"\(([^)]+)\)", text)
    area = area_match.group(1).strip() if area_match else ("库内" if "库内" in text else "")
    name = re.sub(r"\([^)]*\)", "", text).strip()
    return name, area


def _infer_line_name(file_name: object) -> str:
    text = str(file_name or "")
    match = re.search(r"杭州地铁\s*(\d+)\s*号线", text)
    if match:
        return f"杭州地铁{match.group(1)}号线"
    match = re.search(r"杭\s*(\d+)", text)
    if match:
        return f"杭州地铁{match.group(1)}号线"
    match = re.search(r"(\d+)\s*号线", text)
    if match:
        return f"{match.group(1)}号线"
    return ""


def _segment_titles(rows: list[list[str]]) -> list[dict[str, object | None]]:
    titles: list[dict[str, object | None]] = []
    for row_index, values in enumerate(rows, start=1):
        if _is_segment_title_row(values):
            titles.append({"row": row_index, "title": _clean_segment_title(next(value for value in values if str(value or "").strip()))})
    return titles


def _is_segment_title_row(values: list[str]) -> bool:
    non_empty = [str(value or "").strip() for value in values if str(value or "").strip()]
    if len(non_empty) != 1:
        return False
    text = non_empty[0]
    return bool(re.fullmatch(r"\d+[.、]\s*[\u4e00-\u9fa5A-Za-z0-9_-]+", text) or re.search(r"(站|车辆段|停车场|区间|出入线)$", text))


def _nearest_segment_title(row_index: int, titles: list[dict[str, object | None]]) -> str:
    previous = [item for item in titles if int(item.get("row") or 0) < row_index]
    return str(previous[-1].get("title") or "") if previous else ""


def _duplicate_records(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    seen: dict[str, int] = {}
    duplicates: list[dict[str, object | None]] = []
    for row in rows:
        mac = str(row.get("ap_mac_norm") or "")
        if not mac:
            continue
        if mac in seen:
            duplicates.append({"ap_mac_norm": mac, "source_row": row.get("source_row"), "first_source_row": seen[mac], "severity": "warning"})
        else:
            seen[mac] = int(row.get("source_row") or 0)
    return duplicates


def _dominant_template_type(previews: list[SheetPreview]) -> str:
    if not previews:
        return UNKNOWN_TEMPLATE
    return max(previews, key=lambda item: item.confidence_score).template_type


def _default_direction(line_side: object) -> str:
    text = str(line_side or "")
    if "左线" in text:
        return "下行"
    if "右线" in text:
        return "上行"
    if any(token in text for token in ("车辆段", "停车场", "出入线", "库内", "试车线")):
        return "未知"
    return ""


def _normalize_belong_type(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    if text in {"station", "站点"}:
        return "station"
    if text in {"section", "interval", "区间"}:
        return "section"
    if text in {"yard", "场段", "场段/库内", "车辆段", "停车场", "库内"}:
        return "yard"
    if text in {"unknown", "未知"}:
        return "unknown"
    return text if text in {"station", "section", "yard", "unknown"} else ""


def _infer_belong_type(station: object, section: object, yard_name: object, area_name: object) -> str:
    if str(yard_name or "").strip() or any(keyword in str(station or "") for keyword in YARD_KEYWORDS) or str(area_name or "").strip():
        return "yard"
    if str(section or "").strip() and not str(station or "").strip():
        return "section"
    if str(station or "").strip():
        return "station"
    return "unknown"


def _curve_impact_level(radius: object) -> str:
    value = _float_or_none(radius)
    if value is None:
        return "普通区段"
    if value >= 900:
        return "轻微影响"
    if value >= 500:
        return "中等影响"
    if value >= 300:
        return "明显影响"
    return "高风险曲线"


def _interval_risk(distance: object, radius: object) -> tuple[str, str]:
    dist = _float_or_none(distance)
    curve = _float_or_none(radius)
    if dist is None:
        return "", ""
    if curve is not None and curve < 500 and dist > 100:
        return "曲线段间隔偏大", "小半径曲线区段建议保守复核 AP 间隔"
    if dist > 150:
        return "间隔偏大", "PIS 普通正线常见间隔约 80-130m，需结合现场复核"
    return "正常", ""


def _has_business_value(row: dict[str, object | None]) -> bool:
    return any(
        row.get(field_name)
        for field_name in (
            "station_name",
            "section_name",
            "belong_type",
            "yard_name",
            "area_name",
            "mileage_text",
            "ap_point_code",
            "ap_name",
            "ap_mac_display",
        )
    )


def _contains_any(rows: list[list[str]], tokens: tuple[str, ...]) -> bool:
    haystack = "\n".join(" ".join(row) for row in rows[:30])
    return any(token in haystack for token in tokens)


def _normalize_header(value: object) -> str:
    return re.sub(r"[\s_：:（）()\-/]+", "", str(value or "").casefold())


def _value_at(values: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(values):
        return ""
    return _cell_text(values[index])


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _clean_segment_title(value: object) -> str:
    return re.sub(r"^\d+[.、]\s*", "", str(value or "").strip())


def _float_or_none(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _int_or_none(value: object) -> int | None:
    try:
        text = str(value or "").strip()
        return int(text) if text else None
    except ValueError:
        return None


def _mac_display(value: object) -> str:
    mac = normalize_ap_mac(value)
    return mac.display
