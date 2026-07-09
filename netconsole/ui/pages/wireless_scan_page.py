from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.wireless_scan_models import WirelessAdapter
from netconsole.repositories.wireless_scan_repository import WirelessScanRepository
from netconsole.services.export.export_task_builders import repository_query_source, table_csv_source_spec, table_xlsx_source_spec
from netconsole.services.network_tools.wireless_channel_analyzer import rssi_level
from netconsole.services.network_tools.wireless_scan_service import (
    WIRELESS_SCAN_EXPORT_COLUMNS,
    WIRELESS_SCAN_DISPLAY_COLUMNS,
    result_to_row,
    wireless_scanner_external_path,
)
from netconsole.ui.dialogs.wireless_scan_detail_dialog import WirelessScanDetailDialog
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_column_state import TableColumnState
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.wireless_scan_worker import WirelessAdapterLoadWorker, WirelessScanWorker


WIRELESS_SCAN_TAB_KEYS = ("results", "history", "raw")


class WirelessScanPage(QWidget):
    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.settings = SettingsStore(paths)
        self.adapters: list[WirelessAdapter] = []
        self.current_rows: list[dict[str, object]] = []
        self.filtered_rows: list[dict[str, object]] = []
        self.current_scan_id = ""
        self.raw_output = ""
        self.adapter_worker: WirelessAdapterLoadWorker | None = None
        self.scan_worker: WirelessScanWorker | None = None
        self.detail_windows: list[WirelessScanDetailDialog] = []
        self._restoring_settings = False
        self.sort_column: int | None = None
        self.sort_order = Qt.AscendingOrder

        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.adapter_combo = QComboBox()
        self.scan_source_combo = QComboBox()
        self.start_button = QPushButton()
        self.stop_button = QPushButton()
        self.auto_refresh_check = QCheckBox()
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(3, 3600)
        self.interval_spin.setValue(5)
        self.only_trackside_check = QCheckBox()
        self.band_filter = QComboBox()
        self.radio_filter = QComboBox()
        self.search_edit = QLineEdit()
        self.export_button = QPushButton()
        self.external_button = QPushButton()
        self.status_label = QLabel()
        self.summary_label = QLabel()
        self.tabs = QTabWidget()
        self.result_table = QTableWidget(0, len(WIRELESS_SCAN_DISPLAY_COLUMNS))
        self.history_table = QTableWidget(0, 7)
        self.raw_text = QTextEdit()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(5000)
        self.refresh_timer.timeout.connect(self.start_scan)
        self.settings_timer = QTimer(self)
        self.settings_timer.setSingleShot(True)
        self.settings_timer.setInterval(300)
        self.settings_timer.timeout.connect(self.save_settings)
        self.raw_text.setReadOnly(True)
        configure_readonly_table(self.result_table)
        configure_readonly_table(self.history_table)
        self.result_table.setSortingEnabled(False)
        self.result_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_table.setWordWrap(False)
        self.result_table.setTextElideMode(Qt.ElideRight)
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._handle_header_sort)
        set_table_column_fields(self.result_table, [field for _key, field in WIRELESS_SCAN_DISPLAY_COLUMNS])
        self.column_state = TableColumnState(
            self.settings,
            self.result_table,
            "network_tools/wireless_scan/table_column_widths",
            wireless_scan_default_column_widths(),
            wireless_scan_minimum_column_widths(),
        )
        self._build_ui()
        self._connect()
        self.retranslate()
        self.restore_settings()
        self.column_state.restore()
        self.load_adapters()
        self.refresh_history()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.current_rows = []
        self.current_scan_id = ""
        self.apply_filters()
        self.refresh_history()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self.description_label)
        toolbar = QHBoxLayout()
        for widget in (
            QLabel(self.i18n.t("wireless_scan.adapter")),
            self.adapter_combo,
            QLabel(self.i18n.t("wireless_scan.scan_source")),
            self.scan_source_combo,
            self.start_button,
            self.stop_button,
            self.auto_refresh_check,
            self.interval_spin,
            self.only_trackside_check,
            self.band_filter,
            self.radio_filter,
            self.search_edit,
            self.export_button,
            self.external_button,
        ):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        root.addLayout(toolbar)
        root.addWidget(self.summary_label)
        root.addWidget(self.status_label)
        self.tabs.addTab(self.result_table, "")
        self.tabs.addTab(self.history_table, "")
        self.tabs.addTab(self.raw_text, "")
        root.addWidget(self.tabs, 1)

    def _connect(self) -> None:
        self.start_button.clicked.connect(self.start_scan)
        self.stop_button.clicked.connect(self.stop_scan)
        self.auto_refresh_check.toggled.connect(self._toggle_auto_refresh)
        self.interval_spin.valueChanged.connect(lambda value: self.refresh_timer.setInterval(int(value) * 1000))
        self.only_trackside_check.toggled.connect(self.apply_filters)
        self.band_filter.currentIndexChanged.connect(self.apply_filters)
        self.radio_filter.currentIndexChanged.connect(self.apply_filters)
        self.search_edit.textChanged.connect(self.apply_filters)
        self.adapter_combo.currentIndexChanged.connect(self._schedule_save_settings)
        self.scan_source_combo.currentIndexChanged.connect(self._schedule_save_settings)
        self.auto_refresh_check.toggled.connect(self._schedule_save_settings)
        self.interval_spin.valueChanged.connect(self._schedule_save_settings)
        self.only_trackside_check.toggled.connect(self._schedule_save_settings)
        self.band_filter.currentIndexChanged.connect(self._schedule_save_settings)
        self.radio_filter.currentIndexChanged.connect(self._schedule_save_settings)
        self.tabs.currentChanged.connect(self._schedule_save_settings)
        self.export_button.clicked.connect(self.export_current)
        self.external_button.clicked.connect(self.open_external)
        self.result_table.itemDoubleClicked.connect(self.open_detail)

    def retranslate(self) -> None:
        self.description_label.setText(self.i18n.t("wireless_scan.description"))
        self.start_button.setText(self.i18n.t("wireless_scan.start_scan"))
        self.stop_button.setText(self.i18n.t("wireless_scan.stop_scan"))
        self.auto_refresh_check.setText(self.i18n.t("wireless_scan.auto_refresh"))
        self.only_trackside_check.setText(self.i18n.t("wireless_scan.only_trackside"))
        self.export_button.setText(self.i18n.t("wireless_scan.export"))
        self.external_button.setText(self.i18n.t("wireless_scan.open_external"))
        self._apply_button_icons()
        self.search_edit.setPlaceholderText(self.i18n.t("wireless_scan.search_placeholder"))
        current_scan_source = self.scan_source_combo.currentData() or "auto"
        self.scan_source_combo.clear()
        self.scan_source_combo.addItem(self.i18n.t("wireless_scan.scan_source_auto"), "auto")
        self.scan_source_combo.addItem(self.i18n.t("wireless_scan.scan_source_hybrid"), "hybrid")
        self.scan_source_combo.addItem(self.i18n.t("wireless_scan.scan_source_wlan_api"), "wlan_api")
        self.scan_source_combo.addItem(self.i18n.t("wireless_scan.scan_source_netsh"), "netsh")
        _set_combo_data(self.scan_source_combo, current_scan_source)
        self.band_filter.clear()
        for label, data in ((self.i18n.t("wireless_scan.all_bands"), ""), ("2.4G", "2.4G"), ("5G", "5G"), ("6G", "6G")):
            self.band_filter.addItem(label, data)
        self.radio_filter.clear()
        self.radio_filter.addItem(self.i18n.t("wireless_scan.all_radios"), "")
        for radio in (1, 2, 3):
            self.radio_filter.addItem(str(radio), radio)
        self.result_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in WIRELESS_SCAN_DISPLAY_COLUMNS])
        self.result_table.setToolTip(self.i18n.t("wireless_scan.rssi_tooltip"))
        self.column_state.restore()
        self.history_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("wireless_scan.scan_time"),
                self.i18n.t("wireless_scan.adapter"),
                self.i18n.t("wireless_scan.network_count"),
                "2.4G",
                "5G",
                self.i18n.t("wireless_scan.strongest_trackside"),
                self.i18n.t("wireless_scan.strongest_rssi"),
            ]
        )
        self.tabs.setTabText(0, self.i18n.t("wireless_scan.scan_results"))
        self.tabs.setTabText(1, self.i18n.t("wireless_scan.scan_history"))
        self.tabs.setTabText(2, self.i18n.t("wireless_scan.raw_output"))
        self._refresh_external_button()

    def _apply_button_icons(self) -> None:
        for button, icon_name in (
            (self.start_button, "PLAY"),
            (self.stop_button, "CANCEL"),
            (self.export_button, "SHARE"),
            (self.external_button, "FOLDER"),
        ):
            apply_button_icon(button, icon_name)

    def load_adapters(self) -> None:
        if self.adapter_worker and self.adapter_worker.isRunning():
            return
        self.adapter_worker = WirelessAdapterLoadWorker(self.site_name, self.paths, self)
        self.adapter_worker.completed.connect(self._adapters_loaded)
        self.adapter_worker.failed.connect(self._adapters_failed)
        self.adapter_worker.finished.connect(lambda: setattr(self, "adapter_worker", None))
        self.adapter_worker.start()

    def start_scan(self) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            self.status_label.setText(self.i18n.t("wireless_scan.scan_running"))
            return
        adapter = self.adapter_combo.currentData()
        adapter = adapter if isinstance(adapter, WirelessAdapter) else None
        self.start_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("wireless_scan.scanning"))
        self.scan_worker = WirelessScanWorker(self.site_name, self.paths, adapter, str(self.scan_source_combo.currentData() or "auto"), self)
        self.scan_worker.completed.connect(self._scan_completed)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(lambda: setattr(self, "scan_worker", None))
        self.scan_worker.start()

    def stop_scan(self) -> None:
        self.refresh_timer.stop()
        self.auto_refresh_check.setChecked(False)
        self.status_label.setText(self.i18n.t("wireless_scan.stopped"))

    def apply_filters(self) -> None:
        rows = list(self.current_rows)
        if self.only_trackside_check.isChecked():
            rows = [row for row in rows if row.get("matched_trackside_ap")]
        band = self.band_filter.currentData()
        if band:
            rows = [row for row in rows if row.get("band") == band]
        radio = self.radio_filter.currentData()
        if radio:
            rows = [row for row in rows if row.get("matched_radio_id") == radio]
        search = self.search_edit.text().strip().casefold()
        if search:
            fields = ("display_ssid", "display_mac_address", "display_ap_mac", "display_ap_name", "display_station", "display_section", "display_belong_type", "display_location_mileage")
            rows = [row for row in rows if any(search in str(row.get(field) or "").casefold() for field in fields)]
        rows = self._sort_rows(rows)
        self.filtered_rows = rows
        self._render_results(rows)

    def export_current(self) -> None:
        if not self.current_rows or not self.current_scan_id:
            MessageBox.information(self, self.i18n.t("network_tools.wireless_scan"), self.i18n.t("wireless_scan.no_results"))
            return
        export_dir = self.paths.wireless_scan_export_dir(self.site_name)
        export_dir.mkdir(parents=True, exist_ok=True)
        default = export_dir / f"wireless_trackside_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path, selected_filter = QFileDialog.getSaveFileName(self, self.i18n.t("wireless_scan.export"), str(default), "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        headers = [self.i18n.t(key) for key, _field in WIRELESS_SCAN_EXPORT_COLUMNS]
        columns = [
            {"key": field, "title": headers[index], "text": True}
            for index, (_key, field) in enumerate(WIRELESS_SCAN_EXPORT_COLUMNS)
        ]
        source = repository_query_source(
            db_path=self.paths.wireless_scan_db_path(self.site_name),
            repository="wireless_scan_repository",
            method="list_results",
            filters={"scan_id": self.current_scan_id},
        )
        if selected_filter.startswith("CSV") or path.lower().endswith(".csv"):
            spec = table_csv_source_spec(Path(path), columns=columns, source=source, title=self.i18n.t("wireless_scan.export"), open_dir_on_success=True)
        else:
            spec = table_xlsx_source_spec(
                Path(path),
                columns=columns,
                source=source,
                headers=headers,
                sheet_name="Wireless Scan",
                title=self.i18n.t("wireless_scan.export"),
                open_dir_on_success=True,
            )
        submit_export_task(self, spec, success_title=self.i18n.t("wireless_scan.export"), paths=self.paths)

    def open_external(self) -> None:
        configured_path = str(self.settings.get_value("network_tools/wireless_scan/external_path", "") or "")
        path = wireless_scanner_external_path(self.paths, configured_path)
        if path is None:
            MessageBox.information(self, self.i18n.t("wireless_scan.open_external"), self.i18n.t("wireless_scan.external_missing"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_detail(self, item: QTableWidgetItem) -> None:
        row = item.data(Qt.UserRole)
        if not isinstance(row, dict):
            return
        dialog = WirelessScanDetailDialog(self.i18n, row, self)
        dialog.destroyed.connect(lambda _=None, d=dialog: self.detail_windows.remove(d) if d in self.detail_windows else None)
        self.detail_windows.append(dialog)
        dialog.show()

    def refresh_history(self) -> None:
        repo = WirelessScanRepository(self.paths.wireless_scan_db_path(self.site_name))
        runs = repo.list_runs()
        self.history_table.setRowCount(len(runs))
        for index, run in enumerate(runs):
            results = repo.list_results(str(run.get("scan_id") or ""))
            strongest = max([row for row in results if row.get("matched_trackside_ap")], key=lambda row: row.get("rssi_dbm") or -999, default={})
            values = [
                run.get("started_at"),
                run.get("adapter_name"),
                run.get("network_count"),
                len([row for row in results if row.get("band") == "2.4G"]),
                len([row for row in results if row.get("band") == "5G"]),
                strongest.get("matched_ap_name") or "-",
                strongest.get("rssi_dbm") or "-",
            ]
            _set_row(self.history_table, index, values, run)

    def _adapters_loaded(self, adapters: list[WirelessAdapter]) -> None:
        self.adapters = adapters
        self.adapter_combo.clear()
        if not adapters:
            self.adapter_combo.addItem(self.i18n.t("wireless_scan.no_adapter"), None)
            self.start_button.setEnabled(False)
            self.status_label.setText(self.i18n.t("wireless_scan.adapter_unavailable"))
            return
        for adapter in adapters:
            self.adapter_combo.addItem(adapter.display_name, adapter)
        saved_adapter = str(self.settings.get_value("network_tools/wireless_scan/adapter_guid", "") or "")
        if saved_adapter:
            for index, adapter in enumerate(adapters):
                if saved_adapter in {adapter.guid, adapter.name}:
                    self.adapter_combo.setCurrentIndex(index)
                    break
        self.start_button.setEnabled(True)

    def _adapters_failed(self, error: str) -> None:
        self.adapter_combo.clear()
        self.adapter_combo.addItem(self.i18n.t("wireless_scan.no_adapter"), None)
        self.start_button.setEnabled(False)
        self.status_label.setText(error or self.i18n.t("wireless_scan.adapter_unavailable"))

    def _scan_completed(self, result) -> None:
        self.start_button.setEnabled(bool(self.adapters))
        self.raw_output = result.raw_file.read_text(encoding="utf-8") if result.raw_file.exists() else ""
        self.current_scan_id = result.scan_id
        self.current_rows = [result_to_row(item) for item in result.results]
        self.raw_text.setPlainText(self._raw_output_with_debug())
        self.apply_filters()
        self.refresh_history()
        matched = len([row for row in self.current_rows if row.get("matched_trackside_ap")])
        actual_source = _actual_scan_source(self.current_rows)
        source_text = _scan_source_text(self.i18n, actual_source)
        message = self.i18n.t("wireless_scan.scan_done", count=len(self.current_rows), matched=matched)
        if actual_source == "netsh":
            message = f"{message}  {self.i18n.t('wireless_scan.current_scan_source', source=source_text)}，{self.i18n.t('wireless_scan.wlan_api_failed_width_mimo_unavailable')}"
        elif actual_source == "wlan_api":
            message = f"{message}  {self.i18n.t('wireless_scan.current_scan_source', source=source_text)}，{self.i18n.t('wireless_scan.netsh_failed_security_unavailable')}"
        elif actual_source:
            message = f"{message}  {self.i18n.t('wireless_scan.current_scan_source', source=source_text)}"
        self.status_label.setText(message)

    def _scan_failed(self, error: str) -> None:
        self.start_button.setEnabled(bool(self.adapters))
        self.status_label.setText(error or self.i18n.t("wireless_scan.scan_failed"))
        MessageBox.warning(self, self.i18n.t("network_tools.wireless_scan"), self.status_label.text())

    def _render_results(self, rows: list[dict[str, object]]) -> None:
        self.result_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [_localized_display_value(self.i18n, field, row.get(field), row) for _key, field in WIRELESS_SCAN_DISPLAY_COLUMNS]
            _set_row(self.result_table, row_index, values, row)
            rssi_item = self.result_table.item(row_index, 7)
            if rssi_item:
                rssi_item.setForeground(_rssi_color(row.get("rssi_dbm")))
            mimo_item = self.result_table.item(row_index, 13)
            if mimo_item:
                mimo_item.setToolTip(_mimo_tooltip(self.i18n, row))
            width_item = self.result_table.item(row_index, 12)
            if width_item:
                width_item.setToolTip(_channel_width_tooltip(self.i18n, row))
        matched = len([row for row in rows if row.get("matched_trackside_ap")])
        unmatched = len([row for row in rows if row.get("match_status") == "unmatched"])
        radios = {radio: len([row for row in rows if row.get("matched_radio_id") == radio]) for radio in (1, 2, 3)}
        strongest = max([row for row in rows if row.get("matched_trackside_ap")], key=lambda row: row.get("rssi_dbm") or -999, default={})
        self.summary_label.setText(
            self.i18n.t(
                "wireless_scan.summary",
                total=len(rows),
                matched=matched,
                unmatched=unmatched,
                strongest=strongest.get("matched_ap_name") or "-",
                radio1=radios[1],
                radio2=radios[2],
                radio3=radios[3],
                band24=len([row for row in rows if row.get("band") == "2.4G"]),
                band5=len([row for row in rows if row.get("band") == "5G"]),
            )
        )

    def _toggle_auto_refresh(self, checked: bool) -> None:
        if checked:
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

    def _refresh_external_button(self) -> None:
        configured_path = str(self.settings.get_value("network_tools/wireless_scan/external_path", "") or "")
        self.external_button.setEnabled(wireless_scanner_external_path(self.paths, configured_path) is not None)

    def _handle_header_sort(self, column: int) -> None:
        if column < 0 or column >= len(WIRELESS_SCAN_DISPLAY_COLUMNS):
            return
        if self.sort_column == column:
            self.sort_order = Qt.DescendingOrder if self.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self.sort_column = column
            self.sort_order = Qt.AscendingOrder
        self.result_table.horizontalHeader().setSortIndicatorShown(True)
        self.result_table.horizontalHeader().setSortIndicator(column, self.sort_order)
        self._schedule_save_settings()
        self.apply_filters()

    def _sort_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        if self.sort_column is None or self.sort_column >= len(WIRELESS_SCAN_DISPLAY_COLUMNS):
            return sorted(rows, key=_wireless_scan_sort_key)
        _key, field = WIRELESS_SCAN_DISPLAY_COLUMNS[self.sort_column]
        present = [row for row in rows if _sort_value(field, row) is not None]
        missing = [row for row in rows if _sort_value(field, row) is None]
        present.sort(key=lambda row: _sort_value(field, row), reverse=self.sort_order == Qt.DescendingOrder)
        return present + missing

    def restore_settings(self) -> None:
        self._restoring_settings = True
        try:
            self.auto_refresh_check.setChecked(bool(self.settings.get_value("network_tools/wireless_scan/auto_refresh_enabled", False)))
            _set_combo_data(self.scan_source_combo, self.settings.get_value("network_tools/wireless_scan/scan_source", "auto"))
            self.interval_spin.setValue(_int_setting(self.settings, "network_tools/wireless_scan/refresh_interval", 5, 3, 3600))
            self.only_trackside_check.setChecked(bool(self.settings.get_value("network_tools/wireless_scan/trackside_only", False)))
            _set_combo_data(self.band_filter, self.settings.get_value("network_tools/wireless_scan/band_filter", ""))
            _set_combo_data(self.radio_filter, self.settings.get_value("network_tools/wireless_scan/radio_filter", ""))
            self._restore_current_tab()
            sort_column = _int_setting(self.settings, "network_tools/wireless_scan/sort_column", -1, -1, len(WIRELESS_SCAN_DISPLAY_COLUMNS) - 1)
            self.sort_column = sort_column if sort_column >= 0 else None
            order = str(self.settings.get_value("network_tools/wireless_scan/sort_order", "asc") or "asc")
            self.sort_order = Qt.DescendingOrder if order == "desc" else Qt.AscendingOrder
            if self.sort_column is not None:
                self.result_table.horizontalHeader().setSortIndicatorShown(True)
                self.result_table.horizontalHeader().setSortIndicator(self.sort_column, self.sort_order)
        finally:
            self._restoring_settings = False
        self._toggle_auto_refresh(self.auto_refresh_check.isChecked())

    def save_settings(self) -> None:
        adapter = self.adapter_combo.currentData()
        adapter_id = ""
        if isinstance(adapter, WirelessAdapter):
            adapter_id = adapter.guid or adapter.name
        self.settings.values.update(
            {
                "network_tools/wireless_scan/adapter_guid": adapter_id,
                "network_tools/wireless_scan/scan_source": self.scan_source_combo.currentData() or "auto",
                "network_tools/wireless_scan/auto_refresh_enabled": self.auto_refresh_check.isChecked(),
                "network_tools/wireless_scan/refresh_interval": self.interval_spin.value(),
                "network_tools/wireless_scan/trackside_only": self.only_trackside_check.isChecked(),
                "network_tools/wireless_scan/band_filter": self.band_filter.currentData() or "",
                "network_tools/wireless_scan/radio_filter": self.radio_filter.currentData() or "",
                "network_tools/wireless_scan/current_tab_key": self._current_tab_key(),
                "network_tools/wireless_scan/sort_column": self.sort_column if self.sort_column is not None else -1,
                "network_tools/wireless_scan/sort_order": "desc" if self.sort_order == Qt.DescendingOrder else "asc",
                "network_tools/wireless_scan/external_path": str(self.settings.get_value("network_tools/wireless_scan/external_path", "") or ""),
            }
        )
        self.settings.save()

    def _schedule_save_settings(self, *_args: object) -> None:
        if not self._restoring_settings:
            self.settings_timer.start()

    def _current_tab_key(self) -> str:
        index = self.tabs.currentIndex()
        if 0 <= index < len(WIRELESS_SCAN_TAB_KEYS):
            return WIRELESS_SCAN_TAB_KEYS[index]
        return WIRELESS_SCAN_TAB_KEYS[0]

    def _restore_current_tab(self) -> None:
        tab_key = str(self.settings.get_value("network_tools/wireless_scan/current_tab_key", "") or "")
        if tab_key in WIRELESS_SCAN_TAB_KEYS:
            self.tabs.setCurrentIndex(WIRELESS_SCAN_TAB_KEYS.index(tab_key))
            return
        self.tabs.setCurrentIndex(0)

    def _raw_output_with_debug(self) -> str:
        if _actual_scan_source(self.current_rows) != "wlan_api":
            return self.raw_output
        lines = [self.raw_output.strip(), "", "Windows WLAN API IE summary:"]
        for row in self.current_rows:
            lines.append(
                "BSSID={bssid} scan_source={scan_source} frequency={frequency} channel={channel} "
                "channel_width={width} channel_width_source={width_source} mimo={mimo} "
                "mimo_source={mimo_source} ie_blob_size={ie_size} parse_warnings={warnings}".format(
                    bssid=row.get("display_mac_address") or row.get("bssid") or "-",
                    scan_source=row.get("scan_source") or "-",
                    frequency=row.get("frequency_mhz") or "-",
                    channel=row.get("channel") or "-",
                    width=row.get("display_channel_width") or "-",
                    width_source=row.get("channel_width_source") or "unavailable",
                    mimo=row.get("display_mimo") or "-",
                    mimo_source=row.get("mimo_source") or "unavailable",
                    ie_size=len(str(row.get("raw_ie_hex") or "")) // 2,
                    warnings=",".join(row.get("parse_warnings") or []) if isinstance(row.get("parse_warnings"), list) else "-",
                )
            )
        return "\n".join(line for line in lines if line is not None)


def _set_row(table: QTableWidget, row_index: int, values: list[object], data: object | None = None) -> None:
    for column, value in enumerate(values):
        text = "-" if value is None or value == "" else str(value)
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        if column == 0 and data is not None:
            item.setData(Qt.UserRole, data)
        if isinstance(value, int | float):
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row_index, column, item)


def _status_color(status: str) -> QColor:
    return {
        "matched": QColor("#16a34a"),
        "unmatched": QColor("#6b7280"),
        "multi_match": QColor("#ca8a04"),
        "invalid_mac": QColor("#dc2626"),
    }.get(status, QColor("#e5e7eb"))


def _rssi_color(value: object) -> QColor:
    level = rssi_level(int(value)) if isinstance(value, int) else "unknown"
    return {
        "strong": QColor("#16a34a"),
        "good": QColor("#65a30d"),
        "fair": QColor("#ca8a04"),
        "weak": QColor("#dc2626"),
    }.get(level, QColor("#e5e7eb"))


def wireless_scan_default_column_widths() -> dict[str, int]:
    return {
        "display_ssid": 170,
        "display_mac_address": 160,
        "display_ap_mac": 160,
        "display_ap_name": 190,
        "display_radio_id": 80,
        "display_station": 140,
        "display_section": 170,
        "display_belong_type": 90,
        "display_belonging_source": 120,
        "display_location_mileage": 170,
        "display_rssi": 80,
        "display_signal_quality": 95,
        "display_channel": 80,
        "display_frequency": 90,
        "display_band": 80,
        "display_channel_width": 90,
        "display_mimo": 80,
        "display_encryption_method": 110,
        "display_encryption": 130,
        "display_auth_method": 120,
    }


def wireless_scan_minimum_column_widths() -> dict[str, int]:
    widths = {key: 50 for key in wireless_scan_default_column_widths()}
    widths.update(
        {
            "display_ssid": 100,
            "display_mac_address": 130,
            "display_ap_mac": 130,
            "display_ap_name": 140,
            "display_location_mileage": 130,
            "display_auth_method": 100,
        }
    )
    return widths


def _wireless_scan_sort_key(row: dict[str, object]) -> tuple[object, ...]:
    ap_name = str(row.get("display_ap_name") or "")
    has_ap = bool(ap_name and ap_name != "-")
    try:
        rssi = int(row.get("rssi_dbm") if row.get("rssi_dbm") is not None else -999)
    except (TypeError, ValueError):
        rssi = -999
    return (not has_ap, -rssi, str(row.get("display_station") or ""), ap_name, str(row.get("display_mac_address") or ""))


def _int_setting(settings: SettingsStore, key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(settings.get_value(key, default))
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _set_combo_data(combo: QComboBox, value: object) -> None:
    for index in range(combo.count()):
        if str(combo.itemData(index) or "") == str(value or ""):
            combo.setCurrentIndex(index)
            return


def _sort_value(field: str, row: dict[str, object]) -> object | None:
    numeric_source = {
        "display_radio_id": "matched_radio_id",
        "display_rssi": "rssi_dbm",
        "display_signal_quality": "quality",
        "display_channel": "channel",
        "display_frequency": "frequency_mhz",
        "display_channel_width": "channel_width_mhz",
    }
    if field in numeric_source:
        return _numeric_sort_value(row.get(numeric_source[field]))
    if field == "display_mimo":
        return _mimo_sort_value(row.get(field))
    value = row.get(field)
    if _missing(value):
        return None
    return str(value).casefold()


def _numeric_sort_value(value: object) -> int | float | None:
    if _missing(value):
        return None
    if isinstance(value, int | float):
        return value
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _mimo_sort_value(value: object) -> int | None:
    if _missing(value):
        return None
    match = re.search(r"\b([1-8])x[1-8]\b", str(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _missing(value: object) -> bool:
    return value is None or str(value).strip() in {"", "-"}


def _localized_display_value(i18n: I18n, field: str, value: object, row: dict[str, object]) -> object:
    if field == "display_ssid" and row.get("is_hidden"):
        return i18n.t("wireless_scan.hidden_ssid_short")
    if field == "display_band" and value == "Unknown":
        return i18n.t("wireless_scan.unknown")
    return value


def _mimo_tooltip(i18n: I18n, row: dict[str, object]) -> str:
    data_source = f"{i18n.t('wireless_scan.data_source')}: {_scan_source_text(i18n, str(row.get('scan_source') or ''))}"
    if row.get("scan_source") == "netsh":
        return f"{data_source}\n{i18n.t('wireless_scan.netsh_no_mimo_width')}"
    if row.get("mimo_source") and row.get("mimo_source") != "unavailable" and row.get("display_mimo") != "-":
        return f"{data_source}\n{i18n.t('wireless_scan.mimo_source')}: {row.get('mimo_source')}\n{i18n.t('wireless_scan.mimo_capability_note')}"
    return f"{data_source}\n{i18n.t('wireless_scan.mimo_unavailable')}"


def _channel_width_tooltip(i18n: I18n, row: dict[str, object]) -> str:
    data_source = f"{i18n.t('wireless_scan.data_source')}: {_scan_source_text(i18n, str(row.get('scan_source') or ''))}"
    if row.get("scan_source") == "netsh":
        return f"{data_source}\n{i18n.t('wireless_scan.netsh_no_mimo_width')}"
    source = row.get("channel_width_source") or "unavailable"
    return f"{data_source}\n{i18n.t('wireless_scan.channel_width_source')}: {source}"


def _actual_scan_source(rows: list[dict[str, object]]) -> str:
    sources = [str(row.get("scan_source") or "") for row in rows if row.get("scan_source")]
    if not sources:
        return ""
    return sources[0] if all(source == sources[0] for source in sources) else "mixed"


def _scan_source_text(i18n: I18n, source: str) -> str:
    return {
        "auto": i18n.t("wireless_scan.scan_source_auto"),
        "hybrid": i18n.t("wireless_scan.source_wlan_api_netsh"),
        "wlan_api": i18n.t("wireless_scan.scan_source_wlan_api"),
        "netsh": i18n.t("wireless_scan.scan_source_netsh"),
        "mixed": i18n.t("wireless_scan.source_wlan_api_netsh"),
    }.get(source, source or "-")
