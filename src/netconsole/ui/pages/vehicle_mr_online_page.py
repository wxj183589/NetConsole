from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from pathlib import Path
import uuid

from PySide6.QtCore import QDateTime, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QComboBox,
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDateTimeEdit,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.vehicle_mr_online import (
    MatchedAp,
    TrainIdentity,
    TRAIN_STATUS_OFFLINE,
    TRAIN_STATUS_ONLINE,
    TRAIN_STATUS_PARTIAL,
    TRAIN_STATUS_ABNORMAL_SINGLE,
    TRAIN_STATUS_DUAL_ONLINE,
    TRAIN_STATUS_UNEXPECTED_END,
    ONLINE_POLICY_LABELS,
    ONLINE_POLICY_AUTO,
    VehicleMrOnlineSnapshot,
    VehicleMrOnlineStore,
    VehicleMrEndState,
    VehicleMrTrainMapping,
    VehicleMrTrainState,
    is_ac_device,
    normalize_train_no,
    normalize_online_policy,
    online_policy_label,
    train_sort_key,
)
from netconsole.ui.pages.online_mr_collection_page import connection_fields_from_device
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.services.export.export_task_builders import table_xlsx_spec, vehicle_mr_history_xlsx_spec
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.vehicle_mr_online_worker import VehicleMrOnlineWorker
from netconsole.ui.widgets.adaptive_dialog import install_scrollable_dialog_content
from netconsole.ui.widgets.no_wheel import NoWheelSpinBox
from netconsole.ui.widgets.table_combo_delegate import ComboBoxItemDelegate, combo_item_value


VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS = (
    ("train", "车次"),
    ("tc1", "TC1"),
    ("tc2", "TC2"),
    ("online_policy", "在线策略"),
    ("remark", "备注"),
)
VEHICLE_MR_MAPPING_TEMPLATE_ROWS = [
    {"train": "1车", "tc1": "0101", "tc2": "0106", "online_policy": "单端在线-尾端在线", "remark": "正式环境尾端MR在线"},
    {"train": "2车", "tc1": "0201", "tc2": "0206", "online_policy": "双端在线", "remark": "正线双活"},
    {"train": "3车", "tc1": "0301", "tc2": "0306", "online_policy": "单端在线-TC1固定在线", "remark": ""},
    {"train": "4车", "tc1": "0401", "tc2": "0406", "online_policy": "单端在线-TC2固定在线", "remark": ""},
]


def _vehicle_train_state_map(payload: object) -> dict[str, VehicleMrTrainState]:
    result: dict[str, VehicleMrTrainState] = {}
    if not isinstance(payload, dict):
        return result
    for key, value in payload.items():
        if isinstance(value, dict):
            result[str(key)] = _vehicle_train_state_from_dict(value)
    return result


def _vehicle_train_state_from_dict(data: dict[str, object]) -> VehicleMrTrainState:
    values = dict(data)
    for field in ("tc1", "tc2"):
        if isinstance(values.get(field), dict):
            values[field] = VehicleMrEndState(**dict(values[field]))
    return VehicleMrTrainState(**values)


def _vehicle_ap_lookup_from_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {"__resources__": []}
    result: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            result[str(key)] = [MatchedAp(**dict(item)) if isinstance(item, dict) else item for item in value]
        elif isinstance(value, dict):
            result[str(key)] = MatchedAp(**dict(value))
        else:
            result[str(key)] = value
    result.setdefault("__resources__", [])
    return result


def _vehicle_mapping_lookup_from_payload(payload: object) -> dict[str, TrainIdentity]:
    result: dict[str, TrainIdentity] = {}
    if not isinstance(payload, dict):
        return result
    for key, value in payload.items():
        if isinstance(value, dict):
            result[str(key)] = TrainIdentity(**dict(value))
    return result


