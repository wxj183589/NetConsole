from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from netconsole.repositories.ac_repository import AcRepository


def normalize_ap_direction(value: str) -> str:
    text = str(value or "").strip()
    if text.upper() == "CW":
        return "上行"
    if text.upper() == "CT":
        return "下行"
    if text in {"上行", "下行"}:
        return text
    return ""


AP_METADATA_IMPORT_FIELDS = ["AP名称", "归属站点", "里程", "点位说明", "上下行"]
AP_EXPORT_FIELDS = [
    "AP名称",
    "主机地址",
    "MAC地址",
    "型号",
    "序列号",
    "状态",
    "组名称",
    "在线时长",
    "归属站点",
    "里程",
    "点位说明",
    "上下行",
    "更新时间",
]

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


@dataclass(frozen=True)
class ApMetadataImportResult:
    updated: int
    skipped: int
    errors: list[str]


def make_fit_ap_export_filename(site_name: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M")
    safe_site_name = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in site_name).strip().strip(".") or "site"
    return f"{safe_site_name}_fit_ap_{timestamp}.csv"


class FitApImportExportService:
    def __init__(self, repository: AcRepository) -> None:
        self.repository = repository

    def import_metadata_csv(self, path: Path) -> ApMetadataImportResult:
        with Path(path).open("r", newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
        if not rows:
            return ApMetadataImportResult(0, 0, [])
        headers = [header.strip() for header in rows[0]]
        if headers != AP_METADATA_IMPORT_FIELDS:
            raise ValueError("Unsupported AP metadata CSV header")
        updated = 0
        skipped = 0
        errors: list[str] = []
        for line_number, values in enumerate(rows[1:], start=2):
            payload = {field: (values[index].strip() if index < len(values) else "") for index, field in enumerate(headers)}
            ap_name = payload["AP名称"]
            if not ap_name:
                skipped += 1
                errors.append(f"Row {line_number}: AP名称 is required")
                continue
            self.repository.upsert_fit_ap_metadata(
                {
                    "ap_name": ap_name,
                    "site_name": payload["归属站点"],
                    "mileage": payload["里程"],
                    "location_note": payload["点位说明"],
                    "direction": normalize_ap_direction(payload["上下行"]),
                }
            )
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
