from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.services.online_mr.collection_commands import (
    CONFIG_COLLECT_COMMANDS as _CONFIG_COLLECT_COMMANDS,
    INIT_COMMANDS as _INIT_COMMANDS,
    TASK_COMMANDS as _TASK_COMMANDS,
    TERMINAL_MONITOR_INIT_COMMANDS as _TERMINAL_MONITOR_INIT_COMMANDS,
    repeat_command_group as _repeat_command_group,
)


CONFIG_COLLECT_COMMANDS = _CONFIG_COLLECT_COMMANDS
INIT_COMMANDS = _INIT_COMMANDS
TASK_COMMANDS = _TASK_COMMANDS
TERMINAL_MONITOR_INIT_COMMANDS = _TERMINAL_MONITOR_INIT_COMMANDS
repeat_command_group = _repeat_command_group


STATE_CREATED = "CREATED"
STATE_CONNECTING = "CONNECTING"
STATE_INITIALIZING = "INITIALIZING"
STATE_COLLECTING = "COLLECTING"
STATE_RECONNECTING = "RECONNECTING"
STATE_STOPPING = "STOPPING"
STATE_STOPPED = "STOPPED"
STATE_FORCED_STOPPED = "FORCED_STOPPED"
STATE_FAILED = "FAILED"
STATE_ABORTED = "ABORTED"

ACTIVE_SESSION_STATES = {STATE_COLLECTING, STATE_RECONNECTING, STATE_INITIALIZING}

EVENT_ACTIVE_SWITCH = "ACTIVE_SWITCH"
EVENT_NO_ACTIVE = "NO_ACTIVE"
EVENT_MULTI_ACTIVE = "MULTI_ACTIVE"
EVENT_RECONNECT = "RECONNECT"
EVENT_COMMAND_FAILED = "COMMAND_FAILED"

TASK_MESH_LINK = "mesh_link"
TASK_CHANNEL_BUSY = "channel_busy"
TASK_AP_RADIO_STATISTICS = "ap_radio_statistics"
TASK_SWITCH_HISTORY = "switch_history"
TASK_INTERFACE_RATE = "interface_rate"
TASK_TERMINAL_MONITOR = "terminal_monitor"
TASK_FPING = "fping"
DEFAULT_PING_PRESET_KEY = "pis_high_ping_acceptance"
DEFAULT_PING_PRESET_NAME = "PIS 高频 Ping / 验收"
TASK_CONFIG_COLLECT = "config_collect"
TASK_WIRELESS_STATUS = "wireless_status"

@dataclass
class OnlineMrIntervals:
    mesh_link: int = 1
    channel_busy: int = 9
    ap_radio_statistics: int = 10
    switch_history: int = 300
    interface_rate: int = 2
    fping_interval_ms: int = 10
    wireless_status: int = 3

    def normalized(self) -> "OnlineMrIntervals":
        return OnlineMrIntervals(
            mesh_link=max(1, int(self.mesh_link)),
            channel_busy=max(1, int(self.channel_busy)),
            ap_radio_statistics=max(1, int(self.ap_radio_statistics)),
            switch_history=max(10, int(self.switch_history)),
            interface_rate=max(1, int(self.interface_rate)),
            fping_interval_ms=max(10, int(self.fping_interval_ms)),
            wireless_status=max(1, int(self.wireless_status)),
        )

    def as_dict(self) -> dict[str, int]:
        normalized = self.normalized()
        return {
            TASK_MESH_LINK: normalized.mesh_link,
            TASK_CHANNEL_BUSY: normalized.channel_busy,
            TASK_AP_RADIO_STATISTICS: normalized.ap_radio_statistics,
            TASK_SWITCH_HISTORY: normalized.switch_history,
            TASK_INTERFACE_RATE: normalized.interface_rate,
            TASK_WIRELESS_STATUS: normalized.wireless_status,
            "fping_interval_ms": normalized.fping_interval_ms,
        }


