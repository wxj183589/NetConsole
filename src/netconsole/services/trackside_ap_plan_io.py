from __future__ import annotations

import csv
import io
import ipaddress
import re
from pathlib import Path

from netconsole.services.export.common_exporters import export_table_xlsx
from netconsole.services.file_contract import (
    ImportValidationError,
    read_validated_csv_rows,
    validate_csv_import,
    validate_excel_import,
)
from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning

TRACKSIDE_PLAN_COLUMNS = (
    ("ac.trackside_plan.sequence_no", "sequence_no"),
    ("ac.trackside_plan.station_name", "station_name"),
    ("ac.trackside_plan.ap_count", "ap_count"),
    ("ac.trackside_plan.ap_start_address", "ap_start_address"),
    ("ac.trackside_plan.mask", "subnet_mask"),
    ("ac.trackside_plan.ap_gateway", "ap_gateway"),
    ("ac.trackside_plan.ap_management_vlan", "management_vlan"),
    ("field.remark", "remark"),
)
TRACKSIDE_PLAN_SHEET = "AP规划"
LEGACY_TRACKSIDE_PLAN_SHEET = "轨旁AP规划"
TRACKSIDE_PLAN_HEADERS = [
    "序号",
    "车站名称",
    "规划AP总数量",
    "AP起始地址",
    "掩码",
    "AP网关",
    "AP管理VLAN",
    "备注",
]
# 规划数量单独校验新旧二选一表头，避免旧模板失效。
TRACKSIDE_PLAN_REQUIRED_HEADERS = [
    "车站名称",
    "AP管理VLAN",
]
TRACKSIDE_PLAN_COUNT_HEADERS = ("规划AP总数量", "AP数量")
TRACKSIDE_PLAN_COLUMN_WIDTHS = {
    "sequence_no": 80,
    "station_name": 260,
    "ap_count": 90,
    "ap_start_address": 170,
    "subnet_mask": 150,
    "ap_gateway": 170,
    "management_vlan": 120,
    "remark": 220,
}
TRACKSIDE_PLAN_FIELD_NOTES = (
    {
        "field": "序号",
        "requirement": "必填",
        "description": "当前局点内唯一的正整数，保存后按序号升序显示。",
    },
    {
        "field": "站点",
        "requirement": "必填",
        "description": "站点名称不能为空；重复站点按导入时选择的覆盖、跳过或报错策略处理。",
    },
    {
        "field": "规划AP总数量",
        "requirement": "必填",
        "description": "当前确认应建设、应上线的 AP 总数；非负整数，可按现场核减调整。",
    },
    {
        "field": "AP 起始地址",
        "requirement": "可选参考",
        "description": "允许 IPv4、末段 X/x 占位符或空值，不参与自动地址分配。",
    },
    {
        "field": "掩码",
        "requirement": "可选参考",
        "description": "支持 24、/24、点分十进制掩码或空值。",
    },
    {
        "field": "AP 网关",
        "requirement": "可选参考",
        "description": "允许为空或保留既有文本，不参与 VLAN 规划校验。",
    },
    {
        "field": "管理 VLAN",
        "requirement": "必填",
        "description": "1～4094 的单个 VLAN；不同站点允许填写相同 VLAN。",
    },
    {"field": "备注", "requirement": "可选", "description": "规划备注。"},
)

_LEGACY_HEADERS = {
    "AP管理VLAN规划方式": "planning_mode",
    "VLAN组编号": "group_code",
    "VLAN组名称": "group_name",
    "VLAN组起始站": "start_station_name",
    "VLAN组结束站": "end_station_name",
    "管理VLAN": "group_management_vlan",
    "网络地址": "network_address",
    "子网掩码": "group_subnet_mask",
    "默认网关": "group_default_gateway",
    "组AP起始地址": "group_ap_start_address",
    "组AP结束地址": "group_ap_end_address",
    "组内分配顺序": "allocation_order",
    "是否手工锁定": "is_locked",
    "组成员站点ID": "station_ids",
    "组成员站点": "station_names",
}


