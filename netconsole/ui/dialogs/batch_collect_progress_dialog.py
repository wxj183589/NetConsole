from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.ui.batch_collect_worker import BatchCollectItemResult, BatchCollectProgressUpdate
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table, make_text_selectable
from netconsole.ui.widgets.adaptive_dialog import install_scrollable_dialog_content


PROGRESS_COLUMN = 3
BATCH_COLLECT_COLUMN_MIN_WIDTHS = {
    0: 170,
    1: 120,
    2: 80,
    3: 110,
    4: 150,
    5: 260,
    6: 100,
    7: 260,
}
BATCH_COLLECT_COLUMN_MAX_WIDTHS = {
    0: 220,
    1: 150,
    2: 100,
    3: 130,
    4: 220,
    5: 420,
    6: 120,
    7: 520,
}


class BatchCollectProgressDialog(QDialog):
    def __init__(self, i18n: I18n, total: int, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.total = total
        self.completed = 0
        self.running = 0
        self.success = 0
        self.failed = 0
        self.row_by_device_key: dict[str, int] = {}
        self.progress_bars_by_device_key: dict[str, QProgressBar] = {}
        self._started_device_keys: set[str] = set()
        self._completed_device_keys: set[str] = set()
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(1080, 600)

        self.summary_label = make_text_selectable(QLabel())
        self.current_label = make_text_selectable(QLabel())
        self.progress = QProgressBar()
        self.progress.setRange(0, total)
        self.table = QTableWidget(total, 8)
        set_table_column_fields(
            self.table,
            [
                "device_name",
                "primary_address",
                "status",
                "progress",
                "stage",
                "command",
                "elapsed",
                "error_message",
            ],
        )
        configure_readonly_table(self.table)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        attach_table_context_menu(self.table, self.i18n.language, include_history=False)
        self.copy_button = QPushButton()
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        self.copy_button.clicked.connect(self.copy_results)

        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.current_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.scroll_area = install_scrollable_dialog_content(self, content, minimum_width=720, minimum_height=460, content_minimum_width=1080)
        self.retranslate()
        self.update_summary()

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("batch_collect.title"))
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("field.device_name"),
                self.i18n.t("field.primary_address"),
                self.i18n.t("field.status"),
                self.i18n.t("field.progress"),
                self.i18n.t("field.stage"),
                self.i18n.t("field.command"),
                self.i18n.t("batch_collect.elapsed"),
                self.i18n.t("batch_collect.error_message"),
            ]
        )
        self.copy_button.setText(self.i18n.t("batch_collect.copy_results"))
        self.close_button.setText(self.i18n.t("dialog.close"))

    def mark_waiting(self, row: int, device_key: str, device_name: str, primary_address: str) -> None:
        self.row_by_device_key[device_key] = row
        progress_bar = QProgressBar(self.table)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(True)
        self.progress_bars_by_device_key[device_key] = progress_bar
        self._set_row(
            row,
            [
                device_name,
                primary_address,
                self.i18n.t("batch_collect.status.waiting"),
                "",
                self.i18n.t("batch_collect.stage.waiting"),
                "",
                "",
                "",
            ],
            skip_columns={PROGRESS_COLUMN},
        )
        self.table.setCellWidget(row, PROGRESS_COLUMN, progress_bar)

    def resize_columns(self) -> None:
        auto_resize_table_columns(
            self.table,
            column_min_widths=BATCH_COLLECT_COLUMN_MIN_WIDTHS,
            column_max_widths=BATCH_COLLECT_COLUMN_MAX_WIDTHS,
            long_text_max_width=520,
        )

    def update_device_progress(self, progress_update: BatchCollectProgressUpdate) -> None:
        row = self.row_by_device_key.get(progress_update.device_key)
        if row is None:
            return
        if progress_update.device_key in self._completed_device_keys:
            return
        if progress_update.percent > 0 and progress_update.device_key not in self._started_device_keys:
            self._started_device_keys.add(progress_update.device_key)
            self.running += 1
        progress_bar = self.progress_bars_by_device_key.get(progress_update.device_key)
        if progress_bar is not None:
            progress_bar.setValue(max(0, min(100, int(progress_update.percent or 0))))
        self._set_cell(row, 2, self._translated(progress_update.status_text))
        self._set_cell(row, 4, self._translated(progress_update.stage))
        self._set_cell(row, 5, progress_update.command or "")
        self._set_cell(row, 6, f"{progress_update.elapsed_ms}ms" if progress_update.elapsed_ms is not None else "")
        self._set_cell(row, 7, progress_update.message or "")
        self.current_label.setText(self.i18n.t("batch_collect.current", device=progress_update.device_name))
        self.update_summary()

    def add_result(self, item: BatchCollectItemResult) -> None:
        row = self.row_by_device_key.get(item.device_key)
        if row is None or item.device_key in self._completed_device_keys:
            return
        self._completed_device_keys.add(item.device_key)
        self.completed += 1
        if item.device_key in self._started_device_keys:
            self.running = max(0, self.running - 1)
        if item.success:
            self.success += 1
            status = self.i18n.t("batch_collect.status.success")
            stage = self.i18n.t("batch_collect.stage.completed")
            message = ""
        else:
            self.failed += 1
            status = self.i18n.t("batch_collect.status.failed")
            stage = self.i18n.t("batch_collect.stage.failed")
            message = item.result_text
        progress_bar = self.progress_bars_by_device_key.get(item.device_key)
        if progress_bar is not None:
            progress_bar.setValue(100)
        self._set_cell(row, 2, status)
        self._set_cell(row, 4, stage)
        self._set_cell(row, 6, f"{item.elapsed_ms}ms" if item.elapsed_ms is not None else "")
        self._set_cell(row, 7, message)
        self.progress.setValue(self.completed)
        self.current_label.setText(self.i18n.t("batch_collect.current", device=item.device_name))
        self.update_summary()
        if self.completed >= self.total:
            self.resize_columns()

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
            values = []
            for column in range(self.table.columnCount()):
                if column == PROGRESS_COLUMN:
                    progress_bar = self.table.cellWidget(row, column)
                    values.append(f"{progress_bar.value()}%" if isinstance(progress_bar, QProgressBar) else "")
                else:
                    item = self.table.item(row, column)
                    values.append(item.text() if item else "")
            if any(values):
                lines.append("\t".join(values))
        QApplication.clipboard().setText("\n".join(lines))

    def _translated(self, value: str) -> str:
        key, separator, arguments = str(value or "").partition("|")
        if not key.startswith("batch_collect."):
            return str(value or "")
        if separator and key == "batch_collect.stage.collecting_command":
            index, _, total = arguments.partition("|")
            return self.i18n.t(key, index=index, total=total)
        return self.i18n.t(key)

    def _set_row(self, row: int, values: list[str], *, skip_columns: set[int] | None = None) -> None:
        for column, value in enumerate(values):
            if column not in (skip_columns or set()):
                self._set_cell(row, column, value)

    def _set_cell(self, row: int, column: int, value: object) -> None:
        text = "" if value is None else str(value)
        item = self.table.item(row, column) or QTableWidgetItem()
        item.setText(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setToolTip(text if text else "")
        self.table.setItem(row, column, item)
