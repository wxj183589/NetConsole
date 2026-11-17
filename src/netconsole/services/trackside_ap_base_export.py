from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.services.export.common_exporters import export_multi_sheet_xlsx
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]

TRACKSIDE_AP_BASE_COLUMNS = (
    ("AP名称", "ap_name"),
    ("AP MAC", "ap_mac"),
    ("归属位置", "station_name"),
    ("上联交换机", "uplink_switch"),
    ("上联端口", "uplink_port"),
    ("建设阶段", "build_phase"),
    ("位置类型", "location_class"),
)

TRACKSIDE_AP_IMPORT_ISSUE_COLUMNS = (
    ("源行号", "row_number"),
    ("分类", "result"),
    ("级别", "severity"),
    ("问题代码", "code"),
    ("字段", "field_name"),
    ("原始值", "original_value"),
    ("说明", "message"),
    ("建议处理", "suggested_action"),
    ("AP 名称", "ap_name"),
    ("点位编号", "point_code"),
    ("AP MAC", "ap_mac"),
)

_FIELD_NOTES = (
    ("AP名称", "必填", "保存的轨旁 AP 基础名称；不使用运行态 FIT-AP 名称覆盖。"),
    ("AP MAC", "必填、唯一", "首选唯一匹配键，支持常见 MAC 格式，导入后规范化保存。"),
    ("归属位置", "必填", "正式车站、区间、车辆段或停车场；站名支持带站序和“站”后缀的受控匹配。"),
    ("上联交换机", "可选", "保留已有非空值；空白导入默认 KEEP。"),
    ("上联端口", "可选", "保留本端接口完整名称；空白导入默认 KEEP。"),
    ("建设阶段", "可选", "如一期、二期；空白导入默认 KEEP。"),
    ("位置类型", "必填", "只填写正线、车辆段或停车场；正线参与判断，后两者不参与。"),
)

_LOCATION_CLASS_LABELS = {
    "MAINLINE": "正线",
    "DEPOT": "车辆段",
    "PARKING_YARD": "停车场",
}

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')


def build_trackside_ap_base_export_name(site_display_name: str, created_at: datetime) -> str:
    site_name = _INVALID_FILENAME_CHARS.sub("_", str(site_display_name or "").strip(" ."))
    site_name = re.sub(r"_+", "_", site_name).strip(" .")
    if not site_name:
        raise ValueError("轨旁 AP 基础资料导出缺少局点名称")
    return f"{site_name}_轨旁AP基础资料_{created_at:%Y%m%d_%H%M%S}.xlsx"


def export_trackside_ap_base_xlsx_task(
    path: Path,
    payload: Mapping[str, Any],
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> int:
    template = bool(payload.get("template"))
    issue_rows = payload.get("issue_rows")
    if issue_rows is not None:
        rows = [dict(row) for row in list(issue_rows) if isinstance(row, Mapping)]
        sheets = [
            {
                "sheet_name": "问题明细",
                "columns": [
                    {"key": key, "title": title, "text": key != "row_number"}
                    for title, key in TRACKSIDE_AP_IMPORT_ISSUE_COLUMNS
                ],
                "rows": rows,
                "freeze_header": True,
                "auto_filter": True,
                "auto_width": True,
            }
        ]
        return export_multi_sheet_xlsx(path, {"sheets": sheets}, progress, should_cancel)
    if template:
        rows: list[dict[str, object]] = []
    elif payload.get("draft_rows") is not None:
        rows = [_export_row(row) for row in list(payload.get("draft_rows") or [])]
    else:
        app_root = str(payload.get("app_root") or "").strip()
        data_root = str(payload.get("data_root") or "").strip()
        paths = PathResolver(
            app_root=Path(app_root) if app_root else None,
            data_root=Path(data_root) if data_root else None,
        )
        items = RailTransitBaseDataQueryService(paths).list_ap_export_items(
            str(payload.get("site_id") or "")
        )
        rows = [_export_row(item.model_dump()) for item in items]

    sheets = [
        {
            "sheet_name": "轨旁AP",
            "columns": [
                {"key": key, "title": title, "text": True}
                for title, key in TRACKSIDE_AP_BASE_COLUMNS
            ],
            "rows": rows,
            "freeze_header": True,
            "auto_filter": True,
            "auto_width": True,
        },
        {
            "sheet_name": "字段说明",
            "columns": [
                {"key": "field", "title": "字段", "text": True},
                {"key": "requirement", "title": "填写要求", "text": True},
                {"key": "description", "title": "说明", "text": True, "width": 60},
            ],
            "rows": [
                {"field": field, "requirement": requirement, "description": description}
                for field, requirement, description in _FIELD_NOTES
            ],
            "freeze_header": True,
            "auto_filter": True,
            "auto_width": True,
        },
    ]
    return export_multi_sheet_xlsx(path, {"sheets": sheets}, progress, should_cancel)


def _export_row(raw: Mapping[str, Any]) -> dict[str, object]:
    metadata = raw.get("base_metadata")
    base = dict(metadata) if isinstance(metadata, Mapping) else {}
    station_name = raw.get("station") or raw.get("station_name") or ""
    section_name = raw.get("section") or raw.get("section_name") or ""
    return {
        "ap_name": raw.get("name") or raw.get("ap_name") or "",
        "ap_mac": raw.get("mac") or raw.get("ap_mac_display") or raw.get("ap_mac_norm") or "",
        # The seven-column contract uses one location field. Preserve section-only APs there.
        "station_name": station_name or section_name,
        "uplink_switch": raw.get("uplink_switch") or base.get("uplink_switch") or "",
        "uplink_port": raw.get("uplink_port") or base.get("uplink_port") or "",
        "build_phase": raw.get("build_phase") or base.get("build_phase") or "",
        "location_class": _LOCATION_CLASS_LABELS.get(
            str(raw.get("location_class") or base.get("location_class") or "MAINLINE").strip().upper(),
            str(raw.get("location_class") or base.get("location_class") or "MAINLINE"),
        ),
    }


__all__ = [
    "TRACKSIDE_AP_BASE_COLUMNS",
    "build_trackside_ap_base_export_name",
    "export_trackside_ap_base_xlsx_task",
]
