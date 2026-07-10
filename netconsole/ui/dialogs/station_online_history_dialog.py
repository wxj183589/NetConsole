from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.pagination import PaginationState
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.export_path import EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, create_table_context_menu
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.ui.widgets.adaptive_dialog import install_scrollable_widget_content
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.export.export_task_builders import repository_query_source, table_xlsx_source_spec
from netconsole.services.history_export_service import export_station_online_history_xlsx as _export_station_online_history_xlsx


STATION_ONLINE_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("ac.station", "site_name"),
    ("ac.ap_total", "ap_total"),
    ("ac.online", "online_count"),
    ("ac.offline", "offline_count"),
    ("ac.online_rate", "online_rate"),
    ("field.remark", "remark"),
)


def export_station_online_history_xlsx(path: Path, rows: list[dict[str, object | None]], headers: list[str]) -> None:
    _export_station_online_history_xlsx(path, rows, STATION_ONLINE_HISTORY_COLUMNS, headers)


class StationOnlineHistoryDialog(QWidget):
    def __init__(
        self,
        i18n: I18n,
        rows: list[dict[str, object | None]] | None = None,
        site_name: str | None = None,
        *,
        db_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.i18n = i18n
        self.rows = list(rows or [])
        self.site_name = site_name
        self.db_path = Path(db_path) if db_path else None
        self.background_manager = BackgroundProcessManager(self) if self.db_path else None
        self.query_job_id: str | None = None
        if self.background_manager is not None:
            self.background_manager.finished.connect(self._background_finished)
            self.background_manager.failed.connect(self._background_failed)
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE

        self.station_filter = QComboBox()
        self.export_button = QPushButton()
        self.table = QTableWidget()
        self.pagination = PaginationWidget(self.i18n)
        set_table_column_fields(self.table, [field for _key, field in STATION_ONLINE_HISTORY_COLUMNS])
        configure_readonly_table(self.table)
        self.table.setColumnCount(len(STATION_ONLINE_HISTORY_COLUMNS))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        actions = QHBoxLayout()
        actions.addWidget(self.station_filter)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.pagination)
        self.scroll_area = install_scrollable_widget_content(
            self,
            content,
            minimum_width=720,
            minimum_height=420,
            content_minimum_width=860,
        )

        self.station_filter.currentIndexChanged.connect(self.filter_changed)
        self.export_button.clicked.connect(self.export_history)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        self.populate_station_filter()
        self.refresh_table()
        self.resize(920, 520)

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("ac.online_history"))
        self.export_button.setText(self.i18n.t("ac.export_table"))
        self.table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in STATION_ONLINE_HISTORY_COLUMNS])

    def populate_station_filter(self) -> None:
        self.station_filter.blockSignals(True)
        self.station_filter.clear()
        self.station_filter.addItem(self.i18n.t("field.all"), "")
        sites = {str(row.get("site_name") or "") for row in self.rows if row.get("site_name")}
        if self.site_name:
            sites.add(self.site_name)
        for site in sorted(sites):
            self.station_filter.addItem(site, site)
        if self.site_name:
            index = self.station_filter.findData(self.site_name)
            if index >= 0:
                self.station_filter.setCurrentIndex(index)
        self.station_filter.blockSignals(False)

    def filtered_rows(self) -> list[dict[str, object | None]]:
        site = str(self.station_filter.currentData() or "")
        if not site:
            return self.rows
        return [row for row in self.rows if str(row.get("site_name") or "") == site]

    def refresh_table(self) -> None:
        if self.db_path is not None:
            self._start_background_query()
            return
        rows, state = paginate_rows(self.filtered_rows(), self.page_size, self.page)
        self._apply_rows(rows, state)

    def _start_background_query(self) -> None:
        if self.background_manager is None or self.query_job_id is not None:
            return
        self.query_job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type="ac_station_online_history_page",
                params={
                    "db_path": str(self.db_path),
                    "site_name": str(self.station_filter.currentData() or ""),
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
        self.rows = [dict(row) for row in result.get("rows") or [] if isinstance(row, dict)]
        state = PaginationState(
            page_size=int(result.get("page_size") or self.page_size),
            current_page=int(result.get("current_page") or 1),
            total_items=int(result.get("total_items") or 0),
            total_pages=int(result.get("total_pages") or 1),
        )
        self.page = state.current_page
        self._apply_rows(self.rows, state)

    def _background_failed(self, event: dict) -> None:
        if str(event.get("job_id") or "") != self.query_job_id:
            return
        self.query_job_id = None
        self.export_button.setEnabled(True)
        from netconsole.ui.dialogs.message_service import MessageBox

        MessageBox.warning(self, self.windowTitle(), str(event.get("message") or event.get("error") or "历史查询失败"))

    def _apply_rows(self, rows: list[dict[str, object | None]], state: PaginationState) -> None:
        self.page = state.current_page
        self.pagination.set_state(state)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (_key, field) in enumerate(STATION_ONLINE_HISTORY_COLUMNS):
                item = QTableWidgetItem(str(row.get(field) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(True)
        auto_resize_table_columns(self.table)

    def filter_changed(self) -> None:
        self.page = 1
        self.refresh_table()

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh_table()

    def set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.page = 1
        self.refresh_table()

    def show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        menu = create_table_context_menu(self.table, index.row(), index.column(), self.i18n.language, include_history=False)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def export_history(self) -> None:
        if self.db_path is None:
            return
        path = select_export_path(self, self.i18n.t("ac.export_table"), "AP上线历史.xlsx", EXCEL_FILTER)
        if not path:
            return
        headers = [self.i18n.t(key) for key, _field in STATION_ONLINE_HISTORY_COLUMNS]
        submit_export_task(
            self,
            table_xlsx_source_spec(
                path,
                columns=[{"key": field, "title": headers[index]} for index, (_key, field) in enumerate(STATION_ONLINE_HISTORY_COLUMNS)],
                source=repository_query_source(
                    db_path=self.db_path,
                    repository="ac_repository",
                    method="list_station_online_summary_history",
                    filters={"site_name": str(self.station_filter.currentData() or "")},
                ),
                sheet_name="AP Online History",
                title=self.i18n.t("ac.export_table"),
            ),
            success_title=self.i18n.t("ac.export_table"),
        )
        remember_export_path(path)
