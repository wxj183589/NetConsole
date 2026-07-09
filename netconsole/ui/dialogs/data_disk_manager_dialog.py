from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.data_disk_manager import clean_data_disk, scan_data_disk
from netconsole.ui.table_utils import auto_fit_table_columns


class DataDiskScanThread(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver) -> None:
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        try:
            self.result_ready.emit(scan_data_disk(self.paths.data_dir, self.paths.runtime_dir))
        except Exception as exc:
            self.failed.emit(str(exc))


class DataDiskCleanThread(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver, categories: set[str]) -> None:
        super().__init__()
        self.paths = paths
        self.categories = set(categories)

    def run(self) -> None:
        try:
            self.result_ready.emit(clean_data_disk(self.paths.data_dir, self.paths.runtime_dir, self.categories))
        except Exception as exc:
            self.failed.emit(str(exc))


class DataDiskManagerDialog(QDialog):
    def __init__(self, i18n: I18n, paths: PathResolver, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.paths = paths
        self.categories: list[str] = []
        self.scan_thread: DataDiskScanThread | None = None
        self.clean_thread: DataDiskCleanThread | None = None
        self.setMinimumSize(680, 420)

        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("data_disk.category"),
                self.i18n.t("data_disk.path"),
                self.i18n.t("data_disk.size"),
                self.i18n.t("data_disk.cleanable"),
            ]
        )
        root.addWidget(self.table, 1)
        self.status_label = QLabel()
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.refresh_button = QPushButton(self.i18n.t("dialog.refresh"))
        self.clean_button = QPushButton(self.i18n.t("data_disk.clean_selected"))
        self.close_button = QPushButton(self.i18n.t("dialog.cancel"))
        self.refresh_button.clicked.connect(self.refresh)
        self.clean_button.clicked.connect(self.clean_selected)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.clean_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("data_disk.title"))

    def refresh(self) -> None:
        if self.scan_thread is not None and self.scan_thread.isRunning():
            return
        self._set_busy(True, self.i18n.t("data_disk.scanning"))
        self.scan_thread = DataDiskScanThread(self.paths)
        self.scan_thread.result_ready.connect(self._apply_scan_result)
        self.scan_thread.failed.connect(self._show_scan_failed)
        self.scan_thread.finished.connect(lambda: self._set_busy(False, ""))
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(lambda: setattr(self, "scan_thread", None))
        self.scan_thread.start()

    def _apply_scan_result(self, rows: object) -> None:
        self.categories = [row.name for row in rows]
        self.table.setRowCount(len(rows))
        for row_index, category in enumerate(rows):
            values = (
                self.i18n.t(f"data_disk.category.{category.name}"),
                str(category.path),
                _format_bytes(category.bytes),
                self.i18n.t("dialog.yes" if category.cleanable else "dialog.no"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, category.name)
                self.table.setItem(row_index, column, item)
        auto_fit_table_columns(self.table, max_rows=100)

    def clean_selected(self) -> None:
        if self.clean_thread is not None and self.clean_thread.isRunning():
            return
        selected = {
            self.categories[index.row()]
            for index in self.table.selectionModel().selectedRows()
            if 0 <= index.row() < len(self.categories)
        }
        if not selected:
            selected = {"legacy_debug_data", "debug_logs", "runtime_cache"}
        cleanable = selected & {"legacy_debug_data", "debug_logs", "runtime_cache"}
        if not cleanable:
            MessageBox.information(self, self.windowTitle(), self.i18n.t("data_disk.no_cleanable_selected"))
            return
        answer = MessageBox.question(self, self.windowTitle(), self.i18n.t("data_disk.clean_confirm"))
        if answer != MessageBox.Yes:
            return
        self._set_busy(True, self.i18n.t("data_disk.cleaning"))
        self.clean_thread = DataDiskCleanThread(self.paths, cleanable)
        self.clean_thread.result_ready.connect(self._show_clean_done)
        self.clean_thread.failed.connect(self._show_clean_failed)
        self.clean_thread.finished.connect(lambda: self._set_busy(False, ""))
        self.clean_thread.finished.connect(self.clean_thread.deleteLater)
        self.clean_thread.finished.connect(lambda: setattr(self, "clean_thread", None))
        self.clean_thread.start()

    def _show_clean_done(self, result: object) -> None:
        removed = sum(result.values())
        MessageBox.information(self, self.windowTitle(), self.i18n.t("data_disk.clean_done", size=_format_bytes(removed)))
        self.refresh()

    def _show_scan_failed(self, message: str) -> None:
        MessageBox.warning(self, self.windowTitle(), self.i18n.t("data_disk.scan_failed", error=message))

    def _show_clean_failed(self, message: str) -> None:
        MessageBox.warning(self, self.windowTitle(), self.i18n.t("data_disk.clean_failed", error=message))

    def _set_busy(self, busy: bool, message: str) -> None:
        self.refresh_button.setEnabled(not busy)
        self.clean_button.setEnabled(not busy)
        self.status_label.setText(message)


def _format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"
