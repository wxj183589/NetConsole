from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path

from netconsole.services.export.common_exporters import export_table_xlsx
from netconsole.services.file_contract import (
    ImportValidationError,
    read_validated_csv_rows,
    validate_optional_contract_metadata,
)
from netconsole.services.rail_transit.station_source_utils import (
    canonical_station_name,
    normalize_station_source_value,
)
from netconsole.utils.excel_workbook import (
    load_workbook_without_unsupported_image_warning,
)

TRACKSIDE_PLAN_COLUMNS = (
    ("ac.trackside_plan.sequence_no", "sequence_no"),
    ("ac.trackside_plan.station_name", "station_name"),
    ("ac.trackside_plan.ap_count", "ap_count"),
    ("ac.trackside_plan.ap_management_vlan", "management_vlan"),
    ("field.remark", "remark"),
)
TRACKSIDE_PLAN_SHEET = "AP规划"
LEGACY_TRACKSIDE_PLAN_SHEET = "轨旁AP规划"
TRACKSIDE_PLAN_HEADERS = [
    "序号",
    "车站名称",
    "AP数量",
    "AP管理VLAN",
    "备注",
]
TRACKSIDE_PLAN_COLUMN_WIDTHS = {
    "sequence_no": 10,
    "station_name": 30,
    "ap_count": 14,
    "management_vlan": 16,
    "remark": 42,
}
TRACKSIDE_PLAN_FIELD_NOTES = (
    {
        "field": "序号",
        "requirement": "必填",
        "description": "当前局点内唯一的正整数，保存后按序号升序显示。",
    },
    {
        "field": "车站名称",
        "requirement": "必填",
        "description": "必须能够匹配当前基础资料中的站点。",
    },
    {
        "field": "AP数量",
        "requirement": "必填",
        "description": "非负整数，表示该站点规划的轨旁 AP 数量。",
    },
    {
        "field": "AP管理VLAN",
        "requirement": "必填",
        "description": "1～4094 的单个 VLAN；不同站点允许填写相同 VLAN。",
    },
    {"field": "备注", "requirement": "可选", "description": "规划备注。"},
)
TRACKSIDE_PLAN_FIELD_NOTE_COLUMNS = (
    {"key": "field", "title": "字段", "width": 18},
    {"key": "requirement", "title": "填写要求", "width": 12},
    {
        "key": "description",
        "title": "说明",
        "width": 58,
        "wrap": True,
        "horizontal": "left",
    },
)

_HEADER_ALIASES = {
    "sequence_no": ("序号", "顺序", "排序号"),
    "station_name": ("车站名称", "站点名称", "站点", "车站"),
    "ap_count": (
        "AP数量",
        "AP 数量",
        "AP数",
        "AP 数",
        "规划AP数量",
        "规划 AP 数量",
        "规划AP总数量",
    ),
    "management_vlan": (
        "AP管理VLAN",
        "AP 管理 VLAN",
        "AP 管理VLAN",
        "管理VLAN",
        "管理 VLAN",
        "AP VLAN",
    ),
    "remark": ("备注", "说明"),
    # 以下字段只用于识别旧模板，读取后不进入当前规划。
    "ap_start_address": ("AP起始地址", "AP 起始地址"),
    "subnet_mask": ("掩码", "子网掩码"),
    "ap_gateway": ("AP网关", "AP 网关", "默认网关"),
    "planning_mode": ("AP管理VLAN规划方式", "VLAN规划方式"),
    "group_code": ("VLAN组编号",),
    "group_name": ("VLAN组名称",),
    "group_start_station": ("VLAN组起始站",),
    "group_end_station": ("VLAN组结束站",),
    "group_management_vlan": ("组管理VLAN",),
    "group_network_address": ("网络地址",),
    "group_ap_start_address": ("组AP起始地址",),
    "group_ap_end_address": ("组AP结束地址",),
    "allocation_order": ("组内分配顺序", "组内顺序"),
    "is_locked": ("是否手工锁定", "手工锁定"),
    "station_ids": ("组成员站点ID",),
    "station_names": ("组成员站点", "组成员"),
    "revision": ("revision",),
}
_HEADER_FIELD_BY_ALIAS = {
    "".join(
        unicodedata.normalize("NFKC", alias).split()
    ).casefold(): field
    for field, aliases in _HEADER_ALIASES.items()
    for alias in aliases
}
_RETIRED_OR_GROUP_FIELDS = {
    "ap_start_address",
    "subnet_mask",
    "ap_gateway",
    "planning_mode",
    "group_code",
    "group_name",
    "group_start_station",
    "group_end_station",
    "group_management_vlan",
    "group_network_address",
    "group_ap_start_address",
    "group_ap_end_address",
    "allocation_order",
    "is_locked",
    "station_ids",
    "station_names",
    "revision",
}