class VehicleMrOnlinePage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.store = VehicleMrOnlineStore(paths, site_name)
        self.background_manager = BackgroundProcessManager(self, paths=paths)
        self.background_manager.finished.connect(self._refresh_background_finished)
        self.background_manager.failed.connect(self._refresh_background_failed)
        self._refresh_job_id: str | None = None
        self.devices: list[Device] = []
        self.group_names: dict[int, str] = {}
        self.registered_trains: dict[str, VehicleMrTrainState] = {}
        self.current_trains: dict[str, VehicleMrTrainState] = {}
        self.worker: VehicleMrOnlineWorker | None = None
        self.selected_train_id = ""
        self.ap_lookup: dict[str, object] = {}
        self.mapping_lookup: dict[str, TrainIdentity] = {}
        self.history_windows: list[VehicleMrHistoryQueryDialog] = []
        self._ap_refresh_job_id: str | None = None
        self._event_job_id: str | None = None
        self._event_job_train_id = ""
        self._event_widths_initialized = False
        self._last_valid_interval = 10

        self.title_label = QLabel("列车在线情况")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.ac_combo = QComboBox()
        self.interval_spin = NoWheelSpinBox()
        self.interval_spin.setRange(3, 300)
        self.interval_spin.setValue(10)
        self.interval_spin.setMinimumWidth(80)
        self.interval_spin.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.interval_unit_label = QLabel("秒")
        self.interval_unit_label.setMinimumWidth(24)
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.refresh_button = QPushButton("刷新")
        self.refresh_ap_button = QPushButton("刷新AP映射")
        self.mapping_button = QPushButton("映射表管理")
        self.status_label = QLabel("未开始")
        self.status_label.setStyleSheet(_status_stylesheet("未开始"))
        self.ac_time_label = QLabel("-")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.ap_hint_label = QLabel("")
        self.ap_hint_label.setWordWrap(True)

        self.online_count = QLabel("0")
        self.partial_count = QLabel("0")
        self.offline_count = QLabel("0")
        self.unregistered_count = QLabel("0")

        self.train_table = QTableWidget(0, 6)
        self.detail_empty_label = QLabel("请选择左侧列车查看当前状态和历史经过")
        self.detail_empty_label.setAlignment(Qt.AlignCenter)
        self.detail_empty_label.setWordWrap(True)
        self.detail_widget = QWidget()
        self.detail_grid = QGridLayout(self.detail_widget)
        self.detail_title = QLabel("-")
        self.detail_badge = QLabel("")
        self.detail_status = QLabel("-")
        self.detail_station = QLabel("-")
        self.detail_time = QLabel("-")
        self.detail_policy = QLabel("-")
        self.detail_direction = QLabel("-")
        self.detail_expected_end = QLabel("-")
        self.detail_reason = QLabel("-")
        self.tc1_labels = self._end_labels()
        self.tc2_labels = self._end_labels()
        self.event_table = QTableWidget(0, 6)
        for table in (self.train_table, self.event_table):
            configure_readonly_table(table)
            table.setWordWrap(False)
        self.train_table.setHorizontalHeaderLabels(["列车", "状态", "当前车站", "TC1端", "TC2端", "更新时间"])
        self.event_table.setHorizontalHeaderLabels(["时间", "端别", "状态", "车站", "轨旁AP", "RSSI"])

        self._build_ui()
        self._connect_signals()
        self._apply_button_icons()
        self.refresh_all()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.set_site(site_name)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.store = VehicleMrOnlineStore(self.paths, site_name)
        self.refresh_all()

    def first_show_refresh(self) -> None:
        self.refresh_all()

    def refresh_all(self) -> None:
        if self._refresh_job_id is not None:
            self.status_label.setText("刷新中")
            return
        if self.train_table.rowCount() == 0:
            self._fill_train_table([])
        self._refresh_job_id = uuid.uuid4().hex
        self.refresh_button.setEnabled(False)
        self.status_label.setText("刷新中")
        self.background_manager.start_job(
            BackgroundJob(
                job_id=self._refresh_job_id,
                task_type="vehicle_mr_online_refresh_all",
                params={
                    "db_path": str(self.repository.database.path),
                    "site_name": self.site_name,
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                },
            )
        )

    def _refresh_background_finished(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        result = dict(event.get("result") or {})
        if job_id == self._refresh_job_id:
            self._refresh_job_id = None
            self.refresh_button.setEnabled(True)
            self._apply_refresh_result(result)
            return
        if job_id == self._ap_refresh_job_id:
            self._ap_refresh_job_id = None
            self._apply_ap_refresh_result(result)
            self._update_buttons()
            return
        if job_id == self._event_job_id:
            self._event_job_id = None
            self._apply_event_result(result)
            return
        for dialog in list(self.history_windows):
            handler = getattr(dialog, "handle_background_result", None)
            if callable(handler) and handler(job_id, result):
                return

    def _refresh_background_failed(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        message = str(event.get("message") or event.get("error") or "后台任务失败")
        if job_id == self._refresh_job_id:
            self._refresh_job_id = None
            self.refresh_button.setEnabled(True)
            self.status_label.setText("刷新失败")
            MessageBox.warning(self, "列车在线情况", message)
            return
        if job_id == self._ap_refresh_job_id:
            self._ap_refresh_job_id = None
            self._update_buttons()
            self.status_label.setText("AP映射刷新失败")
            MessageBox.warning(self, "列车在线情况", message)
            return
        if job_id == self._event_job_id:
            self._event_job_id = None
            self._event_job_train_id = ""
            self._set_event_placeholder("历史经过加载失败")
            return
        for dialog in list(self.history_windows):
            handler = getattr(dialog, "handle_background_error", None)
            if callable(handler) and handler(job_id, message):
                return

    def _apply_refresh_result(self, result: dict[str, object]) -> None:
        self.devices = [Device.from_mapping(dict(row)) for row in result.get("devices") or [] if isinstance(row, dict)]
        self.group_names = {int(key): str(value) for key, value in dict(result.get("group_names") or {}).items()}
        self.registered_trains = _vehicle_train_state_map(result.get("registered_trains"))
        self.current_trains = _vehicle_train_state_map(result.get("current_trains"))
        self.ap_lookup = _vehicle_ap_lookup_from_payload(result.get("ap_lookup"))
        self.mapping_lookup = _vehicle_mapping_lookup_from_payload(result.get("mapping_lookup"))
        resources = self.ap_lookup.get("__resources__")
        count = len(resources) if isinstance(resources, list) else 0
        self.ap_hint_label.setText("" if count else "请先在 AC管理 → FIT-AP资源 中更新 AP 资源")
        self._fill_ac_combo()
        self._fill_train_table(sorted(self.current_trains.values(), key=train_sort_key))
        self._update_stats()
        self._update_buttons()
        self.status_label.setText("刷新完成")

    def retranslate(self) -> None:
        self.title_label.setText("列车在线情况")
        self._apply_button_icons()

    def _apply_button_icons(self) -> None:
        for button, icon_name in (
            (self.start_button, "PLAY"),
            (self.stop_button, "CANCEL"),
            (self.refresh_button, "SYNC"),
            (self.refresh_ap_button, "SYNC"),
            (self.mapping_button, "SETTING"),
        ):
            apply_button_icon(button, icon_name)

    def start_collection(self) -> None:
        ac = self.ac_combo.currentData()
        if not isinstance(ac, Device):
            MessageBox.warning(self, "列车在线情况", "请先选择无线控制器 AC。")
            return
        config = self._build_connection_config(ac)
        if config is None:
            MessageBox.warning(self, "列车在线情况", "AC 连接信息不完整。")
            return
        self._set_collection_status("连接中")
        self.error_label.setText("")
        self.worker = VehicleMrOnlineWorker(
            ac=ac,
            site_name=self.site_name,
            interval_seconds=self._interval_seconds(),
            paths=self.paths,
            registered_trains=self.registered_trains,
            ap_lookup=self.ap_lookup,
            mapping_lookup=self.mapping_lookup,
            connection_config=config,
            parent=self,
        )
        self.worker.snapshot.connect(self.on_snapshot)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()

    def stop_collection(self) -> None:
        if self.worker is not None:
            self._set_collection_status("停止中")
            self.worker.cancel()
        self._update_buttons()

    def refresh_ap_mapping(self) -> None:
        if self._ap_refresh_job_id is not None:
            self.status_label.setText("AP映射刷新中")
            return
        self._ap_refresh_job_id = uuid.uuid4().hex
        self.refresh_ap_button.setEnabled(False)
        self.status_label.setText("AP映射刷新中")
        self.background_manager.start_job(
            BackgroundJob(
                job_id=self._ap_refresh_job_id,
                task_type="vehicle_mr_ap_mapping_refresh",
                params={
                    "db_path": str(self.repository.database.path),
                    "site_name": self.site_name,
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "train_id": self.selected_train_id,
                    "limit": 200,
                },
            )
        )

    def open_mapping_dialog(self) -> None:
        dialog = VehicleMrMappingDialog(self.store, self)
        dialog.saved.connect(self.on_mapping_saved)
        dialog.exec()

    def on_mapping_saved(self) -> None:
        self.refresh_all()

    def on_snapshot(self, snapshot: VehicleMrOnlineSnapshot) -> None:
        self._set_collection_status(snapshot.status)
        if snapshot.ac_time:
            self.ac_time_label.setText(snapshot.ac_time)
        self.error_label.setText(snapshot.error_message)
        if snapshot.trains:
            self.current_trains = {train.train_id: train for train in snapshot.trains}
            self._fill_train_table(snapshot.trains)
            self._update_stats()
            if self.selected_train_id:
                self._fill_detail(self.current_trains.get(self.selected_train_id))

    def on_completed(self, _session_id: str) -> None:
        self._set_collection_status("已停止")
        self.worker = None
        self._update_buttons()

    def on_failed(self, message: str) -> None:
        self._set_collection_status("连接失败")
        self.error_label.setText(message)
        self.worker = None
        self._update_buttons()

    def on_row_selected(self, row: int, _column: int) -> None:
        item = self.train_table.item(row, 0)
        if item is None:
            return
        train_id = item.data(Qt.UserRole)
        self.selected_train_id = str(train_id or "")
        self._fill_detail(self.current_trains.get(self.selected_train_id))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(self.title_label)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("AC"))
        controls.addWidget(self.ac_combo, 2)
        controls.addWidget(QLabel("采集间隔"))
        controls.addWidget(self.interval_spin)
        controls.addWidget(self.interval_unit_label)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.refresh_ap_button)
        controls.addWidget(self.mapping_button)
        controls.addStretch(1)
        controls.addWidget(QLabel("状态："))
        controls.addWidget(self.status_label)
        controls.addWidget(QLabel("更新时间："))
        controls.addWidget(self.ac_time_label)
        root.addLayout(controls)
        root.addWidget(self.error_label)
        root.addWidget(self.ap_hint_label)

        stats = QHBoxLayout()
        for title, label in (
            ("在线列车", self.online_count),
            ("异常列车", self.partial_count),
            ("离线列车", self.offline_count),
            ("未登记列车", self.unregistered_count),
        ):
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size: 20px; font-weight: 600;")
            layout.addWidget(label)
            stats.addWidget(box)
        root.addLayout(stats)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.train_table)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        current_box = QGroupBox("当前状态")
        current_layout = QVBoxLayout(current_box)
        self._build_detail_widget()
        current_layout.addWidget(self.detail_empty_label)
        current_layout.addWidget(self.detail_widget)
        event_box = QGroupBox("历史经过")
        event_layout = QVBoxLayout(event_box)
        event_layout.addWidget(self.event_table)
        detail_layout.addWidget(current_box)
        detail_layout.addWidget(event_box)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([900, 520])
        root.addWidget(splitter, 1)
        self._configure_tables()

    def _connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start_collection)
        self.stop_button.clicked.connect(self.stop_collection)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.refresh_ap_button.clicked.connect(self.refresh_ap_mapping)
        self.mapping_button.clicked.connect(self.open_mapping_dialog)
        self.interval_spin.valueChanged.connect(self._apply_interval_change)
        self.train_table.cellClicked.connect(self.on_row_selected)
        self.train_table.cellDoubleClicked.connect(self.open_history_for_row)

    def _fill_ac_combo(self) -> None:
        current_id = self.ac_combo.currentData().id if isinstance(self.ac_combo.currentData(), Device) else None
        self.ac_combo.blockSignals(True)
        self.ac_combo.clear()
        for device in sorted([device for device in self.devices if is_ac_device(device)], key=lambda item: item.name):
            self.ac_combo.addItem(f"{device.name} ({device.primary_address})", device)
        if current_id is not None:
            for index in range(self.ac_combo.count()):
                device = self.ac_combo.itemData(index)
                if isinstance(device, Device) and device.id == current_id:
                    self.ac_combo.setCurrentIndex(index)
                    break
        self.ac_combo.blockSignals(False)

    def _fill_train_table(self, trains: list[VehicleMrTrainState]) -> None:
        selected = self.selected_train_id
        self.train_table.clearSpans()
        self.train_table.setRowCount(0)
        if not trains:
            self.train_table.insertRow(0)
            self.train_table.setSpan(0, 0, 1, self.train_table.columnCount())
            item = QTableWidgetItem("当前局点暂无列车在线数据，请点击刷新或开始采集。")
            item.setTextAlignment(Qt.AlignCenter)
            self.train_table.setItem(0, 0, item)
            self._apply_train_table_widths()
            return
        for train in trains:
            row = self.train_table.rowCount()
            self.train_table.insertRow(row)
            values = [
                train.display_name + ("" if train.is_registered else "（未登记）"),
                train.status,
                train.current_station,
                train.tc1.display(),
                train.tc2.display(),
                train.last_ac_time or "-",
            ]
            for column, value in enumerate(values):
                item = _status_item(str(value)) if column == 1 else QTableWidgetItem(str(value))
                if column in {0, 1, 5}:
                    item.setTextAlignment(Qt.AlignCenter)
                elif column in {3, 4}:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                elif column == 2:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignCenter)
                if column == 0:
                    item.setData(Qt.UserRole, train.train_id)
                self.train_table.setItem(row, column, item)
            if selected == train.train_id:
                self.train_table.selectRow(row)
        self._apply_train_table_widths()

    def _fill_detail(self, train: VehicleMrTrainState | None) -> None:
        if train is None:
            self.event_table.setRowCount(0)
            self.detail_empty_label.setVisible(True)
            self.detail_widget.setVisible(False)
            return
        self.detail_empty_label.setVisible(False)
        self.detail_widget.setVisible(True)
        self.detail_title.setText(f"{train.display_name} / {train.train_id}")
        self.detail_badge.setText("" if train.is_registered else "未登记")
        self.detail_badge.setVisible(not train.is_registered)
        self.detail_status.setText(train.status)
        self.detail_status.setStyleSheet(_status_stylesheet(train.status))
        self.detail_station.setText(train.current_station or "-")
        self.detail_time.setText(train.last_ac_time or "-")
        self.detail_policy.setText(online_policy_label(train.online_policy))
        self.detail_direction.setText(train.direction or "未知")
        self.detail_expected_end.setText(train.expected_end or "-")
        self.detail_reason.setText(_status_reason_label(train.status_reason))
        self._set_end_labels(self.tc1_labels, "TC1端", train.tc1)
        self._set_end_labels(self.tc2_labels, "TC2端", train.tc2)
        self._fill_events(train.train_id)

    def _fill_events(self, train_id: str) -> None:
        self._request_events(train_id)

    def _request_events(self, train_id: str) -> None:
        if self._event_job_id is not None and self._event_job_train_id == train_id:
            return
        self._event_job_id = uuid.uuid4().hex
        self._event_job_train_id = train_id
        self._set_event_placeholder("正在加载历史经过...")
        self.background_manager.start_job(
            BackgroundJob(
                job_id=self._event_job_id,
                task_type="vehicle_mr_event_page",
                params={
                    "site_name": self.site_name,
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "train_id": train_id,
                    "limit": 200,
                },
            )
        )

    def _apply_event_result(self, result: dict[str, object]) -> None:
        train_id = str(result.get("train_id") or "")
        self._event_job_train_id = ""
        if train_id != self.selected_train_id:
            return
        self._fill_event_rows([dict(row) for row in result.get("rows") or [] if isinstance(row, dict)])

    def _apply_ap_refresh_result(self, result: dict[str, object]) -> None:
        self.ap_lookup = _vehicle_ap_lookup_from_payload(result.get("ap_lookup"))
        resources = self.ap_lookup.get("__resources__")
        count = len(resources) if isinstance(resources, list) else 0
        self.ap_hint_label.setText("" if count else "请先在 AC管理 → FIT-AP资源 中更新 AP 资源")
        backfilled = int(result.get("backfilled") or 0)
        self.status_label.setText(f"AP映射刷新完成，回填 {backfilled} 条")
        train_id = str(result.get("train_id") or "")
        if train_id and train_id == self.selected_train_id:
            self._fill_event_rows([dict(row) for row in result.get("events") or [] if isinstance(row, dict)])

    def _set_event_placeholder(self, text: str) -> None:
        self.event_table.clearSpans()
        self.event_table.setRowCount(0)
        self.event_table.insertRow(0)
        self.event_table.setSpan(0, 0, 1, self.event_table.columnCount())
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.event_table.setItem(0, 0, item)

    def _fill_event_rows(self, events: list[dict[str, object]]) -> None:
        self.event_table.clearSpans()
        self.event_table.setRowCount(0)
        for event in events:
            row = self.event_table.rowCount()
            self.event_table.insertRow(row)
            values = [
                event.get("event_time") or "",
                event.get("car_end_label") or "",
                event.get("status") or "",
                event.get("station") or "",
                event.get("ap_name") or "",
                event.get("rssi") if event.get("rssi") is not None else "-",
            ]
            for column, value in enumerate(values):
                item = _status_item(str(value)) if column == 2 else QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(str(value))
                self.event_table.setItem(row, column, item)
        if self.event_table.rowCount() == 0:
            self.event_table.insertRow(0)
            self.event_table.setSpan(0, 0, 1, self.event_table.columnCount())
            item = QTableWidgetItem("暂无历史经过")
            item.setTextAlignment(Qt.AlignCenter)
            self.event_table.setItem(0, 0, item)
        if not self._event_widths_initialized:
            self._apply_event_table_widths()
            self._event_widths_initialized = True

    def _update_stats(self) -> None:
        trains = list(self.current_trains.values())
        self.online_count.setText(str(sum(1 for train in trains if train.status in {TRAIN_STATUS_ONLINE, TRAIN_STATUS_DUAL_ONLINE})))
        self.partial_count.setText(str(sum(1 for train in trains if train.status in {TRAIN_STATUS_ABNORMAL_SINGLE, TRAIN_STATUS_UNEXPECTED_END, TRAIN_STATUS_PARTIAL})))
        self.offline_count.setText(str(sum(1 for train in trains if train.status == TRAIN_STATUS_OFFLINE)))
        self.unregistered_count.setText(str(sum(1 for train in trains if not train.is_registered)))

    def _update_buttons(self) -> None:
        running = self.worker is not None
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.ac_combo.setEnabled(not running)
        self.refresh_button.setEnabled(not running and self._refresh_job_id is None)
        self.refresh_ap_button.setEnabled(not running and self._ap_refresh_job_id is None)
        self.mapping_button.setEnabled(not running)
        self.interval_spin.setEnabled(True)

    def _set_collection_status(self, status: str) -> None:
        self.status_label.setText(status)
        self.status_label.setStyleSheet(_status_stylesheet(status))

    def _interval_seconds(self) -> int:
        value = int(self.interval_spin.value() or self._last_valid_interval or 10)
        if value < 3 or value > 300:
            return self._last_valid_interval or 10
        self._last_valid_interval = value
        return value

    def _apply_interval_change(self) -> None:
        value = self._interval_seconds()
        if self.worker is not None:
            self.worker.collector.interval_seconds = value

    def _normalize_interval_combo(self) -> None:
        value = self._interval_seconds()
        self.interval_spin.blockSignals(True)
        try:
            self.interval_spin.setValue(value)
        finally:
            self.interval_spin.blockSignals(False)

    def open_history_for_row(self, row: int, _column: int) -> None:
        item = self.train_table.item(row, 0)
        if item is None:
            return
        train_id = str(item.data(Qt.UserRole) or "")
        train = self.current_trains.get(train_id)
        if train is None:
            return
        dialog = VehicleMrHistoryQueryDialog(self.store, train, self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda _obj=None, d=dialog: self._forget_history_window(d))
        self.history_windows.append(dialog)
        dialog.show()

    def _forget_history_window(self, dialog: QDialog) -> None:
        self.history_windows = [window for window in self.history_windows if window is not dialog]

    def _configure_tables(self) -> None:
        self.train_table.verticalHeader().setDefaultSectionSize(32)
        self.event_table.verticalHeader().setDefaultSectionSize(30)
        self.train_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.event_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._apply_train_table_widths()
        self._apply_event_table_widths()
        self._event_widths_initialized = True

    def _apply_train_table_widths(self) -> None:
        for column, width in enumerate((100, 90, 150, 260, 260, 110)):
            self.train_table.setColumnWidth(column, width)

    def _apply_event_table_widths(self) -> None:
        for column, width in enumerate((165, 60, 70, 150, 180, 60)):
            self.event_table.setColumnWidth(column, width)

    def _end_labels(self) -> dict[str, QLabel]:
        return {key: QLabel("-") for key in ("title", "status", "station", "ap", "rssi", "last_seen")}

    def _build_detail_widget(self) -> None:
        self.detail_widget.setVisible(False)
        header = QHBoxLayout()
        header.addWidget(self.detail_title)
        header.addWidget(self.detail_badge)
        header.addStretch(1)
        self.detail_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detail_badge.setStyleSheet("border-radius: 4px; padding: 2px 6px; background: #dbeafe;")
        self.detail_grid.addLayout(header, 0, 0, 1, 2)
        self.detail_grid.addWidget(QLabel("状态："), 1, 0)
        self.detail_grid.addWidget(self.detail_status, 1, 1)
        self.detail_grid.addWidget(QLabel("当前车站："), 2, 0)
        self.detail_grid.addWidget(self.detail_station, 2, 1)
        self.detail_grid.addWidget(QLabel("更新时间："), 3, 0)
        self.detail_grid.addWidget(self.detail_time, 3, 1)
        self.detail_grid.addWidget(QLabel("在线策略："), 4, 0)
        self.detail_grid.addWidget(self.detail_policy, 4, 1)
        self.detail_grid.addWidget(QLabel("方向："), 5, 0)
        self.detail_grid.addWidget(self.detail_direction, 5, 1)
        self.detail_grid.addWidget(QLabel("预期在线端："), 6, 0)
        self.detail_grid.addWidget(self.detail_expected_end, 6, 1)
        self.detail_grid.addWidget(QLabel("当前判断："), 7, 0)
        self.detail_grid.addWidget(self.detail_reason, 7, 1)
        self._add_end_card(self.detail_grid, self.tc1_labels, 8, 0)
        self._add_end_card(self.detail_grid, self.tc2_labels, 8, 1)

    def _add_end_card(self, parent: QGridLayout, labels: dict[str, QLabel], row: int, column: int) -> None:
        box = QGroupBox()
        layout = QGridLayout(box)
        layout.addWidget(labels["title"], 0, 0, 1, 2)
        labels["title"].setStyleSheet("font-weight: 600;")
        for index, (name, key) in enumerate((("状态", "status"), ("车站", "station"), ("轨旁AP", "ap"), ("RSSI", "rssi"), ("最后出现", "last_seen")), start=1):
            layout.addWidget(QLabel(f"{name}："), index, 0)
            layout.addWidget(labels[key], index, 1)
        parent.addWidget(box, row, column)

    def _set_end_labels(self, labels: dict[str, QLabel], title: str, end_state) -> None:
        labels["title"].setText(title)
        status = "在线" if end_state.seen else "离线"
        labels["status"].setText(status)
        labels["status"].setStyleSheet(_status_stylesheet(status))
        labels["station"].setText(end_state.station or "-")
        labels["ap"].setText(end_state.ap_name or "-")
        labels["rssi"].setText("-" if end_state.rssi is None else str(end_state.rssi))
        labels["last_seen"].setText(end_state.last_seen_at or "-")

    def _build_connection_config(self, ac: Device) -> OnlineMrConnectionConfig | None:
        protocol, port, username, password = connection_fields_from_device(ac)
        if not protocol or not ac.primary_address or not username or not password:
            return None
        return OnlineMrConnectionConfig(
            site=self.site_name,
            mr_id=f"ac-{ac.id or ac.name}",
            mr_name=ac.name,
            safe_mr_name="vehicle_mr_online",
            device_id=ac.id,
            device_name=ac.name,
            host=ac.primary_address,
            protocol=protocol,
            port=port,
            username=username,
            password=password,
            command_timeout=15,
            connection_targets=tuple(connection_targets(ac)),
        )


