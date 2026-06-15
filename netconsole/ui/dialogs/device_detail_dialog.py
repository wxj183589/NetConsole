from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services.h3c_collect_service import CollectDeviceResult
from netconsole.ui.collect_worker import DeviceCollectThread
from netconsole.ui.dialogs.history_data_dialog import (
    HistoryDataDialog,
    INTERFACE_HISTORY_COLUMNS,
    LLDP_HISTORY_COLUMNS,
    OPTICAL_HISTORY_COLUMNS,
)
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table, make_text_selectable


OVERVIEW_FIELDS = (
    ("details.system_name", "sysname"),
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("details.software_version", "software_version"),
    ("details.bootrom_version", "bootrom_version"),
    ("details.vendor", "vendor"),
    ("details.uptime", "uptime"),
    ("details.collected_at", "collected_at"),
    ("details.raw_log_path", "raw_log_path"),
)

COLLECT_LOG_NOT_FOUND = "未找到采集日志"

INTERFACE_COLUMNS = (
    ("details.interface_name", "interface_name"),
    ("details.link", "link_status"),
    ("details.protocol", "protocol_status"),
    ("details.speed", "speed"),
    ("details.duplex", "duplex"),
    ("details.interface_type", "interface_type"),
    ("details.port_status", "port_status"),
    ("details.pvid", "pvid"),
    ("details.port_description", "description"),
    ("details.interface_ip", "ip_address"),
    ("details.mac_address", "mac_address"),
    ("details.vlan", "vlan"),
    ("details.collected_at", "collected_at"),
)

OPTICAL_MODULE_COLUMNS = (
    ("details.interface_name", "interface_name"),
    ("details.rx_power", "rx_power"),
    ("details.tx_power", "tx_power"),
    ("details.temperature", "temperature"),
    ("details.voltage", "voltage"),
    ("details.bias_current", "bias_current"),
    ("details.module_model", "module_model"),
    ("details.module_serial_number", "module_serial_number"),
    ("details.vendor", "module_vendor"),
    ("details.wavelength", "wavelength"),
    ("details.transmission_distance", "transmission_distance"),
    ("field.status", "status"),
    ("details.collected_at", "collected_at"),
)

LLDP_COLUMNS = (
    ("details.local_interface", "local_interface"),
    ("details.neighbor_sysname", "neighbor_sysname"),
    ("details.neighbor_mac", "neighbor_mac"),
    ("details.neighbor_interface", "neighbor_interface"),
    ("details.neighbor_ip", "neighbor_ip"),
    ("details.collected_at", "collected_at"),
)