@dataclass
class OnlineMrTaskToggles:
    mesh_link: bool = True
    channel_busy: bool = True
    ap_radio_statistics: bool = True
    switch_history: bool = True
    interface_rate: bool = True
    wireless_status: bool = False

    def enabled_tasks(self) -> set[str]:
        tasks: set[str] = set()
        if self.mesh_link:
            tasks.add(TASK_MESH_LINK)
        if self.channel_busy:
            tasks.add(TASK_CHANNEL_BUSY)
        if self.ap_radio_statistics:
            tasks.add(TASK_AP_RADIO_STATISTICS)
        if self.switch_history:
            tasks.add(TASK_SWITCH_HISTORY)
        if self.interface_rate:
            tasks.add(TASK_INTERFACE_RATE)
        if self.wireless_status:
            tasks.add(TASK_WIRELESS_STATUS)
        return tasks


@dataclass
class OnlineMrRadioConfig:
    radio_mode: str = ""
    unified_radio_id: int | None = None
    collector_radio_ids: dict[str, int] = field(default_factory=dict)
    channel_busy_radio: int = 1
    ap_radio_statistics_radio: int = 1
    wireless_status_radio: int = 1

    def normalized(self) -> "OnlineMrRadioConfig":
        collector_values = {
            "channel_busy": self.channel_busy_radio,
            "ap_radio_statistics": self.ap_radio_statistics_radio,
            "wireless_status": self.wireless_status_radio,
            **(self.collector_radio_ids or {}),
        }
        channel_busy = self._bounded(collector_values.get("channel_busy", 1))
        ap_radio_statistics = self._bounded(collector_values.get("ap_radio_statistics", 1))
        wireless_status = self._bounded(collector_values.get("wireless_status", 1))
        requested_mode = str(self.radio_mode or "").strip().lower()
        if requested_mode == "unified" or (not requested_mode and self.unified_radio_id not in (None, "")):
            unified = self._bounded(self.unified_radio_id or channel_busy)
            channel_busy = ap_radio_statistics = wireless_status = unified
            mode = "unified"
        elif requested_mode == "per_collector":
            unified = channel_busy if channel_busy == ap_radio_statistics == wireless_status else None
            mode = "per_collector"
        else:
            unified = channel_busy if channel_busy == ap_radio_statistics == wireless_status else None
            mode = "unified" if unified is not None else "per_collector"
        return OnlineMrRadioConfig(
            radio_mode=mode,
            unified_radio_id=unified or 1,
            collector_radio_ids={
                "channel_busy": channel_busy,
                "ap_radio_statistics": ap_radio_statistics,
                "wireless_status": wireless_status,
            },
            channel_busy_radio=channel_busy,
            ap_radio_statistics_radio=ap_radio_statistics,
            wireless_status_radio=wireless_status,
        )

    @staticmethod
    def _bounded(value: object) -> int:
        try:
            return min(3, max(1, int(value or 1)))
        except (TypeError, ValueError):
            return 1

    def as_dict(self) -> dict[str, object]:
        normalized = self.normalized()
        return {
            "radio_mode": normalized.radio_mode,
            "unified_radio_id": normalized.unified_radio_id,
            "collector_radio_ids": dict(normalized.collector_radio_ids),
            "channel_busy_radio": normalized.channel_busy_radio,
            "ap_radio_statistics_radio": normalized.ap_radio_statistics_radio,
            "wireless_status_radio": normalized.wireless_status_radio,
        }


