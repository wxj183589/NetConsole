from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.ui.dialogs.input_dialog_service import InputDialog
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.models.device_group import DeviceGroup
from netconsole.services.background_job import BackgroundJob
from netconsole.ui.job_process_manager import BackgroundProcessManager
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.adaptive_dialog import install_scrollable_dialog_content


GROUP_COLUMNS = ("name", "count")


class DeviceGroupDialog(QDialog):
    groups_changed = Signal()

    def __init__(self, i18n: I18n, repository, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.db_path = repository.database.path
        self.site_name = repository.site_id
        self.groups: list[DeviceGroup] = []
        self.counts: dict[int, int] = {}
        self.background_manager = BackgroundProcessManager(self)
        self.background_manager.finished.connect(self._background_finished)
        self.background_manager.failed.connect(self._background_failed)
        self._jobs: dict[str, dict[str, object]] = {}
        self.table = QTableWidget(0, len(GROUP_COLUMNS))
        set_table_column_fields(self.table, list(GROUP_COLUMNS))
        configure_readonly_table(self.table)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.add_button = QPushButton()
        self.rename_button = QPushButton()
        self.delete_button = QPushButton()
        self.close_button = QPushButton()

        actions = QHBoxLayout()
        for button in (self.add_button, self.rename_button, self.delete_button, self.close_button):
            actions.addWidget(button)
        actions.addStretch(1)
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        self.scroll_area = install_scrollable_dialog_content(self, content, minimum_width=420, minimum_height=300, content_minimum_width=560)

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
        self._start_group_job("device_group_refresh")

    def _fill_groups(self, groups: list[DeviceGroup], counts: dict[int, int]) -> None:
        self.groups = groups
        self.counts = counts
        self.table.setRowCount(len(self.groups))
        for row, group in enumerate(self.groups):
            name = QTableWidgetItem(group.name)
            name.setData(256, group.id)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(str(self.counts.get(int(group.id or 0), 0))))
        apply_table_style(self.table)

    def selected_group_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.groups):
            return None
        return int(self.groups[row].id)

    def add_group(self) -> None:
        name, accepted = InputDialog.getText(self, self.windowTitle(), self.i18n.t("groups.group_name"))
        if accepted:
            self._start_group_job("device_group_create", name=name)

    def rename_group(self) -> None:
        group_id = self.selected_group_id()
        if group_id is None:
            return
        current = self.groups[self.table.currentRow()].name
        name, accepted = InputDialog.getText(self, self.i18n.t("groups.rename_group"), self.i18n.t("groups.group_name"), text=current)
        if accepted:
            self._start_group_job("device_group_rename", group_id=group_id, name=name)

    def delete_group(self) -> None:
        group_id = self.selected_group_id()
        if group_id is None:
            return
        self._start_group_job("device_group_count_devices", group_id=group_id)

    def _confirm_delete_group(self, group_id: int, count: int) -> None:
        message = self.i18n.t("groups.delete_group_confirm_with_devices", count=count) if count else self.i18n.t("groups.delete_group_confirm")
        if MessageBox.question(self, self.i18n.t("groups.delete_group"), message) == MessageBox.Yes:
            self._start_group_job("device_group_delete", group_id=group_id)

    def _start_group_job(self, task_type: str, **params: object) -> None:
        job_params = {"db_path": str(self.db_path), "site_name": self.site_name, **params}
        job_id = self.background_manager.start_job(BackgroundJob(task_type=task_type, params=job_params))
        self._jobs[job_id] = {"task_type": task_type, **params}
        self._set_busy(True)

    def _background_finished(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        context = self._jobs.pop(job_id, {})
        task_type = str(context.get("task_type") or "")
        result = dict(event.get("result") or {})
        if task_type == "device_group_refresh":
            groups = [DeviceGroup(**dict(row)) for row in result.get("groups") or [] if isinstance(row, dict)]
            counts = {int(key): int(value) for key, value in dict(result.get("counts") or {}).items()}
            self._fill_groups(groups, counts)
        elif task_type == "device_group_count_devices":
            self._confirm_delete_group(int(result.get("group_id") or context.get("group_id") or 0), int(result.get("count") or 0))
        elif task_type in {"device_group_create", "device_group_rename", "device_group_delete"}:
            self.groups_changed.emit()
            self.refresh()
            return
        self._set_busy(bool(self._jobs))

    def _background_failed(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        self._jobs.pop(job_id, None)
        message = str(event.get("message") or event.get("error") or "")
        if "exists" in message or "Duplicate" in message:
            message = self.i18n.t("groups.duplicate_group_name")
        elif "empty" in message or "too long" in message or "ValueError" in message:
            message = self.i18n.t("groups.invalid_group_name")
        MessageBox.warning(self, self.windowTitle(), message or self.i18n.t("groups.invalid_group_name"))
        self._set_busy(bool(self._jobs))

    def _set_busy(self, busy: bool) -> None:
        self.add_button.setEnabled(not busy)
        self.rename_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy)
