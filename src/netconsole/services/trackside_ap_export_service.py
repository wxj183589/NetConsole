from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
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
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS
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
    TRACKSIDE_AP_UNMATCHED_ONLINE_COLUMNS,
    TracksideApExportCancelled,
    build_ap_optical_treatment_records,
    build_new_online_ap_overview_rows,
    build_trackside_ap_business_rows,
    enrich_trackside_export_rows,
    export_trackside_ap_business_xlsx,
    filter_station_switch_devices,
    is_trackside_ap_interface,
    normalize_trackside_ap_business_row,
)
from netconsole.services.rail_transit.trackside_ap_identity_shadow import (
    TracksideApIdentityShadowService,
    unavailable_trackside_identity_shadow,
)
from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    EffectiveTracksideApScope,
    TracksideApScopeContext,
    resolve_effective_trackside_ap_scope_from_database,
)

ProgressCallback = Callable[[str, int, int, str], None]
CancelCheck = Callable[[], bool]
_WINDOWS_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]+')
_TRACKSIDE_AP_BUSINESS_SUFFIX = ".xlsx"
_TRACKSIDE_AP_BUSINESS_MARK = "_轨旁AP业务_"
_MAX_TRACKSIDE_AP_BUSINESS_NAME_LENGTH = 180


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
    fit_ap_resource_total_count: int = 0
    fit_ap_matched_count: int = 0
    fit_ap_unmatched_online_count: int = 0
    candidate_ap_interface_count: int = 0
    row_count: int = 0
    business_row_count: int = 0
    empty_reason: str = ""
    identity_shadow: dict[str, object] = field(default_factory=dict)
    scope: EffectiveTracksideApScope | None = None
    partial_data: bool = False
    source_statuses: dict[str, str] = field(default_factory=dict)
    unavailable_sources: list[dict[str, str]] = field(default_factory=list)


def build_trackside_ap_business_export_name(site_display_name: str, created_at: datetime) -> str:
    site_name = _safe_trackside_site_name(site_display_name)
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")
    fixed_tail = f"{_TRACKSIDE_AP_BUSINESS_MARK}{timestamp}{_TRACKSIDE_AP_BUSINESS_SUFFIX}"
    max_site_length = _MAX_TRACKSIDE_AP_BUSINESS_NAME_LENGTH - len(fixed_tail)
    if max_site_length <= 0:
        raise ValueError("轨旁 AP 业务导出文件名规则无效")
    if len(site_name) > max_site_length:
        site_name = site_name[:max_site_length].rstrip(" .")
    if not site_name:
        raise ValueError("轨旁 AP 业务导出缺少局点名称")
    return f"{site_name}{fixed_tail}"


def _safe_trackside_site_name(value: str) -> str:
    site_name = str(value or "").strip(" .")
    if not site_name:
        raise ValueError("轨旁 AP 业务导出缺少局点名称")
    site_name = _WINDOWS_INVALID_FILENAME_CHARS.sub("_", site_name)
    site_name = re.sub(r"_+", "_", site_name).strip(" .")
    if not site_name:
        raise ValueError("轨旁 AP 业务导出缺少局点名称")
    return site_name


