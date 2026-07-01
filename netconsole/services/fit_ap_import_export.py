from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_extension_import import (
    ApExtensionImportService,
    ImportPreview,
    standard_export_row,
    standard_template_headers,
)
from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning
from netconsole.utils.station_normalize import normalize_station_value


def normalize_ap_direction(value: str) -> str:
    text = str(value or "").strip()
    if text.upper() == "CW":
        return "上行"
    if text.upper() == "CT":
        return "下行"
    return text


AP_METADATA_IMPORT_FIELDS = ["AP名称", "AP_MAC", "归属站点", "里程", "点位说明", "上下行"]
AP_EXPORT_FIELDS = [
    "AP名称",
    "AP_IP",
    "AP_MAC",
    "型号",
    "SN",
    "状态",
    "AP组",
    "在线时长",
    "归属站点",
    "里程",
    "点位说明",
    "上下行",
    "更新时间",
]

AP_EXTENSION_TEMPLATE_FIELDS = [
    "AP名称",
    "AP_MAC",
    "归属站点",
    "里程",
    "点位说明",
    "上下行",
]
AP_EXTENSION_TEMPLATE_EDITABLE_FIELDS = {"归属站点", "里程", "点位说明", "上下行"}


@dataclass(frozen=True)
class ApMetadataImportResult:
    updated: int
    skipped: int
    errors: list[str]


def make_fit_ap_export_filename(site_name: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M")
    safe_site_name = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in site_name).strip().strip(".") or "site"
    return f"{safe_site_name}_fit_ap_{timestamp}.csv"


def make_ap_extension_template_filename(ac_name: str | None, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    safe_ac = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in str(ac_name or "AC")).strip().strip(".") or "AC"
    return f"AP扩展信息模板_{safe_ac}_{timestamp}.xlsx"


