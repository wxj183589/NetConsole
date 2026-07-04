from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.repositories.ac_repository import AcRepository, FIT_AP_METADATA_FIELDS, FIT_AP_OPTICAL_FIELDS, FIT_AP_RESOURCE_FIELDS
from netconsole.services.ap_optical_history_service import ApOpticalHistoryService
from netconsole.services.fit_ap_link_info import lldp_display_status, lldp_source_label, resolve_fit_ap_link_info
from netconsole.ui.dialogs.ap_optical_history_dialog import ApOpticalHistoryDialog
from netconsole.ui.dialogs.ap_history_dialog import AP_LLDP_HISTORY_COLUMNS, AP_OPTICAL_HISTORY_COLUMNS, AP_RADIO_HISTORY_COLUMNS, ApHistoryDialog
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, create_table_context_menu, make_text_selectable
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.state_engine import display_optical_status


FIT_AP_DETAIL_TABS = ("basic", "metadata", "radio", "lldp", "optical", "raw_fields")
LLDP_COLUMNS = (
    ("LLDP本地口", "lldp_local_interface"),
    ("LLDP邻居名称", "lldp_neighbor_name"),
    ("LLDP邻居MAC", "lldp_neighbor_mac"),
    ("LLDP邻居接口", "lldp_neighbor_interface"),
    ("邻居设备名称", "neighbor_device_name"),
    ("LLDP来源", "lldp_source"),
    ("LLDP匹配状态", "lldp_match_status"),
    ("采集时间", "lldp_collected_at"),
)
OPTICAL_COLUMNS = (
    ("光衰接口", "optical_interface"),
    ("RX光功率", "optical_rx_power"),
    ("TX光功率", "optical_tx_power"),
    ("details.rx_low_alarm", "rx_low_alarm"),
    ("details.rx_high_alarm", "rx_high_alarm"),
    ("details.tx_low_alarm", "tx_low_alarm"),
    ("details.tx_high_alarm", "tx_high_alarm"),
    ("ap.temperature", "temperature"),
    ("details.voltage", "voltage"),
    ("details.bias_current", "bias_current"),
    ("光衰匹配状态", "optical_match_status"),
    ("采集时间", "optical_collected_at"),
)
RAW_FIELD_GROUPS = (
    ("AP基础字段", ("ap_name", "apid", "ap_ip", "ap_mac", "model", "serial_number", "state_display", "state_raw", "group_name", "online_time", "site", "updated_at")),
    ("AP扩展字段", ("site_name", "mileage", "location_note", "direction")),
    ("Radio字段", ("rid1_channel", "rid1_bandwidth", "rid1_tx_power", "rid1_bbssid", "rid2_channel", "rid2_bandwidth", "rid2_tx_power", "rid2_bbssid", "rid3_channel", "rid3_bandwidth", "rid3_tx_power", "rid3_bbssid")),
    ("LLDP字段", ("lldp_local_interface", "lldp_neighbor_name", "lldp_neighbor_mac", "lldp_neighbor_interface", "neighbor_device_name", "lldp_source", "lldp_match_status", "lldp_collected_at")),
    ("光模块字段", ("optical_interface", "optical_rx_power", "optical_tx_power", "rx_low_alarm", "rx_high_alarm", "tx_low_alarm", "tx_high_alarm", "temperature", "voltage", "bias_current", "optical_match_status", "optical_collected_at")),
    ("系统字段", ("ap_uuid", "ac_device_uuid", "collect_run_uuid", "raw_log_path", "created_at")),
)
RAW_FIELD_LABELS = {
    "ac_device_uuid": "AC UUID",
    "ap_uuid": "AP UUID",
    "ap_name": "AP名称",
    "apid": "APID",
    "ap_ip": "AP IP",
    "ap_mac": "AP MAC",
    "model": "型号",
    "serial_number": "SN",
    "state_display": "状态",
    "state_raw": "原始状态",
    "group_name": "AP组",
    "online_time": "在线时长",
    "site": "站点",
    "site_name": "站点",
    "mileage": "里程",
    "location_note": "点位说明",
    "direction": "上下行",
    "updated_at": "更新时间",
    "rid1_channel": "RID1信道",
    "rid1_bandwidth": "RID1频宽",
    "rid1_tx_power": "RID1功率",
    "rid1_bbssid": "RID1 BSSID",
    "rid2_channel": "RID2信道",
    "rid2_bandwidth": "RID2频宽",
    "rid2_tx_power": "RID2功率",
    "rid2_bbssid": "RID2 BSSID",
    "rid3_channel": "RID3信道",
    "rid3_bandwidth": "RID3频宽",
    "rid3_tx_power": "RID3功率",
    "rid3_bbssid": "RID3 BSSID",
    "lldp_local_interface": "LLDP本地口",
    "lldp_neighbor_name": "LLDP邻居名称",
    "lldp_neighbor_mac": "LLDP邻居MAC",
    "lldp_neighbor_interface": "LLDP邻居接口",
    "neighbor_device_name": "邻居设备名称",
    "lldp_source": "LLDP来源",
    "lldp_match_status": "LLDP匹配状态",
    "lldp_collected_at": "LLDP采集时间",
    "optical_interface": "光衰接口",
    "optical_rx_power": "RX光功率",
    "optical_tx_power": "TX光功率",
    "rx_low_alarm": "RX低告警",
    "rx_high_alarm": "RX高告警",
    "tx_low_alarm": "TX低告警",
    "tx_high_alarm": "TX高告警",
    "temperature": "温度",
    "voltage": "电压",
    "bias_current": "偏置电流",
    "optical_match_status": "光衰匹配状态",
    "optical_collected_at": "光衰采集时间",
    "collect_run_uuid": "采集批次",
    "raw_log_path": "原始日志路径",
    "created_at": "创建时间",
}


