from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.fit_ap_import_export import FitApImportExportService, make_fit_ap_export_filename
from netconsole.ui.ac_collect_worker import AcResourceCollectThread, FitApOpticalCollectThread
from netconsole.ui.dialogs.fit_ap_detail_dialog import FitApDetailDialog
from netconsole.ui.table_utils import auto_resize_table_columns, create_table_context_menu, configure_readonly_table


CHECK_COLUMN = 0
SUMMARY_FIELDS = (
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("details.software_version", "software_version"),
    ("ac.total_aps", "total_aps"),
    ("ac.online_aps", "online_aps"),
    ("ac.offline_aps", "offline_aps"),
    ("ac.ap_licenses", "total_ap_licenses"),
    ("ac.local_ap_licenses", "local_ap_licenses"),
    ("ac.remaining_local_ap_licenses", "remaining_local_ap_licenses"),
    ("ac.cpu_usage", "cpu_usage"),
    ("ac.memory_usage", "memory_usage"),
    ("field.updated_at", "updated_at"),
)

FIT_AP_RESOURCE_COLUMNS = (
    ("", "select"),
    ("ac.ap_name", "ap_name"),
    ("field.ip_address", "ap_ip"),
    ("field.mac_address", "ap_mac"),
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("field.status", "state_display"),
    ("ac.group_name", "group_name"),
    ("ac.online_time", "online_time"),
    ("field.updated_at", "updated_at"),
)

FIT_AP_OPTICAL_COLUMNS = (
    ("ac.ap_name", "ap_name"),
    ("ac.site", "site"),
    ("ac.lldp_neighbor", "lldp_neighbor"),
    ("ap.neighbor_interface", "neighbor_interface"),
    ("ap.neighbor_mac", "neighbor_mac"),
    ("ap.neighbor_device_name", "neighbor_device_name"),
    ("ap.neighbor_rx_power", "neighbor_rx_power"),
    ("ap.interface", "interface_name"),
    ("ap.temperature", "temperature"),
    ("ap.tx_power", "tx_power"),
    ("ap.rx_power", "rx_power"),
    ("field.updated_at", "updated_at"),
    ("field.status", "status"),
    ("ac.error_message", "error_message"),
)


