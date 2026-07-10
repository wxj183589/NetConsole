from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.app_auto_cleanup import APP_CLEANUP_RETENTION_DAYS, AppCleanupResult
from netconsole.ui.app_auto_cleanup_runner import AppAutoCleanupThread
from netconsole.ui.export_path import remember_export_path, select_export_path
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.logs.log_display import display_log_level, display_log_row
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, format_row_for_copy
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.services.export.export_task_builders import app_logs_csv_spec


LOG_EXPORT_FILTER = "CSV Files (*.csv);;Text Files (*.txt);;Log Files (*.log);;All Files (*.*)"


def make_app_log_export_filename(now: datetime | None = None) -> str:
    return f"app_log_{(now or datetime.now()).strftime('%Y-%m-%d-%H%M')}.csv"


class AppLogPage(QWidget):
    def __init__(self, i18n: I18n, auto_refresh: bool = True, paths: PathResolver | None = None) -> None:
        super().__init__()
        self.i18n = i18n
        self.paths = paths or PathResolver()

        self.search_input = QLineEdit()
        self.level_filter = QComboBox()
        self.refresh_button = QPushButton()
        self.open_dir_button = QPushButton()
        self.clear_button = QPushButton()
        self.cleanup_button = QPushButton()
        self.export_current_button = QPushButton()
        self.export_button = QPushButton()
        self.cleanup_status_label = QLabel()
        self.table = QTableWidget(0, 4)
        self.pagination = PaginationWidget(self.i18n)
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.current_rows: list[dict[str, str]] = []
        self.cleanup_thread: AppAutoCleanupThread | None = None
        configure_readonly_table(self.table)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        filters = QHBoxLayout()
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.level_filter)
        filters.addWidget(self.refresh_button)
        filters.addWidget(self.open_dir_button)
        filters.addWidget(self.clear_button)
        filters.addWidget(self.cleanup_button)
        filters.addWidget(self.export_current_button)
        filters.addWidget(self.export_button)

        layout = QVBoxLayout()
        layout.addLayout(filters)
        layout.addWidget(self.cleanup_status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.pagination)
        self.setLayout(layout)

        self.search_input.textChanged.connect(self.apply_filters)
        self.level_filter.currentIndexChanged.connect(self.apply_filters)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_dir_button.clicked.connect(self.open_log_dir)
        self.clear_button.clicked.connect(self.clear_logs)
        self.cleanup_button.clicked.connect(self.cleanup_old_logs)
        self.export_current_button.clicked.connect(self.export_current_page)
        self.export_button.clicked.connect(self.export_logs)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        if auto_refresh:
            self.refresh()

    def retranslate(self) -> None:
        current_level = self.level_filter.currentData()
        self.search_input.setPlaceholderText(self.i18n.t("logs.search"))
        self.refresh_button.setText(self.i18n.t("logs.refresh"))
        self.open_dir_button.setText(self.i18n.t("logs.open_dir"))
        self.clear_button.setText(self.i18n.t("logs.clear_records"))
        self.cleanup_button.setText(self.i18n.t("logs.cleanup_old"))
        self.export_current_button.setText(self.i18n.t("logs.export_current"))
        self.export_button.setText(self.i18n.t("logs.export"))
        if not self.cleanup_status_label.text():
            self.cleanup_status_label.setText(self.i18n.t("logs.cleanup_retention_hint", days=APP_CLEANUP_RETENTION_DAYS))
        self.pagination.retranslate()
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("logs.time"),
                self.i18n.t("logs.level"),
                self.i18n.t("logs.event"),
                self.i18n.t("logs.detail"),
            ]
        )
        self.level_filter.blockSignals(True)
        self.level_filter.clear()
        self.level_filter.addItem(self.i18n.t("logs.level.all"), None)
        for level in ("INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"):
            self.level_filter.addItem(display_log_level(level), level)
        index = self.level_filter.findData(current_level)
        self.level_filter.setCurrentIndex(index if index >= 0 else 0)
        self.level_filter.blockSignals(False)

    def apply_filters(self) -> None:
        self.page = 1
        self.refresh()

    def refresh(self) -> None:
        page = app_logger.get_logs(
            page=self.page,
            page_size=self.page_size,
            keyword=self.search_input.text().strip() or None,
            level=self.level_filter.currentData(),
        )
        self.page = page.state.current_page
        self.page_size = page.state.page_size
        self.pagination.set_state(page.state)
        logs = [display_log_row(row) for row in page.rows]
        self.current_rows = logs
        self.table.setRowCount(len(logs))
        for row, item in enumerate(logs):
            for column, key in enumerate(("time", "display_level", "display_event", "display_detail")):
                self._set_log_item(row, column, item, key)
        auto_resize_table_columns(self.table)

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh()

    def set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.page = 1
        self.refresh()

    def clear_logs(self) -> None:
        answer = MessageBox.question(self, self.i18n.t("logs.title"), self.i18n.t("logs.clear_confirm"))
        if answer != MessageBox.Yes:
            return
        app_logger.clear_logs()
        app_logger.log_info("LOGS_CLEARED", self.i18n.t("logs.cleared_detail"))
        self.refresh()

    def open_log_dir(self) -> None:
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.logs_dir)))

    def cleanup_old_logs(self) -> None:
        if self.cleanup_thread is not None and self.cleanup_thread.isRunning():
            return
        self.cleanup_button.setEnabled(False)
        self.cleanup_status_label.setText(self.i18n.t("logs.cleanup_running"))
        self.cleanup_thread = AppAutoCleanupThread(self.paths, APP_CLEANUP_RETENTION_DAYS)
        self.cleanup_thread.result_ready.connect(self._cleanup_finished)
        self.cleanup_thread.failed.connect(self._cleanup_failed)
        self.cleanup_thread.finished.connect(self.cleanup_thread.deleteLater)
        self.cleanup_thread.finished.connect(lambda: setattr(self, "cleanup_thread", None))
        self.cleanup_thread.finished.connect(lambda: self.cleanup_button.setEnabled(True))
        self.cleanup_thread.start()

    def _cleanup_finished(self, result: object) -> None:
        if isinstance(result, AppCleanupResult):
            self.cleanup_status_label.setText(
                self.i18n.t(
                    "logs.cleanup_done",
                    files=result.deleted_files,
                    size=_format_bytes(result.freed_bytes),
                    failed=result.failed_count,
                )
            )
        self.refresh()

    def _cleanup_failed(self, message: str) -> None:
        app_logger.log_warning("APP_AUTO_CLEANUP_FAILED", message)
        self.cleanup_status_label.setText(self.i18n.t("logs.cleanup_failed", error=message))
        self.refresh()

    def export_current_page(self) -> None:
        path = select_export_path(
            self,
            self.i18n.t("logs.export_current"),
            make_app_log_export_filename(),
            LOG_EXPORT_FILTER,
        )
        if path is None:
            return
        submit_export_task(
            self,
            app_logs_csv_spec(
                path,
                log_path=self.paths.app_log_path,
                keyword=self.search_input.text().strip() or None,
                level=self.level_filter.currentData(),
                offset=(self.page - 1) * self.page_size,
                limit=self.page_size,
                title=self.i18n.t("logs.export_current"),
            ),
            success_title=self.i18n.t("logs.export_current"),
        )
        remember_export_path(path)
        app_logger.log_info("LOGS_CURRENT_PAGE_EXPORT_STARTED", path.name)
        self.refresh()

    def export_logs(self) -> None:
        path = select_export_path(
            self,
            self.i18n.t("logs.export"),
            make_app_log_export_filename(),
            LOG_EXPORT_FILTER,
        )
        if path is None:
            return
        submit_export_task(
            self,
            app_logs_csv_spec(
                path,
                log_path=self.paths.app_log_path,
                keyword=self.search_input.text().strip() or None,
                level=self.level_filter.currentData(),
                title=self.i18n.t("logs.export"),
            ),
            success_title=self.i18n.t("logs.export"),
        )
        remember_export_path(path)
        app_logger.log_info("LOGS_EXPORT_STARTED", path.name)
        self.refresh()

    def _set_log_item(self, row: int, column: int, source: dict[str, str], key: str) -> None:
        item = QTableWidgetItem(source.get(key, ""))
        item.setTextAlignment(Qt.AlignCenter if column in {0, 1} else Qt.AlignLeft | Qt.AlignVCenter)
        if column == 1:
            _apply_level_color(item, source.get("raw_level", source.get("level", "")))
        if column == 2:
            item.setToolTip(f"原始事件：{source.get('raw_event', '')}")
        elif column == 3:
            item.setToolTip(f"中文详情：{source.get('display_detail', '')}\n原始详情：{source.get('raw_detail', '')}")
        else:
            item.setToolTip(item.text())
        self.table.setItem(row, column, item)

    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        row = index.row()
        column = index.column()
        menu = QMenu(self.table)
        copy_cell = menu.addAction("复制单元格")
        copy_cell.setEnabled(row >= 0 and column >= 0 and self.table.item(row, column) is not None)
        copy_row = menu.addAction("复制整行")
        copy_row.setEnabled(row >= 0)
        menu.addSeparator()
        copy_zh_detail = menu.addAction("复制中文详情")
        copy_raw_detail = menu.addAction("复制原始详情")
        copy_raw_event = menu.addAction("复制原始事件")
        for action in (copy_zh_detail, copy_raw_detail, copy_raw_event):
            action.setEnabled(0 <= row < len(self.current_rows))
        action = menu.exec(self.table.viewport().mapToGlobal(position))
        if action is copy_cell:
            item = self.table.item(row, column)
            QApplication.clipboard().setText(item.text() if item else "")
        elif action is copy_row:
            headers = [self.table.horizontalHeaderItem(col).text() if self.table.horizontalHeaderItem(col) else "" for col in range(self.table.columnCount())]
            values = [self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())]
            QApplication.clipboard().setText(format_row_for_copy(headers, values))
        elif 0 <= row < len(self.current_rows):
            item = self.current_rows[row]
            if action is copy_zh_detail:
                QApplication.clipboard().setText(item.get("display_detail", ""))
            elif action is copy_raw_detail:
                QApplication.clipboard().setText(item.get("raw_detail", ""))
            elif action is copy_raw_event:
                QApplication.clipboard().setText(item.get("raw_event", ""))


def _log_export_columns() -> list[dict[str, str]]:
    return [
        {"key": "time", "title": "时间"},
        {"key": "display_level", "title": "级别"},
        {"key": "display_event", "title": "事件"},
        {"key": "display_detail", "title": "详情"},
        {"key": "raw_event", "title": "原始事件"},
        {"key": "raw_detail", "title": "原始详情"},
    ]


def _apply_level_color(item: QTableWidgetItem, level: str) -> None:
    color = {
        "WARNING": QColor("#B45309"),
        "ERROR": QColor("#DC2626"),
        "CRITICAL": QColor("#7F1D1D"),
        "DEBUG": QColor("#6B7280"),
    }.get(str(level or "").upper())
    if color is not None:
        item.setForeground(color)


def _format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"
