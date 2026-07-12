from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, PaginationState, paginate_rows
from netconsole.ui.theme.contrast_engine import apply_item_contrast
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.export_path import EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, create_table_context_menu
from netconsole.ui.widgets.adaptive_dialog import install_scrollable_dialog_content
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.ui.window_popup_service import show_non_focus_window
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.export.export_task_builders import repository_query_source, table_xlsx_source_spec
from netconsole.services.history_export_service import OPTICAL_HISTORY_COLORS, export_ap_history_xlsx as _export_ap_history_xlsx, history_display_value


AP_RADIO_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("ac.ap_name", "ap_name"),
    ("RID", "rid"),
    ("ap.channel", "channel"),
    ("ap.bandwidth", "bandwidth"),
    ("ap.tx_power", "tx_power"),
)
AP_LLDP_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("LLDP来源", "source"),
    ("是否变化", "is_changed"),
    ("冲突标记", "conflict_flag"),
    ("details.local_interface", "local_interface"),
    ("ac.lldp_neighbor", "lldp_neighbor"),
    ("ap.neighbor_interface", "neighbor_interface"),
    ("ap.neighbor_mac", "neighbor_mac"),
    ("ap.neighbor_device_name", "neighbor_device_name"),
)
AP_OPTICAL_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("ap.interface", "interface_name"),
    ("ap.optical_alarm_status", "optical_alarm_status"),
    ("ap.temperature", "temperature"),
    ("details.voltage", "voltage"),
    ("details.bias_current", "bias_current"),
    ("ap.tx_power", "tx_power"),
    ("ap.rx_power", "rx_power"),
    ("details.rx_low_alarm", "rx_low_alarm"),
    ("details.rx_high_alarm", "rx_high_alarm"),
    ("details.tx_low_alarm", "tx_low_alarm"),
    ("details.tx_high_alarm", "tx_high_alarm"),
    ("details.rx_low_warning", "rx_low_warning"),
    ("details.rx_high_warning", "rx_high_warning"),
    ("details.tx_low_warning", "tx_low_warning"),
    ("details.tx_high_warning", "tx_high_warning"),
    ("details.module_model", "module_model"),
    ("details.module_serial_number", "module_serial_number"),
    ("details.vendor", "module_vendor"),
    ("details.wavelength", "wavelength"),
    ("details.transmission_distance", "transmission_distance"),
    ("details.connector_type", "connector_type"),
)
def export_ap_history_xlsx(path: Path, rows: list[dict[str, object | None]], columns: tuple[tuple[str, str], ...], headers: list[str], color_field: str | None = None) -> None:
    _export_ap_history_xlsx(path, rows, columns, headers, color_field)


