from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from netconsole.core.i18n import I18n
from netconsole.core.optical_severity_engine import compute_optical_severity
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.core.sources.switch_source import build_switch_data_lookup, compute_switch_status
from netconsole.services.trackside_ap_business import TRACKSIDE_AP_DEVICE_COLUMNS, build_trackside_ap_business_rows, format_trackside_display_value, trackside_row_status
from netconsole.services.device_web_service import build_https_url, effective_https_port, open_https_url
from netconsole.services.h3c_collect_service import CollectDeviceResult
from netconsole.services.h3c_optical_refresh_service import OpticalRefreshResult
from netconsole.ui.collect_worker import DeviceCollectThread
from netconsole.ui.dialogs.history_data_dialog import (
    HistoryDataDialog,
    INTERFACE_HISTORY_COLUMNS,
    LLDP_HISTORY_COLUMNS,
    OPTICAL_HISTORY_COLUMNS,
)
from netconsole.ui.optical_refresh_worker import OpticalRefreshThread
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, paginate_rows
from netconsole.ui.theme.contrast_engine import apply_status_item_contrast, status_background_color
from netconsole.ui.render.table_render_engine import set_table_column_fields
from netconsole.ui.table_utils import attach_table_context_menu, auto_resize_table_columns, configure_readonly_table, make_text_selectable
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.ui.window_manager import window_manager
from netconsole.utils.text_encoding import read_text_with_fallback


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

COLLECT_LOG_NOT_FOUND = "未找到采集日志"

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
    ("field.status", "status"),
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
    ("details.connector_type", "connector_type"),
    ("details.collected_at", "collected_at"),
)

OPTICAL_STATUS_VALUES = {"normal", "notice", "warning", "alarm", "link_abnormal", "no_light", "no_module", "skipped", "unknown"}

LLDP_COLUMNS = (
    ("details.local_interface", "local_interface"),
    ("details.neighbor_sysname", "neighbor_sysname"),
    ("details.neighbor_mac", "neighbor_mac"),
    ("details.neighbor_interface", "neighbor_interface"),
    ("details.collected_at", "collected_at"),
)


def _is_ac_device(device: Device) -> bool:
    return str(device.device_type or "").upper() == "AC"


def _login_protocol(device: Device) -> str:
    protocols = []
    if device.ssh_enabled:
        protocols.append("SSH")
    if device.telnet_enabled:
        protocols.append("Telnet")
    return "/".join(protocols) or "-"


def _has_optical_module_data(row: dict[str, object | None]) -> bool:
    module_fields = (
        "rx_power",
        "tx_power",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
        "rx_low_alarm",
        "rx_low_warning",
    )
    return any(row.get(field) not in (None, "") for field in module_fields)