class FitApDetailDialog(QWidget):
    def __init__(self, i18n: I18n, repository: AcRepository, ac_device_uuid: str, ap_uuid: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.repository = repository
        self.ac_device_uuid = ac_device_uuid
        self.settings = SettingsStore(PathResolver())
        self.show_raw_fields_tab = True
        resource = self.repository.get_fit_ap_resource_by_uuid(ac_device_uuid, ap_uuid) or self.repository.get_fit_ap_resource(ac_device_uuid, ap_uuid) or {}
        self.ap_uuid = str(resource.get("ap_uuid") or ap_uuid)
        self.ap_name = str(resource.get("ap_name") or ap_uuid)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(self.i18n.t("ap.detail_title", ap=self.ap_name))
        self.resize(900, 680)
        self.setMinimumSize(760, 520)
        self._restore_window_state()

        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.save_button = QPushButton()
        self.tabs = QTabWidget()
        self.basic_tab = QWidget()
        self.metadata_tab = QWidget()
        self.radio_tab = QWidget()
        self.lldp_tab = QWidget()
        self.optical_tab = QWidget()
        self.raw_fields_tab = QWidget()
        self.basic_labels: dict[str, QLabel] = {}
        self.site_input = QLineEdit()
        self.mileage_input = QLineEdit()
        self.location_note_input = QLineEdit()
        self.direction_combo = QComboBox()
        self.radio_history_button = QPushButton()
        self.lldp_history_button = QPushButton()
        self.optical_history_button = QPushButton()
        self.radio_table = QTableWidget()
        self.lldp_table = QTableWidget()
        self.optical_table = QTableWidget()
        self.raw_fields_table = QTableWidget()
        self.show_empty_raw_fields_checkbox = QCheckBox()
        self.raw_fields_pagination = PaginationWidget(self.i18n)
        self.raw_field_rows: list[dict[str, object | None]] = []
        self.raw_fields_page = 1
        self.raw_fields_page_size = DEFAULT_PAGE_SIZE
        self.history_windows: list[ApHistoryDialog] = []
        self.optical_history_window: ApOpticalHistoryDialog | None = None
        self.optical_history_service = ApOpticalHistoryService(repository)
        for table in (self.radio_table, self.lldp_table, self.optical_table, self.raw_fields_table):
            configure_readonly_table(table)
            table.setWordWrap(False)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        for table, kind in ((self.radio_table, "radio"), (self.lldp_table, "lldp"), (self.optical_table, "optical")):
            table.setContextMenuPolicy(Qt.CustomContextMenu)
            table.customContextMenuRequested.connect(lambda position, current_table=table, current_kind=kind: self.show_history_context_menu(current_table, current_kind, position))

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.always_on_top_button)

        self._build_basic_tab()
        self._build_metadata_tab()
        self._build_radio_tab()
        self._build_lldp_tab()
        self._build_optical_tab()
        self._build_raw_fields_tab()
        self.tabs.addTab(self.basic_tab, "")
        self.tabs.addTab(self.metadata_tab, "")
        self.tabs.addTab(self.radio_tab, "")
        self.tabs.addTab(self.lldp_tab, "")
        self.tabs.addTab(self.optical_tab, "")
        self.tabs.addTab(self.raw_fields_tab, "")

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        self.setLayout(layout)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.save_button.clicked.connect(self.save_metadata)
        self.radio_history_button.clicked.connect(lambda: self.open_history("radio"))
        self.lldp_history_button.clicked.connect(lambda: self.open_history("lldp"))
        self.optical_history_button.clicked.connect(lambda: self.open_history("optical"))
        self.raw_fields_pagination.pageChanged.connect(self.set_raw_fields_page)
        self.raw_fields_pagination.pageSizeChanged.connect(self.set_raw_fields_page_size)
        self.show_empty_raw_fields_checkbox.toggled.connect(self.refresh_raw_fields_page)
        self.retranslate()
        self.refresh()
        self.tabs.setCurrentWidget(self.basic_tab)
        app_logger.log_info("FIT_AP_DETAIL_OPENED", f"ap_uuid={ap_uuid}, ap={self.ap_name}")

    def _build_basic_tab(self) -> None:
        form = QFormLayout()
        for key, field in (
            ("ac.ap_name", "ap_name"),
            ("field.ip_address", "ap_ip"),
            ("field.mac_address", "ap_mac"),
            ("details.model", "model"),
            ("details.serial_number", "serial_number"),
            ("field.status", "state_display"),
            ("ac.group_name", "group_name"),
            ("ac.online_time", "online_time"),
            ("ac.site", "site"),
            ("ac.mileage", "mileage"),
            ("ac.location_note", "location_note"),
            ("ac.direction", "direction"),
            ("field.updated_at", "updated_at"),
        ):
            label = QLabel()
            label.setProperty("translation_key", key)
            make_text_selectable(label)
            value = make_text_selectable(QLabel("-"))
            self.basic_labels[field] = value
            form.addRow(label, value)
        self.basic_tab.setLayout(form)

    def _build_metadata_tab(self) -> None:
        self.direction_combo.addItem("", "")
        self.direction_combo.addItem(self.i18n.t("ap.direction.uplink"), "上行")
        self.direction_combo.addItem(self.i18n.t("ap.direction.downlink"), "下行")
        form = QFormLayout()
        form.addRow(self.i18n.t("ac.site"), self.site_input)
        form.addRow(self.i18n.t("ac.mileage"), self.mileage_input)
        form.addRow(self.i18n.t("ac.location_note"), self.location_note_input)
        form.addRow(self.i18n.t("ac.direction"), self.direction_combo)
        form.addRow("", self.save_button)
        self.metadata_tab.setLayout(form)

    def _build_radio_tab(self) -> None:
        self.radio_table.setColumnCount(5)
        set_table_column_fields(self.radio_table, ["rid", "channel", "bandwidth", "tx_power", "bbssid"])
        layout = QVBoxLayout()
        actions = QHBoxLayout()
        actions.addWidget(self.radio_history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.radio_table, 1)
        self.radio_tab.setLayout(layout)

    def _build_lldp_tab(self) -> None:
        self.lldp_table.setColumnCount(len(LLDP_COLUMNS))
        set_table_column_fields(self.lldp_table, [field for _key, field in LLDP_COLUMNS])
        layout = QVBoxLayout()
        actions = QHBoxLayout()
        actions.addWidget(self.lldp_history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.lldp_table, 1)
        self.lldp_tab.setLayout(layout)

    def _build_optical_tab(self) -> None:
        self.optical_table.setColumnCount(len(OPTICAL_COLUMNS))
        set_table_column_fields(self.optical_table, [field for _key, field in OPTICAL_COLUMNS])
        layout = QVBoxLayout()
        actions = QHBoxLayout()
        actions.addWidget(self.optical_history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.optical_table, 1)
        self.optical_tab.setLayout(layout)

    def _build_raw_fields_tab(self) -> None:
        self.raw_fields_table.setColumnCount(2)
        self.raw_fields_table.setWordWrap(True)
        set_table_column_fields(self.raw_fields_table, ["name", "value"])
        layout = QVBoxLayout()
        layout.addWidget(self.show_empty_raw_fields_checkbox)
        layout.addWidget(self.raw_fields_table, 1)
        layout.addWidget(self.raw_fields_pagination)
        self.raw_fields_tab.setLayout(layout)

    def retranslate(self) -> None:
        self.always_on_top_button.setText(self.i18n.t("window.always_on_top"))
        self.save_button.setText(self.i18n.t("dialog.save_device"))
        self.radio_history_button.setText(self.i18n.t("history.view"))
        self.lldp_history_button.setText(self.i18n.t("history.view"))
        self.optical_history_button.setText(self.i18n.t("ap_detail.view_optical_history"))
        self.tabs.setTabText(0, self.i18n.t("ap.basic_info"))
        self.tabs.setTabText(1, self.i18n.t("ap.metadata"))
        self.tabs.setTabText(2, "Radio")
        self.tabs.setTabText(3, self.i18n.t("ac.lldp_neighbor"))
        self.tabs.setTabText(4, self.i18n.t("ap.optical_module"))
        self.tabs.setTabText(5, self.i18n.t("ap.raw_fields"))
        for index in range(self.basic_tab.layout().rowCount()):
            label = self.basic_tab.layout().itemAt(index, QFormLayout.LabelRole).widget()
            label.setText(self.i18n.t(label.property("translation_key")))
        self.radio_table.setHorizontalHeaderLabels(["RID", self.i18n.t("ap.channel"), self.i18n.t("ap.bandwidth"), self.i18n.t("ap.tx_power"), "BSSID"])
        self.lldp_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in LLDP_COLUMNS])
        self.optical_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in OPTICAL_COLUMNS])
        self.show_empty_raw_fields_checkbox.setText("Show empty fields" if self.i18n.language.startswith("en") else "显示空字段")
        field_header = "Field" if self.i18n.language.startswith("en") else "字段"
        self.raw_fields_table.setHorizontalHeaderLabels([field_header, self.i18n.t("field.value")])
        self.raw_fields_pagination.retranslate()

    def refresh(self) -> None:
        resource = self.repository.get_fit_ap_resource_by_uuid(self.ac_device_uuid, self.ap_uuid) or self.repository.get_fit_ap_resource(self.ac_device_uuid, self.ap_name) or {}
        optical = self.repository.get_fit_ap_optical_by_uuid(self.ac_device_uuid, self.ap_uuid) or {}
        metadata = self.repository.get_fit_ap_metadata_by_uuid(self.ap_uuid) or {}
        link_info = resolve_fit_ap_link_info({**resource, **optical})
        basic_source = {
            **resource,
            "site": metadata.get("site_name") or resource.get("site") or optical.get("site"),
            "mileage": metadata.get("mileage") or resource.get("mileage"),
            "location_note": metadata.get("location_note") or resource.get("location_note"),
            "direction": normalize_direction(str(metadata.get("direction") or resource.get("direction") or "")),
        }
        for field, label in self.basic_labels.items():
            value = basic_source.get(field)
            if field == "state_display":
                value = value or resource.get("state")
                label.setToolTip(f"{self.i18n.t('ap.state_raw')}: {resource.get('state_raw') or resource.get('state') or '-'}")
            label.setText(str(value) if value not in (None, "") else "-")
        self.site_input.setText(str(metadata.get("site_name") or optical.get("site") or ""))
        self.mileage_input.setText(str(metadata.get("mileage") or ""))
        self.location_note_input.setText(str(metadata.get("location_note") or ""))
        direction = normalize_direction(str(metadata.get("direction") or ""))
        index = self.direction_combo.findData(direction)
        self.direction_combo.setCurrentIndex(index if index >= 0 else 0)
        self._set_radio_table(resource)
        self._set_table(self.lldp_table, LLDP_COLUMNS, [link_info] if link_info else [])
        summary = self.optical_history_service.get_latest_optical_summary(self.ac_device_uuid, self.ap_uuid)
        optical_info = resolve_fit_ap_link_info({**resource, **optical, **(summary or {})})
        self._set_table(self.optical_table, OPTICAL_COLUMNS, [optical_info] if optical_info else [])
        self._set_raw_fields_table(resource, metadata, optical_info)

    def save_metadata(self) -> None:
        self.repository.upsert_fit_ap_metadata(
            {
                "ap_name": self.ap_name,
                "ap_uuid": self.ap_uuid,
                "site_name": self.site_input.text().strip(),
                "mileage": self.mileage_input.text().strip(),
                "location_note": self.location_note_input.text().strip(),
                "direction": normalize_direction(str(self.direction_combo.currentData() or self.direction_combo.currentText())),
            }
        )
        app_logger.log_info("FIT_AP_METADATA_SAVED", f"ap={self.ap_name}")

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()

    def _set_radio_table(self, row: dict[str, object | None]) -> None:
        self.radio_table.setRowCount(3)
        for index, rid in enumerate((1, 2, 3)):
            values = [rid, row.get(f"rid{rid}_channel"), row.get(f"rid{rid}_bandwidth"), row.get(f"rid{rid}_tx_power"), row.get(f"rid{rid}_bbssid")]
            for column, value in enumerate(values):
                self.radio_table.setItem(index, column, QTableWidgetItem(str(value) if value not in (None, "") else "-"))
                self.radio_table.item(index, column).setTextAlignment(Qt.AlignCenter)
        auto_resize_table_columns(self.radio_table)

    @staticmethod
    def _set_table(table: QTableWidget, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]]) -> None:
        table.setRowCount(len(rows) or 1)
        source_rows = rows or [{}]
        for row_index, row in enumerate(source_rows):
            for column_index, (_key, field) in enumerate(columns):
                value = display_optical_status(compute_ap_status(row), "zh") if field == "optical_alarm_status" else _detail_display_value(row, field)
                item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column_index, item)
        auto_resize_table_columns(table)

    def _set_raw_fields_table(self, resource: dict[str, object | None], metadata: dict[str, object | None], optical: dict[str, object | None]) -> None:
        self.raw_field_rows = build_fit_ap_detail_fields(resource, metadata, optical, show_empty=True)
        self.raw_fields_page = 1
        self.refresh_raw_fields_page()

    def refresh_raw_fields_page(self) -> None:
        source_rows = self.raw_field_rows if self.show_empty_raw_fields_checkbox.isChecked() else [row for row in self.raw_field_rows if not _is_empty_raw_field_value(row.get("value"))]
        rows, state = paginate_rows(source_rows, self.raw_fields_page_size, self.raw_fields_page)
        self.raw_fields_page = state.current_page
        self.raw_fields_pagination.set_state(state)
        self.raw_fields_table.setUpdatesEnabled(False)
        self.raw_fields_table.setSortingEnabled(False)
        self.raw_fields_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, item_value in enumerate((row.get("name"), _format_raw_field_value(row.get("value"), str(row.get("field") or "")))):
                item = QTableWidgetItem(item_value if item_value not in (None, "") else "-")
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(item.text())
                self.raw_fields_table.setItem(row_index, column_index, item)
        self.raw_fields_table.setSortingEnabled(False)
        self.raw_fields_table.setUpdatesEnabled(True)
        auto_resize_table_columns(self.raw_fields_table)

    def set_raw_fields_page(self, page: int) -> None:
        self.raw_fields_page = page
        self.refresh_raw_fields_page()

    def set_raw_fields_page_size(self, page_size: int) -> None:
        self.raw_fields_page_size = page_size
        self.raw_fields_page = 1
        self.refresh_raw_fields_page()

    def show_history_context_menu(self, table: QTableWidget, kind: str, position) -> None:
        index = table.indexAt(position)
        menu = create_table_context_menu(table, index.row(), index.column(), self.i18n.language, include_history=False)
        menu.addSeparator()
        history = menu.addAction(self.i18n.t("history.view"))
        history.triggered.connect(lambda: self.open_history(kind))
        menu.exec(table.viewport().mapToGlobal(position))

    def open_history(self, kind: str) -> None:
        if kind == "radio":
            rows = self.repository.list_fit_ap_radio_history_by_ap(self.ap_uuid)
            columns = AP_RADIO_HISTORY_COLUMNS
            title = "Radio"
            color_field = None
        elif kind == "lldp":
            rows = self.repository.list_fit_ap_lldp_history_by_ap(self.ap_uuid)
            columns = AP_LLDP_HISTORY_COLUMNS
            title = self.i18n.t("ac.lldp_neighbor")
            color_field = None
        else:
            self.open_optical_history()
            return
        dialog = ApHistoryDialog(self.i18n, self.ap_name, title, rows, columns, color_field, owner=self)
        self.history_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_history_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_history_window(self, window: ApHistoryDialog) -> None:
        self.history_windows = [item for item in self.history_windows if item is not window]

    def open_optical_history(self) -> None:
        if self.optical_history_window is not None:
            self.optical_history_window.show()
            self.optical_history_window.raise_()
            self.optical_history_window.activateWindow()
            return
        rows = self.optical_history_service.query_ap_optical_history_all(self.ap_uuid)
        dialog = ApOpticalHistoryDialog(self.i18n, self.ap_name, rows, self.settings, owner=self)
        self.optical_history_window = dialog
        dialog.destroyed.connect(lambda _=None: setattr(self, "optical_history_window", None))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def closeEvent(self, event) -> None:
        self.settings.set_value("ac/ap_detail/window_geometry", {"width": self.width(), "height": self.height()})
        self.settings.set_value("ac/ap_detail/window_maximized", self.isMaximized())
        super().closeEvent(event)

    def _restore_window_state(self) -> None:
        geometry = self.settings.get_value("ac/ap_detail/window_geometry", {})
        if isinstance(geometry, dict):
            try:
                width = max(760, int(geometry.get("width") or 900))
                height = max(520, int(geometry.get("height") or 680))
                self.resize(width, height)
            except (TypeError, ValueError):
                pass
        if self.settings.get_value("ac/ap_detail/window_maximized", False):
            self.showMaximized()


