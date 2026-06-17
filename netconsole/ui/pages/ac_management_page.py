from __future__ import annotations

import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.fit_ap_import_export import FitApImportExportService, make_fit_ap_export_filename
from netconsole.ui.ac_collect_worker import AcResourceCollectThread, FitApOpticalCollectThread
from netconsole.ui.dialogs.fit_ap_detail_dialog import FitApDetailDialog
from netconsole.ui.dialogs.station_online_history_dialog import StationOnlineHistoryDialog
from netconsole.ui.table_utils import auto_resize_table_columns, create_table_context_menu, configure_readonly_table, make_text_selectable
from netconsole.utils.interface_sort import interface_sort_key
from netconsole.utils.optical_status import display_optical_status


CHECK_COLUMN = 0
SUMMARY_FIELDS = (
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("details.software_version", "software_version"),
    ("ac.total_aps", "total_aps"),
    ("ac.online_aps", "online_aps"),
    ("ac.offline_aps", "offline_aps"),
    ("ac.ap_licenses", "total_ap_licenses"),
    ("ac.local_ap_licenses", "local_ap_licenses"),
    ("ac.remaining_local_ap_licenses", "remaining_local_ap_licenses"),
    ("ac.cpu_usage", "cpu_usage"),
    ("ac.memory_usage", "memory_usage"),
    ("field.updated_at", "updated_at"),
)

FIT_AP_RESOURCE_COLUMNS = (
    ("", "select"),
    ("ac.ap_name", "ap_name"),
    ("APID", "apid"),
    ("field.ip_address", "ap_ip"),
    ("field.mac_address", "ap_mac"),
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("field.status", "state_display"),
    ("ac.group_name", "group_name"),
    ("ac.online_time", "online_time"),
    ("field.updated_at", "updated_at"),
)

FIT_AP_OPTICAL_COLUMNS = (
    ("ac.ap_name", "ap_name"),
    ("ac.ap_mac", "ap_mac"),
    ("ac.station", "site"),
    ("ac.indoor_switch", "neighbor_device_name"),
    ("ac.indoor_port", "neighbor_interface"),
    ("ac.indoor_switch_rx_power", "neighbor_rx_power"),
    ("ac.ap_side_rx_power", "rx_power"),
    ("ap.optical_alarm_status", "optical_alarm_status"),
    ("field.updated_at", "updated_at"),
)

FIT_AP_OPTICAL_DETAIL_COLUMNS = (
    ("ac.ap_name", "ap_name"),
    ("field.ip_address", "ap_ip"),
    ("ac.site", "site"),
    ("ac.lldp_neighbor", "lldp_neighbor"),
    ("ap.neighbor_interface", "neighbor_interface"),
    ("ap.neighbor_mac", "neighbor_mac"),
    ("ap.neighbor_device_name", "neighbor_device_name"),
    ("ap.neighbor_rx_power", "neighbor_rx_power"),
    ("ap.interface", "interface_name"),
    ("ap.temperature", "temperature"),
    ("ap.tx_power", "tx_power"),
    ("ap.rx_power", "rx_power"),
    ("ap.optical_alarm_status", "optical_alarm_status"),
    ("field.updated_at", "updated_at"),
    ("field.status", "status"),
    ("ac.error_message", "error_message"),
)

OPTICAL_STATUS_COLORS = {
    "normal": "#dcfce7",
    "warning": "#fef9c3",
    "alarm": "#fee2e2",
    "link_abnormal": "#ffe4e6",
    "no_light": "#e5e7eb",
}
OPTICAL_EXPORT_COLOR_RGB = {
    "normal": "DCFCE7",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "no_light": "E5E7EB",
    "skipped": "F3F4F6",
}
OPTICAL_STATUS_SEVERITY = {"unknown": 0, "skipped": 1, "normal": 2, "no_light": 3, "warning": 4, "link_abnormal": 5, "alarm": 6}
OPTICAL_STATUS_FILTERS = ("", "normal", "warning", "alarm", "link_abnormal", "no_light", "skipped", "unknown")
AP_ONLINE_OVERVIEW_COLUMNS = (
    ("ac.station", "site"),
    ("ac.ap_total", "total"),
    ("ac.online", "online"),
    ("ac.offline", "offline"),
    ("ac.online_rate", "online_rate"),
    ("field.remark", "remark"),
)
AC_TAB_STYLESHEET = """
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
QTabBar::tab:!selected {
    background: #e5e7eb;
    color: #111827;
}
"""


