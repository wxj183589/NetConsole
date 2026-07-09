from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDoubleValidator, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.network_tools.iperf_runner import (
    IperfClientConfig,
    IperfServerConfig,
    build_iperf_client_args,
    build_iperf_server_args,
    normalize_bandwidth_text,
)
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.iperf_worker import IperfProcessWorker
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.no_wheel import NoWheelComboBox, NoWheelSpinBox


class IperfBandwidthPage(QWidget):
    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.server_worker: IperfProcessWorker | None = None
        self.client_worker: IperfProcessWorker | None = None
        self.server_state = "STOPPED"
        self.current_values: list[float] = []
        self.tool_label = QLabel()
        self.tool_label.setWordWrap(True)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.server_status_label = QLabel()
        self.server_status_dot = QLabel()

        self.server_bind_edit = QLineEdit()
        self.server_port_spin = self._spin(1, 65535, 5201)
        self.server_interval_spin = self._spin(1, 3600, 1)
        self.server_one_off = QCheckBox()
        self.server_start_button = QPushButton()
        self.server_stop_button = QPushButton()
        self.server_clear_button = QPushButton()
        self.open_logs_button = QPushButton()
        self.server_output = QTextEdit()
        self.server_output.setReadOnly(True)
        self.server_output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.server_output.setMinimumHeight(120)

        self.client_host_edit = QLineEdit()
        self.client_port_spin = self._spin(1, 65535, 5201)
        self.client_protocol_combo = NoWheelComboBox()
        self.client_protocol_combo.addItems(["TCP", "UDP"])
        self.client_direction_combo = NoWheelComboBox()
        self.client_duration_spin = self._spin(1, 86400, 10)
        self.client_interval_spin = self._spin(1, 3600, 1)
        self.client_parallel_spin = self._spin(1, 128, 1)
        self.client_bandwidth_edit = QLineEdit()
        self.client_bandwidth_edit.setValidator(QDoubleValidator(0.0, 999999.0, 3, self))
        self.client_bandwidth_unit_combo = NoWheelComboBox()
        self.client_bandwidth_unit_combo.addItems(["K", "M", "G"])
        self.client_bandwidth_unit_combo.setCurrentText("M")
        self.client_bandwidth_hint_label = QLabel()
        self.client_bandwidth_hint_label.setWordWrap(True)
        self.client_start_button = QPushButton()
        self.client_stop_button = QPushButton()
        self.client_clear_button = QPushButton()
        self.client_open_logs_button = QPushButton()
        self.client_output = QTextEdit()
        self.client_output.setReadOnly(True)
        self.client_output.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.client_output.setMinimumHeight(96)
        self.current_mbps_label = QLabel("0")
        self.avg_mbps_label = QLabel("0")
        self.max_mbps_label = QLabel("0")
        self.retransmits_label = QLabel("0")
        self.interval_table = QTableWidget(0, 5)
        configure_readonly_table(self.interval_table)
        self.interval_table.setMinimumHeight(110)

        self._build_ui()
        self._apply_layout_constraints()
        self._connect_signals()
        self.retranslate()
        self._set_server_state("STOPPED")
        self.refresh_tool_status()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.refresh_tool_status()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self.tool_label)
        self.splitter.addWidget(self._server_panel())
        self.splitter.addWidget(self._client_panel())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([620, 620])
        root.addWidget(self.splitter, 1)

    def _server_panel(self) -> QGroupBox:
        panel = QGroupBox()
        panel.setMinimumWidth(520)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        box = QGroupBox()
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addRow(self.i18n.t("iperf.bind_address"), self.server_bind_edit)
        form.addRow(self.i18n.t("iperf.port"), self.server_port_spin)
        form.addRow(self.i18n.t("iperf.interval"), self.server_interval_spin)
        form.addRow(self.i18n.t("iperf.one_off"), self.server_one_off)
        buttons = QHBoxLayout()
        buttons.addWidget(self.server_status_dot)
        buttons.addWidget(self.server_status_label)
        for button in (self.server_start_button, self.server_stop_button, self.server_clear_button, self.open_logs_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addWidget(box)
        layout.addLayout(buttons)
        layout.addWidget(self.server_output, 1)
        return panel

    def _client_panel(self) -> QGroupBox:
        panel = QGroupBox()
        panel.setMinimumWidth(520)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        box = QGroupBox()
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.client_direction_combo.addItem(self.i18n.t("iperf.upload"), "upload")
        self.client_direction_combo.addItem(self.i18n.t("iperf.download"), "download")
        self.client_direction_combo.addItem(self.i18n.t("iperf.bidirectional"), "bidirectional")
        form.addRow(self.i18n.t("iperf.server_address"), self.client_host_edit)
        form.addRow(self.i18n.t("iperf.port"), self.client_port_spin)
        form.addRow(self.i18n.t("iperf.protocol"), self.client_protocol_combo)
        form.addRow(self.i18n.t("iperf.direction"), self.client_direction_combo)
        form.addRow(self.i18n.t("iperf.duration"), self.client_duration_spin)
        form.addRow(self.i18n.t("iperf.interval"), self.client_interval_spin)
        form.addRow(self.i18n.t("iperf.parallel"), self.client_parallel_spin)
        bandwidth_row = QHBoxLayout()
        bandwidth_row.setContentsMargins(0, 0, 0, 0)
        bandwidth_row.setSpacing(8)
        bandwidth_row.addWidget(self.client_bandwidth_edit)
        bandwidth_row.addWidget(self.client_bandwidth_unit_combo)
        form.addRow(self.i18n.t("iperf.target_bandwidth"), bandwidth_row)
        form.addRow("", self.client_bandwidth_hint_label)
        buttons = QHBoxLayout()
        for button in (self.client_start_button, self.client_stop_button, self.client_clear_button, self.client_open_logs_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        summary = QHBoxLayout()
        for label, value in (
            ("iperf.current_mbps", self.current_mbps_label),
            ("iperf.avg_mbps", self.avg_mbps_label),
            ("iperf.max_mbps", self.max_mbps_label),
            ("iperf.retransmits", self.retransmits_label),
        ):
            summary.addWidget(QLabel(self.i18n.t(label)))
            summary.addWidget(value)
        summary.addStretch(1)
        layout.addWidget(box)
        layout.addLayout(buttons)
        layout.addLayout(summary)
        layout.addWidget(self.interval_table)
        layout.addWidget(self.client_output, 1)
        return panel

    def _apply_layout_constraints(self) -> None:
        for widget in (
            self.server_bind_edit,
            self.client_host_edit,
            self.client_bandwidth_edit,
            self.client_protocol_combo,
            self.client_direction_combo,
        ):
            widget.setMinimumWidth(260)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for spin in (
            self.server_port_spin,
            self.server_interval_spin,
            self.client_port_spin,
            self.client_duration_spin,
            self.client_interval_spin,
            self.client_parallel_spin,
        ):
            spin.setMinimumWidth(110)
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if hasattr(spin, "setButtonSymbols"):
                spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.client_bandwidth_unit_combo.setMinimumWidth(64)
        self.client_bandwidth_unit_combo.setMaximumWidth(76)

    def _connect_signals(self) -> None:
        self.server_start_button.clicked.connect(self.start_server)
        self.server_stop_button.clicked.connect(self.stop_server)
        self.server_clear_button.clicked.connect(self.server_output.clear)
        self.open_logs_button.clicked.connect(lambda: self._open_log_dir(self.paths.iperf_server_dir(self.site_name)))
        self.client_start_button.clicked.connect(self.start_client)
        self.client_stop_button.clicked.connect(self.stop_client)
        self.client_clear_button.clicked.connect(self._clear_client)
        self.client_open_logs_button.clicked.connect(lambda: self._open_log_dir(self.paths.iperf_client_dir(self.site_name)))

    def retranslate(self) -> None:
        self.splitter.widget(0).setTitle(self.i18n.t("iperf.server"))
        self.splitter.widget(1).setTitle(self.i18n.t("iperf.client"))
        self.server_start_button.setText(self.i18n.t("iperf.start_server"))
        self.server_stop_button.setText(self.i18n.t("iperf.stop_server"))
        self.server_clear_button.setText(self.i18n.t("iperf.clear_output"))
        self.open_logs_button.setText(self.i18n.t("iperf.open_log_dir"))
        self._set_server_state(self.server_state)
        self.client_start_button.setText(self.i18n.t("iperf.start_client"))
        self.client_stop_button.setText(self.i18n.t("iperf.stop_client"))
        self.client_clear_button.setText(self.i18n.t("iperf.clear_output"))
        self.client_open_logs_button.setText(self.i18n.t("iperf.open_log_dir"))
        self.client_bandwidth_hint_label.setText(self.i18n.t("iperf.empty_tcp_auto"))
        tooltip = self.i18n.t("iperf.target_bandwidth_tooltip")
        self.client_bandwidth_edit.setToolTip(tooltip)
        self.client_bandwidth_unit_combo.setToolTip(self.i18n.t("iperf.bandwidth_unit"))
        self._apply_button_icons()
        for widget in (
            self.server_port_spin,
            self.server_interval_spin,
            self.client_port_spin,
            self.client_duration_spin,
            self.client_interval_spin,
            self.client_parallel_spin,
            self.client_protocol_combo,
            self.client_direction_combo,
            self.client_bandwidth_unit_combo,
        ):
            widget.setToolTip(self.i18n.t("iperf.no_wheel_hint"))
        self.interval_table.setHorizontalHeaderLabels([self.i18n.t("online_mr.time"), "Mbps", self.i18n.t("iperf.retransmits"), self.i18n.t("iperf.transfer"), self.i18n.t("online_mr.raw")])

    def _apply_button_icons(self) -> None:
        for button, icon_name in (
            (self.server_start_button, "PLAY"),
            (self.server_stop_button, "CANCEL"),
            (self.server_clear_button, "DELETE"),
            (self.open_logs_button, "FOLDER"),
            (self.client_start_button, "PLAY"),
            (self.client_stop_button, "CANCEL"),
            (self.client_clear_button, "DELETE"),
            (self.client_open_logs_button, "FOLDER"),
        ):
            apply_button_icon(button, icon_name)

    def refresh_tool_status(self) -> None:
        tool = find_iperf_tool(self.paths)
        if tool is None:
            self.tool_label.setText(self.i18n.t("iperf.tool_missing"))
            self.server_start_button.setEnabled(False)
            self.server_stop_button.setEnabled(False)
            self.client_start_button.setEnabled(False)
            return
        status = detect_iperf_version(tool)
        self.tool_label.setText(f"{self.i18n.t('iperf.tool_found')}: iperf {status.version or self.i18n.t('iperf.unknown_version')} ({tool})")
        self._set_server_state(self.server_state)
        self.client_start_button.setEnabled(True)

    def start_server(self) -> None:
        tool = find_iperf_tool(self.paths)
        if tool is None:
            MessageBox.warning(self, self.i18n.t("network_tools.iperf"), self.i18n.t("iperf.tool_missing"))
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.paths.iperf_server_dir(self.site_name) / f"iperf_server_{stamp}.log"
        command = build_iperf_server_args(tool, IperfServerConfig(self.server_bind_edit.text(), self.server_port_spin.value(), self.server_interval_spin.value(), self.server_one_off.isChecked()))
        self.server_worker = IperfProcessWorker(tool, command, log_file, db_path=self.paths.iperf_db_path(self.site_name), mode="server", parent=self)
        self.server_worker.line_received.connect(self.server_output.append)
        self.server_worker.started.connect(lambda: self._set_server_state("RUNNING"))
        self.server_worker.completed.connect(self._server_completed)
        self.server_worker.failed.connect(self._server_failed)
        self._set_server_state("STARTING")
        self.server_worker.start()

    def stop_server(self) -> None:
        if self.server_worker:
            self._set_server_state("STOPPING")
            self.server_worker.stop()

    def start_client(self) -> None:
        tool = find_iperf_tool(self.paths)
        if tool is None:
            MessageBox.warning(self, self.i18n.t("network_tools.iperf"), self.i18n.t("iperf.tool_missing"))
            return
        config = IperfClientConfig(
            self.client_host_edit.text(),
            self.client_port_spin.value(),
            self.client_protocol_combo.currentText(),
            self.client_duration_spin.value(),
            self.client_interval_spin.value(),
            self.client_parallel_spin.value(),
            self.client_direction_combo.currentData(),
            normalize_bandwidth_text(self.client_bandwidth_edit.text(), self.client_bandwidth_unit_combo.currentText()),
        ).normalized()
        if not config.server_ip:
            MessageBox.warning(self, self.i18n.t("network_tools.iperf"), self.i18n.t("iperf.server_required"))
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.paths.iperf_client_dir(self.site_name) / f"iperf_client_{stamp}.log"
        command = build_iperf_client_args(tool, config)
        self.client_worker = IperfProcessWorker(tool, command, log_file, db_path=self.paths.iperf_db_path(self.site_name), config=config, mode="client", parent=self)
        self.client_worker.line_received.connect(self.client_output.append)
        self.client_worker.interval_received.connect(self._append_interval)
        self.client_worker.failed.connect(lambda message: MessageBox.warning(self, self.i18n.t("network_tools.iperf"), message))
        self.client_worker.start()

    def stop_client(self) -> None:
        if self.client_worker:
            self.client_worker.stop()

    def _open_log_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _append_interval(self, row: dict[str, object]) -> None:
        mbps = float(row.get("bitrate_mbps") or 0)
        self.current_values.append(mbps)
        self.current_mbps_label.setText(f"{mbps:.2f}")
        self.avg_mbps_label.setText(f"{sum(self.current_values) / len(self.current_values):.2f}")
        self.max_mbps_label.setText(f"{max(self.current_values):.2f}")
        retransmits = sum(int(self.interval_table.item(r, 2).text() or "0") for r in range(self.interval_table.rowCount())) + int(row.get("retransmits") or 0)
        self.retransmits_label.setText(str(retransmits))
        table_row = self.interval_table.rowCount()
        self.interval_table.insertRow(table_row)
        values = [row.get("interval_center_time") or row.get("collector_time"), f"{mbps:.2f}", row.get("retransmits", 0), int(float(row.get("transfer_bytes") or 0)), row.get("raw_line", "")]
        for column, value in enumerate(values):
            self.interval_table.setItem(table_row, column, QTableWidgetItem(str(value)))

    def _clear_client(self) -> None:
        self.client_output.clear()
        self.interval_table.setRowCount(0)
        self.current_values.clear()

    def _server_completed(self, status: str) -> None:
        self.server_output.append(self.i18n.t("iperf.stopped"))
        self._set_server_state("STOPPED" if status in {"STOPPED", "DONE"} else "FAILED")
        self.server_worker = None

    def _server_failed(self, message: str) -> None:
        self._set_server_state("FAILED")
        self.server_worker = None
        MessageBox.warning(self, self.i18n.t("network_tools.iperf"), message)

    def _set_server_state(self, state: str) -> None:
        self.server_state = state
        key = {
            "STOPPED": "iperf.server_stopped",
            "STARTING": "iperf.server_starting",
            "RUNNING": "iperf.server_running",
            "STOPPING": "iperf.server_stopping",
            "FAILED": "iperf.server_failed",
        }.get(state, "iperf.server_stopped")
        color = {
            "RUNNING": "#22c55e",
            "STARTING": "#f59e0b",
            "STOPPING": "#f59e0b",
            "FAILED": "#ef4444",
            "STOPPED": "#ef4444",
        }.get(state, "#ef4444")
        self.server_status_dot.setText("●")
        self.server_status_dot.setStyleSheet(f"QLabel {{ color: {color}; font-size: 16px; font-weight: 700; }}")
        self.server_status_label.setText(f"{self.i18n.t('iperf.server_status')}: {self.i18n.t(key)}")
        self.server_start_button.setEnabled(state in {"STOPPED", "FAILED"} and find_iperf_tool(self.paths) is not None)
        self.server_stop_button.setEnabled(state in {"STARTING", "RUNNING"})

    def _spin(self, minimum: int, maximum: int, value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setToolTip(self.i18n.t("iperf.no_wheel_hint"))
        return spin
