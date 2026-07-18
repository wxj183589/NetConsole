from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from netconsole.core.optical_severity_engine import compute_optical_severity
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import Device
from netconsole.parsers.h3c.interface_parser import parse_interfaces
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.transceiver_parser import parse_transceiver_diagnosis
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.trackside_optical_result_repository import TracksideOpticalResultRepository
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources, collect_h3c_fit_ap_optical
from netconsole.services.h3c_optical_refresh_service import merge_existing_optical_modules
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, safe_send_command, sanitize_sensitive_text
from netconsole.services.offline_ap_ledger import is_fit_ap_offline
from netconsole.services.trackside_ap_business import build_trackside_ap_business_rows, is_trackside_ap_interface
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.text_encoding import clean_h3c_device_text


TRACKSIDE_OPTICAL_COMMANDS = (
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
    "display interface brief",
)
DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY = 1000
TRACKSIDE_MAX_DEVICE_CONCURRENCY_KEY = "trackside_ap/max_device_concurrency"
TRACKSIDE_MAX_SWITCH_CONCURRENCY_KEY = "trackside_ap/max_switch_concurrency"
TRACKSIDE_MAX_FIT_AP_CONCURRENCY_KEY = "trackside_ap/max_fit_ap_concurrency"
UNSUPPORTED_VENDOR_REASON = "vendor_not_supported"
ACTIVE_AC_KEYWORDS = ("active", "master", "primary", "主用", "主控", "主")
STANDBY_AC_KEYWORDS = ("standby", "backup", "secondary", "备机", "备用", "备")


def rank_ac_device_for_trackside(device: Device, summary: dict[str, object | None] | None = None) -> tuple[int, int, str, str]:
    text = " ".join(
        str(value or "")
        for value in (
            getattr(device, "name", ""),
            getattr(device, "system_name", ""),
            getattr(device, "remark", ""),
        )
    ).casefold()
    active_rank = 0
    if any(keyword.casefold() in text for keyword in ACTIVE_AC_KEYWORDS):
        active_rank = -1
    elif any(keyword.casefold() in text for keyword in STANDBY_AC_KEYWORDS):
        active_rank = 1
    online_count = _int_value((summary or {}).get("online_aps"))
    updated_at = str((summary or {}).get("updated_at") or (summary or {}).get("collected_at") or "")
    return active_rank, -online_count, "".join(chr(255 - ord(ch)) for ch in updated_at), str(device.name or "").casefold()


class UnsupportedVendor(ValueError):
    pass


class OpticalCommandAdapter:
    H3C_ALIASES = {"h3c", "新华三", "新华三技术", "newh3c", "new h3c", "h3ctechnologies", "h3c technologies"}
    HUAWEI_ALIASES = {"huawei", "华为"}
    ZTE_ALIASES = {"zte", "中兴"}

    @classmethod
    def normalize_vendor(cls, vendor: object) -> str:
        text = str(vendor or "").strip()
        compact = re.sub(r"[\s_\-]+", "", text).casefold()
        if text in cls.H3C_ALIASES or compact in cls.H3C_ALIASES:
            return "H3C"
        if text in cls.HUAWEI_ALIASES or compact in cls.HUAWEI_ALIASES:
            return "HUAWEI"
        if text in cls.ZTE_ALIASES or compact in cls.ZTE_ALIASES:
            return "ZTE"
        return text.upper() if text else ""

    @classmethod
    def get_optical_diagnosis_commands(cls, vendor: object, device_type: object = None) -> tuple[str, ...]:
        normalized = cls.normalize_vendor(vendor)
        if normalized == "H3C":
            return TRACKSIDE_OPTICAL_COMMANDS
        raise UnsupportedVendor(UNSUPPORTED_VENDOR_REASON)


def get_optical_diagnosis_commands(vendor: object, device_type: object = None) -> tuple[str, ...]:
    return OpticalCommandAdapter.get_optical_diagnosis_commands(vendor, device_type)


@dataclass(frozen=True)
class TracksideOpticalTarget:
    key: str
    name: str
    host: str
    port: int
    protocol: str
    target_type: str
    group_name: str
    device: Device
    device_id: int | None = None
    device_uuid: str | None = None
    ac_device_uuid: str | None = None
    ap_uuid: str | None = None
    ap_name: str | None = None
    source: str = ""
    commands: tuple[str, ...] = TRACKSIDE_OPTICAL_COMMANDS


@dataclass(frozen=True)
class TracksideSkippedTarget:
    name: str
    target_type: str
    reason: str
    host: str = ""


