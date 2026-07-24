from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.export.common_exporters import ExportCancelled
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]
_UNSAFE_TARGET = re.compile(r'[\x00-\x1f\x7f;|&><"\']')
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')


class TracksideApRenameConflictError(ValueError):
    pass


def build_trackside_ap_rename_export_name(site_display_name: str, created_at: datetime) -> str:
    site_name = _INVALID_FILENAME_CHARS.sub("_", str(site_display_name or "").strip(" ."))
    site_name = re.sub(r"_+", "_", site_name).strip(" .")
    if not site_name:
        raise ValueError("轨旁 AP 重命名命令导出缺少局点名称")
    return f"轨旁AP重命名命令_{site_name}_{created_at:%Y%m%d_%H%M%S}.txt"


def h3c_ap_mac(value: object) -> str:
    normalized = normalize_ap_mac(value).normalized
    if len(normalized) != 12:
        return ""
    return f"{normalized[:4]}-{normalized[4:8]}-{normalized[8:]}"


def build_trackside_ap_rename_commands(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    prepared: list[dict[str, Any]] = []
    skipped: list[str] = []
    mac_targets: dict[str, set[str]] = defaultdict(set)
    target_macs: dict[str, set[str]] = defaultdict(set)
    for index, raw in enumerate(rows, 1):
        runtime_raw = raw.get("runtime")
        runtime = dict(runtime_raw) if isinstance(runtime_raw, Mapping) else {}
        mac = h3c_ap_mac(raw.get("mac") or raw.get("ap_mac_display") or raw.get("ap_mac_norm"))
        point_code = str(raw.get("point_code") or raw.get("ap_point_code") or "").strip()
        actual_name = str(runtime.get("fit_ap_name") or raw.get("name") or raw.get("ap_name") or "").strip()
        label = point_code or actual_name or f"第 {index} 行"
        if not raw.get("mac") and not raw.get("ap_mac_display") and not raw.get("ap_mac_norm"):
            skipped.append(f"{label}：缺少 AP MAC")
            continue
        if not mac:
            skipped.append(f"{label}：AP MAC 格式无效")
            continue
        if not point_code:
            skipped.append(f"{label}：缺少点位编号")
            continue
        if _UNSAFE_TARGET.search(point_code):
            skipped.append(f"{label}：点位编号包含不允许的命令字符")
            continue
        if actual_name and actual_name == point_code:
            skipped.append(f"{label}：名称已一致")
            continue
        mac_targets[mac].add(point_code)
        target_macs[point_code.casefold()].add(mac)
        prepared.append(
            {
                "mac": mac,
                "point_code": point_code,
                "station": str(raw.get("station") or raw.get("station_name") or ""),
                "section": str(raw.get("section") or raw.get("section_name") or ""),
                "mileage": _mileage_value(raw),
            }
        )
    conflicts = [f"MAC {mac} 对应多个点位编号：{'、'.join(sorted(targets))}" for mac, targets in mac_targets.items() if len(targets) > 1]
    conflicts.extend(
        f"点位编号 {target} 对应多个 AP MAC：{'、'.join(sorted(macs))}"
        for target, macs in target_macs.items()
        if len(macs) > 1
    )
    if conflicts:
        raise TracksideApRenameConflictError("；".join(conflicts))
    unique = {(row["mac"], row["point_code"]): row for row in prepared}
    ordered = sorted(
        unique.values(),
        key=lambda row: (row["station"], row["section"], row["mileage"] is None, row["mileage"] or 0, row["point_code"].casefold(), row["mac"]),
    )
    return {
        "commands": [f"wlan rename-ap {row['mac']} {row['point_code']}" for row in ordered],
        "scanned_count": len(rows),
        "valid_command_count": len(ordered),
        "skipped_count": len(skipped),
        "blocking_error_count": 0,
        "warnings": skipped,
    }


def export_trackside_ap_rename_commands_task(
    path: Path,
    payload: Mapping[str, Any],
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> dict[str, Any]:
    if payload.get("draft_rows") is not None:
        rows = [dict(row) for row in list(payload.get("draft_rows") or [])]
    else:
        app_root = str(payload.get("app_root") or "").strip()
        data_root = str(payload.get("data_root") or "").strip()
        paths = PathResolver(app_root=Path(app_root) if app_root else None, data_root=Path(data_root) if data_root else None)
        rows = [item.model_dump() for item in RailTransitBaseDataQueryService(paths).list_ap_export_items(str(payload.get("site_id") or ""))]
    if progress:
        progress("validate", 1, 3, "正在校验轨旁 AP 重命名数据")
    result = build_trackside_ap_rename_commands(rows)
    if should_cancel and should_cancel():
        raise ExportCancelled("导出已取消")
    generated_at = str(payload.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    site_name = str(payload.get("site_display_name") or payload.get("site_id") or "")
    lines = [
        "# NetConsole 轨旁 AP 重命名命令",
        f"# 局点：{site_name}",
        f"# 生成时间：{generated_at}",
        f"# 有效命令：{result['valid_command_count']}",
        f"# 跳过：{result['skipped_count']}",
        "#",
        *result["commands"],
    ]
    path.write_bytes(b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8"))
    if progress:
        progress("write", 3, 3, "轨旁 AP 重命名命令已生成")
    return {**result, "row_count": int(result["valid_command_count"])}


def _mileage_value(raw: Mapping[str, Any]) -> float | None:
    mileage = raw.get("mileage")
    if isinstance(mileage, Mapping) and isinstance(mileage.get("meters"), (int, float)):
        return float(mileage["meters"])
    value = raw.get("mileage_m")
    return float(value) if isinstance(value, (int, float)) else None


__all__ = [
    "TracksideApRenameConflictError",
    "build_trackside_ap_rename_commands",
    "build_trackside_ap_rename_export_name",
    "export_trackside_ap_rename_commands_task",
    "h3c_ap_mac",
]
