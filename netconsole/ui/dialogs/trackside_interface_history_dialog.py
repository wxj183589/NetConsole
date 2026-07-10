from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.ui.export_path import EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, PaginationState, paginate_rows
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_column_state import TableColumnState
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.export.export_task_builders import repository_query_source, table_xlsx_source_spec
from netconsole.services.history_export_service import export_interface_history_xlsx as _export_interface_history_xlsx


INTERFACE_HISTORY_COLUMNS = (
    ("trackside_ap.collected_at", "collected_at"),
    ("trackside_ap.source_device", "source_device_name"),
    ("details.interface_name", "interface_name"),
    ("trackside_ap.rx_power", "rx_power"),
    ("trackside_ap.tx_power", "tx_power"),
    ("ap.temperature", "temperature"),
    ("details.voltage", "voltage"),
    ("details.bias_current", "bias_current"),
    ("trackside_ap.optical_status", "optical_status"),
)


class TracksideInterfaceHistoryDialog(QDialog):
    def __init__(
        self,
        i18n: I18n,
        rows: list[dict[str, object | None]] | None,
        title: str,
        settings,
        parent=None,
        *,
        db_path: str | Path | None = None,
        device_uuid: str = "",
        interface_name: str = "",
    ) -> None:
        super().__init__(
            None,
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint,
        )
        self.i18n = i18n
        self.rows = list(rows or [])
        self.visible_rows: list[dict[str, object | None]] = []
        self.db_path = Path(db_path) if db_path else None
        self.device_uuid = device_uuid
        self.interface_name = interface_name
        self.background_manager = BackgroundProcessManager(self) if self.db_path else None
        self.query_job_id: str | None = None
        if self.background_manager is not None:
            self.background_manager.finished.connect(self._background_finished)
            self.background_manager.failed.connect(self._background_failed)
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.settings = settings
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.setWindowTitle(title)
        self.resize(1100, 640)
        self.setMinimumSize(860, 520)

        self.close_button = QPushButton()
        self.export_button = QPushButton()
        self.pin_button = QPushButton()
        self.pin_button.setCheckable(True)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.table = QTableWidget()
        self.detail_table = QTableWidget()
        self.pagination = PaginationWidget(i18n)
        self.splitter = QSplitter(Qt.Horizontal)

        for table in (self.table, self.detail_table):
            configure_readonly_table(table)
            table.setWordWrap(False)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setColumnCount(len(INTERFACE_HISTORY_COLUMNS))
        self.detail_table.setColumnCount(2)
        set_table_column_fields(self.table, [field for _key, field in INTERFACE_HISTORY_COLUMNS])
        set_table_column_fields(self.detail_table, ["name", "value"])
        self.table.itemSelectionChanged.connect(self.refresh_detail)
        self.table.itemDoubleClicked.connect(lambda _item: self.refresh_detail())

        actions = QHBoxLayout()
        actions.addWidget(self.close_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.pin_button)
        actions.addStretch(1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.table, 1)
        left_layout.addWidget(self.pagination)
        left_layout.addWidget(self.status_label)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.detail_table)
        self.splitter.setSizes([770, 330])
        layout = QVBoxLayout(self)
        layout.addLayout(actions)
        layout.addWidget(self.splitter, 1)

        self.table_state = TableColumnState(settings, self.table, "rail_transit/trackside_interface_history/table_column_widths", default_widths())
        self.detail_state = TableColumnState(settings, self.detail_table, "rail_transit/trackside_interface_history/detail_column_widths", {"name": 180, "value": 360})
        self.export_button.clicked.connect(self.export_history)
        self.pin_button.toggled.connect(self.set_always_on_top)
        self.close_button.clicked.connect(self.close)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        self.table_state.restore()
        self.detail_state.restore()
        self._restore_window_state()
        self.refresh_table()

    def retranslate(self) -> None:
        self.close_button.setText(self.i18n.t("dialog.close"))
        self.export_button.setText(self.i18n.t("trackside_ap.export_history"))
        self.pin_button.setText(self.i18n.t("window.always_on_top"))
        self.table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in INTERFACE_HISTORY_COLUMNS])
        self.detail_table.setHorizontalHeaderLabels([self.i18n.t("trackside_ap.field_name"), self.i18n.t("trackside_ap.field_value")])
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
                task_type="trackside_interface_history_page",
                params={
                    "db_path": str(self.db_path),
                    "device_uuid": self.device_uuid,
                    "interface_name": self.interface_name,
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
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (_key, field) in enumerate(INTERFACE_HISTORY_COLUMNS):
                value = row.get(field)
                item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(str(value) if value not in (None, "") else "")
                self.table.setItem(row_index, column_index, item)
        if rows:
            self.table.selectRow(0)
            self.status_label.setText("")
        else:
            self.status_label.setText(self.i18n.t("trackside_ap.no_interface_history"))
        self.refresh_detail()

    def refresh_detail(self) -> None:
        row = self.current_record()
        detail_rows = [(self.i18n.t(key), row.get(field)) for key, field in INTERFACE_HISTORY_COLUMNS] if row else []
        self.detail_table.setRowCount(len(detail_rows))
        for row_index, (name, value) in enumerate(detail_rows):
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
        path = select_export_path(self, self.i18n.t("trackside_ap.export_history"), "interface_history.xlsx", EXCEL_FILTER)
        if not path:
            return
        headers = [self.i18n.t(key) for key, _field in INTERFACE_HISTORY_COLUMNS]
        submit_export_task(
            self,
            table_xlsx_source_spec(
                path,
                columns=[{"key": field, "title": headers[index]} for index, (_key, field) in enumerate(INTERFACE_HISTORY_COLUMNS)],
                source=repository_query_source(
                    db_path=self.db_path,
                    repository="device_fact_repository",
                    method="list_trackside_interface_history",
                    filters={"device_uuid": self.device_uuid, "interface_name": self.interface_name},
                ),
                sheet_name="Interface History",
                title=self.i18n.t("trackside_ap.export_history"),
            ),
            success_title=self.i18n.t("trackside_ap.export_history"),
        )
        remember_export_path(path)

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.show()
        if enabled:
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event) -> None:
        self._save_window_state()
        super().closeEvent(event)

    def _save_window_state(self) -> None:
        self.table_state.save_now()
        self.detail_state.save_now()
        self.settings.set_value("rail_transit/trackside_interface_history/window_geometry", bytes(self.saveGeometry()).hex())
        self.settings.set_value("rail_transit/trackside_interface_history/window_maximized", self.isMaximized())
        self.settings.set_value("rail_transit/trackside_interface_history/splitter_state", bytes(self.splitter.saveState()).hex())

    def _restore_window_state(self) -> None:
        geometry_hex = str(self.settings.get_value("rail_transit/trackside_interface_history/window_geometry", "") or "")
        if geometry_hex:
            try:
                geometry = QByteArray.fromHex(geometry_hex.encode("ascii"))
                if geometry and self._geometry_is_on_screen(geometry):
                    self.restoreGeometry(geometry)
            except ValueError:
                pass
        splitter_hex = str(self.settings.get_value("rail_transit/trackside_interface_history/splitter_state", "") or "")
        if splitter_hex:
            try:
                self.splitter.restoreState(QByteArray.fromHex(splitter_hex.encode("ascii")))
            except ValueError:
                pass
        if bool(self.settings.get_value("rail_transit/trackside_interface_history/window_maximized", False)):
            self.showMaximized()

    def _geometry_is_on_screen(self, geometry: QByteArray) -> bool:
        probe = QDialog()
        probe.restoreGeometry(geometry)
        frame = probe.frameGeometry()
        return any(screen.availableGeometry().intersects(frame) for screen in QApplication.screens())


def export_interface_history_xlsx(path: Path, rows: list[dict[str, object | None]], headers: list[str]) -> None:
    _export_interface_history_xlsx(path, rows, INTERFACE_HISTORY_COLUMNS, headers)


def default_widths() -> dict[str, int]:
    return {
        "collected_at": 170,
        "source_device_name": 160,
        "interface_name": 190,
        "rx_power": 120,
        "tx_power": 120,
        "temperature": 100,
        "voltage": 100,
        "bias_current": 110,
        "optical_status": 130,
    }
