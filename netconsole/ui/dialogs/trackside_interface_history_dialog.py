from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.services.rail_transit.trackside_optical_history import TracksideOpticalHistoryService
from netconsole.ui.export_path import EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_column_state import TableColumnState
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.pagination_widget import PaginationWidget


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
    ("trackside_ap.raw_log", "raw_log_path"),
)


class TracksideInterfaceHistoryDialog(QWidget):
    def __init__(self, i18n: I18n, rows: list[dict[str, object | None]], title: str, settings, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.rows = rows
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.settings = settings
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.resize(1100, 640)
        self.setMinimumSize(860, 520)

        self.export_button = QPushButton()
        self.open_raw_button = QPushButton()
        self.close_button = QPushButton()
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
        actions.addWidget(self.export_button)
        actions.addWidget(self.open_raw_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.table, 1)
        left_layout.addWidget(self.pagination)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.detail_table)
        self.splitter.setSizes([660, 440])
        layout = QVBoxLayout(self)
        layout.addLayout(actions)
        layout.addWidget(self.splitter, 1)

        self.table_state = TableColumnState(settings, self.table, "rail_transit/trackside_ap/interface_history_column_widths", default_widths())
        self.detail_state = TableColumnState(settings, self.detail_table, "rail_transit/trackside_ap/interface_history_detail_widths", {"name": 180, "value": 360})
        self.export_button.clicked.connect(self.export_history)
        self.open_raw_button.clicked.connect(self.open_raw_log_folder)
        self.close_button.clicked.connect(self.close)
        self.pagination.pageChanged.connect(self.set_page)
        self.pagination.pageSizeChanged.connect(self.set_page_size)
        self.retranslate()
        self.table_state.restore()
        self.detail_state.restore()
        self.refresh_table()

    def retranslate(self) -> None:
        self.export_button.setText(self.i18n.t("trackside_ap.export_history"))
        self.open_raw_button.setText(self.i18n.t("trackside_ap.open_raw_log_folder"))
        self.close_button.setText(self.i18n.t("dialog.close"))
        self.table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in INTERFACE_HISTORY_COLUMNS])
        self.detail_table.setHorizontalHeaderLabels([self.i18n.t("field.name"), self.i18n.t("field.value")])
        self.pagination.retranslate()

    def refresh_table(self) -> None:
        rows, state = paginate_rows(self.rows, self.page_size, self.page)
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
        rows, _state = paginate_rows(self.rows, self.page_size, self.page)
        return rows[current] if 0 <= current < len(rows) else None

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh_table()

    def set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.page = 1
        self.refresh_table()

    def open_raw_log_folder(self) -> None:
        record = self.current_record()
        directory = TracksideOpticalHistoryService.raw_log_dir(record or {})
        if directory is not None and directory.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def export_history(self) -> None:
        path = select_export_path(self, self.i18n.t("trackside_ap.export_history"), "interface_history.xlsx", EXCEL_FILTER)
        if not path:
            return
        export_interface_history_xlsx(path, self.rows, [self.i18n.t(key) for key, _field in INTERFACE_HISTORY_COLUMNS])
        remember_export_path(path)


def export_interface_history_xlsx(path: Path, rows: list[dict[str, object | None]], headers: list[str]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Interface History"
    sheet.append(headers)
    for row in rows:
        sheet.append([str(row.get(field) or "") for _key, field in INTERFACE_HISTORY_COLUMNS])
    workbook.save(path)


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
        "raw_log_path": 260,
    }