def _detail_display_value(row: dict[str, object | None], field: str) -> object:
    value = row.get(field)
    if field == "lldp_source":
        return lldp_source_label(value)
    if field in {"lldp_match_status", "optical_match_status", "link_match_status"}:
        return lldp_display_status(value)
    return value


def build_fit_ap_detail_fields(
    resource: dict[str, object | None],
    metadata: dict[str, object | None],
    optical: dict[str, object | None],
    show_empty: bool = False,
) -> list[dict[str, object | None]]:
    combined = {**resource, **metadata, **optical}
    rows: list[dict[str, object | None]] = []
    used_fields: set[str] = set()
    for group_label, fields in RAW_FIELD_GROUPS:
        for field in fields:
            used_fields.add(field)
            value = combined.get(field)
            if not show_empty and _is_empty_raw_field_value(value):
                continue
            rows.append({"name": f"{group_label} / {RAW_FIELD_LABELS.get(field, field)}", "field": field, "value": value})
    for field in sorted(set(combined) - used_fields):
        value = combined.get(field)
        if not show_empty and _is_empty_raw_field_value(value):
            continue
        rows.append({"name": f"系统字段 / {RAW_FIELD_LABELS.get(field, field)}", "field": field, "value": value})
    return rows


def _is_empty_raw_field_value(value: object) -> bool:
    text = str(value or "").strip()
    return text == "" or text in {"-", "N/A", "未知"} or text.casefold() in {"n/a", "unknown", "none", "null"}


def _format_raw_field_value(value: object, field: str = "") -> str:
    if value in (None, ""):
        return "-"
    if field == "lldp_source":
        return lldp_source_label(value)
    if field in {"lldp_match_status", "optical_match_status", "link_match_status"}:
        return lldp_display_status(value)
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def normalize_direction(value: str) -> str:
    text = str(value or "").strip()
    if text.upper() == "CW":
        return "上行"
    if text.upper() == "CT":
        return "下行"
    if text in {"上行", "下行"}:
        return text
    return ""
