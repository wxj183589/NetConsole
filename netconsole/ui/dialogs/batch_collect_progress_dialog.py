from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.ui.batch_collect_worker import BATCH_CONCURRENCY, BatchCollectItemResult
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table, make_text_selectable


class BatchCollectProgressDialog(QDialog):
    def __init__(self, i18n: I18n, total: int, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.total = total
        self.completed = 0
        self.running = 0
        self.success = 0
        self.failed = 0
        self.concurrency_combo = QComboBox()
        for value in (5, 10, 20, 50, 100):
            self.concurrency_combo.addItem(str(value), value)
        self.concurrency_combo.setCurrentText(str(BATCH_CONCURRENCY))
        self.setModal(False)
        self.setMinimumSize(820, 520)
        self.resize(900, 560)

        self.summary_label = make_text_selectable(QLabel())
        self.current_label = make_text_selectable(QLabel())
        self.progress = QProgressBar()
        self.progress.setRange(0, total)
        self.table = QTableWidget(total, 5)
        set_table_column_fields(self.table, ["device_name", "primary_address", "status", "elapsed", "error_message"])
        configure_readonly_table(self.table)
        attach_table_context_menu(self.table, self.i18n.language, include_history=False)
        self.copy_button = QPushButton()
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        self.copy_button.clicked.connect(self.copy_results)

        buttons = QHBoxLayout()
        buttons.addWidget(QLabel(self.i18n.t("batch_collect.concurrency")))
        buttons.addWidget(self.concurrency_combo)
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout()
        layout.addWidget(self.summary_label)
        layout.addWidget(self.current_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.setLayout(layout)
        self.retranslate()
        self.update_summary()

    def set_running(self, running: bool) -> None:
        self.concurrency_combo.setEnabled(not running)

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("batch_collect.title"))
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("field.device_name"),
                self.i18n.t("field.primary_address"),
                self.i18n.t("field.status"),
                self.i18n.t("batch_collect.elapsed"),
                self.i18n.t("batch_collect.error_message"),
            ]
        )
        self.copy_button.setText(self.i18n.t("batch_collect.copy_results"))
        self.close_button.setText(self.i18n.t("dialog.close"))

    def mark_running(self, row: int, device_name: str, primary_address: str) -> None:
        self.running += 1
        self.current_label.setText(self.i18n.t("batch_collect.current", device=device_name))
        self._set_row(row, [device_name, primary_address, self.i18n.t("batch_collect.status.running"), "", ""])
        self.update_summary()

    def add_result(self, row: int, item: BatchCollectItemResult) -> None:
        self.completed += 1
        self.running = max(0, self.running - 1)
        if item.success:
            self.success += 1
            status = self.i18n.t("batch_collect.status.success")
        else:
            self.failed += 1
            status = self.i18n.t("batch_collect.status.failed")
        elapsed = f"{item.elapsed_ms}ms" if item.elapsed_ms is not None else ""
        self._set_row(row, [item.device_name, item.primary_address, status, elapsed, "" if item.success else item.result_text])
        self.progress.setValue(self.completed)
        self.current_label.setText(self.i18n.t("batch_collect.current", device=item.device_name))
        self.update_summary()

    def update_summary(self) -> None:
        self.summary_label.setText(
            self.i18n.t(
                "batch_collect.summary",
                total=self.total,
                running=self.running,
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
            self.table.setItem(row, column, item)
        auto_resize_table_columns(self.table)