def load_trackside_ap_business_snapshot(
    repository: DeviceRepository,
    site_name: str,
    generation: int,
    *,
    scope_context: TracksideApScopeContext | None = None,
) -> TracksideApBusinessLoadResult:
    query_start = perf_counter()
    fact_repository = DeviceFactRepository(repository.database)
    ac_repository = AcRepository(repository.database)
    source_statuses: dict[str, str] = {
        "switch_devices": "loaded",
        "interfaces": "loaded",
        "switch_optical": "loaded",
        "lldp": "loaded",
        "fit_ap_resources": "loaded",
        "fit_ap_optical": "loaded",
        "ap_lldp_history": "loaded",
        "planning": "loaded",
    }
    unavailable_sources: list[dict[str, str]] = []

    def source_failure(
        source: str,
        label: str,
        code: str,
        error: Exception,
        *,
        device_id: str = "",
    ) -> None:
        unavailable_sources.append(
            {
                "source": source,
                "label": label,
                "code": code,
                "message": f"{label}暂时不可用。",
                "device_id": device_id,
            }
        )
        app_logger.log_warning(
            "TRACKSIDE_AP_SOURCE_UNAVAILABLE",
            (
                f"site={site_name} source={source} device={device_id or '-'} "
                f"error={type(error).__name__}: {error}"
            ),
        )

    try:
        fit_ap_resource_input = (
            ac_repository.list_all_fit_ap_resources_with_metadata()
        )
    except Exception as exc:
        fit_ap_resource_input = []
        source_statuses["fit_ap_resources"] = "failed"
        source_failure(
            "fit_ap_resources",
            "FIT-AP 资源",
            "FIT_AP_RESOURCES_UNAVAILABLE",
            exc,
        )
    scope = resolve_effective_trackside_ap_scope_from_database(
        repository.database,
        site_id=site_name,
        context=scope_context,
        resource_rows=fit_ap_resource_input,
    )
    try:
        devices = filter_station_switch_devices(
            repository.list(),
            repository.database,
            site_name,
            project_phase=scope.context.project_phase,
        )
    except Exception as exc:
        devices = []
        source_statuses["switch_devices"] = "failed"
        source_failure(
            "switch_devices",
            "站点交换机",
            "SWITCH_DEVICES_UNAVAILABLE",
            exc,
        )

    def device_facts(
        source: str,
        label: str,
        code: str,
        loader: Callable[[str], list[dict[str, object | None]]],
    ) -> dict[str, list[dict[str, object | None]]]:
        values: dict[str, list[dict[str, object | None]]] = {}
        failed = 0
        for device in devices:
            device_id = str(device.device_uuid or "")
            try:
                values[device_id] = loader(device_id)
            except Exception as exc:
                failed += 1
                values[device_id] = []
                source_failure(
                    source,
                    label,
                    code,
                    exc,
                    device_id=device_id,
                )
        if failed:
            source_statuses[source] = (
                "failed" if failed == len(devices) else "partial"
            )
        return values

    interfaces_by_device = device_facts(
        "interfaces",
        "交换机接口事实",
        "SWITCH_INTERFACES_UNAVAILABLE",
        fact_repository.list_device_interfaces,
    )
    optical_by_device = device_facts(
        "switch_optical",
        "交换机光模块事实",
        "SWITCH_OPTICAL_UNAVAILABLE",
        fact_repository.list_optical_modules,
    )
    lldp_by_device = device_facts(
        "lldp",
        "交换机 LLDP 事实",
        "SWITCH_LLDP_UNAVAILABLE",
        fact_repository.list_lldp_neighbors,
    )
    try:
        fit_ap_optical_rows = scope.filter_identity_rows(
            ac_repository.list_all_fit_ap_optical()
        )
    except Exception as exc:
        fit_ap_optical_rows = []
        source_statuses["fit_ap_optical"] = "failed"
        source_failure(
            "fit_ap_optical",
            "FIT-AP 光衰",
            "FIT_AP_OPTICAL_UNAVAILABLE",
            exc,
        )
    fit_ap_resource_rows = scope.resources
    try:
        historical_lldp_rows = ac_repository.list_latest_ap_lldp_histories()
    except Exception as exc:
        historical_lldp_rows = []
        source_statuses["ap_lldp_history"] = "failed"
        source_failure(
            "ap_lldp_history",
            "AP 历史 LLDP",
            "AP_LLDP_HISTORY_UNAVAILABLE",
            exc,
        )
    try:
        active_plan = ac_repository.get_active_trackside_pvid_plan()
    except Exception as exc:
        active_plan = None
        source_statuses["planning"] = "failed"
        source_failure(
            "planning",
            "轨旁 AP 规划",
            "TRACKSIDE_AP_PLAN_UNAVAILABLE",
            exc,
        )
    switch_lookup = build_switch_data_lookup(devices, optical_by_device)
    try:
        latest_lldp, latest_optical = build_latest_ap_history_indexes(
            ac_repository,
            fit_ap_resource_rows,
        )
    except Exception as exc:
        latest_lldp, latest_optical = {}, {}
        source_statuses["ap_lldp_history"] = "failed"
        source_failure(
            "ap_lldp_history",
            "AP 历史 LLDP",
            "AP_LLDP_HISTORY_UNAVAILABLE",
            exc,
        )
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
    rows = scope.filter_switch_scope_rows(
        build_trackside_ap_business_rows(
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
        ),
        switch_device_ids={str(device.device_uuid or "") for device in devices},
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
        generation=generation,
        site_name=site_name,
        rows=rows,
        device_count=len(devices),
        query_ms=query_ms,
        build_ms=build_ms,
        interface_count=interface_count,
        optical_count=optical_count,
        lldp_count=lldp_count,
        fit_ap_optical_count=len(fit_ap_optical_rows),
        fit_ap_resource_count=len(fit_ap_resource_rows),
        fit_ap_resource_total_count=scope.fit_ap_resource_total_count,
        fit_ap_matched_count=scope.fit_ap_matched_count,
        fit_ap_unmatched_online_count=scope.fit_ap_unmatched_online_count,
        candidate_ap_interface_count=candidate_ap_interface_count,
        row_count=row_count,
        business_row_count=row_count,
        empty_reason=empty_reason,
        identity_shadow=identity_shadow,
        scope=scope,
        partial_data=bool(unavailable_sources),
        source_statuses=source_statuses,
        unavailable_sources=unavailable_sources,
    )


