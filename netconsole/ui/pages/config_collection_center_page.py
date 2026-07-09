from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.config_snapshot_repository import ConfigSnapshot, ConfigSnapshotRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_group_service import ALL_GROUPS, UNGROUPED, group_filter_to_repository_value
from netconsole.services.config_lifecycle_service import BatchConfigItemResult, ConfigDiffResult, ConfigLifecycleService, MultiDeviceCompareResult, safe_device_name, snapshot_timestamp, unique_export_folder_name
from netconsole.services.export.export_task_builders import config_snapshots_zip_spec, markdown_text_spec
from netconsole.ui.config_lifecycle_worker import ConfigLifecycleWorker
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.widgets.config_diff_viewer import ConfigDiffViewer
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.shell.fluent_bridge import InfoBar, InfoBarPosition
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate, is_checked_value, set_all_table_rows_checked


DEVICE_COLUMNS = ("select", "name", "device_type", "station")
SNAPSHOT_COLUMNS = ("select", "type", "timestamp", "size")
CHECK_COLUMN = 0
SNAPSHOT_CHECK_COLUMN = 0


class ConfigCollectionCenterPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.snapshot_repository = ConfigSnapshotRepository(repository.database)
        self.group_repository = DeviceGroupRepository(repository.database, site_name)
        self.service = ConfigLifecycleService(site_name, repository.database, paths, self.snapshot_repository)
        self.worker: ConfigLifecycleWorker | None = None
        self.devices: list[Device] = []
        self.snapshots: list[ConfigSnapshot] = []
        self.checked_device_ids: set[int] = set()
        self.checked_snapshot_ids: set[int] = set()
        self.current_batch_results: list[BatchConfigItemResult] = []
        self.current_raw_diff = ""
        self._updating_checks = False
        self._updating_snapshot_checks = False

        self.title_label = QLabel()
        self.search_input = QLineEdit()
        self.group_label = QLabel()
        self.group_filter = QComboBox()
        self.status_label = QLabel()
        self.snapshots_label = QLabel()
        self.device_table = QTableWidget(0, len(DEVICE_COLUMNS))
        self.snapshot_table = QTableWidget(0, len(SNAPSHOT_COLUMNS))
        self.save_button = QPushButton()
        self.fetch_button = QPushButton()
        self.compare_button = QPushButton()
        self.open_dir_button = QPushButton()
        self.download_button = QPushButton()
        self.export_batch_button = QPushButton()
        self.export_diff_button = QPushButton()
        self.delete_button = QPushButton()
        self.refresh_button = QPushButton()
        self.toggle_sidebar_button = QPushButton()
        self.running_text = QTextEdit()
        self.saved_text = QTextEdit()
        self.diff_viewer = ConfigDiffViewer(i18n)
        self.tabs = QTabWidget()
        self.left_panel = QWidget()
        self.splitter = QSplitter(Qt.Horizontal)
        self._left_collapsed = False
        self._left_last_width = 320

        self._configure_tables()
        for editor in (self.running_text, self.saved_text):
            editor.setReadOnly(True)
            editor.setLineWrapMode(QTextEdit.NoWrap)

        file_actions = QHBoxLayout()
        for button in (self.open_dir_button, self.download_button, self.export_batch_button, self.export_diff_button, self.delete_button):
            file_actions.addWidget(button)
        file_actions.addStretch(1)

        left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(self.title_label)
        left_layout.addWidget(self.search_input)
        group_row = QHBoxLayout()
        group_row.addWidget(self.group_label)
        group_row.addWidget(self.group_filter)
        group_row.addStretch(1)
        left_layout.addLayout(group_row)
        left_layout.addWidget(self.device_table, 3)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.snapshots_label)
        left_layout.addWidget(self.snapshot_table, 2)
        left_layout.addLayout(file_actions)

        self.tabs.addTab(self.running_text, "")
        self.tabs.addTab(self.saved_text, "")
        self.tabs.addTab(self.diff_viewer, "")

        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        sidebar_row = QHBoxLayout()
        sidebar_row.addWidget(self.toggle_sidebar_button)
        sidebar_row.addStretch(1)
        layout.addLayout(sidebar_row)
        layout.addWidget(self.splitter)

        self.device_table.itemSelectionChanged.connect(self.refresh_snapshots)
        self.device_table.itemChanged.connect(self._device_item_changed)
        self.device_table.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.search_input.textChanged.connect(self.refresh)
        self.group_filter.currentIndexChanged.connect(self._group_filter_changed)
        self.snapshot_table.itemSelectionChanged.connect(self.show_selected_snapshot)
        self.snapshot_table.itemChanged.connect(self._snapshot_item_changed)
        self.snapshot_table.horizontalHeader().sectionClicked.connect(self._snapshot_header_clicked)
        self.save_button.clicked.connect(lambda: self._start_single_action("save"))
        self.fetch_button.clicked.connect(self.download_configs)
        self.compare_button.clicked.connect(self.compare_configs)
        self.refresh_button.clicked.connect(self.refresh)
        self.toggle_sidebar_button.clicked.connect(self.toggle_sidebar)
        self.open_dir_button.clicked.connect(self.open_device_config_dir)
        self.download_button.clicked.connect(self.download_selected_snapshot)
        self.export_batch_button.clicked.connect(self.export_current_batch)
        self.export_diff_button.clicked.connect(self.export_current_diff)
        self.delete_button.clicked.connect(self.delete_selected_snapshot)

        self.retranslate()
        self.refresh()

    def t(self, key: str, **kwargs: object) -> str:
        return self.i18n.t(key, **kwargs)

    def retranslate(self) -> None:
        self.title_label.setText(self.t("config_center.title"))
        self.search_input.setPlaceholderText(self.t("config_center.search.placeholder"))
        self.group_label.setText(self.t("groups.group"))
        self.snapshots_label.setText(self.t("config_center.snapshots"))
        self.save_button.setText(self.t("config_center.btn.save_config"))
        self.fetch_button.setText(self.t("config_center.btn.download_config"))
        self.compare_button.setText(self.t("config_center.btn.compare_config"))
        self.refresh_button.setText(self.t("config_center.btn.refresh"))
        self._sync_sidebar_button_text()
        self.open_dir_button.setText(self.t("config_center.btn.open_config_dir"))
        self.download_button.setText(self.t("config_center.btn.download_snapshot"))
        self.export_batch_button.setText(self.t("config_center.btn.export_batch"))
        self.export_diff_button.setText(self.t("config_center.btn.export_diff"))
        self.delete_button.setText(self.t("config_center.btn.delete_snapshot"))
        self.delete_button.setObjectName("dangerButton")
        self._apply_button_icons()
        self.device_table.setHorizontalHeaderLabels(
            [
                "",
                self.t("config_center.col.device_name"),
                self.t("config_center.col.type"),
                self.t("config_center.col.station"),
            ]
        )
        self._sync_header_check_state()
        self.snapshot_table.setHorizontalHeaderLabels(
            [
                "",
                self.t("config_center.col.type"),
                self.t("config_center.col.time"),
                self.t("config_center.col.size"),
            ]
        )
        self._sync_snapshot_header_check_state()
        self.tabs.setTabText(0, self.t("config_center.tab.running"))
        self.tabs.setTabText(1, self.t("config_center.tab.saved"))
        self.tabs.setTabText(2, self.t("config_center.tab.diff"))
        self.diff_viewer.retranslate()
        self._sync_buttons()
        self.refresh_groups()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.site_name = site_name
        self.snapshot_repository = ConfigSnapshotRepository(repository.database)
        self.group_repository = DeviceGroupRepository(repository.database, site_name)
        self.service = ConfigLifecycleService(site_name, repository.database, self.paths, self.snapshot_repository)
        self.checked_device_ids.clear()
        self.current_batch_results = []
        self.current_raw_diff = ""
        self.search_input.clear()
        self.refresh_groups()
        self.refresh()

    def refresh_groups(self) -> None:
        current = self.group_filter.currentData()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem(self.t("groups.all_groups"), ALL_GROUPS)
        self.group_filter.addItem(self.t("groups.ungrouped"), UNGROUPED)
        for group in self.group_repository.list():
            self.group_filter.addItem(group.name, group.id)
        index = self.group_filter.findData(current if current is not None else ALL_GROUPS)
        self.group_filter.setCurrentIndex(index if index >= 0 else 0)
        self.group_filter.blockSignals(False)

    def toggle_sidebar(self) -> None:
        sizes = self.splitter.sizes()
        if self._left_collapsed:
            restored = max(self._left_last_width, 240)
            total = sum(sizes) or self.width() or 1000
            self.splitter.setSizes([restored, max(total - restored, 300)])
            self._left_collapsed = False
        else:
            if sizes and sizes[0] > 0:
                self._left_last_width = sizes[0]
            total = sum(sizes) or self.width() or 1000
            self.splitter.setSizes([0, max(total, 300)])
            self._left_collapsed = True
        self._sync_sidebar_button_text()

    def _group_filter_changed(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        search = self.search_input.text().strip()
        self.devices = self.repository.list(
            search=search or None,
            vendor="H3C",
            group_filter=group_filter_to_repository_value(self.group_filter.currentData()),
        )
        self._updating_checks = True
        self.device_table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            self._set_checkbox(row, device)
            for column, value in enumerate((device.name, device.device_type, device.station), start=1):
                item = QTableWidgetItem("" if value is None else str(value))
                item.setData(Qt.UserRole, int(device.id) if device.id is not None else None)
                self.device_table.setItem(row, column, item)
        self._updating_checks = False
        self._sync_header_check_state()
        apply_table_style(self.device_table)
        if self.devices and self.device_table.currentRow() < 0:
            self.device_table.setCurrentCell(0, 1)
        self.refresh_snapshots()

    def refresh_snapshots(self) -> None:
        device = self.selected_device()
        self.snapshots = [] if device is None else self.service.list_device_snapshots(device)
        visible_snapshot_ids = {int(snapshot.id) for snapshot in self.snapshots if snapshot.id is not None}
        self.checked_snapshot_ids.intersection_update(visible_snapshot_ids)
        self._updating_snapshot_checks = True
        self.snapshot_table.setRowCount(len(self.snapshots))
        for row, snapshot in enumerate(self.snapshots):
            self._set_snapshot_checkbox(row, snapshot)
            values = (self._snapshot_type_label(snapshot.type), snapshot.timestamp, self._snapshot_size(snapshot))
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, int(snapshot.id) if snapshot.id is not None else None)
                self.snapshot_table.setItem(row, column, item)
        self._updating_snapshot_checks = False
        apply_table_style(self.snapshot_table)
        self._sync_snapshot_header_check_state()
        self._sync_buttons()

    def selected_device(self) -> Device | None:
        row = self.device_table.currentRow()
        if row < 0 or row >= len(self.devices):
            return None
        return self.devices[row]

    def checked_devices(self) -> list[Device]:
        return [device for device in self.devices if device.id in self.checked_device_ids]

    def primary_device(self) -> Device | None:
        checked = self.checked_devices()
        if len(checked) == 1:
            return checked[0]
        return self.selected_device()

    def selected_snapshot(self) -> ConfigSnapshot | None:
        row = self.snapshot_table.currentRow()
        if row < 0 or row >= len(self.snapshots):
            return None
        return self.snapshots[row]

    def selected_snapshots(self) -> list[ConfigSnapshot]:
        selected_ids = set(self.checked_snapshot_ids)
        return [snapshot for snapshot in self.snapshots if snapshot.id in selected_ids]

    def download_configs(self) -> None:
        checked = self.checked_devices()
        if len(checked) > 1:
            self._start_batch_fetch(checked)
            return
        self._start_single_action("fetch")

    def compare_configs(self) -> None:
        checked = self.checked_devices()
        if len(checked) == 2:
            self.compare_two_devices(checked[0], checked[1])
            return
        if len(checked) > 2:
            self._show_info("config_center.msg.select_two_devices")
            return
        self.compare_latest_snapshots()

    def compare_two_devices(self, device_a: Device, device_b: Device) -> None:
        try:
            result = self.service.compare_latest_running_between_devices(device_a, device_b)
        except Exception as exc:
            MessageBox.warning(self, self._title(), str(exc))
            return
        self.running_text.setPlainText(self.t("config_center.text.running_config", device=result.device_a))
        self.saved_text.setPlainText(self.t("config_center.text.running_config", device=result.device_b))
        self.current_raw_diff = result.diff.raw_diff
        self.diff_viewer.set_diff(result.device_a, result.device_b, self.service.snapshot_text(self.service.list_device_snapshots(device_a, "running")[0]), self.service.snapshot_text(self.service.list_device_snapshots(device_b, "running")[0]), result.diff.raw_diff)
        self.tabs.setCurrentWidget(self.diff_viewer)
        self.status_label.setText(self.t("config_center.status.two_device_compare_done"))

    def compare_latest_snapshots(self) -> None:
        device = self.primary_device()
        if device is None:
            return
        running = self.service.list_device_snapshots(device, "running")
        saved = self.service.list_device_snapshots(device, "saved")
        if not running or not saved:
            self._show_info("config_center.msg.need_snapshots")
            return
        diff = self.service.compare_snapshots(running[0], saved[0])
        running_text = self.service.snapshot_text(running[0])
        saved_text = self.service.snapshot_text(saved[0])
        self.running_text.setPlainText(running_text)
        self.saved_text.setPlainText(saved_text)
        self.current_raw_diff = diff.raw_diff
        self.diff_viewer.set_diff(self.t("config_center.tab.running"), self.t("config_center.tab.saved"), running_text, saved_text, diff.raw_diff)
        self.tabs.setCurrentWidget(self.diff_viewer)
        self.status_label.setText(self.t("config_center.status.latest_compare_done"))

    def _start_single_action(self, action: str) -> None:
        device = self.primary_device()
        if device is None:
            self._show_info("config_center.msg.select_device")
            return
        self._set_busy(True)
        self.status_label.setText(self.t("config_center.status.running"))
        self.worker = ConfigLifecycleWorker(action, self.service, device=device, parent=self)
        self.worker.result_ready.connect(self._handle_operation_result)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(lambda: setattr(self, "worker", None))
        self.worker.start()

    def _start_batch_fetch(self, devices: list[Device]) -> None:
        self._set_busy(True)
        self.status_label.setText(self.t("config_center.status.download_running", count=len(devices)))
        self.worker = ConfigLifecycleWorker("batch_fetch", self.service, devices=devices, parent=self)
        self.worker.result_ready.connect(self._handle_batch_result)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(lambda: setattr(self, "worker", None))
        self.worker.start()

    def _handle_operation_result(self, result) -> None:
        self._set_busy(False)
        self.current_batch_results = []
        self.refresh_snapshots()
        if result.success:
            self.status_label.setText(result.warning_message or self.t("config_center.status.done"))
            self._show_result_snapshots(result.snapshots, result.diff)
        else:
            message = result.error_message or self.t("config_center.status.failed")
            self.status_label.setText(message)
            MessageBox.warning(self, self._title(), message)

    def _handle_batch_result(self, results) -> None:
        self._set_busy(False)
        self.refresh_snapshots()
        success = sum(1 for item in results if item.success)
        failed = len(results) - success
        self.current_batch_results = list(results)
        self.current_raw_diff = ""
        lines = [self.t("config_center.status.download_done", success=success, failed=failed), ""]
        for item in results:
            status = self.t("config_center.result.success") if item.success else self.t("config_center.result.failed")
            lines.append(f"{item.device_name}: {status} {item.result_text}")
        self.diff_viewer.set_message("\n".join(lines))
        self.tabs.setCurrentWidget(self.diff_viewer)
        self.status_label.setText(lines[0])
        self._sync_buttons()

    def show_selected_snapshot(self) -> None:
        snapshot = self.selected_snapshot()
        if snapshot is None:
            self._sync_buttons()
            return
        text = self.service.snapshot_text(snapshot)
        if snapshot.type == "running":
            self.running_text.setPlainText(text)
            self.tabs.setCurrentWidget(self.running_text)
        elif snapshot.type == "saved":
            self.saved_text.setPlainText(text)
            self.tabs.setCurrentWidget(self.saved_text)
        else:
            self.current_raw_diff = text
            self.diff_viewer.set_message(text)
            self.tabs.setCurrentWidget(self.diff_viewer)
        self._sync_buttons()

    def open_device_config_dir(self) -> None:
        device = self.primary_device()
        if device is None:
            return
        path = self.service.device_config_dir(device)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def download_selected_snapshot(self) -> None:
        snapshots = self.selected_snapshots()
        if not snapshots:
            self._show_info("config_center.msg.select_snapshot")
            return
        if len(snapshots) > 1:
            directory = QFileDialog.getExistingDirectory(self, self.download_button.text(), str(Path.cwd()))
            if not directory:
                return
            target_dir = Path(directory)
            for snapshot in snapshots:
                suffix = ".diff" if snapshot.type == "diff" else ".txt"
                self.service.copy_snapshot(snapshot, target_dir / self._snapshot_download_filename(snapshot, suffix))
            self.status_label.setText(self.t("config_center.status.snapshot_downloaded"))
            self._show_success(self.t("config_center.status.snapshot_downloaded"))
            return
        snapshot = snapshots[0]
        suffix = ".diff" if snapshot.type == "diff" else ".txt"
        target, _ = QFileDialog.getSaveFileName(self, self.download_button.text(), self._snapshot_download_filename(snapshot, suffix))
        if target:
            self.service.copy_snapshot(snapshot, Path(target))
            self.status_label.setText(self.t("config_center.status.snapshot_downloaded"))
            self._show_success(self.t("config_center.status.snapshot_downloaded"))

    def export_current_batch(self) -> None:
        snapshots = self.selected_snapshots()
        if snapshots:
            timestamps = {snapshot.timestamp for snapshot in snapshots}
            if len(timestamps) != 1:
                self._show_info("config_center.msg.batch_unresolved")
                return
            default_name = f"{safe_device_name(self.t('config_center.batch_export.prefix'))}_{safe_device_name(self.site_name)}_{next(iter(timestamps))}.zip"
            target, _ = QFileDialog.getSaveFileName(self, self.export_batch_button.text(), default_name, "ZIP (*.zip)")
            if not target:
                return
            self._export_snapshots_zip(snapshots, Path(target))
            return
        if not self.current_batch_results:
            self._show_info("config_center.msg.select_snapshot")
            return
        default_name = f"{safe_device_name(self.t('config_center.batch_export.prefix'))}_{safe_device_name(self.site_name)}_{snapshot_timestamp()}.zip"
        target, _ = QFileDialog.getSaveFileName(self, self.export_batch_button.text(), default_name, "ZIP (*.zip)")
        if not target:
            return
        snapshot_entries, file_entries, failures_text = self._current_batch_zip_entries()
        submit_export_task(
            self,
            config_snapshots_zip_spec(
                target,
                db_path=self.repository.database.path,
                site_name=self.site_name,
                snapshot_entries=snapshot_entries,
                file_entries=file_entries,
                failures_text=failures_text,
                title=self.export_batch_button.text(),
                open_dir_on_success=True,
            ),
            success_title=self.export_batch_button.text(),
            paths=self.paths,
        )

    def export_current_diff(self) -> None:
        snapshots = self.selected_snapshots()
        if snapshots:
            if len(snapshots) != 2:
                self._show_info("config_center.msg.select_two_snapshots")
                return
            diff = self.service.compare_snapshots(snapshots[0], snapshots[1])
            self.current_raw_diff = diff.raw_diff
            self.diff_viewer.set_diff(
                self._snapshot_type_label(snapshots[0].type),
                self._snapshot_type_label(snapshots[1].type),
                self.service.snapshot_text(snapshots[0]),
                self.service.snapshot_text(snapshots[1]),
                diff.raw_diff,
            )
            self.tabs.setCurrentWidget(self.diff_viewer)
        if not self.current_raw_diff:
            self._show_info("config_center.msg.select_two_snapshots")
            return
        target, _ = QFileDialog.getSaveFileName(self, self.export_diff_button.text(), f"diff_{snapshot_timestamp()}.diff", "Diff (*.diff);;Text (*.txt)")
        if target:
            submit_export_task(
                self,
                markdown_text_spec(target, text=self.current_raw_diff, title=self.export_diff_button.text(), open_dir_on_success=True),
                success_title=self.export_diff_button.text(),
                paths=self.paths,
            )

    def delete_selected_snapshot(self) -> None:
        snapshots = self.selected_snapshots()
        if not snapshots:
            self._show_info("config_center.msg.select_snapshot")
            return
        answer = MessageBox.question(self, self.t("config_center.btn.delete_snapshot"), self.t("config_center.msg.confirm_delete_snapshot", count=len(snapshots)))
        if answer == MessageBox.Yes:
            for snapshot in snapshots:
                self.service.delete_snapshot(snapshot)
            self.checked_snapshot_ids.clear()
            self.refresh_snapshots()
            self._show_success(self.t("config_center.status.snapshot_deleted", count=len(snapshots)))

    def _show_result_snapshots(self, snapshots: list[ConfigSnapshot], diff: ConfigDiffResult | None) -> None:
        for snapshot in snapshots:
            text = self.service.snapshot_text(snapshot)
            if snapshot.type == "running":
                self.running_text.setPlainText(text)
            elif snapshot.type == "saved":
                self.saved_text.setPlainText(text)
            elif snapshot.type == "diff":
                self.current_raw_diff = text
                self.diff_viewer.set_message(text)
        if diff is not None:
            running = next((snapshot for snapshot in snapshots if snapshot.type == "running"), None)
            saved = next((snapshot for snapshot in snapshots if snapshot.type == "saved"), None)
            self.current_raw_diff = diff.raw_diff
            if running is not None and saved is not None:
                self.diff_viewer.set_diff(self.t("config_center.tab.running"), self.t("config_center.tab.saved"), self.service.snapshot_text(running), self.service.snapshot_text(saved), diff.raw_diff)
            else:
                self.diff_viewer.set_message(diff.raw_diff)
            self.tabs.setCurrentWidget(self.diff_viewer)

    def _configure_tables(self) -> None:
        set_table_column_fields(self.device_table, DEVICE_COLUMNS)
        set_table_column_fields(self.snapshot_table, SNAPSHOT_COLUMNS)
        configure_readonly_table(self.device_table)
        configure_readonly_table(self.snapshot_table)
        install_checkbox_only_delegate(self.device_table, CHECK_COLUMN)
        install_checkbox_only_delegate(self.snapshot_table, SNAPSHOT_CHECK_COLUMN)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.snapshot_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.device_table.setColumnWidth(CHECK_COLUMN, 72)
        self.snapshot_table.setColumnWidth(SNAPSHOT_CHECK_COLUMN, 72)

    def _set_checkbox(self, row: int, device: Device) -> None:
        item = create_checkable_table_item(
            device.id in self.checked_device_ids,
            user_data=int(device.id) if device.id is not None else None,
        )
        self.device_table.setItem(row, CHECK_COLUMN, item)

    def _set_snapshot_checkbox(self, row: int, snapshot: ConfigSnapshot) -> None:
        item = create_checkable_table_item(
            snapshot.id in self.checked_snapshot_ids,
            user_data=int(snapshot.id) if snapshot.id is not None else None,
        )
        self.snapshot_table.setItem(row, SNAPSHOT_CHECK_COLUMN, item)

    def _device_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_checks or item.column() != CHECK_COLUMN:
            return
        device_id = item.data(Qt.UserRole)
        if device_id is None:
            return
        if is_checked_value(item.checkState()):
            self.checked_device_ids.add(int(device_id))
        else:
            self.checked_device_ids.discard(int(device_id))
        self._sync_header_check_state()
        self._sync_buttons()

    def _snapshot_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_snapshot_checks or item.column() != SNAPSHOT_CHECK_COLUMN:
            return
        snapshot_id = item.data(Qt.UserRole)
        if snapshot_id is None:
            return
        if is_checked_value(item.checkState()):
            self.checked_snapshot_ids.add(int(snapshot_id))
        else:
            self.checked_snapshot_ids.discard(int(snapshot_id))
        self._sync_snapshot_header_check_state()
        self._sync_buttons()

    def _header_clicked(self, section: int) -> None:
        if section != CHECK_COLUMN:
            return
        selectable_count = len([device for device in self.devices if device.id is not None])
        visible_checked = len([device for device in self.devices if device.id in self.checked_device_ids])
        self._set_all_checked(visible_checked != selectable_count)

    def _snapshot_header_clicked(self, section: int) -> None:
        if section != SNAPSHOT_CHECK_COLUMN:
            return
        selectable_count = len([snapshot for snapshot in self.snapshots if snapshot.id is not None])
        visible_checked = len([snapshot for snapshot in self.snapshots if snapshot.id in self.checked_snapshot_ids])
        self._set_all_snapshots_checked(visible_checked != selectable_count)

    def _set_all_checked(self, checked: bool) -> None:
        self._updating_checks = True
        visible_ids = {int(device.id) for device in self.devices if device.id is not None}
        if not checked:
            self.checked_device_ids.difference_update(visible_ids)
        set_all_table_rows_checked(self.device_table, checked, CHECK_COLUMN)
        for row, device in enumerate(self.devices):
            item = self.device_table.item(row, CHECK_COLUMN)
            if item is None:
                continue
            if checked and device.id is not None:
                self.checked_device_ids.add(int(device.id))
        self._updating_checks = False
        self._sync_header_check_state()
        self._sync_buttons()

    def _set_all_snapshots_checked(self, checked: bool) -> None:
        self._updating_snapshot_checks = True
        visible_ids = {int(snapshot.id) for snapshot in self.snapshots if snapshot.id is not None}
        if not checked:
            self.checked_snapshot_ids.difference_update(visible_ids)
        set_all_table_rows_checked(self.snapshot_table, checked, SNAPSHOT_CHECK_COLUMN)
        for snapshot in self.snapshots:
            if checked and snapshot.id is not None:
                self.checked_snapshot_ids.add(int(snapshot.id))
        self._updating_snapshot_checks = False
        self._sync_snapshot_header_check_state()
        self._sync_buttons()

    def _sync_header_check_state(self) -> None:
        item = self.device_table.horizontalHeaderItem(CHECK_COLUMN) or QTableWidgetItem()
        item.setText(self.t("config_center.btn.select_all"))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        visible_ids = {int(device.id) for device in self.devices if device.id is not None}
        total = len(visible_ids)
        checked = len(visible_ids & self.checked_device_ids)
        if checked == 0 or total == 0:
            item.setCheckState(Qt.Unchecked)
        elif checked == total:
            item.setCheckState(Qt.Checked)
        else:
            item.setCheckState(Qt.PartiallyChecked)
        self.device_table.setHorizontalHeaderItem(CHECK_COLUMN, item)

    def _sync_snapshot_header_check_state(self) -> None:
        item = self.snapshot_table.horizontalHeaderItem(SNAPSHOT_CHECK_COLUMN) or QTableWidgetItem()
        item.setText(self.t("config_center.btn.select_all"))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        visible_ids = {int(snapshot.id) for snapshot in self.snapshots if snapshot.id is not None}
        total = len(visible_ids)
        checked = len(visible_ids & self.checked_snapshot_ids)
        if checked == 0 or total == 0:
            item.setCheckState(Qt.Unchecked)
        elif checked == total:
            item.setCheckState(Qt.Checked)
        else:
            item.setCheckState(Qt.PartiallyChecked)
        self.snapshot_table.setHorizontalHeaderItem(SNAPSHOT_CHECK_COLUMN, item)

    def _set_busy(self, busy: bool) -> None:
        for button in (self.save_button, self.fetch_button, self.compare_button, self.refresh_button, self.open_dir_button):
            button.setEnabled(not busy)
        self.device_table.setEnabled(not busy)
        self.snapshot_table.setEnabled(not busy)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_device = self.primary_device() is not None
        checked_count = len(self.checked_device_ids)
        selected_snapshot_count = len(self.selected_snapshots())
        has_snapshot = selected_snapshot_count > 0
        if self.worker is None:
            self.save_button.setEnabled(has_device and checked_count <= 1)
            self.fetch_button.setEnabled(has_device)
            self.compare_button.setEnabled(has_device or checked_count == 2)
            self.refresh_button.setEnabled(True)
            self.open_dir_button.setEnabled(has_device and checked_count <= 1)
        self.download_button.setEnabled(has_snapshot and self.worker is None)
        self.export_batch_button.setEnabled((has_snapshot or (bool(self.current_batch_results) and any(item.success for item in self.current_batch_results))) and self.worker is None)
        self.export_diff_button.setEnabled(((selected_snapshot_count == 2) or bool(self.current_raw_diff)) and self.worker is None)
        self.delete_button.setEnabled(has_snapshot and self.worker is None)
        self.snapshots_label.setText(f"{self.t('config_center.snapshots')}（{self.t('config_center.status.selected_snapshots', count=selected_snapshot_count)}）")

    def _sync_sidebar_button_text(self) -> None:
        self.toggle_sidebar_button.setText(self.t("config_center.btn.expand_sidebar") if self._left_collapsed else self.t("config_center.btn.collapse_sidebar"))

    def _snapshot_size(self, snapshot: ConfigSnapshot) -> str:
        path = self.paths.site_dir(self.site_name) / snapshot.file_path
        if not path.exists():
            return "-"
        return self.t("config_center.unit.bytes", size=path.stat().st_size)

    def _snapshot_type_label(self, snapshot_type: str) -> str:
        labels = {
            "running": self.t("config_center.tab.running"),
            "saved": self.t("config_center.tab.saved"),
            "diff": self.t("config_center.tab.diff"),
        }
        return labels.get(snapshot_type, snapshot_type)

    def _format_multi_device_diff(self, result: MultiDeviceCompareResult) -> str:
        only_a = "\n".join(f"- {item}" for item in result.structure_diff["only_in_a"]) or "-"
        only_b = "\n".join(f"- {item}" for item in result.structure_diff["only_in_b"]) or "-"
        return "\n".join(
            [
                self.t("config_center.text.structure_diff", device=result.device_a),
                only_a,
                "",
                self.t("config_center.text.structure_diff", device=result.device_b),
                only_b,
                "",
                self.t("config_center.text.unified_diff"),
                result.diff.raw_diff,
            ]
        )

    def _snapshot_download_filename(self, snapshot: ConfigSnapshot, suffix: str) -> str:
        device = self.selected_device()
        device_name = ""
        if device is not None:
            device_name = str(device.name or device.system_name or device.device_uuid or "")
        if not device_name:
            device_name = str(snapshot.device_uuid or "device")
        return f"{safe_device_name(device_name)}_{snapshot.type}_{snapshot.timestamp}{suffix}"

    def _show_info(self, key: str) -> None:
        MessageBox.information(self, self._title(), self.t(key))

    def _title(self) -> str:
        return self.t("config_center.title")

    def _apply_button_icons(self) -> None:
        for button, icon_name in (
            (self.save_button, "SAVE"),
            (self.fetch_button, "DOWNLOAD"),
            (self.compare_button, "DOCUMENT"),
            (self.open_dir_button, "FOLDER"),
            (self.refresh_button, "SYNC"),
            (self.download_button, "DOWNLOAD"),
            (self.export_batch_button, "SHARE"),
            (self.export_diff_button, "DOCUMENT"),
            (self.delete_button, "DELETE"),
            (self.toggle_sidebar_button, "MENU"),
        ):
            apply_button_icon(button, icon_name)
            button.setToolTip(button.text())

    def _show_success(self, message: str) -> None:
        self.status_label.setText(message)
        if InfoBar is not None:
            InfoBar.success(title=self._title(), content=message, duration=2500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _export_snapshots_zip(self, snapshots: list[ConfigSnapshot], target_zip_path: Path) -> None:
        submit_export_task(
            self,
            config_snapshots_zip_spec(
                target_zip_path,
                db_path=self.repository.database.path,
                site_name=self.site_name,
                snapshot_entries=self._snapshot_zip_entries(snapshots),
                title=self.export_batch_button.text(),
                open_dir_on_success=True,
            ),
            success_title=self.export_batch_button.text(),
            paths=self.paths,
        )

    def _snapshot_zip_entries(self, snapshots: list[ConfigSnapshot]) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for snapshot in snapshots:
            if snapshot.id is None:
                continue
            suffix = "diff" if snapshot.type == "diff" else "txt"
            entries.append(
                {
                    "snapshot_id": int(snapshot.id),
                    "archive_name": f"{snapshot.timestamp}/{snapshot.type}_{snapshot.id or 'snapshot'}.{suffix}",
                }
            )
        return entries

    def _current_batch_zip_entries(self) -> tuple[list[dict[str, object]], list[dict[str, object]], str]:
        snapshot_entries: list[dict[str, object]] = []
        file_entries: list[dict[str, object]] = []
        failures: list[str] = []
        used_folders: dict[str, int] = {}
        for item in self.current_batch_results:
            if not item.success:
                message = item.error_message or item.result_text or "failed"
                failures.append(f"{item.device_name or item.device_uuid}\t{message}")
                continue
            folder = unique_export_folder_name(item.device_name, item.device_uuid, used_folders)
            for snapshot in item.snapshots:
                if snapshot.id is None:
                    continue
                suffix = "diff" if snapshot.type == "diff" else "txt"
                snapshot_entries.append(
                    {
                        "snapshot_id": int(snapshot.id),
                        "archive_name": f"{folder}/{snapshot.type}_{snapshot.timestamp}.{suffix}",
                    }
                )
            for log_path in self.service._batch_log_paths(item):
                file_entries.append({"path": str(log_path), "archive_name": f"{folder}/logs/{log_path.name}"})
        return snapshot_entries, file_entries, "\n".join(failures)