def read_trackside_plan_file(path: Path) -> list[dict[str, object | None]]:
    validate_optional_contract_metadata(
        path,
        expected_module="ac.trackside_ap_plan",
    )
    if path.suffix.casefold() == ".csv":
        rows, _metadata, _encoding = read_validated_csv_rows(path)
        return _read_plan_rows(rows)

    sheet_name = _trackside_plan_sheet_name(path)
    workbook = load_workbook_without_unsupported_image_warning(
        path,
        data_only=True,
    )
    try:
        rows = list(workbook[sheet_name].iter_rows(values_only=True))
        return _read_plan_rows(
            rows,
            legacy_sheet=sheet_name == LEGACY_TRACKSIDE_PLAN_SHEET,
        )
    finally:
        workbook.close()


def _trackside_plan_sheet_name(path: Path) -> str:
    workbook = load_workbook_without_unsupported_image_warning(
        path,
        data_only=True,
        read_only=True,
    )
    try:
        visible = [
            sheet.title
            for sheet in workbook.worksheets
            if sheet.title != "_netconsole_meta"
            and sheet.sheet_state == "visible"
            and sheet.title != "字段说明"
        ]
        if TRACKSIDE_PLAN_SHEET in visible:
            return TRACKSIDE_PLAN_SHEET
        if LEGACY_TRACKSIDE_PLAN_SHEET in visible:
            return LEGACY_TRACKSIDE_PLAN_SHEET
        if len(visible) == 1:
            return visible[0]
    finally:
        workbook.close()
    raise ImportValidationError("缺少必要 sheet：AP规划")


def _read_plan_rows(
    source_rows: list[list[object]] | list[tuple[object, ...]],
    *,
    legacy_sheet: bool = False,
) -> list[dict[str, object | None]]:
    if not source_rows:
        raise ImportValidationError("文件为空")
    header_index, header_fields, legacy_schema = _find_plan_header(source_rows)
    output: list[dict[str, object | None]] = []
    for source_row_number, values in enumerate(
        source_rows[header_index + 1 :],
        start=header_index + 2,
    ):
        if not any(value not in (None, "") for value in values):
            continue
        row: dict[str, object | None] = {}
        for column_index, field in header_fields.items():
            value = values[column_index] if column_index < len(values) else ""
            if field not in row or row[field] in (None, ""):
                row[field] = value
        if row.get("management_vlan") in (None, ""):
            row["management_vlan"] = row.get("group_management_vlan", "")
        if row.get("sequence_no") in (None, ""):
            row["sequence_no"] = len(output) + 1
        row["__source_row_number__"] = source_row_number
        row["__legacy_schema__"] = legacy_sheet or legacy_schema
        output.append(row)
    if not output:
        raise ImportValidationError("文件为空：没有可导入的数据")
    return output


def _find_plan_header(
    rows: list[list[object]] | list[tuple[object, ...]],
) -> tuple[int, dict[int, str], bool]:
    for row_index, values in enumerate(rows[:10]):
        fields = {
            column_index: field
            for column_index, value in enumerate(values)
            if (field := _header_field(value))
        }
        present = set(fields.values())
        if not {"station_name", "ap_count"}.issubset(present):
            continue
        if not {"management_vlan", "group_management_vlan"}.intersection(present):
            continue
        legacy = bool(present.intersection(_RETIRED_OR_GROUP_FIELDS))
        if "sequence_no" not in present:
            # 历史模板没有序号时按数据顺序补齐；新模板始终导出序号。
            legacy = True
        if any(
            _normalize_header(value) == _normalize_header("规划AP总数量")
            for value in values
        ):
            legacy = True
        return row_index, fields, legacy
    raise ImportValidationError(
        "缺少必要字段：序号、车站名称、AP数量、AP管理VLAN"
    )


def _header_field(value: object) -> str:
    return _HEADER_FIELD_BY_ALIAS.get(_normalize_header(value), "")


def _normalize_header(value: object) -> str:
    return "".join(
        unicodedata.normalize("NFKC", str(value or "")).strip().split()
    ).casefold()


def export_trackside_plan_xlsx(
    path: Path,
    rows: list[dict[str, object | None]],
) -> None:
    export_table_xlsx(
        path,
        {
            "sheet_name": TRACKSIDE_PLAN_SHEET,
            "columns": [
                {
                    "key": field,
                    "title": TRACKSIDE_PLAN_HEADERS[index],
                    "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field),
                }
                for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)
            ],
            "rows": rows,
        },
    )


