from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from time import perf_counter

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit.trackside_optical_history import TracksideOpticalHistoryService
from netconsole.services.rail_transit.trackside_optical_collection import DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY
from netconsole.services.trackside_ap_business import (
    TRACKSIDE_AP_BUSINESS_COLUMNS,
    build_trackside_site_filter_items,
    export_trackside_ap_business_xlsx,
    filter_trackside_ap_business_rows,
    format_trackside_display_value,
    trackside_row_status,
)
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS, ApOnlineOverviewService
from netconsole.ui.dialogs.device_detail_dialog import DeviceDetailDialog
from netconsole.ui.dialogs.fit_ap_detail_dialog import FitApDetailDialog
from netconsole.ui.dialogs.trackside_interface_history_dialog import TracksideInterfaceHistoryDialog
from netconsole.ui.export_path import EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.table_column_state import TableColumnState
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, create_table_context_menu, make_text_selectable
from netconsole.ui.theme.contrast_engine import apply_status_item_contrast
from netconsole.ui.trackside_optical_worker import TracksideApBusinessLoadResult, TracksideApBusinessLoadThread, TracksideOpticalCollectThread
from netconsole.ui.widgets.pagination_widget import PaginationWidget


def trackside_default_column_widths() -> dict[str, int]:
    return {
        "site": 120,
        "device_name": 160,
        "interface_name": 190,
        "link_status": 80,
        "description": 220,
        "port_status": 110,
        "pvid": 70,
        "match_source": 110,
        "vlan": 80,
        "switch_rx_power": 120,
        "switch_optical_status": 120,
        "ap_mac": 160,
        "ap_name": 180,
        "ap_rx_power": 120,
        "ap_optical_status": 130,
        "ap_tx_power": 100,
        "updated_at": 170,
    }


def trackside_minimum_column_widths() -> dict[str, int]:
    return trackside_default_column_widths()


def normalize_trackside_mac(value: object) -> str:
    import re

    hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    return hex_text.casefold() if len(hex_text) == 12 else ""


