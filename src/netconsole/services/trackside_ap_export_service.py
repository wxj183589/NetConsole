from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from time import perf_counter, sleep
from types import MappingProxyType
from typing import Callable
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.sources.switch_source import build_switch_data_lookup
from netconsole.models.ap_identity_index import ApIdentityMatch
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac_key
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
    CURRENT_OPTICAL_ABNORMAL_COLUMNS,
    NEW_ONLINE_AP_OVERVIEW_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    TRACKSIDE_AP_UNMATCHED_ONLINE_COLUMNS,
    TracksideApExportCancelled,
    build_ap_optical_treatment_records,
    build_new_online_ap_overview_rows,
    build_trackside_ap_business_rows,
    enrich_trackside_export_rows,
    export_trackside_ap_business_xlsx,
    filter_trackside_ap_business_rows,
    filter_station_switch_devices,
    count_current_optical_abnormal_aps,
    is_current_optical_abnormal_row,
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
    resolve_effective_trackside_ap_scope,
)
from netconsole.services.rail_transit.trackside_ap_runtime_snapshot import (
    TracksideApRuntimeSnapshot,
    build_trackside_ap_runtime_snapshot,
)
from netconsole.services.rail_transit.trackside_ap_business_snapshot import (
    TRACKSIDE_AP_SORT_CONTRACT,
    TracksideApBusinessSnapshotError,
    build_business_revision,
    business_row_id,
    content_sha256,
    read_export_snapshot,
    read_trackside_ap_source_revisions,
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
    rows: Sequence[Mapping[str, object | None]]
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
    fit_ap_matched_online_count: int = 0
    fit_ap_online_total_count: int = 0
    fit_ap_offline_total_count: int = 0
    fit_ap_unknown_total_count: int = 0
    fit_ap_unmatched_online_count: int = 0
    fit_ap_lldp_snapshot_stale_count: int = 0
    fit_ap_lldp_exact_match_pending_count: int = 0
    fit_ap_current_conflict_count: int = 0
    fit_ap_planning_missing_count: int = 0
    fit_ap_ambiguous_online_count: int = 0
    fit_ap_station_master_missing_count: int = 0
    fit_ap_unknown_association_count: int = 0
    fit_ap_switch_not_found_count: int = 0
    fit_ap_switch_identity_ambiguous_count: int = 0
    fit_ap_switch_data_incomplete_count: int = 0
    fit_ap_plan_not_found_count: int = 0
    fit_ap_plan_station_missing_count: int = 0
    fit_ap_plan_station_invalid_count: int = 0
    candidate_ap_interface_count: int = 0
    row_count: int = 0
    business_row_count: int = 0
    empty_reason: str = ""
    identity_shadow: dict[str, object] = field(default_factory=dict)
    scope: EffectiveTracksideApScope | None = None
    partial_data: bool = False
    source_statuses: dict[str, str] = field(default_factory=dict)
    unavailable_sources: list[dict[str, str]] = field(default_factory=list)
    runtime_snapshot: TracksideApRuntimeSnapshot = field(default_factory=TracksideApRuntimeSnapshot)
    all_devices: tuple[Device, ...] = ()
    snapshot_id: str = ""
    business_revision: str = ""
    source_revisions: Mapping[str, str] = field(default_factory=dict)
    identity_revision: int = 0
    created_at: str = ""
    content_sha256: str = ""
    unresolved_count: int = 0
    ambiguous_count: int = 0
    snapshot_retry_count: int = 0
    identity_distinct_count: int = 0
    identity_query_entities: Mapping[str, str] = field(default_factory=dict)


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
    identity_query_macs: Sequence[object] = (),
    max_attempts: int = 3,
) -> TracksideApBusinessLoadResult:
    context = scope_context or TracksideApScopeContext(
        site_id=site_name,
        project_id=site_name,
    )
    context_payload = _scope_context_payload(context)
    attempts = max(1, min(int(max_attempts), 3))
    for attempt in range(attempts):
        source_revisions = read_trackside_ap_source_revisions(
            repository.database,
            scope_context=context_payload,
        )
        snapshot = _load_trackside_ap_business_snapshot_once(
            repository,
            site_name,
            generation,
            scope_context=context,
            identity_query_macs=identity_query_macs,
        )
        confirmed_revisions = read_trackside_ap_source_revisions(
            repository.database,
            scope_context=context_payload,
        )
        if source_revisions == confirmed_revisions:
            rows = tuple(
                MappingProxyType(dict(row))
                for row in snapshot.rows
            )
            revision = build_business_revision(site_name, confirmed_revisions)
            created_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
            if snapshot.scope is not None:
                snapshot.scope.unmatched_online_items = [
                    replace(
                        item,
                        source_revisions=dict(confirmed_revisions),
                        snapshot_revision=revision,
                        snapshot_created_at=created_at,
                    )
                    for item in snapshot.scope.unmatched_online_items
                ]
            stable_snapshot = replace(
                snapshot,
                rows=rows,
                snapshot_id=uuid4().hex,
                business_revision=revision,
                source_revisions=MappingProxyType(dict(confirmed_revisions)),
                created_at=created_at,
                content_sha256=content_sha256(rows),
                snapshot_retry_count=attempt,
                identity_query_entities=MappingProxyType(
                    dict(snapshot.identity_query_entities)
                ),
            )
            app_logger.log_info(
                "TRACKSIDE_AP_SNAPSHOT_BUILT",
                (
                    f"site={site_name} revision={revision[:12]} rows={len(rows)} "
                    f"snapshot_build_ms={snapshot.query_ms + snapshot.build_ms} "
                    f"snapshot_retry_count={attempt} "
                    f"source_revision_count={len(confirmed_revisions)} "
                    f"identity_distinct_count={snapshot.identity_distinct_count}"
                ),
            )
            return stable_snapshot
        if attempt + 1 < attempts:
            sleep(0.02 * (attempt + 1))
    raise TracksideApBusinessSnapshotError(
        "TRACKSIDE_AP_SNAPSHOT_UNSTABLE",
        "轨旁 AP 数据正在刷新，暂时无法形成一致快照，请稍后重试。",
    )


