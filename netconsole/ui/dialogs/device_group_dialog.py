from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.ui.dialogs.input_dialog_service import InputDialog
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from netconsole.core.i18n import I18n
from netconsole.repositories.device_group_repository import DeviceGroupRepository, DuplicateGroupName
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.table_utils import configure_readonly_table


GROUP_COLUMNS = ("name", "count")


class DeviceGroupDialog(QDialog):
    groups_changed = Signal()

    def __init__(self, i18n: I18n, repository: DeviceGroupRepository, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.repository = repository
        self.groups = []
        self.table = QTableWidget(0, len(GROUP_COLUMNS))
        set_table_column_fields(self.table, list(GROUP_COLUMNS))
        configure_readonly_table(self.table)
        self.add_button = QPushButton()
        self.rename_button = QPushButton()
        self.delete_button = QPushButton()
        self.close_button = QPushButton()

        actions = QHBoxLayout()
        for button in (self.add_button, self.rename_button, self.delete_button, self.close_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(actions)

        self.add_button.clicked.connect(self.add_group)
        self.rename_button.clicked.connect(self.rename_group)
        self.delete_button.clicked.connect(self.delete_group)
        self.close_button.clicked.connect(self.accept)
        self.resize(520, 360)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        self.setWindowTitle(self.i18n.t("groups.manage_groups"))
        self.add_button.setText(self.i18n.t("groups.add_group"))
        self.rename_button.setText(self.i18n.t("groups.rename_group"))
        self.delete_button.setText(self.i18n.t("groups.delete_group"))
        self.close_button.setText(self.i18n.t("dialog.cancel"))
        self.table.setHorizontalHeaderLabels([self.i18n.t("groups.group_name"), self.i18n.t("groups.device_count")])

    def refresh(self) -> None:
        self.groups = self.repository.list()
        counts = self.repository.counts()
        self.table.setRowCount(len(self.groups))
        for row, group in enumerate(self.groups):
            name = QTableWidgetItem(group.name)
            name.setData(256, group.id)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(str(counts.get(int(group.id or 0), 0))))
        apply_table_style(self.table)

    def selected_group_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.groups):
            return None
        return int(self.groups[row].id)

    def add_group(self) -> None:
        name, accepted = InputDialog.getText(self, self.windowTitle(), self.i18n.t("groups.group_name"))
        if accepted:
            self._save(lambda: self.repository.create(name))

    def rename_group(self) -> None:
        group_id = self.selected_group_id()
        if group_id is None:
            return
        current = self.groups[self.table.currentRow()].name
        name, accepted = InputDialog.getText(self, self.i18n.t("groups.rename_group"), self.i18n.t("groups.group_name"), text=current)
        if accepted:
            self._save(lambda: self.repository.rename(group_id, name))

    def delete_group(self) -> None:
        group_id = self.selected_group_id()
        if group_id is None:
            return
        count = self.repository.count_devices(group_id)
        message = self.i18n.t("groups.delete_group_confirm_with_devices", count=count) if count else self.i18n.t("groups.delete_group_confirm")
        if MessageBox.question(self, self.i18n.t("groups.delete_group"), message) == MessageBox.Yes:
            self.repository.delete(group_id)
            self.refresh()
            self.groups_changed.emit()

    def _save(self, action) -> None:
        try:
            action()
        except DuplicateGroupName:
            MessageBox.warning(self, self.windowTitle(), self.i18n.t("groups.duplicate_group_name"))
            return
        except ValueError:
            MessageBox.warning(self, self.windowTitle(), self.i18n.t("groups.invalid_group_name"))
            return
        self.refresh()
        self.groups_changed.emit()
