from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.rail_transit.car_network_diagnostic import (
    NODE_ORDER,
    POINT_TABLE_FIELDS,
    DEFAULT_GLOBAL_CONFIG,
    AcApStatus,
    AcProbeResult,
    CarNetworkDiagnosticResult,
    CarNetworkGlobalConfigStore,
    CarNetworkNode,
    CarNetworkPointTableStore,
    CarNetworkTrain,
    PingResult,
    SshResult,
    TrainAcStatus,
    apply_address_mapping,
    apply_global_rules_to_nodes,
    build_result_tables,
    build_car_network_trains,
    default_point_table,
    discover_ac_devices,
    discover_core_switch_candidates,
    generate_point_table_from_devices,
    get_train_sort_key,
    merge_global_config,
    node_from_mapping,
    normalize_train_network_defaults,
    sort_car_network_trains,
)
from netconsole.services.export.export_task_builders import car_network_point_table_spec
from netconsole.services.vehicle_mr_online import normalize_train_no
from netconsole.ui.car_network_diagnostic_worker import CarNetworkDiagnosticWorker
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.theme.qt_theme_engine import current_theme_mode, current_theme_tokens
from netconsole.ui.widgets.table_combo_delegate import ComboBoxItemDelegate, combo_item_value
from netconsole.ui.window_popup_service import show_non_focus_window


STATE_LABELS = {
    "ok": "正常",
    "fail": "故障",
    "unstable": "不稳定",
    "pending": "未检测",
    "running": "检测中",
    "skipped": "跳过",
    "not_applicable": "不适用",
}

POINT_TABLE_HEADER_LABELS = {
    "train_id": "列车ID",
    "train_no": "车号",
    "display_name": "显示名称",
    "tc": "TC端",
    "end": "端别",
    "node_name": "节点名称",
    "node_type": "节点类型",
    "device_id": "设备ID",
    "device_name": "设备名称",
    "device_group": "设备分组",
    "station": "归属站点",
    "primary_address": "主用地址",
    "backup_address": "备用地址",
    "ip_vehicle": "车内IP",
    "ip_uplink": "落地IP",
    "ssh_host": "SSH地址",
    "vrrp_ip": "VRRP地址",
    "address_mapping_mode": "映射模式",
    "primary_address_role": "主用地址映射",
    "backup_address_role": "备用地址映射",
    "remark": "备注",
}

MAPPING_VALUE_LABELS = {
    "vehicle_ip": "车内IP",
    "uplink_ip": "落地IP",
    "ssh_host": "SSH地址",
    "all": "全部",
    "ignore": "忽略",
    "global": "全局",
    "custom": "自定义",
}
MAPPING_LABEL_VALUES = {label: value for value, label in MAPPING_VALUE_LABELS.items()}
MAPPING_ROLE_OPTIONS = ("vehicle_ip", "uplink_ip", "ssh_host", "all", "ignore")
MAPPING_MODE_OPTIONS = ("global", "custom")
SSH_SOURCE_LABELS = {
    "primary_address": "主用地址",
    "backup_address": "备用地址",
    "ip_vehicle": "车内IP",
    "ip_uplink": "落地IP",
    "empty": "留空",
}
SSH_SOURCE_OPTIONS = ("primary_address", "backup_address", "ip_vehicle", "ip_uplink", "empty")


def _rail_communication_diag(message: str) -> None:
    print(message)
    app_logger.log_info("RAIL_COMMUNICATION_UI", message)


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


def _car_network_nodes_from_payload(payload: object) -> list[CarNetworkNode]:
    return [CarNetworkNode(**dict(row)) for row in payload or [] if isinstance(row, dict)]


def _car_network_trains_from_payload(payload: object) -> list[CarNetworkTrain]:
    trains: list[CarNetworkTrain] = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        data = dict(row)
        for key in ("tc1_device", "tc2_device"):
            value = data.get(key)
            if isinstance(value, dict):
                data[key] = Device.from_mapping(value)
        trains.append(CarNetworkTrain(**data))
    return trains


class CarNetworkDiagnosticPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.store = CarNetworkPointTableStore(paths, site_name)
        self.config_store = CarNetworkGlobalConfigStore(paths, site_name)
        self.nodes: list[CarNetworkNode] = []
        self.trains: list[CarNetworkTrain] = []
        self.current_train_id = ""
        self.node_states: dict[str, str] = {name: "pending" for name in NODE_ORDER}
        self.train_statuses: dict[str, str] = {}
        self.ping_results: dict[str, PingResult] = {}
        self.ssh_results: dict[str, SshResult] = {}
        self.ac_status = AcApStatus()
        self.ac_probe: AcProbeResult | None = None
        self.train_ac_status: TrainAcStatus | None = None
        self.last_result: CarNetworkDiagnosticResult | None = None
        self.worker: CarNetworkDiagnosticWorker | None = None
        self.background_manager = BackgroundProcessManager(self, paths=paths)
        self.background_manager.finished.connect(self._background_finished)
        self.background_manager.failed.connect(self._background_failed)
        self._background_job_context: dict[str, str] = {}
        self.car_network_point_table_window: PointTableDialog | None = None
        self.task_rows: dict[str, tuple[QTableWidget, int]] = {}
        self.log_lines: list[str] = []
        self.settings = QSettings("NetConsole", "CarNetworkDiagnostic")
        self.left_collapsed = self.settings.value("left_collapsed", False, type=bool)
        self.left_expanded_width = int(self.settings.value("left_width", 260) or 260)
        self.main_splitter: QSplitter | None = None
        self.left_panel: QWidget | None = None
        self.left_content: QWidget | None = None
        self.progress_state = "running"
        self.status_badge_state = "pending"
        self.cross_tc_status = "skipped"
        self.topology_title_labels: list[QLabel] = []
        self.topology_line_labels: list[QLabel] = []
        self._applying_theme = False
        self._last_theme_key: str | None = None
        self._last_page_stylesheet: str | None = None

        self.title_label = QLabel("车内通信检测系统")
        self.start_button = QPushButton("开始检测")
        self.start_button.setObjectName("carNetworkPrimaryButton")
        self.refresh_button = QPushButton("刷新")
        self.import_button = QPushButton("导入点表")
        self.export_button = QPushButton("导出点表")
        self.point_table_button = QPushButton("打开点表")
        self.status_label = QLabel("未检测")
        self._set_status_badge_state("pending")
        self.toggle_left_button = QPushButton("收起 «")
        self.toggle_left_button.setMinimumWidth(76)
        self.toggle_left_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(12)
        self.stage_label = QLabel("当前阶段：未检测")
        self.task_label = QLabel("当前任务：-")
        self.task_count_label = QLabel("已完成 0 / 0 项")
        self.scope_hint_label = QLabel("检测说明：本页面主检测对象为车内有线通信链路。地面到车载MR落地IP不可达属于常见现场情况，仅作为辅助状态，不直接判定车内网络故障。")
        self.scope_hint_label.setWordWrap(True)

        self.train_table = QTableWidget(0, 2)
        self.train_table.setHorizontalHeaderLabels(["列车", "状态"])
        configure_readonly_table(self.train_table)

        self.node_buttons: dict[str, QPushButton] = {}
        self.vrrp_label = QLabel("VRRP\n-")
        self.cross_tc_label = QLabel("跨TC通信：未检测")
        self.page_scroll_area: QScrollArea | None = None
        self.content_widget: QWidget | None = None
        self.topology_scroll: QScrollArea | None = None
        self.topology_wrapper: QWidget | None = None
        self.topology_canvas: QGroupBox | None = None
        self.results_container = QSplitter(Qt.Horizontal)
        self.results_container.setChildrenCollapsible(False)
        self.tc1_table = self._new_result_table("tc1")
        self.tc2_table = self._new_result_table("tc2")
        self.tc1_box = QGroupBox("TC1端 / CT车头 实时检测结果")
        self.tc2_box = QGroupBox("TC2端 / CW车尾 实时检测结果")
        self.tc1_box.setMinimumHeight(260)
        self.tc2_box.setMinimumHeight(260)
        tc1_layout = QVBoxLayout(self.tc1_box)
        tc2_layout = QVBoxLayout(self.tc2_box)
        tc1_layout.addWidget(self.tc1_table)
        tc2_layout.addWidget(self.tc2_table)

        self.json_output = QPlainTextEdit()
        self.json_output.setReadOnly(True)
        self.json_output.setMinimumHeight(120)
        self.json_output.setObjectName("carNetworkJsonOutput")
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(200)
        self.log_output.setMinimumHeight(100)
        self.log_output.setObjectName("carNetworkLogOutput")

        self._build_ui()
        self._connect_signals()
        self._apply_button_icons()
        self.refresh_all()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.set_site(site_name)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.store = CarNetworkPointTableStore(self.paths, site_name)
        self.config_store = CarNetworkGlobalConfigStore(self.paths, site_name)
        self.car_network_point_table_window = None
        self.refresh_all()

    def refresh_all(self) -> None:
        self._start_background_job(
            "car_network_refresh_all",
            {"db_path": str(self.repository.database.path), "site_name": self.site_name},
            "刷新车内通信点表",
        )

    def retranslate(self) -> None:
        self.title_label.setText("车内通信检测系统")
        self._apply_button_icons()

    def _apply_button_icons(self) -> None:
        start_icon = "CANCEL" if self.worker is not None else "PLAY"
        for button, icon_name in (
            (self.start_button, start_icon),
            (self.refresh_button, "SYNC"),
            (self.import_button, "DOWNLOAD"),
            (self.export_button, "SHARE"),
            (self.point_table_button, "FOLDER"),
            (self.toggle_left_button, "DOWN" if self.left_collapsed else "UP"),
        ):
            apply_button_icon(button, icon_name)

    def apply_theme(self, force: bool = False) -> None:
        if self._applying_theme:
            return
        tokens = current_theme_tokens()
        theme_key = current_theme_mode()
        page_stylesheet = _page_style(tokens)
        visual_refresh_only = not force and self._last_theme_key == theme_key and self._last_page_stylesheet == page_stylesheet
        self._applying_theme = True
        previous_updates_enabled = self.updatesEnabled()
        try:
            self.setUpdatesEnabled(False)
            self._apply_visual_style(tokens, page_stylesheet, update_page_stylesheet=not visual_refresh_only)
            self._last_theme_key = theme_key
            self._last_page_stylesheet = page_stylesheet
        finally:
            self.setUpdatesEnabled(previous_updates_enabled)
            self._applying_theme = False
        self.update()

    def _refresh_table_item_theme(self) -> None:
        for row in range(self.train_table.rowCount()):
            status_item = self.train_table.item(row, 1)
            if status_item is not None:
                fg, bg = _status_cell_colors(status_item.text())
                status_item.setForeground(QBrush(QColor(fg)))
                status_item.setBackground(QBrush(QColor(bg)))
        for table in (self.tc1_table, self.tc2_table):
            for row in range(table.rowCount()):
                status_item = table.item(row, 2)
                status = status_item.text() if status_item is not None else ""
                running = "检测中" in status
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item is not None:
                        _style_result_item(item, column, status, running=running)

    def _refresh_visual_states(self) -> None:
        self._refresh_topology()
        self._refresh_table_item_theme()
        self._set_progress_state(self.progress_state)
        self._set_status_badge_state(self.status_badge_state)
        self.cross_tc_label.setStyleSheet(_cross_tc_ping_style(self.cross_tc_status))

    def _set_progress_state(self, state: str) -> None:
        self.progress_state = state
        self.progress_bar.setStyleSheet(_progress_bar_style(state))

    def _set_status_badge_state(self, state: str) -> None:
        self.status_badge_state = state
        self.status_label.setStyleSheet(_badge_style(state))

    def start_diagnostic(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status_label.setText("正在取消检测...")
            self.append_log("用户请求取消检测")
            return
        train_nodes = self._current_nodes()
        train = self._current_train()
        if not train_nodes:
            MessageBox.warning(self, "车内通信检测", "当前列车没有点表数据。")
            return
        self.node_states = {node.node_name: "running" for node in train_nodes}
        self.ping_results = {}
        self.ssh_results = {}
        self.ac_status = AcApStatus()
        self.ac_probe = None
        self.train_ac_status = None
        self.last_result = None
        self._apply_cross_tc_ping({"status": "checking", "note": "跨TC通信检测中"})
        self.task_rows = {}
        self.log_lines = []
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self._set_progress_state("running")
        self.stage_label.setText("当前阶段：准备检测")
        self.task_label.setText("当前任务：读取点表")
        self.task_count_label.setText("已完成 0 / 0 项")
        self.status_label.setText("检测中")
        self._set_status_badge_state("running")
        self._refresh_topology()
        self._fill_point_rows()
        ac_devices = discover_ac_devices(self.repository)
        core_candidates = discover_core_switch_candidates(self.repository, self.site_name)
        core_devices = [device for device, candidate in core_candidates if candidate.selected]
        core_discovery = {
            "candidates": [
                {
                    "device_name": candidate.device_name,
                    "system_name": candidate.system_name,
                    "group": candidate.group,
                    "host": candidate.host,
                    "selected": candidate.selected,
                    "reason": candidate.reason,
                }
                for _device, candidate in core_candidates
            ],
            "selected_count": len(core_devices),
        }
        self.status_label.setText("正在连接无线控制器...")
        self._set_status_badge_state("running")
        self.worker = CarNetworkDiagnosticWorker(
            train_nodes,
            train,
            ac_devices,
            core_devices,
            self.paths,
            self.site_name,
            core_discovery,
            self,
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.progress_changed.connect(self.on_progress_changed)
        self.worker.stage_changed.connect(self.on_stage_changed)
        self.worker.task_started.connect(self.on_task_started)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.diagnosis_message.connect(self.on_diagnosis_message)
        self.worker.log_line.connect(self.append_log)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()

    def on_progress(self, stage: str, payload: object) -> None:
        if stage == "ping" and isinstance(payload, PingResult):
            self.ping_results[payload.ip] = payload
        elif stage == "ssh" and isinstance(payload, SshResult):
            self.ssh_results[payload.node_name or payload.host] = payload
        elif stage == "ac_probe" and isinstance(payload, tuple) and len(payload) == 2:
            probe, train_status = payload
            if isinstance(probe, AcProbeResult):
                self.ac_probe = probe
            if isinstance(train_status, TrainAcStatus):
                self.train_ac_status = train_status
            self.status_label.setText(_ac_probe_status_text(self.ac_probe, self.train_ac_status))
        elif stage == "ac" and isinstance(payload, AcApStatus):
            self.ac_status = payload
            self.status_label.setText("AC检测完成，继续执行 ping / SSH" if not self.last_result else self.status_label.text())
        elif stage == "cross_tc_ping" and isinstance(payload, dict):
            self._apply_cross_tc_ping(payload)
        self._fill_point_rows()

    def on_progress_changed(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(max(0, min(100, percent)))
        if message:
            self.task_label.setText(f"当前任务：{message}")

    def on_stage_changed(self, stage: str) -> None:
        self.stage_label.setText(f"当前阶段：{stage}")

    def on_task_started(self, payload: dict) -> None:
        self._upsert_task_row(payload, running=True)
        message = str(payload.get("message") or "")
        if message:
            self.task_label.setText(f"当前任务：{message}")
        source = str(payload.get("source") or "")
        target = str(payload.get("target") or "")
        for name in (source, target):
            if name in self.node_states:
                self.node_states[name] = "running"
        self._refresh_topology()

    def on_task_finished(self, payload: dict) -> None:
        self._upsert_task_row(payload, running=False)
        completed = payload.get("completed")
        total = payload.get("total")
        if completed is not None and total is not None:
            self.task_count_label.setText(f"已完成 {completed} / {total} 项")
        target = str(payload.get("target") or "")
        status = str(payload.get("status") or "")
        if target in self.node_states and status in {"ok", "fail", "unstable", "skipped"}:
            self.node_states[target] = status
            self._refresh_topology()

    def on_diagnosis_message(self, message: str) -> None:
        self.append_log(message)

    def append_log(self, message: str) -> None:
        if not message:
            return
        from datetime import datetime

        self.log_lines.append(f"[{datetime.now():%H:%M:%S}] {message}")
        self.log_lines = self.log_lines[-200:]
        self.log_output.setPlainText("\n".join(self.log_lines))
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def on_completed(self, result: CarNetworkDiagnosticResult) -> None:
        self.worker = None
        self.last_result = result
        self.node_states = dict(result.nodes)
        self.train_statuses[result.train_id] = _train_status_label(result)
        self.ping_results = result.ping_results
        self.ssh_results = result.ssh_results
        self.ac_status = result.ac_detail
        self.ac_probe = result.ac_probe
        self.train_ac_status = result.train_ac_status
        self._apply_cross_tc_ping(result.cross_tc_ping)
        self.status_label.setText(result.conclusion)
        self.progress_bar.setValue(100)
        self._set_progress_state("ok" if result.status == "ok" else "fail")
        self.stage_label.setText("当前阶段：检测完成")
        self.task_label.setText(f"当前任务：{result.conclusion}")
        self.append_log(f"结论：{result.conclusion}")
        self._set_status_badge_state("ok" if result.status == "ok" else "fail" if result.status == "offline" else "unstable")
        self.json_output.setPlainText(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
        self._fill_train_table()
        self._refresh_topology()
        self._fill_point_rows()
        self._update_buttons()

    def on_failed(self, message: str) -> None:
        self.worker = None
        self.status_label.setText(f"检测失败：{message}")
        self.stage_label.setText("当前阶段：检测失败")
        self.task_label.setText(f"当前任务：{message}")
        self.append_log(f"检测失败：{message}")
        self._set_status_badge_state("fail")
        self._set_progress_state("fail")
        self._update_buttons()

    def import_points(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "导入车内通信点表", "", "Point Table (*.xlsx *.csv)")
        if not path:
            return
        self.background_manager.start_job(
            BackgroundJob(
                task_type="car_network_point_table_import",
                params={
                    "path": path,
                    "site_name": self.site_name,
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                },
            )
        )

    def _background_finished(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        task_type = self._background_job_context.pop(job_id, "")
        result = dict(event.get("result") or {})
        if task_type == "car_network_refresh_all":
            self._apply_background_point_table(result)
            return
        if task_type == "car_network_generate_point_table":
            nodes = _car_network_nodes_from_payload(result.get("nodes"))
            if not nodes:
                MessageBox.information(self, "从设备管理生成", "设备管理的车载分组中没有识别到可用节点。")
                return
            self.nodes = nodes
            MessageBox.information(self, "从设备管理生成", f"已生成/刷新 {len({node.train_no for node in nodes if node.train_no})} 列车点表，已保留手工地址映射。")
            self.refresh_all()
            return
        if "count" not in result:
            return
        MessageBox.information(self, "导入车内通信点表", f"导入完成：{int(result.get('count') or 0)} 条")
        self.refresh_all()

    def _background_failed(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        self._background_job_context.pop(job_id, None)
        MessageBox.warning(self, "车内通信点表", str(event.get("message") or event.get("error") or "后台任务失败"))

    def _start_background_job(self, task_type: str, params: dict[str, object], title: str) -> str:
        params = {
            **params,
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
        }
        job_id = self.background_manager.start_job(BackgroundJob(task_type=task_type, params=params))
        self._background_job_context[job_id] = task_type
        self.status_label.setText(f"{title}中...")
        return job_id

    def _apply_background_point_table(self, result: dict[str, object]) -> None:
        self.nodes = _car_network_nodes_from_payload(result.get("nodes"))
        self.trains = _car_network_trains_from_payload(result.get("trains"))
        if self.trains and self.current_train_id not in {train.train_id for train in self.trains}:
            self.current_train_id = self.trains[0].train_id
        self._fill_train_table()
        self._refresh_topology()
        self._fill_point_rows()
        self._update_buttons()

    def export_points(self) -> None:
        default = Path.home() / "Desktop" / "车内通信点表.xlsx"
        if not default.parent.exists():
            default = Path.home() / default.name
        path, _filter = QFileDialog.getSaveFileName(self, "导出车内通信点表", str(default), "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        output_path = Path(path)
        spec = car_network_point_table_spec(output_path, site_name=self.site_name, title="导出车内通信点表", open_dir_on_success=True)
        submit_export_task(self, spec, success_title="导出车内通信点表", paths=self.paths)

    def generate_from_devices(self) -> None:
        self._start_background_job(
            "car_network_generate_point_table",
            {
                "db_path": str(self.repository.database.path),
                "site_name": self.site_name,
                "nodes": [asdict(node) for node in self.nodes],
                "save_result": True,
            },
            "从设备管理生成",
        )

    def open_point_table(self) -> None:
        if self.car_network_point_table_window is not None and self.car_network_point_table_window.isVisible():
            show_non_focus_window(self, self.car_network_point_table_window, key="car_network_point_table", activate=False, raise_window=False)
            return
        dialog = PointTableDialog(self.repository, self.site_name, self.store, self.config_store, self)
        dialog.accepted.connect(self.refresh_all)
        dialog.destroyed.connect(lambda _obj=None: setattr(self, "car_network_point_table_window", None))
        self.car_network_point_table_window = dialog
        show_non_focus_window(self, dialog, key="car_network_point_table", activate=False, raise_window=False)

    def on_train_selected(self, row: int, _column: int) -> None:
        item = self.train_table.item(row, 0)
        if item is None:
            return
        self.current_train_id = str(item.data(Qt.UserRole) or "")
        self.node_states = {name: "pending" for name in NODE_ORDER}
        self.ping_results = {}
        self.ssh_results = {}
        self.ac_status = AcApStatus()
        self.ac_probe = None
        self.train_ac_status = None
        self.last_result = None
        self._apply_cross_tc_ping({})
        self.status_label.setText("未检测")
        self._set_status_badge_state("pending")
        self.json_output.clear()
        self._refresh_topology()
        self._fill_point_rows()

    def show_node_detail(self, node_name: str) -> None:
        node = next((item for item in self._current_nodes() if item.node_name == node_name), None)
        if node is None:
            return
        ping_lines = []
        for ip in node.ping_ips:
            result = self.ping_results.get(ip)
            if result is None:
                ping_lines.append(f"{ip}: 未检测")
                continue
            rtt = "-" if result.avg_rtt_ms is None else f"{result.avg_rtt_ms} ms"
            ping_lines.append(f"{result.ip}: {_ping_status_label(result)}, RTT {rtt}, loss {result.loss_percent}%")
        ssh = self.ssh_results.get(node.node_name)
        ssh_text = "成功" if ssh and ssh.ok else (ssh.error if ssh else "未检测")
        message = "\n".join(
            [
                f"节点：{node.node_name}",
                f"类型：{node.node_type}",
                f"端别：{node.tc}/{node.end}",
                f"设备管理名称：{node.device_name or '-'}",
                f"Device ID：{node.device_id or '-'}",
                f"SSH主机：{node.ssh_host or node.ip_uplink or node.ip_vehicle or '-'}",
                f"车内IP：{node.ip_vehicle or '-'}",
                f"落地IP：{node.ip_uplink or '-'}",
                f"VRRP：{node.vrrp_ip or '-'}",
                f"状态：{STATE_LABELS.get(self.node_states.get(node.node_name, 'pending'), '-')}",
                f"Ping：{'; '.join(ping_lines) if ping_lines else '不适用'}",
                f"SSH：{ssh_text if node.is_mr else '不适用'}",
                f"AC：{'在线证据存在' if self.ac_status.online else self.ac_status.error or '未检测'}",
                f"诊断说明：{self.last_result.conclusion if self.last_result else '-'}",
            ]
        )
        MessageBox.information(self, node.node_name, message)

    def _build_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        self.page_scroll_area = QScrollArea()
        self.page_scroll_area.setObjectName("carNetworkPageScroll")
        self.page_scroll_area.setWidgetResizable(True)
        self.page_scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.page_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_widget = QWidget()
        root = QVBoxLayout(self.content_widget)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(self.title_label)

        controls = QHBoxLayout()
        for button in (self.start_button, self.refresh_button, self.import_button, self.export_button, self.point_table_button):
            controls.addWidget(button)
        controls.addStretch(1)
        controls.addWidget(QLabel("状态："))
        controls.addWidget(self.status_label)
        root.addLayout(controls)
        root.addWidget(self.scope_hint_label)

        progress_box = QGroupBox("检测进度")
        progress_layout = QGridLayout(progress_box)
        progress_layout.addWidget(QLabel("检测进度："), 0, 0)
        progress_layout.addWidget(self.progress_bar, 0, 1, 1, 3)
        progress_layout.addWidget(self.task_count_label, 0, 4)
        progress_layout.addWidget(self.stage_label, 1, 0, 1, 2)
        progress_layout.addWidget(self.task_label, 1, 2, 1, 3)
        root.addWidget(progress_box)

        splitter = QSplitter(Qt.Horizontal)
        self.main_splitter = splitter
        left = QWidget()
        self.left_panel = left
        left.setMinimumWidth(180)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.toggle_left_button)
        self.left_content = QWidget()
        left_content_layout = QVBoxLayout(self.left_content)
        left_content_layout.setContentsMargins(0, 0, 0, 0)
        left_content_layout.addWidget(QLabel("列车列表"))
        left_content_layout.addWidget(self.train_table, 1)
        left_layout.addWidget(self.left_content, 1)
        splitter.addWidget(left)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        topology_canvas = QGroupBox("固定拓扑")
        self.topology_canvas = topology_canvas
        topology_canvas.setMinimumSize(1050, 620)
        topology_canvas.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        topo_layout = QGridLayout(topology_canvas)
        self._build_topology(topo_layout)
        topology_scroll = QScrollArea()
        self.topology_scroll = topology_scroll
        topology_scroll.setObjectName("carNetworkTopologyScroll")
        topology_scroll.setWidgetResizable(True)
        topology_scroll.setFrameShape(QScrollArea.NoFrame)
        topology_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        topology_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        topology_scroll.setMinimumHeight(650)
        topology_wrapper = QWidget()
        self.topology_wrapper = topology_wrapper
        topology_wrapper.setMinimumSize(topology_canvas.minimumSize())
        wrapper_layout = QHBoxLayout(topology_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addStretch(1)
        wrapper_layout.addWidget(topology_canvas, 0, Qt.AlignHCenter | Qt.AlignTop)
        wrapper_layout.addStretch(1)
        topology_scroll.setWidget(topology_wrapper)

        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)
        self._arrange_result_tables()
        result_layout.addWidget(self.results_container)
        result_layout.addWidget(QLabel("检测日志"))
        result_layout.addWidget(self.log_output)
        result_layout.addWidget(QLabel("诊断输出 JSON"))
        result_layout.addWidget(self.json_output)
        result_panel.setMinimumHeight(500)

        right_layout.addWidget(topology_scroll)
        right_layout.addWidget(result_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([max(220, min(260, self.left_expanded_width)), 1050])
        self._apply_left_panel_state()
        splitter.splitterMoved.connect(self._save_left_width)
        root.addWidget(splitter)
        self.page_scroll_area.setWidget(self.content_widget)
        page_layout.addWidget(self.page_scroll_area)
        self._sync_topology_wrapper_size()
        self.apply_theme(force=True)

    def _apply_visual_style(self, tokens: dict[str, str], page_stylesheet: str, *, update_page_stylesheet: bool) -> None:
        if update_page_stylesheet:
            self.setStyleSheet(page_stylesheet)
        self.title_label.setStyleSheet(f"color: {tokens['text_primary']}; font-size: 18px; font-weight: 700;")
        self.stage_label.setStyleSheet(f"color: {tokens['text_primary']}; font-size: 12px; font-weight: 600;")
        self.task_label.setStyleSheet(f"color: {tokens['text_secondary']}; font-size: 12px;")
        self.task_count_label.setStyleSheet(f"color: {tokens['text_secondary']}; font-size: 12px; font-weight: 600;")
        self.scope_hint_label.setStyleSheet(f"color: {tokens['text_secondary']}; font-size: 12px; padding: 4px 2px;")
        self.log_output.setStyleSheet(_plain_text_style("carNetworkLogOutput", tokens))
        self.json_output.setStyleSheet(_plain_text_style("carNetworkJsonOutput", tokens))
        for table in (self.train_table, self.tc1_table, self.tc2_table):
            table.setStyleSheet(_result_table_style(tokens))
            table.viewport().update()
        for label in self.topology_title_labels:
            label.setStyleSheet(f"color: {tokens['text_primary']}; font-size: 13px; font-weight: 700;")
        for label in self.topology_line_labels:
            font_size = 28 if label.text() == "|" else 14
            label.setStyleSheet(f"color: {tokens['primary']}; font-size: {font_size}px; font-weight: 800;")
        self.vrrp_label.setStyleSheet(f"color: {tokens['primary']}; font-size: 13px; font-weight: 800;")
        self._refresh_visual_states()

    def toggle_left_panel(self) -> None:
        if not self.left_collapsed and self.main_splitter is not None:
            sizes = self.main_splitter.sizes()
            if sizes and sizes[0] > 60:
                self.left_expanded_width = sizes[0]
        self.left_collapsed = not self.left_collapsed
        self.settings.setValue("left_collapsed", self.left_collapsed)
        self.settings.setValue("left_width", self.left_expanded_width)
        self._apply_left_panel_state()

    def _apply_left_panel_state(self) -> None:
        if self.left_content is not None:
            self.left_content.setVisible(not self.left_collapsed)
        self.toggle_left_button.setText("列车列表 »" if self.left_collapsed else "收起 «")
        self._apply_button_icons()
        self.toggle_left_button.setMinimumWidth(34 if self.left_collapsed else 76)
        if self.left_panel is not None:
            self.left_panel.setMinimumWidth(34 if self.left_collapsed else 220)
        if self.main_splitter is not None:
            left_width = 34 if self.left_collapsed else max(220, min(320, self.left_expanded_width))
            self.main_splitter.setSizes([left_width, max(900, self.width() - left_width)])

    def _save_left_width(self, _pos: int, _index: int) -> None:
        if self.left_collapsed or self.main_splitter is None:
            return
        sizes = self.main_splitter.sizes()
        if sizes and sizes[0] > 60:
            self.left_expanded_width = sizes[0]
            self.settings.setValue("left_width", self.left_expanded_width)

    def _build_topology(self, layout: QGridLayout) -> None:
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(10)
        tc1_title = QLabel("TC1端 / CT车头")
        tc2_title = QLabel("TC2端 / CW车尾")
        self.topology_title_labels.extend((tc1_title, tc2_title))
        layout.addWidget(tc1_title, 0, 0, 1, 3, Qt.AlignCenter)
        layout.addWidget(tc2_title, 0, 4, 1, 3, Qt.AlignCenter)
        positions = {
            "TC1-MR": (1, 1),
            "TC1-SW": (3, 1),
            "TC1-SRV": (5, 1),
            "TC2-MR": (1, 5),
            "TC2-SW": (3, 5),
            "TC2-SRV": (5, 5),
        }
        for name, (row, column) in positions.items():
            button = QPushButton(name)
            button.setObjectName("carNetworkTopologyNode")
            button.setMinimumSize(128, 58)
            button.setMaximumSize(128, 58)
            button.clicked.connect(lambda _checked=False, value=name: self.show_node_detail(value))
            self.node_buttons[name] = button
            layout.addWidget(button, row, column)
        for row, column in ((2, 1), (4, 1), (2, 5), (4, 5)):
            line = QLabel("|")
            line.setAlignment(Qt.AlignCenter)
            self.topology_line_labels.append(line)
            layout.addWidget(line, row, column)
        left_line = QLabel("----------")
        right_line = QLabel("----------")
        for label in (left_line, right_line):
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(130)
            self.topology_line_labels.append(label)
        self.vrrp_label.setAlignment(Qt.AlignCenter)
        self.vrrp_label.setMinimumWidth(160)
        layout.addWidget(left_line, 3, 2)
        layout.addWidget(self.vrrp_label, 3, 3)
        layout.addWidget(right_line, 3, 4)
        self.cross_tc_label.setAlignment(Qt.AlignCenter)
        self.cross_tc_label.setMinimumHeight(28)
        self.cross_tc_label.setMinimumWidth(360)
        layout.addWidget(self.cross_tc_label, 4, 2, 1, 3)
        for column, width in enumerate((80, 140, 130, 170, 130, 140, 80)):
            layout.setColumnMinimumWidth(column, width)
        for row in range(6):
            layout.setRowMinimumHeight(row, 62 if row in {1, 3, 5} else 34)

    def _connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start_diagnostic)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.import_button.clicked.connect(self.import_points)
        self.export_button.clicked.connect(self.export_points)
        self.point_table_button.clicked.connect(self.open_point_table)
        self.toggle_left_button.clicked.connect(self.toggle_left_panel)
        self.train_table.cellClicked.connect(self.on_train_selected)

    def _fill_train_table(self) -> None:
        self.train_table.setRowCount(0)
        for train in self._sorted_trains(self.trains):
            row = self.train_table.rowCount()
            self.train_table.insertRow(row)
            tc1 = train.tc1_device.name if train.tc1_device else "-"
            tc2 = train.tc2_device.name if train.tc2_device else "-"
            values = [train.display_name, self.train_statuses.get(train.train_id, "未检测")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(f"TC1/CT: {tc1}\nTC2/CW: {tc2}")
                if column == 0:
                    item.setData(Qt.UserRole, train.train_id)
                if column == 1:
                    fg, bg = _status_cell_colors(str(value))
                    item.setForeground(QBrush(QColor(fg)))
                    item.setBackground(QBrush(QColor(bg)))
                self.train_table.setItem(row, column, item)
            if train.train_id == self.current_train_id:
                self.train_table.selectRow(row)
        for column, width in enumerate((100, 90)):
            self.train_table.setColumnWidth(column, width)

    def _refresh_topology(self) -> None:
        nodes = {node.node_name: node for node in self._current_nodes()}
        for name, button in self.node_buttons.items():
            state = self.node_states.get(name, "pending")
            node = nodes.get(name)
            ip = _node_ip_summary(node)
            button.setText(f"{_state_dot(state)}\n{name}\n{ip}")
            button.setStyleSheet(_node_style(state))
        vrrp = next((node.vrrp_ip for node in nodes.values() if node.vrrp_ip), "")
        self.vrrp_label.setText(f"VRRP\n{vrrp or '-'}")
        if self.worker is not None and not (self.last_result and self.last_result.cross_tc_ping):
            self._apply_cross_tc_ping({"status": "checking", "note": "跨TC通信检测中"})

    def _apply_cross_tc_ping(self, payload: dict[str, object]) -> None:
        status = str(payload.get("status") or "skipped")
        self.cross_tc_status = status
        text = _cross_tc_ping_label(payload)
        self.cross_tc_label.setText(text)
        self.cross_tc_label.setStyleSheet(_cross_tc_ping_style(status))
        tooltip = _cross_tc_ping_tooltip(payload)
        self.cross_tc_label.setToolTip(tooltip)

    def _fill_point_rows(self) -> None:
        if self.last_result and self.last_result.tables:
            self._fill_table(self.tc1_table, self.last_result.tables.get("TC1", []))
            self._fill_table(self.tc2_table, self.last_result.tables.get("TC2", []))
            return
        rows = build_result_tables(self._current_nodes(), {}, self.ssh_results, self.ac_status, {}, [], self.train_ac_status)
        self._fill_table(self.tc1_table, rows.get("TC1", []))
        self._fill_table(self.tc2_table, rows.get("TC2", []))

    def _new_result_table(self, key: str) -> QTableWidget:
        table = QTableWidget(0, 6)
        table.setObjectName(f"car_network_{key}_result_table")
        table.setMinimumHeight(220)
        table.setHorizontalHeaderLabels(["节点/IP", "层级", "状态", "RTT", "丢包", "说明"])
        configure_readonly_table(table)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.ElideRight)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setAlternatingRowColors(True)
        table.setShowGrid(True)
        table.verticalHeader().setDefaultSectionSize(38)
        table.verticalHeader().setMinimumSectionSize(36)
        table.horizontalHeader().setFixedHeight(36)
        table.setStyleSheet(_result_table_style())
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self._restore_result_table_widths(table, key)
        header.sectionResized.connect(lambda _index, _old, _new, table=table, key=key: self._save_result_table_widths(table, key))
        return table

    def _fill_table(self, table: QTableWidget, rows: list[dict[str, object]]) -> None:
        table.setRowCount(0)
        if table is self.tc1_table or table is self.tc2_table:
            self.task_rows = {task_id: (task_table, row) for task_id, (task_table, row) in self.task_rows.items() if task_table is not table}
        for data in rows:
            values = [data.get("node", ""), data.get("layer", ""), data.get("status", ""), data.get("rtt", ""), data.get("loss", ""), data.get("note", "")]
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter if column in {1, 2, 3, 4} else Qt.AlignVCenter | Qt.AlignLeft)
                item.setToolTip(str(value))
                _style_result_item(item, column, str(data.get("status", "")))
                table.setItem(row, column, item)
            table.setRowHeight(row, 38)

    def _upsert_task_row(self, payload: dict, *, running: bool) -> None:
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            return
        table = self._task_table(payload)
        row = self.task_rows.get(task_id, (table, -1))[1]
        if row < 0 or row >= table.rowCount():
            row = table.rowCount()
            table.insertRow(row)
            self.task_rows[task_id] = (table, row)
        source = str(payload.get("source") or "")
        target = str(payload.get("target") or "")
        target_ip = str(payload.get("target_ip") or "")
        node_text = f"{source} -> {target} / {target_ip}" if source and target else target or source or target_ip
        rtt = "-" if payload.get("avg_rtt") in {None, ""} else f"{payload.get('avg_rtt')} ms"
        loss = "-" if payload.get("loss") in {None, ""} else f"{payload.get('loss')}%"
        values = [
            node_text,
            str(payload.get("layer") or ""),
            "检测中" if running else _task_status_label(str(payload.get("status") or "")),
            rtt,
            loss,
            str(payload.get("message") or ""),
        ]
        for column, value in enumerate(values):
            item = table.item(row, column) or QTableWidgetItem()
            item.setText(value)
            item.setTextAlignment(Qt.AlignCenter if column in {1, 2, 3, 4} else Qt.AlignVCenter | Qt.AlignLeft)
            item.setToolTip(value)
            _style_result_item(item, column, str(values[2]), running=running)
            table.setItem(row, column, item)
        table.setRowHeight(row, 38)

    def _task_table(self, payload: dict) -> QTableWidget:
        text = " ".join(str(payload.get(key) or "") for key in ("source", "target", "task_id"))
        return self.tc2_table if "TC2" in text else self.tc1_table

    def _restore_result_table_widths(self, table: QTableWidget, key: str) -> None:
        defaults = [260, 150, 90, 90, 90, 420]
        stored = self.settings.value(f"{key}_result_widths", "")
        widths = defaults
        if isinstance(stored, str) and stored:
            try:
                parsed = [int(value) for value in stored.split(",")]
                if len(parsed) == table.columnCount():
                    widths = parsed
            except ValueError:
                widths = defaults
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)

    def _save_result_table_widths(self, table: QTableWidget, key: str) -> None:
        widths = [str(table.columnWidth(column)) for column in range(table.columnCount())]
        self.settings.setValue(f"{key}_result_widths", ",".join(widths))

    def _arrange_result_tables(self) -> None:
        horizontal = self.width() >= 1500
        orientation = Qt.Horizontal if horizontal else Qt.Vertical
        if self.results_container.orientation() != orientation:
            self.results_container.setOrientation(orientation)
        if self.results_container.count() == 0:
            self.results_container.addWidget(self.tc1_box)
            self.results_container.addWidget(self.tc2_box)
            self.results_container.setStretchFactor(0, 1)
            self.results_container.setStretchFactor(1, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        horizontal = self.width() >= 1500
        current_horizontal = self.results_container.orientation() == Qt.Horizontal
        if horizontal != current_horizontal:
            self._arrange_result_tables()
        self._sync_topology_wrapper_size()

    def _sync_topology_wrapper_size(self) -> None:
        if self.topology_scroll is None or self.topology_wrapper is None or self.topology_canvas is None:
            return
        viewport = self.topology_scroll.viewport()
        self.topology_wrapper.setMinimumWidth(max(viewport.width(), self.topology_canvas.minimumWidth()))
        self.topology_wrapper.setMinimumHeight(max(viewport.height(), self.topology_canvas.minimumHeight()))

    def on_enter(self) -> None:
        self._sync_topology_wrapper_size()
        self._arrange_result_tables()
        canvas_size = self.topology_canvas.minimumSize() if self.topology_canvas is not None else self.minimumSize()
        _rail_communication_diag("[Rail][Communication] page enter")
        _rail_communication_diag(f"[Rail][Communication] topology canvas: {canvas_size.width()}x{canvas_size.height()}")
        _rail_communication_diag("[Rail][Communication] scroll area enabled: yes")
        visible = not any(widget.isHidden() for widget in (self.tc1_box, self.tc2_box, self.log_output, self.json_output))
        _rail_communication_diag(f"[Rail][Communication] result panels visible: {'yes' if visible else 'no'}")

    def _current_train(self) -> CarNetworkTrain | None:
        return next((train for train in self.trains if train.train_id == self.current_train_id), None)

    def _current_nodes(self) -> list[CarNetworkNode]:
        train = self._current_train()
        if train is None:
            return []
        by_name = {node.node_name: node for node in self.nodes if node.train_id == train.train_id or node.train_no == train.train_no}
        return [by_name[name] for name in NODE_ORDER if name in by_name]

    def _view_nodes(self, stored_nodes: list[CarNetworkNode]) -> list[CarNetworkNode]:
        return sorted(stored_nodes, key=lambda node: (get_train_sort_key(node), NODE_ORDER.index(node.node_name) if node.node_name in NODE_ORDER else 99, node.node_name))

    def _fallback_trains_from_nodes(self, nodes: list[CarNetworkNode]) -> list[CarNetworkTrain]:
        trains: list[CarNetworkTrain] = []
        seen: set[str] = set()
        for node in nodes:
            key = node.train_id or node.train_no
            if not key or key in seen:
                continue
            seen.add(key)
            train_no = node.train_no or normalize_train_no(node.train_id)
            trains.append(CarNetworkTrain(node.train_id or f"列车{train_no}", train_no, f"{train_no}车" if train_no else node.train_id))
        return self._sorted_trains(trains)

    @staticmethod
    def _sorted_trains(trains: list[CarNetworkTrain]) -> list[CarNetworkTrain]:
        return sort_car_network_trains(trains)

    def _update_buttons(self) -> None:
        running = self.worker is not None
        self.start_button.setEnabled(True)
        self.start_button.setText("取消检测" if running else "开始检测")
        self._apply_button_icons()
        self.start_button.setProperty("danger", running)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        self.refresh_button.setEnabled(not running)
        self.import_button.setEnabled(not running)
        self.export_button.setEnabled(not running)
        self.point_table_button.setEnabled(not running)


class PointTableDialog(QDialog):
    def __init__(self, repository: DeviceRepository, site_name: str, store: CarNetworkPointTableStore, config_store: CarNetworkGlobalConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.store = store
        self.config_store = config_store
        self.background_manager = BackgroundProcessManager(self, paths=store.paths)
        self.background_manager.finished.connect(self._background_finished)
        self.background_manager.failed.connect(self._background_failed)
        self._background_job_context: dict[str, str] = {}
        self.global_config = merge_global_config(DEFAULT_GLOBAL_CONFIG)
        self.nodes: list[CarNetworkNode] = []
        self.setWindowTitle("车内通信点表")
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.resize(1280, 760)
        self.setMinimumSize(900, 600)

        self.train_filter = NoWheelComboBox()
        self.node_type_filter = NoWheelComboBox()
        self.global_mapping_combos: dict[tuple[str, str], QComboBox] = {}
        self.locked = bool(self.global_config.get("point_table_locked", False))
        self.lock_button = QPushButton()
        self.lock_hint_label = QLabel()
        self.srv_enabled_check = QCheckBox("启用自动SRV生成")
        self.tc1_srv_host_spin = NoWheelSpinBox()
        self.tc2_srv_host_spin = NoWheelSpinBox()
        self.vrrp_host_spin = NoWheelSpinBox()
        self.table = QTableWidget(0, len(POINT_TABLE_FIELDS))
        self.table.setHorizontalHeaderLabels([POINT_TABLE_HEADER_LABELS.get(field, field) for field in POINT_TABLE_FIELDS])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.horizontalHeader().setFixedHeight(36)
        for field, values in (
            ("primary_address_role", MAPPING_ROLE_OPTIONS),
            ("backup_address_role", MAPPING_ROLE_OPTIONS),
            ("address_mapping_mode", MAPPING_MODE_OPTIONS),
        ):
            options = [(MAPPING_VALUE_LABELS[value], value) for value in values]
            self.table.setItemDelegateForColumn(
                POINT_TABLE_FIELDS.index(field),
                ComboBoxItemDelegate(options, self.table),
            )

        self.add_button = QPushButton("新增行")
        self.delete_button = QPushButton("删除行")
        self.apply_mapping_button = QPushButton("地址映射并应用")
        self.generate_button = QPushButton("从设备管理生成")
        self.save_global_button = QPushButton("保存全局规则")
        self.apply_global_button = QPushButton("应用全局规则")
        self.apply_global_override_button = QPushButton("应用全局规则并覆盖自定义行")
        self.restore_global_button = QPushButton("恢复默认映射")
        self.import_button = QPushButton("导入")
        self.export_button = QPushButton("导出")
        self.save_button = QPushButton("保存")
        self.cancel_button = QPushButton("取消")

        layout = QVBoxLayout(self)
        config_content = QWidget(self)
        config_layout = QVBoxLayout(config_content)
        config_layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("列车"))
        filters.addWidget(self.train_filter)
        filters.addWidget(QLabel("节点类型"))
        filters.addWidget(self.node_type_filter)
        filters.addStretch(1)
        filters.addWidget(self.lock_hint_label)
        filters.addWidget(self.lock_button)
        config_layout.addLayout(filters)
        config_layout.addWidget(self._build_global_rules_box())
        config_scroll = QScrollArea(self)
        config_scroll.setWidgetResizable(True)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        config_scroll.setFrameShape(QScrollArea.NoFrame)
        config_scroll.setMaximumHeight(300)
        config_scroll.setWidget(config_content)
        layout.addWidget(config_scroll, 0)
        layout.addWidget(self.table, 1)
        buttons = QGridLayout()
        action_buttons = (
            self.add_button,
            self.delete_button,
            self.apply_mapping_button,
            self.generate_button,
            self.save_global_button,
            self.apply_global_button,
            self.apply_global_override_button,
            self.restore_global_button,
            self.import_button,
            self.export_button,
            self.save_button,
            self.cancel_button,
        )
        for index, button in enumerate(action_buttons):
            button.setMinimumHeight(32)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            buttons.addWidget(button, index // 4, index % 4)
        buttons.setColumnStretch(3, 1)
        layout.addLayout(buttons)

        self.train_filter.currentIndexChanged.connect(self._apply_filter)
        self.node_type_filter.currentIndexChanged.connect(self._apply_filter)
        self.table.itemChanged.connect(self._point_table_item_changed)
        self.lock_button.clicked.connect(self._toggle_locked)
        self.add_button.clicked.connect(self._add_row)
        self.delete_button.clicked.connect(self._delete_rows)
        self.apply_mapping_button.clicked.connect(self._apply_mapping)
        self.generate_button.clicked.connect(self._generate)
        self.save_global_button.clicked.connect(self._save_global_rules)
        self.apply_global_button.clicked.connect(lambda: self._apply_global_rules(False))
        self.apply_global_override_button.clicked.connect(lambda: self._apply_global_rules(True))
        self.restore_global_button.clicked.connect(self._restore_global_rules)
        self.import_button.clicked.connect(self._import)
        self.export_button.clicked.connect(self._export)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)

        self._reload_filters()
        self._load_global_rule_widgets()
        self._fill_table()
        self._update_lock_state()
        self.lock_hint_label.setText("正在加载点表...")
        self._start_background_job("car_network_point_table_load", {"site_name": self.site_name})

    def _build_global_rules_box(self) -> QGroupBox:
        box = QGroupBox("全局规则")
        layout = QGridLayout(box)
        headers = ["节点类型", "主用地址映射", "备用地址映射", "SSH来源"]
        for column, text in enumerate(headers):
            layout.addWidget(QLabel(text), 0, column)
        for row, node_type in enumerate(("MR", "3SW", "SRV"), start=1):
            layout.addWidget(QLabel(node_type), row, 0)
            for column, key in enumerate(("primary_address_role", "backup_address_role"), start=1):
                combo = NoWheelComboBox()
                combo.setMinimumHeight(30)
                combo.setToolTip(
                    "主用地址映射 = 全部：将主用地址同时作为车内IP、落地IP和SSH地址。"
                    if key == "primary_address_role"
                    else "备用地址映射 = 全部：将备用地址同时作为车内IP、落地IP和SSH地址，一般仅用于特殊站点。"
                )
                for value in MAPPING_ROLE_OPTIONS:
                    combo.addItem(MAPPING_VALUE_LABELS[value], value)
                self.global_mapping_combos[(node_type, key)] = combo
                layout.addWidget(combo, row, column)
            ssh_combo = NoWheelComboBox()
            ssh_combo.setMinimumHeight(30)
            for value in SSH_SOURCE_OPTIONS:
                ssh_combo.addItem(SSH_SOURCE_LABELS[value], value)
            self.global_mapping_combos[(node_type, "ssh_source")] = ssh_combo
            layout.addWidget(ssh_combo, row, 3)

        for spin in (self.tc1_srv_host_spin, self.tc2_srv_host_spin, self.vrrp_host_spin):
            spin.setRange(1, 254)
            spin.setMinimumHeight(30)
        self.srv_enabled_check.setMinimumHeight(30)
        layout.addWidget(self.srv_enabled_check, 1, 4)
        layout.addWidget(QLabel("TC1-SRV主机位"), 2, 4)
        layout.addWidget(self.tc1_srv_host_spin, 2, 5)
        layout.addWidget(QLabel("TC2-SRV主机位"), 3, 4)
        layout.addWidget(self.tc2_srv_host_spin, 3, 5)
        layout.addWidget(QLabel("VRRP主机位"), 1, 5)
        layout.addWidget(self.vrrp_host_spin, 1, 6)
        layout.setColumnStretch(7, 1)
        return box

    def _load_global_rule_widgets(self) -> None:
        mapping = self.global_config.get("address_mapping")
        srv = self.global_config.get("srv_generation")
        mapping = mapping if isinstance(mapping, dict) else {}
        srv = srv if isinstance(srv, dict) else {}
        for node_type in ("MR", "3SW", "SRV"):
            rule = mapping.get(node_type)
            rule = rule if isinstance(rule, dict) else {}
            for key in ("primary_address_role", "backup_address_role", "ssh_source"):
                combo = self.global_mapping_combos[(node_type, key)]
                combo.setCurrentIndex(max(0, combo.findData(str(rule.get(key) or ""))))
        self.srv_enabled_check.setChecked(bool(srv.get("enabled", True)))
        self.tc1_srv_host_spin.setValue(int(srv.get("tc1_host", 1) or 1))
        self.tc2_srv_host_spin.setValue(int(srv.get("tc2_host", 2) or 2))
        self.vrrp_host_spin.setValue(int(srv.get("vrrp_host", 254) or 254))

    def _read_global_rule_widgets(self) -> dict[str, object]:
        config = merge_global_config(self.global_config)
        mapping = config["address_mapping"]
        assert isinstance(mapping, dict)
        for node_type in ("MR", "3SW", "SRV"):
            rule = mapping.setdefault(node_type, {})
            assert isinstance(rule, dict)
            for key in ("primary_address_role", "backup_address_role", "ssh_source"):
                rule[key] = self.global_mapping_combos[(node_type, key)].currentData() or ""
        config["srv_generation"] = {
            "enabled": self.srv_enabled_check.isChecked(),
            "tc1_host": self.tc1_srv_host_spin.value(),
            "tc2_host": self.tc2_srv_host_spin.value(),
            "vrrp_host": self.vrrp_host_spin.value(),
            "mode": "same_vehicle_subnet",
        }
        config["point_table_locked"] = self.locked
        return config

    def _toggle_locked(self) -> None:
        self.locked = not self.locked
        self.global_config = self._read_global_rule_widgets()
        self._update_lock_state()
        self._start_background_job(
            "car_network_save_point_table",
            {
                "site_name": self.site_name,
                "nodes": [asdict(node) for node in self._rows_to_nodes()],
                "global_config": self.global_config,
                "overwrite_custom": False,
            },
            context="car_network_save_lock_state",
        )

    def _update_lock_state(self) -> None:
        self.lock_button.setText("解锁编辑" if self.locked else "锁定编辑")
        self.lock_hint_label.setText("当前点表已锁定，禁止编辑。" if self.locked else "")
        editable_buttons = (
            self.add_button,
            self.delete_button,
            self.apply_mapping_button,
            self.generate_button,
            self.save_global_button,
            self.apply_global_button,
            self.apply_global_override_button,
            self.restore_global_button,
            self.import_button,
            self.save_button,
        )
        for button in editable_buttons:
            button.setEnabled(not self.locked)
        self.export_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.srv_enabled_check.setEnabled(not self.locked)
        for spin in (self.tc1_srv_host_spin, self.tc2_srv_host_spin, self.vrrp_host_spin):
            spin.setEnabled(not self.locked)
        for combo in self.global_mapping_combos.values():
            combo.setEnabled(not self.locked)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers if self.locked else QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)

    def _guard_locked(self, action: str) -> bool:
        if not self.locked:
            return False
        MessageBox.information(self, "车内通信点表", f"当前点表已锁定，不能{action}。")
        return True

    def _reload_filters(self) -> None:
        self.train_filter.blockSignals(True)
        self.node_type_filter.blockSignals(True)
        self.train_filter.clear()
        self.node_type_filter.clear()
        self.train_filter.addItem("全部", "")
        self.node_type_filter.addItem("全部", "")
        for train_no in sorted({node.train_no for node in self.nodes if node.train_no}, key=get_train_sort_key):
            self.train_filter.addItem(train_no, train_no)
        for node_type in sorted({node.node_type for node in self.nodes if node.node_type}):
            self.node_type_filter.addItem(node_type, node_type)
        self.train_filter.blockSignals(False)
        self.node_type_filter.blockSignals(False)

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(0)
        combo_options = {
            "primary_address_role": MAPPING_ROLE_OPTIONS,
            "backup_address_role": MAPPING_ROLE_OPTIONS,
            "address_mapping_mode": MAPPING_MODE_OPTIONS,
        }
        try:
            for node in sorted(self.nodes, key=lambda item: (get_train_sort_key(item), NODE_ORDER.index(item.node_name) if item.node_name in NODE_ORDER else 99, item.node_name)):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setRowHeight(row, 38)
                values = {field: str(getattr(node, field)) for field in POINT_TABLE_FIELDS}
                values["address_mapping_mode"] = "custom" if values["address_mapping_mode"] in {"custom", "manual"} else "global"
                for column, field in enumerate(POINT_TABLE_FIELDS):
                    if field in combo_options:
                        value = values[field]
                        item = QTableWidgetItem(MAPPING_VALUE_LABELS.get(value, value))
                        item.setData(Qt.UserRole, value)
                        if field == "primary_address_role":
                            item.setToolTip("主用地址映射 = 全部：将主用地址同时作为车内IP、落地IP和SSH地址。")
                        elif field == "backup_address_role":
                            item.setToolTip("备用地址映射 = 全部：将备用地址同时作为车内IP、落地IP和SSH地址，一般仅用于特殊站点。")
                        self.table.setItem(row, column, item)
                    else:
                        item = QTableWidgetItem(values[field])
                        item.setToolTip(values[field])
                        self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)
        self._apply_filter()
        for column, field in enumerate(POINT_TABLE_FIELDS):
            self.table.setColumnWidth(column, _point_table_column_width(field))
        self._update_lock_state()

    def _rows_to_nodes(self) -> list[CarNetworkNode]:
        nodes: list[CarNetworkNode] = []
        for row in range(self.table.rowCount()):
            data: dict[str, object] = {}
            for column, field in enumerate(POINT_TABLE_FIELDS):
                item = self.table.item(row, column)
                data[field] = combo_item_value(item) if field in {"primary_address_role", "backup_address_role", "address_mapping_mode"} else item.text() if item is not None else ""
            nodes.append(node_from_mapping(data))
        return nodes

    def _point_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() in {
            POINT_TABLE_FIELDS.index("primary_address_role"),
            POINT_TABLE_FIELDS.index("backup_address_role"),
        }:
            self._mark_row_custom(item.row())

    def _mark_row_custom(self, row: int) -> None:
        mode_column = POINT_TABLE_FIELDS.index("address_mapping_mode")
        item = self.table.item(row, mode_column)
        if item is None or combo_item_value(item) == "custom":
            return
        blocked = self.table.blockSignals(True)
        item.setText(MAPPING_VALUE_LABELS["custom"])
        item.setData(Qt.UserRole, "custom")
        self.table.blockSignals(blocked)

    def _apply_filter(self) -> None:
        train_no = str(self.train_filter.currentData() or "")
        node_type = str(self.node_type_filter.currentData() or "")
        train_col = POINT_TABLE_FIELDS.index("train_no")
        type_col = POINT_TABLE_FIELDS.index("node_type")
        for row in range(self.table.rowCount()):
            row_train = self.table.item(row, train_col).text() if self.table.item(row, train_col) else ""
            row_type = self.table.item(row, type_col).text() if self.table.item(row, type_col) else ""
            hidden = bool(train_no and row_train != train_no) or bool(node_type and row_type != node_type)
            self.table.setRowHidden(row, hidden)

    def _add_row(self) -> None:
        if self._guard_locked("新增行"):
            return
        self.nodes = self._rows_to_nodes()
        self.nodes.append(CarNetworkNode(train_id="", node_name="TC1-MR", node_type="MR", tc="TC1", end="CT"))
        self._reload_filters()
        self._fill_table()

    def _delete_rows(self) -> None:
        if self._guard_locked("删除行"):
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        self.nodes = [node for index, node in enumerate(self._rows_to_nodes()) if index not in set(rows)]
        self._reload_filters()
        self._fill_table()

    def _apply_mapping(self) -> None:
        if self._guard_locked("应用地址映射"):
            return
        self.global_config = self._read_global_rule_widgets()
        self.nodes = [
            apply_address_mapping(node, self.global_config, overwrite=node.address_mapping_mode == "global")
            for node in self._rows_to_nodes()
        ]
        self.nodes = normalize_train_network_defaults(self.nodes, self.global_config, overwrite_custom=False)
        self._reload_filters()
        self._fill_table()

    def _generate(self) -> None:
        if self._guard_locked("从设备管理生成"):
            return
        self.global_config = self._read_global_rule_widgets()
        self._start_background_job(
            "car_network_generate_point_table",
            {
                "db_path": str(self.repository.database.path),
                "site_name": self.site_name,
                "nodes": [asdict(node) for node in self._rows_to_nodes()],
                "global_config": self.global_config,
                "save_result": False,
            },
        )

    def _save_global_rules(self) -> None:
        if self._guard_locked("保存全局规则"):
            return
        self.global_config = self._read_global_rule_widgets()
        self._start_background_job(
            "car_network_save_point_table",
            {
                "site_name": self.site_name,
                "nodes": [asdict(node) for node in self._rows_to_nodes()],
                "global_config": self.global_config,
                "overwrite_custom": False,
            },
            context="car_network_save_global_rules",
        )

    def _apply_global_rules(self, overwrite_custom: bool) -> None:
        if self._guard_locked("应用全局规则"):
            return
        self.global_config = self._read_global_rule_widgets()
        self.nodes = apply_global_rules_to_nodes(self._rows_to_nodes(), self.global_config, overwrite_custom=overwrite_custom)
        self._reload_filters()
        self._fill_table()

    def _restore_global_rules(self) -> None:
        if self._guard_locked("恢复默认映射"):
            return
        self.global_config = merge_global_config(DEFAULT_GLOBAL_CONFIG)
        self._load_global_rule_widgets()

    def _import(self) -> None:
        if self._guard_locked("导入点表"):
            return
        path, _filter = QFileDialog.getOpenFileName(self, "导入车内通信点表", "", "Point Table (*.xlsx *.csv)")
        if not path:
            return
        self.background_manager.start_job(
            BackgroundJob(
                task_type="car_network_point_table_import",
                params={
                    "path": path,
                    "site_name": self.site_name,
                    "app_root": str(self.store.paths.app_root),
                    "data_root": str(self.store.paths.data_root),
                },
            )
        )

    def _background_finished(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        task_type = self._background_job_context.pop(job_id, "")
        result = dict(event.get("result") or {})
        if task_type == "car_network_point_table_load":
            self.global_config = merge_global_config(dict(result.get("global_config") or {}))
            self.nodes = _car_network_nodes_from_payload(result.get("nodes"))
            self.locked = bool(self.global_config.get("point_table_locked", False))
            self._reload_filters()
            self._load_global_rule_widgets()
            self._fill_table()
            self._update_lock_state()
            return
        if task_type == "car_network_generate_point_table":
            self.nodes = _car_network_nodes_from_payload(result.get("nodes"))
            self._reload_filters()
            self._fill_table()
            return
        if task_type == "car_network_save_point_table":
            self.nodes = _car_network_nodes_from_payload(result.get("nodes"))
            self.accept()
            return
        if task_type in {"car_network_save_global_rules", "car_network_save_lock_state"}:
            self.nodes = _car_network_nodes_from_payload(result.get("nodes"))
            if task_type == "car_network_save_global_rules":
                MessageBox.information(self, "车内通信点表", "全局规则已保存。")
            return
        if "count" not in result:
            return
        self.nodes = _car_network_nodes_from_payload(result.get("nodes"))
        self._reload_filters()
        self._fill_table()

    def _background_failed(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        self._background_job_context.pop(job_id, None)
        MessageBox.warning(self, "车内通信点表", str(event.get("message") or event.get("error") or "后台任务失败"))

    def _start_background_job(self, task_type: str, params: dict[str, object], *, context: str = "") -> str:
        params = {
            **params,
            "app_root": str(self.store.paths.app_root),
            "data_root": str(self.store.paths.data_root),
        }
        job_id = self.background_manager.start_job(BackgroundJob(task_type=task_type, params=params))
        self._background_job_context[job_id] = context or task_type
        return job_id

    def _export(self) -> None:
        default = Path.home() / "Desktop" / "车内通信点表.xlsx"
        path, _filter = QFileDialog.getSaveFileName(self, "导出车内通信点表", str(default), "Excel (*.xlsx);;CSV (*.csv)")
        if path:
            output_path = Path(path)
            spec = car_network_point_table_spec(output_path, site_name=self.site_name, title="导出车内通信点表", open_dir_on_success=True)
            submit_export_task(self, spec, success_title="导出车内通信点表")

    def _save(self) -> None:
        if self._guard_locked("保存点表"):
            return
        self.global_config = self._read_global_rule_widgets()
        self._start_background_job(
            "car_network_save_point_table",
            {
                "site_name": self.site_name,
                "nodes": [asdict(node) for node in self._rows_to_nodes()],
                "global_config": self.global_config,
                "overwrite_custom": False,
            },
        )


def _node_ip_summary(node: CarNetworkNode | None) -> str:
    if node is None:
        return "-"
    if node.is_mr and not node.ip_vehicle:
        return node.ip_uplink or node.ssh_host or "无车内IP"
    return node.ip_vehicle or node.ip_uplink or node.ssh_host or "-"


def _point_table_column_width(field: str) -> int:
    widths = {
        "train_id": 120,
        "train_no": 80,
        "display_name": 100,
        "tc": 80,
        "end": 80,
        "node_name": 120,
        "node_type": 100,
        "device_id": 90,
        "device_name": 150,
        "device_group": 120,
        "station": 140,
        "primary_address": 130,
        "backup_address": 130,
        "ip_vehicle": 130,
        "ip_uplink": 130,
        "ssh_host": 130,
        "vrrp_ip": 130,
        "address_mapping_mode": 90,
        "primary_address_role": 130,
        "backup_address_role": 130,
        "remark": 180,
    }
    return widths.get(field, 115)


def _ping_status_label(ping: PingResult) -> str:
    if ping.ok and ping.loss_percent == 0:
        return "OK"
    if ping.ok and ping.loss_percent > 0:
        return "丢包异常"
    return "不通"


def _task_status_label(status: str) -> str:
    return {
        "ok": "OK",
        "fail": "不通",
        "unstable": "丢包异常",
        "partial_fail": "异常",
        "offline": "离线",
        "unknown": "未知",
        "skipped": "跳过",
    }.get(status, status or "-")


def _table_row(name: str, layer: str, status: str, rtt: str, loss: str, note: str) -> dict[str, object]:
    return {"node": name, "layer": layer, "status": status, "rtt": rtt, "loss": loss, "note": note}


def _train_status_label(result: CarNetworkDiagnosticResult) -> str:
    if result.status == "ok":
        return "正常"
    if result.status == "offline":
        return "离线"
    failed_ends = [end for end in ("TC1", "TC2") if result.ends.get(end, {}).get("status") in {"fail", "unstable"}]
    return "单端异常" if len(failed_ends) == 1 else "异常"


def _cross_tc_ping_label(payload: dict[str, object]) -> str:
    status = str(payload.get("status") or "skipped")
    loss = payload.get("loss_percent")
    if status == "checking":
        return "跨TC通信：检测中"
    if status == "ok":
        return "跨TC通信：正常"
    if status == "loss":
        return f"跨TC通信：丢包 {loss}%" if loss is not None else "跨TC通信：丢包"
    if status == "fail":
        return "跨TC通信：不通"
    return "跨TC通信：未检测"


def _cross_tc_ping_tooltip(payload: dict[str, object]) -> str:
    values = [
        f"执行位置：{payload.get('source') or '-'}",
        f"目标：{payload.get('target') or '-'} / {payload.get('target_ip') or '-'}",
        f"命令：{payload.get('command') or '-'}",
        f"丢包率：{payload.get('loss_percent') if payload.get('loss_percent') is not None else '-'}%",
        f"RTT：{payload.get('avg_rtt_ms') if payload.get('avg_rtt_ms') is not None else '-'} ms",
        f"说明：{payload.get('note') or '-'}",
    ]
    return "\n".join(values)


def _cross_tc_ping_style(status: str) -> str:
    tokens = current_theme_tokens()
    fg, bg, border = {
        "checking": ("#075985", "#E0F2FE", "#38BDF8"),
        "ok": ("#14532D", "#DCFCE7", "#22C55E"),
        "loss": ("#713F12", "#FEF3C7", "#FACC15"),
        "fail": ("#7F1D1D", "#FECACA", "#EF4444"),
        "skipped": (tokens["text_muted"], tokens["surface_alt"], tokens["border_strong"]),
    }.get(status, (tokens["text_muted"], tokens["surface_alt"], tokens["border_strong"]))
    return (
        f"QLabel {{ color: {fg}; background-color: {bg}; border: 2px solid {border}; "
        "border-radius: 4px; font-size: 12px; font-weight: 700; padding: 4px 10px; }}"
    )


def _ac_probe_status_text(probe: AcProbeResult | None, status: TrainAcStatus | None) -> str:
    if probe is None or status is None:
        return "正在查询 AC mesh-link..."
    if not probe.query_success:
        return "AC mesh-link 查询失败，继续执行 ping / SSH"
    if status.tc1_mr_online and status.tc2_mr_online:
        return "AC mesh-link 发现双端 MR 在线，继续检测车内链路"
    if status.tc1_mr_online or status.tc2_mr_online:
        return "AC mesh-link 发现单端 MR 在线，继续检测车内链路"
    if status.parse_warning or status.suspected_current_train_lines:
        return "AC输出疑似包含当前列车但解析失败，继续 ping/SSH 辅助检测"
    return "AC mesh-link 未发现 TC1-MR 和 TC2-MR，继续判断后续检测策略"


def _state_dot(state: str) -> str:
    return {"ok": "●", "fail": "●", "unstable": "●", "running": "●", "not_applicable": "○"}.get(state, "○")


def _page_style(tokens: dict[str, str] | None = None) -> str:
    tokens = tokens or current_theme_tokens()
    return f"""
QWidget {{
    background-color: {tokens['background']};
    color: {tokens['text_secondary']};
    font-size: 12px;
}}
QGroupBox {{
    background-color: {tokens['surface']};
    color: {tokens['text_primary']};
    border: 1px solid {tokens['border']};
    border-radius: 6px;
    margin-top: 10px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
QLabel {{
    color: {tokens['text_secondary']};
}}
QPushButton {{
    background-color: {tokens['surface']};
    color: {tokens['text_primary']};
    border: 1px solid {tokens['border_strong']};
    border-radius: 4px;
    padding: 5px 10px;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {tokens['hover']};
    border-color: {tokens['primary']};
}}
QPushButton:disabled {{
    background-color: {tokens['panel']};
    color: {tokens['text_muted']};
    border-color: {tokens['border']};
}}
QPushButton#carNetworkPrimaryButton {{
    background-color: {tokens['primary']};
    color: #FFFFFF;
    border-color: {tokens['primary_hover']};
    font-weight: 700;
}}
QPushButton#carNetworkPrimaryButton[danger="true"] {{
    background-color: {tokens['danger']};
    border-color: {tokens['danger']};
}}
QTableWidget {{
    background-color: {tokens['surface']};
    alternate-background-color: {tokens['surface_alt']};
    color: {tokens['text_primary']};
    gridline-color: {tokens['border']};
    selection-background-color: {tokens['selected']};
    selection-color: {tokens['selected_text']};
}}
QTableWidget::item:selected {{
    background-color: {tokens['selected']};
    color: {tokens['selected_text']};
}}
QHeaderView::section {{
    background-color: {tokens['panel']};
    color: {tokens['text_primary']};
    border: 1px solid {tokens['border']};
    padding: 6px;
    font-weight: 700;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {tokens['scrollbar_bg']};
    border: 1px solid {tokens['border']};
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {tokens['scrollbar_handle']};
    border-radius: 4px;
}}
QScrollBar::handle:hover {{
    background: {tokens['scrollbar_handle_hover']};
}}
"""


def _plain_text_style(object_name: str, tokens: dict[str, str] | None = None) -> str:
    tokens = tokens or current_theme_tokens()
    return f"""
QPlainTextEdit#{object_name} {{
    background-color: {tokens['log_background']};
    color: {tokens['log_text']};
    border: 1px solid {tokens['border']};
    font-family: Consolas, 'Microsoft YaHei UI';
    font-size: 12px;
    padding: 6px;
    selection-background-color: {tokens['selected']};
    selection-color: {tokens['selected_text']};
}}
"""


def _result_table_style(tokens: dict[str, str] | None = None) -> str:
    tokens = tokens or current_theme_tokens()
    return f"""
QTableWidget {{
    background-color: {tokens['surface']};
    alternate-background-color: {tokens['surface_alt']};
    color: {tokens['text_primary']};
    gridline-color: {tokens['border']};
    selection-background-color: {tokens['selected']};
    selection-color: {tokens['selected_text']};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 5px;
    color: {tokens['text_primary']};
}}
QTableWidget::item:selected {{
    background-color: {tokens['selected']};
    color: {tokens['selected_text']};
}}
QTableWidget::item:hover {{
    background-color: {tokens['hover']};
    color: {tokens['text_primary']};
}}
QHeaderView::section {{
    background-color: {tokens['panel']};
    color: {tokens['text_primary']};
    border: 1px solid {tokens['border']};
    padding: 6px;
    font-weight: 700;
    font-size: 12px;
}}
QTableCornerButton::section {{
    background-color: {tokens['panel']};
    border: 1px solid {tokens['border']};
}}
"""


def _progress_bar_style(state: str) -> str:
    tokens = current_theme_tokens()
    chunk = {"ok": "#22C55E", "fail": "#EF4444"}.get(state, "#38BDF8")
    return f"""
QProgressBar {{
    background-color: {tokens['surface_alt']};
    color: {tokens['text_primary']};
    border: 1px solid {tokens['border']};
    border-radius: 5px;
    min-height: 12px;
    text-align: center;
    font-size: 12px;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background-color: {chunk};
    border-radius: 4px;
}}
"""


def _status_cell_colors(status: str) -> tuple[str, str]:
    tokens = current_theme_tokens()
    text = (status or "").strip()
    lowered = text.lower()
    if text == "OK" or lowered == "ok" or any(word in text for word in ("正常", "成功", "可管理", "在线")):
        return "#DCFCE7", "#14532D"
    if any(word in text for word in ("检测中", "正在")):
        return "#FFFFFF", "#075985"
    if any(word in text for word in ("丢包", "不稳定", "警告", "AC未发现", "握手失败", "认证失败")):
        return "#FEF3C7", "#713F12"
    if any(word in text for word in ("故障", "失败", "不通", "离线", "超时", "异常")):
        return "#FEE2E2", "#7F1D1D"
    if any(word in text for word in ("跳过", "未检测", "不适用")) or text in {"", "-"}:
        return tokens["text_muted"], tokens["surface_alt"]
    return tokens["text_primary"], tokens["surface_alt"]


def _style_result_item(item: QTableWidgetItem, column: int, status: str, *, running: bool = False) -> None:
    tokens = current_theme_tokens()
    if running:
        item.setForeground(QBrush(QColor("#FFFFFF")))
        item.setBackground(QBrush(QColor("#075985")))
        return
    item.setForeground(QBrush(QColor(tokens["text_primary"] if column != 5 else tokens["text_secondary"])))
    item.setBackground(QBrush())
    if column == 2:
        fg, bg = _status_cell_colors(status)
        item.setForeground(QBrush(QColor(fg)))
        item.setBackground(QBrush(QColor(bg)))


def _node_style(state: str) -> str:
    tokens = current_theme_tokens()
    fg, bg, border, border_width = {
        "ok": ("#052E16", "#BBF7D0", "#22C55E", 2),
        "fail": ("#7F1D1D", "#FECACA", "#EF4444", 2),
        "unstable": ("#713F12", "#FEF08A", "#FACC15", 2),
        "running": ("#FFFFFF", tokens["primary"], tokens["primary_hover"], 3),
        "not_applicable": (tokens["text_muted"], tokens["surface_alt"], tokens["border_strong"], 2),
    }.get(state, (tokens["text_primary"], tokens["surface_alt"], tokens["border_strong"], 2))
    return (
        "QPushButton {"
        f"color: {fg}; background: {bg}; border: {border_width}px solid {border};"
        "border-radius: 6px; font-size: 12px; font-weight: 700; padding: 4px;"
        "min-width: 128px; max-width: 128px; min-height: 58px; max-height: 58px;"
        "}"
    )


def _badge_style(state: str) -> str:
    tokens = current_theme_tokens()
    fg, bg = {
        "ok": ("#DCFCE7", "#14532D"),
        "fail": ("#FEE2E2", "#7F1D1D"),
        "unstable": ("#FEF3C7", "#713F12"),
        "running": ("#FFFFFF", "#075985"),
    }.get(state, (tokens["text_muted"], tokens["surface_alt"]))
    return f"QLabel {{ color: {fg}; background: {bg}; border-radius: 4px; padding: 3px 8px; font-weight: 600; }}"