def _load_trackside_ap_business_snapshot_once(
    repository: DeviceRepository,
    site_name: str,
    generation: int,
    *,
    scope_context: TracksideApScopeContext,
    identity_query_macs: Sequence[object] = (),
) -> TracksideApBusinessLoadResult:
    query_start = perf_counter()
    fact_repository = DeviceFactRepository(repository.database)
    ac_repository = AcRepository(repository.database)
    source_statuses: dict[str, str] = {
        "switch_devices": "loaded",
        "switch_collection_attempts": "loaded",
        "interfaces": "loaded",
        "switch_optical": "loaded",
        "lldp": "loaded",
        "fit_ap_resources": "loaded",
        "fit_ap_optical": "loaded",
        "ap_lldp_history": "loaded",
        "planning": "loaded",
    }
    unavailable_sources: list[dict[str, str]] = []
    context = scope_context

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
    try:
        runtime_station_rows = ac_repository.list_trackside_ap_runtime_station_evidence_rows()
    except Exception as exc:
        runtime_station_rows = []
        source_statuses["lldp"] = "failed"
        source_failure("lldp", "车站交换机 LLDP", "SWITCH_LLDP_UNAVAILABLE", exc)
    try:
        all_devices = repository.list()
        devices = filter_station_switch_devices(
            all_devices,
            repository.database,
            site_name,
            project_phase=context.project_phase,
        )
    except Exception as exc:
        all_devices = []
        devices = []
        source_statuses["switch_devices"] = "failed"
        source_failure(
            "switch_devices",
            "站点交换机",
            "SWITCH_DEVICES_UNAVAILABLE",
            exc,
        )

    try:
        latest_switch_collect_runs = {
            str(row.get("device_uuid") or ""): str(
                row.get("collect_run_uuid") or ""
            )
            for row in fact_repository.list_device_facts()
            if row.get("device_uuid") and row.get("collect_run_uuid")
        }
    except Exception as exc:
        latest_switch_collect_runs = {}
        source_statuses["switch_collection_attempts"] = "failed"
        source_failure(
            "switch_collection_attempts",
            "交换机本轮采集标记",
            "SWITCH_COLLECTION_ATTEMPTS_UNAVAILABLE",
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
        # AC runtime facts are a primary business source. Base-data scope only
        # enriches or excludes the final switch-port projection.
        fit_ap_optical_rows = ac_repository.list_all_fit_ap_optical()
    except Exception as exc:
        fit_ap_optical_rows = []
        source_statuses["fit_ap_optical"] = "failed"
        source_failure(
            "fit_ap_optical",
            "FIT-AP 光衰",
            "FIT_AP_OPTICAL_UNAVAILABLE",
            exc,
        )
    fit_ap_resource_rows = fit_ap_resource_input
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
    runtime_snapshot = build_trackside_ap_runtime_snapshot(
        fit_ap_rows=fit_ap_resource_rows,
        switch_lldp_rows=runtime_station_rows,
        optical_rows=fit_ap_optical_rows,
    )
    scope = resolve_effective_trackside_ap_scope(
        context=context,
        station_rows=ac_repository.list_ap_extension_points(),
        plan_rows=ac_repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE),
        reference_rows=ac_repository.list_ap_extension_points(),
        resource_rows=fit_ap_resource_input,
        runtime_station_rows=runtime_station_rows,
        switch_identity_rows=ac_repository.list_trackside_switch_identity_rows(),
        runtime_snapshot=runtime_snapshot,
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
            station_names=scope.station_names,
            latest_switch_collect_runs=latest_switch_collect_runs,
            runtime_snapshot=runtime_snapshot,
        ),
        switch_device_ids={str(device.device_uuid or "") for device in devices},
    )
    rows, identity_revision, identity_counts, identity_query_entities = _apply_batch_identity(
        rows,
        repository.database,
        identity_query_macs=identity_query_macs,
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
        fit_ap_matched_online_count=scope.fit_ap_matched_online_count,
        fit_ap_online_total_count=scope.fit_ap_online_total_count,
        fit_ap_offline_total_count=scope.fit_ap_offline_total_count,
        fit_ap_unknown_total_count=scope.fit_ap_unknown_total_count,
        fit_ap_unmatched_online_count=scope.fit_ap_unmatched_online_count,
        fit_ap_lldp_snapshot_stale_count=scope.fit_ap_lldp_snapshot_stale_count,
        fit_ap_lldp_exact_match_pending_count=scope.fit_ap_lldp_exact_match_pending_count,
        fit_ap_current_conflict_count=scope.fit_ap_current_conflict_count,
        fit_ap_planning_missing_count=scope.fit_ap_planning_missing_count,
        fit_ap_ambiguous_online_count=scope.fit_ap_ambiguous_online_count,
        fit_ap_station_master_missing_count=scope.fit_ap_station_master_missing_count,
        fit_ap_unknown_association_count=scope.fit_ap_unknown_association_count,
        fit_ap_switch_not_found_count=scope.fit_ap_switch_not_found_count,
        fit_ap_switch_identity_ambiguous_count=scope.fit_ap_switch_identity_ambiguous_count,
        fit_ap_switch_data_incomplete_count=scope.fit_ap_switch_data_incomplete_count,
        fit_ap_plan_not_found_count=scope.fit_ap_plan_not_found_count,
        fit_ap_plan_station_missing_count=scope.fit_ap_plan_station_missing_count,
        fit_ap_plan_station_invalid_count=scope.fit_ap_plan_station_invalid_count,
        candidate_ap_interface_count=candidate_ap_interface_count,
        row_count=row_count,
        business_row_count=row_count,
        empty_reason=empty_reason,
        identity_shadow=identity_shadow,
        scope=scope,
        partial_data=bool(unavailable_sources),
        source_statuses=source_statuses,
        unavailable_sources=unavailable_sources,
        runtime_snapshot=runtime_snapshot,
        all_devices=tuple(all_devices),
        identity_revision=identity_revision,
        unresolved_count=identity_counts["unresolved"],
        ambiguous_count=identity_counts["ambiguous"],
        identity_distinct_count=identity_counts["distinct"],
        identity_query_entities=identity_query_entities,
    )


