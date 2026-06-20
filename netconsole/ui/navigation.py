from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QListWidgetItem

from netconsole.core.i18n import I18n


class Navigation(QListWidget):
    def __init__(self, i18n: I18n) -> None:
        super().__init__()
        self.i18n = i18n
        self.setFixedWidth(180)
        self.setObjectName("navigation")
        self.retranslate()

    def retranslate(self) -> None:
        current_page = self.current_page()
        self.clear()
        for key, page_id in (
            ("nav.devices", "devices"),
            ("nav.config_collection", "config_collection"),
            ("nav.file_management", "file_management"),
            ("nav.rail_transit", "rail_transit"),
            ("nav.ac", "ac"),
            ("nav.logs", "logs"),
        ):
            item = QListWidgetItem(self.i18n.t(key))
            item.setData(256, page_id)
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