def sort_fit_ap_optical_rows(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    def key(row: dict[str, object | None]) -> tuple[int, str, tuple[object, ...], str]:
        name = str(row.get("neighbor_device_name") or "").strip()
        missing_name = 1 if name in {"", "-"} else 0
        return (missing_name, name.casefold(), interface_sort_key(row.get("neighbor_interface")), str(row.get("ap_name") or ""))

    return sorted(rows, key=key)


def enrich_fit_ap_optical_rows(rows: list[dict[str, object | None]], resources: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    resources_by_uuid = {str(row.get("ap_uuid") or ""): row for row in resources if row.get("ap_uuid")}
    resources_by_name = {str(row.get("ap_name") or ""): row for row in resources if row.get("ap_name")}
    result: list[dict[str, object | None]] = []
    for row in rows:
        resource = resources_by_uuid.get(str(row.get("ap_uuid") or "")) or resources_by_name.get(str(row.get("ap_name") or ""), {})
        result.append(
            {
                **row,
                "ap_mac": row.get("ap_mac") or resource.get("ap_mac"),
                "site": row.get("site") or resource.get("site_name") or resource.get("site") or "未归属",
                "neighbor_device_name": None if _is_invalid_neighbor_text(row.get("neighbor_device_name")) else row.get("neighbor_device_name"),
            }
        )
    return result


def filter_fit_ap_optical_rows(rows: list[dict[str, object | None]], filters: dict[str, object | None]) -> list[dict[str, object | None]]:
    text_fields = ("ap_name", "site")
    result = rows
    for field in text_fields:
        needle = str(filters.get(field) or "").strip().casefold()
        if needle:
            result = [row for row in result if needle in str(row.get(field) or "").casefold()]
    status = str(filters.get("optical_alarm_status") or "").strip()
    if status:
        result = [row for row in result if evaluate_fit_ap_row_status(row) == status]
    return result


def build_site_filter_items(rows: list[dict[str, object | None]], all_label: str) -> list[tuple[str, str]]:
    sites = sorted({str(row.get("site") or "").strip() for row in rows if str(row.get("site") or "").strip()})
    return [(all_label, ""), *[(site, site) for site in sites]]


def build_ap_online_overview_rows(
    rows: list[dict[str, object | None]],
    optical_rows: list[dict[str, object | None]] | None = None,
    capacities: dict[str, object] | None = None,
) -> list[dict[str, object | None]]:
    optical_by_uuid = {str(row.get("ap_uuid") or ""): row for row in optical_rows or [] if row.get("ap_uuid")}
    optical_by_name = {str(row.get("ap_name") or ""): row for row in optical_rows or [] if row.get("ap_name")}
    capacities = capacities or {}
    grouped: dict[str, dict[str, object | None]] = {}
    seen: set[str] = set()
    for row in rows:
        unique_key = _ap_unique_key(row)
        if unique_key in seen:
            continue
        seen.add(unique_key)
        optical = optical_by_uuid.get(str(row.get("ap_uuid") or "")) or optical_by_name.get(str(row.get("ap_name") or ""), {})
        site = str(optical.get("site") or row.get("site_name") or row.get("site") or "").strip() or "未归属"
        item = grouped.setdefault(site, {"site": site, "total": 0, "online": 0, "offline": 0})
        item["total"] = int(item["total"] or 0) + 1
        if is_fit_ap_online(row):
            item["online"] = int(item["online"] or 0) + 1
    result = []
    for row in sorted(grouped.values(), key=lambda item: str(item.get("site") or "")):
        site = str(row.get("site") or "")
        online = int(row.get("online") or 0)
        total, remark = _capacity_total_remark(capacities.get(site), online)
        row["total"] = total
        row["offline"] = max(total - online, 0)
        row["remark"] = remark
        result.append(_with_online_rate(row))
    total = sum(int(row.get("total") or 0) for row in result)
    online = sum(int(row.get("online") or 0) for row in result)
    offline = total - online
    return [*result, _with_online_rate({"site": "合计", "total": total, "online": online, "offline": offline, "remark": ""})]


def is_fit_ap_online(row: dict[str, object | None]) -> bool:
    state = str(row.get("state") or row.get("state_raw") or row.get("state_display") or "").strip().upper()
    return state in {"R", "R/M", "R/B"}


def export_ap_online_overview_xlsx(path: Path, rows: list[dict[str, object | None]], headers: list[str]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "AP Online Overview"
    alignment = Alignment(horizontal="center", vertical="center")
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = alignment
    sheet.freeze_panes = "A2"
    for row in rows:
        sheet.append([_display_value(row.get(field)) for _key, field in AP_ONLINE_OVERVIEW_COLUMNS])
        fill = _overview_row_fill(row)
        for cell in sheet[sheet.max_row]:
            cell.alignment = alignment
            if fill:
                cell.fill = fill
        if int(row.get("offline") or 0) > 0:
            sheet.cell(sheet.max_row, 4).fill = PatternFill(fill_type="solid", fgColor="FEE2E2")
    _auto_width_sheet(sheet)
    workbook.save(path)


def evaluate_fit_ap_row_status(row: dict[str, object | None], neighbor_optical: dict[str, object | None] | None = None) -> str:
    local_status = str(row.get("optical_alarm_status") or "unknown")
    neighbor_status = _evaluate_neighbor_status(row.get("neighbor_rx_power"), neighbor_optical)
    return local_status if OPTICAL_STATUS_SEVERITY.get(local_status, 0) >= OPTICAL_STATUS_SEVERITY.get(neighbor_status, 0) else neighbor_status


def export_fit_ap_optical_xlsx(path: Path, rows: list[dict[str, object | None]], columns: tuple[tuple[str, str], ...], headers: list[str], legend: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "FIT-AP Optical"
    alignment = Alignment(horizontal="center", vertical="center")
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = alignment
    sheet.freeze_panes = "A2"
    for row in rows:
        status = evaluate_fit_ap_row_status(row)
        sheet.append([display_optical_status(status) if field == "optical_alarm_status" else _display_value(row.get(field)) for _key, field in columns])
        color = OPTICAL_EXPORT_COLOR_RGB.get(status)
        fill = PatternFill(fill_type="solid", fgColor=color) if color else None
        for cell in sheet[sheet.max_row]:
            cell.alignment = alignment
            if fill:
                cell.fill = fill
    _auto_width_sheet(sheet)
    legend_sheet = workbook.create_sheet("说明")
    legend_sheet["A1"] = legend
    legend_sheet["A1"].alignment = Alignment(wrap_text=True)
    workbook.save(path)


def make_fit_ap_optical_export_filename(site_name: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M")
    safe_site = "".join(char if char not in '<>:"/\\|?*' else "_" for char in site_name or "site")
    return f"{safe_site}_FIT-AP光衰_{stamp}.xlsx"


def _evaluate_neighbor_status(rx_power: object, neighbor_optical: dict[str, object | None] | None) -> str:
    if neighbor_optical:
        from netconsole.parsers.h3c.transceiver_parser import evaluate_optical_status

        return str(evaluate_optical_status(neighbor_optical, None).get("status") or "unknown")
    value = _to_float(rx_power)
    if value is not None and value <= -35:
        return "no_light"
    if value is not None:
        return "normal"
    return "unknown"


def _to_float(value: object) -> float | None:
    import re

    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _display_value(value: object) -> str:
    return str(value) if value not in (None, "") else "-"


def _ap_unique_key(row: dict[str, object | None]) -> str:
    for field in ("ap_uuid", "serial_number", "ap_mac"):
        value = str(row.get(field) or "").strip()
        if value:
            return f"{field}:{value.casefold()}"
    return f"row:{id(row)}"


def _capacity_total_remark(value: object, default_total: int) -> tuple[int, str]:
    if isinstance(value, dict):
        return int(value.get("ap_total") or value.get("total") or default_total), str(value.get("remark") or "")
    if value is None:
        return default_total, ""
    return int(value), ""


def _is_invalid_neighbor_text(value: object) -> bool:
    text = str(value or "")
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in ("Nearest", "Chassis ID", "Default", "customer bridge", "nontpmr"))


def _with_online_rate(row: dict[str, object | None]) -> dict[str, object | None]:
    total = int(row.get("total") or 0)
    online = int(row.get("online") or 0)
    row["online_rate"] = f"{online / total:.1%}" if total else "0.0%"
    return row


def _overview_row_fill(row: dict[str, object | None]):
    from openpyxl.styles import PatternFill

    if str(row.get("site") or "") == "合计":
        return PatternFill(fill_type="solid", fgColor="DBEAFE")
    total = int(row.get("total") or 0)
    online = int(row.get("online") or 0)
    if total and online == total:
        return PatternFill(fill_type="solid", fgColor="DCFCE7")
    if total and online / total < 0.8:
        return PatternFill(fill_type="solid", fgColor="FEF9C3")
    return None


def _auto_width_sheet(sheet) -> None:
    from openpyxl.utils import get_column_letter

    for column_index in range(1, sheet.max_column + 1):
        max_length = 0
        for cell in sheet[get_column_letter(column_index)]:
            max_length = max(max_length, len(str(cell.value or "")))
        sheet.column_dimensions[get_column_letter(column_index)].width = min(max_length + 2, 48)


class AcManagementPage(QWidget):
    def __init__(self, device_repository: DeviceRepository, i18n: I18n, site_name: str = "demo") -> None:
        super().__init__()
        self.device_repository = device_repository
        self.repository = AcRepository(device_repository.database)
        self.import_export_service = FitApImportExportService(self.repository)
        self.i18n = i18n
        self.site_name = site_name
        self.ac_devices: list[Device] = []
        self.resource_thread: AcResourceCollectThread | None = None
        self.optical_thread: FitApOpticalCollectThread | None = None
        self.detail_windows: list[FitApDetailDialog] = []
        self.optical_rows: list[dict[str, object | None]] = []
        self._updating_online_summary = False

        self.device_combo = QComboBox()
        self.open_web_button = QPushButton()
        self.refresh_button = QPushButton()
        self.status_label = make_text_selectable(QLabel())
        self.summary_labels: dict[str, QLabel] = {field: make_text_selectable(QLabel("-")) for _key, field in SUMMARY_FIELDS}
        self.tabs = QTabWidget()
        self.resources_table = QTableWidget()
        self.batch_delete_button = QPushButton()
        self.batch_edit_button = QPushButton()
        self.import_button = QPushButton()
        self.export_button = QPushButton()
        self.clear_selection_button = QPushButton()
        self.invert_selection_button = QPushButton()
        self.selection_label = make_text_selectable(QLabel())
        self.optical_table = QTableWidget()
        self.refresh_optical_button = QPushButton()
        self.optical_concurrency_combo = QComboBox()
        self.optical_export_button = QPushButton()
        self.clear_optical_filters_button = QPushButton()
        self.optical_ap_filter = QLineEdit()
        self.optical_site_filter = QComboBox()
        self.optical_alarm_filter = QComboBox()
        self.overview_table = QTableWidget()
        self.export_overview_button = QPushButton()
        self.save_overview_history_button = QPushButton()
        self.view_overview_history_button = QPushButton()
        self.optical_legend_label = make_text_selectable(QLabel())
        self.coming_soon_label = make_text_selectable(QLabel())

        configure_readonly_table(self.resources_table)
        configure_readonly_table(self.optical_table)
        configure_readonly_table(self.overview_table)
        self.overview_table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.resources_table.setColumnCount(len(FIT_AP_RESOURCE_COLUMNS))
        self.optical_table.setColumnCount(len(FIT_AP_OPTICAL_COLUMNS))
        self.overview_table.setColumnCount(len(AP_ONLINE_OVERVIEW_COLUMNS))
        self.tabs.setStyleSheet(AC_TAB_STYLESHEET)
        self.overview_table.itemChanged.connect(self.save_overview_total)
        self.resources_table.horizontalHeader().sectionClicked.connect(self._resource_header_clicked)
        self.resources_table.itemChanged.connect(self.update_selection_state)
        self.resources_table.doubleClicked.connect(lambda index: self.open_ap_detail(index.row()))
        self.resources_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.resources_table.customContextMenuRequested.connect(self.show_resource_context_menu)
        self.optical_table.doubleClicked.connect(lambda index: self.open_ap_detail_from_optical(index.row()))
        self.optical_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.optical_table.customContextMenuRequested.connect(self.show_optical_context_menu)

        top = QHBoxLayout()
        top.addWidget(self.device_combo, 1)
        top.addWidget(self.open_web_button)
        top.addWidget(self.status_label)

        summary = QGridLayout()
        for index, (key, field) in enumerate(SUMMARY_FIELDS):
            label = QLabel()
            label.setObjectName(f"summary_label_{field}")
            label.setProperty("translation_key", key)
            make_text_selectable(label)
            summary.addWidget(label, index // 4 * 2, index % 4)
            summary.addWidget(self.summary_labels[field], index // 4 * 2 + 1, index % 4)

        resources_tab = QWidget()
        resources_layout = QVBoxLayout()
        resource_actions = QHBoxLayout()
        for button in (
            self.refresh_button,
            self.batch_delete_button,
            self.batch_edit_button,
            self.import_button,
            self.export_button,
            self.clear_selection_button,
            self.invert_selection_button,
        ):
            resource_actions.addWidget(button)
        resource_actions.addWidget(self.selection_label)
        resource_actions.addStretch(1)
        resources_layout.addLayout(resource_actions)
        resources_layout.addWidget(self.resources_table)
        resources_tab.setLayout(resources_layout)

        optical_tab = QWidget()
        optical_layout = QVBoxLayout()
        optical_actions = QHBoxLayout()
        optical_actions.addWidget(self.refresh_optical_button)
        optical_actions.addWidget(self.optical_concurrency_combo)
        optical_actions.addWidget(self.optical_export_button)
        optical_actions.addWidget(self.clear_optical_filters_button)
        optical_actions.addStretch(1)
        optical_filters = QHBoxLayout()
        for widget in (
            self.optical_ap_filter,
            self.optical_site_filter,
            self.optical_alarm_filter,
        ):
            optical_filters.addWidget(widget)
        self.optical_legend_label.setWordWrap(True)
        optical_layout.addLayout(optical_actions)
        optical_layout.addLayout(optical_filters)
        optical_layout.addWidget(self.optical_legend_label)
        optical_layout.addWidget(self.optical_table)
        optical_tab.setLayout(optical_layout)

        overview_tab = QWidget()
        overview_layout = QVBoxLayout()
        overview_actions = QHBoxLayout()
        overview_actions.addWidget(self.export_overview_button)
        overview_actions.addWidget(self.save_overview_history_button)
        overview_actions.addWidget(self.view_overview_history_button)
        overview_actions.addStretch(1)
        overview_layout.addLayout(overview_actions)
        overview_layout.addWidget(self.overview_table)
        overview_tab.setLayout(overview_layout)

        mr_tab = QWidget()
        mr_layout = QVBoxLayout()
        self.coming_soon_label.setAlignment(Qt.AlignCenter)
        mr_layout.addWidget(self.coming_soon_label, 1)
        mr_tab.setLayout(mr_layout)

        self.tabs.addTab(resources_tab, "")
        self.tabs.addTab(optical_tab, "")
        self.tabs.addTab(overview_tab, "")
        self.tabs.addTab(mr_tab, "")

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(summary)
        layout.addWidget(self.tabs, 1)
        self.setLayout(layout)

        self.device_combo.currentIndexChanged.connect(self.refresh_data)
        self.open_web_button.clicked.connect(self.open_web)
        self.refresh_button.clicked.connect(self.refresh_ac_resources)
        self.batch_delete_button.clicked.connect(self.batch_delete_aps)
        self.batch_edit_button.clicked.connect(self.batch_edit_site)
        self.import_button.clicked.connect(self.import_metadata)
        self.export_button.clicked.connect(self.export_aps)
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.invert_selection_button.clicked.connect(self.invert_selection)
        self.refresh_optical_button.clicked.connect(self.refresh_fit_ap_optical)
        self.optical_export_button.clicked.connect(self.export_optical_table)
        self.export_overview_button.clicked.connect(self.export_overview_table)
        self.save_overview_history_button.clicked.connect(self.save_overview_history_snapshot)
        self.view_overview_history_button.clicked.connect(self.open_overview_history)
        self.clear_optical_filters_button.clicked.connect(self.clear_optical_filters)
        self.optical_ap_filter.textChanged.connect(self.apply_optical_filters)
        self.optical_site_filter.currentIndexChanged.connect(self.apply_optical_filters)
        self.optical_alarm_filter.currentIndexChanged.connect(self.apply_optical_filters)
        self.retranslate()
        self.refresh_devices()

    def set_repository(self, device_repository: DeviceRepository, site_name: str) -> None:
        self.device_repository = device_repository
        self.repository = AcRepository(device_repository.database)
        self.import_export_service = FitApImportExportService(self.repository)
        self.site_name = site_name
        self.refresh_devices()

    def retranslate(self) -> None:
        self.open_web_button.setText(self.i18n.t("ac.open_web"))
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self.batch_delete_button.setText(self.i18n.t("devices.batch_delete"))
        self.batch_edit_button.setText(self.i18n.t("ap.batch_edit"))
        self.import_button.setText(self.i18n.t("ap.import_metadata"))
        self.export_button.setText(self.i18n.t("ap.export_info"))
        self.clear_selection_button.setText(self.i18n.t("devices.clear_selection"))
        self.invert_selection_button.setText(self.i18n.t("devices.invert_selection"))
        self.refresh_optical_button.setText(self.i18n.t("ac.refresh_optical"))
        self.optical_export_button.setText(self.i18n.t("ac.export_table"))
        self.export_overview_button.setText(self.i18n.t("ac.export_overview"))
        self.save_overview_history_button.setText(self.i18n.t("ac.save_history_snapshot"))
        self.view_overview_history_button.setText(self.i18n.t("ac.view_history"))
        self.clear_optical_filters_button.setText(self.i18n.t("ac.clear_filters"))
        self.optical_ap_filter.setPlaceholderText(self.i18n.t("ac.ap_name"))
        self.optical_concurrency_combo.clear()
        for value in (50, 100, 200, 500, 1000):
            self.optical_concurrency_combo.addItem(f"{self.i18n.t('batch_collect.concurrency')}: {value}", value)
        self.optical_concurrency_combo.setCurrentIndex(3)
        current_status = self.optical_alarm_filter.currentData()
        self.optical_alarm_filter.blockSignals(True)
        self.optical_alarm_filter.clear()
        for status in OPTICAL_STATUS_FILTERS:
            label = self.i18n.t("field.all") if not status else self.i18n.t(f"optical.status.{status}")
            self.optical_alarm_filter.addItem(label, status)
        index = self.optical_alarm_filter.findData(current_status)
        self.optical_alarm_filter.setCurrentIndex(index if index >= 0 else 0)
        self.optical_alarm_filter.blockSignals(False)
        self.optical_legend_label.setText(self.i18n.t("details.optical_color_legend"))
        self.status_label.setText(self.i18n.t("ac.status.not_collected"))
        self.coming_soon_label.setText(self.i18n.t("ac.coming_soon"))
        for index, (key, _field) in enumerate(SUMMARY_FIELDS):
            label = self.findChild(QLabel, f"summary_label_{SUMMARY_FIELDS[index][1]}")
            if label is not None:
                label.setText(self.i18n.t(key))
        self.tabs.setTabText(0, self.i18n.t("ac.fit_ap_resources"))
        self.tabs.setTabText(1, self.i18n.t("ac.fit_ap_optical"))
        self.tabs.setTabText(2, self.i18n.t("ac.ap_online_overview"))
        self.tabs.setTabText(3, self.i18n.t("ac.online_vehicle_mr"))
        self.resources_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in FIT_AP_RESOURCE_COLUMNS])
        self.resources_table.horizontalHeaderItem(CHECK_COLUMN).setText(self.i18n.t("ap.select_all"))
        self.optical_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in FIT_AP_OPTICAL_COLUMNS])
        self.overview_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS])
        auto_resize_table_columns(self.resources_table, column_min_widths={0: 80, 1: 150})
        self._resize_optical_columns()
        auto_resize_table_columns(self.overview_table, column_min_widths={0: 180})
        self.update_selection_state()

    def refresh_devices(self) -> None:
        current_uuid = self.current_device_uuid()
        self.ac_devices = self.device_repository.list(vendor="H3C", device_type="AC")
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self.ac_devices:
            self.device_combo.addItem(f"{device.name} ({device.ip_address})", device.device_uuid)
        index = self.device_combo.findData(current_uuid)
        self.device_combo.setCurrentIndex(index if index >= 0 else (0 if self.ac_devices else -1))
        self.device_combo.blockSignals(False)
        self.refresh_data()

    def refresh_data(self) -> None:
        ac_uuid = self.current_device_uuid()
        if not ac_uuid:
            self._set_summary(None)
            self._set_rows(self.resources_table, FIT_AP_RESOURCE_COLUMNS, [])
            self.optical_rows = []
            self._set_site_filter_items([])
            self.apply_optical_filters()
            self._set_rows(self.overview_table, AP_ONLINE_OVERVIEW_COLUMNS, [])
            return
        self._set_summary(self.repository.get_ac_ap_summary(ac_uuid))
        resources = self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        self._set_rows(self.resources_table, FIT_AP_RESOURCE_COLUMNS, resources)
        self.optical_rows = sort_fit_ap_optical_rows(enrich_fit_ap_optical_rows(self.repository.list_fit_ap_optical(ac_uuid), resources))
        self._set_site_filter_items(self.optical_rows)
        self.apply_optical_filters()
        self.refresh_overview_table(resources)
        self.update_selection_state()

    def open_web(self) -> None:
        device = self.current_device()
        if device is not None:
            webbrowser.open(f"https://{device.ip_address}")

    def refresh_ac_resources(self) -> None:
        device = self.current_device()
        if device is None:
            QMessageBox.information(self, self.i18n.t("ac.title"), self.i18n.t("devices.select_first"))
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("ac.status.updating"))
        self.resource_thread = AcResourceCollectThread(device, self.site_name, parent=self)
        self.resource_thread.collect_finished.connect(self._finish_resource_collect)
        self.resource_thread.collect_failed.connect(self._fail_resource_collect)
        self.resource_thread.finished.connect(self.resource_thread.deleteLater)
        self.resource_thread.finished.connect(lambda: setattr(self, "resource_thread", None))
        self.resource_thread.start()

    def refresh_fit_ap_optical(self) -> None:
        device = self.current_device()
        if device is None:
            return
        self.refresh_optical_button.setEnabled(False)
        self.status_label.setText(self.i18n.t("ac.status.updating"))
        self.optical_thread = FitApOpticalCollectThread(device, self.site_name, int(self.optical_concurrency_combo.currentData() or 200), self)
        self.optical_thread.collect_finished.connect(self._finish_optical_collect)
        self.optical_thread.collect_failed.connect(self._fail_optical_collect)
        self.optical_thread.finished.connect(self.optical_thread.deleteLater)
        self.optical_thread.finished.connect(lambda: setattr(self, "optical_thread", None))
        self.optical_thread.start()

    def _finish_resource_collect(self, result) -> None:
        self.refresh_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.done" if result.success else "ac.status.failed"))
        if not result.success and result.error_message:
            QMessageBox.warning(self, self.i18n.t("ac.title"), result.error_message)
        self.refresh_data()

    def _fail_resource_collect(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.failed"))
        QMessageBox.warning(self, self.i18n.t("ac.title"), message)

    def _finish_optical_collect(self, result) -> None:
        self.refresh_optical_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.done" if result.success else "ac.status.failed"))
        self.refresh_data()

    def _fail_optical_collect(self, message: str) -> None:
        self.refresh_optical_button.setEnabled(True)
        self.status_label.setText(self.i18n.t("ac.status.failed"))
        QMessageBox.warning(self, self.i18n.t("ac.title"), message)

    def current_device_uuid(self) -> str | None:
        value = self.device_combo.currentData()
        return str(value) if value else None

    def current_device(self) -> Device | None:
        current_uuid = self.current_device_uuid()
        for device in self.ac_devices:
            if device.device_uuid == current_uuid:
                return device
        return None

    def selected_ap_names(self) -> list[str]:
        names: list[str] = []
        for row in range(self.resources_table.rowCount()):
            item = self.resources_table.item(row, CHECK_COLUMN)
            if item and item.checkState() == Qt.Checked:
                names.append(str(item.data(Qt.UserRole)))
        return names

    def checked_or_all_ap_rows(self) -> list[dict[str, object | None]]:
        ac_uuid = self.current_device_uuid()
        if not ac_uuid:
            return []
        rows = self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        selected = set(self.selected_ap_names())
        return [row for row in rows if not selected or row.get("ap_uuid") in selected]

    def update_selection_state(self) -> None:
        count = len(self.selected_ap_names())
        self.selection_label.setText(self.i18n.t("ap.selected_count", count=count))
        self.batch_delete_button.setEnabled(count > 0)
        self.batch_edit_button.setEnabled(count > 0)
        self.clear_selection_button.setEnabled(count > 0)
        self.invert_selection_button.setEnabled(self.resources_table.rowCount() > 0)

    def _resource_header_clicked(self, column: int) -> None:
        if column == CHECK_COLUMN:
            self._set_all_checked(len(self.selected_ap_names()) != self.resources_table.rowCount())

    def _set_all_checked(self, checked: bool) -> None:
        self.resources_table.blockSignals(True)
        for row in range(self.resources_table.rowCount()):
            item = self.resources_table.item(row, CHECK_COLUMN)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.resources_table.blockSignals(False)
        self.update_selection_state()

    def clear_selection(self) -> None:
        self._set_all_checked(False)

    def invert_selection(self) -> None:
        self.resources_table.blockSignals(True)
        for row in range(self.resources_table.rowCount()):
            item = self.resources_table.item(row, CHECK_COLUMN)
            if item:
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self.resources_table.blockSignals(False)
        self.update_selection_state()

    def batch_delete_aps(self) -> None:
        ac_uuid = self.current_device_uuid()
        names = self.selected_ap_names()
        if not ac_uuid or not names:
            return
        answer = QMessageBox.question(self, self.i18n.t("ac.title"), self.i18n.t("ap.batch_delete_confirm"))
        if answer != QMessageBox.Yes:
            return
        count = self.repository.delete_fit_aps(ac_uuid, names)
        app_logger.log_info("FIT_AP_BATCH_DELETE", f"ac={ac_uuid}, count={count}")
        self.refresh_data()

    def batch_edit_site(self) -> None:
        names = self.selected_ap_names()
        if not names:
            return
        site_name, accepted = QInputDialog.getText(self, self.i18n.t("ap.batch_edit"), self.i18n.t("ac.site"))
        if not accepted:
            return
        count = self.repository.update_fit_ap_site(names, site_name.strip())
        app_logger.log_info("FIT_AP_BATCH_EDIT_SITE", f"count={count}, site={site_name.strip()}")
        self.refresh_data()

    def import_metadata(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("ap.import_metadata"), "", "CSV Files (*.csv)")
        if not path:
            return
        result = self.import_export_service.import_metadata_csv(Path(path))
        app_logger.log_info("FIT_AP_IMPORT", f"updated={result.updated}, skipped={result.skipped}")
        self.refresh_data()

    def export_aps(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("ap.export_info"), make_fit_ap_export_filename(self.site_name), "CSV Files (*.csv)")
        if not path:
            return
        rows = self.checked_or_all_ap_rows()
        self.import_export_service.export_ap_csv(Path(path), rows)
        app_logger.log_info("FIT_AP_EXPORT", f"count={len(rows)}, file={Path(path).name}")

    def current_optical_filters(self) -> dict[str, object | None]:
        return {
            "ap_name": self.optical_ap_filter.text(),
            "site": self.optical_site_filter.currentData(),
            "optical_alarm_status": self.optical_alarm_filter.currentData(),
        }

    def filtered_optical_rows(self) -> list[dict[str, object | None]]:
        return filter_fit_ap_optical_rows(sort_fit_ap_optical_rows(self.optical_rows), self.current_optical_filters())

    def apply_optical_filters(self) -> None:
        self._set_rows(self.optical_table, FIT_AP_OPTICAL_COLUMNS, self.filtered_optical_rows())

    def clear_optical_filters(self) -> None:
        self.optical_ap_filter.clear()
        self.optical_site_filter.setCurrentIndex(0)
        self.optical_alarm_filter.setCurrentIndex(0)
        self.clear_selection()
        self.apply_optical_filters()

    def export_optical_table(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("ac.export_table"), make_fit_ap_optical_export_filename(self.site_name), "Excel Files (*.xlsx)")
        if not path:
            return
        rows = self.filtered_optical_rows()
        export_fit_ap_optical_xlsx(Path(path), rows, FIT_AP_OPTICAL_COLUMNS, [self.i18n.t(key) for key, _field in FIT_AP_OPTICAL_COLUMNS], self.i18n.t("details.optical_color_legend"))
        app_logger.log_info("FIT_AP_OPTICAL_EXPORT", f"count={len(rows)}, file={Path(path).name}")

    def export_overview_table(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("ac.export_overview"), make_fit_ap_optical_export_filename(self.site_name), "Excel Files (*.xlsx)")
        if not path:
            return
        rows = self.current_overview_rows()
        export_ap_online_overview_xlsx(Path(path), rows, [self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS])
        app_logger.log_info("AP_ONLINE_OVERVIEW_EXPORT", f"count={len(rows)}, file={Path(path).name}")

    def save_overview_history_snapshot(self) -> None:
        count = self.repository.save_station_online_summary_history(self.current_overview_rows())
        QMessageBox.information(self, self.i18n.t("ac.ap_online_overview"), self.i18n.t("ac.history_snapshot_saved"))
        app_logger.log_info("AP_ONLINE_OVERVIEW_HISTORY_SAVE", f"count={count}")

    def open_overview_history(self) -> None:
        site_name = self.selected_overview_site()
        rows = self.repository.list_station_online_summary_history(site_name=site_name)
        dialog = StationOnlineHistoryDialog(self.i18n, rows, site_name)
        self.detail_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def selected_overview_site(self) -> str | None:
        selected = self.overview_table.selectionModel().selectedRows() if self.overview_table.selectionModel() else []
        if not selected:
            return None
        item = self.overview_table.item(selected[0].row(), 0)
        if not item or item.text() == "合计":
            return None
        return item.text()

    def current_overview_rows(self) -> list[dict[str, object | None]]:
        return [self._table_row_to_dict(self.overview_table, AP_ONLINE_OVERVIEW_COLUMNS, row) for row in range(self.overview_table.rowCount())]

    def refresh_overview_table(self, resources: list[dict[str, object | None]] | None = None) -> None:
        ac_uuid = self.current_device_uuid()
        if not ac_uuid:
            self._set_rows(self.overview_table, AP_ONLINE_OVERVIEW_COLUMNS, [])
            return
        source_rows = resources if resources is not None else self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        self._set_rows(
            self.overview_table,
            AP_ONLINE_OVERVIEW_COLUMNS,
            build_ap_online_overview_rows(source_rows, self.optical_rows, self.repository.list_station_ap_capacity_details()),
        )

    def _set_site_filter_items(self, rows: list[dict[str, object | None]]) -> None:
        current = self.optical_site_filter.currentData()
        self.optical_site_filter.blockSignals(True)
        self.optical_site_filter.clear()
        for label, value in build_site_filter_items(rows, self.i18n.t("field.all")):
            self.optical_site_filter.addItem(label, value)
        index = self.optical_site_filter.findData(current)
        self.optical_site_filter.setCurrentIndex(index if index >= 0 else 0)
        self.optical_site_filter.blockSignals(False)

    def show_resource_context_menu(self, position) -> None:
        index = self.resources_table.indexAt(position)
        menu = self.build_resource_context_menu(index.row(), index.column())
        menu.exec(self.resources_table.viewport().mapToGlobal(position))

    def build_resource_context_menu(self, row: int, column: int) -> QMenu:
        menu = create_table_context_menu(self.resources_table, row, column, self.i18n.language, include_history=False)
        menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
        detail = QAction(self.i18n.t("ap.view_details"), menu)
        if menu.actions():
            menu.insertAction(menu.actions()[0], detail)
        else:
            menu.addAction(detail)
        detail.setEnabled(row >= 0)
        detail.triggered.connect(lambda: self.open_ap_detail(row))
        return menu

    def show_optical_context_menu(self, position) -> None:
        index = self.optical_table.indexAt(position)
        menu = self.build_optical_context_menu(index.row(), index.column())
        menu.exec(self.optical_table.viewport().mapToGlobal(position))

    def build_optical_context_menu(self, row: int, column: int) -> QMenu:
        menu = create_table_context_menu(self.optical_table, row, column, self.i18n.language, include_history=False)
        menu.insertSeparator(menu.actions()[0] if menu.actions() else None)
        detail = QAction(self.i18n.t("ap.view_details"), menu)
        if menu.actions():
            menu.insertAction(menu.actions()[0], detail)
        else:
            menu.addAction(detail)
        detail.setEnabled(row >= 0)
        detail.triggered.connect(lambda: self.open_ap_detail_from_optical(row))
        return menu

    def open_ap_detail(self, row: int) -> None:
        ac_uuid = self.current_device_uuid()
        item = self.resources_table.item(row, CHECK_COLUMN)
        ap_uuid = str(item.data(Qt.UserRole)) if item else ""
        if not ac_uuid or not ap_uuid:
            return
        dialog = FitApDetailDialog(self.i18n, self.repository, ac_uuid, ap_uuid)
        self.detail_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_ap_detail_from_optical(self, row: int) -> None:
        ac_uuid = self.current_device_uuid()
        item = self.optical_table.item(row, 0)
        if not ac_uuid or not item:
            return
        ap_name = item.text()
        current_row = self.filtered_optical_rows()[row] if 0 <= row < len(self.filtered_optical_rows()) else {}
        ap_uuid = str(current_row.get("ap_uuid") or "")
        resource_rows = self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        resource_index = next((index for index, resource in enumerate(resource_rows) if resource.get("ap_uuid") == ap_uuid), -1)
        if resource_index >= 0:
            self.open_ap_detail(resource_index)
        else:
            dialog = FitApDetailDialog(self.i18n, self.repository, ac_uuid, ap_uuid or ap_name)
            self.detail_windows.append(dialog)
            dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
            dialog.show()

    def _forget_detail_window(self, window: FitApDetailDialog) -> None:
        self.detail_windows = [item for item in self.detail_windows if item is not window]

    def _set_summary(self, row: dict[str, object | None] | None) -> None:
        for _key, field in SUMMARY_FIELDS:
            value = row.get(field) if row else None
            self.summary_labels[field].setText(str(value) if value not in (None, "") else "-")
        if row and self.summary_labels.get("cpu_usage"):
            self.summary_labels["cpu_usage"].setToolTip(
                f"5秒：{row.get('cpu_5s') or '-'}%\n1分钟：{row.get('cpu_1m') or '-'}%\n5分钟：{row.get('cpu_5m') or '-'}%"
            )

    def _set_rows(self, table: QTableWidget, columns: tuple[tuple[str, str], ...], rows: list[dict[str, object | None]]) -> None:
        previous_updating_online_summary = self._updating_online_summary
        if table is self.overview_table:
            self._updating_online_summary = True
        table.blockSignals(True)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, (_key, field) in enumerate(columns):
                    if field == "select":
                        item = QTableWidgetItem("")
                        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                        item.setCheckState(Qt.Unchecked)
                        item.setData(Qt.UserRole, row.get("ap_uuid") or row.get("ap_name"))
                    else:
                        value = row.get(field)
                        if field == "optical_alarm_status":
                            value = display_optical_status(evaluate_fit_ap_row_status(row), self.i18n.language)
                        item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                        if table is self.overview_table and field in {"total", "remark"} and row.get("site") != "合计":
                            item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        else:
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        if field == "state_display":
                            item.setToolTip(f"{self.i18n.t('ap.state_raw')}: {row.get('state_raw') or row.get('state') or '-'}")
                        if table is self.optical_table:
                            color = OPTICAL_STATUS_COLORS.get(evaluate_fit_ap_row_status(row))
                            if color:
                                item.setBackground(QColor(color))
                        if table is self.overview_table:
                            self._apply_overview_color(item, row, field)
                    item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row_index, column_index, item)
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
            if table is self.overview_table:
                self._updating_online_summary = previous_updating_online_summary
        if table is self.optical_table:
            self._resize_optical_columns()
        elif table is self.overview_table:
            auto_resize_table_columns(table, column_min_widths={0: 180})
        else:
            auto_resize_table_columns(table, column_min_widths={0: 80, 1: 150})

    def _resize_optical_columns(self) -> None:
        auto_resize_table_columns(self.optical_table, column_min_widths={0: 180, 1: 150, 2: 150, 3: 180}, max_width=520)
        header = self.optical_table.horizontalHeader()
        for column in range(self.optical_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column in (0, 1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.Stretch)

    def _apply_overview_color(self, item: QTableWidgetItem, row: dict[str, object | None], field: str) -> None:
        total = int(row.get("total") or 0)
        online = int(row.get("online") or 0)
        offline = int(row.get("offline") or 0)
        if total and online == total:
            item.setBackground(QColor("#dcfce7"))
        elif total and online / total < 0.8:
            item.setBackground(QColor("#fef9c3"))
        if field == "offline" and offline > 0:
            item.setBackground(QColor("#fee2e2"))

    @staticmethod
    def _table_row_to_dict(table: QTableWidget, columns: tuple[tuple[str, str], ...], row: int) -> dict[str, object | None]:
        return {field: table.item(row, column).text() if table.item(row, column) else None for column, (_key, field) in enumerate(columns)}

    def save_overview_total(self, item: QTableWidgetItem) -> None:
        if self._updating_online_summary:
            return
        if item.column() not in {1, 5}:
            return
        site_item = self.overview_table.item(item.row(), 0)
        if not site_item or site_item.text() == "合计":
            return
        if item.column() == 5:
            remark = item.text()
            if remark == "-":
                remark = ""
            if len(remark) > 500:
                QMessageBox.warning(self, self.i18n.t("ac.ap_online_overview"), self.i18n.t("ac.remark_too_long"))
                self.refresh_overview_table()
                return
            self.repository.upsert_station_ap_remark(site_item.text(), remark)
            self.refresh_overview_table()
            return
        try:
            total = int(item.text())
            if total < 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, self.i18n.t("ac.ap_online_overview"), self.i18n.t("ac.ap_total_invalid"))
            self.refresh_overview_table()
            return
        self.repository.upsert_station_ap_capacity(site_item.text(), total)
        self.refresh_overview_table()
