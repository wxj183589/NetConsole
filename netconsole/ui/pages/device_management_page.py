from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import DeviceImportExportService, make_device_export_filename
from netconsole.ui.dialogs.device_dialog import DeviceDialog
from netconsole.ui.widgets.device_table import DeviceTable


class DeviceManagementPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str = "demo") -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.service = DeviceImportExportService(repository)

        self.search_input = QLineEdit()
        self.vendor_filter = QComboBox()
        self.type_filter = QComboBox()
        self.add_button = QPushButton()
        self.edit_button = QPushButton()
        self.delete_button = QPushButton()
        self.refresh_button = QPushButton()
        self.import_csv_button = QPushButton()
        self.export_csv_button = QPushButton()
        self.export_template_button = QPushButton()
        self.table = DeviceTable(i18n)

        filters = QHBoxLayout()
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.vendor_filter)
        filters.addWidget(self.type_filter)

        actions = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.refresh_button,
            self.import_csv_button,
            self.export_csv_button,
            self.export_template_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(filters)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)
        self.setLayout(layout)

        self.search_input.textChanged.connect(self.refresh)
        self.vendor_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.add_button.clicked.connect(self.add_device)
        self.edit_button.clicked.connect(self.edit_device)
        self.delete_button.clicked.connect(self.delete_device)
        self.refresh_button.clicked.connect(self.refresh)
        self.import_csv_button.clicked.connect(self.import_csv)
        self.export_csv_button.clicked.connect(self.export_csv)
        self.export_template_button.clicked.connect(self.export_template)
        self.table.doubleClicked.connect(self.edit_device)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        self.search_input.setPlaceholderText(self.i18n.t("devices.search"))
        self.add_button.setText(self.i18n.t("devices.add"))
        self.edit_button.setText(self.i18n.t("devices.edit"))
        self.delete_button.setText(self.i18n.t("devices.delete"))
        self.refresh_button.setText(self.i18n.t("devices.refresh"))
        self.import_csv_button.setText(self.i18n.t("devices.import_csv"))
        self.export_csv_button.setText(self.i18n.t("devices.export_csv"))
        self.export_template_button.setText(self.i18n.t("devices.export_template"))
        self._populate_filters()
        self.table.retranslate()

    def _populate_filters(self) -> None:
        vendor = self.vendor_filter.currentData()
        dtype = self.type_filter.currentData()
        self.vendor_filter.blockSignals(True)
        self.type_filter.blockSignals(True)
        self.vendor_filter.clear()
        self.type_filter.clear()
        self.vendor_filter.addItem(self.i18n.t("devices.vendor.all"), None)
        self.type_filter.addItem(self.i18n.t("devices.type.all"), None)
        for item in DEVICE_VENDORS:
            self.vendor_filter.addItem(item, item)
        for item in DEVICE_TYPES:
            self.type_filter.addItem(item, item)
        self._restore_combo_value(self.vendor_filter, vendor)
        self._restore_combo_value(self.type_filter, dtype)
        self.vendor_filter.blockSignals(False)
        self.type_filter.blockSignals(False)

    @staticmethod
    def _restore_combo_value(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def refresh(self) -> None:
        devices = self.repository.list(
            search=self.search_input.text().strip() or None,
            vendor=self.vendor_filter.currentData(),
            device_type=self.type_filter.currentData(),
        )
        self.table.set_devices(devices)

    def selected_id(self) -> int | None:
        return self.table.selected_device_id()

    def add_device(self) -> None:
        dialog = DeviceDialog(self.i18n, self)
        if dialog.exec():
            self.repository.create(dialog.device())
            self.refresh()

    def edit_device(self) -> None:
        device_id = self.selected_id()
        if device_id is None:
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        device = self.repository.get(device_id)
        dialog = DeviceDialog(self.i18n, self, device)
        if dialog.exec():
            self.repository.update(dialog.device())
            self.refresh()

    def delete_device(self) -> None:
        device_id = self.selected_id()
        if device_id is None:
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        answer = QMessageBox.question(self, self.i18n.t("devices.title"), self.i18n.t("devices.delete_confirm"))
        if answer == QMessageBox.Yes:
            self.repository.delete(device_id)
            self.refresh()

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("devices.import_csv"), "", "CSV Files (*.csv)")
        if path:
            result = self.service.import_csv(Path(path))
            self.refresh()
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.import_done", created=result.created, skipped=result.skipped))

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("devices.export_csv"),
            make_device_export_filename(self.site_name),
            "CSV Files (*.csv)",
        )
        if path:
            self.service.export_csv(Path(path), self.repository.list())
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.export_done"))

    def export_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("devices.export_template"),
            self.i18n.t("devices.template_filename"),
            "CSV Files (*.csv)",
        )
        if path:
            self.service.export_template_csv(Path(path))
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.template_done"))