@dataclass
class TracksideDeviceCollectionResult:
    target: TracksideOpticalTarget
    success: bool
    raw_log_path: str = ""
    parsed_count: int = 0
    error_message: str | None = None
    rows: list[dict[str, object | None]] = field(default_factory=list)
    interfaces: list[dict[str, object | None]] = field(default_factory=list)
    lldp_rows: list[dict[str, object | None]] = field(default_factory=list)


@dataclass
class TracksideOpticalSessionResult:
    session_id: str
    session_dir: Path
    success_count: int
    failed_count: int
    skipped_count: int
    target_count: int
    concurrency: int
    status: str
    skipped: list[TracksideSkippedTarget] = field(default_factory=list)
    results: list[TracksideDeviceCollectionResult] = field(default_factory=list)
    fit_ap_total: int = 0
    station_switch_total: int = 0
    scope: str = "all"
    target_label: str = ""
    target_ap_offline: bool = False
    switch_scope: str = "all"
    switch_scope_reason: str = ""
    candidate_ap_interface_count: int = 0
    current_lldp_port_count: int = 0
    preserved_lldp_port_count: int = 0
    fit_ap_resource_count: int = 0
    fit_ap_optical_success_count: int = 0
    fit_ap_optical_failed_count: int = 0
    trackside_rows_total: int = 0
    rows_with_ap_identity: int = 0
    rows_without_ap_identity: int = 0
    current_lldp_identity_count: int = 0


def normalize_switch_type(value: object) -> str:
    text = re.sub(r"[\s_\-]+", "", str(value or "")).casefold()
    if text in {"sw", "switch", "交换机", "交换机sw"}:
        return "SWITCH"
    return text.upper()


def is_switch_device_type(value: object) -> bool:
    return normalize_switch_type(value) == "SWITCH"


def is_connectable_device(device: Device) -> bool:
    target = choose_connection_target(device)
    if target is None:
        return False
    return bool(target.host and target.username and target.password and target.port)


def build_station_switch_targets(repository: DeviceRepository, site_name: str, station: str | None = None) -> tuple[list[TracksideOpticalTarget], list[TracksideSkippedTarget]]:
    groups = {group.id: group.name for group in DeviceGroupRepository(repository.database, site_name).list()}
    station_text = str(station or "").strip()
    targets: list[TracksideOpticalTarget] = []
    skipped: list[TracksideSkippedTarget] = []
    for device in sorted(repository.list(), key=lambda item: str(item.name or "").casefold()):
        group_name = groups.get(device.group_id or -1, "")
        if station_text and str(device.station or "").strip() != station_text:
            continue
        if group_name != "车站" or not is_switch_device_type(device.device_type):
            continue
        target = choose_connection_target(device)
        if target is None or not target.host or not target.username or not target.password:
            skipped.append(TracksideSkippedTarget(device.name, "SWITCH", "connection_incomplete", device.primary_address))
            continue
        try:
            commands = get_optical_diagnosis_commands(device.device_vendor, device.device_type)
        except UnsupportedVendor:
            skipped.append(TracksideSkippedTarget(device.name, "SWITCH", UNSUPPORTED_VENDOR_REASON, device.primary_address))
            continue
        device.ensure_device_uuid()
        targets.append(
            TracksideOpticalTarget(
                key=f"device:{device.id}",
                name=device.name,
                host=target.host,
                port=target.port,
                protocol=target.protocol,
                target_type="SWITCH",
                group_name=group_name,
                device=device,
                device_id=device.id,
                device_uuid=str(device.device_uuid),
                source="device_management",
                commands=commands,
            )
        )
    if not targets and not skipped:
        skipped.append(TracksideSkippedTarget("车站", "SWITCH", "no_station_switches"))
    return targets, skipped


