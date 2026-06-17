from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
from netconsole.repositories.ac_repository import AcRepository, FIT_AP_METADATA_FIELDS, FIT_AP_OPTICAL_FIELDS, FIT_AP_RESOURCE_FIELDS
from netconsole.ui.dialogs.ap_history_dialog import AP_LLDP_HISTORY_COLUMNS, AP_OPTICAL_HISTORY_COLUMNS, AP_RADIO_HISTORY_COLUMNS, ApHistoryDialog
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, create_table_context_menu, make_text_selectable
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.state_engine import display_optical_status


FIT_AP_DETAIL_TABS = ("basic", "metadata", "radio", "lldp", "optical", "raw_fields")
DETAIL_STYLESHEET = """
QWidget {
    background: #ffffff;
    color: #111827;
}
QTabBar::tab {
    background: #f3f4f6;
    color: #111827;
    font-weight: 500;
    padding: 8px 14px;
    border: 1px solid #d1d5db;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #111827;
    font-weight: 700;
}
QComboBox, QComboBox QAbstractItemView {
    background: #ffffff;
    color: #111827;
    selection-background-color: #dbeafe;
    selection-color: #111827;
    min-height: 24px;
}
"""
LLDP_COLUMNS = (
    ("ac.lldp_neighbor", "lldp_neighbor"),
    ("ap.neighbor_interface", "neighbor_interface"),
    ("ap.neighbor_mac", "neighbor_mac"),
    ("ap.neighbor_device_name", "neighbor_device_name"),
    ("ap.neighbor_rx_power", "neighbor_rx_power"),
)
OPTICAL_COLUMNS = (
    ("ap.interface", "interface_name"),
    ("ap.temperature", "temperature"),
    ("ap.tx_power", "tx_power"),
    ("ap.rx_power", "rx_power"),
    ("ap.optical_alarm_status", "optical_alarm_status"),
)