class ApHistoryDialog(QWidget):
    def __init__(
        self,
        i18n: I18n,
        ap_name: str,
        history_type: str,
        rows: list[dict[str, object | None]] | None,
        columns: tuple[tuple[str, str], ...],
        color_field: str | None = None,
        owner=None,
        parent=None,
        *,
        db_path: str | Path | None = None,
        ap_uuid: str = "",
        history_kind: str = "",
    ) -> None:
        super().__init__(None)
        self.i18n = i18n
        self.ap_name = ap_name
        self.history_type = history_type
        self.rows = list(rows or [])
        self.visible_rows: list[dict[str, object | None]] = []
        self.columns = columns
        self.color_field = color_field
        self.owner = owner if owner is not None else parent
        self.db_path = Path(db_path) if db_path else None
        self.ap_uuid = ap_uuid
        self.history_kind = history_kind
        self.background_manager = BackgroundProcessManager(self) if self.db_path else None
        self.query_job_id: str | None = None
        if self.background_manager is not None:
            self.background_manager.finished.connect(self._background_finished)
            self.background_manager.failed.connect(self._background_failed)
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(self.i18n.t("history.title_with_object", device=ap_name, object=history_type))
        self.resize(900, 560)

        self.back_button = QPushButton()
        self.close_button = QPushButton()
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.export_button = QPushButton()
        self.table = QTableWidget()
        self.detail_table = QTableWidget()
        self.pagination = PaginationWidget(self.i18n)
        self.splitter = QSplitter(Qt.Horizontal)
        set_table_column_fields(self.table, [field for _key, field in columns])
        set_table_column_fields(self.detail_table, ["name", "value"])
        configure_readonly_table(self.table)
        configure_readonly_table(self.detail_table)
        self.table.setWordWrap(False)
        self.detail_table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.detail_table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.detail_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.detail_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setColumnCount(len(columns))
        self.detail_table.setColumnCount(2)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemSelectionChanged.connect(self.refresh_detail)

        actions = QHBoxLayout()
        actions.addWidget(self.back_button)
        actions.addWidget(self.close_button)
        actions.addStretch(1)
        actions.addWidget(self.export_button)
        actions.addWidget(self.always_on_top_button)
        content = QWidget(self)
        content.setMinimumWidth(840)
        layout = QVBoxLayout(content)
        layout.addLayout(actions)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.table, 1)
        left_layout.addWidget(self.pagination)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.detail_table)
        self.splitter.setSizes([540, 360])
        layout.addWidget(self.splitter, 1)
        self.scroll_area = install_scrollable_dialog_content(self, content, minimum_width=720, minimum_height=460, content_minimum_width=840)

        self.back_button.clicked.connect(self.return_to_parent)
        self.close_button.clicked.connect(self.close)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.export_button.clicked.connect(self.export_history)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        self.refresh_table()

    def retranslate(self) -> None:
        self.back_button.setText(self.i18n.t("history.back"))
        self.close_button.setText(self.i18n.t("dialog.close"))
        self.always_on_top_button.setText(self.i18n.t("window.always_on_top"))
        self.export_button.setText(self.i18n.t("ac.export_table"))
        self.table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in self.columns])
        self.detail_table.setHorizontalHeaderLabels([self.i18n.t("field.name"), self.i18n.t("field.value")])

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
                    "history_kind": self.history_kind,
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
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            color = OPTICAL_HISTORY_COLORS.get(str(row.get(self.color_field or "") or ""))
            for column_index, (_key, field) in enumerate(self.columns):
                item = QTableWidgetItem(history_display_value(row, field, self.color_field, self.i18n.language))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if color:
                    apply_item_contrast(item, color)
                self.table.setItem(row_index, column_index, item)
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(True)
        auto_resize_table_columns(self.table)
        if rows:
            self.table.selectRow(0)
        self.refresh_detail()

    def refresh_detail(self) -> None:
        row = self.current_record()
        rows = [(self.i18n.t(key), row.get(field)) for key, field in self.columns] if row else []
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

    def show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        menu = create_table_context_menu(self.table, index.row(), index.column(), self.i18n.language, include_history=False)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()

    def return_to_parent(self) -> None:
        self.close()
        if self.owner is not None:
            show_non_focus_window(None, self.owner, key="ap_history_owner", center=False, activate=False, raise_window=False)

    def export_history(self) -> None:
        if self.db_path is None:
            return
        path = select_export_path(self, self.i18n.t("ac.export_table"), f"{self.ap_name}_{self.history_type}_history.xlsx", EXCEL_FILTER)
        if not path:
            return
        headers = [self.i18n.t(key) for key, _field in self.columns]
        submit_export_task(
            self,
            table_xlsx_source_spec(
                path,
                columns=[{"key": field, "title": headers[index]} for index, (_key, field) in enumerate(self.columns)],
                source=repository_query_source(
                    db_path=self.db_path,
                    repository="ac_repository",
                    method="list_fit_ap_history",
                    filters={
                        "ap_uuid": self.ap_uuid,
                        "history_kind": self.history_kind,
                        "color_field": self.color_field or "",
                        "language": self.i18n.language,
                    },
                ),
                sheet_name="AP History",
                title=self.i18n.t("ac.export_table"),
                row_fill_field="__row_fill" if self.color_field else "",
            ),
            success_title=self.i18n.t("ac.export_table"),
        )
        remember_export_path(path)


def _history_display_value(row: dict[str, object | None], field: str, color_field: str | None = None, language: str = "zh") -> str:
    return history_display_value(row, field, color_field, language)
