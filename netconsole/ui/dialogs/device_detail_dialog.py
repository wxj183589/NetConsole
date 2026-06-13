from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository


OVERVIEW_FIELDS = (
    ("details.system_name", "sysname"),
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("details.software_version", "software_version"),
    ("details.bootrom_version", "bootrom_version"),
    ("details.vendor", "vendor"),
    ("details.uptime", "uptime"),
    ("details.collected_at", "collected_at"),
    ("details.raw_log_path", "raw_log_path"),
)

INTERFACE_COLUMNS = (
    ("details.interface_name", "interface_name"),
    ("details.link", "link_status"),
    ("details.protocol", "protocol_status"),
    ("details.speed", "speed"),
    ("details.duplex", "duplex"),
    ("details.interface_type", "interface_type"),
    ("details.port_status", "port_status"),
    ("details.pvid", "pvid"),
    ("details.port_description", "description"),
    ("details.interface_ip", "ip_address"),
    ("details.mac_address", "mac_address"),
    ("details.vlan", "vlan"),
    ("details.collected_at", "collected_at"),
)

OPTICAL_MODULE_COLUMNS = (
    ("details.interface_name", "interface_name"),
    ("details.rx_power", "rx_power"),
    ("details.tx_power", "tx_power"),
    ("details.temperature", "temperature"),
    ("details.voltage", "voltage"),
    ("details.bias_current", "bias_current"),
    ("details.module_model", "module_model"),
    ("details.module_serial_number", "module_serial_number"),
    ("details.vendor", "module_vendor"),
    ("details.wavelength", "wavelength"),
    ("details.transmission_distance", "transmission_distance"),
    ("field.status", "status"),
    ("details.collected_at", "collected_at"),
)

LLDP_COLUMNS = (
    ("details.local_interface", "local_interface"),
    ("details.neighbor_sysname", "neighbor_sysname"),
    ("details.neighbor_mac", "neighbor_mac"),
    ("details.neighbor_interface", "neighbor_interface"),
    ("details.neighbor_ip", "neighbor_ip"),
    ("details.collected_at", "collected_at"),
)


class DeviceDetailDialog(QDialog):
    def __init__(self, i18n: I18n, repository: DeviceFactRepository, device: Device, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.repository = repository
        self.device = device
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setMinimumSize(720, 480)
        self.resize(800, 520)

        self.title_label = QLabel()
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.tabs = QTabWidget()
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.always_on_top_button)
        layout.addLayout(header)
        layout.addWidget(self.tabs)
        self.apply_style()
        self.retranslate()

    def retranslate(self) -> None:
        title = self.i18n.t("details.title_with_name", name=self.device.name)
        self.setWindowTitle(title)
        self.title_label.setText(title)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))
        self.tabs.clear()
        self.tabs.addTab(self._overview_tab(), self.i18n.t("details.overview"))
        self.tabs.addTab(self._interfaces_tab(), self.i18n.t("details.interfaces"))
        self.tabs.addTab(self._optical_modules_tab(), self.i18n.t("details.optical_modules"))
        self.tabs.addTab(self._lldp_tab(), self.i18n.t("details.lldp"))

    def _overview_tab(self) -> QWidget:
        fact = self.repository.get_device_fact(str(self.device.device_uuid or ""))
        if not fact:
            return self._empty_tab("details.overview_note")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self._note_label("details.overview_note"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        for label_key, field in OVERVIEW_FIELDS:
            form.addRow(self.i18n.t(label_key), QLabel(str(fact.get(field) or "")))
        layout.addStretch(1)
        return widget

    def _interfaces_tab(self) -> QWidget:
        rows = self.repository.list_device_interfaces(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.interfaces_note")
        return self._table_tab("details.interfaces_note", INTERFACE_COLUMNS, rows)

    def _optical_modules_tab(self) -> QWidget:
        rows = self.repository.list_optical_modules(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.optical_modules_note")
        return self._table_tab("details.optical_modules_note", OPTICAL_MODULE_COLUMNS, rows)

    def _lldp_tab(self) -> QWidget:
        rows = self.repository.list_lldp_neighbors(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.lldp_note")
        return self._table_tab("details.lldp_note", LLDP_COLUMNS, rows)

    def _table_tab(self, note_key: str, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]]) -> QWidget:
        table = QTableWidget(len(rows), len(columns))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setDefaultSectionSize(30)
        table.verticalHeader().setVisible(False)
        table.setHorizontalHeaderLabels([self.i18n.t(label_key) for label_key, _field in columns])
        for row_index, row in enumerate(rows):
            for column_index, (_label_key, field) in enumerate(columns):
                table.setItem(row_index, column_index, QTableWidgetItem(str(row.get(field) or "")))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setStretchLastSection(True)
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(self._note_label(note_key))
        layout.addWidget(table)
        return wrapper

    def _empty_tab(self, note_key: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self._note_label(note_key))
        label = QLabel(self.i18n.t("details.no_data_demo_hint"))
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _note_label(self, key: str) -> QLabel:
        label = QLabel(self.i18n.t(key))
        label.setWordWrap(True)
        return label

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()
        self.raise_()
        self.activateWindow()

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog, QWidget { background: #f7f8fa; color: #1f2933; font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
            QLabel { color: #1f2933; }
            QTabWidget::pane { background: #ffffff; border: 1px solid #cbd5df; top: -1px; }
            QTabBar::tab { background: #e9eef5; color: #1f2933; border: 1px solid #cbd5df; padding: 8px 16px; min-width: 92px; }
            QTabBar::tab:selected { background: #ffffff; color: #0f3d75; border-bottom: 1px solid #ffffff; font-weight: 600; }
            QTabBar::tab:!selected:hover { background: #f1f5fb; }
            QTableWidget { background: #ffffff; border: 1px solid #dde3ea; gridline-color: #edf1f5; selection-background-color: #dcecff; }
            QHeaderView::section { background: #f0f3f7; color: #1f2933; border: 0; border-right: 1px solid #dde3ea; border-bottom: 1px solid #dde3ea; padding: 6px; font-weight: 600; }
            QPushButton { background: #ffffff; border: 1px solid #cbd5df; border-radius: 4px; padding: 6px 10px; }
            QPushButton:hover { background: #eef5ff; border-color: #8bb7ee; }
            """
        )
