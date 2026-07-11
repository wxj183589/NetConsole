from __future__ import annotations

import json

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.table_utils import configure_readonly_table, format_row_for_copy
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate, invert_table_rows_checked, is_checked_value, set_all_table_rows_checked


CHECK_COLUMN = 0
DEVICE_TABLE_DIRECT_FILL_LIMIT = 200
DEVICE_TABLE_BATCH_SIZE = 100
DEVICE_TABLE_FILTER_HINT_LIMIT = 1000
DEVICE_COLUMN_WIDTHS = {
    "select": 48,
    "name": 180,
    "group": 100,
    "station": 160,
    "system_name": 160,
    "primary_address": 130,
    "backup_address": 130,
    "protocols": 80,
    "updated_at": 170,
}

COLUMNS = (
    ("select", ""),
    ("name", "field.name"),
    ("group", "groups.group"),
    ("system_name", "field.system_name"),
    ("station", "field.station"),
    ("primary_address", "field.primary_address"),
    ("backup_address", "field.backup_address"),
    ("protocols", "field.protocols"),
    ("updated_at", "field.updated_at"),
)

DEVICE_HEADER_TOOLTIPS = {
    "system_name": "field.tooltip.system_name",
    "station": "field.tooltip.station",
    "primary_address": "field.tooltip.primary_address",
    "backup_address": "field.tooltip.backup_address",
}


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
    duplicate_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    external_terminal_requested = Signal(int)

    def __init__(self, i18n: I18n) -> None:
        super().__init__(0, len(COLUMNS))
        self.i18n = i18n
        self.devices: list[Device] = []
        self.group_names: dict[int, str] = {}
        self.selected_device_ids: set[int] = set()
        self.external_terminal_visible = True
        self.external_terminal_enabled = True
        self._updating_checks = False
        self._populate_generation = 0
        set_table_column_fields(self, [field for field, _key in COLUMNS])
        configure_readonly_table(self)
        install_checkbox_only_delegate(self, CHECK_COLUMN)
        self.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.itemChanged.connect(self._item_changed)
        self.cellClicked.connect(self._cell_clicked)
        self.cellDoubleClicked.connect(self._cell_double_clicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.retranslate()

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([self.i18n.t(key) if key else "" for _, key in COLUMNS])
        self._apply_header_tooltips()
        self._set_header_check_state(Qt.Unchecked)
        apply_table_style(self)
        self._apply_column_layout()

    def _apply_header_tooltips(self) -> None:
        for column, (field, key) in enumerate(COLUMNS):
            item = self.horizontalHeaderItem(column)
            if item is None:
                continue
            tooltip_key = DEVICE_HEADER_TOOLTIPS.get(field)
            item.setToolTip(self.i18n.t(tooltip_key) if tooltip_key else (self.i18n.t(key) if key else ""))

    def set_devices(self, devices: list[Device]) -> None:
        self._populate_generation += 1
        generation = self._populate_generation
        self.devices = devices
        self.selected_device_ids.clear()
        self.clearContents()
        self.setRowCount(0)
        total = len(devices)
        if total <= 0:
            self._finish_populate(total)
            return
        if total <= DEVICE_TABLE_DIRECT_FILL_LIMIT:
            self._append_device_rows(0, total)
            self._finish_populate(total)
            return

        self.setToolTip(f"正在分批显示 {total} 台设备" + ("；设备较多时建议使用分组或筛选缩小范围。" if total > DEVICE_TABLE_FILTER_HINT_LIMIT else "。"))

        def fill_next(start: int = 0) -> None:
            try:
                if generation != self._populate_generation:
                    return
                end = min(start + DEVICE_TABLE_BATCH_SIZE, total)
                self._append_device_rows(start, end)
                if end < total:
                    QTimer.singleShot(0, lambda: fill_next(end))
                    return
                self._finish_populate(total)
            except RuntimeError:
                return

        QTimer.singleShot(0, fill_next)

    def _append_device_rows(self, start: int, end: int) -> None:
        self._updating_checks = True
        self.setUpdatesEnabled(False)
        try:
            self.setRowCount(end)
            for row in range(start, end):
                self._populate_device_row(row, self.devices[row])
        finally:
            self.setUpdatesEnabled(True)
            self._updating_checks = False

    def _populate_device_row(self, row: int, device: Device) -> None:
        self._set_checkbox_item(row, device)
        values = {
            "name": device.name,
            "group": self.group_names.get(int(device.group_id), self.i18n.t("groups.ungrouped")) if device.group_id else self.i18n.t("groups.ungrouped"),
            "system_name": device.system_name,
            "station": device.station,
            "primary_address": device.primary_address,
            "backup_address": device.backup_address,
            "protocols": protocol_label(device.ssh_enabled, device.telnet_enabled),
            "updated_at": device.updated_at,
        }
        for column, (field, _) in enumerate(COLUMNS):
            if field == "select":
                continue
            item = QTableWidgetItem("" if values.get(field) is None else str(values[field]))
            item.setData(Qt.UserRole, device.id)
            self.setItem(row, column, item)

    def _finish_populate(self, total: int) -> None:
        if total > DEVICE_TABLE_FILTER_HINT_LIMIT:
            self.setToolTip(f"当前显示 {total} 台设备，建议使用分组或筛选缩小范围。")
        else:
            self.setToolTip("")
        self._set_header_check_state(Qt.Unchecked)
        apply_table_style(self)
        self._apply_column_layout()
        self.selection_changed.emit()

    def set_group_names(self, group_names: dict[int, str]) -> None:
        self.group_names = dict(group_names)

    def set_external_terminal_action_state(self, *, visible: bool, enabled: bool) -> None:
        self.external_terminal_visible = visible
        self.external_terminal_enabled = enabled

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
        invert_table_rows_checked(self, CHECK_COLUMN)
        for row in range(self.rowCount()):
            item = self.item(row, CHECK_COLUMN)
            if item is None:
                continue
            device_id = item.data(Qt.UserRole)
            if is_checked_value(item.checkState()) and device_id is not None:
                self.selected_device_ids.add(int(device_id))
        self._updating_checks = False
        self._sync_header_check_state()
        self.selection_changed.emit()

    def _set_checkbox_item(self, row: int, device: Device) -> None:
        item = create_checkable_table_item(False, user_data=device.id)
        self.setItem(row, CHECK_COLUMN, item)

    def context_menu_for_device(self, device_id: int, row: int, column: int) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.i18n.t("details.button"), lambda: self.detail_requested.emit(device_id))
        menu.addAction(self.i18n.t("devices.duplicate"), lambda: self.duplicate_requested.emit(device_id))
        if self.external_terminal_visible:
            terminal_action = menu.addAction(
                self.i18n.t("devices.external_terminal"),
                lambda: self.external_terminal_requested.emit(device_id),
            )
            terminal_action.setEnabled(self.external_terminal_enabled)
        menu.addAction(self.i18n.t("devices.edit"), lambda: self.edit_requested.emit(device_id))
        menu.addAction(self.i18n.t("devices.delete"), lambda: self.delete_requested.emit(device_id))
        menu.addSeparator()
        copy_menu = QMenu(self.i18n.t("devices.copy_text"), menu)
        menu.addMenu(copy_menu)
        menu._copy_text_menu = copy_menu
        copy_menu.addAction(self.i18n.t("devices.copy_current_cell"), lambda: self._copy_current_cell(row, column))
        device = self.devices[row]
        copy_menu.addAction(self.i18n.t("devices.copy_name"), lambda: self._copy_text(device.name))
        copy_menu.addAction(self.i18n.t("devices.copy_primary_address"), lambda: self._copy_text(device.primary_address))
        copy_menu.addAction(self.i18n.t("devices.copy_backup_address"), lambda: self._copy_text(device.backup_address))
        copy_menu.addAction(self.i18n.t("devices.copy_system_name"), lambda: self._copy_text(device.system_name))
        copy_menu.addAction(self.i18n.t("devices.copy_station"), lambda: self._copy_text(device.station))
        copy_menu.addAction(self.i18n.t("devices.copy_row"), lambda: self._copy_row(row))
        copy_menu.addAction(self.i18n.t("devices.copy_device_info"), lambda: self._copy_device_info(device))
        return menu

    def _show_context_menu(self, position: QPoint) -> None:
        index = self.indexAt(position)
        row = index.row()
        if not 0 <= row < len(self.devices):
            return
        device = self.devices[row]
        if device.id is None:
            return
        self.setCurrentCell(row, index.column())
        menu = self.context_menu_for_device(int(device.id), row, index.column())
        menu.exec(self.viewport().mapToGlobal(position))
        menu.deleteLater()

    @staticmethod
    def _copy_text(value: object | None) -> None:
        QApplication.clipboard().setText("" if value is None else str(value))

    def _copy_current_cell(self, row: int, column: int) -> None:
        item = self.item(row, column)
        self._copy_text(item.text() if item is not None else "")

    def _copy_row(self, row: int) -> None:
        visible_columns = [column for column, (field, _key) in enumerate(COLUMNS) if field != "select"]
        headers = [self.horizontalHeaderItem(column).text() if self.horizontalHeaderItem(column) else "" for column in visible_columns]
        values = [self.item(row, column).text() if self.item(row, column) else "" for column in visible_columns]
        self._copy_text(format_row_for_copy(headers, values))

    def _copy_device_info(self, device: Device) -> None:
        self._copy_text(json.dumps(device.to_record(), ensure_ascii=False, indent=2, default=str))

    def _header_clicked(self, section: int) -> None:
        if section != CHECK_COLUMN:
            return
        header = self.horizontalHeaderItem(CHECK_COLUMN)
        checked = header is None or not is_checked_value(header.checkState())
        self._set_all_checked(checked)

    def _set_all_checked(self, checked: bool) -> None:
        self._updating_checks = True
        self.selected_device_ids.clear()
        set_all_table_rows_checked(self, checked, CHECK_COLUMN)
        for row in range(self.rowCount()):
            item = self.item(row, CHECK_COLUMN)
            if item:
                device_id = item.data(Qt.UserRole)
                if checked and device_id is not None:
                    self.selected_device_ids.add(int(device_id))
        self._updating_checks = False
        self._set_header_check_state(Qt.Checked if checked else Qt.Unchecked)
        self.selection_changed.emit()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_checks or item.column() != CHECK_COLUMN:
            return
        device_id = item.data(Qt.UserRole)
        if device_id is not None:
            if is_checked_value(item.checkState()):
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

    def _cell_double_clicked(self, row: int, column: int) -> None:
        if column == CHECK_COLUMN:
            return
        if 0 <= row < len(self.devices):
            device = self.devices[row]
            if device.id is not None:
                self.detail_requested.emit(int(device.id))

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

    def _apply_column_layout(self) -> None:
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setProperty("netconsole_manual_column_widths", True)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column, (field, _) in enumerate(COLUMNS):
            width = DEVICE_COLUMN_WIDTHS.get(field)
            if width is not None:
                self.setColumnWidth(column, width)
            if field == "select":
                header.setSectionResizeMode(column, QHeaderView.Fixed)
                item = self.horizontalHeaderItem(column)
                if item is not None:
                    item.setTextAlignment(Qt.AlignCenter)
            else:
                header.setSectionResizeMode(column, QHeaderView.Interactive)

    @staticmethod
    def _column_index(field: str) -> int:
        for index, (column_field, _) in enumerate(COLUMNS):
            if column_field == field:
                return index
        raise KeyError(field)