class VehicleMrHistoryQueryDialog(QDialog):
    def __init__(self, store: VehicleMrOnlineStore, train: VehicleMrTrainState, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.train = train
        self.rows: list[dict[str, object]] = []
        self.background_manager = getattr(parent, "background_manager", None)
        self.query_job_id: str | None = None
        self.setWindowTitle(f"历史记录 - {train.display_name}")
        self.resize(920, 560)
        self.start_edit = QDateTimeEdit()
        self.end_edit = QDateTimeEdit()
        for edit in (self.start_edit, self.end_edit):
            edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            edit.setCalendarPopup(True)
        now = QDateTime.currentDateTime()
        self.start_edit.setDateTime(QDateTime(now.date(), QTime(0, 0, 0)))
        self.end_edit.setDateTime(now)
        self.end_combo = QComboBox()
        self.end_combo.addItems(["全部", "TC1", "TC2"])
        self.status_combo = QComboBox()
        self.status_combo.addItems(["全部", "在线", "离线"])
        self.station_edit = QLineEdit()
        self.ap_edit = QLineEdit()
        self.query_button = QPushButton("查询")
        self.reset_button = QPushButton("重置")
        self.export_button = QPushButton("导出")
        self.hint_label = QLabel("历史记录查询结果不会实时刷新，请点击“查询”更新。")
        self.table = QTableWidget(0, 8)
        configure_readonly_table(self.table)
        self.table.setHorizontalHeaderLabels(["时间", "端别", "状态", "车站", "轨旁AP", "RSSI", "事件类型", "判断说明"])
        self.scroll_area = None
        self._build_ui()
        self.query_button.clicked.connect(lambda: self.query())
        self.reset_button.clicked.connect(self.reset)
        self.export_button.clicked.connect(self.export)
        self.query(show_error=False)

    def _build_ui(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        filters = QGridLayout()
        filters.setHorizontalSpacing(12)
        filters.setVerticalSpacing(10)
        filters.addWidget(QLabel(f"列车：{self.train.display_name} / {self.train.train_id}"), 0, 0, 1, 2)
        filters.addWidget(QLabel("开始时间"), 1, 0)
        filters.addWidget(self.start_edit, 1, 1)
        filters.addWidget(QLabel("结束时间"), 1, 2)
        filters.addWidget(self.end_edit, 1, 3)
        filters.addWidget(QLabel("端别"), 2, 0)
        filters.addWidget(self.end_combo, 2, 1)
        filters.addWidget(QLabel("状态"), 2, 2)
        filters.addWidget(self.status_combo, 2, 3)
        filters.addWidget(QLabel("车站"), 3, 0)
        filters.addWidget(self.station_edit, 3, 1)
        filters.addWidget(QLabel("轨旁AP"), 3, 2)
        filters.addWidget(self.ap_edit, 3, 3)
        for widget in (self.start_edit, self.end_edit, self.end_combo, self.status_combo, self.station_edit, self.ap_edit):
            widget.setMinimumWidth(180)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.query_button)
        actions.addWidget(self.reset_button)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        for button in (self.query_button, self.reset_button, self.export_button):
            button.setMinimumWidth(82)
        layout.addLayout(filters)
        layout.addLayout(actions)
        layout.addWidget(self.hint_label)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table)
        self.scroll_area = install_scrollable_dialog_content(
            self,
            content,
            minimum_width=820,
            minimum_height=520,
            content_minimum_width=900,
        )
        self._apply_widths()

    def query(self, *, show_error: bool = True) -> None:
        if self.query_job_id is not None:
            return
        end_label = "" if self.end_combo.currentText() == "全部" else self.end_combo.currentText()
        status = "" if self.status_combo.currentText() == "全部" else self.status_combo.currentText()
        manager = self.background_manager
        if manager is None:
            self.hint_label.setText("后台任务管理器不可用，暂时无法查询历史记录。")
            if show_error:
                MessageBox.warning(self, "历史查询失败", "后台任务管理器不可用。")
            return
        self.query_job_id = uuid.uuid4().hex
        self.query_button.setEnabled(False)
        self.hint_label.setText("正在查询历史记录...")
        manager.start_job(
            BackgroundJob(
                job_id=self.query_job_id,
                task_type="vehicle_mr_history_query",
                params={
                    "site_name": self.store.site_name,
                    "app_root": str(self.store.paths.app_root),
                    "data_root": str(self.store.paths.data_root),
                    "train_id": self.train.train_id,
                    "start_time": self.start_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
                    "end_time": self.end_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
                    "car_end_label": end_label,
                    "status": status,
                    "station": self.station_edit.text().strip(),
                    "ap_name": self.ap_edit.text().strip(),
                    "limit": 1000,
                },
            )
        )

    def handle_background_result(self, job_id: str, result: dict[str, object]) -> bool:
        if job_id != self.query_job_id:
            return False
        self.query_job_id = None
        self.query_button.setEnabled(True)
        self.rows = [dict(row) for row in result.get("rows") or [] if isinstance(row, dict)]
        limit = int(result.get("limit") or 1000)
        suffix = "，已按 1000 条限制显示" if len(self.rows) >= limit else ""
        self.hint_label.setText(f"查询完成，共 {len(self.rows)} 条{suffix}")
        self._fill_rows()
        return True

    def handle_background_error(self, job_id: str, message: str) -> bool:
        if job_id != self.query_job_id:
            return False
        self.query_job_id = None
        self.query_button.setEnabled(True)
        self.hint_label.setText("查询失败")
        MessageBox.warning(self, "历史查询失败", message)
        return True

    def reset(self) -> None:
        now = QDateTime.currentDateTime()
        self.start_edit.setDateTime(QDateTime(now.date(), QTime(0, 0, 0)))
        self.end_edit.setDateTime(now)
        self.end_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.station_edit.clear()
        self.ap_edit.clear()
        self.query()

    def export(self) -> None:
        default = Path.home() / "Desktop" / f"列车在线情况_{self.train.display_name}_历史记录_{QDateTime.currentDateTime().toString('yyyyMMdd')}.xlsx"
        if not default.parent.exists():
            default = Path.home() / default.name
        path, _filter = QFileDialog.getSaveFileName(self, "导出历史记录", str(default), "Excel (*.xlsx)")
        if not path:
            return
        submit_export_task(
            self,
            vehicle_mr_history_xlsx_spec(
                Path(path),
                app_root=self.store.paths.app_root,
                data_root=self.store.paths.data_root,
                site_name=self.store.site_name,
                train_id=self.train.train_id,
                filters={
                    "start_time": self.start_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
                    "end_time": self.end_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
                    "car_end_label": "" if self.end_combo.currentText() == "全部" else self.end_combo.currentText(),
                    "status": "" if self.status_combo.currentText() == "全部" else self.status_combo.currentText(),
                    "station": self.station_edit.text().strip(),
                    "ap_name": self.ap_edit.text().strip(),
                },
                title="导出历史记录",
            ),
            success_title="导出历史记录",
        )

    def _fill_rows(self) -> None:
        self.table.setRowCount(0)
        for row_data in self.rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                row_data.get("event_time") or "",
                row_data.get("car_end_label") or "",
                row_data.get("status") or "",
                row_data.get("station") or "",
                row_data.get("ap_name") or "",
                row_data.get("rssi") if row_data.get("rssi") is not None else "-",
                row_data.get("event_type") or "",
                _status_reason_label(str(row_data.get("status_reason") or "")),
            ]
            for column, value in enumerate(values):
                item = _status_item(str(value)) if column == 2 else QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        self._apply_widths()

    def _apply_widths(self) -> None:
        for column, width in enumerate((165, 60, 90, 150, 170, 60, 90, 180)):
            self.table.setColumnWidth(column, width)