class AcManagementPage(QWidget):
    def __init__(self, device_repository: DeviceRepository, i18n: I18n, site_name: str = "demo") -> None:
        super().__init__()
        self.device_repository = device_repository
        self.repository = AcRepository(device_repository.database)
        self.import_export_service = FitApImportExportService(self.repository)
        self.i18n = i18n
        self.site_name = site_name
        self.ac_devices: list[Device] = []
        self.resource_thread: AcResourceCollectThread | None = None
        self.optical_thread: FitApOpticalCollectThread | None = None
        self.detail_windows: list[FitApDetailDialog] = []

        self.device_combo = QComboBox()
        self.open_web_button = QPushButton()
        self.refresh_button = QPushButton()
        self.status_label = QLabel()
        self.summary_labels: dict[str, QLabel] = {field: QLabel("-") for _key, field in SUMMARY_FIELDS}
        self.tabs = QTabWidget()
        self.resources_table = QTableWidget()
        self.batch_delete_button = QPushButton()
        self.batch_edit_button = QPushButton()
        self.import_button = QPushButton()
        self.export_button = QPushButton()
        self.clear_selection_button = QPushButton()
        self.invert_selection_button = QPushButton()
        self.selection_label = QLabel()
        self.optical_table = QTableWidget()
        self.refresh_optical_button = QPushButton()
        self.coming_soon_label = QLabel()

        configure_readonly_table(self.resources_table)
        configure_readonly_table(self.optical_table)
        self.resources_table.setColumnCount(len(FIT_AP_RESOURCE_COLUMNS))
        self.optical_table.setColumnCount(len(FIT_AP_OPTICAL_COLUMNS))
        self.resources_table.horizontalHeader().sectionClicked.connect(self._resource_header_clicked)
        self.resources_table.itemChanged.connect(self.update_selection_state)
        self.resources_table.doubleClicked.connect(lambda index: self.open_ap_detail(index.row()))
        self.resources_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.resources_table.customContextMenuRequested.connect(self.show_resource_context_menu)
        self.optical_table.doubleClicked.connect(lambda index: self.open_ap_detail_from_optical(index.row()))
        self.optical_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.optical_table.customContextMenuRequested.connect(self.show_optical_context_menu)

        top = QHBoxLayout()
        top.addWidget(self.device_combo, 1)
        top.addWidget(self.open_web_button)
        top.addWidget(self.status_label)

        summary = QGridLayout()
        for index, (key, field) in enumerate(SUMMARY_FIELDS):
            label = QLabel()
            label.setObjectName(f"summary_label_{field}")
            label.setProperty("translation_key", key)
            summary.addWidget(label, index // 4 * 2, index % 4)
            summary.addWidget(self.summary_labels[field], index // 4 * 2 + 1, index % 4)

        resources_tab = QWidget()
        resources_layout = QVBoxLayout()
        resource_actions = QHBoxLayout()
        for button in (
            self.refresh_button,
            self.batch_delete_button,
            self.batch_edit_button,
            self.import_button,
            self.export_button,
            self.clear_selection_button,
            self.invert_selection_button,
        ):
            resource_actions.addWidget(button)
        resource_actions.addWidget(self.selection_label)
        resource_actions.addStretch(1)
        resources_layout.addLayout(resource_actions)
        resources_layout.addWidget(self.resources_table)
        resources_tab.setLayout(resources_layout)

        optical_tab = QWidget()
        optical_layout = QVBoxLayout()
        optical_actions = QHBoxLayout()
        optical_actions.addWidget(self.refresh_optical_button)
        optical_actions.addStretch(1)
        optical_layout.addLayout(optical_actions)
        optical_layout.addWidget(self.optical_table)
        optical_tab.setLayout(optical_layout)

        mr_tab = QWidget()
        mr_layout = QVBoxLayout()
        self.coming_soon_label.setAlignment(Qt.AlignCenter)
        mr_layout.addWidget(self.coming_soon_label, 1)
        mr_tab.setLayout(mr_layout)

        self.tabs.addTab(resources_tab, "")
        self.tabs.addTab(optical_tab, "")
        self.tabs.addTab(mr_tab, "")

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(summary)
        layout.addWidget(self.tabs, 1)
        self.setLayout(layout)

        self.device_combo.currentIndexChanged.connect(self.refresh_data)
        self.open_web_button.clicked.connect(self.open_web)
        self.refresh_button.clicked.connect(self.refresh_ac_resources)
        self.batch_delete_button.clicked.connect(self.batch_delete_aps)
        self.batch_edit_button.clicked.connect(self.batch_edit_site)
        self.import_button.clicked.connect(self.import_metadata)
        self.export_button.clicked.connect(self.export_aps)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.invert_selection_button.clicked.connect(self.invert_selection)
        self.refresh_optical_button.clicked.connect(self.refresh_fit_ap_optical)
        self.retranslate()
        self.refresh_devices()

    def set_repository(self, device_repository: DeviceRepository, site_name: str) -> None:
        self.device_repository = device_repository
        self.repository = AcRepository(device_repository.database)
        self.import_export_service = FitApImportExportService(self.repository)
        self.site_name = site_name
        self.refresh_devices()

    def retranslate(self) -> None:
        self.open_web_button.setText(self.i18n.t("ac.open_web"))
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self.batch_delete_button.setText(self.i18n.t("devices.batch_delete"))
        self.batch_edit_button.setText(self.i18n.t("ap.batch_edit"))
        self.import_button.setText(self.i18n.t("ap.import_metadata"))
        self.export_button.setText(self.i18n.t("ap.export_info"))
        self.clear_selection_button.setText(self.i18n.t("devices.clear_selection"))
        self.invert_selection_button.setText(self.i18n.t("devices.invert_selection"))
        self.refresh_optical_button.setText(self.i18n.t("ac.refresh_optical"))
        self.status_label.setText(self.i18n.t("ac.status.not_collected"))
        self.coming_soon_label.setText(self.i18n.t("ac.coming_soon"))
        for index, (key, _field) in enumerate(SUMMARY_FIELDS):
            label = self.findChild(QLabel, f"summary_label_{SUMMARY_FIELDS[index][1]}")
            if label is not None:
                label.setText(self.i18n.t(key))
        self.tabs.setTabText(0, self.i18n.t("ac.fit_ap_resources"))
        self.tabs.setTabText(1, self.i18n.t("ac.fit_ap_optical"))
        self.tabs.setTabText(2, self.i18n.t("ac.online_vehicle_mr"))
        self.resources_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in FIT_AP_RESOURCE_COLUMNS])
        self.resources_table.horizontalHeaderItem(CHECK_COLUMN).setText(self.i18n.t("ap.select_all"))
        self.optical_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in FIT_AP_OPTICAL_COLUMNS])
        auto_resize_table_columns(self.resources_table, column_min_widths={0: 80, 1: 150})
        auto_resize_table_columns(self.optical_table, column_min_widths={2: 180, 3: 180, 5: 180, 13: 180})
        self.update_selection_state()

    def refresh_devices(self) -> None:
        current_uuid = self.current_device_uuid()
        self.ac_devices = self.device_repository.list(device_type="AC")
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self.ac_devices:
            self.device_combo.addItem(f"{device.name} ({device.ip_address})", device.device_uuid)
        index = self.device_combo.findData(current_uuid)
        self.device_combo.setCurrentIndex(index if index >= 0 else (0 if self.ac_devices else -1))
        self.device_combo.blockSignals(False)
        self.refresh_data()

    def refresh_data(self) -> None:
        ac_uuid = self.current_device_uuid()
        if not ac_uuid:
            self._set_summary(None)
            self._set_rows(self.resources_table, FIT_AP_RESOURCE_COLUMNS, [])
            self._set_rows(self.optical_table, FIT_AP_OPTICAL_COLUMNS, [])
            return
        self._set_summary(self.repository.get_ac_ap_summary(ac_uuid))
        self._set_rows(self.resources_table, FIT_AP_RESOURCE_COLUMNS, self.repository.list_fit_ap_resources_with_metadata(ac_uuid))
        self._set_rows(self.optical_table, FIT_AP_OPTICAL_COLUMNS, self.repository.list_fit_ap_optical(ac_uuid))
        self.update_selection_state()

    def open_web(self) -> None:
        device = self.current_device()
        if device is not None:
            webbrowser.open(f"https://{device.ip_address}")

    def refresh_ac_resources(self) -> None:
        device = self.current_device()
        if device is None:
            QMessageBox.information(self, self.i18n.t("ac.title"), self.i18n.t("devices.select_first"))
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("ac.status.updating"))
        self.resource_thread = AcResourceCollectThread(device, self.site_name, self)
        self.resource_thread.collect_finished.connect(self._finish_resource_collect)
        self.resource_thread.collect_failed.connect(self._fail_resource_collect)
        self.resource_thread.finished.connect(self.resource_thread.deleteLater)
        self.resource_thread.finished.connect(lambda: setattr(self, "resource_thread", None))
        self.resource_thread.start()

    def refresh_fit_ap_optical(self) -> None:
        device = self.current_device()
        if device is None:
            return
        self.refresh_optical_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("ac.status.updating"))
        self.optical_thread = FitApOpticalCollectThread(device, self.site_name, self)
        self.optical_thread.collect_finished.connect(self._finish_optical_collect)
        self.optical_thread.collect_failed.connect(self._fail_optical_collect)
        self.optical_thread.finished.connect(self.optical_thread.deleteLater)
        self.optical_thread.finished.connect(lambda: setattr(self, "optical_thread", None))
        self.optical_thread.start()

    def _finish_resource_collect(self, result) -> None:
        self.refresh_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.done" if result.success else "ac.status.failed"))
        self.refresh_data()

    def _fail_resource_collect(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.failed"))
        QMessageBox.warning(self, self.i18n.t("ac.title"), message)

    def _finish_optical_collect(self, result) -> None:
        self.refresh_optical_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.done" if result.success else "ac.status.failed"))
        self.refresh_data()

    def _fail_optical_collect(self, message: str) -> None:
        self.refresh_optical_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.failed"))
        QMessageBox.warning(self, self.i18n.t("ac.title"), message)

    def current_device_uuid(self) -> str | None:
        value = self.device_combo.currentData()
        return str(value) if value else None

    def current_device(self) -> Device | None:
        current_uuid = self.current_device_uuid()
        for device in self.ac_devices:
            if device.device_uuid == current_uuid:
                return device
        return None

    def selected_ap_names(self) -> list[str]:
        names: list[str] = []
        for row in range(self.resources_table.rowCount()):
            item = self.resources_table.item(row, CHECK_COLUMN)
            if item and item.checkState() == Qt.Checked:
                names.append(str(item.data(Qt.UserRole)))
        return names

    def checked_or_all_ap_rows(self) -> list[dict[str, object | None]]:
        ac_uuid = self.current_device_uuid()
        if not ac_uuid:
            return []
        rows = self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        selected = set(self.selected_ap_names())
        return [row for row in rows if not selected or row.get("ap_name") in selected]

    def update_selection_state(self) -> None:
        count = len(self.selected_ap_names())
        self.selection_label.setText(self.i18n.t("ap.selected_count", count=count))
        self.batch_delete_button.setEnabled(count > 0)
        self.batch_edit_button.setEnabled(count > 0)
        self.clear_selection_button.setEnabled(count > 0)
        self.invert_selection_button.setEnabled(self.resources_table.rowCount() > 0)

    def _resource_header_clicked(self, column: int) -> None:
        if column == CHECK_COLUMN:
            self._set_all_checked(len(self.selected_ap_names()) != self.resources_table.rowCount())

    def _set_all_checked(self, checked: bool) -> None:
        self.resources_table.blockSignals(True)
        for row in range(self.resources_table.rowCount()):
            item = self.resources_table.item(row, CHECK_COLUMN)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.resources_table.blockSignals(False)
        self.update_selection_state()

    def clear_selection(self) -> None:
        self._set_all_checked(False)

    def invert_selection(self) -> None:
        self.resources_table.blockSignals(True)
        for row in range(self.resources_table.rowCount()):
            item = self.resources_table.item(row, CHECK_COLUMN)
            if item:
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self.resources_table.blockSignals(False)
        self.update_selection_state()

    def batch_delete_aps(self) -> None:
        ac_uuid = self.current_device_uuid()
        names = self.selected_ap_names()
        if not ac_uuid or not names:
            return
        answer = QMessageBox.question(self, self.i18n.t("ac.title"), self.i18n.t("ap.batch_delete_confirm"))
        if answer != QMessageBox.Yes:
            return
        count = self.repository.delete_fit_aps(ac_uuid, names)
        app_logger.log_info("FIT_AP_BATCH_DELETE", f"ac={ac_uuid}, count={count}")
        self.refresh_data()

    def batch_edit_site(self) -> None:
        names = self.selected_ap_names()
        if not names:
            return
        site_name, accepted = QInputDialog.getText(self, self.i18n.t("ap.batch_edit"), self.i18n.t("ac.site"))
        if not accepted:
            return
        count = self.repository.update_fit_ap_site(names, site_name.strip())
        app_logger.log_info("FIT_AP_BATCH_EDIT_SITE", f"count={count}, site={site_name.strip()}")
        self.refresh_data()

    def import_metadata(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("ap.import_metadata"), "", "CSV Files (*.csv)")
        if not path:
            return
        result = self.import_export_service.import_metadata_csv(Path(path))
        app_logger.log_info("FIT_AP_IMPORT", f"updated={result.updated}, skipped={result.skipped}")
        self.refresh_data()

    def export_aps(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("ap.export_info"), make_fit_ap_export_filename(self.site_name), "CSV Files (*.csv)")
        if not path:
            return
        rows = self.checked_or_all_ap_rows()
        self.import_export_service.export_ap_csv(Path(path), rows)
        app_logger.log_info("FIT_AP_EXPORT", f"count={len(rows)}, file={Path(path).name}")

    def show_resource_context_menu(self, position) -> None:
        index = self.resources_table.indexAt(position)
        menu = create_table_context_menu(self.resources_table, index.row(), index.column(), self.i18n.language, include_history=False)
        menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
        detail = menu.insertAction(menu.actions()[0] if menu.actions() else None, self.i18n.t("ap.view_details"))
        detail.setEnabled(index.row() >= 0)
        detail.triggered.connect(lambda: self.open_ap_detail(index.row()))
        menu.exec(self.resources_table.viewport().mapToGlobal(position))

    def show_optical_context_menu(self, position) -> None:
        index = self.optical_table.indexAt(position)
        menu = create_table_context_menu(self.optical_table, index.row(), index.column(), self.i18n.language, include_history=False)
        menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
        detail = menu.insertAction(menu.actions()[0] if menu.actions() else None, self.i18n.t("ap.view_details"))
        detail.setEnabled(index.row() >= 0)
        detail.triggered.connect(lambda: self.open_ap_detail_from_optical(index.row()))
        menu.exec(self.optical_table.viewport().mapToGlobal(position))

    def open_ap_detail(self, row: int) -> None:
        ac_uuid = self.current_device_uuid()
        item = self.resources_table.item(row, CHECK_COLUMN)
        ap_name = str(item.data(Qt.UserRole)) if item else ""
        if not ac_uuid or not ap_name:
            return
        dialog = FitApDetailDialog(self.i18n, self.repository, ac_uuid, ap_name)
        self.detail_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_ap_detail_from_optical(self, row: int) -> None:
        ac_uuid = self.current_device_uuid()
        item = self.optical_table.item(row, 0)
        if not ac_uuid or not item:
            return
        ap_name = item.text()
        resource_rows = self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        resource_index = next((index for index, resource in enumerate(resource_rows) if resource.get("ap_name") == ap_name), -1)
        if resource_index >= 0:
            self.open_ap_detail(resource_index)
        else:
            dialog = FitApDetailDialog(self.i18n, self.repository, ac_uuid, ap_name)
            self.detail_windows.append(dialog)
            dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
            dialog.show()

    def _forget_detail_window(self, window: FitApDetailDialog) -> None:
        self.detail_windows = [item for item in self.detail_windows if item is not window]

    def _set_summary(self, row: dict[str, object | None] | None) -> None:
        for _key, field in SUMMARY_FIELDS:
            value = row.get(field) if row else None
            self.summary_labels[field].setText(str(value) if value not in (None, "") else "-")
        if row and self.summary_labels.get("cpu_usage"):
            self.summary_labels["cpu_usage"].setToolTip(
                f"5秒：{row.get('cpu_5s') or '-'}%\n1分钟：{row.get('cpu_1m') or '-'}%\n5分钟：{row.get('cpu_5m') or '-'}%"
            )

    def _set_rows(self, table: QTableWidget, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]]) -> None:
        table.blockSignals(True)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (_key, field) in enumerate(columns):
                if field == "select":
                    item = QTableWidgetItem("")
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                    item.setCheckState(Qt.Unchecked)
                    item.setData(Qt.UserRole, row.get("ap_name"))
                else:
                    value = row.get(field)
                    item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if field == "state_display":
                        item.setToolTip(f"{self.i18n.t('ap.state_raw')}: {row.get('state_raw') or row.get('state') or '-'}")
                item.setTextAlignment(Qt.AlignCenter if column_index < 2 else Qt.AlignVCenter | Qt.AlignLeft)
                table.setItem(row_index, column_index, item)
        table.blockSignals(False)
        auto_resize_table_columns(table, column_min_widths={0: 80, 1: 150})