class FitApDetailDialog(QWidget):
    def __init__(self, i18n: I18n, repository: AcRepository, ac_device_uuid: str, ap_uuid: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.repository = repository
        self.ac_device_uuid = ac_device_uuid
        resource = self.repository.get_fit_ap_resource_by_uuid(ac_device_uuid, ap_uuid) or self.repository.get_fit_ap_resource(ac_device_uuid, ap_uuid) or {}
        self.ap_uuid = str(resource.get("ap_uuid") or ap_uuid)
        self.ap_name = str(resource.get("ap_name") or ap_uuid)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(DETAIL_STYLESHEET)
        self.setWindowTitle(self.i18n.t("ap.detail_title", ap=self.ap_name))
        self.resize(900, 680)
        self.setMinimumSize(760, 520)

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
        self.raw_fields_pagination = PaginationWidget(self.i18n)
        self.raw_field_rows: list[dict[str, object | None]] = []
        self.raw_fields_page = 1
        self.raw_fields_page_size = DEFAULT_PAGE_SIZE
        self.history_windows: list[ApHistoryDialog] = []
        for table in (self.radio_table, self.lldp_table, self.optical_table, self.raw_fields_table):
            configure_readonly_table(table)
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
        self.retranslate()
        self.refresh()
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
        self.radio_table.setColumnCount(4)
        layout = QVBoxLayout()
        actions = QHBoxLayout()
        actions.addWidget(self.radio_history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.radio_table)
        self.radio_tab.setLayout(layout)

    def _build_lldp_tab(self) -> None:
        self.lldp_table.setColumnCount(len(LLDP_COLUMNS))
        layout = QVBoxLayout()
        actions = QHBoxLayout()
        actions.addWidget(self.lldp_history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.lldp_table)
        self.lldp_tab.setLayout(layout)

    def _build_optical_tab(self) -> None:
        self.optical_table.setColumnCount(len(OPTICAL_COLUMNS))
        layout = QVBoxLayout()
        actions = QHBoxLayout()
        actions.addWidget(self.optical_history_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.optical_table)
        self.optical_tab.setLayout(layout)

    def _build_raw_fields_tab(self) -> None:
        self.raw_fields_table.setColumnCount(3)
        layout = QVBoxLayout()
        layout.addWidget(self.raw_fields_table)
        layout.addWidget(self.raw_fields_pagination)
        self.raw_fields_tab.setLayout(layout)

    def retranslate(self) -> None:
        self.always_on_top_button.setText(self.i18n.t("window.always_on_top"))
        self.save_button.setText(self.i18n.t("dialog.save_device"))
        self.radio_history_button.setText(self.i18n.t("history.view"))
        self.lldp_history_button.setText(self.i18n.t("history.view"))
        self.optical_history_button.setText(self.i18n.t("history.view"))
        self.tabs.setTabText(0, self.i18n.t("ap.basic_info"))
        self.tabs.setTabText(1, self.i18n.t("ap.metadata"))
        self.tabs.setTabText(2, "Radio")
        self.tabs.setTabText(3, self.i18n.t("ac.lldp_neighbor"))
        self.tabs.setTabText(4, self.i18n.t("ap.optical_module"))
        self.tabs.setTabText(5, self.i18n.t("ap.raw_fields"))
        for index in range(self.basic_tab.layout().rowCount()):
            label = self.basic_tab.layout().itemAt(index, QFormLayout.LabelRole).widget()
            label.setText(self.i18n.t(label.property("translation_key")))
        self.radio_table.setHorizontalHeaderLabels(["RID", self.i18n.t("ap.channel"), self.i18n.t("ap.bandwidth"), self.i18n.t("ap.tx_power")])
        self.lldp_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in LLDP_COLUMNS])
        self.optical_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in OPTICAL_COLUMNS])
        self.raw_fields_table.setHorizontalHeaderLabels([self.i18n.t("field.type"), self.i18n.t("field.name"), self.i18n.t("field.value")])
        self.raw_fields_pagination.retranslate()

    def refresh(self) -> None:
        resource = self.repository.get_fit_ap_resource_by_uuid(self.ac_device_uuid, self.ap_uuid) or self.repository.get_fit_ap_resource(self.ac_device_uuid, self.ap_name) or {}
        optical = self.repository.get_fit_ap_optical_by_uuid(self.ac_device_uuid, self.ap_uuid) or {}
        metadata = self.repository.get_fit_ap_metadata_by_uuid(self.ap_uuid) or {}
        for field, label in self.basic_labels.items():
            value = resource.get(field)
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
        self._set_table(self.lldp_table, LLDP_COLUMNS, [optical] if optical else [])
        self._set_table(self.optical_table, OPTICAL_COLUMNS, [optical] if optical else [])
        self._set_raw_fields_table(resource, metadata, optical)

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
            values = [rid, row.get(f"rid{rid}_channel"), row.get(f"rid{rid}_bandwidth"), row.get(f"rid{rid}_tx_power")]
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
                value = display_optical_status(compute_ap_status(row), "zh") if field == "optical_alarm_status" else row.get(field)
                item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column_index, item)
        auto_resize_table_columns(table, column_min_widths={0: 180})

    def _set_raw_fields_table(self, resource: dict[str, object | None], metadata: dict[str, object | None], optical: dict[str, object | None]) -> None:
        rows: list[dict[str, object | None]] = []
        for group, fields, source in (
            ("resource", FIT_AP_RESOURCE_FIELDS, resource),
            ("metadata", FIT_AP_METADATA_FIELDS, metadata),
            ("optical", FIT_AP_OPTICAL_FIELDS, optical),
        ):
            rows.extend({"type": group, "name": field, "value": source.get(field)} for field in fields)
        self.raw_field_rows = rows
        self.raw_fields_page = 1
        self.refresh_raw_fields_page()

    def refresh_raw_fields_page(self) -> None:
        rows, state = paginate_rows(self.raw_field_rows, self.raw_fields_page_size, self.raw_fields_page)
        self.raw_fields_page = state.current_page
        self.raw_fields_pagination.set_state(state)
        self.raw_fields_table.setUpdatesEnabled(False)
        self.raw_fields_table.setSortingEnabled(False)
        self.raw_fields_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, item_value in enumerate((row.get("type"), row.get("name"), row.get("value"))):
                item = QTableWidgetItem(str(item_value) if item_value not in (None, "") else "-")
                item.setTextAlignment(Qt.AlignCenter)
                self.raw_fields_table.setItem(row_index, column_index, item)
        self.raw_fields_table.setSortingEnabled(False)
        self.raw_fields_table.setUpdatesEnabled(True)
        auto_resize_table_columns(self.raw_fields_table, column_min_widths={0: 100, 1: 180, 2: 260})

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
            rows = self.repository.list_fit_ap_optical_history_by_ap(self.ap_uuid)
            columns = AP_OPTICAL_HISTORY_COLUMNS
            title = self.i18n.t("ap.optical_module")
            color_field = "optical_alarm_status"
        dialog = ApHistoryDialog(self.i18n, self.ap_name, title, rows, columns, color_field, self)
        self.history_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_history_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_history_window(self, window: ApHistoryDialog) -> None:
        self.history_windows = [item for item in self.history_windows if item is not window]


def normalize_direction(value: str) -> str:
    text = str(value or "").strip()
    if text.upper() == "CW":
        return "上行"
    if text.upper() == "CT":
        return "下行"
    if text in {"上行", "下行"}:
        return text
    return ""