def _scope_context_payload(context: TracksideApScopeContext) -> dict[str, object]:
    return {
        "site_id": context.site_id,
        "project_id": context.project_id,
        "line_name": context.line_name,
        "project_phase": context.project_phase,
    }


def _apply_batch_identity(
    rows: Sequence[Mapping[str, object | None]],
    database: Database,
    *,
    identity_query_macs: Sequence[object] = (),
) -> tuple[list[dict[str, object | None]], int, dict[str, int], dict[str, str]]:
    normalized_rows = [dict(row) for row in rows]
    row_keys = [
        normalize_mac_key(
            row.get("lldp_observed_neighbor_mac") or row.get("ap_mac")
        )
        for row in normalized_rows
    ]
    query_keys = [
        key for value in identity_query_macs if (key := normalize_mac_key(value))
    ]
    alias_fields = (
        "lldp_observed_neighbor_mac",
        "ap_mac",
        "radio_mac",
        "ap_radio_mac",
        "peer_mac",
        "peer_radio_mac",
        "bssid",
        "bbssid",
    )
    requested = list(
        dict.fromkeys(
            key
            for row in normalized_rows
            for field in alias_fields
            if (key := normalize_mac_key(row.get(field)))
        )
    )
    distinct_query_keys = list(dict.fromkeys(query_keys))
    batch_keys = list(dict.fromkeys((*requested, *distinct_query_keys)))
    batch = ApIdentityQueryService(database).resolve_ap_macs(
        batch_keys,
        ap_role="trackside",
    )
    statuses: list[str] = []
    for row, mac_key in zip(normalized_rows, row_keys, strict=True):
        match = batch.matches.get(mac_key or "") if mac_key else None
        status = match.status if match is not None else "unresolved"
        statuses.append(status)
        row["ap_identity_entity_id"] = match.matched_entity_id if match else ""
        row["identity_match_status"] = status
        row["identity_match_rule"] = _identity_match_rule(match)
        if row.get("lldp_observed_neighbor_mac") and not row.get("lldp_match_status"):
            row["lldp_match_status"] = status.upper()
        row["business_row_id"] = business_row_id(row)
    query_entities = {
        key: match.matched_entity_id
        for key in distinct_query_keys
        if (match := batch.matches.get(key)) is not None and match.status == "matched"
    }
    return (
        normalized_rows,
        batch.revision,
        {
            "distinct": len(batch_keys),
            "unresolved": sum(status == "unresolved" for status in statuses),
            "ambiguous": sum(status == "ambiguous" for status in statuses),
        },
        query_entities,
    )