class DeviceDetailDialog(QDialog):
    def __init__(self, i18n: I18n, repository: DeviceFactRepository, device: Device, parent=None, site_name: str = "demo") -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.repository = repository
        self.device = device
        self.site_name = site_name
        self.collect_thread: DeviceCollectThread | None = None
        self.history_dialogs: list[HistoryDataDialog] = []
        self.collect_log_dialogs: list[CollectLogDialog] = []
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setMinimumSize(720, 480)
        self.resize(800, 520)

        self.title_label = make_text_selectable(QLabel())
        self.always_on_top_button = QPushButton()
        self.refresh_button = QPushButton()
        self.view_collect_log_button = QPushButton()
        self.copy_collect_log_button = QPushButton()
        self.export_collect_log_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.refresh_button.clicked.connect(self.refresh_device_details)
        self.view_collect_log_button.clicked.connect(self.view_collect_log)
        self.copy_collect_log_button.clicked.connect(self.copy_collect_log)
        self.export_collect_log_button.clicked.connect(self.export_collect_log)
        self.tabs = QTabWidget()
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        header.addWidget(self.view_collect_log_button)
        header.addWidget(self.copy_collect_log_button)
        header.addWidget(self.export_collect_log_button)
        header.addWidget(self.always_on_top_button)
        layout.addLayout(header)
        layout.addWidget(self.tabs)
        self.apply_style()
        self.retranslate()

    def retranslate(self) -> None:
        title = self.i18n.t("details.title_with_name", name=self.device.name)
        self.setWindowTitle(title)
        self.title_label.setText(title)
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self.view_collect_log_button.setText(self.i18n.t("details.view_collect_log"))
        self.copy_collect_log_button.setText(self.i18n.t("details.copy_collect_log"))
        self.export_collect_log_button.setText(self.i18n.t("details.export_collect_log"))
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))
        self.reload_tabs()

    def reload_tabs(self) -> None:
        self.tabs.clear()
        self.tabs.addTab(self._overview_tab(), self.i18n.t("details.overview"))
        self.tabs.addTab(self._interfaces_tab(), self.i18n.t("details.interfaces"))
        self.tabs.addTab(self._optical_modules_tab(), self.i18n.t("details.optical_modules"))
        self.tabs.addTab(self._lldp_tab(), self.i18n.t("details.lldp"))

    def refresh_device_details(self) -> None:
        if self.collect_thread is not None and self.collect_thread.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText(self.i18n.t("details.refreshing"))
        self.collect_thread = DeviceCollectThread(self.device, self.site_name, self)
        self.collect_thread.collect_finished.connect(self._collect_finished)
        self.collect_thread.collect_failed.connect(self._collect_failed)
        self.collect_thread.finished.connect(self.collect_thread.deleteLater)
        self.collect_thread.finished.connect(lambda: setattr(self, "collect_thread", None))
        self.collect_thread.start()

    def _collect_finished(self, result: CollectDeviceResult) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self.reload_tabs()
        if result.success and result.error_message:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_partial"))
        elif result.success:
            QMessageBox.information(self, self.windowTitle(), self.i18n.t("details.refresh_done"))
        else:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_failed", error=result.error_message or "unknown"))

    def _collect_failed(self, error_message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_failed", error=error_message))

    def _overview_tab(self) -> QWidget:
        fact = self.repository.get_device_fact(str(self.device.device_uuid or ""))
        if not fact:
            return self._empty_tab("details.overview_note")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self._note_label("details.overview_note"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        for label_key, field in OVERVIEW_FIELDS:
            value = QLabel(str(fact.get(field) or ""))
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(self.i18n.t(label_key), value)
        layout.addStretch(1)
        return widget

    def view_collect_log(self) -> None:
        try:
            path, text = self._load_collect_log()
        except FileNotFoundError:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.collect_log_not_found"))
            return
        dialog = CollectLogDialog(self.i18n.t("details.collect_log_title"), str(path), text, self)
        self.collect_log_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._remove_collect_log_dialog(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def copy_collect_log(self) -> None:
        try:
            _path, text = self._load_collect_log()
        except FileNotFoundError:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.collect_log_not_found"))
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, self.windowTitle(), self.i18n.t("details.collect_log_copied"))

    def export_collect_log(self) -> None:
        try:
            _path, text = self._load_collect_log()
        except FileNotFoundError:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.collect_log_not_found"))
            return
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("details.export_collect_log"), f"{self.device.name}_collect_log.txt", "Text Files (*.txt);;All Files (*.*)")
        if not path:
            return
        Path(path).write_text(text, encoding="utf-8")

    def _load_collect_log(self) -> tuple[Path, str]:
        raw_log_path = self.repository.get_latest_raw_log_path(str(self.device.device_uuid or ""))
        return read_collect_log_text(raw_log_path)

    def _interfaces_tab(self) -> QWidget:
        rows = self.repository.list_device_interfaces(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.interfaces_note")
        return self._table_tab("details.interfaces_note", INTERFACE_COLUMNS, rows, "description", "interface")

    def _optical_modules_tab(self) -> QWidget:
        rows = self.repository.list_optical_modules(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.optical_modules_note")
        return self._table_tab("details.optical_modules_note", OPTICAL_MODULE_COLUMNS, rows, "module_model", "optical")

    def _lldp_tab(self) -> QWidget:
        rows = self.repository.list_lldp_neighbors(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.lldp_note")
        return self._table_tab("details.lldp_note", LLDP_COLUMNS, rows, "neighbor_sysname", "lldp")

    def _table_tab(self, note_key: str, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]], stretch_field: str, history_kind: str) -> QWidget:
        table = QTableWidget(len(rows), len(columns))
        configure_readonly_table(table)
        attach_table_context_menu(table, self.i18n.language, history_callback=lambda row, kind=history_kind, data=rows: self.open_history_data(kind, data[row]))
        table.setHorizontalHeaderLabels([self.i18n.t(label_key) for label_key, _field in columns])
        for row_index, row in enumerate(rows):
            for column_index, (_label_key, field) in enumerate(columns):
                item = QTableWidgetItem(str(row.get(field) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column_index, item)
        stretch_index = _column_index(columns, stretch_field)
        auto_resize_table_columns(
            table,
            stretch_columns={stretch_index} if stretch_index is not None else set(),
            column_min_widths=_column_min_widths(columns),
        )
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(self._note_label(note_key))
        layout.addWidget(table)
        return wrapper

    def open_history_data(self, history_kind: str, row: dict[str, object | None]) -> HistoryDataDialog:
        device_uuid = str(self.device.device_uuid or "")
        if history_kind == "interface":
            object_name = str(row.get("interface_name") or "")
            rows = self.repository.list_interface_history(device_uuid, object_name)
            columns = INTERFACE_HISTORY_COLUMNS
        elif history_kind == "optical":
            object_name = str(row.get("interface_name") or "")
            rows = self.repository.list_optical_history(device_uuid, object_name)
            columns = OPTICAL_HISTORY_COLUMNS
        elif history_kind == "lldp":
            object_name = str(row.get("local_interface") or "")
            rows = self.repository.list_lldp_history(device_uuid, object_name)
            columns = LLDP_HISTORY_COLUMNS
        else:
            raise ValueError(f"Unsupported history kind: {history_kind}")
        dialog = HistoryDataDialog(self.i18n, self.device.name, object_name, columns, rows, self)
        self.history_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._remove_history_dialog(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _remove_history_dialog(self, dialog: HistoryDataDialog) -> None:
        if dialog in self.history_dialogs:
            self.history_dialogs.remove(dialog)

    def _remove_collect_log_dialog(self, dialog: "CollectLogDialog") -> None:
        if dialog in self.collect_log_dialogs:
            self.collect_log_dialogs.remove(dialog)

    def _empty_tab(self, note_key: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self._note_label(note_key))
        label = QLabel(self.i18n.t("details.no_data_demo_hint"))
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        make_text_selectable(label)
        layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _note_label(self, key: str) -> QLabel:
        label = QLabel(self.i18n.t(key))
        label.setWordWrap(True)
        make_text_selectable(label)
        return label

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()
        self.raise_()
        self.activateWindow()

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog, QWidget { background: #f7f8fa; color: #1f2933; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
            QLabel { color: #1f2933; }
            QTabWidget::pane { background: #ffffff; border: 1px solid #cbd5df; top: -1px; }
            QTabBar::tab { background: #e9eef5; color: #1f2933; border: 1px solid #cbd5df; padding: 8px 16px; min-width: 92px; }
            QTabBar::tab:selected { background: #ffffff; color: #0f3d75; border-bottom: 1px solid #ffffff; font-weight: 600; }
            QTabBar::tab:!selected:hover { background: #f1f5fb; }
            QPushButton { background: #ffffff; border: 1px solid #cbd5df; border-radius: 4px; padding: 6px 10px; }
            QPushButton:hover { background: #eef5ff; border-color: #8bb7ee; }
            """
        )


class CollectLogDialog(QDialog):
    def __init__(self, title: str, raw_log_path: str, text: str, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.resize(900, 640)
        self.path_label = make_text_selectable(QLabel(raw_log_path))
        self.path_label.setWordWrap(True)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(text)
        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addWidget(self.text_edit, 1)


def read_collect_log_text(raw_log_path: str | None) -> tuple[Path, str]:
    if not raw_log_path:
        raise FileNotFoundError(COLLECT_LOG_NOT_FOUND)
    path = Path(raw_log_path)
    if not path.is_file():
        raise FileNotFoundError(COLLECT_LOG_NOT_FOUND)
    return path, path.read_text(encoding="utf-8", errors="replace")


def _column_index(columns: tuple[tuple[str, str], ...], field: str) -> int | None:
    for index, (_label_key, column_field) in enumerate(columns):
        if column_field == field:
            return index
    return None


def _column_min_widths(columns: tuple[tuple[str, str], ...]) -> dict[int, int]:
    widths = {
        "interface_name": 180,
        "local_interface": 180,
        "neighbor_interface": 180,
        "neighbor_sysname": 160,
        "neighbor_mac": 150,
        "module_model": 180,
        "module_serial_number": 180,
        "description": 180,
    }
    return {index: widths[field] for index, (_label_key, field) in enumerate(columns) if field in widths}