def normalize_trackside_plan_row(
    row: dict[str, object | None],
    *,
    row_number: int = 2,
) -> dict[str, object | None]:
    value = dict(row)
    sequence_no = _required_integer(
        value.get("sequence_no")
        if value.get("sequence_no") not in (None, "")
        else (
            int(value.get("sort_order") or 0) + 1
            if value.get("sort_order") not in (None, "")
            else row_number - 1
        ),
        row_number=row_number,
        field="序号",
    )
    if sequence_no <= 0:
        raise ValueError(f"第{row_number}行 序号：必须是正整数")

    station = str(value.get("station_name") or "").strip()
    if not station:
        raise ValueError(f"第{row_number}行 车站名称：必填")

    raw_ap_count = (
        value.get("planned_ap_count")
        if value.get("planned_ap_count") not in (None, "")
        else value.get("ap_count")
    )
    if raw_ap_count in (None, ""):
        raise ValueError(f"第{row_number}行 AP数量：必填")
    ap_count = _required_integer(
        raw_ap_count,
        row_number=row_number,
        field="AP数量",
    )
    if ap_count < 0:
        raise ValueError(f"第{row_number}行 AP数量：必须是非负整数")

    raw_vlan = (
        value.get("management_vlan")
        if value.get("management_vlan") not in (None, "")
        else value.get("ap_management_vlans")
        if value.get("ap_management_vlans") not in (None, "")
        else value.get("group_management_vlan")
    )
    if raw_vlan in (None, ""):
        raise ValueError(f"第{row_number}行 AP管理VLAN：必填")
    management_vlan = _required_integer(
        raw_vlan,
        row_number=row_number,
        field="AP管理VLAN",
    )
    if not 1 <= management_vlan <= 4094:
        raise ValueError(f"第{row_number}行 AP管理VLAN：必须在 1～4094 范围内")

    return {
        "station_id": str(value.get("station_id") or "").strip(),
        "sequence_no": sequence_no,
        "station_name": station,
        "ap_count": ap_count,
        "management_vlan": management_vlan,
        "remark": str(value.get("remark") or value.get("notes") or "").strip(),
        # 数据库保留历史列，但当前规划不读取、校验或保存用户输入的 IP 字段。
        "ap_start_address": "",
        "subnet_mask": "",
        "mask_length": None,
        "ap_gateway": "",
        "ap_management_vlans": str(management_vlan),
        "sort_order": sequence_no - 1,
    }


def bind_trackside_plan_station(
    row: Mapping[str, object | None],
    stations: list[Mapping[str, object]],
    *,
    row_number: int,
) -> dict[str, object | None]:
    result = dict(row)
    station_id = str(result.get("station_id") or "").strip()
    if station_id:
        direct = [
            station
            for station in stations
            if _station_id(station) == station_id
        ]
        if len(direct) == 1:
            result["station_id"] = _station_id(direct[0])
            result["station_name"] = _station_name(direct[0])
            return result

    requested_name = str(result.get("station_name") or "").strip()
    exact_key = normalize_station_source_value(requested_name)[1]
    exact = [
        station
        for station in stations
        if normalize_station_source_value(_station_name(station))[1] == exact_key
    ]
    if len(exact) == 1:
        result["station_id"] = _station_id(exact[0])
        result["station_name"] = _station_name(exact[0])
        return result
    if len(exact) > 1:
        raise ValueError(f"第{row_number}行 车站名称：匹配到多个当前站点")

    canonical_key = canonical_station_name(requested_name).casefold()
    compatible = [
        station
        for station in stations
        if canonical_station_name(_station_name(station)).casefold()
        == canonical_key
    ]
    if len(compatible) == 1:
        result["station_id"] = _station_id(compatible[0])
        result["station_name"] = _station_name(compatible[0])
        return result
    if len(compatible) > 1:
        raise ValueError(f"第{row_number}行 车站名称：去除序号后匹配到多个当前站点")
    raise ValueError(f"第{row_number}行 车站名称：未匹配到当前站点")


def normalize_trackside_plan_rows(
    rows: list[dict[str, object | None]],
) -> list[dict[str, object | None]]:
    normalized = [
        normalize_trackside_plan_row(row, row_number=index)
        for index, row in enumerate(rows, start=2)
    ]
    station_keys = [
        str(row.get("station_id") or "").strip()
        or canonical_station_name(row["station_name"]).casefold()
        for row in normalized
    ]
    if len(station_keys) != len(set(station_keys)):
        raise ValueError("轨旁 AP 规划存在重复车站")
    sequence_numbers = [int(row["sequence_no"]) for row in normalized]
    if len(sequence_numbers) != len(set(sequence_numbers)):
        raise ValueError("轨旁 AP 规划存在重复序号")
    return sorted(
        normalized,
        key=lambda row: (int(row["sequence_no"]), str(row["station_name"])),
    )


def _required_integer(value: object, *, row_number: int, field: str) -> int:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"第{row_number}行 {field}：必须是整数") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"第{row_number}行 {field}：必须是整数")
    return int(number)


def _station_id(station: Mapping[str, object]) -> str:
    return str(station.get("id") or station.get("station_id") or "").strip()


def _station_name(station: Mapping[str, object]) -> str:
    return str(station.get("name") or station.get("station_name") or "").strip()
