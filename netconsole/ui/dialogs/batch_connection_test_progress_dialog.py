from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.ui.batch_connection_worker import (
    BATCH_CONNECTION_CONCURRENCY_OPTIONS,
    BATCH_CONNECTION_DEFAULT_CONCURRENCY,
    BatchConnectionTestItemResult,
)
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table, make_text_selectable


BATCH_CONNECTION_COLUMN_MIN_WIDTHS = {
    0: 170,
    1: 120,
    2: 80,
    3: 110,
    4: 80,
    5: 120,
    6: 100,
    7: 260,
}
BATCH_CONNECTION_COLUMN_MAX_WIDTHS = {
    0: 220,
    1: 150,
    2: 100,
    3: 140,
    4: 100,
    5: 180,
    6: 120,
    7: 520,
}


class BatchConnectionTestProgressDialog(QDialog):
    def __init__(self, i18n: I18n, total: int, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.total = total
        self.completed = 0
        self.success = 0
        self.failed = 0
        self.concurrency_combo = QComboBox()
        for value in BATCH_CONNECTION_CONCURRENCY_OPTIONS:
            self.concurrency_combo.addItem(str(value), value)
        self.concurrency_combo.setCurrentText(str(BATCH_CONNECTION_DEFAULT_CONCURRENCY))
        self.setMinimumSize(820, 500)
        self.resize(900, 540)

        self.summary_label = make_text_selectable(QLabel())
        self.progress = QProgressBar()
        self.progress.setRange(0, total)
        self.table = QTableWidget(total, 8)
        set_table_column_fields(self.table, ["device_name", "primary_address", "protocol", "method", "status", "prompt", "elapsed", "error_message"])
        configure_readonly_table(self.table)
        attach_table_context_menu(self.table, self.i18n.language, include_history=False)
        self.copy_button = QPushButton()
        self.close_button = QPushButton()
        self.copy_button.clicked.connect(self.copy_results)
        self.close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(QLabel(self.i18n.t("batch_collect.concurrency")))
        buttons.addWidget(self.concurrency_combo)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout()
        layout.addWidget(self.summary_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.setLayout(layout)
        self.retranslate()
        self.update_summary()

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("batch_test.title"))
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("field.device_name"),
                self.i18n.t("field.primary_address"),
                self.i18n.t("field.protocol"),
                self.i18n.t("field.connection_method"),
                self.i18n.t("field.status"),
                "Prompt",
                self.i18n.t("batch_collect.elapsed"),
                self.i18n.t("batch_collect.error_message"),
            ]
        )
        self.copy_button.setText(self.i18n.t("batch_collect.copy_results"))
        self.close_button.setText(self.i18n.t("dialog.close"))

    def mark_waiting(self, row: int, device_name: str, primary_address: str) -> None:
        self._set_row(row, [device_name, primary_address, "", "", self.i18n.t("batch_collect.status.waiting"), "", "", ""])

    def add_result(self, row: int, item: BatchConnectionTestItemResult) -> None:
        self.completed += 1
        if item.success:
            self.success += 1
            status = self.i18n.t("batch_collect.status.success")
        else:
            self.failed += 1
            status = self.i18n.t("batch_collect.status.failed")
        elapsed = f"{item.elapsed_ms}ms" if item.elapsed_ms is not None else ""
        self._set_row(row, [item.device_name, item.primary_address, item.protocol, item.method, status, item.prompt or "", elapsed, item.error_message or ""])
        self.progress.setValue(self.completed)
        self.update_summary()

    def update_summary(self) -> None:
        self.summary_label.setText(
            self.i18n.t(
                "batch_collect.summary",
                total=self.total,
                running=max(0, self.total - self.completed),
                completed=self.completed,
                success=self.success,
                failed=self.failed,
            )
        )

    def copy_results(self) -> None:
        lines = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, column).text() if self.table.item(row, column) else "" for column in range(self.table.columnCount())]
            if any(values):
                lines.append("\t".join(values))
        QApplication.clipboard().setText("\n".join(lines))

    def _set_row(self, row: int, values: list[str]) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            if value:
                item.setToolTip(value)
            self.table.setItem(row, column, item)
        auto_resize_table_columns(
            self.table,
            column_min_widths=BATCH_CONNECTION_COLUMN_MIN_WIDTHS,
            column_max_widths=BATCH_CONNECTION_COLUMN_MAX_WIDTHS,
            long_text_max_width=520,
        )
