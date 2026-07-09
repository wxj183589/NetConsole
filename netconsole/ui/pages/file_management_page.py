from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.ui.dialogs.input_dialog_service import InputDialog
import re
import traceback
from uuid import uuid4
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from netconsole.core import app_logger
from netconsole.core.feature_flags import FeatureGate, apply_feature_to_widget, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.device import Device
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.services.device_group_service import ALL_GROUPS, UNGROUPED, group_filter_to_repository_value
from netconsole.services.external_terminal import launch_winscp
from netconsole.services.file_transfer_service import (
    FILE_TRANSFER_MAX_CONCURRENCY,
    FileTransferService,
    RemoteDeviceFile,
    TransferCancelled,
    TransferVerificationFailed,
    auto_rename_path,
    parent_remote_path,
    safe_device_name,
)
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.netmiko_connection import sanitize_sensitive_text
from netconsole.services.path_preference_service import PathPreferenceService
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.shell.fluent_bridge import InfoBar, InfoBarPosition
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate, is_checked_value, set_table_row_checked


LOCAL_COLUMNS = (("name", "file_management.name"), ("size", "file_management.size"), ("modified", "file_management.modified"), ("type", "file_management.type"))
REMOTE_CHECK_COLUMN = 0
REMOTE_COLUMNS = (
    ("select", "file_management.select_column"),
    ("name", "file_management.name"),
    ("size", "file_management.size"),
    ("modified", "file_management.modified"),
    ("type", "file_management.type"),
)
QUEUE_COLUMNS = (
    ("name", "file_management.name"),
    ("device", "file_management.source_device"),
    ("remote_path", "file_management.remote_path"),
    ("local_path", "file_management.local_path"),
    ("size", "file_management.file_size"),
    ("downloaded", "file_management.downloaded_size"),
    ("progress", "file_management.progress"),
    ("speed", "file_management.speed"),
    ("status", "file_management.status"),
    ("action", "file_management.action"),
)


@dataclass
class TransferTask:
    id: int
    batch_id: str
    device: Device
    remote_file: RemoteDeviceFile
    local_path: Path
    size: int
    downloaded: int = 0
    status_key: str = "file_management.status.queued"
    speed: str = "-"


@dataclass
class DownloadBatch:
    batch_id: str
    created_at: str
    device_id: int | None
    task_ids: list[int]
    total_count: int
    success_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    completed_count: int = 0
    summary_shown: bool = False


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