def build_trackside_ap_targets(
    ac_repository: AcRepository,
    device_repository: DeviceRepository,
    trackside_rows: list[dict[str, object | None]],
) -> tuple[list[TracksideOpticalTarget], list[TracksideSkippedTarget]]:
    row_ap_uuids = {str(row.get("ap_uuid") or "") for row in trackside_rows if row.get("ap_uuid")}
    row_ap_names = {str(row.get("ap_name") or "") for row in trackside_rows if row.get("ap_name")}
    row_ap_macs = {str(row.get("ap_mac") or "").casefold() for row in trackside_rows if row.get("ap_mac")}
    devices = device_repository.list()
    targets: list[TracksideOpticalTarget] = []
    skipped: list[TracksideSkippedTarget] = []
    for ap in ac_repository.list_all_fit_ap_resources_with_metadata():
        if row_ap_uuids and str(ap.get("ap_uuid") or "") not in row_ap_uuids:
            continue
        if not row_ap_uuids and row_ap_names and str(ap.get("ap_name") or "") not in row_ap_names:
            continue
        if not row_ap_uuids and not row_ap_names and row_ap_macs and str(ap.get("ap_mac") or "").casefold() not in row_ap_macs:
            continue
        name = str(ap.get("ap_name") or ap.get("ap_ip") or "trackside-ap")
        device = _find_related_device(ap, devices)
        if device is None:
            skipped.append(TracksideSkippedTarget(name, "AP", "no_device_connection", str(ap.get("ap_ip") or "")))
            continue
        target = choose_connection_target(device)
        if target is None or not target.host or not target.username or not target.password:
            skipped.append(TracksideSkippedTarget(name, "AP", "connection_incomplete", device.primary_address))
            continue
        try:
            commands = get_optical_diagnosis_commands(device.device_vendor, device.device_type)
        except UnsupportedVendor:
            skipped.append(TracksideSkippedTarget(name, "AP", UNSUPPORTED_VENDOR_REASON, device.primary_address))
            continue
        device.ensure_device_uuid()
        targets.append(
            TracksideOpticalTarget(
                key=f"device:{device.id}" if device.id is not None else f"host:{target.host}:{target.port}:{target.protocol}",
                name=device.name or name,
                host=target.host,
                port=target.port,
                protocol=target.protocol,
                target_type="AP",
                group_name="轨旁AP",
                device=device,
                device_id=device.id,
                device_uuid=str(device.device_uuid),
                ac_device_uuid=str(ap.get("ac_device_uuid") or ""),
                ap_uuid=str(ap.get("ap_uuid") or ""),
                ap_name=name,
                source="trackside_ap_service",
                commands=commands,
            )
        )
    return targets, skipped


def dedupe_targets(targets: list[TracksideOpticalTarget]) -> list[TracksideOpticalTarget]:
    result: list[TracksideOpticalTarget] = []
    seen: set[str] = set()
    for target in targets:
        key = f"device:{target.device_id}" if target.device_id is not None else f"host:{target.host}:{target.port}:{target.protocol}"
        if key in seen:
            continue
        seen.add(key)
        result.append(target)
    return result