def export_trackside_ap_business_from_database(
    *,
    database_path: str | Path,
    site_name: str,
    output_path: str | Path,
    tmp_path: str | Path,
    language: str = "zh_CN",
    scope_context: dict[str, object] | None = None,
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
    snapshot = load_trackside_ap_business_snapshot(
        repository,
        site_name,
        generation=0,
        scope_context=TracksideApScopeContext.from_metadata(
            site_name,
            scope_context,
        ),
    )
    require_complete_trackside_snapshot(snapshot, "轨旁 AP 业务导出")
    app_logger.log_info(
        "TRACKSIDE_AP_EXPORT_STARTED",
        f"site={site_name} rows={len(snapshot.rows)} output={output.name}",
    )
    check_cancel()

    emit("query_fit_ap_resources", 0, 0, "正在读取AP信息")
    scope = snapshot.scope
    if scope is None:
        raise RuntimeError("轨旁 AP 有效范围解析失败")
    resources = scope.resources
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
    resource_history_rows = scope.filter_identity_rows(
        ac_repository.list_all_fit_ap_resource_history()
    )
    ap_optical_history_rows = scope.filter_identity_rows(
        ac_repository.list_all_ap_optical_history()
    )
    ap_lldp_history_rows = scope.filter_identity_rows(
        ac_repository.list_all_ap_lldp_history()
    )
    check_cancel()

    emit("build_workbook_data", 0, 0, "正在生成导出工作簿")
    overview_rows = scope.overview_export_rows()
    latest_lldp, latest_optical = build_latest_ap_history_indexes(ac_repository, resources)
    devices = filter_station_switch_devices(
        repository.list(),
        repository.database,
        site_name,
        project_phase=scope.context.project_phase,
    )
    switch_optical_history_rows = fact_repository.list_all_optical_history([str(device.device_uuid or "") for device in devices])
    offline_stats, offline_ledger_rows = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap=latest_lldp,
        latest_optical_by_ap=latest_optical,
        device_lookup_by_name=build_device_lookup_by_name(devices),
        resource_history_rows=resource_history_rows,
    )
    rows = [
        normalize_trackside_ap_business_row(row)
        for row in enrich_trackside_export_rows(
            snapshot.rows,
            fact_repository,
            ac_repository,
            switch_optical_history_rows=switch_optical_history_rows,
            ap_optical_history_rows=ap_optical_history_rows,
            ap_lldp_history_rows=ap_lldp_history_rows,
        )
    ]
    unauthenticated_rows = scope.filter_identity_rows(
        ac_repository.list_all_fit_ap_unauthenticated()
    )
    new_online_ap_rows = build_new_online_ap_overview_rows(resources, resource_history_rows, snapshot.rows, unauthenticated_rows)
    optical_treatment_rows = build_ap_optical_treatment_records(
        rows,
        ap_optical_history_rows,
        switch_optical_history_rows,
        resources,
        resource_history_rows,
        offline_ledger_rows=offline_ledger_rows,
    )
    unmatched_online_rows = [
        item.to_dict() for item in scope.unmatched_online_items
    ]
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
        unmatched_online_rows,
        TRACKSIDE_AP_UNMATCHED_ONLINE_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_UNMATCHED_ONLINE_COLUMNS],
        i18n.t("trackside.export.sheet_unmatched_online"),
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
        payload={
            "source_module": "rail.trackside_ap_business",
            "contract_metadata": {
                "site_id": site_name,
                "site_display_name": str(
                    (scope_context or {}).get("site_display_name")
                    or (scope_context or {}).get("display_name")
                    or ""
                ),
                "generated_at": str((scope_context or {}).get("generated_at") or ""),
                "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        },
    )
    os.replace(tmp, output)
    emit("done", len(rows), len(rows), "完成")
    app_logger.log_info(
        "TRACKSIDE_AP_EXPORT_COMPLETED",
        f"site={site_name} rows={len(rows)} output={output.name}",
    )
    return {"path": str(output), "row_count": len(rows)}


def require_complete_trackside_snapshot(
    snapshot: TracksideApBusinessLoadResult,
    operation: str,
) -> None:
    if not snapshot.partial_data:
        return
    labels = sorted(
        {
            str(item.get("label") or item.get("source") or "").strip()
            for item in snapshot.unavailable_sources
            if str(item.get("label") or item.get("source") or "").strip()
        }
    )
    detail = "、".join(labels) or "部分数据来源"
    raise RuntimeError(f"{operation}所需数据不完整：{detail}暂时不可用，请刷新后重试")


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
