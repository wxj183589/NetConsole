from __future__ import annotations

import csv
import shutil
from dataclasses import asdict
from datetime import datetime
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
    if job.task_type == "device_list_page":
        return _device_list_page(params, progress_callback, should_cancel)
    if job.task_type == "device_object_history_page":
        return _device_object_history_page(params, progress_callback, should_cancel)
    if job.task_type == "trackside_interface_history_page":
        return _trackside_interface_history_page(params, progress_callback, should_cancel)
    if job.task_type == "car_network_point_table_import":
        return _car_network_point_table_import(params, progress_callback, should_cancel)
    if job.task_type == "car_network_point_table_load":
        return _car_network_point_table_load(params, progress_callback, should_cancel)
    if job.task_type == "car_network_refresh_all":
        return _car_network_refresh_all(params, progress_callback, should_cancel)
    if job.task_type == "car_network_generate_point_table":
        return _car_network_generate_point_table(params, progress_callback, should_cancel)
    if job.task_type == "car_network_save_point_table":
        return _car_network_save_point_table(params, progress_callback, should_cancel)
    if job.task_type == "trackside_ap_plan_import":
        return _trackside_ap_plan_import(params, progress_callback, should_cancel)
    if job.task_type == "trackside_ap_plan_refresh":
        return _trackside_ap_plan_refresh(params, progress_callback, should_cancel)
    if job.task_type == "trackside_ap_plan_save":
        return _trackside_ap_plan_save(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_mapping_import":
        return _vehicle_mr_mapping_import(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_mapping_load":
        return _vehicle_mr_mapping_load(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_mapping_save":
        return _vehicle_mr_mapping_save(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_online_refresh_all":
        return _vehicle_mr_online_refresh_all(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_ap_mapping_refresh":
        return _vehicle_mr_ap_mapping_refresh(params, progress_callback, should_cancel)
    if job.task_type == "vehicle_mr_event_page":
        return _vehicle_mr_event_page(params, progress_callback, should_cancel)
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
    if job.task_type == "ac_fit_ap_resources_refresh":
        return _ac_fit_ap_resources_refresh(params, progress_callback, should_cancel)
    if job.task_type == "ac_fit_ap_optical_refresh":
        return _ac_fit_ap_optical_refresh(params, progress_callback, should_cancel)
    if job.task_type == "ac_ap_extensions_refresh":
        return _ac_ap_extensions_refresh(params, progress_callback, should_cancel)
    if job.task_type == "omnipeek_name_table_preview":
        return _omnipeek_name_table_preview(params, progress_callback, should_cancel)
    if job.task_type == "ac_overview_history_snapshot":
        return _ac_overview_history_snapshot(params, progress_callback, should_cancel)
    if job.task_type == "ac_station_online_history_page":
        return _ac_station_online_history_page(params, progress_callback, should_cancel)
    if job.task_type == "ac_ap_history_page":
        return _ac_ap_history_page(params, progress_callback, should_cancel)
    if job.task_type == "ac_trackside_business_refresh":
        return _ac_trackside_business_refresh(params, progress_callback, should_cancel)
    if job.task_type == "config_compare_latest_running_between_devices":
        return _config_compare_latest_running_between_devices(params, progress_callback, should_cancel)
    if job.task_type == "config_compare_latest_snapshots":
        return _config_compare_latest_snapshots(params, progress_callback, should_cancel)
    if job.task_type == "config_compare_snapshot_pair":
        return _config_compare_snapshot_pair(params, progress_callback, should_cancel)
    if job.task_type == "config_snapshot_load_content":
        return _config_snapshot_load_content(params, progress_callback, should_cancel)
    if job.task_type == "config_snapshot_copy":
        return _config_snapshot_copy(params, progress_callback, should_cancel)
    if job.task_type == "config_snapshot_pair_load_content":
        return _config_snapshot_pair_load_content(params, progress_callback, should_cancel)
    if job.task_type == "config_snapshot_delete_many":
        return _config_snapshot_delete_many(params, progress_callback, should_cancel)
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
    if job.task_type == "snmp_center_data_refresh":
        return _snmp_center_data_refresh(params, progress_callback, should_cancel)
    if job.task_type == "snmp_center_data_action":
        return _snmp_center_data_action(params, progress_callback, should_cancel)
    if job.task_type == "wireless_scan_history_refresh":
        return _wireless_scan_history_refresh(params, progress_callback, should_cancel)
    if job.task_type == "wireless_scan_result_load":
        return _wireless_scan_result_load(params, progress_callback, should_cancel)
    if job.task_type == "wifi_survey_refresh":
        return _wifi_survey_refresh(params, progress_callback, should_cancel)
    if job.task_type == "wifi_survey_floor_import":
        return _wifi_survey_floor_import(params, progress_callback, should_cancel)
    if job.task_type == "wifi_survey_create_session":
        return _wifi_survey_create_session(params, progress_callback, should_cancel)
    if job.task_type == "wifi_survey_update_scale":
        return _wifi_survey_update_scale(params, progress_callback, should_cancel)
    if job.task_type == "wifi_survey_save_sample":
        return _wifi_survey_save_sample(params, progress_callback, should_cancel)
    if job.task_type == "wifi_survey_heatmap_render":
        return _wifi_survey_heatmap_render(params, progress_callback, should_cancel)
    if job.task_type == "ac_devices_refresh":
        return _ac_devices_refresh(params, progress_callback, should_cancel)
    if job.task_type == "ac_fit_ap_delete_many":
        return _ac_fit_ap_delete_many(params, progress_callback, should_cancel)
    if job.task_type == "ac_ap_extension_save":
        return _ac_ap_extension_save(params, progress_callback, should_cancel)
    if job.task_type == "ac_ap_extension_delete":
        return _ac_ap_extension_delete(params, progress_callback, should_cancel)
    if job.task_type == "ac_ap_extension_clear":
        return _ac_ap_extension_clear(params, progress_callback, should_cancel)
    if job.task_type == "ac_station_overview_value_save":
        return _ac_station_overview_value_save(params, progress_callback, should_cancel)
    if job.task_type == "device_detail_load_all":
        return _device_detail_load_all(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_detail_load":
        return _fit_ap_detail_load(params, progress_callback, should_cancel)
    if job.task_type == "fit_ap_metadata_save":
        return _fit_ap_metadata_save(params, progress_callback, should_cancel)
    if job.task_type == "online_mr_collection_devices_refresh":
        return _online_mr_collection_devices_refresh(params, progress_callback, should_cancel)
    if job.task_type == "online_mr_mark_stale_sessions":
        return _online_mr_mark_stale_sessions(params, progress_callback, should_cancel)
    if job.task_type == "mesh_mr_profiles_refresh":
        return _mesh_mr_profiles_refresh(params, progress_callback, should_cancel)
    if job.task_type == "file_management_navigation_refresh":
        return _file_management_navigation_refresh(params, progress_callback, should_cancel)
    if job.task_type == "device_mutation":
        return _device_mutation(params, progress_callback, should_cancel)
    if job.task_type == "device_lookup":
        return _device_lookup(params, progress_callback, should_cancel)
    if job.task_type == "device_group_refresh":
        return _device_group_refresh(params, progress_callback, should_cancel)
    if job.task_type == "device_group_create":
        return _device_group_create(params, progress_callback, should_cancel)
    if job.task_type == "device_group_rename":
        return _device_group_rename(params, progress_callback, should_cancel)
    if job.task_type == "device_group_count_devices":
        return _device_group_count_devices(params, progress_callback, should_cancel)
    if job.task_type == "device_group_delete":
        return _device_group_delete(params, progress_callback, should_cancel)
    if job.task_type == "trackside_device_detail_resolve":
        return _trackside_device_detail_resolve(params, progress_callback, should_cancel)
    if job.task_type == "trackside_fit_ap_detail_resolve":
        return _trackside_fit_ap_detail_resolve(params, progress_callback, should_cancel)
    if job.task_type == "network_profile_store":
        return _network_profile_store(params, progress_callback, should_cancel)
    raise ValueError(f"不支持的后台任务类型：{job.task_type}")


def _path_resolver_from_params(params: dict[str, Any]):
    from netconsole.core.paths import PathResolver

    app_root = str(params.get("app_root") or "").strip() or None
    data_root = str(params.get("data_root") or "").strip() or None
    return PathResolver(app_root=Path(app_root) if app_root else None, data_root=Path(data_root) if data_root else None)


def _online_mr_mark_stale_sessions(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.online_mr_session_store import OnlineMrSessionStore

    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    changed = OnlineMrSessionStore(_path_resolver_from_params(params)).mark_stale_sessions_aborted(site_name)
    return {"changed_count": len(changed)}


def _write_background_text_artifact(params: dict[str, Any], subdir: str, prefix: str, text: str) -> Path:
    cache_dir = _path_resolver_from_params(params).runtime_cache_dir / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    path.write_text(text, encoding="utf-8")
    return path


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
    repository = GlobalMibRepository(Path(str(params.get("db_path") or "")))
    references = repository.list_product_references()
    tree_nodes: list[dict[str, object]] = []
    visited: set[int] = set()

    def collect(reference_id: int, parent_id: int | None) -> None:
        for node in repository.list_product_reference_tree_nodes(reference_id, parent_id):
            node_id = int(node.get("id") or 0)
            if not node_id or node_id in visited:
                continue
            visited.add(node_id)
            tree_nodes.append(node)
            _check_cancel(should_cancel)
            collect(reference_id, node_id)

    for reference in references:
        reference_id = int(reference.get("id") or 0)
        if reference_id:
            collect(reference_id, None)
    _emit(progress, "snmp_product_references_refresh", 1, 1, "产品 MIB 参考表刷新完成")
    return {"references": references, "tree_nodes": tree_nodes}


def _snmp_center_data_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.repositories.global_mib_repository import GlobalMibRepository
    from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
    from netconsole.services.snmp_poll_service import SnmpPollService
    from netconsole.services.snmp_trap_service import SnmpTrapService

    view = str(params.get("view") or "")
    _emit(progress, "snmp_center_data_refresh", 0, 1, f"正在后台刷新 SNMP {view}")
    _check_cancel(should_cancel)
    global_repo = GlobalMibRepository(Path(str(params.get("global_db_path") or "")))
    site_repo = SiteSnmpRepository(Path(str(params.get("site_snmp_db_path") or "")))
    limit = max(1, min(int(params.get("limit") or 500), 2000))
    result: dict[str, Any] = {"view": view}
    if view == "overview":
        device_count = len(DeviceRepository(Database(Path(str(params.get("site_db_path") or "")))).list())
        result["summary"] = {**global_repo.startup_summary(), **site_repo.startup_summary(), "device_count": device_count}
    elif view == "dictionary_sets":
        result["rows"] = global_repo.list_dictionary_sets()[:limit]
    elif view == "devices":
        from netconsole.repositories.device_group_repository import DeviceGroupRepository

        database = Database(Path(str(params.get("site_db_path") or "")))
        filters = dict(params.get("filters") or {})
        allowed_filters = {key: filters.get(key) for key in ("search", "vendor", "device_type", "group_filter") if filters.get(key) is not None}
        devices = DeviceRepository(database).list(**allowed_filters)[:limit]
        result["devices"] = [device.to_record() for device in devices]
        result["enabled_dictionary_ids"] = {
            str(device.device_uuid or device.id): site_repo.list_enabled_dictionary_ids(str(device.device_uuid or device.id))
            for device in devices
        }
        groups = DeviceGroupRepository(database, str(params.get("site_name") or "")).list()
        result["groups"] = [{"id": group.id, "name": group.name} for group in groups if group.id is not None]
    elif view == "templates":
        result["global_rows"] = global_repo.list_templates()[:limit]
        result["site_rows"] = site_repo.list_site_templates()[:limit]
    elif view == "monitor_jobs":
        result["rows"] = SnmpPollService(site_repo).list_jobs()[:limit]
    elif view == "traps":
        result["rows"] = SnmpTrapService(site_repo).list_traps()[:limit]
    elif view == "topology":
        result["nodes"] = site_repo.list_topology_nodes()[:limit]
        result["edges"] = site_repo.list_topology_edges()[:limit]
    elif view == "mib_detail_lookup":
        module_name = str(params.get("module_name") or "")
        object_name = str(params.get("object_name") or "")
        oid = str(params.get("oid") or "")
        syntax = str(params.get("syntax") or "")
        source_text = str(params.get("source_text") or "")
        result["object_override"] = global_repo.find_product_object_override(
            module_name=module_name,
            object_name=object_name,
            numeric_oid=oid,
        )
        result["trap_override"] = (
            global_repo.find_product_trap_override(
                module_name=module_name,
                trap_name=object_name,
                trap_oid=oid,
            )
            if "trap" in syntax.casefold() or bool(params.get("is_trap"))
            else None
        )
        result["translation"] = global_repo.get_object_translation(
            module_name=module_name,
            object_name=object_name,
            numeric_oid=oid,
            source_text=source_text,
        )
    else:
        raise ValueError(f"不支持的 SNMP 后台刷新视图：{view}")
    _emit(progress, "snmp_center_data_refresh", 1, 1, f"SNMP {view} 刷新完成")
    return result


def _snmp_center_data_action(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.models.snmp_models import DictionaryRecommendation, DeviceSnmpProfileResult
    from netconsole.repositories.global_mib_repository import GlobalMibRepository
    from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
    from netconsole.services.mib_dictionary_service import MibDictionaryService

    action = str(params.get("action") or "")
    _emit(progress, "snmp_center_data_action", 0, 1, f"正在执行 SNMP 操作：{action}")
    _check_cancel(should_cancel)
    global_repo = GlobalMibRepository(Path(str(params.get("global_db_path") or "")))
    site_repo = SiteSnmpRepository(Path(str(params.get("site_snmp_db_path") or "")))
    if action == "create_dictionary":
        result = {"id": MibDictionaryService(global_repo).create_dictionary_set(str(params.get("name") or ""))}
    elif action == "create_template":
        result = {
            "id": global_repo.create_template(
                name=str(params.get("name") or ""),
                oid=str(params.get("oid") or ""),
                method=str(params.get("method") or "Get"),
                module_name=str(params.get("module_name") or ""),
                object_name=str(params.get("object_name") or ""),
            )
        }
    elif action == "save_profile_recommendations":
        from netconsole.models.device import Device
        from netconsole.services.snmp_recommend_service import SnmpRecommendService

        device_id = str(params.get("device_id") or "")
        profile = DeviceSnmpProfileResult(**dict(params.get("profile") or {}))
        device_payload = dict(params.get("device") or {})
        if device_payload:
            device = Device.from_mapping(device_payload)
            recommend_service = SnmpRecommendService(global_repo)
            recommendations = recommend_service.recommend(device, profile)
            reference_recommendations = recommend_service.recommend_product_references(device, profile)
        else:
            recommendations = [DictionaryRecommendation(**dict(row)) for row in params.get("recommendations") or []]
            reference_recommendations = []
        site_repo.save_device_profile(device_id, profile)
        site_repo.save_recommendations(device_id, recommendations)
        result = {
            "saved": True,
            "recommendations": [asdict(item) for item in recommendations],
            "reference_recommendations": [asdict(item) for item in reference_recommendations],
        }
    elif action == "apply_recommendations":
        recommendations = [DictionaryRecommendation(**dict(row)) for row in params.get("recommendations") or []]
        site_repo.apply_recommendations(str(params.get("device_id") or ""), recommendations)
        result = {"applied": len(recommendations)}
    elif action == "set_snmp_set_enabled":
        site_repo.set_snmp_set_enabled(bool(params.get("enabled")))
        result = {"enabled": bool(params.get("enabled"))}
    elif action == "generate_recommended_view":
        from netconsole.models.device import Device
        from netconsole.services.snmp_recommend_service import SnmpRecommendService

        device = Device.from_mapping(dict(params.get("device") or {}))
        device_id = str(device.device_uuid or device.id)
        profile_row = site_repo.latest_device_profile(device_id) or {}
        profile = DeviceSnmpProfileResult(
            device_name=str(profile_row.get("device_name") or device.name),
            vendor=str(profile_row.get("vendor") or device.device_vendor or ""),
            device_type=str(profile_row.get("device_type") or device.device_type or ""),
            model=str(profile_row.get("model") or ""),
            system=str(profile_row.get("system") or ""),
            system_version=str(profile_row.get("system_version") or ""),
            sys_object_id=str(profile_row.get("sys_object_id") or ""),
            sys_descr=str(profile_row.get("sys_descr") or ""),
            sys_up_time=str(profile_row.get("sys_up_time") or ""),
            status=str(profile_row.get("status") or "cached"),
        )
        recommendations = SnmpRecommendService(global_repo).recommend(device, profile)
        if recommendations:
            site_repo.apply_recommendations(device_id, recommendations)
        result = {"applied": len(recommendations)}
    elif action == "upsert_translation":
        global_repo.upsert_object_translation(
            object_id=int(params.get("object_id") or 0) or None,
            module_name=str(params.get("module_name") or ""),
            object_name=str(params.get("object_name") or ""),
            numeric_oid=str(params.get("numeric_oid") or ""),
            source_text=str(params.get("source_text") or ""),
            translated_text=str(params.get("translated_text") or ""),
        )
        result = {"saved": True}
    else:
        raise ValueError(f"不支持的 SNMP 后台操作：{action}")
    _emit(progress, "snmp_center_data_action", 1, 1, f"SNMP 操作完成：{action}")
    return {"action": action, **result}


def _snmp_module_display_name(row: dict[str, object]) -> str:
    module = str(row.get("module_name") or "未归属")
    version = str(row.get("version_line") or "")
    package_version = str(row.get("package_version") or "")
    if version or package_version:
        return f"{module} [H3C {version or '用户导入'} / {package_version or '-'}]"
    if row.get("file_id") is None:
        return f"{module} [内置通用]"
    return module


def _wireless_scan_history_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.wireless_scan_repository import WirelessScanRepository

    repository = WirelessScanRepository(Path(str(params.get("db_path") or "")))
    runs = repository.list_runs(limit=max(1, min(int(params.get("limit") or 200), 500)))
    rows: list[dict[str, Any]] = []
    total = max(len(runs), 1)
    for index, run in enumerate(runs, start=1):
        _check_cancel(should_cancel)
        results = repository.list_results(str(run.get("scan_id") or ""))
        matched = [row for row in results if row.get("matched_trackside_ap")]
        strongest = max(matched, key=lambda row: row.get("rssi_dbm") or -999, default={})
        rows.append(
            {
                "run": run,
                "band24_count": sum(1 for row in results if row.get("band") == "2.4G"),
                "band5_count": sum(1 for row in results if row.get("band") == "5G"),
                "strongest_ap": strongest.get("matched_ap_name") or "-",
                "strongest_rssi": strongest.get("rssi_dbm") or "-",
            }
        )
        if index == len(runs) or index % 20 == 0:
            _emit(progress, "wireless_scan_history_refresh", index, total, f"正在加载扫描历史 {index}/{len(runs)}")
    return {"rows": rows}


def _wireless_scan_result_load(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.wireless_scan_repository import WirelessScanRepository
    from netconsole.services.network_tools.wireless_scan_service import repository_row_to_display_row
    from netconsole.utils.text_encoding import read_text_with_fallback

    _emit(progress, "wireless_scan_result_load", 0, 2, "正在后台读取无线扫描结果")
    _check_cancel(should_cancel)
    repository = WirelessScanRepository(Path(str(params.get("db_path") or "")))
    all_rows = repository.list_results(str(params.get("scan_id") or ""))
    limit = max(1, min(int(params.get("limit") or 500), 2000))
    rows = [repository_row_to_display_row(row) for row in all_rows[:limit]]
    raw_file = Path(str(params.get("raw_file") or ""))
    raw_text = read_text_with_fallback(raw_file) if raw_file.is_file() else ""
    _emit(progress, "wireless_scan_result_load", 2, 2, "无线扫描结果加载完成")
    return {"rows": rows, "total_items": len(all_rows), "raw_text": raw_text, "scan_id": str(params.get("scan_id") or "")}


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


def _device_list_page(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from math import ceil

    from netconsole.core.database import Database
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.repositories.device_repository import DeviceRepository

    _emit(progress, "device_list_page", 0, 2, "正在后台查询设备列表")
    _check_cancel(should_cancel)
    database = Database(Path(str(params.get("db_path") or "")))
    filters = dict(params.get("filters") or {})
    allowed_filters = {key: filters.get(key) for key in ("search", "vendor", "device_type", "group_filter") if filters.get(key) is not None}
    devices = DeviceRepository(database).list(**allowed_filters)
    total = len(devices)
    page_size = max(1, min(int(params.get("page_size") or 200), 1000))
    total_pages = max(ceil(total / page_size), 1)
    current_page = max(1, min(int(params.get("current_page") or 1), total_pages))
    start = (current_page - 1) * page_size
    page_devices = devices[start : start + page_size]
    site_name = str(params.get("site_name") or "")
    groups = DeviceGroupRepository(database, site_name).list() if site_name else []
    _emit(progress, "device_list_page", 2, 2, "设备列表加载完成")
    return {
        "devices": [device.to_record() for device in page_devices],
        "total_items": total,
        "total_pages": total_pages,
        "current_page": current_page,
        "page_size": page_size,
        "groups": [{"id": group.id, "name": group.name} for group in groups],
    }


def _device_object_history_page(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from math import ceil

    from netconsole.core.database import Database
    from netconsole.repositories.device_fact_repository import DeviceFactRepository

    _emit(progress, "device_object_history_page", 0, 1, "正在查询设备历史")
    _check_cancel(should_cancel)
    repository = DeviceFactRepository(Database(Path(str(params.get("db_path") or ""))))
    history_kind = str(params.get("history_kind") or "")
    device_uuid = str(params.get("device_uuid") or "")
    object_name = str(params.get("object_name") or "")
    page_size = max(1, min(int(params.get("page_size") or 200), 1000))
    total = repository.count_object_history(history_kind, device_uuid, object_name)
    total_pages = max(ceil(total / page_size), 1)
    current_page = min(max(int(params.get("page") or 1), 1), total_pages)
    rows = repository.list_object_history_page(
        history_kind,
        device_uuid,
        object_name,
        limit=page_size,
        offset=(current_page - 1) * page_size,
    )
    _emit(progress, "device_object_history_page", 1, 1, "设备历史查询完成")
    return {
        "rows": rows,
        "total_items": total,
        "total_pages": total_pages,
        "current_page": current_page,
        "page_size": page_size,
    }


def _trackside_interface_history_page(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    result = _device_object_history_page(
        {
            **params,
            "history_kind": "optical",
            "object_name": str(params.get("interface_name") or ""),
        },
        progress,
        should_cancel,
    )
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository

    database = Database(Path(str(params.get("db_path") or "")))
    device_uuid = str(params.get("device_uuid") or "")
    device = next((item for item in DeviceRepository(database).list() if str(item.device_uuid or "") == device_uuid), None)
    result["rows"] = [_trackside_interface_history_row(dict(row), device, device_uuid) for row in result.get("rows") or []]
    return result


def _trackside_interface_history_row(row: dict[str, Any], device: Any, device_uuid: str) -> dict[str, Any]:
    return {
        **row,
        "source_device_name": device.name if device is not None else row.get("device_uuid"),
        "source_device_id": device_uuid,
        "host": device.ip_address if device is not None else "",
        "optical_status": row.get("status"),
        "session_id": row.get("collect_run_uuid"),
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


def _car_network_point_table_load(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.rail_transit.car_network_diagnostic import CarNetworkGlobalConfigStore, CarNetworkPointTableStore, merge_global_config

    _emit(progress, "car_network_point_table_load", 0, 1, "正在加载车内通信点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    paths = _path_resolver_from_params(params)
    global_config = merge_global_config(CarNetworkGlobalConfigStore(paths, site_name).load())
    nodes = CarNetworkPointTableStore(paths, site_name).load()
    _emit(progress, "car_network_point_table_load", 1, 1, "车内通信点表加载完成")
    return {"global_config": global_config, "nodes": [asdict(node) for node in nodes], "count": len(nodes)}


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
        merge_global_config,
    )

    _emit(progress, "car_network_generate_point_table", 0, 1, "正在从设备管理生成点表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    paths = _path_resolver_from_params(params)
    existing_nodes = [CarNetworkNode(**dict(row)) for row in params.get("nodes") or [] if isinstance(row, dict)]
    global_config = dict(params.get("global_config") or {})
    if not global_config:
        global_config = CarNetworkGlobalConfigStore(paths, site_name).load()
    global_config = merge_global_config(global_config)
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


def _trackside_ap_plan_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE

    _emit(progress, "trackside_ap_plan_refresh", 0, 1, "正在加载轨旁 AP 规划")
    _check_cancel(should_cancel)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    rows = repository.list_trackside_ap_plan(str(params.get("mode") or TRACKSIDE_AP_PLAN_MODE))
    _emit(progress, "trackside_ap_plan_refresh", 1, 1, "轨旁 AP 规划加载完成")
    return {"rows": rows, "count": len(rows)}


def _trackside_ap_plan_save(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE

    rows = [dict(row) for row in params.get("rows") or [] if isinstance(row, dict)]
    _emit(progress, "trackside_ap_plan_save", 0, max(len(rows), 1), "正在保存轨旁 AP 规划")
    _check_cancel(should_cancel)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    repository.replace_trackside_ap_plan_rows(str(params.get("mode") or TRACKSIDE_AP_PLAN_MODE), rows)
    _emit(progress, "trackside_ap_plan_save", max(len(rows), 1), max(len(rows), 1), "轨旁 AP 规划保存完成")
    return {"count": len(rows)}


def _vehicle_mr_mapping_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore

    _emit(progress, "vehicle_mr_mapping_import", 0, 1, "正在导入车载 MR 映射表")
    _check_cancel(should_cancel)
    site_name = str(params.get("site_name") or "")
    rows = _read_named_table_file(Path(str(params.get("path") or "")))
    store = VehicleMrOnlineStore(_path_resolver_from_params(params), site_name)
    count = store.import_mapping_rows(rows)
    mappings = store.list_mappings()
    _emit(progress, "vehicle_mr_mapping_import", 1, 1, "车载 MR 映射表导入完成")
    return {"count": count, "mappings": [asdict(mapping) for mapping in mappings]}


def _vehicle_mr_mapping_load(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore

    _emit(progress, "vehicle_mr_mapping_load", 0, 1, "正在读取车载 MR 映射表")
    _check_cancel(should_cancel)
    store = VehicleMrOnlineStore(_path_resolver_from_params(params), str(params.get("site_name") or ""))
    mappings = store.list_mappings()
    _emit(progress, "vehicle_mr_mapping_load", 1, 1, "车载 MR 映射表读取完成")
    return {"mappings": [asdict(mapping) for mapping in mappings], "count": len(mappings)}


def _vehicle_mr_mapping_save(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore, VehicleMrTrainMapping

    rows = [VehicleMrTrainMapping(**dict(row)) for row in params.get("mappings") or [] if isinstance(row, dict)]
    _emit(progress, "vehicle_mr_mapping_save", 0, max(len(rows), 1), "正在保存车载 MR 映射表")
    _check_cancel(should_cancel)
    store = VehicleMrOnlineStore(_path_resolver_from_params(params), str(params.get("site_name") or ""))
    store.save_mappings(rows)
    mappings = store.list_mappings()
    _emit(progress, "vehicle_mr_mapping_save", max(len(rows), 1), max(len(rows), 1), "车载 MR 映射表保存完成")
    return {"mappings": [asdict(mapping) for mapping in mappings], "count": len(mappings)}


def _vehicle_mr_online_refresh_all(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.models.device import Device
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.vehicle_mr_online import (
        build_mapping_lookup,
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
    mappings = store.list_mappings()
    mapping_trains = build_mapping_trains(mappings)
    mapping_lookup = build_mapping_lookup(mappings)
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
        "mapping_lookup": {key: asdict(value) for key, value in mapping_lookup.items()},
    }


def _vehicle_mr_ap_mapping_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore, load_trackside_ap_lookup

    _emit(progress, "vehicle_mr_ap_mapping_refresh", 0, 2, "正在读取轨旁 AP 映射")
    _check_cancel(should_cancel)
    repository = DeviceRepository(Database(Path(str(params.get("db_path") or ""))))
    site_name = str(params.get("site_name") or "")
    store = VehicleMrOnlineStore(_path_resolver_from_params(params), site_name)
    ap_lookup = load_trackside_ap_lookup(repository)
    _emit(progress, "vehicle_mr_ap_mapping_refresh", 1, 2, "正在回填历史车站")
    _check_cancel(should_cancel)
    backfilled = store.backfill_event_stations(ap_lookup)
    train_id = str(params.get("train_id") or "")
    events = store.list_events(train_id, int(params.get("limit") or 200)) if train_id else []
    _emit(progress, "vehicle_mr_ap_mapping_refresh", 2, 2, "AP 映射刷新完成")
    return {
        "ap_lookup": _jsonable_vehicle_ap_lookup(ap_lookup),
        "backfilled": backfilled,
        "train_id": train_id,
        "events": events,
    }


def _vehicle_mr_event_page(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore

    _emit(progress, "vehicle_mr_event_page", 0, 1, "正在读取车载 MR 历史经过")
    _check_cancel(should_cancel)
    train_id = str(params.get("train_id") or "")
    limit = int(params.get("limit") or 200)
    store = VehicleMrOnlineStore(_path_resolver_from_params(params), str(params.get("site_name") or ""))
    rows = store.list_events(train_id, limit)
    _emit(progress, "vehicle_mr_event_page", 1, 1, "车载 MR 历史经过读取完成")
    return {"train_id": train_id, "rows": rows, "limit": limit}


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


def _ac_fit_ap_resources_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    _emit(progress, "ac_fit_ap_resources_refresh", 0, 1, "正在读取 FIT-AP 资源")
    _check_cancel(should_cancel)
    ac_uuid = str(params.get("ac_uuid") or "").strip()
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    result = {
        "ac_uuid": ac_uuid,
        "summary": repository.get_ac_ap_summary(ac_uuid),
        "resources": repository.list_fit_ap_resources_with_metadata(ac_uuid),
    }
    _emit(progress, "ac_fit_ap_resources_refresh", 1, 1, "FIT-AP 资源刷新完成")
    return result


def _ac_fit_ap_optical_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.core.sources.switch_source import build_switch_data_lookup, compute_switch_status
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.repositories.device_fact_repository import DeviceFactRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.offline_ap_ledger import OFFLINE_AP_STATUS_TEXT, is_fit_ap_offline
    from netconsole.utils.interface_sort import interface_sort_key

    _emit(progress, "ac_fit_ap_optical_refresh", 0, 3, "正在读取 FIT-AP 资源和光衰")
    _check_cancel(should_cancel)
    ac_uuid = str(params.get("ac_uuid") or "").strip()
    database = Database(Path(str(params.get("db_path") or "")))
    ac_repository = AcRepository(database)
    resources = ac_repository.list_fit_ap_resources_with_metadata(ac_uuid)
    optical_rows = ac_repository.list_fit_ap_optical(ac_uuid)
    _emit(progress, "ac_fit_ap_optical_refresh", 1, 3, "正在读取交换机光模块状态")
    _check_cancel(should_cancel)
    devices = DeviceRepository(database).list()
    fact_repository = DeviceFactRepository(database)
    optical_by_device = {
        str(device.device_uuid or ""): fact_repository.list_optical_modules(str(device.device_uuid or ""))
        for device in devices
    }
    lookup = build_switch_data_lookup(devices, optical_by_device)
    resources_by_uuid = {str(row.get("ap_uuid") or ""): row for row in resources if row.get("ap_uuid")}
    resources_by_name = {str(row.get("ap_name") or ""): row for row in resources if row.get("ap_name")}
    enriched: list[dict[str, object | None]] = []
    for row in optical_rows:
        _check_cancel(should_cancel)
        resource = resources_by_uuid.get(str(row.get("ap_uuid") or "")) or resources_by_name.get(str(row.get("ap_name") or ""), {})
        neighbor_name = row.get("neighbor_device_name")
        lowered = str(neighbor_name or "").casefold()
        if any(token.casefold() in lowered for token in ("Nearest", "Chassis ID", "Default", "customer bridge", "nontpmr")):
            neighbor_name = None
        switch_status = compute_switch_status(device_name=neighbor_name, interface_name=row.get("neighbor_interface"), lookup=lookup)
        is_offline = is_fit_ap_offline(resource) or bool(row.get("is_ap_offline"))
        enriched.append(
            {
                **row,
                "ap_mac": row.get("ap_mac") or resource.get("ap_mac"),
                "site": row.get("site") or resource.get("site_name") or resource.get("site") or "未归属",
                "neighbor_device_name": neighbor_name,
                "switch_optical_status": switch_status,
                "is_ap_offline": is_offline,
                "optical_alarm_status": OFFLINE_AP_STATUS_TEXT if is_offline else row.get("optical_alarm_status"),
                "ap_optical_status": "offline" if is_offline else row.get("ap_optical_status"),
                "data_source": "historical" if is_offline else row.get("data_source"),
            }
        )
    enriched.sort(
        key=lambda row: (
            1 if str(row.get("neighbor_device_name") or "").strip() in {"", "-"} else 0,
            str(row.get("neighbor_device_name") or "").casefold(),
            interface_sort_key(row.get("neighbor_interface")),
            str(row.get("ap_name") or ""),
        )
    )
    _emit(progress, "ac_fit_ap_optical_refresh", 3, 3, "FIT-AP 光衰刷新完成")
    return {
        "ac_uuid": ac_uuid,
        "summary": ac_repository.get_ac_ap_summary(ac_uuid),
        "resources": resources,
        "optical_rows": enriched,
    }


def _ac_ap_extensions_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    _emit(progress, "ac_ap_extensions_refresh", 0, 1, "正在读取 AP 扩展信息")
    _check_cancel(should_cancel)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    rows = repository.list_ap_extension_points(search=str(params.get("search") or ""))
    _emit(progress, "ac_ap_extensions_refresh", 1, 1, "AP 扩展信息刷新完成")
    return {"rows": rows}


def _omnipeek_name_table_preview(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.models.omnipeek_name_table import SOURCE_DEVICE_MANAGEMENT
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.omnipeek_name_table_service import OmniPeekNameTableService

    _emit(progress, "omnipeek_name_table_preview", 0, 3, "正在后台收集 OmniPeek 名称数据")
    _check_cancel(should_cancel)
    database = Database(Path(str(params.get("db_path") or "")))
    site_name = str(params.get("site_name") or "")
    device_repository = DeviceRepository(database)
    ac_repository = AcRepository(database)
    filters = dict(params.get("device_filters") or {})
    allowed_filters = {key: filters.get(key) for key in ("search", "vendor", "device_type", "group_filter") if filters.get(key) is not None}
    devices = device_repository.list(**allowed_filters)
    selected_device_uuids = {str(value) for value in params.get("selected_device_uuids") or [] if str(value)}
    if selected_device_uuids:
        devices = [device for device in devices if str(device.device_uuid or "") in selected_device_uuids]
    groups = DeviceGroupRepository(database, site_name).list() if site_name else []
    group_names = {int(group.id): group.name for group in groups if group.id is not None}
    service = OmniPeekNameTableService(ac_repository, device_repository)
    items = service.collect_items(
        include_ac_fit_ap=bool(params.get("include_ac_fit_ap", True)),
        include_ap_extensions=bool(params.get("include_ap_extensions", True)),
        include_device_mr=bool(params.get("include_device_mr", True)),
        ac_device_uuid=str(params.get("ac_uuid") or "") or None,
        devices=devices,
        group_names=group_names,
    )
    _emit(progress, "omnipeek_name_table_preview", 2, 3, "正在整理预览和异常统计")
    _check_cancel(should_cancel)
    abnormal = [item for item in items if item.status != "正常"]
    normal = [item for item in items if item.status == "正常"]
    preview_limit = max(1, min(int(params.get("preview_limit") or 500), 2000))
    preview_items = (abnormal + normal)[:preview_limit]
    source_counts = service.source_counts(ac_device_uuid=str(params.get("ac_uuid") or "") or None, devices=devices)
    source_counts[SOURCE_DEVICE_MANAGEMENT] = sum(1 for item in items if SOURCE_DEVICE_MANAGEMENT in (item.sources or [item.source]))
    stats = {
        "total": len(items),
        "selected": sum(1 for item in items if item.selected),
        "abnormal": len(abnormal),
        "mac_conflict": sum(1 for item in items if item.status == "MAC冲突"),
        "r2_failed": sum(1 for item in items if item.status == "R2推导失败"),
        "missing_mac": sum(1 for item in items if item.status == "缺少物理MAC"),
        "preview_count": len(preview_items),
    }
    _emit(progress, "omnipeek_name_table_preview", 3, 3, "OmniPeek 名称表预览已就绪")
    return {"items": [asdict(item) for item in preview_items], "source_counts": source_counts, "stats": stats}


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


def _ac_station_online_history_page(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from math import ceil

    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    _emit(progress, "ac_station_online_history_page", 0, 1, "正在查询 AP 在线历史")
    _check_cancel(should_cancel)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    site_name = str(params.get("site_name") or "").strip() or None
    page_size = max(1, min(int(params.get("page_size") or 200), 1000))
    total = repository.count_station_online_summary_history(site_name)
    total_pages = max(ceil(total / page_size), 1)
    current_page = min(max(int(params.get("page") or 1), 1), total_pages)
    rows = repository.list_station_online_summary_history(site_name, page_size, (current_page - 1) * page_size)
    _emit(progress, "ac_station_online_history_page", 1, 1, "AP 在线历史查询完成")
    return {
        "rows": rows,
        "total_items": total,
        "total_pages": total_pages,
        "current_page": current_page,
        "page_size": page_size,
    }


def _ac_ap_history_page(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from math import ceil

    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    _emit(progress, "ac_ap_history_page", 0, 1, "正在查询 FIT-AP 历史")
    _check_cancel(should_cancel)
    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    history_kind = str(params.get("history_kind") or "")
    ap_uuid = str(params.get("ap_uuid") or "")
    page_size = max(1, min(int(params.get("page_size") or 200), 1000))
    total = repository.count_fit_ap_history(history_kind, ap_uuid)
    total_pages = max(ceil(total / page_size), 1)
    current_page = min(max(int(params.get("page") or 1), 1), total_pages)
    rows = repository.list_fit_ap_history_page(
        history_kind,
        ap_uuid,
        limit=page_size,
        offset=(current_page - 1) * page_size,
    )
    _emit(progress, "ac_ap_history_page", 1, 1, "FIT-AP 历史查询完成")
    return {
        "rows": rows,
        "total_items": total,
        "total_pages": total_pages,
        "current_page": current_page,
        "page_size": page_size,
    }


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
    diff_file = _write_background_text_artifact(params, "config_diff", "two_devices_diff", diff.raw_diff)
    _emit(progress, "config_compare", 1, 1, "配置比较完成")
    return {
        "kind": "two_devices",
        "left_label": name_a,
        "right_label": name_b,
        "left_text": text_a,
        "right_text": text_b,
        "raw_diff": diff.raw_diff,
        "diff_file": str(diff_file),
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
    result["diff_file"] = str(_write_background_text_artifact(params, "config_diff", "latest_snapshots_diff", str(result.get("raw_diff") or "")))
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
    result["diff_file"] = str(_write_background_text_artifact(params, "config_diff", "snapshot_pair_diff", str(result.get("raw_diff") or "")))
    _emit(progress, "config_compare", 1, 1, "配置比较完成")
    return result


def _config_snapshot_service(params: dict[str, Any]) -> tuple[Any, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
    from netconsole.services.config_lifecycle_service import ConfigLifecycleService

    database = Database(Path(str(params.get("db_path") or "")))
    repository = ConfigSnapshotRepository(database)
    service = ConfigLifecycleService(str(params.get("site_name") or ""), database, _path_resolver_from_params(params), repository)
    return repository, service


def _limited_snapshot_text(text: str, max_chars: int) -> tuple[str, bool, int]:
    original_length = len(text)
    if max_chars > 0 and original_length > max_chars:
        notice = f"\n\n[内容过长，仅显示前 {max_chars} 个字符；完整内容请下载快照查看。]"
        return text[:max_chars] + notice, True, original_length
    return text, False, original_length


def _config_snapshot_load_content(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    _emit(progress, "config_snapshot_load_content", 0, 1, "正在后台读取配置快照")
    _check_cancel(should_cancel)
    repository, service = _config_snapshot_service(params)
    snapshot = repository.get(int(params.get("snapshot_id") or 0))
    text, truncated, original_length = _limited_snapshot_text(service.snapshot_text(snapshot), int(params.get("max_chars") or 2_000_000))
    _emit(progress, "config_snapshot_load_content", 1, 1, "配置快照读取完成")
    result = {
        "snapshot_id": snapshot.id,
        "snapshot_type": snapshot.type,
        "text": text,
        "truncated": truncated,
        "original_length": original_length,
    }
    if snapshot.type == "diff":
        result["diff_file"] = str(_write_background_text_artifact(params, "config_diff", "snapshot_diff", text))
    return result


def _config_snapshot_copy(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository, service = _config_snapshot_service(params)
    entries = [entry for entry in params.get("entries") or [] if isinstance(entry, dict)]
    total = max(len(entries), 1)
    copied: list[str] = []
    for index, entry in enumerate(entries, start=1):
        _check_cancel(should_cancel)
        snapshot = repository.get(int(entry.get("snapshot_id") or 0))
        target = Path(str(entry.get("target_path") or ""))
        _emit(progress, "config_snapshot_copy", index - 1, total, f"正在复制配置快照 {index}/{len(entries)}")
        service.copy_snapshot(snapshot, target)
        copied.append(str(target))
    _emit(progress, "config_snapshot_copy", total, total, "配置快照复制完成")
    return {"copied_paths": copied}


def _config_snapshot_pair_load_content(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    _emit(progress, "config_snapshot_pair_load_content", 0, 2, "正在后台读取配置快照")
    _check_cancel(should_cancel)
    repository, service = _config_snapshot_service(params)
    snapshot_ids = [int(value) for value in params.get("snapshot_ids") or [] if int(value or 0) > 0]
    snapshots = [repository.get(snapshot_id) for snapshot_id in snapshot_ids]
    max_chars = int(params.get("max_chars") or 2_000_000)
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        text, truncated, original_length = _limited_snapshot_text(service.snapshot_text(snapshot), max_chars)
        rows.append(
            {
                "snapshot_id": snapshot.id,
                "snapshot_type": snapshot.type,
                "text": text,
                "truncated": truncated,
                "original_length": original_length,
            }
        )
    raw_diff = str(params.get("raw_diff") or "")
    result: dict[str, Any] = {"snapshots": rows, "raw_diff": raw_diff}
    if raw_diff:
        result["diff_file"] = str(_write_background_text_artifact(params, "config_diff", "snapshot_pair_content_diff", raw_diff))
    _emit(progress, "config_snapshot_pair_load_content", 2, 2, "配置快照读取完成")
    return result


def _config_snapshot_delete_many(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository, service = _config_snapshot_service(params)
    snapshot_ids = [int(value) for value in params.get("snapshot_ids") or [] if int(value or 0) > 0]
    total = len(snapshot_ids)
    deleted = 0
    failed_items: list[dict[str, object]] = []
    for index, snapshot_id in enumerate(snapshot_ids, start=1):
        _check_cancel(should_cancel)
        _emit(progress, "config_snapshot_delete_many", index - 1, max(total, 1), f"正在删除配置快照 {index}/{total}")
        try:
            service.delete_snapshot(repository.get(snapshot_id))
            deleted += 1
        except Exception as exc:
            failed_items.append({"snapshot_id": snapshot_id, "error": str(exc)})
    _emit(progress, "config_snapshot_delete_many", max(total, 1), max(total, 1), "配置快照删除完成")
    return {
        "total": total,
        "deleted": deleted,
        "failed": len(failed_items),
        "failed_items": failed_items,
    }


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

    result = MeshImportService(site_name, _path_resolver_from_params(params)).import_files(
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


def _wifi_survey_repository(db_path: object):
    from netconsole.core.database import Database
    from netconsole.repositories.wifi_survey_repository import WifiSurveyRepository

    return WifiSurveyRepository(Database(Path(str(db_path or ""))))


def _wifi_survey_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository = _wifi_survey_repository(params.get("db_path"))
    _emit(progress, "wifi_survey_read", 1, 3, "正在读取 WiFi 勘测数据")
    floors = repository.list_floor_plans()
    requested_floor_id = int(params.get("floor_plan_id") or 0)
    floor = next((row for row in floors if int(row.get("id") or 0) == requested_floor_id), floors[0] if floors else None)
    sessions = repository.list_sessions(int(floor["id"])) if floor else []
    requested_session_id = int(params.get("session_id") or 0)
    session = next((row for row in sessions if int(row.get("id") or 0) == requested_session_id), sessions[0] if sessions else None)
    _check_cancel(should_cancel)
    points = repository.list_points(int(session["id"])) if session else []
    observations = repository.list_observations_by_session(int(session["id"])) if session else []
    network_rows = repository.list_network_tree(int(session["id"])) if session else []
    _emit(progress, "wifi_survey_done", 3, 3, "WiFi 勘测数据加载完成")
    return {
        "floors": floors,
        "floor": floor,
        "sessions": sessions,
        "session": session,
        "points": points,
        "observations": observations,
        "network_rows": network_rows,
    }


def _wifi_survey_floor_import(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from PySide6.QtGui import QImageReader

    source = Path(str(params.get("source_path") or ""))
    target_dir = Path(str(params.get("target_dir") or ""))
    if not source.is_file():
        raise FileNotFoundError(source)
    reader = QImageReader(str(source))
    size = reader.size()
    if not size.isValid():
        raise ValueError("无法读取图纸文件")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    counter = 1
    while target.exists():
        target = target_dir / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    _check_cancel(should_cancel)
    shutil.copy2(source, target)
    repository = _wifi_survey_repository(params.get("db_path"))
    plan = repository.create_floor_plan(source.stem, str(target), size.width(), size.height())
    return {"floor": plan}


def _wifi_survey_create_session(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository = _wifi_survey_repository(params.get("db_path"))
    session = repository.create_session(int(params.get("floor_plan_id") or 0), str(params.get("name") or "").strip())
    return {"session": session}


def _wifi_survey_update_scale(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository = _wifi_survey_repository(params.get("db_path"))
    floor_plan_id = int(params.get("floor_plan_id") or 0)
    repository.update_floor_plan_scale(floor_plan_id, float(params.get("meter_per_px") or 0.0))
    return {"floor": repository.get_floor_plan(floor_plan_id)}


def _wifi_survey_save_sample(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.wifi_survey.scanner import WifiObservation

    repository = _wifi_survey_repository(params.get("db_path"))
    session_id = int(params.get("session_id") or 0)
    points = repository.list_points(session_id)
    point = repository.create_point(
        session_id,
        len(points) + 1,
        float(params.get("x_px") or 0.0),
        float(params.get("y_px") or 0.0),
        float(params["meter_per_px"]) if params.get("meter_per_px") not in (None, "") else None,
    )
    observations = [WifiObservation(**dict(row)) for row in params.get("observations") or [] if isinstance(row, dict)]
    repository.save_observations(int(point["id"]), observations)
    return {"point": point, "observation_count": len(observations)}


def _wifi_survey_heatmap_render(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.wifi_survey.heatmap import build_heatmap_samples, generate_idw_heatmap_image

    repository = _wifi_survey_repository(params.get("db_path"))
    session_id = int(params.get("session_id") or 0)
    points = repository.list_points(session_id)
    observations = repository.list_observations_by_session(session_id)
    mode = str(params.get("mode") or "strongest")
    samples = build_heatmap_samples(
        points,
        observations,
        mode,
        {str(value) for value in params.get("selected_ssids") or []},
        {str(value) for value in params.get("selected_bssids") or []},
    )
    if len(samples) < 3:
        return {"path": "", "valid_count": len(samples), "point_count": len(points), "mode": mode}
    _emit(progress, "wifi_survey_heatmap", 1, 2, "正在计算 WiFi 热力图")
    image = generate_idw_heatmap_image(
        int(params.get("width") or 0),
        int(params.get("height") or 0),
        [(sample.x_px, sample.y_px, sample.rssi_dbm) for sample in samples],
    )
    _check_cancel(should_cancel)
    output_path = Path(str(params.get("output_path") or ""))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if image is None or not image.save(str(output_path), "PNG"):
        raise RuntimeError("WiFi 热力图生成失败")
    return {"path": str(output_path), "valid_count": len(samples), "point_count": len(points), "mode": mode}


def _ac_devices_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository

    devices = DeviceRepository(Database(Path(str(params.get("db_path") or "")))).list(vendor="H3C", device_type="AC")
    return {"devices": [device.to_record() for device in devices]}


def _ac_repository(params: dict[str, Any]):
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    return AcRepository(Database(Path(str(params.get("db_path") or ""))))


def _ac_fit_ap_delete_many(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    count = _ac_repository(params).delete_fit_aps(str(params.get("ac_uuid") or ""), [str(value) for value in params.get("names") or []])
    return {"count": count}


def _ac_ap_extension_save(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    return {"row": _ac_repository(params).upsert_ap_extension_point(dict(params.get("row") or {}))}


def _ac_ap_extension_delete(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    count = _ac_repository(params).delete_ap_extension_points([int(value) for value in params.get("ids") or []])
    return {"count": count}


def _ac_ap_extension_clear(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    return {"count": _ac_repository(params).clear_ap_extension_points()}


def _ac_station_overview_value_save(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository = _ac_repository(params)
    station = str(params.get("station") or "")
    kind = str(params.get("kind") or "")
    if kind == "remark":
        repository.upsert_station_ap_remark(station, str(params.get("value") or ""))
    elif kind == "capacity":
        repository.upsert_station_ap_capacity(station, int(params.get("value") or 0))
    else:
        raise ValueError("不支持的在线概览保存类型")
    return {"station": station, "kind": kind}


def _device_detail_load_all(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.core.sources.switch_source import build_switch_data_lookup
    from netconsole.models.device import Device
    from netconsole.repositories.ac_repository import AcRepository
    from netconsole.repositories.device_fact_repository import DeviceFactRepository
    from netconsole.services.trackside_ap_business import build_trackside_ap_business_rows

    database = Database(Path(str(params.get("db_path") or "")))
    repository = DeviceFactRepository(database)
    device = Device.from_mapping(dict(params.get("device") or {}))
    device_uuid = str(device.device_uuid or "")
    fact = repository.get_device_fact(device_uuid)
    interfaces = repository.list_device_interfaces(device_uuid)
    optical_modules = repository.list_optical_modules(device_uuid)
    lldp = repository.list_lldp_neighbors(device_uuid)
    _check_cancel(should_cancel)
    ac_repository = AcRepository(database)
    lookup = build_switch_data_lookup([device], {device_uuid: optical_modules})
    trackside = build_trackside_ap_business_rows(
        [device],
        {device_uuid: interfaces},
        {device_uuid: optical_modules},
        ac_repository.list_all_fit_ap_optical(),
        {device_uuid: lldp},
        ac_repository.list_all_fit_ap_resources_with_metadata(),
        lookup,
    )
    return {"fact": fact, "interfaces": interfaces, "optical_modules": optical_modules, "lldp": lldp, "trackside": trackside}


def _fit_ap_detail_load(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.services.ap_optical_history_service import ApOpticalHistoryService

    repository = _ac_repository(params)
    ac_uuid = str(params.get("ac_uuid") or "")
    ap_key = str(params.get("ap_key") or "")
    resource = repository.get_fit_ap_resource_by_uuid(ac_uuid, ap_key) or repository.get_fit_ap_resource(ac_uuid, ap_key) or {}
    ap_uuid = str(resource.get("ap_uuid") or ap_key)
    optical = repository.get_fit_ap_optical_by_uuid(ac_uuid, ap_uuid) or {}
    metadata = repository.get_fit_ap_metadata_by_uuid(ap_uuid) or {}
    summary = ApOpticalHistoryService(repository).get_latest_optical_summary(ac_uuid, ap_uuid) or {}
    return {"resource": resource, "optical": optical, "metadata": metadata, "optical_summary": summary, "ap_uuid": ap_uuid}


def _fit_ap_metadata_save(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    return {"metadata": _ac_repository(params).upsert_fit_ap_metadata(dict(params.get("metadata") or {}))}


def _online_mr_collection_devices_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.repositories.device_repository import DeviceRepository

    database = Database(Path(str(params.get("db_path") or "")))
    devices = DeviceRepository(database).list()
    groups = DeviceGroupRepository(database, str(params.get("site_name") or "")).list()
    return {
        "devices": [device.to_record() for device in devices],
        "groups": [{"id": group.id, "name": group.name} for group in groups],
    }


def _mesh_mr_profiles_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.models.mesh_log_models import dataclass_to_json_dict
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
    from netconsole.services.mesh_storage_service import MeshStorageService
    from netconsole.services.rail_transit.constants import VEHICLE_MR_GROUP_NAME
    from netconsole.core.paths import PathResolver

    paths = PathResolver(
        app_root=Path(str(params.get("app_root") or Path.cwd())),
        data_root=Path(str(params.get("data_root") or params.get("app_root") or Path.cwd())),
    )
    site_name = str(params.get("site_name") or "")
    db_path = str(params.get("db_path") or "")
    if db_path:
        database = Database(Path(db_path))
        group = DeviceGroupRepository(database, site_name).find_by_name(VEHICLE_MR_GROUP_NAME)
        devices = DeviceRepository(database).list(group_filter=int(group.id)) if group and group.id is not None else []
        profiles = MeshStorageService(site_name, paths).sync_mr_profiles_from_devices(devices)
    else:
        profiles = MeshCatalogRepository(paths.mesh_catalog_path(site_name)).list_profiles()
    return {"profiles": [dataclass_to_json_dict(profile) for profile in profiles]}


def _file_management_navigation_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.device_group_service import group_filter_to_repository_value

    database = Database(Path(str(params.get("db_path") or "")))
    site_name = str(params.get("site_name") or "")
    groups = DeviceGroupRepository(database, site_name).list()
    repository = DeviceRepository(database)
    try:
        devices = repository.list(
            search=str(params.get("search") or "").strip() or None,
            group_filter=group_filter_to_repository_value(params.get("group_filter")),
        )
    except TypeError:
        devices = repository.list()
    return {
        "groups": [{"id": group.id, "name": group.name} for group in groups],
        "devices": [device.to_record() for device in devices],
    }


def _device_mutation(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.models.device import Device
    from netconsole.repositories.device_repository import DeviceRepository

    repository = DeviceRepository(Database(Path(str(params.get("db_path") or ""))))
    action = str(params.get("action") or "")
    if action == "create":
        device = repository.create(Device.from_mapping(dict(params.get("device") or {})))
        return {"action": action, "device": device.to_record()}
    if action == "update":
        device = repository.update(Device.from_mapping(dict(params.get("device") or {})))
        return {"action": action, "device": device.to_record()}
    if action == "delete":
        deleted: list[dict[str, object | None]] = []
        failed_items: list[dict[str, object]] = []
        for value in params.get("device_ids") or []:
            try:
                device = repository.get(int(value))
                repository.delete(int(value))
                deleted.append(device.to_record())
            except Exception as exc:
                failed_items.append({"device_id": int(value), "error": str(exc)})
        return {
            "action": action,
            "devices": deleted,
            "total": len(deleted) + len(failed_items),
            "deleted": len(deleted),
            "failed": len(failed_items),
            "failed_items": failed_items,
            "count": len(deleted),
        }
    raise ValueError("不支持的设备写入操作")


def _device_lookup(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.device_repository import DeviceRepository

    device_uuid = str(params.get("device_uuid") or "")
    device = next(
        (item for item in DeviceRepository(Database(Path(str(params.get("db_path") or "")))).list() if str(item.device_uuid or "") == device_uuid),
        None,
    )
    return {"device": device.to_record() if device is not None else None}


def _device_group_repository(params: dict[str, Any]):
    from netconsole.core.database import Database
    from netconsole.repositories.device_group_repository import DeviceGroupRepository

    return DeviceGroupRepository(Database(Path(str(params.get("db_path") or ""))), str(params.get("site_name") or ""))


def _device_group_refresh(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    repository = _device_group_repository(params)
    groups = repository.list()
    counts = repository.counts()
    return {"groups": [asdict(group) for group in groups], "counts": {str(key): int(value) for key, value in counts.items()}}


def _device_group_create(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.device_group_repository import DuplicateGroupName

    try:
        group = _device_group_repository(params).create(str(params.get("name") or ""))
    except DuplicateGroupName as exc:
        raise ValueError("DuplicateGroupName") from exc
    return {"group": asdict(group)}


def _device_group_rename(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.repositories.device_group_repository import DuplicateGroupName

    try:
        group = _device_group_repository(params).rename(int(params.get("group_id") or 0), str(params.get("name") or ""))
    except DuplicateGroupName as exc:
        raise ValueError("DuplicateGroupName") from exc
    return {"group": asdict(group)}


def _device_group_count_devices(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    group_id = int(params.get("group_id") or 0)
    return {"group_id": group_id, "count": _device_group_repository(params).count_devices(group_id)}


def _device_group_delete(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    group_id = int(params.get("group_id") or 0)
    _device_group_repository(params).delete(group_id)
    return {"group_id": group_id}


def _trackside_device_detail_resolve(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.models.device import Device

    database = Database(Path(str(params.get("db_path") or "")))
    device_id = int(params.get("device_id") or 0)
    device_uuid = str(params.get("device_uuid") or "").strip()
    device_ip = str(params.get("device_ip") or "").strip()
    device_name = str(params.get("device_name") or "").strip()
    with database.connect() as conn:
        row = None
        if device_id > 0:
            row = conn.execute("SELECT * FROM devices WHERE id = ? LIMIT 1", (device_id,)).fetchone()
        if row is None and device_uuid:
            row = conn.execute("SELECT * FROM devices WHERE device_uuid = ? LIMIT 1", (device_uuid,)).fetchone()
        if row is None and device_ip:
            row = conn.execute("SELECT * FROM devices WHERE primary_address = ? OR backup_address = ? LIMIT 1", (device_ip, device_ip)).fetchone()
        if row is None and device_name:
            row = conn.execute("SELECT * FROM devices WHERE name = ? OR system_name = ? LIMIT 1", (device_name, device_name)).fetchone()
    device = Device.from_mapping(dict(row)) if row is not None else None
    return {"device": device.to_record() if device is not None else None}


def _trackside_fit_ap_detail_resolve(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from netconsole.core.database import Database
    from netconsole.repositories.ac_repository import AcRepository

    def normalize_mac(value: object) -> str:
        hex_text = "".join(char for char in str(value or "") if char in "0123456789abcdefABCDEF")
        return hex_text.casefold() if len(hex_text) == 12 else ""

    repository = AcRepository(Database(Path(str(params.get("db_path") or ""))))
    ac_uuid = str(params.get("ac_device_uuid") or "").strip()
    ap_uuid = str(params.get("ap_uuid") or "").strip()
    ap_mac = normalize_mac(params.get("ap_mac"))
    ap_name = str(params.get("ap_name") or "").strip()
    if ac_uuid and ap_uuid:
        return {"matches": [{"ac_device_uuid": ac_uuid, "ap_uuid": ap_uuid, "ap_name": ap_name}]}
    resources = repository.list_all_fit_ap_resources_with_metadata()
    matches: list[dict[str, object | None]] = []
    if ap_mac:
        matches = [item for item in resources if normalize_mac(item.get("ap_mac")) == ap_mac]
    if not matches and ap_name:
        matches = [item for item in resources if str(item.get("ap_name") or "").strip().casefold() == ap_name.casefold()]
    return {"matches": matches}


def _network_profile_store(params: dict[str, Any], progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
    from dataclasses import asdict
    from netconsole.services.network_profile_store import AdapterMatch, AdapterProfile, NetworkProfileStore, SecondaryIp
    from netconsole.services.route_profile_store import RouteProfile, RouteProfileEntry, RouteProfileStore

    adapter_store = NetworkProfileStore(Path(str(params.get("adapter_path") or "")))
    route_store = RouteProfileStore(Path(str(params.get("route_path") or "")))
    action = str(params.get("action") or "load")
    if action == "save_adapter":
        row = dict(params.get("profile") or {})
        match = dict(row.get("adapter_match") or {})
        row["adapter_match"] = AdapterMatch(**match)
        row["secondary_ips"] = [SecondaryIp(**dict(item)) for item in row.get("secondary_ips") or [] if isinstance(item, dict)]
        adapter_store.upsert(AdapterProfile(**row))
    elif action == "save_route":
        row = dict(params.get("profile") or {})
        row["routes"] = [RouteProfileEntry(**dict(item)) for item in row.get("routes") or [] if isinstance(item, dict)]
        route_store.upsert(RouteProfile(**row))
    elif action != "load":
        raise ValueError("不支持的网络 Profile 操作")
    return {
        "action": action,
        "adapter_profiles": [asdict(profile) for profile in adapter_store.load()],
        "route_profiles": [asdict(profile) for profile in route_store.load()],
    }


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