class VehicleMrMappingDialog(QDialog):
    saved = Signal()

    def __init__(self, store: VehicleMrOnlineStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.background_manager = BackgroundProcessManager(self, paths=store.paths)
        self.background_manager.finished.connect(self._background_finished)
        self.background_manager.failed.connect(self._background_failed)
        self._mapping_job_id: str | None = None
        self._mapping_job_action = ""
        self.setWindowTitle("车载MR映射表管理")
        self.resize(860, 520)
        self.table = QTableWidget(0, 7)
        configure_readonly_table(self.table)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        self.table.setHorizontalHeaderLabels(["启用", "车次", "TC1", "TC2", "在线策略", "备注", "更新时间"])
        self.table.setItemDelegateForColumn(
            4,
            ComboBoxItemDelegate([(label, value) for value, label in ONLINE_POLICY_LABELS.items()], self.table),
        )
        self.add_button = QPushButton("新增")
        self.delete_button = QPushButton("删除")
        self.save_button = QPushButton("保存")
        self.import_button = QPushButton("导入")
        self.export_button = QPushButton("导出模板")
        self.refresh_button = QPushButton("刷新")
        self.scroll_area = None
        self._build_ui()
        self.add_button.clicked.connect(self.add_row)
        self.delete_button.clicked.connect(self.delete_rows)
        self.save_button.clicked.connect(self.save)
        self.import_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_template)
        self.refresh_button.clicked.connect(self.load)
        self.load()

    def _build_ui(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for button in (self.add_button, self.delete_button, self.save_button, self.import_button, self.export_button, self.refresh_button):
            button.setMinimumWidth(86)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table)
        self.scroll_area = install_scrollable_dialog_content(
            self,
            content,
            minimum_width=820,
            minimum_height=500,
            content_minimum_width=900,
        )

    def load(self) -> None:
        self._start_mapping_job("vehicle_mr_mapping_load", "load")

    def add_row(self) -> None:
        self._append_mapping(VehicleMrTrainMapping(enabled=True))

    def delete_rows(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def save(self) -> None:
        try:
            mappings = self._read_table()
        except ValueError as exc:
            MessageBox.warning(self, "映射表管理", str(exc))
            return
        self._start_mapping_job(
            "vehicle_mr_mapping_save",
            "save",
            {"mappings": [asdict(mapping) for mapping in mappings]},
        )

    def import_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "导入映射表", "", "映射表 (*.xlsx *.csv)")
        if not path:
            return
        self._start_mapping_job("vehicle_mr_mapping_import", "import", {"path": path})

    def _background_finished(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        if job_id != self._mapping_job_id:
            return
        action = self._mapping_job_action
        self._mapping_job_id = None
        self._mapping_job_action = ""
        self._set_busy(False)
        result = dict(event.get("result") or {})
        self._apply_mapping_rows(result.get("mappings"))
        if action == "import":
            MessageBox.information(self, "映射表导入", f"导入完成：{int(result.get('count') or 0)} 条")
            self.saved.emit()
        elif action == "save":
            self.saved.emit()

    def _background_failed(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        if job_id == self._mapping_job_id:
            self._mapping_job_id = None
            self._mapping_job_action = ""
            self._set_busy(False)
        MessageBox.warning(self, "映射表管理失败", str(event.get("message") or event.get("error") or "操作失败"))

    def _start_mapping_job(self, task_type: str, action: str, params: dict[str, object] | None = None) -> None:
        if self._mapping_job_id is not None:
            return
        self._mapping_job_action = action
        self._set_busy(True)
        self._mapping_job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type=task_type,
                params={
                    **(params or {}),
                    "site_name": self.store.site_name,
                    "app_root": str(self.store.paths.app_root),
                    "data_root": str(self.store.paths.data_root),
                },
            )
        )

    def _set_busy(self, busy: bool) -> None:
        for button in (self.add_button, self.delete_button, self.save_button, self.import_button, self.refresh_button):
            button.setEnabled(not busy)

    def _apply_mapping_rows(self, payload: object) -> None:
        self.table.setRowCount(0)
        for item in payload or []:
            if isinstance(item, dict):
                self._append_mapping(VehicleMrTrainMapping(**dict(item)))
        self._apply_widths()

    def export_template(self) -> None:
        default_path = Path.home() / "Desktop" / "车载MR映射模板.xlsx"
        if not default_path.parent.exists():
            default_path = Path.home() / "车载MR映射模板.xlsx"
        path, _filter = QFileDialog.getSaveFileName(self, "导出映射模板", str(default_path), "Excel (*.xlsx)")
        if not path:
            return
        submit_export_task(
            self,
            table_xlsx_spec(
                Path(path),
                columns=[{"key": key, "title": title} for key, title in VEHICLE_MR_MAPPING_TEMPLATE_COLUMNS],
                rows=VEHICLE_MR_MAPPING_TEMPLATE_ROWS,
                sheet_name="车载MR映射表",
                title="导出映射模板",
                allow_inline_rows=True,
                inline_reason="车载 MR 映射模板为空白静态模板",
            ),
            success_title="导出映射模板",
        )

    def _append_mapping(self, mapping: VehicleMrTrainMapping) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QTableWidgetItem("是")
        enabled.setCheckState(Qt.Checked if mapping.enabled else Qt.Unchecked)
        self.table.setItem(row, 0, enabled)
        values = [mapping.display_name, mapping.tc1_peer_name, mapping.tc2_peer_name]
        for column, value in enumerate(values, start=1):
            self.table.setItem(row, column, QTableWidgetItem(str(value or "")))
        policy = normalize_online_policy(mapping.online_policy)
        policy_item = QTableWidgetItem(ONLINE_POLICY_LABELS.get(policy, policy))
        policy_item.setData(Qt.UserRole, policy)
        self.table.setItem(row, 4, policy_item)
        self.table.setItem(row, 5, QTableWidgetItem(str(mapping.remark or "")))
        self.table.setItem(row, 6, QTableWidgetItem(str(mapping.updated_at or "")))

    def _read_table(self) -> list[VehicleMrTrainMapping]:
        mappings: list[VehicleMrTrainMapping] = []
        for row in range(self.table.rowCount()):
            enabled_item = self.table.item(row, 0)
            display_name = _item_text(self.table, row, 1)
            tc1 = _item_text(self.table, row, 2)
            tc2 = _item_text(self.table, row, 3)
            policy = _combo_data(self.table, row, 4, ONLINE_POLICY_AUTO)
            remark = _item_text(self.table, row, 5)
            if not display_name and not tc1 and not tc2 and not remark:
                continue
            if not display_name:
                raise ValueError(f"第 {row + 1} 行车次不能为空")
            if not tc1 and not tc2:
                raise ValueError(f"第 {row + 1} 行 TC1 和 TC2 不能同时为空")
            train_no = normalize_train_no(display_name)
            mappings.append(
                VehicleMrTrainMapping(
                    enabled=enabled_item.checkState() == Qt.Checked if enabled_item else True,
                    train_display_name=f"{train_no}车" if train_no else display_name,
                    train_id=f"列车{train_no}" if train_no else display_name,
                    train_no=train_no,
                    tc1_peer_name=tc1,
                    tc2_peer_name=tc2,
                    online_policy=normalize_online_policy(policy),
                    remark=remark,
                )
            )
        return mappings

    def _apply_widths(self) -> None:
        for column, width in enumerate((60, 90, 190, 190, 210, 180, 150)):
            self.table.setColumnWidth(column, width)