class DeviceDetailDialog(QDialog):
    def __init__(
        self,
        i18n: I18n,
        repository: DeviceFactRepository,
        device: Device,
        parent=None,
        site_name: str = "demo",
        group_names: dict[int, str] | None = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.repository = repository
        self.device = device
        self.site_name = site_name
        self.group_names = dict(group_names or {})
        self.collect_thread: DeviceCollectThread | None = None
        self.history_dialogs: list[HistoryDataDialog] = []
        self.collect_log_dialogs: list[CollectLogDialog] = []
        self.optical_refresh_thread: OpticalRefreshThread | None = None
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setMinimumSize(720, 480)
        self.resize(800, 520)

        self.title_label = make_text_selectable(QLabel())
        self.always_on_top_button = QPushButton()
        self.refresh_button = QPushButton()
        self.refresh_optical_button = QPushButton()
        self.view_collect_log_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.refresh_button.clicked.connect(self.refresh_device_details)
        self.refresh_optical_button.clicked.connect(self.refresh_device_optical)
        self.view_collect_log_button.clicked.connect(self.view_collect_log)
        self.tabs = QTabWidget()
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        header.addWidget(self.refresh_optical_button)
        header.addWidget(self.view_collect_log_button)
        header.addWidget(self.always_on_top_button)
        layout.addLayout(header)
        layout.addWidget(self.tabs)
        self.retranslate()

    def retranslate(self) -> None:
        title = self.i18n.t("details.title_with_name", name=self.device.name)
        self.setWindowTitle(title)
        self.title_label.setText(title)
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self.refresh_optical_button.setText(self.i18n.t("details.refresh_optical"))
        self.view_collect_log_button.setText(self.i18n.t("details.view_collect_log"))
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))
        self.reload_tabs()

    def reload_tabs(self) -> None:
        self.tabs.clear()
        self.tabs.addTab(self._overview_tab(), self.i18n.t("details.overview"))
        self.tabs.addTab(self._interfaces_tab(), self.i18n.t("details.interfaces"))
        self.tabs.addTab(self._optical_modules_tab(), self.i18n.t("details.optical_modules"))
        self.tabs.addTab(self._lldp_tab(), self.i18n.t("details.lldp"))
        self.tabs.addTab(self._trackside_ap_business_tab(), self.i18n.t("trackside.title"))

    def refresh_device_details(self) -> None:
        if self.collect_thread is not None and self.collect_thread.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText(self.i18n.t("details.refreshing"))
        self.collect_thread = DeviceCollectThread(self.device, self.site_name, parent=self)
        self.collect_thread.collect_finished.connect(self._collect_finished)
        self.collect_thread.collect_failed.connect(self._collect_failed)
        self.collect_thread.finished.connect(self.collect_thread.deleteLater)
        self.collect_thread.finished.connect(lambda: setattr(self, "collect_thread", None))
        self.collect_thread.start()

    def _collect_finished(self, result: CollectDeviceResult) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self.reload_tabs()
        if result.success and result.error_message:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_partial"))
        elif result.success:
            QMessageBox.information(self, self.windowTitle(), self.i18n.t("details.refresh_done"))
        else:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_failed", error=result.error_message or "unknown"))

    def _collect_failed(self, error_message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_failed", error=error_message))

    def refresh_device_optical(self) -> None:
        if self.optical_refresh_thread is not None and self.optical_refresh_thread.isRunning():
            return
        self.refresh_optical_button.setEnabled(False)
        self.refresh_optical_button.setText(self.i18n.t("details.refreshing_optical"))
        self.optical_refresh_thread = OpticalRefreshThread(self.device, self.site_name, parent=self)
        self.optical_refresh_thread.refresh_finished.connect(self._optical_refresh_finished)
        self.optical_refresh_thread.refresh_failed.connect(self._optical_refresh_failed)
        self.optical_refresh_thread.finished.connect(self.optical_refresh_thread.deleteLater)
        self.optical_refresh_thread.finished.connect(lambda: setattr(self, "optical_refresh_thread", None))
        self.optical_refresh_thread.start()

    def _optical_refresh_finished(self, result: OpticalRefreshResult) -> None:
        self.refresh_optical_button.setEnabled(True)
        self.refresh_optical_button.setText(self.i18n.t("details.refresh_optical"))
        self.reload_tabs()
        if result.success and result.error_message:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_optical_partial"))
        elif result.success:
            QMessageBox.information(self, self.windowTitle(), self.i18n.t("details.refresh_optical_done"))
        else:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_optical_failed", error=result.error_message or "unknown"))

    def _optical_refresh_failed(self, error_message: str) -> None:
        self.refresh_optical_button.setEnabled(True)
        self.refresh_optical_button.setText(self.i18n.t("details.refresh_optical"))
        QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.refresh_optical_failed", error=error_message))

    def _overview_tab(self) -> QWidget:
        fact = self.repository.get_device_fact(str(self.device.device_uuid or ""))
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self._note_label("details.overview_note"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)
        for label_key, value_text in self._device_overview_rows():
            value = QLabel(value_text)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(self.i18n.t(label_key), value)
        if _is_ac_device(self.device):
            self._add_ac_web_rows(form)
        if fact:
            for label_key, field in OVERVIEW_FIELDS:
                value = QLabel(str(fact.get(field) or ""))
                value.setWordWrap(True)
                value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(self.i18n.t(label_key), value)
        layout.addStretch(1)
        return widget

    def _device_overview_rows(self) -> list[tuple[str, str]]:
        return [
            ("field.name", str(self.device.name or "")),
            ("field.sysname", str(self.device.sysname or "")),
            ("groups.group", self.group_names.get(int(self.device.group_id), self.i18n.t("groups.ungrouped")) if self.device.group_id else self.i18n.t("groups.ungrouped")),
            ("field.device_type", str(self.device.device_type or "")),
            ("field.station", str(self.device.station or "")),
            ("field.ip_address", str(self.device.ip_address or "")),
            ("field.ssh_port", str(self.device.ssh_port or "")),
            ("details.login_protocol", _login_protocol(self.device)),
            ("field.remark", str(self.device.remark or "")),
            ("field.updated_at", str(self.device.updated_at or "")),
        ]

    def _add_ac_web_rows(self, form: QFormLayout) -> None:
        port, source = effective_https_port(self.device.https_port)
        url = build_https_url(self.device.ip_address, port)
        port_text = str(port) if source == "device" else self.i18n.t("ac.https_port_default", port=port)
        for label_key, text in (("field.https_port", port_text), ("details.web_address", url or self.i18n.t("common.not_collected"))):
            value = QLabel(text)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(self.i18n.t(label_key), value)
        button = QPushButton(self.i18n.t("ac.open_web"))
        button.setEnabled(url is not None)
        button.clicked.connect(self.open_device_web)
        form.addRow("", button)

    def open_device_web(self) -> None:
        port, _source = effective_https_port(self.device.https_port)
        if not build_https_url(self.device.ip_address, port):
            QMessageBox.information(self, self.windowTitle(), self.i18n.t("ac.https_port_not_collected"))
            return
        if not open_https_url(self.device.ip_address, port):
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("ac.open_web_failed"))

    def view_collect_log(self) -> None:
        try:
            path, text = self._load_collect_log()
        except FileNotFoundError:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("details.collect_log_not_found"))
            return
        dialog = CollectLogDialog(self.i18n.t("details.collect_log_title"), str(path), text, self)
        self.collect_log_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._remove_collect_log_dialog(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _load_collect_log(self) -> tuple[Path, str]:
        raw_log_path = self.repository.get_latest_raw_log_path(str(self.device.device_uuid or ""))
        return read_collect_log_text(raw_log_path, PathResolver().get_site_root(self.site_name))

    def _interfaces_tab(self) -> QWidget:
        rows = self.repository.list_device_interfaces(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.interfaces_note")
        optical_status_by_interface = {
            str(item.get("interface_name") or ""): str(item.get("status") or "")
            for item in self._computed_optical_rows(self.repository.list_optical_modules(str(self.device.device_uuid or "")), rows)
        }
        return self._table_tab("details.interfaces_note", INTERFACE_COLUMNS, rows, "description", "interface", optical_status_by_interface)

    def _optical_modules_tab(self) -> QWidget:
        device_uuid = str(self.device.device_uuid or "")
        rows = self._computed_optical_rows(self.repository.list_optical_modules(device_uuid), self.repository.list_device_interfaces(device_uuid))
        if not rows:
            return self._empty_tab("details.optical_modules_note")
        return self._table_tab("details.optical_modules_note", OPTICAL_MODULE_COLUMNS, rows, "module_model", "optical")

    def _computed_optical_rows(
        self,
        rows: list[dict[str, object | None]],
        interfaces: list[dict[str, object | None]] | None = None,
    ) -> list[dict[str, object | None]]:
        interfaces_by_name = {str(row.get("interface_name") or ""): row for row in interfaces or []}
        computed_rows: list[dict[str, object | None]] = []
        for row in rows:
            interface = interfaces_by_name.get(str(row.get("interface_name") or ""), {})
            computed = dict(row)
            result = compute_optical_severity(
                {
                    "module_present": _has_optical_module_data(row),
                    "switch_rx_power": row.get("rx_power"),
                    "switch_port_status": row.get("port_status") or interface.get("link_status"),
                    "alarm_low": row.get("rx_low_alarm"),
                    "alarm_high": row.get("rx_high_alarm"),
                    "warning_low": row.get("rx_low_warning"),
                    "device_type": "switch",
                }
            )
            computed["status"] = result.severity
            computed_rows.append(computed)
        return computed_rows

    def _lldp_tab(self) -> QWidget:
        rows = self.repository.list_lldp_neighbors(str(self.device.device_uuid or ""))
        if not rows:
            return self._empty_tab("details.lldp_note")
        return self._table_tab("details.lldp_note", LLDP_COLUMNS, rows, "neighbor_sysname", "lldp")

    def _trackside_ap_business_tab(self) -> QWidget:
        device_uuid = str(self.device.device_uuid or "")
        optical_modules = self.repository.list_optical_modules(device_uuid)
        lookup = build_switch_data_lookup([self.device], {device_uuid: optical_modules})
        rows = build_trackside_ap_business_rows(
            [self.device],
            {device_uuid: self.repository.list_device_interfaces(device_uuid)},
            {device_uuid: optical_modules},
            AcRepository(self.repository.database).list_all_fit_ap_optical(),
            {device_uuid: self.repository.list_lldp_neighbors(device_uuid)},
            AcRepository(self.repository.database).list_all_fit_ap_resources_with_metadata(),
            lookup,
        )
        if not rows:
            return self._empty_tab("trackside.note")
        return self._table_tab("trackside.note", TRACKSIDE_AP_DEVICE_COLUMNS, rows, "description", "trackside")

    def _table_tab(
        self,
        note_key: str,
        columns: tuple[tuple[str, str], ...],
        rows: list[dict[str, object | None]],
        stretch_field: str,
        history_kind: str,
        optical_status_by_interface: dict[str, str] | None = None,
    ) -> QWidget:
        table = QTableWidget(0, len(columns))
        set_table_column_fields(table, [field for _label_key, field in columns])
        configure_readonly_table(table)
        table.setHorizontalHeaderLabels([self.i18n.t(label_key) for label_key, _field in columns])
        page_state = {"page": 1, "page_size": DEFAULT_PAGE_SIZE, "visible_rows": []}
        pagination = PaginationWidget(self.i18n)

        def render() -> None:
            visible_rows, state = paginate_rows(rows, int(page_state["page_size"]), int(page_state["page"]))
            page_state["page"] = state.current_page
            page_state["visible_rows"] = visible_rows
            pagination.set_state(state)
            table.setUpdatesEnabled(False)
            table.setSortingEnabled(False)
            table.setRowCount(len(visible_rows))
            for row_index, row in enumerate(visible_rows):
                row_status = str(row.get("status") or "")
                if history_kind == "interface":
                    row_status = (optical_status_by_interface or {}).get(str(row.get("interface_name") or ""), "")
                elif history_kind == "trackside":
                    row_status = trackside_row_status(row)
                for column_index, (_label_key, field) in enumerate(columns):
                    value = (
                        format_trackside_display_value(field, row, self.i18n.language)
                        if history_kind == "trackside"
                        else self._format_table_value(field, row.get(field))
                    )
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignCenter)
                    self._apply_status_background(item, history_kind, row_status)
                    table.setItem(row_index, column_index, item)
            table.setSortingEnabled(False)
            table.setUpdatesEnabled(True)
            auto_resize_table_columns(table)

        def open_paged_history(row: int, kind=history_kind) -> None:
            visible_rows = page_state["visible_rows"]
            if 0 <= row < len(visible_rows):
                self.open_history_data(kind, visible_rows[row])

        attach_table_context_menu(table, self.i18n.language, history_callback=open_paged_history, include_history=history_kind in {"interface", "optical", "lldp"})
        pagination.pageChanged.connect(lambda page: (page_state.__setitem__("page", page), render()))
        pagination.pageSizeChanged.connect(lambda size: (page_state.__setitem__("page_size", size), page_state.__setitem__("page", 1), render()))
        _ = stretch_field
        render()
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(self._note_label(note_key))
        if history_kind == "interface":
            layout.addWidget(self._note_label("details.interface_color_note"))
        elif history_kind == "optical":
            layout.addWidget(self._note_label("details.optical_color_legend"))
        layout.addWidget(table, 1)
        layout.addWidget(pagination)
        return wrapper

    def _format_table_value(self, field: str, value: object | None) -> str:
        if field in {"status", "switch_optical_status", "ap_optical_status"} and value in OPTICAL_STATUS_VALUES:
            return self.i18n.t(f"optical.status.{value}")
        return str(value or "")

    @staticmethod
    def optical_status_color(status: object | None) -> str | None:
        return status_background_color(status)

    @staticmethod
    def interface_row_status_color(status: object | None) -> str | None:
        return status_background_color(status) if status in {"link_abnormal", "no_light", "alarm", "warning", "notice"} else None

    @staticmethod
    def _apply_status_background(item: QTableWidgetItem, history_kind: str, status: object | None) -> None:
        if history_kind == "optical":
            color_value = DeviceDetailDialog.optical_status_color(status)
        elif history_kind == "interface":
            color_value = DeviceDetailDialog.interface_row_status_color(status)
        elif history_kind == "trackside":
            color_value = DeviceDetailDialog.optical_status_color(status)
        else:
            return
        if color_value is not None:
            apply_status_item_contrast(item, status)

    def open_history_data(self, history_kind: str, row: dict[str, object | None]) -> HistoryDataDialog:
        device_uuid = str(self.device.device_uuid or "")
        if history_kind == "interface":
            object_name = str(row.get("interface_name") or "")
            rows = self.repository.list_interface_history(device_uuid, object_name)
            columns = INTERFACE_HISTORY_COLUMNS
        elif history_kind == "optical":
            object_name = str(row.get("interface_name") or "")
            rows = self.repository.list_optical_history(device_uuid, object_name)
            columns = OPTICAL_HISTORY_COLUMNS
        elif history_kind == "lldp":
            object_name = str(row.get("local_interface") or "")
            rows = self.repository.list_lldp_history(device_uuid, object_name)
            columns = LLDP_HISTORY_COLUMNS
        else:
            raise ValueError(f"Unsupported history kind: {history_kind}")
        dialog = HistoryDataDialog(self.i18n, self.device.name, object_name, columns, rows, self)
        self.history_dialogs.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._remove_history_dialog(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _remove_history_dialog(self, dialog: HistoryDataDialog) -> None:
        if dialog in self.history_dialogs:
            self.history_dialogs.remove(dialog)

    def _remove_collect_log_dialog(self, dialog: "CollectLogDialog") -> None:
        if dialog in self.collect_log_dialogs:
            self.collect_log_dialogs.remove(dialog)

    def _empty_tab(self, note_key: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self._note_label(note_key))
        label = QLabel(self.i18n.t("details.no_data_demo_hint"))
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        make_text_selectable(label)
        layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _note_label(self, key: str) -> QLabel:
        label = QLabel(self.i18n.t(key))
        label.setWordWrap(True)
        make_text_selectable(label)
        return label

    def set_always_on_top(self, enabled: bool) -> None:
        window_manager.set_child_on_top(self, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.raise_()
        self.activateWindow()

class CollectLogDialog(QDialog):
    def __init__(self, title: str, raw_log_path: str, text: str, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.matches: list[tuple[int, int]] = []
        self.current_match_index = -1
        self._plain_text = text
        self._folded_text = text.casefold()
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.resize(900, 640)
        self.path_label = make_text_selectable(QLabel(raw_log_path))
        self.path_label.setWordWrap(True)
        self.copy_button = QPushButton("Copy Log")
        self.export_button = QPushButton("Export Log")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search")
        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.clear_button = QPushButton("Clear")
        self.close_button = QPushButton("Close")
        self.count_label = make_text_selectable(QLabel("0 / 0"))
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(text)
        self.copy_button.clicked.connect(self.copy_log)
        self.export_button.clicked.connect(self.export_log)
        self.search_input.textChanged.connect(self.update_search)
        self.previous_button.clicked.connect(self.find_previous)
        self.next_button.clicked.connect(self.find_next)
        self.clear_button.clicked.connect(self.clear_search)
        self.close_button.clicked.connect(self.close)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.previous_button)
        toolbar.addWidget(self.next_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.count_label)
        toolbar.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addLayout(toolbar)
        layout.addWidget(self.text_edit, 1)

    def copy_log(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())

    def export_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), "collect_log.txt", "Text Files (*.txt);;All Files (*.*)")
        if path:
            Path(path).write_text(self.text_edit.toPlainText(), encoding="utf-8")

    def focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def update_search(self) -> None:
        query = self.search_input.text()
        self.matches = collect_search_matches(self._plain_text, query, self._folded_text)
        self.current_match_index = 0 if self.matches else -1
        self._apply_search_highlights()
        self._select_current_match()
        self._update_count_label()

    def find_next(self) -> None:
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.matches)
        self._apply_search_highlights()
        self._select_current_match()
        self._update_count_label()

    def find_previous(self) -> None:
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.matches)
        self._apply_search_highlights()
        self._select_current_match()
        self._update_count_label()

    def clear_search(self) -> None:
        self.search_input.clear()
        self.matches = []
        self.current_match_index = -1
        self.text_edit.setExtraSelections([])
        self._update_count_label()

    def _apply_search_highlights(self) -> None:
        selections = []
        for index, (start, length) in enumerate(self.matches):
            cursor = QTextCursor(self.text_edit.document())
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#facc15" if index != self.current_match_index else "#fb923c"))
            selection.format = fmt
            selections.append(selection)
        self.text_edit.setExtraSelections(selections)

    def _select_current_match(self) -> None:
        if self.current_match_index < 0:
            return
        start, length = self.matches[self.current_match_index]
        cursor = self.text_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.KeepAnchor)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()

    def _update_count_label(self) -> None:
        current = self.current_match_index + 1 if self.current_match_index >= 0 else 0
        self.count_label.setText(f"{current} / {len(self.matches)}")


