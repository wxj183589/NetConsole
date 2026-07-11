from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.ui.table_utils import make_text_selectable


class WirelessScanDetailDialog(QDialog):
    def __init__(self, i18n: I18n, row: dict[str, object], parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.row = row
        self.setWindowTitle(self.i18n.t("wireless_scan.detail_title"))
        self.resize(640, 520)
        self.setMinimumSize(560, 420)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        for key in (
            "matched_ap_name",
            "matched_ap_mac",
            "bssid",
            "matched_radio_id",
            "matched_station",
            "matched_location",
            "matched_direction",
            "rssi_dbm",
            "channel",
            "frequency_mhz",
            "ssid",
            "is_hidden",
            "match_rule",
            "last_seen",
        ):
            form.addRow(self.i18n.t(f"wireless_scan.{key}") if self.i18n.t(f"wireless_scan.{key}") != f"wireless_scan.{key}" else key, make_text_selectable(str(row.get(key) or "-")))
        close_button = QPushButton(self.i18n.t("app.cancel"))
        close_button.clicked.connect(self.close)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(close_button)
