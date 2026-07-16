from __future__ import annotations

import csv
import io
from pathlib import Path

from netconsole.services.file_contract import read_validated_csv_rows, validate_csv_import, validate_excel_import
from netconsole.services.vehicle_mr_online import VehicleMrTrainMapping, normalize_online_policy, normalize_train_no
from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning

VEHICLE_MR_MAPPING_HEADERS = ("车次", "TC1", "TC2", "在线策略", "备注")
VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS = tuple(
    {"key": key, "title": title}
    for key, title in zip(("train", "tc1", "tc2", "online_policy", "remark"), VEHICLE_MR_MAPPING_HEADERS, strict=True)
)
VEHICLE_MR_MAPPING_TEMPLATE_ROWS = (
    {"train": "1车", "tc1": "0101", "tc2": "0106", "online_policy": "单端在线-尾端在线", "remark": "正式环境尾端MR在线"},
    {"train": "2车", "tc1": "0201", "tc2": "0206", "online_policy": "双端在线", "remark": "正线双活"},
    {"train": "3车", "tc1": "0301", "tc2": "0306", "online_policy": "单端在线-TC1固定在线", "remark": ""},
    {"train": "4车", "tc1": "0401", "tc2": "0406", "online_policy": "单端在线-TC2固定在线", "remark": ""},
)


def read_vehicle_mr_mapping_file(path: Path) -> list[dict[str, object]]:
    if path.suffix.casefold() == ".csv":
        validate_csv_import(
            path,
            expected_module="rail.vehicle_mr_mapping",
            required_headers=VEHICLE_MR_MAPPING_HEADERS[:3],
            allow_legacy=True,
        )
        rows, _metadata, _encoding = read_validated_csv_rows(path)
        return [dict(row) for row in csv.DictReader(io.StringIO(_rows_to_csv(rows)))]
    validate_excel_import(
        path,
        expected_module="rail.vehicle_mr_mapping",
        required_headers={"车载MR映射表": VEHICLE_MR_MAPPING_HEADERS[:3]},
        allow_legacy=True,
    )
    workbook = load_workbook_without_unsupported_image_warning(path, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    headers = [str(cell.value or "").strip() for cell in sheet[1]]
    return [
        {headers[index]: values[index] if index < len(values) else "" for index in range(len(headers))}
        for values in sheet.iter_rows(min_row=2, values_only=True)
        if any(value not in (None, "") for value in values)
    ]


def normalize_vehicle_mr_mapping_row(row: dict[str, object], *, row_number: int) -> VehicleMrTrainMapping:
    display_name = str(row.get("车次") or row.get("train") or row.get("train_display_name") or "").strip()
    tc1 = str(row.get("TC1") or row.get("tc1") or row.get("tc1_peer_name") or "").strip()
    tc2 = str(row.get("TC2") or row.get("tc2") or row.get("tc2_peer_name") or "").strip()
    if not display_name:
        raise ValueError(f"第{row_number}行 车次：必填")
    if not tc1 and not tc2:
        raise ValueError(f"第{row_number}行 TC1 和 TC2：不能同时为空")
    train_no = normalize_train_no(display_name)
    return VehicleMrTrainMapping(
        enabled=bool(row.get("enabled", True)),
        train_display_name=f"{train_no}车" if train_no else display_name,
        train_id=f"列车{train_no}" if train_no else display_name,
        train_no=train_no,
        tc1_peer_name=tc1,
        tc2_peer_name=tc2,
        online_policy=normalize_online_policy(row.get("在线策略") or row.get("online_policy") or row.get("policy") or ""),
        remark=str(row.get("备注") or row.get("remark") or "").strip(),
    )


def _rows_to_csv(rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue()


__all__ = [
    "VEHICLE_MR_MAPPING_HEADERS",
    "VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS",
    "VEHICLE_MR_MAPPING_TEMPLATE_ROWS",
    "normalize_vehicle_mr_mapping_row",
    "read_vehicle_mr_mapping_file",
]