class SftpConnectWorker(QThread):
    connected = Signal(object, str)
    failed = Signal(str)
    status_changed = Signal(str)

    def __init__(self, site_name: str, device: Device, paths: PathResolver, parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.device = device
        self.paths = paths

    def run(self) -> None:
        service = FileTransferService(self.site_name, self.paths)
        try:
            root = service.connect(self.device, self.status_changed.emit)
            self.connected.emit(service, root)
        except Exception as exc:
            app_logger.log_error("FILE_MANAGER_CONNECT_WORKER_FAILED", f"device={self.device.name or self.device.primary_address}, error={sanitize_sensitive_text(str(exc), self.device)}\n{traceback.format_exc()}")
            service.disconnect()
            self.failed.emit(str(exc))


class SftpListWorker(QThread):
    listed = Signal(str, object)
    failed = Signal(str)

    def __init__(self, service: FileTransferService, remote_path: str, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.remote_path = remote_path

    def run(self) -> None:
        try:
            files = self.service.list_directory(self.remote_path)
            self.listed.emit(self.service.current_path, files)
        except Exception as exc:
            self.failed.emit(str(exc))


class SftpDownloadWorker(QThread):
    progress = Signal(int, int)
    completed = Signal()
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, site_name: str, paths: PathResolver, task: TransferTask, parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.paths = paths
        self.task = task
        self.cancel_token = CancelToken()

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def run(self) -> None:
        service = FileTransferService(self.site_name, self.paths)
        last_emit = 0.0
        try:
            service.connect(self.task.device)

            def on_progress(downloaded: int, total: int) -> None:
                nonlocal last_emit
                now = monotonic()
                if now - last_emit >= 0.2 or downloaded >= total:
                    last_emit = now
                    self.progress.emit(downloaded, total)

            service.download(self.task.remote_file.remote_path, self.task.local_path, on_progress, self.cancel_token)
            self.completed.emit()
        except TransferCancelled:
            self.cancelled.emit()
        except TransferVerificationFailed:
            self.failed.emit("verification_failed")
        except Exception as exc:
            self.failed.emit(sanitize_sensitive_text(str(exc), self.task.device))
        finally:
            service.disconnect()


class MeshAutoImportWorker(QThread):
    completed = Signal(int, int, int)
    failed = Signal(str)

    def __init__(self, site_name: str, paths: PathResolver, profile: MeshMrProfile, local_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.paths = paths
        self.profile = profile
        self.local_path = Path(local_path)
        self.result: tuple[int, int, int] | None = None
        self.error_message = ""

    def run(self) -> None:
        try:
            result = MeshImportService(self.site_name, self.paths).import_files(self.profile, [self.local_path])
            self.result = (result.imported_count, result.duplicate_count, result.parsed_record_count)
            self.completed.emit(result.imported_count, result.duplicate_count, result.parsed_record_count)
        except Exception as exc:
            self.error_message = str(exc)
            self.failed.emit(self.error_message)


class FileManagementPage(QWidget):
    def __init__(
        self,
        repository: DeviceRepository,
        i18n: I18n,
        site_name: str = "demo",
        paths: PathResolver | None = None,
        feature_gate: FeatureGate | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths or PathResolver()
        self.feature_gate = feature_gate or default_feature_gate()
        self.group_repository = self._make_group_repository(repository, site_name)
        self.settings = SettingsStore(self.paths)
        self._initializing_columns = True
        self._restoring_column_widths = False
        self._local_column_layout_initialized = False
        self._remote_column_layout_initialized = False
        self.remote_sort_column = 1
        self.remote_sort_order = Qt.AscendingOrder
        self.sftp_service: FileTransferService | None = None
        self.connected_device: Device | None = None
        self.connection_status_key = "file_management.status.disconnected"
        self.remote_files: list[RemoteDeviceFile] = []
        self.checked_remote_paths: set[str] = set()
        self._updating_remote_checks = False
        self.local_path = self.paths.file_downloads_root(site_name)
        self.tasks: list[TransferTask] = []
        self.batches: dict[str, DownloadBatch] = {}
        self.next_task_id = 1
        self.active_worker: SftpDownloadWorker | None = None
        self.mesh_import_workers: dict[int, MeshAutoImportWorker] = {}
        self.connect_worker: SftpConnectWorker | None = None
        self.list_worker: SftpListWorker | None = None
        self.active_winscp_sessions: list[object] = []

        self.site_label = QLabel()
        self.group_label = QLabel()
        self.group_combo = QComboBox()
        self.device_search_edit = QLineEdit()
        self.device_combo = QComboBox()
        self.device_name_label = QLabel()
        self.ip_label = QLabel()
        self.type_label = QLabel()
        self.connect_button = QPushButton()
        self.external_winscp_button = QPushButton()
        self.disconnect_button = QPushButton()
        self.connection_status_label = QLabel()
        self.protocol_label = QLabel()

        self.local_title = QLabel()
        self.local_path_label = QLabel()
        self.local_up_button = QPushButton()
        self.local_refresh_button = QPushButton()
        self.new_folder_button = QPushButton()
        self.open_local_button = QPushButton()
        self.local_table = QTableWidget(0, len(LOCAL_COLUMNS))
        set_table_column_fields(self.local_table, [field for field, _key in LOCAL_COLUMNS])
        configure_readonly_table(self.local_table)

        self.remote_title = QLabel()
        self.remote_path_label = QLabel()
        self.remote_up_button = QPushButton()
        self.remote_refresh_button = QPushButton()
        self.remote_select_all_button = QPushButton()
        self.remote_clear_selection_button = QPushButton()
        self.remote_mesh_logs_button = QPushButton()
        self.download_button = QPushButton()
        self.remote_read_only_label = QLabel()
        self.remote_table = QTableWidget(0, len(REMOTE_COLUMNS))
        set_table_column_fields(self.remote_table, [field for field, _key in REMOTE_COLUMNS])
        configure_readonly_table(self.remote_table)
        install_checkbox_only_delegate(self.remote_table, REMOTE_CHECK_COLUMN)

        self.queue_title = QLabel()
        self.open_download_dir_button = QPushButton()
        self.clear_completed_button = QPushButton()
        self.clear_failed_button = QPushButton()
        self.cancel_selected_task_button = QPushButton()
        self.queue_table = QTableWidget(0, len(QUEUE_COLUMNS))
        set_table_column_fields(self.queue_table, [field for field, _key in QUEUE_COLUMNS])
        configure_readonly_table(self.queue_table)

        top = QHBoxLayout()
        for widget in (
            self.site_label,
            self.group_label,
            self.group_combo,
            self.device_search_edit,
            self.device_combo,
            self.device_name_label,
            self.ip_label,
            self.type_label,
            self.connect_button,
            self.external_winscp_button,
            self.disconnect_button,
            self.connection_status_label,
            self.protocol_label,
        ):
            top.addWidget(widget)
        top.addStretch(1)

        self.file_splitter = QSplitter(Qt.Horizontal)
        self.file_splitter.addWidget(self._local_panel())
        self.file_splitter.addWidget(self._remote_panel())
        self.file_splitter.setChildrenCollapsible(False)
        self.file_splitter.setStretchFactor(0, 1)
        self.file_splitter.setStretchFactor(1, 1)
        self.file_splitter.setSizes([640, 640])

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.file_splitter, 1)
        queue_header = QHBoxLayout()
        queue_header.addWidget(self.queue_title)
        queue_header.addStretch(1)
        for widget in (
            self.open_download_dir_button,
            self.clear_completed_button,
            self.clear_failed_button,
            self.cancel_selected_task_button,
        ):
            queue_header.addWidget(widget)
        layout.addLayout(queue_header)
        layout.addWidget(self.queue_table)
        self.setLayout(layout)

        self.group_combo.currentIndexChanged.connect(self.on_group_filter_changed)
        self.device_search_edit.textChanged.connect(lambda _text: self.refresh_devices())
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.connect_button.clicked.connect(self.connect_sftp)
        self.external_winscp_button.clicked.connect(self.open_external_winscp)
        self.disconnect_button.clicked.connect(self.disconnect_sftp)
        self.local_up_button.clicked.connect(self.local_up)
        self.local_refresh_button.clicked.connect(self.refresh_local)
        self.new_folder_button.clicked.connect(self.new_local_folder)
        self.open_local_button.clicked.connect(lambda: open_folder(self.local_path))
        self.remote_up_button.clicked.connect(self.remote_up)
        self.remote_refresh_button.clicked.connect(self.refresh_remote)
        self.remote_select_all_button.clicked.connect(self.select_all_remote_files)
        self.remote_clear_selection_button.clicked.connect(self.clear_remote_selection)
        self.remote_mesh_logs_button.clicked.connect(self.select_mesh_logs)
        self.download_button.clicked.connect(self.download_selected)
        self.open_download_dir_button.clicked.connect(self.open_download_dir)
        self.clear_completed_button.clicked.connect(self.clear_completed_tasks)
        self.clear_failed_button.clicked.connect(self.clear_failed_tasks)
        self.cancel_selected_task_button.clicked.connect(self.cancel_selected_queue_task)
        self.local_table.cellDoubleClicked.connect(self.local_double_clicked)
        self.remote_table.cellDoubleClicked.connect(self.remote_double_clicked)
        self.remote_table.itemChanged.connect(self.remote_item_changed)
        self.remote_table.itemSelectionChanged.connect(self._sync_file_operation_buttons)
        self.queue_table.itemSelectionChanged.connect(self._sync_file_operation_buttons)
        self.remote_table.horizontalHeader().sectionClicked.connect(self.remote_header_clicked)
        self.local_table.horizontalHeader().sectionResized.connect(lambda _section, _old, _new: self.save_table_column_widths(self.local_table, "file_manager/local_table/column_widths"))
        self.remote_table.horizontalHeader().sectionResized.connect(lambda _section, _old, _new: self.save_table_column_widths(self.remote_table, "file_manager/remote_table/column_widths"))
        self.local_table.itemActivated.connect(lambda item: self.open_local_path_from_item(item))

        self.retranslate()
        self._apply_feature_gate()
        self.refresh_devices()
        self._initializing_columns = False

    def _apply_feature_gate(self) -> None:
        apply_feature_to_widget(self.feature_gate, "file.mesh_log_download", self.remote_mesh_logs_button)
        apply_feature_to_widget(self.feature_gate, "file.mesh_log_download", self.download_button)
        apply_feature_to_widget(self.feature_gate, "file.external_winscp", self.external_winscp_button)

    def _apply_button_icons(self) -> None:
        icon_map = (
            (self.connect_button, "CONNECT"),
            (self.disconnect_button, "CANCEL"),
            (self.external_winscp_button, "FOLDER"),
            (self.local_up_button, "UP"),
            (self.remote_up_button, "UP"),
            (self.local_refresh_button, "SYNC"),
            (self.remote_refresh_button, "SYNC"),
            (self.new_folder_button, "FOLDER_ADD"),
            (self.open_local_button, "FOLDER"),
            (self.remote_select_all_button, "ACCEPT"),
            (self.remote_clear_selection_button, "CANCEL"),
            (self.remote_mesh_logs_button, "DOCUMENT"),
            (self.download_button, "DOWNLOAD"),
            (self.open_download_dir_button, "FOLDER"),
            (self.clear_completed_button, "DELETE"),
            (self.clear_failed_button, "DELETE"),
            (self.cancel_selected_task_button, "CANCEL"),
        )
        for button, icon_name in icon_map:
            apply_button_icon(button, icon_name)

    def _show_success(self, title: str, message: str) -> None:
        if InfoBar is not None and InfoBarPosition is not None:
            InfoBar.success(title=title, content=message, duration=2500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
            return
        MessageBox.information(self, title, message)

    def _show_warning(self, title: str, message: str) -> None:
        if InfoBar is not None and InfoBarPosition is not None:
            InfoBar.warning(title=title, content=message, duration=3500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
            return
        MessageBox.warning(self, title, message)

    def _show_error(self, title: str, message: str) -> None:
        if InfoBar is not None and InfoBarPosition is not None:
            InfoBar.error(title=title, content=message, duration=4500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
            return
        MessageBox.warning(self, title, message)

    def _local_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(420)
        controls = QHBoxLayout()
        controls.addWidget(self.local_up_button)
        controls.addWidget(self.local_refresh_button)
        controls.addWidget(self.new_folder_button)
        controls.addWidget(self.open_local_button)
        controls.addStretch(1)
        layout = QVBoxLayout(panel)
        layout.addWidget(self.local_title)
        layout.addWidget(self.local_path_label)
        layout.addLayout(controls)
        layout.addWidget(self.local_table, 1)
        return panel

    def _remote_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(420)
        controls = QHBoxLayout()
        controls.addWidget(self.remote_up_button)
        controls.addWidget(self.remote_refresh_button)
        controls.addWidget(self.remote_select_all_button)
        controls.addWidget(self.remote_clear_selection_button)
        controls.addWidget(self.remote_mesh_logs_button)
        controls.addWidget(self.download_button)
        controls.addStretch(1)
        layout = QVBoxLayout(panel)
        layout.addWidget(self.remote_title)
        layout.addWidget(self.remote_path_label)
        layout.addWidget(self.remote_read_only_label)
        layout.addLayout(controls)
        layout.addWidget(self.remote_table, 1)
        return panel

    def retranslate(self) -> None:
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self.group_label.setText(self.i18n.t("groups.group"))
        self.device_search_edit.setPlaceholderText("搜索设备 / IP / 站点 / 分组 / 类型")
        self.connect_button.setText(self.i18n.t("file_management.connect"))
        self.external_winscp_button.setText(self.i18n.t("file_management.external_winscp"))
        self.disconnect_button.setText(self.i18n.t("file_management.disconnect"))
        self.local_title.setText(self.i18n.t("file_management.local_files"))
        self.remote_title.setText(self.i18n.t("file_management.remote_files"))
        self.local_up_button.setText(self.i18n.t("file_management.up"))
        self.remote_up_button.setText(self.i18n.t("file_management.up"))
        self.local_refresh_button.setText(self.i18n.t("file_management.refresh"))
        self.remote_refresh_button.setText(self.i18n.t("file_management.refresh"))
        self.remote_select_all_button.setText(self.i18n.t("file_management.select_all"))
        self.remote_clear_selection_button.setText(self.i18n.t("file_management.clear_selection"))
        self.remote_mesh_logs_button.setText(self.i18n.t("file_management.mesh_logs"))
        self.new_folder_button.setText(self.i18n.t("file_management.new_local_folder"))
        self.open_local_button.setText(self.i18n.t("file_management.open_local_folder"))
        self.remote_read_only_label.setText(self.i18n.t("file_management.remote_read_only_hint"))
        self.queue_title.setText(self.i18n.t("file_management.transfer_queue"))
        self.open_download_dir_button.setText(self.i18n.t("file_management.open_download_dir"))
        self.clear_completed_button.setText(self.i18n.t("file_management.clear_completed"))
        self.clear_failed_button.setText(self.i18n.t("file_management.clear_failed"))
        self.cancel_selected_task_button.setText(self.i18n.t("file_management.cancel_selected_task"))
        self.protocol_label.setText(f"{self.i18n.t('file_management.protocol')}: SFTP")
        self.local_table.setHorizontalHeaderLabels([self.i18n.t(key) for _field, key in LOCAL_COLUMNS])
        self.remote_table.setHorizontalHeaderLabels([self.i18n.t(key) for _field, key in REMOTE_COLUMNS])
        self.remote_table.horizontalHeaderItem(REMOTE_CHECK_COLUMN).setText("")
        self.queue_table.setHorizontalHeaderLabels([self.i18n.t(key) for _field, key in QUEUE_COLUMNS])
        self.apply_table_style_without_saving(self.local_table)
        self.apply_table_style_without_saving(self.remote_table)
        self.apply_table_style_without_saving(self.queue_table)
        self.apply_column_layouts()
        self.update_device_labels()
        self.update_connection_status(self.connection_status_key)
        self.refresh_groups()
        self.refresh_local()
        self.refresh_queue()
        self._apply_button_icons()
        self.update_download_button()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.disconnect_sftp()
        self.repository = repository
        self.site_name = site_name
        self.group_repository = self._make_group_repository(repository, site_name)
        self.local_path = self.paths.file_downloads_root(site_name)
        self.refresh_groups()
        self.refresh_devices()
        self.retranslate()

    def refresh_groups(self) -> None:
        current = self.group_combo.currentData()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem(self.i18n.t("groups.all_groups"), ALL_GROUPS)
        self.group_combo.addItem(self.i18n.t("groups.ungrouped"), UNGROUPED)
        for group in self._list_groups():
            self.group_combo.addItem(group.name, group.id)
        index = self.group_combo.findData(current if current is not None else ALL_GROUPS)
        self.group_combo.setCurrentIndex(index if index >= 0 else 0)
        self.group_combo.blockSignals(False)

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
            app_logger.log_warning("FILE_MANAGER_GROUP_LIST_FAILED", str(exc))
            return []

    def refresh_devices(self, trigger_device_change: bool = True) -> None:
        current_id = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        search_text = self.device_search_edit.text().strip()
        try:
            devices = self.repository.list(search=search_text or None, group_filter=group_filter_to_repository_value(self.group_combo.currentData()))
        except TypeError:
            devices = self.repository.list()
        if not devices:
            self.device_combo.addItem("未找到匹配设备", None)
        for device in devices:
            if device.id is not None:
                self.device_combo.addItem(str(device.name or device.system_name or device.primary_address), int(device.id))
        index = self.device_combo.findData(current_id)
        self.device_combo.setCurrentIndex(index if index >= 0 else (0 if self.device_combo.count() else -1))
        new_id = self.device_combo.currentData()
        self.device_combo.blockSignals(False)
        if trigger_device_change and new_id != current_id:
            self.on_device_changed()
        elif trigger_device_change:
            self.update_device_labels()

    def on_group_filter_changed(self) -> None:
        current_device_id = self.device_combo.currentData()
        self.refresh_devices(trigger_device_change=False)
        if current_device_id is not None and self.device_combo.findData(current_device_id) >= 0:
            self.update_device_labels()
            return
        self.disconnect_sftp()
        self.on_device_changed()

    def current_device(self) -> Device | None:
        device_id = self.device_combo.currentData()
        if device_id is None:
            return None
        return self.repository.get(int(device_id))

    def on_device_changed(self) -> None:
        self.disconnect_sftp()
        device = self.current_device()
        self.update_device_labels()
        self.remote_files = []
        self.checked_remote_paths.clear()
        self.populate_remote_table()
        self.local_path = self.default_local_dir(device)
        self.local_path.mkdir(parents=True, exist_ok=True)
        self.refresh_local()
        self._sync_file_operation_buttons()

    def update_device_labels(self) -> None:
        device = self.current_device()
        if device is None:
            self.device_name_label.setText(self.i18n.t("file_management.no_device"))
            self.ip_label.setText("")
            self.type_label.setText("")
            return
        self.device_name_label.setText(f"{self.i18n.t('field.name')}: {device.name}")
        self.ip_label.setText(f"{self.i18n.t('field.primary_address')}: {device.primary_address}")
        self.type_label.setText(f"{self.i18n.t('field.device_type')}: {device.device_type or '-'}")

    def update_connection_status(self, status_key: str) -> None:
        self.connection_status_key = status_key
        self.connection_status_label.setText(f"{self.i18n.t('file_management.connection_status')}: {self.i18n.t(status_key)}")
        self._sync_file_operation_buttons()

    def is_remote_connected(self) -> bool:
        return self.sftp_service is not None and self.sftp_service.is_connected()

    def _sync_file_operation_buttons(self) -> None:
        device = self.current_device()
        connecting = self.connect_worker is not None and self.connect_worker.isRunning()
        listing = self.list_worker is not None and self.list_worker.isRunning()
        connected = self.is_remote_connected()
        has_checked_remote_files = bool(self.checked_remote_files_in_view_order())
        has_queue_selection = self.selected_queue_task() is not None
        has_completed = any(task.status_key in self._completed_queue_statuses() for task in self.tasks)
        has_failed = any(task.status_key in self._failed_queue_statuses() for task in self.tasks)

        self.connect_button.setEnabled(device is not None and not connecting and not connected)
        self.disconnect_button.setEnabled(connecting or connected)
        self.external_winscp_button.setEnabled(device is not None)
        for button in (
            self.remote_up_button,
            self.remote_select_all_button,
            self.remote_clear_selection_button,
            self.remote_mesh_logs_button,
        ):
            button.setEnabled(connected)
        self.remote_refresh_button.setEnabled(connected and not listing)
        self.download_button.setEnabled(connected and has_checked_remote_files)
        self.clear_completed_button.setEnabled(has_completed)
        self.clear_failed_button.setEnabled(has_failed)
        self.cancel_selected_task_button.setEnabled(has_queue_selection)

    def default_local_dir(self, device: Device | None) -> Path:
        name = safe_device_name(device.name or device.system_name or "device") if device is not None else "device"
        return self.paths.device_file_download_dir(self.site_name, name)

    def selected_remote_items_for_operation(self) -> list[RemoteDeviceFile]:
        checked = self.checked_remote_files_in_view_order()
        if checked:
            return checked
        current = self.selected_remote_file()
        return [current] if current is not None else []

    def selected_queue_task(self) -> TransferTask | None:
        row = self.queue_table.currentRow()
        if row < 0:
            return None
        item = self.queue_table.item(row, 0)
        if item is None:
            return None
        task_id = item.data(Qt.UserRole)
        return next((task for task in self.tasks if task.id == task_id), None)

    @staticmethod
    def _completed_queue_statuses() -> set[str]:
        return {"file_management.status.completed", "file_management.mesh_auto_import_done", "file_management.mesh_auto_import_duplicate"}

    @staticmethod
    def _failed_queue_statuses() -> set[str]:
        return {"file_management.status.failed", "file_management.status.verification_failed", "file_management.mesh_auto_import_failed"}

    def download_directory_for_remote_file(self, remote_file: RemoteDeviceFile, device: Device) -> Path:
        if is_mesh_log_file(remote_file.name) and self.is_vehicle_mr_device(device):
            profile = MeshStorageService(self.site_name, self.paths).ensure_mr_profile_for_device(device)
            target = self.paths.mesh_mr_raw_dir(self.site_name, profile.safe_folder_name)
            target.mkdir(parents=True, exist_ok=True)
            return target
        self.local_path.mkdir(parents=True, exist_ok=True)
        return self.local_path

    def is_vehicle_mr_device(self, device: Device) -> bool:
        values = (device.device_type, device.name, device.system_name)
        return any("MR" in str(value or "").upper() for value in values)

    def open_external_winscp(self) -> None:
        device = self.current_device()
        if device is None:
            MessageBox.information(self, self.i18n.t("file_management.title"), self.i18n.t("file_management.no_device"))
            return
        result = launch_winscp(device, self.settings, self.active_winscp_sessions)
        if result.success:
            app_logger.log_info("WINSCP_LAUNCHED", f"device={device.name or device.primary_address}, command={result.safe_command}")
            MessageBox.information(self, self.i18n.t("file_management.external_winscp"), result.message)
        else:
            MessageBox.warning(self, self.i18n.t("file_management.external_winscp"), result.message)

    def connect_sftp(self) -> None:
        device = self.current_device()
        if device is None:
            self._show_warning(self.i18n.t("file_management.title"), self.i18n.t("file_management.no_device"))
            return
        self.disconnect_sftp()
        self.update_connection_status("file_management.status.connecting")
        self._sync_file_operation_buttons()
        self.connect_worker = SftpConnectWorker(self.site_name, device, self.paths, self)
        self.connect_worker.status_changed.connect(self.update_connection_status)
        self.connect_worker.connected.connect(self.on_connected)
        self.connect_worker.failed.connect(self.on_connect_failed)
        self.connect_worker.finished.connect(self.connect_worker.deleteLater)
        self.connect_worker.finished.connect(lambda: setattr(self, "connect_worker", None))
        self.connect_worker.finished.connect(self._sync_file_operation_buttons)
        self.connect_worker.start()

    def on_connected(self, service: FileTransferService, root_path: str) -> None:
        self.sftp_service = service
        self.connected_device = self.current_device()
        self.update_connection_status("file_management.status.connected")
        self.remote_path_label.setText(f"{self.i18n.t('file_management.current_path')}: {root_path}")
        self.refresh_remote()
        self._show_success(self.i18n.t("file_management.connect"), self.i18n.t("file_management.connect_success", device=self.connected_device.name if self.connected_device else ""))
        self._sync_file_operation_buttons()

    def on_connect_failed(self, error: str) -> None:
        self.update_connection_status("file_management.status.connection_failed")
        app_logger.log_error("FILE_MANAGER_CONNECT_FAILED", f"error={error}")
        self._show_error(self.i18n.t("file_management.connect_failed_title"), error)
        self._sync_file_operation_buttons()

    def disconnect_sftp(self) -> None:
        self.fail_waiting_tasks_on_disconnect()
        if self.list_worker and self.list_worker.isRunning():
            self.list_worker.wait(1000)
        if self.sftp_service is not None:
            self.sftp_service.disconnect()
        self.sftp_service = None
        self.connected_device = None
        self.remote_files = []
        self.checked_remote_paths.clear()
        self.populate_remote_table()
        self.update_connection_status("file_management.status.disconnected")
        self.remote_path_label.setText(f"{self.i18n.t('file_management.current_path')}: -")
        self._sync_file_operation_buttons()

    def refresh_connection_status(self) -> None:
        if self.is_remote_connected():
            self.refresh_remote()
            self._show_success(self.i18n.t("file_management.title"), self.i18n.t("file_management.refresh_done"))
            return
        self.refresh_devices(trigger_device_change=False)
        self.update_device_labels()
        self.update_connection_status("file_management.status.disconnected")

    def fail_waiting_tasks_on_disconnect(self) -> None:
        changed = False
        for task in self.tasks:
            if task.status_key == "file_management.status.queued":
                task.status_key = "file_management.status.failed"
                changed = True
        if self.active_worker is not None and self.active_worker.isRunning():
            self.active_worker.cancel()
        if changed:
            self.refresh_queue()

    def refresh_remote(self) -> None:
        if self.sftp_service is None or not self.sftp_service.is_connected():
            return
        self.remote_refresh_button.setEnabled(False)
        self.list_worker = SftpListWorker(self.sftp_service, self.sftp_service.current_path or self.sftp_service.root_path, self)
        self.list_worker.listed.connect(self.on_remote_listed)
        self.list_worker.failed.connect(self.on_remote_failed)
        self.list_worker.finished.connect(self.list_worker.deleteLater)
        self.list_worker.finished.connect(lambda: setattr(self, "list_worker", None))
        self.list_worker.finished.connect(self._sync_file_operation_buttons)
        self.list_worker.start()

    def on_remote_listed(self, remote_path: str, files: list[RemoteDeviceFile]) -> None:
        self.remote_refresh_button.setEnabled(True)
        self.remote_path_label.setText(f"{self.i18n.t('file_management.current_path')}: {remote_path}")
        existing = {item.remote_path for item in files if not item.is_dir}
        self.checked_remote_paths.intersection_update(existing)
        self.remote_files = files
        self.populate_remote_table()
        self._sync_file_operation_buttons()

    def on_remote_failed(self, error: str) -> None:
        self.remote_refresh_button.setEnabled(True)
        self._show_error(self.i18n.t("file_management.title"), error)
        self._sync_file_operation_buttons()

    def remote_up(self) -> None:
        if self.sftp_service is None:
            return
        self.start_remote_list(parent_remote_path(self.sftp_service.current_path or self.sftp_service.root_path, self.sftp_service.root_path))

    def start_remote_list(self, path: str) -> None:
        if self.sftp_service is None:
            return
        self.checked_remote_paths.clear()
        self.update_download_button()
        self.remote_refresh_button.setEnabled(False)
        self.list_worker = SftpListWorker(self.sftp_service, path, self)
        self.list_worker.listed.connect(self.on_remote_listed)
        self.list_worker.failed.connect(self.on_remote_failed)
        self.list_worker.finished.connect(self.list_worker.deleteLater)
        self.list_worker.finished.connect(lambda: setattr(self, "list_worker", None))
        self.list_worker.finished.connect(self._sync_file_operation_buttons)
        self.list_worker.start()

    def populate_remote_table(self) -> None:
        self._updating_remote_checks = True
        self.remote_table.setRowCount(len(self.remote_files))
        for row, item in enumerate(self.remote_files):
            values = {
                "select": "",
                "name": item.name,
                "size": "" if item.is_dir or item.size is None else str(item.size),
                "modified": item.modified_time or "",
                "type": self.i18n.t("file_management.type.directory") if item.is_dir else item.file_type,
            }
            for column, (field, _key) in enumerate(REMOTE_COLUMNS):
                table_item = QTableWidgetItem(values.get(field, ""))
                table_item.setData(Qt.UserRole, row)
                table_item.setToolTip(values.get(field, ""))
                if field == "select":
                    if not item.is_dir:
                        table_item = create_checkable_table_item(item.remote_path in self.checked_remote_paths, user_data=row)
                        table_item.setToolTip(values.get(field, ""))
                    else:
                        table_item.setFlags(Qt.ItemIsEnabled)
                elif field == "size":
                    table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.remote_table.setItem(row, column, table_item)
        self._updating_remote_checks = False
        self.apply_table_style_without_saving(self.remote_table)
        self.apply_remote_column_layout()
        self.update_download_button()

    def remote_double_clicked(self, row: int, _column: int) -> None:
        item = self.remote_file_for_table_row(row)
        if item is None:
            return
        if item.is_dir:
            self.start_remote_list(item.remote_path)
        else:
            self.toggle_remote_file_checked(item)

    def selected_remote_file(self) -> RemoteDeviceFile | None:
        row = self.remote_table.currentRow()
        return self.remote_file_for_table_row(row)

    def download_selected(self) -> None:
        self.feature_gate.assert_enabled("file.mesh_log_download")
        files = self.checked_remote_files_in_view_order()
        if not files:
            self._show_warning(self.i18n.t("file_management.title"), self.i18n.t("file_management.no_file_selected"))
            return
        self.enqueue_downloads(files)

    def new_remote_folder(self) -> None:
        self._show_warning(self.i18n.t("file_management.title"), self.i18n.t("file_management.remote_read_only_rejected"))

    def delete_selected_remote_files(self) -> None:
        self._show_warning(self.i18n.t("file_management.title"), self.i18n.t("file_management.remote_read_only_rejected"))

    def enqueue_downloads(self, remote_files: list[RemoteDeviceFile]) -> None:
        device = self.connected_device or self.current_device()
        if device is None:
            return
        queued_paths = {task.remote_file.remote_path for task in self.tasks if task.status_key in {"file_management.status.queued", "file_management.status.downloading"}}
        batch_id = str(uuid4())
        task_ids: list[int] = []
        for remote_file in remote_files:
            if remote_file.is_dir or remote_file.remote_path in queued_paths:
                continue
            target_dir = self.download_directory_for_remote_file(remote_file, device)
            target = resolve_local_download_path(target_dir, remote_file, device.name)
            task = TransferTask(self.allocate_task_id(), batch_id, device, remote_file, target, int(remote_file.size or 0))
            self.tasks.append(task)
            task_ids.append(task.id)
            queued_paths.add(remote_file.remote_path)
        if task_ids:
            self.batches[batch_id] = DownloadBatch(
                batch_id=batch_id,
                created_at=datetime.now().isoformat(timespec="seconds"),
                device_id=device.id,
                task_ids=task_ids,
                total_count=len(task_ids),
            )
        self.refresh_queue()
        self.start_next_download()

    def start_next_download(self) -> None:
        if self.active_worker is not None:
            return
        if FILE_TRANSFER_MAX_CONCURRENCY != 1:
            app_logger.log_warning("FILE_TRANSFER_CONCURRENCY_IGNORED", f"configured={FILE_TRANSFER_MAX_CONCURRENCY}, active=1")
        next_task = next((task for task in self.tasks if task.status_key == "file_management.status.queued"), None)
        if next_task is None:
            self.maybe_show_finished_batch_summaries()
            return
        next_task.status_key = "file_management.status.downloading"
        next_task.speed = "-"
        self.refresh_queue()
        worker = SftpDownloadWorker(self.site_name, self.paths, next_task, self)
        self.active_worker = worker
        started = monotonic()
        worker.progress.connect(lambda downloaded, total, task=next_task, start=started: self.on_download_progress(task, downloaded, total, start))
        worker.completed.connect(lambda task=next_task: self.on_download_completed(task))
        worker.cancelled.connect(lambda task=next_task: self.on_download_cancelled(task))
        worker.failed.connect(lambda error, task=next_task: self.on_download_failed(task, error))
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "active_worker", None))
        worker.finished.connect(self.start_next_download)
        worker.start()

    def on_download_progress(self, task: TransferTask, downloaded: int, total: int, started: float) -> None:
        task.downloaded = downloaded
        elapsed = max(0.001, monotonic() - started)
        task.speed = format_speed(downloaded / elapsed)
        if total:
            task.size = total
        self.refresh_queue()

    def on_download_completed(self, task: TransferTask) -> None:
        task.downloaded = task.size
        task.status_key = "file_management.status.completed"
        task.speed = "-"
        PathPreferenceService(self.paths).record_download_if_vehicle_mr(task.local_path, task.remote_file.name)
        self.refresh_queue()
        self.refresh_local(select_path=task.local_path)
        self._start_mesh_auto_import_if_needed(task)
        self.maybe_show_batch_summary(task.batch_id)

    def _start_mesh_auto_import_if_needed(self, task: TransferTask) -> None:
        if not self.feature_gate.is_enabled("file.mesh_auto_import"):
            return
        if not (is_mesh_log_file(task.remote_file.name) and self.is_vehicle_mr_device(task.device) and task.local_path.exists()):
            return
        try:
            profile = MeshStorageService(self.site_name, self.paths).ensure_mr_profile_for_device(task.device)
        except Exception as exc:
            self._mesh_auto_import_failed(task, str(exc))
            return
        task.status_key = "file_management.mesh_auto_import_started"
        self.refresh_queue()
        worker = MeshAutoImportWorker(self.site_name, self.paths, profile, task.local_path, self)
        self.mesh_import_workers[task.id] = worker
        worker.completed.connect(lambda imported, duplicates, parsed, t=task: self._mesh_auto_import_completed(t, imported, duplicates, parsed))
        worker.failed.connect(lambda message, t=task: self._mesh_auto_import_failed(t, message))
        worker.finished.connect(lambda t=task, w=worker: self._mesh_auto_import_finished(t, w))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _mesh_auto_import_finished(self, task: TransferTask, worker: MeshAutoImportWorker) -> None:
        if task.status_key != "file_management.mesh_auto_import_started":
            return
        if worker.result is not None:
            imported, duplicates, parsed = worker.result
            self._mesh_auto_import_completed(task, imported, duplicates, parsed)
            return
        self._mesh_auto_import_failed(task, worker.error_message or "unknown error")

    def _mesh_auto_import_completed(self, task: TransferTask, imported: int, duplicates: int, parsed: int) -> None:
        task.status_key = "file_management.mesh_auto_import_duplicate" if duplicates and not imported else "file_management.mesh_auto_import_done"
        self.mesh_import_workers.pop(task.id, None)
        app_logger.log_info("MESH_AUTO_IMPORT_DONE", f"path={task.local_path}, imported={imported}, duplicates={duplicates}, parsed={parsed}")
        self.refresh_queue()

    def _mesh_auto_import_failed(self, task: TransferTask, message: str) -> None:
        task.status_key = "file_management.mesh_auto_import_failed"
        self.mesh_import_workers.pop(task.id, None)
        app_logger.log_warning("MESH_AUTO_IMPORT_FAILED", f"path={task.local_path}, error={message}")
        self.refresh_queue()

    def on_download_cancelled(self, task: TransferTask) -> None:
        task.status_key = "file_management.status.cancelled"
        task.speed = "-"
        self.refresh_queue()
        self.maybe_show_batch_summary(task.batch_id)

    def on_download_failed(self, task: TransferTask, error: str) -> None:
        task.status_key = "file_management.status.verification_failed" if error == "verification_failed" else "file_management.status.failed"
        task.speed = "-"
        self.refresh_queue()
        self.maybe_show_batch_summary(task.batch_id)

    def refresh_queue(self) -> None:
        self.queue_table.setRowCount(len(self.tasks))
        for row, task in enumerate(self.tasks):
            progress = int(task.downloaded * 100 / task.size) if task.size else 0
            values = {
                "name": task.local_path.name,
                "device": task.device.name,
                "remote_path": task.remote_file.remote_path,
                "local_path": str(task.local_path),
                "size": str(task.size),
                "downloaded": str(task.downloaded),
                "progress": f"{progress}%",
                "speed": task.speed,
                "status": self.i18n.t(task.status_key),
            }
            for column, (field, _key) in enumerate(QUEUE_COLUMNS):
                if field == "action":
                    self.queue_table.setCellWidget(row, column, self.queue_action_widget(task))
                    continue
                item = QTableWidgetItem(values.get(field, ""))
                item.setData(Qt.UserRole, task.id)
                tooltip = values.get(field, "")
                if field == "name":
                    tooltip = f"{values.get(field, '')}\n{task.remote_file.name}"
                item.setToolTip(tooltip)
                if field in {"size", "downloaded", "progress", "speed"}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.queue_table.setItem(row, column, item)
        self.apply_table_style_without_saving(self.queue_table)
        self.apply_queue_column_layout()
        self._sync_file_operation_buttons()

    def queue_action_widget(self, task: TransferTask) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        cancel_button = QPushButton(self.i18n.t("file_management.cancel"))
        retry_button = QPushButton(self.i18n.t("file_management.retry"))
        open_button = QPushButton(self.i18n.t("file_management.open_containing_folder"))
        cancel_button.setEnabled(task.status_key in {"file_management.status.queued", "file_management.status.downloading"})
        retry_button.setEnabled(task.status_key in {"file_management.status.cancelled", "file_management.status.failed", "file_management.status.verification_failed"})
        open_button.setEnabled(task.local_path.exists())
        apply_button_icon(cancel_button, "CANCEL")
        apply_button_icon(retry_button, "SYNC")
        apply_button_icon(open_button, "FOLDER")
        cancel_button.clicked.connect(lambda _=False, value=task: self.cancel_task(value))
        retry_button.clicked.connect(lambda _=False, value=task: self.retry_task(value))
        open_button.clicked.connect(lambda _=False, value=task: open_folder(value.local_path.parent))
        layout.addWidget(cancel_button)
        layout.addWidget(retry_button)
        layout.addWidget(open_button)
        return widget

    def cancel_task(self, task: TransferTask) -> None:
        if task.status_key == "file_management.status.queued":
            task.status_key = "file_management.status.cancelled"
        elif task.status_key == "file_management.status.downloading" and self.active_worker is not None:
            self.active_worker.cancel()
        self.refresh_queue()

    def retry_task(self, task: TransferTask) -> None:
        batch_id = str(uuid4())
        retry = TransferTask(
            self.allocate_task_id(),
            batch_id,
            task.device,
            task.remote_file,
            resolve_local_download_path(self.download_directory_for_remote_file(task.remote_file, task.device), task.remote_file, task.device.name),
            int(task.remote_file.size or task.size or 0),
        )
        self.tasks.append(retry)
        self.batches[batch_id] = DownloadBatch(
            batch_id=batch_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            device_id=task.device.id,
            task_ids=[retry.id],
            total_count=1,
        )
        self.refresh_queue()
        self.start_next_download()

    def open_download_dir(self) -> None:
        self.local_path.mkdir(parents=True, exist_ok=True)
        open_folder(self.local_path)

    def clear_completed_tasks(self) -> None:
        completed_statuses = self._completed_queue_statuses()
        self.tasks = [task for task in self.tasks if task.status_key not in completed_statuses]
        self.refresh_queue()
        self._show_success(self.i18n.t("file_management.transfer_queue"), self.i18n.t("file_management.completed_tasks_cleared"))

    def clear_failed_tasks(self) -> None:
        failed_statuses = self._failed_queue_statuses()
        self.tasks = [task for task in self.tasks if task.status_key not in failed_statuses]
        self.refresh_queue()
        self._show_success(self.i18n.t("file_management.transfer_queue"), self.i18n.t("file_management.failed_tasks_cleared"))

    def cancel_selected_queue_task(self) -> None:
        task = self.selected_queue_task()
        if task is None:
            self._show_warning(self.i18n.t("file_management.transfer_queue"), self.i18n.t("file_management.no_queue_task_selected"))
            return
        self.cancel_task(task)

    def allocate_task_id(self) -> int:
        existing = {task.id for task in self.tasks}
        while self.next_task_id in existing:
            self.next_task_id += 1
        task_id = self.next_task_id
        self.next_task_id += 1
        return task_id

    def remote_file_for_table_row(self, row: int) -> RemoteDeviceFile | None:
        if row < 0:
            return None
        item = self.remote_table.item(row, 0)
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        if index is None:
            return None
        try:
            remote_file = self.remote_files[int(index)]
        except (TypeError, ValueError, IndexError):
            return None
        return remote_file

    def checked_remote_files_in_view_order(self) -> list[RemoteDeviceFile]:
        files: list[RemoteDeviceFile] = []
        for row in range(self.remote_table.rowCount()):
            remote_file = self.remote_file_for_table_row(row)
            if remote_file is not None and not remote_file.is_dir and remote_file.remote_path in self.checked_remote_paths:
                files.append(remote_file)
        return files

    def remote_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_remote_checks or item.column() != REMOTE_CHECK_COLUMN:
            return
        remote_file = self.remote_file_for_table_row(item.row())
        if remote_file is None or remote_file.is_dir:
            return
        if is_checked_value(item.checkState()):
            self.checked_remote_paths.add(remote_file.remote_path)
        else:
            self.checked_remote_paths.discard(remote_file.remote_path)
        self.update_download_button()

    def remote_header_clicked(self, section: int) -> None:
        if section == REMOTE_CHECK_COLUMN:
            return
        if self.remote_sort_column == section:
            self.remote_sort_order = Qt.DescendingOrder if self.remote_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self.remote_sort_column = section
            self.remote_sort_order = Qt.AscendingOrder
        self.remote_table.sortItems(section, self.remote_sort_order)

    def select_all_remote_files(self) -> None:
        files = [item for item in self.remote_files if not item.is_dir]
        for item in files:
            self.checked_remote_paths.add(item.remote_path)
        self.populate_remote_table()

    def clear_remote_selection(self) -> None:
        self.checked_remote_paths.clear()
        self.populate_remote_table()

    def select_mesh_logs(self) -> None:
        self.feature_gate.assert_enabled("file.mesh_log_download")
        selected_paths = {
            item.remote_path
            for item in self.remote_files
            if not item.is_dir and is_mesh_log_file(item.name)
        }
        self.checked_remote_paths.clear()
        self.checked_remote_paths.update(selected_paths)
        self.populate_remote_table()
        if not selected_paths:
            MessageBox.information(self, self.i18n.t("file_management.mesh_logs"), self.i18n.t("file_management.no_mesh_logs_found"))

    def toggle_remote_file_checked(self, remote_file: RemoteDeviceFile) -> None:
        if remote_file.remote_path in self.checked_remote_paths:
            self.checked_remote_paths.discard(remote_file.remote_path)
        else:
            self.checked_remote_paths.add(remote_file.remote_path)
        for row in range(self.remote_table.rowCount()):
            row_file = self.remote_file_for_table_row(row)
            if row_file is not None and row_file.remote_path == remote_file.remote_path:
                self._updating_remote_checks = True
                set_table_row_checked(self.remote_table, row, remote_file.remote_path in self.checked_remote_paths, REMOTE_CHECK_COLUMN)
                self._updating_remote_checks = False
                break
        self.update_download_button()

    def update_download_button(self) -> None:
        count = len(self.checked_remote_files_in_view_order())
        if count:
            self.download_button.setText(self.i18n.t("file_management.download_files_count", count=count))
            self.download_button.setToolTip(self.i18n.t("file_management.selected_files", count=count))
        else:
            self.download_button.setText(self.i18n.t("file_management.download_files"))
            self.download_button.setToolTip(self.i18n.t("file_management.no_file_selected"))
        self._sync_file_operation_buttons()

    def maybe_show_finished_batch_summaries(self) -> None:
        for batch_id in list(self.batches):
            self.maybe_show_batch_summary(batch_id)

    def maybe_show_batch_summary(self, batch_id: str) -> None:
        batch = self.batches.get(batch_id)
        if batch is None or batch.summary_shown:
            return
        terminal_states = {
            "file_management.status.completed",
            "file_management.status.cancelled",
            "file_management.status.failed",
            "file_management.status.verification_failed",
        }
        batch_tasks = [task for task in self.tasks if task.id in set(batch.task_ids)]
        if len(batch_tasks) != batch.total_count or any(task.status_key not in terminal_states for task in batch_tasks):
            return
        success = sum(1 for task in batch_tasks if task.status_key == "file_management.status.completed")
        cancelled = sum(1 for task in batch_tasks if task.status_key == "file_management.status.cancelled")
        failed = len(batch_tasks) - success - cancelled
        batch.success_count = success
        batch.cancelled_count = cancelled
        batch.failed_count = failed
        batch.completed_count = len(batch_tasks)
        batch.summary_shown = True
        MessageBox.information(
            self,
            self.i18n.t("file_management.download_completed_title"),
            self.i18n.t("file_management.download_summary", success=success, failed=failed, cancelled=cancelled),
        )

    def apply_column_layouts(self) -> None:
        self.apply_local_column_layout()
        self.apply_remote_column_layout()
        self.apply_queue_column_layout()

    def apply_table_style_without_saving(self, table: QTableWidget) -> None:
        header = table.horizontalHeader()
        self._restoring_column_widths = True
        old_blocked = header.blockSignals(True)
        try:
            apply_table_style(table)
        finally:
            header.blockSignals(old_blocked)
            self._restoring_column_widths = False

    def apply_local_column_layout(self) -> None:
        header = self.local_table.horizontalHeader()
        self._restoring_column_widths = True
        old_blocked = header.blockSignals(True)
        try:
            header.setStretchLastSection(False)
            header.setSectionsMovable(False)
            for column in range(self.local_table.columnCount()):
                header.setSectionResizeMode(column, QHeaderView.Interactive)
            has_saved = isinstance(self.settings.get_value("file_manager/local_table/column_widths", None), list)
            if has_saved or not self._local_column_layout_initialized:
                self.restore_table_column_widths(self.local_table, "file_manager/local_table/column_widths", {0: 280, 1: 90, 2: 150, 3: 80}, {0: 180, 1: 60, 2: 120, 3: 60})
                self._local_column_layout_initialized = True
        finally:
            header.blockSignals(old_blocked)
            self._restoring_column_widths = False

    def apply_remote_column_layout(self) -> None:
        header = self.remote_table.horizontalHeader()
        self._restoring_column_widths = True
        old_blocked = header.blockSignals(True)
        try:
            header.setMinimumSectionSize(1)
            header.setStretchLastSection(False)
            header.setSectionsMovable(False)
            for column in range(self.remote_table.columnCount()):
                header.setSectionResizeMode(column, QHeaderView.Interactive)
            header.setSectionResizeMode(0, QHeaderView.Fixed)
            self.remote_table.setColumnWidth(0, 48)
            has_saved = isinstance(self.settings.get_value("file_manager/remote_table/column_widths", None), list)
            if has_saved or not self._remote_column_layout_initialized:
                self.restore_table_column_widths(self.remote_table, "file_manager/remote_table/column_widths", {0: 48, 1: 350, 2: 90, 3: 150, 4: 80}, {0: 48, 1: 180, 2: 60, 3: 120, 4: 60}, fixed_widths={0: 48})
                self._remote_column_layout_initialized = True
        finally:
            header.blockSignals(old_blocked)
            self._restoring_column_widths = False

    def apply_queue_column_layout(self) -> None:
        header = self.queue_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        for column in range(self.queue_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        defaults = {0: 220, 1: 150, 2: 320, 3: 320, 4: 100, 5: 110, 6: 100, 7: 100, 8: 150, 9: 120}
        for column, width in defaults.items():
            if column < self.queue_table.columnCount():
                self.queue_table.setColumnWidth(column, max(width, self.queue_table.columnWidth(column)))

    def restore_table_column_widths(
        self,
        table: QTableWidget,
        key: str,
        defaults: dict[int, int],
        minimums: dict[int, int],
        fixed_widths: dict[int, int] | None = None,
    ) -> None:
        fixed_widths = fixed_widths or {}
        raw = self.settings.get_value(key, None)
        widths = raw if isinstance(raw, list) else []
        header = table.horizontalHeader()
        self._restoring_column_widths = True
        old_blocked = header.blockSignals(True)
        try:
            for column in range(table.columnCount()):
                if column in fixed_widths:
                    width = fixed_widths[column]
                elif column < len(widths):
                    width = safe_column_width(widths[column], minimums.get(column, 50), defaults.get(column, 100))
                else:
                    width = defaults.get(column, 100)
                table.setColumnWidth(column, width)
        finally:
            header.blockSignals(old_blocked)
            self._restoring_column_widths = False

    def save_table_column_widths(self, table: QTableWidget, key: str) -> None:
        if self._initializing_columns or self._restoring_column_widths:
            return
        widths = [max(1, int(table.columnWidth(column))) for column in range(table.columnCount())]
        if key == "file_manager/remote_table/column_widths" and widths:
            widths[0] = 48
        self.settings.set_value(key, widths)

    def refresh_local(self, select_path: Path | None = None) -> None:
        self.local_path.mkdir(parents=True, exist_ok=True)
        self.local_path_label.setText(f"{self.i18n.t('file_management.current_path')}: {self.local_path}")
        entries = sorted(self.local_path.iterdir(), key=lambda path: (not path.is_dir(), path.name.casefold()))
        self.local_table.setRowCount(len(entries))
        selected_row = -1
        for row, path in enumerate(entries):
            stat_result = path.stat()
            values = {
                "name": path.name,
                "size": "" if path.is_dir() else str(stat_result.st_size),
                "modified": format_local_mtime(stat_result.st_mtime),
                "type": self.i18n.t("file_management.type.directory") if path.is_dir() else local_file_type(path),
            }
            for column, (field, _key) in enumerate(LOCAL_COLUMNS):
                item = QTableWidgetItem(values.get(field, ""))
                item.setData(Qt.UserRole, str(path))
                item.setToolTip(str(path if field == "name" else values.get(field, "")))
                if field == "size":
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.local_table.setItem(row, column, item)
            if select_path is not None and path.resolve() == select_path.resolve():
                selected_row = row
        self.apply_table_style_without_saving(self.local_table)
        self.apply_local_column_layout()
        if selected_row >= 0:
            self.local_table.selectRow(selected_row)

    def local_double_clicked(self, row: int, _column: int) -> None:
        item = self.local_table.item(row, 0)
        self.open_local_path_from_item(item)

    def open_local_path_from_item(self, item: QTableWidgetItem | None) -> None:
        if item is None:
            return
        path = Path(str(item.data(Qt.UserRole))).resolve()
        if not path.exists():
            self.refresh_local()
            MessageBox.warning(self, self.i18n.t("file_management.title"), self.i18n.t("file_management.file_not_found"))
            return
        if path.is_dir():
            self.local_path = path
            self.refresh_local()
            return
        self.open_local_file(path)

    def open_local_file(self, path: Path) -> None:
        if not path.exists():
            self.refresh_local()
            MessageBox.warning(self, self.i18n.t("file_management.title"), self.i18n.t("file_management.file_not_found"))
            return
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        if not ok:
            MessageBox.warning(
                self,
                self.i18n.t("file_management.open_file_failed"),
                self.i18n.t("file_management.no_associated_application"),
            )

    def local_up(self) -> None:
        root = self.paths.file_downloads_root(self.site_name)
        if self.local_path.resolve() == root.resolve():
            return
        try:
            self.local_path.resolve().relative_to(root.resolve())
        except ValueError:
            self.local_path = root
        else:
            self.local_path = self.local_path.parent
        self.refresh_local()

    def new_local_folder(self) -> None:
        name, accepted = InputDialog.getText(self, self.i18n.t("file_management.new_folder"), self.i18n.t("file_management.folder_name"))
        if not accepted or not name.strip():
            return
        (self.local_path / safe_device_name(name)).mkdir(parents=True, exist_ok=True)
        self.refresh_local()

    def closeEvent(self, event) -> None:
        self.disconnect_sftp()
        if self.active_worker is not None and self.active_worker.isRunning():
            self.active_worker.cancel()
            self.active_worker.wait(2000)
        super().closeEvent(event)


def format_local_mtime(value: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def local_file_type(path: Path) -> str:
    if path.name.casefold().endswith(".tar.gz"):
        return "tar.gz"
    return path.suffix.lstrip(".") or "file"


def format_speed(bytes_per_second: float) -> str:
    value = float(bytes_per_second)
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


def safe_column_width(value: object, minimum: int, default: int) -> int:
    try:
        width = int(value)
    except (TypeError, ValueError):
        return default
    return max(int(minimum), width)


MESH_HISTORY_LOG_PATTERN = re.compile(r"^\d{4}_\d{2}_\d{2}_\d+meshlog\.log\.gz$", re.IGNORECASE)


def is_mesh_log_file(filename: str) -> bool:
    basename = Path(str(filename or "")).name
    return basename.casefold() == "meshlog.log" or MESH_HISTORY_LOG_PATTERN.match(basename) is not None


def resolve_local_download_name(remote_file: RemoteDeviceFile, device_name: str = "", today: date | None = None) -> str:
    basename = Path(str(remote_file.name or "")).name
    safe_name = safe_device_name(device_name or "device")
    if MESH_HISTORY_LOG_PATTERN.match(basename):
        return f"{safe_name}-{basename}"
    if basename.casefold() != "meshlog.log":
        return basename
    resolved_date = meshlog_modified_date(remote_file.modified_time)
    if resolved_date is None:
        resolved_date = today or date.today()
        app_logger.log_info("MESHLOG_DATE_FALLBACK", f"remote_path={remote_file.remote_path}")
    return f"{safe_name}-{resolved_date:%Y_%m_%d}-meshlog.log"


def meshlog_modified_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text.startswith("1970-01-01"):
        return None
    for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:length], fmt).date()
        except ValueError:
            continue
    return None


def resolve_local_download_path(directory: Path, remote_file: RemoteDeviceFile, device_name: str = "") -> Path:
    filename = resolve_local_download_name(remote_file, device_name)
    target = Path(directory) / filename
    return auto_rename_path(target)


def open_folder(folder: Path) -> bool:
    try:
        path = Path(folder)
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    except Exception as exc:
        app_logger.log_error("FILE_MANAGEMENT_OPEN_FOLDER_FAILED", f"folder={folder}, error={exc}")
        return False
