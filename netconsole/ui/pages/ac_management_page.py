from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
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
from netconsole.core.optical_severity_engine import compute_optical_severity, worse_optical_severity
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.sources.switch_source import (
    build_switch_data_lookup,
    compute_switch_status,
)
from netconsole.core.state_engine import STATUS_COLORS, compute_state, display_optical_status
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.trackside_ap_business import (
    TRACKSIDE_AP_BUSINESS_COLUMNS,
    build_trackside_ap_business_rows,
    build_trackside_site_filter_items,
    export_trackside_ap_business_xlsx,
    filter_trackside_ap_business_rows,
    trackside_row_status,
)
from netconsole.services.ap_online_overview import (
    AP_ONLINE_OVERVIEW_COLUMNS,
    ApOnlineOverviewService,
    build_ap_online_overview_rows,
    export_ap_online_overview_xlsx,
    write_ap_online_overview_sheet as _write_ap_online_overview_sheet,
)
from netconsole.services.fit_ap_import_export import FitApImportExportService, make_fit_ap_export_filename
from netconsole.services.device_web_service import DEFAULT_HTTPS_PORT, build_https_url, effective_https_port, open_https_url
from netconsole.ui.ac_collect_worker import AcResourceCollectThread, FitApOpticalCollectThread
from netconsole.ui.dialogs.device_detail_dialog import DeviceDetailDialog
from netconsole.ui.dialogs.fit_ap_detail_dialog import FitApDetailDialog
from netconsole.ui.dialogs.station_online_history_dialog import StationOnlineHistoryDialog
from netconsole.ui.pages.trackside_ap_plan_page import TracksideApPlanPage
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, PaginationState, paginate_rows
from netconsole.ui.render.table_render_engine import STATUS_COLOR_MAP, apply_table_style, set_table_column_fields
from netconsole.ui.theme.contrast_engine import apply_item_contrast, apply_status_item_contrast
from netconsole.ui.export_path import CSV_FILTER, EXCEL_FILTER, remember_export_path, select_export_path
from netconsole.ui.table.table_autosize_engine import apply_worksheet_autofit
from netconsole.ui.table_utils import auto_resize_table_columns, create_table_context_menu, configure_readonly_table, make_text_selectable
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.utils.interface_sort import interface_sort_key