def select_trackside_ap_business_rows(
    rows: Sequence[Mapping[str, object | None]],
    *,
    station: str = "",
    query: str = "",
    optical_anomaly_only: bool = False,
    selected_row_ids: Sequence[str] = (),
    identity_query_entities: Mapping[str, str] | None = None,
) -> list[dict[str, object | None]]:
    normalized = [normalize_trackside_ap_business_row(row) for row in rows]
    selected = filter_trackside_ap_business_rows(normalized, station, query)
    query_mac = normalize_mac_key(query)
    query_entity = (identity_query_entities or {}).get(query_mac or "")
    if query_entity:
        selected_by_id = {
            str(row.get("business_row_id") or business_row_id(row)): row
            for row in selected
        }
        for row in filter_trackside_ap_business_rows(normalized, station, ""):
            if row.get("ap_identity_entity_id") == query_entity:
                selected_by_id[
                    str(row.get("business_row_id") or business_row_id(row))
                ] = row
        selected = list(selected_by_id.values())
    if optical_anomaly_only:
        selected = [row for row in selected if is_current_optical_abnormal_row(row)]
    requested_ids = tuple(
        value
        for value in dict.fromkeys(
            str(raw_value or "").strip() for raw_value in selected_row_ids
        )
        if value
    )
    if not requested_ids:
        return selected
    by_id = {
        str(row.get("business_row_id") or business_row_id(row)): row
        for row in selected
    }
    if any(row_id not in by_id for row_id in requested_ids):
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_EXPORT_SELECTION_STALE",
            "所选轨旁 AP 行已变化，请刷新后重新选择。",
        )
    return [by_id[row_id] for row_id in requested_ids]


def _identity_match_rule(match: ApIdentityMatch | None) -> str:
    if match is None:
        return "invalid_peer_mac"
    return str(
        match.match_rule
        or match.matched_alias_type
        or match.unresolved_reason
        or ""
    )


