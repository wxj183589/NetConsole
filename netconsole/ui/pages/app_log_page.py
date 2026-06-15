from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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
from netconsole.ui.table_utils import attach_table_context_menu, configure_readonly_table


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
        self.export_button = QPushButton()
        self.table = QTableWidget(0, 4)
        configure_readonly_table(self.table)
        attach_table_context_menu(self.table, self.i18n.language, include_history=False)

        filters = QHBoxLayout()
        filters.addWidget(self.search_input, 1)
        filters.addWidget(self.level_filter)
        filters.addWidget(self.refresh_button)
        filters.addWidget(self.clear_button)
        filters.addWidget(self.export_button)

        layout = QVBoxLayout()
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        self.setLayout(layout)

        self.search_input.textChanged.connect(self.refresh)
        self.level_filter.currentIndexChanged.connect(self.refresh)
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button.clicked.connect(self.clear_logs)
        self.export_button.clicked.connect(self.export_logs)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        current_level = self.level_filter.currentData()
        self.search_input.setPlaceholderText(self.i18n.t("logs.search"))
        self.refresh_button.setText(self.i18n.t("logs.refresh"))
        self.clear_button.setText(self.i18n.t("logs.clear"))
        self.export_button.setText(self.i18n.t("logs.export"))
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

    def refresh(self) -> None:
        logs = app_logger.read_logs(
            keyword=self.search_input.text().strip() or None,
            level=self.level_filter.currentData(),
        )
        self.table.setRowCount(len(logs))
        for row, item in enumerate(logs):
            for column, key in enumerate(("time", "level", "event", "detail")):
                self.table.setItem(row, column, QTableWidgetItem(item[key]))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def clear_logs(self) -> None:
        answer = QMessageBox.question(self, self.i18n.t("logs.title"), self.i18n.t("logs.clear_confirm"))
        if answer != QMessageBox.Yes:
            return
        app_logger.clear_logs()
        app_logger.log_info("LOGS_CLEARED", self.i18n.t("logs.cleared_detail"))
        self.refresh()

    def export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.i18n.t("logs.export"),
            make_app_log_export_filename(),
            "Text Files (*.txt);;Log Files (*.log);;All Files (*.*)",
        )
        if not path:
            return
        try:
            app_logger.export_logs(Path(path))
            app_logger.log_info("LOGS_EXPORTED", Path(path).name)
        except Exception as exc:
            app_logger.log_error("LOGS_EXPORT_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("logs.title"), str(exc))
            return
        self.refresh()
