import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QTableWidget

from netconsole.core.i18n import I18n
from netconsole.ui.dialogs.history_data_dialog import (
    HistoryDataDialog,
    INTERFACE_HISTORY_COLUMNS,
    LLDP_HISTORY_COLUMNS,
    OPTICAL_HISTORY_COLUMNS,
)


def app():
    return QApplication.instance() or QApplication([])


def test_history_dialog_interface_columns_are_complete():
    assert [field for _key, field in INTERFACE_HISTORY_COLUMNS] == [
        "collected_at",
        "interface_name",
        "link_status",
        "protocol_status",
        "speed",
        "duplex",
        "interface_type",
        "port_status",
        "pvid",
        "description",
        "ip_address",
        "mac_address",
        "vlan",
    ]


def test_history_dialog_optical_and_lldp_columns_are_complete():
    assert [field for _key, field in OPTICAL_HISTORY_COLUMNS] == [
        "collected_at",
        "interface_name",
        "rx_power",
        "tx_power",
        "temperature",
        "voltage",
        "bias_current",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "status",
    ]
    assert [field for _key, field in LLDP_HISTORY_COLUMNS] == [
        "collected_at",
        "local_interface",
        "neighbor_sysname",
        "neighbor_mac",
        "neighbor_interface",
    ]


def test_history_dialog_shows_empty_hint_when_no_rows():
    app()
    dialog = HistoryDataDialog(I18n("en_US"), "SW01", "GE1/0/1", INTERFACE_HISTORY_COLUMNS, [])

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert dialog.windowTitle() == "History Data - SW01 - GE1/0/1"
    assert "No history data" in labels


def test_history_dialog_renders_table_rows():
    app()
    dialog = HistoryDataDialog(
        I18n("en_US"),
        "SW01",
        "GE1/0/1",
        INTERFACE_HISTORY_COLUMNS,
        [{"collected_at": "2026-06-13T11:00:00", "interface_name": "GE1/0/1"}],
    )

    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.rowCount() == 1
    assert table.horizontalHeaderItem(0).text() == "Collected At"
