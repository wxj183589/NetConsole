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
    ("点位编号", "ap_point_code"),
    ("AP MAC", "ap_mac"),
    ("管理 IP", "management_ip"),
    ("型号", "model"),
    ("归属类型", "belong_type"),
    ("归属站点", "station_name"),
    ("归属区间", "section_name"),
    ("区间起点站", "section_start_station"),
    ("区间终点站", "section_end_station"),
    ("场段", "yard_name"),
    ("区域", "area_name"),
    ("网络", "network_domain"),
    ("线别", "line_side"),
    ("行车方向", "direction"),
    ("里程", "mileage_text"),
    ("点位说明", "location_desc"),
    ("上联交换机", "uplink_switch"),
    ("上联端口", "uplink_port"),
    ("光模块端口", "optical_port"),
    ("供电站", "power_station"),
    ("电源分配", "power_distribution"),
    ("光缆接入站", "fiber_access_station"),
    ("光缆分配", "fiber_distribution"),
    ("备注", "remark"),
    ("线路名称", "line_name"),
    ("FIT-AP 关联状态（只读）", "fit_ap_status"),
    ("当前光衰状态（只读）", "optical_status"),
    ("来源文件（只读）", "source_file"),
    ("来源工作表（只读）", "source_sheet"),
    ("来源行（只读）", "source_row"),
    ("数据质量问题数（只读）", "issue_count"),
)

_FIELD_NOTES = (
    ("AP名称", "只读", "AC 当前真实 FIT-AP 名称；未匹配运行态时回退为基础资料中的名称。"),
    ("点位编号", "条件必填", "项目定义的 AP 点位编号，也是重命名命令的目标名称。"),
    ("AP MAC", "条件必填", "首选唯一匹配键，支持常见 MAC 格式，导入后规范化为 xxxx-xxxx-xxxx。"),
    ("管理 IP", "只读", "来自当前 FIT-AP 运行态；重新导入不会覆盖正式基础资料。"),
    ("型号", "只读", "来自当前 FIT-AP 运行态；重新导入不会覆盖正式基础资料。"),
    ("归属类型", "可选", "section、station、yard 或 unknown；缺失时按站点/区间推断。"),
    ("归属站点", "可选", "空白默认 KEEP，不清除已有站点。"),
    ("归属区间", "可选", "空白默认 KEEP，不清除已有区间。"),
    ("区间起点站", "可选", "归属区间的起点站。"),
    ("区间终点站", "可选", "归属区间的终点站。"),
    ("场段", "可选", "停车场、车辆段等场段名称。"),
    ("区域", "可选", "安装区域。"),
    ("网络", "可选", "信号/PIS 或 A/B 网等现有业务网络语义。"),
    ("线别", "自动/可选", "优先按正式区间方向和局点映射自动生成；人工或导入确认值不会被静默覆盖。"),
    ("行车方向", "可选", "例如上行、下行。"),
    ("里程", "可选", "允许为空；空白默认 KEEP，不清除已有里程。"),
    ("点位说明", "可选", "安装位置或点位说明。"),
    ("上联交换机", "可选", "正式扩展资料；空白默认 KEEP。"),
    ("上联端口", "可选", "正式扩展资料；空白默认 KEEP。"),
    ("光模块端口", "可选", "光模块或光口标识。"),
    ("供电站", "可选", "供电来源站点。"),
    ("电源分配", "可选", "电源分配说明。"),
    ("光缆接入站", "可选", "光缆接入来源站点。"),
    ("光缆分配", "可选", "光缆分配说明。"),
    ("备注", "可选", "空白默认 KEEP；删除只能通过页面明确操作。"),
    ("线路名称", "可选", "当前局点线路名称。"),
    ("只读导出列", "只读", "FIT-AP、光衰、来源和问题数仅用于查看，重新导入不会覆盖正式资料。"),
)

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
    runtime_raw = raw.get("runtime")
    runtime = dict(runtime_raw) if isinstance(runtime_raw, Mapping) else {}
    mileage_raw = raw.get("mileage")
    mileage = dict(mileage_raw) if isinstance(mileage_raw, Mapping) else {}
    return {
        "ap_name": runtime.get("fit_ap_name") or raw.get("name") or raw.get("ap_name") or "",
        "ap_point_code": raw.get("point_code") or raw.get("ap_point_code") or "",
        "ap_mac": raw.get("mac") or raw.get("ap_mac_display") or raw.get("ap_mac_norm") or "",
        "management_ip": raw.get("management_ip") or "",
        "model": raw.get("model") or "",
        "belong_type": base.get("belong_type") or raw.get("record_kind") or raw.get("belong_type") or "unknown",
        "station_name": raw.get("station") or raw.get("station_name") or "",
        "section_name": raw.get("section") or raw.get("section_name") or "",
        "section_start_station": raw.get("section_start_station") or "",
        "section_end_station": raw.get("section_end_station") or "",
        "yard_name": base.get("yard_name") or raw.get("yard_name") or "",
        "area_name": base.get("area_name") or raw.get("area_name") or "",
        "network_domain": base.get("network_domain") or raw.get("network_domain") or "",
        "line_side": raw.get("line_side") or "",
        "direction": raw.get("direction") or "",
        "mileage_text": mileage.get("normalized") or mileage.get("raw") or raw.get("mileage_text") or "",
        "location_desc": base.get("location_desc") or raw.get("location_desc") or "",
        "uplink_switch": base.get("uplink_switch") or raw.get("uplink_switch") or "",
        "uplink_port": base.get("uplink_port") or raw.get("uplink_port") or "",
        "optical_port": base.get("optical_port") or raw.get("optical_port") or "",
        "power_station": base.get("power_station") or raw.get("power_station") or "",
        "power_distribution": base.get("power_distribution") or raw.get("power_distribution") or "",
        "fiber_access_station": base.get("fiber_access_station") or raw.get("fiber_access_station") or "",
        "fiber_distribution": base.get("fiber_distribution") or raw.get("fiber_distribution") or "",
        "remark": raw.get("remark") or "",
        "line_name": raw.get("line_name") or "",
        "fit_ap_status": runtime.get("fit_ap_status") or "unknown",
        "optical_status": runtime.get("optical_status") or "no_data",
        "source_file": raw.get("source_file") or "",
        "source_sheet": raw.get("source_sheet") or "",
        "source_row": raw.get("source_row") or "",
        "issue_count": raw.get("issue_count") or 0,
    }


__all__ = [
    "TRACKSIDE_AP_BASE_COLUMNS",
    "build_trackside_ap_base_export_name",
    "export_trackside_ap_base_xlsx_task",
]
