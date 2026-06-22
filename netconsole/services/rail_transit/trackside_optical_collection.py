from __future__ import annotations

import json
import re
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.optical_severity_engine import compute_optical_severity
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors
from netconsole.parsers.h3c.transceiver_parser import parse_transceiver_diagnosis
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources, collect_h3c_fit_ap_optical
from netconsole.services.h3c_optical_refresh_service import merge_existing_optical_modules
from netconsole.services.netmiko_connection import build_netmiko_params, choose_connection_target, safe_send_command, sanitize_sensitive_text
from netconsole.utils.text_encoding import clean_h3c_device_text


TRACKSIDE_OPTICAL_COMMANDS = (
    "screen-length disable",
    "display transceiver diagnosis interface",
)
DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY = 1000
UNSUPPORTED_VENDOR_REASON = "vendor_not_supported"


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
    raw_log_path: str
    parsed_count: int = 0
    error_message: str | None = None
    rows: list[dict[str, object | None]] = field(default_factory=list)
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


def build_station_switch_targets(repository: DeviceRepository, site_name: str) -> tuple[list[TracksideOpticalTarget], list[TracksideSkippedTarget]]:
    groups = {group.id: group.name for group in DeviceGroupRepository(repository.database, site_name).list()}
    targets: list[TracksideOpticalTarget] = []
    skipped: list[TracksideSkippedTarget] = []
    for device in sorted(repository.list(), key=lambda item: str(item.name or "").casefold()):
        group_name = groups.get(device.group_id or -1, "")
        if group_name != "车站" or not is_switch_device_type(device.device_type):
            continue
        target = choose_connection_target(device)
        if target is None or not target.host or not target.username or not target.password:
            skipped.append(TracksideSkippedTarget(device.name, "SWITCH", "connection_incomplete", device.ip_address))
            continue
        try:
            commands = get_optical_diagnosis_commands(device.device_vendor, device.device_type)
        except UnsupportedVendor:
            skipped.append(TracksideSkippedTarget(device.name, "SWITCH", UNSUPPORTED_VENDOR_REASON, device.ip_address))
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
            skipped.append(TracksideSkippedTarget(name, "AP", "connection_incomplete", device.ip_address))
            continue
        try:
            commands = get_optical_diagnosis_commands(device.device_vendor, device.device_type)
        except UnsupportedVendor:
            skipped.append(TracksideSkippedTarget(name, "AP", UNSUPPORTED_VENDOR_REASON, device.ip_address))
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
) -> TracksideOpticalSessionResult:
    ac_repository = AcRepository(repository.database)
    switch_targets, switch_skipped = build_station_switch_targets(repository, site_name)
    targets = dedupe_targets(switch_targets)
    skipped = [*switch_skipped]
    session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    session_dir = paths.trackside_ap_update_session_dir(site_name, session_id)
    raw_dir = session_dir / "raw"
    fit_ap_resource_raw_dir = raw_dir / "ac_fit_ap_resource"
    fit_ap_optical_raw_dir = raw_dir / "ac_fit_ap_optical"
    station_switch_raw_dir = raw_dir / "station_switch_optical"
    parsed_dir = session_dir / "parsed"
    exports_dir = session_dir / "exports"
    for directory in (fit_ap_resource_raw_dir, fit_ap_optical_raw_dir, station_switch_raw_dir, parsed_dir, exports_dir):
        directory.mkdir(parents=True, exist_ok=True)
    started_at = _now()
    cancel_event = cancel_event or Event()
    command_guard.validate_command_list(TRACKSIDE_OPTICAL_COMMANDS, "optical_refresh")
    max_workers = max(1, min(int(concurrency or DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY), len(targets) or 1))
    results: list[TracksideDeviceCollectionResult] = []
    completed = 0
    total_units = len(targets)
    if progress_callback is not None:
        progress_callback(0, total_units)
    with ThreadPoolExecutor(max_workers=1) as branch_executor:
        fit_future = branch_executor.submit(_collect_fit_ap_optical_subtasks, repository, site_name, paths, session_dir, concurrency, cancel_event)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for target in targets:
                if cancel_event.is_set():
                    skipped.append(TracksideSkippedTarget(target.name, target.target_type, "cancelled", target.host))
                    continue
                futures.append(executor.submit(_collect_one_target, target, station_switch_raw_dir, session_dir))
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                _persist_result(repository, ac_repository, result, parsed_dir / "trackside_update_results.sqlite")
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, max(total_units, 1))
        fit_ap_results, fit_ap_total, fit_ap_skipped = fit_future.result()
    skipped.extend(fit_ap_skipped)
    fit_success = sum(max(int(result.optical_rows_updated or 0) - int(result.failed_aps or 0), 0) for result in fit_ap_results)
    fit_failed = sum(int(result.failed_aps or 0) for result in fit_ap_results)
    fit_failures = sum(1 for result in fit_ap_results if not result.success and not result.partial_success and int(result.optical_rows_updated or 0) == 0)
    total_units = fit_ap_total + len(targets)
    if progress_callback is not None:
        progress_callback(total_units, total_units)
    status = "CANCELLED" if cancel_event.is_set() else "DONE"
    success_count = fit_success + sum(1 for result in results if result.success)
    failed_count = fit_failed + fit_failures + sum(1 for result in results if not result.success)
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
            "station_switch_success_count": sum(1 for result in results if result.success),
            "station_switch_total": len(targets),
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": len(skipped),
            "concurrency": concurrency,
            "command_list": sorted({command for target in targets for command in target.commands}),
            "commands": sorted({command for target in targets for command in target.commands}),
            "status": status,
            "skipped": [item.__dict__ for item in skipped],
        },
    )
    return TracksideOpticalSessionResult(session_id, session_dir, success_count, failed_count, len(skipped), total_units, concurrency, status, skipped, results, fit_ap_total, len(targets))


