from __future__ import annotations

import json
import inspect
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from netconsole.adapters.trackside_switch import (
    TracksidePortError,
    resolve_trackside_switch_adapter,
)
from netconsole.core.optical_severity_engine import (
    compute_optical_severity,
    compute_zte_optical_severity,
    normalize_zte_optical_record,
)
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import Device
from netconsole.parsers.zte.vlan import merge_interface_vlan_facts
from netconsole.parsers.zte.zxr10 import merge_optical_snapshot as merge_zte_optical_snapshot
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import netmiko_connection
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.services.ac.fit_ap_optical_concurrency import (
    DEFAULT_FIT_AP_OPTICAL_CONCURRENCY,
)
from netconsole.services.ac.ac_models import is_ac_device_type
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources, collect_h3c_fit_ap_optical
from netconsole.services.h3c_optical_refresh_service import merge_existing_optical_modules
from netconsole.services.netmiko_connection import (
    CommandCancelled,
    CommandOutputLimitExceeded,
    build_netmiko_params,
    choose_connection_target,
    sanitize_sensitive_text,
)
from netconsole.services.offline_ap_ledger import is_fit_ap_offline
from netconsole.services.trackside_ap_business import build_trackside_ap_business_rows, is_trackside_ap_interface
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.services.rail_transit.station_source_utils import canonical_station_name


TRACKSIDE_OPTICAL_COMMANDS = (
    "screen-length disable",
    "display lldp neighbor-information list",
    "display transceiver diagnosis interface",
    "display interface brief",
)
DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY = DEFAULT_FIT_AP_OPTICAL_CONCURRENCY
TRACKSIDE_OPTICAL_CONCURRENCY_OPTIONS = (64, 128, 256, 512)
TRACKSIDE_OPTICAL_MAX_CONCURRENCY = max(TRACKSIDE_OPTICAL_CONCURRENCY_OPTIONS)
TRACKSIDE_MAX_DEVICE_CONCURRENCY_KEY = "trackside_ap/max_device_concurrency"
TRACKSIDE_MAX_SWITCH_CONCURRENCY_KEY = "trackside_ap/max_switch_concurrency"
TRACKSIDE_MAX_FIT_AP_CONCURRENCY_KEY = "trackside_ap/max_fit_ap_concurrency"
UNSUPPORTED_VENDOR_REASON = "vendor_not_supported"
EXCLUDED_WORK_SCOPE_REASON = "设备当前工作状态为暂不参与，已自动排除"
IGNORED_SKIPPED_REASONS = frozenset(
    {"no_station_switches", EXCLUDED_WORK_SCOPE_REASON}
)
def rank_ac_device_for_trackside(device: Device, summary: dict[str, object | None] | None = None) -> tuple[int, int, str, str]:
    online_count = _int_value((summary or {}).get("online_aps"))
    updated_at = str((summary or {}).get("updated_at") or (summary or {}).get("collected_at") or "")
    return 0, -online_count, "".join(chr(255 - ord(ch)) for ch in updated_at), str(device.name or "").casefold()


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
        if normalized == "ZTE":
            return (
                "show version",
                "show interface brief",
                "show opticalinfo brief",
            )
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
    identity: dict[str, object | None] = field(default_factory=dict)
    vendor: str = ""
    profile_id: str = ""
    warnings: list[str] = field(default_factory=list)
    port_errors: list[TracksidePortError] = field(default_factory=list)
    lldp_status: str = ""
    skipped_reason: str = ""
    collect_run_uuid: str = field(default_factory=lambda: uuid4().hex)
    interface_snapshot_status: str = ""
    optical_snapshot_status: str = ""
    duration_ms: int = 0


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
    actionable_skipped_count: int = 0
    ignored_skipped_count: int = 0
    skipped_reason_counts: dict[str, int] = field(default_factory=dict)
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
    requested_concurrency: int = 0
    effective_concurrency: int = 0
    platform_concurrency_limit: int = 0
    fit_ap_effective_concurrency: int = 0
    fit_ap_round_summaries: list[dict[str, object]] = field(default_factory=list)
    warning_count: int = 0
    warnings: list[str] = field(default_factory=list)
    port_errors: list[dict[str, str]] = field(default_factory=list)
    warning_reason_counts: dict[str, int] = field(default_factory=dict)
    persistence_errors: list[dict[str, object]] = field(default_factory=list)
    failure_reason_counts: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, object]] = field(default_factory=list)
    fit_ap_resource_failed_count: int = 0


ProgressCallback = Callable[..., None]
StageCallback = Callable[..., None]


STAGE_MESSAGES = {
    "trackside_ap.prepare": "正在准备轨旁 AP 光衰更新",
    "trackside_ap.ac_resource_refresh": "正在刷新 AC FIT-AP 资源",
    "trackside_ap.switch.collect": "正在采集交换机侧光模块",
    "trackside_ap.switch.persist": "正在保存交换机侧光模块",
    "trackside_ap.fit_ap.plan": "正在统计 AP 侧光衰目标",
    "trackside_ap.fit_ap.collect": "正在采集 AP 侧光衰",
    "trackside_ap.fit_ap.retry": "正在重试 AP 侧光衰",
    "trackside_ap.aggregate": "正在聚合轨旁 AP 光衰结果",
    "trackside_ap.persist": "正在写入轨旁 AP 光衰结果",
}


