from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.ui.dialogs.input_dialog_service import InputDialog
import os
from pathlib import Path
import platform
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.core import app_logger
from netconsole.core.feature_flags import FeatureGate, apply_feature_to_widget, default_feature_gate
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS
from netconsole.models.omnipeek_name_table import SOURCE_AC_FIT_AP, SOURCE_AP_EXTENSION, SOURCE_DEVICE_MANAGEMENT
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_import_export import DeviceImportExportService, make_device_export_filename
from netconsole.services.diagnostic_download_service import DiagnosticDownloadService
from netconsole.services.device_group_service import ALL_GROUPS, UNGROUPED, DeviceGroupService, group_filter_to_repository_value
from netconsole.services.external_terminal import TERMINAL_LABELS, available_external_terminal_configs, launch_external_terminal
from netconsole.services.omnipeek_name_table_service import OmniPeekNameTableService, default_omnipeek_line_name
from netconsole.services.securecrt_session_export import export_securecrt_sessions
from netconsole.services.netmiko_connection import ConnectionTestResult
from netconsole.ui.batch_connection_worker import BATCH_CONNECTION_DEFAULT_CONCURRENCY, BatchConnectionTestWorker
from netconsole.ui.batch_collect_worker import BATCH_CONCURRENCY, BatchCollectWorker
from netconsole.ui.connection_worker import DeviceConnectionTestThread
from netconsole.ui.diagnostic_download_worker import DiagnosticDownloadWorker
from netconsole.ui.dialogs.batch_connection_test_progress_dialog import BatchConnectionTestProgressDialog
from netconsole.ui.dialogs.batch_collect_progress_dialog import BatchCollectProgressDialog
from netconsole.ui.dialogs.device_detail_dialog import DeviceDetailDialog
from netconsole.ui.dialogs.device_dialog import DeviceDialog
from netconsole.ui.dialogs.device_group_dialog import DeviceGroupDialog
from netconsole.ui.dialogs.external_terminal_settings_dialog import ExternalTerminalSettingsDialog
from netconsole.ui.dialogs.omnipeek_export_dialog import OmniPeekExportDialog
from netconsole.ui.export_path import CSV_FILTER, remember_export_path, select_export_path
from netconsole.ui.shell.fluent_bridge import FIF
from netconsole.ui.window_manager import window_manager
from netconsole.ui.window_popup_service import show_non_focus_window
from netconsole.ui.windowing import DeviceDialogRegistry
from netconsole.ui.widgets.device_table import DeviceTable


def choose_devices_for_export(all_devices: list, selected_devices: list) -> list:
    return selected_devices if selected_devices else all_devices


def delete_device_ids(repository: DeviceRepository, device_ids: list[int]) -> None:
    for device_id in device_ids:
        repository.delete(device_id)


def select_device_id_for_connection(checked_ids: list[int], current_id: int | None) -> tuple[int | None, str | None]:
    if len(checked_ids) > 1:
        return None, "devices.select_one_for_test"
    if len(checked_ids) == 1:
        return checked_ids[0], None
    if current_id is None:
        return None, "devices.select_first_test"
    return current_id, None


def open_diagnostic_folder_for_results(results, site_name: str, paths: PathResolver | None = None) -> bool:
    paths = paths or PathResolver()
    successful_files = [
        paths.site_dir(site_name) / item.file_path
        for item in results
        if getattr(item, "success", False) and getattr(item, "file_path", None)
    ]
    existing_files = [path for path in successful_files if path.exists()]
    if not existing_files:
        return True
    latest_file = max(existing_files, key=lambda path: path.stat().st_mtime)
    folder_path = latest_file.parent
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(folder_path))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(folder_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder_path)], check=False)
        app_logger.log_info("DIAGNOSTIC_FOLDER_OPENED", f"folder={folder_path}, latest_file={latest_file.name}")
        return True
    except Exception as exc:
        app_logger.log_error("DIAGNOSTIC_FOLDER_OPEN_FAILED", f"folder={folder_path}, error={exc}")
        return False


def _set_button_icon(button: QPushButton, icon: object | None) -> None:
    if icon is None:
        return
    icon_factory = getattr(icon, "icon", None)
    resolved_icon = icon_factory() if callable(icon_factory) else icon
    try:
        button.setIcon(resolved_icon)
    except TypeError:
        pass


