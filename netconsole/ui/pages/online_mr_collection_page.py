from __future__ import annotations

import re
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import Device
from netconsole.models.online_mr_models import FpingConfig, IperfTrafficConfig, OnlineMrConnectionConfig, OnlineMrIntervals, OnlineMrRadioConfig, OnlineMrSnapshot
from netconsole.services.fping_v5 import detect_fping_version, find_fping_tool
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, build_iperf_client_args, normalize_bandwidth_text
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.online_mr_collector import OnlineMrCollectionManager
from netconsole.services.online_mr_session_store import OnlineMrSession, OnlineMrSessionStore
from netconsole.services.online_mr.core.event_model import EVENT_BUSY_SAMPLE, EVENT_IPERF3_SAMPLE, EVENT_MESH_SAMPLE, OnlineMrEvent
from netconsole.services.online_mr.core.realtime_model import PingConfig, RealtimeMRState, build_realtime_state
from netconsole.services.online_mr.db.event_writer import EventWriter
from netconsole.services.online_mr.diagnosis_engine import OnlineMrDiagnosisEngine
from netconsole.services.online_mr.event_bus import OnlineMrEventBus
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine
from netconsole.services.online_mr.realtime.sliding_window_buffer import SlidingWindowBuffer
from netconsole.services.online_mr.workers.fping_v5_worker import FpingV5ProbeWorker
from netconsole.services.ap_radio_mapping_service import ApRadioMappingService
from netconsole.ui.iperf_worker import IperfProcessWorker
from netconsole.ui.online_mr_collector_worker import OnlineMrCollectorWorker
from netconsole.ui.online_mr_parse_worker import OnlineMrParseWorker
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.no_wheel import NoWheelComboBox, NoWheelSpinBox


TABLE_WIDTH_KEYS = {
    "session_summary": "online_mr/table_widths/session_summary",
    "mesh_link": "online_mr/table_widths/mesh_link",
    "channel_busy": "online_mr/table_widths/channel_busy",
    "statistics": "online_mr/table_widths/statistics",
    "switch_history": "online_mr/table_widths/switch_history",
    "interface_rate": "online_mr/table_widths/interface_rate",
    "iperf": "online_mr/table_widths/iperf",
    "history_sessions": "online_mr/table_widths/history_sessions",
}

STATUS_I18N_KEYS = {
    "CREATED": "online_mr.status_created",
    "CONNECTING": "online_mr.status_connecting",
    "INITIALIZING": "online_mr.status_initializing",
    "COLLECTING": "online_mr.status_collecting",
    "RECONNECTING": "online_mr.status_reconnecting",
    "STOPPING": "online_mr.status_stopping",
    "STOPPED": "online_mr.status_stopped",
    "FAILED": "online_mr.status_failed",
    "ABORTED": "online_mr.status_aborted",
}

SUMMARY_COL_DEVICE_NAME = 0
SUMMARY_COL_HOST = 1
SUMMARY_COL_STATUS = 2
SUMMARY_COL_ACTIVE_PEER = 3
SUMMARY_COL_MR_RSSI = 4
SUMMARY_COL_PEER_SITE = 5
SUMMARY_COL_CTL_BUSY = 6
SUMMARY_COL_TX_BUSY = 7
SUMMARY_COL_RX_BUSY = 8
SUMMARY_COL_PING_LOSS = 9
SUMMARY_COL_PING_LATENCY = 10
SUMMARY_COL_COLLECTED = 11
SUMMARY_COL_FAILED = 12
SUMMARY_COL_RECONNECTS = 13
SUMMARY_COL_LAST_COLLECTION = 14
SUMMARY_COL_IPERF_MBPS = 15
SUMMARY_COL_IPERF_RETRANS = 16
SUMMARY_COL_IPERF_STATUS = 17
SUMMARY_COL_SESSION = 18
SUMMARY_COL_DEVICE_ID = 19


class OnlineMrUiThrottle:
    def __init__(self, interval_ms: int = 300) -> None:
        self.interval_ms = interval_ms
        self.pending_snapshot: OnlineMrSnapshot | None = None
        self.flush_count = 0

    def enqueue(self, snapshot: OnlineMrSnapshot) -> None:
        self.pending_snapshot = snapshot

    def flush(self) -> OnlineMrSnapshot | None:
        snapshot = self.pending_snapshot
        self.pending_snapshot = None
        if snapshot is not None:
            self.flush_count += 1
        return snapshot


class NoWheelValueChangeFilter(QObject):
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            event.ignore()
            return True
        return super().eventFilter(obj, event)


def normalize_device_type(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def is_fat_ap_device(value: str | None) -> bool:
    return normalize_device_type(value) in {"FATAP", "CLOUDAP"}


def safe_device_folder_name(device: Device) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(device.name or "device")).strip(" ._") or "device"
    return f"{name}__{device.id}"


def connection_fields_from_device(device: Device) -> tuple[str, int, str, str]:
    if device.ssh_enabled:
        return "SSH", int(device.ssh_port or 22), str(device.ssh_username or "").strip(), str(device.ssh_password or "")
    if device.telnet_enabled:
        return "Telnet", int(device.telnet_port or 23), str(device.telnet_username or "").strip(), str(device.telnet_password or "")
    return "", 0, "", ""


def natural_device_sort_key(device: Device) -> tuple[list[object], str, int]:
    parts: list[object] = []
    for part in re.split(r"(\d+)", str(device.name or "")):
        parts.append(int(part) if part.isdigit() else part.casefold())
    return parts, str(device.primary_address or ""), int(device.id or 0)


class OnlineMrCollectionPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.settings = SettingsStore(paths)
        self.store = OnlineMrSessionStore(paths)
        self.manager = OnlineMrCollectionManager(max_concurrent=2)
        self.devices: list[Device] = []
        self.filtered_devices: list[Device] = []
        self.device_groups: dict[int, str] = {}
        self.workers: dict[str, OnlineMrCollectorWorker] = {}
        self.fping_workers: dict[str, FpingV5ProbeWorker] = {}
        self.iperf_workers: dict[str, IperfProcessWorker] = {}
        self.session_dirs: dict[str, Path] = {}
        self.session_to_device_id: dict[str, int] = {}
        self.workers_by_device_id: dict[int, OnlineMrCollectorWorker] = {}
        self.fping_workers_by_device_id: dict[int, FpingV5ProbeWorker] = {}
        self.iperf_workers_by_device_id: dict[int, IperfProcessWorker] = {}
        self.latest_iperf_by_device_id: dict[int, dict[str, object]] = {}
        self.event_buses: dict[str, OnlineMrEventBus] = {}
        self.realtime_buffers: dict[str, SlidingWindowBuffer] = {}
        self.diagnosis_engines: dict[str, OnlineMrDiagnosisEngine] = {}
        self.event_parsers: dict[str, EventParserEngine] = {}
        self._raw_tail_offsets: dict[tuple[str, str], int] = {}
        self.realtime_states_by_device_id: dict[int, RealtimeMRState] = {}
        self.peer_station_cache: dict[str, dict[str, object]] = {}
        self.peer_mapping_service = ApRadioMappingService(site_name, paths)
        self.parse_worker: OnlineMrParseWorker | None = None
        self.last_session_dir_by_device_id: dict[int, Path] = {}
        self.throttle = OnlineMrUiThrottle(300)
        self._updating_device_checks = False
        self._first_show_refreshed = False
        self._history_refresh_pending = False
        self._tool_status_loaded = False
        self._device_refresh_pending = False
        self._last_realtime_parse_at: dict[str, float] = {}
        self.realtime_parse_worker: OnlineMrParseWorker | None = None
        self._stale_sessions_checked_sites: set[str] = set()
        self._view_device_user_selected = False

        self.site_label = QLabel()
        self.available_device_count_label = QLabel()
        self.selected_device_count_label = QLabel()
        self.running_count_label = QLabel()
        self.available_metric_label = QLabel()
        self.selected_metric_label = QLabel()
        self.running_metric_label = QLabel()
        self.filter_hint_label = QLabel()
        self.device_table = QTableWidget(0, 9)
        self.view_device_combo = QComboBox()
        self.status_label = QLabel()
        self.status_value = "STOPPED"
        self.start_button = QPushButton()
        self.stop_selected_button = QPushButton()
        self.stop_all_button = QPushButton()
        self.open_button = QPushButton()
        self.refresh_devices_button = QPushButton()
        self.parse_session_button = QPushButton()

        self.mesh_interval = self._interval_spin(1, 3600, 1)
        self.channel_interval = self._interval_spin(1, 3600, 9)
        self.statistics_interval = self._interval_spin(1, 3600, 10)
        self.switch_interval = self._interval_spin(10, 86400, 300)
        self.interface_rate_interval = self._interval_spin(1, 3600, 2)
        self.radio_port = self._radio_combo()
        self.channel_radio = self.radio_port
        self.statistics_radio = self.radio_port
        self.auto_reconnect_check = QCheckBox()
        self.auto_reconnect_check.setChecked(True)
        self.reconnect_interval = self._interval_spin(1, 3600, 5)
        self.max_reconnect = self._interval_spin(0, 9999, 0)
        self.duration_minutes = self._interval_spin(0, 10080, 0)
        self.enable_fping_check = QCheckBox()
        self.enable_fping_check.setChecked(True)
        self.fping_target_edit = QLineEdit()
        self.fping_packet_size = self._interval_spin(1, 1472, 64)
        self.fping_interval_ms = self._interval_spin(10, 60000, 10)
        self.fping_loss_threshold_ms = self._interval_spin(1, 60000, 100)
        self.fping_tool_label = QLabel()
        self.fping_tool_label.setWordWrap(True)
        self.fping_device_combo_1 = NoWheelComboBox()
        self.fping_device_combo_2 = NoWheelComboBox()
        self.fping_target_label_1 = QLineEdit()
        self.fping_target_label_2 = QLineEdit()
        for target_label in (self.fping_target_label_1, self.fping_target_label_2):
            target_label.setReadOnly(True)
            target_label.setPlaceholderText("-")
        self.fping_status_label_1 = QLabel("Ping 1: idle")
        self.fping_status_label_2 = QLabel("Ping 2: idle")
        self.collect_progress_1 = QProgressBar()
        self.collect_progress_2 = QProgressBar()
        self.collect_status_label_1 = QLabel("Device 1: idle")
        self.collect_status_label_2 = QLabel("Device 2: idle")
        self.collect_status_box = QGroupBox("实时采集状态")
        self.collect_card_1 = QGroupBox("设备 1")
        self.collect_card_2 = QGroupBox("设备 2")
        self.enable_iperf_check = QCheckBox()
        self.iperf_server_edit = QLineEdit()
        self.iperf_port_spin = self._no_wheel_spin(1, 65535, 5201)
        self.iperf_protocol_combo = NoWheelComboBox()
        self.iperf_protocol_combo.addItems(["TCP", "UDP"])
        self.iperf_direction_combo = NoWheelComboBox()
        self.iperf_parallel_spin = self._no_wheel_spin(1, 128, 1)
        self.iperf_interval_spin = self._no_wheel_spin(1, 3600, 1)
        self.iperf_bandwidth_edit = QLineEdit()
        self.iperf_bandwidth_edit.setValidator(QDoubleValidator(0.0, 999999.0, 3, self))
        self.iperf_bandwidth_unit_combo = NoWheelComboBox()
        self.iperf_bandwidth_unit_combo.addItems(["K", "M", "G"])
        self.iperf_bandwidth_unit_combo.setCurrentText("M")
        self.iperf_bandwidth_hint_label = QLabel()
        self.iperf_bandwidth_hint_label.setWordWrap(True)
        self.iperf_follow_check = QCheckBox()
        self.iperf_follow_check.setChecked(True)
        self.iperf_duration_spin = self._no_wheel_spin(0, 86400, 0)
        self.iperf_tool_label = QLabel()
        self.iperf_tool_label.setWordWrap(True)
        self._no_wheel_filter = NoWheelValueChangeFilter(self)

        self.summary_table = QTableWidget(0, 20)
        self.mesh_table = QTableWidget(0, 12)
        self.channel_table = QTableWidget(0, 5)
        self.events_table = QTableWidget(0, 6)
        self.statistics_text = QTextEdit()
        self.switch_history_text = QTextEdit()
        self.interface_rate_table = QTableWidget(0, 6)
        self.iperf_table = QTableWidget(0, 5)
        self.diagnosis_table = QTableWidget(0, 14)
        self.history_table = QTableWidget(0, 9)
        for table in (self.summary_table, self.mesh_table, self.channel_table, self.events_table, self.interface_rate_table, self.iperf_table, self.diagnosis_table, self.history_table):
            configure_readonly_table(table)
            self._configure_online_table(table)
        self.statistics_text.setReadOnly(True)
        self.switch_history_text.setReadOnly(True)
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.tabs = QTabWidget()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(self.throttle.interval_ms)
        self.refresh_timer.timeout.connect(self._flush_snapshot)
        self.connection_box: QGroupBox | None = None
        self.period_box: QGroupBox | None = None
        self.radio_box: QGroupBox | None = None
        self.ping_box: QGroupBox | None = None
        self.iperf_box: QGroupBox | None = None
        self.advanced_box: QGroupBox | None = None
        self.advanced_toggle = QToolButton()
        self.advanced_summary_label = QLabel()
        self.advanced_detail = QWidget()
        self.labels: dict[str, QLabel] = {}
        self.text_labels: list[tuple[str, QLabel]] = []

        self._build_ui()
        self._connect_signals()
        self._refresh_top_metrics()
        self.refresh_timer.start()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.set_site(site_name)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self._first_show_refreshed = False
        self._schedule_device_refresh(refresh_tools=False)

    def first_show_refresh(self) -> None:
        if self.site_name not in self._stale_sessions_checked_sites:
            self._stale_sessions_checked_sites.add(self.site_name)
            QTimer.singleShot(0, lambda site_name=self.site_name: self.store.mark_stale_sessions_aborted(site_name))
        self._first_show_refreshed = True
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self.filter_hint_label.setText(self.i18n.t("app.loading"))
        self._schedule_device_refresh(refresh_tools=False)

    def refresh_all(self, defer_heavy: bool = False, refresh_tools: bool = False) -> None:
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self.devices = self.repository.list()
        self._load_device_groups()
        self._fill_devices()
        self._fill_view_devices()
        if defer_heavy:
            self._schedule_history_refresh(refresh_tools=refresh_tools)
        else:
            self._fill_history()
            self._refresh_tool_status_once(force=refresh_tools)
        self._update_action_state()
        self._refresh_top_metrics()

    def _schedule_device_refresh(self, refresh_tools: bool = False) -> None:
        if self._device_refresh_pending:
            return
        self._device_refresh_pending = True

        def run() -> None:
            self._device_refresh_pending = False
            self.refresh_all(defer_heavy=True, refresh_tools=refresh_tools)

        QTimer.singleShot(0, run)

    def retranslate(self) -> None:
        if self.connection_box:
            self.connection_box.setTitle(self.i18n.t("online_mr.connection"))
        if self.period_box:
            self.period_box.setTitle("采集参数")
        if self.radio_box and self.radio_box is not self.period_box:
            self.radio_box.setTitle(self.i18n.t("online_mr.radio_params"))
        if self.ping_box:
            self.ping_box.setTitle(self.i18n.t("online_mr.high_freq_ping"))
        if self.iperf_box:
            self.iperf_box.setTitle(self.i18n.t("online_mr.traffic_test"))
        if self.advanced_box:
            self.advanced_box.setTitle(self.i18n.t("online_mr.advanced_params"))
        for key, label in self.labels.items():
            label.setText(self.i18n.t(key))
        for key, label in self.text_labels:
            label.setText(self.i18n.t(key))
        self.start_button.setText(self.i18n.t("online_mr.start"))
        self.stop_selected_button.setText(self.i18n.t("online_mr.stop_selected"))
        self.stop_all_button.setText(self.i18n.t("online_mr.stop_all"))
        self.open_button.setText(self.i18n.t("online_mr.open_session_dir"))
        self.refresh_devices_button.setText(self.i18n.t("online_mr.refresh_devices"))
        self.parse_session_button.setText(self.i18n.t("online_mr.parse_collection_data"))
        self.auto_reconnect_check.setText(self.i18n.t("online_mr.auto_reconnect"))
        self.enable_fping_check.setText(self.i18n.t("online_mr.high_freq_ping"))
        self.enable_iperf_check.setText(self.i18n.t("online_mr.enable_traffic_test"))
        self.iperf_follow_check.setText(self.i18n.t("iperf.follow_collection"))
        self.iperf_bandwidth_hint_label.setText(self.i18n.t("iperf.tcp_auto_bandwidth_hint"))
        bandwidth_tooltip = self.i18n.t("iperf.target_bandwidth_tooltip")
        self.iperf_bandwidth_edit.setToolTip(bandwidth_tooltip)
        self.iperf_bandwidth_unit_combo.setToolTip(self.i18n.t("iperf.bandwidth_unit"))
        for widget in (
            self.iperf_port_spin,
            self.iperf_protocol_combo,
            self.iperf_direction_combo,
            self.iperf_parallel_spin,
            self.iperf_interval_spin,
            self.iperf_bandwidth_unit_combo,
            self.iperf_duration_spin,
        ):
            widget.setToolTip(self.i18n.t("iperf.no_wheel_hint"))
        self._fill_iperf_direction_combo()
        self._set_status(self.status_value)
        self._refresh_top_metrics()
        self._update_advanced_summary()
        self.device_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("online_mr.select"),
                self.i18n.t("online_mr.device_name"),
                self.i18n.t("online_mr.host"),
                self.i18n.t("online_mr.protocol"),
                self.i18n.t("online_mr.port"),
                self.i18n.t("online_mr.username"),
                self.i18n.t("online_mr.vehicle_group"),
                self.i18n.t("online_mr.device_type"),
                self.i18n.t("online_mr.status"),
            ]
        )
        self.summary_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("online_mr.device_name"),
                self.i18n.t("online_mr.host"),
                self.i18n.t("online_mr.status"),
                self.i18n.t("online_mr.active_peer"),
                "MR RSSI",
                "归属站点",
                "CtlBusy(%)",
                "TxBusy(%)",
                "RxBusy(%)",
                self.i18n.t("online_mr.ping_loss_rate"),
                self.i18n.t("online_mr.latest_ping_latency"),
                self.i18n.t("online_mr.collected"),
                self.i18n.t("online_mr.failed"),
                self.i18n.t("online_mr.reconnects"),
                self.i18n.t("online_mr.last_collection"),
                "IPERF Mbps",
                self.i18n.t("iperf.retransmits"),
                self.i18n.t("iperf.status"),
                self.i18n.t("online_mr.session"),
                self.i18n.t("online_mr.device_id"),
            ]
        )
        self.mesh_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), self.i18n.t("online_mr.radio_id"), self.i18n.t("online_mr.state"), "PeerMac", "MR RSSI", "Peer RSSI", self.i18n.t("online_mr.mr_signal"), self.i18n.t("online_mr.peer_signal"), "TxBusy", "RxBusy", self.i18n.t("online_mr.rate"), "Retry/Err"])
        self.channel_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), self.i18n.t("online_mr.radio_id"), "TxBusy", "RxBusy", self.i18n.t("online_mr.raw")])
        self.events_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), self.i18n.t("online_mr.type"), self.i18n.t("online_mr.radio_id"), self.i18n.t("online_mr.from_peer"), self.i18n.t("online_mr.to_peer"), self.i18n.t("online_mr.details")])
        self.interface_rate_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), self.i18n.t("online_mr.direction"), self.i18n.t("online_mr.interface"), self.i18n.t("online_mr.usage_percent"), "PPS", self.i18n.t("online_mr.raw")])
        self.iperf_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), "Mbps", self.i18n.t("iperf.retransmits"), self.i18n.t("iperf.transfer"), self.i18n.t("online_mr.raw")])
        self.diagnosis_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("online_mr.start_time"),
                self.i18n.t("online_mr.end_time"),
                self.i18n.t("online_mr.active_peer"),
                self.i18n.t("mesh_analysis.mr_rssi"),
                self.i18n.t("mesh_analysis.min_rssi"),
                self.i18n.t("online_mr.ping_loss_rate"),
                self.i18n.t("online_mr.latest_ping_latency"),
                "IPERF Avg Mbps",
                "IPERF Max Mbps",
                "Avg TxBusy",
                "Avg RxBusy",
                "In PPS",
                "Out PPS",
                self.i18n.t("online_mr.status"),
            ]
        )
        self.history_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.session"), self.i18n.t("online_mr.start_time"), self.i18n.t("online_mr.end_time"), self.i18n.t("online_mr.status"), self.i18n.t("online_mr.mesh_ok_fail"), self.i18n.t("online_mr.busy_ok_fail"), self.i18n.t("online_mr.reconnects"), "MR", self.i18n.t("online_mr.directory")])
        self.tabs.setTabText(0, self.i18n.t("online_mr.mesh_link"))
        self.tabs.setTabText(1, self.i18n.t("online_mr.channel_busy"))
        self.tabs.setTabText(2, self.i18n.t("online_mr.ap_radio_statistics"))
        self.tabs.setTabText(3, self.i18n.t("online_mr.switch_history"))
        self.tabs.setTabText(4, self.i18n.t("online_mr.interface_rate"))
        self.tabs.setTabText(5, self.i18n.t("online_mr.raw_output"))
        self.tabs.setTabText(6, self.i18n.t("online_mr.collection_log"))
        self.tabs.setTabText(7, self.i18n.t("online_mr.traffic_test"))
        self.tabs.setTabText(8, self.i18n.t("online_mr.diagnosis_results"))
        self.tabs.setTabText(9, self.i18n.t("online_mr.history_sessions"))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        self.page_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        scroll.setWidget(content)
        root.addWidget(scroll)

        controls = QGroupBox()
        self.connection_box = controls
        top_layout = QHBoxLayout(controls)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(12)
        self._cap_controls()
        controls.setMinimumHeight(58)
        controls.setMaximumHeight(76)
        controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        top_layout.addWidget(self.site_label)
        top_layout.addSpacing(18)
        top_layout.addWidget(self.available_metric_label)
        top_layout.addSpacing(18)
        top_layout.addWidget(self.selected_metric_label)
        top_layout.addSpacing(18)
        top_layout.addWidget(self.running_metric_label)
        top_layout.addSpacing(24)
        top_layout.addWidget(self.start_button)
        top_layout.addWidget(self.stop_selected_button)
        top_layout.addWidget(self.stop_all_button)
        top_layout.addWidget(self.open_button)
        top_layout.addWidget(self.refresh_devices_button)
        top_layout.addStretch(1)
        top_layout.addWidget(self._label("online_mr.status"))
        top_layout.addWidget(self.status_label)
        content_layout.addWidget(controls)
        content_layout.addWidget(self.filter_hint_label)

        self.device_table.setMinimumHeight(260)
        self.device_table.setMaximumHeight(330)
        self._configure_online_table(self.device_table)

        self.advanced_box = self._advanced_box()
        self.period_box = self._period_box()
        self.radio_box = self.period_box
        self.ping_box = self._ping_box()
        self.iperf_box = self._iperf_box()

        main_work_panel = QWidget()
        self.main_work_panel = main_work_panel
        main_grid = QGridLayout(main_work_panel)
        main_grid.setContentsMargins(0, 0, 0, 0)
        main_grid.setHorizontalSpacing(10)
        main_grid.setVerticalSpacing(8)
        device_panel = QWidget()
        self.device_panel = device_panel
        device_panel.setMinimumHeight(280)
        device_panel.setMaximumHeight(350)
        device_layout = QVBoxLayout(device_panel)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(0)
        device_layout.addWidget(self.device_table)
        self.collect_status_box.setMinimumHeight(140)
        self.collect_status_box.setMaximumHeight(190)
        collect_layout = QHBoxLayout(self.collect_status_box)
        collect_layout.setContentsMargins(8, 8, 8, 8)
        collect_layout.setSpacing(8)
        for progress in (self.collect_progress_1, self.collect_progress_2):
            progress.setRange(0, 0)
            progress.setTextVisible(False)
            progress.setMaximumHeight(12)
            progress.setVisible(False)
        for card, label in ((self.collect_card_1, self.collect_status_label_1), (self.collect_card_2, self.collect_status_label_2)):
            card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            card_layout.addWidget(label)
            collect_layout.addWidget(card)
        control_panel = QWidget()
        self.control_panel = control_panel
        control_panel.setMinimumWidth(560)
        control_panel.setMaximumWidth(680)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(10)
        control_layout.addWidget(self.period_box)
        control_layout.addWidget(self.ping_box)
        control_layout.addWidget(self.iperf_box)
        control_layout.addStretch(1)
        right_scroll = QScrollArea()
        self.right_control_scroll = right_scroll
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setMinimumWidth(560)
        right_scroll.setMaximumWidth(700)
        right_scroll.setWidget(control_panel)
        self._install_no_wheel_filter_for_controls(control_panel)
        main_grid.addWidget(device_panel, 0, 0)
        main_grid.addWidget(self.collect_status_box, 1, 0)
        main_grid.addWidget(right_scroll, 0, 1, 2, 1)
        main_grid.setColumnStretch(0, 6)
        main_grid.setColumnStretch(1, 4)
        main_grid.setRowStretch(0, 4)
        main_grid.setRowStretch(1, 2)
        main_work_panel.setMinimumHeight(430)
        main_work_panel.setMaximumHeight(520)

        vertical_splitter = QSplitter(Qt.Vertical)
        self.vertical_splitter = vertical_splitter
        vertical_splitter.addWidget(main_work_panel)
        self.summary_table.setMinimumHeight(120)
        self.summary_table.setMaximumHeight(150)
        vertical_splitter.addWidget(self.summary_table)
        view_row = QWidget()
        view_row.setMinimumHeight(40)
        view_row.setMaximumHeight(44)
        view_layout = QHBoxLayout(view_row)
        view_layout.setContentsMargins(0, 4, 0, 4)
        view_layout.addWidget(self._text_label("online_mr.view_device"))
        self.view_device_combo.setMinimumWidth(260)
        self.view_device_combo.setMaximumWidth(360)
        view_layout.addWidget(self.view_device_combo)
        self.parse_session_button.setMinimumWidth(140)
        view_layout.addWidget(self.parse_session_button)
        view_layout.addStretch(1)
        self.tabs.addTab(self.mesh_table, "")
        self.tabs.addTab(self.channel_table, "")
        self.tabs.addTab(self.statistics_text, "")
        self.tabs.addTab(self.switch_history_text, "")
        self.tabs.addTab(self.interface_rate_table, "")
        self.tabs.addTab(self.raw_text, "")
        self.tabs.addTab(self.log_text, "")
        self.tabs.addTab(self.iperf_table, "")
        self.tabs.addTab(self.diagnosis_table, "")
        self.tabs.addTab(self.history_table, "")
        self.tabs.setMinimumHeight(260)
        detail = QWidget()
        detail.setMinimumHeight(320)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)
        detail_layout.addWidget(view_row)
        detail_layout.addWidget(self.tabs)
        vertical_splitter.addWidget(detail)
        vertical_splitter.setStretchFactor(0, 5)
        vertical_splitter.setStretchFactor(1, 1)
        vertical_splitter.setStretchFactor(2, 3)
        vertical_splitter.setSizes([500, 135, 360])
        content_layout.addWidget(vertical_splitter, 1)
        self.retranslate()
        self._load_all_table_widths()

    def _connect_signals(self) -> None:
        self.device_table.itemChanged.connect(self._device_item_changed)
        self.device_table.currentCellChanged.connect(self._on_device_current_row_changed)
        self.view_device_combo.currentIndexChanged.connect(self._view_device_changed)
        self.start_button.clicked.connect(self.start_collection)
        self.stop_selected_button.clicked.connect(self.stop_selected)
        self.stop_all_button.clicked.connect(self.stop_all)
        self.open_button.clicked.connect(self.open_selected_session_dir)
        self.refresh_devices_button.clicked.connect(lambda: self.refresh_all(defer_heavy=False, refresh_tools=True))
        self.parse_session_button.clicked.connect(self.parse_selected_session)
        self.fping_device_combo_1.currentIndexChanged.connect(lambda _index: self._refresh_ping_target_labels())
        self.fping_device_combo_2.currentIndexChanged.connect(lambda _index: self._refresh_ping_target_labels())

    def _install_no_wheel_filter_for_controls(self, root_widget: QWidget) -> None:
        widgets = list(root_widget.findChildren(QAbstractSpinBox)) + list(root_widget.findChildren(QComboBox))
        for widget in widgets:
            widget.installEventFilter(self._no_wheel_filter)
            widget.setFocusPolicy(Qt.StrongFocus)

    def start_collection(self) -> None:
        selected = self._selected_devices()
        if not selected:
            QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), self.i18n.t("online_mr.select_mr_device"))
            return
        if len(selected) > 2:
            QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), self.i18n.t("online_mr.max_two_devices"))
            return
        capacity = max(0, self.manager.max_concurrent - self.manager.running_count())
        if capacity <= 0:
            QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), self.i18n.t("online_mr.max_two_running"))
            return
        if self.enable_iperf_check.isChecked() and len([device for device in selected if device.id not in self.workers_by_device_id]) >= 2:
            answer = QMessageBox.question(
                self,
                self.i18n.t("online_mr.traffic_test"),
                self.i18n.t("online_mr.confirm_two_traffic"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        started = 0
        skipped: list[str] = []
        for device in selected:
            if started >= capacity:
                break
            if device.id in self.workers_by_device_id:
                continue
            try:
                config = self._build_config_for_device(device)
            except ValueError as exc:
                QMessageBox.warning(self, self.i18n.t("online_mr.traffic_test"), str(exc))
                return
            if config is None:
                skipped.append(device.name)
                self._update_device_status(device.id, self.i18n.t("online_mr.connection_incomplete"))
                continue
            worker = OnlineMrCollectorWorker(config, self.store, parent=self)
            worker.started_session.connect(lambda meta, w=worker: self._worker_started(meta, w))
            worker.snapshot.connect(self.throttle.enqueue)
            worker.completed.connect(self._worker_completed)
            worker.failed.connect(lambda message, device_id=device.id: self._worker_failed(message, device_id))
            worker.start()
            started += 1
            self._update_device_status(device.id, self.i18n.t("online_mr.status_connecting"))
        if skipped:
            QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), f"{self.i18n.t('online_mr.connection_incomplete')}: {', '.join(skipped)}")
        if self.enable_fping_check.isChecked() and not self._selected_fping_device_ids():
            self.log_text.append(self.i18n.t("online_mr.ping_target_empty"))
        if started:
            self._set_status("CONNECTING")
        self._update_action_state()

    def stop_selected(self) -> None:
        stopped_any = False
        for device in self._selected_devices():
            if device.id is None:
                continue
            iperf_worker = self.iperf_workers_by_device_id.get(device.id)
            if iperf_worker:
                iperf_worker.stop()
            fping_worker = self.fping_workers_by_device_id.get(device.id)
            if fping_worker:
                self._set_ping_status(device.id, "stopping")
                fping_worker.stop()
            worker = self.workers_by_device_id.get(device.id)
            if worker:
                worker.cancel()
                self._update_device_status(device.id, self.i18n.t("online_mr.status_stopping"))
                self._update_summary_status_by_device(device.id, "STOPPING")
                stopped_any = True
        if stopped_any:
            self._set_status("STOPPING")
        self._update_action_state()

    def stop_all(self) -> None:
        for worker in list(self.iperf_workers_by_device_id.values()):
            worker.stop()
        for worker in list(self.fping_workers_by_device_id.values()):
            worker.stop()
        for device_id in list(self.fping_workers_by_device_id.keys()):
            self._set_ping_status(device_id, "stopping")
        for device_id, worker in list(self.workers_by_device_id.items()):
            worker.cancel()
            self._update_device_status(device_id, self.i18n.t("online_mr.status_stopping"))
            self._update_summary_status_by_device(device_id, "STOPPING")
        if self.workers_by_device_id:
            self._set_status("STOPPING")
        self._update_action_state()

    def open_selected_session_dir(self) -> None:
        selected = self._selected_devices()
        path: Path | None = None
        if len(selected) == 1 and selected[0].id in self.last_session_dir_by_device_id:
            path = self.last_session_dir_by_device_id.get(selected[0].id)
        else:
            row = self.summary_table.currentRow()
            session_id = self.summary_table.item(row, SUMMARY_COL_SESSION).text() if row >= 0 and self.summary_table.item(row, SUMMARY_COL_SESSION) else ""
            path = self.session_dirs.get(session_id)
        if path is None:
            path = self.paths.online_mr_root(self.site_name)
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, self.i18n.t("online_mr.open_session_dir"), f"Open collection directory failed: {exc}")

    def _selected_session_dir_for_parse(self) -> Path | None:
        device_id = self.view_device_combo.currentData()
        if device_id is not None:
            parsed_device_id = int(device_id)
            path = self.last_session_dir_by_device_id.get(parsed_device_id)
            if path and path.exists():
                return path
            latest = self._latest_session_dir_for_device(parsed_device_id)
            if latest is not None:
                return latest

        row = self.summary_table.currentRow()
        if row >= 0:
            session_item = self.summary_table.item(row, SUMMARY_COL_SESSION)
            session_id = session_item.text() if session_item else ""
            path = self.session_dirs.get(session_id)
            if path is not None:
                return path

        row = self.history_table.currentRow()
        if row >= 0:
            item = self.history_table.item(row, 8)
            if item is not None and item.text():
                return Path(item.text())
        return None

    def _latest_session_dir_for_device(self, device_id: int) -> Path | None:
        for row in self.store.list_sessions(self.site_name, None):
            if int(row.get("device_id") or -1) != int(device_id):
                continue
            session_dir = row.get("session_dir")
            if session_dir:
                return Path(str(session_dir))
        return None

    def parse_selected_session(self) -> None:
        session_dir = self._selected_session_dir_for_parse()
        if session_dir is None:
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), "Please select a device or history session to parse.")
            return
        if not session_dir.exists():
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), f"Collection directory does not exist: {session_dir}")
            return
        raw_dir = session_dir / "raw"
        if not raw_dir.exists():
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), f"Raw directory was not found: {raw_dir}")
            return
        self.parse_session_button.setEnabled(False)
        self.log_text.append(f"Start parsing collection data: {session_dir}")
        self.parse_worker = OnlineMrParseWorker(session_dir, parent=self)
        self.parse_worker.completed.connect(lambda summary, d=session_dir: self._parse_completed(d, summary))
        self.parse_worker.failed.connect(self._parse_failed)
        self.parse_worker.start()

    def _parse_completed(self, session_dir: Path, summary) -> None:
        self.parse_session_button.setEnabled(True)
        self.log_text.append(
            f"Parse completed: active_segments={summary.active_segments}, "
            f"mesh_samples={getattr(summary, 'mesh_samples', 0)}, "
            f"ping_samples={summary.ping_samples}, iperf_samples={summary.iperf_samples}, issues={summary.issues}"
        )
        rows = self._load_diagnosis_results(session_dir)
        self.tabs.setCurrentWidget(self.diagnosis_table)
        if rows == 0:
            message = (
                "解析完成，但没有生成诊断结果。\n"
                f"已检查：\n"
                f"mesh-link：{getattr(summary, 'mesh_samples', 0)} 条\n"
                f"channelbusy：{getattr(summary, 'channel_samples', 0)} 条\n"
                f"fping：{getattr(summary, 'ping_samples', 0)} 条\n"
                f"interface-rate：{getattr(summary, 'interface_samples', 0)} 条\n"
                "请检查 raw 文件格式。"
            )
            self.log_text.append(message)
            QMessageBox.information(self, self.i18n.t("online_mr.parse_collection_data"), message)
        self.parse_worker = None

    def _parse_failed(self, message: str) -> None:
        self.parse_session_button.setEnabled(True)
        self.parse_worker = None
        QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), message)

    def _load_diagnosis_results(self, session_dir: Path) -> int:
        import sqlite3

        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        self.diagnosis_table.setRowCount(0)
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT s.start_time, s.end_time, s.active_peer_mac, s.avg_mr_rssi, s.min_mr_rssi,
                       m.ping_loss_percent, m.avg_latency_ms, m.max_latency_ms,
                       m.avg_mbps, m.max_mbps, m.avg_tx_busy, m.avg_rx_busy, s.event_type
                FROM active_segments s
                LEFT JOIN active_segment_metrics m ON m.segment_id = s.id
                ORDER BY s.start_time
                """
            ).fetchall()
        for row_data in rows:
            row = self.diagnosis_table.rowCount()
            self.diagnosis_table.insertRow(row)
            values = list(row_data[:2]) + [row_data[2], row_data[3], row_data[4], row_data[5], row_data[6], row_data[8], row_data[9], row_data[10], row_data[11], "", "", row_data[12]]
            for column, value in enumerate(values):
                self.diagnosis_table.setItem(row, column, QTableWidgetItem("-" if value in {None, ""} else str(value)))
        return len(rows)

    def _worker_started(self, meta, worker: OnlineMrCollectorWorker) -> None:
        self.manager.register(meta.session_id, worker)
        if meta.device_id is not None:
            self.manager.register_device(int(meta.device_id), worker)
            self.session_to_device_id[meta.session_id] = int(meta.device_id)
            self.workers_by_device_id[int(meta.device_id)] = worker
        self.workers[meta.session_id] = worker
        if meta.session_dir:
            self.session_dirs[meta.session_id] = Path(meta.session_dir)
            self._ensure_event_pipeline(meta.session_id, Path(meta.session_dir))
            if meta.device_id is not None:
                self.last_session_dir_by_device_id[int(meta.device_id)] = Path(meta.session_dir)
        self._start_fping_worker(meta, worker)
        self._start_iperf_worker(meta, worker)
        self._set_status(meta.status)
        if meta.device_id is not None:
            self._update_device_status(int(meta.device_id), self._status_text(meta.status))
        self._fill_view_devices(prefer_device_id=int(meta.device_id) if meta.device_id is not None else None)
        self._fill_history()

    def _worker_completed(self, session_id: str) -> None:
        self.manager.unregister(session_id)
        device_id = self.session_to_device_id.pop(session_id, None)
        if device_id is not None:
            self.manager.unregister_device(device_id)
            self.workers_by_device_id.pop(device_id, None)
            self.fping_workers_by_device_id.pop(device_id, None)
            self.iperf_workers_by_device_id.pop(device_id, None)
            self._update_device_status(device_id, self.i18n.t("online_mr.status_stopped"))
            self._update_summary_status_by_device(device_id, "STOPPED")
        self.workers.pop(session_id, None)
        self.fping_workers.pop(session_id, None)
        self.iperf_workers.pop(session_id, None)
        self.event_buses.pop(session_id, None)
        self.realtime_buffers.pop(session_id, None)
        self.diagnosis_engines.pop(session_id, None)
        self.event_parsers.pop(session_id, None)
        self._clear_raw_tail_offsets(session_id)
        self._set_status("STOPPED" if not self.workers_by_device_id else "COLLECTING")
        self.running_count_label.setText(str(self.manager.running_count()))
        self._refresh_top_metrics()
        self._fill_view_devices(prefer_device_id=device_id)
        self._fill_history()
        self._update_action_state()

    def _worker_failed(self, message: str, device_id: int | None = None) -> None:
        if device_id is not None:
            session_id = next((sid for sid, sid_device_id in self.session_to_device_id.items() if sid_device_id == device_id), "")
            self._update_device_status(device_id, self.i18n.t("online_mr.status_failed"))
            self._update_summary_status_by_device(device_id, "FAILED")
            self.workers_by_device_id.pop(device_id, None)
            self.iperf_workers_by_device_id.pop(device_id, None)
            self.fping_workers_by_device_id.pop(device_id, None)
            self.manager.unregister_device(device_id)
            if session_id:
                self.event_buses.pop(session_id, None)
                self.realtime_buffers.pop(session_id, None)
                self.diagnosis_engines.pop(session_id, None)
                self.event_parsers.pop(session_id, None)
                self._clear_raw_tail_offsets(session_id)
        self._set_status("FAILED" if not self.workers_by_device_id else "COLLECTING")
        self.running_count_label.setText(str(self.manager.running_count()))
        self._refresh_top_metrics()
        self._update_action_state()
        QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), message)

    def _start_fping_worker(self, meta, ssh_worker: OnlineMrCollectorWorker) -> None:
        config = ssh_worker.collector.config.fping.normalized()
        if meta.session_dir is None:
            return
        session = OnlineMrSession(Path(meta.session_dir), meta)
        if not config.enabled:
            session.write_fping_final_summary("High frequency ping is disabled")
            if meta.device_id is not None:
                self._set_ping_status(int(meta.device_id), "disabled")
            return
        if not config.target:
            session.write_fping_final_summary("High frequency ping failed: target is empty")
            if meta.device_id is not None:
                self._set_ping_status(int(meta.device_id), "empty target")
            return
        tool = find_fping_tool(self.paths)
        if tool is None:
            self.log_text.append(self.i18n.t("online_mr.fping_tool_missing"))
            session.write_fping_final_summary("High frequency ping failed: fping v5 was not found")
            if meta.device_id is not None:
                self._set_ping_status(int(meta.device_id), "tool missing")
            return
        bus = self._ensure_event_pipeline(meta.session_id, Path(meta.session_dir))
        worker = FpingV5ProbeWorker(session, config, tool, event_bus=bus, source_device_id=meta.device_id, parent=self)
        worker.failed.connect(lambda message: self.log_text.append(f"Fping: {message}"))
        worker.completed.connect(lambda _status, session_id=meta.session_id, device_id=meta.device_id: self._fping_completed(session_id, device_id))
        self.fping_workers[meta.session_id] = worker
        if meta.device_id is not None:
            self.fping_workers_by_device_id[int(meta.device_id)] = worker
            self._set_ping_status(int(meta.device_id), f"running -> {config.target}")
        worker.start()

    def _fping_completed(self, session_id: str, device_id: int | None) -> None:
        self.fping_workers.pop(session_id, None)
        if device_id is not None:
            self.fping_workers_by_device_id.pop(int(device_id), None)
            self._set_ping_status(int(device_id), "stopped")

    def _start_iperf_worker(self, meta, ssh_worker: OnlineMrCollectorWorker) -> None:
        config = ssh_worker.collector.config.iperf.normalized()
        if not config.enabled or not config.server_ip or meta.session_dir is None:
            return
        tool = find_iperf_tool(self.paths)
        if tool is None:
            self.log_text.append(self.i18n.t("iperf.tool_missing"))
            return
        duration = config.duration_seconds
        if config.follow_collection:
            duration = int(ssh_worker.collector.config.duration_minutes or 0) * 60 or 86400
        client_config = IperfClientConfig(
            server_ip=config.server_ip,
            port=config.port,
            protocol=config.protocol,
            duration_seconds=duration,
            interval_seconds=config.interval_seconds,
            parallel=config.parallel,
            direction=config.direction,
            target_bandwidth=config.target_bandwidth,
            follow_collection=config.follow_collection,
        ).normalized()
        command = build_iperf_client_args(tool, client_config)
        session_dir = Path(meta.session_dir)
        log_file = session_dir / "raw" / "iperf_client_raw.log"
        worker = IperfProcessWorker(tool, command, log_file, store=None, session_id=meta.session_id, device_id=meta.device_id, config=client_config, mode="client", parent=self)
        worker.line_received.connect(lambda line: self.log_text.append(f"IPERF: {line}"))
        worker.interval_received.connect(lambda row, device_id=meta.device_id: self._append_iperf_interval(device_id, row))
        worker.completed.connect(lambda _run_id, session_id=meta.session_id, device_id=meta.device_id: self._iperf_completed(session_id, device_id))
        worker.failed.connect(lambda message: self.log_text.append(f"IPERF: {message}"))
        self.iperf_workers[meta.session_id] = worker
        if meta.device_id is not None:
            self.iperf_workers_by_device_id[int(meta.device_id)] = worker
        worker.start()

    def _iperf_completed(self, session_id: str, device_id: int | None) -> None:
        self.iperf_workers.pop(session_id, None)
        if device_id is not None:
            self.iperf_workers_by_device_id.pop(int(device_id), None)

    def _append_iperf_interval(self, device_id: int | None, row: dict[str, object]) -> None:
        if device_id is not None:
            self.latest_iperf_by_device_id[int(device_id)] = row
            self._publish_iperf_event(int(device_id), row)
        table_row = self.iperf_table.rowCount()
        self.iperf_table.insertRow(table_row)
        values = [
            row.get("interval_center_time") or row.get("collector_time"),
            f"{float(row.get('bitrate_mbps') or 0):.2f}",
            row.get("retransmits", 0),
            int(float(row.get("transfer_bytes") or 0)),
            row.get("raw_line", ""),
        ]
        for column, value in enumerate(values):
            self.iperf_table.setItem(table_row, column, QTableWidgetItem(str(value)))
        if device_id is not None:
            self._update_summary_iperf(int(device_id), row)
        self._trim_table(self.iperf_table)

    def _publish_iperf_event(self, device_id: int, row: dict[str, object]) -> None:
        session_id = next((sid for sid, sid_device_id in self.session_to_device_id.items() if sid_device_id == device_id), "")
        if not session_id:
            return
        bus = self.event_buses.get(session_id)
        if bus is None:
            session_dir = self.session_dirs.get(session_id)
            if session_dir is None:
                return
            bus = self._ensure_event_pipeline(session_id, session_dir)
        bus.publish(
            OnlineMrEvent(
                timestamp=datetime.now(),
                session_id=session_id,
                device_id=device_id,
                source="iperf3",
                module="iperf",
                event_type=EVENT_IPERF3_SAMPLE,
                payload=dict(row),
                raw=str(row.get("raw_line") or ""),
            )
        )

    def _flush_snapshot(self) -> None:
        snapshot = self.throttle.flush()
        if snapshot is None:
            self._refresh_realtime_view()
            return
        self._publish_snapshot_event(snapshot)
        self._set_status(snapshot.status)
        self._upsert_summary(snapshot)
        self._append_mesh_snapshot(snapshot)
        self._refresh_realtime_view()
        self._maybe_parse_realtime(snapshot)

    def _ensure_event_pipeline(self, session_id: str, session_dir: Path) -> OnlineMrEventBus:
        bus = self.event_buses.get(session_id)
        if bus is not None:
            return bus
        bus = OnlineMrEventBus()
        buffer = SlidingWindowBuffer(window_seconds=5)
        parser = EventParserEngine()
        diagnosis = OnlineMrDiagnosisEngine()
        writer = EventWriter(session_dir / "parsed" / "online_diagnosis.sqlite")
        bus.subscribe("*", buffer.add)
        bus.subscribe("*", parser.on_event)
        bus.subscribe("*", diagnosis.on_event)
        bus.subscribe("*", writer.write_event_to_db)
        self.event_buses[session_id] = bus
        self.realtime_buffers[session_id] = buffer
        self.event_parsers[session_id] = parser
        self.diagnosis_engines[session_id] = diagnosis
        return bus

    def _publish_snapshot_event(self, snapshot: OnlineMrSnapshot) -> None:
        bus = self.event_buses.get(snapshot.session_id)
        device_id = self.session_to_device_id.get(snapshot.session_id)
        if bus is None:
            session_dir = self.session_dirs.get(snapshot.session_id)
            if session_dir is None:
                return
            bus = self._ensure_event_pipeline(snapshot.session_id, session_dir)
        timestamp = _snapshot_time(snapshot.last_collection_time)
        self._publish_realtime_raw_tail(snapshot, bus, device_id, timestamp)
        if snapshot.active_peer:
            peer_info = self._resolve_peer_cached(snapshot.active_peer) or {}
            bus.publish(
                OnlineMrEvent(
                    timestamp=timestamp,
                    session_id=snapshot.session_id,
                    device_id=device_id,
                    source="ssh",
                    module="mesh",
                    event_type=EVENT_MESH_SAMPLE,
                    payload={
                        "active_peer": snapshot.active_peer,
                        "peer_mac": snapshot.active_peer,
                        "peer_name": peer_info.get("peer_ap_name") or "",
                        "peer_site": peer_info.get("peer_site") or "",
                        "peer_radio": peer_info.get("peer_radio_label") or "",
                        "link_state": "ACTIVE",
                        "local_rssi": snapshot.local_rssi,
                        "peer_rssi": snapshot.peer_rssi,
                        "mr_rssi": snapshot.local_rssi,
                    },
                    raw=None,
                )
            )
        if snapshot.local_tx_busy is not None or snapshot.local_rx_busy is not None:
            bus.publish(
                OnlineMrEvent(
                    timestamp=timestamp,
                    session_id=snapshot.session_id,
                    device_id=device_id,
                    source="ssh",
                    module="busy",
                    event_type=EVENT_BUSY_SAMPLE,
                    payload={"tx_busy": snapshot.local_tx_busy, "rx_busy": snapshot.local_rx_busy, "ctl_busy": None},
                    raw=None,
                )
            )

    def _publish_realtime_raw_tail(
        self,
        snapshot: OnlineMrSnapshot,
        bus: OnlineMrEventBus,
        device_id: int | None,
        timestamp: datetime,
    ) -> None:
        session_dir = self.session_dirs.get(snapshot.session_id)
        if session_dir is None:
            return
        raw_dir = session_dir / "raw"
        if not raw_dir.exists():
            return
        parser = self.event_parsers.get(snapshot.session_id)
        if parser is None:
            parser = EventParserEngine()
            self.event_parsers[snapshot.session_id] = parser
        specs = (
            ("mesh_link_raw.log", "mesh", EVENT_MESH_SAMPLE, parser.parse_mesh),
            ("channel_busy_raw.log", "busy", EVENT_BUSY_SAMPLE, parser.parse_busy),
        )
        for filename, module, event_type, parse in specs:
            raw = self._read_raw_tail(snapshot.session_id, filename, raw_dir / filename)
            if not raw.strip():
                continue
            base_event = OnlineMrEvent(
                timestamp=timestamp,
                session_id=snapshot.session_id,
                device_id=device_id,
                source="ssh",
                module=module,
                event_type=event_type,
                payload={},
                raw=raw,
            )
            payload = parse(base_event)
            bus.publish(
                OnlineMrEvent(
                    timestamp=timestamp,
                    session_id=snapshot.session_id,
                    device_id=device_id,
                    source="ssh",
                    module=module,
                    event_type=event_type,
                    payload=payload,
                    raw=raw,
                )
            )

    def _read_raw_tail(self, session_id: str, filename: str, path: Path) -> str:
        if not path.exists():
            return ""
        key = (session_id, filename)
        try:
            size = path.stat().st_size
            offset = self._raw_tail_offsets.get(key, 0)
            if size < offset:
                offset = 0
            if size == offset:
                return ""
            read_from = offset
            if size - offset > 131072:
                read_from = max(0, size - 131072)
            with path.open("rb") as file:
                file.seek(read_from)
                data = file.read()
            self._raw_tail_offsets[key] = size
            return data.decode("utf-8", errors="replace")
        except OSError as exc:
            self.log_text.append(f"Raw tail read failed: {filename}: {exc}")
            return ""

    def _clear_raw_tail_offsets(self, session_id: str) -> None:
        for key in [key for key in self._raw_tail_offsets if key[0] == session_id]:
            self._raw_tail_offsets.pop(key, None)

    def _refresh_realtime_view(self) -> None:
        now = datetime.now()
        for session_id, buffer in list(self.realtime_buffers.items()):
            device_id = self.session_to_device_id.get(session_id)
            if device_id is None:
                continue
            events = [event for event in buffer.get_window() if event.device_id in {None, device_id}]
            state = self._build_realtime_state_for_device(session_id, device_id, events)
            self.realtime_states_by_device_id[device_id] = state
            diagnosis = self.diagnosis_engines.get(session_id)
            if diagnosis is not None:
                diagnosis.on_state(state)
            self._update_summary_from_state(state)
            latest_fping = self._latest_module_event(events, "fping")
            if latest_fping is not None:
                self._set_ping_status(device_id, self._format_ping_status(latest_fping.payload))
            latest_iperf = self._latest_module_event(events, "iperf")
            if latest_iperf is not None:
                self._update_summary_iperf(device_id, self._coerce_iperf_summary(latest_iperf.payload))
            last_event_time = buffer.last_event_time
            if (
                last_event_time is not None
                and device_id in self.workers_by_device_id
                and (now - last_event_time).total_seconds() > 5
            ):
                self._update_device_status(device_id, "事件停滞")
        self._refresh_collection_animation()

    def _build_realtime_state_for_device(self, session_id: str, device_id: int, events: list[OnlineMrEvent]) -> RealtimeMRState:
        worker = self.workers_by_device_id.get(device_id)
        snapshot = worker.collector.snapshot() if worker is not None else None
        device_name = ""
        if worker is not None:
            device_name = worker.collector.config.device_name
        if not device_name:
            device_name = next((device.name for device in self.filtered_devices if device.id == device_id), str(device_id))
        return build_realtime_state(
            device_id=device_id,
            device_name=device_name,
            status=snapshot.status if snapshot is not None else self._device_runtime_status(device_id),
            events=events,
            sample_count=snapshot.collected_count if snapshot is not None else 0,
            fail_count=snapshot.failed_count if snapshot is not None else 0,
            reconnect_count=snapshot.reconnect_count if snapshot is not None else 0,
            resolve_peer=self._resolve_peer_cached,
        )

    def _update_summary_from_state(self, state: RealtimeMRState) -> None:
        row = self._find_row(self.summary_table, str(state.device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            return
        values = {
            SUMMARY_COL_STATUS: self._status_text(state.status),
            SUMMARY_COL_ACTIVE_PEER: state.peer_name or state.peer_mac or "",
            SUMMARY_COL_MR_RSSI: state.mr_rssi,
            SUMMARY_COL_PEER_SITE: state.peer_station or state.peer_site or "",
            SUMMARY_COL_CTL_BUSY: state.ctl_busy,
            SUMMARY_COL_TX_BUSY: state.tx_busy,
            SUMMARY_COL_RX_BUSY: state.rx_busy,
            SUMMARY_COL_PING_LOSS: None if state.loss is None else f"{state.loss:.2f}%",
            SUMMARY_COL_PING_LATENCY: None if state.rtt is None else f"{state.rtt:.2f} ms",
            SUMMARY_COL_COLLECTED: state.sample_count,
            SUMMARY_COL_FAILED: state.fail_count,
            SUMMARY_COL_RECONNECTS: state.reconnect_count,
            SUMMARY_COL_LAST_COLLECTION: state.last_time.isoformat(sep=" ", timespec="milliseconds") if state.last_time else None,
            SUMMARY_COL_IPERF_MBPS: None if state.iperf_mbps is None else f"{state.iperf_mbps:.2f}",
            SUMMARY_COL_IPERF_RETRANS: state.retrans,
        }
        for column, value in values.items():
            item = QTableWidgetItem(self._summary_text(value))
            if column in {
                SUMMARY_COL_STATUS,
                SUMMARY_COL_MR_RSSI,
                SUMMARY_COL_CTL_BUSY,
                SUMMARY_COL_TX_BUSY,
                SUMMARY_COL_RX_BUSY,
                SUMMARY_COL_PING_LOSS,
                SUMMARY_COL_PING_LATENCY,
                SUMMARY_COL_COLLECTED,
                SUMMARY_COL_FAILED,
                SUMMARY_COL_RECONNECTS,
                SUMMARY_COL_IPERF_MBPS,
                SUMMARY_COL_IPERF_RETRANS,
            }:
                item.setTextAlignment(Qt.AlignCenter)
            self.summary_table.setItem(row, column, item)

    def _resolve_peer_cached(self, peer_mac: str) -> dict[str, object] | None:
        key = _normalize_mac_key(peer_mac)
        if not key:
            return None
        if key not in self.peer_station_cache:
            try:
                resolved = self.peer_mapping_service.resolve_peer_mac(peer_mac)
                self.peer_station_cache[key] = {
                    "peer_ap_name": resolved.ap_name or "",
                    "peer_site": resolved.site or "",
                    "peer_radio_label": resolved.radio or "",
                    "peer_radio_mac": resolved.radio_mac or "",
                    "match_rule": resolved.source,
                }
            except Exception:
                self.peer_station_cache[key] = {}
        return self.peer_station_cache.get(key)

    @staticmethod
    def _latest_module_event(events: list[OnlineMrEvent], module: str) -> OnlineMrEvent | None:
        for event in reversed(events):
            if event.module == module:
                return event
        return None

    def _update_summary_ping(self, device_id: int, payload: dict[str, object]) -> None:
        row = self._find_row(self.summary_table, str(device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            return
        loss = self._payload_float(payload, "loss_rate_percent", "loss_percent")
        if loss is None:
            ok = payload.get("ok")
            loss = 0.0 if ok is True else 100.0 if ok is False else None
        latency = self._payload_float(payload, "avg_rtt_ms", "rtt_ms", "last_rtt_ms")
        values = {
            SUMMARY_COL_PING_LOSS: None if loss is None else f"{loss:.2f}%",
            SUMMARY_COL_PING_LATENCY: None if latency is None else f"{latency:.2f} ms",
        }
        for column, value in values.items():
            item = QTableWidgetItem(self._summary_text(value))
            item.setTextAlignment(Qt.AlignCenter)
            self.summary_table.setItem(row, column, item)

    def _format_ping_status(self, payload: dict[str, object]) -> str:
        loss = self._payload_float(payload, "loss_rate_percent", "loss_percent")
        if loss is None:
            ok = payload.get("ok")
            loss = 0.0 if ok is True else 100.0 if ok is False else None
        latency = self._payload_float(payload, "avg_rtt_ms", "rtt_ms", "last_rtt_ms")
        parts = []
        if loss is not None:
            parts.append(f"loss {loss:.1f}%")
        if latency is not None:
            parts.append(f"rtt {latency:.1f}ms")
        return " ".join(parts) if parts else "running"

    def _coerce_iperf_summary(self, payload: dict[str, object]) -> dict[str, object]:
        row = dict(payload)
        mbps = self._payload_float(row, "bitrate_mbps", "throughput_mbps")
        retransmits = row.get("retransmits")
        if mbps is None or retransmits is None:
            end = row.get("end")
            if isinstance(end, dict):
                for key in ("sum_received", "sum_sent", "sum"):
                    summary = end.get(key)
                    if not isinstance(summary, dict):
                        continue
                    if mbps is None and summary.get("bits_per_second") is not None:
                        try:
                            mbps = float(summary["bits_per_second"]) / 1_000_000.0
                        except (TypeError, ValueError):
                            pass
                    if retransmits is None and summary.get("retransmits") is not None:
                        retransmits = summary.get("retransmits")
                    if mbps is not None and retransmits is not None:
                        break
        if mbps is None and row.get("bits_per_second") is not None:
            try:
                mbps = float(row["bits_per_second"]) / 1_000_000.0
            except (TypeError, ValueError):
                mbps = None
        row["bitrate_mbps"] = mbps if mbps is not None else 0.0
        row["retransmits"] = retransmits or 0
        return row

    @staticmethod
    def _payload_float(payload: dict[str, object], *keys: str) -> float | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _build_config_for_device(self, device: Device) -> OnlineMrConnectionConfig | None:
        if device.id is None:
            return None
        protocol, port, username, password = connection_fields_from_device(device)
        host = str(device.primary_address or "").strip()
        if not host or not username or not password:
            return None
        safe_name = safe_device_folder_name(device)
        ping_config = self._ping_config_for_device(device)
        fping_target = ping_config.target_ip if ping_config is not None else ""
        return OnlineMrConnectionConfig(
            site=self.site_name,
            mr_id=str(device.id),
            mr_name=device.name,
            safe_mr_name=safe_name,
            device_id=device.id,
            device_name=device.name,
            host=host,
            protocol=protocol,
            port=int(port),
            username=username,
            password=password,
            connection_targets=tuple(connection_targets(device)),
            intervals=OnlineMrIntervals(
                self.mesh_interval.value(),
                self.channel_interval.value(),
                self.statistics_interval.value(),
                self.switch_interval.value(),
                self.interface_rate_interval.value(),
                self.fping_interval_ms.value(),
            ),
            radio=OnlineMrRadioConfig(int(self.channel_radio.currentData()), int(self.statistics_radio.currentData())),
            fping=FpingConfig(
                enabled=self.enable_fping_check.isChecked() and bool(fping_target),
                target=fping_target,
                packet_size=self.fping_packet_size.value(),
                interval_ms=self.fping_interval_ms.value(),
                loss_threshold_ms=self.fping_loss_threshold_ms.value(),
            ),
            iperf=IperfTrafficConfig(
                enabled=self.enable_iperf_check.isChecked(),
                server_ip=self.iperf_server_edit.text().strip(),
                port=self.iperf_port_spin.value(),
                protocol=self.iperf_protocol_combo.currentText(),
                direction=self.iperf_direction_combo.currentData() or "upload",
                parallel=self.iperf_parallel_spin.value(),
                interval_seconds=self.iperf_interval_spin.value(),
                target_bandwidth=normalize_bandwidth_text(self.iperf_bandwidth_edit.text(), self.iperf_bandwidth_unit_combo.currentText()),
                follow_collection=self.iperf_follow_check.isChecked(),
                duration_seconds=self.iperf_duration_spin.value(),
            ),
            auto_reconnect=self.auto_reconnect_check.isChecked(),
            reconnect_interval=self.reconnect_interval.value(),
            max_reconnect=None if self.max_reconnect.value() == 0 else self.max_reconnect.value(),
            duration_minutes=None if self.duration_minutes.value() == 0 else self.duration_minutes.value(),
        )

    def _fill_devices(self) -> None:
        checked_ids = {device.id for device in self._selected_devices()}
        self.filtered_devices = sorted([device for device in self.devices if self._is_vehicle_fat_ap(device)], key=natural_device_sort_key)
        self._updating_device_checks = True
        self.device_table.setUpdatesEnabled(False)
        try:
            self.device_table.setRowCount(len(self.filtered_devices))
            for row, device in enumerate(self.filtered_devices):
                check_item = QTableWidgetItem("")
                check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                check_item.setCheckState(Qt.Checked if device.id in checked_ids else Qt.Unchecked)
                self.device_table.setItem(row, 0, check_item)
                protocol, port, username, _password = connection_fields_from_device(device)
                values = [
                    device.name,
                    device.primary_address,
                    protocol,
                    port,
                    username,
                    self.device_groups.get(int(device.group_id or 0), ""),
                    device.device_type or "",
                    self._device_runtime_status(device.id),
                ]
                for offset, value in enumerate(values, start=1):
                    item = QTableWidgetItem("" if value is None else str(value))
                    if offset in {3, 4, 8}:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.device_table.setItem(row, offset, item)
        finally:
            self.device_table.setUpdatesEnabled(True)
            self._updating_device_checks = False
        self.available_device_count_label.setText(str(len(self.filtered_devices)))
        self.filter_hint_label.setText("" if self.filtered_devices else self.i18n.t("online_mr.no_vehicle_fat_ap"))
        self._update_selected_count()
        self._refresh_fping_device_choices()
        self._refresh_top_metrics()

    def _load_device_groups(self) -> None:
        groups = DeviceGroupRepository(self.repository.database, self.site_name).list()
        self.device_groups = {int(group.id): group.name for group in groups if group.id is not None}

    def _is_vehicle_fat_ap(self, device: Device) -> bool:
        group_name = self.device_groups.get(int(device.group_id or 0), "")
        has_vehicle_mr_group = any("车载-MR" in name for name in self.device_groups.values())
        if has_vehicle_mr_group:
            return "车载-MR" in group_name and is_fat_ap_device(device.device_type)
        return group_name == "\u8f66\u8f7d" and is_fat_ap_device(device.device_type)

    def _selected_devices(self) -> list[Device]:
        checked: list[Device] = []
        for row in range(self.device_table.rowCount()):
            item = self.device_table.item(row, 0)
            if item and item.checkState() == Qt.Checked and row < len(self.filtered_devices):
                checked.append(self.filtered_devices[row])
        return checked

    def _device_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_device_checks or item.column() != 0:
            return
        changed_device_id: int | None = None
        if 0 <= item.row() < len(self.filtered_devices):
            device = self.filtered_devices[item.row()]
            if device.id is not None and item.checkState() == Qt.Checked:
                changed_device_id = int(device.id)
        selected = self._selected_devices()
        if len(selected) > 2:
            self._updating_device_checks = True
            item.setCheckState(Qt.Unchecked)
            self._updating_device_checks = False
            QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), self.i18n.t("online_mr.max_two_devices"))
            changed_device_id = None
        if changed_device_id is not None:
            self._view_device_user_selected = False
            self._fill_view_devices(prefer_device_id=changed_device_id)
        self._update_selected_count()
        self._refresh_fping_device_choices()
        self._update_action_state()

    def _on_device_current_row_changed(self, current_row: int, _current_column: int, _previous_row: int, _previous_column: int) -> None:
        if self._updating_device_checks or self._view_device_user_selected:
            return
        if current_row < 0 or current_row >= len(self.filtered_devices):
            return
        device = self.filtered_devices[current_row]
        if device.id is not None:
            self._fill_view_devices(prefer_device_id=int(device.id))

    def _view_device_changed(self, _index: int) -> None:
        if not self.view_device_combo.signalsBlocked():
            self._view_device_user_selected = True

    def _update_selected_count(self) -> None:
        self.selected_device_count_label.setText(str(len(self._selected_devices())))
        self.running_count_label.setText(str(self.manager.running_count()))
        self._refresh_top_metrics()

    def _update_action_state(self) -> None:
        selected = self._selected_devices()
        selected_ids = {device.id for device in selected if device.id is not None}
        running_selected = any(device_id in self.workers_by_device_id for device_id in selected_ids)
        can_start = bool(selected) and len(selected) <= 2 and self.manager.running_count() < self.manager.max_concurrent
        self.start_button.setEnabled(can_start)
        self.stop_selected_button.setEnabled(running_selected)
        self.stop_all_button.setEnabled(bool(self.workers_by_device_id))
        self.open_button.setEnabled(True)
        self.running_count_label.setText(str(self.manager.running_count()))
        self._refresh_top_metrics()
        self._refresh_collection_animation()

    def _refresh_top_metrics(self) -> None:
        self.available_metric_label.setText(f"{self.i18n.t('online_mr.available_devices')}: {self.available_device_count_label.text() or '0'}")
        self.selected_metric_label.setText(f"{self.i18n.t('online_mr.selected_devices')}: {self.selected_device_count_label.text() or '0'}")
        self.running_metric_label.setText(f"{self.i18n.t('online_mr.running_collectors')}: {self.running_count_label.text() or '0'}")

    def _refresh_fping_device_choices(self) -> None:
        selected = [device for device in self._selected_devices() if device.id is not None]
        previous_1 = self.fping_device_combo_1.currentData()
        previous_2 = self.fping_device_combo_2.currentData()
        available_ids = {int(device.id) for device in selected if device.id is not None}

        for combo in (self.fping_device_combo_1, self.fping_device_combo_2):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("-", None)
            for device in selected:
                host = str(device.primary_address or "").strip()
                label = f"{device.name} ({host})" if host else device.name
                combo.addItem(label, int(device.id))
            combo.blockSignals(False)

        defaults = [selected[0].id if selected else None, selected[1].id if len(selected) > 1 else (selected[0].id if selected else None)]
        desired: list[int | None] = []
        for previous, default in ((previous_1, defaults[0]), (previous_2, defaults[1])):
            wanted = int(previous) if previous in available_ids else (int(default) if default is not None else None)
            desired.append(wanted)
        if len(selected) > 1 and desired[0] is not None and desired[0] == desired[1]:
            desired[1] = int(selected[1].id)
        for combo, wanted in (
            (self.fping_device_combo_1, desired[0]),
            (self.fping_device_combo_2, desired[1]),
        ):
            index = combo.findData(wanted)
            combo.blockSignals(True)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self._refresh_ping_target_labels()
        self._refresh_ping_status_labels()

    def _refresh_ping_target_labels(self) -> None:
        for combo, target_label in (
            (self.fping_device_combo_1, self.fping_target_label_1),
            (self.fping_device_combo_2, self.fping_target_label_2),
        ):
            device_id = combo.currentData()
            target = ""
            placeholder = "-"
            if device_id is not None:
                device = self._device_by_id(int(device_id))
                if device is not None:
                    target = str(device.primary_address or "").strip()
                    if not target:
                        placeholder = "主机地址为空"
            target_label.setPlaceholderText(placeholder)
            target_label.setText(target)

    def _selected_fping_device_ids(self) -> set[int]:
        ids: set[int] = set()
        for combo in (self.fping_device_combo_1, self.fping_device_combo_2):
            value = combo.currentData()
            if value is not None:
                ids.add(int(value))
        return ids

    def _ping_config_for_device(self, device: Device) -> PingConfig | None:
        if device.id is None:
            return None
        selected_ids = self._selected_fping_device_ids()
        source_device_id = int(device.id)
        if selected_ids and source_device_id not in selected_ids:
            return None
        repo_device = self._device_by_id(source_device_id)
        target_ip = str((repo_device.primary_address if repo_device else device.primary_address) or "").strip()
        if not target_ip:
            return None
        return PingConfig(source_device_id=source_device_id, target_ip=target_ip)

    def _device_by_id(self, device_id: int) -> Device | None:
        try:
            return self.repository.get(device_id)
        except Exception:
            return next((device for device in self.filtered_devices if device.id == device_id), None)

    def _fping_target_for_device(self, device: Device) -> str:
        config = self._ping_config_for_device(device)
        return config.target_ip if config is not None else ""

    def _set_ping_status(self, device_id: int | None, status: str) -> None:
        if device_id is None:
            return
        for combo, label, name in (
            (self.fping_device_combo_1, self.fping_status_label_1, "Ping 1"),
            (self.fping_device_combo_2, self.fping_status_label_2, "Ping 2"),
        ):
            if combo.currentData() == device_id:
                label.setText(f"{name}: {status}")

    def _refresh_ping_status_labels(self) -> None:
        for combo, label, name in (
            (self.fping_device_combo_1, self.fping_status_label_1, "Ping 1"),
            (self.fping_device_combo_2, self.fping_status_label_2, "Ping 2"),
        ):
            value = combo.currentData()
            if value is None:
                label.setText(f"{name}: idle")
            elif int(value) in self.fping_workers_by_device_id:
                label.setText(f"{name}: running")
            else:
                label.setText(f"{name}: ready")

    def _refresh_collection_animation(self) -> None:
        selected = [device for device in self._selected_devices() if device.id is not None][:2]
        if not selected and not self.workers_by_device_id:
            self.collect_status_label_1.setText(
                "暂无运行采集\n"
                f"{self.fping_status_label_1.text()}\n"
                f"{self.fping_status_label_2.text()}"
            )
            self.collect_card_1.setTitle("实时采集")
            self.collect_card_1.setVisible(True)
            self.collect_card_2.setVisible(False)
            self.collect_status_label_2.setText("")
            for progress in (self.collect_progress_1, self.collect_progress_2):
                progress.setRange(0, 1)
                progress.setValue(0)
            return
        slots = [
            (self.collect_status_label_1, self.collect_progress_1, "Device 1"),
            (self.collect_status_label_2, self.collect_progress_2, "Device 2"),
        ]
        for index, (label, progress, fallback_name) in enumerate(slots):
            card = self.collect_card_1 if index == 0 else self.collect_card_2
            if index >= len(selected):
                card.setVisible(False)
                label.setText(f"{fallback_name}: idle")
                progress.setRange(0, 1)
                progress.setValue(0)
                continue
            card.setVisible(True)
            device = selected[index]
            card.setTitle(device.name)
            ping_label = self.fping_status_label_1 if index == 0 else self.fping_status_label_2
            worker = self.workers_by_device_id.get(int(device.id))
            if worker is None:
                label.setText(f"状态：已停止\nMesh：-\nBusy：-\nStats：-\n{ping_label.text()}")
                progress.setRange(0, 1)
                progress.setValue(0)
                continue
            collector = getattr(worker, "collector", None)
            if collector is None:
                label.setText(f"状态：{self._status_text('COLLECTING')}\nMesh：正常  Busy：-  Stats：-\n{ping_label.text()}")
                progress.setRange(0, 0)
                continue
            snapshot = collector.snapshot()
            modules = ["mesh", "busy", "stats"]
            if int(device.id) in self.fping_workers_by_device_id:
                modules.append("ping")
            realtime = self._realtime_status_for_device(int(device.id))
            ping_text = realtime if realtime else ping_label.text()
            label.setText(
                f"状态：{self._status_text(snapshot.status)}  会话：{snapshot.session_id or '-'}\n"
                f"Mesh：正常  Busy：正常  Stats：正常\n"
                f"{ping_text}\n"
                f"采集时长：{snapshot.uptime_seconds}s"
            )
            progress.setRange(0, 0)

    def _realtime_status_for_device(self, device_id: int) -> str:
        session_id = next((sid for sid, sid_device_id in self.session_to_device_id.items() if sid_device_id == device_id), "")
        if not session_id:
            return ""
        buffer = self.realtime_buffers.get(session_id)
        if buffer is None:
            return ""
        events = [event for event in buffer.get_window() if event.device_id in {None, device_id}]
        if not events:
            return ""
        counts: dict[str, int] = {}
        latest_loss: object = None
        latest_rtt: object = None
        for event in events:
            counts[event.module] = counts.get(event.module, 0) + 1
            if event.module == "fping":
                latest_loss = event.payload.get("loss_rate_percent")
                latest_rtt = event.payload.get("avg_rtt_ms") or event.payload.get("rtt_ms")
        score = self.diagnosis_engines.get(session_id).score if session_id in self.diagnosis_engines else None
        parts = [f"win5s {sum(counts.values())}ev"]
        if latest_loss is not None:
            parts.append(f"loss {float(latest_loss):.1f}%")
        if latest_rtt is not None:
            parts.append(f"rtt {float(latest_rtt):.1f}ms")
        if score is not None:
            parts.append(f"score {float(score):.0f}")
        return " ".join(parts)

    def _maybe_parse_realtime(self, snapshot: OnlineMrSnapshot) -> None:
        if self.realtime_parse_worker is not None or self.parse_worker is not None:
            return
        session_dir = self.session_dirs.get(snapshot.session_id)
        if session_dir is None or not session_dir.exists():
            return
        raw_dir = session_dir / "raw"
        if not raw_dir.exists():
            return
        now = time.monotonic()
        if now - self._last_realtime_parse_at.get(snapshot.session_id, 0.0) < 30.0:
            return
        self._last_realtime_parse_at[snapshot.session_id] = now
        worker = OnlineMrParseWorker(session_dir, parent=self)
        self.realtime_parse_worker = worker
        worker.completed.connect(lambda summary, d=session_dir: self._realtime_parse_completed(d, summary))
        worker.failed.connect(self._realtime_parse_failed)
        worker.start()

    def _realtime_parse_completed(self, session_dir: Path, summary) -> None:
        self.log_text.append(
            f"Realtime parse completed: mesh_samples={getattr(summary, 'mesh_samples', 0)}, "
            f"ping_samples={summary.ping_samples}, iperf_samples={summary.iperf_samples}"
        )
        if self.tabs.currentWidget() == self.diagnosis_table:
            self._load_diagnosis_results(session_dir)
        self.realtime_parse_worker = None

    def _realtime_parse_failed(self, message: str) -> None:
        self.log_text.append(f"Realtime parse failed: {message}")
        self.realtime_parse_worker = None

    def _device_runtime_status(self, device_id: int | None) -> str:
        if device_id is not None and device_id in self.workers_by_device_id:
            return self._status_text("COLLECTING")
        return self.i18n.t("online_mr.status_stopped")

    def _update_device_status(self, device_id: int | None, status: str) -> None:
        if device_id is None:
            return
        for row, device in enumerate(self.filtered_devices):
            if device.id == device_id:
                self.device_table.setItem(row, 8, QTableWidgetItem(status))
                break

    def _preferred_view_device_id(self) -> int | None:
        selected = self._selected_devices()
        if selected and selected[0].id is not None:
            return int(selected[0].id)
        row = self.device_table.currentRow()
        if 0 <= row < len(self.filtered_devices):
            device = self.filtered_devices[row]
            if device.id is not None:
                return int(device.id)
        if self.workers_by_device_id:
            return next(iter(self.workers_by_device_id.keys()))
        current = self.view_device_combo.currentData()
        if current is not None:
            return int(current)
        return None

    def _fill_view_devices(self, prefer_device_id: int | None = None) -> None:
        if prefer_device_id is None:
            prefer_device_id = self._preferred_view_device_id()
        self.view_device_combo.blockSignals(True)
        self.view_device_combo.clear()
        seen: set[int] = set()
        devices = list(self.filtered_devices)
        if prefer_device_id is not None:
            devices.sort(key=lambda device: 0 if device.id == prefer_device_id else 1)
        for device in devices:
            if device.id is None:
                continue
            seen.add(int(device.id))
            self.view_device_combo.addItem(device.name, int(device.id))
        for device_id in self.workers_by_device_id:
            if device_id not in seen:
                self.view_device_combo.addItem(str(device_id), device_id)
        index = self.view_device_combo.findData(prefer_device_id)
        self.view_device_combo.setCurrentIndex(index if index >= 0 else 0)
        self.view_device_combo.blockSignals(False)

    def _fill_history(self) -> None:
        self._history_refresh_pending = False
        rows = self.store.list_sessions(self.site_name, None)
        self.history_table.setUpdatesEnabled(False)
        try:
            self.history_table.setRowCount(len(rows))
            for row, row_data in enumerate(rows):
                stats = row_data.get("stats") if isinstance(row_data.get("stats"), dict) else {}
                values = [
                    row_data.get("session_id", ""),
                    row_data.get("started_at", ""),
                    row_data.get("ended_at", ""),
                    row_data.get("status", ""),
                    f"{stats.get('mesh_link_success', 0)}/{stats.get('mesh_link_failed', 0)}",
                    f"{stats.get('channel_busy_success', 0)}/{stats.get('channel_busy_failed', 0)}",
                    stats.get("reconnect_count", 0),
                    row_data.get("mr_name", ""),
                    row_data.get("session_dir", ""),
                ]
                for column, value in enumerate(values):
                    self.history_table.setItem(row, column, QTableWidgetItem(str(value)))
        finally:
            self.history_table.setUpdatesEnabled(True)

    def _schedule_history_refresh(self, refresh_tools: bool = False) -> None:
        if self._history_refresh_pending:
            return
        self._history_refresh_pending = True

        def run() -> None:
            self._fill_history()
            self._refresh_tool_status_once(force=refresh_tools)

        QTimer.singleShot(0, run)

    def _refresh_tool_status_once(self, force: bool = False) -> None:
        if self._tool_status_loaded and not force:
            return
        self._refresh_fping_tool_status()
        self._refresh_iperf_tool_status()
        self._tool_status_loaded = True

    def _refresh_fping_tool_status(self) -> None:
        tool = find_fping_tool(self.paths)
        if tool is None:
            self.fping_tool_label.setText(self.i18n.t("online_mr.fping_tool_missing"))
            self.enable_fping_check.setEnabled(False)
            return
        status = detect_fping_version(tool)
        text = self.i18n.t("online_mr.fping_tool_found")
        if status.version:
            text = f"{text}: fping {status.version}"
        elif status.unknown_version:
            text = f"{text}: {self.i18n.t('online_mr.fping_unknown_version')}"
        self.fping_tool_label.setText(f"{text} ({tool})")
        self.enable_fping_check.setEnabled(True)

    def _refresh_iperf_tool_status(self) -> None:
        tool = find_iperf_tool(self.paths)
        if tool is None:
            self.iperf_tool_label.setText(self.i18n.t("iperf.tool_missing"))
            self.enable_iperf_check.setEnabled(False)
            return
        status = detect_iperf_version(tool)
        text = self.i18n.t("iperf.tool_found")
        if status.version:
            text = f"{text}: iperf {status.version}"
        else:
            text = f"{text}: {self.i18n.t('iperf.unknown_version')}"
        self.iperf_tool_label.setText(f"{text} ({tool})")
        self.enable_iperf_check.setEnabled(True)

    def _upsert_summary(self, snapshot: OnlineMrSnapshot) -> None:
        device_id = self.session_to_device_id.get(snapshot.session_id)
        row_key = str(device_id if device_id is not None else snapshot.session_id)
        row = self._find_row(self.summary_table, row_key, column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
        worker = self.workers.get(snapshot.session_id)
        config = worker.collector.config if worker else None
        host_text = ""
        if config:
            host_text = config.host
            if config.connection_method:
                host_text = f"{host_text} ({config.connection_method})"
        values = [
            config.device_name if config else "",
            host_text,
            snapshot.status,
            snapshot.active_peer,
            snapshot.local_rssi,
            "",
            "",
            snapshot.local_tx_busy,
            snapshot.local_rx_busy,
            "",
            "",
            snapshot.collected_count,
            snapshot.failed_count,
            snapshot.reconnect_count,
            snapshot.last_collection_time,
            snapshot.iperf_mbps,
            snapshot.iperf_retransmits,
            snapshot.iperf_status,
            snapshot.session_id,
            row_key,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(self._status_text(str(value)) if column == SUMMARY_COL_STATUS and value else self._summary_text(value))
            if column in {
                SUMMARY_COL_STATUS,
                SUMMARY_COL_MR_RSSI,
                SUMMARY_COL_CTL_BUSY,
                SUMMARY_COL_TX_BUSY,
                SUMMARY_COL_RX_BUSY,
                SUMMARY_COL_PING_LOSS,
                SUMMARY_COL_PING_LATENCY,
                SUMMARY_COL_COLLECTED,
                SUMMARY_COL_FAILED,
                SUMMARY_COL_RECONNECTS,
                SUMMARY_COL_IPERF_MBPS,
                SUMMARY_COL_IPERF_RETRANS,
            }:
                item.setTextAlignment(Qt.AlignCenter)
            self.summary_table.setItem(row, column, item)

    def _update_summary_iperf(self, device_id: int, row_data: dict[str, object]) -> None:
        row = self._find_row(self.summary_table, str(device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            return
        self.summary_table.setItem(row, SUMMARY_COL_IPERF_MBPS, QTableWidgetItem(f"{float(row_data.get('bitrate_mbps') or 0):.2f}"))
        self.summary_table.setItem(row, SUMMARY_COL_IPERF_RETRANS, QTableWidgetItem(str(row_data.get("retransmits", 0))))
        self.summary_table.setItem(row, SUMMARY_COL_IPERF_STATUS, QTableWidgetItem(self.i18n.t("online_mr.status_collecting")))

    def _update_summary_status_by_device(self, device_id: int | None, status: str) -> None:
        if device_id is None:
            return
        row = self._find_row(self.summary_table, str(device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            return
        item = QTableWidgetItem(self._status_text(status))
        item.setTextAlignment(Qt.AlignCenter)
        self.summary_table.setItem(row, 2, item)

    def _append_mesh_snapshot(self, snapshot: OnlineMrSnapshot) -> None:
        if not snapshot.active_peer:
            return
        row = self.mesh_table.rowCount()
        self.mesh_table.insertRow(row)
        values = [snapshot.last_collection_time, 1, "ACTIVE", snapshot.active_peer, snapshot.local_rssi, snapshot.peer_rssi, "", "", snapshot.local_tx_busy, snapshot.local_rx_busy, "", ""]
        for column, value in enumerate(values):
            self.mesh_table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
        self._trim_table(self.mesh_table)

    def _trim_table(self, table: QTableWidget, max_rows: int = 5000) -> None:
        while table.rowCount() > max_rows:
            table.removeRow(0)

    def _find_row(self, table: QTableWidget, value: str, column: int = 0) -> int:
        for row in range(table.rowCount()):
            item = table.item(row, column)
            if item and item.text() == value:
                return row
        return -1

    def _interval_spin(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setFixedWidth(72)
        spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return spin

    def _no_wheel_spin(self, minimum: int, maximum: int, value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setMaximumWidth(100)
        spin.setMinimumWidth(72)
        spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        spin.setToolTip(self.i18n.t("iperf.no_wheel_hint"))
        return spin

    def _radio_combo(self) -> QComboBox:
        combo = QComboBox()
        for value in (1, 2, 3):
            combo.addItem(str(value), value)
        combo.setFixedWidth(90)
        combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return combo

    def _label(self, key: str) -> QLabel:
        label = QLabel()
        self.labels[key] = label
        label.setMinimumWidth(90)
        return label

    def _text_label(self, key: str) -> QLabel:
        label = QLabel()
        self.text_labels.append((key, label))
        return label

    def _cap_controls(self) -> None:
        for widget, width in (
            (self.status_label, 140),
            (self.fping_device_combo_1, 220),
            (self.fping_device_combo_2, 220),
            (self.fping_target_label_1, 160),
            (self.fping_target_label_2, 160),
            (self.iperf_server_edit, 260),
            (self.iperf_bandwidth_edit, 140),
            (self.iperf_bandwidth_unit_combo, 80),
            (self.iperf_protocol_combo, 100),
            (self.iperf_direction_combo, 140),
            (self.view_device_combo, 260),
        ):
            widget.setMaximumWidth(width)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        for button in (self.start_button, self.stop_selected_button, self.stop_all_button, self.open_button, self.refresh_devices_button):
            button.setMinimumWidth(86)
            button.setMaximumWidth(130)
            button.setMinimumHeight(28)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumWidth(72)
        self.status_label.setMaximumWidth(96)
        self.status_label.setMinimumHeight(28)
        for label in (self.site_label, self.available_metric_label, self.selected_metric_label, self.running_metric_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        for label in (self.fping_status_label_1, self.fping_status_label_2):
            label.setMinimumWidth(150)
            label.setMaximumWidth(240)
            label.setAlignment(Qt.AlignCenter)
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        for combo in (self.fping_device_combo_1, self.fping_device_combo_2):
            combo.setMinimumWidth(220)
            combo.setMaximumWidth(360)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for target in (self.fping_target_label_1, self.fping_target_label_2):
            target.setMinimumWidth(150)
            target.setMaximumWidth(240)
            target.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.iperf_server_edit.setMinimumWidth(220)
        self.iperf_server_edit.setMaximumWidth(340)

    def _period_box(self) -> QGroupBox:
        box = QGroupBox()
        self.collect_param_box = box
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        box.setMinimumHeight(220)
        box.setMaximumHeight(280)
        outer = QGridLayout(box)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setHorizontalSpacing(18)
        outer.setVerticalSpacing(6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        rows = (
            ("online_mr.mesh_link", self.mesh_interval),
            ("online_mr.channel_busy", self.channel_interval),
            ("online_mr.ap_radio_statistics", self.statistics_interval),
            ("online_mr.switch_history", self.switch_interval),
            ("online_mr.interface_rate", self.interface_rate_interval),
        )
        for row, (key, spin) in enumerate(rows):
            label = self._label(key)
            label.setMinimumWidth(100)
            label.setMinimumHeight(28)
            unit = self._text_label("online_mr.seconds")
            unit.setMinimumWidth(24)
            unit.setMinimumHeight(28)
            grid.addWidget(label, row, 0)
            spin.setMinimumHeight(28)
            grid.addWidget(spin, row, 1)
            grid.addWidget(unit, row, 2)
        radio_row = len(rows)
        radio_label = QLabel("Radio")
        radio_label.setMinimumWidth(100)
        radio_label.setMinimumHeight(28)
        self.radio_port.setMinimumHeight(28)
        grid.addWidget(radio_label, radio_row, 0)
        grid.addWidget(self.radio_port, radio_row, 1)
        if self.advanced_box is not None:
            self.advanced_box.setMinimumWidth(260)
            self.advanced_box.setMaximumWidth(320)
            self.advanced_box.setMinimumHeight(190)
            self.advanced_box.setMaximumHeight(240)
            outer.addWidget(self.advanced_box, 0, 1, alignment=Qt.AlignTop)
        outer.addLayout(grid, 0, 0, alignment=Qt.AlignTop)
        outer.setColumnStretch(0, 0)
        outer.setColumnStretch(1, 1)
        return box

    def _radio_box(self) -> QGroupBox:
        box = QGroupBox()
        grid = QGridLayout(box)
        radio_label = QLabel("Radio")
        radio_label.setMinimumWidth(72)
        grid.addWidget(radio_label, 0, 0)
        grid.addWidget(self.radio_port, 0, 1)
        if self.advanced_box is not None:
            grid.addWidget(self.advanced_box, 1, 0, 1, 3)
        grid.setColumnStretch(2, 1)
        return box

    def _ping_box(self) -> QGroupBox:
        box = QGroupBox()
        box.setMinimumHeight(300)
        box.setMaximumHeight(380)
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.enable_fping_check)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        cards.addWidget(self._ping_endpoint_box("Ping 1", self.fping_device_combo_1, self.fping_target_label_1), 1)
        cards.addWidget(self._ping_endpoint_box("Ping 2", self.fping_device_combo_2, self.fping_target_label_2), 1)
        layout.addLayout(cards)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        for row, (key, spin, unit) in enumerate(
            (
                ("online_mr.packet_size", self.fping_packet_size, "online_mr.bytes"),
                ("online_mr.ping_interval_ms", self.fping_interval_ms, "online_mr.milliseconds"),
                ("online_mr.loss_threshold_ms", self.fping_loss_threshold_ms, "online_mr.milliseconds"),
            ),
            start=0,
        ):
            label = self._label(key)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            spin.setFixedWidth(76)
            grid.addWidget(label, row, 0)
            grid.addWidget(spin, row, 1)
            unit_label = self._text_label(unit)
            unit_label.setMinimumWidth(48)
            grid.addWidget(unit_label, row, 2)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        layout.addWidget(self.fping_tool_label)
        for combo in (self.fping_device_combo_1, self.fping_device_combo_2):
            combo.setMinimumWidth(220)
            combo.setMaximumWidth(360)
        for target in (self.fping_target_label_1, self.fping_target_label_2):
            target.setMinimumWidth(160)
            target.setMaximumWidth(260)
            target.setMinimumHeight(28)
            target.setReadOnly(True)
        return box

    def _ping_endpoint_box(self, title: str, combo: QComboBox, target: QLineEdit) -> QGroupBox:
        box = QGroupBox(title)
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        form = QGridLayout(box)
        form.setContentsMargins(8, 8, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        device_label = QLabel("设备")
        device_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        target_label = QLabel("目标IP")
        target_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.addWidget(device_label, 0, 0)
        form.addWidget(combo, 0, 1)
        form.addWidget(target_label, 1, 0)
        form.addWidget(target, 1, 1)
        form.setColumnStretch(1, 1)
        return box

    def _iperf_box(self) -> QGroupBox:
        box = QGroupBox()
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid = QGridLayout(box)
        grid.addWidget(self.enable_iperf_check, 0, 0, 1, 3)
        grid.addWidget(self._label("iperf.server_address"), 1, 0)
        grid.addWidget(self.iperf_server_edit, 1, 1, 1, 2)
        rows = (
            ("iperf.port", self.iperf_port_spin, None),
            ("iperf.protocol", self.iperf_protocol_combo, None),
            ("iperf.direction", self.iperf_direction_combo, None),
            ("iperf.parallel", self.iperf_parallel_spin, None),
            ("iperf.interval", self.iperf_interval_spin, "online_mr.seconds"),
            ("iperf.duration", self.iperf_duration_spin, "online_mr.seconds"),
        )
        for row, (key, widget, unit) in enumerate(rows, start=2):
            grid.addWidget(self._label(key), row, 0)
            grid.addWidget(widget, row, 1)
            if unit:
                grid.addWidget(self._text_label(unit), row, 2)
        bandwidth_row = 8
        bandwidth_layout = QHBoxLayout()
        bandwidth_layout.addWidget(self.iperf_bandwidth_edit)
        bandwidth_layout.addWidget(self.iperf_bandwidth_unit_combo)
        grid.addWidget(self._label("iperf.target_bandwidth"), bandwidth_row, 0)
        grid.addLayout(bandwidth_layout, bandwidth_row, 1, 1, 2)
        grid.addWidget(self.iperf_bandwidth_hint_label, 9, 1, 1, 2)
        grid.addWidget(self.iperf_follow_check, 10, 0, 1, 3)
        grid.addWidget(self._label("online_mr.tool_status"), 11, 0)
        grid.addWidget(self.iperf_tool_label, 11, 1, 1, 2)
        return box

    def _fill_iperf_direction_combo(self) -> None:
        current = self.iperf_direction_combo.currentData() or "upload"
        self.iperf_direction_combo.blockSignals(True)
        self.iperf_direction_combo.clear()
        self.iperf_direction_combo.addItem(self.i18n.t("iperf.upload"), "upload")
        self.iperf_direction_combo.addItem(self.i18n.t("iperf.download"), "download")
        self.iperf_direction_combo.addItem(self.i18n.t("iperf.bidirectional"), "bidirectional")
        index = self.iperf_direction_combo.findData(current)
        self.iperf_direction_combo.setCurrentIndex(index if index >= 0 else 0)
        self.iperf_direction_combo.blockSignals(False)

    def _advanced_box(self) -> QGroupBox:
        box = QGroupBox()
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        box.setMinimumWidth(260)
        box.setMaximumWidth(320)
        box.setMinimumHeight(190)
        box.setMaximumHeight(240)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setText(self.i18n.t("online_mr.expand_advanced"))
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.advanced_summary_label.setWordWrap(True)
        self.advanced_summary_label.setMinimumHeight(44)
        self.advanced_summary_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced_summary_label)
        detail_grid = QGridLayout(self.advanced_detail)
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setHorizontalSpacing(8)
        detail_grid.setVerticalSpacing(6)
        self.auto_reconnect_check.setMinimumHeight(24)
        detail_grid.addWidget(self.auto_reconnect_check, 0, 0, 1, 3)
        for row, (label_key, spin, unit_key) in enumerate(
            (
                ("online_mr.reconnect_interval", self.reconnect_interval, "online_mr.seconds"),
                ("online_mr.max_reconnect", self.max_reconnect, None),
                ("online_mr.duration_minutes", self.duration_minutes, "online_mr.minutes"),
            ),
            start=1,
        ):
            label = self._text_label(label_key)
            label.setMinimumHeight(26)
            spin.setFixedWidth(76)
            spin.setMinimumHeight(26)
            detail_grid.addWidget(label, row, 0)
            detail_grid.addWidget(spin, row, 1)
            if unit_key:
                unit = self._text_label(unit_key)
                unit.setMinimumWidth(24)
                unit.setMinimumHeight(26)
                detail_grid.addWidget(unit, row, 2)
        detail_grid.setColumnStretch(0, 0)
        detail_grid.setColumnStretch(1, 0)
        detail_grid.setColumnStretch(2, 1)
        self.advanced_detail.setVisible(False)
        layout.addWidget(self.advanced_detail)
        return box

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_detail.setVisible(expanded)
        self.advanced_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.advanced_toggle.setText(self.i18n.t("online_mr.collapse_advanced" if expanded else "online_mr.expand_advanced"))

    def _update_advanced_summary(self) -> None:
        duration = self.i18n.t("online_mr.manual_stop") if self.duration_minutes.value() == 0 else f"{self.duration_minutes.value()} {self.i18n.t('online_mr.minutes')}"
        reconnect = self.i18n.t("online_mr.enabled" if self.auto_reconnect_check.isChecked() else "online_mr.disabled")
        self.advanced_summary_label.setText(
            f"{self.i18n.t('online_mr.auto_reconnect')}: {reconnect}\n"
            f"{self.i18n.t('online_mr.reconnect_interval')}: {self.reconnect_interval.value()} {self.i18n.t('online_mr.seconds')}；"
            f"{self.i18n.t('online_mr.duration_minutes')}: {duration}"
        )

    def _configure_online_table(self, table: QTableWidget) -> None:
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.verticalHeader().setDefaultSectionSize(32)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        table.setMinimumHeight(260 if table is self.device_table else 250 if table is not self.summary_table else 120)
        if table is self.device_table:
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
            table.setColumnWidth(0, 48)
            for column, width in ((1, 210), (2, 130), (3, 65), (4, 60), (5, 85), (6, 70), (7, 90), (8, 90)):
                table.setColumnWidth(column, width)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    def _load_all_table_widths(self) -> None:
        tables = {
            "session_summary": self.summary_table,
            "mesh_link": self.mesh_table,
            "channel_busy": self.channel_table,
            "statistics": self.events_table,
            "interface_rate": self.interface_rate_table,
            "iperf": self.iperf_table,
            "history_sessions": self.history_table,
        }
        defaults = {
            "session_summary": [160, 120, 90, 160, 80, 120, 80, 80, 80, 90, 110, 80, 80, 80, 160, 100, 80, 90, 160, 70],
            "mesh_link": [180, 90, 110, 180, 90, 90, 110, 110, 90, 90, 100, 110],
            "channel_busy": [180, 90, 90, 90, 360],
            "statistics": [180, 120, 90, 180, 180, 320],
            "interface_rate": [180, 110, 180, 120, 100, 360],
            "iperf": [180, 100, 90, 120, 520],
            "history_sessions": [170, 170, 170, 110, 120, 120, 100, 120, 360],
        }
        for name, table in tables.items():
            widths = self.settings.get_value(TABLE_WIDTH_KEYS[name], defaults[name])
            if not isinstance(widths, list):
                widths = defaults[name]
            for column, width in enumerate(widths[: table.columnCount()]):
                table.setColumnWidth(column, int(width))
            table.horizontalHeader().sectionResized.connect(lambda _idx, _old, _new, n=name, t=table: self._save_table_widths(n, t))

    def _save_table_widths(self, name: str, table: QTableWidget) -> None:
        widths = [table.columnWidth(column) for column in range(table.columnCount())]
        self.settings.set_value(TABLE_WIDTH_KEYS[name], widths)

    def _set_status(self, status: str) -> None:
        self.status_value = status
        self.status_label.setText(self._status_text(status))
        color = {
            "COLLECTING": "#1f7a4d",
            "CONNECTING": "#2563eb",
            "INITIALIZING": "#2563eb",
            "RECONNECTING": "#b45309",
            "STOPPING": "#b45309",
            "FAILED": "#b91c1c",
            "ABORTED": "#b91c1c",
            "STOPPED": "#475569",
        }.get(status, "#475569")
        self.status_label.setStyleSheet(f"QLabel {{ border-radius: 4px; padding: 4px 8px; background: {color}; color: white; }}")
        self._update_action_state()

    def _status_text(self, status: str) -> str:
        return self.i18n.t(STATUS_I18N_KEYS.get(status, "online_mr.status_stopped"))

    @staticmethod
    def _summary_text(value: object) -> str:
        if value is None:
            return "-"
        text = str(value).strip()
        return text if text else "-"


def _snapshot_time(value: object) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace(" ", "T"))
        except ValueError:
            pass
    return datetime.now()


def _normalize_mac_key(value: object) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", str(value or "")).lower()
    return compact if len(compact) == 12 else ""
