from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QDoubleValidator
from PySide6.QtWidgets import (
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
from netconsole.services.fping_v3 import detect_fping_version, find_fping_tool
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfResultStore, build_iperf_client_args, normalize_bandwidth_text
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool
from netconsole.services.online_mr_collector import OnlineMrCollectionManager
from netconsole.services.online_mr_session_store import OnlineMrSession, OnlineMrSessionStore
from netconsole.ui.fping_worker import FpingProbeWorker
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


class OnlineMrUiThrottle:
    def __init__(self, interval_ms: int = 500) -> None:
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


def normalize_device_type(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def is_fat_ap_device(value: str | None) -> bool:
    return normalize_device_type(value) == "FATAP"


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
    return parts, str(device.ip_address or ""), int(device.id or 0)


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
        self.fping_workers: dict[str, FpingProbeWorker] = {}
        self.iperf_workers: dict[str, IperfProcessWorker] = {}
        self.session_dirs: dict[str, Path] = {}
        self.session_to_device_id: dict[str, int] = {}
        self.workers_by_device_id: dict[int, OnlineMrCollectorWorker] = {}
        self.fping_workers_by_device_id: dict[int, FpingProbeWorker] = {}
        self.iperf_workers_by_device_id: dict[int, IperfProcessWorker] = {}
        self.latest_iperf_by_device_id: dict[int, dict[str, object]] = {}
        self.parse_worker: OnlineMrParseWorker | None = None
        self.last_session_dir_by_device_id: dict[int, Path] = {}
        self.throttle = OnlineMrUiThrottle(500)
        self._updating_device_checks = False

        self.site_label = QLabel()
        self.available_device_count_label = QLabel()
        self.selected_device_count_label = QLabel()
        self.running_count_label = QLabel()
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
        self.channel_radio = self._radio_combo()
        self.statistics_radio = self._radio_combo()
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

        self.summary_table = QTableWidget(0, 19)
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
        self.store.mark_stale_sessions_aborted(site_name)
        self.refresh_all()
        self.refresh_timer.start()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.set_site(site_name)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.store.mark_stale_sessions_aborted(site_name)
        self.refresh_all()

    def refresh_all(self) -> None:
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self.devices = self.repository.list()
        self._load_device_groups()
        self._fill_devices()
        self._fill_view_devices()
        self._fill_history()
        self._update_action_state()

    def retranslate(self) -> None:
        if self.connection_box:
            self.connection_box.setTitle(self.i18n.t("online_mr.connection"))
        if self.period_box:
            self.period_box.setTitle(self.i18n.t("online_mr.collection_period"))
        if self.radio_box:
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
                "Peer RSSI",
                "MR TxBusy",
                "MR RxBusy",
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
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(8)
        scroll.setWidget(content)
        root.addWidget(scroll)

        controls = QGroupBox()
        self.connection_box = controls
        form = QGridLayout(controls)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self._cap_controls()
        form.addWidget(self.site_label, 0, 0, 1, 2)
        form.addWidget(self._label("online_mr.available_devices"), 0, 2)
        form.addWidget(self.available_device_count_label, 0, 3)
        form.addWidget(self._label("online_mr.selected_devices"), 0, 4)
        form.addWidget(self.selected_device_count_label, 0, 5)
        form.addWidget(self._label("online_mr.running_collectors"), 0, 6)
        form.addWidget(self.running_count_label, 0, 7)
        form.addWidget(self._label("online_mr.status"), 0, 8)
        form.addWidget(self.status_label, 0, 9)
        actions = QHBoxLayout()
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_selected_button)
        actions.addWidget(self.stop_all_button)
        actions.addWidget(self.open_button)
        actions.addWidget(self.refresh_devices_button)
        actions.addStretch(1)
        form.addLayout(actions, 1, 0, 1, 10)
        form.addWidget(self.filter_hint_label, 2, 0, 1, 10)
        content_layout.addWidget(controls)

        self.device_table.setMinimumHeight(150)
        self.device_table.setMaximumHeight(220)
        self._configure_online_table(self.device_table)
        content_layout.addWidget(self.device_table)

        settings_row = QHBoxLayout()
        left_settings = QVBoxLayout()
        self.period_box = self._period_box()
        self.radio_box = self._radio_box()
        left_settings.addWidget(self.period_box)
        left_settings.addWidget(self.radio_box)
        right_settings = QVBoxLayout()
        self.ping_box = self._ping_box()
        self.iperf_box = self._iperf_box()
        self.advanced_box = self._advanced_box()
        right_settings.addWidget(self.ping_box)
        right_settings.addWidget(self.iperf_box)
        right_settings.addWidget(self.advanced_box)
        settings_row.addLayout(left_settings, 1)
        settings_row.addLayout(right_settings, 1)
        content_layout.addLayout(settings_row)

        main_splitter = QSplitter(Qt.Vertical)
        self.summary_table.setMinimumHeight(120)
        self.summary_table.setMaximumHeight(180)
        main_splitter.addWidget(self.summary_table)
        view_row = QWidget()
        view_layout = QHBoxLayout(view_row)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.addWidget(self._text_label("online_mr.view_device"))
        view_layout.addWidget(self.view_device_combo)
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
        self.tabs.setMinimumHeight(300)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(view_row)
        detail_layout.addWidget(self.tabs)
        main_splitter.addWidget(detail)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        content_layout.addWidget(main_splitter, 1)
        self.retranslate()
        self._load_all_table_widths()

    def _connect_signals(self) -> None:
        self.device_table.itemChanged.connect(self._device_item_changed)
        self.start_button.clicked.connect(self.start_collection)
        self.stop_selected_button.clicked.connect(self.stop_selected)
        self.stop_all_button.clicked.connect(self.stop_all)
        self.open_button.clicked.connect(self.open_selected_session_dir)
        self.refresh_devices_button.clicked.connect(self.refresh_all)
        self.parse_session_button.clicked.connect(self.parse_selected_session)

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
        if self.enable_fping_check.isChecked() and not self.fping_target_edit.text().strip():
            self.log_text.append(self.i18n.t("online_mr.ping_target_empty"))
        if started:
            self._set_status("CONNECTING")
        self._update_action_state()

    def stop_selected(self) -> None:
        for device in self._selected_devices():
            if device.id is None:
                continue
            iperf_worker = self.iperf_workers_by_device_id.get(device.id)
            if iperf_worker:
                iperf_worker.stop()
            fping_worker = self.fping_workers_by_device_id.get(device.id)
            if fping_worker:
                fping_worker.stop()
            worker = self.workers_by_device_id.get(device.id)
            if worker:
                worker.cancel()
                self._update_device_status(device.id, self.i18n.t("online_mr.status_stopping"))
        self._update_action_state()

    def stop_all(self) -> None:
        for worker in list(self.iperf_workers_by_device_id.values()):
            worker.stop()
        for worker in list(self.fping_workers_by_device_id.values()):
            worker.stop()
        for device_id, worker in list(self.workers_by_device_id.items()):
            worker.cancel()
            self._update_device_status(device_id, self.i18n.t("online_mr.status_stopping"))
        self._update_action_state()

    def open_selected_session_dir(self) -> None:
        selected = self._selected_devices()
        path = None
        if len(selected) == 1 and selected[0].id in self.last_session_dir_by_device_id:
            path = self.last_session_dir_by_device_id.get(selected[0].id)
        else:
            row = self.summary_table.currentRow()
            session_id = self.summary_table.item(row, 17).text() if row >= 0 and self.summary_table.item(row, 17) else ""
            path = self.session_dirs.get(session_id)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def parse_selected_session(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), self.i18n.t("online_mr.select_history_session"))
            return
        item = self.history_table.item(row, 8)
        if item is None or not item.text():
            return
        session_dir = Path(item.text())
        self.parse_session_button.setEnabled(False)
        self.parse_worker = OnlineMrParseWorker(session_dir, parent=self)
        self.parse_worker.completed.connect(lambda summary, d=session_dir: self._parse_completed(d, summary))
        self.parse_worker.failed.connect(self._parse_failed)
        self.parse_worker.start()

    def _parse_completed(self, session_dir: Path, summary) -> None:
        self.parse_session_button.setEnabled(True)
        self.log_text.append(
            self.i18n.t(
                "online_mr.parse_done",
                segments=summary.active_segments,
                ping=summary.ping_samples,
                iperf=summary.iperf_samples,
                issues=summary.issues,
            )
        )
        self._load_diagnosis_results(session_dir)
        self.tabs.setCurrentWidget(self.diagnosis_table)
        self.parse_worker = None

    def _parse_failed(self, message: str) -> None:
        self.parse_session_button.setEnabled(True)
        self.parse_worker = None
        QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), message)

    def _load_diagnosis_results(self, session_dir: Path) -> None:
        import sqlite3

        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        self.diagnosis_table.setRowCount(0)
        if not db_path.exists():
            return
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
                self.diagnosis_table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))

    def _worker_started(self, meta, worker: OnlineMrCollectorWorker) -> None:
        self.manager.register(meta.session_id, worker)
        if meta.device_id is not None:
            self.manager.register_device(int(meta.device_id), worker)
            self.session_to_device_id[meta.session_id] = int(meta.device_id)
            self.workers_by_device_id[int(meta.device_id)] = worker
        self.workers[meta.session_id] = worker
        if meta.session_dir:
            self.session_dirs[meta.session_id] = Path(meta.session_dir)
            if meta.device_id is not None:
                self.last_session_dir_by_device_id[int(meta.device_id)] = Path(meta.session_dir)
        self._start_fping_worker(meta, worker)
        self._start_iperf_worker(meta, worker)
        self._set_status(meta.status)
        if meta.device_id is not None:
            self._update_device_status(int(meta.device_id), self._status_text(meta.status))
        self._fill_view_devices()
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
        self.workers.pop(session_id, None)
        self.fping_workers.pop(session_id, None)
        self.iperf_workers.pop(session_id, None)
        self._set_status("STOPPED" if not self.workers_by_device_id else "COLLECTING")
        self._fill_view_devices()
        self._fill_history()
        self._update_action_state()

    def _worker_failed(self, message: str, device_id: int | None = None) -> None:
        if device_id is not None:
            self._update_device_status(device_id, self.i18n.t("online_mr.status_failed"))
            self.workers_by_device_id.pop(device_id, None)
            self.iperf_workers_by_device_id.pop(device_id, None)
            self.manager.unregister_device(device_id)
        self._set_status("FAILED" if not self.workers_by_device_id else "COLLECTING")
        self._update_action_state()
        QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), message)

    def _start_fping_worker(self, meta, ssh_worker: OnlineMrCollectorWorker) -> None:
        config = ssh_worker.collector.config.fping.normalized()
        if not config.enabled or not config.target or meta.session_dir is None:
            return
        tool = find_fping_tool(self.paths)
        if tool is None:
            self.log_text.append(self.i18n.t("online_mr.fping_tool_missing"))
            return
        session = OnlineMrSession(Path(meta.session_dir), meta)
        worker = FpingProbeWorker(session, config, tool, parent=self)
        worker.failed.connect(lambda message: self.log_text.append(f"Fping: {message}"))
        worker.completed.connect(lambda _status, session_id=meta.session_id, device_id=meta.device_id: self._fping_completed(session_id, device_id))
        self.fping_workers[meta.session_id] = worker
        if meta.device_id is not None:
            self.fping_workers_by_device_id[int(meta.device_id)] = worker
        worker.start()

    def _fping_completed(self, session_id: str, device_id: int | None) -> None:
        self.fping_workers.pop(session_id, None)
        if device_id is not None:
            self.fping_workers_by_device_id.pop(int(device_id), None)

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
        store = IperfResultStore(session_dir / "parsed" / "online_diagnosis.sqlite")
        worker = IperfProcessWorker(tool, command, log_file, store=store, session_id=meta.session_id, device_id=meta.device_id, config=client_config, mode="client", parent=self)
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

    def _flush_snapshot(self) -> None:
        snapshot = self.throttle.flush()
        if snapshot is None:
            return
        self._set_status(snapshot.status)
        self._upsert_summary(snapshot)
        self._append_mesh_snapshot(snapshot)

    def _build_config_for_device(self, device: Device) -> OnlineMrConnectionConfig | None:
        if device.id is None:
            return None
        protocol, port, username, password = connection_fields_from_device(device)
        host = str(device.ip_address or "").strip()
        if not host or not username or not password:
            return None
        safe_name = safe_device_folder_name(device)
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
                enabled=self.enable_fping_check.isChecked(),
                target=self.fping_target_edit.text().strip(),
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
        self.device_table.setRowCount(0)
        for device in self.filtered_devices:
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            check_item = QTableWidgetItem("")
            check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            check_item.setCheckState(Qt.Checked if device.id in checked_ids else Qt.Unchecked)
            self.device_table.setItem(row, 0, check_item)
            protocol, port, username, _password = connection_fields_from_device(device)
            values = [
                device.name,
                device.ip_address,
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
        self._updating_device_checks = False
        self.available_device_count_label.setText(str(len(self.filtered_devices)))
        self.filter_hint_label.setText("" if self.filtered_devices else self.i18n.t("online_mr.no_vehicle_fat_ap"))
        self._update_selected_count()

    def _load_device_groups(self) -> None:
        groups = DeviceGroupRepository(self.repository.database, self.site_name).list()
        self.device_groups = {int(group.id): group.name for group in groups if group.id is not None}

    def _is_vehicle_fat_ap(self, device: Device) -> bool:
        group_name = self.device_groups.get(int(device.group_id or 0), "")
        return group_name == "车载" and is_fat_ap_device(device.device_type)

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
        selected = self._selected_devices()
        if len(selected) > 2:
            self._updating_device_checks = True
            item.setCheckState(Qt.Unchecked)
            self._updating_device_checks = False
            QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), self.i18n.t("online_mr.max_two_devices"))
        self._update_selected_count()
        self._update_action_state()

    def _update_selected_count(self) -> None:
        self.selected_device_count_label.setText(str(len(self._selected_devices())))
        self.running_count_label.setText(str(self.manager.running_count()))

    def _update_action_state(self) -> None:
        selected = self._selected_devices()
        selected_ids = {device.id for device in selected if device.id is not None}
        running_selected = any(device_id in self.workers_by_device_id for device_id in selected_ids)
        can_start = bool(selected) and len(selected) <= 2 and self.manager.running_count() < self.manager.max_concurrent
        self.start_button.setEnabled(can_start)
        self.stop_selected_button.setEnabled(running_selected)
        self.stop_all_button.setEnabled(bool(self.workers_by_device_id))
        self.running_count_label.setText(str(self.manager.running_count()))

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

    def _fill_view_devices(self) -> None:
        current = self.view_device_combo.currentData()
        self.view_device_combo.blockSignals(True)
        self.view_device_combo.clear()
        seen: set[int] = set()
        for device in self.filtered_devices:
            if device.id is None:
                continue
            seen.add(int(device.id))
            self.view_device_combo.addItem(device.name, int(device.id))
        for device_id in self.workers_by_device_id:
            if device_id not in seen:
                self.view_device_combo.addItem(str(device_id), device_id)
        index = self.view_device_combo.findData(current)
        self.view_device_combo.setCurrentIndex(index if index >= 0 else 0)
        self.view_device_combo.blockSignals(False)

    def _fill_history(self) -> None:
        rows = self.store.list_sessions(self.site_name, None)
        self.history_table.setRowCount(0)
        for row_data in rows:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
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
        self._refresh_fping_tool_status()
        self._refresh_iperf_tool_status()

    def _refresh_fping_tool_status(self) -> None:
        tool = find_fping_tool(self.paths)
        if tool is None:
            self.fping_tool_label.setText(self.i18n.t("online_mr.fping_tool_missing"))
            self.enable_fping_check.setEnabled(False)
            return
        status = detect_fping_version(tool)
        text = self.i18n.t("online_mr.fping_tool_found")
        if status.version:
            text = f"{text}: Fast Pinger {status.version}"
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
        row = self._find_row(self.summary_table, row_key, column=18)
        if row < 0:
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
        worker = self.workers.get(snapshot.session_id)
        config = worker.collector.config if worker else None
        values = [
            config.device_name if config else "",
            config.host if config else "",
            snapshot.status,
            snapshot.active_peer,
            snapshot.local_rssi,
            snapshot.peer_rssi,
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
            item = QTableWidgetItem("" if value is None else (self._status_text(str(value)) if column == 2 else str(value)))
            if column in {2, 4, 5, 6, 7, 8, 9, 10, 11, 12}:
                item.setTextAlignment(Qt.AlignCenter)
            self.summary_table.setItem(row, column, item)

    def _update_summary_iperf(self, device_id: int, row_data: dict[str, object]) -> None:
        row = self._find_row(self.summary_table, str(device_id), column=18)
        if row < 0:
            return
        self.summary_table.setItem(row, 14, QTableWidgetItem(f"{float(row_data.get('bitrate_mbps') or 0):.2f}"))
        self.summary_table.setItem(row, 15, QTableWidgetItem(str(row_data.get("retransmits", 0))))
        self.summary_table.setItem(row, 16, QTableWidgetItem(self.i18n.t("online_mr.status_collecting")))

    def _append_mesh_snapshot(self, snapshot: OnlineMrSnapshot) -> None:
        if not snapshot.active_peer:
            return
        row = self.mesh_table.rowCount()
        self.mesh_table.insertRow(row)
        values = [snapshot.last_collection_time, 1, "ACTIVE", snapshot.active_peer, snapshot.local_rssi, snapshot.peer_rssi, "", "", snapshot.local_tx_busy, snapshot.local_rx_busy, "", ""]
        for column, value in enumerate(values):
            self.mesh_table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))

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
        spin.setMaximumWidth(100)
        spin.setMinimumWidth(72)
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
        combo.setMaximumWidth(100)
        combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return combo

    def _label(self, key: str) -> QLabel:
        label = QLabel()
        self.labels[key] = label
        label.setMinimumWidth(72)
        return label

    def _text_label(self, key: str) -> QLabel:
        label = QLabel()
        self.text_labels.append((key, label))
        return label

    def _cap_controls(self) -> None:
        for widget, width in (
            (self.status_label, 140),
            (self.fping_target_edit, 260),
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
            button.setMinimumWidth(96)
            button.setMaximumWidth(130)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumHeight(28)

    def _period_box(self) -> QGroupBox:
        box = QGroupBox()
        grid = QGridLayout(box)
        rows = (
            ("online_mr.mesh_link", self.mesh_interval),
            ("online_mr.channel_busy", self.channel_interval),
            ("online_mr.ap_radio_statistics", self.statistics_interval),
            ("online_mr.switch_history", self.switch_interval),
            ("online_mr.interface_rate", self.interface_rate_interval),
        )
        for row, (key, spin) in enumerate(rows):
            grid.addWidget(self._label(key), row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(self._text_label("online_mr.seconds"), row, 2)
        grid.setColumnStretch(3, 1)
        return box

    def _radio_box(self) -> QGroupBox:
        box = QGroupBox()
        grid = QGridLayout(box)
        grid.addWidget(self._label("online_mr.channel_busy_radio"), 0, 0)
        grid.addWidget(self.channel_radio, 0, 1)
        grid.addWidget(self._label("online_mr.statistics_radio"), 1, 0)
        grid.addWidget(self.statistics_radio, 1, 1)
        grid.setColumnStretch(2, 1)
        return box

    def _ping_box(self) -> QGroupBox:
        box = QGroupBox()
        grid = QGridLayout(box)
        grid.addWidget(self.enable_fping_check, 0, 0, 1, 3)
        grid.addWidget(self._label("online_mr.ping_target"), 1, 0)
        grid.addWidget(self.fping_target_edit, 1, 1, 1, 2)
        for row, (key, spin, unit) in enumerate(
            (
                ("online_mr.packet_size", self.fping_packet_size, "online_mr.bytes"),
                ("online_mr.ping_interval_ms", self.fping_interval_ms, "online_mr.milliseconds"),
                ("online_mr.loss_threshold_ms", self.fping_loss_threshold_ms, "online_mr.milliseconds"),
            ),
            start=2,
        ):
            grid.addWidget(self._label(key), row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(self._text_label(unit), row, 2)
        grid.addWidget(self._label("online_mr.tool_status"), 5, 0)
        grid.addWidget(self.fping_tool_label, 5, 1, 1, 2)
        return box

    def _iperf_box(self) -> QGroupBox:
        box = QGroupBox()
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
        layout = QVBoxLayout(box)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setText(self.i18n.t("online_mr.expand_advanced"))
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.advanced_summary_label.setWordWrap(True)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced_summary_label)
        form = QFormLayout(self.advanced_detail)
        form.addRow(self.auto_reconnect_check)
        form.addRow(self._text_label("online_mr.reconnect_interval"), self.reconnect_interval)
        form.addRow(self._text_label("online_mr.max_reconnect"), self.max_reconnect)
        form.addRow(self._text_label("online_mr.duration_minutes"), self.duration_minutes)
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
            self.i18n.t(
                "online_mr.advanced_summary",
                reconnect=reconnect,
                interval=self.reconnect_interval.value(),
                duration=duration,
            )
        )

    def _configure_online_table(self, table: QTableWidget) -> None:
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.verticalHeader().setDefaultSectionSize(max(table.fontMetrics().height() + 10, 30))
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        table.setMinimumHeight(250 if table is not self.summary_table else 120)

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
            "session_summary": [160, 110, 110, 180, 90, 90, 95, 95, 90, 90, 90, 90, 90, 180, 90, 90, 110, 180, 90],
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
