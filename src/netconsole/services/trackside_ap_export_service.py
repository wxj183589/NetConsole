from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Callable

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.sources.switch_source import build_switch_data_lookup
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS, ApOnlineOverviewService
from netconsole.services.offline_ap_ledger import (
    OFFLINE_AP_LEDGER_COLUMNS,
    OFFLINE_AP_STATS_COLUMNS,
    build_device_lookup_by_name,
    build_latest_ap_history_indexes,
    build_offline_ap_ledger,
    offline_ap_headers,
)
from netconsole.services.trackside_ap_business import (
    AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
    NEW_ONLINE_AP_OVERVIEW_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    TracksideApExportCancelled,
    build_ap_optical_treatment_records,
    build_new_online_ap_overview_rows,
    build_trackside_ap_business_rows,
    enrich_trackside_export_rows,
    export_trackside_ap_business_xlsx,
    filter_station_switch_devices,
    is_trackside_ap_interface,
)
from netconsole.services.rail_transit.trackside_ap_identity_shadow import (
    TracksideApIdentityShadowService,
    unavailable_trackside_identity_shadow,
)

ProgressCallback = Callable[[str, int, int, str], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class TracksideApBusinessLoadResult:
    generation: int
    site_name: str
    rows: list[dict[str, object | None]]
    device_count: int
    query_ms: int
    build_ms: int
    interface_count: int = 0
    optical_count: int = 0
    lldp_count: int = 0
    fit_ap_optical_count: int = 0
    fit_ap_resource_count: int = 0
    candidate_ap_interface_count: int = 0
    row_count: int = 0
    empty_reason: str = ""
    identity_shadow: dict[str, object] = field(default_factory=dict)


def load_trackside_ap_business_snapshot(repository: DeviceRepository, site_name: str, generation: int) -> TracksideApBusinessLoadResult:
    query_start = perf_counter()
    fact_repository = DeviceFactRepository(repository.database)
    ac_repository = AcRepository(repository.database)
    devices = filter_station_switch_devices(repository.list(), repository.database, site_name)
    interfaces_by_device = {str(device.device_uuid or ""): fact_repository.list_device_interfaces(str(device.device_uuid or "")) for device in devices}
    optical_by_device = {str(device.device_uuid or ""): fact_repository.list_optical_modules(str(device.device_uuid or "")) for device in devices}
    lldp_by_device = {str(device.device_uuid or ""): fact_repository.list_lldp_neighbors(str(device.device_uuid or "")) for device in devices}
    fit_ap_optical_rows = ac_repository.list_all_fit_ap_optical()
    fit_ap_resource_rows = ac_repository.list_all_fit_ap_resources_with_metadata()
    historical_lldp_rows = ac_repository.list_latest_ap_lldp_histories()
    active_plan = ac_repository.get_active_trackside_pvid_plan()
    switch_lookup = build_switch_data_lookup(devices, optical_by_device)
    latest_lldp, latest_optical = build_latest_ap_history_indexes(ac_repository, fit_ap_resource_rows)
    _offline_stats, offline_ledger_rows = build_offline_ap_ledger(
        fit_ap_resources=fit_ap_resource_rows,
        latest_lldp_by_ap=latest_lldp,
        latest_optical_by_ap=latest_optical,
        device_lookup_by_name=build_device_lookup_by_name(devices),
    )
    interface_count = sum(len(rows) for rows in interfaces_by_device.values())
    optical_count = sum(len(rows) for rows in optical_by_device.values())
    lldp_count = sum(len(rows) for rows in lldp_by_device.values())
    candidate_ap_interface_count = sum(
        1
        for device in devices
        for row in interfaces_by_device.get(str(device.device_uuid or ""), [])
        if is_trackside_ap_interface(device, row, active_plan)[0]
    )
    query_ms = int((perf_counter() - query_start) * 1000)

    build_start = perf_counter()
    rows = build_trackside_ap_business_rows(
        devices,
        interfaces_by_device,
        optical_by_device,
        fit_ap_optical_rows,
        lldp_by_device,
        fit_ap_resource_rows,
        switch_lookup,
        active_plan,
        offline_ledger_rows,
        historical_lldp_rows,
    )
    try:
        identity_shadow = TracksideApIdentityShadowService().shadow_rows(rows, fit_ap_resource_rows).to_payload()
    except Exception as exc:
        identity_shadow = unavailable_trackside_identity_shadow(len(rows), exc)
    build_ms = int((perf_counter() - build_start) * 1000)
    row_count = len(rows)
    empty_reason = ""
    if row_count == 0:
        empty_reason = _trackside_empty_reason(
            len(devices),
            interface_count,
            candidate_ap_interface_count,
            optical_count,
            lldp_count,
            len(fit_ap_optical_rows),
            len(fit_ap_resource_rows),
        )
    return TracksideApBusinessLoadResult(
        generation,
        site_name,
        rows,
        len(devices),
        query_ms,
        build_ms,
        interface_count,
        optical_count,
        lldp_count,
        len(fit_ap_optical_rows),
        len(fit_ap_resource_rows),
        candidate_ap_interface_count,
        row_count,
        empty_reason,
        identity_shadow,
    )


def export_trackside_ap_business_from_database(
    *,
    database_path: str | Path,
    site_name: str,
    output_path: str | Path,
    tmp_path: str | Path,
    language: str = "zh_CN",
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> dict[str, object]:
    output = Path(output_path)
    tmp = Path(tmp_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    i18n = I18n(language)
    repository = DeviceRepository(Database(Path(database_path)))
    ac_repository = AcRepository(repository.database)
    fact_repository = DeviceFactRepository(repository.database)

    def emit(stage: str, current: int = 0, total: int = 0, message: str = "") -> None:
        if progress_callback:
            progress_callback(stage, current, total, message or stage)

    def check_cancel() -> None:
        if should_cancel and should_cancel():
            raise TracksideApExportCancelled("导出已取消")

    emit("prepare", 0, 0, "准备导出")
    check_cancel()
    emit("query_trackside_data", 0, 0, "正在读取轨旁AP业务数据")
    snapshot = load_trackside_ap_business_snapshot(repository, site_name, generation=0)
    app_logger.log_info("TRACKSIDE_AP_EXPORT_STARTED", f"site={site_name} rows={len(snapshot.rows)} output={output}")
    check_cancel()

    emit("query_fit_ap_resources", 0, 0, "正在读取AP信息")
    resources = ac_repository.list_all_fit_ap_resources_with_metadata()
    ac_device_names = {str(device.device_uuid or ""): device.name for device in repository.list() if str(device.device_uuid or "")}
    resources = [
        {
            **row,
            "ac_device_name": row.get("ac_device_name") or ac_device_names.get(str(row.get("ac_device_uuid") or "")),
        }
        for row in resources
    ]
    check_cancel()

    emit("query_fit_ap_optical", 0, 0, "正在读取光衰与状态")
    optical_rows = ac_repository.list_all_fit_ap_optical()
    resource_history_rows = ac_repository.list_all_fit_ap_resource_history()
    ap_optical_history_rows = ac_repository.list_all_ap_optical_history()
    ap_lldp_history_rows = ac_repository.list_all_ap_lldp_history()
    capacity_details = ac_repository.list_active_trackside_plan_capacity_details() or ac_repository.list_station_ap_capacity_details()
    check_cancel()

    emit("build_workbook_data", 0, 0, "正在生成导出工作簿")
    overview_rows = ApOnlineOverviewService.build_rows(
        metadata_rows=ac_repository.list_fit_ap_metadata(),
        fit_ap_resources=resources,
        optical_rows=optical_rows,
        capacity_details=capacity_details,
    )
    latest_lldp, latest_optical = build_latest_ap_history_indexes(ac_repository, resources)
    devices = filter_station_switch_devices(repository.list(), repository.database, site_name)
    switch_optical_history_rows = fact_repository.list_all_optical_history([str(device.device_uuid or "") for device in devices])
    offline_stats, offline_ledger_rows = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap=latest_lldp,
        latest_optical_by_ap=latest_optical,
        device_lookup_by_name=build_device_lookup_by_name(devices),
        resource_history_rows=resource_history_rows,
    )
    rows = enrich_trackside_export_rows(
        snapshot.rows,
        fact_repository,
        ac_repository,
        switch_optical_history_rows=switch_optical_history_rows,
        ap_optical_history_rows=ap_optical_history_rows,
        ap_lldp_history_rows=ap_lldp_history_rows,
    )
    unauthenticated_rows = ac_repository.list_all_fit_ap_unauthenticated()
    new_online_ap_rows = build_new_online_ap_overview_rows(resources, resource_history_rows, snapshot.rows, unauthenticated_rows)
    optical_treatment_rows = build_ap_optical_treatment_records(
        rows,
        ap_optical_history_rows,
        switch_optical_history_rows,
        resources,
        resource_history_rows,
        offline_ledger_rows=offline_ledger_rows,
    )
    check_cancel()

    export_trackside_ap_business_xlsx(
        tmp,
        rows,
        TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS],
        overview_rows,
        AP_ONLINE_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        new_online_ap_rows,
        NEW_ONLINE_AP_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in NEW_ONLINE_AP_OVERVIEW_COLUMNS],
        i18n.t("trackside.export.sheet_new_online_ap_overview"),
        optical_treatment_rows,
        AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
        [i18n.t(key) for key, _field in AP_OPTICAL_TREATMENT_RECORD_COLUMNS],
        i18n.t("trackside.export.sheet_ap_optical_treatment"),
        offline_stats,
        offline_ledger_rows,
        offline_ap_headers(OFFLINE_AP_STATS_COLUMNS),
        offline_ap_headers(OFFLINE_AP_LEDGER_COLUMNS),
        progress_callback=emit,
        should_cancel=should_cancel,
    )
    check_cancel()
    emit("save_file", len(rows), len(rows), "正在保存Excel文件")
    from netconsole.services.file_contract import attach_export_metadata

    attach_export_metadata(
        tmp,
        effective_suffix=output.suffix,
        export_type="trackside_ap_business",
        payload={"source_module": "rail.trackside_ap_business"},
    )
    os.replace(tmp, output)
    emit("done", len(rows), len(rows), "完成")
    app_logger.log_info("TRACKSIDE_AP_EXPORT_COMPLETED", f"site={site_name} rows={len(rows)} output={output}")
    return {"path": str(output), "row_count": len(rows)}


def _trackside_empty_reason(
    device_count: int,
    interface_count: int,
    candidate_ap_interface_count: int,
    optical_count: int,
    lldp_count: int,
    fit_ap_optical_count: int,
    fit_ap_resource_count: int,
) -> str:
    if device_count == 0:
        return "trackside.empty.no_devices"
    if interface_count == 0:
        return "trackside.empty.no_interfaces"
    if candidate_ap_interface_count == 0:
        return "trackside.empty.no_ap_interfaces"
    if optical_count == 0 and fit_ap_optical_count == 0 and fit_ap_resource_count == 0:
        return "trackside.empty.no_optical_or_fit"
    if lldp_count == 0 and fit_ap_optical_count == 0:
        return "trackside.empty.no_lldp_or_fit"
    if fit_ap_resource_count == 0:
        return "trackside.empty.no_fit_ap_resource"
    if fit_ap_optical_count == 0:
        return "trackside.empty.no_fit_ap_optical"
    return "trackside.empty.no_rows"
