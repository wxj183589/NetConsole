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
    if job.task_type == "car_network_refresh_all":
        return _car_network_refresh_all(params, progress_callback, should_cancel)
    if job.task_type == "car_network_generate_point_table":
        return _car_network_generate_point_table(params, progress_callback, should_cancel)
    if job.task_type == "car_network_save_point_table":
        return _car_network_save_point_table(params, progress_callback, should_cancel)
    if job.task_type == "trackside_ap_plan_import":
        return _trackside_ap_plan_import(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_mapping_import":
        return _vehicle_mr_mapping_import(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_online_refresh_all":
        return _vehicle_mr_online_refresh_all(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_history_query":
        return _vehicle_mr_history_query(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_metadata_import":
        return _fit_ap_metadata_import(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_extension_preview":
        return _fit_ap_extension_preview(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_extension_commit":
        return _fit_ap_extension_commit(params, progress_callback, should_cancel)
    if job.task_type == "ac_overview_refresh":
        return _ac_overview_refresh(params, progress_callback, should_cancel)
    if job.task_type == "ac_overview_history_snapshot":
        return _ac_overview_history_snapshot(params, progress_callback, should_cancel)
    if job.task_type == "ac_trackside_business_refresh":
        return _ac_trackside_business_refresh(params, progress_callback, should_cancel)
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
    if job.task_type == "snmp_mib_resource_refresh":
        return _snmp_mib_resource_refresh(params, progress_callback, should_cancel)
    if job.task_type == "snmp_product_references_refresh":
        return _snmp_product_references_refresh(params, progress_callback, should_cancel)
    raise ValueError(f"不支持的后台任务类型：{job.task_type}")


def _path_resolver_from_params(params: dict[str, Any]):
    from netconsole.core.paths import PathResolver

    app_root = str(params.get("app_root") or "").strip() or None
    data_root = str(params.get("data_root") or "").strip() or None
    return PathResolver(app_root=Path(app_root) if app_root else None, data_root=Path(data_root) if data_root else None)


def _snmp_mib_resource_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.global_mib_repository import GlobalMibRepository

    repository = GlobalMibRepository(Path(str(params.get("db_path") or "")))
    _emit(progress, "snmp_mib_resource_refresh", 0, 4, "正在读取 MIB 导入历史")
    _check_cancel(should_cancel)
    file_rows = [
        ["ASN.1 MIB", row.get("file_name"), row.get("module_name"), row.get("compile_status"), row.get("file_hash"), row.get("error_message")]
        for row in repository.list_files()
    ]
    file_rows.extend(
        [
            [
                "产品参考表",
                Path(str(row.get("source_file") or "")).name,
                row.get("reference_name"),
                f"对象覆盖 {row.get('object_override_count', 0)} / Trap 覆盖 {row.get('trap_override_count', 0)}",
                row.get("file_hash"),
                "",
            ]
            for row in repository.list_product_references()
        ]
    )
    _emit(progress, "snmp_mib_resource_refresh", 1, 4, "正在读取 MIB 模块")
    _check_cancel(should_cancel)
    modules = repository.list_modules()
    if bool(params.get("only_missing")):
        modules = [row for row in modules if row.get("status") == "missing_dependencies"]
    module_rows = [
        [
            _snmp_module_display_name(row),
            row.get("status"),
            row.get("object_count"),
            row.get("table_count"),
            row.get("trap_count"),
            row.get("error_message") or ("缺少依赖，未统计对象/表/Trap" if row.get("status") == "missing_dependencies" else ""),
        ]
        for row in modules
    ]
    _emit(progress, "snmp_mib_resource_refresh", 3, 4, "正在读取缺失依赖汇总")
    _check_cancel(should_cancel)
    missing = repository.list_missing_dependency_summary()
    lines = [f"{row.get('dependency_module')}：影响 {row.get('affected_count')} 个 MIB" for row in missing]
    if any(row.get("dependency_module") == "HH3C-OID-MIB" for row in missing):
        lines.insert(0, "提示：大量 H3C 私有 MIB 依赖 HH3C-OID-MIB，请导入完整 H3C Comware MIB 包或补充 HH3C-OID-MIB。")
    if any(str(row.get("dependency_module") or "") in {"SNMP-FRAMEWORK-MIB", "INET-ADDRESS-MIB", "Q-BRIDGE-MIB", "SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF"} for row in missing):
        lines.insert(0, "提示：标准依赖缺失，请补齐内置标准 MIB 或导入标准 MIB 包。")
    _emit(progress, "snmp_mib_resource_refresh", 4, 4, "MIB 资源库刷新完成")
    return {"file_rows": file_rows, "module_rows": module_rows, "missing_summary": "\n".join(lines) if lines else "当前没有缺失依赖。"}


def _snmp_product_references_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.global_mib_repository import GlobalMibRepository

    _emit(progress, "snmp_product_references_refresh", 0, 1, "正在读取产品 MIB 参考表")
    _check_cancel(should_cancel)
    references = GlobalMibRepository(Path(str(params.get("db_path") or ""))).list_product_references()
    _emit(progress, "snmp_product_references_refresh", 1, 1, "产品 MIB 参考表刷新完成")
    return {"references": references}


def _snmp_module_display_name(row: dict[str, object]) -> str:
    module = str(row.get("module_name") or "未归属")
    version = str(row.get("version_line") or "")
    package_version = str(row.get("package_version") or "")
    if version or package_version:
        return f"{module} [H3C {version or '用户导入'} / {package_version or '-'}]"
    if row.get("file_id") is None:
        return f"{module} [内置通用]"
    return module


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
    from netconsole.services.rail_transit.car_network_diagnostic import CarNetworkPointTableStore

    _emit(progress, "car_network_point_table_import", 0, 1, "正在导入车内通信点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    store = CarNetworkPointTableStore(_path_resolver_from_params(params), site_name)
    count = store.import_file(Path(str(params.get("path") or "")))
    nodes = store.load()
    _emit(progress, "car_network_point_table_import", 1, 1, "车内通信点表导入完成")
    return {"count": count, "nodes": [asdict(node) for node in nodes]}


def _car_network_refresh_all(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.rail_transit.car_network_diagnostic import (
        CarNetworkPointTableStore,
        CarNetworkTrain,
        build_car_network_trains,
        sort_car_network_trains,
    )
    from netconsole.services.vehicle_mr_online import normalize_train_no

    _emit(progress, "car_network_refresh_all", 0, 2, "正在加载车内通信点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    paths = _path_resolver_from_params(params)
    nodes = CarNetworkPointTableStore(paths, site_name).load()
    trains = build_car_network_trains(DeviceRepository(Database(Path(str(params.get("db_path") or "")))), site_name)
    if not trains:
        trains = _fallback_car_network_trains(nodes, normalize_train_no)
    trains = sort_car_network_trains(trains)
    nodes = sorted(nodes, key=lambda node: (str(node.train_no or node.train_id), str(node.node_name)))
    _emit(progress, "car_network_refresh_all", 2, 2, "车内通信点表刷新完成")
    return {
        "nodes": [asdict(node) for node in nodes],
        "trains": [asdict(train) if hasattr(train, "__dataclass_fields__") else dict(train) for train in trains],
    }


def _fallback_car_network_trains(nodes: list[Any], normalize_train_no_func: Callable[[object], str]) -> list[Any]:
    from netconsole.services.rail_transit.car_network_diagnostic import CarNetworkTrain, sort_car_network_trains

    trains: list[CarNetworkTrain] = []
    seen: set[str] = set()
    for node in nodes:
        key = str(getattr(node, "train_id", "") or getattr(node, "train_no", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        train_no = str(getattr(node, "train_no", "") or normalize_train_no_func(getattr(node, "train_id", "")))
        trains.append(CarNetworkTrain(str(getattr(node, "train_id", "") or f"列车{train_no}"), train_no, f"{train_no}车" if train_no else str(getattr(node, "train_id", ""))))
    return sort_car_network_trains(trains)


def _car_network_generate_point_table(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.rail_transit.car_network_diagnostic import (
        CarNetworkNode,
        CarNetworkGlobalConfigStore,
        CarNetworkPointTableStore,
        generate_point_table_from_devices,
    )

    _emit(progress, "car_network_generate_point_table", 0, 1, "正在从设备管理生成点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    paths = _path_resolver_from_params(params)
    existing_nodes = [CarNetworkNode(**dict(row)) for row in params.get("nodes") or [] if isinstance(row, dict)]
    global_config = dict(params.get("global_config") or {})
    nodes = generate_point_table_from_devices(DeviceRepository(Database(Path(str(params.get("db_path") or "")))), site_name, existing_nodes, global_config)
    if bool(params.get("save_result")):
        CarNetworkGlobalConfigStore(paths, site_name).save(global_config)
        CarNetworkPointTableStore(paths, site_name).save(nodes)
    _emit(progress, "car_network_generate_point_table", 1, 1, "车内通信点表生成完成")
    return {"nodes": [asdict(node) for node in nodes], "count": len(nodes), "saved": bool(params.get("save_result"))}


def _car_network_save_point_table(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.rail_transit.car_network_diagnostic import (
        CarNetworkGlobalConfigStore,
        CarNetworkNode,
        CarNetworkPointTableStore,
        normalize_train_network_defaults,
    )

    _emit(progress, "car_network_save_point_table", 0, 1, "正在保存车内通信点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    paths = _path_resolver_from_params(params)
    global_config = dict(params.get("global_config") or {})
    nodes = [CarNetworkNode(**dict(row)) for row in params.get("nodes") or [] if isinstance(row, dict)]
    nodes = normalize_train_network_defaults(nodes, global_config, overwrite_custom=bool(params.get("overwrite_custom", False)))
    CarNetworkGlobalConfigStore(paths, site_name).save(global_config)
    CarNetworkPointTableStore(paths, site_name).save(nodes)
    _emit(progress, "car_network_save_point_table", 1, 1, "车内通信点表保存完成")
    return {"nodes": [asdict(node) for node in nodes], "count": len(nodes)}


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
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore

    _emit(progress, "vehicle_mr_mapping_import", 0, 1, "正在导入车载 MR 映射表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    rows = _read_named_table_file(Path(str(params.get("path") or "")))
    count = VehicleMrOnlineStore(_path_resolver_from_params(params), site_name).import_mapping_rows(rows)
    _emit(progress, "vehicle_mr_mapping_import", 1, 1, "车载 MR 映射表导入完成")
    return {"count": count}


def _vehicle_mr_online_refresh_all(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.models.device import Device
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.vehicle_mr_online import (
        build_mapping_trains,
        build_registered_trains,
        load_group_names,
        load_trackside_ap_lookup,
        VehicleMrOnlineStore,
    )

    _emit(progress, "vehicle_mr_online_refresh_all", 0, 5, "正在读取设备和映射")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    repository = DeviceRepository(Database(Path(str(params.get("db_path") or ""))))
    paths = _path_resolver_from_params(params)
    store = VehicleMrOnlineStore(paths, site_name)
    devices = repository.list()
    group_names = load_group_names(repository, site_name)
    device_trains = build_registered_trains(devices, group_names)
    mapping_trains = build_mapping_trains(store.list_mappings())
    registered_trains = {**device_trains, **mapping_trains}
    _emit(progress, "vehicle_mr_online_refresh_all", 2, 5, "正在整理当前列车状态")
    _check_cancel(should_cancel)
    store.cleanup_history(30)
    store.merge_duplicate_current_states_by_train_no(registered_trains)
    store.cleanup_history(30)
    persisted = store.load_current_states()
    merged = {**registered_trains, **persisted}
    for train_id, train in registered_trains.items():
        if train_id in persisted:
            persisted[train_id].is_registered = True
            persisted[train_id].online_policy = train.online_policy
            persisted[train_id].expected_end = train.expected_end
            persisted[train_id].direction = train.direction
            merged[train_id] = persisted[train_id]
    _emit(progress, "vehicle_mr_online_refresh_all", 4, 5, "正在读取轨旁 AP 映射")
    _check_cancel(should_cancel)
    ap_lookup = _jsonable_vehicle_ap_lookup(load_trackside_ap_lookup(repository))
    _emit(progress, "vehicle_mr_online_refresh_all", 5, 5, "车载 MR 在线状态刷新完成")
    return {
        "devices": [device.to_record() if isinstance(device, Device) else dict(device) for device in devices],
        "group_names": {str(key): value for key, value in group_names.items()},
        "registered_trains": {key: asdict(value) for key, value in registered_trains.items()},
        "current_trains": {key: asdict(value) for key, value in merged.items()},
        "ap_lookup": ap_lookup,
    }


def _vehicle_mr_history_query(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore

    _emit(progress, "vehicle_mr_history_query", 0, 1, "正在查询车载 MR 历史")
    _check_cancel(should_cancel)
    store = VehicleMrOnlineStore(_path_resolver_from_params(params), str(params.get("site_name") or ""))
    rows = store.query_events(
        str(params.get("train_id") or ""),
        str(params.get("start_time") or ""),
        str(params.get("end_time") or ""),
        car_end_label=str(params.get("car_end_label") or ""),
        status=str(params.get("status") or ""),
        station=str(params.get("station") or ""),
        ap_name=str(params.get("ap_name") or ""),
        limit=int(params.get("limit") or 1000),
    )
    _emit(progress, "vehicle_mr_history_query", 1, 1, "车载 MR 历史查询完成")
    return {"rows": rows, "limit": int(params.get("limit") or 1000)}


def _jsonable_vehicle_ap_lookup(ap_lookup: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in ap_lookup.items():
        if isinstance(value, list):
            result[key] = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in value]
        elif hasattr(value, "__dataclass_fields__"):
            result[key] = asdict(value)
        else:
            result[key] = value
    return result


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


def _ac_overview_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.ap_online_overview import ApOnlineOverviewService
    from netconsole.services.offline_ap_ledger import build_device_lookup_by_name, build_latest_ap_history_indexes, build_offline_ap_ledger

    _emit(progress, "ac_overview_refresh", 0, 4, "正在读取 FIT-AP 资源")
    _check_cancel(should_cancel)
    ac_uuid = str(params.get("ac_uuid") or "").strip()
    database = Database(Path(str(params.get("db_path") or "")))
    repository = AcRepository(database)
    resources = repository.list_fit_ap_resources_with_metadata(ac_uuid)
    optical_rows = repository.list_fit_ap_optical(ac_uuid)
    metadata_rows = repository.list_fit_ap_metadata()
    _emit(progress, "ac_overview_refresh", 1, 4, "正在读取容量规划")
    _check_cancel(should_cancel)
    capacity_details = repository.list_active_trackside_plan_capacity_details()
    uses_trackside_plan = bool(capacity_details)
    if not capacity_details:
        capacity_details = repository.list_station_ap_capacity_details()
    overview_rows = ApOnlineOverviewService.build_rows(
        metadata_rows=metadata_rows,
        fit_ap_resources=resources,
        optical_rows=optical_rows,
        capacity_details=capacity_details,
    )
    _emit(progress, "ac_overview_refresh", 2, 4, "正在计算离线 AP 台账")
    _check_cancel(should_cancel)
    latest_lldp, _latest_optical = build_latest_ap_history_indexes(repository, resources)
    devices = DeviceRepository(database).list()
    stats, ledger = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap=latest_lldp,
        device_lookup_by_name=build_device_lookup_by_name(devices),
    )
    _emit(progress, "ac_overview_refresh", 4, 4, "AC 在线概览刷新完成")
    return {
        "overview_rows": overview_rows,
        "offline_ap_stats": stats,
        "offline_ap_ledger_rows": ledger,
        "uses_trackside_plan": uses_trackside_plan,
    }


def _ac_overview_history_snapshot(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    payload = _ac_overview_refresh(params, progress, should_cancel)
    _emit(progress, "ac_overview_history_snapshot", 0, 1, "正在保存 AP 在线概览历史")
    _check_cancel(should_cancel)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    count = repository.save_station_online_summary_history([dict(row) for row in payload.get("overview_rows") or [] if isinstance(row, dict)])
    _emit(progress, "ac_overview_history_snapshot", 1, 1, "AP 在线概览历史保存完成")
    return {"count": count}


def _ac_trackside_business_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.core.sources.switch_source import build_switch_data_lookup
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.repositories.device_fact_repository import DeviceFactRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.offline_ap_ledger import build_device_lookup_by_name, build_latest_ap_history_indexes, build_offline_ap_ledger
    from netconsole.services.trackside_ap_business import build_trackside_ap_business_rows, filter_station_switch_devices

    _emit(progress, "ac_trackside_business_refresh", 0, 5, "正在读取设备和接口数据")
    _check_cancel(should_cancel)
    database = Database(Path(str(params.get("db_path") or "")))
    site_name = str(params.get("site_name") or "")
    ac_uuid = str(params.get("ac_uuid") or "").strip()
    device_repository = DeviceRepository(database)
    fact_repository = DeviceFactRepository(database)
    ac_repository = AcRepository(database)
    devices = filter_station_switch_devices(device_repository.list(), database, site_name)
    interfaces_by_device: dict[str, list[dict[str, object | None]]] = {}
    optical_by_device: dict[str, list[dict[str, object | None]]] = {}
    lldp_by_device: dict[str, list[dict[str, object | None]]] = {}
    for index, device in enumerate(devices, start=1):
        _check_cancel(should_cancel)
        device_uuid = str(device.device_uuid or "")
        interfaces_by_device[device_uuid] = fact_repository.list_device_interfaces(device_uuid)
        optical_by_device[device_uuid] = fact_repository.list_optical_modules(device_uuid)
        lldp_by_device[device_uuid] = fact_repository.list_lldp_neighbors(device_uuid)
        if index == len(devices) or index % 10 == 0:
            _emit(progress, "ac_trackside_business_refresh", min(index, len(devices)), max(len(devices), 1), f"正在读取设备事实 {index}/{len(devices)}")
    lookup = build_switch_data_lookup(devices, optical_by_device)
    _emit(progress, "ac_trackside_business_refresh", 3, 5, "正在读取 FIT-AP 和离线台账")
    resources = ac_repository.list_fit_ap_resources_with_metadata(ac_uuid) if ac_uuid else ac_repository.list_all_fit_ap_resources_with_metadata()
    latest_lldp, _latest_optical = build_latest_ap_history_indexes(ac_repository, resources)
    _stats, ledger = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap=latest_lldp,
        device_lookup_by_name=build_device_lookup_by_name(device_repository.list()),
    )
    _emit(progress, "ac_trackside_business_refresh", 4, 5, "正在构建轨旁 AP 业务行")
    _check_cancel(should_cancel)
    rows = build_trackside_ap_business_rows(
        devices,
        interfaces_by_device,
        optical_by_device,
        ac_repository.list_all_fit_ap_optical(),
        lldp_by_device,
        ac_repository.list_all_fit_ap_resources_with_metadata(),
        lookup,
        ac_repository.get_active_trackside_pvid_plan(),
        ledger,
    )
    _emit(progress, "ac_trackside_business_refresh", 5, 5, "轨旁 AP 业务刷新完成")
    return {"rows": rows}


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
