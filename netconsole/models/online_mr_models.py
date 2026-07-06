from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


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
TASK_CONFIG_COLLECT = "config_collect"

CONFIG_COLLECT_COMMANDS: tuple[str, ...] = (
    "screen-length disable",
    "display current-configuration",
    "quit",
)

INIT_COMMANDS: tuple[str, ...] = (
    "screen-length disable",
    "terminal logging level 7",
    "terminal monitor",
    "system-view",
    "user-interface vty 0 31",
    "idle-timeout 1440 0",
    "return",
    "system-view",
    "probe",
    "return",
)

TERMINAL_MONITOR_INIT_COMMANDS: tuple[str, ...] = (
    "screen-length disable",
    "terminal monitor",
    "terminal logging level 7",
)

TASK_COMMANDS: dict[str, tuple[str, ...]] = {
    TASK_MESH_LINK: ("display clock", "display wlan mesh-link"),
    TASK_CHANNEL_BUSY: ("display clock", "display ar5drv 1 channelbusy"),
    TASK_AP_RADIO_STATISTICS: ("display clock", "display ar5drv 1 statistics"),
    TASK_SWITCH_HISTORY: ("display clock", "display wlan mesh-link switch-history"),
    TASK_INTERFACE_RATE: ("display clock", "dis counters rate inbound interface", "dis counters rate outbound interface"),
}


def repeat_command_group(task_type: str, *, interval: int | None = None, radio_id: int = 1) -> tuple[str, ...]:
    delay = max(1, int(interval or 1))
    if task_type == TASK_MESH_LINK:
        return ("display clock", "display wlan mesh-link", f"repeat 2 delay {delay}")
    if task_type == TASK_CHANNEL_BUSY:
        return ("display clock", f"display ar5drv {radio_id} channelbusy", f"repeat 2 delay {delay}")
    if task_type == TASK_AP_RADIO_STATISTICS:
        return ("display clock", f"display ar5drv {radio_id} statistics", f"repeat 2 delay {delay}")
    if task_type == TASK_SWITCH_HISTORY:
        return ("display clock", "display wlan mesh-link switch-history", f"repeat 2 delay {delay}")
    if task_type == TASK_INTERFACE_RATE:
        return (
            "display clock",
            "dis counters rate inbound interface",
            "dis counters rate outbound interface",
            f"repeat 3 delay {delay}",
        )
    raise ValueError(f"unsupported repeat task: {task_type}")


@dataclass
class OnlineMrIntervals:
    mesh_link: int = 1
    channel_busy: int = 9
    ap_radio_statistics: int = 10
    switch_history: int = 300
    interface_rate: int = 2
    fping_interval_ms: int = 10

    def normalized(self) -> "OnlineMrIntervals":
        return OnlineMrIntervals(
            mesh_link=max(1, int(self.mesh_link)),
            channel_busy=max(1, int(self.channel_busy)),
            ap_radio_statistics=max(1, int(self.ap_radio_statistics)),
            switch_history=max(10, int(self.switch_history)),
            interface_rate=max(1, int(self.interface_rate)),
            fping_interval_ms=max(10, int(self.fping_interval_ms)),
        )

    def as_dict(self) -> dict[str, int]:
        normalized = self.normalized()
        return {
            TASK_MESH_LINK: normalized.mesh_link,
            TASK_CHANNEL_BUSY: normalized.channel_busy,
            TASK_AP_RADIO_STATISTICS: normalized.ap_radio_statistics,
            TASK_SWITCH_HISTORY: normalized.switch_history,
            TASK_INTERFACE_RATE: normalized.interface_rate,
            "fping_interval_ms": normalized.fping_interval_ms,
        }


@dataclass
class OnlineMrTaskToggles:
    mesh_link: bool = True
    channel_busy: bool = True
    ap_radio_statistics: bool = True
    switch_history: bool = True
    interface_rate: bool = True

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
        return tasks


@dataclass
class OnlineMrRadioConfig:
    channel_busy_radio: int = 1
    ap_radio_statistics_radio: int = 1

    def normalized(self) -> "OnlineMrRadioConfig":
        return OnlineMrRadioConfig(
            channel_busy_radio=min(3, max(1, int(self.channel_busy_radio))),
            ap_radio_statistics_radio=min(3, max(1, int(self.ap_radio_statistics_radio))),
        )

    def as_dict(self) -> dict[str, int]:
        normalized = self.normalized()
        return {
            "channel_busy_radio": normalized.channel_busy_radio,
            "ap_radio_statistics_radio": normalized.ap_radio_statistics_radio,
        }


@dataclass
class FpingConfig:
    enabled: bool = True
    target: str = ""
    preset_key: str = ""
    preset_name: str = ""
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
    tcp_pacing_enabled: bool = False
    tcp_pacing_mbps: float | None = None
    udp_bitrate_mbps: float | None = None
    udp_report_threshold_mbps: float | None = None
    packet_length: int | None = None
    follow_collection: bool = True
    duration_seconds: int = 0
    tcp_block_size: str | None = None

    def normalized(self) -> "IperfTrafficConfig":
        protocol = str(self.protocol or "TCP").upper()
        direction = str(self.direction or "upload").lower()
        bandwidth = str(self.target_bandwidth or "").strip() or None
        legacy_threshold = _optional_float(self.report_threshold_mbps)
        legacy_bandwidth_mbps = _bandwidth_text_to_mbps(bandwidth)
        tcp_threshold = _optional_float(self.tcp_report_threshold_mbps)
        tcp_pacing = _optional_float(self.tcp_pacing_mbps)
        udp_bitrate = _optional_float(self.udp_bitrate_mbps)
        udp_threshold = _optional_float(self.udp_report_threshold_mbps)
        if protocol == "TCP":
            if tcp_threshold is None:
                tcp_threshold = legacy_threshold if legacy_threshold is not None else legacy_bandwidth_mbps
            bandwidth = f"{tcp_pacing:g}M" if self.tcp_pacing_enabled and tcp_pacing is not None else None
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
            tcp_pacing_enabled=bool(self.tcp_pacing_enabled and tcp_pacing is not None),
            tcp_pacing_mbps=tcp_pacing if self.tcp_pacing_enabled else None,
            udp_bitrate_mbps=udp_bitrate,
            udp_report_threshold_mbps=udp_threshold,
            packet_length=max(1, int(self.packet_length)) if self.packet_length else None,
            follow_collection=bool(self.follow_collection),
            duration_seconds=max(0, int(self.duration_seconds or 0)),
            tcp_block_size=str(self.tcp_block_size or "").strip() or None,
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
