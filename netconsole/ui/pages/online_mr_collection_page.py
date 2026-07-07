from __future__ import annotations

import re
import json
import os
import subprocess
import time
import traceback
import weakref
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QIntValidator, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
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

from netconsole.core import app_logger
from netconsole.core.feature_flags import FeatureGate, apply_feature_to_widget, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.shutdown_manager import shutdown_manager
from netconsole.models.device import Device
from netconsole.models.online_mr_models import (
    STATE_COLLECTING,
    STATE_CONNECTING,
    STATE_FORCED_STOPPED,
    STATE_INITIALIZING,
    STATE_RECONNECTING,
    STATE_STOPPING,
    FpingConfig,
    IperfTrafficConfig,
    OnlineMrConnectionConfig,
    OnlineMrIntervals,
    OnlineMrRadioConfig,
    OnlineMrSnapshot,
    OnlineMrTaskToggles,
)
from netconsole.services.fping_v5 import detect_fping_version, find_fping_tool
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.network_tools.iperf_runner import (
    FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
    IperfClientConfig,
    build_iperf_client_args,
    run_iperf_client_preflight,
)
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.online_mr_collector import OnlineMrCollectionManager
from netconsole.services.online_mr_parser import parse_ap_radio_statistics_text, parse_channel_busy_text, parse_mesh_link_text, parse_switch_history_text, summarize_active
from netconsole.services.online_mr_session_store import OnlineMrSession, OnlineMrSessionStore
from netconsole.services.online_mr.core.event_model import (
    EVENT_BUSY_SAMPLE,
    EVENT_INTERFACE_SAMPLE,
    EVENT_IPERF3_ERROR,
    EVENT_IPERF3_SAMPLE,
    EVENT_LINK_SWITCH,
    EVENT_MESH_SAMPLE,
    EVENT_STATS_SAMPLE,
    OnlineMrEvent,
)
from netconsole.services.online_mr.core.realtime_model import PingConfig, RealtimeMRState, build_realtime_state
from netconsole.services.online_mr.core.realtime_cache import OnlineMrRealtimeCache
from netconsole.services.online_mr.core.realtime_parser import OnlineMrRealtimeParser
from netconsole.services.online_mr.db.event_writer import EventWriter
from netconsole.services.online_mr.ping_presets import DEFAULT_PING_PRESET_KEY, get_ping_preset, list_ping_presets
from netconsole.services.online_mr.traffic_presets import DEFAULT_TRAFFIC_PRESET_KEY, DEFAULT_TRAFFIC_PRESET_PORT, get_traffic_preset, list_traffic_presets
from netconsole.services.online_mr.diagnosis_engine import OnlineMrDiagnosisEngine
from netconsole.services.online_mr.event_bus import OnlineMrEventBus
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine
from netconsole.services.online_mr.realtime.sliding_window_buffer import SlidingWindowBuffer
from netconsole.services.online_mr.workers.fping_v5_worker import FpingV5ProbeWorker
from netconsole.services.ap_radio_mapping_service import ApRadioMappingService
from netconsole.utils.station_normalize import normalize_station_value
from netconsole.ui.iperf_worker import IperfProcessWorker
from netconsole.ui.online_mr_collector_worker import OnlineMrCollectorWorker
from netconsole.ui.online_mr_parse_worker import OnlineMrAnalysisLoadWorker, OnlineMrParseWorker, OnlineMrReportExportWorker
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.table_utils import apply_analysis_table_style, auto_fit_table_columns, configure_readonly_table, make_table_item
from netconsole.ui.widgets.online_mr_analysis_chart_widget import OnlineMrAnalysisChartWidget
from netconsole.ui.widgets.no_wheel import NoWheelComboBox, NoWheelSpinBox
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate, is_checked_value, set_table_row_checked


TABLE_WIDTH_KEYS = {
    "session_summary": "online_mr/table_widths/session_summary",
    "mesh_link": "online_mr/table_widths/mesh_link",
    "mesh_link_detail": "online_mr/table_widths/mesh_link_detail",
    "channel_busy": "online_mr/table_widths/channel_busy",
    "statistics": "online_mr/table_widths/statistics",
    "switch_history": "online_mr/table_widths/switch_history",
    "active_link_switch_logs": "online_mr/table_widths/active_link_switch_logs",
    "interface_rate": "online_mr/table_widths/interface_rate",
    "fping_1s": "online_mr/table_widths/fping_1s",
    "iperf": "online_mr/table_widths/iperf",
    "diagnosis": "online_mr/table_widths/diagnosis",
    "history_sessions": "online_mr/table_widths/history_sessions",
}

ONLINE_MR_PAGE_MIN_WIDTH = 1080
ONLINE_MR_WORK_PANEL_MIN_WIDTH = 1040
ONLINE_MR_LEFT_PANEL_MIN_WIDTH = 620
ONLINE_MR_RIGHT_PANEL_MIN_WIDTH = 420
SPLITTER_SIZES_KEY = "online_mr/realtime_vertical_splitter_sizes"
PARAM_PANEL_COLLAPSED_KEY = "online_mr/parameter_panel_collapsed"
FORCE_STOP_DELAY_SECONDS = 5
BATCH_STOP_TIMEOUT_SECONDS = 30
DEFAULT_REALTIME_SPLITTER_SIZES = [380, 150, 160, 320]

STATUS_I18N_KEYS = {
    "CREATED": "online_mr.status_created",
    "CONNECTING": "online_mr.status_connecting",
    "INITIALIZING": "online_mr.status_initializing",
    "COLLECTING": "online_mr.status_collecting",
    "RECONNECTING": "online_mr.status_reconnecting",
    "STOPPING": "online_mr.status_stopping",
    "STOPPED": "online_mr.status_stopped",
    "FORCED_STOPPED": "online_mr.status_stopped",
    "FAILED": "online_mr.status_failed",
    "ABORTED": "online_mr.status_aborted",
}
ACTIVE_UI_STATES = {STATE_CONNECTING, STATE_INITIALIZING, STATE_COLLECTING, STATE_RECONNECTING, STATE_STOPPING}

SUMMARY_COL_DEVICE_NAME = 0
SUMMARY_COL_HOST = 1
SUMMARY_COL_STATUS = 2
SUMMARY_COL_ACTIVE_PEER = 3
SUMMARY_COL_PEER_MAC = 4
SUMMARY_COL_MR_RSSI = 5
SUMMARY_COL_PEER_SITE = 6
SUMMARY_COL_PEER_SECTION = 7
SUMMARY_COL_PING_LOSS = 8
SUMMARY_COL_PING_LATENCY = 9
SUMMARY_COL_COLLECTED = 10
SUMMARY_COL_FAILED = 11
SUMMARY_COL_RECONNECTS = 12
SUMMARY_COL_LAST_COLLECTION = 13
SUMMARY_COL_IPERF_MBPS = 14
SUMMARY_COL_IPERF_RETRANS = 15
SUMMARY_COL_SESSION = 16
SUMMARY_COL_DEVICE_ID = 17


def _rail_mrcollect_diag(message: str) -> None:
    print(message)
    app_logger.log_info("RAIL_MR_COLLECT_UI", message)


@dataclass
class OnlineMrRuntimeSiteState:
    workers: dict[str, OnlineMrCollectorWorker] = field(default_factory=dict)
    fping_workers: dict[str, FpingV5ProbeWorker] = field(default_factory=dict)
    iperf_workers: dict[str, IperfProcessWorker] = field(default_factory=dict)
    iperf_batch_workers: dict[tuple[object, ...], IperfProcessWorker] = field(default_factory=dict)
    iperf_batch_sessions: dict[tuple[object, ...], set[str]] = field(default_factory=dict)
    session_dirs: dict[str, Path] = field(default_factory=dict)
    session_to_device_id: dict[str, int] = field(default_factory=dict)
    workers_by_device_id: dict[int, OnlineMrCollectorWorker] = field(default_factory=dict)
    fping_workers_by_device_id: dict[int, FpingV5ProbeWorker] = field(default_factory=dict)
    iperf_workers_by_device_id: dict[int, IperfProcessWorker] = field(default_factory=dict)
    output_buffers_by_device_id: dict[int, deque[str]] = field(default_factory=dict)
    output_hidden: bool = False


class OnlineMrSharedRuntime:
    def __init__(self) -> None:
        self.manager = OnlineMrCollectionManager(max_concurrent=2)
        self.realtime_cache = OnlineMrRealtimeCache()
        self.sites: dict[str, OnlineMrRuntimeSiteState] = {}
        self.observers: dict[str, weakref.WeakSet[OnlineMrCollectionPage]] = {}

    def site(self, site_name: str) -> OnlineMrRuntimeSiteState:
        return self.sites.setdefault(site_name, OnlineMrRuntimeSiteState())

    def observe(self, site_name: str, page: OnlineMrCollectionPage) -> None:
        self.observers.setdefault(site_name, weakref.WeakSet()).add(page)

    def unobserve(self, site_name: str, page: OnlineMrCollectionPage) -> None:
        observers = self.observers.get(site_name)
        if observers is not None:
            observers.discard(page)


_ONLINE_MR_RUNTIMES: dict[str, OnlineMrSharedRuntime] = {}


def _online_mr_runtime(paths: PathResolver) -> OnlineMrSharedRuntime:
    runtime_key = str(Path(paths.data_root).resolve())
    runtime = _ONLINE_MR_RUNTIMES.get(runtime_key)
    if runtime is None:
        runtime = OnlineMrSharedRuntime()
        _ONLINE_MR_RUNTIMES[runtime_key] = runtime
    return runtime


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


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, horizontal_spacing: int = 8, vertical_spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = horizontal_spacing
        self._v_spacing = vertical_spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


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