def collect_search_matches(text: str, query: str, folded_text: str | None = None) -> list[tuple[int, int]]:
    if not query:
        return []
    haystack = folded_text if folded_text is not None else text.casefold()
    needle = query.casefold()
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        matches.append((index, len(query)))
        start = index + max(1, len(query))
    return matches


def read_collect_log_text(raw_log_path: str | None, site_root: Path | None = None) -> tuple[Path, str]:
    if not raw_log_path:
        raise FileNotFoundError(COLLECT_LOG_NOT_FOUND)
    path = Path(raw_log_path)
    if not path.is_absolute() and site_root is not None:
        path = site_root / path
    if not path.is_file():
        raise FileNotFoundError(COLLECT_LOG_NOT_FOUND)
    return path, read_text_with_fallback(path)


def _column_index(columns: tuple[tuple[str, str], ...], field: str) -> int | None:
    for index, (_label_key, column_field) in enumerate(columns):
        if column_field == field:
            return index
    return None


def _column_min_widths(columns: tuple[tuple[str, str], ...]) -> dict[int, int]:
    widths = {
        "interface_name": 180,
        "local_interface": 180,
        "neighbor_interface": 180,
        "neighbor_sysname": 160,
        "neighbor_mac": 150,
        "module_model": 180,
        "module_serial_number": 180,
        "description": 180,
    }
    return {index: widths[field] for index, (_label_key, field) in enumerate(columns) if field in widths}