def read_trackside_plan_file(path: Path) -> list[dict[str, object | None]]:
    if path.suffix.casefold() == ".csv":
        validation = validate_csv_import(
            path,
            expected_module="ac.trackside_ap_plan",
            required_headers=TRACKSIDE_PLAN_REQUIRED_HEADERS,
            allow_legacy=True,
        )
        _validate_plan_count_header(validation.headers)
        rows, _metadata, _encoding = read_validated_csv_rows(path)
        return [_row_from_named(row) for row in csv.DictReader(io.StringIO(_rows_to_csv(rows)))]
    sheet_name = _trackside_plan_sheet_name(path)
    validation = validate_excel_import(
        path,
        expected_module="ac.trackside_ap_plan",
        required_headers={sheet_name: TRACKSIDE_PLAN_REQUIRED_HEADERS},
        allow_legacy=True,
    )
    _validate_plan_count_header(validation.headers)
    workbook = load_workbook_without_unsupported_image_warning(path, data_only=True)
    try:
        sheet = workbook[sheet_name]
        headers = [str(cell.value or "").strip() for cell in sheet[1]]
        rows = []
        for values in sheet.iter_rows(min_row=2, values_only=True):
            raw = {headers[index]: values[index] if index < len(values) else "" for index in range(len(headers))}
            if any(value not in (None, "") for value in raw.values()):
                rows.append(_row_from_named(raw))
        return rows
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
            name
            for name in workbook.sheetnames
            if name != "_netconsole_meta"
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