@dataclass
class FpingConfig:
    enabled: bool = True
    target: str = ""
    preset_key: str = DEFAULT_PING_PRESET_KEY
    preset_name: str = DEFAULT_PING_PRESET_NAME
    packet_size: int = 64
    interval_ms: int = 10
    loss_threshold_ms: int = 100
    loss_warn_percent: float = 0.7
    latency_warn_ms: int = 100
    continuous: bool = True
    write_file: bool = True

    @staticmethod
    def _int_value(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _float_value(value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def normalized(self) -> "FpingConfig":
        return FpingConfig(
            enabled=bool(self.enabled),
            target=str(self.target).strip(),
            preset_key=str(self.preset_key or "").strip(),
            preset_name=str(self.preset_name or "").strip(),
            packet_size=min(65535, max(1, self._int_value(self.packet_size, 64))),
            interval_ms=min(60000, max(1, self._int_value(self.interval_ms, 10))),
            loss_threshold_ms=min(60000, max(1, self._int_value(self.loss_threshold_ms, 100))),
            loss_warn_percent=min(100.0, max(0.0, self._float_value(self.loss_warn_percent, 0.7))),
            latency_warn_ms=min(60000, max(1, self._int_value(self.latency_warn_ms, 100))),
            continuous=bool(self.continuous),
            write_file=bool(self.write_file),
        )

    def as_dict(self) -> dict[str, object]:
        normalized = self.normalized()
        return {
            "enabled": normalized.enabled,
            "target": normalized.target,
            "preset_key": normalized.preset_key,
            "preset_name": normalized.preset_name,
            "packet_size": normalized.packet_size,
            "packet_size_bytes": normalized.packet_size,
            "interval_ms": normalized.interval_ms,
            "loss_threshold_ms": normalized.loss_threshold_ms,
            "timeout_ms": normalized.loss_threshold_ms,
            "loss_warn_percent": normalized.loss_warn_percent,
            "latency_warn_ms": normalized.latency_warn_ms,
            "continuous": normalized.continuous,
            "write_file": normalized.write_file,
        }


@dataclass
class IperfTrafficConfig:
    enabled: bool = False
    server_ip: str = ""
    port: int = 5201
    preset_key: str = ""
    preset_name: str = ""
    test_type: str = ""
    deployment_mode: str = "ground_server_train_client"
    business_direction: str = "train_to_ground"
    protocol: str = "TCP"
    direction: str = "upload"
    parallel: int = 1
    interval_seconds: int = 1
    target_bandwidth: str | None = None
    report_threshold_mbps: float | None = None
    tcp_report_threshold_mbps: float | None = None
    tcp_rate_limit_mbps: float | None = None
    tcp_pacing_enabled: bool = False
    tcp_pacing_mbps: float | None = None
    udp_bitrate_mbps: float | None = None
    udp_report_threshold_mbps: float | None = None
    packet_length: int | None = None
    follow_collection: bool = True
    duration_seconds: int = 0
    tcp_block_size: str | None = None
    debug_output_enabled: bool = True

    def normalized(self) -> "IperfTrafficConfig":
        protocol = str(self.protocol or "TCP").upper()
        direction = str(self.direction or "upload").lower()
        bandwidth = str(self.target_bandwidth or "").strip() or None
        legacy_threshold = _optional_float(self.report_threshold_mbps)
        legacy_bandwidth_mbps = _bandwidth_text_to_mbps(bandwidth)
        tcp_threshold = _optional_float(self.tcp_report_threshold_mbps)
        tcp_rate_limit = _optional_float(self.tcp_rate_limit_mbps)
        tcp_pacing = _optional_float(self.tcp_pacing_mbps)
        if tcp_rate_limit is None and self.tcp_pacing_enabled:
            tcp_rate_limit = tcp_pacing
        udp_bitrate = _optional_float(self.udp_bitrate_mbps)
        udp_threshold = _optional_float(self.udp_report_threshold_mbps)
        if protocol == "TCP":
            if tcp_threshold is None:
                tcp_threshold = legacy_threshold if legacy_threshold is not None else legacy_bandwidth_mbps
            bandwidth = f"{tcp_rate_limit:g}M" if tcp_rate_limit is not None and tcp_rate_limit > 0 else None
        if protocol == "UDP" and not bandwidth and udp_bitrate is not None:
            bandwidth = f"{udp_bitrate:g}M"
        if protocol == "UDP" and not bandwidth:
            bandwidth = "10M"
            if udp_bitrate is None:
                udp_bitrate = 10.0
        if protocol == "UDP" and udp_bitrate is None:
            udp_bitrate = _bandwidth_text_to_mbps(bandwidth)
        if protocol == "UDP" and udp_threshold is None:
            udp_threshold = legacy_threshold if legacy_threshold is not None else udp_bitrate
        report_threshold = tcp_threshold if protocol == "TCP" else udp_threshold
        return IperfTrafficConfig(
            enabled=bool(self.enabled),
            server_ip=str(self.server_ip or "").strip(),
            port=max(1, min(65535, int(self.port or 5201))),
            preset_key=str(self.preset_key or "").strip(),
            preset_name=str(self.preset_name or "").strip(),
            test_type=str(self.test_type or "").strip(),
            deployment_mode=str(self.deployment_mode or "ground_server_train_client").strip(),
            business_direction=str(self.business_direction or "train_to_ground").strip(),
            protocol=protocol if protocol in {"TCP", "UDP"} else "TCP",
            direction=direction if direction in {"upload", "download", "bidirectional"} else "upload",
            parallel=max(1, int(self.parallel or 1)),
            interval_seconds=max(1, int(self.interval_seconds or 1)),
            target_bandwidth=bandwidth,
            report_threshold_mbps=report_threshold,
            tcp_report_threshold_mbps=tcp_threshold,
            tcp_rate_limit_mbps=tcp_rate_limit,
            tcp_pacing_enabled=bool(tcp_rate_limit is not None and tcp_rate_limit > 0),
            tcp_pacing_mbps=tcp_rate_limit if tcp_rate_limit is not None and tcp_rate_limit > 0 else None,
            udp_bitrate_mbps=udp_bitrate,
            udp_report_threshold_mbps=udp_threshold,
            packet_length=max(1, int(self.packet_length)) if self.packet_length else None,
            follow_collection=bool(self.follow_collection),
            duration_seconds=max(0, int(self.duration_seconds or 0)),
            tcp_block_size=str(self.tcp_block_size or "").strip() or None,
            debug_output_enabled=bool(self.debug_output_enabled),
        )

    def as_dict(self) -> dict[str, object]:
        normalized = self.normalized()
        return dict(normalized.__dict__)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bandwidth_text_to_mbps(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    unit = text[-1:].upper()
    number_text = text[:-1] if unit in {"K", "M", "G"} else text
    try:
        number = float(number_text)
    except ValueError:
        return None
    if unit == "K":
        return number / 1000.0
    if unit == "G":
        return number * 1000.0
    return number


@dataclass
class OnlineMrConnectionConfig:
    site: str
    mr_id: str
    mr_name: str
    safe_mr_name: str
    device_id: int | None
    device_name: str
    host: str
    protocol: str = "SSH"
    port: int = 22
    username: str = ""
    password: str = ""
    intervals: OnlineMrIntervals = field(default_factory=OnlineMrIntervals)
    tasks: OnlineMrTaskToggles = field(default_factory=OnlineMrTaskToggles)
    radio: OnlineMrRadioConfig = field(default_factory=OnlineMrRadioConfig)
    fping: FpingConfig = field(default_factory=FpingConfig)
    iperf: IperfTrafficConfig = field(default_factory=IperfTrafficConfig)
    auto_reconnect: bool = True
    reconnect_interval: int = 5
    max_reconnect: int | None = None
    command_timeout: int = 15
    duration_minutes: int | None = None
    connection_targets: tuple[object, ...] = field(default_factory=tuple)
    connection_method: str = ""
    collect_config_on_start: bool = False
    fping_required_before_collection: bool = False


@dataclass
class OnlineMrStats:
    mesh_link_success: int = 0
    mesh_link_failed: int = 0
    channel_busy_success: int = 0
    channel_busy_failed: int = 0
    ap_radio_statistics_success: int = 0
    ap_radio_statistics_failed: int = 0
    switch_history_success: int = 0
    switch_history_failed: int = 0
    interface_rate_success: int = 0
    interface_rate_failed: int = 0
    wireless_status_success: int = 0
    wireless_status_failed: int = 0
    fping_samples: int = 0
    fping_lost: int = 0
    iperf_samples: int = 0
    iperf_retransmits: int = 0
    reconnect_count: int = 0
    parse_failed: int = 0
    command_failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class OnlineMrSessionMeta:
    session_id: str
    site: str
    mr_id: str
    mr_name: str
    device_id: int | None
    device_name: str
    host: str
    protocol: str
    port: int
    started_at: datetime
    connection_method: str = ""
    ended_at: datetime | None = None
    status: str = STATE_CREATED
    intervals: dict[str, int] = field(default_factory=dict)
    radio: dict[str, int] = field(default_factory=dict)
    fping: dict[str, object] = field(default_factory=dict)
    iperf: dict[str, object] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)
    session_dir: Path | None = None
    session_type: str = "realtime"
    config_collect_enabled: bool = False
    config_collect_status: str = "skipped"
    config_file_path: str = ""
    config_error: str | None = None
    raw_log_path: str = ""
    init: dict[str, Any] = field(default_factory=dict)
    configured_duration_minutes: int | None = None
    duration_minutes: float | None = None
    stop_reason: str = ""
    force_stopped: bool = False
    traffic_summary: dict[str, Any] = field(default_factory=dict)
    startup_timeline: list[dict[str, Any]] = field(default_factory=list)
    finalization_warnings: list[str] = field(default_factory=list)
    finalization_complete: bool = False
    package_available: bool = False
    data_integrity: str = "unknown"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "site": self.site,
            "mr_id": self.mr_id,
            "mr_name": self.mr_name,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "host": self.host,
            "protocol": self.protocol,
            "port": self.port,
            "connection_method": self.connection_method,
            "started_at": self.started_at.isoformat(sep=" ", timespec="seconds"),
            "ended_at": self.ended_at.isoformat(sep=" ", timespec="seconds") if self.ended_at else None,
            "status": self.status,
            "intervals": self.intervals,
            "radio": self.radio,
            "fping": self.fping,
            "iperf": self.iperf,
            "stats": self.stats,
            "session_type": self.session_type,
            "config_collect_enabled": self.config_collect_enabled,
            "config_collect_status": self.config_collect_status,
            "config_file_path": self.config_file_path,
            "config_error": self.config_error,
            "raw_log_path": self.raw_log_path,
            "init": self.init,
            "configured_duration_minutes": self.configured_duration_minutes,
            "duration_minutes": self.duration_minutes,
            "stop_reason": self.stop_reason,
            "force_stopped": self.force_stopped,
            "traffic_summary": self.traffic_summary,
            "startup_timeline": self.startup_timeline,
            "finalization_warnings": self.finalization_warnings,
            "finalization_complete": self.finalization_complete,
            "package_available": self.package_available,
            "data_integrity": self.data_integrity,
        }


@dataclass
class OnlineMrSnapshot:
    session_id: str
    status: str
    device_id: int | None = None
    device_name: str = ""
    host: str = ""
    active_peer: str = ""
    peer_name: str = ""
    peer_station: str = ""
    peer_site: str = ""
    local_rssi: int | None = None
    peer_rssi: int | None = None
    local_tx_busy: int | None = None
    local_rx_busy: int | None = None
    latest_switch_time: str = ""
    collected_count: int = 0
    failed_count: int = 0
    reconnect_count: int = 0
    uptime_seconds: int = 0
    last_collection_time: str = ""
    iperf_mbps: float | None = None
    iperf_retransmits: int | None = None
    iperf_status: str = ""
    config_collect_status: str = ""
    config_file_path: str = ""


class OnlineMrConnection:
    def send_command(self, command: str, timeout: int) -> str:
        raise NotImplementedError

    def run_repeat_stream(self, commands, raw_path, stop_event, timeout: int, line_callback=None) -> None:
        raise NotImplementedError

    def run_terminal_monitor_stream(self, commands, stop_event, timeout: int, line_callback=None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