class TracksideApServicePage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.device_repository = repository
        self.ac_repository = AcRepository(repository.database)
        self.fact_repository = DeviceFactRepository(repository.database)
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.settings = SettingsStore(paths)
        self.trackside_rows: list[dict[str, object | None]] = []
        self.trackside_page = 1
        self.trackside_page_size = DEFAULT_PAGE_SIZE
        self.collect_thread: TracksideOpticalCollectThread | None = None
        self.load_thread: TracksideApBusinessLoadThread | None = None
        self.is_loading = False
        self.load_generation = 0
        self.dirty = True
        self.has_loaded = False
        self.empty_reason = ""
        self.last_loaded_at: datetime | None = None
        self._table_widths_initialized = False
        self.detail_windows: list[QWidget] = []
        self.history_windows: list[QWidget] = []
        self.history_windows_by_key: dict[str, QWidget] = {}

        self.update_button = QPushButton()
        self.cancel_update_button = QPushButton()
        self.trackside_site_filter = QComboBox()
        self.trackside_search_input = QLineEdit()
        self.trackside_export_button = QPushButton()
        self.status_label = make_text_selectable(QLabel())
        self.trackside_table = QTableWidget()
        self.trackside_pagination = PaginationWidget(self.i18n)
        self.search_debounce_timer = QTimer(self)
        self.search_debounce_timer.setSingleShot(True)
        self.search_debounce_timer.setInterval(300)
        configure_readonly_table(self.trackside_table)
        self._configure_trackside_table()
        self.trackside_table.setColumnCount(len(TRACKSIDE_AP_BUSINESS_COLUMNS))
        set_table_column_fields(self.trackside_table, [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS])
        self.column_state = TableColumnState(self.settings, self.trackside_table, "rail_transit/trackside_ap/table_column_widths", trackside_default_column_widths(), trackside_minimum_column_widths())
        self.trackside_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trackside_table.customContextMenuRequested.connect(self.show_trackside_context_menu)
        self.trackside_table.itemDoubleClicked.connect(self.handle_trackside_double_click)

        actions = QHBoxLayout()
        actions.addWidget(self.update_button)
        actions.addWidget(self.cancel_update_button)
        actions.addWidget(self.trackside_export_button)
        actions.addWidget(self.trackside_site_filter)
        actions.addWidget(self.trackside_search_input)
        actions.addWidget(self.status_label, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(actions)
        layout.addWidget(self.trackside_table, 1)
        layout.addWidget(self.trackside_pagination)

        self.update_button.clicked.connect(self.start_optical_update)
        self.cancel_update_button.clicked.connect(self.cancel_optical_update)
        self.trackside_export_button.clicked.connect(self.export_trackside_table)
        self.trackside_site_filter.currentIndexChanged.connect(self.apply_trackside_filters)
        self.trackside_search_input.textChanged.connect(self.schedule_trackside_filter)
        self.search_debounce_timer.timeout.connect(self.apply_trackside_filters)
        self.trackside_pagination.pageChanged.connect(self.set_trackside_page)
        self.trackside_pagination.pageSizeChanged.connect(self.set_trackside_page_size)
        self.retranslate()
        self.column_state.restore()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.device_repository = repository
        self.ac_repository = AcRepository(repository.database)
        self.fact_repository = DeviceFactRepository(repository.database)
        self.site_name = site_name
        self.clear_cached_rows()
        if self.isVisible():
            self.refresh_async(force=True)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.clear_cached_rows()
        if self.isVisible():
            self.refresh_async(force=True)

    def retranslate(self) -> None:
        self.update_button.setText(self.i18n.t("trackside_ap.update"))
        self.update_button.setToolTip(self.i18n.t("trackside_ap.update_tooltip"))
        self.cancel_update_button.setText(self.i18n.t("trackside_ap.cancel_update"))
        self.trackside_export_button.setText(self.i18n.t("trackside.export"))
        self.trackside_search_input.setPlaceholderText(self.i18n.t("trackside.search"))
        self.trackside_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS])
        self.column_state.restore()
        self.trackside_pagination.retranslate()
        if self.is_loading:
            self.status_label.setText(self.i18n.t("trackside_ap.loading"))
        elif self.collect_thread is None:
            self._update_idle_status()
        self.cancel_update_button.setEnabled(self.collect_thread is not None)
        apply_table_style(self.trackside_table)
        self._configure_trackside_table()

    def refresh_all(self) -> None:
        self.refresh_async(force=True)

    def refresh_async(self, force: bool = False) -> None:
        if self.is_loading:
            self.status_label.setText(self.i18n.t("trackside_ap.loading"))
            return
        if self.has_loaded and not self.dirty and not force:
            self.apply_trackside_pagination()
            self._update_idle_status()
            return
        self.is_loading = True
        self.empty_reason = ""
        self.load_generation += 1
        generation = self.load_generation
        self.update_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("trackside_ap.loading"))
        detail = f"site={self.site_name}, generation={generation}"
        app_logger.log_info("TRACKSIDE_LOAD_STARTED", detail)
        thread = TracksideApBusinessLoadThread(self.device_repository, self.site_name, generation, self)
        self.load_thread = thread
        thread.load_finished.connect(self._finish_load)
        thread.load_failed.connect(self._fail_load)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_load_thread(thread))
        thread.start()

    def mark_dirty(self) -> None:
        self.dirty = True

    def clear_cached_rows(self) -> None:
        self.load_generation += 1
        self.is_loading = bool(self.load_thread is not None and self.load_thread.isRunning())
        self.trackside_rows = []
        self.trackside_page = 1
        self.dirty = True
        self.has_loaded = False
        self.empty_reason = ""
        self.last_loaded_at = None
        self._set_trackside_site_filter_items([])
        self.apply_trackside_pagination()

    def schedule_trackside_filter(self) -> None:
        self.search_debounce_timer.start()

    def _finish_load(self, result: TracksideApBusinessLoadResult) -> None:
        if result.generation != self.load_generation:
            app_logger.log_info(
                "TRACKSIDE_LOAD_DISCARDED",
                (
                    f"site={result.site_name}, generation={result.generation}, current_generation={self.load_generation}, "
                    f"dirty={self.dirty}, is_visible={self.isVisible()}, is_loading={self.is_loading}, "
                    f"has_loaded={self.has_loaded}, row_count={len(result.rows)}"
                ),
            )
            self.is_loading = False
            self.dirty = True
            if self.dirty and self.isVisible():
                QTimer.singleShot(0, lambda: self.refresh_async(force=True))
            return
        self.is_loading = False
        self.dirty = False
        self.has_loaded = True
        self.last_loaded_at = datetime.now()
        self.trackside_rows = result.rows
        self.empty_reason = result.empty_reason if not result.rows else ""
        self._set_trackside_site_filter_items(self.trackside_rows)
        render_start = perf_counter()
        self.apply_trackside_filters()
        render_ms = int((perf_counter() - render_start) * 1000)
        if self.collect_thread is None:
            self.update_button.setEnabled(True)
            self._update_idle_status()
        app_logger.log_info(
            "TRACKSIDE_LOAD_COMPLETED",
            (
                f"site={result.site_name}, generation={result.generation}, device_count={result.device_count}, "
                f"interface_count={result.interface_count}, candidate_ap_interface_count={result.candidate_ap_interface_count}, "
                f"optical_count={result.optical_count}, lldp_count={result.lldp_count}, "
                f"fit_ap_optical_count={result.fit_ap_optical_count}, fit_ap_resource_count={result.fit_ap_resource_count}, "
                f"row_count={result.row_count or len(result.rows)}, empty_reason={result.empty_reason}, "
                f"query_ms={result.query_ms}, build_ms={result.build_ms}, render_ms={render_ms}"
            ),
        )
        if not result.rows:
            app_logger.log_warning(
                "TRACKSIDE_LOAD_EMPTY",
                (
                    f"site={result.site_name}, device_count={result.device_count}, interface_count={result.interface_count}, "
                    f"candidate_ap_interface_count={result.candidate_ap_interface_count}, optical_count={result.optical_count}, "
                    f"lldp_count={result.lldp_count}, fit_ap_optical_count={result.fit_ap_optical_count}, "
                    f"fit_ap_resource_count={result.fit_ap_resource_count}, empty_reason={result.empty_reason}"
                ),
            )

    def _fail_load(self, generation: int, message: str) -> None:
        if generation != self.load_generation:
            app_logger.log_info(
                "TRACKSIDE_LOAD_DISCARDED",
                (
                    f"site={self.site_name}, generation={generation}, current_generation={self.load_generation}, "
                    f"dirty={self.dirty}, is_visible={self.isVisible()}, is_loading={self.is_loading}, has_loaded={self.has_loaded}"
                ),
            )
            self.is_loading = False
            self.dirty = True
            if self.dirty and self.isVisible():
                QTimer.singleShot(0, lambda: self.refresh_async(force=True))
            return
        self.is_loading = False
        self.dirty = True
        self.has_loaded = False
        self.empty_reason = "trackside.empty.load_failed"
        if self.collect_thread is None:
            self.update_button.setEnabled(True)
        self.status_label.setText(f"{self.i18n.t('trackside_ap.load_failed')}: {message}" if message else self.i18n.t("trackside_ap.load_failed"))
        app_logger.log_error("TRACKSIDE_LOAD_FAILED", f"site={self.site_name}, generation={generation}, error={message}")

    def _clear_load_thread(self, thread: TracksideApBusinessLoadThread) -> None:
        if self.load_thread is thread:
            self.load_thread = None

    def start_optical_update(self) -> None:
        if self.collect_thread is not None or self.is_loading:
            return
        self.update_button.setEnabled(False)
        self.cancel_update_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("trackside_ap.collecting_progress", done=0, total=0))
        self.collect_thread = TracksideOpticalCollectThread(
            self.device_repository,
            self.site_name,
            self.paths,
            self.trackside_rows,
            DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
            self,
        )
        self.collect_thread.progress_changed.connect(self._update_progress)
        self.collect_thread.collect_finished.connect(self._finish_collect)
        self.collect_thread.collect_failed.connect(self._fail_collect)
        self.collect_thread.finished.connect(self.collect_thread.deleteLater)
        self.collect_thread.finished.connect(lambda: setattr(self, "collect_thread", None))
        self.collect_thread.start()

    def cancel_optical_update(self) -> None:
        if self.collect_thread is not None:
            self.collect_thread.cancel()
            self.cancel_update_button.setEnabled(False)

    def _update_progress(self, done: int, total: int) -> None:
        self.status_label.setText(self.i18n.t("trackside_ap.collecting_progress", done=done, total=total))

    def _finish_collect(self, result) -> None:
        self.cancel_update_button.setEnabled(False)
        self.status_label.setText(
            self.i18n.t(
                "trackside_ap.collection_summary",
                success=result.success_count,
                failed=result.failed_count,
                skipped=result.skipped_count,
            )
        )
        self.mark_dirty()
        self.refresh_async(force=True)

    def _fail_collect(self, message: str) -> None:
        self.update_button.setEnabled(True)
        self.cancel_update_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("trackside_ap.collection_failed"))
        QMessageBox.warning(self, self.i18n.t("rail_transit.trackside_ap_service"), message)

    def current_trackside_filters(self) -> dict[str, object | None]:
        return {"site": self.trackside_site_filter.currentData(), "search": self.trackside_search_input.text()}

    def filtered_trackside_rows(self) -> list[dict[str, object | None]]:
        filters = self.current_trackside_filters()
        return filter_trackside_ap_business_rows(self.trackside_rows, filters.get("site"), filters.get("search"))

    def current_trackside_page_rows(self) -> list[dict[str, object | None]]:
        rows, _state = paginate_rows(self.filtered_trackside_rows(), self.trackside_page_size, self.trackside_page)
        return rows

    def apply_trackside_filters(self) -> None:
        self.trackside_page = 1
        self.apply_trackside_pagination()

    def apply_trackside_pagination(self) -> None:
        rows, state = paginate_rows(self.filtered_trackside_rows(), self.trackside_page_size, self.trackside_page)
        self.trackside_page = state.current_page
        self.trackside_pagination.set_state(state)
        self._set_rows(rows)

    def set_trackside_page(self, page: int) -> None:
        self.trackside_page = page
        self.apply_trackside_pagination()

    def set_trackside_page_size(self, page_size: int) -> None:
        self.trackside_page_size = page_size
        self.trackside_page = 1
        self.apply_trackside_pagination()

    def export_trackside_table(self) -> None:
        path = select_export_path(self, self.i18n.t("trackside.export"), trackside_export_default_filename(self.site_name), EXCEL_FILTER)
        if not path:
            return
        export_trackside_ap_business_xlsx(
            path,
            self.filtered_trackside_rows(),
            TRACKSIDE_AP_BUSINESS_COLUMNS,
            [self.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
            self.ap_online_overview_rows(),
            AP_ONLINE_OVERVIEW_COLUMNS,
            [self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        )
        remember_export_path(path)

    def handle_trackside_double_click(self, item: QTableWidgetItem) -> None:
        fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]
        if item.column() < 0 or item.column() >= len(fields):
            return
        field = fields[item.column()]
        if field == "interface_name":
            self.open_interface_history_from_trackside(item.row())
        elif field in {"ap_name", "ap_mac"}:
            self.open_ap_detail_from_trackside(item.row())

    def open_interface_history_from_trackside(self, row: int) -> None:
        rows = self.current_trackside_page_rows()
        if row < 0 or row >= len(rows):
            return
        current_row = rows[row]
        device_uuid = str(current_row.get("device_uuid") or "")
        interface_name = str(current_row.get("interface_name") or "")
        device_name = str(current_row.get("device_name") or "")
        if not device_uuid or not interface_name:
            QMessageBox.information(self, self.i18n.t("trackside_ap.interface_history"), self.i18n.t("trackside_ap.no_interface_history"))
            return
        window_key = self._interface_history_window_key(current_row)
        existing = self.history_windows_by_key.get(window_key)
        if existing is not None and existing.isVisible():
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        service = TracksideOpticalHistoryService(self.device_repository)
        history_rows = service.query_interface_history_all(device_uuid, interface_name)
        title = self.i18n.t("trackside_ap.interface_history_title", device=device_name, interface=interface_name)
        dialog = TracksideInterfaceHistoryDialog(self.i18n, history_rows, title, self.settings)
        self.history_windows.append(dialog)
        self.history_windows_by_key[window_key] = dialog
        dialog.destroyed.connect(lambda _=None, window=dialog, key=window_key: self._forget_history_window(window, key))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_trackside_context_menu(self, position) -> None:
        index = self.trackside_table.indexAt(position)
        menu = self.build_trackside_context_menu(index.row(), index.column())
        menu.exec(self.trackside_table.viewport().mapToGlobal(position))

    def build_trackside_context_menu(self, row: int, column: int) -> QMenu:
        menu = create_table_context_menu(self.trackside_table, row, column, self.i18n.language, include_history=False)
        first_action = menu.actions()[0] if menu.actions() else None
        device_detail = QAction(self.i18n.t("trackside.view_device_detail"), menu)
        ap_detail = QAction(self.i18n.t("trackside.view_ap_detail"), menu)
        device_detail.setEnabled(row >= 0)
        ap_detail.setEnabled(row >= 0)
        device_detail.triggered.connect(lambda: self.open_device_detail_from_trackside(row))
        ap_detail.triggered.connect(lambda: self.open_ap_detail_from_trackside(row))
        if first_action:
            menu.insertAction(first_action, device_detail)
            menu.insertAction(first_action, ap_detail)
            menu.insertSeparator(first_action)
        else:
            menu.addAction(device_detail)
            menu.addAction(ap_detail)
        return menu

    def open_device_detail_from_trackside(self, row: int) -> None:
        rows = self.current_trackside_page_rows()
        if row < 0 or row >= len(rows):
            return
        device_uuid = str(rows[row].get("device_uuid") or "")
        device = next((item for item in self.device_repository.list() if item.device_uuid == device_uuid), None)
        if device is None:
            return
        dialog = DeviceDetailDialog(self.i18n, self.fact_repository, device, self, self.site_name)
        self.detail_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_ap_detail_from_trackside(self, row: int) -> None:
        rows = self.current_trackside_page_rows()
        if row < 0 or row >= len(rows):
            return
        current_row = rows[row]
        match = self._resolve_ap_detail_match(current_row)
        if match is None:
            QMessageBox.information(self, self.i18n.t("trackside_ap.open_ap_detail"), self.i18n.t("trackside_ap.no_ap_detail"))
            return
        dialog = FitApDetailDialog(self.i18n, self.ac_repository, str(match.get("ac_device_uuid") or ""), str(match.get("ap_uuid") or match.get("ap_name") or ""))
        self.detail_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _resolve_ap_detail_match(self, row: dict[str, object | None]) -> dict[str, object | None] | None:
        if row.get("ac_device_uuid") and row.get("ap_uuid"):
            return {"ac_device_uuid": row.get("ac_device_uuid"), "ap_uuid": row.get("ap_uuid"), "ap_name": row.get("ap_name")}
        resources = self.ac_repository.list_all_fit_ap_resources_with_metadata()
        ap_mac = normalize_trackside_mac(row.get("ap_mac"))
        ap_name = str(row.get("ap_name") or "").strip()
        matches: list[dict[str, object | None]] = []
        if ap_mac:
            matches = [item for item in resources if normalize_trackside_mac(item.get("ap_mac")) == ap_mac]
        if not matches and ap_name:
            matches = [item for item in resources if str(item.get("ap_name") or "").strip().casefold() == ap_name.casefold()]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        labels = [f"{item.get('ap_name') or '-'} | {item.get('ap_mac') or '-'} | {item.get('ap_ip') or '-'}" for item in matches]
        selected, accepted = QInputDialog.getItem(self, self.i18n.t("trackside_ap.open_ap_detail"), self.i18n.t("trackside_ap.open_ap_detail"), labels, 0, False)
        if not accepted:
            return None
        return matches[labels.index(selected)]

    def _forget_detail_window(self, window: QWidget) -> None:
        self.detail_windows = [item for item in self.detail_windows if item is not window]

    def _forget_history_window(self, window: QWidget, key: str | None = None) -> None:
        self.history_windows = [item for item in self.history_windows if item is not window]
        if key is not None and self.history_windows_by_key.get(key) is window:
            self.history_windows_by_key.pop(key, None)

    def _interface_history_window_key(self, row: dict[str, object | None]) -> str:
        device_key = str(row.get("source_device_id") or row.get("device_uuid") or row.get("source_device") or row.get("device_name") or "")
        return f"{device_key}::{row.get('interface_name') or ''}"

    def _set_trackside_site_filter_items(self, rows: list[dict[str, object | None]]) -> None:
        current = self.trackside_site_filter.currentData()
        self.trackside_site_filter.blockSignals(True)
        self.trackside_site_filter.clear()
        for label, value in build_trackside_site_filter_items(rows, self.i18n.t("field.all")):
            self.trackside_site_filter.addItem(label, value)
        index = self.trackside_site_filter.findData(current)
        self.trackside_site_filter.setCurrentIndex(index if index >= 0 else 0)
        self.trackside_site_filter.blockSignals(False)

    def _set_rows(self, rows: list[dict[str, object | None]]) -> None:
        render_start = perf_counter()
        was_sorting_enabled = self.trackside_table.isSortingEnabled()
        self.trackside_table.setSortingEnabled(False)
        self.trackside_table.blockSignals(True)
        self.trackside_table.setUpdatesEnabled(False)
        try:
            self.trackside_table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, (_key, field) in enumerate(TRACKSIDE_AP_BUSINESS_COLUMNS):
                    value = format_trackside_display_value(field, row, self.i18n.language)
                    item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setToolTip(str(value) if value not in (None, "") else "")
                    apply_status_item_contrast(item, trackside_row_status(row))
                    self.trackside_table.setItem(row_index, column_index, item)
        finally:
            self.trackside_table.blockSignals(False)
            self.trackside_table.setUpdatesEnabled(True)
            self.trackside_table.setSortingEnabled(was_sorting_enabled)
        if not self._table_widths_initialized:
            self.column_state.restore()
            self._table_widths_initialized = True
        render_ms = int((perf_counter() - render_start) * 1000)
        app_logger.log_info("TRACKSIDE_RENDER_COMPLETED", f"site={self.site_name}, row_count={len(rows)}, render_ms={render_ms}")

    def _update_idle_status(self) -> None:
        if self.is_loading:
            self.status_label.setText(self.i18n.t("trackside_ap.loading"))
            return
        if self.trackside_rows:
            online, offline = self.ap_online_overview_counts()
            self.status_label.setText(self.i18n.t("trackside.loaded_count_with_ap_status", count=len(self.trackside_rows), online=online, offline=offline))
            return
        if self.has_loaded:
            reason_key = self.empty_reason or "trackside.empty.no_rows"
            self.status_label.setText(f"{self.i18n.t('trackside.empty.title')} {self.i18n.t(reason_key)}")
            return
        self.status_label.setText(self.i18n.t("trackside_ap.not_collected"))

    def _configure_trackside_table(self) -> None:
        self.trackside_table.setWordWrap(False)
        self.trackside_table.setTextElideMode(Qt.ElideRight)
        self.trackside_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.trackside_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.trackside_table.setProperty("netconsole_manual_column_widths", True)
        header = self.trackside_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)

    def ap_online_overview_rows(self) -> list[dict[str, object | None]]:
        capacity_details = self.ac_repository.list_active_trackside_plan_capacity_details()
        if not capacity_details:
            capacity_details = self.ac_repository.list_station_ap_capacity_details()
        return ApOnlineOverviewService.build_rows(
            metadata_rows=self.ac_repository.list_fit_ap_metadata(),
            fit_ap_resources=self.ac_repository.list_all_fit_ap_resources_with_metadata(),
            optical_rows=self.ac_repository.list_all_fit_ap_optical(),
            capacity_details=capacity_details,
        )

    def ap_online_overview_counts(self) -> tuple[int, int]:
        overview_rows = self.ap_online_overview_rows()
        total_row = next((row for row in overview_rows if str(row.get("site") or "") == "合计"), overview_rows[-1] if overview_rows else {})
        return int(total_row.get("online") or 0), int(total_row.get("offline") or 0)


def trackside_export_default_filename(site_name: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_site = re.sub(r'[\\/:*?"<>|]+', "_", str(site_name or "").strip()) or "site"
    return f"{safe_site}_\u8f68\u65c1AP\u4e1a\u52a1_{timestamp}.xlsx"
