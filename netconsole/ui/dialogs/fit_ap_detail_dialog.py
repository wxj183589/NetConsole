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
from netconsole.repositories.ac_repository import AcRepository
from netconsole.ui.table_utils import auto_resize_table_columns, configure_readonly_table, make_text_selectable


FIT_AP_DETAIL_TABS = ("basic", "metadata", "radio", "lldp", "optical")
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
    def __init__(self, i18n: I18n, repository: AcRepository, ac_device_uuid: str, ap_name: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.repository = repository
        self.ac_device_uuid = ac_device_uuid
        self.ap_name = ap_name
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(self.i18n.t("ap.detail_title", ap=ap_name))
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
        self.basic_labels: dict[str, QLabel] = {}
        self.site_input = QLineEdit()
        self.mileage_input = QLineEdit()
        self.location_note_input = QLineEdit()
        self.direction_combo = QComboBox()
        self.radio_table = QTableWidget()
        self.lldp_table = QTableWidget()
        self.optical_table = QTableWidget()
        for table in (self.radio_table, self.lldp_table, self.optical_table):
            configure_readonly_table(table)

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.always_on_top_button)

        self._build_basic_tab()
        self._build_metadata_tab()
        self._build_radio_tab()
        self._build_lldp_tab()
        self._build_optical_tab()
        self.tabs.addTab(self.basic_tab, "")
        self.tabs.addTab(self.metadata_tab, "")
        self.tabs.addTab(self.radio_tab, "")
        self.tabs.addTab(self.lldp_tab, "")
        self.tabs.addTab(self.optical_tab, "")

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        self.setLayout(layout)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.save_button.clicked.connect(self.save_metadata)
        self.retranslate()
        self.refresh()
        app_logger.log_info("FIT_AP_DETAIL_OPENED", f"ap={ap_name}")

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
        self.direction_combo.addItems(["", "CW", "CT"])
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
        layout.addWidget(self.radio_table)
        self.radio_tab.setLayout(layout)

    def _build_lldp_tab(self) -> None:
        self.lldp_table.setColumnCount(len(LLDP_COLUMNS))
        layout = QVBoxLayout()
        layout.addWidget(self.lldp_table)
        self.lldp_tab.setLayout(layout)

    def _build_optical_tab(self) -> None:
        self.optical_table.setColumnCount(len(OPTICAL_COLUMNS))
        layout = QVBoxLayout()
        layout.addWidget(self.optical_table)
        self.optical_tab.setLayout(layout)

    def retranslate(self) -> None:
        self.always_on_top_button.setText(self.i18n.t("window.always_on_top"))
        self.save_button.setText(self.i18n.t("dialog.save_device"))
        self.tabs.setTabText(0, self.i18n.t("ap.basic_info"))
        self.tabs.setTabText(1, self.i18n.t("ap.metadata"))
        self.tabs.setTabText(2, "Radio")
        self.tabs.setTabText(3, self.i18n.t("ac.lldp_neighbor"))
        self.tabs.setTabText(4, self.i18n.t("ap.optical_module"))
        for index in range(self.basic_tab.layout().rowCount()):
            label = self.basic_tab.layout().itemAt(index, QFormLayout.LabelRole).widget()
            label.setText(self.i18n.t(label.property("translation_key")))
        self.radio_table.setHorizontalHeaderLabels(["RID", self.i18n.t("ap.channel"), self.i18n.t("ap.bandwidth"), self.i18n.t("ap.tx_power")])
        self.lldp_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in LLDP_COLUMNS])
        self.optical_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in OPTICAL_COLUMNS])

    def refresh(self) -> None:
        resource = self.repository.get_fit_ap_resource(self.ac_device_uuid, self.ap_name) or {}
        optical = self.repository.get_fit_ap_optical_by_ap(self.ac_device_uuid, self.ap_name) or {}
        metadata = self.repository.get_fit_ap_metadata(self.ap_name) or {}
        for field, label in self.basic_labels.items():
            value = resource.get(field)
            if field == "state_display":
                value = value or resource.get("state")
                label.setToolTip(f"{self.i18n.t('ap.state_raw')}: {resource.get('state_raw') or resource.get('state') or '-'}")
            label.setText(str(value) if value not in (None, "") else "-")
        self.site_input.setText(str(metadata.get("site_name") or ""))
        self.mileage_input.setText(str(metadata.get("mileage") or ""))
        self.location_note_input.setText(str(metadata.get("location_note") or ""))
        self.direction_combo.setCurrentIndex(max(self.direction_combo.findText(str(metadata.get("direction") or "")), 0))
        self._set_radio_table(resource)
        self._set_table(self.lldp_table, LLDP_COLUMNS, [optical] if optical else [])
        self._set_table(self.optical_table, OPTICAL_COLUMNS, [optical] if optical else [])

    def save_metadata(self) -> None:
        self.repository.upsert_fit_ap_metadata(
            {
                "ap_name": self.ap_name,
                "site_name": self.site_input.text().strip(),
                "mileage": self.mileage_input.text().strip(),
                "location_note": self.location_note_input.text().strip(),
                "direction": self.direction_combo.currentText(),
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
        auto_resize_table_columns(self.radio_table)

    @staticmethod
    def _set_table(table: QTableWidget, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]]) -> None:
        table.setRowCount(len(rows) or 1)
        source_rows = rows or [{}]
        for row_index, row in enumerate(source_rows):
            for column_index, (_key, field) in enumerate(columns):
                value = row.get(field)
                table.setItem(row_index, column_index, QTableWidgetItem(str(value) if value not in (None, "") else "-"))
        auto_resize_table_columns(table, column_min_widths={0: 180})