class FitApImportExportService:
    def __init__(self, repository: AcRepository) -> None:
        self.repository = repository
        self.ap_extension_import_service = ApExtensionImportService()

    def preview_ap_extension_import(self, path: Path, import_mode: str) -> ImportPreview:
        return self.ap_extension_import_service.preview_file(path, import_mode=import_mode)

    def commit_ap_extension_import(
        self,
        preview: ImportPreview,
        duplicate_strategy: str = "update_by_priority",
    ) -> dict[str, int | str]:
        return self.repository.import_ap_extension_points(
            preview.standard_rows,
            source_file=preview.file_name,
            template_type=preview.template_type,
            duplicate_strategy=duplicate_strategy,
        )

    def import_metadata_csv(self, path: Path) -> ApMetadataImportResult:
        with Path(path).open("r", newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
        if not rows:
            return ApMetadataImportResult(0, 0, [])
        return self.import_metadata_rows([header.strip() for header in rows[0]], rows[1:])

    def import_metadata_file(self, path: Path) -> ApMetadataImportResult:
        suffix = Path(path).suffix.casefold()
        if suffix == ".xlsx":
            sheet = load_workbook_without_unsupported_image_warning(path, data_only=True).active
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                return ApMetadataImportResult(0, 0, [])
            headers = [str(value or "").strip() for value in rows[0]]
            values = [[str(value or "").strip() for value in row] for row in rows[1:]]
            return self.import_metadata_rows(headers, values)
        return self.import_metadata_csv(path)

    def import_metadata_rows(self, headers: list[str], rows: list[list[object]]) -> ApMetadataImportResult:
        if headers != AP_METADATA_IMPORT_FIELDS:
            raise ValueError("Unsupported AP metadata template header")
        updated = 0
        skipped = 0
        errors: list[str] = []
        for line_number, values in enumerate(rows, start=2):
            payload = {field: (_text(values[index]) if index < len(values) else "") for index, field in enumerate(headers)}
            ap_mac = normalize_ap_mac(payload["AP_MAC"])
            if not ap_mac:
                skipped += 1
                errors.append(f"Row {line_number}: AP_MAC is empty or invalid")
                continue
            matched = self.repository.update_ap_entity_extension_by_mac(
                ap_mac,
                {
                    "station": payload["归属站点"],
                    "milestone": payload["里程"],
                    "location_note": payload["点位说明"],
                    "direction": normalize_ap_direction(payload["上下行"]),
                },
            )
            if not matched:
                skipped += 1
                errors.append(f"Row {line_number}: AP_MAC {payload['AP_MAC']} not matched")
                continue
            updated += 1
        return ApMetadataImportResult(updated, skipped, errors)

    def export_ap_csv(self, path: Path, rows: list[dict[str, object | None]]) -> None:
        with Path(path).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(AP_EXPORT_FIELDS)
            for row in rows:
                writer.writerow(
                    [
                        row.get("ap_name") or "",
                        row.get("ap_ip") or "",
                        row.get("ap_mac") or "",
                        row.get("model") or "",
                        row.get("serial_number") or "",
                        row.get("state_display") or row.get("state") or "",
                        row.get("group_name") or "",
                        row.get("online_time") or "",
                        row.get("site") or "",
                        row.get("mileage") or "",
                        row.get("location_note") or "",
                        row.get("direction") or "",
                        row.get("updated_at") or "",
                    ]
                )

    def export_ap_extension_template_xlsx(
        self,
        path: Path,
        rows: list[dict[str, object | None]],
        ap_entities: list[dict[str, object | None]] | None = None,
    ) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "AP扩展信息模板"
        sheet.append(AP_EXTENSION_TEMPLATE_FIELDS)
        editable_fill = PatternFill(fill_type="solid", fgColor="FFF7D6")
        entity_lookup = _build_ap_entity_lookup(ap_entities or [])
        for row in rows:
            entity = _lookup_ap_entity(row, entity_lookup)
            sheet.append(_ap_extension_template_row(row, entity))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            if cell.value in AP_EXTENSION_TEMPLATE_EDITABLE_FIELDS:
                cell.fill = editable_fill
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if sheet.cell(row=1, column=cell.column).value in AP_EXTENSION_TEMPLATE_EDITABLE_FIELDS:
                    cell.fill = editable_fill
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        _auto_width(sheet)
        workbook.save(path)

    def export_standard_ap_extension_xlsx(
        self,
        path: Path,
        rows: list[dict[str, object | None]],
    ) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "FIT-AP扩展信息"
        headers = list(standard_template_headers())
        sheet.append(headers)
        editable_fill = PatternFill(fill_type="solid", fgColor="FFF7D6")
        for row in rows:
            sheet.append(standard_export_row(row))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.fill = editable_fill
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        _auto_width(sheet)
        workbook.save(path)


def _ap_extension_template_row(row: dict[str, object | None], entity: dict[str, object | None] | None = None) -> list[str]:
    station = normalize_station_value(entity) or normalize_station_value(row)
    return [
        _text(row.get("ap_name") or (entity or {}).get("ap_name")),
        normalize_ap_mac(row.get("ap_mac") or (entity or {}).get("ap_mac")),
        station,
        _text(row.get("mileage") or row.get("milestone") or (entity or {}).get("milestone")),
        _text(row.get("location_note") or (entity or {}).get("location_note")),
        _text(row.get("direction") or (entity or {}).get("direction")),
    ]


def _build_ap_entity_lookup(rows: list[dict[str, object | None]]) -> dict[tuple[str, str], dict[str, object | None]]:
    lookup: dict[tuple[str, str], dict[str, object | None]] = {}
    for row in rows:
        ap_mac = normalize_ap_mac(row.get("ap_mac"))
        if ap_mac:
            lookup[("ap_mac", ap_mac)] = row
    return lookup


def _lookup_ap_entity(row: dict[str, object | None], lookup: dict[tuple[str, str], dict[str, object | None]]) -> dict[str, object | None] | None:
    return lookup.get(("ap_mac", normalize_ap_mac(row.get("ap_mac"))))


def _auto_width(sheet) -> None:
    for column_cells in sheet.columns:
        width = max(len(str(cell.value or "")) for cell in column_cells) + 2
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(width, 10), 36)


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalize_ap_mac(value: object) -> str:
    import re

    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(hex_text) != 12:
        return ""
    hex_text = hex_text.casefold()
    return f"{hex_text[0:4]}-{hex_text[4:8]}-{hex_text[8:12]}"
