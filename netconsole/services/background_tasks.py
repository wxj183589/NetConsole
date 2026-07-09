from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from netconsole.services.background_job import BackgroundJob

ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class BackgroundTaskCancelled(RuntimeError):
    pass


def run_background_task(job: BackgroundJob, progress_callback: ProgressCallback | None = None, should_cancel: CancelCallback | None = None) -> dict[str, Any]:
    job.validate()
    params = dict(job.params or {})
    if job.task_type == "device_csv_import":
        return _device_csv_import(params, progress_callback, should_cancel)
    if job.task_type == "car_network_point_table_import":
        return _car_network_point_table_import(params, progress_callback, should_cancel)
    if job.task_type == "trackside_ap_plan_import":
        return _trackside_ap_plan_import(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_mapping_import":
        return _vehicle_mr_mapping_import(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_metadata_import":
        return _fit_ap_metadata_import(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_extension_preview":
        return _fit_ap_extension_preview(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_extension_commit":
        return _fit_ap_extension_commit(params, progress_callback, should_cancel)
    if job.task_type == "config_compare_latest_running_between_devices":
        return _config_compare_latest_running_between_devices(params, progress_callback, should_cancel)
    if job.task_type == "config_compare_latest_snapshots":
        return _config_compare_latest_snapshots(params, progress_callback, should_cancel)
    if job.task_type == "config_compare_snapshot_pair":
        return _config_compare_snapshot_pair(params, progress_callback, should_cancel)
    if job.task_type == "online_mr_parse":
        return _online_mr_parse(params, progress_callback, should_cancel)
    if job.task_type == "mesh_log_import":
        return _mesh_log_import(params, progress_callback, should_cancel)
    if job.task_type == "mesh_derived_rebuild":
        return _mesh_derived_rebuild(params, progress_callback, should_cancel)
    if job.task_type == "online_mr_report_export":
        return _online_mr_report_export(params, progress_callback, should_cancel)
    raise ValueError(f"不支持的后台任务类型：{job.task_type}")


def _path_resolver_from_params(params: dict[str, Any]):
    from netconsole.core.paths import PathResolver

    app_root = str(params.get("app_root") or "").strip() or None
    data_root = str(params.get("data_root") or "").strip() or None
    return PathResolver(app_root=Path(app_root) if app_root else None, data_root=Path(data_root) if data_root else None)


def _device_csv_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.device_import_export import DeviceImportExportService

    _emit(progress, "device_csv_import", 0, 1, "正在导入设备 CSV")
    _check_cancel(should_cancel)
    db_path = Path(str(params.get("db_path") or ""))
    site_name = str(params.get("site_name") or "")
    database = Database(db_path)
    service = DeviceImportExportService(DeviceRepository(database), DeviceGroupRepository(database, site_name) if site_name else None)
    result = service.import_csv(Path(str(params.get("path") or "")))
    _emit(progress, "device_csv_import", 1, 1, "设备 CSV 导入完成")
    return {
        "created": result.created,
        "skipped": result.skipped,
        "groups_created": result.groups_created,
        "errors": list(result.errors),
    }


def _car_network_point_table_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.paths import PathResolver
    from netconsole.services.rail_transit.car_network_diagnostic import CarNetworkPointTableStore

    _emit(progress, "car_network_point_table_import", 0, 1, "正在导入车内通信点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    count = CarNetworkPointTableStore(PathResolver(), site_name).import_file(Path(str(params.get("path") or "")))
    _emit(progress, "car_network_point_table_import", 1, 1, "车内通信点表导入完成")
    return {"count": count}


def _trackside_ap_plan_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE

    _emit(progress, "trackside_ap_plan_import", 0, 1, "正在导入轨旁 AP 规划")
    _check_cancel(should_cancel)
    rows = _dedupe_trackside_station_rows(_read_trackside_plan_file(Path(str(params.get("path") or ""))))
    _validate_trackside_plan_rows(rows)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    repository.replace_trackside_ap_plan_rows(str(params.get("mode") or TRACKSIDE_AP_PLAN_MODE), rows)
    _emit(progress, "trackside_ap_plan_import", 1, 1, "轨旁 AP 规划导入完成")
    return {"count": len(rows)}


def _vehicle_mr_mapping_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.paths import PathResolver
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore

    _emit(progress, "vehicle_mr_mapping_import", 0, 1, "正在导入车载 MR 映射表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    rows = _read_named_table_file(Path(str(params.get("path") or "")))
    count = VehicleMrOnlineStore(PathResolver(), site_name).import_mapping_rows(rows)
    _emit(progress, "vehicle_mr_mapping_import", 1, 1, "车载 MR 映射表导入完成")
    return {"count": count}


def _fit_ap_metadata_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.services.fit_ap_import_export import FitApImportExportService

    _emit(progress, "fit_ap_metadata_import", 0, 1, "正在导入 FIT-AP 元数据")
    _check_cancel(should_cancel)
    service = FitApImportExportService(AcRepository(Database(Path(str(params.get("db_path") or "")))))
    result = service.import_metadata_file(Path(str(params.get("path") or "")))
    _emit(progress, "fit_ap_metadata_import", 1, 1, "FIT-AP 元数据导入完成")
    return {"updated": result.updated, "skipped": result.skipped, "errors": list(result.errors)}


def _fit_ap_extension_preview(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.services.fit_ap_import_export import FitApImportExportService

    _emit(progress, "fit_ap_extension_preview", 0, 1, "正在解析 AP 扩展信息预览")
    _check_cancel(should_cancel)
    service = FitApImportExportService(AcRepository(Database(Path(str(params.get("db_path") or "")))))
    preview = service.preview_ap_extension_import(Path(str(params.get("path") or "")), str(params.get("import_mode") or "standard_template"))
    _emit(progress, "fit_ap_extension_preview", 1, 1, "AP 扩展信息预览完成")
    return {
        "file_name": preview.file_name,
        "template_type": preview.template_type,
        "confidence_score": preview.confidence_score,
        "sheet_count": len(preview.sheets),
        "summary": dict(preview.summary),
        "low_confidence": bool(preview.low_confidence),
    }


def _fit_ap_extension_commit(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.services.fit_ap_import_export import FitApImportExportService

    _emit(progress, "fit_ap_extension_commit", 0, 2, "正在解析 AP 扩展信息")
    _check_cancel(should_cancel)
    service = FitApImportExportService(AcRepository(Database(Path(str(params.get("db_path") or "")))))
    preview = service.preview_ap_extension_import(Path(str(params.get("path") or "")), str(params.get("import_mode") or "standard_template"))
    _emit(progress, "fit_ap_extension_commit", 1, 2, "正在写入 AP 扩展信息")
    _check_cancel(should_cancel)
    stats = service.commit_ap_extension_import(preview, duplicate_strategy=str(params.get("duplicate_strategy") or "update_by_priority"))
    _emit(progress, "fit_ap_extension_commit", 2, 2, "AP 扩展信息导入完成")
    return dict(stats)


def _config_compare_latest_running_between_devices(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
    from netconsole.services.config_lifecycle_service import ConfigLifecycleService, compare_named_config_text, structure_diff

    _emit(progress, "config_compare", 0, 1, "正在比较两台设备最新 running 配置")
    _check_cancel(should_cancel)
    database = Database(Path(str(params.get("db_path") or "")))
    repository = ConfigSnapshotRepository(database)
    service = ConfigLifecycleService(str(params.get("site_name") or ""), database, _path_resolver_from_params(params), repository)
    device_a = _device_by_uuid(database, str(params.get("device_uuid_a") or ""))
    device_b = _device_by_uuid(database, str(params.get("device_uuid_b") or ""))
    running_a = service.list_device_snapshots(device_a, "running")
    running_b = service.list_device_snapshots(device_b, "running")
    if not running_a or not running_b:
        raise ValueError("两台设备都需要先采集 running 配置。")
    text_a = service.snapshot_text(running_a[0])
    text_b = service.snapshot_text(running_b[0])
    name_a = str(device_a.name or device_a.system_name or device_a.device_uuid or "device_a")
    name_b = str(device_b.name or device_b.system_name or device_b.device_uuid or "device_b")
    diff = compare_named_config_text(text_a, text_b, name_a, name_b)
    _emit(progress, "config_compare", 1, 1, "配置比较完成")
    return {
        "kind": "two_devices",
        "left_label": name_a,
        "right_label": name_b,
        "left_text": text_a,
        "right_text": text_b,
        "raw_diff": diff.raw_diff,
        "structure_diff": structure_diff(text_a, text_b),
    }


def _config_compare_latest_snapshots(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
    from netconsole.services.config_lifecycle_service import ConfigLifecycleService

    _emit(progress, "config_compare", 0, 1, "正在比较最新 running/saved 配置")
    _check_cancel(should_cancel)
    database = Database(Path(str(params.get("db_path") or "")))
    repository = ConfigSnapshotRepository(database)
    service = ConfigLifecycleService(str(params.get("site_name") or ""), database, _path_resolver_from_params(params), repository)
    device = _device_by_uuid(database, str(params.get("device_uuid") or ""))
    running = service.list_device_snapshots(device, "running")
    saved = service.list_device_snapshots(device, "saved")
    if not running or not saved:
        raise ValueError("需要先采集 running 和 saved 配置。")
    result = _compare_snapshot_texts(service, running[0], saved[0])
    result["kind"] = "latest_snapshots"
    _emit(progress, "config_compare", 1, 1, "配置比较完成")
    return result


def _config_compare_snapshot_pair(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
    from netconsole.services.config_lifecycle_service import ConfigLifecycleService

    _emit(progress, "config_compare", 0, 1, "正在比较配置快照")
    _check_cancel(should_cancel)
    database = Database(Path(str(params.get("db_path") or "")))
    repository = ConfigSnapshotRepository(database)
    service = ConfigLifecycleService(str(params.get("site_name") or ""), database, _path_resolver_from_params(params), repository)
    left = repository.get(int(params.get("left_snapshot_id") or 0))
    right = repository.get(int(params.get("right_snapshot_id") or 0))
    result = _compare_snapshot_texts(service, left, right)
    result["kind"] = "snapshot_pair"
    _emit(progress, "config_compare", 1, 1, "配置比较完成")
    return result


def _compare_snapshot_texts(service: Any, left: Any, right: Any) -> dict[str, Any]:
    diff = service.compare_snapshots(left, right)
    return {
        "left_label": str(getattr(left, "type", "") or "left"),
        "right_label": str(getattr(right, "type", "") or "right"),
        "left_text": service.snapshot_text(left),
        "right_text": service.snapshot_text(right),
        "raw_diff": diff.raw_diff,
    }


def _device_by_uuid(database: Any, device_uuid: str):
    from netconsole.models.device import Device

    if not device_uuid:
        raise ValueError("缺少设备 UUID")
    with database.connect() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_uuid = ?", (device_uuid,)).fetchone()
    if row is None:
        raise KeyError(f"未找到设备：{device_uuid}")
    return Device.from_mapping(dict(row))


def _online_mr_parse(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser

    summary = OnlineMrDiagnosisParser(Path(str(params.get("session_dir") or ""))).parse(
        force=bool(params.get("force_reparse", True)),
        progress=progress,
        should_cancel=should_cancel,
    )
    return asdict(summary)


def _mesh_log_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.paths import PathResolver
    from netconsole.models.mesh_log_models import MeshMrProfile
    from netconsole.services.mesh_import_service import MeshImportService

    site_name = str(params.get("site_name") or "")
    profile_data = dict(params.get("profile") or {})
    profile = MeshMrProfile(
        mr_id=str(profile_data.get("mr_id") or ""),
        display_name=str(profile_data.get("display_name") or ""),
        safe_folder_name=str(profile_data.get("safe_folder_name") or ""),
        relative_folder_path=str(profile_data.get("relative_folder_path") or ""),
        linked_device_id=int(profile_data["linked_device_id"]) if profile_data.get("linked_device_id") is not None else None,
        notes=str(profile_data.get("notes") or ""),
    )
    files = [Path(str(path)) for path in params.get("files") or []]

    def emit_mesh_progress(file_index: int, total_files: int, lines: int, parsed: int, skipped: int) -> None:
        _emit(progress, f"mesh_log_import:{int(lines)}:{int(parsed)}:{int(skipped)}", int(file_index), int(total_files), "正在导入 MESH 日志")

    result = MeshImportService(site_name, PathResolver()).import_files(
        profile,
        files,
        should_cancel=should_cancel,
        progress=emit_mesh_progress,
    )
    return {
        "imported_count": result.imported_count,
        "duplicate_count": result.duplicate_count,
        "parsed_record_count": result.parsed_record_count,
        "issue_count": len(result.issues),
        "file_count": len(result.files),
    }


def _mesh_derived_rebuild(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.mesh_mr_repository import MeshMrRepository

    processed = 0

    def emit_rebuild_progress(value: int) -> None:
        nonlocal processed
        processed = int(value or 0)
        _emit(progress, "mesh_derived_rebuild", processed, 0, f"已重建 {processed} 条派生分析")

    MeshMrRepository(Path(str(params.get("db_path") or ""))).rebuild_derived_analysis(
        should_cancel=should_cancel,
        progress=emit_rebuild_progress,
    )
    return {"processed": processed}


def _online_mr_report_export(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.vehicle_mr_offline_excel_report import VehicleMrOfflineExcelReportExporter

    session_dir = Path(str(params.get("session_dir") or ""))
    output_path = Path(str(params.get("output_path") or ""))
    _emit(progress, "online_mr_report_prepare", 1, 3, "正在读取 parsed 数据")
    _check_cancel(should_cancel)
    result = VehicleMrOfflineExcelReportExporter().export(session_dir, output_path)
    _emit(progress, "online_mr_report_done", 3, 3, "离线分析报告导出完成")
    return {"path": str(result), "row_count": 1 if result.exists() else 0}


TRACKSIDE_PLAN_HEADERS = ["车站名称", "AP数量", "AP起始地址", "掩码", "AP网关", "AP管理VLAN", "备注"]
TRACKSIDE_PLAN_FIELDS = ["station_name", "ap_count", "ap_start_address", "mask_length", "ap_gateway", "ap_management_vlans", "remark"]
MASK_ERROR_TEXT = "必须是0-32或合法连续IPv4掩码"


def _read_trackside_plan_file(path: Path) -> list[dict[str, object | None]]:
    return [{field: row.get(header, "") for header, field in zip(TRACKSIDE_PLAN_HEADERS, TRACKSIDE_PLAN_FIELDS, strict=False)} for row in _read_named_table_file(path)]


def _read_named_table_file(path: Path) -> list[dict[str, object]]:
    if path.suffix.casefold() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    from netconsole.utils.excel_workbook import load_workbook_without_unsupported_image_warning

    workbook = load_workbook_without_unsupported_image_warning(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(value or "").strip() for value in rows[0]]
    return [{headers[index]: value for index, value in enumerate(values) if index < len(headers)} for values in rows[1:]]


def _validate_trackside_plan_rows(rows: list[dict[str, object | None]]) -> None:
    from netconsole.services.trackside_ap_business import parse_vlan_set

    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        station = str(row.get("station_name") or "").strip()
        if not station:
            raise ValueError(f"第{index}行 车站名称：必填")
        if station.casefold() in seen:
            continue
        seen.add(station.casefold())
        try:
            row["ap_count"] = int(str(row.get("ap_count") or "0").strip())
        except ValueError:
            raise ValueError(f"第{index}行 AP数量：必须是整数") from None
        if int(row["ap_count"] or 0) < 0:
            raise ValueError(f"第{index}行 AP数量：必须是非负整数")
        mask_length = _parse_mask_length(row.get("mask_length"))
        if mask_length is None and str(row.get("mask_length") or "").strip():
            raise ValueError(f"第{index}行 掩码：{MASK_ERROR_TEXT}")
        row["mask_length"] = mask_length
        vlans = parse_vlan_set(row.get("ap_management_vlans"))
        if not vlans:
            raise ValueError(f"第{index}行 AP管理VLAN：必填")
        row["station_name"] = station
        row["ap_management_vlans"] = ",".join(str(vlan) for vlan in sorted(vlans))
        start = str(row.get("ap_start_address") or "").strip()
        gateway = str(row.get("ap_gateway") or "").strip()
        if start and not _valid_ipv4_or_placeholder(start):
            raise ValueError(f"第{index}行 AP起始地址：格式无效")
        if gateway and not _valid_ipv4(gateway):
            raise ValueError(f"第{index}行 AP网关：必须是IPv4")


def _dedupe_trackside_station_rows(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    by_station: dict[str, dict[str, object | None]] = {}
    order: list[str] = []
    for row in rows:
        station = str(row.get("station_name") or "").strip()
        key = station.casefold()
        if not key:
            key = f"__blank_{len(order)}"
        if key not in by_station:
            order.append(key)
        by_station[key] = row
    result = [by_station[key] for key in order if key in by_station]
    for index, row in enumerate(result):
        row["sort_order"] = index
    return result


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
    try:
        octets = [int(part) for part in parts]
    except ValueError:
        return None
    if any(octet < 0 or octet > 255 for octet in octets):
        return None
    bits = "".join(f"{octet:08b}" for octet in octets)
    if not all(char == "1" for char in bits[: bits.count("1")]) or "1" in bits[bits.count("1") :]:
        return None
    return bits.count("1")


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


def _emit(progress: ProgressCallback | None, stage: str, current: int, total: int, message: str) -> None:
    if progress:
        progress(stage, current, total, message)


def _check_cancel(should_cancel: CancelCallback | None) -> None:
    if should_cancel and should_cancel():
        raise BackgroundTaskCancelled("后台任务已取消")