def build_trackside_ap_business_export_snapshot(
    repository: DeviceRepository,
    site_name: str,
    *,
    scope_context: Mapping[str, object] | None = None,
    station: str = "",
    query: str = "",
    optical_anomaly_only: bool = False,
    selected_row_ids: Sequence[str] = (),
    max_attempts: int = 3,
) -> dict[str, object]:
    context = TracksideApScopeContext.from_metadata(site_name, scope_context)
    revision_context = _scope_context_payload(context)
    attempts = max(1, min(int(max_attempts), 3))
    for attempt in range(attempts):
        revisions = read_trackside_ap_source_revisions(
            repository.database,
            scope_context=revision_context,
            include_export_history=True,
        )
        payload = _build_trackside_ap_business_export_snapshot_once(
            repository,
            site_name,
            context=context,
            scope_context=scope_context,
            station=station,
            query=query,
            optical_anomaly_only=optical_anomaly_only,
            selected_row_ids=selected_row_ids,
        )
        confirmed = read_trackside_ap_source_revisions(
            repository.database,
            scope_context=revision_context,
            include_export_history=True,
        )
        if revisions == confirmed:
            payload["source_revisions"] = confirmed
            payload["export_revision"] = content_sha256(
                {
                    "business_revision": payload["business_revision"],
                    "source_revisions": confirmed,
                }
            )
            payload["snapshot_retry_count"] = int(
                payload.get("snapshot_retry_count") or 0
            ) + attempt
            return payload
        if attempt + 1 < attempts:
            sleep(0.02 * (attempt + 1))
    raise TracksideApBusinessSnapshotError(
        "TRACKSIDE_AP_SNAPSHOT_UNSTABLE",
        "轨旁 AP 数据正在刷新，暂时无法形成一致快照，请稍后重试。",
    )


def _build_trackside_ap_business_export_snapshot_once(
    repository: DeviceRepository,
    site_name: str,
    *,
    context: TracksideApScopeContext,
    scope_context: Mapping[str, object] | None,
    station: str,
    query: str,
    optical_anomaly_only: bool,
    selected_row_ids: Sequence[str],
) -> dict[str, object]:
    started = perf_counter()
    ac_repository = AcRepository(repository.database)
    fact_repository = DeviceFactRepository(repository.database)
    snapshot = load_trackside_ap_business_snapshot(
        repository,
        site_name,
        generation=0,
        scope_context=context,
        identity_query_macs=(query,),
    )
    require_complete_trackside_snapshot(snapshot, "轨旁 AP 业务导出")
    scope = snapshot.scope
    if scope is None:
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 有效范围解析失败，请刷新后重试。",
        )
    resources = scope.runtime_resources
    ac_device_names = {
        str(device.device_uuid or ""): device.name
        for device in snapshot.all_devices
        if str(device.device_uuid or "")
    }
    resources = [
        {
            **row,
            "ac_device_name": row.get("ac_device_name")
            or ac_device_names.get(str(row.get("ac_device_uuid") or "")),
        }
        for row in resources
    ]
    resource_history_rows = ac_repository.list_all_fit_ap_resource_history()
    ap_optical_history_rows = scope.filter_identity_rows(
        ac_repository.list_all_ap_optical_history()
    )
    ap_lldp_history_rows = scope.filter_identity_rows(
        ac_repository.list_all_ap_lldp_history()
    )
    overview_rows = scope.overview_export_rows()
    latest_lldp, latest_optical = build_latest_ap_history_indexes(
        ac_repository,
        resources,
    )
    devices = filter_station_switch_devices(
        snapshot.all_devices,
        repository.database,
        site_name,
        project_phase=scope.context.project_phase,
    )
    switch_optical_history_rows = fact_repository.list_all_optical_history(
        [str(device.device_uuid or "") for device in devices]
    )
    offline_stats, offline_ledger_rows = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap=latest_lldp,
        latest_optical_by_ap=latest_optical,
        device_lookup_by_name=build_device_lookup_by_name(devices),
        resource_history_rows=resource_history_rows,
    )
    business_rows = select_trackside_ap_business_rows(
        snapshot.rows,
        station=station,
        query=query,
        optical_anomaly_only=optical_anomaly_only,
        selected_row_ids=selected_row_ids,
        identity_query_entities=snapshot.identity_query_entities,
    )
    rows = [
        normalize_trackside_ap_business_row(row)
        for row in enrich_trackside_export_rows(
            business_rows,
            fact_repository,
            ac_repository,
            switch_optical_history_rows=switch_optical_history_rows,
            ap_optical_history_rows=ap_optical_history_rows,
            ap_lldp_history_rows=ap_lldp_history_rows,
        )
    ]
    requested_ids = tuple(
        dict.fromkeys(str(value or "").strip() for value in selected_row_ids)
    )
    requested_ids = tuple(value for value in requested_ids if value)
    unauthenticated_rows = ac_repository.list_all_fit_ap_unauthenticated()
    new_online_ap_rows = build_new_online_ap_overview_rows(
        resources,
        resource_history_rows,
        snapshot.rows,
        unauthenticated_rows,
    )
    optical_treatment_rows = build_ap_optical_treatment_records(
        rows,
        ap_optical_history_rows,
        switch_optical_history_rows,
        resources,
        resource_history_rows,
        offline_ledger_rows=offline_ledger_rows,
    )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "site_id": site_name,
        "business_revision": snapshot.business_revision,
        "identity_revision": snapshot.identity_revision,
        "created_at": snapshot.created_at,
        "content_sha256": content_sha256(business_rows),
        "export_content_sha256": content_sha256(rows),
        "row_count": len(business_rows),
        "abnormal_count": count_current_optical_abnormal_aps(business_rows),
        "unresolved_count": sum(
            row.get("identity_match_status") == "unresolved"
            for row in business_rows
        ),
        "ambiguous_count": sum(
            row.get("identity_match_status") == "ambiguous"
            for row in business_rows
        ),
        "snapshot_retry_count": snapshot.snapshot_retry_count,
        "identity_distinct_count": snapshot.identity_distinct_count,
        "export_kind": "trackside_ap_business",
        "filters": {
            "station": station,
            "query": query,
            "optical_anomaly_only": bool(optical_anomaly_only),
        },
        "selected_row_ids": list(requested_ids),
        "sort_contract": list(TRACKSIDE_AP_SORT_CONTRACT),
        "snapshot_build_ms": int((perf_counter() - started) * 1000),
        "scope_context": dict(scope_context or {}),
        "business_rows": business_rows,
        "workbook": {
            "rows": rows,
            "overview_rows": overview_rows,
            "new_online_ap_rows": new_online_ap_rows,
            "optical_treatment_rows": optical_treatment_rows,
            "offline_stats": offline_stats,
            "offline_ledger_rows": offline_ledger_rows,
            "unmatched_online_rows": [
                item.to_dict() for item in scope.unmatched_online_items
            ],
        },
    }