def _rows_to_csv(rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue()


def _validate_plan_count_header(headers: tuple[str, ...]) -> None:
    if not any(header in headers for header in TRACKSIDE_PLAN_COUNT_HEADERS):
        raise ImportValidationError(
            "缺少必要字段：规划AP总数量（旧模板可使用 AP数量）"
        )


def export_trackside_plan_xlsx(path: Path, rows: list[dict[str, object | None]]) -> None:
    export_table_xlsx(
        path,
        {
            "sheet_name": TRACKSIDE_PLAN_SHEET,
            "columns": [{"key": field, "title": TRACKSIDE_PLAN_HEADERS[index], "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field)} for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)],
            "rows": rows,
        },
    )


def _row_from_named(row: dict[object, object]) -> dict[str, object | None]:
    simple_mapping = dict(
        zip(
            TRACKSIDE_PLAN_HEADERS,
            [field for _key, field in TRACKSIDE_PLAN_COLUMNS],
            strict=False,
        )
    )
    result = {field: row.get(header, "") for header, field in simple_mapping.items()}
    if result.get("ap_count") in (None, ""):
        result["ap_count"] = row.get("AP数量", "")
    legacy = any(str(row.get(header) or "").strip() for header in _LEGACY_HEADERS)
    for header, field in _LEGACY_HEADERS.items():
        result[field] = row.get(header, "")
    result["__legacy_schema__"] = legacy
    return result


def _parse_mask_length(value: object) -> int | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    if text.startswith("/"):
        text = text[1:].strip()
    if text.isdigit():
        prefix = int(text)
        return prefix if 0 <= prefix <= 32 else None
    if "." in text:
        return _dotted_netmask_to_prefix(text)
    return None


def _dotted_netmask_to_prefix(mask: str) -> int | None:
    parts = mask.split(".")
    if len(parts) != 4:
        return None
    octets: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        value = int(part)
        if value < 0 or value > 255:
            return None
        octets.append(value)
    bits = "".join(f"{octet:08b}" for octet in octets)
    if re.fullmatch(r"1*0*", bits) is None:
        return None
    return bits.count("1")


def normalize_trackside_plan_row(
    row: dict[str, object | None],
    *,
    row_number: int = 2,
) -> dict[str, object | None]:
    value = dict(row)
    try:
        sequence_no = int(
            str(
                value.get("sequence_no")
                or (
                    int(value.get("sort_order") or 0) + 1
                    if value.get("sort_order") not in (None, "")
                    else row_number - 1
                )
            ).strip()
        )
    except (TypeError, ValueError):
        raise ValueError(f"第{row_number}行 序号：必须是正整数") from None
    if sequence_no <= 0:
        raise ValueError(f"第{row_number}行 序号：必须是正整数")
    station = str(value.get("station_name") or "").strip()
    if not station:
        raise ValueError(f"第{row_number}行 车站名称：必填")
    raw_planned_ap_count = (
        value.get("planned_ap_count")
        if value.get("planned_ap_count") not in (None, "")
        else value.get("ap_count")
    )
    if raw_planned_ap_count in (None, ""):
        raise ValueError(f"第{row_number}行 规划AP总数量：必填")
    try:
        ap_count = int(str(raw_planned_ap_count).strip())
    except ValueError:
        raise ValueError(f"第{row_number}行 规划AP总数量：必须是整数") from None
    if ap_count < 0:
        raise ValueError(f"第{row_number}行 规划AP总数量：必须是非负整数")
    raw_mask = (
        value.get("subnet_mask")
        if value.get("subnet_mask") not in (None, "")
        else value.get("mask_length")
        if value.get("mask_length") not in (None, "")
        else value.get("group_subnet_mask")
    )
    subnet_mask = str(raw_mask or "").strip()
    mask_length = _parse_mask_length(subnet_mask)
    if subnet_mask and mask_length is None:
        raise ValueError(f"第{row_number}行 掩码：格式无效")
    raw_vlan = (
        value.get("management_vlan")
        if value.get("management_vlan") not in (None, "")
        else value.get("ap_management_vlans")
        if value.get("ap_management_vlans") not in (None, "")
        else value.get("group_management_vlan")
    )
    try:
        management_vlan = int(str(raw_vlan).strip())
    except (TypeError, ValueError):
        raise ValueError(f"第{row_number}行 AP管理VLAN：必填")
    if not 1 <= management_vlan <= 4094:
        raise ValueError(f"第{row_number}行 AP管理VLAN：必须在 1～4094 范围内")
    start = str(
        value.get("ap_start_address")
        or value.get("group_ap_start_address")
        or ""
    ).strip()
    if start:
        candidate = re.sub(r"[xX]$", "1", start)
        try:
            ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            raise ValueError(
                f"第{row_number}行 AP起始地址：应为 IPv4 或末段 X 占位符"
            ) from None
        if re.search(r"[xX]", start) and re.fullmatch(
            r"(?:\d{1,3}\.){3}[xX]", start
        ) is None:
            raise ValueError(
                f"第{row_number}行 AP起始地址：X 只能用于地址末段"
            )
    gateway = str(
        value.get("ap_gateway")
        or value.get("group_default_gateway")
        or ""
    ).strip()
    if gateway:
        try:
            ipaddress.IPv4Address(gateway)
        except ipaddress.AddressValueError:
            raise ValueError(f"第{row_number}行 AP网关：IPv4 格式无效") from None
    return {
        "station_id": str(value.get("station_id") or "").strip(),
        "sequence_no": sequence_no,
        "station_name": station,
        "ap_count": ap_count,
        "ap_start_address": start,
        "subnet_mask": subnet_mask,
        "mask_length": mask_length,
        "ap_gateway": gateway,
        "management_vlan": management_vlan,
        "ap_management_vlans": str(management_vlan),
        "remark": str(value.get("remark") or "").strip(),
        "sort_order": sequence_no - 1,
    }


def normalize_trackside_plan_rows(
    rows: list[dict[str, object | None]],
) -> list[dict[str, object | None]]:
    normalized = [
        normalize_trackside_plan_row(row, row_number=index)
        for index, row in enumerate(rows, start=2)
    ]
    station_names = [str(row["station_name"]).casefold() for row in normalized]
    if len(station_names) != len(set(station_names)):
        raise ValueError("轨旁 AP 规划存在重复车站名称")
    sequence_numbers = [int(row["sequence_no"]) for row in normalized]
    if len(sequence_numbers) != len(set(sequence_numbers)):
        raise ValueError("轨旁 AP 规划存在重复序号")
    station_ids = [
        str(row.get("station_id") or "")
        for row in normalized
        if str(row.get("station_id") or "")
    ]
    if len(station_ids) != len(set(station_ids)):
        raise ValueError("轨旁 AP 规划存在重复 station_id")
    return sorted(
        normalized,
        key=lambda row: (int(row["sequence_no"]), str(row["station_name"])),
    )
