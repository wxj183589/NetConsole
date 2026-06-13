from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.core import app_logger
from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import DeviceImportExportService, make_device_export_filename
from netconsole.ui.dialogs.device_dialog import DeviceDialog
from netconsole.ui.windowing import DeviceDialogRegistry
from netconsole.ui.widgets.device_table import DeviceTable


def choose_devices_for_export(all_devices: list, selected_devices: list) -> list:
    return selected_devices if selected_devices else all_devices


def delete_device_ids(repository: DeviceRepository, device_ids: list[int]) -> None:
    for device_id in device_ids:
        repository.delete(device_id)


class DeviceManagementPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str = "demo") -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.service = DeviceImportExportService(repository)
        self.dialog_registry = DeviceDialogRegistry()

        self.search_input = QLineEdit()
        self.vendor_filter = QComboBox()
        self.type_filter = QComboBox()
        self.add_button = QPushButton()
        self.edit_button = QPushButton()
        self.delete_button = QPushButton()
        self.batch_delete_button = QPushButton()
        self.refresh_button = QPushButton()
        self.import_csv_button = QPushButton()
        self.export_csv_button = QPushButton()
        self.export_template_button = QPushButton()
        self.clear_selection_button = QPushButton()
        self.invert_selection_button = QPushButton()
        self.selection_label = QLabel()
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
            self.batch_delete_button,
            self.refresh_button,
            self.import_csv_button,
            self.export_csv_button,
            self.export_template_button,
            self.clear_selection_button,
            self.invert_selection_button,
        ):
            actions.addWidget(button)
        actions.addWidget(self.selection_label)
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
        self.batch_delete_button.clicked.connect(self.batch_delete_devices)
        self.refresh_button.clicked.connect(self.refresh)
        self.import_csv_button.clicked.connect(self.import_csv)
        self.export_csv_button.clicked.connect(self.export_csv)
        self.export_template_button.clicked.connect(self.export_template)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.invert_selection_button.clicked.connect(self.invert_selection)
        self.table.selection_changed.connect(self.update_selection_state)
        self.table.edit_requested.connect(self.edit_device_by_id)
        self.table.delete_requested.connect(self.delete_device_by_id)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        self.search_input.setPlaceholderText(self.i18n.t("devices.search"))
        self.add_button.setText(self.i18n.t("devices.add"))
        self.edit_button.setText(self.i18n.t("devices.edit"))
        self.delete_button.setText(self.i18n.t("devices.delete"))
        self.batch_delete_button.setText(self.i18n.t("devices.batch_delete"))
        self.refresh_button.setText(self.i18n.t("devices.refresh"))
        self.import_csv_button.setText(self.i18n.t("devices.import_csv"))
        self.export_csv_button.setText(self.i18n.t("devices.export_csv"))
        self.export_template_button.setText(self.i18n.t("devices.export_template"))
        self.clear_selection_button.setText(self.i18n.t("devices.clear_selection"))
        self.invert_selection_button.setText(self.i18n.t("devices.invert_selection"))
        self.batch_delete_button.setStyleSheet("QPushButton { color: #b91c1c; font-weight: 600; }")
        self._populate_filters()
        self.table.retranslate()
        self.update_selection_state()

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
        self.update_selection_state()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.site_name = site_name
        self.service = DeviceImportExportService(repository)
        self.dialog_registry = DeviceDialogRegistry()
        self.search_input.clear()
        self.vendor_filter.setCurrentIndex(0)
        self.type_filter.setCurrentIndex(0)
        self.refresh()

    def selected_id(self) -> int | None:
        return self.table.selected_device_id()

    def add_device(self) -> None:
        existing = self.dialog_registry.get_add_window()
        if isinstance(existing, DeviceDialog):
            self._activate_window(existing)
            return
        dialog = DeviceDialog(self.i18n, self)
        self.dialog_registry.set_add_window(dialog)
        dialog.saved.connect(self._create_device_from_dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self.dialog_registry.remove_add_window(window))
        self._show_window(dialog)

    def edit_device(self) -> None:
        if len(self.table.checked_device_ids()) > 1:
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_one_for_edit"))
            return
        device_id = self.selected_id()
        if device_id is None:
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        self.edit_device_by_id(device_id)

    def edit_device_by_id(self, device_id: int) -> None:
        device = self.repository.get(device_id)
        device_uuid = device.device_uuid or str(device.id)
        existing = self.dialog_registry.get_edit_window(device_uuid)
        if isinstance(existing, DeviceDialog):
            self._activate_window(existing)
            return
        dialog = DeviceDialog(self.i18n, self, device)
        self.dialog_registry.set_edit_window(device_uuid, dialog)
        dialog.saved.connect(self._update_device_from_dialog)
        dialog.destroyed.connect(lambda _=None, uuid=device_uuid, window=dialog: self.dialog_registry.remove_edit_window(uuid, window))
        self._show_window(dialog)

    def _show_window(self, dialog: DeviceDialog) -> None:
        dialog.show()
        self._activate_window(dialog)

    @staticmethod
    def _activate_window(dialog: DeviceDialog) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _create_device_from_dialog(self, device) -> None:
        try:
            created = self.repository.create(device)
        except Exception as exc:
            app_logger.log_error("DEVICE_CREATE_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
            return
        app_logger.log_info("DEVICE_CREATED", f"设备已新增: {created.name}")
        self.refresh()
        self._close_sender_dialog()

    def _update_device_from_dialog(self, device) -> None:
        try:
            updated = self.repository.update(device)
        except Exception as exc:
            app_logger.log_error("DEVICE_UPDATE_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
            return
        app_logger.log_info("DEVICE_UPDATED", f"设备已编辑: {updated.name}")
        self.refresh()
        self._close_sender_dialog()

    def _close_sender_dialog(self) -> None:
        sender = self.sender()
        if isinstance(sender, DeviceDialog):
            sender.close()

    def delete_device(self) -> None:
        device_id = self.selected_id()
        if device_id is None:
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        self.delete_device_by_id(device_id)

    def delete_device_by_id(self, device_id: int) -> None:
        answer = QMessageBox.question(self, self.i18n.t("devices.title"), self.i18n.t("devices.delete_confirm"))
        if answer == QMessageBox.Yes:
            device = self.repository.get(device_id)
            self.repository.delete(device_id)
            app_logger.log_info("DEVICE_DELETED", f"设备已删除: {device.name}")
            self.refresh()

    def batch_delete_devices(self) -> None:
        device_ids = self.table.checked_device_ids()
        if not device_ids:
            return
        answer = QMessageBox.question(
            self,
            self.i18n.t("devices.title"),
            self.i18n.t("devices.batch_delete_confirm", count=len(device_ids)),
        )
        if answer != QMessageBox.Yes:
            return
        delete_device_ids(self.repository, device_ids)
        app_logger.log_info("DEVICE_BATCH_DELETED", f"批量删除设备: {len(device_ids)}")
        self.refresh()

    def clear_selection(self) -> None:
        self.table.clear_checked()
        app_logger.log_info("DEVICE_SELECTION_CLEARED", "清空选择")
        self.update_selection_state()

    def invert_selection(self) -> None:
        self.table.invert_checked()
        app_logger.log_info("DEVICE_SELECTION_INVERTED", "反选")
        self.update_selection_state()

    def update_selection_state(self) -> None:
        count = len(self.table.checked_device_ids())
        self.selection_label.setText(self.i18n.t("devices.selected_count", count=count))
        self.batch_delete_button.setEnabled(count > 0)
        self.clear_selection_button.setEnabled(count > 0)
        self.invert_selection_button.setEnabled(self.table.rowCount() > 0)

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("devices.import_csv"), "", "CSV Files (*.csv)")
        if path:
            try:
                result = self.service.import_csv(Path(path))
            except Exception as exc:
                app_logger.log_error("CSV_IMPORT_FAILED", f"{Path(path).name}: {exc}")
                QMessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
                return
            self.refresh()
            app_logger.log_info("CSV_IMPORTED", f"{Path(path).name}: created={result.created}, skipped={result.skipped}")
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.import_done", created=result.created, skipped=result.skipped))

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("devices.export_csv"),
            make_device_export_filename(self.site_name),
            "CSV Files (*.csv)",
        )
        if path:
            selected_devices = self.table.checked_devices()
            try:
                self.service.export_csv(Path(path), choose_devices_for_export(self.repository.list(), selected_devices))
            except Exception as exc:
                app_logger.log_error("CSV_EXPORT_FAILED", f"{Path(path).name}: {exc}")
                QMessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
                return
            app_logger.log_info("CSV_EXPORTED", Path(path).name)
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.export_done"))

    def export_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("devices.export_template"),
            self.i18n.t("devices.template_filename"),
            "CSV Files (*.csv)",
        )
        if path:
            try:
                self.service.export_template_csv(Path(path))
            except Exception as exc:
                app_logger.log_error("CSV_TEMPLATE_EXPORT_FAILED", f"{Path(path).name}: {exc}")
                QMessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
                return
            app_logger.log_info("CSV_TEMPLATE_EXPORTED", Path(path).name)
            QMessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.template_done"))
