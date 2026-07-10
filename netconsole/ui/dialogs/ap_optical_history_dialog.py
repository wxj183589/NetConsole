from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.core.settings import SettingsStore
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.export.export_task_builders import repository_query_source, table_xlsx_source_spec
from netconsole.ui.dialogs.ap_history_dialog import AP_OPTICAL_HISTORY_COLUMNS
from netconsole.ui.export_path import EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, PaginationState, paginate_rows
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_column_state import TableColumnState
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.ui.window_popup_service import show_non_focus_window


class ApOpticalHistoryDialog(QWidget):
    def __init__(
        self,
        i18n: I18n,
        ap_name: str,
        rows: list[dict[str, object | None]] | None,
        settings: SettingsStore,
        owner: QWidget | None = None,
        *,
        db_path: str | Path | None = None,
        ap_uuid: str = "",
    ) -> None:
        super().__init__(None)
        self.i18n = i18n
        self.ap_name = ap_name
        self.rows = list(rows or [])
        self.visible_rows: list[dict[str, object | None]] = []
        self.db_path = Path(db_path) if db_path else None
        self.ap_uuid = ap_uuid
        self.background_manager = BackgroundProcessManager(self) if self.db_path else None
        self.query_job_id: str | None = None
        if self.background_manager is not None:
            self.background_manager.finished.connect(self._background_finished)
            self.background_manager.failed.connect(self._background_failed)
        self.settings = settings
        self.owner = owner
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(self.i18n.t("ap_detail.optical_history_title", ap=ap_name))
        self.resize(1180, 720)
        self.setMinimumSize(900, 560)
        self._restore_window_state()

        self.back_button = QPushButton()
        self.close_button = QPushButton()
        self.export_button = QPushButton()
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.empty_label = QLabel()
        self.table = QTableWidget()
        self.detail_table = QTableWidget()
        self.pagination = PaginationWidget(i18n)
        self.splitter = QSplitter(Qt.Horizontal)

        for table in (self.table, self.detail_table):
            configure_readonly_table(table)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.ElideRight)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnCount(len(AP_OPTICAL_HISTORY_COLUMNS))
        self.detail_table.setColumnCount(2)
        set_table_column_fields(self.table, [field for _key, field in AP_OPTICAL_HISTORY_COLUMNS])
        set_table_column_fields(self.detail_table, ["name", "value"])
        self.table.itemSelectionChanged.connect(self.refresh_detail)
        self.table.itemDoubleClicked.connect(lambda _item: self.refresh_detail())

        actions = QHBoxLayout()
        actions.addWidget(self.back_button)
        actions.addWidget(self.close_button)
        actions.addStretch(1)
        actions.addWidget(self.export_button)
        actions.addWidget(self.always_on_top_button)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.table, 1)
        left_layout.addWidget(self.pagination)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.detail_table)
        self.splitter.setSizes(self._saved_splitter_sizes())

        layout = QVBoxLayout(self)
        layout.addLayout(actions)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.splitter, 1)

        self.table_state = TableColumnState(settings, self.table, "ac/ap_history/table_column_widths", default_history_widths())
        self.detail_state = TableColumnState(settings, self.detail_table, "ac/ap_history/detail_column_widths", {"name": 180, "value": 360})
        self.back_button.clicked.connect(self.return_to_parent)
        self.close_button.clicked.connect(self.close)
        self.export_button.clicked.connect(self.export_history)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        self.table_state.restore()
        self.detail_state.restore()
        self.refresh_table()

    def retranslate(self) -> None:
        self.back_button.setText(self.i18n.t("history.back"))
        self.close_button.setText(self.i18n.t("dialog.close"))
        self.export_button.setText(self.i18n.t("ac.export_table"))
        self.always_on_top_button.setText(self.i18n.t("window.always_on_top"))
        self.empty_label.setText(self.i18n.t("ap_detail.no_optical_history"))
        self.table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in AP_OPTICAL_HISTORY_COLUMNS])
        self.detail_table.setHorizontalHeaderLabels([self.i18n.t("ap_detail.field_name"), self.i18n.t("ap_detail.field_value")])
        self.pagination.retranslate()

    def refresh_table(self) -> None:
        if self.background_manager is not None:
            self._start_background_query()
            return
        rows, state = paginate_rows(self.rows, self.page_size, self.page)
        self._apply_rows(rows, state)

    def _start_background_query(self) -> None:
        if self.background_manager is None or self.query_job_id is not None:
            return
        self.query_job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type="ac_ap_history_page",
                params={
                    "db_path": str(self.db_path),
                    "ap_uuid": self.ap_uuid,
                    "history_kind": "optical",
                    "page": self.page,
                    "page_size": self.page_size,
                },
            )
        )
        self.export_button.setEnabled(False)

    def _background_finished(self, event: dict) -> None:
        if str(event.get("job_id") or "") != self.query_job_id:
            return
        self.query_job_id = None
        self.export_button.setEnabled(True)
        result = dict(event.get("result") or {})
        rows = [dict(row) for row in result.get("rows") or [] if isinstance(row, dict)]
        state = PaginationState(
            page_size=int(result.get("page_size") or self.page_size),
            current_page=int(result.get("current_page") or 1),
            total_items=int(result.get("total_items") or 0),
            total_pages=int(result.get("total_pages") or 1),
        )
        self._apply_rows(rows, state)

    def _background_failed(self, event: dict) -> None:
        if str(event.get("job_id") or "") != self.query_job_id:
            return
        self.query_job_id = None
        self.export_button.setEnabled(True)
        from netconsole.ui.dialogs.message_service import MessageBox

        MessageBox.warning(self, self.windowTitle(), str(event.get("message") or event.get("error") or "历史查询失败"))

    def _apply_rows(self, rows: list[dict[str, object | None]], state: PaginationState) -> None:
        self.visible_rows = rows
        self.page = state.current_page
        self.pagination.set_state(state)
        self.empty_label.setVisible(state.total_items == 0)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (_key, field) in enumerate(AP_OPTICAL_HISTORY_COLUMNS):
                value = row.get(field)
                item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(str(value) if value not in (None, "") else "")
                self.table.setItem(row_index, column_index, item)
        if rows:
            self.table.selectRow(0)
        self.refresh_detail()

    def refresh_detail(self) -> None:
        row = self.current_record()
        rows = [(self.i18n.t(key), row.get(field)) for key, field in AP_OPTICAL_HISTORY_COLUMNS] if row else []
        self.detail_table.setRowCount(len(rows))
        for row_index, (name, value) in enumerate(rows):
            for column_index, text in enumerate((name, value)):
                item = QTableWidgetItem(str(text) if text not in (None, "") else "-")
                item.setToolTip(str(text) if text not in (None, "") else "")
                self.detail_table.setItem(row_index, column_index, item)

    def current_record(self) -> dict[str, object | None] | None:
        current = self.table.currentRow()
        return self.visible_rows[current] if 0 <= current < len(self.visible_rows) else None

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh_table()

    def set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.page = 1
        self.refresh_table()

    def export_history(self) -> None:
        if self.db_path is None:
            return
        filename = f"{self.ap_name}_optical_history_{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
        path = select_export_path(self, self.i18n.t("ac.export_table"), filename, EXCEL_FILTER)
        if not path:
            return
        headers = [self.i18n.t(key) for key, _field in AP_OPTICAL_HISTORY_COLUMNS]
        submit_export_task(
            self,
            table_xlsx_source_spec(
                Path(path),
                columns=[{"key": field, "title": headers[index]} for index, (_key, field) in enumerate(AP_OPTICAL_HISTORY_COLUMNS)],
                source=repository_query_source(
                    db_path=self.db_path,
                    repository="ac_repository",
                    method="list_fit_ap_history",
                    filters={
                        "ap_uuid": self.ap_uuid,
                        "history_kind": "optical",
                        "color_field": "optical_alarm_status",
                        "language": self.i18n.language,
                    },
                ),
                sheet_name="AP History",
                title=self.i18n.t("ac.export_table"),
                row_fill_field="__row_fill",
            ),
            success_title=self.i18n.t("ac.export_table"),
        )
        remember_export_path(path)

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()

    def return_to_parent(self) -> None:
        self.close()
        if self.owner is not None:
            show_non_focus_window(None, self.owner, key="ap_optical_history_owner", center=False, activate=False, raise_window=False)

    def closeEvent(self, event) -> None:
        self.settings.set_value("ac/ap_history/window_geometry", {"width": self.width(), "height": self.height()})
        self.settings.set_value("ac/ap_history/window_maximized", self.isMaximized())
        self.settings.set_value("ac/ap_history/splitter_state", self.splitter.sizes())
        self.table_state.save_now()
        self.detail_state.save_now()
        super().closeEvent(event)

    def _restore_window_state(self) -> None:
        geometry = self.settings.get_value("ac/ap_history/window_geometry", {})
        if isinstance(geometry, dict):
            try:
                self.resize(max(900, int(geometry.get("width") or 1180)), max(560, int(geometry.get("height") or 720)))
            except (TypeError, ValueError):
                pass
        if self.settings.get_value("ac/ap_history/window_maximized", False):
            self.showMaximized()

    def _saved_splitter_sizes(self) -> list[int]:
        sizes = self.settings.get_value("ac/ap_history/splitter_state", [820, 360])
        return sizes if isinstance(sizes, list) and len(sizes) == 2 else [820, 360]


def default_history_widths() -> dict[str, int]:
    return {
        "collected_at": 170,
        "interface_name": 150,
        "optical_alarm_status": 130,
        "temperature": 100,
        "voltage": 100,
        "bias_current": 110,
        "tx_power": 110,
        "rx_power": 120,
        "module_model": 150,
        "module_serial_number": 170,
        "module_vendor": 120,
    }
