from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from netconsole.core.i18n import I18n
from netconsole.models.device import Device


COLUMNS = (
    ("index", "field.index"),
    ("name", "field.name"),
    ("sysname", "field.sysname"),
    ("station", "field.station"),
    ("device_vendor", "field.device_vendor"),
    ("device_type", "field.device_type"),
    ("ip_address", "field.ip_address"),
    ("ssh_enabled", "field.ssh_enabled"),
    ("ssh_port", "field.ssh_port"),
    ("telnet_enabled", "field.telnet_enabled"),
    ("telnet_port", "field.telnet_port"),
    ("username", "field.username"),
    ("tags", "field.tags"),
    ("remark", "field.remark"),
    ("updated_at", "field.updated_at"),
)


class DeviceTable(QTableWidget):
    def __init__(self, i18n: I18n) -> None:
        super().__init__(0, len(COLUMNS))
        self.i18n = i18n
        self.devices: list[Device] = []
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.retranslate()

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([self.i18n.t(key) for _, key in COLUMNS])
        widths = [56, 140, 130, 140, 90, 90, 130, 70, 80, 80, 90, 110, 120, 160, 150]
        for index, width in enumerate(widths):
            self.setColumnWidth(index, width)

    def set_devices(self, devices: list[Device]) -> None:
        self.devices = devices
        self.setRowCount(len(devices))
        for row, device in enumerate(devices):
            for column, (field, _) in enumerate(COLUMNS):
                value = row + 1 if field == "index" else getattr(device, field)
                if field in {"ssh_enabled", "telnet_enabled"}:
                    value = "Y" if value else "N"
                item = QTableWidgetItem("" if value is None else str(value))
                item.setData(Qt.UserRole, device.id)
                self.setItem(row, column, item)

    def selected_device_id(self) -> int | None:
        row = self.currentRow()
        if row < 0:
            return None
        item = self.item(row, 0)
        return int(item.data(Qt.UserRole)) if item and item.data(Qt.UserRole) is not None else None
