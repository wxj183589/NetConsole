from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
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
from netconsole.services.netmiko_connection import sanitize_sensitive_text
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.table_utils import configure_readonly_table


LOCAL_COLUMNS = (("name", "file_management.name"), ("size", "file_management.size"), ("modified", "file_management.modified"), ("type", "file_management.type"))
REMOTE_COLUMNS = (("name", "file_management.name"), ("size", "file_management.size"), ("modified", "file_management.modified"), ("type", "file_management.type"))
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
    device: Device
    remote_file: RemoteDeviceFile
    local_path: Path
    size: int
    downloaded: int = 0
    status_key: str = "file_management.status.queued"
    speed: str = "-"


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

    def __init__(self, site_name: str, device: Device, paths: PathResolver, parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.device = device
        self.paths = paths

    def run(self) -> None:
        service = FileTransferService(self.site_name, self.paths)
        try:
            root = service.connect(self.device)
            self.connected.emit(service, root)
        except Exception as exc:
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


class FileManagementPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str = "demo", paths: PathResolver | None = None) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths or PathResolver()
        self.sftp_service: FileTransferService | None = None
        self.connected_device: Device | None = None
        self.remote_files: list[RemoteDeviceFile] = []
        self.local_path = self.paths.ensure_site_dirs(site_name) / "raw" / "files"
        self.tasks: list[TransferTask] = []
        self.next_task_id = 1
        self.active_worker: SftpDownloadWorker | None = None
        self.connect_worker: SftpConnectWorker | None = None
        self.list_worker: SftpListWorker | None = None

        self.site_label = QLabel()
        self.device_combo = QComboBox()
        self.device_name_label = QLabel()
        self.ip_label = QLabel()
        self.type_label = QLabel()
        self.connect_button = QPushButton()
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
        self.download_button = QPushButton()
        self.remote_table = QTableWidget(0, len(REMOTE_COLUMNS))
        set_table_column_fields(self.remote_table, [field for field, _key in REMOTE_COLUMNS])
        configure_readonly_table(self.remote_table)

        self.queue_title = QLabel()
        self.queue_table = QTableWidget(0, len(QUEUE_COLUMNS))
        set_table_column_fields(self.queue_table, [field for field, _key in QUEUE_COLUMNS])
        configure_readonly_table(self.queue_table)

        top = QHBoxLayout()
        for widget in (
            self.site_label,
            self.device_combo,
            self.device_name_label,
            self.ip_label,
            self.type_label,
            self.connect_button,
            self.disconnect_button,
            self.connection_status_label,
            self.protocol_label,
        ):
            top.addWidget(widget)
        top.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._local_panel())
        splitter.addWidget(self._remote_panel())
        splitter.setSizes([600, 600])

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.queue_title)
        layout.addWidget(self.queue_table)
        self.setLayout(layout)

        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.connect_button.clicked.connect(self.connect_sftp)
        self.disconnect_button.clicked.connect(self.disconnect_sftp)
        self.local_up_button.clicked.connect(self.local_up)
        self.local_refresh_button.clicked.connect(self.refresh_local)
        self.new_folder_button.clicked.connect(self.new_local_folder)
        self.open_local_button.clicked.connect(lambda: open_folder(self.local_path))
        self.remote_up_button.clicked.connect(self.remote_up)
        self.remote_refresh_button.clicked.connect(self.refresh_remote)
        self.download_button.clicked.connect(self.download_selected)
        self.local_table.cellDoubleClicked.connect(self.local_double_clicked)
        self.remote_table.cellDoubleClicked.connect(self.remote_double_clicked)

        self.retranslate()
        self.refresh_devices()

    def _local_panel(self) -> QWidget:
        panel = QWidget()
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
        controls = QHBoxLayout()
        controls.addWidget(self.remote_up_button)
        controls.addWidget(self.remote_refresh_button)
        controls.addWidget(self.download_button)
        controls.addStretch(1)
        layout = QVBoxLayout(panel)
        layout.addWidget(self.remote_title)
        layout.addWidget(self.remote_path_label)
        layout.addLayout(controls)
        layout.addWidget(self.remote_table, 1)
        return panel

    def retranslate(self) -> None:
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site_name}")
        self.connect_button.setText(self.i18n.t("file_management.connect"))
        self.disconnect_button.setText(self.i18n.t("file_management.disconnect"))
        self.local_title.setText(self.i18n.t("file_management.local_files"))
        self.remote_title.setText(self.i18n.t("file_management.remote_files"))
        self.local_up_button.setText(self.i18n.t("file_management.up"))
        self.remote_up_button.setText(self.i18n.t("file_management.up"))
        self.local_refresh_button.setText(self.i18n.t("file_management.refresh"))
        self.remote_refresh_button.setText(self.i18n.t("file_management.refresh"))
        self.new_folder_button.setText(self.i18n.t("file_management.new_folder"))
        self.open_local_button.setText(self.i18n.t("file_management.open_local_folder"))
        self.download_button.setText(self.i18n.t("file_management.download"))
        self.queue_title.setText(self.i18n.t("file_management.transfer_queue"))
        self.protocol_label.setText(f"{self.i18n.t('file_management.protocol')}: SFTP")
        self.local_table.setHorizontalHeaderLabels([self.i18n.t(key) for _field, key in LOCAL_COLUMNS])
        self.remote_table.setHorizontalHeaderLabels([self.i18n.t(key) for _field, key in REMOTE_COLUMNS])
        self.queue_table.setHorizontalHeaderLabels([self.i18n.t(key) for _field, key in QUEUE_COLUMNS])
        apply_table_style(self.local_table)
        apply_table_style(self.remote_table)
        apply_table_style(self.queue_table)
        self.update_device_labels()
        self.update_connection_status("file_management.status.disconnected")
        self.refresh_local()
        self.refresh_queue()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.disconnect_sftp()
        self.repository = repository
        self.site_name = site_name
        self.local_path = self.paths.ensure_site_dirs(site_name) / "raw" / "files"
        self.refresh_devices()
        self.retranslate()

    def refresh_devices(self) -> None:
        current_id = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self.repository.list():
            if device.id is not None:
                self.device_combo.addItem(str(device.name or device.sysname or device.ip_address), int(device.id))
        index = self.device_combo.findData(current_id)
        self.device_combo.setCurrentIndex(index if index >= 0 else (0 if self.device_combo.count() else -1))
        self.device_combo.blockSignals(False)
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
        self.populate_remote_table()
        self.local_path = self.default_local_dir(device)
        self.local_path.mkdir(parents=True, exist_ok=True)
        self.refresh_local()

    def update_device_labels(self) -> None:
        device = self.current_device()
        if device is None:
            self.device_name_label.setText(self.i18n.t("file_management.no_device"))
            self.ip_label.setText("")
            self.type_label.setText("")
            return
        self.device_name_label.setText(f"{self.i18n.t('field.name')}: {device.name}")
        self.ip_label.setText(f"{self.i18n.t('field.ip_address')}: {device.ip_address}")
        self.type_label.setText(f"{self.i18n.t('field.device_type')}: {device.device_type or '-'}")

    def update_connection_status(self, status_key: str) -> None:
        self.connection_status_label.setText(f"{self.i18n.t('file_management.connection_status')}: {self.i18n.t(status_key)}")

    def default_local_dir(self, device: Device | None) -> Path:
        name = safe_device_name(device.name or device.sysname or "device") if device is not None else "device"
        return self.paths.ensure_site_dirs(self.site_name) / "raw" / "files" / name

    def connect_sftp(self) -> None:
        device = self.current_device()
        if device is None:
            QMessageBox.information(self, self.i18n.t("file_management.title"), self.i18n.t("file_management.no_device"))
            return
        self.disconnect_sftp()
        self.update_connection_status("file_management.status.connecting")
        self.connect_button.setEnabled(False)
        self.connect_worker = SftpConnectWorker(self.site_name, device, self.paths, self)
        self.connect_worker.connected.connect(self.on_connected)
        self.connect_worker.failed.connect(self.on_connect_failed)
        self.connect_worker.finished.connect(self.connect_worker.deleteLater)
        self.connect_worker.finished.connect(lambda: setattr(self, "connect_worker", None))
        self.connect_worker.start()

    def on_connected(self, service: FileTransferService, root_path: str) -> None:
        self.sftp_service = service
        self.connected_device = self.current_device()
        self.connect_button.setEnabled(True)
        self.update_connection_status("file_management.status.connected")
        self.remote_path_label.setText(f"{self.i18n.t('file_management.current_path')}: {root_path}")
        self.refresh_remote()

    def on_connect_failed(self, error: str) -> None:
        self.connect_button.setEnabled(True)
        self.update_connection_status("file_management.status.connection_failed")
        QMessageBox.warning(self, self.i18n.t("file_management.title"), error)

    def disconnect_sftp(self) -> None:
        if self.list_worker and self.list_worker.isRunning():
            self.list_worker.wait(1000)
        if self.sftp_service is not None:
            self.sftp_service.disconnect()
        self.sftp_service = None
        self.connected_device = None
        self.remote_files = []
        self.populate_remote_table()
        self.connect_button.setEnabled(True)
        self.update_connection_status("file_management.status.disconnected")
        self.remote_path_label.setText(f"{self.i18n.t('file_management.current_path')}: -")

    def refresh_remote(self) -> None:
        if self.sftp_service is None or not self.sftp_service.is_connected():
            return
        self.remote_refresh_button.setEnabled(False)
        self.list_worker = SftpListWorker(self.sftp_service, self.sftp_service.current_path or self.sftp_service.root_path, self)
        self.list_worker.listed.connect(self.on_remote_listed)
        self.list_worker.failed.connect(self.on_remote_failed)
        self.list_worker.finished.connect(self.list_worker.deleteLater)
        self.list_worker.finished.connect(lambda: setattr(self, "list_worker", None))
        self.list_worker.start()

    def on_remote_listed(self, remote_path: str, files: list[RemoteDeviceFile]) -> None:
        self.remote_refresh_button.setEnabled(True)
        self.remote_path_label.setText(f"{self.i18n.t('file_management.current_path')}: {remote_path}")
        self.remote_files = files
        self.populate_remote_table()

    def on_remote_failed(self, error: str) -> None:
        self.remote_refresh_button.setEnabled(True)
        QMessageBox.warning(self, self.i18n.t("file_management.title"), error)

    def remote_up(self) -> None:
        if self.sftp_service is None:
            return
        self.start_remote_list(parent_remote_path(self.sftp_service.current_path or self.sftp_service.root_path, self.sftp_service.root_path))

    def start_remote_list(self, path: str) -> None:
        if self.sftp_service is None:
            return
        self.remote_refresh_button.setEnabled(False)
        self.list_worker = SftpListWorker(self.sftp_service, path, self)
        self.list_worker.listed.connect(self.on_remote_listed)
        self.list_worker.failed.connect(self.on_remote_failed)
        self.list_worker.finished.connect(self.list_worker.deleteLater)
        self.list_worker.finished.connect(lambda: setattr(self, "list_worker", None))
        self.list_worker.start()

    def populate_remote_table(self) -> None:
        self.remote_table.setRowCount(len(self.remote_files))
        for row, item in enumerate(self.remote_files):
            values = {
                "name": item.name,
                "size": "" if item.is_dir or item.size is None else str(item.size),
                "modified": item.modified_time or "",
                "type": self.i18n.t("file_management.type.directory") if item.is_dir else item.file_type,
            }
            for column, (field, _key) in enumerate(REMOTE_COLUMNS):
                table_item = QTableWidgetItem(values.get(field, ""))
                table_item.setData(Qt.UserRole, row)
                self.remote_table.setItem(row, column, table_item)
        apply_table_style(self.remote_table)

    def remote_double_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.remote_files):
            return
        item = self.remote_files[row]
        if item.is_dir:
            self.start_remote_list(item.remote_path)
        else:
            self.enqueue_download(item)

    def selected_remote_file(self) -> RemoteDeviceFile | None:
        row = self.remote_table.currentRow()
        if row < 0 or row >= len(self.remote_files):
            return None
        return self.remote_files[row]

    def download_selected(self) -> None:
        item = self.selected_remote_file()
        if item is None or item.is_dir:
            QMessageBox.information(self, self.i18n.t("file_management.title"), self.i18n.t("file_management.select_file"))
            return
        self.enqueue_download(item)

    def enqueue_download(self, remote_file: RemoteDeviceFile) -> None:
        device = self.connected_device or self.current_device()
        if device is None:
            return
        target = self.resolve_download_target(remote_file)
        if target is None:
            return
        task = TransferTask(self.next_task_id, device, remote_file, target, int(remote_file.size or 0))
        self.next_task_id += 1
        self.tasks.append(task)
        self.refresh_queue()
        self.start_next_download()

    def resolve_download_target(self, remote_file: RemoteDeviceFile) -> Path | None:
        target = self.local_path / remote_file.name
        message = self.i18n.t(
            "file_management.download_confirm",
            name=remote_file.name,
            remote_path=remote_file.remote_path,
            size=remote_file.size if remote_file.size is not None else "-",
            local_path=target,
        )
        if target.exists():
            box = QMessageBox(self)
            box.setWindowTitle(self.i18n.t("file_management.download"))
            box.setText(message)
            overwrite = box.addButton(self.i18n.t("file_management.overwrite"), QMessageBox.AcceptRole)
            rename = box.addButton(self.i18n.t("file_management.auto_rename"), QMessageBox.ActionRole)
            cancel = box.addButton(self.i18n.t("file_management.cancel"), QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel:
                return None
            if clicked is rename:
                return auto_rename_path(target)
            if clicked is overwrite:
                return target
            return None
        answer = QMessageBox.question(self, self.i18n.t("file_management.download"), message)
        return target if answer == QMessageBox.Yes else None

    def start_next_download(self) -> None:
        if self.active_worker is not None:
            return
        if FILE_TRANSFER_MAX_CONCURRENCY != 1:
            app_logger.log_warning("FILE_TRANSFER_CONCURRENCY_IGNORED", f"configured={FILE_TRANSFER_MAX_CONCURRENCY}, active=1")
        next_task = next((task for task in self.tasks if task.status_key == "file_management.status.queued"), None)
        if next_task is None:
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
        self.refresh_queue()
        self.refresh_local(select_path=task.local_path)

    def on_download_cancelled(self, task: TransferTask) -> None:
        task.status_key = "file_management.status.cancelled"
        task.speed = "-"
        self.refresh_queue()

    def on_download_failed(self, task: TransferTask, error: str) -> None:
        task.status_key = "file_management.status.verification_failed" if error == "verification_failed" else "file_management.status.failed"
        task.speed = "-"
        self.refresh_queue()

    def refresh_queue(self) -> None:
        self.queue_table.setRowCount(len(self.tasks))
        for row, task in enumerate(self.tasks):
            progress = int(task.downloaded * 100 / task.size) if task.size else 0
            values = {
                "name": task.remote_file.name,
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
                self.queue_table.setItem(row, column, item)
        apply_table_style(self.queue_table)

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
        task.downloaded = 0
        task.status_key = "file_management.status.queued"
        task.speed = "-"
        self.refresh_queue()
        self.start_next_download()

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
                self.local_table.setItem(row, column, item)
            if select_path is not None and path.resolve() == select_path.resolve():
                selected_row = row
        apply_table_style(self.local_table)
        if selected_row >= 0:
            self.local_table.selectRow(selected_row)

    def local_double_clicked(self, row: int, _column: int) -> None:
        item = self.local_table.item(row, 0)
        if item is None:
            return
        path = Path(str(item.data(Qt.UserRole)))
        if path.is_dir():
            self.local_path = path
            self.refresh_local()

    def local_up(self) -> None:
        root = self.paths.ensure_site_dirs(self.site_name) / "raw" / "files"
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
        name, accepted = QInputDialog.getText(self, self.i18n.t("file_management.new_folder"), self.i18n.t("file_management.folder_name"))
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


def open_folder(folder: Path) -> bool:
    try:
        path = Path(folder)
        if platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception as exc:
        app_logger.log_error("FILE_MANAGEMENT_OPEN_FOLDER_FAILED", f"folder={folder}, error={exc}")
        return False