def _collect_fit_ap_optical_subtasks(
    repository: DeviceRepository,
    site_name: str,
    paths: PathResolver,
    session_dir: Path,
    concurrency: int,
    cancel_event: Event,
):
    ac_repository = AcRepository(repository.database)
    results = []
    skipped: list[TracksideSkippedTarget] = []
    total = 0
    for ac_device in sorted(repository.list(vendor="H3C", device_type="AC"), key=lambda item: str(item.name or "").casefold()):
        if cancel_event.is_set():
            continue
        resource_result = collect_h3c_ac_resources(ac_device, site_name, repository=ac_repository, paths=paths)
        _copy_ac_raw(paths, site_name, resource_result.collect_run_uuid, session_dir / "raw" / "ac_fit_ap_resource")
        if not resource_result.success:
            skipped.append(TracksideSkippedTarget(ac_device.name, "AC", "fit_ap_resource_failed", ac_device.ip_address))
            continue
        resources = ac_repository.list_fit_ap_resources_with_metadata(str(ac_device.device_uuid or ""))
        total += len(resources)
        skipped.extend(
            TracksideSkippedTarget(str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"), "FIT_AP", "connection_incomplete", str(row.get("ap_ip") or ""))
            for row in resources
            if not row.get("ap_ip")
        )
        if cancel_event.is_set():
            skipped.extend(TracksideSkippedTarget(str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"), "FIT_AP", "cancelled", str(row.get("ap_ip") or "")) for row in resources if row.get("ap_ip"))
            continue
        result = collect_h3c_fit_ap_optical(ac_device, site_name, repository=ac_repository, paths=paths, max_workers=concurrency)
        results.append(result)
        _copy_ac_raw(paths, site_name, result.collect_run_uuid, session_dir / "raw" / "ac_fit_ap_optical")
    return results, total, skipped


def _copy_ac_raw(paths: PathResolver, site_name: str, collect_run_uuid: str, target_root: Path) -> None:
    source = paths.site_dir(site_name) / "raw" / "ac" / collect_run_uuid
    target = target_root / collect_run_uuid
    if not source.exists():
        return
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _collect_one_target(target: TracksideOpticalTarget, raw_dir: Path, session_dir: Path) -> TracksideDeviceCollectionResult:
    raw_log = raw_dir / f"{_safe_file_name(target.name)}__{target.device_id or target.host.replace('.', '_')}.log"
    connection = None
    command_outputs: dict[str, str] = {}
    lines = [
        f"Device Name: {target.name}",
        f"Device IP: {target.host}",
        f"Device Type: {target.target_type}",
        f"Protocol: {target.protocol}",
        f"Collected At: {_now()}",
        "",
    ]
    try:
        connection = netmiko_connection.ConnectHandler(**build_netmiko_params(choose_connection_target(target.device)))  # type: ignore[arg-type]
        for command in target.commands:
            output = clean_h3c_device_text(safe_send_command(connection, command, read_timeout=120, strip_prompt=False, strip_command=False, use_timing=True))
            command_outputs[command] = output
            lines.extend([f"===== COMMAND: {command} =====", output, ""])
        parsed = parse_transceiver_diagnosis(command_outputs.get("display transceiver diagnosis interface", ""))
        lldp_rows = parse_lldp_neighbors(command_outputs.get("display lldp neighbor-information list", ""))
        rows = [_result_row(target, row, session_dir, raw_log) for row in parsed]
        raw_log.write_text("\n".join(lines), encoding="utf-8")
        return TracksideDeviceCollectionResult(target, True, str(raw_log), len(rows), rows=rows, lldp_rows=lldp_rows)
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), target.device)
        lines.extend(["===== ERROR =====", message, ""])
        raw_log.write_text("\n".join(lines), encoding="utf-8")
        return TracksideDeviceCollectionResult(target, False, str(raw_log), 0, message)
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
        existing = fact_repository.list_optical_modules(str(result.target.device_uuid or ""))
        modules = merge_existing_optical_modules(
            existing,
            result.rows,
            [],
            {
                "collected_at": _now(),
                "updated_at": _now(),
                "collect_run_uuid": "",
                "raw_log_path": result.raw_log_path,
            },
        )
        fact_repository.replace_optical_modules(str(result.target.device_uuid or ""), modules)
        if result.lldp_rows:
            metadata = {
                "collected_at": _now(),
                "updated_at": _now(),
                "collect_run_uuid": "",
                "raw_log_path": result.raw_log_path,
            }
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
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS optical_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT,
                device_ip TEXT,
                device_type TEXT,
                group_name TEXT,
                interface_name TEXT,
                module_type TEXT,
                rx_power TEXT,
                tx_power TEXT,
                rx_status TEXT,
                tx_status TEXT,
                collected_at TEXT,
                raw_log_path TEXT,
                error_message TEXT
            )
            """
        )
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
        for row in rows:
            conn.execute(
                """
                INSERT INTO optical_results (
                    device_name, device_ip, device_type, group_name, interface_name, module_type,
                    rx_power, tx_power, rx_status, tx_status, collected_at, raw_log_path, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("device_name"),
                    row.get("device_ip"),
                    row.get("device_type"),
                    row.get("group_name"),
                    row.get("interface_name"),
                    row.get("module_model"),
                    row.get("rx_power"),
                    row.get("tx_power"),
                    row.get("optical_alarm_status"),
                    row.get("tx_status"),
                    row.get("collected_at"),
                    row.get("raw_log_path"),
                    row.get("error_message"),
                ),
            )
        conn.commit()


def _result_row(target: TracksideOpticalTarget, parsed: dict[str, object | None], session_dir: Path, raw_log: Path) -> dict[str, object | None]:
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
        "raw_log_path": str(raw_log.relative_to(session_dir)),
    }


def _find_related_device(ap: dict[str, object | None], devices: list[Device]) -> Device | None:
    ap_ip = str(ap.get("ap_ip") or "").strip()
    ap_name = str(ap.get("ap_name") or "").strip().casefold()
    for device in devices:
        if ap_ip and device.ip_address == ap_ip:
            return device
    for device in devices:
        if ap_name and ap_name in {str(device.name or "").strip().casefold(), str(device.sysname or "").strip().casefold()}:
            return device
    return None


def _write_session_meta(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_file_name(value: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", value.strip())
    return text or "device"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