def collect_trackside_optical(
    repository: DeviceRepository,
    site_name: str,
    paths: PathResolver,
    trackside_rows: list[dict[str, object | None]],
    concurrency: int = DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
    cancel_event: Event | None = None,
    progress_callback=None,
    stage_callback=None,
    target_station: str | None = None,
    target_ap_uuid: str | None = None,
    target_ap_mac: str | None = None,
    target_ap_name: str | None = None,
) -> TracksideOpticalSessionResult:
    def stage(key: str) -> None:
        if stage_callback is not None:
            stage_callback(key)

    stage("trackside_ap.stage_prepare")
    ac_repository = AcRepository(repository.database)
    stage("trackside_ap.stage_collect_lldp")
    effective_station = str(target_station or "").strip()
    target_ap_update = bool(target_ap_uuid or target_ap_mac or target_ap_name)
    if not effective_station and target_ap_update:
        effective_station = _station_for_target_ap(ac_repository, target_ap_uuid, target_ap_mac, target_ap_name)
    switch_targets, switch_skipped = build_station_switch_targets(repository, site_name, effective_station or None)
    switch_scope = "station" if effective_station else "all"
    switch_scope_reason = "station_scope" if effective_station else "full_scope"
    if target_ap_update:
        switch_targets, switch_scope, switch_scope_reason = _scope_switch_targets_for_target_ap(
            repository,
            ac_repository,
            switch_targets,
            trackside_rows,
            target_ap_uuid=target_ap_uuid,
            target_ap_mac=target_ap_mac,
            target_ap_name=target_ap_name,
            fallback_scope=switch_scope,
        )
    targets = dedupe_targets(switch_targets)
    skipped = [*switch_skipped]
    session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    session_dir = paths.trackside_ap_update_session_dir(site_name, session_id)
    parsed_dir = paths.trackside_ap_update_parsed_session_dir(site_name, session_id)
    exports_dir = paths.trackside_ap_update_outputs_session_dir(site_name, session_id)
    for directory in (session_dir, parsed_dir, exports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    started_at = _now()
    cancel_event = cancel_event or Event()
    command_guard.validate_command_list(TRACKSIDE_OPTICAL_COMMANDS, "optical_refresh")
    concurrency_settings = _trackside_concurrency_settings(paths)
    requested_concurrency = max(1, int(concurrency or concurrency_settings["device"]))
    switch_concurrency = max(1, int(concurrency_settings["switch"] or requested_concurrency))
    fit_ap_concurrency = max(1, int(concurrency_settings["fit_ap"] or requested_concurrency))
    max_workers = max(1, min(requested_concurrency, switch_concurrency, len(targets) or 1))
    results: list[TracksideDeviceCollectionResult] = []
    completed = 0
    total_units = len(targets)
    if progress_callback is not None:
        progress_callback(0, total_units)
    with ThreadPoolExecutor(max_workers=1) as branch_executor:
        stage("trackside_ap.stage_refresh_fit_ap")
        fit_future = branch_executor.submit(
            _collect_fit_ap_optical_subtasks,
            repository,
            site_name,
            paths,
            min(requested_concurrency, fit_ap_concurrency),
            cancel_event,
            effective_station or None,
            target_ap_uuid,
            target_ap_mac,
            target_ap_name,
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            stage("trackside_ap.stage_collect_optical")
            futures = []
            for target in targets:
                if cancel_event.is_set():
                    skipped.append(TracksideSkippedTarget(target.name, target.target_type, "cancelled", target.host))
                    continue
                futures.append(executor.submit(_collect_one_target, target))
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                stage("trackside_ap.stage_write_database")
                _persist_result(repository, ac_repository, result, parsed_dir / "trackside_update_results.sqlite")
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, max(total_units, 1))
        stage("trackside_ap.stage_refresh_fit_ap_optical")
        fit_ap_results, fit_ap_total, fit_ap_skipped = fit_future.result()
    target_ap_resource = _find_scoped_fit_ap_resource(
        ac_repository.list_all_fit_ap_resources_with_metadata(),
        target_ap_uuid=target_ap_uuid,
        target_ap_mac=target_ap_mac,
        target_ap_name=target_ap_name,
    )
    target_ap_offline = bool(target_ap_update and target_ap_resource and is_fit_ap_offline(target_ap_resource))
    skipped.extend(fit_ap_skipped)
    stage("trackside_ap.stage_aggregate")
    fit_success = sum(max(int(result.optical_rows_updated or 0) - int(result.failed_aps or 0), 0) for result in fit_ap_results)
    fit_failed = sum(int(result.failed_aps or 0) for result in fit_ap_results)
    fit_failures = sum(1 for result in fit_ap_results if not result.success and not result.partial_success and int(result.optical_rows_updated or 0) == 0)
    total_units = fit_ap_total + len(targets)
    if progress_callback is not None:
        progress_callback(total_units, total_units)
    stage("trackside_ap.stage_write_database")
    status = "CANCELLED" if cancel_event.is_set() else "DONE"
    success_count = fit_success + sum(1 for result in results if result.success)
    failed_count = fit_failed + fit_failures + sum(1 for result in results if not result.success)
    coverage = _trackside_update_coverage(
        repository,
        ac_repository,
        [target.device for target in targets],
        results,
    )
    _write_session_meta(
        session_dir / "session_meta.json",
        {
            "session_id": session_id,
            "site": site_name,
            "started_at": started_at,
            "ended_at": _now(),
            "target_count": total_units,
            "fit_ap_total": fit_ap_total,
            "fit_ap_resource_count": fit_ap_total,
            "fit_ap_resource_status": "DONE" if fit_ap_results or fit_ap_total else "SKIPPED",
            "fit_ap_optical_status": "DONE" if fit_ap_results else "SKIPPED",
            "station_switch_optical_status": "DONE" if results else "SKIPPED",
            "fit_ap_optical_success_count": fit_success,
            "fit_ap_optical_failed_count": fit_failed,
            "station_switch_success_count": sum(1 for result in results if result.success),
            "station_switch_total": len(targets),
            **coverage,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": len(skipped),
            "concurrency": concurrency,
            "command_list": sorted({command for target in targets for command in target.commands}),
            "commands": sorted({command for target in targets for command in target.commands}),
            "status": status,
            "skipped": [item.__dict__ for item in skipped],
            "scope": "ap" if target_ap_update else ("station" if effective_station else "all"),
            "target_label": _target_ap_label(target_ap_resource, target_ap_uuid, target_ap_mac, target_ap_name) if target_ap_update else (effective_station or ""),
            "target_ap_offline": target_ap_offline,
            "switch_scope": switch_scope,
            "switch_scope_reason": switch_scope_reason,
        },
    )
    return TracksideOpticalSessionResult(
        session_id,
        session_dir,
        success_count,
        failed_count,
        len(skipped),
        total_units,
        concurrency,
        status,
        skipped,
        results,
        fit_ap_total,
        len(targets),
        "ap" if target_ap_update else ("station" if effective_station else "all"),
        _target_ap_label(target_ap_resource, target_ap_uuid, target_ap_mac, target_ap_name) if target_ap_update else (effective_station or ""),
        target_ap_offline,
        switch_scope,
        switch_scope_reason,
        int(coverage.get("candidate_ap_interface_count") or 0),
        int(coverage.get("current_lldp_port_count") or 0),
        int(coverage.get("preserved_lldp_port_count") or 0),
        int(coverage.get("fit_ap_resource_count") or 0),
        int(coverage.get("fit_ap_optical_success_count") or fit_success),
        int(coverage.get("fit_ap_optical_failed_count") or fit_failed),
        int(coverage.get("trackside_rows_total") or 0),
        int(coverage.get("rows_with_ap_identity") or 0),
        int(coverage.get("rows_without_ap_identity") or 0),
        int(coverage.get("current_lldp_identity_count") or 0),
    )


def _trackside_update_coverage(
    repository: DeviceRepository,
    ac_repository: AcRepository,
    devices: list[Device],
    results: list[TracksideDeviceCollectionResult],
) -> dict[str, int]:
    fact_repository = DeviceFactRepository(repository.database)
    device_uuids = [str(device.device_uuid or "") for device in devices if str(device.device_uuid or "").strip()]
    interfaces_by_device = {device_uuid: fact_repository.list_device_interfaces(device_uuid) for device_uuid in device_uuids}
    optical_by_device = {device_uuid: fact_repository.list_optical_modules(device_uuid) for device_uuid in device_uuids}
    lldp_by_device = {device_uuid: fact_repository.list_lldp_neighbors(device_uuid) for device_uuid in device_uuids}
    fit_ap_optical_rows = ac_repository.list_all_fit_ap_optical()
    fit_ap_resource_rows = ac_repository.list_all_fit_ap_resources_with_metadata()
    active_plan = ac_repository.get_active_trackside_pvid_plan()
    historical_lldp_rows = ac_repository.list_latest_ap_lldp_histories()
    rows = build_trackside_ap_business_rows(
        devices,
        interfaces_by_device,
        optical_by_device,
        fit_ap_optical_rows,
        lldp_by_device,
        fit_ap_resource_rows,
        None,
        active_plan,
        [],
        historical_lldp_rows,
    )
    candidate_ap_interface_count = sum(
        1
        for device in devices
        for interface in interfaces_by_device.get(str(device.device_uuid or ""), [])
        if is_trackside_ap_interface(device, interface, active_plan)[0]
    )
    collected_lldp_ports = {
        (str(result.target.device_uuid or ""), normalize_interface_name(row.get("local_interface")).casefold())
        for result in results
        if result.success
        for row in result.lldp_rows
        if normalize_interface_name(row.get("local_interface")).casefold()
    }
    stored_lldp_ports = {
        (device_uuid, normalize_interface_name(row.get("local_interface")).casefold())
        for device_uuid, lldp_rows in lldp_by_device.items()
        for row in lldp_rows
        if normalize_interface_name(row.get("local_interface")).casefold()
    }
    rows_with_ap_identity = sum(1 for row in rows if _has_trackside_ap_identity(row))
    rows_without_ap_identity = max(len(rows) - rows_with_ap_identity, 0)
    return {
        "candidate_ap_interface_count": candidate_ap_interface_count,
        "current_lldp_port_count": len(collected_lldp_ports),
        "preserved_lldp_port_count": max(len(stored_lldp_ports - collected_lldp_ports), 0),
        "fit_ap_resource_count": len(fit_ap_resource_rows),
        "fit_ap_optical_success_count": sum(1 for row in fit_ap_optical_rows if str(row.get("status") or "").casefold() == "success"),
        "fit_ap_optical_failed_count": sum(1 for row in fit_ap_optical_rows if str(row.get("status") or "").casefold() not in {"", "success"}),
        "trackside_rows_total": len(rows),
        "rows_with_ap_identity": rows_with_ap_identity,
        "rows_without_ap_identity": rows_without_ap_identity,
        "current_lldp_identity_count": sum(1 for row in rows if row.get("has_current_lldp") and _has_trackside_ap_identity(row)),
    }


def _has_trackside_ap_identity(row: dict[str, object | None]) -> bool:
    return bool(_normalize_mac_text(row.get("ap_mac")) or str(row.get("ap_name") or "").strip())


def _trackside_concurrency_settings(paths: PathResolver) -> dict[str, int]:
    settings = SettingsStore(paths)
    device = _positive_int_setting(settings.get_value(TRACKSIDE_MAX_DEVICE_CONCURRENCY_KEY, DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY), DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY)
    switch = _positive_int_setting(settings.get_value(TRACKSIDE_MAX_SWITCH_CONCURRENCY_KEY, device), device)
    fit_ap = _positive_int_setting(settings.get_value(TRACKSIDE_MAX_FIT_AP_CONCURRENCY_KEY, device), device)
    return {"device": device, "switch": switch, "fit_ap": fit_ap}


def _positive_int_setting(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def _collect_fit_ap_optical_subtasks(
    repository: DeviceRepository,
    site_name: str,
    paths: PathResolver,
    concurrency: int,
    cancel_event: Event,
    target_station: str | None = None,
    target_ap_uuid: str | None = None,
    target_ap_mac: str | None = None,
    target_ap_name: str | None = None,
):
    ac_repository = AcRepository(repository.database)
    results = []
    skipped: list[TracksideSkippedTarget] = []
    total = 0
    summaries = {str(row.get("ac_device_uuid") or ""): row for row in ac_repository.list_ac_ap_summaries()}
    for ac_device in sorted(repository.list(vendor="H3C", device_type="AC"), key=lambda item: rank_ac_device_for_trackside(item, summaries.get(str(item.device_uuid or "")))):
        if cancel_event.is_set():
            continue
        resource_result = collect_h3c_ac_resources(ac_device, site_name, repository=ac_repository, paths=paths, refresh_ac_overview=False)
        if not resource_result.success:
            skipped.append(TracksideSkippedTarget(ac_device.name, "AC", "fit_ap_resource_failed", ac_device.primary_address))
            continue
        resources = _filter_scoped_fit_ap_resources(
            ac_repository.list_fit_ap_resources_with_metadata(str(ac_device.device_uuid or "")),
            target_station=target_station,
            target_ap_uuid=target_ap_uuid,
            target_ap_mac=target_ap_mac,
            target_ap_name=target_ap_name,
        )
        total += len(resources)
        skipped.extend(
            TracksideSkippedTarget(str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"), "FIT_AP", "connection_incomplete", str(row.get("ap_ip") or ""))
            for row in resources
            if not row.get("ap_ip")
        )
        if cancel_event.is_set():
            skipped.extend(TracksideSkippedTarget(str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"), "FIT_AP", "cancelled", str(row.get("ap_ip") or "")) for row in resources if row.get("ap_ip"))
            continue
        result = collect_h3c_fit_ap_optical(
            ac_device,
            site_name,
            repository=ac_repository,
            paths=paths,
            max_workers=concurrency,
            target_ap_uuids=[target_ap_uuid] if target_ap_uuid else None,
            target_ap_macs=[target_ap_mac] if target_ap_mac else None,
            target_ap_names=[target_ap_name] if target_ap_name else None,
            target_stations=[target_station] if target_station else None,
        )
        results.append(result)
    return results, total, skipped


def _station_for_target_ap(ac_repository: AcRepository, ap_uuid: str | None, ap_mac: str | None, ap_name: str | None) -> str:
    rows = _filter_scoped_fit_ap_resources(
        ac_repository.list_all_fit_ap_resources_with_metadata(),
        target_ap_uuid=ap_uuid,
        target_ap_mac=ap_mac,
        target_ap_name=ap_name,
    )
    if not rows:
        return ""
    row = rows[0]
    return str(row.get("site") or row.get("site_name") or row.get("station") or "").strip()


def _scope_switch_targets_for_target_ap(
    repository: DeviceRepository,
    ac_repository: AcRepository,
    switch_targets: list[TracksideOpticalTarget],
    trackside_rows: list[dict[str, object | None]],
    *,
    target_ap_uuid: str | None = None,
    target_ap_mac: str | None = None,
    target_ap_name: str | None = None,
    fallback_scope: str = "station",
) -> tuple[list[TracksideOpticalTarget], str, str]:
    matched_rows = [
        row
        for row in trackside_rows
        if _row_matches_target_ap(row, target_ap_uuid=target_ap_uuid, target_ap_mac=target_ap_mac, target_ap_name=target_ap_name)
    ]
    by_device_uuid = {str(row.get("device_uuid") or "").strip() for row in matched_rows if row.get("device_uuid")}
    by_device_name = {
        str(row.get(field) or "").strip().casefold()
        for row in matched_rows
        for field in ("device_name", "source_device")
        if str(row.get(field) or "").strip()
    }
    scoped = _filter_switch_targets_by_identity(switch_targets, by_device_uuid, by_device_name)
    if scoped:
        return scoped, "ap_switch", "current_trackside_row"

    identity = {
        key: value
        for key, value in {
            "ap_uuid": str(target_ap_uuid or "").strip(),
            "ap_mac": _normalize_mac_text(target_ap_mac),
            "ap_name": str(target_ap_name or "").strip(),
        }.items()
        if value
    }
    lldp_row = ac_repository.get_previous_ap_lldp_history(identity) if identity else None
    lldp_names = {
        str((lldp_row or {}).get(field) or "").strip().casefold()
        for field in ("neighbor_device_name", "neighbor_switch_sysname", "lldp_neighbor")
        if str((lldp_row or {}).get(field) or "").strip()
    }
    scoped = _filter_switch_targets_by_identity(switch_targets, set(), lldp_names)
    if scoped:
        return scoped, "ap_switch", "historical_lldp"

    devices = repository.list()
    scoped = _filter_switch_targets_by_identity(
        switch_targets,
        set(),
        _device_names_for_lldp_names(devices, lldp_names),
    )
    if scoped:
        return scoped, "ap_switch", "historical_lldp_device_alias"

    return switch_targets, fallback_scope, "fallback_station_or_all"


def _filter_switch_targets_by_identity(
    switch_targets: list[TracksideOpticalTarget],
    device_uuids: set[str],
    device_names: set[str],
) -> list[TracksideOpticalTarget]:
    result = []
    for target in switch_targets:
        uuid = str(target.device_uuid or "").strip()
        names = {
            str(target.name or "").strip().casefold(),
            str(getattr(target.device, "name", "") or "").strip().casefold(),
            str(getattr(target.device, "system_name", "") or "").strip().casefold(),
        }
        if uuid and uuid in device_uuids:
            result.append(target)
            continue
        if names & device_names:
            result.append(target)
    return result


def _device_names_for_lldp_names(devices: list[Device], lldp_names: set[str]) -> set[str]:
    if not lldp_names:
        return set()
    result: set[str] = set()
    for device in devices:
        names = {
            str(device.name or "").strip().casefold(),
            str(device.system_name or "").strip().casefold(),
        }
        if names & lldp_names:
            result.update(name for name in names if name)
    return result


def _row_matches_target_ap(
    row: dict[str, object | None],
    *,
    target_ap_uuid: str | None = None,
    target_ap_mac: str | None = None,
    target_ap_name: str | None = None,
) -> bool:
    ap_uuid = str(target_ap_uuid or "").strip()
    ap_mac = _normalize_mac_text(target_ap_mac)
    ap_name = str(target_ap_name or "").strip().casefold()
    if ap_uuid and str(row.get("ap_uuid") or "").strip() == ap_uuid:
        return True
    if ap_mac and _normalize_mac_text(row.get("ap_mac")) == ap_mac:
        return True
    if ap_name and str(row.get("ap_name") or "").strip().casefold() == ap_name:
        return True
    return False


def _find_scoped_fit_ap_resource(
    rows: list[dict[str, object | None]],
    *,
    target_ap_uuid: str | None = None,
    target_ap_mac: str | None = None,
    target_ap_name: str | None = None,
) -> dict[str, object | None] | None:
    scoped = _filter_scoped_fit_ap_resources(
        rows,
        target_ap_uuid=target_ap_uuid,
        target_ap_mac=target_ap_mac,
        target_ap_name=target_ap_name,
    )
    return scoped[0] if scoped else None


def _target_ap_label(
    resource: dict[str, object | None] | None,
    target_ap_uuid: str | None,
    target_ap_mac: str | None,
    target_ap_name: str | None,
) -> str:
    return str(
        (resource or {}).get("ap_name")
        or target_ap_name
        or (resource or {}).get("ap_mac")
        or target_ap_mac
        or (resource or {}).get("ap_uuid")
        or target_ap_uuid
        or ""
    )


def _filter_scoped_fit_ap_resources(
    rows: list[dict[str, object | None]],
    *,
    target_station: str | None = None,
    target_ap_uuid: str | None = None,
    target_ap_mac: str | None = None,
    target_ap_name: str | None = None,
) -> list[dict[str, object | None]]:
    station = str(target_station or "").strip().casefold()
    ap_uuid = str(target_ap_uuid or "").strip()
    ap_mac = _normalize_mac_text(target_ap_mac)
    ap_name = str(target_ap_name or "").strip().casefold()
    if not any((station, ap_uuid, ap_mac, ap_name)):
        return list(rows)
    has_ap_identity = bool(ap_uuid or ap_mac or ap_name)
    result: list[dict[str, object | None]] = []
    for row in rows:
        if ap_uuid and str(row.get("ap_uuid") or "").strip() == ap_uuid:
            result.append(row)
            continue
        if ap_mac and _normalize_mac_text(row.get("ap_mac")) == ap_mac:
            result.append(row)
            continue
        if ap_name and str(row.get("ap_name") or "").strip().casefold() == ap_name:
            result.append(row)
            continue
        if has_ap_identity:
            continue
        row_station = str(row.get("site") or row.get("site_name") or row.get("station") or "").strip().casefold()
        if station and row_station == station:
            result.append(row)
    return result


def _normalize_mac_text(value: object) -> str:
    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    return hex_text.casefold() if len(hex_text) == 12 else ""


def _int_value(value: object) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _collect_one_target(target: TracksideOpticalTarget) -> TracksideDeviceCollectionResult:
    connection = None
    command_outputs: dict[str, str] = {}
    try:
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(choose_connection_target(target.device)))  # type: ignore[arg-type]
        for command in target.commands:
            output = clean_h3c_device_text(safe_send_command(connection, command, read_timeout=120, strip_prompt=False, strip_command=False, use_timing=True))
            command_outputs[command] = output
        interfaces = parse_interfaces(command_outputs.get("display interface brief", "") or command_outputs.get("display interface", ""))
        parsed = parse_transceiver_diagnosis(command_outputs.get("display transceiver diagnosis interface", ""))
        lldp_rows = parse_lldp_neighbors(command_outputs.get("display lldp neighbor-information list", ""))
        rows = [_result_row(target, row) for row in parsed]
        return TracksideDeviceCollectionResult(target, True, "", len(rows), rows=rows, interfaces=interfaces, lldp_rows=lldp_rows)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), target.device)
        return TracksideDeviceCollectionResult(target, False, "", 0, message)
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass


def _persist_result(repository: DeviceRepository, ac_repository: AcRepository, result: TracksideDeviceCollectionResult, db_path: Path) -> None:
    _write_sqlite_rows(db_path, result)
    if not result.success:
        return
    if result.target.target_type == "SWITCH":
        fact_repository = DeviceFactRepository(repository.database)
        metadata = {
            "collected_at": _now(),
            "updated_at": _now(),
            "collect_run_uuid": "",
            "raw_log_path": result.raw_log_path,
        }
        if result.interfaces:
            fact_repository.replace_device_interfaces(str(result.target.device_uuid or ""), [{**row, **metadata} for row in result.interfaces])
        existing = fact_repository.list_optical_modules(str(result.target.device_uuid or ""))
        modules = merge_existing_optical_modules(
            existing,
            result.rows,
            [],
            metadata,
        )
        fact_repository.replace_optical_modules(str(result.target.device_uuid or ""), modules)
        if result.lldp_rows:
            fact_repository.replace_lldp_neighbors(str(result.target.device_uuid or ""), [{**row, **metadata} for row in result.lldp_rows])
        return
    if result.target.ac_device_uuid:
        existing = ac_repository.list_fit_ap_optical(result.target.ac_device_uuid)
        by_key = {str(row.get("ap_uuid") or row.get("ap_name") or row.get("interface_name") or ""): dict(row) for row in existing}
        for row in result.rows:
            key = str(result.target.ap_uuid or result.target.ap_name or row.get("interface_name") or "")
            by_key[key] = {**by_key.get(key, {}), **row}
        ac_repository.replace_fit_ap_optical(result.target.ac_device_uuid, list(by_key.values()))


def _write_sqlite_rows(db_path: Path, result: TracksideDeviceCollectionResult) -> None:
    rows = result.rows or [
        {
            "device_name": result.target.name,
            "device_ip": result.target.host,
            "device_type": result.target.target_type,
            "group_name": result.target.group_name,
            "error_message": result.error_message,
            "raw_log_path": result.raw_log_path,
            "collected_at": _now(),
        }
    ]
    TracksideOpticalResultRepository(db_path).append_rows(rows)


def _result_row(target: TracksideOpticalTarget, parsed: dict[str, object | None]) -> dict[str, object | None]:
    collected_at = _now()
    severity = compute_optical_severity(
        {
            "switch_rx_power" if target.target_type == "SWITCH" else "ap_rx_power": parsed.get("rx_power"),
            "alarm_low": parsed.get("rx_low_alarm"),
            "alarm_high": parsed.get("rx_high_alarm"),
            "warning_low": parsed.get("rx_low_warning"),
            "device_type": "switch" if target.target_type == "SWITCH" else "ap",
        }
    ).severity
    return {
        **parsed,
        "device_name": target.name,
        "device_ip": target.host,
        "device_type": target.target_type,
        "group_name": target.group_name,
        "ap_uuid": target.ap_uuid,
        "ap_name": target.ap_name or target.name,
        "ac_device_uuid": target.ac_device_uuid,
        "ap_ip": target.host if target.target_type == "AP" else None,
        "optical_alarm_status": severity,
        "status": "success",
        "tx_status": "unknown",
        "collected_at": collected_at,
        "updated_at": collected_at,
        "raw_log_path": "",
    }


def _find_related_device(ap: dict[str, object | None], devices: list[Device]) -> Device | None:
    ap_ip = str(ap.get("ap_ip") or "").strip()
    ap_name = str(ap.get("ap_name") or "").strip().casefold()
    for device in devices:
        if ap_ip and device.primary_address == ap_ip:
            return device
    for device in devices:
        if ap_name and ap_name in {str(device.name or "").strip().casefold(), str(device.system_name or "").strip().casefold()}:
            return device
    return None


def _write_session_meta(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