def _bandwidth_input_to_mbps(value: object, unit: object = "M") -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    unit_text = str(unit or "M").strip().upper()
    if text[-1:].upper() in {"K", "M", "G"}:
        unit_text = text[-1:].upper()
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError:
        return None
    if unit_text == "K":
        return number / 1000.0
    if unit_text == "G":
        return number * 1000.0
    return number


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
    session_history_changed = Signal()

    def __init__(
        self,
        repository: DeviceRepository,
        i18n: I18n,
        site_name: str,
        paths: PathResolver,
        analysis_only: bool = False,
        feature_gate: FeatureGate | None = None,
    ) -> None:
        super().__init__()
        self._closing = False
        self._destroyed = False
        self._ui_updates_enabled = True
        self._shutdown_requested = False
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.analysis_only = analysis_only
        self.feature_gate = feature_gate or default_feature_gate()
        self.settings = SettingsStore(paths)
        self.store = OnlineMrSessionStore(paths)
        self.runtime = _online_mr_runtime(paths)
        self.manager = self.runtime.manager
        self.realtime_cache = self.runtime.realtime_cache
        self._runtime_site_state: OnlineMrRuntimeSiteState | None = None
        self._attached_worker_sessions: set[str] = set()
        self.devices: list[Device] = []
        self.filtered_devices: list[Device] = []
        self.available_devices: list[Device] = []
        self.device_groups: dict[int, str] = {}
        self.selected_device_ids: set[int] = set()
        self.workers: dict[str, OnlineMrCollectorWorker] = {}
        self.fping_workers: dict[str, FpingV5ProbeWorker] = {}
        self.iperf_workers: dict[str, IperfProcessWorker] = {}
        self.iperf_batch_workers: dict[tuple[object, ...], IperfProcessWorker] = {}
        self.iperf_batch_sessions: dict[tuple[object, ...], set[str]] = {}
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
        self.realtime_stream_parsers: dict[str, OnlineMrRealtimeParser] = {}
        self._stream_interface_direction: dict[str, str] = {}
        self._last_active_peer_by_device_id: dict[int, str] = {}
        self._stream_sample_count_by_device_id: dict[int, int] = {}
        self.realtime_states_by_device_id: dict[int, RealtimeMRState] = {}
        self.peer_station_cache: dict[str, dict[str, object]] = {}
        self.peer_name_cache: dict[str, dict[str, object]] = {}
        self._peer_name_cache_loaded = False
        self.peer_mapping_service = ApRadioMappingService(site_name, paths)
        self.parse_worker: OnlineMrParseWorker | None = None
        self.analysis_load_worker: OnlineMrAnalysisLoadWorker | None = None
        self.export_report_worker: OnlineMrReportExportWorker | None = None
        self._analysis_load_task_label = ""
        self._analysis_load_profile_phase = ""
        self._analysis_load_profile_start = 0.0
        self._analysis_load_summary = None
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
        self._fping_target_user_edited: dict[int, bool] = {1: False, 2: False}
        self._updating_fping_targets = False
        self._fping_status_texts: dict[int, str] = {1: "Ping 1: idle", 2: "Ping 2: idle"}
        self._available_device_count = 0
        self._selected_device_count = 0
        self._running_count = 0
        self._collection_status = "STOPPED"
        self.output_widgets_by_device_id: dict[int, QTextEdit] = {}
        self.output_titles_by_device_id: dict[int, QLabel] = {}
        self.output_buffers_by_device_id: dict[int, deque[str]] = {}
        self.output_dirty_devices: set[int] = set()
        self.output_render_enabled = True
        self._stopping_task_count = 0
        self._stop_animation_step = 0
        self._stop_requested_monotonic: float | None = None
        self._force_stop_in_progress = False
        self.parameter_panel_collapsed = False
        self._bind_runtime_site(site_name)

        self.site_label = QLabel()
        self.available_device_count_label = QLabel()
        self.selected_device_count_label = QLabel()
        self.running_count_label = QLabel()
        self.available_metric_label = QLabel()
        self.selected_metric_label = QLabel()
        self.running_metric_label = QLabel()
        self.filter_hint_label = QLabel()
        self.device_search_input = QLineEdit()
        self.device_table = QTableWidget(0, 9)
        self.view_device_combo = QComboBox()
        self.status_label = QLabel()
        self.status_value = "STOPPED"
        self.start_button = QPushButton()
        self.stop_selected_button = QPushButton()
        self.stop_all_button = QPushButton()
        self.force_stop_button = QPushButton("强制停止")
        self.params_toggle_button = QPushButton("收起参数")
        self.open_button = QPushButton()
        self.refresh_devices_button = QPushButton()
        self.action_bar: QWidget | None = None
        self.action_layout: FlowLayout | None = None
        self.main_splitter: QSplitter | None = None
        self.left_work_panel: QWidget | None = None
        self.parse_session_button = QPushButton()
        self.force_parse_button = QPushButton()
        self.parse_cancel_button = QPushButton("取消解析")
        self.parse_progress_bar = QProgressBar()
        self.parse_progress_label = QLabel()
        self.export_analysis_report_button = QPushButton()
        self.session_search_input = QLineEdit()
        self.session_select_combo = QComboBox()
        self.session_history_rows: list[dict[str, object]] = []
        self.session_filter_timer = QTimer(self)
        self.session_filter_timer.setSingleShot(True)
        self.session_filter_timer.setInterval(250)

        self.mesh_interval = self._interval_spin(1, 3600, 1)
        self.channel_interval = self._interval_spin(1, 3600, 9)
        self.statistics_interval = self._interval_spin(1, 3600, 10)
        self.switch_interval = self._interval_spin(10, 86400, 300)
        self.interface_rate_interval = self._interval_spin(1, 3600, 2)
        self.wireless_status_label = QLabel()
        self.wireless_status_interval_edit = QLineEdit("3")
        self.wireless_status_interval_edit.setValidator(QIntValidator(1, 3600, self))
        self.radio_port = self._radio_combo()
        self.channel_radio = self.radio_port
        self.statistics_radio = self.radio_port
        self.auto_reconnect_check = QCheckBox()
        self.auto_reconnect_check.setChecked(True)
        self.collect_config_on_start_check = QCheckBox()
        self.collect_config_on_start_check.setChecked(True)
        self.reconnect_interval = self._interval_spin(1, 3600, 5)
        self.max_reconnect = self._interval_spin(0, 999, 0)
        self.duration_minutes = self._interval_spin(0, 1440, 0)
        self.enable_fping_check = QCheckBox()
        self.enable_fping_check.setChecked(True)
        self.fping_target_edit = QLineEdit()
        self.fping_preset_combo = NoWheelComboBox()
        self.fping_packet_size = self._interval_spin(1, 65535, 64)
        self.fping_interval_ms = self._interval_spin(1, 60000, 10)
        self.fping_loss_threshold_ms = self._interval_spin(1, 60000, 100)
        self.fping_loss_warn_edit = QLineEdit()
        self.fping_loss_warn_edit.setValidator(QDoubleValidator(0.0, 100.0, 3, self))
        self.fping_loss_warn_edit.setText("0.7")
        self.fping_latency_warn_ms = self._interval_spin(1, 60000, 100)
        self.fping_tool_label = QLabel()
        self.fping_tool_label.setWordWrap(True)
        self.fping_device_combo_1 = NoWheelComboBox()
        self.fping_device_combo_2 = NoWheelComboBox()
        self.fping_target_label_1 = QLineEdit()
        self.fping_target_label_2 = QLineEdit()
        for target_label in (self.fping_target_label_1, self.fping_target_label_2):
            target_label.setPlaceholderText("默认使用所选设备IP")
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
        self.iperf_preset_combo = NoWheelComboBox()
        self.iperf_server_edit = QLineEdit()
        self.iperf_port_spin = self._no_wheel_spin(1, 65535, DEFAULT_TRAFFIC_PRESET_PORT)
        self.iperf_protocol_combo = NoWheelComboBox()
        self.iperf_protocol_combo.addItems(["TCP", "UDP"])
        self.iperf_direction_combo = NoWheelComboBox()
        self.iperf_parallel_spin = self._no_wheel_spin(1, 128, 1)
        self.iperf_interval_spin = self._no_wheel_spin(1, 3600, 1)
        self.iperf_tcp_threshold_edit = QLineEdit()
        self.iperf_tcp_threshold_edit.setValidator(QDoubleValidator(1.0, 10000.0, 3, self))
        self.iperf_udp_bitrate_edit = QLineEdit()
        self.iperf_udp_bitrate_edit.setValidator(QDoubleValidator(1.0, 10000.0, 3, self))
        self.iperf_udp_threshold_edit = QLineEdit()
        self.iperf_udp_threshold_edit.setValidator(QDoubleValidator(1.0, 10000.0, 3, self))
        self.iperf_packet_length_spin = self._no_wheel_spin(1, 65535, 1400)
        self.iperf_tcp_pacing_check = QCheckBox("限制 TCP 发送速率")
        self.iperf_tcp_pacing_edit = QLineEdit()
        self.iperf_tcp_pacing_edit.setValidator(QDoubleValidator(1.0, 10000.0, 3, self))
        self.iperf_tcp_pacing_edit.setEnabled(False)
        self.iperf_bandwidth_hint_label = QLabel()
        self.iperf_bandwidth_hint_label.setWordWrap(True)
        self.iperf_duration_mode_label = QLabel()
        self.iperf_duration_mode_label.setWordWrap(True)
        self.iperf_follow_check = QCheckBox()
        self.iperf_follow_check.setChecked(True)
        self.iperf_follow_check.setVisible(False)
        self.iperf_duration_spin = self._no_wheel_spin(1, FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS, FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS)
        self.iperf_duration_spin.setVisible(False)
        self.iperf_check_server_button = QPushButton()
        self.iperf_retry_button = QPushButton()
        self.iperf_tool_label = QLabel()
        self.iperf_tool_label.setWordWrap(True)
        self._no_wheel_filter = NoWheelValueChangeFilter(self)

        self.summary_table = QTableWidget(0, 18)
        self.mesh_table = QTableWidget(0, 13)
        self.mesh_detail_table = QTableWidget(0, 15)
        self.channel_table = QTableWidget(0, 9)
        self.events_table = QTableWidget(0, 6)
        self.statistics_text = QTextEdit()
        self.switch_history_table = QTableWidget(0, 13)
        self.switch_history_text = QTextEdit()
        self.active_link_switch_table = QTableWidget(0, 17)
        self.interface_rate_table = QTableWidget(0, 8)
        self.fping_1s_table = QTableWidget(0, 15)
        self.iperf_table = QTableWidget(0, 5)
        self.diagnosis_table = QTableWidget(0, 14)
        self.history_table = QTableWidget(0, 9)
        for table in (self.summary_table, self.mesh_table, self.mesh_detail_table, self.channel_table, self.events_table, self.switch_history_table, self.active_link_switch_table, self.interface_rate_table, self.fping_1s_table, self.iperf_table, self.diagnosis_table, self.history_table):
            configure_readonly_table(table)
            self._configure_online_table(table)
        self.statistics_text.setReadOnly(True)
        self.switch_history_text.setReadOnly(True)
        self.switch_history_text.setMaximumHeight(72)
        self.switch_history_panel = QWidget()
        switch_history_layout = QVBoxLayout(self.switch_history_panel)
        switch_history_layout.setContentsMargins(0, 0, 0, 0)
        switch_history_layout.setSpacing(4)
        switch_history_layout.addWidget(self.switch_history_table)
        switch_history_layout.addWidget(self.switch_history_text)
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.output_panel = QWidget()
        self.output_toggle = QCheckBox()
        self.output_splitter = QSplitter(Qt.Horizontal)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.tabs = QTabWidget()
        self.analysis_charts = QTabWidget()
        self.analysis_chart_pages: dict[str, QWidget] = {}
        self.analysis_chart_canvases: dict[str, object] = {}
        self.analysis_chart_axes: dict[str, object] = {}
        self.analysis_chart_views: dict[str, object] = {}
        self.analysis_chart_hover_controllers: dict[str, object] = {}
        self.analysis_chart_widgets: dict[str, OnlineMrAnalysisChartWidget] = {}
        self.analysis_chart_locked_time: datetime | None = None
        self.analysis_chart_session_dir: Path | None = None
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(self.throttle.interval_ms)
        self.refresh_timer.timeout.connect(self._flush_snapshot)
        self.output_render_timer = QTimer(self)
        self.output_render_timer.setInterval(500)
        self.output_render_timer.timeout.connect(self._flush_output_buffers)
        self.reconcile_timer = QTimer(self)
        self.reconcile_timer.setInterval(3000)
        self.reconcile_timer.timeout.connect(self._reconcile_collection_state)
        self.stop_animation_timer = QTimer(self)
        self.stop_animation_timer.setInterval(400)
        self.stop_animation_timer.timeout.connect(self._tick_stop_animation)
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
        self._updating_fping_preset = False
        self._fill_fping_preset_combo()
        self._updating_iperf_preset = False
        self._fill_iperf_preset_combo()

        self._build_ui()
        self._connect_signals()
        self._apply_fping_preset(DEFAULT_PING_PRESET_KEY)
        self._apply_iperf_preset(DEFAULT_TRAFFIC_PRESET_KEY)
        self._refresh_top_metrics()
        self.refresh_timer.start()
        self.output_render_timer.start()
        self.reconcile_timer.start()
        if not self.analysis_only:
            self.attach_to_running_collections()
        self.destroyed.connect(lambda _obj=None: self._mark_destroyed())

    def _mark_destroyed(self) -> None:
        self._destroyed = True
        self._ui_updates_enabled = False

    def _can_update_ui(self) -> bool:
        if self._closing or self._destroyed or self._shutdown_requested:
            return False
        if not self._ui_updates_enabled:
            return False
        if shutdown_manager.is_shutting_down():
            return False
        return self.window() is not None

    def prepare_close(self, reason: str = "window_close") -> None:
        self.prepare_shutdown(reason)

    def prepare_shutdown(self, reason: str = "app_exit") -> None:
        if self._shutdown_requested:
            return
        self._closing = True
        self._shutdown_requested = True
        self._ui_updates_enabled = False
        app_logger.log_info("ONLINE_MR_PAGE_PREPARE_SHUTDOWN", f"site={self.site_name} reason={reason}")
        self.stop_runtime_activity()

    def stop_runtime_activity(self) -> None:
        for timer in self._runtime_timers():
            timer.stop()
        self.throttle.pending_snapshot = None
        self.output_dirty_devices.clear()
        self._device_refresh_pending = False
        self._history_refresh_pending = False
        self._detach_from_runtime_site()
        self._request_workers_stop_for_shutdown()

    def _runtime_timers(self) -> tuple[QTimer, ...]:
        return (
            self.session_filter_timer,
            self.refresh_timer,
            self.output_render_timer,
            self.reconcile_timer,
            self.stop_animation_timer,
        )

    def _request_workers_stop_for_shutdown(self) -> None:
        self._stop_all_iperf_workers(status="STOPPED_BY_COLLECTION_END")
        for worker in list(self.fping_workers_by_device_id.values()) + list(self.fping_workers.values()):
            worker.stop()
        seen: set[int] = set()
        for worker in list(self.workers_by_device_id.values()) + list(self.workers.values()):
            marker = id(worker)
            if marker in seen:
                continue
            seen.add(marker)
            try:
                worker.cancel()
            except Exception as exc:
                app_logger.log_error("ONLINE_MR_SHUTDOWN_WORKER_CANCEL_FAILED", f"site={self.site_name} error={exc}")

    def _bind_runtime_site(self, site_name: str) -> None:
        self.runtime.unobserve(getattr(self, "site_name", site_name), self)
        state = self.runtime.site(site_name)
        self._runtime_site_state = state
        self.workers = state.workers
        self.fping_workers = state.fping_workers
        self.iperf_workers = state.iperf_workers
        self.iperf_batch_workers = state.iperf_batch_workers
        self.iperf_batch_sessions = state.iperf_batch_sessions
        self.session_dirs = state.session_dirs
        self.session_to_device_id = state.session_to_device_id
        self.workers_by_device_id = state.workers_by_device_id
        self.fping_workers_by_device_id = state.fping_workers_by_device_id
        self.iperf_workers_by_device_id = state.iperf_workers_by_device_id
        self.output_buffers_by_device_id = state.output_buffers_by_device_id
        self.output_render_enabled = not state.output_hidden
        self.runtime.observe(site_name, self)

    def attach_to_running_collections(self) -> None:
        if self.analysis_only:
            return
        self._bind_runtime_site(self.site_name)
        self._apply_output_hidden(self._runtime_site_state.output_hidden if self._runtime_site_state else False)
        restored = 0
        for session_id, worker in list(self.workers.items()):
            if not self._worker_belongs_to_current_site(worker):
                app_logger.log_info("ONLINE_MR_CROSS_SITE_STATE_FILTERED", f"site={self.site_name} session_id={session_id}")
                continue
            self._connect_runtime_worker(session_id, worker)
            device_id = self.session_to_device_id.get(session_id)
            if device_id is not None:
                self._ensure_output_widget(device_id, session_id)
                self.output_dirty_devices.add(device_id)
            session_dir = self.session_dirs.get(session_id)
            if session_dir is not None:
                self._ensure_event_pipeline(session_id, session_dir)
            snapshot = self._snapshot_from_worker(worker)
            if snapshot is not None:
                self.throttle.enqueue(snapshot)
                self._upsert_summary(snapshot)
            restored += 1
        if self.output_render_enabled:
            self._flush_output_buffers()
        self._reconcile_collection_state()
        app_logger.log_info("ONLINE_MR_UI_ATTACH_RUNTIME", f"site={self.site_name} restored_workers={restored}")
        app_logger.log_info("ONLINE_MR_DETACHED_WINDOW_ATTACHED", f"site={self.site_name} restored_workers={restored}")

    def _detach_from_runtime_site(self) -> None:
        self.runtime.unobserve(self.site_name, self)
        self._attached_worker_sessions.clear()
        app_logger.log_info("ONLINE_MR_UI_DETACH_RUNTIME", f"site={self.site_name}")

    def _clear_runtime_view(self) -> None:
        if not self._can_update_ui():
            return
        self.selected_device_ids.clear()
        self.summary_table.setRowCount(0)
        self.mesh_table.setRowCount(0)
        self.channel_table.setRowCount(0)
        self.events_table.setRowCount(0)
        self.statistics_text.clear()
        self.switch_history_table.setRowCount(0)
        self.switch_history_text.clear()
        self.interface_rate_table.setRowCount(0)
        self.iperf_table.setRowCount(0)
        self.diagnosis_table.setRowCount(0)
        self.log_text.clear()
        self.output_widgets_by_device_id.clear()
        self.output_titles_by_device_id.clear()
        self.output_dirty_devices.clear()
        while self.output_splitter.count():
            widget = self.output_splitter.widget(0)
            widget.setParent(None)
            widget.deleteLater()
        placeholder = QTextEdit()
        placeholder.setReadOnly(True)
        placeholder.setLineWrapMode(QTextEdit.NoWrap)
        placeholder.setPlainText(self.i18n.t("online_mr.waiting_realtime_output"))
        self.raw_text = placeholder
        self.output_splitter.addWidget(placeholder)
        self.event_buses.clear()
        self.realtime_buffers.clear()
        self.diagnosis_engines.clear()
        self.event_parsers.clear()
        self.realtime_stream_parsers.clear()
        self._stream_interface_direction.clear()
        self._last_active_peer_by_device_id.clear()
        self._stream_sample_count_by_device_id.clear()
        self.realtime_states_by_device_id.clear()
        self._set_status("STOPPED" if not self.workers_by_device_id else "COLLECTING")
        app_logger.log_info("ONLINE_MR_CROSS_SITE_STATE_FILTERED", f"site={self.site_name} source=site_switch")

    def _append_runtime_log(self, message: str) -> None:
        if not self._can_update_ui():
            return
        self.log_text.append(message)

    def _connect_runtime_worker(self, session_id: str, worker: OnlineMrCollectorWorker) -> None:
        if self._shutdown_requested:
            return
        if session_id in self._attached_worker_sessions:
            return
        worker.snapshot.connect(self.throttle.enqueue)
        worker.raw_stream_event.connect(self._handle_raw_stream_event)
        worker.completed.connect(self._worker_completed)
        worker.failed.connect(lambda message, device_id=self.session_to_device_id.get(session_id): self._worker_failed(message, device_id))
        self._attached_worker_sessions.add(session_id)

    def _worker_belongs_to_current_site(self, worker: OnlineMrCollectorWorker) -> bool:
        config = getattr(getattr(worker, "collector", None), "config", None)
        return str(getattr(config, "site", self.site_name) or self.site_name) == self.site_name

    def _snapshot_from_worker(self, worker: OnlineMrCollectorWorker) -> OnlineMrSnapshot | None:
        collector = getattr(worker, "collector", None)
        snapshot_fn = getattr(collector, "snapshot", None)
        if not callable(snapshot_fn):
            return None
        try:
            return snapshot_fn()
        except Exception as exc:
            app_logger.log_warning("ONLINE_MR_RUNTIME_SNAPSHOT_FAILED", f"site={self.site_name} error={exc}")
            return None

    def _site_running_count(self) -> int:
        return len({id(worker) for worker in list(self.workers.values()) + list(self.workers_by_device_id.values())})

    def closeEvent(self, event) -> None:
        self.prepare_shutdown("close_event")
        super().closeEvent(event)

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.set_site(site_name)

    def set_site(self, site_name: str) -> None:
        if self._shutdown_requested:
            return
        if site_name == self.site_name:
            self.attach_to_running_collections()
            self._schedule_device_refresh(refresh_tools=False)
            return
        old_site = self.site_name
        self._detach_from_runtime_site()
        self.site_name = site_name
        self._bind_runtime_site(site_name)
        self._first_show_refreshed = False
        self._clear_runtime_view()
        self._clear_peer_identity_cache()
        self._schedule_device_refresh(refresh_tools=False)
        self.attach_to_running_collections()
        app_logger.log_info("ONLINE_MR_SITE_CONTEXT_SWITCHED", f"old_site={old_site} new_site={site_name}")

    def first_show_refresh(self) -> None:
        if not self._can_update_ui():
            return
        if self.site_name not in self._stale_sessions_checked_sites:
            self._stale_sessions_checked_sites.add(self.site_name)
            QTimer.singleShot(0, lambda site_name=self.site_name: None if self._shutdown_requested else self.store.mark_stale_sessions_aborted(site_name))
        self._first_show_refreshed = True
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self.filter_hint_label.setText(self.i18n.t("app.loading"))
        if self.analysis_only:
            self._schedule_history_refresh(refresh_tools=False)
        else:
            self._schedule_device_refresh(refresh_tools=False)

    def on_enter(self) -> None:
        if not self._first_show_refreshed and not self.analysis_only:
            self.first_show_refresh()
        self._update_realtime_responsive_layout()
        fields = (
            self.fping_packet_size,
            self.fping_interval_ms,
            self.fping_loss_threshold_ms,
            self.fping_loss_warn_edit,
            self.fping_latency_warn_ms,
        )
        visible = self.ping_box is not None and not self.ping_box.isHidden() and all(not field.isHidden() for field in fields)
        _rail_mrcollect_diag("[Rail][MRCollect] high ping layout: grid")
        _rail_mrcollect_diag(f"[Rail][MRCollect] high ping fields visible: {'yes' if visible else 'no'}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_realtime_responsive_layout()

    def _update_realtime_responsive_layout(self) -> None:
        splitter = getattr(self, "main_splitter", None)
        if self.analysis_only or splitter is None:
            return
        if hasattr(self, "page_scroll"):
            viewport_width = max(self.page_scroll.viewport().width(), self.page_scroll.width(), self.width())
        else:
            viewport_width = self.width()
        if viewport_width < 1250 and splitter.orientation() != Qt.Vertical:
            splitter.setOrientation(Qt.Vertical)
            splitter.setSizes([420, 520])
        elif viewport_width >= 1250 and splitter.orientation() != Qt.Horizontal:
            splitter.setOrientation(Qt.Horizontal)
            splitter.setSizes([760, 460])

    def _toggle_parameter_panel(self) -> None:
        self._apply_parameter_panel_collapsed(not self.parameter_panel_collapsed, persist=True)

    def _apply_parameter_panel_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        self.parameter_panel_collapsed = bool(collapsed)
        if hasattr(self, "right_control_scroll") and self.right_control_scroll is not None:
            self.right_control_scroll.setVisible(not self.parameter_panel_collapsed)
        self.params_toggle_button.setText("展开参数" if self.parameter_panel_collapsed else "收起参数")
        self.params_toggle_button.setToolTip(self.params_toggle_button.text())
        if self.main_splitter is not None:
            if self.parameter_panel_collapsed:
                self.main_splitter.setSizes([1, 0])
            elif self.main_splitter.orientation() == Qt.Horizontal:
                self.main_splitter.setSizes([760, 460])
            else:
                self.main_splitter.setSizes([420, 520])
        if persist:
            self.settings.set_value(PARAM_PANEL_COLLAPSED_KEY, self.parameter_panel_collapsed)

    def refresh_all(self, defer_heavy: bool = False, refresh_tools: bool = False) -> None:
        if not self._can_update_ui():
            return
        profile_start = time.perf_counter()
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self._clear_peer_identity_cache()
        if self.analysis_only:
            self.devices = self.repository.list()
            self._load_device_groups()
            self.available_devices = self.devices
            self.filtered_devices = self.devices
            self._fill_view_devices()
            self._fill_history()
            self._update_action_state()
            self._log_page_profile("refresh", profile_start, rows=len(self.session_history_rows))
            return
        self.devices = self.repository.list()
        self._load_device_groups()
        self._fill_devices()
        self._fill_view_devices()
        if defer_heavy:
            self._schedule_history_refresh(refresh_tools=refresh_tools)
        else:
            self._fill_history()
            self._refresh_tool_status_once(force=refresh_tools)
        self.attach_to_running_collections()
        self._update_action_state()
        self._log_page_profile("refresh", profile_start, rows=len(self.filtered_devices))

    def _clear_peer_identity_cache(self) -> None:
        self.peer_station_cache.clear()
        self.peer_name_cache.clear()
        self._peer_name_cache_loaded = False
        if not self._can_update_ui():
            return
        self._refresh_top_metrics()

    def _schedule_device_refresh(self, refresh_tools: bool = False) -> None:
        if not self._can_update_ui():
            return
        if self._device_refresh_pending:
            return
        self._device_refresh_pending = True

        def run() -> None:
            self._device_refresh_pending = False
            if not self._can_update_ui():
                return
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
        self.force_stop_button.setText("强制停止")
        self.params_toggle_button.setText("展开参数" if self.parameter_panel_collapsed else "收起参数")
        self.open_button.setText(self.i18n.t("online_mr.open_session_dir"))
        self.refresh_devices_button.setText(self.i18n.t("online_mr.refresh_devices"))
        self.parse_session_button.setText(self.i18n.t("online_mr.parse_selected_session" if self.analysis_only else "online_mr.parse_collection_data"))
        self.force_parse_button.setText(self.i18n.t("online_mr.force_reparse"))
        self.force_parse_button.setVisible(self.analysis_only)
        self.parse_cancel_button.setText("取消解析")
        self.export_analysis_report_button.setText(self.i18n.t("online_mr.export_analysis_report"))
        self.export_analysis_report_button.setVisible(self.analysis_only)
        self._apply_button_icons()
        self.device_search_input.setPlaceholderText(self.i18n.t("online_mr.device_search_placeholder"))
        self.session_search_input.setPlaceholderText(self.i18n.t("online_mr.search_device"))
        self.auto_reconnect_check.setText(self.i18n.t("online_mr.auto_reconnect"))
        self.collect_config_on_start_check.setText(self.i18n.t("online_mr.collect_config_on_start"))
        self.enable_fping_check.setText(self.i18n.t("online_mr.high_freq_ping"))
        self.enable_iperf_check.setText(self.i18n.t("online_mr.enable_traffic_test"))
        self.wireless_status_label.setText(self.i18n.t("online_mr.wireless_status"))
        self.iperf_follow_check.setText(self.i18n.t("iperf.follow_collection"))
        self.iperf_duration_mode_label.setText("运行方式：跟随采集启停")
        self.iperf_check_server_button.setText("检测打流服务端")
        self.iperf_retry_button.setText("重试打流")
        self.iperf_bandwidth_hint_label.setText(self.i18n.t("iperf.tcp_auto_bandwidth_hint"))
        self.iperf_tcp_threshold_edit.setToolTip(self.i18n.t("iperf.tcp_report_threshold_tooltip"))
        self.iperf_udp_bitrate_edit.setToolTip(self.i18n.t("iperf.udp_bitrate_tooltip"))
        self.iperf_udp_threshold_edit.setToolTip(self.i18n.t("iperf.udp_report_threshold_tooltip"))
        self.iperf_tcp_pacing_check.setToolTip(self.i18n.t("iperf.tcp_pacing_tooltip"))
        self.iperf_tcp_pacing_edit.setToolTip(self.i18n.t("iperf.tcp_pacing_tooltip"))
        self.iperf_tcp_pacing_check.setText(self.i18n.t("iperf.tcp_pacing_enabled"))
        self.iperf_preset_combo.setToolTip(self.i18n.t("iperf.preset"))
        for widget in (
            self.iperf_port_spin,
            self.iperf_preset_combo,
            self.iperf_protocol_combo,
            self.iperf_direction_combo,
            self.iperf_parallel_spin,
            self.iperf_interval_spin,
            self.iperf_packet_length_spin,
        ):
            widget.setToolTip(self.i18n.t("iperf.no_wheel_hint"))
        self._fill_iperf_direction_combo()
        self._update_iperf_controls_visibility()
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
                self.i18n.t("online_mr.peer_name"),
                self.i18n.t("online_mr.peer_mac"),
                "MR RSSI",
                self.i18n.t("online_mr.peer_site"),
                self.i18n.t("online_mr.peer_section"),
                self.i18n.t("online_mr.ping_loss_rate"),
                self.i18n.t("online_mr.ping_latency"),
                self.i18n.t("online_mr.collected"),
                self.i18n.t("online_mr.failed"),
                self.i18n.t("online_mr.reconnects"),
                self.i18n.t("online_mr.last_collection"),
                self.i18n.t("online_mr.avg_bandwidth"),
                self.i18n.t("iperf.retransmits"),
                self.i18n.t("online_mr.session"),
                "ID",
            ]
        )
        self.mesh_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.row_number"), self.i18n.t("online_mr.sample_time"), self.i18n.t("online_mr.device_time"), self.i18n.t("online_mr.radio_id"), self.i18n.t("online_mr.link_state"), self.i18n.t("online_mr.peer_name"), self.i18n.t("online_mr.peer_mac"), "MR侧RSSI", "BSSID", self.i18n.t("online_mr.mesh_interface"), self.i18n.t("online_mr.peer_site"), self.i18n.t("online_mr.peer_section"), self.i18n.t("online_mr.online_time")])
        self.mesh_detail_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.row_number"), self.i18n.t("online_mr.sample_time"), self.i18n.t("online_mr.device_time"), "Radio", self.i18n.t("online_mr.status"), "PeerMac", "当前PEER AP名称", "AP MAC", self.i18n.t("online_mr.peer_site"), self.i18n.t("online_mr.peer_section"), "Peer Radio MAC", "MR RSSI", "BSSID", self.i18n.t("online_mr.mesh_interface"), "Online Time"])
        self.channel_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("online_mr.row_number"),
                self.i18n.t("online_mr.device_time"),
                self.i18n.t("online_mr.radio_id"),
                "控制信道",
                "频宽",
                "记录间隔",
                self.i18n.t("online_mr.ctl_busy"),
                self.i18n.t("online_mr.tx_busy"),
                self.i18n.t("online_mr.rx_busy"),
            ]
        )
        self.events_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), self.i18n.t("online_mr.type"), self.i18n.t("online_mr.radio_id"), self.i18n.t("online_mr.from_peer"), self.i18n.t("online_mr.to_peer"), self.i18n.t("online_mr.details")])
        self.switch_history_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.row_number"), self.i18n.t("online_mr.switch_time"), self.i18n.t("online_mr.radio_id"), self.i18n.t("online_mr.from_peer_name"), self.i18n.t("online_mr.to_peer_name"), self.i18n.t("online_mr.from_peer_mac"), self.i18n.t("online_mr.to_peer_mac"), self.i18n.t("online_mr.from_peer_site"), self.i18n.t("online_mr.to_peer_site"), "归属区间", self.i18n.t("online_mr.switch_reason"), self.i18n.t("online_mr.in_out_rssi"), self.i18n.t("online_mr.active_duration")])
        self.active_link_switch_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("online_mr.row_number"),
                self.i18n.t("online_mr.device_time"),
                self.i18n.t("online_mr.device_name"),
                self.i18n.t("online_mr.from_ap_name"),
                self.i18n.t("online_mr.from_radio_mac"),
                self.i18n.t("online_mr.from_rssi"),
                self.i18n.t("online_mr.from_peer_site"),
                "原归属区间",
                self.i18n.t("online_mr.to_ap_name"),
                self.i18n.t("online_mr.to_radio_mac"),
                self.i18n.t("online_mr.to_rssi"),
                self.i18n.t("online_mr.to_peer_site"),
                "新归属区间",
                self.i18n.t("online_mr.peer_quantity"),
                self.i18n.t("online_mr.link_quantity"),
                self.i18n.t("online_mr.switch_reason_code"),
                self.i18n.t("online_mr.switch_reason"),
            ]
        )
        self.interface_rate_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.row_number"), self.i18n.t("online_mr.device_time"), self.i18n.t("online_mr.direction"), self.i18n.t("online_mr.interface"), self.i18n.t("online_mr.usage_percent"), self.i18n.t("online_mr.total_pps"), self.i18n.t("online_mr.broadcast_pps"), self.i18n.t("online_mr.multicast_pps")])
        self.fping_1s_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("online_mr.row_number"),
                self.i18n.t("online_mr.time"),
                "设备对齐时间",
                "本地时间",
                "目标IP",
                "目标名称",
                "发送数",
                "接收数",
                "丢失数",
                "丢包率(%)",
                "平均延迟(ms)",
                "最小延迟(ms)",
                "最大延迟(ms)",
                "Jitter(ms)",
                "状态",
            ]
        )
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
                self.i18n.t("online_mr.avg_bandwidth"),
                self.i18n.t("online_mr.max_bandwidth"),
                self.i18n.t("online_mr.avg_tx_busy"),
                self.i18n.t("online_mr.avg_rx_busy"),
                self.i18n.t("online_mr.in_pps"),
                self.i18n.t("online_mr.out_pps"),
                self.i18n.t("online_mr.status"),
            ]
        )
        self.history_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.session"), self.i18n.t("online_mr.start_time"), self.i18n.t("online_mr.end_time"), self.i18n.t("online_mr.status"), self.i18n.t("online_mr.mesh_ok_fail"), self.i18n.t("online_mr.busy_ok_fail"), self.i18n.t("online_mr.reconnects"), "MR", self.i18n.t("online_mr.directory")])
        self._apply_online_table_styles()
        if self.analysis_only:
            labels = (
                self.i18n.t("online_mr.history_sessions"),
                self.i18n.t("online_mr.mesh_link"),
                self.i18n.t("online_mr.link_details"),
                self.i18n.t("online_mr.channel_busy"),
                self.i18n.t("online_mr.ap_radio_statistics"),
                self.i18n.t("online_mr.switch_history"),
                self.i18n.t("online_mr.active_link_switch_logs"),
                self.i18n.t("online_mr.interface_rate"),
                self.i18n.t("online_mr.analysis_charts"),
                self.i18n.t("online_mr.fping_1s_summary"),
                self.i18n.t("online_mr.traffic_test"),
                self.i18n.t("online_mr.diagnosis_results"),
                self.i18n.t("online_mr.raw_output"),
                self.i18n.t("online_mr.collection_log"),
            )
        else:
            labels = (
                self.i18n.t("online_mr.raw_output"),
                self.i18n.t("online_mr.collection_log"),
                self.i18n.t("online_mr.traffic_test"),
            )
        for index, label in enumerate(labels):
            if index < self.tabs.count():
                self.tabs.setTabText(index, label)
        self.output_toggle.setText(self.i18n.t("online_mr.hide_output"))
        self._retranslate_output_titles()

    def _apply_button_icons(self) -> None:
        for button, icon_name in (
            (self.start_button, "PLAY"),
            (self.stop_selected_button, "PAUSE"),
            (self.stop_all_button, "CANCEL"),
            (self.force_stop_button, "CANCEL"),
            (self.params_toggle_button, "MENU"),
            (self.open_button, "FOLDER"),
            (self.refresh_devices_button, "SYNC"),
            (self.parse_session_button, "PLAY"),
            (self.force_parse_button, "SYNC"),
            (self.export_analysis_report_button, "SHARE"),
        ):
            apply_button_icon(button, icon_name)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        self.page_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("onlineMrRealtimeContent")
        content.setMinimumWidth(ONLINE_MR_PAGE_MIN_WIDTH)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll)

        controls = QGroupBox()
        self.connection_box = controls
        top_layout = FlowLayout(controls, horizontal_spacing=20, vertical_spacing=8)
        top_layout.setContentsMargins(16, 10, 16, 10)
        self._cap_controls()
        controls.setMinimumHeight(92)
        controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        top_layout.addWidget(self.available_metric_label)
        top_layout.addWidget(self.selected_metric_label)
        top_layout.addWidget(self.running_metric_label)
        status_item = QWidget()
        status_layout = QHBoxLayout(status_item)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(self._label("online_mr.status"))
        status_layout.addWidget(self.status_label)
        top_layout.addWidget(status_item)

        self.site_label.hide()
        action_bar = QWidget()
        self.action_bar = action_bar
        action_bar.setMinimumHeight(44)
        action_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        action_layout = FlowLayout(action_bar, horizontal_spacing=8, vertical_spacing=8)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout = action_layout
        self.force_stop_button.setVisible(False)
        self.force_stop_button.setEnabled(False)
        for button in (self.start_button, self.stop_selected_button, self.stop_all_button, self.force_stop_button, self.params_toggle_button, self.open_button, self.refresh_devices_button):
            action_layout.addWidget(button)
        if not self.analysis_only:
            root.insertWidget(0, action_bar)
            content_layout.addWidget(controls)
            content_layout.addWidget(self.filter_hint_label)

        self.device_table.setMinimumHeight(260)
        self.device_table.setMaximumHeight(16777215)
        self.device_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._configure_online_table(self.device_table)
        install_checkbox_only_delegate(self.device_table, 0)

        self.advanced_box = self._advanced_box()
        self.period_box = self._period_box()
        self.radio_box = self.period_box
        self.ping_box = self._ping_box()
        self.iperf_box = self._iperf_box()

        main_work_panel = QWidget()
        self.main_work_panel = main_work_panel
        main_layout = QVBoxLayout(main_work_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)
        device_panel = QWidget()
        self.device_panel = device_panel
        device_panel.setMinimumWidth(ONLINE_MR_LEFT_PANEL_MIN_WIDTH)
        device_panel.setMinimumHeight(360)
        device_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        device_layout = QVBoxLayout(device_panel)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(6)
        device_layout.addWidget(self.device_search_input)
        device_layout.addWidget(self.device_table)
        self.collect_status_box.setMinimumHeight(140)
        self.collect_status_box.setMaximumHeight(16777215)
        self.collect_status_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
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
        control_panel.setMinimumWidth(ONLINE_MR_RIGHT_PANEL_MIN_WIDTH)
        control_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
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
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setMinimumWidth(ONLINE_MR_RIGHT_PANEL_MIN_WIDTH)
        right_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_scroll.setWidget(control_panel)
        self._install_no_wheel_filter_for_controls(control_panel)
        main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter = main_splitter
        main_splitter.setChildrenCollapsible(False)
        main_splitter.addWidget(device_panel)
        main_splitter.addWidget(right_scroll)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([760, 460])
        main_splitter.setMinimumHeight(360)
        main_layout.addWidget(main_splitter, 1)
        main_work_panel.setMinimumHeight(380)
        main_work_panel.setMinimumWidth(ONLINE_MR_WORK_PANEL_MIN_WIDTH)

        vertical_splitter = QSplitter(Qt.Vertical)
        self.vertical_splitter = vertical_splitter
        self.summary_table.setMinimumHeight(120)
        if not self.analysis_only:
            vertical_splitter.addWidget(main_work_panel)
            vertical_splitter.addWidget(self.collect_status_box)
            vertical_splitter.addWidget(self.summary_table)
        view_row = QWidget()
        self.view_row = view_row
        view_row.setMinimumHeight(40)
        view_row.setMaximumHeight(44)
        view_layout = QHBoxLayout(view_row)
        view_layout.setContentsMargins(0, 4, 0, 4)
        if self.analysis_only:
            self.session_search_input.setMinimumWidth(220)
            self.session_select_combo.setMinimumWidth(520)
            view_layout.addWidget(self._text_label("online_mr.search_device"))
            view_layout.addWidget(self.session_search_input)
            view_layout.addWidget(self._text_label("online_mr.select_session"))
            view_layout.addWidget(self.session_select_combo, 1)
        else:
            view_layout.addWidget(self._text_label("online_mr.view_device"))
            self.view_device_combo.setMinimumWidth(260)
            self.view_device_combo.setMaximumWidth(360)
            view_layout.addWidget(self.view_device_combo)
        self.parse_session_button.setMinimumWidth(140)
        view_layout.addWidget(self.parse_session_button)
        self.force_parse_button.setMinimumWidth(110)
        view_layout.addWidget(self.force_parse_button)
        self.parse_cancel_button.setMinimumWidth(90)
        self.parse_cancel_button.setVisible(False)
        view_layout.addWidget(self.parse_cancel_button)
        self.parse_progress_bar.setRange(0, 100)
        self.parse_progress_bar.setValue(0)
        self.parse_progress_bar.setTextVisible(True)
        self.parse_progress_bar.setMinimumWidth(180)
        self.parse_progress_bar.setMaximumWidth(260)
        self.parse_progress_bar.setVisible(False)
        view_layout.addWidget(self.parse_progress_bar)
        self.parse_progress_label.setMinimumWidth(220)
        self.parse_progress_label.setVisible(False)
        view_layout.addWidget(self.parse_progress_label)
        self.export_analysis_report_button.setMinimumWidth(130)
        self.export_analysis_report_button.setVisible(self.analysis_only)
        view_layout.addWidget(self.export_analysis_report_button)
        view_layout.addStretch(1)
        self._build_analysis_chart_pages()
        if self.analysis_only:
            self.tabs.addTab(self.history_table, "")
            self.tabs.addTab(self.mesh_table, "")
            self.tabs.addTab(self.mesh_detail_table, "")
            self.tabs.addTab(self.channel_table, "")
            self.tabs.addTab(self.statistics_text, "")
            self.tabs.addTab(self.switch_history_panel, "")
            self.tabs.addTab(self.active_link_switch_table, "")
            self.tabs.addTab(self.interface_rate_table, "")
            self.tabs.addTab(self.analysis_charts, "")
            self.tabs.addTab(self.fping_1s_table, "")
            self.tabs.addTab(self.iperf_table, "")
            self.tabs.addTab(self.diagnosis_table, "")
            self.tabs.addTab(self.raw_text, "")
            self.tabs.addTab(self.log_text, "")
        else:
            self._build_output_panel()
            self.tabs.addTab(self.output_panel, "")
            self.tabs.addTab(self.log_text, "")
            self.tabs.addTab(self.iperf_table, "")
        self.tabs.setMinimumHeight(220)
        detail = QWidget()
        detail.setMinimumHeight(180)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)
        if self.analysis_only:
            detail_layout.addWidget(view_row)
        detail_layout.addWidget(self.tabs)
        vertical_splitter.addWidget(detail)
        if self.analysis_only:
            vertical_splitter.setStretchFactor(0, 1)
            vertical_splitter.setSizes([720])
        else:
            vertical_splitter.setStretchFactor(0, 20)
            vertical_splitter.setStretchFactor(1, 8)
            vertical_splitter.setStretchFactor(2, 10)
            vertical_splitter.setStretchFactor(3, 30)
            vertical_splitter.setSizes(DEFAULT_REALTIME_SPLITTER_SIZES)
            self._restore_vertical_splitter_sizes()
            vertical_splitter.splitterMoved.connect(self._save_vertical_splitter_sizes)
        content_layout.addWidget(vertical_splitter, 1)
        self.retranslate()
        self._apply_feature_gate()
        self._load_all_table_widths()
        if not self.analysis_only:
            self.parameter_panel_collapsed = bool(self.settings.get_value(PARAM_PANEL_COLLAPSED_KEY, False))
            self._apply_parameter_panel_collapsed(self.parameter_panel_collapsed, persist=False)

    def _connect_signals(self) -> None:
        self.device_table.itemChanged.connect(self._device_item_changed)
        self.device_table.currentCellChanged.connect(self._on_device_current_row_changed)
        self.view_device_combo.currentIndexChanged.connect(self._view_device_changed)
        self.device_search_input.textChanged.connect(self._fill_devices)
        self.session_search_input.textChanged.connect(lambda _text: self.session_filter_timer.start())
        self.session_filter_timer.timeout.connect(self._refresh_session_select_combo)
        self.start_button.clicked.connect(self.start_collection)
        self.stop_selected_button.clicked.connect(self.stop_selected)
        self.stop_all_button.clicked.connect(self.stop_all)
        self.force_stop_button.clicked.connect(self.force_stop_collection)
        self.params_toggle_button.clicked.connect(self._toggle_parameter_panel)
        self.open_button.clicked.connect(self.open_selected_session_dir)
        self.refresh_devices_button.clicked.connect(lambda: self.refresh_all(defer_heavy=False, refresh_tools=True))
        self.parse_session_button.clicked.connect(self.parse_selected_session)
        self.force_parse_button.clicked.connect(lambda: self.parse_selected_session(force_reparse=True))
        self.parse_cancel_button.clicked.connect(self._cancel_parse_worker)
        self.export_analysis_report_button.clicked.connect(self.export_analysis_report)
        self.session_select_combo.currentIndexChanged.connect(lambda _index: self._refresh_parse_button_state())
        self.output_toggle.toggled.connect(self._output_render_toggled)
        self.fping_preset_combo.currentIndexChanged.connect(lambda _index: self._fping_preset_changed())
        self.fping_packet_size.valueChanged.connect(lambda _value: self._mark_fping_preset_custom())
        self.fping_interval_ms.valueChanged.connect(lambda _value: self._mark_fping_preset_custom())
        self.fping_loss_threshold_ms.valueChanged.connect(lambda _value: self._mark_fping_preset_custom())
        self.fping_loss_warn_edit.textChanged.connect(lambda _text: self._mark_fping_preset_custom())
        self.fping_latency_warn_ms.valueChanged.connect(lambda _value: self._mark_fping_preset_custom())
        self.fping_device_combo_1.currentIndexChanged.connect(lambda _index: self._fping_device_changed(1))
        self.fping_device_combo_2.currentIndexChanged.connect(lambda _index: self._fping_device_changed(2))
        self.fping_target_label_1.textEdited.connect(lambda _text: self._fping_target_edited(1))
        self.fping_target_label_2.textEdited.connect(lambda _text: self._fping_target_edited(2))
        self.iperf_preset_combo.currentIndexChanged.connect(lambda _index: self._iperf_preset_changed())
        self.iperf_protocol_combo.currentIndexChanged.connect(lambda _index: self._update_iperf_controls_visibility())
        self.iperf_tcp_pacing_check.toggled.connect(lambda checked: self.iperf_tcp_pacing_edit.setEnabled(bool(checked)))
        self.iperf_check_server_button.clicked.connect(self.check_iperf_server)
        self.iperf_retry_button.clicked.connect(self.retry_iperf_for_running_sessions)
        self.analysis_charts.currentChanged.connect(self._analysis_chart_tab_changed)

    def _build_analysis_chart_pages(self) -> None:
        if self.analysis_charts.count() > 0:
            return
        for key, title in self._analysis_chart_titles():
            page = QWidget()
            page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout = QVBoxLayout(page)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(4)
            chart_widget = OnlineMrAnalysisChartWidget(self.i18n, key, title, page)
            chart_widget.hoverChanged.connect(lambda controller, chart_key=key: self._analysis_chart_hover_changed(chart_key, controller))
            chart_widget.lockTimeRequested.connect(self._set_analysis_chart_locked_time)
            chart_widget.lockTimeCleared.connect(self._clear_analysis_chart_locked_time)
            layout.addWidget(chart_widget, 1)
            self.analysis_chart_pages[key] = page
            self.analysis_chart_widgets[key] = chart_widget
            self.analysis_chart_views[key] = chart_widget.view
            self.analysis_chart_canvases[key] = chart_widget.canvas
            self.analysis_charts.addTab(page, title)

    def _build_output_panel(self) -> None:
        layout = QVBoxLayout(self.output_panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.output_toggle.setChecked(False)
        toolbar.addWidget(self.output_toggle)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.output_splitter.setChildrenCollapsible(False)
        layout.addWidget(self.output_splitter, 1)
        self._ensure_placeholder_output()

    @staticmethod
    def _configure_output_editor(editor: QTextEdit) -> None:
        editor.setReadOnly(True)
        editor.setLineWrapMode(QTextEdit.NoWrap)
        editor.setMinimumHeight(180)
        editor.setStyleSheet("QTextEdit { font-family: Consolas, 'Courier New', monospace; }")

    def _ensure_placeholder_output(self) -> None:
        if self.output_widgets_by_device_id:
            return
        placeholder = QTextEdit()
        self._configure_output_editor(placeholder)
        placeholder.setPlainText(self.i18n.t("online_mr.waiting_realtime_output"))
        self.raw_text = placeholder
        self.output_splitter.addWidget(placeholder)

    def _ensure_output_widget(self, device_id: int | None, session_id: str = "") -> QTextEdit:
        if device_id is None:
            device_id = -1
        if device_id in self.output_widgets_by_device_id:
            return self.output_widgets_by_device_id[device_id]
        if len(self.output_widgets_by_device_id) == 0 and self.output_splitter.count() == 1:
            placeholder = self.output_splitter.widget(0)
            placeholder.setParent(None)
            placeholder.deleteLater()
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(2, 2, 2, 2)
        panel_layout.setSpacing(4)
        title = QLabel(self._output_title_for_device(device_id, session_id))
        title.setMinimumHeight(24)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        editor = QTextEdit()
        self._configure_output_editor(editor)
        panel_layout.addWidget(title)
        panel_layout.addWidget(editor, 1)
        self.output_titles_by_device_id[device_id] = title
        self.output_widgets_by_device_id[device_id] = editor
        self.output_buffers_by_device_id.setdefault(device_id, deque(maxlen=2000))
        self.output_splitter.addWidget(panel)
        self.raw_text = editor
        self._retranslate_output_titles()
        return editor

    def _output_title_for_device(self, device_id: int, session_id: str = "") -> str:
        worker = self.workers_by_device_id.get(device_id)
        if worker is not None:
            config = worker.collector.config
            return f"{config.device_name} / {config.host}"
        device = next((item for item in self.available_devices + self.filtered_devices if item.id == device_id), None)
        if device is not None:
            return f"{device.name} / {device.primary_address or '-'}"
        if session_id:
            return f"{self.i18n.t('online_mr.unknown_or_deleted_device', device_id=device_id)} / {session_id}"
        return self.i18n.t("online_mr.waiting_realtime_output")

    def _retranslate_output_titles(self) -> None:
        for device_id, title in self.output_titles_by_device_id.items():
            title.setText(self._output_title_for_device(device_id, self._session_id_for_device(device_id)))

    def _output_render_toggled(self, checked: bool) -> None:
        hidden = checked
        if self._runtime_site_state is not None:
            self._runtime_site_state.output_hidden = hidden
        for page in list(self.runtime.observers.get(self.site_name, ())):
            page._apply_output_hidden(hidden)
        app_logger.log_info("ONLINE_MR_UI_OUTPUT_STATE_SYNCED", f"site={self.site_name} hidden={hidden}")

    def _apply_output_hidden(self, hidden: bool) -> None:
        self.output_render_enabled = not hidden
        if self.output_toggle.isChecked() != hidden:
            self.output_toggle.blockSignals(True)
            self.output_toggle.setChecked(hidden)
            self.output_toggle.blockSignals(False)
        self.output_toggle.setText(self.i18n.t("online_mr.hide_output"))
        self._set_output_area_collapsed(hidden)
        if not hidden:
            self.output_dirty_devices.update(self.output_buffers_by_device_id)
            self._flush_output_buffers()
        else:
            app_logger.log_info(
                "ONLINE_MR_OUTPUT_RENDER_DISABLED",
                f"output_render_enabled=False workers_count={len(self.workers)} manager_running_count={self.manager.running_count()}",
            )

    def _set_output_area_collapsed(self, collapsed: bool) -> None:
        self.output_splitter.setVisible(not collapsed)
        self.output_panel.setMaximumHeight(54 if collapsed else 16777215)
        if not self.analysis_only and hasattr(self, "vertical_splitter"):
            if collapsed:
                self.vertical_splitter.setSizes([420, 170, 240, 56])
            else:
                self._restore_vertical_splitter_sizes()

    def _focus_output_device(self, device_id: int | None) -> None:
        if self.analysis_only or device_id is None:
            return
        editor = self.output_widgets_by_device_id.get(int(device_id))
        if editor is None:
            return
        self.tabs.setCurrentWidget(self.output_panel)
        editor.setFocus()

    def _restore_vertical_splitter_sizes(self) -> None:
        if self.analysis_only or not hasattr(self, "vertical_splitter"):
            return
        sizes = self.settings.get_value(SPLITTER_SIZES_KEY, DEFAULT_REALTIME_SPLITTER_SIZES)
        if isinstance(sizes, list) and len(sizes) == 3:
            sizes = [sizes[0], 150, sizes[1], sizes[2]]
        if not isinstance(sizes, list) or len(sizes) != 4:
            sizes = DEFAULT_REALTIME_SPLITTER_SIZES
        try:
            self.vertical_splitter.setSizes([max(40, int(size)) for size in sizes])
        except (TypeError, ValueError):
            self.vertical_splitter.setSizes(DEFAULT_REALTIME_SPLITTER_SIZES)

    def _save_vertical_splitter_sizes(self, _pos: int | None = None, _index: int | None = None) -> None:
        if self.analysis_only or not hasattr(self, "vertical_splitter"):
            return
        sizes = self.vertical_splitter.sizes()
        self.settings.set_value(SPLITTER_SIZES_KEY, sizes)
        app_logger.log_info("ONLINE_MR_LAYOUT_SPLITTER_CHANGED", f"sizes={sizes}")

    def _start_stop_animation(self, task_count: int) -> None:
        self._stopping_task_count = max(1, int(task_count))
        self._stop_animation_step = 0
        self._stop_requested_monotonic = time.monotonic()
        self._force_stop_in_progress = False
        if not self._can_update_ui():
            return
        self.force_stop_button.setVisible(False)
        self.force_stop_button.setEnabled(False)
        self.stop_animation_timer.start()
        self._tick_stop_animation()
        app_logger.log_info(
            "ONLINE_MR_STOP_ANIMATION_STARTED",
            f"tasks={self._stopping_task_count} workers_count={len(self.workers)} manager_running_count={self.manager.running_count()}",
        )

    def _stop_stop_animation(self) -> None:
        self._stopping_task_count = 0
        self._stop_requested_monotonic = None
        self._force_stop_in_progress = False
        if self._can_update_ui():
            self.force_stop_button.setVisible(False)
            self.force_stop_button.setEnabled(False)
        self.stop_animation_timer.stop()

    def _tick_stop_animation(self) -> None:
        if not self._can_update_ui():
            self.stop_animation_timer.stop()
            return
        if self._stopping_task_count <= 0:
            self.stop_animation_timer.stop()
            return
        elapsed = 0.0
        if self._stop_requested_monotonic is not None:
            elapsed = time.monotonic() - self._stop_requested_monotonic
        if elapsed >= FORCE_STOP_DELAY_SECONDS:
            self.force_stop_button.setVisible(True)
            self.force_stop_button.setEnabled(True)
        if elapsed >= BATCH_STOP_TIMEOUT_SECONDS and not self._force_stop_in_progress:
            self.force_stop_collection(reason="timeout")
            return
        dots = "." * ((self._stop_animation_step % 3) + 1)
        self._stop_animation_step += 1
        text = self.i18n.t("online_mr.stopping_count", count=self._stopping_task_count)
        self.status_label.setText(f"{text}{dots}")

    @staticmethod
    def _analysis_chart_titles() -> tuple[tuple[str, str], ...]:
        return (
            ("rssi", "主链路 RSSI"),
            ("ping_loss", "Ping 丢包率"),
            ("ping", "Ping 延迟"),
            ("interface", "接口 PPS"),
            ("traffic", "业务打流"),
            ("busy", "信道繁忙度"),
            ("switch_rssi", "主链路切换前后信号"),
            ("switch_log_rssi", "主链路切换日志RSSI"),
        )

    def _install_no_wheel_filter_for_controls(self, root_widget: QWidget) -> None:
        widgets = list(root_widget.findChildren(QAbstractSpinBox)) + list(root_widget.findChildren(QComboBox))
        for widget in widgets:
            widget.installEventFilter(self._no_wheel_filter)
            widget.setFocusPolicy(Qt.StrongFocus)

    def start_collection(self) -> None:
        if self.enable_fping_check.isChecked():
            self.feature_gate.assert_enabled("online_mr.advanced_ping")
        if self.enable_iperf_check.isChecked():
            self.feature_gate.assert_enabled("online_mr.iperf_test")
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
        if not self._preflight_iperf_before_start():
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
            worker = OnlineMrCollectorWorker(config, self.store, realtime_cache=self.realtime_cache, parent=self)
            if device.id is not None:
                self.workers_by_device_id[int(device.id)] = worker
                self.manager.register_device(int(device.id), worker)
            worker.started_session.connect(lambda meta, w=worker: self._worker_started(meta, w))
            worker.snapshot.connect(self.throttle.enqueue)
            worker.raw_stream_event.connect(self._handle_raw_stream_event)
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

    def check_iperf_server(self) -> None:
        ok, message = self._run_current_iperf_preflight()
        if ok:
            QMessageBox.information(self, self.i18n.t("online_mr.traffic_test"), message)
        else:
            QMessageBox.warning(self, self.i18n.t("online_mr.traffic_test"), message)

    def retry_iperf_for_running_sessions(self) -> None:
        if not self.enable_iperf_check.isChecked():
            return
        sessions = set(self.workers)
        if not sessions:
            QMessageBox.information(self, self.i18n.t("online_mr.traffic_test"), "当前没有正在采集的会话。")
            return
        ok, message = self._run_current_iperf_preflight()
        self._append_runtime_log(f"IPERF preflight: {message}")
        if not ok:
            QMessageBox.warning(self, self.i18n.t("online_mr.traffic_test"), message)
            return
        self._stop_iperf_workers_for_sessions(sessions, status="STOPPED_BY_RETRY")
        self._retry_iperf_for_sessions(sessions)

    def _preflight_iperf_before_start(self) -> bool:
        if not self.enable_iperf_check.isChecked():
            return True
        ok, message = self._run_current_iperf_preflight()
        self._append_runtime_log(f"IPERF preflight: {message}")
        if ok:
            return True
        QMessageBox.warning(self, self.i18n.t("online_mr.traffic_test"), message)
        return False

    def _run_current_iperf_preflight(self) -> tuple[bool, str]:
        try:
            client_config = self._current_iperf_client_config(duration_seconds=1, follow_collection=False)
        except ValueError as exc:
            return False, str(exc)
        tool = find_iperf_tool(self.paths)
        if tool is None:
            return False, self.i18n.t("iperf.tool_missing")
        result = run_iperf_client_preflight(tool, client_config)
        if result.ok:
            return True, f"打流服务端可用：{client_config.server_ip}:{client_config.port}"
        return False, self._format_iperf_preflight_failure(client_config, result.error_code, result.message)

    def _current_iperf_client_config(self, *, duration_seconds: int, follow_collection: bool) -> IperfClientConfig:
        traffic = IperfTrafficConfig(
            enabled=True,
            server_ip=self.iperf_server_edit.text().strip(),
            port=self.iperf_port_spin.value(),
            protocol=self.iperf_protocol_combo.currentText(),
            direction=self.iperf_direction_combo.currentData() or "upload",
            parallel=self.iperf_parallel_spin.value(),
            interval_seconds=self.iperf_interval_spin.value(),
            target_bandwidth=None,
            tcp_report_threshold_mbps=self._current_iperf_tcp_threshold_mbps(),
            tcp_pacing_enabled=self.iperf_tcp_pacing_check.isChecked(),
            tcp_pacing_mbps=self._current_iperf_tcp_pacing_mbps(),
            udp_bitrate_mbps=self._current_iperf_udp_bitrate_mbps(),
            udp_report_threshold_mbps=self._current_iperf_udp_threshold_mbps(),
            packet_length=self._current_iperf_packet_length(),
            follow_collection=follow_collection,
            duration_seconds=duration_seconds,
        ).normalized()
        if not traffic.server_ip:
            raise ValueError("打流服务端地址不能为空。")
        return self._iperf_client_config_from_traffic(traffic, duration_seconds=duration_seconds, follow_collection=follow_collection)

    @staticmethod
    def _iperf_client_config_from_traffic(config: IperfTrafficConfig, *, duration_seconds: int, follow_collection: bool) -> IperfClientConfig:
        normalized = config.normalized()
        return IperfClientConfig(
            server_ip=normalized.server_ip,
            port=normalized.port,
            protocol=normalized.protocol,
            duration_seconds=duration_seconds,
            interval_seconds=normalized.interval_seconds,
            parallel=normalized.parallel,
            direction=normalized.direction,
            target_bandwidth=normalized.target_bandwidth,
            follow_collection=follow_collection,
            tcp_block_size=normalized.tcp_block_size,
            packet_length=normalized.packet_length,
            tcp_report_threshold_mbps=normalized.tcp_report_threshold_mbps,
            tcp_pacing_enabled=normalized.tcp_pacing_enabled,
            tcp_pacing_mbps=normalized.tcp_pacing_mbps,
            udp_bitrate_mbps=normalized.udp_bitrate_mbps,
            udp_report_threshold_mbps=normalized.udp_report_threshold_mbps,
        ).normalized()

    @staticmethod
    def _format_iperf_preflight_failure(config: IperfClientConfig, error_code: str, message: str) -> str:
        endpoint = f"{config.server_ip}:{config.port}"
        text = str(message or "").strip()
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        if config.server_ip.casefold() in local_hosts and (error_code in {"unable_to_connect", "connection_refused"} or "connection refused" in text.casefold()):
            return f"当前为 127.0.0.1 本机模拟打流，但本机 {config.port} 端口没有 iperf3 服务端监听。请先在网络工具中启动 iperf 服务端，或修改服务端地址/端口。"
        if error_code == "server_busy":
            return f"打流服务端忙：{endpoint} 正在运行其他 iperf 测试，请稍后重试。"
        if error_code in {"unable_to_connect", "connection_refused"}:
            return f"打流服务端不可用：{endpoint} 连接失败。请先启动 iperf3 服务端或修改服务端地址/端口。{text}"
        if error_code == "timed_out":
            return f"打流服务端不可用：{endpoint} 预检查超时。请检查链路、防火墙和端口。"
        return f"打流服务端不可用：{endpoint}。{text}"

    def stop_selected(self) -> None:
        stopped_any = False
        selected_session_ids: set[str] = set()
        for device in self._selected_devices():
            if device.id is None:
                continue
            session_id = self._session_id_for_device(device.id)
            if session_id:
                selected_session_ids.add(session_id)
            fping_worker = self.fping_workers_by_device_id.get(device.id)
            if fping_worker:
                self._set_ping_status(device.id, "stopping")
                fping_worker.stop()
            worker = self.workers_by_device_id.get(device.id)
            if worker:
                app_logger.log_info("ONLINE_MR_STOP_REQUESTED", f"device_id={device.id} session_id={self._session_id_for_device(device.id)}")
                worker.cancel()
                self._update_device_status(device.id, self.i18n.t("online_mr.status_stopping"))
                self._update_summary_status_by_device(device.id, "STOPPING")
                stopped_any = True
        if selected_session_ids:
            self._stop_iperf_workers_for_sessions(selected_session_ids, status="STOPPED_BY_USER")
        if stopped_any:
            self._set_status("STOPPING")
            self._start_stop_animation(1)
        self._reconcile_collection_state()
        self._update_action_state()

    def stop_all(self) -> None:
        self._request_stop_all_collectors()
        self._update_action_state()

    def force_stop_collection(self, reason: str = "force_stop") -> None:
        if self._force_stop_in_progress:
            return
        self._force_stop_in_progress = True
        workers = list({id(worker): worker for worker in list(self.workers_by_device_id.values()) + list(self.workers.values())}.values())
        fping_workers = list({id(worker): worker for worker in list(self.fping_workers_by_device_id.values()) + list(self.fping_workers.values())}.values())
        iperf_workers = list({id(worker): worker for worker in list(self.iperf_batch_workers.values()) + list(self.iperf_workers_by_device_id.values()) + list(self.iperf_workers.values())}.values())
        device_ids = set(self.workers_by_device_id)
        device_ids.update(self.session_to_device_id.values())
        session_ids = set(self.workers)

        app_logger.log_info(
            "ONLINE_MR_FORCE_STOP_REQUESTED",
            f"reason={reason} devices={sorted(device_ids)} sessions={sorted(session_ids)} workers={len(workers)} fping={len(fping_workers)} iperf={len(iperf_workers)}",
        )
        for worker in iperf_workers:
            self._force_stop_probe_worker(worker, status="STOPPED_BY_FORCE_STOP")
        for worker in fping_workers:
            self._force_stop_probe_worker(worker)
        for worker in workers:
            self._force_stop_collector_worker(worker, reason=reason)

        for session_id in list(session_ids):
            device_id = self.session_to_device_id.get(session_id)
            self._finalize_collection_state(device_id=device_id, session_id=session_id, final_status=STATE_FORCED_STOPPED, reason=reason)
        for device_id in list(device_ids):
            if device_id in self.workers_by_device_id:
                self._finalize_collection_state(device_id=device_id, session_id=self._session_id_for_device(device_id), final_status=STATE_FORCED_STOPPED, reason=reason)
            self._update_device_status(device_id, "已强制停止")
            self._update_summary_status_by_device(device_id, STATE_FORCED_STOPPED)
        self.workers.clear()
        self.workers_by_device_id.clear()
        self.session_to_device_id.clear()
        self.fping_workers.clear()
        self.fping_workers_by_device_id.clear()
        self.iperf_workers.clear()
        self.iperf_workers_by_device_id.clear()
        self.iperf_batch_workers.clear()
        self.iperf_batch_sessions.clear()
        self.manager.stop_all()
        for session_id in session_ids:
            self.manager.unregister(session_id)
        for device_id in device_ids:
            self.manager.unregister_device(device_id)
        self._stop_stop_animation()
        self._set_status("STOPPED")
        self.status_label.setText(f"已强制停止 {len(device_ids) or len(workers)} 个采集任务")
        self._append_runtime_log(f"STOP: force stop completed reason={reason}")
        self._update_action_state()

    def _request_stop_all_collectors(self) -> None:
        workers: list[OnlineMrCollectorWorker] = []
        seen_workers: set[int] = set()
        for worker in list(self.workers_by_device_id.values()) + list(self.workers.values()):
            marker = id(worker)
            if marker in seen_workers:
                continue
            seen_workers.add(marker)
            workers.append(worker)

        device_ids: set[int] = set(self.workers_by_device_id)
        device_ids.update(self.session_to_device_id.values())
        session_ids: set[str] = set(self.workers)
        session_ids.update(self.session_to_device_id)

        self._stop_all_iperf_workers(status="STOPPED_BY_USER")
        for worker in list(self.fping_workers_by_device_id.values()):
            worker.stop()
        for device_id in list(self.fping_workers_by_device_id.keys()):
            self._set_ping_status(device_id, "stopping")

        app_logger.log_info(
            "ONLINE_MR_STOP_ALL_REQUESTED",
            f"devices={sorted(device_ids)} sessions={sorted(session_ids)} workers_count={len(workers)} manager_running_count={self.manager.running_count()}",
        )
        for worker in workers:
            device_id = getattr(getattr(worker, "collector", None), "config", None)
            actual_device_id = getattr(device_id, "device_id", None)
            session_id = next((sid for sid, item in self.workers.items() if item is worker), "")
            app_logger.log_info("ONLINE_MR_WORKER_CANCEL_SENT", f"device_id={actual_device_id} session_id={session_id}")
            worker.cancel()
        for device_id in device_ids:
            self._update_device_status(device_id, self.i18n.t("online_mr.status_stopping"))
            self._update_summary_status_by_device(device_id, "STOPPING")
        if workers or device_ids or session_ids:
            self._set_status("STOPPING")
            self._start_stop_animation(max(len(workers), len(device_ids), 1))
        self._reconcile_collection_state()

    def _force_stop_collector_worker(self, worker: object, *, reason: str) -> None:
        try:
            force_stop = getattr(worker, "force_stop", None)
            if callable(force_stop):
                force_stop(reason)
            else:
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
        except Exception as exc:
            app_logger.log_warning("ONLINE_MR_FORCE_STOP_WORKER_FAILED", f"reason={reason} error={exc}")
        self._terminate_qthread_if_running(worker)

    def _force_stop_probe_worker(self, worker: object, *, status: str | None = None) -> None:
        try:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                if status is None:
                    stop()
                else:
                    try:
                        stop(status=status)
                    except TypeError:
                        stop()
        except Exception as exc:
            app_logger.log_warning("ONLINE_MR_FORCE_STOP_PROBE_FAILED", f"status={status or ''} error={exc}")
        self._terminate_qthread_if_running(worker)

    @staticmethod
    def _terminate_qthread_if_running(worker: object) -> None:
        try:
            is_running = getattr(worker, "isRunning", None)
            if callable(is_running) and not is_running():
                return
            terminate = getattr(worker, "terminate", None)
            if callable(terminate):
                terminate()
            wait = getattr(worker, "wait", None)
            if callable(wait):
                wait(100)
        except Exception:
            pass

    def _stop_iperf_workers_for_sessions(self, session_ids: set[str], *, status: str) -> None:
        for batch_key, batch_sessions in list(self.iperf_batch_sessions.items()):
            target_sessions = batch_sessions & session_ids
            if not target_sessions:
                continue
            if batch_sessions - session_ids:
                continue
            worker = self.iperf_batch_workers.get(batch_key)
            if worker is not None:
                self._stop_iperf_worker(worker, status=status)
        for session_id in session_ids:
            if any(session_id in sessions for sessions in self.iperf_batch_sessions.values()):
                continue
            worker = self.iperf_workers.get(session_id)
            if worker is not None:
                self._stop_iperf_worker(worker, status=status)

    def _stop_all_iperf_workers(self, *, status: str) -> None:
        seen_iperf_workers: set[int] = set()
        for worker in list(self.iperf_batch_workers.values()) + list(self.iperf_workers_by_device_id.values()) + list(self.iperf_workers.values()):
            marker = id(worker)
            if marker in seen_iperf_workers:
                continue
            seen_iperf_workers.add(marker)
            self._stop_iperf_worker(worker, status=status)

    @staticmethod
    def _stop_iperf_worker(worker: IperfProcessWorker, *, status: str) -> None:
        try:
            worker.stop(status=status)
        except TypeError:
            worker.stop()

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
        if self.analysis_only:
            selected_dir = self.session_select_combo.currentData()
            if selected_dir:
                return Path(str(selected_dir))
            row = self.history_table.currentRow()
            if row >= 0:
                item = self.history_table.item(row, 8)
                if item is not None and item.text():
                    return Path(item.text())
            return None
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

    def parse_selected_session(self, *, force_reparse: bool = False) -> None:
        session_dir = self._selected_session_dir_for_parse()
        if session_dir is None:
            QMessageBox.warning(
                self,
                self.i18n.t("online_mr.parse_collection_data"),
                self.i18n.t("online_mr.no_session_selected") if self.analysis_only else "Please select a device or history session to parse.",
            )
            return
        if not session_dir.exists():
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), f"Collection directory does not exist: {session_dir}")
            return
        raw_dir = session_dir / "raw"
        if not raw_dir.exists():
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), f"Raw directory was not found: {raw_dir}")
            return
        if not force_reparse and self._load_cached_parse_if_valid(session_dir):
            return
        self._log_page_profile("parse.start", time.perf_counter(), rows=1)
        self._set_parse_running(True, "准备解析", 0)
        self.log_text.append(f"Start parsing collection data: {session_dir}")
        self.parse_worker = OnlineMrParseWorker(session_dir, parent=self, force_reparse=True)
        self.parse_worker.progress.connect(self._parse_progress)
        self.parse_worker.completed.connect(lambda summary, d=session_dir: self._parse_completed(d, summary))
        self.parse_worker.failed.connect(self._parse_failed)
        self.parse_worker.start()

    def _set_parse_running(self, running: bool, message: str = "", percent: int = 0) -> None:
        self.parse_session_button.setEnabled(not running)
        self.force_parse_button.setEnabled(not running)
        self.parse_cancel_button.setVisible(running)
        self.parse_progress_bar.setVisible(running)
        self.parse_progress_label.setVisible(running or bool(message))
        self.parse_progress_bar.setValue(max(0, min(100, int(percent))))
        self.parse_progress_label.setText(message)

    def _set_analysis_task_progress(self, running: bool, message: str = "", percent: int = 0) -> None:
        self.parse_session_button.setEnabled(not running)
        self.force_parse_button.setEnabled(not running)
        self.export_analysis_report_button.setEnabled(not running)
        self.parse_cancel_button.setVisible(False)
        self.parse_progress_bar.setVisible(running)
        self.parse_progress_label.setVisible(running or bool(message))
        self.parse_progress_bar.setValue(max(0, min(100, int(percent))))
        self.parse_progress_label.setText(message)

    def _parse_progress(self, stage: str, current: int, total: int, message: str) -> None:
        percent = int(max(0, min(100, current * 100 / max(1, total))))
        text = f"正在解析：{stage}  {percent}%"
        if message and message != stage:
            text = f"{text}  {message}"
        self._set_parse_running(True, text, percent)
        if current == 0 or percent == 100 or percent % 10 == 0:
            self.log_text.append(text)

    def _cancel_parse_worker(self) -> None:
        if self.parse_worker is None:
            return
        self.parse_cancel_button.setEnabled(False)
        self.parse_progress_label.setText("正在取消解析...")
        self.parse_worker.cancel()

    def _load_cached_parse_if_valid(self, session_dir: Path) -> bool:
        from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser

        try:
            summary = OnlineMrDiagnosisParser(session_dir).cached_summary_if_valid()
        except Exception:
            QMessageBox.information(self, self.i18n.t("online_mr.parse_collection_data"), self.i18n.t("online_mr.parsed_cache_unavailable"))
            return False
        if summary is None:
            return False
        started = self._start_offline_analysis_load(session_dir, task_label="加载已解析结果", profile_phase="load.cached_analysis")
        if started:
            self.log_text.append(f"Parsed cache is valid, loading in background: {session_dir}")
        return started

    def _refresh_parse_button_state(self) -> None:
        if not self.analysis_only:
            self.parse_session_button.setText(self.i18n.t("online_mr.parse_collection_data"))
            return
        session_dir = self._selected_session_dir_for_parse()
        if session_dir is None:
            self.parse_session_button.setText(self.i18n.t("online_mr.parse_selected_session"))
            return
        from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser

        try:
            status = OnlineMrDiagnosisParser(session_dir).cache_status()
        except Exception:
            status = "broken"
        if status == "valid":
            key = "online_mr.load_parsed_cache"
        elif status in {"stale", "broken"}:
            key = "online_mr.reparse_selected_session"
        else:
            key = "online_mr.parse_selected_session"
        self.parse_session_button.setText(self.i18n.t(key))

    def export_analysis_report(self) -> None:
        session_dir = self._selected_session_dir_for_parse()
        if session_dir is None:
            QMessageBox.warning(self, self.i18n.t("online_mr.export_analysis_report"), self.i18n.t("online_mr.no_session_selected"))
            return
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            QMessageBox.warning(self, self.i18n.t("online_mr.export_analysis_report"), "请先解析或加载已解析结果后再导出分析报表")
            return
        default_path = session_dir / "exports" / f"车载MR分析报表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path_text, _filter = QFileDialog.getSaveFileName(self, self.i18n.t("online_mr.export_analysis_report"), str(default_path), "Excel (*.xlsx)")
        if not path_text:
            return
        if self.export_report_worker is not None:
            QMessageBox.information(self, self.i18n.t("online_mr.export_analysis_report"), "离线分析报告正在导出，请稍后")
            return
        self._set_analysis_task_progress(True, "正在导出离线分析报告：准备导出数据 5%", 5)
        worker = OnlineMrReportExportWorker(session_dir, Path(path_text), parent=self)
        self.export_report_worker = worker
        worker.progress.connect(self._export_report_progress)
        worker.completed.connect(self._export_report_completed)
        worker.failed.connect(self._export_report_failed)
        worker.start()

    def _parse_completed(self, session_dir: Path, summary) -> None:
        if not self._can_update_ui():
            self.parse_worker = None
            return
        profile_start = time.perf_counter()
        self._set_parse_running(False, "解析完成", 100)
        self.parse_cancel_button.setEnabled(True)
        self.log_text.append(
            f"Parse completed: active_segments={summary.active_segments}, "
            f"mesh_samples={getattr(summary, 'mesh_samples', 0)}, "
            f"radio_stats_samples={getattr(summary, 'radio_stats_samples', 0)}, "
            f"switch_history_samples={getattr(summary, 'switch_history_samples', 0)}, "
            f"ping_samples={summary.ping_samples}, iperf_samples={summary.iperf_samples}, issues={summary.issues}"
        )
        self.parse_worker = None
        if not self._start_offline_analysis_load(session_dir, task_label="刷新分析结果", profile_phase="render.analysis", profile_start=profile_start, summary=summary):
            self._refresh_parse_button_state()

    def _parse_failed(self, message: str) -> None:
        if not self._can_update_ui():
            self.parse_worker = None
            return
        self._set_parse_running(False, f"解析失败：{message}", 0)
        self.parse_cancel_button.setEnabled(True)
        self.parse_worker = None
        QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), message)

    def _start_offline_analysis_load(
        self,
        session_dir: Path,
        *,
        task_label: str,
        profile_phase: str,
        profile_start: float | None = None,
        summary=None,
    ) -> bool:
        if self.analysis_load_worker is not None:
            self.log_text.append(f"{task_label}仍在后台执行，请稍后")
            return False
        self._analysis_load_task_label = task_label
        self._analysis_load_profile_phase = profile_phase
        self._analysis_load_profile_start = profile_start if profile_start is not None else time.perf_counter()
        self._analysis_load_summary = summary
        self._set_analysis_task_progress(True, f"正在{task_label}：准备后台加载 1%", 1)
        worker = OnlineMrAnalysisLoadWorker(session_dir, parent=self)
        self.analysis_load_worker = worker
        worker.progress.connect(self._analysis_load_progress)
        worker.completed.connect(self._analysis_load_completed)
        worker.failed.connect(self._analysis_load_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return True

    def _analysis_load_progress(self, stage: str, current: int, total: int, message: str) -> None:
        percent = int(max(0, min(100, current * 100 / max(1, total))))
        task_label = self._analysis_load_task_label or "加载已解析结果"
        stage_text = message or stage
        self._set_analysis_task_progress(True, f"正在{task_label}：{stage_text} {percent}%", percent)

    def _analysis_load_completed(self, payload: object) -> None:
        if not self._can_update_ui():
            self.analysis_load_worker = None
            return
        task_label = self._analysis_load_task_label or "加载已解析结果"
        summary = self._analysis_load_summary
        rows = 0
        try:
            if not isinstance(payload, dict):
                raise RuntimeError("后台分析结果格式异常")
            session_dir = Path(payload.get("session_dir") or "")
            self._set_analysis_task_progress(True, f"正在{task_label}：刷新表格显示 90%", 90)
            rows = self._load_offline_analysis(session_dir, include_charts=False)
            self._apply_analysis_chart_payload(session_dir, payload)
            if self._analysis_load_profile_phase:
                self._log_page_profile(self._analysis_load_profile_phase, self._analysis_load_profile_start, rows=rows)
            self.log_text.append(f"{task_label}完成：{session_dir}")
            self.tabs.setCurrentWidget(self.diagnosis_table)
            if rows == 0 and summary is not None:
                message = (
                    "解析完成，但没有生成诊断结果。\n"
                    f"已检查：\n"
                    f"mesh-link：{getattr(summary, 'mesh_samples', 0)} 条\n"
                    f"channelbusy：{getattr(summary, 'channel_samples', 0)} 条\n"
                    f"AP射频统计：{getattr(summary, 'radio_stats_samples', 0)} 条\n"
                    f"主链路切换历史：{getattr(summary, 'switch_history_samples', 0)} 条\n"
                    f"fping：{getattr(summary, 'ping_samples', 0)} 条\n"
                    f"interface-rate：{getattr(summary, 'interface_samples', 0)} 条\n"
                    f"iperf3：{getattr(summary, 'iperf_samples', 0)} 条\n"
                    "请检查 raw 文件格式。"
                )
                self.log_text.append(message)
                QMessageBox.information(self, self.i18n.t("online_mr.parse_collection_data"), message)
            self._set_analysis_task_progress(False, f"{task_label}完成", 100)
        except Exception as exc:
            stack = traceback.format_exc()
            app_logger.log_error("ONLINE_MR_ANALYSIS_LOAD_APPLY_FAILED", f"task={task_label} error={exc}\n{stack}")
            self.log_text.append(f"{task_label}失败：{exc}")
            self._set_analysis_task_progress(False, f"{task_label}失败：{exc}", 0)
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), f"{task_label}失败：{exc}")
        finally:
            self.analysis_load_worker = None
            self._analysis_load_summary = None
            self._refresh_parse_button_state()

    def _analysis_load_failed(self, message: str) -> None:
        task_label = self._analysis_load_task_label or "加载已解析结果"
        app_logger.log_error("ONLINE_MR_ANALYSIS_LOAD_FAILED", f"task={task_label} error={message}")
        if self._can_update_ui():
            self.log_text.append(f"{task_label}失败：{message}")
            self._set_analysis_task_progress(False, f"{task_label}失败：{message}", 0)
            QMessageBox.warning(self, self.i18n.t("online_mr.parse_collection_data"), f"{task_label}失败：{message}")
            self._refresh_parse_button_state()
        self.analysis_load_worker = None
        self._analysis_load_summary = None

    def _export_report_progress(self, stage: str, current: int, total: int, message: str) -> None:
        percent = int(max(0, min(100, current * 100 / max(1, total))))
        self._set_analysis_task_progress(True, f"正在导出离线分析报告：{message or stage} {percent}%", percent)

    def _export_report_completed(self, output_path: str) -> None:
        self.export_report_worker = None
        self._set_analysis_task_progress(False, "导出完成", 100)
        QMessageBox.information(self, self.i18n.t("online_mr.export_analysis_report"), f"已导出：{output_path}")

    def _export_report_failed(self, message: str) -> None:
        self.export_report_worker = None
        app_logger.log_error("ONLINE_MR_ANALYSIS_REPORT_EXPORT_FAILED", message)
        self._set_analysis_task_progress(False, f"导出失败：{message}", 0)
        QMessageBox.warning(self, self.i18n.t("online_mr.export_analysis_report"), message)

    def _load_offline_analysis(self, session_dir: Path, *, show_progress: bool = False, task_label: str = "加载已解析结果", include_charts: bool = True) -> int:
        stages = [
            ("mesh_link", "读取主链路信息", self._load_mesh_link_details),
            ("mesh_link_detail", "读取链路明细", self._load_mesh_link_detail_records),
            ("channel_busy", "读取信道繁忙度", self._load_channel_busy_details),
            ("interface_rate", "读取接口速率", self._load_interface_rate_details),
            ("fping_1s", "读取fping 1s聚合", self._load_fping_1s_details),
            ("iperf", "读取打流数据", self._load_iperf_details),
            ("switch_history", "读取主链路切换历史", self._load_link_switch_history),
            ("active_link_switch_logs", "读取主链路切换日志", self._load_active_link_switch_logs),
            ("radio_statistics", "读取AP射频统计", self._load_radio_statistics_details),
            ("diagnosis", "读取诊断结果", self._load_diagnosis_results),
        ]
        if include_charts:
            stages.append(("analysis_charts", "构建图表数据", self._render_analysis_charts))
        rows = 0
        for index, (name, stage_text, loader) in enumerate(stages, start=1):
            percent = int(index * 100 / max(1, len(stages)))
            if show_progress:
                self._set_analysis_task_progress(True, f"正在{task_label}：{stage_text} {percent}%", percent)
            result = self._safe_load_analysis_table(name, session_dir, loader)
            if name == "diagnosis":
                rows = result
        if show_progress:
            self._set_analysis_task_progress(False, f"{task_label}完成", 100)
        return rows

    def _safe_load_analysis_table(self, table_name: str, session_dir: Path, loader) -> int:
        try:
            result = loader(session_dir)
            return int(result or 0)
        except Exception as exc:
            stack = traceback.format_exc()
            message = f"table={table_name} session_dir={session_dir} error={exc}\n{stack}"
            app_logger.log_error("ONLINE_MR_ANALYSIS_TABLE_LOAD_FAILED", message)
            if hasattr(self, "log_text") and self.log_text is not None:
                self.log_text.append(f"加载分析表格失败：{table_name}，已跳过。{exc}")
            return 0

    def _load_mesh_link_details(self, session_dir: Path) -> int:
        from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrRawBlockSplitter

        self.mesh_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if db_path.exists():
            import sqlite3

            try:
                with sqlite3.connect(db_path) as conn:
                    rows = conn.execute(
                        """
                        SELECT collector_time, COALESCE(NULLIF(device_time, ''), device_clock, collector_time),
                               radio, link_state, COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac),
                               peer_mac, mr_rssi, bssid, mesh_interface, belong_station, belong_section, online_time
                        FROM main_link_samples
                        WHERE UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%'
                        ORDER BY collector_time ASC, id ASC
                        LIMIT 5000
                        """
                    ).fetchall()
            except sqlite3.Error:
                rows = []
            if rows:
                self.mesh_table.setUpdatesEnabled(False)
                try:
                    for row_data in rows:
                        row = self.mesh_table.rowCount()
                        self.mesh_table.insertRow(row)
                        values = [row + 1, *row_data]
                        for column, value in enumerate(values):
                            self._set_table_item(self.mesh_table, row, column, value, active=True)
                finally:
                    self.mesh_table.setUpdatesEnabled(True)
                self._auto_fit_online_table(self.mesh_table, "mesh_link")
                return len(rows)

        raw_path = session_dir / "raw" / "mesh_link_raw.log"
        if not raw_path.exists():
            return 0
        count = 0
        self.mesh_table.setUpdatesEnabled(False)
        for block in OnlineMrRawBlockSplitter().split(raw_path):
            records, _status, _error = parse_mesh_link_text(block.text, block.collected_at)
            for record in records:
                if not str(record.link_state or "").upper().startswith("ACTIVE"):
                    continue
                metrics = record.metrics
                peer_mac = record.peer_mac_raw or record.peer_mac_h3c()
                peer_name = str(metrics.get("peer_name") or "")
                peer_info = self._resolve_peer_cached(peer_name) if peer_name else None
                if not peer_info and peer_mac:
                    peer_info = self._resolve_peer_cached(peer_mac)
                if not peer_info and metrics.get("bssid"):
                    peer_info = self._resolve_peer_cached(str(metrics.get("bssid")))
                peer_info = peer_info or {}
                station = str(peer_info.get("peer_site") or "")
                section = str(peer_info.get("peer_section") or "")
                belong_type = _display_belong_type(peer_info.get("belong_type") or "unknown")
                resolved_peer_name = peer_name or str(peer_info.get("peer_ap_name") or "") or peer_mac
                row = self.mesh_table.rowCount()
                values = [
                    row + 1,
                    block.collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    block.collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    record.radio,
                    record.link_state,
                    resolved_peer_name,
                    peer_mac,
                    metrics.get("local_rssi_db"),
                    metrics.get("bssid") or "",
                    metrics.get("interface") or "",
                    station,
                    section,
                    metrics.get("online_time") or "",
                ]
                self.mesh_table.insertRow(row)
                for column, value in enumerate(values):
                    self._set_table_item(self.mesh_table, row, column, value, active=True)
                count += 1
                if count >= 5000:
                    break
            if count >= 5000:
                break
        self.mesh_table.setUpdatesEnabled(True)
        self._auto_fit_online_table(self.mesh_table, "mesh_link")
        return count

    def _load_mesh_link_detail_records(self, session_dir: Path) -> int:
        import sqlite3

        self.mesh_detail_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            return 0
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT collector_time, COALESCE(NULLIF(device_time, ''), device_clock, collector_time),
                           radio, link_state, peer_mac,
                           COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac),
                           peer_mac, belong_station, belong_section, peer_mac, mr_rssi, bssid,
                           mesh_interface, online_time
                    FROM main_link_samples
                    ORDER BY collector_time ASC, id ASC
                    LIMIT 20000
                    """
                ).fetchall()
        except sqlite3.Error:
            return 0
        self.mesh_detail_table.setUpdatesEnabled(False)
        try:
            for row_data in rows:
                row = self.mesh_detail_table.rowCount()
                self.mesh_detail_table.insertRow(row)
                values = [row + 1, *row_data]
                active = str(row_data[3] or "").upper().startswith("ACTIVE")
                for column, value in enumerate(values):
                    self._set_table_item(self.mesh_detail_table, row, column, value, active=active)
        finally:
            self.mesh_detail_table.setUpdatesEnabled(True)
        self._auto_fit_online_table(self.mesh_detail_table, "mesh_link_detail")
        return len(rows)

    def _load_link_switch_history(self, session_dir: Path) -> int:
        from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrRawBlockSplitter

        self.switch_history_table.setRowCount(0)
        self.switch_history_text.clear()
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if db_path.exists():
            import sqlite3

            try:
                with sqlite3.connect(db_path) as conn:
                    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    if "switch_history_events" in tables:
                        rows = conn.execute(
                            """
                            SELECT event_time_local, radio, old_peer_name, new_peer_name, old_peer_mac, new_peer_mac,
                                   old_belong_station, new_belong_station, old_belong_section, new_belong_section,
                                   switch_reason_text, old_rssi, new_rssi, active_duration
                            FROM switch_history_events
                            ORDER BY event_time_local ASC, id ASC
                            LIMIT 5000
                            """
                        ).fetchall()
                    else:
                        rows = []
            except sqlite3.Error:
                rows = []
            if rows:
                for item in rows:
                    self._append_switch_history_table_row(
                        {
                            "switch_time": item[0],
                            "radio": item[1],
                            "from_peer_name": item[2],
                            "to_peer_name": item[3],
                            "from_peer_mac": item[4],
                            "to_peer_mac": item[5],
                            "from_peer_site": item[6],
                            "to_peer_site": item[7],
                            "from_peer_section": item[8],
                            "to_peer_section": item[9],
                            "reason": item[10],
                            "out_rssi": item[11],
                            "in_rssi": item[12],
                            "active_time": item[13],
                        }
                    )
                self.switch_history_text.setPlainText("\n".join(f"{row[0]}  {row[4]} -> {row[5]}  {row[10]}" for row in rows[:200]))
                self._auto_fit_online_table(self.switch_history_table, "switch_history")
                return len(rows)
        switch_path = session_dir / "raw" / "switch_history_latest.log"
        if switch_path.exists():
            collected_at = datetime.fromtimestamp(switch_path.stat().st_mtime)
            rows = parse_switch_history_text(switch_path.read_text(encoding="utf-8", errors="replace"), collected_at)
            for parsed in rows[:5000]:
                self._append_switch_history_table_row(parsed)
            if rows:
                summary = [
                    f"{row.get('switch_time')}  {self._summary_text(row.get('to_peer_name'))}  {self._summary_text(row.get('to_peer_mac'))}  {self._summary_text(row.get('reason'))}"
                    for row in rows[:200]
                ]
                self.switch_history_text.setPlainText("\n".join(summary))
                self._auto_fit_online_table(self.switch_history_table, "switch_history")
                return len(rows)

        raw_path = session_dir / "raw" / "mesh_link_raw.log"
        if not raw_path.exists():
            self.switch_history_text.setPlainText("无主链路切换数据")
            return 0
        last_peer = ""
        last_peer_name = ""
        last_station = ""
        lines: list[str] = []
        for block in OnlineMrRawBlockSplitter().split(raw_path):
            records, _status, _error = parse_mesh_link_text(block.text, block.collected_at)
            active = summarize_active(records)
            if active is None:
                continue
            metrics = active.metrics
            peer_name = str(metrics.get("peer_name") or "")
            peer = _normalize_mac_key(active.peer_mac_raw) or active.peer_mac_raw or active.peer_mac_h3c()
            if not peer:
                continue
            station = ""
            if peer_name:
                station = str((self._resolve_peer_cached(peer_name) or {}).get("peer_site") or "")
            if not station:
                station = str((self._resolve_peer_cached(active.peer_mac_raw or peer) or {}).get("peer_site") or "")
            if not station and metrics.get("bssid"):
                station = str((self._resolve_peer_cached(str(metrics.get("bssid"))) or {}).get("peer_site") or "")
            if last_peer and last_peer != peer:
                parsed = {
                    "switch_time": block.collected_at.isoformat(sep=" ", timespec="milliseconds"),
                    "radio": active.radio,
                    "from_peer_name": last_peer_name,
                    "to_peer_name": peer_name,
                    "from_peer_mac": last_peer,
                    "to_peer_mac": peer,
                    "from_peer_site": last_station,
                    "to_peer_site": station,
                    "reason": "ACTIVE peer changed",
                    "raw_line": active.raw_line,
                }
                self._append_switch_history_table_row(parsed)
                lines.append(f"{parsed['switch_time']}  {last_peer} -> {peer}")
            last_peer = peer
            last_peer_name = peer_name
            last_station = station
        self.switch_history_text.setPlainText("\n".join(lines) if lines else "未检测到主链路切换")
        self._auto_fit_online_table(self.switch_history_table, "switch_history")
        return len(lines)

    def _append_switch_history_table_row(self, parsed: dict[str, object]) -> None:
        from_mac = str(parsed.get("from_peer_mac") or "")
        to_mac = str(parsed.get("to_peer_mac") or "")
        from_station = str(parsed.get("from_peer_site") or "")
        to_station = str(parsed.get("to_peer_site") or "")
        if not from_station and from_mac:
            from_station = str((self._resolve_peer_cached(from_mac) or {}).get("peer_site") or "")
        if not to_station and to_mac:
            to_station = str((self._resolve_peer_cached(to_mac) or {}).get("peer_site") or "")
        if not to_station and parsed.get("to_peer_name"):
            to_station = str((self._resolve_peer_cached(str(parsed.get("to_peer_name"))) or {}).get("peer_site") or "")
        to_section = str(parsed.get("to_peer_section") or parsed.get("belong_section") or "")
        if not to_section and to_mac:
            to_section = str((self._resolve_peer_cached(to_mac) or {}).get("peer_section") or "")
        if not to_section and parsed.get("to_peer_name"):
            to_section = str((self._resolve_peer_cached(str(parsed.get("to_peer_name"))) or {}).get("peer_section") or "")
        row = self.switch_history_table.rowCount()
        values = [
            row + 1,
            parsed.get("switch_time"),
            parsed.get("radio") or 1,
            parsed.get("from_peer_name") or "-",
            parsed.get("to_peer_name"),
            from_mac or "-",
            to_mac,
            from_station,
            to_station,
            to_section,
            parsed.get("reason") or parsed.get("role"),
            _format_in_out_rssi(parsed.get("in_rssi"), parsed.get("out_rssi")),
            parsed.get("active_time"),
        ]
        self.switch_history_table.insertRow(row)
        reason = str(parsed.get("reason") or parsed.get("role") or "")
        warning = "fault" in reason.lower()
        for column, value in enumerate(values):
            self._set_table_item(self.switch_history_table, row, column, value, emphasize=column in {4, 6, 8, 9}, warning=warning)

    def _load_active_link_switch_logs(self, session_dir: Path) -> int:
        import sqlite3

        self.active_link_switch_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            self.active_link_switch_table.setToolTip(self.i18n.t("online_mr.active_link_switch_logs_empty"))
            return 0
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT 'terminal_monitor', device_time, device_name,
                           old_peer_name, old_peer_mac, old_rssi, old_belong_station, old_belong_section, '', CASE WHEN old_peer_mac IS NULL OR old_peer_mac = '' OR old_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                           new_peer_name, new_peer_mac, new_rssi, new_belong_station, new_belong_section, '', CASE WHEN new_peer_mac IS NULL OR new_peer_mac = '' OR new_peer_mac LIKE '0000%' THEN 'empty_link' ELSE '' END,
                           peer_quantity, link_quantity, switch_reason_code, switch_reason_text
                    FROM switch_realtime_events
                    ORDER BY device_time ASC, id ASC
                    LIMIT 5000
                    """
                ).fetchall()
        except sqlite3.Error:
            self.active_link_switch_table.setToolTip(self.i18n.t("online_mr.active_link_switch_logs_empty"))
            return 0
        if not rows:
            self.active_link_switch_table.setToolTip(self.i18n.t("online_mr.active_link_switch_logs_empty"))
            return 0
        self.active_link_switch_table.setToolTip("")
        for row_data in rows:
            row = self.active_link_switch_table.rowCount()
            self.active_link_switch_table.insertRow(row)
            from_empty = str(row_data[9] or "") == "empty_link"
            to_empty = str(row_data[16] or "") == "empty_link"
            values = [
                row + 1,
                row_data[1],
                row_data[2],
                self.i18n.t("online_mr.empty_link") if from_empty else row_data[3],
                "-" if from_empty else row_data[4],
                "-" if from_empty else row_data[5],
                row_data[6] or "-",
                row_data[7] or "-",
                self.i18n.t("online_mr.empty_link") if to_empty else row_data[10],
                "-" if to_empty else row_data[11],
                "-" if to_empty else row_data[12],
                row_data[13] or "-",
                row_data[14] or "-",
                row_data[17],
                row_data[18],
                row_data[19],
                row_data[20],
            ]
            reason_code = row_data[19]
            warning = reason_code == 4 or to_empty
            active = from_empty and not to_empty
            for column, value in enumerate(values):
                self._set_table_item(self.active_link_switch_table, row, column, value, active=active and column in {8, 9, 10, 11, 16}, emphasize=column in {8, 9, 10, 11}, warning=warning and column in {0, 8, 10, 16})
        self._auto_fit_online_table(self.active_link_switch_table, "active_link_switch_logs")
        return len(rows)

    def _load_channel_busy_details(self, session_dir: Path) -> int:
        import sqlite3

        self.channel_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT device_time, radio, ctl_channel, bandwidth,
                       record_interval, ctl_busy, tx_busy, rx_busy
                FROM channel_busy_records
                WHERE COALESCE(row_index, 1) = 1
                ORDER BY device_time ASC, COALESCE(row_index, 1) ASC
                LIMIT 10000
                """
            ).fetchall()
        self.channel_table.setUpdatesEnabled(False)
        try:
            for row_data in rows:
                row = self.channel_table.rowCount()
                self.channel_table.insertRow(row)
                values = [
                    row + 1,
                    row_data[0],
                    row_data[1],
                    row_data[2],
                    row_data[3],
                    row_data[4],
                    row_data[5],
                    row_data[6],
                    row_data[7],
                ]
                for column, value in enumerate(values):
                    self._set_table_item(self.channel_table, row, column, value)
        finally:
            self.channel_table.setUpdatesEnabled(True)
        self._auto_fit_online_table(self.channel_table, "channel_busy")
        return len(rows)

    def _load_interface_rate_details(self, session_dir: Path) -> int:
        import sqlite3

        self.interface_rate_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT device_time, direction, COALESCE(NULLIF(interface_normalized, ''), interface_name), usage_percent,
                       total_pps, broadcast_pps, multicast_pps
                FROM interface_rate_samples
                WHERE lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xge%'
                  AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'xgigabitethernet%'
                  AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'ten-gigabitethernet%'
                  AND lower(COALESCE(NULLIF(interface_normalized, ''), interface_name, '')) NOT LIKE 'tengigabitethernet%'
                ORDER BY device_time ASC
                LIMIT 5000
                """
            ).fetchall()
        for row_data in rows:
            row = self.interface_rate_table.rowCount()
            self.interface_rate_table.insertRow(row)
            values = [row + 1, *row_data]
            for column, value in enumerate(values):
                self._set_table_item(self.interface_rate_table, row, column, value)
        self._auto_fit_online_table(self.interface_rate_table, "interface_rate")
        return len(rows)

    def _load_fping_1s_details(self, session_dir: Path) -> int:
        import sqlite3

        self.fping_1s_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            return 0
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time) AS display_time,
                           COALESCE(NULLIF(device_bucket_time, ''), '-'),
                           COALESCE(NULLIF(local_bucket_time, ''), NULLIF(bucket_time, ''), '-'),
                           target_ip,
                           COALESCE(target_name, ''),
                           sent, received,
                           COALESCE(lost, sent - received),
                           loss_percent, avg_latency_ms,
                           min_latency_ms, max_latency_ms, jitter_ms,
                           COALESCE(status, '')
                    FROM fping_1s_summary
                    ORDER BY display_time ASC, target_ip ASC
                    LIMIT 20000
                    """
                ).fetchall()
        except sqlite3.Error:
            try:
                with sqlite3.connect(db_path) as conn:
                    rows = conn.execute(
                        """
                        SELECT bucket_time, '-', bucket_time, target_ip,
                               COALESCE(target_name, ''),
                               sent, received,
                               COALESCE(lost, sent - received),
                               loss_percent, avg_latency_ms,
                               min_latency_ms, max_latency_ms, jitter_ms,
                               COALESCE(status, '')
                        FROM fping_1s_summary
                        ORDER BY bucket_time ASC, target_ip ASC
                        LIMIT 20000
                        """
                    ).fetchall()
            except sqlite3.Error:
                return 0
        self.fping_1s_table.setUpdatesEnabled(False)
        try:
            for row_data in rows:
                row = self.fping_1s_table.rowCount()
                self.fping_1s_table.insertRow(row)
                values = [row + 1, *row_data[:-1], self._fping_status_label(row_data[-1])]
                for column, value in enumerate(values):
                    self._set_table_item(self.fping_1s_table, row, column, value)
        finally:
            self.fping_1s_table.setUpdatesEnabled(True)
        self._auto_fit_online_table(self.fping_1s_table, "fping_1s")
        return len(rows)

    @staticmethod
    def _fping_status_label(value: object) -> str:
        text = str(value or "").strip().lower()
        if text in {"ok", "success", "normal"}:
            return "正常"
        if text in {"loss", "lost"}:
            return "丢包"
        if text in {"timeout", "time_out"}:
            return "超时"
        if text in {"no_data", "nodata"}:
            return "无数据"
        if text in {"error", "failed", "fail"}:
            return "错误"
        return str(value or "-") or "-"

    def _load_iperf_details(self, session_dir: Path) -> int:
        import sqlite3

        self.iperf_table.setRowCount(0)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(interval_center_time, collector_time), bitrate_mbps, retransmits, transfer_bytes, raw_line
                FROM iperf_intervals
                ORDER BY COALESCE(interval_center_time, collector_time) ASC
                LIMIT 5000
                """
            ).fetchall()
        for row_data in rows:
            row = self.iperf_table.rowCount()
            self.iperf_table.insertRow(row)
            values = [row_data[0], None if row_data[1] is None else f"{float(row_data[1]):.2f}", row_data[2], row_data[3], row_data[4]]
            for column, value in enumerate(values):
                self._set_table_item(self.iperf_table, row, column, value)
        self._auto_fit_online_table(self.iperf_table, "iperf")
        return len(rows)

    def _load_radio_statistics_details(self, session_dir: Path) -> int:
        import sqlite3

        self.statistics_text.clear()
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            return 0
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT collector_time, metric_name, metric_value, metric_unit
                FROM radio_statistics_samples
                ORDER BY collector_time ASC, id ASC
                LIMIT 2000
                """
            ).fetchall()
        lines: list[str] = []
        grouped: dict[str, list[str]] = {}
        for collector_time, metric_name, metric_value, metric_unit in rows:
            value_text = self._summary_text(metric_value)
            if metric_unit:
                value_text = f"{value_text}{metric_unit}"
            grouped.setdefault(str(collector_time or "-"), []).append(f"{metric_name}={value_text}")
        for collector_time, metrics in grouped.items():
            lines.append(f"{collector_time}  " + "  ".join(metrics))
        if not lines:
            raw_path = session_dir / "raw" / "ap_radio_statistics_raw.log"
            if raw_path.exists():
                parsed = parse_ap_radio_statistics_text(raw_path.read_text(encoding="utf-8", errors="replace"))
                counters = parsed.get("counters") if isinstance(parsed, dict) else {}
                if isinstance(counters, dict) and counters:
                    lines.append("raw summary: " + "  ".join(f"{key}={value}" for key, value in counters.items()))
        self.statistics_text.setPlainText("\n".join(lines) if lines else "无 AP 射频统计解析结果")
        return len(rows)

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
                       m.avg_mbps, m.max_mbps, m.avg_tx_busy, m.avg_rx_busy, s.event_type, s.details_json
                FROM active_segments s
                LEFT JOIN active_segment_metrics m ON m.segment_id = s.id
                ORDER BY s.start_time
                """
            ).fetchall()
        for row_data in rows:
            row = self.diagnosis_table.rowCount()
            self.diagnosis_table.insertRow(row)
            in_pps, out_pps = self._interface_pps_from_details(row_data[13])
            values = list(row_data[:2]) + [row_data[2], row_data[3], row_data[4], row_data[5], row_data[6], row_data[8], row_data[9], row_data[10], row_data[11], in_pps, out_pps, row_data[12]]
            for column, value in enumerate(values):
                self._set_table_item(self.diagnosis_table, row, column, value)
        self._auto_fit_online_table(self.diagnosis_table, "diagnosis")
        return len(rows)

    def _render_analysis_charts(self, session_dir: Path) -> None:
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not db_path.exists():
            self._clear_analysis_charts(session_dir)
            return
        from netconsole.services.vehicle_mr_offline_analysis import build_vehicle_mr_analysis_chart_payload

        payload = build_vehicle_mr_analysis_chart_payload(session_dir)
        self._apply_analysis_chart_payload(session_dir, payload)

    def _clear_analysis_charts(self, session_dir: Path) -> None:
        self._hide_all_analysis_chart_hovers()
        if self.analysis_chart_session_dir != session_dir:
            self.analysis_chart_session_dir = session_dir
            self.analysis_chart_locked_time = None
            for widget in self.analysis_chart_widgets.values():
                widget.clear_locked_time(redraw=False)
        self.analysis_chart_locked_time = None
        for key, _title in self._analysis_chart_titles():
            widget = self.analysis_chart_widgets.get(key)
            if widget is not None:
                widget.clear_locked_time(redraw=False)
                widget.set_summary({})
                widget.clear("未解析到图表数据")

    def _apply_analysis_chart_payload(self, session_dir: Path, payload: dict[str, object]) -> None:
        self._hide_all_analysis_chart_hovers()
        if self.analysis_chart_session_dir != session_dir:
            self.analysis_chart_session_dir = session_dir
            self.analysis_chart_locked_time = None
            for widget in self.analysis_chart_widgets.values():
                widget.clear_locked_time(redraw=False)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        charts = payload.get("charts") if isinstance(payload.get("charts"), dict) else {}
        for key, chart in charts.items():
            widget = self.analysis_chart_widgets.get(key)
            if widget is None:
                continue
            widget.set_summary(summary)
            widget.set_locked_time(self.analysis_chart_locked_time, redraw=False)
            widget.render_chart(chart)
            self.analysis_chart_canvases[key] = widget.canvas
            self.analysis_chart_views[key] = widget.view
            if widget.axis is not None:
                self.analysis_chart_axes[key] = widget.axis

    def _analysis_chart_hover_changed(self, key: str, controller: object) -> None:
        if controller is None:
            self.analysis_chart_hover_controllers.pop(key, None)
            return
        self.analysis_chart_hover_controllers[key] = controller

    def _set_analysis_chart_locked_time(self, timestamp: object) -> None:
        if not isinstance(timestamp, datetime):
            return
        self.analysis_chart_locked_time = timestamp.replace(tzinfo=None)
        self._hide_all_analysis_chart_hovers()
        for widget in self.analysis_chart_widgets.values():
            widget.set_locked_time(self.analysis_chart_locked_time)

    def _clear_analysis_chart_locked_time(self) -> None:
        self.analysis_chart_locked_time = None
        self._hide_all_analysis_chart_hovers()
        for widget in self.analysis_chart_widgets.values():
            widget.clear_locked_time()

    def _hide_all_analysis_chart_hovers(self) -> None:
        for controller in list(self.analysis_chart_hover_controllers.values()):
            controller.hide()

    def _analysis_chart_tab_changed(self, _index: int) -> None:
        self._hide_all_analysis_chart_hovers()

    @staticmethod
    def _interface_pps_from_details(details_json: object) -> tuple[object, object]:
        try:
            details = json.loads(str(details_json or "{}"))
        except json.JSONDecodeError:
            return None, None
        interface = details.get("interface_rate") if isinstance(details, dict) else {}
        if not isinstance(interface, dict):
            return None, None
        inbound = interface.get("inbound") if isinstance(interface.get("inbound"), dict) else {}
        outbound = interface.get("outbound") if isinstance(interface.get("outbound"), dict) else {}
        return inbound.get("avg_pps"), outbound.get("avg_pps")

    def _worker_started(self, meta, worker: OnlineMrCollectorWorker) -> None:
        if self._shutdown_requested:
            worker.cancel()
            return
        self.manager.register(meta.session_id, worker)
        self._attached_worker_sessions.add(meta.session_id)
        if meta.device_id is not None:
            self.session_to_device_id[meta.session_id] = int(meta.device_id)
            self.workers_by_device_id[int(meta.device_id)] = worker
            if not self.analysis_only:
                self._ensure_output_widget(int(meta.device_id), meta.session_id)
        self.workers[meta.session_id] = worker
        if meta.session_dir:
            self.session_dirs[meta.session_id] = Path(meta.session_dir)
            self._ensure_event_pipeline(meta.session_id, Path(meta.session_dir))
            if meta.device_id is not None:
                self.last_session_dir_by_device_id[int(meta.device_id)] = Path(meta.session_dir)
        if not getattr(worker.collector, "cancelled", False) and meta.status != STATE_STOPPING:
            self._start_fping_worker(meta, worker)
            self._start_iperf_worker(meta, worker)
        self._set_status(meta.status)
        if meta.device_id is not None:
            self._update_device_status(int(meta.device_id), self._status_text(meta.status))
        self._fill_view_devices(prefer_device_id=int(meta.device_id) if meta.device_id is not None else None)
        self._fill_history()

    def _worker_completed(self, session_id: str) -> None:
        app_logger.log_info("ONLINE_MR_WORKER_FINISHED", f"session_id={session_id}")
        self._finalize_collection_state(device_id=None, session_id=session_id, final_status="STOPPED", reason="completed")

    def _worker_failed(self, message: str, device_id: int | None = None) -> None:
        session_id = self._session_id_for_device(device_id) if device_id is not None else None
        self._finalize_collection_state(device_id=device_id, session_id=session_id, final_status="FAILED", reason=message)
        if not self._can_update_ui():
            return
        QMessageBox.warning(self, self.i18n.t("rail_transit.online_mr_collection"), message)

    def _finalize_collection_state(
        self,
        *,
        device_id: int | None,
        session_id: str | None,
        final_status: str,
        reason: str | None = None,
    ) -> None:
        if session_id and device_id is None:
            device_id = self.session_to_device_id.get(session_id)
        if device_id is not None and not session_id:
            session_id = self._session_id_for_device(device_id)
        if session_id:
            self.manager.unregister(session_id)
            self.workers.pop(session_id, None)
            self.session_to_device_id.pop(session_id, None)
            self.session_dirs.pop(session_id, None)
            self.fping_workers.pop(session_id, None)
            self.iperf_workers.pop(session_id, None)
            for batch_key, sessions in list(self.iperf_batch_sessions.items()):
                sessions.discard(session_id)
                if not sessions:
                    self.iperf_batch_sessions.pop(batch_key, None)
                    worker = self.iperf_batch_workers.pop(batch_key, None)
                    if worker is not None:
                        self._stop_iperf_worker(worker, status="STOPPED_BY_COLLECTION_END")
            self.event_buses.pop(session_id, None)
            self.realtime_buffers.pop(session_id, None)
            self.diagnosis_engines.pop(session_id, None)
            self.event_parsers.pop(session_id, None)
            self.realtime_stream_parsers.pop(session_id, None)
            self._stream_interface_direction.pop(session_id, None)
            self.realtime_cache.close_session(session_id)
        if device_id is not None:
            self.manager.unregister_device(device_id)
            self.workers_by_device_id.pop(device_id, None)
            self.iperf_workers_by_device_id.pop(device_id, None)
            self.fping_workers_by_device_id.pop(device_id, None)
            self._last_active_peer_by_device_id.pop(device_id, None)
            self._stream_sample_count_by_device_id.pop(device_id, None)
        app_logger.log_info(
            "ONLINE_MR_COLLECTION_FINALIZED",
            f"device_id={device_id} session_id={session_id} new_status={final_status} reason={reason or ''} workers_count={len(self.workers)} manager_running_count={self.manager.running_count()}",
        )
        if not self._can_update_ui():
            self._running_count = self._site_running_count()
            return
        if device_id is not None:
            self._update_device_status(device_id, self._status_text(final_status))
            self._update_summary_status_by_device(device_id, final_status)
        self._reconcile_collection_state()
        self._set_status("STOPPED" if not self.workers_by_device_id else "COLLECTING")
        if not self.workers_by_device_id:
            self._stop_stop_animation()
        self._running_count = self._site_running_count()
        if not self._can_update_ui():
            return
        self.running_count_label.setText(str(self._running_count))
        self._refresh_top_metrics()
        self._fill_view_devices(prefer_device_id=device_id)
        self._fill_history()
        self.session_history_changed.emit()
        self._update_action_state()

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
        worker.failed.connect(lambda message: self._append_runtime_log(f"Fping: {message}"))
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
        client_config = self._iperf_client_config_from_traffic(
            config,
            duration_seconds=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
            follow_collection=True,
        )
        command = build_iperf_client_args(tool, client_config)
        session_dir = Path(meta.session_dir)
        log_file = session_dir / "raw" / "iperf_client_raw.log"
        batch_key = self._iperf_batch_key(client_config)
        iperf_context = self._iperf_context_for_meta(meta, client_config, batch_key)
        existing = self.iperf_batch_workers.get(batch_key)
        if existing is not None and self._is_iperf_worker_reusable(existing):
            existing.add_mirror_log_file(log_file, context=iperf_context)
            self.iperf_workers[meta.session_id] = existing
            self.iperf_batch_sessions.setdefault(batch_key, set()).add(meta.session_id)
            if meta.device_id is not None:
                self.iperf_workers_by_device_id[int(meta.device_id)] = existing
            self._append_runtime_log(f"IPERF: reuse batch worker for session {meta.session_id}")
            return
        if existing is not None:
            self._append_runtime_log("IPERF: discard failed batch worker and create new one")
            self._stop_iperf_worker(existing, status="STOPPED_BY_RETRY")
        self.iperf_batch_workers.pop(batch_key, None)
        self.iperf_batch_sessions.pop(batch_key, None)
        worker = IperfProcessWorker(
            tool,
            command,
            log_file,
            store=None,
            session_id=meta.session_id,
            device_id=meta.device_id,
            config=client_config,
            mode="client",
            context=iperf_context,
            parent=self,
        )
        worker.line_received.connect(lambda line: self._append_runtime_log(line))
        worker.interval_received.connect(lambda row, key=batch_key: self._append_iperf_interval_for_batch(key, row))
        worker.error_received.connect(lambda error, key=batch_key: self._handle_iperf_error_for_batch(key, error))
        worker.completed.connect(lambda _status, key=batch_key: self._iperf_batch_completed(key))
        worker.failed.connect(lambda message, key=batch_key: self._iperf_batch_failed(key, message))
        self.iperf_batch_workers[batch_key] = worker
        self.iperf_batch_sessions[batch_key] = {meta.session_id}
        self.iperf_workers[meta.session_id] = worker
        if meta.device_id is not None:
            self.iperf_workers_by_device_id[int(meta.device_id)] = worker
        worker.start()

    def _is_iperf_worker_reusable(self, worker: IperfProcessWorker) -> bool:
        is_running = getattr(worker, "isRunning", None)
        if not callable(is_running) or not is_running():
            return False
        runner = getattr(worker, "runner", None)
        if runner is None:
            return True
        if getattr(runner, "stop_requested", False):
            return False
        if getattr(runner, "last_error_code", ""):
            return False
        last_status = str(getattr(runner, "last_status", "") or "").upper()
        if last_status and last_status not in {"CREATED", "RUNNING"}:
            return False
        process = getattr(runner, "process", None)
        if process is not None and callable(getattr(process, "poll", None)) and process.poll() is not None:
            return False
        return True

    def _retry_iperf_for_sessions(self, session_ids: set[str]) -> None:
        for session_id in sorted(session_ids):
            worker = self.workers.get(session_id)
            if worker is None or worker.collector.session is None:
                continue
            self._start_iperf_worker(worker.collector.session.meta, worker)

    def _schedule_iperf_retry_for_sessions(self, session_ids: set[str]) -> None:
        active_sessions = {session_id for session_id in session_ids if session_id in self.workers}
        if not active_sessions or not self.enable_iperf_check.isChecked():
            return

        def retry() -> None:
            if not self._can_update_ui():
                return
            still_active = {session_id for session_id in active_sessions if session_id in self.workers}
            if not still_active:
                return
            ok, message = self._run_current_iperf_preflight()
            self._append_runtime_log(f"IPERF reconnect preflight: {message}")
            if ok:
                self._retry_iperf_for_sessions(still_active)

        QTimer.singleShot(1000, retry)

    def _iperf_completed(self, session_id: str, device_id: int | None) -> None:
        self.iperf_workers.pop(session_id, None)
        if device_id is not None:
            self.iperf_workers_by_device_id.pop(int(device_id), None)

    def _iperf_batch_key(self, config: IperfClientConfig) -> tuple[object, ...]:
        cfg = config.normalized()
        return (
            self.site_name,
            cfg.server_ip,
            cfg.port,
            cfg.protocol,
            cfg.direction,
            cfg.parallel,
            cfg.target_bandwidth or "",
            cfg.tcp_block_size or "",
            cfg.packet_length or "",
            cfg.udp_bitrate_mbps or "",
        )

    @staticmethod
    def _iperf_batch_label(batch_key: tuple[object, ...]) -> str:
        return "|".join(str(item) for item in batch_key)

    def _iperf_context_for_meta(self, meta, config: IperfClientConfig, batch_key: tuple[object, ...]) -> dict[str, object]:
        cfg = config.normalized()
        batch_label = self._iperf_batch_label(batch_key)
        return {
            "batch_key": batch_label,
            "session_id": getattr(meta, "session_id", ""),
            "device_id": getattr(meta, "device_id", None),
            "device_name": getattr(meta, "device_name", "") or self._device_name_for_id(getattr(meta, "device_id", None)),
            "mode": "client",
            "server": cfg.server_ip,
            "port": cfg.port,
            "protocol": cfg.protocol,
            "direction": cfg.direction,
            "bandwidth": cfg.target_bandwidth or "",
            "tcp_report_threshold_mbps": cfg.tcp_report_threshold_mbps or "",
            "tcp_pacing_enabled": cfg.tcp_pacing_enabled,
            "tcp_pacing_mbps": cfg.tcp_pacing_mbps or "",
            "udp_bitrate_mbps": cfg.udp_bitrate_mbps or "",
            "udp_report_threshold_mbps": cfg.udp_report_threshold_mbps or "",
            "tcp_block_size": cfg.tcp_block_size or "",
            "packet_length": cfg.packet_length or "",
            "duration_mode": "follow_collection",
            "protection_duration_seconds": cfg.duration_seconds,
            "stop_policy": "stop_with_collection",
        }

    def _device_name_for_id(self, device_id: int | None) -> str:
        if device_id is None:
            return ""
        for device in self.devices:
            if device.id == device_id:
                return device.name
        return ""

    def _append_iperf_interval_for_batch(self, batch_key: tuple[object, ...], row: dict[str, object]) -> None:
        for session_id in list(self.iperf_batch_sessions.get(batch_key, set())):
            device_id = self.session_to_device_id.get(session_id)
            if device_id is None:
                continue
            self._append_iperf_interval(device_id, row)

    def _handle_iperf_error_for_batch(self, batch_key: tuple[object, ...], error: dict[str, object]) -> None:
        if str(error.get("error_code") or "") == "server_busy":
            self._append_runtime_log("IPERF：服务端忙")
        for session_id in list(self.iperf_batch_sessions.get(batch_key, set())):
            device_id = self.session_to_device_id.get(session_id)
            if device_id is None:
                continue
            self._publish_iperf_error_event(session_id, int(device_id), error)

    def _iperf_batch_completed(self, batch_key: tuple[object, ...]) -> None:
        sessions = self.iperf_batch_sessions.pop(batch_key, set())
        worker = self.iperf_batch_workers.pop(batch_key, None)
        for session_id in sessions:
            self.iperf_workers.pop(session_id, None)
            device_id = self.session_to_device_id.get(session_id)
            if device_id is not None and self.iperf_workers_by_device_id.get(int(device_id)) is worker:
                self.iperf_workers_by_device_id.pop(int(device_id), None)

    def _iperf_batch_failed(self, batch_key: tuple[object, ...], message: str) -> None:
        sessions = set(self.iperf_batch_sessions.get(batch_key, set()))
        self._append_runtime_log(f"IPERF: {message}")
        self._iperf_batch_completed(batch_key)
        self._schedule_iperf_retry_for_sessions(sessions)

    def _append_iperf_interval(self, device_id: int | None, row: dict[str, object]) -> None:
        if device_id is not None:
            self.latest_iperf_by_device_id[int(device_id)] = row
        if not self._can_update_ui():
            return
        if device_id is not None:
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
            self._set_table_item(self.iperf_table, table_row, column, value)
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
                timestamp=self._iperf_event_time(row),
                session_id=session_id,
                device_id=device_id,
                source="iperf3",
                module="iperf",
                event_type=EVENT_IPERF3_SAMPLE,
                payload=dict(row),
                raw=str(row.get("raw_line") or ""),
            )
        )

    def _publish_iperf_error_event(self, session_id: str, device_id: int, error: dict[str, object]) -> None:
        bus = self.event_buses.get(session_id)
        if bus is None:
            session_dir = self.session_dirs.get(session_id)
            if session_dir is None:
                return
            bus = self._ensure_event_pipeline(session_id, session_dir)
        bus.publish(
            OnlineMrEvent(
                timestamp=self._iperf_event_time(error),
                session_id=session_id,
                device_id=device_id,
                source="iperf3",
                module="iperf",
                event_type=EVENT_IPERF3_ERROR,
                payload=dict(error),
                raw=str(error.get("raw_line") or ""),
            )
        )

    @staticmethod
    def _iperf_event_time(payload: dict[str, object]) -> datetime:
        value = payload.get("collector_time")
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("T", " "))
            except ValueError:
                pass
        return datetime.now()

    def _flush_snapshot(self) -> None:
        if not self._can_update_ui():
            self.throttle.pending_snapshot = None
            return
        snapshot = self.throttle.flush()
        if snapshot is None:
            self._refresh_realtime_view()
            return
        self._publish_snapshot_event(snapshot)
        self._set_status(snapshot.status)
        self._upsert_summary(snapshot)
        self._append_mesh_snapshot(snapshot)
        self._refresh_realtime_view()

    def _ensure_event_pipeline(self, session_id: str, session_dir: Path) -> OnlineMrEventBus:
        bus = self.event_buses.get(session_id)
        if bus is not None:
            return bus
        bus = OnlineMrEventBus()
        buffer = SlidingWindowBuffer(window_seconds=60)
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

    def _handle_raw_stream_event(self, event: OnlineMrEvent) -> None:
        if self._shutdown_requested:
            return
        session_dir = self.session_dirs.get(event.session_id)
        if session_dir is None:
            return
        raw_started = datetime.now()
        app_logger.log_info(
            "ONLINE_MR_REALTIME_RAW_LINE",
            f"device_id={event.device_id} session_id={event.session_id} module={event.module} raw_line_prefix={str(event.raw or '')[:80]} output_render_enabled={self.output_render_enabled}",
        )
        self._append_raw_stream_text(event)
        bus = self._ensure_event_pipeline(event.session_id, session_dir)
        parser = self.realtime_stream_parsers.setdefault(event.session_id, OnlineMrRealtimeParser())
        sample = parser.parse_raw_event(event)
        if sample is None:
            return
        parsed_event = OnlineMrEvent(
            timestamp=event.timestamp,
            session_id=event.session_id,
            device_id=event.device_id,
            source=event.source,
            module=event.module,
            event_type=event.event_type,
            payload=sample.payload,
            raw=event.raw,
        )
        if event.device_id is not None:
            self._stream_sample_count_by_device_id[int(event.device_id)] = self._stream_sample_count_by_device_id.get(int(event.device_id), 0) + 1
        self.realtime_cache.append_parsed_sample(event.session_id, parsed_event)
        elapsed_ms = int((datetime.now() - raw_started).total_seconds() * 1000)
        app_logger.log_info(
            "ONLINE_MR_REALTIME_MESH_ROW_PARSED" if parsed_event.module == "mesh" else "ONLINE_MR_REALTIME_EVENT_PARSED",
            f"device_id={event.device_id} session_id={event.session_id} module={parsed_event.module} peer_name={parsed_event.payload.get('peer_name', '')} peer_mac={parsed_event.payload.get('peer_mac', '')} link_state={parsed_event.payload.get('link_state', '')} mr_rssi={parsed_event.payload.get('mr_rssi', '')} elapsed_ms_from_raw_to_ui={elapsed_ms}",
        )
        self._publish_link_switch_if_needed(bus, parsed_event)
        bus.publish(parsed_event)
        self._refresh_realtime_view()

    def _append_raw_stream_text(self, event: OnlineMrEvent) -> None:
        text = str(event.raw or "").rstrip()
        if not text:
            return
        device_id = int(event.device_id) if event.device_id is not None else -1
        line = f"{event.timestamp.isoformat(sep=' ', timespec='milliseconds')} [{event.module}] {text}"
        self.output_buffers_by_device_id.setdefault(device_id, deque(maxlen=2000)).append(line)
        self._ensure_output_widget(device_id, event.session_id)
        if self.output_render_enabled:
            self.output_dirty_devices.add(device_id)

    def _flush_output_buffers(self) -> None:
        if not self._can_update_ui():
            self.output_dirty_devices.clear()
            return
        if not self.output_render_enabled:
            return
        dirty = list(self.output_dirty_devices)
        if not dirty:
            return
        self.output_dirty_devices.clear()
        rendered = 0
        for device_id in dirty:
            editor = self.output_widgets_by_device_id.get(device_id)
            if editor is None:
                continue
            lines = list(self.output_buffers_by_device_id.get(device_id, ()))
            if not lines:
                continue
            editor.setPlainText("\n".join(lines[-2000:]))
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            rendered += 1
        if rendered:
            app_logger.log_info(
                "ONLINE_MR_OUTPUT_RENDER_THROTTLED",
                f"rendered_devices={rendered} raw_queue_size={sum(len(buffer) for buffer in self.output_buffers_by_device_id.values())} output_render_enabled={self.output_render_enabled}",
            )

    def _parse_raw_stream_payload(self, parser: EventParserEngine, event: OnlineMrEvent) -> dict[str, object] | None:
        if event.module == "mesh":
            payload = parser.parse_mesh_line_stream(event)
            if not any(payload.get(key) is not None and payload.get(key) != "" for key in ("peer_mac", "peer_name", "mr_rssi", "link_state")):
                return None
            return payload
        if event.module == "busy":
            payload = parser.parse_busy(event)
            if not any(payload.get(key) is not None for key in ("ctl_busy", "tx_busy", "rx_busy")):
                return None
            return payload
        if event.module == "stats":
            payload = parser.parse_stats(event)
            counters = payload.get("counters")
            if not isinstance(counters, dict) or not counters:
                return None
            return payload
        if event.module == "interface_rate":
            raw = str(event.raw or "")
            lowered = raw.lower()
            if "inbound interface" in lowered:
                self._stream_interface_direction[event.session_id] = "inbound"
                return None
            if "outbound interface" in lowered:
                self._stream_interface_direction[event.session_id] = "outbound"
                return None
            direction = self._stream_interface_direction.get(event.session_id)
            if not direction:
                return None
            direction_header = "Inbound interface" if direction == "inbound" else "Outbound interface"
            enriched = OnlineMrEvent(
                timestamp=event.timestamp,
                session_id=event.session_id,
                device_id=event.device_id,
                source=event.source,
                module=event.module,
                event_type=event.event_type,
                payload=event.payload,
                raw=f"{direction_header}\n{raw}",
            )
            payload = parser.parse_interface_rate(enriched)
            rows = payload.get("rows")
            if not isinstance(rows, list) or not rows:
                return None
            latest = rows[-1]
            if isinstance(latest, dict):
                payload.update(latest)
            return payload
        return None

    def _publish_link_switch_if_needed(self, bus: OnlineMrEventBus, event: OnlineMrEvent) -> None:
        if event.module != "mesh" or str(event.payload.get("link_state") or "").upper() != "ACTIVE":
            return
        if event.device_id is None:
            return
        peer = _normalize_mac_key(event.payload.get("peer_mac")) or str(event.payload.get("peer_mac") or event.payload.get("peer_name") or "").strip()
        if not peer:
            return
        previous = self._last_active_peer_by_device_id.get(int(event.device_id))
        if previous and previous != peer:
            self._append_switch_history_table_row(
                {
                    "switch_time": event.timestamp.isoformat(sep=" ", timespec="milliseconds"),
                    "radio": event.payload.get("radio") or 1,
                    "from_peer_name": "",
                    "to_peer_name": event.payload.get("peer_name") or "",
                    "from_peer_mac": previous,
                    "to_peer_mac": peer,
                    "from_peer_site": "",
                    "to_peer_site": event.payload.get("peer_station") or event.payload.get("peer_site") or "",
                    "reason": "ACTIVE peer changed",
                    "raw_line": event.raw or "",
                }
            )
            switch_event = OnlineMrEvent(
                timestamp=event.timestamp,
                session_id=event.session_id,
                device_id=event.device_id,
                source="realtime_state",
                module="link_switch",
                event_type=EVENT_LINK_SWITCH,
                payload={"from_peer": previous, "to_peer": peer},
                raw=None,
            )
            bus.publish(switch_event)
            self.switch_history_text.append(
                f"{event.timestamp.isoformat(sep=' ', timespec='milliseconds')}  {previous} -> {peer}"
            )
        self._last_active_peer_by_device_id[int(event.device_id)] = peer

    def _publish_snapshot_event(self, snapshot: OnlineMrSnapshot) -> None:
        if not snapshot.session_id or str(snapshot.session_id).startswith("pending:"):
            return
        bus = self.event_buses.get(snapshot.session_id)
        device_id = self.session_to_device_id.get(snapshot.session_id)
        if bus is None:
            session_dir = self.session_dirs.get(snapshot.session_id)
            if session_dir is None:
                return
            bus = self._ensure_event_pipeline(snapshot.session_id, session_dir)
        timestamp = _snapshot_time(snapshot.last_collection_time)
        if snapshot.active_peer:
            snapshot_peer_name = str(getattr(snapshot, "peer_name", "") or "")
            snapshot_peer_site = str(getattr(snapshot, "peer_station", "") or getattr(snapshot, "peer_site", "") or "")
            peer_info = self._resolve_peer_identity_cached(snapshot_peer_name or snapshot.active_peer) or {}
            if not peer_info and snapshot_peer_name:
                peer_info = self._resolve_peer_identity_cached(snapshot.active_peer) or {}
            peer_name = snapshot_peer_name or str(peer_info.get("peer_ap_name") or "")
            peer_site = snapshot_peer_site or str(peer_info.get("peer_site") or "")
            peer_section = str(peer_info.get("peer_section") or "")
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
                        "peer_name": peer_name,
                        "peer_site": peer_site,
                        "peer_station": peer_site,
                        "peer_section": peer_section,
                        "belong_section": peer_section,
                        "belong_type": peer_info.get("belong_type") or "unknown",
                        "belonging_source": peer_info.get("belonging_source") or peer_info.get("match_rule") or "",
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

    def _refresh_realtime_view(self) -> None:
        if not self._can_update_ui():
            return
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
            sample_count=max(
                int(snapshot.collected_count if snapshot is not None else 0),
                self._stream_sample_count_by_device_id.get(device_id, 0),
            ),
            fail_count=snapshot.failed_count if snapshot is not None else 0,
            reconnect_count=snapshot.reconnect_count if snapshot is not None else 0,
            resolve_peer=self._resolve_peer_cached,
        )

    def _update_summary_from_state(self, state: RealtimeMRState) -> None:
        row = self._find_row(self.summary_table, str(state.device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            row = self._insert_summary_row_for_state(state)
        values = {
            SUMMARY_COL_STATUS: self._status_text(state.status),
            SUMMARY_COL_ACTIVE_PEER: state.peer_name or state.peer_mac or "",
            SUMMARY_COL_PEER_MAC: state.peer_mac or "",
            SUMMARY_COL_MR_RSSI: state.mr_rssi,
            SUMMARY_COL_PEER_SITE: state.peer_station or state.peer_site or "",
            SUMMARY_COL_PEER_SECTION: state.peer_section or "",
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
            item = make_table_item(self._summary_text(value))
            self.summary_table.setItem(row, column, item)
        app_logger.log_info(
            "ONLINE_MR_REALTIME_SUMMARY_UPDATED",
            f"device_id={state.device_id} device_name={state.device_name} new_status={state.status} peer_name={state.peer_name or ''} peer_mac={state.peer_mac or ''} mr_rssi={state.mr_rssi if state.mr_rssi is not None else ''}",
        )

    def _insert_summary_row_for_state(self, state: RealtimeMRState) -> int:
        row = self.summary_table.rowCount()
        self.summary_table.insertRow(row)
        worker = self.workers_by_device_id.get(state.device_id)
        config = worker.collector.config if worker is not None else None
        device = next((item for item in self.filtered_devices if item.id == state.device_id), None)
        host = config.host if config is not None else str(getattr(device, "primary_address", "") or "")
        session_id = self._session_id_for_device(state.device_id)
        values = [
            state.device_name or (config.device_name if config is not None else getattr(device, "name", "")),
            host,
            state.status,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            state.sample_count,
            state.fail_count,
            state.reconnect_count,
            "",
            "",
            "",
            session_id,
            state.device_id,
        ]
        for column, value in enumerate(values):
            item = make_table_item(self._status_text(str(value)) if column == SUMMARY_COL_STATUS and value else self._summary_text(value))
            self.summary_table.setItem(row, column, item)
        return row

    def _resolve_peer_cached(self, peer_mac_or_name: str) -> dict[str, object] | None:
        return self._resolve_peer_identity_cached(peer_mac_or_name)

    def _resolve_peer_identity_cached(self, peer_mac_or_name: str) -> dict[str, object] | None:
        text = str(peer_mac_or_name or "").strip()
        if not text:
            return None
        key = _normalize_mac_key(text)
        if key:
            if key not in self.peer_station_cache:
                try:
                    resolved = self.peer_mapping_service.resolve_peer_mac(text)
                    payload = {
                        "peer_ap_name": resolved.ap_name or "",
                        "peer_site": resolved.site or "",
                        "peer_section": resolved.section or "",
                        "belong_type": resolved.belong_type or "unknown",
                        "belonging_source": resolved.belonging_source or "",
                        "peer_radio_label": resolved.radio or "",
                        "peer_radio_mac": resolved.radio_mac or "",
                        "peer_serial_number": resolved.serial_number or "",
                        "serial_number": resolved.serial_number or "",
                        "peer_mac": resolved.peer_mac or text,
                        "match_rule": resolved.source,
                    }
                    self.peer_station_cache[key] = payload if _is_valid_peer_resolution(payload) else {}
                except Exception:
                    self.peer_station_cache[key] = {}
            return self.peer_station_cache.get(key)
        self._ensure_peer_name_cache()
        return self.peer_name_cache.get(_normalize_peer_name_key(text))

    def _ensure_peer_name_cache(self) -> None:
        if self._peer_name_cache_loaded:
            return
        self._peer_name_cache_loaded = True
        try:
            repository = AcRepository(self.repository.database)
            rows = repository.list_all_fit_ap_resources_with_metadata()
            rows.extend(self._extension_peer_identity_rows(repository, rows))
        except Exception:
            rows = []
        for row in rows:
            name = str(row.get("ap_name") or "").strip()
            key = _normalize_peer_name_key(name)
            if not key:
                continue
            self.peer_name_cache[key] = {
                "peer_ap_name": name,
                "peer_site": normalize_station_value(row),
                "peer_section": row.get("section_name") or row.get("belong_section") or "",
                "belong_type": row.get("belong_type") or "unknown",
                "belonging_source": row.get("_identity_source") or row.get("extension_match_status") or "ap_name",
                "peer_radio_label": "",
                "peer_radio_mac": "",
                "peer_mac": row.get("ap_mac") or row.get("ap_mac_display") or row.get("ap_mac_norm") or "",
                "peer_serial_number": row.get("serial_number") or row.get("serial") or row.get("sn") or row.get("device_sn") or "",
                "serial_number": row.get("serial_number") or row.get("serial") or row.get("sn") or row.get("device_sn") or "",
                "match_rule": "ap_name",
            }

    @staticmethod
    def _extension_peer_identity_rows(repository: AcRepository, fit_rows: list[dict[str, object | None]]) -> list[dict[str, object]]:
        try:
            extensions = repository.list_ap_extension_points()
        except Exception:
            return []
        known_names = {str(row.get("ap_name") or "").strip().casefold() for row in fit_rows if str(row.get("ap_name") or "").strip()}
        rows: list[dict[str, object]] = []
        for extension in extensions:
            name = str(extension.get("ap_name") or "").strip()
            if not name or name.casefold() in known_names:
                continue
            row = dict(extension)
            row["ap_mac"] = extension.get("ap_mac_display") or extension.get("ap_mac_norm") or ""
            row["_identity_source"] = "ap_metadata"
            rows.append(row)
        return rows

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
            item = make_table_item(self._summary_text(value))
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
                self._wireless_status_interval_seconds(),
            ),
            tasks=OnlineMrTaskToggles(wireless_status=True),
            radio=OnlineMrRadioConfig(int(self.channel_radio.currentData()), int(self.statistics_radio.currentData()), int(self.radio_port.currentData())),
            fping=FpingConfig(
                enabled=self.enable_fping_check.isChecked() and bool(fping_target),
                target=fping_target,
                preset_key=self.fping_preset_combo.currentData() or "",
                preset_name=self.fping_preset_combo.currentText(),
                packet_size=self.fping_packet_size.value(),
                interval_ms=self.fping_interval_ms.value(),
                loss_threshold_ms=self.fping_loss_threshold_ms.value(),
                loss_warn_percent=self._current_fping_loss_warn_percent(),
                latency_warn_ms=self.fping_latency_warn_ms.value(),
            ),
            iperf=IperfTrafficConfig(
                enabled=self.enable_iperf_check.isChecked(),
                server_ip=self.iperf_server_edit.text().strip(),
                port=self.iperf_port_spin.value(),
                preset_key=self.iperf_preset_combo.currentData() or "",
                preset_name=self.iperf_preset_combo.currentText(),
                test_type=self._current_iperf_preset().test_type if self._current_iperf_preset() else "",
                deployment_mode=self._current_iperf_preset().deployment_mode if self._current_iperf_preset() else "ground_server_train_client",
                business_direction=self._current_iperf_preset().business_direction if self._current_iperf_preset() else ("ground_to_train" if (self.iperf_direction_combo.currentData() or "upload") == "download" else "train_to_ground"),
                protocol=self.iperf_protocol_combo.currentText(),
                direction=self.iperf_direction_combo.currentData() or "upload",
                parallel=self.iperf_parallel_spin.value(),
                interval_seconds=self.iperf_interval_spin.value(),
                target_bandwidth=None,
                tcp_report_threshold_mbps=self._current_iperf_tcp_threshold_mbps(),
                tcp_pacing_enabled=self.iperf_tcp_pacing_check.isChecked(),
                tcp_pacing_mbps=self._current_iperf_tcp_pacing_mbps(),
                udp_bitrate_mbps=self._current_iperf_udp_bitrate_mbps(),
                udp_report_threshold_mbps=self._current_iperf_udp_threshold_mbps(),
                packet_length=self._current_iperf_packet_length(),
                follow_collection=True,
                duration_seconds=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
            ),
            auto_reconnect=self.auto_reconnect_check.isChecked(),
            reconnect_interval=self.reconnect_interval.value(),
            max_reconnect=None if self.max_reconnect.value() == 0 else self.max_reconnect.value(),
            duration_minutes=None if self.duration_minutes.value() == 0 else self.duration_minutes.value(),
            collect_config_on_start=self.collect_config_on_start_check.isChecked(),
        )

    def _wireless_status_interval_seconds(self) -> int:
        try:
            value = int(self.wireless_status_interval_edit.text().strip() or "3")
        except ValueError:
            value = 3
        return max(1, min(3600, value))

    def _fill_devices(self) -> None:
        self.available_devices = sorted([device for device in self.devices if self._is_vehicle_fat_ap(device)], key=natural_device_sort_key)
        keyword = self.device_search_input.text().strip().lower()
        self.filtered_devices = [device for device in self.available_devices if self._matches_device_search(device, keyword)]
        self._updating_device_checks = True
        self.device_table.setUpdatesEnabled(False)
        try:
            self.device_table.setRowCount(len(self.filtered_devices))
            for row, device in enumerate(self.filtered_devices):
                check_item = create_checkable_table_item(device.id in self.selected_device_ids)
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
        self._available_device_count = len(self.available_devices)
        if not self._can_update_ui():
            return
        self.available_device_count_label.setText(str(self._available_device_count))
        if not self.available_devices:
            self.filter_hint_label.setText(self.i18n.t("online_mr.no_vehicle_fat_ap"))
        elif not self.filtered_devices:
            self.filter_hint_label.setText(self.i18n.t("online_mr.no_device_search_results"))
        else:
            self.filter_hint_label.setText(self.i18n.t("online_mr.filtered_device_count", total=len(self.available_devices), shown=len(self.filtered_devices), selected=len(self.selected_device_ids)))
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
        by_id = {int(device.id): device for device in self.available_devices if device.id is not None}
        return [by_id[device_id] for device_id in sorted(self.selected_device_ids) if device_id in by_id]

    def _device_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_device_checks or item.column() != 0:
            return
        changed_device_id: int | None = None
        if 0 <= item.row() < len(self.filtered_devices):
            device = self.filtered_devices[item.row()]
            if device.id is not None:
                changed_device_id = int(device.id)
                if is_checked_value(item.checkState()):
                    self.selected_device_ids.add(int(device.id))
                else:
                    self.selected_device_ids.discard(int(device.id))
        selected = self._selected_devices()
        if len(selected) > 2:
            self._updating_device_checks = True
            set_table_row_checked(self.device_table, item.row(), False, 0)
            self._updating_device_checks = False
            if changed_device_id is not None:
                self.selected_device_ids.discard(changed_device_id)
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
            self._focus_output_device(int(device.id))

    def _view_device_changed(self, _index: int) -> None:
        if not self.view_device_combo.signalsBlocked():
            self._view_device_user_selected = True

    def _update_selected_count(self) -> None:
        self._selected_device_count = len(self.selected_device_ids)
        self._running_count = self._site_running_count()
        if not self._can_update_ui():
            return
        self.selected_device_count_label.setText(str(self._selected_device_count))
        self.running_count_label.setText(str(self._running_count))
        self._refresh_top_metrics()

    def _update_action_state(self) -> None:
        if not self._can_update_ui():
            return
        if not self.workers and not self.workers_by_device_id:
            self._prune_orphan_summary_rows()
        selected = self._selected_devices()
        selected_ids = {device.id for device in selected if device.id is not None}
        running_selected = any(device_id in self.workers_by_device_id for device_id in selected_ids)
        can_start = bool(selected) and len(selected) <= 2 and self.manager.running_count() < self.manager.max_concurrent
        stopping = self.status_value == "STOPPING"
        self.start_button.setEnabled(can_start and not stopping)
        self.stop_selected_button.setEnabled(running_selected and not stopping)
        self.stop_all_button.setEnabled(bool(self.workers_by_device_id or self.workers) and not stopping)
        if not stopping:
            self.force_stop_button.setVisible(False)
            self.force_stop_button.setEnabled(False)
        elif self._stop_requested_monotonic is not None:
            force_ready = time.monotonic() - self._stop_requested_monotonic >= FORCE_STOP_DELAY_SECONDS
            self.force_stop_button.setVisible(force_ready)
            self.force_stop_button.setEnabled(force_ready)
        self.iperf_retry_button.setEnabled(self.enable_iperf_check.isChecked() and bool(self.workers) and not stopping)
        self.open_button.setEnabled(True)
        self._running_count = self._site_running_count()
        self.running_count_label.setText(str(self._running_count))
        self._refresh_top_metrics()
        self._refresh_collection_animation()

    def _apply_feature_gate(self) -> None:
        apply_feature_to_widget(self.feature_gate, "online_mr.advanced_ping", self.enable_fping_check)
        apply_feature_to_widget(self.feature_gate, "online_mr.iperf_test", self.enable_iperf_check)
        apply_feature_to_widget(self.feature_gate, "online_mr.iperf_test", self.iperf_check_server_button)
        apply_feature_to_widget(self.feature_gate, "online_mr.iperf_test", self.iperf_retry_button)

    def _reconcile_collection_state(self) -> None:
        if not self._can_update_ui():
            return
        self._prune_orphan_summary_rows()
        self._restore_runtime_summary_rows()
        if not self.workers and not self.workers_by_device_id:
            self._set_status("STOPPED")
            self._stop_stop_animation()
        elif self.status_value != "STOPPING":
            self._set_status("COLLECTING")
        self._running_count = self._site_running_count()
        self.running_count_label.setText(str(self._running_count))
        self._refresh_top_metrics()
        app_logger.log_info(
            "ONLINE_MR_UI_STATE_RECONCILED",
            f"site={self.site_name} workers_count={len(self.workers)} manager_running_count={self.manager.running_count()} site_running_count={self._site_running_count()}",
        )

    def _restore_runtime_summary_rows(self) -> None:
        for session_id, worker in list(self.workers.items()):
            if not self._worker_belongs_to_current_site(worker):
                app_logger.log_info("ONLINE_MR_CROSS_SITE_STATE_FILTERED", f"site={self.site_name} session_id={session_id}")
                continue
            device_id = self.session_to_device_id.get(session_id)
            if device_id is None:
                continue
            if self._find_row(self.summary_table, str(device_id), column=SUMMARY_COL_DEVICE_ID) >= 0:
                continue
            snapshot = self._snapshot_from_worker(worker)
            if snapshot is not None:
                self._upsert_summary(snapshot)
                continue
            state = RealtimeMRState(
                device_id=int(device_id),
                device_name=self._output_title_for_device(int(device_id), session_id).split(" / ", 1)[0],
                status=STATE_COLLECTING,
            )
            self._insert_summary_row_for_state(state)

    def _refresh_top_metrics(self) -> None:
        if not self._can_update_ui():
            return
        self.available_metric_label.setText(f"{self.i18n.t('online_mr.available_devices')}: {self._available_device_count}")
        self.selected_metric_label.setText(f"{self.i18n.t('online_mr.selected_devices')}: {self._selected_device_count}")
        self.running_metric_label.setText(f"{self.i18n.t('online_mr.running_collectors')}: {self._running_count}")

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
        if previous_1 != desired[0]:
            self._fping_target_user_edited[1] = False
        if previous_2 != desired[1]:
            self._fping_target_user_edited[2] = False
        self._refresh_ping_target_labels()
        self._refresh_ping_status_labels()

    def _fping_device_changed(self, slot: int) -> None:
        self._fping_target_user_edited[slot] = False
        self._refresh_ping_target_labels()

    def _fping_target_edited(self, slot: int) -> None:
        if self._updating_fping_targets:
            return
        self._fping_target_user_edited[slot] = True

    def _refresh_ping_target_labels(self) -> None:
        self._updating_fping_targets = True
        try:
            for slot, combo, target_label in (
                (1, self.fping_device_combo_1, self.fping_target_label_1),
                (2, self.fping_device_combo_2, self.fping_target_label_2),
            ):
                device_id = combo.currentData()
                target = ""
                placeholder = self.i18n.t("online_mr.ping_target_placeholder")
                if device_id is not None:
                    device = self._device_by_id(int(device_id))
                    if device is not None:
                        target = str(device.primary_address or "").strip()
                        if not target:
                            placeholder = self.i18n.t("online_mr.ping_target_empty")
                target_label.setPlaceholderText(placeholder)
                if not self._fping_target_user_edited.get(slot, False):
                    target_label.setText(target)
        finally:
            self._updating_fping_targets = False

    def _fping_target_text_for_device(self, device_id: int, fallback: object = "") -> str:
        for combo, target_label in (
            (self.fping_device_combo_1, self.fping_target_label_1),
            (self.fping_device_combo_2, self.fping_target_label_2),
        ):
            if combo.currentData() == device_id:
                target = target_label.text().strip()
                if target:
                    return target
        return str(fallback or "").strip()

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
        fallback = repo_device.primary_address if repo_device else device.primary_address
        target_ip = self._fping_target_text_for_device(source_device_id, fallback)
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
        for index, combo, label, name in (
            (1, self.fping_device_combo_1, self.fping_status_label_1, "Ping 1"),
            (2, self.fping_device_combo_2, self.fping_status_label_2, "Ping 2"),
        ):
            if combo.currentData() == device_id:
                text = f"{name}: {status}"
                self._fping_status_texts[index] = text
                if self._can_update_ui():
                    label.setText(text)

    def _refresh_ping_status_labels(self) -> None:
        for index, combo, label, name in (
            (1, self.fping_device_combo_1, self.fping_status_label_1, "Ping 1"),
            (2, self.fping_device_combo_2, self.fping_status_label_2, "Ping 2"),
        ):
            value = combo.currentData()
            if value is None:
                text = f"{name}: idle"
            elif int(value) in self.fping_workers_by_device_id:
                text = f"{name}: running"
            else:
                text = f"{name}: ready"
            self._fping_status_texts[index] = text
            if self._can_update_ui():
                label.setText(text)

    def _refresh_collection_animation(self) -> None:
        if not self._can_update_ui():
            return
        selected = [device for device in self._selected_devices() if device.id is not None][:2]
        if not selected and not self.workers_by_device_id:
            self.collect_status_label_1.setText(
                "暂无运行采集\n"
                f"{self._fping_status_texts.get(1, 'Ping 1: idle')}\n"
                f"{self._fping_status_texts.get(2, 'Ping 2: idle')}"
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
            ping_text = self._fping_status_texts.get(index + 1, f"Ping {index + 1}: idle")
            worker = self.workers_by_device_id.get(int(device.id))
            if worker is None:
                label.setText(f"状态：已停止\nMesh：-\nBusy：-\nStats：-\n{ping_text}")
                progress.setRange(0, 1)
                progress.setValue(0)
                continue
            collector = getattr(worker, "collector", None)
            if collector is None:
                label.setText(f"状态：{self._status_text('COLLECTING')}\nMesh：正常  Busy：-  Stats：-\n{ping_text}")
                progress.setRange(0, 0)
                continue
            snapshot = collector.snapshot()
            if snapshot.status == STATE_STOPPING or self.status_value == "STOPPING":
                label.setText(f"状态：正在停止...\n正在通知采集线程停止\n正在停止 SSH repeat / terminal monitor\n正在停止 fping / iperf")
                progress.setRange(0, 0)
                continue
            modules = ["mesh", "busy", "stats"]
            if int(device.id) in self.fping_workers_by_device_id:
                modules.append("ping")
            realtime = self._realtime_status_for_device(int(device.id))
            ping_text = realtime if realtime else ping_text
            session_text = "" if str(snapshot.session_id or "").startswith("pending:") else snapshot.session_id
            label.setText(
                f"状态：{self._status_text(snapshot.status)}  会话：{session_text or '-'}\n"
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
        if not self._can_update_ui():
            self.realtime_parse_worker = None
            return
        self.log_text.append(
            f"Realtime parse completed: mesh_samples={getattr(summary, 'mesh_samples', 0)}, "
            f"switch_history_samples={getattr(summary, 'switch_history_samples', 0)}, "
            f"ping_samples={summary.ping_samples}, iperf_samples={summary.iperf_samples}"
        )
        current = self.tabs.currentWidget()
        if current in {self.diagnosis_table, self.analysis_charts, self.switch_history_panel, self.active_link_switch_table}:
            self._start_offline_analysis_load(session_dir, task_label="刷新实时解析结果", profile_phase="render.realtime_analysis")
        self.realtime_parse_worker = None

    def _realtime_parse_failed(self, message: str) -> None:
        if not self._can_update_ui():
            self.realtime_parse_worker = None
            return
        self.log_text.append(f"Realtime parse failed: {message}")
        self.realtime_parse_worker = None

    def _device_runtime_status(self, device_id: int | None) -> str:
        if device_id is not None and device_id in self.workers_by_device_id:
            return self._status_text("COLLECTING")
        return self.i18n.t("online_mr.status_stopped")

    def _session_id_for_device(self, device_id: int | None) -> str:
        if device_id is None:
            return ""
        return next((sid for sid, sid_device_id in self.session_to_device_id.items() if sid_device_id == device_id), "")

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
        devices = list(self.available_devices or self.filtered_devices)
        if prefer_device_id is not None:
            devices.sort(key=lambda device: 0 if device.id == prefer_device_id else 1)
        for device in devices:
            if device.id is None:
                continue
            seen.add(int(device.id))
            self.view_device_combo.addItem(device.name, int(device.id))
        for device_id in self.workers_by_device_id:
            if device_id not in seen:
                self.view_device_combo.addItem(self.i18n.t("online_mr.unknown_or_deleted_device", device_id=device_id), device_id)
                seen.add(device_id)
        if self.analysis_only:
            for row in self.store.list_sessions(self.site_name, None):
                raw_device_id = row.get("device_id")
                try:
                    device_id = int(raw_device_id)
                except (TypeError, ValueError):
                    continue
                if device_id not in seen:
                    label = str(row.get("device_name") or "").strip() or self.i18n.t("online_mr.unknown_or_deleted_device", device_id=device_id)
                    self.view_device_combo.addItem(label, device_id)
                    seen.add(device_id)
        index = self.view_device_combo.findData(prefer_device_id)
        self.view_device_combo.setCurrentIndex(index if index >= 0 else 0)
        self.view_device_combo.blockSignals(False)

    def _fill_history(self) -> None:
        profile_start = time.perf_counter()
        self._history_refresh_pending = False
        rows = self.store.list_sessions(self.site_name, None)
        self.session_history_rows = list(rows)
        self.history_table.setUpdatesEnabled(False)
        try:
            self.history_table.setRowCount(len(rows))
            for row, row_data in enumerate(rows):
                stats = row_data.get("stats") if isinstance(row_data.get("stats"), dict) else {}
                session_type = str(row_data.get("session_type") or "realtime")
                status_text = str(row_data.get("status", ""))
                if session_type == "config_only":
                    status_text = f"{status_text} / {self.i18n.t('online_mr.config_only_session')}"
                values = [
                    row_data.get("session_id", ""),
                    row_data.get("started_at", ""),
                    row_data.get("ended_at", ""),
                    status_text,
                    f"{stats.get('mesh_link_success', 0)}/{stats.get('mesh_link_failed', 0)}",
                    f"{stats.get('channel_busy_success', 0)}/{stats.get('channel_busy_failed', 0)}",
                    stats.get("reconnect_count", 0),
                    row_data.get("mr_name", ""),
                    row_data.get("session_dir", ""),
                ]
                for column, value in enumerate(values):
                    item = make_table_item(value)
                    if column == 8 and row_data.get("config_file_path"):
                        item.setToolTip(f"{self.i18n.t('online_mr.config_file_path')}: {row_data.get('config_file_path')}")
                    self.history_table.setItem(row, column, item)
        finally:
            self.history_table.setUpdatesEnabled(True)
        if self.analysis_only:
            self._refresh_session_select_combo()
        self._auto_fit_online_table(self.history_table, "history_sessions")
        self._log_page_profile("load.history", profile_start, rows=len(rows))

    def _refresh_session_select_combo(self) -> None:
        if not self.analysis_only:
            return
        keyword = self.session_search_input.text().strip().lower()
        current_dir = self.session_select_combo.currentData()
        filtered = [row for row in self.session_history_rows if self._matches_session_search(row, keyword)]
        self.session_select_combo.blockSignals(True)
        try:
            self.session_select_combo.clear()
            for row in filtered:
                session_dir = str(row.get("session_dir") or "").strip()
                if not session_dir:
                    continue
                self.session_select_combo.addItem(self._session_combo_label(row), session_dir)
            if current_dir:
                index = self.session_select_combo.findData(current_dir)
                if index >= 0:
                    self.session_select_combo.setCurrentIndex(index)
        finally:
            self.session_select_combo.blockSignals(False)
        if not filtered:
            self.session_search_input.setToolTip(self.i18n.t("online_mr.session_filter_empty"))
        else:
            self.session_search_input.setToolTip("")
        self._refresh_parse_button_state()

    def _matches_session_search(self, row: dict[str, object], keyword: str) -> bool:
        if not keyword:
            return True
        device_id = row.get("device_id")
        device = next((item for item in self.devices if str(item.id) == str(device_id)), None)
        group_name = self.device_groups.get(int(getattr(device, "group_id", 0) or 0), "") if device is not None else ""
        values = [
            row.get("device_name"),
            row.get("mr_name"),
            row.get("session_id"),
            row.get("session_dir"),
            row.get("status"),
            row.get("session_type"),
            row.get("host"),
            row.get("protocol"),
            row.get("device_name"),
            device.primary_address if device is not None else "",
            device.device_type if device is not None else "",
            group_name,
        ]
        return any(keyword in str(value or "").lower() for value in values)

    @staticmethod
    def _session_combo_label(row: dict[str, object]) -> str:
        start = str(row.get("started_at") or "-")
        end = str(row.get("ended_at") or "-")
        status = str(row.get("status") or "-")
        mr_name = str(row.get("mr_name") or row.get("device_name") or "-")
        session_id = str(row.get("session_id") or "-")
        return f"{start} ~ {end} | {status} | {mr_name} | {session_id}"

    def _log_page_profile(self, phase: str, start: float, *, rows: int = 0) -> None:
        page = "rail.online_mr_analysis" if self.analysis_only else "rail.online_mr_collection"
        elapsed_ms = (time.perf_counter() - start) * 1000
        app_logger.log_info("UI_PAGE_PROFILE", f"page={page} phase={phase} elapsed_ms={elapsed_ms:.1f} rows={rows}")

    def _matches_device_search(self, device: Device, keyword: str) -> bool:
        if not keyword:
            return True
        group_name = self.device_groups.get(int(device.group_id or 0), "")
        values = [device.name, device.primary_address, device.device_type or "", group_name]
        return any(keyword in str(value or "").lower() for value in values)

    def _ensure_analysis_device_session_dirs(self) -> None:
        if not self.analysis_only:
            return
        return

    def _schedule_history_refresh(self, refresh_tools: bool = False) -> None:
        if not self._can_update_ui():
            return
        if self._history_refresh_pending:
            return
        self._history_refresh_pending = True

        def run() -> None:
            self._history_refresh_pending = False
            if not self._can_update_ui():
                return
            self._fill_history()
            self._refresh_tool_status_once(force=refresh_tools)

        QTimer.singleShot(0, run)

    def _refresh_tool_status_once(self, force: bool = False) -> None:
        if not self._can_update_ui():
            return
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
        device_id = self.session_to_device_id.get(snapshot.session_id) or getattr(snapshot, "device_id", None)
        if device_id is None:
            app_logger.log_warning("ONLINE_MR_SNAPSHOT_WITHOUT_DEVICE", f"session_id={snapshot.session_id}")
            return
        try:
            device_id_int = int(device_id)
        except (TypeError, ValueError):
            app_logger.log_warning("ONLINE_MR_SNAPSHOT_WITH_INVALID_DEVICE", f"session_id={snapshot.session_id} device_id={device_id}")
            return
        device = next((item for item in self.filtered_devices if item.id == device_id_int), None)
        worker = self.workers.get(snapshot.session_id) or self.workers_by_device_id.get(device_id_int)
        if device is None and worker is None and snapshot.status in ACTIVE_UI_STATES:
            app_logger.log_warning("ONLINE_MR_SNAPSHOT_ORPHAN_SKIPPED", f"session_id={snapshot.session_id} device_id={device_id}")
            return
        if snapshot.status in ACTIVE_UI_STATES and worker is None:
            app_logger.log_warning("ONLINE_MR_ACTIVE_SNAPSHOT_WITHOUT_WORKER", f"session_id={snapshot.session_id} device_id={device_id}")
            return
        row_key = str(device_id_int)
        row = self._find_row(self.summary_table, row_key, column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
        config = worker.collector.config if worker else None
        host_text = getattr(snapshot, "host", "") or ""
        if config:
            host_text = config.host
            if config.connection_method:
                host_text = f"{host_text} ({config.connection_method})"
        peer_name = str(getattr(snapshot, "peer_name", "") or "")
        peer_station = str(getattr(snapshot, "peer_station", "") or getattr(snapshot, "peer_site", "") or "")
        peer_info = self._resolve_peer_identity_cached(peer_name or snapshot.active_peer) or {}
        if not peer_info and peer_name and snapshot.active_peer:
            peer_info = self._resolve_peer_identity_cached(snapshot.active_peer) or {}
        peer_display = peer_name or str(peer_info.get("peer_ap_name") or peer_info.get("ap_name") or "") or snapshot.active_peer
        peer_site = peer_station or str(peer_info.get("peer_site") or peer_info.get("site") or "")
        peer_section = str(peer_info.get("peer_section") or peer_info.get("belong_section") or "")
        values = [
            config.device_name if config else getattr(snapshot, "device_name", ""),
            host_text,
            snapshot.status,
            peer_display,
            snapshot.active_peer,
            snapshot.local_rssi,
            peer_site,
            peer_section,
            "",
            "",
            snapshot.collected_count,
            snapshot.failed_count,
            snapshot.reconnect_count,
            snapshot.last_collection_time,
            snapshot.iperf_mbps,
            snapshot.iperf_retransmits,
            snapshot.session_id,
            row_key,
        ]
        for column, value in enumerate(values):
            item = make_table_item(self._status_text(str(value)) if column == SUMMARY_COL_STATUS and value else self._summary_text(value))
            self.summary_table.setItem(row, column, item)
        app_logger.log_info(
            "ONLINE_MR_REALTIME_SUMMARY_UPDATED",
            f"device_id={device_id_int} device_name={getattr(snapshot, 'device_name', '')} new_status={snapshot.status} peer_name={peer_display or ''} peer_mac={snapshot.active_peer or ''} mr_rssi={snapshot.local_rssi if snapshot.local_rssi is not None else ''}",
        )

    def _prune_orphan_summary_rows(self) -> None:
        known_device_ids = {int(device.id) for device in self.filtered_devices if device.id is not None}
        running_device_ids = set(self.workers_by_device_id)
        for row in range(self.summary_table.rowCount() - 1, -1, -1):
            status_item = self.summary_table.item(row, SUMMARY_COL_STATUS)
            device_item = self.summary_table.item(row, SUMMARY_COL_DEVICE_ID)
            session_item = self.summary_table.item(row, SUMMARY_COL_SESSION)
            status_code = self._summary_status_code(status_item.text() if status_item else "")
            if status_code not in ACTIVE_UI_STATES:
                continue
            device_id: int | None = None
            try:
                device_id = int(device_item.text()) if device_item and device_item.text().strip() else None
            except ValueError:
                device_id = None
            session_id = session_item.text().strip() if session_item else ""
            has_worker = (device_id is not None and device_id in running_device_ids) or (session_id in self.workers)
            if has_worker:
                continue
            detail = f"device_id={device_id} session_id={session_id} source=summary_table reason=no_running_worker"
            app_logger.log_info("ONLINE_MR_ORPHAN_COLLECTION_CLEANED", detail)
            if device_id is None or device_id not in known_device_ids:
                self.summary_table.removeRow(row)
            else:
                self._update_summary_status_by_device(device_id, "STOPPED")

    def _summary_status_code(self, text: str) -> str:
        value = str(text or "").strip()
        for status in STATUS_I18N_KEYS:
            if value == status or value == self._status_text(status):
                return status
        return value

    def _update_summary_iperf(self, device_id: int, row_data: dict[str, object]) -> None:
        row = self._find_row(self.summary_table, str(device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            return
        self.summary_table.setItem(row, SUMMARY_COL_IPERF_MBPS, make_table_item(f"{float(row_data.get('bitrate_mbps') or 0):.2f}"))
        self.summary_table.setItem(row, SUMMARY_COL_IPERF_RETRANS, make_table_item(row_data.get("retransmits", 0)))

    def _update_summary_status_by_device(self, device_id: int | None, status: str) -> None:
        if device_id is None:
            return
        row = self._find_row(self.summary_table, str(device_id), column=SUMMARY_COL_DEVICE_ID)
        if row < 0:
            return
        item = make_table_item(self._status_text(status))
        self.summary_table.setItem(row, SUMMARY_COL_STATUS, item)

    def _append_mesh_snapshot(self, snapshot: OnlineMrSnapshot) -> None:
        if not snapshot.active_peer:
            return
        row = self.mesh_table.rowCount()
        self.mesh_table.insertRow(row)
        peer_name = str(getattr(snapshot, "peer_name", "") or "")
        peer_info = self._resolve_peer_identity_cached(peer_name or snapshot.active_peer) or {}
        if not peer_info and peer_name:
            peer_info = self._resolve_peer_identity_cached(snapshot.active_peer) or {}
        peer_site = str(getattr(snapshot, "peer_station", "") or getattr(snapshot, "peer_site", "") or peer_info.get("peer_site") or "")
        peer_section = str(peer_info.get("peer_section") or "")
        belong_type = _display_belong_type(peer_info.get("belong_type") or "unknown")
        values = [row + 1, snapshot.last_collection_time, 1, "ACTIVE", peer_name or peer_info.get("peer_ap_name") or snapshot.active_peer or "", snapshot.active_peer, snapshot.local_rssi, "", "", peer_site, peer_section, belong_type, ""]
        for column, value in enumerate(values):
            self._set_table_item(self.mesh_table, row, column, value, active=True)
        self._trim_table(self.mesh_table)

    def _set_table_item(self, table: QTableWidget, row: int, column: int, value: object, *, active: bool = False, emphasize: bool = False, warning: bool = False) -> None:
        item = make_table_item(self._summary_text(value))
        if active or emphasize:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        if active:
            item.setForeground(QColor("#22c55e"))
        elif warning:
            item.setForeground(QColor("#f59e0b"))
        table.setItem(row, column, item)

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
        self._configure_numeric_spin(spin)
        return spin

    def _no_wheel_spin(self, minimum: int, maximum: int, value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        self._configure_numeric_spin(spin)
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
            (self.iperf_preset_combo, 260),
            (self.iperf_tcp_threshold_edit, 120),
            (self.iperf_udp_bitrate_edit, 120),
            (self.iperf_udp_threshold_edit, 120),
            (self.iperf_tcp_pacing_edit, 120),
            (self.iperf_protocol_combo, 100),
            (self.iperf_direction_combo, 140),
            (self.view_device_combo, 260),
        ):
            widget.setMaximumWidth(width)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        for button in (
            self.start_button,
            self.stop_selected_button,
            self.stop_all_button,
            self.open_button,
            self.refresh_devices_button,
        ):
            button.setMinimumWidth(104)
            button.setMaximumWidth(180)
            button.setMinimumHeight(34)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumWidth(72)
        self.status_label.setMaximumWidth(140)
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
            target.setMinimumWidth(180)
            target.setMaximumWidth(320)
            target.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.iperf_server_edit.setMinimumWidth(220)
        self.iperf_server_edit.setMaximumWidth(340)

    def _configure_numeric_spin(self, spin: QAbstractSpinBox) -> None:
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(110)
        spin.setMaximumWidth(140)
        spin.setMinimumHeight(28)
        spin.setKeyboardTracking(False)
        spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _configure_numeric_line_edit(self, edit: QLineEdit) -> None:
        edit.setMinimumWidth(110)
        edit.setMaximumWidth(140)
        edit.setMinimumHeight(28)
        edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _period_box(self) -> QGroupBox:
        box = QGroupBox()
        self.collect_param_box = box
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        box.setMinimumHeight(220)
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
        wireless_row = len(rows)
        self.wireless_status_label.setMinimumHeight(28)
        self._configure_numeric_line_edit(self.wireless_status_interval_edit)
        grid.addWidget(self.wireless_status_label, wireless_row, 0)
        grid.addWidget(self.wireless_status_interval_edit, wireless_row, 1)
        unit = self._text_label("online_mr.seconds")
        unit.setMinimumWidth(24)
        unit.setMinimumHeight(28)
        grid.addWidget(unit, wireless_row, 2)
        radio_row = wireless_row + 1
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
        box.setMinimumWidth(360)
        box.setMinimumHeight(430)
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.enable_fping_check)

        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(8)
        preset_label = self._label("online_mr.ping_preset")
        preset_label.setMinimumWidth(90)
        preset_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fping_preset_combo.setMinimumWidth(220)
        self.fping_preset_combo.setMaximumWidth(360)
        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.fping_preset_combo, 1)
        layout.addLayout(preset_layout)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        cards.addWidget(self._ping_endpoint_box("Ping 1", self.fping_device_combo_1, self.fping_target_label_1), 1)
        cards.addWidget(self._ping_endpoint_box("Ping 2", self.fping_device_combo_2, self.fping_target_label_2), 1)
        layout.addLayout(cards)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        for row, (key, widget, unit) in enumerate(
            (
                ("online_mr.packet_size", self.fping_packet_size, "online_mr.bytes"),
                ("online_mr.ping_interval_ms", self.fping_interval_ms, "online_mr.milliseconds"),
                ("online_mr.loss_threshold_ms", self.fping_loss_threshold_ms, "online_mr.milliseconds"),
                ("online_mr.loss_warn_percent", self.fping_loss_warn_edit, "online_mr.percent"),
                ("online_mr.latency_warn_ms", self.fping_latency_warn_ms, "online_mr.milliseconds"),
            ),
            start=0,
        ):
            label = self._label(key)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumWidth(110)
            label.setMaximumWidth(130)
            if isinstance(widget, QAbstractSpinBox):
                self._configure_numeric_spin(widget)
            elif isinstance(widget, QLineEdit):
                self._configure_numeric_line_edit(widget)
            grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1)
            unit_label = self._text_label(unit)
            unit_label.setMinimumWidth(50)
            unit_label.setMaximumWidth(60)
            grid.addWidget(unit_label, row, 2)
            grid.setRowMinimumHeight(row, 32)
        grid.setColumnMinimumWidth(0, 110)
        grid.setColumnMinimumWidth(1, 110)
        grid.setColumnMinimumWidth(2, 50)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        layout.addWidget(self.fping_tool_label)
        layout.addStretch(1)
        for combo in (self.fping_device_combo_1, self.fping_device_combo_2):
            combo.setMinimumWidth(220)
            combo.setMaximumWidth(360)
        for target in (self.fping_target_label_1, self.fping_target_label_2):
            target.setMinimumWidth(180)
            target.setMaximumWidth(320)
            target.setMinimumHeight(28)
            target.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        grid = QGridLayout(box)
        grid.addWidget(self.enable_iperf_check, 0, 0, 1, 3)
        grid.addWidget(self.iperf_duration_mode_label, 1, 0, 1, 3)
        grid.addWidget(self._label("iperf.preset"), 2, 0)
        grid.addWidget(self.iperf_preset_combo, 2, 1, 1, 2)
        grid.addWidget(self._label("iperf.server_address"), 3, 0)
        grid.addWidget(self.iperf_server_edit, 3, 1, 1, 2)
        rows = (
            ("iperf.port", self.iperf_port_spin, None),
            ("iperf.protocol", self.iperf_protocol_combo, None),
            ("iperf.direction", self.iperf_direction_combo, None),
            ("iperf.parallel", self.iperf_parallel_spin, None),
            ("iperf.interval", self.iperf_interval_spin, "online_mr.seconds"),
        )
        for row, (key, widget, unit) in enumerate(rows, start=4):
            grid.addWidget(self._label(key), row, 0)
            grid.addWidget(widget, row, 1)
            if unit:
                grid.addWidget(self._text_label(unit), row, 2)
        self.iperf_tcp_threshold_label = self._label("iperf.tcp_report_threshold")
        tcp_threshold_layout = QHBoxLayout()
        tcp_threshold_layout.addWidget(self.iperf_tcp_threshold_edit)
        tcp_threshold_layout.addWidget(QLabel("Mbps"))
        grid.addWidget(self.iperf_tcp_threshold_label, 9, 0)
        grid.addLayout(tcp_threshold_layout, 9, 1, 1, 2)

        self.iperf_udp_bitrate_label = self._label("iperf.udp_bitrate")
        udp_bitrate_layout = QHBoxLayout()
        udp_bitrate_layout.addWidget(self.iperf_udp_bitrate_edit)
        udp_bitrate_layout.addWidget(QLabel("Mbps"))
        grid.addWidget(self.iperf_udp_bitrate_label, 10, 0)
        grid.addLayout(udp_bitrate_layout, 10, 1, 1, 2)

        self.iperf_udp_threshold_label = self._label("iperf.udp_report_threshold")
        udp_threshold_layout = QHBoxLayout()
        udp_threshold_layout.addWidget(self.iperf_udp_threshold_edit)
        udp_threshold_layout.addWidget(QLabel("Mbps"))
        grid.addWidget(self.iperf_udp_threshold_label, 11, 0)
        grid.addLayout(udp_threshold_layout, 11, 1, 1, 2)

        self.iperf_packet_length_label = self._label("iperf.packet_length")
        grid.addWidget(self.iperf_packet_length_label, 12, 0)
        grid.addWidget(self.iperf_packet_length_spin, 12, 1)
        grid.addWidget(QLabel("bytes"), 12, 2)

        self.iperf_tcp_pacing_label = self._label("iperf.tcp_pacing")
        tcp_pacing_layout = QHBoxLayout()
        tcp_pacing_layout.addWidget(self.iperf_tcp_pacing_check)
        tcp_pacing_layout.addWidget(self.iperf_tcp_pacing_edit)
        tcp_pacing_layout.addWidget(QLabel("Mbps"))
        grid.addWidget(self.iperf_tcp_pacing_label, 13, 0)
        grid.addLayout(tcp_pacing_layout, 13, 1, 1, 2)

        grid.addWidget(self.iperf_bandwidth_hint_label, 14, 1, 1, 2)
        grid.addWidget(self._label("online_mr.tool_status"), 15, 0)
        grid.addWidget(self.iperf_tool_label, 15, 1, 1, 2)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.iperf_check_server_button)
        button_layout.addWidget(self.iperf_retry_button)
        grid.addLayout(button_layout, 16, 1, 1, 2)
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

    def _fill_fping_preset_combo(self) -> None:
        self.fping_preset_combo.blockSignals(True)
        try:
            self.fping_preset_combo.clear()
            self.fping_preset_combo.addItem("自定义", "")
            for preset in list_ping_presets():
                self.fping_preset_combo.addItem(preset.name, preset.key)
            index = self.fping_preset_combo.findData(DEFAULT_PING_PRESET_KEY)
            self.fping_preset_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.fping_preset_combo.blockSignals(False)

    def _fping_preset_changed(self) -> None:
        if self._updating_fping_preset:
            return
        self._apply_fping_preset(self.fping_preset_combo.currentData())

    def _apply_fping_preset(self, key: str | None) -> None:
        preset = get_ping_preset(key)
        if preset is None:
            return
        self._updating_fping_preset = True
        try:
            self.fping_packet_size.setValue(preset.packet_size_bytes)
            self.fping_interval_ms.setValue(preset.interval_ms)
            self.fping_loss_threshold_ms.setValue(preset.timeout_ms)
            self.fping_loss_warn_edit.setText(f"{preset.loss_warn_percent:g}")
            self.fping_latency_warn_ms.setValue(preset.latency_warn_ms)
        finally:
            self._updating_fping_preset = False

    def _mark_fping_preset_custom(self) -> None:
        if self._updating_fping_preset:
            return
        custom_index = self.fping_preset_combo.findData("")
        if custom_index >= 0 and self.fping_preset_combo.currentIndex() != custom_index:
            self._updating_fping_preset = True
            try:
                self.fping_preset_combo.setCurrentIndex(custom_index)
            finally:
                self._updating_fping_preset = False

    def _current_fping_loss_warn_percent(self) -> float:
        try:
            value = float(self.fping_loss_warn_edit.text().strip())
        except ValueError:
            value = 0.7
        return min(100.0, max(0.0, value))

    def _fill_iperf_preset_combo(self) -> None:
        self.iperf_preset_combo.blockSignals(True)
        try:
            self.iperf_preset_combo.clear()
            self.iperf_preset_combo.addItem("自定义", "")
            for preset in list_traffic_presets():
                self.iperf_preset_combo.addItem(preset.name, preset.key)
            index = self.iperf_preset_combo.findData(DEFAULT_TRAFFIC_PRESET_KEY)
            self.iperf_preset_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.iperf_preset_combo.blockSignals(False)

    def _current_iperf_preset(self):
        return get_traffic_preset(self.iperf_preset_combo.currentData())

    def _iperf_preset_changed(self) -> None:
        if self._updating_iperf_preset:
            return
        self._apply_iperf_preset(self.iperf_preset_combo.currentData())

    def _apply_iperf_preset(self, key: str | None) -> None:
        preset = get_traffic_preset(key)
        if preset is None:
            self._update_iperf_controls_visibility()
            return
        self._updating_iperf_preset = True
        try:
            self.iperf_protocol_combo.setCurrentText(preset.protocol)
            direction_index = self.iperf_direction_combo.findData("download" if preset.reverse else "upload")
            if direction_index >= 0:
                self.iperf_direction_combo.setCurrentIndex(direction_index)
            self.iperf_parallel_spin.setValue(preset.parallel)
            self.iperf_interval_spin.setValue(preset.interval_sec)
            self.iperf_port_spin.setValue(preset.port)
            self.iperf_duration_spin.setValue(FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS)
            self.iperf_tcp_threshold_edit.setText(f"{preset.report_threshold_mbps:g}" if preset.protocol.upper() == "TCP" else "")
            self.iperf_udp_bitrate_edit.setText(f"{preset.udp_bitrate_mbps:g}" if preset.udp_bitrate_mbps is not None else "")
            self.iperf_udp_threshold_edit.setText(f"{preset.report_threshold_mbps:g}" if preset.protocol.upper() == "UDP" else "")
            self.iperf_packet_length_spin.setValue(int(preset.packet_length or 1400))
            self.iperf_tcp_pacing_check.setChecked(False)
            self.iperf_tcp_pacing_edit.clear()
        finally:
            self._updating_iperf_preset = False
        self._update_iperf_controls_visibility()

    def _current_iperf_tcp_threshold_mbps(self) -> float | None:
        if self.iperf_protocol_combo.currentText().upper() != "TCP":
            return None
        return _bandwidth_input_to_mbps(self.iperf_tcp_threshold_edit.text(), "M")

    def _current_iperf_tcp_pacing_mbps(self) -> float | None:
        if self.iperf_protocol_combo.currentText().upper() != "TCP" or not self.iperf_tcp_pacing_check.isChecked():
            return None
        return _bandwidth_input_to_mbps(self.iperf_tcp_pacing_edit.text(), "M")

    def _current_iperf_udp_bitrate_mbps(self) -> float | None:
        if self.iperf_protocol_combo.currentText().upper() != "UDP":
            return None
        return _bandwidth_input_to_mbps(self.iperf_udp_bitrate_edit.text(), "M")

    def _current_iperf_udp_threshold_mbps(self) -> float | None:
        if self.iperf_protocol_combo.currentText().upper() != "UDP":
            return None
        threshold = _bandwidth_input_to_mbps(self.iperf_udp_threshold_edit.text(), "M")
        return threshold if threshold is not None else self._current_iperf_udp_bitrate_mbps()

    def _current_iperf_packet_length(self) -> int | None:
        return self.iperf_packet_length_spin.value()

    def _update_iperf_controls_visibility(self) -> None:
        is_tcp = self.iperf_protocol_combo.currentText().upper() == "TCP"
        for row, visible in ((9, is_tcp), (10, not is_tcp), (11, not is_tcp), (12, not is_tcp), (13, is_tcp)):
            self._set_grid_row_visible(self.iperf_box.layout(), row, visible)
        self.iperf_tcp_pacing_edit.setEnabled(is_tcp and self.iperf_tcp_pacing_check.isChecked())
        if is_tcp:
            self.iperf_bandwidth_hint_label.setText("TCP 模式下该值只作为报告验收阈值，不生成 iperf3 -b；TCP 默认自动打满链路。")
        else:
            self.iperf_bandwidth_hint_label.setText("UDP 模式下发送速率用于 iperf3 -b，验收阈值只用于报告判定；PIS 模板默认包长 1400。")

    def _set_grid_row_visible(self, layout, row: int, visible: bool) -> None:
        if not isinstance(layout, QGridLayout):
            return
        for column in range(layout.columnCount()):
            item = layout.itemAtPosition(row, column)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setVisible(visible)
                continue
            child_layout = item.layout()
            if child_layout is None:
                continue
            for index in range(child_layout.count()):
                child = child_layout.itemAt(index)
                child_widget = child.widget() if child is not None else None
                if child_widget is not None:
                    child_widget.setVisible(visible)

    def _advanced_box(self) -> QGroupBox:
        box = QGroupBox()
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        box.setMinimumWidth(260)
        box.setMaximumWidth(320)
        box.setMinimumHeight(190)
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
        self.collect_config_on_start_check.setMinimumHeight(24)
        detail_grid.addWidget(self.collect_config_on_start_check, 1, 0, 1, 3)
        for row, (label_key, spin, unit_key) in enumerate(
            (
                ("online_mr.reconnect_interval", self.reconnect_interval, "online_mr.seconds"),
                ("online_mr.max_reconnect", self.max_reconnect, None),
                ("online_mr.duration_minutes", self.duration_minutes, "online_mr.minutes"),
            ),
            start=2,
        ):
            label = self._text_label(label_key)
            label.setMinimumHeight(26)
            self._configure_numeric_spin(spin)
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
        apply_analysis_table_style(table)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setMinimumHeight(260 if table is self.device_table else 250 if table is not self.summary_table else 120)
        if table is self.device_table:
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
            table.setColumnWidth(0, 48)
            for column, width in ((1, 210), (2, 130), (3, 65), (4, 60), (5, 85), (6, 70), (7, 90), (8, 90)):
                table.setColumnWidth(column, width)

    def _apply_online_table_styles(self) -> None:
        for table in (
            self.summary_table,
            self.mesh_table,
            self.mesh_detail_table,
            self.channel_table,
            self.events_table,
            self.switch_history_table,
            self.active_link_switch_table,
            self.interface_rate_table,
            self.fping_1s_table,
            self.iperf_table,
            self.diagnosis_table,
            self.history_table,
        ):
            apply_analysis_table_style(table)

    def _auto_fit_online_table(self, table: QTableWidget, name: str) -> None:
        min_widths, max_widths = self._analysis_table_width_bounds(name)
        auto_fit_table_columns(table, min_widths=min_widths, max_widths=max_widths)

    @staticmethod
    def _analysis_table_width_bounds(name: str) -> tuple[dict[int, int], dict[int, int]]:
        min_bounds: dict[str, dict[int, int]] = {
            "mesh_link": {0: 60, 1: 190, 2: 190, 3: 80, 4: 100, 5: 150, 6: 150, 7: 90, 8: 150, 9: 160, 10: 140, 11: 160, 12: 120},
            "mesh_link_detail": {0: 60, 1: 190, 2: 190, 3: 80, 4: 100, 5: 150, 6: 160, 7: 150, 8: 140, 9: 160, 10: 150, 11: 90, 12: 150, 13: 160, 14: 120},
            "channel_busy": {0: 60, 1: 190, 2: 80, 3: 100, 4: 80, 5: 90, 6: 150, 7: 120, 8: 120},
            "switch_history": {0: 60, 1: 190, 2: 80, 3: 150, 4: 150, 5: 150, 6: 150, 7: 140, 8: 140, 9: 180, 10: 220, 11: 100, 12: 130, 13: 700},
            "active_link_switch_logs": {0: 60, 1: 190, 2: 160, 3: 150, 4: 150, 5: 80, 6: 140, 7: 160, 8: 150, 9: 150, 10: 80, 11: 140, 12: 160, 13: 90, 14: 90, 15: 100, 16: 260, 17: 520},
            "interface_rate": {0: 60, 1: 190, 2: 100, 3: 120, 4: 100, 5: 100, 6: 100, 7: 100, 8: 700},
            "fping_1s": {0: 60, 1: 190, 2: 190, 3: 190, 4: 140, 5: 150, 6: 90, 7: 90, 8: 90, 9: 100, 10: 120, 11: 120, 12: 120, 13: 100, 14: 90},
            "session_summary": {0: 180, 1: 130, 2: 90, 3: 190, 4: 150, 5: 80, 6: 130, 7: 160, 8: 80, 9: 90, 10: 90, 11: 90, 12: 90, 13: 190, 14: 100, 15: 80, 16: 170, 17: 80},
            "statistics": {0: 180, 1: 120, 2: 90, 3: 180, 4: 180, 5: 320},
            "iperf": {0: 180, 1: 100, 2: 90, 3: 120, 4: 700},
            "diagnosis": {0: 190, 1: 190, 2: 170, 3: 90, 4: 90, 5: 90, 6: 110, 7: 110, 8: 110, 9: 130, 10: 130, 11: 100, 12: 100, 13: 100},
            "history_sessions": {0: 170, 1: 170, 2: 170, 3: 110, 4: 120, 5: 120, 6: 100, 7: 120, 8: 700},
        }
        max_bounds = {column: 900 if width >= 700 else max(width, 420) for column, width in min_bounds.get(name, {}).items()}
        return min_bounds.get(name, {}), max_bounds

    def _load_all_table_widths(self) -> None:
        tables = {
            "session_summary": self.summary_table,
            "mesh_link": self.mesh_table,
            "mesh_link_detail": self.mesh_detail_table,
            "channel_busy": self.channel_table,
            "statistics": self.events_table,
            "switch_history": self.switch_history_table,
            "active_link_switch_logs": self.active_link_switch_table,
            "interface_rate": self.interface_rate_table,
            "fping_1s": self.fping_1s_table,
            "iperf": self.iperf_table,
            "diagnosis": self.diagnosis_table,
            "history_sessions": self.history_table,
        }
        defaults = {
            "session_summary": [180, 130, 90, 190, 150, 80, 130, 160, 80, 90, 90, 90, 90, 190, 100, 80, 170, 80],
            "mesh_link": [70, 190, 190, 90, 110, 160, 170, 90, 160, 150, 130, 160, 140],
            "mesh_link_detail": [70, 190, 190, 90, 110, 160, 170, 160, 130, 160, 160, 90, 160, 150, 140],
            "channel_busy": [60, 190, 90, 100, 80, 90, 150, 120, 120],
            "statistics": [180, 120, 90, 180, 180, 320],
            "switch_history": [70, 190, 90, 150, 150, 150, 150, 130, 130, 180, 150, 120, 140, 500],
            "active_link_switch_logs": [60, 190, 160, 150, 150, 80, 140, 160, 150, 150, 80, 140, 160, 90, 90, 100, 260, 520],
            "interface_rate": [60, 190, 100, 120, 100, 100, 100, 100, 700],
            "fping_1s": [60, 190, 190, 190, 140, 150, 90, 90, 90, 100, 120, 120, 120, 100, 90],
            "iperf": [180, 100, 90, 120, 520],
            "diagnosis": [190, 190, 170, 90, 90, 90, 110, 110, 110, 130, 130, 100, 100, 100],
            "history_sessions": [170, 170, 170, 110, 120, 120, 100, 120, 360],
        }
        for name, table in tables.items():
            widths = self.settings.get_value(TABLE_WIDTH_KEYS[name], defaults[name])
            if not isinstance(widths, list):
                widths = defaults[name]
            for column, width in enumerate(widths[: table.columnCount()]):
                default_width = defaults[name][column] if column < len(defaults[name]) else int(width)
                table.setColumnWidth(column, max(int(width), int(default_width)))
            if table is self.summary_table:
                header = table.horizontalHeader()
                for column in range(table.columnCount()):
                    header.setSectionResizeMode(column, QHeaderView.Interactive)
            table.horizontalHeader().sectionResized.connect(lambda _idx, _old, _new, n=name, t=table: self._save_table_widths(n, t))

    def _save_table_widths(self, name: str, table: QTableWidget) -> None:
        widths = [table.columnWidth(column) for column in range(table.columnCount())]
        self.settings.set_value(TABLE_WIDTH_KEYS[name], widths)

    def _set_status(self, status: str) -> None:
        self.status_value = status
        self._collection_status = status
        if not self._can_update_ui():
            return
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


def _normalize_peer_name_key(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _format_in_out_rssi(in_rssi: object, out_rssi: object) -> str:
    left = str(in_rssi or "").strip()
    right = str(out_rssi or "").strip()
    if not left and not right:
        return ""
    return f"{left or '-'}/{right or '-'}"


def _format_duration_value(value: object) -> str:
    if value is None or str(value).strip() == "":
        return "-"
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value).strip() or "-"
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s"


def _display_belong_type(value: object) -> str:
    text = str(value or "").strip().casefold()
    return {
        "station": "站点",
        "section": "区间",
        "yard": "场段/库内",
        "unknown": "未知",
    }.get(text, str(value or "").strip() or "-")


def _is_valid_peer_resolution(value: dict[str, object]) -> bool:
    if not value:
        return False
    if str(value.get("match_rule") or "").strip().lower() == "unresolved":
        return False
    return any(str(value.get(key) or "").strip() for key in ("peer_ap_name", "peer_site", "peer_section", "site", "serial_number", "peer_serial_number", "radio_mac", "peer_radio_mac"))
