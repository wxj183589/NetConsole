from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table


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
    ("history.raw_log_path", "raw_log_path"),
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
    ("history.raw_log_path", "raw_log_path"),
)

LLDP_HISTORY_COLUMNS = (
    ("history.collected_at", "collected_at"),
    ("details.local_interface", "local_interface"),
    ("details.neighbor_sysname", "neighbor_sysname"),
    ("details.neighbor_mac", "neighbor_mac"),
    ("details.neighbor_interface", "neighbor_interface"),
    ("details.neighbor_ip", "neighbor_ip"),
    ("history.raw_log_path", "raw_log_path"),
)


class HistoryDataDialog(QDialog):
    def __init__(self, i18n: I18n, device_name: str, object_name: str, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]], parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.device_name = device_name
        self.object_name = object_name
        self.columns = columns
        self.rows = rows
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
            layout.addWidget(self._table())
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
        table = QTableWidget(len(self.rows), len(self.columns))
        configure_readonly_table(table)
        attach_table_context_menu(table, self.i18n.language, include_history=False)
        table.setHorizontalHeaderLabels([self.i18n.t(label_key) for label_key, _field in self.columns])
        for row_index, row in enumerate(self.rows):
            for column_index, (_label_key, field) in enumerate(self.columns):
                item = QTableWidgetItem(str(row.get(field) or ""))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column_index, item)
        auto_resize_table_columns(table, column_min_widths=_history_column_min_widths(self.columns))
        return table

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()
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
        "raw_log_path": 220,
    }
    return {index: widths[field] for index, (_label_key, field) in enumerate(columns) if field in widths}
