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
        self.clear()
        item = QListWidgetItem(self.i18n.t("nav.devices"))
        item.setData(256, "devices")
        self.addItem(item)
        self.setCurrentRow(0)