def export_trackside_ap_business_from_snapshot(
    *,
    snapshot_path: str | Path,
    snapshot_sha256: str,
    output_path: str | Path,
    tmp_path: str | Path,
    language: str = "zh_CN",
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> dict[str, object]:
    payload = read_export_snapshot(snapshot_path, expected_sha256=snapshot_sha256)
    return _render_trackside_ap_business_export(
        payload,
        output_path=output_path,
        tmp_path=tmp_path,
        language=language,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
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
    repository = DeviceRepository(Database(Path(database_path)))
    payload = build_trackside_ap_business_export_snapshot(
        repository,
        site_name,
        scope_context=scope_context,
    )
    return _render_trackside_ap_business_export(
        payload,
        output_path=output_path,
        tmp_path=tmp_path,
        language=language,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )


def _render_trackside_ap_business_export(
    payload: Mapping[str, object],
    *,
    output_path: str | Path,
    tmp_path: str | Path,
    language: str,
    progress_callback: ProgressCallback | None,
    should_cancel: CancelCheck | None,
) -> dict[str, object]:
    output = Path(output_path)
    tmp = Path(tmp_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    i18n = I18n(language)
    workbook = payload.get("workbook")
    if not isinstance(workbook, Mapping):
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照缺少工作簿数据，请重新导出。",
        )

    def rows(name: str) -> list[dict[str, object | None]]:
        value = workbook.get(name)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise TracksideApBusinessSnapshotError(
                "TRACKSIDE_AP_SNAPSHOT_INVALID",
                "轨旁 AP 导出快照内容无效，请重新导出。",
            )
        return [dict(item) for item in value]

    def emit(stage: str, current: int = 0, total: int = 0, message: str = "") -> None:
        if progress_callback:
            progress_callback(stage, current, total, message or stage)

    def check_cancel() -> None:
        if should_cancel and should_cancel():
            raise TracksideApExportCancelled("导出已取消")

    business_rows = rows("rows")
    frozen_business_rows = payload.get("business_rows")
    if (
        not isinstance(frozen_business_rows, list)
        or not all(isinstance(item, dict) for item in frozen_business_rows)
        or content_sha256(frozen_business_rows) != payload.get("content_sha256")
        or content_sha256(business_rows) != payload.get("export_content_sha256")
        or len(frozen_business_rows) != int(payload.get("row_count") or 0)
    ):
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照业务行校验失败，请重新导出。",
        )
    offline_stats = workbook.get("offline_stats")
    if not isinstance(offline_stats, Mapping):
        raise TracksideApBusinessSnapshotError(
            "TRACKSIDE_AP_SNAPSHOT_INVALID",
            "轨旁 AP 导出快照离线统计无效，请重新导出。",
        )
    emit("prepare", 0, len(business_rows), "正在校验冻结快照")
    check_cancel()
    render_started = perf_counter()
    export_trackside_ap_business_xlsx(
        tmp,
        business_rows,
        TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS],
        rows("overview_rows"),
        AP_ONLINE_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        rows("new_online_ap_rows"),
        NEW_ONLINE_AP_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in NEW_ONLINE_AP_OVERVIEW_COLUMNS],
        i18n.t("trackside.export.sheet_new_online_ap_overview"),
        rows("optical_treatment_rows"),
        AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
        [i18n.t(key) for key, _field in AP_OPTICAL_TREATMENT_RECORD_COLUMNS],
        i18n.t("trackside.export.sheet_ap_optical_treatment"),
        dict(offline_stats),
        rows("offline_ledger_rows"),
        offline_ap_headers(OFFLINE_AP_STATS_COLUMNS),
        offline_ap_headers(OFFLINE_AP_LEDGER_COLUMNS),
        rows("unmatched_online_rows"),
        TRACKSIDE_AP_UNMATCHED_ONLINE_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_UNMATCHED_ONLINE_COLUMNS],
        i18n.t("trackside.export.sheet_unmatched_online"),
        progress_callback=emit,
        should_cancel=should_cancel,
        current_optical_abnormal_headers=[
            i18n.t(key) for key, _field in CURRENT_OPTICAL_ABNORMAL_COLUMNS
        ],
    )
    check_cancel()
    from netconsole.services.file_contract import attach_export_metadata

    scope_context = payload.get("scope_context")
    scope_values = scope_context if isinstance(scope_context, Mapping) else {}
    attach_export_metadata(
        tmp,
        effective_suffix=output.suffix,
        export_type="trackside_ap_business",
        payload={
            "source_module": "rail.trackside_ap_business",
            "contract_metadata": {
                "site_id": str(payload.get("site_id") or ""),
                "site_display_name": str(
                    scope_values.get("site_display_name")
                    or scope_values.get("display_name")
                    or ""
                ),
                "generated_at": str(scope_values.get("generated_at") or ""),
                "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "snapshot_id": str(payload.get("snapshot_id") or ""),
                "business_revision": str(payload.get("business_revision") or ""),
                "content_sha256": str(payload.get("content_sha256") or ""),
            },
        },
    )
    os.replace(tmp, output)
    result = {
        "path": str(output),
        "row_count": len(business_rows),
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "business_revision": str(payload.get("business_revision") or ""),
        "export_revision": str(payload.get("export_revision") or ""),
        "content_sha256": str(payload.get("content_sha256") or ""),
        "export_content_sha256": str(payload.get("export_content_sha256") or ""),
        "source_revisions": dict(payload.get("source_revisions") or {}),
        "export_kind": str(payload.get("export_kind") or "trackside_ap_business"),
        "identity_revision": int(payload.get("identity_revision") or 0),
        "abnormal_count": int(payload.get("abnormal_count") or 0),
        "unresolved_count": int(payload.get("unresolved_count") or 0),
        "ambiguous_count": int(payload.get("ambiguous_count") or 0),
        "identity_distinct_count": int(payload.get("identity_distinct_count") or 0),
        "snapshot_created_at": str(payload.get("created_at") or ""),
        "snapshot_build_ms": int(payload.get("snapshot_build_ms") or 0),
        "snapshot_retry_count": int(payload.get("snapshot_retry_count") or 0),
        "export_render_ms": int((perf_counter() - render_started) * 1000),
    }
    app_logger.log_info(
        "TRACKSIDE_AP_EXPORT_COMPLETED",
        (
            f"site={payload.get('site_id') or ''} rows={len(business_rows)} "
            f"revision={str(payload.get('business_revision') or '')[:12]} "
            f"output={output.name}"
        ),
    )
    return result


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
    raise TracksideApBusinessSnapshotError(
        "TRACKSIDE_AP_SNAPSHOT_INVALID",
        f"{operation}所需数据不完整：{detail}暂时不可用，请刷新后重试",
    )


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
