from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.ui.render.table_render_engine import ACTION_BUTTON_HEIGHT, ROW_HEIGHT, apply_action_column, apply_table_style, set_table_column_fields
from netconsole.ui.table_utils import configure_readonly_table


CHECK_COLUMN = 0

COLUMNS = (
    ("select", ""),
    ("status", "field.status"),
    ("name", "field.name"),
    ("group", "groups.group"),
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
        self.group_names: dict[int, str] = {}
        self.selected_device_ids: set[int] = set()
        self._updating_checks = False
        set_table_column_fields(self, [field for field, _key in COLUMNS])
        configure_readonly_table(self)
        self.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.itemChanged.connect(self._item_changed)
        self.cellClicked.connect(self._cell_clicked)
        self.retranslate()

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([self.i18n.t(key) if key else "" for _, key in COLUMNS])
        self._set_header_check_state(Qt.Unchecked)
        apply_table_style(self)
        apply_action_column(self)
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
                "group": self.group_names.get(int(device.group_id), self.i18n.t("groups.ungrouped")) if device.group_id else self.i18n.t("groups.ungrouped"),
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
        apply_table_style(self)
        apply_action_column(self)
        self.selection_changed.emit()

    def set_group_names(self, group_names: dict[int, str]) -> None:
        self.group_names = dict(group_names)

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
        return ActionCellWidget(
            connect_text=self.i18n.t("devices.test_connection"),
            edit_text=self.i18n.t("devices.edit"),
            delete_text=self.i18n.t("devices.delete"),
            device_id=int(device.id) if device.id is not None else None,
            detail_requested=self.detail_requested.emit,
            edit_requested=self.edit_requested.emit,
            delete_requested=self.delete_requested.emit,
        )

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


class ActionCellWidget(QWidget):
    def __init__(
        self,
        connect_text: str,
        edit_text: str,
        delete_text: str,
        device_id: int | None,
        detail_requested,
        edit_requested,
        delete_requested,
    ) -> None:
        super().__init__()
        self.setMinimumHeight(ROW_HEIGHT)
        self.setMaximumHeight(ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)
        buttons = (
            (QPushButton(connect_text), detail_requested),
            (QPushButton(edit_text), edit_requested),
            (QPushButton(delete_text), delete_requested),
        )
        for button, callback in buttons:
            button.setObjectName("tableActionButton")
            button.setMinimumHeight(ACTION_BUTTON_HEIGHT)
            button.setMaximumHeight(ACTION_BUTTON_HEIGHT)
            button.setMinimumWidth(56)
            if device_id is not None:
                button.clicked.connect(lambda _=False, value=device_id, handler=callback: handler(value))
            layout.addWidget(button)
