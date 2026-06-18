from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.ui.export_path import remember_export_path, select_export_path
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table
from netconsole.ui.widgets.pagination_widget import PaginationWidget


LOG_EXPORT_FILTER = "Text Files (*.txt);;Log Files (*.log);;All Files (*.*)"


def make_app_log_export_filename(now: datetime | None = None) -> str:
    return f"app_log_{(now or datetime.now()).strftime('%Y-%m-%d-%H%M')}.txt"


class AppLogPage(QWidget):
    def __init__(self, i18n: I18n) -> None:
        super().__init__()
        self.i18n = i18n

        self.search_input = QLineEdit()
        self.level_filter = QComboBox()
        self.refresh_button = QPushButton()
        self.clear_button = QPushButton()
        self.export_current_button = QPushButton()
        self.export_button = QPushButton()
        self.table = QTableWidget(0, 4)
        self.pagination = PaginationWidget(self.i18n)
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.current_rows: list[dict[str, str]] = []
        configure_readonly_table(self.table)
        attach_table_context_menu(self.table, self.i18n.language, include_history=False)

        filters = QHBoxLayout()
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.level_filter)
        filters.addWidget(self.refresh_button)
        filters.addWidget(self.clear_button)
        filters.addWidget(self.export_current_button)
        filters.addWidget(self.export_button)

        layout = QVBoxLayout()
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.pagination)
        self.setLayout(layout)

        self.search_input.textChanged.connect(self.apply_filters)
        self.level_filter.currentIndexChanged.connect(self.apply_filters)
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button.clicked.connect(self.clear_logs)
        self.export_current_button.clicked.connect(self.export_current_page)
        self.export_button.clicked.connect(self.export_logs)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        current_level = self.level_filter.currentData()
        self.search_input.setPlaceholderText(self.i18n.t("logs.search"))
        self.refresh_button.setText(self.i18n.t("logs.refresh"))
        self.clear_button.setText(self.i18n.t("logs.clear"))
        self.export_current_button.setText(self.i18n.t("logs.export_current"))
        self.export_button.setText(self.i18n.t("logs.export"))
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
        for level in ("INFO", "WARNING", "ERROR"):
            self.level_filter.addItem(level, level)
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
        logs = page.rows
        self.current_rows = logs
        self.table.setRowCount(len(logs))
        for row, item in enumerate(logs):
            for column, key in enumerate(("time", "level", "event", "detail")):
                self.table.setItem(row, column, QTableWidgetItem(item[key]))
        auto_resize_table_columns(self.table)

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh()

    def set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.page = 1
        self.refresh()

    def clear_logs(self) -> None:
        answer = QMessageBox.question(self, self.i18n.t("logs.title"), self.i18n.t("logs.clear_confirm"))
        if answer != QMessageBox.Yes:
            return
        app_logger.clear_logs()
        app_logger.log_info("LOGS_CLEARED", self.i18n.t("logs.cleared_detail"))
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
        try:
            _write_log_rows(path, self.current_rows)
            remember_export_path(path)
            app_logger.log_info("LOGS_CURRENT_PAGE_EXPORTED", path.name)
        except Exception as exc:
            app_logger.log_error("LOGS_EXPORT_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("logs.title"), str(exc))
            return
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
        try:
            app_logger.export_logs(path)
            remember_export_path(path)
            app_logger.log_info("LOGS_EXPORTED", path.name)
        except Exception as exc:
            app_logger.log_error("LOGS_EXPORT_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("logs.title"), str(exc))
            return
        self.refresh()


def _write_log_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(
                f"{row.get('time', '')} | {row.get('level', '')} | "
                f"{row.get('event', '')} | {row.get('detail', '')}\n"
            )
