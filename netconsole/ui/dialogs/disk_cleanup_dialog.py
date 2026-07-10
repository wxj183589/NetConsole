from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.app_auto_cleanup import APP_CLEANUP_RETENTION_DAYS, AppCleanupResult, AppCleanupService, CleanupItem
from netconsole.ui.table_utils import auto_resize_table_columns_to_contents, setup_readable_table
from netconsole.ui.widgets.adaptive_dialog import install_scrollable_dialog_content
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate, is_table_row_checked


class CleanupScanThread(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver, retention_days: int) -> None:
        super().__init__()
        self.paths = paths
        self.retention_days = retention_days

    def run(self) -> None:
        try:
            self.result_ready.emit(AppCleanupService(self.paths).scan_cleanup_items(self.retention_days))
        except Exception as exc:
            app_logger.log_warning("APP_CLEANUP_SCAN_FAILED", str(exc))
            self.failed.emit(str(exc))


class CleanupRunThread(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver, retention_days: int, items: list[CleanupItem]) -> None:
        super().__init__()
        self.paths = paths
        self.retention_days = retention_days
        self.items = items

    def run(self) -> None:
        try:
            self.result_ready.emit(AppCleanupService(self.paths).cleanup_items(self.items, self.retention_days))
        except Exception as exc:
            app_logger.log_warning("APP_CLEANUP_RUN_FAILED", str(exc))
            self.failed.emit(str(exc))


class DiskCleanupDialog(QDialog):
    HEADERS = ("是否清理", "清理项", "说明", "文件数量", "占用空间", "保留策略", "状态")

    def __init__(self, paths: PathResolver, parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.cleanup_items: list[CleanupItem] = []
        self.worker: QThread | None = None
        self.setModal(False)
        self.setWindowTitle("磁盘清理")

        content = QWidget(self)
        layout = QVBoxLayout(content)
        title = QLabel("磁盘清理")
        title.setObjectName("fluentPageTitle")
        subtitle = QLabel("清理软件运行缓存、临时文件和过期运行日志，不会删除采集数据。")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        actions = QHBoxLayout()
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setValue(APP_CLEANUP_RETENTION_DAYS)
        self.scan_button = QPushButton("扫描")
        self.cleanup_button = QPushButton("清理选中")
        self.refresh_button = QPushButton("刷新")
        self.open_cache_button = QPushButton("打开缓存目录")
        self.open_logs_button = QPushButton("打开日志目录")
        actions.addWidget(QLabel("自动清理超过："))
        actions.addWidget(self.retention_spin)
        actions.addWidget(QLabel("天"))
        actions.addSpacing(12)
        for button in (self.scan_button, self.cleanup_button, self.refresh_button, self.open_cache_button, self.open_logs_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status_label = QLabel("未扫描")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        install_checkbox_only_delegate(self.table, 0)
        setup_readable_table(self.table, horizontal_scroll=True, interactive=True, stretch_last_section=False)
        layout.addWidget(self.table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QPushButton("关闭")
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)
        self.scroll_area = install_scrollable_dialog_content(self, content, minimum_width=720, minimum_height=460, content_minimum_width=900)

        self.scan_button.clicked.connect(self.scan)
        self.refresh_button.clicked.connect(self.scan)
        self.cleanup_button.clicked.connect(self.cleanup_selected)
        self.open_cache_button.clicked.connect(lambda: self._open_dir(self.paths.runtime_cache_dir))
        self.open_logs_button.clicked.connect(lambda: self._open_dir(self.paths.logs_dir))
        self.close_button.clicked.connect(self.close)

    def scan(self) -> None:
        if self._worker_running():
            return
        self._set_busy(True, "正在扫描可清理的软件缓存和运行日志...")
        worker = CleanupScanThread(self.paths, self.retention_spin.value())
        self.worker = worker
        worker.result_ready.connect(self._on_scan_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: self._set_worker(None))
        worker.start()

    def cleanup_selected(self) -> None:
        selected = [item for row, item in enumerate(self.cleanup_items) if is_table_row_checked(self.table, row, 0) and item.file_count]
        if not selected:
            MessageBox.information(self, "磁盘清理", "没有可清理的选中项。")
            return
        if MessageBox.question(self, "确认清理", "将清理选中的软件缓存和运行日志，不会删除采集数据。是否继续？") != MessageBox.StandardButton.Yes:
            return
        self._set_busy(True, "正在清理选中的软件缓存和运行日志...")
        worker = CleanupRunThread(self.paths, self.retention_spin.value(), selected)
        self.worker = worker
        worker.result_ready.connect(self._on_cleanup_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: self._set_worker(None))
        worker.start()

    def _on_scan_finished(self, items: list[CleanupItem]) -> None:
        self.cleanup_items = items
        self._populate_table(items)
        total_files = sum(item.file_count for item in items)
        total_bytes = sum(item.total_bytes for item in items)
        self._set_busy(False, f"扫描完成：发现 {total_files} 个过期文件，占用 {_format_size(total_bytes)}。")

    def _on_cleanup_finished(self, result: AppCleanupResult) -> None:
        self._set_busy(False, f"清理完成：删除 {result.deleted_files} 个文件，释放 {_format_size(result.freed_bytes)}，失败 {result.failed_count} 个。")
        if result.failures:
            first = result.failures[0]
            MessageBox.warning(self, "清理部分失败", f"有 {result.failed_count} 个文件清理失败，首个失败：{first.path}\n{first.error}")
        self.scan()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False, f"操作失败：{message}")
        MessageBox.warning(self, "磁盘清理失败", message)

    def _populate_table(self, items: list[CleanupItem]) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, create_checkable_table_item(item.file_count > 0, user_data=item.item_id, enabled=item.file_count > 0))
            values = (item.title, item.description, str(item.file_count), _format_size(item.total_bytes), item.retention_policy, item.status)
            for column, value in enumerate(values, start=1):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, cell)
        auto_resize_table_columns_to_contents(self.table)
        self.table.setUpdatesEnabled(True)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_label.setText(status)
        for widget in (self.scan_button, self.cleanup_button, self.refresh_button, self.retention_spin):
            widget.setEnabled(not busy)

    def _set_worker(self, worker: QThread | None) -> None:
        self.worker = worker

    def _worker_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _open_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._worker_running():
            self.worker.requestInterruption()
            self.worker.quit()
            self.worker.wait(1000)
        super().closeEvent(event)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