class TracksideOpticalProgressTracker:
    """聚合交换机与 FIT-AP 两条并行分支的可见进度。"""

    _FINAL_STEP = 1

    def __init__(
        self,
        *,
        switch_total: int,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.switch_total = max(0, int(switch_total or 0))
        self.switch_completed = 0
        self.switch_success_count = 0
        self.switch_failed_count = 0
        self.fit_ap_total = 0
        self.fit_ap_completed = 0
        self.fit_ap_plan_ready = False
        self.fit_ap_branch_done = False
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self._progress_callback = progress_callback
        self._fit_ap_plan_by_ac: dict[str, int] = {}
        self._fit_ap_status_by_identity: dict[str, str] = {}
        self._lock = Lock()

    def emit_stage(self, stage: str, message: str, **details: object) -> None:
        with self._lock:
            self._emit_locked(stage, message, details)

    def mark_switch_completed(
        self,
        result: TracksideDeviceCollectionResult,
        *,
        persist_elapsed_ms: int = 0,
    ) -> None:
        status = "success" if result.success else "failed"
        with self._lock:
            self.switch_completed = min(self.switch_total, self.switch_completed + 1)
            if result.success:
                self.switch_success_count += 1
            else:
                self.switch_failed_count += 1
            self._recount_fit_ap_status_locked()
            self._emit_locked(
                "trackside_ap.switch.persist",
                f"交换机 {self.switch_completed}/{self.switch_total} {'成功' if result.success else '失败'}：{result.target.name}",
                {
                    "phase": "switch_optical",
                    "event": "switch_completed",
                    "status": status,
                    "target_name": result.target.name,
                    "target_ip": result.target.host,
                    "device_uuid": result.target.device_uuid or "",
                    "error_message": result.error_message or "",
                    "elapsed_ms": max(0, int(persist_elapsed_ms)),
                },
            )

    def mark_switch_skipped(self, result: TracksideDeviceCollectionResult) -> None:
        with self._lock:
            self.switch_completed = min(self.switch_total, self.switch_completed + 1)
            self.skipped_count += 1
            self._recount_fit_ap_status_locked()
            self._emit_locked(
                "trackside_ap.switch.persist",
                f"交换机 {self.switch_completed}/{self.switch_total} 已跳过：{result.target.name}",
                {
                    "phase": "switch_optical",
                    "event": "switch_skipped",
                    "status": "skipped",
                    "target_name": result.target.name,
                    "target_ip": result.target.host,
                    "device_uuid": result.target.device_uuid or "",
                    "reason": result.skipped_reason,
                },
            )

    def handle_fit_ap_event(self, payload: Mapping[str, object]) -> None:
        event = str(payload.get("event") or "")
        details = dict(payload)
        stage = self._fit_ap_stage(event)
        message = str(details.get("message") or STAGE_MESSAGES.get(stage) or stage)
        with self._lock:
            if event == "plan_ready":
                ac_uuid = str(details.get("ac_device_uuid") or "")
                planned_total = max(0, _int_value(details.get("total")))
                previous = self._fit_ap_plan_by_ac.get(ac_uuid)
                if previous is None:
                    self.fit_ap_total += planned_total
                else:
                    self.fit_ap_total += planned_total - previous
                if ac_uuid:
                    self._fit_ap_plan_by_ac[ac_uuid] = planned_total
                self.fit_ap_total = max(0, self.fit_ap_total)
                self.fit_ap_plan_ready = True
            elif event == "ap_completed":
                identity = str(details.get("ap_identity") or details.get("ap_uuid") or details.get("ap_name") or details.get("ap_ip") or "")
                status = str(details.get("status") or "failed").casefold()
                if identity:
                    self._fit_ap_status_by_identity[identity] = "success" if status == "success" else "failed"
                    self.fit_ap_completed = len(self._fit_ap_status_by_identity)
                    self._recount_fit_ap_status_locked()
            self._emit_locked(stage, message, details)

    def mark_fit_ap_branch_done(self) -> None:
        with self._lock:
            self.fit_ap_branch_done = True
            if not self.fit_ap_plan_ready:
                self.fit_ap_plan_ready = True
            self._emit_locked(
                "trackside_ap.fit_ap.collect",
                "AP 侧光衰采集分支已收口",
                {"phase": "fit_ap_optical", "event": "fit_ap_branch_done"},
            )

    def mark_persisting(self) -> None:
        with self._lock:
            self._emit_locked(
                "trackside_ap.persist",
                "正在写入轨旁 AP 光衰结果",
                {"phase": "persist", "event": "persist_started"},
            )

    def mark_completed(self) -> None:
        with self._lock:
            self._emit_locked(
                "trackside_ap.aggregate",
                "轨旁 AP 光衰更新即将完成",
                {"phase": "aggregate", "event": "final_progress"},
                force_work_complete=True,
            )

    @staticmethod
    def _fit_ap_stage(event: str) -> str:
        if event == "plan_ready":
            return "trackside_ap.fit_ap.plan"
        if event == "ap_retry_started":
            return "trackside_ap.fit_ap.retry"
        return "trackside_ap.fit_ap.collect"

    def _recount_fit_ap_status_locked(self) -> None:
        fit_success = sum(1 for status in self._fit_ap_status_by_identity.values() if status == "success")
        fit_failed = sum(1 for status in self._fit_ap_status_by_identity.values() if status != "success")
        self.success_count = self.switch_success_count + fit_success
        self.failed_count = self.switch_failed_count + fit_failed

    def _emit_locked(
        self,
        stage: str,
        message: str,
        details: Mapping[str, object],
        *,
        force_work_complete: bool = False,
    ) -> None:
        if self._progress_callback is None:
            return
        logical_total = self.switch_total + self.fit_ap_total
        logical_current = logical_total if force_work_complete else min(
            logical_total,
            self.switch_completed + self.fit_ap_completed,
        )
        total = logical_total + self._FINAL_STEP if (self.fit_ap_plan_ready or self.fit_ap_branch_done) else 0
        current = logical_current if total > 0 else 0
        payload = {
            "message": message,
            "stage": stage,
            "phase": details.get("phase") or "",
            "switch_total": self.switch_total,
            "switch_completed": self.switch_completed,
            "fit_ap_total": self.fit_ap_total,
            "fit_ap_completed": self.fit_ap_completed,
            "logical_total": logical_total,
            "logical_current": logical_current,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "prevent_running_100": True,
            **dict(details),
        }
        _call_progress_callback(self._progress_callback, current, total, payload)


def _call_progress_callback(
    callback: ProgressCallback,
    current: int,
    total: int,
    details: Mapping[str, object] | None = None,
) -> None:
    if details is None:
        callback(int(current or 0), int(total or 0))
        return
    try:
        callback(int(current or 0), int(total or 0), dict(details))
    except TypeError:
        callback(int(current or 0), int(total or 0))


def _call_stage_callback(
    callback: StageCallback | None,
    stage: str,
    message: str,
    details: Mapping[str, object] | None = None,
) -> None:
    if callback is None:
        return
    payload = {"message": message, **dict(details or {})}
    try:
        callback(stage, message, payload)
    except TypeError:
        try:
            callback(stage, message)
        except TypeError:
            callback(stage)


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
        if station_text and (
            canonical_station_name(device.station).casefold()
            != canonical_station_name(station_text).casefold()
        ):
            continue
        if group_name != "车站" or not is_switch_device_type(device.device_type):
            continue
        if _is_excluded_device(device):
            skipped.append(
                TracksideSkippedTarget(
                    device.name,
                    "SWITCH",
                    EXCLUDED_WORK_SCOPE_REASON,
                    device.primary_address,
                )
            )
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
    row_ap_macs = {
        normalize_mac(row.get("ap_mac"))
        for row in trackside_rows
        if normalize_mac(row.get("ap_mac"))
    }
    devices = device_repository.list()
    targets: list[TracksideOpticalTarget] = []
    skipped: list[TracksideSkippedTarget] = []
    for ap in ac_repository.list_all_fit_ap_resources_with_metadata():
        if row_ap_uuids and str(ap.get("ap_uuid") or "") not in row_ap_uuids:
            continue
        if not row_ap_uuids and row_ap_macs and normalize_mac(ap.get("ap_mac")) not in row_ap_macs:
            continue
        name = str(ap.get("ap_name") or ap.get("ap_ip") or "trackside-ap")
        device = _find_related_device(ap, devices)
        if device is None:
            skipped.append(TracksideSkippedTarget(name, "AP", "no_device_connection", str(ap.get("ap_ip") or "")))
            continue
        if _is_excluded_device(device):
            skipped.append(
                TracksideSkippedTarget(
                    name,
                    "AP",
                    EXCLUDED_WORK_SCOPE_REASON,
                    device.primary_address,
                )
            )
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
    def stage(key: str, message: str | None = None, **details: object) -> None:
        text = message or STAGE_MESSAGES.get(key) or key
        _call_stage_callback(stage_callback, key, text, details)

    stage("trackside_ap.prepare")
    ac_repository = AcRepository(repository.database)
    if target_ap_name and not (target_ap_uuid or target_ap_mac):
        raise ValueError("定向轨旁 AP 更新必须提供 ap_uuid 或规范化 ap_mac，禁止按 AP 名称选择")
    stage("trackside_ap.fit_ap.plan", "正在统计轨旁 AP 与车站交换机目标", phase="prepare", event="target_planning")
    effective_station = str(target_station or "").strip()
    target_ap_update = bool(target_ap_uuid or target_ap_mac or target_ap_name)
    if not effective_station and target_ap_update:
        effective_station = _station_for_target_ap(ac_repository, target_ap_uuid, target_ap_mac, target_ap_name)
    if target_ap_update and not effective_station:
        switch_targets, switch_skipped = [], []
        switch_scope = "ap_switch"
        switch_scope_reason = "target_station_unresolved"
    else:
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
    platform_concurrency_limit = TRACKSIDE_OPTICAL_MAX_CONCURRENCY
    concurrency_settings = _trackside_concurrency_settings(paths)
    requested_concurrency = _positive_int_setting(
        concurrency if concurrency is not None else concurrency_settings["device"],
        concurrency_settings["device"],
    )
    safe_requested_concurrency = _safe_trackside_concurrency(requested_concurrency, platform_concurrency_limit)
    # An explicit request is the per-run operator choice.  The persisted
    # settings remain the default for legacy callers that omit concurrency.
    switch_concurrency = _safe_trackside_concurrency(
        safe_requested_concurrency if concurrency is not None else concurrency_settings["switch"],
        platform_concurrency_limit,
    )
    fit_ap_concurrency = _safe_trackside_concurrency(
        safe_requested_concurrency if concurrency is not None else concurrency_settings["fit_ap"],
        platform_concurrency_limit,
    )
    max_workers = max(1, min(safe_requested_concurrency, switch_concurrency, len(targets) or 1))
    fit_ap_requested_concurrency = min(safe_requested_concurrency, fit_ap_concurrency)
    results: list[TracksideDeviceCollectionResult] = []
    progress_tracker = TracksideOpticalProgressTracker(
        switch_total=len(targets),
        progress_callback=progress_callback,
    )
    progress_tracker.emit_stage(
        "trackside_ap.fit_ap.plan",
        "正在统计 AP 侧光衰目标",
        phase="fit_ap_optical",
        event="target_planning",
        requested_concurrency=fit_ap_requested_concurrency,
    )

    def ac_progress(payload: Mapping[str, object]) -> None:
        details = dict(payload)
        message = str(details.pop("message", "") or "正在刷新 AC FIT-AP 资源")
        progress_tracker.emit_stage("trackside_ap.ac_resource_refresh", message, **details)

    with ThreadPoolExecutor(max_workers=1) as branch_executor:
        stage("trackside_ap.ac_resource_refresh")
        fit_future = branch_executor.submit(
            _collect_fit_ap_optical_subtasks,
            repository,
            site_name,
            paths,
            fit_ap_requested_concurrency,
            cancel_event,
            effective_station or None,
            target_ap_uuid,
            target_ap_mac,
            target_ap_name,
            progress_tracker.handle_fit_ap_event,
            ac_progress,
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            stage("trackside_ap.switch.collect")
            futures = []
            for target in targets:
                if cancel_event.is_set():
                    skipped.append(TracksideSkippedTarget(target.name, target.target_type, "cancelled", target.host))
                    continue
                device_artifact_dir = (
                    session_dir
                    / re.sub(
                        r"[^A-Za-z0-9._-]+",
                        "-",
                        str(target.device_uuid or target.name or "switch"),
                    ).strip(".-")
                )
                futures.append(
                    executor.submit(
                        _collect_one_target,
                        target,
                        device_artifact_dir,
                        cancel_event,
                        repository,
                    )
                )
            for future in as_completed(futures):
                result = future.result()
                if result.skipped_reason:
                    skipped.append(
                        TracksideSkippedTarget(
                            result.target.name,
                            result.target.target_type,
                            result.skipped_reason,
                            result.target.host,
                        )
                    )
                    progress_tracker.mark_switch_skipped(result)
                    continue
                results.append(result)
                progress_tracker.mark_switch_completed(
                    result,
                )
        stage("trackside_ap.fit_ap.collect")
        fit_ap_results, fit_ap_total, fit_ap_skipped, fit_ap_resource_failures = fit_future.result()
        progress_tracker.mark_fit_ap_branch_done()
    persistence_errors: list[dict[str, object]] = []
    persistence_started = time.monotonic()
    for result in results:
        try:
            _persist_result(repository, ac_repository, result)
        except Exception as exc:
            persistence_errors.append(_persistence_error("switch_optical.persist", exc, repository.database.path, "switch_optical_upsert", len(result.rows), persistence_started))
    fit_rows_by_ac: dict[str, list[dict[str, object | None]]] = {}
    for result in fit_ap_results:
        fit_rows_by_ac.setdefault(str(result.ac_device_uuid or ""), []).extend(result.optical_rows)
    for ac_device_uuid, rows in fit_rows_by_ac.items():
        if not ac_device_uuid or not rows:
            continue
        try:
            ac_repository.replace_fit_ap_optical(ac_device_uuid, rows)
        except Exception as exc:
            persistence_errors.append(_persistence_error("fit_ap_optical.persist", exc, repository.database.path, "fit_ap_optical_upsert", len(rows), persistence_started))
    fit_ap_effective_concurrency = max(
        (int(getattr(result, "effective_concurrency", 0) or 0) for result in fit_ap_results),
        default=0,
    )
    fit_ap_round_summaries = _fit_ap_result_round_summaries(fit_ap_results)
    target_ap_resource = _find_scoped_fit_ap_resource(
        ac_repository.list_all_fit_ap_resources_with_metadata(),
        target_ap_uuid=target_ap_uuid,
        target_ap_mac=target_ap_mac,
        target_ap_name=target_ap_name,
    )
    target_ap_offline = bool(target_ap_update and target_ap_resource and is_fit_ap_offline(target_ap_resource))
    skipped.extend(fit_ap_skipped)
    failures: list[dict[str, object]] = [*fit_ap_resource_failures]
    failures.extend(_switch_failure_details(results))
    failures.extend(_fit_ap_failure_details(fit_ap_results))
    for error in persistence_errors:
        failures.append(
            {
                "target_type": "PERSISTENCE",
                "device_uuid": "",
                "device_name": "",
                "host": "",
                "stage": str(error.get("stage") or "persist"),
                "exception_type": str(error.get("exception_type") or "PersistenceError"),
                "message": str(error.get("message") or ""),
                "reason_code": "persistence_failed",
                "duration_ms": int(error.get("elapsed_ms") or 0),
            }
        )
    stage("trackside_ap.aggregate")
    progress_tracker.emit_stage("trackside_ap.aggregate", "正在聚合轨旁 AP 光衰结果", phase="aggregate", event="aggregate_started")
    fit_success = sum(max(int(result.optical_rows_updated or 0) - int(result.failed_aps or 0), 0) for result in fit_ap_results)
    fit_failed = sum(int(result.failed_aps or 0) for result in fit_ap_results)
    fit_failures = sum(1 for result in fit_ap_results if not result.success and not result.partial_success and int(result.optical_rows_updated or 0) == 0)
    total_units = fit_ap_total + len(targets) + len(fit_ap_resource_failures)
    stage("trackside_ap.persist")
    progress_tracker.mark_persisting()
    success_count = fit_success + sum(1 for result in results if result.success)
    failed_count = (
        fit_failed
        + fit_failures
        + len(fit_ap_resource_failures)
        + sum(1 for result in results if not result.success)
    )
    switch_warnings = [
        warning
        for result in results
        for warning in result.warnings
    ]
    switch_port_errors = [
        {
            "device_uuid": str(result.target.device_uuid or ""),
            "device_name": result.target.name,
            "interface_name": item.interface_name,
            "capability": item.capability,
            "error_code": item.error_code,
            "message": item.message,
        }
        for result in results
        for item in result.port_errors
    ]
    warning_count = len(switch_warnings) + len(switch_port_errors)
    if persistence_errors:
        failed_count += len(persistence_errors)
    warning_reason_counts = _snapshot_warning_reason_counts(results)
    failure_reason_counts = _failure_reason_counts(
        results=results,
        fit_failed=fit_failed,
        fit_failures=fit_failures,
        fit_ap_resource_failures=len(fit_ap_resource_failures),
        persistence_errors=len(persistence_errors),
    )
    actionable_skipped_count, ignored_skipped_count, skipped_reason_counts = classify_trackside_skipped(skipped)
    status = _trackside_update_status(
        success_count=success_count,
        failed_count=failed_count,
        actionable_skipped_count=actionable_skipped_count,
        cancelled=cancel_event.is_set(),
        warning_count=warning_count + len(persistence_errors),
    )
    if persistence_errors and not cancel_event.is_set():
        status = "FAILED"
    coverage = _trackside_update_coverage(
        repository,
        ac_repository,
        [target.device for target in targets],
        results,
    )
    fit_ap_resource_status = (
        "PARTIAL"
        if fit_ap_resource_failures and (fit_ap_results or fit_ap_total)
        else "FAILED"
        if fit_ap_resource_failures
        else "DONE"
        if fit_ap_results or fit_ap_total
        else "SKIPPED"
    )
    fit_ap_optical_status = (
        "FAILED"
        if fit_failed + fit_failures and not fit_success
        else "PARTIAL"
        if fit_failed + fit_failures
        else "DONE"
        if fit_ap_results
        else "FAILED"
        if fit_ap_resource_failures
        else "SKIPPED"
    )
    station_switch_status = (
        "PARTIAL"
        if results and any(not result.success for result in results)
        else "FAILED"
        if targets and not results
        else "DONE"
        if results
        else "SKIPPED"
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
            "fit_ap_resource_status": fit_ap_resource_status,
            "fit_ap_optical_status": fit_ap_optical_status,
            "station_switch_optical_status": station_switch_status,
            "fit_ap_optical_success_count": fit_success,
            "fit_ap_optical_failed_count": fit_failed,
            "fit_ap_resource_failed_count": len(fit_ap_resource_failures),
            "station_switch_success_count": sum(1 for result in results if result.success),
            "station_switch_total": len(targets),
            **coverage,
            "success_count": success_count,
            "failed_count": failed_count,
            "warning_count": warning_count + len(persistence_errors),
            "warning_reason_counts": warning_reason_counts,
            "warnings": switch_warnings,
            "port_errors": switch_port_errors,
            "skipped_count": len(skipped),
            "actionable_skipped_count": actionable_skipped_count,
            "ignored_skipped_count": ignored_skipped_count,
            "skipped_reason_counts": skipped_reason_counts,
            "concurrency": safe_requested_concurrency,
            "requested_concurrency": requested_concurrency,
            "effective_concurrency": max_workers if targets else 0,
            "platform_concurrency_limit": platform_concurrency_limit,
            "fit_ap_effective_concurrency": fit_ap_effective_concurrency,
            "round_summaries": fit_ap_round_summaries,
            "command_list": sorted({command for target in targets for command in target.commands}),
            "commands": sorted({command for target in targets for command in target.commands}),
            "status": status,
            "skipped": [item.__dict__ for item in skipped],
            "scope": "ap" if target_ap_update else ("station" if effective_station else "all"),
            "target_label": _target_ap_label(target_ap_resource, target_ap_uuid, target_ap_mac, target_ap_name) if target_ap_update else (effective_station or ""),
            "target_ap_offline": target_ap_offline,
            "switch_scope": switch_scope,
            "switch_scope_reason": switch_scope_reason,
            "persistence_errors": persistence_errors,
            "failure_reason_counts": failure_reason_counts,
            "failures": failures,
        },
    )
    progress_tracker.mark_completed()
    return TracksideOpticalSessionResult(
        session_id=session_id,
        session_dir=session_dir,
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=len(skipped),
        target_count=total_units,
        concurrency=safe_requested_concurrency,
        status=status,
        actionable_skipped_count=actionable_skipped_count,
        ignored_skipped_count=ignored_skipped_count,
        skipped_reason_counts=skipped_reason_counts,
        skipped=skipped,
        results=results,
        fit_ap_total=fit_ap_total,
        station_switch_total=len(targets),
        scope="ap" if target_ap_update else ("station" if effective_station else "all"),
        target_label=_target_ap_label(target_ap_resource, target_ap_uuid, target_ap_mac, target_ap_name)
        if target_ap_update
        else (effective_station or ""),
        target_ap_offline=target_ap_offline,
        switch_scope=switch_scope,
        switch_scope_reason=switch_scope_reason,
        candidate_ap_interface_count=int(coverage.get("candidate_ap_interface_count") or 0),
        current_lldp_port_count=int(coverage.get("current_lldp_port_count") or 0),
        preserved_lldp_port_count=int(coverage.get("preserved_lldp_port_count") or 0),
        fit_ap_resource_count=int(coverage.get("fit_ap_resource_count") or 0),
        fit_ap_optical_success_count=fit_success,
        fit_ap_optical_failed_count=fit_failed,
        trackside_rows_total=int(coverage.get("trackside_rows_total") or 0),
        rows_with_ap_identity=int(coverage.get("rows_with_ap_identity") or 0),
        rows_without_ap_identity=int(coverage.get("rows_without_ap_identity") or 0),
        current_lldp_identity_count=int(coverage.get("current_lldp_identity_count") or 0),
        requested_concurrency=requested_concurrency,
        effective_concurrency=max_workers if targets else 0,
        platform_concurrency_limit=platform_concurrency_limit,
        fit_ap_effective_concurrency=fit_ap_effective_concurrency,
        fit_ap_round_summaries=fit_ap_round_summaries,
        warning_count=warning_count,
        warnings=switch_warnings,
        port_errors=switch_port_errors,
        warning_reason_counts=warning_reason_counts,
        persistence_errors=persistence_errors,
        failure_reason_counts=failure_reason_counts,
        failures=failures,
        fit_ap_resource_failed_count=len(fit_ap_resource_failures),
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
    current_lldp_rows = ac_repository.list_current_ap_lldp_states()
    device_fact_rows = fact_repository.list_device_facts()
    latest_switch_collect_runs = {
        str(row.get("device_uuid") or ""): str(row.get("collect_run_uuid") or "")
        for row in device_fact_rows
        if row.get("device_uuid") and row.get("collect_run_uuid")
    }
    collect_runs = fact_repository.get_collect_runs(
        list(latest_switch_collect_runs.values())
    )
    latest_switch_collection_attempts = {
        device_uuid: collect_runs[collect_run_uuid]
        for device_uuid, collect_run_uuid in latest_switch_collect_runs.items()
        if collect_run_uuid in collect_runs
    }
    latest_switch_collection_attempts.update(
        {
            str(result.target.device_uuid or ""): {
                "status": "success" if result.success else "failed",
                "error_message": result.error_message or "",
            }
            for result in results
            if result.target.device_uuid
        }
    )
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
        current_lldp_rows,
        latest_switch_collect_runs=latest_switch_collect_runs,
        latest_switch_collection_attempts=latest_switch_collection_attempts,
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
    return bool(_normalize_mac_text(row.get("ap_mac")))


def _trackside_concurrency_settings(paths: PathResolver) -> dict[str, int]:
    settings = SettingsStore(paths)
    device = _safe_trackside_concurrency(
        settings.get_value(TRACKSIDE_MAX_DEVICE_CONCURRENCY_KEY, DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY),
        TRACKSIDE_OPTICAL_MAX_CONCURRENCY,
    )
    switch = _safe_trackside_concurrency(
        settings.get_value(TRACKSIDE_MAX_SWITCH_CONCURRENCY_KEY, device),
        TRACKSIDE_OPTICAL_MAX_CONCURRENCY,
    )
    fit_ap = _safe_trackside_concurrency(
        settings.get_value(TRACKSIDE_MAX_FIT_AP_CONCURRENCY_KEY, device),
        TRACKSIDE_OPTICAL_MAX_CONCURRENCY,
    )
    return {"device": device, "switch": switch, "fit_ap": fit_ap}


def _trackside_update_status(
    *,
    success_count: int,
    failed_count: int,
    actionable_skipped_count: int,
    cancelled: bool,
    warning_count: int = 0,
) -> str:
    if cancelled:
        return "CANCELLED"
    if success_count <= 0 and failed_count <= 0 and actionable_skipped_count <= 0:
        return "NO_TARGET"
    if success_count > 0:
        if failed_count > 0 or actionable_skipped_count > 0 or warning_count > 0:
            return "PARTIAL_SUCCESS"
        return "SUCCESS"
    return "FAILED"


def _snapshot_warning_reason_counts(
    results: list[TracksideDeviceCollectionResult],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for status_field, reason in (
            ("interface_snapshot_status", "switch_interface_snapshot_invalid"),
            ("optical_snapshot_status", "switch_optical_snapshot_invalid"),
        ):
            status = str(
                getattr(result, status_field, "") or ""
            ).strip().upper()
            if status and status != "OK":
                counts[reason] = counts.get(reason, 0) + 1
    return counts


def classify_trackside_skipped(
    skipped: list[TracksideSkippedTarget],
) -> tuple[int, int, dict[str, int]]:
    reason_counts: dict[str, int] = {}
    ignored_count = 0
    for item in skipped:
        reason = str(item.reason or "unknown").strip() or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if reason in IGNORED_SKIPPED_REASONS:
            ignored_count += 1
    return len(skipped) - ignored_count, ignored_count, reason_counts


def _switch_failure_details(
    results: list[TracksideDeviceCollectionResult],
) -> list[dict[str, object]]:
    return [
        {
            "target_type": result.target.target_type,
            "device_uuid": str(result.target.device_uuid or ""),
            "device_name": result.target.name,
            "host": result.target.host,
            "stage": "trackside_ap.switch.collect",
            "exception_type": "CollectionError",
            "message": str(result.error_message or "交换机采集失败"),
            "reason_code": "device_collection_failed",
            "duration_ms": int(result.duration_ms or 0),
        }
        for result in results
        if not result.success
    ]


def _fit_ap_failure_details(results: list[object]) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for result in results:
        failed_rows = [
            row
            for row in (getattr(result, "optical_rows", []) or [])
            if str(row.get("status") or "").casefold() != "success"
        ]
        if failed_rows:
            for row in failed_rows:
                failures.append(
                    {
                        "target_type": "FIT_AP",
                        "device_uuid": str(getattr(result, "ac_device_uuid", "") or ""),
                        "device_name": str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"),
                        "host": str(row.get("ap_ip") or ""),
                        "stage": "trackside_ap.fit_ap.collect",
                        "exception_type": "FitApOpticalCollectionError",
                        "message": str(row.get("error_message") or "AP 光衰采集失败"),
                        "reason_code": "fit_ap_collection_failed",
                        "duration_ms": int(row.get("duration_ms") or 0),
                    }
                )
        elif not bool(getattr(result, "success", False)):
            failures.append(
                {
                    "target_type": "FIT_AP",
                    "device_uuid": str(getattr(result, "ac_device_uuid", "") or ""),
                    "device_name": str(getattr(result, "ac_device_uuid", "") or "FIT-AP"),
                    "host": "",
                    "stage": "trackside_ap.fit_ap.collect",
                    "exception_type": "FitApOpticalCollectionError",
                    "message": str(getattr(result, "error_message", "") or "AP 光衰采集失败"),
                    "reason_code": "fit_ap_collection_failed",
                    "duration_ms": 0,
                }
            )
    return failures


def _failure_reason_counts(
    *,
    results: list[TracksideDeviceCollectionResult],
    fit_failed: int,
    fit_failures: int,
    fit_ap_resource_failures: int,
    persistence_errors: int,
) -> dict[str, int]:
    counts = {
        "device_collection_failed": sum(1 for result in results if not result.success),
        "fit_ap_collection_failed": int(fit_failed) + int(fit_failures),
        "fit_ap_resource_failed": int(fit_ap_resource_failures),
        "persistence_failed": int(persistence_errors),
    }
    return {key: value for key, value in counts.items() if value > 0}


def _safe_trackside_concurrency(value: object, platform_limit: int) -> int:
    return max(1, min(_positive_int_setting(value, DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY), int(platform_limit or 1)))


def _positive_int_setting(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def _fit_ap_result_round_summaries(results: list[object]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for result in results:
        rounds = getattr(result, "round_summaries", None)
        if not rounds:
            continue
        summaries.append(
            {
                "ac_device_uuid": str(getattr(result, "ac_device_uuid", "") or ""),
                "requested_concurrency": int(getattr(result, "requested_concurrency", 0) or 0),
                "effective_concurrency": int(getattr(result, "effective_concurrency", 0) or 0),
                "platform_concurrency_limit": int(getattr(result, "platform_concurrency_limit", 0) or 0),
                "rounds": [dict(row) for row in rounds if isinstance(row, dict)],
            }
        )
    return summaries


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
    fit_ap_progress_callback: Callable[[Mapping[str, object]], None] | None = None,
    ac_progress_callback: Callable[[Mapping[str, object]], None] | None = None,
):
    ac_repository = AcRepository(repository.database)
    results = []
    skipped: list[TracksideSkippedTarget] = []
    failures: list[dict[str, object]] = []
    total = 0
    summaries = {str(row.get("ac_device_uuid") or ""): row for row in ac_repository.list_ac_ap_summaries()}
    ac_devices = sorted(
        [
            device
            for device in repository.list(vendor="H3C", work_scope_status="included")
            if is_ac_device_type(device.device_type)
            if not _is_excluded_device(device)
        ],
        key=lambda item: rank_ac_device_for_trackside(item, summaries.get(str(item.device_uuid or ""))),
    )
    ac_total = len(ac_devices)
    for ac_index, ac_device in enumerate(ac_devices, start=1):
        if cancel_event.is_set():
            continue
        ac_name = str(ac_device.name or ac_device.system_name or ac_device.device_uuid or "")

        def emit_ac_progress(message: object, *, event: str = "ac_resource_refresh") -> None:
            if ac_progress_callback is None:
                return
            ac_progress_callback(
                {
                    "message": str(message or ""),
                    "phase": "fit_ap_optical",
                    "event": event,
                    "ac_device_uuid": str(ac_device.device_uuid or ""),
                    "ac_name": ac_name,
                    "ac_index": ac_index,
                    "ac_total": ac_total,
                }
            )

        emit_ac_progress(f"正在刷新 AC {ac_index}/{ac_total} FIT-AP 资源：{ac_name}", event="ac_resource_refresh_started")
        resource_started_at = time.monotonic()
        resource_result = collect_h3c_ac_resources(
            ac_device,
            site_name,
            repository=ac_repository,
            paths=paths,
            progress=lambda message: emit_ac_progress(message),
            should_cancel=cancel_event.is_set,
            refresh_ac_overview=False,
        )
        if not resource_result.success:
            emit_ac_progress(f"AC {ac_name} FIT-AP 资源刷新失败", event="ac_resource_refresh_failed")
            failures.append(
                {
                    "target_type": "AC",
                    "device_uuid": str(ac_device.device_uuid or ""),
                    "device_name": ac_name,
                    "host": str(ac_device.primary_address or ""),
                    "stage": "trackside_ap.ac_resource_refresh",
                    "exception_type": "AcResourceCollectionError",
                    "message": str(resource_result.error_message or "AC FIT-AP 资源刷新失败"),
                    "reason_code": "fit_ap_resource_failed",
                    "duration_ms": max(0, int((time.monotonic() - resource_started_at) * 1000)),
                }
            )
            continue
        resources = _filter_scoped_fit_ap_resources(
            ac_repository.list_fit_ap_resources_with_metadata(str(ac_device.device_uuid or "")),
            target_station=target_station,
            target_ap_uuid=target_ap_uuid,
            target_ap_mac=target_ap_mac,
            target_ap_name=target_ap_name,
        )
        total += len(resources)
        emit_ac_progress(f"AC {ac_name} 可用 FIT-AP 目标 {len(resources)} 台", event="ac_resource_refresh_completed")
        if not resources:
            skipped.append(
                TracksideSkippedTarget(
                    ac_name,
                    "FIT_AP",
                    "no_fit_ap_resource",
                    ac_device.primary_address,
                )
            )
            continue
        skipped.extend(
            TracksideSkippedTarget(str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"), "FIT_AP", "connection_incomplete", str(row.get("ap_ip") or ""))
            for row in resources
            if not row.get("ap_ip")
        )
        if cancel_event.is_set():
            skipped.extend(TracksideSkippedTarget(str(row.get("ap_name") or row.get("ap_uuid") or "FIT-AP"), "FIT_AP", "cancelled", str(row.get("ap_ip") or "")) for row in resources if row.get("ap_ip"))
            continue

        def item_progress(payload: Mapping[str, object]) -> None:
            if fit_ap_progress_callback is None:
                return
            fit_ap_progress_callback(
                {
                    **dict(payload),
                    "ac_index": ac_index,
                    "ac_total": ac_total,
                }
            )

        fit_collect_kwargs = dict(
            ac_device=ac_device,
            site_name=site_name,
            repository=ac_repository,
            paths=paths,
            max_workers=concurrency,
            progress=lambda message: item_progress(
                {
                    "message": str(message or ""),
                    "phase": "fit_ap_optical",
                    "event": "fit_ap_progress_message",
                }
            ),
            item_progress=item_progress,
            target_ap_uuids=[target_ap_uuid] if target_ap_uuid else None,
            target_ap_macs=[target_ap_mac] if target_ap_mac else None,
            target_ap_names=[target_ap_name] if target_ap_name else None,
            target_stations=[target_station] if target_station else None,
            should_cancel=cancel_event.is_set,
        )
        if "persist" in inspect.signature(collect_h3c_fit_ap_optical).parameters:
            fit_collect_kwargs["persist"] = False
        if "concurrency_platform_limit" in inspect.signature(collect_h3c_fit_ap_optical).parameters:
            fit_collect_kwargs["concurrency_platform_limit"] = TRACKSIDE_OPTICAL_MAX_CONCURRENCY
        result = collect_h3c_fit_ap_optical(
            **fit_collect_kwargs,
        )
        results.append(result)
    return results, total, skipped, failures


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

    return [], "ap_switch", "no_matching_switch"


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
    checks: list[bool] = []
    row_uuid = str(row.get("ap_uuid") or "").strip()
    row_mac = _normalize_mac_text(row.get("ap_mac"))
    if ap_uuid and row_uuid:
        checks.append(row_uuid == ap_uuid)
    if ap_mac and row_mac:
        checks.append(row_mac == ap_mac)
    return bool(checks) and all(checks)


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
    if not any((station, ap_uuid, ap_mac)):
        return list(rows)
    has_ap_identity = bool(ap_uuid or ap_mac)
    result: list[dict[str, object | None]] = []
    for row in rows:
        if has_ap_identity:
            if ap_uuid and str(row.get("ap_uuid") or "").strip() != ap_uuid:
                continue
            if ap_mac and _normalize_mac_text(row.get("ap_mac")) != ap_mac:
                continue
            result.append(row)
            continue
        row_station = str(row.get("site") or row.get("site_name") or row.get("station") or "").strip().casefold()
        if station and row_station == station:
            result.append(row)
    return result


def _normalize_mac_text(value: object) -> str:
    normalized = normalize_mac(value)
    return normalized.replace(":", "") if normalized else ""


def _int_value(value: object) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _collect_one_target(
    target: TracksideOpticalTarget,
    artifact_dir: Path | None = None,
    cancel_event: Event | None = None,
    repository: DeviceRepository | None = None,
) -> TracksideDeviceCollectionResult:
    started_at = time.monotonic()
    connection = None
    try:
        current_device = target.device
        if repository is not None and target.device_uuid:
            current = repository.get_by_uuid(str(target.device_uuid))
            if current is None:
                return TracksideDeviceCollectionResult(
                    target=target,
                    success=True,
                    skipped_reason="设备已不存在，已自动排除",
                )
            if _is_excluded_device(current):
                return TracksideDeviceCollectionResult(
                    target=target,
                    success=True,
                    skipped_reason=EXCLUDED_WORK_SCOPE_REASON,
                )
            current_device = current
        with netmiko_connection.ssh_connection_context(
            "trackside_optical",
            "collect",
            device_uuid=str(current_device.device_uuid or ""),
        ):
            connection = netmiko_connection.ConnectHandler(
                **build_netmiko_params(choose_connection_target(current_device))
            )  # type: ignore[arg-type]
        adapter = resolve_trackside_switch_adapter(current_device)
        collected = adapter.collect(
            connection,
            artifact_dir=artifact_dir,
            cancel_check=(cancel_event.is_set if cancel_event is not None else None),
            optical_fast_only=(current_device.vendor_key == "zte"),
        )
        raw_log_path = str(artifact_dir or "")
        rows = [
            _result_row(target, row, raw_log_path=raw_log_path)
            for row in collected.optical_modules
        ]
        interface_snapshot_status = (
            collected.interface_snapshot_status
            or ("OK" if collected.interfaces else "EMPTY")
        )
        optical_snapshot_status = (
            collected.optical_snapshot_status
            or ("OK" if rows else "EMPTY")
        )
        warnings = list(collected.warnings)
        if interface_snapshot_status != "OK" and not any(
            "接口摘要状态" in warning for warning in warnings
        ):
            warnings.append(
                f"{collected.vendor or '交换机'} 接口摘要状态为 "
                f"{interface_snapshot_status}，上一份接口状态快照已保留"
            )
        if optical_snapshot_status != "OK" and not any(
            "光模块摘要状态" in warning for warning in warnings
        ):
            warnings.append(
                f"{collected.vendor or '交换机'} 光模块摘要状态为 "
                f"{optical_snapshot_status}，上一份光模块快照已保留"
            )
        return TracksideDeviceCollectionResult(
            target=target,
            success=True,
            raw_log_path=raw_log_path,
            parsed_count=len(rows),
            rows=rows,
            interfaces=collected.interfaces,
            lldp_rows=collected.lldp_neighbors,
            identity=collected.identity,
            vendor=collected.vendor,
            profile_id=collected.profile_id,
            warnings=warnings,
            port_errors=collected.port_errors,
            lldp_status=collected.lldp_status,
            interface_snapshot_status=interface_snapshot_status,
            optical_snapshot_status=optical_snapshot_status,
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )
    except CommandCancelled:
        if cancel_event is not None:
            cancel_event.set()
        return TracksideDeviceCollectionResult(
            target,
            False,
            str(artifact_dir or ""),
            0,
            "采集已取消",
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )
    except CommandOutputLimitExceeded:
        return TracksideDeviceCollectionResult(
            target,
            False,
            str(artifact_dir or ""),
            0,
            "ZTE_OUTPUT_LIMIT_EXCEEDED",
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )
    except Exception as exc:
        message = sanitize_sensitive_text(str(exc), target.device)
        return TracksideDeviceCollectionResult(
            target,
            False,
            str(artifact_dir or ""),
            0,
            message,
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        )
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass


def _snapshot_can_replace(
    result: TracksideDeviceCollectionResult,
    snapshot_type: str,
    current_rows: list[dict[str, object | None]],
    existing_rows: list[dict[str, object | None]],
) -> bool:
    status_field = f"{snapshot_type}_snapshot_status"
    status = str(getattr(result, status_field, "") or "").strip().upper()
    if status != "OK" or not current_rows:
        return False
    if (
        str(result.vendor or "").strip().casefold() == "zte"
        and existing_rows
        and len(current_rows) < len(existing_rows)
    ):
        setattr(result, status_field, "INCOMPLETE")
        label = "接口" if snapshot_type == "interface" else "光模块"
        warning = (
            f"{result.target.name}：本轮{label}摘要仅解析 {len(current_rows)} 条，"
            f"少于上一份 {len(existing_rows)} 条，已拒绝覆盖当前快照"
        )
        if warning not in result.warnings:
            result.warnings.append(warning)
        return False
    return True


def _persist_result(repository: DeviceRepository, ac_repository: AcRepository, result: TracksideDeviceCollectionResult) -> None:
    if result.target.target_type == "SWITCH":
        fact_repository = DeviceFactRepository(repository.database)
        device_uuid = str(result.target.device_uuid or "")
        collect_status = "success" if result.success else "failed"
        collect_run = fact_repository.get_collect_run(result.collect_run_uuid)
        if collect_run is None:
            fact_repository.create_collect_run(
                {
                    "collect_run_uuid": result.collect_run_uuid,
                    "collect_type": "trackside_switch_optical",
                    "status": collect_status,
                    "raw_log_dir": result.raw_log_path or None,
                    "error_message": result.error_message if not result.success else None,
                }
            )
        else:
            fact_repository.update_collect_run_status(
                result.collect_run_uuid,
                collect_status,
                error_message=result.error_message if not result.success else None,
            )
        fact_repository.mark_device_collection_attempt(
            device_uuid,
            result.collect_run_uuid,
            (
                result.raw_log_path
                if result.raw_log_path and Path(result.raw_log_path).exists()
                else ""
            ),
        )
    if not result.success:
        return
    if result.target.target_type == "SWITCH":
        collected_at = _now()
        metadata = {
            "collected_at": collected_at,
            "updated_at": collected_at,
            "collect_run_uuid": result.collect_run_uuid,
            "raw_log_path": result.raw_log_path,
        }
        if result.identity:
            fact_repository.upsert_device_fact(
                {
                    "device_uuid": str(result.target.device_uuid or ""),
                    "model": result.identity.get("model"),
                    "software_version": result.identity.get("software_version"),
                    "vendor": result.identity.get("vendor") or result.vendor,
                    "uptime": result.identity.get("uptime"),
                    **metadata,
                }
            )
        existing_interfaces = fact_repository.list_device_interfaces(device_uuid)
        if _snapshot_can_replace(
            result,
            "interface",
            result.interfaces,
            existing_interfaces,
        ):
            interfaces = [{**row, **metadata} for row in result.interfaces]
            if result.vendor == "ZTE":
                interfaces = merge_interface_vlan_facts(
                    interfaces,
                    None,
                    None,
                    existing_interfaces,
                ).interfaces
            fact_repository.replace_device_interfaces(device_uuid, interfaces)
        existing = fact_repository.list_optical_modules(device_uuid)
        diagnostics = result.rows
        if _snapshot_can_replace(
            result,
            "optical",
            diagnostics,
            existing,
        ):
            if result.vendor == "ZTE":
                diagnostics = merge_zte_optical_snapshot(
                    existing,
                    [
                    {
                        **row,
                        "device_vendor": "ZTE",
                        "status": row.get("module_status")
                        or row.get("optical_alarm_status")
                        or row.get("status"),
                    }
                    for row in result.rows
                    ],
                )
                modules = [{**row, **metadata} for row in diagnostics]
            else:
                modules = merge_existing_optical_modules(
                    existing,
                    diagnostics,
                    [],
                    metadata,
                )
            fact_repository.replace_optical_modules(device_uuid, modules)
        if result.lldp_rows:
            fact_repository.replace_lldp_neighbors(device_uuid, [{**row, **metadata} for row in result.lldp_rows])
        return


def _persistence_error(
    stage: str,
    exc: BaseException,
    db_path: Path,
    operation: str,
    rows_attempted: int,
    started_at: float,
) -> dict[str, object]:
    return {
        "stage": stage,
        "exception_type": type(exc).__name__,
        "message": sanitize_sensitive_text(str(exc), None)[:500],
        "sqlite_errorcode": getattr(exc, "sqlite_errorcode", None),
        "sqlite_errorname": getattr(exc, "sqlite_errorname", None),
        "db_path": str(db_path),
        "operation": operation,
        "rows_attempted": int(rows_attempted),
        "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
    }


def _result_row(
    target: TracksideOpticalTarget,
    parsed: dict[str, object | None],
    *,
    raw_log_path: str = "",
) -> dict[str, object | None]:
    collected_at = _now()
    if target.device.vendor_key == "zte":
        parsed = normalize_zte_optical_record(parsed)
        collector_status = str(parsed.get("status") or "").strip().casefold()
        severity = compute_zte_optical_severity(parsed).severity
    else:
        collector_status = str(parsed.get("status") or "").strip().casefold()
        if collector_status in {
            "no_module",
            "abnormal",
            "unverified",
            "dom_unavailable",
            "offline",
        }:
            severity = collector_status
        else:
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
        "module_status": collector_status,
        "collection_status": "success",
        "tx_status": "unknown",
        "collected_at": collected_at,
        "updated_at": collected_at,
        "raw_log_path": raw_log_path,
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


def _is_excluded_device(device: Device) -> bool:
    return str(device.work_scope_status or "").strip().casefold() == "excluded"


def _write_session_meta(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