CHECK_COLUMN = 0
SUMMARY_FIELDS = (
    ("details.model", "model"),
    ("details.serial_number", "serial_number"),
    ("details.software_version", "software_version"),
    ("field.https_port", "https_port"),
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
    ("fit_ap.switch_optical_status", "switch_optical_status"),
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

OPTICAL_STATUS_COLORS = STATUS_COLOR_MAP
OPTICAL_EXPORT_COLOR_RGB = {
    "normal": "DCFCE7",
    "notice": "FEF9C3",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "link_down": "FFE4E6",
    "no_light": "E5E7EB",
    "skipped": "F3F4F6",
}
OPTICAL_STATUS_SEVERITY = {"unknown": 0, "not_collected": 0, "skipped": 1, "normal": 2, "notice": 3, "warning": 4, "alarm": 5, "link_abnormal": 6, "link_down": 6, "no_light": 7}
def sort_fit_ap_optical_rows(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    def key(row: dict[str, object | None]) -> tuple[int, str, tuple[object, ...], str]:
        name = str(row.get("neighbor_device_name") or "").strip()
        missing_name = 1 if name in {"", "-"} else 0
        return (missing_name, name.casefold(), interface_sort_key(row.get("neighbor_interface")), str(row.get("ap_name") or ""))

    return sorted(rows, key=key)


def enrich_fit_ap_optical_rows(
    rows: list[dict[str, object | None]],
    resources: list[dict[str, object | None]],
    device_optical_status_lookup: dict[tuple[str, str], dict[str, object | None]] | None = None,
) -> list[dict[str, object | None]]:
    resources_by_uuid = {str(row.get("ap_uuid") or ""): row for row in resources if row.get("ap_uuid")}
    resources_by_name = {str(row.get("ap_name") or ""): row for row in resources if row.get("ap_name")}
    lookup = device_optical_status_lookup or {}
    result: list[dict[str, object | None]] = []
    for row in rows:
        resource = resources_by_uuid.get(str(row.get("ap_uuid") or "")) or resources_by_name.get(str(row.get("ap_name") or ""), {})
        neighbor_name = None if _is_invalid_neighbor_text(row.get("neighbor_device_name")) else row.get("neighbor_device_name")
        switch_status = _lookup_switch_status(neighbor_name, row.get("neighbor_interface"), lookup)
        result.append(
            {
                **row,
                "ap_mac": row.get("ap_mac") or resource.get("ap_mac"),
                "site": row.get("site") or resource.get("site_name") or resource.get("site") or "未归属",
                "neighbor_device_name": neighbor_name,
                "switch_optical_status": switch_status,
            }
        )
    return result


def _lookup_switch_status(
    neighbor_device_name: object,
    neighbor_interface: object,
    lookup: dict[tuple[str, str], dict[str, object | None]],
) -> str:
    """Compute switch-side status real-time from raw optical module data."""
    return compute_switch_status(
        device_name=neighbor_device_name,
        interface_name=neighbor_interface,
        lookup=lookup,
    )


def filter_fit_ap_optical_rows(rows: list[dict[str, object | None]], filters: dict[str, object | None]) -> list[dict[str, object | None]]:
    text_fields = ("ap_name", "site")
    result = rows
    for field in text_fields:
        needle = str(filters.get(field) or "").strip().casefold()
        if needle:
            result = [row for row in result if needle in str(row.get(field) or "").casefold()]
    status = str(filters.get("optical_alarm_status") or "").strip()
    if status:
        result = [row for row in result if evaluate_fit_ap_ap_status(row) == status]
    return result


def build_site_filter_items(rows: list[dict[str, object | None]], all_label: str) -> list[tuple[str, str]]:
    sites = sorted({str(row.get("site") or "").strip() for row in rows if str(row.get("site") or "").strip()})
    return [(all_label, ""), *[(site, site) for site in sites]]


def evaluate_fit_ap_row_status(row: dict[str, object | None], neighbor_optical: dict[str, object | None] | None = None) -> str:
    """Return the overall optical status for a FIT-AP row via state_engine."""
    if neighbor_optical:
        ap_status = compute_ap_status(row)
        switch_status = _evaluate_neighbor_status(row.get("neighbor_rx_power"), neighbor_optical)
        return worse_optical_severity(switch_status, ap_status)
    result = compute_state({
        "switch_device_name": row.get("neighbor_device_name"),
        "switch_interface_name": row.get("neighbor_interface"),
        "fit_ap_row": row,
    })
    return result.optical_status


def evaluate_fit_ap_ap_status(row: dict[str, object | None]) -> str:
    """Evaluate AP side optical alarm status — delegates to ``ap_source.compute_ap_status``."""
    return _evaluate_ap_result(row).severity


def evaluate_fit_ap_switch_status(row: dict[str, object | None], neighbor_optical: dict[str, object | None] | None = None) -> str:
    """Evaluate switch side optical status real-time from raw data."""
    if neighbor_optical:
        return _evaluate_neighbor_status(row.get("neighbor_rx_power"), neighbor_optical)
    return compute_state({
        "switch_device_name": row.get("neighbor_device_name"),
        "switch_interface_name": row.get("neighbor_interface"),
        "fit_ap_row": row,
    }).switch_status


def export_fit_ap_optical_xlsx(
    path: Path,
    rows: list[dict[str, object | None]],
    columns: tuple[tuple[str, str], ...],
    headers: list[str],
    legend: str,
    overview_rows: list[dict[str, object | None]] | None = None,
    overview_headers: list[str] | None = None,
) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    overview_sheet = workbook.active
    overview_sheet.title = "AP上线情况概览"
    _write_ap_online_overview_sheet(
        overview_sheet,
        overview_rows or [],
        overview_headers or [key for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
    )
    optical_sheet = workbook.create_sheet("FIT-AP光衰")
    _write_fit_ap_optical_sheet(optical_sheet, rows, columns, headers)
    workbook.save(path)


def _write_fit_ap_optical_sheet(sheet, rows: list[dict[str, object | None]], columns: tuple[tuple[str, str], ...], headers: list[str]) -> None:
    from openpyxl.styles import PatternFill

    sheet.append(headers)
    for row in rows:
        status = evaluate_fit_ap_row_status(row)
        sheet.append([_fit_ap_optical_export_value(row, field) for _key, field in columns])
        color = OPTICAL_EXPORT_COLOR_RGB.get(status)
        fill = PatternFill(fill_type="solid", fgColor=color) if color else None
        for cell in sheet[sheet.max_row]:
            if fill:
                cell.fill = fill
    _format_export_sheet(sheet)


def make_fit_ap_optical_export_filename(site_name: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M")
    safe_site = "".join(char if char not in '<>:"/\\|?*' else "_" for char in site_name or "site")
    return f"{safe_site}_FIT-AP光衰_{stamp}.xlsx"


def _evaluate_neighbor_status(rx_power: object, neighbor_optical: dict[str, object | None] | None) -> str:
    if neighbor_optical:
        return compute_optical_severity({
            "switch_rx_power": neighbor_optical.get("rx_power"),
            "switch_port_status": neighbor_optical.get("port_status"),
            "alarm_low": neighbor_optical.get("rx_low_alarm"),
            "alarm_high": neighbor_optical.get("rx_high_alarm"),
            "warning_low": neighbor_optical.get("rx_low_warning"),
            "device_type": "switch",
        }).severity
    value = _to_float(rx_power)
    return compute_optical_severity({"switch_rx_power": value, "device_type": "switch"}).severity


def _fit_ap_optical_export_value(row: dict[str, object | None], field: str) -> str:
    if field == "switch_optical_status":
        return display_optical_status(evaluate_fit_ap_switch_status(row))
    if field == "optical_alarm_status":
        return display_optical_status(evaluate_fit_ap_ap_status(row))
    return _display_value(row.get(field))


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


def _evaluate_ap_result(row: dict[str, object | None]):
    return compute_optical_severity(
        {
            "ap_rx_power": row.get("rx_power"),
            "ap_port_status": row.get("ap_port_status"),
            "alarm_low": row.get("rx_low_alarm"),
            "alarm_high": row.get("rx_high_alarm"),
            "warning_low": row.get("rx_low_warning"),
            "device_type": "ap",
        }
    )


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
    apply_worksheet_autofit(sheet, maximum=60)


def _format_export_sheet(sheet) -> None:
    from openpyxl.styles import Alignment, Border, Font, Side

    alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
    border = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB"),
    )
    sheet.freeze_panes = "A2"
    for row in sheet.iter_rows():
        sheet.row_dimensions[row[0].row].height = 24 if row[0].row == 1 else 22
        for cell in row:
            cell.alignment = alignment
            cell.border = border
            if cell.row == 1:
                cell.font = Font(bold=True)
    _auto_width_sheet(sheet)


class AcManagementPage(QWidget):
    def __init__(self, device_repository: DeviceRepository, i18n: I18n, site_name: str = "demo") -> None:
        super().__init__()
        self.device_repository = device_repository
        self.repository = AcRepository(device_repository.database)
        self.fact_repository = DeviceFactRepository(device_repository.database)
        self.import_export_service = FitApImportExportService(self.repository)
        self.i18n = i18n
        self.site_name = site_name
        self.ac_devices: list[Device] = []
        self.resource_thread: AcResourceCollectThread | None = None
        self.optical_thread: FitApOpticalCollectThread | None = None
        self.detail_windows: list[FitApDetailDialog] = []
        self.optical_rows: list[dict[str, object | None]] = []
        self.trackside_rows: list[dict[str, object | None]] = []
        self._overview_uses_trackside_plan = False
        self.resource_rows: list[dict[str, object | None]] = []
        self._device_optical_status_lookup: dict[tuple[str, str], dict[str, object | None]] = {}
        self.resource_page = 1
        self.resource_page_size = DEFAULT_PAGE_SIZE
        self.optical_page = 1
        self.optical_page_size = DEFAULT_PAGE_SIZE
        self.trackside_page = 1
        self.trackside_page_size = DEFAULT_PAGE_SIZE
        self._updating_online_summary = False

        self.device_combo = QComboBox()
        self.open_web_button = QPushButton()
        self.refresh_button = QPushButton()
        self.status_label = make_text_selectable(QLabel())
        self.summary_labels: dict[str, QLabel] = {field: make_text_selectable(QLabel("-")) for _key, field in SUMMARY_FIELDS}
        self.tabs = QTabWidget()
        self.resources_table = QTableWidget()
        self.resources_pagination = PaginationWidget(self.i18n)
        self.batch_delete_button = QPushButton()
        self.batch_edit_button = QPushButton()
        self.import_button = QPushButton()
        self.export_button = QPushButton()
        self.clear_selection_button = QPushButton()
        self.invert_selection_button = QPushButton()
        self.selection_label = make_text_selectable(QLabel())
        self.optical_table = QTableWidget()
        self.optical_pagination = PaginationWidget(self.i18n)
        self.refresh_optical_button = QPushButton()
        self.optical_concurrency_combo = QComboBox()
        self.optical_export_button = QPushButton()
        self.clear_optical_filters_button = QPushButton()
        self.optical_ap_filter = QLineEdit()
        self.optical_site_filter = QComboBox()
        self.overview_table = QTableWidget()
        self.export_overview_button = QPushButton()
        self.save_overview_history_button = QPushButton()
        self.view_overview_history_button = QPushButton()
        self.trackside_table = QTableWidget()
        self.trackside_pagination = PaginationWidget(self.i18n)
        self.trackside_site_filter = QComboBox()
        self.trackside_search_input = QLineEdit()
        self.trackside_export_button = QPushButton()
        self.optical_legend_label = make_text_selectable(QLabel())
        self.coming_soon_label = make_text_selectable(QLabel())
        self.trackside_plan_page = TracksideApPlanPage(self.repository, self.i18n, self.site_name)

        configure_readonly_table(self.resources_table)
        configure_readonly_table(self.optical_table)
        configure_readonly_table(self.overview_table)
        configure_readonly_table(self.trackside_table)
        self.overview_table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.resources_table.setColumnCount(len(FIT_AP_RESOURCE_COLUMNS))
        self.optical_table.setColumnCount(len(FIT_AP_OPTICAL_COLUMNS))
        self.overview_table.setColumnCount(len(AP_ONLINE_OVERVIEW_COLUMNS))
        self.trackside_table.setColumnCount(len(TRACKSIDE_AP_BUSINESS_COLUMNS))
        set_table_column_fields(self.resources_table, [field for _key, field in FIT_AP_RESOURCE_COLUMNS])
        set_table_column_fields(self.optical_table, [field for _key, field in FIT_AP_OPTICAL_COLUMNS])
        set_table_column_fields(self.overview_table, [field for _key, field in AP_ONLINE_OVERVIEW_COLUMNS])
        set_table_column_fields(self.trackside_table, [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS])
        self.overview_table.itemChanged.connect(self.save_overview_total)
        self.resources_table.horizontalHeader().sectionClicked.connect(self._resource_header_clicked)
        self.resources_table.itemChanged.connect(self.update_selection_state)
        self.resources_table.doubleClicked.connect(lambda index: self.open_ap_detail(index.row()))
        self.resources_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.resources_table.customContextMenuRequested.connect(self.show_resource_context_menu)
        self.optical_table.doubleClicked.connect(lambda index: self.open_ap_detail_from_optical(index.row()))
        self.optical_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.optical_table.customContextMenuRequested.connect(self.show_optical_context_menu)
        self.trackside_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trackside_table.customContextMenuRequested.connect(self.show_trackside_context_menu)

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
        resources_layout.addWidget(self.resources_table, 1)
        resources_layout.addWidget(self.resources_pagination)
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
        ):
            optical_filters.addWidget(widget)
        self.optical_legend_label.setWordWrap(True)
        optical_layout.addLayout(optical_actions)
        optical_layout.addLayout(optical_filters)
        optical_layout.addWidget(self.optical_legend_label)
        optical_layout.addWidget(self.optical_table, 1)
        optical_layout.addWidget(self.optical_pagination)
        optical_tab.setLayout(optical_layout)

        overview_tab = QWidget()
        overview_layout = QVBoxLayout()
        overview_actions = QHBoxLayout()
        overview_actions.addWidget(self.export_overview_button)
        overview_actions.addWidget(self.save_overview_history_button)
        overview_actions.addWidget(self.view_overview_history_button)
        overview_actions.addStretch(1)
        overview_layout.addLayout(overview_actions)
        overview_layout.addWidget(self.overview_table, 1)
        overview_tab.setLayout(overview_layout)

        mr_tab = QWidget()
        mr_layout = QVBoxLayout()
        self.coming_soon_label.setAlignment(Qt.AlignCenter)
        mr_layout.addWidget(self.coming_soon_label, 1)
        mr_tab.setLayout(mr_layout)

        self.tabs.addTab(self.trackside_plan_page, "")
        self.tabs.addTab(overview_tab, "")
        self.tabs.addTab(resources_tab, "")
        self.tabs.addTab(optical_tab, "")
        self.tabs.addTab(mr_tab, "")
        # Trackside AP Service is mounted under Rail Transit.

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
        self.trackside_export_button.clicked.connect(self.export_trackside_table)
        self.clear_optical_filters_button.clicked.connect(self.clear_optical_filters)
        self.optical_ap_filter.textChanged.connect(self.apply_optical_filters)
        self.optical_site_filter.currentIndexChanged.connect(self.apply_optical_filters)
        self.trackside_site_filter.currentIndexChanged.connect(self.apply_trackside_filters)
        self.trackside_search_input.textChanged.connect(self.apply_trackside_filters)
        self.resources_pagination.pageChanged.connect(self.set_resource_page)
        self.resources_pagination.pageSizeChanged.connect(self.set_resource_page_size)
        self.optical_pagination.pageChanged.connect(self.set_optical_page)
        self.optical_pagination.pageSizeChanged.connect(self.set_optical_page_size)
        self.trackside_pagination.pageChanged.connect(self.set_trackside_page)
        self.trackside_pagination.pageSizeChanged.connect(self.set_trackside_page_size)
        self.trackside_plan_page.plan_saved.connect(self._handle_trackside_plan_saved)
        self.retranslate()
        self.refresh_devices()

    def set_repository(self, device_repository: DeviceRepository, site_name: str) -> None:
        self.device_repository = device_repository
        self.repository = AcRepository(device_repository.database)
        self.fact_repository = DeviceFactRepository(device_repository.database)
        self.import_export_service = FitApImportExportService(self.repository)
        self.site_name = site_name
        self.trackside_plan_page.repository = self.repository
        self.trackside_plan_page.site_name = site_name
        self.trackside_plan_page.refresh()
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
        self.trackside_export_button.setText(self.i18n.t("trackside.export"))
        self.trackside_search_input.setPlaceholderText(self.i18n.t("trackside.search"))
        self.resources_pagination.retranslate()
        self.optical_pagination.retranslate()
        self.trackside_pagination.retranslate()
        self.clear_optical_filters_button.setText(self.i18n.t("ac.clear_filters"))
        self.optical_ap_filter.setPlaceholderText(self.i18n.t("ac.ap_name"))
        self.optical_concurrency_combo.clear()
        for value in (50, 100, 200, 500, 1000):
            self.optical_concurrency_combo.addItem(f"{self.i18n.t('batch_collect.concurrency')}: {value}", value)
        self.optical_concurrency_combo.setCurrentIndex(3)
        self.optical_legend_label.setText(self.i18n.t("details.optical_color_legend"))
        self.status_label.setText(self.i18n.t("ac.status.not_collected"))
        self.coming_soon_label.setText(self.i18n.t("ac.coming_soon"))
        for index, (key, _field) in enumerate(SUMMARY_FIELDS):
            label = self.findChild(QLabel, f"summary_label_{SUMMARY_FIELDS[index][1]}")
            if label is not None:
                label.setText(self.i18n.t(key))
        self.tabs.setTabText(0, self.i18n.t("ac.trackside_ap_plan"))
        self.tabs.setTabText(1, self.i18n.t("ac.ap_online_overview"))
        self.tabs.setTabText(2, self.i18n.t("ac.fit_ap_resources"))
        self.tabs.setTabText(3, self.i18n.t("ac.fit_ap_optical"))
        self.tabs.setTabText(4, self.i18n.t("ac.online_vehicle_mr"))
        self.trackside_plan_page.retranslate()
        self.resources_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in FIT_AP_RESOURCE_COLUMNS])
        self.resources_table.horizontalHeaderItem(CHECK_COLUMN).setText(self.i18n.t("ap.select_all"))
        self.optical_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in FIT_AP_OPTICAL_COLUMNS])
        self.overview_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS])
        self.trackside_table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS])
        apply_table_style(self.resources_table)
        apply_table_style(self.optical_table)
        apply_table_style(self.overview_table)
        apply_table_style(self.trackside_table)
        self.update_selection_state()
        self.update_open_web_button()

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
            self.resource_rows = []
            self.apply_resource_pagination()
            self.optical_rows = []
            self._set_site_filter_items([])
            self.apply_optical_filters()
            self._set_rows(self.overview_table, AP_ONLINE_OVERVIEW_COLUMNS, [])
            self.refresh_trackside_table()
            self.update_open_web_button()
            return
        self._set_summary(self.repository.get_ac_ap_summary(ac_uuid))
        resources = self.repository.list_fit_ap_resources_with_metadata(ac_uuid)
        self.resource_rows = resources
        self.apply_resource_pagination()
        self._rebuild_device_optical_status_lookup()
        self.optical_rows = sort_fit_ap_optical_rows(enrich_fit_ap_optical_rows(self.repository.list_fit_ap_optical(ac_uuid), resources, self._device_optical_status_lookup))
        self._set_site_filter_items(self.optical_rows)
        self.apply_optical_filters()
        self.refresh_overview_table(resources)
        self.refresh_trackside_table()
        self.update_selection_state()
        self.update_open_web_button()

    def open_web(self) -> None:
        device = self.current_device()
        if device is None:
            return
        port, _source = effective_https_port(device.https_port)
        if not build_https_url(device.ip_address, port):
            QMessageBox.information(self, self.i18n.t("ac.open_web"), self.i18n.t("ac.https_port_not_collected"))
            return
        if not open_https_url(device.ip_address, port):
            QMessageBox.warning(self, self.i18n.t("ac.open_web"), self.i18n.t("ac.open_web_failed"))

    def update_open_web_button(self) -> None:
        device = self.current_device()
        port, _source = effective_https_port(device.https_port if device is not None else None)
        enabled = device is not None and build_https_url(device.ip_address, port) is not None
        self.open_web_button.setEnabled(enabled)
        self.open_web_button.setToolTip("" if enabled else self.i18n.t("ac.https_port_not_collected"))
        app_logger.log_info("AC_HTTPS_PORT_BUTTON_STATE", f"device={device.name if device else ''}, effective_port={port}, button_enabled={enabled}")

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
        if not result.success and result.error_message:
            self.status_label.setText(self.i18n.t("ac.status.failed"))
            QMessageBox.warning(self, self.i18n.t("ac.title"), result.error_message)
            self.refresh_devices()
            return
        self.refresh_devices()
        if getattr(result, "https_port_collected", False) and result.https_port is not None:
            if not getattr(result, "https_port_persisted", False):
                self._apply_transient_https_port(result.https_port)
                self.status_label.setText(self.i18n.t("ac.update_done_https_save_failed", port=result.https_port))
            else:
                self.status_label.setText(self.i18n.t("ac.update_done_with_https", port=result.https_port))
        else:
            device = self.current_device()
            port, source = effective_https_port(device.https_port if device is not None else None)
            self.status_label.setText(
                self.i18n.t("ac.update_done_https_history", port=port)
                if source == "device"
                else self.i18n.t("ac.update_done_https_default", port=DEFAULT_HTTPS_PORT)
            )
        device = self.current_device()
        app_logger.log_info("AC_HTTPS_PORT_UI_REFRESHED", f"device={device.name if device else ''}, ui_port={device.https_port if device else None}")

    def _apply_transient_https_port(self, port: int) -> None:
        device = self.current_device()
        if device is None:
            return
        device.https_port = port
        self._set_summary(self.repository.get_ac_ap_summary(str(device.device_uuid or "")))
        self.update_open_web_button()

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
        path = select_export_path(self, self.i18n.t("ap.export_info"), make_fit_ap_export_filename(self.site_name), CSV_FILTER)
        if not path:
            return
        rows = self.checked_or_all_ap_rows()
        self.import_export_service.export_ap_csv(path, rows)
        remember_export_path(path)
        app_logger.log_info("FIT_AP_EXPORT", f"count={len(rows)}, file={path.name}")

    def current_optical_filters(self) -> dict[str, object | None]:
        return {
            "ap_name": self.optical_ap_filter.text(),
            "site": self.optical_site_filter.currentData(),
        }

    def filtered_optical_rows(self) -> list[dict[str, object | None]]:
        return filter_fit_ap_optical_rows(sort_fit_ap_optical_rows(self.optical_rows), self.current_optical_filters())

    def current_optical_page_rows(self) -> list[dict[str, object | None]]:
        rows, _state = paginate_rows(self.filtered_optical_rows(), self.optical_page_size, self.optical_page)
        return rows

    def apply_optical_filters(self) -> None:
        self.optical_page = 1
        self.apply_optical_pagination()

    def apply_resource_pagination(self) -> None:
        rows, state = paginate_rows(self.resource_rows, self.resource_page_size, self.resource_page)
        self.resource_page = state.current_page
        self.resources_pagination.set_state(state)
        self._set_rows(self.resources_table, FIT_AP_RESOURCE_COLUMNS, rows)

    def set_resource_page(self, page: int) -> None:
        self.resource_page = page
        self.apply_resource_pagination()

    def set_resource_page_size(self, page_size: int) -> None:
        self.resource_page_size = page_size
        self.resource_page = 1
        self.apply_resource_pagination()

    def apply_optical_pagination(self) -> None:
        rows, state = paginate_rows(self.filtered_optical_rows(), self.optical_page_size, self.optical_page)
        self.optical_page = state.current_page
        self.optical_pagination.set_state(state)
        self._set_rows(self.optical_table, FIT_AP_OPTICAL_COLUMNS, rows)

    def set_optical_page(self, page: int) -> None:
        self.optical_page = page
        self.apply_optical_pagination()

    def set_optical_page_size(self, page_size: int) -> None:
        self.optical_page_size = page_size
        self.optical_page = 1
        self.apply_optical_pagination()

    def current_trackside_filters(self) -> dict[str, object | None]:
        return {
            "site": self.trackside_site_filter.currentData(),
            "search": self.trackside_search_input.text(),
        }

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
        self._set_rows(self.trackside_table, TRACKSIDE_AP_BUSINESS_COLUMNS, rows)

    def set_trackside_page(self, page: int) -> None:
        self.trackside_page = page
        self.apply_trackside_pagination()

    def set_trackside_page_size(self, page_size: int) -> None:
        self.trackside_page_size = page_size
        self.trackside_page = 1
        self.apply_trackside_pagination()

    def clear_optical_filters(self) -> None:
        self.optical_ap_filter.clear()
        self.optical_site_filter.setCurrentIndex(0)
        self.clear_selection()
        self.apply_optical_filters()

    def export_optical_table(self) -> None:
        path = select_export_path(self, self.i18n.t("ac.export_table"), make_fit_ap_optical_export_filename(self.site_name), EXCEL_FILTER)
        if not path:
            return
        self.refresh_overview_table()
        rows = self.filtered_optical_rows()
        export_fit_ap_optical_xlsx(
            path,
            rows,
            FIT_AP_OPTICAL_COLUMNS,
            [self.i18n.t(key) for key, _field in FIT_AP_OPTICAL_COLUMNS],
            self.i18n.t("details.optical_color_legend"),
            self.current_overview_rows(),
            [self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        )
        remember_export_path(path)
        app_logger.log_info("FIT_AP_OPTICAL_EXPORT", f"count={len(rows)}, file={path.name}")

    def export_overview_table(self) -> None:
        path = select_export_path(self, self.i18n.t("ac.export_overview"), make_fit_ap_optical_export_filename(self.site_name), EXCEL_FILTER)
        if not path:
            return
        self.refresh_overview_table()
        rows = self.current_overview_rows()
        export_ap_online_overview_xlsx(path, rows, [self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS])
        remember_export_path(path)
        app_logger.log_info("AP_ONLINE_OVERVIEW_EXPORT", f"count={len(rows)}, file={path.name}")

    def export_trackside_table(self) -> None:
        path = select_export_path(self, self.i18n.t("trackside.export"), f"{self.site_name}_轨旁AP业务_{datetime.now().strftime('%Y-%m-%d-%H%M')}.xlsx", EXCEL_FILTER)
        if not path:
            return
        self.refresh_overview_table()
        rows = self.filtered_trackside_rows()
        export_trackside_ap_business_xlsx(
            path,
            rows,
            TRACKSIDE_AP_BUSINESS_COLUMNS,
            [self.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
            self.current_overview_rows(),
            AP_ONLINE_OVERVIEW_COLUMNS,
            [self.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        )
        remember_export_path(path)
        app_logger.log_info("TRACKSIDE_AP_BUSINESS_EXPORT", f"count={len(rows)}, file={path.name}")

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
        capacity_details = self.repository.list_active_trackside_plan_capacity_details()
        self._overview_uses_trackside_plan = bool(capacity_details)
        if not capacity_details:
            capacity_details = self.repository.list_station_ap_capacity_details()
        self._set_rows(
            self.overview_table,
            AP_ONLINE_OVERVIEW_COLUMNS,
            ApOnlineOverviewService.build_rows(
                metadata_rows=self.repository.list_fit_ap_metadata(),
                fit_ap_resources=source_rows,
                optical_rows=self.repository.list_fit_ap_optical(ac_uuid),
                capacity_details=capacity_details,
            ),
        )

    def _handle_trackside_plan_saved(self) -> None:
        self.refresh_overview_table()
        self.refresh_trackside_table()

    def _rebuild_device_optical_status_lookup(self) -> None:
        """Rebuild the device optical status lookup from all devices and their optical modules.

        This lookup maps (device_name, interface_name) -> optical module status,
        which is the single source of truth from device detail.
        """
        devices = self.device_repository.list()
        optical_by_device = {str(device.device_uuid or ""): self.fact_repository.list_optical_modules(str(device.device_uuid or "")) for device in devices}
        self._device_optical_status_lookup = build_switch_data_lookup(devices, optical_by_device)

    def refresh_trackside_table(self) -> None:
        devices = self.device_repository.list()
        interfaces_by_device = {str(device.device_uuid or ""): self.fact_repository.list_device_interfaces(str(device.device_uuid or "")) for device in devices}
        optical_by_device = {str(device.device_uuid or ""): self.fact_repository.list_optical_modules(str(device.device_uuid or "")) for device in devices}
        lldp_by_device = {str(device.device_uuid or ""): self.fact_repository.list_lldp_neighbors(str(device.device_uuid or "")) for device in devices}
        lookup = self._device_optical_status_lookup or build_switch_data_lookup(devices, optical_by_device)
        self.trackside_rows = build_trackside_ap_business_rows(
            devices,
            interfaces_by_device,
            optical_by_device,
            self.repository.list_all_fit_ap_optical(),
            lldp_by_device,
            self.repository.list_all_fit_ap_resources_with_metadata(),
            lookup,
            self.repository.get_active_trackside_pvid_plan(),
        )
        self._set_trackside_site_filter_items(self.trackside_rows)
        self.apply_trackside_filters()

    def _set_site_filter_items(self, rows: list[dict[str, object | None]]) -> None:
        current = self.optical_site_filter.currentData()
        self.optical_site_filter.blockSignals(True)
        self.optical_site_filter.clear()
        for label, value in build_site_filter_items(rows, self.i18n.t("field.all")):
            self.optical_site_filter.addItem(label, value)
        index = self.optical_site_filter.findData(current)
        self.optical_site_filter.setCurrentIndex(index if index >= 0 else 0)
        self.optical_site_filter.blockSignals(False)

    def _set_trackside_site_filter_items(self, rows: list[dict[str, object | None]]) -> None:
        current = self.trackside_site_filter.currentData()
        self.trackside_site_filter.blockSignals(True)
        self.trackside_site_filter.clear()
        for label, value in build_trackside_site_filter_items(rows, self.i18n.t("field.all")):
            self.trackside_site_filter.addItem(label, value)
        index = self.trackside_site_filter.findData(current)
        self.trackside_site_filter.setCurrentIndex(index if index >= 0 else 0)
        self.trackside_site_filter.blockSignals(False)

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
        page_rows = self.current_optical_page_rows()
        current_row = page_rows[row] if 0 <= row < len(page_rows) else {}
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
        ac_uuid = str(current_row.get("ac_device_uuid") or self.current_device_uuid() or "")
        ap_uuid = str(current_row.get("ap_uuid") or "")
        if not ac_uuid or not ap_uuid:
            QMessageBox.information(self, self.i18n.t("trackside.view_ap_detail"), self.i18n.t("trackside.ap_not_found"))
            return
        dialog = FitApDetailDialog(self.i18n, self.repository, ac_uuid, ap_uuid)
        self.detail_windows.append(dialog)
        dialog.destroyed.connect(lambda _=None, window=dialog: self._forget_detail_window(window))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_detail_window(self, window: FitApDetailDialog) -> None:
        self.detail_windows = [item for item in self.detail_windows if item is not window]

    def _set_summary(self, row: dict[str, object | None] | None) -> None:
        for _key, field in SUMMARY_FIELDS:
            if field == "https_port":
                device = self.current_device()
                port, source = effective_https_port(device.https_port if device is not None else None)
                self.summary_labels[field].setText(str(port) if source == "device" else self.i18n.t("ac.https_port_default", port=port))
                continue
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
        table.setSortingEnabled(False)
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
                        if table is self.optical_table and field == "switch_optical_status":
                            value = display_optical_status(evaluate_fit_ap_switch_status(row), self.i18n.language)
                        elif table is self.optical_table and field == "optical_alarm_status":
                            value = display_optical_status(evaluate_fit_ap_ap_status(row), self.i18n.language)
                        elif field in {"switch_optical_status", "ap_optical_status"}:
                            value = display_optical_status(str(value or ""), self.i18n.language) if value else value
                        item = QTableWidgetItem(str(value) if value not in (None, "") else "-")
                        plan_locked = table is self.overview_table and bool(row.get("source") == "trackside_plan" or row.get("remark") == "\u8f68\u65c1AP\u89c4\u5212")
                        if field == "remark":
                            plan_locked = False
                        if table is self.overview_table and field in {"total", "remark"} and row.get("site") != "合计" and not plan_locked:
                            item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        else:
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        if plan_locked and field == "total":
                            item.setToolTip(self.i18n.t("ac.trackside_plan_total_locked"))
                        if field == "state_display":
                            item.setToolTip(f"{self.i18n.t('ap.state_raw')}: {row.get('state_raw') or row.get('state') or '-'}")
                        if table is self.optical_table:
                            apply_status_item_contrast(item, evaluate_fit_ap_row_status(row))
                        if table is self.trackside_table:
                            apply_status_item_contrast(item, trackside_row_status(row))
                        if table is self.overview_table:
                            self._apply_overview_color(item, row, field)
                    item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row_index, column_index, item)
        finally:
            table.blockSignals(False)
            table.setSortingEnabled(False)
            table.setUpdatesEnabled(True)
            if table is self.overview_table:
                self._updating_online_summary = previous_updating_online_summary
        if table is self.optical_table:
            self._resize_optical_columns()
        elif table is self.overview_table:
            auto_resize_table_columns(table)
        elif table is self.trackside_table:
            auto_resize_table_columns(table)
        else:
            auto_resize_table_columns(table)

    def _resize_optical_columns(self) -> None:
        auto_resize_table_columns(self.optical_table)

    def _apply_overview_color(self, item: QTableWidgetItem, row: dict[str, object | None], field: str) -> None:
        total = int(row.get("total") or 0)
        online = int(row.get("online") or 0)
        offline = int(row.get("offline") or 0)
        if total and online == total:
            apply_item_contrast(item, STATUS_COLOR_MAP["normal"])
        elif total and online / total < 0.8:
            apply_item_contrast(item, STATUS_COLOR_MAP["warning"])
        if field == "offline" and offline > 0:
            apply_item_contrast(item, STATUS_COLOR_MAP["alarm"])

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
        if self._overview_uses_trackside_plan:
            QMessageBox.information(self, self.i18n.t("ac.ap_online_overview"), self.i18n.t("ac.trackside_plan_total_locked"))
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
