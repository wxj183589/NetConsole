from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.i18n import I18n


class Navigation(QListWidget):
    EXPANDED_WIDTH = 180
    COLLAPSED_WIDTH = 64
    ITEMS = (
        ("module.devices", "nav.devices", "devices", "Dev"),
        ("module.ac", "nav.ac", "ac", "AC"),
        ("module.rail_transit", "nav.rail_transit", "rail_transit", "Rail"),
        ("module.wifi_survey", "nav.wifi_survey", "wifi_survey", "WiFi"),
        ("module.config_collection", "nav.config_collection", "config_collection", "Cfg"),
        ("module.file_management", "nav.file_management", "file_management", "File"),
        ("module.network_tools", "nav.network_tools", "network_tools", "Net"),
        ("module.logs", "nav.logs", "logs", "Log"),
        ("system.feature_flags", "system.feature_flags", "feature_flags", "Flag"),
    )

    def __init__(self, i18n: I18n, feature_gate: FeatureGate | None = None) -> None:
        super().__init__()
        self.i18n = i18n
        self.feature_gate = feature_gate or default_feature_gate()
        self.collapsed = False
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self.setObjectName("navigation")
        self.retranslate()

    def retranslate(self) -> None:
        self._populate_items()

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        self.setFixedWidth(self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH)
        blocked = self.blockSignals(True)
        try:
            self._populate_items()
        finally:
            self.blockSignals(blocked)

    def _populate_items(self) -> None:
        current_page = self.current_page()
        self.clear()
        for feature_id, key, page_id, collapsed_text in self.ITEMS:
            if not self.feature_gate.is_visible(feature_id) or not self.feature_gate.is_enabled(feature_id):
                continue
            label = self.i18n.t(key)
            item = QListWidgetItem(collapsed_text if self.collapsed else label)
            item.setData(256, page_id)
            item.setData(257, label)
            item.setData(258, feature_id)
            item.setToolTip(label)
            item.setTextAlignment(Qt.AlignCenter)
            self.addItem(item)
        index = self.find_page(current_page)
        self.setCurrentRow(index if index >= 0 else 0)

    def current_page(self) -> str:
        item = self.currentItem()
        return str(item.data(256)) if item is not None else "devices"

    def find_page(self, page_id: str) -> int:
        for index in range(self.count()):
            if self.item(index).data(256) == page_id:
                return index
        return -1