class DeviceManagementPage(QWidget):
    groups_changed = Signal()
    devices_changed = Signal()

    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str = "demo", feature_gate: FeatureGate | None = None) -> None:
        super().__init__()
        self.repository = repository
        self.fact_repository = DeviceFactRepository(repository.database)
        self.group_repository = self._make_group_repository(repository, site_name)
        self.group_service = DeviceGroupService(repository, self.group_repository) if self.group_repository is not None else None
        self.i18n = i18n
        self.site_name = site_name
        self.service = DeviceImportExportService(repository, self.group_repository)
        self.paths = PathResolver()
        self.settings = SettingsStore(self.paths)
        self.feature_gate = feature_gate or default_feature_gate()
        self.dialog_registry = DeviceDialogRegistry()
        self.detail_dialogs: dict[str, DeviceDetailDialog] = {}
        self.group_dialog: DeviceGroupDialog | None = None
        self.external_terminal_settings_dialog: ExternalTerminalSettingsDialog | None = None

        self.search_input = QLineEdit()
        self.vendor_filter = QComboBox()
        self.type_filter = QComboBox()
        self.group_filter = QComboBox()
        self.add_button = QPushButton()
        self.detail_button = QPushButton()
        self.test_connection_button = QPushButton()
        self.diagnostic_download_button = QPushButton()
        self.external_terminal_button = QPushButton()
        self.generate_crt_sessions_button = QPushButton()
        self.manage_groups_button = QPushButton()
        self.assign_group_button = QPushButton()
        self.batch_refresh_details_button = QPushButton()
        self.batch_delete_button = QPushButton()
        self.refresh_button = QPushButton()
        self.import_csv_button = QPushButton()
        self.export_csv_button = QPushButton()
        self.export_template_button = QPushButton()
        self.more_button = QPushButton()
        self.more_menu = QMenu(self)
        self.export_omnipeek_action = self.more_menu.addAction("导出 OmniPeek 名称表")
        self.more_button.setMenu(self.more_menu)
        self.clear_selection_button = QPushButton()
        self.invert_selection_button = QPushButton()
        self.selection_label = QLabel()
        self.table = DeviceTable(i18n)

        self.search_input.setMinimumWidth(240)
        self.search_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.vendor_filter.setFixedWidth(130)
        self.type_filter.setFixedWidth(130)
        self.group_filter.setFixedWidth(170)
        self.selection_label.setMinimumWidth(130)
        self.selection_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.vendor_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.group_filter)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.action_content = QWidget()
        self.external_terminal_button.setParent(self.action_content)
        for button in (
            self.add_button,
            self.test_connection_button,
            self.external_terminal_button,
            self.generate_crt_sessions_button,
            self.clear_selection_button,
            self.invert_selection_button,
            self.batch_delete_button,
            self.diagnostic_download_button,
            self.manage_groups_button,
            self.assign_group_button,
            self.batch_refresh_details_button,
            self.import_csv_button,
            self.export_csv_button,
            self.export_template_button,
            self.more_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        self.action_content.setLayout(actions)
        self.action_scroll = QScrollArea()
        self.action_scroll.setFrameShape(QFrame.NoFrame)
        self.action_scroll.setWidgetResizable(False)
        self.action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.action_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.action_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.action_scroll.setWidget(self.action_content)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.action_scroll, 1)
        action_row.addWidget(self.selection_label)

        layout = QVBoxLayout()
        layout.addLayout(filters)
        layout.addLayout(action_row)
        layout.addWidget(self.table, 1)
        self.setLayout(layout)

        self.search_input.textChanged.connect(self.refresh)
        self.vendor_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.group_filter.currentIndexChanged.connect(self.refresh)
        self.add_button.clicked.connect(self.add_device)
        self.detail_button.clicked.connect(self.show_selected_device_detail)
        self.test_connection_button.clicked.connect(self.test_selected_device_connection)
        self.diagnostic_download_button.clicked.connect(self.download_diagnostics)
        self.external_terminal_button.clicked.connect(self.open_external_terminal_settings)
        self.generate_crt_sessions_button.clicked.connect(self.generate_securecrt_sessions)
        self.manage_groups_button.clicked.connect(self.manage_groups)
        self.assign_group_button.clicked.connect(self.assign_group)
        self.batch_refresh_details_button.clicked.connect(self.batch_refresh_details)
        self.batch_delete_button.clicked.connect(self.batch_delete_devices)
        self.refresh_button.clicked.connect(self.refresh)
        self.import_csv_button.clicked.connect(self.import_csv)
        self.export_csv_button.clicked.connect(self.export_csv)
        self.export_template_button.clicked.connect(self.export_template)
        self.export_omnipeek_action.triggered.connect(self.export_omnipeek_name_table)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.invert_selection_button.clicked.connect(self.invert_selection)
        self.table.selection_changed.connect(self.update_selection_state)
        self.table.detail_requested.connect(self.show_device_detail)
        self.table.edit_requested.connect(self.edit_device_by_id)
        self.table.delete_requested.connect(self.delete_device_by_id)
        self.table.external_terminal_requested.connect(self.launch_external_terminal_for_device_id)
        self.retranslate()
        self.refresh()
        self.connection_test_thread: DeviceConnectionTestThread | None = None
        self.batch_connection_test_worker: BatchConnectionTestWorker | None = None
        self.batch_connection_test_dialog: BatchConnectionTestProgressDialog | None = None
        self.batch_collect_worker: BatchCollectWorker | None = None
        self.batch_collect_dialog: BatchCollectProgressDialog | None = None
        apply_feature_to_widget(self.feature_gate, "devices.external_terminal", self.external_terminal_button)
        self.table.set_external_terminal_action_state(
            visible=self.feature_gate.is_visible("devices.external_terminal"),
            enabled=self.feature_gate.is_enabled("devices.external_terminal"),
        )
        apply_feature_to_widget(self.feature_gate, "devices.securecrt_sessions", self.generate_crt_sessions_button)
        self._sync_omnipeek_action_state()
        self.diagnostic_download_worker: DiagnosticDownloadWorker | None = None

    def retranslate(self) -> None:
        self.search_input.setPlaceholderText(self.i18n.t("devices.search"))
        self.add_button.setText(self.i18n.t("devices.add"))
        self.detail_button.setText(self.i18n.t("details.title"))
        self.test_connection_button.setText(self.i18n.t("devices.test_connection"))
        self.diagnostic_download_button.setText(self.i18n.t("devices.diagnostic_download"))
        self.external_terminal_button.setText(self.i18n.t("devices.external_terminal_config"))
        self.generate_crt_sessions_button.setText(self.i18n.t("devices.generate_crt_sessions"))
        self.manage_groups_button.setText(self.i18n.t("groups.manage_groups"))
        self.assign_group_button.setText(self.i18n.t("groups.assign_group"))
        self.batch_refresh_details_button.setText(self.i18n.t("devices.batch_refresh_details"))
        self.batch_delete_button.setText(self.i18n.t("devices.batch_delete"))
        self.refresh_button.setText(self.i18n.t("devices.refresh"))
        self.import_csv_button.setText(self.i18n.t("devices.import_csv"))
        self.export_csv_button.setText(self.i18n.t("devices.export_csv"))
        self.export_template_button.setText(self.i18n.t("devices.export_template"))
        self.more_button.setText("更多")
        self.export_omnipeek_action.setText("导出 OmniPeek 名称表")
        self.clear_selection_button.setText(self.i18n.t("devices.clear_selection"))
        self.invert_selection_button.setText(self.i18n.t("devices.invert_selection"))
        self.batch_delete_button.setObjectName("dangerButton")
        _set_button_icon(self.more_button, getattr(FIF, "MORE", None) or getattr(FIF, "APPLICATION", None))
        self._populate_filters()
        self.table.retranslate()
        self._sync_omnipeek_action_state()
        self._sync_action_scroll_width()
        self.update_selection_state()

    def _sync_action_scroll_width(self) -> None:
        self.action_content.adjustSize()
        self.action_content.setMinimumWidth(self.action_content.sizeHint().width())

    def test_selected_device_connection(self) -> None:
        checked_ids = self.table.checked_device_ids()
        if not checked_ids:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        if len(checked_ids) > 1:
            self.batch_test_connections([self.repository.get(device_id) for device_id in checked_ids])
            return
        device_id = checked_ids[0]
        device = self.repository.get(device_id)
        self.test_connection_button.setEnabled(False)
        self.test_connection_button.setText(self.i18n.t("devices.testing_connection"))
        self.connection_test_thread = DeviceConnectionTestThread(device, self)
        self.connection_test_thread.result_ready.connect(self._show_connection_result)
        self.connection_test_thread.finished.connect(self.connection_test_thread.deleteLater)
        self.connection_test_thread.finished.connect(lambda: setattr(self, "connection_test_thread", None))
        self.connection_test_thread.start()

    def batch_test_connections(self, devices) -> None:
        dialog = BatchConnectionTestProgressDialog(self.i18n, len(devices), self)
        for row, device in enumerate(devices):
            dialog.mark_waiting(row, str(device.name or ""), str(device.ip_address or ""))
        self.batch_connection_test_dialog = dialog
        self.batch_connection_test_worker = BatchConnectionTestWorker(devices, concurrency=int(dialog.concurrency_combo.currentData() or BATCH_CONNECTION_DEFAULT_CONCURRENCY), parent=self)

        def on_device_finished(item) -> None:
            row = next(
                (
                    index
                    for index in range(dialog.table.rowCount())
                    if dialog.table.item(index, 0) and dialog.table.item(index, 0).text() == item.device_name
                ),
                dialog.completed,
            )
            dialog.add_result(row, item)

        self.batch_connection_test_worker.device_finished.connect(on_device_finished)
        self.batch_connection_test_worker.finished.connect(self.batch_connection_test_worker.deleteLater)
        self.batch_connection_test_worker.finished.connect(lambda: setattr(self, "batch_connection_test_worker", None))
        show_non_focus_window(self, dialog, key="batch_connection_test_progress", activate=False, raise_window=False)
        self.batch_connection_test_worker.start()

    def _show_connection_result(self, result: ConnectionTestResult) -> None:
        self.test_connection_button.setEnabled(True)
        self.test_connection_button.setText(self.i18n.t("devices.test_connection"))
        if result.success:
            message = self.i18n.t(
                "connection.success_detail",
                protocol=result.protocol,
                host=f"{result.host}:{result.port}",
                prompt=result.prompt or "-",
                elapsed=result.elapsed_ms if result.elapsed_ms is not None else "-",
            )
            MessageBox.information(self, self.i18n.t("connection.success_title"), message)
        else:
            MessageBox.warning(
                self,
                self.i18n.t("connection.failed_title"),
                self.i18n.t("connection.failed_detail", reason=result.message),
            )

    def launch_external_terminal_for_selection(self) -> None:
        devices = self._external_terminal_target_devices()
        if not devices:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        if len(devices) > 20:
            answer = MessageBox.question(self, self.i18n.t("devices.external_terminal"), self.i18n.t("external_terminal.confirm_many", count=len(devices)))
            if answer != MessageBox.Yes:
                return
        config = self._select_external_terminal_config()
        if config is None:
            return
        success = 0
        failures: list[str] = []
        for device in devices:
            result = launch_external_terminal(device, config)
            if result.success:
                success += 1
            else:
                failures.append(f"{device.name or device.primary_address}: {result.message}")
        message = self.i18n.t("external_terminal.launch_done", success=success, failed=len(failures))
        if failures:
            message = f"{message}\n\n" + "\n".join(failures[:10])
            MessageBox.warning(self, self.i18n.t("devices.external_terminal"), message)
        else:
            MessageBox.information(self, self.i18n.t("devices.external_terminal"), message)

    def launch_external_terminal_for_device_id(self, device_id: int) -> None:
        device = self.repository.get(device_id)
        config = self._select_external_terminal_config()
        if config is None:
            return
        result = launch_external_terminal(device, config)
        if result.success:
            MessageBox.information(self, self.i18n.t("devices.external_terminal"), result.message)
        else:
            MessageBox.warning(self, self.i18n.t("devices.external_terminal"), result.message)

    def _select_external_terminal_config(self):
        configs = available_external_terminal_configs(self.settings)
        if not configs:
            MessageBox.information(
                self,
                self.i18n.t("devices.external_terminal"),
                self.i18n.t("external_terminal.not_configured"),
            )
            return None
        if len(configs) == 1:
            return configs[0]
        labels = [TERMINAL_LABELS.get(config.terminal_type, config.terminal_type) for config in configs]
        label, accepted = InputDialog.getItem(
            self,
            self.i18n.t("external_terminal.select_terminal"),
            self.i18n.t("external_terminal.select_terminal"),
            labels,
            0,
            False,
        )
        if not accepted:
            return None
        return configs[labels.index(label)]

    def open_external_terminal_settings(self) -> None:
        if self.external_terminal_settings_dialog is not None:
            self._activate_window(self.external_terminal_settings_dialog)
            return
        dialog = ExternalTerminalSettingsDialog(self.i18n, self.settings, self)
        self.external_terminal_settings_dialog = dialog
        dialog.destroyed.connect(lambda _=None: setattr(self, "external_terminal_settings_dialog", None))
        show_non_focus_window(self, dialog, key="external_terminal_settings", activate=False, raise_window=False)

    def generate_securecrt_sessions(self) -> None:
        devices = self.table.checked_devices() or self._filtered_devices()
        if not devices:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        output_dir = QFileDialog.getExistingDirectory(self, self.i18n.t("external_terminal.select_output_dir"), "")
        if not output_dir:
            return
        template_path, _ = QFileDialog.getOpenFileName(
            self,
            self.i18n.t("external_terminal.select_template_ini"),
            "",
            "SecureCRT Session (*.ini);;All Files (*)",
        )
        template = Path(template_path) if template_path else Path()
        group_names = {int(group.id): group.name for group in self._list_groups() if group.id is not None}
        result = export_securecrt_sessions(
            devices,
            self.site_name,
            Path(output_dir),
            group_names=group_names,
            template_ini=template if template.is_file() else None,
        )
        self._open_folder(result.output_dir)
        MessageBox.information(
            self,
            self.i18n.t("devices.generate_crt_sessions"),
            self.i18n.t("external_terminal.export_done", generated=result.generated, skipped=result.skipped, path=result.output_dir),
        )

    def _external_terminal_target_devices(self):
        checked = self.table.checked_devices()
        if checked:
            return checked
        current_id = self.selected_id()
        return [self.repository.get(current_id)] if current_id is not None else []

    def _filtered_devices(self):
        selected_group_data = self.group_filter.currentData()
        return self.repository.list(
            search=self.search_input.text().strip() or None,
            vendor=self.vendor_filter.currentData(),
            device_type=self.type_filter.currentData(),
            group_filter=self._repository_group_filter_value(selected_group_data),
        )

    def _repository_group_filter_value(self, value: object) -> int | str | None:
        try:
            return group_filter_to_repository_value(value)
        except (TypeError, ValueError) as exc:
            app_logger.log_warning(
                "DEVICE_GROUP_FILTER_INVALID_VALUE",
                f"site_name={self.site_name}, selected_text={self.group_filter.currentText()}, selected_data={value}, error={exc}",
            )
            return None

    @staticmethod
    def _open_folder(path: Path) -> None:
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:
            app_logger.log_warning("OPEN_FOLDER_FAILED", f"{path}: {exc}")

    def download_diagnostics(self) -> None:
        devices = self._diagnostic_target_devices()
        if not devices:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        self.diagnostic_download_button.setEnabled(False)
        self.diagnostic_download_button.setText(self.i18n.t("devices.diagnostic_downloading"))
        service = DiagnosticDownloadService(self.site_name)
        self.diagnostic_download_worker = DiagnosticDownloadWorker(service, devices, self)
        self.diagnostic_download_worker.result_ready.connect(self._handle_diagnostic_results)
        self.diagnostic_download_worker.finished.connect(self.diagnostic_download_worker.deleteLater)
        self.diagnostic_download_worker.finished.connect(lambda: setattr(self, "diagnostic_download_worker", None))
        self.diagnostic_download_worker.start()

    def _diagnostic_target_devices(self):
        checked_ids = self.table.checked_device_ids()
        if checked_ids:
            return [self.repository.get(device_id) for device_id in checked_ids]
        current_id = self.selected_id()
        if current_id is None:
            return []
        return [self.repository.get(current_id)]

    def _handle_diagnostic_results(self, results) -> None:
        self.diagnostic_download_button.setEnabled(True)
        self.diagnostic_download_button.setText(self.i18n.t("devices.diagnostic_download"))
        success = sum(1 for item in results if item.success)
        failed = len(results) - success
        detail = "\n".join(
            f"{item.device_name}: {self.i18n.t('devices.diagnostic_status_success' if item.success else 'devices.diagnostic_status_failed')}"
            + (f" - {item.error_message}" if item.error_message else "")
            for item in results
        )
        message = self.i18n.t("devices.diagnostic_done", success=success, failed=failed)
        if detail:
            message = f"{message}\n\n{detail}"
        folder_opened = open_diagnostic_folder_for_results(results, self.site_name)
        if not folder_opened:
            message = f"{message}\n\n{self.i18n.t('devices.diagnostic_open_folder_failed')}"
        if failed:
            MessageBox.warning(self, self.i18n.t("devices.diagnostic_download"), message)
        else:
            MessageBox.information(self, self.i18n.t("devices.diagnostic_download"), message)

    def _populate_filters(self) -> None:
        vendor = self.vendor_filter.currentData()
        dtype = self.type_filter.currentData()
        group = self.group_filter.currentData()
        self.vendor_filter.blockSignals(True)
        self.type_filter.blockSignals(True)
        self.group_filter.blockSignals(True)
        self.vendor_filter.clear()
        self.type_filter.clear()
        self.group_filter.clear()
        self.vendor_filter.addItem(self.i18n.t("devices.vendor.all"), None)
        self.type_filter.addItem(self.i18n.t("devices.type.all"), None)
        self.group_filter.addItem(self.i18n.t("groups.all_groups"), ALL_GROUPS)
        self.group_filter.addItem(self.i18n.t("groups.ungrouped"), UNGROUPED)
        for item in self._list_groups():
            self.group_filter.addItem(item.name, item.id)
        for item in DEVICE_VENDORS:
            self.vendor_filter.addItem(item, item)
        for item in DEVICE_TYPES:
            self.type_filter.addItem(item, item)
        self._restore_combo_value(self.vendor_filter, vendor)
        self._restore_combo_value(self.type_filter, dtype)
        self._restore_combo_value(self.group_filter, group if group is not None else ALL_GROUPS)
        self.vendor_filter.blockSignals(False)
        self.type_filter.blockSignals(False)
        self.group_filter.blockSignals(False)

    @staticmethod
    def _restore_combo_value(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _make_group_repository(repository: DeviceRepository, site_name: str) -> DeviceGroupRepository | None:
        database = getattr(repository, "database", None)
        return DeviceGroupRepository(database, site_name) if database is not None else None

    def _list_groups(self):
        if self.group_repository is None:
            return []
        try:
            return self.group_repository.list()
        except Exception as exc:
            app_logger.log_warning("DEVICE_GROUP_LIST_FAILED", str(exc))
            return []

    def refresh(self) -> None:
        selected_group_data = self.group_filter.currentData()
        repository_group_filter = self._repository_group_filter_value(selected_group_data)
        devices = self.repository.list(
            search=self.search_input.text().strip() or None,
            vendor=self.vendor_filter.currentData(),
            device_type=self.type_filter.currentData(),
            group_filter=repository_group_filter,
        )
        app_logger.log_info(
            "DEVICE_GROUP_FILTER_APPLIED",
            (
                f"site_name={self.site_name}, selected_text={self.group_filter.currentText()}, "
                f"selected_data={selected_group_data}, selected_data_type={type(selected_group_data).__name__}, "
                f"repository_filter_value={repository_group_filter}, result_count={len(devices)}"
            ),
        )
        self.table.set_group_names({int(group.id): group.name for group in self._list_groups() if group.id is not None})
        self.table.set_external_terminal_action_state(
            visible=self.feature_gate.is_visible("devices.external_terminal"),
            enabled=self.feature_gate.is_enabled("devices.external_terminal"),
        )
        self.table.set_devices(devices)
        self.update_selection_state()

    def refresh_groups(self) -> None:
        self._populate_filters()
        self.refresh()

    def manage_groups(self) -> None:
        if self.group_repository is None:
            return
        if self.group_dialog is not None:
            self._activate_window(self.group_dialog)
            return
        dialog = DeviceGroupDialog(self.i18n, self.group_repository, self)
        self.group_dialog = dialog
        dialog.groups_changed.connect(self._handle_groups_changed)
        dialog.destroyed.connect(lambda _=None: setattr(self, "group_dialog", None))
        self._show_window(dialog)

    def _handle_groups_changed(self) -> None:
        self.refresh_groups()
        self.groups_changed.emit()

    def assign_group(self) -> None:
        device_ids = self.table.checked_device_ids()
        if not device_ids or self.group_service is None:
            return
        groups = self._list_groups()
        labels = [self.i18n.t("groups.ungrouped")] + [group.name for group in groups]
        label, accepted = InputDialog.getItem(self, self.i18n.t("groups.assign_group"), self.i18n.t("groups.select_group"), labels, 0, False)
        if not accepted:
            return
        group_id = None
        if label != self.i18n.t("groups.ungrouped"):
            group = next((item for item in groups if item.name == label), None)
            group_id = int(group.id) if group and group.id is not None else None
        result = self.group_service.assign_devices(device_ids, group_id)
        MessageBox.information(self, self.i18n.t("groups.assign_group"), self.i18n.t("groups.assign_done", success=result.success, failed=result.failed))
        self.clear_selection()
        self.refresh_groups()
        self.groups_changed.emit()
        self.devices_changed.emit()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.fact_repository = DeviceFactRepository(repository.database)
        self.group_repository = self._make_group_repository(repository, site_name)
        self.group_service = DeviceGroupService(repository, self.group_repository) if self.group_repository is not None else None
        self.site_name = site_name
        self.service = DeviceImportExportService(repository, self.group_repository)
        self.dialog_registry = DeviceDialogRegistry()
        self.detail_dialogs = {}
        self.group_dialog = None
        self.external_terminal_settings_dialog = None
        self.search_input.clear()
        self.vendor_filter.setCurrentIndex(0)
        self.type_filter.setCurrentIndex(0)
        self._populate_filters()
        self.group_filter.setCurrentIndex(0)
        self.refresh()

    def selected_id(self) -> int | None:
        return self.table.selected_device_id()

    def add_device(self) -> None:
        existing = self.dialog_registry.get_add_window()
        if isinstance(existing, DeviceDialog):
            self._activate_window(existing)
            return
        dialog = DeviceDialog(self.i18n, None, groups=self._list_groups())
        self.dialog_registry.set_add_window(dialog)
        dialog.saved.connect(self._create_device_from_dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self.dialog_registry.remove_add_window(window))
        self._show_window(dialog)

    def edit_device(self) -> None:
        if len(self.table.checked_device_ids()) > 1:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_one_for_edit"))
            return
        device_id = self.selected_id()
        if device_id is None:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        self.edit_device_by_id(device_id)

    def edit_device_by_id(self, device_id: int) -> None:
        device = self.repository.get(device_id)
        device_uuid = device.device_uuid or str(device.id)
        existing = self.dialog_registry.get_edit_window(device_uuid)
        if isinstance(existing, DeviceDialog):
            self._activate_window(existing)
            return
        dialog = DeviceDialog(self.i18n, None, device, groups=self._list_groups())
        self.dialog_registry.set_edit_window(device_uuid, dialog)
        dialog.saved.connect(self._update_device_from_dialog)
        dialog.destroyed.connect(lambda _=None, uuid=device_uuid, window=dialog: self.dialog_registry.remove_edit_window(uuid, window))
        self._show_window(dialog)

    def show_device_detail(self, device_id: int) -> None:
        device = self.repository.get(device_id)
        device.ensure_device_uuid()
        detail_key = str(device.device_uuid or device.id)
        existing = self.detail_dialogs.get(detail_key)
        if isinstance(existing, DeviceDetailDialog):
            show_non_focus_window(self, existing, key=f"device_detail:{detail_key}", activate=False, raise_window=False)
            return
        dialog = DeviceDetailDialog(
            self.i18n,
            self.fact_repository,
            device,
            None,
            self.site_name,
            {int(group.id): group.name for group in self._list_groups() if group.id is not None},
        )
        self.detail_dialogs[detail_key] = dialog
        window_manager.register_child_window(dialog)
        dialog.destroyed.connect(lambda _=None, key=detail_key, window=dialog: self._remove_detail_dialog(key, window))
        show_non_focus_window(self, dialog, key=f"device_detail:{detail_key}", activate=False, raise_window=False)

    def _remove_detail_dialog(self, detail_key: str, dialog: DeviceDetailDialog) -> None:
        if self.detail_dialogs.get(detail_key) is dialog:
            self.detail_dialogs.pop(detail_key, None)
        window_manager.unregister_child_window(dialog)

    def show_selected_device_detail(self) -> None:
        device_id = self.selected_id()
        if device_id is None:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        self.show_device_detail(device_id)

    def _show_window(self, dialog: DeviceDialog) -> None:
        self._activate_window(dialog)

    @staticmethod
    def _activate_window(dialog: DeviceDialog) -> None:
        show_non_focus_window(dialog.parentWidget(), dialog, key="device_dialog", activate=False, raise_window=False)

    def _create_device_from_dialog(self, device) -> None:
        try:
            created = self.repository.create(device)
        except Exception as exc:
            app_logger.log_error("DEVICE_CREATE_FAILED", str(exc))
            MessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
            return
        app_logger.log_info("DEVICE_CREATED", f"设备已新增: {created.name}")
        self.refresh()
        self.devices_changed.emit()
        self._close_sender_dialog()

    def _update_device_from_dialog(self, device) -> None:
        try:
            updated = self.repository.update(device)
        except Exception as exc:
            app_logger.log_error("DEVICE_UPDATE_FAILED", str(exc))
            MessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
            return
        app_logger.log_info("DEVICE_UPDATED", f"设备已编辑: {updated.name}")
        self.refresh()
        self.devices_changed.emit()
        self._close_sender_dialog()

    def _close_sender_dialog(self) -> None:
        sender = self.sender()
        if isinstance(sender, DeviceDialog):
            sender.close()

    def delete_device(self) -> None:
        device_id = self.selected_id()
        if device_id is None:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        self.delete_device_by_id(device_id)

    def delete_device_by_id(self, device_id: int) -> None:
        answer = MessageBox.question(self, self.i18n.t("devices.title"), self.i18n.t("devices.delete_confirm"))
        if answer == MessageBox.Yes:
            device = self.repository.get(device_id)
            self.repository.delete(device_id)
            app_logger.log_info("DEVICE_DELETED", f"设备已删除: {device.name}")
            self.refresh()
            self.devices_changed.emit()

    def batch_delete_devices(self) -> None:
        device_ids = self.table.checked_device_ids()
        if not device_ids:
            return
        answer = MessageBox.question(
            self,
            self.i18n.t("devices.title"),
            self.i18n.t("devices.batch_delete_confirm", count=len(device_ids)),
        )
        if answer != MessageBox.Yes:
            return
        delete_device_ids(self.repository, device_ids)
        app_logger.log_info("DEVICE_BATCH_DELETED", f"批量删除设备: {len(device_ids)}")
        self.refresh()
        self.devices_changed.emit()

    def batch_refresh_details(self) -> None:
        device_ids = self.table.checked_device_ids()
        if not device_ids:
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.select_first"))
            return
        devices = [self.repository.get(device_id) for device_id in device_ids]
        answer = MessageBox.question(
            self,
            self.i18n.t("devices.title"),
            self.i18n.t("devices.batch_refresh_confirm", count=len(devices)),
        )
        if answer != MessageBox.Yes:
            return
        dialog = BatchCollectProgressDialog(self.i18n, len(devices), self)
        for row, device in enumerate(devices):
            dialog.mark_running(row, str(device.name or ""), str(device.ip_address or ""))
            item = dialog.table.item(row, 2)
            if item:
                item.setText(self.i18n.t("batch_collect.status.waiting"))
            dialog.running = max(0, dialog.running - 1)
        dialog.update_summary()
        self.batch_collect_dialog = dialog
        start_concurrency = int(dialog.concurrency_combo.currentData() or BATCH_CONCURRENCY)
        dialog.set_running(True)
        self.batch_collect_worker = BatchCollectWorker(devices, self.site_name, max_workers=start_concurrency, parent=self)

        def on_device_finished(item) -> None:
            row = next(
                (
                    index
                    for index in range(dialog.table.rowCount())
                    if dialog.table.item(index, 0) and dialog.table.item(index, 0).text() == item.device_name
                ),
                dialog.completed,
            )
            dialog.add_result(row, item)

        self.batch_collect_worker.device_finished.connect(on_device_finished)
        self.batch_collect_worker.batch_finished.connect(lambda _success, _failed: self.refresh())
        self.batch_collect_worker.finished.connect(lambda: dialog.set_running(False))
        self.batch_collect_worker.finished.connect(self.batch_collect_worker.deleteLater)
        self.batch_collect_worker.finished.connect(lambda: setattr(self, "batch_collect_worker", None))
        show_non_focus_window(self, dialog, key="batch_collect_progress", activate=False, raise_window=False)
        self.batch_collect_worker.start()

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
        self.batch_refresh_details_button.setEnabled(count > 0)
        self.batch_delete_button.setEnabled(count > 0)
        self.clear_selection_button.setEnabled(count > 0)
        self.invert_selection_button.setEnabled(self.table.rowCount() > 0)
        self.assign_group_button.setEnabled(count > 0)

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("devices.import_csv"), "", "CSV Files (*.csv)")
        if path:
            try:
                result = self.service.import_csv(Path(path))
            except Exception as exc:
                app_logger.log_error("CSV_IMPORT_FAILED", f"{Path(path).name}: {exc}")
                MessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
                return
            self.refresh_groups()
            if result.groups_created:
                self.groups_changed.emit()
            if result.created:
                self.devices_changed.emit()
            app_logger.log_info("CSV_IMPORTED", f"{Path(path).name}: created={result.created}, skipped={result.skipped}")
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.import_done", created=result.created, skipped=result.skipped))

    def export_csv(self) -> None:
        path = select_export_path(self, self.i18n.t("devices.export_csv"), make_device_export_filename(self.site_name), CSV_FILTER)
        if path:
            selected_devices = self.table.checked_devices()
            try:
                self.service.export_csv(path, choose_devices_for_export(self.repository.list(), selected_devices))
            except Exception as exc:
                app_logger.log_error("CSV_EXPORT_FAILED", f"{path.name}: {exc}")
                MessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
                return
            remember_export_path(path)
            app_logger.log_info("CSV_EXPORTED", path.name)
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.export_done"))

    def export_template(self) -> None:
        path = select_export_path(self, self.i18n.t("devices.export_template"), self.i18n.t("devices.template_filename"), CSV_FILTER)
        if path:
            try:
                self.service.export_template_csv(path)
            except Exception as exc:
                app_logger.log_error("CSV_TEMPLATE_EXPORT_FAILED", f"{path.name}: {exc}")
                MessageBox.warning(self, self.i18n.t("devices.title"), str(exc))
                return
            remember_export_path(path)
            app_logger.log_info("CSV_TEMPLATE_EXPORTED", path.name)
            MessageBox.information(self, self.i18n.t("devices.title"), self.i18n.t("devices.template_done"))

    def export_omnipeek_name_table(self) -> None:
        self.feature_gate.assert_enabled("devices.omnipeek_name_table_export")
        source_devices = self.table.checked_devices() or list(self.table.devices)
        service = OmniPeekNameTableService(AcRepository(self.repository.database), self.repository)
        items = service.collect_items(
            include_ac_fit_ap=False,
            include_ap_extensions=False,
            include_device_mr=True,
            devices=source_devices,
            group_names=self._device_group_names(),
        )
        if not items:
            MessageBox.warning(self, "导出 OmniPeek 名称表", "当前筛选或勾选设备中没有可导出的车载 MR。")
            return
        source_counts = {
            SOURCE_AC_FIT_AP: 0,
            SOURCE_AP_EXTENSION: 0,
            SOURCE_DEVICE_MANAGEMENT: len(items),
        }
        dialog = OmniPeekExportDialog(
            items,
            source_counts,
            default_line_name=default_omnipeek_line_name(self.site_name, self.settings.paths),
            settings=self.settings,
            parent=self,
        )
        dialog.exec()

    def _sync_omnipeek_action_state(self) -> None:
        visible = self.feature_gate.is_visible("devices.omnipeek_name_table_export")
        enabled = self.feature_gate.is_enabled("devices.omnipeek_name_table_export")
        self.export_omnipeek_action.setVisible(visible)
        self.export_omnipeek_action.setEnabled(enabled)
        self.more_button.setVisible(visible)
        self.more_button.setEnabled(enabled)

    def _device_group_names(self) -> dict[int, str]:
        if self.table.group_names:
            return dict(self.table.group_names)
        if self.group_repository is None:
            return {}
        try:
            return {int(group.id): group.name for group in self.group_repository.list() if group.id is not None}
        except Exception as exc:
            app_logger.log_error("OMNIPEEK_GROUP_LOAD_FAILED", str(exc))
            return {}
