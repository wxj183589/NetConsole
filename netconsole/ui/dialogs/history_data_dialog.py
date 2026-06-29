from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.core.optical_severity_engine import display_optical_status


INTERFACE_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("details.interface_name", "interface_name"),
    ("details.link", "link_status"),
    ("details.protocol", "protocol_status"),
    ("details.speed", "speed"),
    ("details.duplex", "duplex"),
    ("details.interface_type", "interface_type"),
    ("details.port_status", "port_status"),
    ("details.pvid", "pvid"),
    ("details.port_description", "description"),
    ("details.interface_ip", "ip_address"),
    ("details.mac_address", "mac_address"),
    ("details.vlan", "vlan"),
)

OPTICAL_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("details.interface_name", "interface_name"),
    ("details.rx_power", "rx_power"),
    ("details.tx_power", "tx_power"),
    ("details.temperature", "temperature"),
    ("details.voltage", "voltage"),
    ("details.bias_current", "bias_current"),
    ("details.module_model", "module_model"),
    ("details.module_serial_number", "module_serial_number"),
    ("details.vendor", "module_vendor"),
    ("details.wavelength", "wavelength"),
    ("details.transmission_distance", "transmission_distance"),
    ("field.status", "status"),
)

LLDP_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("details.local_interface", "local_interface"),
    ("details.neighbor_sysname", "neighbor_sysname"),
    ("details.neighbor_mac", "neighbor_mac"),
    ("details.neighbor_interface", "neighbor_interface"),
)


class HistoryDataDialog(QDialog):
    def __init__(self, i18n: I18n, device_name: str, object_name: str, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]], parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.device_name = device_name
        self.object_name = object_name
        self.columns = columns
        self.rows = rows
        self.page = 1
        self.page_size = DEFAULT_PAGE_SIZE
        self.setModal(False)
        self.setMinimumSize(900, 560)
        self.resize(900, 560)

        self.title_label = QLabel()
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.always_on_top_button)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        if rows:
            self.table = self._table()
            self.pagination = PaginationWidget(self.i18n)
            self.pagination.pageChanged.connect(self.set_page)
            self.pagination.pageSizeChanged.connect(self.set_page_size)
            layout.addWidget(self.table, 1)
            layout.addWidget(self.pagination)
            self.refresh_table()
        else:
            label = QLabel(self.i18n.t("history.no_data"))
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, 1)
        self.retranslate()

    def retranslate(self) -> None:
        title = self.i18n.t("history.title_with_object", device=self.device_name, object=self.object_name)
        self.setWindowTitle(title)
        self.title_label.setText(title)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))

    def _table(self) -> QTableWidget:
        table = QTableWidget(0, len(self.columns))
        set_table_column_fields(table, [field for _label_key, field in self.columns])
        configure_readonly_table(table)
        attach_table_context_menu(table, self.i18n.language, include_history=False)
        table.setHorizontalHeaderLabels([self.i18n.t(label_key) for label_key, _field in self.columns])
        return table

    def refresh_table(self) -> None:
        rows, state = paginate_rows(self.rows, self.page_size, self.page)
        self.page = state.current_page
        self.pagination.set_state(state)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (_label_key, field) in enumerate(self.columns):
                value = display_optical_status(row.get(field), self.i18n.language) if field == "status" else str(row.get(field) or "")
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column_index, item)
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(True)
        auto_resize_table_columns(self.table)

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh_table()

    def set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.page = 1
        self.refresh_table()

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()
        if enabled:
            self.raise_()
            self.activateWindow()


def _history_column_min_widths(columns: tuple[tuple[str, str], ...]) -> dict[int, int]:
    widths = {
        "interface_name": 180,
        "local_interface": 180,
        "neighbor_interface": 180,
        "neighbor_sysname": 160,
        "neighbor_mac": 150,
        "module_model": 180,
        "module_serial_number": 180,
        "description": 180,
    }
    return {index: widths[field] for index, (_label_key, field) in enumerate(columns) if field in widths}