def _item_text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text().strip() if item else ""


def _combo_data(table: QTableWidget, row: int, column: int, default: str = "") -> str:
    item = table.item(row, column)
    if item is not None:
        return str(combo_item_value(item, default) or default)
    widget = table.cellWidget(row, column)
    if isinstance(widget, QComboBox):
        return str(widget.currentData() or default)
    return default


def _status_palette(status: str) -> tuple[str, str, str]:
    if status in {TRAIN_STATUS_ONLINE, TRAIN_STATUS_DUAL_ONLINE, "采集中"}:
        return "#14532d", "#bbf7d0", "status-online"
    if status in {"连接中", "停止中", "已停止", "未开始"}:
        return "#1e3a8a", "#bfdbfe", "status-info"
    if status in {TRAIN_STATUS_PARTIAL, TRAIN_STATUS_ABNORMAL_SINGLE, TRAIN_STATUS_UNEXPECTED_END}:
        return "#7c2d12", "#fed7aa", "status-partial"
    if status in {"连接失败", "解析失败/格式未适配"}:
        return "#7f1d1d", "#fecaca", "status-error"
    if status == "未登记":
        return "#1e3a8a", "#bfdbfe", "status-unregistered"
    return "#111827", "#e5e7eb", "status-offline"


def _status_reason_label(reason: str) -> str:
    labels = {
        "both_offline": "双端均离线",
        "dual_active_ok": "双端在线",
        "tc1_missing": "双活缺TC1",
        "tc2_missing": "双活缺TC2",
        "both_ends_online": "双端在线",
        "expected_tc1_online": "TC1符合预期在线",
        "expected_tc2_online": "TC2符合预期在线",
        "unexpected_tc1_online": "非预期TC1在线",
        "unexpected_tc2_online": "非预期TC2在线",
        "expected_tail_online": "尾端在线",
        "unexpected_end_online": "非预期端在线",
        "direction_unknown_any_end_online": "方向未知，任意一端在线视为在线",
        "policy_unknown_any_end_online": "自动/未知策略，任意一端在线视为在线",
    }
    return labels.get(reason, reason or "-")


def _status_stylesheet(status: str) -> str:
    fg, bg, _role = _status_palette(status)
    return f"QLabel {{ color: {fg}; background: {bg}; border-radius: 4px; padding: 2px 6px; font-weight: 600; }}"


def _status_item(status: str) -> QTableWidgetItem:
    from PySide6.QtGui import QColor, QBrush

    fg, bg, role = _status_palette(status)
    item = QTableWidgetItem(status)
    item.setForeground(QBrush(QColor(fg)))
    item.setBackground(QBrush(QColor(bg)))
    item.setData(Qt.UserRole, role)
    item.setData(Qt.UserRole + 1, fg)
    item.setData(Qt.UserRole + 2, bg)
    return item
