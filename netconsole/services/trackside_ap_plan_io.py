from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from netconsole.services.export.common_exporters import export_table_xlsx
from netconsole.services.file_contract import read_validated_csv_rows, validate_csv_import, validate_excel_import
from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning

TRACKSIDE_PLAN_COLUMNS = (
    ("ac.trackside_plan.station_name", "station_name"),
    ("ac.trackside_plan.ap_count", "ap_count"),
    ("ac.trackside_plan.ap_start_address", "ap_start_address"),
    ("ac.trackside_plan.mask", "mask_length"),
    ("ac.trackside_plan.ap_gateway", "ap_gateway"),
    ("ac.trackside_plan.ap_management_vlan", "ap_management_vlans"),
    ("field.remark", "remark"),
)
TRACKSIDE_PLAN_HEADERS = ["车站名称", "AP数量", "AP起始地址", "掩码", "AP网关", "AP管理VLAN", "备注"]
TRACKSIDE_PLAN_REQUIRED_HEADERS = TRACKSIDE_PLAN_HEADERS[:-1]
TRACKSIDE_PLAN_COLUMN_WIDTHS = {
    "station_name": 260,
    "ap_count": 90,
    "ap_start_address": 170,
    "mask_length": 140,
    "ap_gateway": 170,
    "ap_management_vlans": 170,
    "remark": 220,
}
MASK_ERROR_TEXT = "必须是0-32或合法连续IPv4掩码"


def read_trackside_plan_file(path: Path) -> list[dict[str, object | None]]:
    if path.suffix.casefold() == ".csv":
        validate_csv_import(path, expected_module="ac.trackside_ap_plan", required_headers=TRACKSIDE_PLAN_REQUIRED_HEADERS, allow_legacy=True)
        rows, _metadata, _encoding = read_validated_csv_rows(path)
        return [_row_from_named(row) for row in csv.DictReader(io.StringIO(_rows_to_csv(rows)))]
    validate_excel_import(
        path,
        expected_module="ac.trackside_ap_plan",
        required_headers={"轨旁AP规划": TRACKSIDE_PLAN_REQUIRED_HEADERS},
        allow_legacy=True,
    )
    workbook = load_workbook_without_unsupported_image_warning(path, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    headers = [str(cell.value or "").strip() for cell in sheet[1]]
    rows = []
    for values in sheet.iter_rows(min_row=2, values_only=True):
        raw = {headers[index]: values[index] if index < len(values) else "" for index in range(len(headers))}
        if any(value not in (None, "") for value in raw.values()):
            rows.append(_row_from_named(raw))
    return rows


def _rows_to_csv(rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue()


def export_trackside_plan_xlsx(path: Path, rows: list[dict[str, object | None]]) -> None:
    export_table_xlsx(
        path,
        {
            "sheet_name": "轨旁AP规划",
            "columns": [{"key": field, "title": TRACKSIDE_PLAN_HEADERS[index], "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field)} for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)],
            "rows": rows,
        },
    )


def _row_from_named(row: dict[object, object]) -> dict[str, object | None]:
    mapping = dict(zip(TRACKSIDE_PLAN_HEADERS, [field for _key, field in TRACKSIDE_PLAN_COLUMNS], strict=False))
    return {field: row.get(header, "") for header, field in mapping.items()}


def _dedupe_station_rows(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    by_station: dict[str, dict[str, object | None]] = {}
    order: list[str] = []
    for row in rows:
        station = str(row.get("station_name") or "").strip()
        key = station.casefold()
        if not key:
            order.append(f"__blank_{len(order)}")
            by_station[order[-1]] = row
            continue
        if key not in by_station:
            order.append(key)
        by_station[key] = row
    result = [by_station[key] for key in order if key in by_station]
    for index, row in enumerate(result):
        row["sort_order"] = index
    return result


def _valid_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def _valid_ipv4_or_placeholder(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if part.upper() == "X":
            continue
        try:
            if int(part) < 0 or int(part) > 255:
                return False
        except ValueError:
            return False
    return True


def _parse_mask_length(value: object) -> int | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
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
