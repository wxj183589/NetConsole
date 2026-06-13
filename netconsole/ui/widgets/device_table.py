from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import Device


CHECK_COLUMN = 0

COLUMNS = (
    ("select", ""),
    ("status", "field.status"),
    ("name", "field.name"),
    ("station", "field.station"),
    ("ip_address", "field.ip_address"),
    ("protocols", "field.protocols"),
    ("updated_at", "field.updated_at"),
    ("actions", "field.actions"),
)


def protocol_label(ssh_enabled: object, telnet_enabled: object) -> str:
    ssh = bool(ssh_enabled)
    telnet = bool(telnet_enabled)
    if ssh and telnet:
        return "SSH/Telnet"
    if ssh:
        return "SSH"
    if telnet:
        return "Telnet"
    return "-"


class DeviceTable(QTableWidget):
    selection_changed = Signal()
    detail_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, i18n: I18n) -> None:
        super().__init__(0, len(COLUMNS))
        self.i18n = i18n
        self.devices: list[Device] = []
        self.selected_device_ids: set[int] = set()
        self._updating_checks = False
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.itemChanged.connect(self._item_changed)
        self.cellClicked.connect(self._cell_clicked)
        self.retranslate()

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([self.i18n.t(key) if key else "" for _, key in COLUMNS])
        self._set_header_check_state(Qt.Unchecked)
        widths = [44, 70, 190, 150, 150, 110, 160, 250]
        for index, width in enumerate(widths):
            self.setColumnWidth(index, width)
        self._refresh_action_buttons()

    def set_devices(self, devices: list[Device]) -> None:
        self._updating_checks = True
        self.devices = devices
        self.selected_device_ids.clear()
        self.setRowCount(len(devices))
        for row, device in enumerate(devices):
            self._set_checkbox_item(row, device)
            values = {
                "status": "-",
                "name": device.name,
                "station": device.station,
                "ip_address": device.ip_address,
                "protocols": protocol_label(device.ssh_enabled, device.telnet_enabled),
                "updated_at": device.updated_at,
            }
            for column, (field, _) in enumerate(COLUMNS):
                if field in {"select", "actions"}:
                    continue
                item = QTableWidgetItem("" if values.get(field) is None else str(values[field]))
                item.setData(Qt.UserRole, device.id)
                self.setItem(row, column, item)
            self.setCellWidget(row, self._column_index("actions"), self._action_widget(device))
        self._updating_checks = False
        self._set_header_check_state(Qt.Unchecked)
        self.selection_changed.emit()

    def selected_device_id(self) -> int | None:
        row = self.currentRow()
        if row < 0:
            return None
        device = self.devices[row] if row < len(self.devices) else None
        return int(device.id) if device and device.id is not None else None

    def checked_device_ids(self) -> list[int]:
        return [int(device.id) for device in self.devices if device.id in self.selected_device_ids]

    def checked_devices(self) -> list[Device]:
        selected_ids = set(self.checked_device_ids())
        return [device for device in self.devices if device.id in selected_ids]

    def clear_checked(self) -> None:
        self._set_all_checked(False)

    def invert_checked(self) -> None:
        self._updating_checks = True
        self.selected_device_ids.clear()
        for row in range(self.rowCount()):
            item = self.item(row, CHECK_COLUMN)
            if item is None:
                continue
            checked = item.checkState() != Qt.Checked
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            device_id = item.data(Qt.UserRole)
            if checked and device_id is not None:
                self.selected_device_ids.add(int(device_id))
        self._updating_checks = False
        self._sync_header_check_state()
        self.selection_changed.emit()

    def _set_checkbox_item(self, row: int, device: Device) -> None:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        item.setCheckState(Qt.Unchecked)
        item.setData(Qt.UserRole, device.id)
        self.setItem(row, CHECK_COLUMN, item)

    def _action_widget(self, device: Device) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        detail_button = QPushButton(self.i18n.t("details.button"))
        edit_button = QPushButton(self.i18n.t("devices.edit"))
        delete_button = QPushButton(self.i18n.t("devices.delete"))
        if device.id is not None:
            device_id = int(device.id)
            detail_button.clicked.connect(lambda _=False, value=device_id: self.detail_requested.emit(value))
            edit_button.clicked.connect(lambda _=False, value=device_id: self.edit_requested.emit(value))
            delete_button.clicked.connect(lambda _=False, value=device_id: self.delete_requested.emit(value))
        for button in (detail_button, edit_button, delete_button):
            layout.addWidget(button)
        return widget

    def _refresh_action_buttons(self) -> None:
        for row, device in enumerate(self.devices):
            self.setCellWidget(row, self._column_index("actions"), self._action_widget(device))

    def _header_clicked(self, section: int) -> None:
        if section != CHECK_COLUMN:
            return
        header = self.horizontalHeaderItem(CHECK_COLUMN)
        checked = header is not None and header.checkState() != Qt.Checked
        self._set_all_checked(checked)

    def _set_all_checked(self, checked: bool) -> None:
        self._updating_checks = True
        state = Qt.Checked if checked else Qt.Unchecked
        self.selected_device_ids.clear()
        for row in range(self.rowCount()):
            item = self.item(row, CHECK_COLUMN)
            if item:
                item.setCheckState(state)
                device_id = item.data(Qt.UserRole)
                if checked and device_id is not None:
                    self.selected_device_ids.add(int(device_id))
        self._updating_checks = False
        self._set_header_check_state(state)
        self.selection_changed.emit()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_checks or item.column() != CHECK_COLUMN:
            return
        device_id = item.data(Qt.UserRole)
        if device_id is not None:
            if item.checkState() == Qt.Checked:
                self.selected_device_ids.add(int(device_id))
            else:
                self.selected_device_ids.discard(int(device_id))
        self._sync_header_check_state()
        self.selection_changed.emit()

    def _cell_clicked(self, row: int, column: int) -> None:
        if column != CHECK_COLUMN:
            return
        item = self.item(row, CHECK_COLUMN)
        if item is None:
            return
        self.setCurrentCell(row, column)

    def _sync_header_check_state(self) -> None:
        checked_count = len(self.selected_device_ids)
        if checked_count == 0:
            self._set_header_check_state(Qt.Unchecked)
        elif checked_count == self.rowCount():
            self._set_header_check_state(Qt.Checked)
        else:
            self._set_header_check_state(Qt.PartiallyChecked)

    def _set_header_check_state(self, state: Qt.CheckState) -> None:
        item = self.horizontalHeaderItem(CHECK_COLUMN) or QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        item.setCheckState(state)
        self.setHorizontalHeaderItem(CHECK_COLUMN, item)

    @staticmethod
    def _column_index(field: str) -> int:
        for index, (column_field, _) in enumerate(COLUMNS):
            if column_field == field:
                return index
        raise KeyError(field)
