from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from netconsole.core import app_logger
from netconsole.core.feature_flags import apply_feature_to_widget, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.mesh_log_models import MeshMrProfile, format_mac_h3c
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_link_detail_export import export_mesh_link_details_xlsx
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.path_preference_service import PathPreferenceService
from netconsole.services.rail_transit.constants import VEHICLE_MR_GROUP_NAME
from netconsole.ui.mesh_log_workers import MeshDerivedAnalysisRebuildWorker, MeshLogImportWorker
from netconsole.ui.mesh_table_column_state import MeshTableColumnState
from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, PaginationState
from netconsole.ui.table.table_autosize_engine import apply_table_autosize
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.ui.dialogs.mesh_peer_detail_dialog import MeshActiveLinkChartDialog, MeshPeerDetailDialog
from netconsole.utils.natural_sort import natural_text_key


FILE_FILTER = "MESH Logs (*.log *.log.gz *.txt);;Log Files (*.log *.log.gz);;Text Files (*.txt);;All Files (*.*)"
MESH_DEFAULT_PAGE_SIZE = 1000
MESH_ANALYSIS_REPORT_ENABLED = True
REPORT_STAGE_LABELS = {
    "loading": "读取数据库",
    "normalize_samples": "规范化链路数据",
    "sample_quality": "采样点质量分析",
    "active_segments": "Active区段分析",
    "peer_ranking": "Peer质量排名",
    "switch_analysis": "切换事件分析",
    "anomaly_analysis": "异常事件分析",
    "busy_analysis": "空口繁忙度分析",
    "link_rebuild_analysis": "链路重建分析",
    "raw_evidence": "原始证据提取",
    "analysis_done": "分析完成",
    "excel_overview": "Excel写入：报告总览",
    "excel_sample_quality": "Excel写入：采样点质量统计",
    "excel_active_segments": "Excel写入：Active主链路区段",
    "excel_peer_ranking": "Excel写入：Peer质量排名",
    "excel_raw_evidence": "Excel写入：原始证据片段",
    "excel_save": "Excel保存文件",
    "done": "完成",
}
REPORT_STAGE_LABELS.update(
    {
        "source_files": "查询源文件清单",
        "parallel_workers": "多进程并行生成",
        "loading": "读取数据库",
        "normalize_samples": "规范化链路数据",
        "sample_quality": "采样点质量分析",
        "active_segments": "Active区段分析",
        "peer_ranking": "Peer质量排名",
        "switch_analysis": "切换事件分析",
        "anomaly_analysis": "异常事件分析",
        "busy_analysis": "空口繁忙度分析",
        "link_rebuild_analysis": "链路重建分析",
        "raw_evidence": "原始证据提取",
        "analysis_done": "分析完成",
        "excel_overview": "Excel写入：报告总览",
        "excel_sample_quality": "Excel写入：采样点质量统计",
        "excel_active_segments": "Excel写入：Active主链路区段",
        "excel_peer_ranking": "Excel写入：Peer质量排名",
        "excel_raw_evidence": "Excel写入：原始证据片段",
        "excel_save": "Excel保存文件",
        "done": "完成",
    }
)


class MeshLinkDetailExportWorker(QThread):
    stageChanged = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        output_path: Path,
        filters: dict[str, object | None],
        source_file_id: int | None,
        radio: int | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.output_path = Path(output_path)
        self.filters = dict(filters)
        self.source_file_id = source_file_id
        self.radio = radio

    def run(self) -> None:
        tmp_path = self.output_path.with_name(f"{self.output_path.stem}.tmp{self.output_path.suffix}")
        try:
            repo = MeshMrRepository(self.db_path)
            self.stageChanged.emit("mesh_analysis.export_progress_query_links")
            total, _ = repo.query_links(1, 0, self.filters)
            _total, rows = repo.query_links(max(total, 1), 0, self.filters)
            self.stageChanged.emit("mesh_analysis.export_progress_query_build_order")
            active_build_order_rows = repo.query_active_link_build_order(self.source_file_id, self.radio)
            self.stageChanged.emit("mesh_analysis.export_progress_write_links")
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            export_mesh_link_details_xlsx(tmp_path, rows, active_build_order_rows)
            self.stageChanged.emit("mesh_analysis.export_progress_save")
            os.replace(tmp_path, self.output_path)
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            self.failed.emit(str(exc))
            return
        self.completed.emit(str(self.output_path))


class MeshLogAnalysisPage(QWidget):
    def __init__(
        self,
        repository: DeviceRepository | I18n | None,
        i18n: I18n | str | None = None,
        site_name: str | PathResolver = "demo",
        paths: PathResolver | None = None,
    ) -> None:
        super().__init__()
        if isinstance(repository, I18n):
            legacy_i18n = repository
            legacy_site_name = str(i18n or "demo")
            legacy_paths = site_name if isinstance(site_name, PathResolver) else paths
            repository = None
            i18n = legacy_i18n
            site_name = legacy_site_name
            paths = legacy_paths
        self.repository = repository if isinstance(repository, DeviceRepository) else None
        self.i18n = i18n if isinstance(i18n, I18n) else I18n()
        self.site_name = str(site_name)
        self.paths = paths or PathResolver()
        self.group_repository = self._make_group_repository(self.repository, self.site_name)
        self.storage = MeshStorageService(site_name, self.paths)
        self.settings = SettingsStore(self.paths)
        self.catalog_repo = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name))
        self.feature_gate = default_feature_gate()
        self.repo_cache: dict[str, MeshMrRepository] = {}
        self.profile_by_id: dict[str, MeshMrProfile] = {}
        self.worker: MeshLogImportWorker | None = None
        self.export_worker: MeshLinkDetailExportWorker | None = None
        self.report_worker: object | None = None
        self.report_open_output_dir = True
        self.derived_worker: MeshDerivedAnalysisRebuildWorker | None = None
        self.peer_dialogs: list[MeshPeerDetailDialog] = []
        self.profiles: list[MeshMrProfile] = []
        self.current_profile: MeshMrProfile | None = None
        self.current_source_file_id: int | None = None
        self.current_source_file_name: str | None = None
        self.link_page = 1
        self.event_page = 1
        self.issue_page = 1
        self.source_page = 1
        self.page_size = MESH_DEFAULT_PAGE_SIZE
        self._populating_tables = False
        self._suppress_mr_selection = False
        self._restoring_column_widths = False
        self._link_column_widths_changed = False
        self.mr_load_generation = 0
        self.dirty_tabs: set[str] = {"source", "link", "active_build_order", "event", "issue"}

        self.title_label = QLabel()
        self.create_mr_button = QPushButton()
        self.import_button = QPushButton()
        self.import_folder_button = QPushButton()
        self.show_all_sources_button = QPushButton()
        self.cancel_button = QPushButton()
        self.refresh_button = QPushButton()
        self.open_folder_button = QPushButton()
        self.generate_report_button = QPushButton()
        self.export_link_button = QPushButton()
        self.open_full_active_chart_button = QPushButton()
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel()

        self.mr_table = QTableWidget(0, 8)
        self.source_table = QTableWidget(0, 15)
        self.link_table = QTableWidget(0, 27)
        self.active_build_order_table = QTableWidget(0, 18)
        self.event_table = QTableWidget(0, 14)
        self.issue_table = QTableWidget(0, 7)
        self.issue_empty_widget = QWidget()
        self.issue_empty_title = QLabel()
        self.issue_empty_description = QLabel()
        for table in (self.mr_table, self.source_table, self.link_table, self.active_build_order_table, self.event_table, self.issue_table):
            table.setProperty("netconsole_manual_column_widths", True)
            configure_readonly_table(table)
            table.setSortingEnabled(True)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.ElideRight)
            table.verticalHeader().setDefaultSectionSize(max(table.fontMetrics().height() + 12, 32))
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setStretchLastSection(False)
        self.link_table.setAlternatingRowColors(False)
        self.link_table.setProperty("netconsole_center_cells", True)
        self.mr_table.setProperty("netconsole_natural_sort_first_column", True)
        self.mr_table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.link_table.horizontalHeader().sectionResized.connect(self._mark_link_column_width_changed)

        self.radio_filter = QLineEdit()
        self.state_filter = QComboBox()
        self.state_filter.addItem(self.i18n.t("mesh_analysis.state_default"), None)
        self.state_filter.addItem(self.i18n.t("mesh_analysis.state_active"), "ACTIVE")
        self.state_filter.addItem(self.i18n.t("mesh_analysis.state_standby"), "STANDBY")
        self.peer_filter = QLineEdit()
        self.keyword_filter = QLineEdit()
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)

        self.source_pagination = PaginationWidget(self.i18n)
        self.link_pagination = PaginationWidget(self.i18n)
        self.event_pagination = PaginationWidget(self.i18n)
        self.issue_pagination = PaginationWidget(self.i18n)
        for pagination in (self.source_pagination, self.link_pagination, self.event_pagination, self.issue_pagination):
            pagination.set_state(PaginationState(page_size=self.page_size, current_page=1, total_items=0, total_pages=1))
        self.tabs = QTabWidget()
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(300)
        self.mr_selection_timer = QTimer(self)
        self.mr_selection_timer.setSingleShot(True)
        self.mr_selection_timer.setInterval(120)
        self.column_states: dict[str, MeshTableColumnState] = {}
        self._build_layout()
        self._connect_signals()
        self.retranslate()
        self._setup_column_states()
        self.refresh_all()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.group_repository = self._make_group_repository(repository, site_name)
        self.set_site(site_name)

    def set_site(self, site_name: str) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        self.site_name = site_name
        self.storage = MeshStorageService(site_name, self.paths)
        self.settings = SettingsStore(self.paths)
        self.catalog_repo = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name))
        self.feature_gate = default_feature_gate()
        if self.repository is not None:
            self.group_repository = self._make_group_repository(self.repository, self.site_name)
        self.repo_cache.clear()
        self.profile_by_id.clear()
        self.current_profile = None
        self.current_source_file_id = None
        self.current_source_file_name = None
        self.refresh_all()

    @staticmethod
    def _make_group_repository(repository: DeviceRepository | None, site_name: str) -> DeviceGroupRepository | None:
        database = getattr(repository, "database", None)
        return DeviceGroupRepository(database, site_name) if database is not None else None

    def retranslate(self) -> None:
        self.title_label.setText(self.i18n.t("mesh_analysis.title"))
        self.import_button.setText(self.i18n.t("mesh_analysis.import_logs"))
        self.import_folder_button.setText(self.i18n.t("mesh_analysis.import_folder"))
        self.show_all_sources_button.setText("显示全部文件")
        self.cancel_button.setText(self.i18n.t("mesh_analysis.cancel"))
        self.refresh_button.setText(self.i18n.t("mesh_analysis.refresh"))
        self.open_folder_button.setText(self.i18n.t("mesh_analysis.open_folder"))
        self.generate_report_button.setText("生成 MR 原始 MESH 分析报告")
        self.export_link_button.setText("导出链路明细")
        self.open_full_active_chart_button.setText(self.i18n.t("mesh_analysis.open_full_active_chart"))
        self.radio_filter.setPlaceholderText("Radio")
        self.state_filter.setItemText(0, self.i18n.t("mesh_analysis.state_default"))
        self.state_filter.setItemText(1, self.i18n.t("mesh_analysis.state_active"))
        self.state_filter.setItemText(2, self.i18n.t("mesh_analysis.state_standby"))
        self.peer_filter.setPlaceholderText("PeerMac / AP名称 / 站点")
        self.keyword_filter.setPlaceholderText(self.i18n.t("mesh_analysis.keyword"))
        self.mr_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("mesh_analysis.mr_name"),
                self.i18n.t("mesh_analysis.earliest_time"),
                self.i18n.t("mesh_analysis.latest_time"),
                self.i18n.t("mesh_analysis.source_files"),
                self.i18n.t("mesh_analysis.samples"),
                self.i18n.t("mesh_analysis.link_records"),
                self.i18n.t("mesh_analysis.events"),
                self.i18n.t("mesh_analysis.last_import_at"),
            ]
        )
        self.source_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("mesh_analysis.file_name"),
                "当前显示",
                self.i18n.t("mesh_analysis.archived_path"),
                "文件状态",
                self.i18n.t("mesh_analysis.file_size"),
                "SHA-256",
                self.i18n.t("mesh_analysis.imported_at"),
                self.i18n.t("mesh_analysis.start_time"),
                self.i18n.t("mesh_analysis.end_time"),
                self.i18n.t("mesh_analysis.parse_status"),
                self.i18n.t("mesh_analysis.records_parsed"),
                self.i18n.t("mesh_analysis.records_skipped"),
                self.i18n.t("mesh_analysis.duplicate_records"),
                self.i18n.t("mesh_analysis.issue_count"),
                self.i18n.t("mesh_analysis.parser_version"),
            ]
        )
        self.link_table.setHorizontalHeaderLabels(
            [
                "序号",
                self.i18n.t("mesh_analysis.sample_time"),
                "Radio",
                self.i18n.t("mesh_analysis.state"),
                "PeerMac",
                "当前PEER AP名称",
                "AP MAC",
                "归属站点",
                "Peer Radio MAC",
                "PEER Radio",
                self.i18n.t("mesh_analysis.establish_time"),
                self.i18n.t("mesh_analysis.duration"),
                "LinkCnt",
                self.i18n.t("mesh_analysis.local_rssi"),
                self.i18n.t("mesh_analysis.peer_rssi"),
                self.i18n.t("mesh_analysis.local_noise"),
                self.i18n.t("mesh_analysis.peer_noise"),
                self.i18n.t("mesh_analysis.local_signal"),
                self.i18n.t("mesh_analysis.peer_signal"),
                self.i18n.t("mesh_analysis.local_rate"),
                self.i18n.t("mesh_analysis.peer_rate"),
                "L_TxBusy",
                "P_TxBusy",
                "L_RxBusy",
                "P_RxBusy",
                self.i18n.t("mesh_analysis.source_file"),
                self.i18n.t("mesh_analysis.line_number"),
            ]
        )
        self.active_build_order_table.setHorizontalHeaderLabels(
            [
                "序号",
                "Radio",
                "Active PeerMac",
                "当前PEER AP名称",
                "归属站点",
                "Peer Radio",
                self.i18n.t("mesh_analysis.build_start_time"),
                self.i18n.t("mesh_analysis.build_end_time"),
                self.i18n.t("mesh_analysis.main_link_duration_seconds"),
                self.i18n.t("mesh_analysis.reported_duration_seconds"),
                self.i18n.t("mesh_analysis.samples"),
                self.i18n.t("mesh_analysis.mr_rssi"),
                self.i18n.t("mesh_analysis.min_rssi"),
                self.i18n.t("mesh_analysis.max_rssi"),
                "TxBusy",
                "RxBusy",
                self.i18n.t("mesh_analysis.build_result"),
                self.i18n.t("mesh_analysis.file_name"),
            ]
        )
        self.event_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("mesh_analysis.event_time"),
                "Radio",
                self.i18n.t("mesh_analysis.event_type"),
                self.i18n.t("mesh_analysis.from_peer"),
                self.i18n.t("mesh_analysis.to_peer"),
                self.i18n.t("mesh_analysis.observed_window"),
                self.i18n.t("mesh_analysis.previous_mr_rssi"),
                self.i18n.t("mesh_analysis.new_mr_rssi"),
                self.i18n.t("mesh_analysis.previous_peer_rssi"),
                self.i18n.t("mesh_analysis.new_peer_rssi"),
                self.i18n.t("mesh_analysis.from_rate"),
                self.i18n.t("mesh_analysis.to_rate"),
                self.i18n.t("mesh_analysis.source_file"),
                self.i18n.t("mesh_analysis.line_number"),
            ]
        )
        self.issue_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("mesh_analysis.file_name"),
                self.i18n.t("mesh_analysis.line_number"),
                self.i18n.t("mesh_analysis.severity"),
                self.i18n.t("mesh_analysis.issue_type"),
                self.i18n.t("mesh_analysis.field_name"),
                self.i18n.t("mesh_analysis.message"),
                self.i18n.t("mesh_analysis.raw_content"),
            ]
        )
        self.tabs.setTabText(0, self.i18n.t("mesh_analysis.source_files"))
        self.tabs.setTabText(1, self.i18n.t("mesh_analysis.link_details"))
        self.tabs.setTabText(2, self.i18n.t("mesh_analysis.active_build_order"))
        self.tabs.setTabText(3, self.i18n.t("mesh_analysis.events"))
        self._set_issue_tab_count(0)
        self.issue_empty_title.setText(self.i18n.t("mesh_analysis.no_parse_issues"))
        self.issue_empty_description.setText(self.i18n.t("mesh_analysis.no_parse_issues_description"))
        self._restore_column_widths()

    def _build_layout(self) -> None:
        toolbar = QHBoxLayout()
        for button in (
            self.import_button,
            self.import_folder_button,
            self.show_all_sources_button,
            self.cancel_button,
            self.refresh_button,
            self.open_folder_button,
            self.export_link_button,
            self.open_full_active_chart_button,
        ):
            toolbar.addWidget(button)
        toolbar.addWidget(self.generate_report_button)
        apply_feature_to_widget(self.feature_gate, "mesh.generate_report", self.generate_report_button)
        toolbar.addStretch(1)
        progress = QHBoxLayout()
        progress.addWidget(self.progress_bar, 1)
        progress.addWidget(self.progress_label)
        filters = QHBoxLayout()
        filters.addWidget(self.radio_filter)
        filters.addWidget(self.state_filter)
        filters.addWidget(self.peer_filter)
        filters.addWidget(self.keyword_filter, 1)
        source_page = QWidget()
        source_layout = QVBoxLayout(source_page)
        source_layout.addWidget(self.source_table)
        source_layout.addWidget(self.source_pagination)
        links_page = QWidget()
        links_layout = QVBoxLayout(links_page)
        links_layout.addLayout(filters)
        links_layout.addWidget(self.link_table, 1)
        links_layout.addWidget(self.link_pagination)
        links_layout.addWidget(self.detail_text)
        active_build_page = QWidget()
        active_build_layout = QVBoxLayout(active_build_page)
        active_build_layout.addWidget(self.active_build_order_table)
        event_page = QWidget()
        event_layout = QVBoxLayout(event_page)
        event_layout.addWidget(self.event_table)
        event_layout.addWidget(self.event_pagination)
        issue_page = QWidget()
        issue_layout = QVBoxLayout(issue_page)
        empty_layout = QVBoxLayout(self.issue_empty_widget)
        empty_layout.addStretch(1)
        self.issue_empty_title.setAlignment(Qt.AlignCenter)
        self.issue_empty_description.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.issue_empty_title)
        empty_layout.addWidget(self.issue_empty_description)
        empty_layout.addStretch(1)
        issue_layout.addWidget(self.issue_table)
        issue_layout.addWidget(self.issue_pagination)
        issue_layout.addWidget(self.issue_empty_widget, 1)
        self.tabs.addTab(source_page, "")
        self.tabs.addTab(links_page, "")
        self.tabs.addTab(active_build_page, "")
        self.tabs.addTab(event_page, "")
        self.tabs.addTab(issue_page, "")
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.tabs)
        splitter = QSplitter()
        splitter.addWidget(self.mr_table)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 4)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addLayout(toolbar)
        layout.addLayout(progress)
        layout.addWidget(splitter, 1)

    def _connect_signals(self) -> None:
        self.import_button.clicked.connect(self.import_logs)
        self.import_folder_button.clicked.connect(self.import_folder)
        self.show_all_sources_button.clicked.connect(self.show_all_source_files)
        self.cancel_button.clicked.connect(self.cancel_import)
        self.refresh_button.clicked.connect(lambda: self.refresh_all())
        self.open_folder_button.clicked.connect(self.open_mr_folder)
        self.generate_report_button.clicked.connect(self.generate_report)
        self.export_link_button.clicked.connect(self.export_link_details)
        self.open_full_active_chart_button.clicked.connect(self.open_full_active_chart)
        self.mr_table.itemSelectionChanged.connect(self._schedule_current_mr_selection)
        self.radio_filter.textChanged.connect(self._schedule_link_refresh)
        self.state_filter.currentIndexChanged.connect(self._schedule_link_refresh)
        self.peer_filter.textChanged.connect(self._schedule_link_refresh)
        self.keyword_filter.textChanged.connect(self._schedule_link_refresh)
        self.filter_timer.timeout.connect(self.refresh_link_table)
        self.mr_selection_timer.timeout.connect(self.select_current_mr)
        self.link_table.itemSelectionChanged.connect(self.show_link_detail)
        self.link_table.cellDoubleClicked.connect(self._open_peer_from_link_cell)
        self.source_table.cellDoubleClicked.connect(self._open_source_file_links)
        self.source_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.source_table.customContextMenuRequested.connect(self._show_source_context_menu)
        self.event_table.cellDoubleClicked.connect(self._open_peer_from_event_cell)
        self.source_pagination.pageChanged.connect(lambda page: self._set_page("source", page))
        self.link_pagination.pageChanged.connect(lambda page: self._set_page("link", page))
        self.event_pagination.pageChanged.connect(lambda page: self._set_page("event", page))
        self.issue_pagination.pageChanged.connect(lambda page: self._set_page("issue", page))
        for pagination in (self.source_pagination, self.link_pagination, self.event_pagination, self.issue_pagination):
            pagination.pageSizeChanged.connect(self._set_page_size)
        self.tabs.currentChanged.connect(lambda _index: self.refresh_current_tab())

    def create_mr(self) -> None:
        name, ok = QInputDialog.getText(self, self.i18n.t("mesh_analysis.create_mr"), self.i18n.t("mesh_analysis.mr_name"))
        if not ok:
            return
        try:
            profile = self.storage.create_mr_profile(name)
        except Exception as exc:
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.create_mr"), str(exc))
            return
        app_logger.log_info("MESH_MR_CREATED", profile.display_name)
        self.refresh_all(select_mr_id=profile.mr_id)

    def import_logs(self) -> None:
        profile = self._require_profile()
        if profile is None:
            return
        files, _ = QFileDialog.getOpenFileNames(self, self.i18n.t("mesh_analysis.import_logs"), str(self._import_start_dir()), FILE_FILTER)
        if files:
            self._start_import(profile, [Path(file) for file in files])

    def import_folder(self) -> None:
        profile = self._require_profile()
        if profile is None:
            return
        folder = QFileDialog.getExistingDirectory(self, self.i18n.t("mesh_analysis.import_folder"), str(self._import_start_dir()))
        if not folder:
            return
        files = MeshImportService(self.site_name, self.paths).discover_mesh_logs(Path(folder))
        self._start_import(profile, files)

    def _import_start_dir(self) -> Path:
        return PathPreferenceService(self.paths).get_default_mesh_import_dir(self.site_name)

    def export_link_details(self) -> None:
        profile = self._require_profile()
        if profile is None:
            return
        if self.export_worker is not None and self.export_worker.isRunning():
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), self.progress_label.text())
            return
        repo = self._repo()
        filters = self._current_link_filters()
        total, _rows = repo.query_links(1, 0, filters)
        if total <= 0:
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), "暂无可导出的链路明细数据")
            return
        radio = self._current_radio()
        export_dir = self.paths.mesh_mr_export_dir(self.site_name, profile.safe_folder_name)
        export_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"{_safe_filename(profile.display_name)}_链路明细_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        selected, _ = QFileDialog.getSaveFileName(self, "导出链路明细", str(export_dir / default_name), "Excel Files (*.xlsx)")
        if not selected:
            return
        path = Path(selected)
        if path.suffix.casefold() != ".xlsx":
            path = path.with_suffix(".xlsx")
        self.export_link_button.setEnabled(False)
        self.progress_label.setText(self.i18n.t("mesh_analysis.export_progress_query_links"))
        self.export_worker = MeshLinkDetailExportWorker(
            self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name),
            path,
            filters,
            self.current_source_file_id,
            radio,
            self,
        )
        self.export_worker.stageChanged.connect(lambda key: self.progress_label.setText(self.i18n.t(key)))
        self.export_worker.completed.connect(self._on_link_export_completed)
        self.export_worker.failed.connect(self._on_link_export_failed)
        self.export_worker.completed.connect(lambda _path: self._cleanup_export_worker())
        self.export_worker.failed.connect(lambda _error: self._cleanup_export_worker())
        self.export_worker.start()

    def _on_link_export_completed(self, path: str) -> None:
        self.export_link_button.setEnabled(True)
        self.progress_label.setText(f"链路明细已导出：{path}")
        QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), f"链路明细已导出：\n{path}")

    def _on_link_export_failed(self, error: str) -> None:
        self.export_link_button.setEnabled(True)
        self.progress_label.setText(f"导出链路明细失败：{error}")
        QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), f"导出链路明细失败：{error}")

    def _cleanup_export_worker(self) -> None:
        if self.export_worker is not None:
            self.export_worker.deleteLater()
            self.export_worker = None

    def open_full_active_chart(self) -> None:
        profile = self._require_profile()
        if profile is None:
            return
        radio = self._current_radio()
        source_label = self.current_source_file_name or self.i18n.t("mesh_analysis.all_source_files")
        dialog = MeshActiveLinkChartDialog(
            self.i18n,
            profile,
            self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name),
            radio,
            self.current_source_file_id,
            source_label,
            parent=None,
            owner_widget=self,
            detail_jump_handler=self.jump_to_mesh_link_detail,
        )
        self.peer_dialogs.append(dialog)
        dialog.finished.connect(lambda _result, dialog=dialog: self._remove_peer_dialog(dialog))
        dialog.show()

    def _current_radio(self) -> int | None:
        text = self.radio_filter.text().strip()
        return int(text) if text.isdigit() else None

    def _remove_peer_dialog(self, dialog: MeshPeerDetailDialog) -> None:
        if dialog in self.peer_dialogs:
            self.peer_dialogs.remove(dialog)
        dialog.deleteLater()

    def cancel_import(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        if self.report_worker and self.report_worker.isRunning():
            self.progress_label.setText("正在取消报告生成...")
            self.report_worker.cancel()

    def refresh_all(self, select_mr_id: str | None = None) -> None:
        current_id = select_mr_id or (self.current_profile.mr_id if self.current_profile else None)
        self.profiles = self._vehicle_mr_profiles()
        self.profile_by_id = {profile.mr_id: profile for profile in self.profiles}
        sorting = self.mr_table.isSortingEnabled()
        sort_column = self.mr_table.horizontalHeader().sortIndicatorSection()
        sort_order = self.mr_table.horizontalHeader().sortIndicatorOrder()
        self.mr_table.setSortingEnabled(False)
        self._suppress_mr_selection = True
        blocker = QSignalBlocker(self.mr_table)
        self.mr_table.setRowCount(len(self.profiles))
        selected_row = -1
        for row, profile in enumerate(self.profiles):
            if current_id and profile.mr_id == current_id:
                selected_row = row
            values = [
                profile.display_name,
                _display(profile.earliest_sample_time),
                _display(profile.latest_sample_time),
                profile.source_file_count,
                profile.sample_count,
                profile.link_record_count,
                profile.event_count,
                _display(profile.last_import_at),
            ]
            _set_row(self.mr_table, row, values, profile.mr_id)
        del blocker
        self.mr_table.setSortingEnabled(sorting)
        if sorting and sort_column >= 0:
            self.mr_table.sortItems(sort_column, sort_order)
        if self.profiles:
            target_id = current_id or self.profiles[0].mr_id
            selected_row = self._find_mr_row(str(target_id))
        if selected_row >= 0:
            self.mr_table.selectRow(selected_row)
            mr_id = self.mr_table.item(selected_row, 0).data(Qt.UserRole)
            self._suppress_mr_selection = False
            self._load_profile_by_id(str(mr_id))
        else:
            self._suppress_mr_selection = False
            self.current_profile = None
            self.current_source_file_id = None
            self.current_source_file_name = None
        self.refresh_current_mr_data()

    def _vehicle_mr_profiles(self) -> list[MeshMrProfile]:
        if self.repository is None or self.group_repository is None:
            return self.catalog_repo.list_profiles()
        group = self.group_repository.find_by_name(VEHICLE_MR_GROUP_NAME)
        if group is None or group.id is None:
            return []
        devices = self.repository.list(group_filter=int(group.id))
        return self.storage.sync_mr_profiles_from_devices(devices)

    def refresh_profiles(self, select_mr_id: str | None = None) -> None:
        self.refresh_all(select_mr_id)

    def _schedule_current_mr_selection(self) -> None:
        if self._suppress_mr_selection:
            return
        app_logger.log_info("MESH_MR_SWITCH_REQUESTED", f"row={self.mr_table.currentRow()}")
        self.mr_selection_timer.start()

    def select_current_mr(self) -> None:
        row = self.mr_table.currentRow()
        if row < 0:
            return
        item = self.mr_table.item(row, 0)
        if item is None:
            return
        self._load_profile_by_id(str(item.data(Qt.UserRole)))

    def _load_profile_by_id(self, mr_id: str) -> None:
        self.current_profile = self.profile_by_id.get(mr_id) or self.catalog_repo.get_profile(mr_id)
        if self.current_profile is None:
            return
        self.current_source_file_id = None
        self.current_source_file_name = None
        self.mr_load_generation += 1
        generation = self.mr_load_generation
        app_logger.log_info("MESH_MR_LOAD_STARTED", f"mr_id={mr_id}, generation={generation}, tab={self._current_tab_name()}")
        self.source_page = self.link_page = self.event_page = self.issue_page = 1
        self.dirty_tabs = {"source", "link", "active_build_order", "event", "issue"}
        self.refresh_current_tab(generation)
        app_logger.log_info("MESH_MR_LOAD_COMPLETED", f"mr_id={mr_id}, generation={generation}, tab={self._current_tab_name()}")

    def refresh_current_mr_data(self, current_tab_only: bool = False) -> None:
        if self.current_profile is None:
            for table in (self.source_table, self.link_table, self.active_build_order_table, self.event_table, self.issue_table):
                table.setRowCount(0)
            self.refresh_parse_issues()
            return
        repo = self._repo()
        self._ensure_current_derived_analysis(repo)
        if current_tab_only:
            self._render_tab(self._current_tab_name(), repo)
            return
        self._render_sources(repo)
        self.refresh_link_table()
        self._render_active_build_order(repo)
        self._render_events(repo)
        self.refresh_parse_issues(repo)
        self.dirty_tabs.clear()

    def refresh_current_tab(self, generation: int | None = None) -> None:
        if self.current_profile is None:
            return
        if generation is not None and generation != self.mr_load_generation:
            app_logger.log_info("MESH_MR_LOAD_DISCARDED", f"generation={generation}, current={self.mr_load_generation}")
            return
        tab = self._current_tab_name()
        if tab not in self.dirty_tabs and generation is None:
            return
        repo = self._repo()
        self._ensure_current_derived_analysis(repo)
        self._render_tab(tab, repo)
        self.dirty_tabs.discard(tab)

    def _render_tab(self, tab: str, repo: MeshMrRepository) -> None:
        if tab == "source":
            self._render_sources(repo)
        elif tab == "link":
            self._render_links(repo)
        elif tab == "active_build_order":
            self._render_active_build_order(repo)
        elif tab == "event":
            self._render_events(repo)
        elif tab == "issue":
            self.refresh_parse_issues(repo)

    def refresh_link_table(self) -> None:
        if self.current_profile is None:
            self.link_table.setRowCount(0)
            return
        self._render_links(self._repo())
        self.dirty_tabs.discard("link")

    def show_link_detail(self) -> None:
        row = self.link_table.currentRow()
        item = self.link_table.item(row, 0) if row >= 0 else None
        data = item.data(Qt.UserRole) if item else None
        if not isinstance(data, dict):
            self.detail_text.clear()
            return
        metrics = _json_dict(data.get("metrics_json"))
        deltas = _json_dict(data.get("deltas_json"))
        lines = [
            f"Session: {data.get('session_id') or '-'}",
            f"CPU: {metrics.get('local_cpu_percent')}/{metrics.get('peer_cpu_percent')}",
            f"Mem: {metrics.get('local_mem_percent')}/{metrics.get('peer_mem_percent')}",
            f"TxDesFreeCnt: {metrics.get('local_tx_des_free_cnt')}/{metrics.get('peer_tx_des_free_cnt')}",
            f"Tx/Rx: {metrics.get('local_tx')}/{metrics.get('peer_tx')}  {metrics.get('local_rx')}/{metrics.get('peer_rx')}",
            f"Retry/Err: {metrics.get('local_retry')}/{metrics.get('peer_retry')}  {metrics.get('local_err')}/{metrics.get('peer_err')}",
            f"Delta: {deltas}",
            f"Raw: {data.get('raw_line')}",
        ]
        self.detail_text.setPlainText("\n".join(lines))

    def open_mr_folder(self) -> None:
        profile = self._require_profile()
        if profile is None:
            return
        path = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(path)))

    def generate_report(self) -> None:
        if not self.feature_gate.is_enabled("mesh.generate_report"):
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), self.i18n.t("mesh_report.disabled"))
            return
        profile = self._require_profile()
        if profile is None:
            return
        if self.report_worker and self.report_worker.isRunning():
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), self.i18n.t("mesh_report.running"))
            return
        from PySide6.QtWidgets import QDialog
        from netconsole.ui.dialogs.mesh_report_settings_dialog import MeshReportSettingsDialog
        from netconsole.ui.mesh_log_workers import MeshAnalysisReportWorker

        dialog = MeshReportSettingsDialog(self.i18n, profile.display_name, self)
        if dialog.exec() != QDialog.Accepted:
            return
        options = dialog.options()
        self.report_open_output_dir = bool(options.open_output_dir_after_done)
        export_dir = self.paths.mesh_mr_export_dir(self.site_name, profile.safe_folder_name)
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_mr = _safe_filename(profile.display_name)
        output_path = export_dir / f"{filename_mr}_MR原始MESH日志分析报告_{timestamp}.xlsx"
        self.progress_bar.setValue(0)
        self.progress_label.setText(self.i18n.t("mesh_report.generating"))
        output_path = export_dir / f"{filename_mr}_MR原始MESH日志分析报告_{timestamp}.xlsx"
        self.report_worker = MeshAnalysisReportWorker(self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name), profile.display_name, output_path, options, self)
        self.report_worker.progress.connect(self._on_report_progress)
        self.report_worker.completed.connect(self._on_report_finished)
        self.report_worker.failed.connect(self._on_report_failed)
        self.report_worker.cancelled.connect(self._on_report_cancelled)
        self.report_worker.completed.connect(lambda _path: self._cleanup_report_worker())
        self.report_worker.failed.connect(lambda _error: self._cleanup_report_worker())
        self.report_worker.cancelled.connect(self._cleanup_report_worker)
        self.report_worker.start()

    def _on_report_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"报告生成进度 {value}%：{REPORT_STAGE_LABELS.get(message, message)}")

    def _on_report_finished(self, path: str) -> None:
        self.progress_bar.setValue(100)
        self.progress_label.setText(self.i18n.t("mesh_report.done", path=path))
        QMessageBox.information(self, self.i18n.t("mesh_report.generate_report"), self.i18n.t("mesh_report.done", path=path))

    def _on_report_failed(self, error: str) -> None:
        self.progress_label.setText(self.i18n.t("mesh_report.failed", error=error))
        QMessageBox.warning(self, self.i18n.t("mesh_report.generate_report"), error)

    def _on_report_cancelled(self) -> None:
        self.progress_label.setText(self.i18n.t("mesh_report.cancelled"))

    def _on_report_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        stage, file_index, file_total, file_name = _parse_report_progress_message(message)
        stage_label = REPORT_STAGE_LABELS.get(stage, stage)
        if stage.startswith("workers:"):
            stage_label = f"准备工作进程：{stage.split(':', 1)[1]} 个"
        if file_total > 0:
            self.progress_label.setText(
                f"正在生成 MR 原始MESH分析报告：文件 {file_index}/{file_total}：{file_name}；阶段：{stage_label}；进度：{value}%"
            )
        else:
            self.progress_label.setText(f"报告生成进度 {value}%：{stage_label}")

    def _on_report_finished(self, path: str) -> None:
        self.progress_bar.setValue(100)
        self.progress_label.setText(self.i18n.t("mesh_report.done", path=path))
        if self.report_open_output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.fspath(Path(path))))
        QMessageBox.information(self, self.i18n.t("mesh_report.generate_report"), self.i18n.t("mesh_report.done", path=path))

    def _cleanup_report_worker(self) -> None:
        if self.report_worker is not None:
            self.report_worker.deleteLater()
            self.report_worker = None

    def _start_import(self, profile: MeshMrProfile, files: list[Path]) -> None:
        if not files:
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), self.i18n.t("mesh_analysis.no_files"))
            return
        PathPreferenceService(self.paths).remember_last_mesh_import_dir(files[0].parent)
        self.progress_bar.setValue(0)
        self.worker = MeshLogImportWorker(self.site_name, self.paths, profile, files)
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_import_finished)
        self.worker.failed.connect(self._on_import_failed)
        self.worker.cancelled.connect(self._on_import_cancelled)
        self.worker.completed.connect(self._cleanup_worker)
        self.worker.failed.connect(lambda _error: self._cleanup_worker())
        self.worker.cancelled.connect(self._cleanup_worker)
        self.worker.start()
        app_logger.log_info("MESH_PARSE_STARTED", profile.display_name)

    def _on_progress(self, file_index: int, total_files: int, lines: int, parsed: int, skipped: int) -> None:
        self.progress_bar.setValue(int(file_index / max(total_files, 1) * 100))
        self.progress_label.setText(self.i18n.t("mesh_analysis.progress", file=file_index, total=total_files, lines=lines, parsed=parsed, skipped=skipped))

    def _on_import_finished(self, result) -> None:
        self.progress_bar.setValue(100)
        self.progress_label.setText(self.i18n.t("mesh_analysis.import_done", count=result.imported_count, duplicate=result.duplicate_count))
        current_id = self.current_profile.mr_id if self.current_profile else None
        self.refresh_all(select_mr_id=current_id)
        app_logger.log_info("MESH_ANALYSIS_COMPLETED", self.progress_label.text())

    def _on_import_failed(self, error: str) -> None:
        QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), error)
        app_logger.log_error("MESH_PARSE_FAILED", error)

    def _on_import_cancelled(self) -> None:
        self.progress_label.setText(self.i18n.t("mesh_analysis.cancelled"))

    def _cleanup_worker(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def _render_sources(self, repo: MeshMrRepository) -> None:
        rows = repo.list_source_files()
        total, page_rows = _page(rows, self.source_page, self.page_size)
        self.source_pagination.set_state(PaginationState(self.page_size, self.source_page, total, max((total + self.page_size - 1) // self.page_size, 1)))
        _begin_table_update(self.source_table)
        self.source_table.setRowCount(len(page_rows))
        for row_index, row in enumerate(page_rows):
            values = [
                row.get("archived_filename"),
                "当前" if self.current_source_file_id is not None and int(row.get("id") or 0) == int(self.current_source_file_id) else "-",
                row.get("archived_path"),
                _source_file_status(row),
                row.get("file_size"),
                str(row.get("sha256") or "")[:12],
                row.get("imported_at"),
                row.get("first_sample_time"),
                row.get("last_sample_time"),
                row.get("parse_status"),
                row.get("records_parsed"),
                row.get("records_skipped"),
                row.get("duplicate_records"),
                row.get("issue_count"),
                row.get("parser_version"),
            ]
            _set_row(self.source_table, row_index, values, row)
        _end_table_update(self.source_table)

    def _render_links(self, repo: MeshMrRepository) -> None:
        filters = self._current_link_filters()
        total, rows = repo.query_links(self.page_size, (self.link_page - 1) * self.page_size, filters)
        self.link_pagination.set_state(PaginationState(self.page_size, self.link_page, total, max((total + self.page_size - 1) // self.page_size, 1)))
        _begin_table_update(self.link_table)
        self.link_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            metrics = _json_dict(row.get("metrics_json"))
            peer = format_mac_h3c(row.get("peer_mac_normalized")) if row.get("peer_mac_normalized") else row.get("peer_mac_raw")
            values = [
                row.get("record_seq") or row.get("source_line_number"),
                row.get("sample_time"),
                row.get("radio"),
                row.get("link_state"),
                row.get("peer_mac_raw") or peer,
                row.get("peer_ap_name") or "-",
                format_mac_h3c(row.get("peer_ap_mac")) if row.get("peer_ap_mac") else "-",
                row.get("peer_site") or "-",
                format_mac_h3c(row.get("peer_radio_mac")) if row.get("peer_radio_mac") else "-",
                row.get("peer_radio") or row.get("peer_radio_label") or "-",
                row.get("establish_time"),
                row.get("duration_text"),
                row.get("link_count"),
                metrics.get("local_rssi_db"),
                metrics.get("peer_rssi_db"),
                row.get("local_noise_dbm"),
                row.get("peer_noise_dbm"),
                row.get("local_signal_dbm"),
                row.get("peer_signal_dbm"),
                metrics.get("local_rate_raw"),
                metrics.get("peer_rate_raw"),
                metrics.get("local_tx_busy"),
                metrics.get("peer_tx_busy"),
                metrics.get("local_rx_busy"),
                metrics.get("peer_rx_busy"),
                row.get("archived_filename"),
                row.get("source_line_number"),
            ]
            _set_row(self.link_table, row_index, values, row)
        _end_table_update(self.link_table)
        if not self._link_column_widths_changed and not isinstance(self.settings.get_value("mesh_analysis/column_widths/link", None), list):
            self._restoring_column_widths = True
            try:
                apply_table_autosize(self.link_table)
            finally:
                self._restoring_column_widths = False
        self.link_table.sortItems(0, Qt.AscendingOrder)
        self.restyle_visible_link_rows()

    def _render_active_build_order(self, repo: MeshMrRepository) -> None:
        radio = int(self.radio_filter.text()) if self.radio_filter.text().strip().isdigit() else None
        rows = repo.query_active_link_build_order(self.current_source_file_id, radio)
        _begin_table_update(self.active_build_order_table)
        self.active_build_order_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("sequence"),
                row.get("radio"),
                format_mac_h3c(row.get("active_peer_mac")) if row.get("active_peer_mac") else "",
                row.get("peer_ap_name"),
                row.get("peer_site"),
                row.get("peer_radio"),
                row.get("build_start_time"),
                row.get("build_end_time"),
                row.get("main_link_duration_seconds"),
                row.get("reported_duration_seconds"),
                row.get("sample_count"),
                row.get("avg_mr_rssi"),
                row.get("min_mr_rssi"),
                row.get("max_mr_rssi"),
                row.get("avg_tx_busy"),
                row.get("avg_rx_busy"),
                self.i18n.t("mesh_analysis.build_result_normal") if row.get("build_result") == "normal" else self.i18n.t("mesh_analysis.build_result_short"),
                row.get("source_file"),
            ]
            _set_row(self.active_build_order_table, row_index, values, row)
        _end_table_update(self.active_build_order_table)
        app_logger.log_info(
            "MESH_ACTIVE_BUILD_ORDER_RENDERED",
            f"source_file_id={self.current_source_file_id or 'ALL'}, radio={radio if radio is not None else 'ALL'}, rows={len(rows)}",
        )

    def _render_events(self, repo: MeshMrRepository) -> None:
        total, rows = repo.query_events(self.page_size, (self.event_page - 1) * self.page_size, self.current_source_file_id)
        self.event_pagination.set_state(PaginationState(self.page_size, self.event_page, total, max((total + self.page_size - 1) // self.page_size, 1)))
        _begin_table_update(self.event_table)
        self.event_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            details = _json_dict(row.get("details_json"))
            values = [
                row.get("event_time"),
                row.get("radio"),
                self._event_label(str(row.get("event_type"))),
                row.get("from_peer_mac"),
                row.get("to_peer_mac"),
                row.get("observed_window_ms"),
                details.get("from_local_rssi"),
                details.get("to_local_rssi"),
                details.get("from_peer_rssi"),
                details.get("to_peer_rssi"),
                details.get("from_local_rate"),
                details.get("to_local_rate"),
                details.get("source_file"),
                row.get("source_line_number"),
            ]
            _set_row(self.event_table, row_index, values, row)
        _end_table_update(self.event_table)

    def refresh_parse_issues(self, repo: MeshMrRepository | None = None) -> None:
        if self.current_profile is None and repo is None:
            self._set_issue_tab_count(0)
            self.issue_table.setRowCount(0)
            self.issue_table.hide()
            self.issue_pagination.hide()
            self.issue_empty_widget.show()
            return
        self._render_issues(repo or self._repo())

    def _render_issues(self, repo: MeshMrRepository) -> None:
        total, rows = repo.query_issues(self.page_size, (self.issue_page - 1) * self.page_size, self.current_source_file_id)
        self._set_issue_tab_count(total)
        if total <= 0:
            self.issue_table.setRowCount(0)
            self.issue_table.hide()
            self.issue_pagination.hide()
            self.issue_empty_widget.show()
            self.issue_pagination.set_state(PaginationState(self.page_size, 1, 0, 1))
            return
        self.issue_empty_widget.hide()
        self.issue_table.show()
        self.issue_pagination.show()
        self.issue_pagination.set_state(PaginationState(self.page_size, self.issue_page, total, max((total + self.page_size - 1) // self.page_size, 1)))
        _begin_table_update(self.issue_table)
        self.issue_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [Path(str(row.get("source_file"))).name, row.get("line_number"), row.get("severity"), row.get("issue_type"), row.get("field_name"), row.get("message"), row.get("raw_line")]
            _set_row(self.issue_table, row_index, values)
        _end_table_update(self.issue_table)

    def _set_issue_tab_count(self, count: int) -> None:
        if self.tabs.count() >= 5:
            self.tabs.setTabText(4, self.i18n.t("mesh_analysis.parse_issues_with_count", count=count))

    def _ensure_current_derived_analysis(self, repo: MeshMrRepository) -> None:
        if self.derived_worker is not None and self.derived_worker.isRunning():
            return
        if not repo.needs_derived_analysis_rebuild():
            return
        self.progress_label.setText(self.i18n.t("mesh_analysis.rebuilding_derived_analysis"))
        self.derived_worker = MeshDerivedAnalysisRebuildWorker(repo.path, self)
        self.derived_worker.completed.connect(self._on_derived_rebuild_finished)
        self.derived_worker.failed.connect(self._on_derived_rebuild_failed)
        self.derived_worker.completed.connect(self._cleanup_derived_worker)
        self.derived_worker.failed.connect(lambda _error: self._cleanup_derived_worker())
        self.derived_worker.start()
        app_logger.log_info("MESH_DERIVED_REBUILD_STARTED", repo.path.name)

    def _on_derived_rebuild_finished(self) -> None:
        self.progress_label.setText(self.i18n.t("mesh_analysis.derived_analysis_ready"))
        current_id = self.current_profile.mr_id if self.current_profile else None
        if current_id:
            self.refresh_all(select_mr_id=current_id)
        app_logger.log_info("MESH_DERIVED_REBUILD_COMPLETED", current_id or "")

    def _on_derived_rebuild_failed(self, error: str) -> None:
        self.progress_label.setText(error)
        QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), error)
        app_logger.log_error("MESH_DERIVED_REBUILD_FAILED", error)

    def _cleanup_derived_worker(self) -> None:
        if self.derived_worker is not None:
            self.derived_worker.deleteLater()
            self.derived_worker = None

    def _set_page(self, page_name: str, page: int) -> None:
        setattr(self, f"{page_name}_page", page)
        self.dirty_tabs.add(page_name)
        if self._current_tab_name() == page_name:
            self.refresh_current_tab()

    def _set_page_size(self, page_size: int) -> None:
        self.page_size = page_size
        self.source_page = self.link_page = self.event_page = self.issue_page = 1
        self.dirty_tabs = {"source", "link", "active_build_order", "event", "issue"}
        self.refresh_current_tab()

    def show_all_source_files(self) -> None:
        self.current_source_file_id = None
        self.current_source_file_name = None
        self.link_page = self.event_page = self.issue_page = 1
        repo = self._repo() if self.current_profile is not None else None
        if repo is None:
            return
        self._render_sources(repo)
        self._render_links(repo)
        self._render_active_build_order(repo)
        self._render_events(repo)
        self.refresh_parse_issues(repo)
        self.progress_label.setText("当前显示：全部文件")

    def _open_source_file_links(self, row: int, _column: int = 0) -> None:
        item = self.source_table.item(row, 0) if row >= 0 else None
        data = item.data(Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        payload = self._source_open_payload(data)
        app_logger.log_info(
            "MESH_SOURCE_DOUBLE_CLICK",
            f"mr_id={payload['mr_id']} source_file_id={payload['source_file_id']} file_path={payload['file_path']} current_tab={payload['current_tab']}",
        )
        QTimer.singleShot(0, lambda payload=payload: self._open_link_detail_for_source(payload))

    def _show_source_file_links(self, data: dict[str, object]) -> None:
        self._open_link_detail_for_source(self._source_open_payload(data))

    def _source_open_payload(self, data: dict[str, object]) -> dict[str, object]:
        return {
            "source_file_id": int(data.get("id") or 0),
            "file_name": str(data.get("archived_filename") or data.get("original_filename") or data.get("id") or ""),
            "file_path": str(data.get("archived_path") or data.get("original_path") or ""),
            "mr_id": self.current_profile.mr_id if self.current_profile is not None else "",
            "mr_name": self.current_profile.display_name if self.current_profile is not None else "",
            "current_tab": self._current_tab_name(),
        }

    def _open_link_detail_for_source(self, payload: dict[str, object]) -> None:
        source_file_id = int(payload.get("source_file_id") or 0)
        if source_file_id <= 0 or self.current_profile is None:
            return
        if payload.get("mr_id") and str(payload.get("mr_id")) != self.current_profile.mr_id:
            return
        self.current_source_file_id = source_file_id
        self.current_source_file_name = str(payload.get("file_name") or source_file_id)
        self.link_page = self.event_page = self.issue_page = 1
        repo = self._repo()
        self._render_sources(repo)
        self.tabs.setCurrentIndex(1)
        self._render_links(repo)
        self._render_active_build_order(repo)
        self._render_events(repo)
        self.refresh_parse_issues(repo)
        self.progress_label.setText(f"当前显示文件：{self.current_source_file_name}")

    def jump_to_mesh_link_detail(self, target: dict[str, object]) -> None:
        if self.current_profile is None:
            return
        repo = self._repo()
        filters = self._current_link_filters()
        position = repo.find_link_detail_row_position(
            str(target.get("session_id") or ""),
            str(target.get("sample_time") or ""),
            str(target.get("peer_mac") or "") or None,
            target.get("radio"),
            str(target.get("state") or "") or None,
            self.page_size,
            filters,
        )
        if position is None:
            filters = {}
            self._clear_link_filters()
            position = repo.find_link_detail_row_position(
                str(target.get("session_id") or ""),
                str(target.get("sample_time") or ""),
                str(target.get("peer_mac") or "") or None,
                target.get("radio"),
                str(target.get("state") or "") or None,
                self.page_size,
                filters,
            )
        if position is None:
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), "Cannot locate the selected mesh link row.")
            return
        self.tabs.setCurrentIndex(1)
        self.link_page = position.page_no
        self._render_links(repo)
        row = self._find_link_table_row_by_id(position.link_id)
        if row < 0 and 0 <= position.index_in_page < self.link_table.rowCount():
            row = position.index_in_page
        if row < 0:
            return
        self.link_table.selectRow(row)
        item = self.link_table.item(row, 0)
        if item is not None:
            self.link_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self._highlight_link_row(row)

    def _current_link_filters(self) -> dict[str, object]:
        return {
            "source_file_id": self.current_source_file_id,
            "radio": self._current_radio(),
            "state": str(self.state_filter.currentData()).strip().upper() if self.state_filter.currentData() not in (None, "") else None,
            "peer": self.peer_filter.text().strip() or None,
            "keyword": self.keyword_filter.text().strip() or None,
        }

    def _clear_link_filters(self) -> None:
        for widget in (self.radio_filter, self.peer_filter, self.keyword_filter):
            blocker = QSignalBlocker(widget)
            widget.clear()
            del blocker
        blocker = QSignalBlocker(self.state_filter)
        self.state_filter.setCurrentIndex(0)
        del blocker

    def _find_link_table_row_by_id(self, link_id: int) -> int:
        for row in range(self.link_table.rowCount()):
            item = self.link_table.item(row, 0)
            data = item.data(Qt.UserRole) if item else None
            if isinstance(data, dict) and int(data.get("id") or 0) == int(link_id):
                return row
        return -1

    def _highlight_link_row(self, row: int) -> None:
        color = QColor("#fde68a")
        for column in range(self.link_table.columnCount()):
            item = self.link_table.item(row, column)
            if item is not None:
                item.setBackground(color)
        QTimer.singleShot(1600, self.restyle_visible_link_rows)

    def restyle_visible_link_rows(self) -> None:
        base = self.link_table.palette().base()
        alternate = self.link_table.palette().alternateBase()
        active_color = QColor("#22c55e")
        default_color = self.link_table.palette().text().color()
        for row in range(self.link_table.rowCount()):
            data_item = self.link_table.item(row, 0)
            data = data_item.data(Qt.UserRole) if data_item else {}
            group_index = int(data.get("sample_group_index") or 0) if isinstance(data, dict) else 0
            background = base if group_index % 2 == 0 else alternate
            is_active = isinstance(data, dict) and data.get("link_state") == "ACTIVE"
            for column in range(self.link_table.columnCount()):
                item = self.link_table.item(row, column)
                if item is None:
                    continue
                item.setBackground(background)
                font = item.font()
                font.setBold(is_active)
                item.setFont(font)
                item.setForeground(active_color if is_active else default_color)

    def _schedule_link_refresh(self, *_args: object) -> None:
        self.link_page = 1
        self.filter_timer.start()

    def _mark_link_column_width_changed(self, _section: int, _old_size: int, _new_size: int) -> None:
        if self._restoring_column_widths or self._populating_tables:
            return
        self._link_column_widths_changed = True

    def _setup_column_states(self) -> None:
        defaults = {
            "mr": [180, 180, 180, 90, 100, 120, 90, 180],
            "source": [180, 90, 320, 100, 90, 120, 180, 180, 180, 100, 90, 90, 90, 80, 120],
            "link": [90, 180, 70, 90, 180, 180, 140, 140, 150, 110, 140, 110, 80, 90, 90, 90, 90, 90, 90, 110, 110, 90, 90, 90, 90, 240, 80],
            "active_build_order": [70, 70, 160, 180, 140, 100, 180, 180, 130, 130, 90, 100, 100, 100, 90, 90, 100, 220],
            "event": [180, 60, 140, 150, 150, 120, 110, 110, 110, 110, 110, 110, 240, 70],
            "issue": [180, 70, 90, 140, 120, 240, 320],
        }
        tables = {"mr": self.mr_table, "source": self.source_table, "link": self.link_table, "active_build_order": self.active_build_order_table, "event": self.event_table, "issue": self.issue_table}
        for key, table in tables.items():
            state = MeshTableColumnState(self.settings, table, f"mesh_analysis/column_widths/{key}", defaults[key])
            self.column_states[key] = state
            self._restoring_column_widths = True
            try:
                state.restore()
            finally:
                self._restoring_column_widths = False

    def _restore_column_widths(self) -> None:
        self._restoring_column_widths = True
        try:
            for state in getattr(self, "column_states", {}).values():
                state.restore()
        finally:
            self._restoring_column_widths = False

    def _open_peer_from_link_cell(self, row: int, column: int) -> None:
        if column not in {3, 4} or self.current_profile is None:
            return
        item = self.link_table.item(row, 0)
        data = item.data(Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        peer = data.get("peer_mac_normalized")
        if not peer:
            return
        link_id = int(data.get("id") or 0) or None
        self._open_peer_dialog(str(peer), int(data.get("radio") or 0), str(data.get("session_id") or ""), link_id, self.current_source_file_id)

    def _open_peer_from_event_cell(self, row: int, column: int) -> None:
        if column not in {3, 4} or self.current_profile is None:
            return
        text = self.event_table.item(row, column).text() if self.event_table.item(row, column) else ""
        peer = text.replace("-", "").replace(":", "").lower()
        if len(peer) == 12:
            radio = int(self.event_table.item(row, 1).text()) if self.event_table.item(row, 1) and self.event_table.item(row, 1).text().isdigit() else None
            self._open_peer_dialog(peer, radio, "", None, self.current_source_file_id)

    def _open_peer_dialog(self, peer_mac: str, radio: int | None, session_id: str, anchor_link_id: int | None = None, source_file_id: int | None = None) -> None:
        if self.current_profile is None:
            return
        dialog = MeshPeerDetailDialog(
            self.i18n,
            self.current_profile,
            self.paths.mesh_mr_db_path(self.site_name, self.current_profile.safe_folder_name),
            peer_mac,
            radio,
            session_id,
            None,
            anchor_link_id=anchor_link_id,
            source_file_id=source_file_id,
            owner_widget=self,
            detail_jump_handler=self.jump_to_mesh_link_detail,
        )
        dialog.destroyed.connect(lambda _=None, d=dialog: self.peer_dialogs.remove(d) if d in self.peer_dialogs else None)
        self.peer_dialogs.append(dialog)
        dialog.show()

    def _show_source_context_menu(self, pos) -> None:
        row_index = self.source_table.rowAt(pos.y())
        if row_index < 0:
            return
        item = self.source_table.item(row_index, 0)
        data = item.data(Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        path = Path(str(data.get("archived_path") or data.get("original_path") or ""))
        menu = QMenu(self)
        show_file_action = menu.addAction("显示此文件链路明细")
        show_all_action = menu.addAction("显示全部文件")
        menu.addSeparator()
        open_action = menu.addAction("打开所在目录")
        copy_action = menu.addAction("复制文件路径")
        menu.addSeparator()
        delete_action = menu.addAction("删除本地源文件")
        open_action.setEnabled(path.parent.exists())
        copy_action.setEnabled(bool(str(path)))
        delete_action.setEnabled(path.exists() and path.is_file() and not str(data.get("deleted_at") or ""))
        selected = menu.exec(self.source_table.viewport().mapToGlobal(pos))
        if selected is show_file_action:
            self._show_source_file_links(data)
        elif selected is show_all_action:
            self.show_all_source_files()
        elif selected is open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        elif selected is copy_action:
            QApplication.clipboard().setText(str(path))
        elif selected is delete_action:
            self._delete_source_file(data)

    def _delete_source_file(self, data: dict[str, object]) -> None:
        source_file_id = int(data.get("id") or 0)
        if source_file_id <= 0 or self.current_profile is None:
            return
        path = Path(str(data.get("archived_path") or ""))
        if not path.exists():
            self._repo().mark_source_file_missing(source_file_id)
            self._render_sources(self._repo())
            return
        if not path.is_file():
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), "只能删除本地源文件，不能删除目录。")
            return
        answer = QMessageBox.question(
            self,
            self.i18n.t("mesh_analysis.title"),
            f"确定要删除本地源文件吗？\n\n路径：{path}\n\n此操作只删除磁盘上的源文件，不删除数据库中的解析结果。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        repo = self._repo()
        try:
            path.unlink()
            repo.mark_source_file_deleted(source_file_id)
        except OSError as exc:
            repo.mark_source_file_delete_failed(source_file_id, str(exc))
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), str(exc))
        self._render_sources(repo)

    def _show_source_context_menu(self, pos) -> None:
        row_index = self.source_table.rowAt(pos.y())
        if row_index < 0:
            return
        item = self.source_table.item(row_index, 0)
        data = item.data(Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        path = Path(str(data.get("archived_path") or data.get("original_path") or ""))
        source_file_id = int(data.get("id") or 0)
        repo = self._repo()
        counts = repo.count_parsed_data_by_source_file(source_file_id) if source_file_id > 0 else {"links": 0, "events": 0, "issues": 0, "caches": 0}
        has_parsed_data = any(int(counts.get(key, 0)) > 0 for key in ("links", "events", "issues", "caches"))
        menu = QMenu(self)
        show_file_action = menu.addAction("显示此文件链路明细")
        show_all_action = menu.addAction("显示全部文件")
        menu.addSeparator()
        open_action = menu.addAction("打开所在目录")
        copy_action = menu.addAction("复制文件路径")
        menu.addSeparator()
        delete_action = menu.addAction("删除本地源文件")
        delete_parsed_action = menu.addAction("删除解析数据")
        delete_all_action = menu.addAction("删除本地源文件和解析数据")
        show_file_action.setEnabled(has_parsed_data)
        open_action.setEnabled(path.parent.exists())
        copy_action.setEnabled(bool(str(path)))
        delete_action.setEnabled(path.exists() and path.is_file() and not str(data.get("deleted_at") or ""))
        delete_parsed_action.setEnabled(source_file_id > 0 and has_parsed_data)
        delete_all_action.setEnabled((path.exists() and path.is_file()) or (source_file_id > 0 and has_parsed_data))
        selected = menu.exec(self.source_table.viewport().mapToGlobal(pos))
        if selected is show_file_action:
            self._show_source_file_links(data)
        elif selected is show_all_action:
            self.show_all_source_files()
        elif selected is open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        elif selected is copy_action:
            QApplication.clipboard().setText(str(path))
        elif selected is delete_action:
            self._delete_source_file(data)
        elif selected is delete_parsed_action:
            self._delete_parsed_data(data, delete_local_file=False)
        elif selected is delete_all_action:
            self._delete_parsed_data(data, delete_local_file=True)

    def _delete_source_file(self, data: dict[str, object]) -> None:
        source_file_id = int(data.get("id") or 0)
        if source_file_id <= 0 or self.current_profile is None:
            return
        path = Path(str(data.get("archived_path") or ""))
        repo = self._repo()
        if not path.exists():
            repo.mark_source_file_missing(source_file_id)
            self._render_sources(repo)
            self.progress_label.setText("文件不存在，已标记为文件缺失。")
            return
        if not path.is_file():
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), "只能删除本地源文件，不能删除目录。")
            return
        answer = QMessageBox.question(
            self,
            self.i18n.t("mesh_analysis.title"),
            f"确定要删除本地源文件吗？\n\n路径：{path}\n\n此操作只删除磁盘上的源文件，不删除数据库中的解析结果。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            path.unlink()
            repo.mark_source_file_deleted(source_file_id)
            self.progress_label.setText("已删除本地源文件，解析数据仍可查看。")
        except OSError as exc:
            repo.mark_source_file_delete_failed(source_file_id, str(exc))
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), f"删除失败：{exc}")
        self._render_sources(repo)

    def _delete_parsed_data(self, data: dict[str, object], delete_local_file: bool = False) -> None:
        source_file_id = int(data.get("id") or 0)
        if source_file_id <= 0 or self.current_profile is None:
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), "该源文件缺少有效 source_file_id，无法安全删除对应解析数据。")
            return
        repo = self._repo()
        counts = repo.count_parsed_data_by_source_file(source_file_id)
        file_name = str(data.get("archived_filename") or data.get("original_filename") or source_file_id)
        path = Path(str(data.get("archived_path") or ""))
        if delete_local_file:
            message = (
                "确定要删除本地源文件和对应解析数据吗？\n\n"
                f"文件名：{file_name}\n"
                f"路径：{path}\n"
                f"链路明细：{counts['links']} 条\n"
                f"事件：{counts['events']} 条\n"
                f"解析问题：{counts['issues']} 条\n\n"
                "此操作会删除本地文件，并删除数据库中的解析结果。"
            )
        else:
            message = (
                "确定要删除该源文件对应的解析数据吗？\n\n"
                f"文件名：{file_name}\n"
                f"源文件ID：{source_file_id}\n"
                f"链路明细：{counts['links']} 条\n"
                f"事件：{counts['events']} 条\n"
                f"解析问题：{counts['issues']} 条\n\n"
                "此操作只删除数据库中的解析结果，不删除本地源文件。\n"
                "删除后该文件需要重新导入才会恢复解析数据。"
            )
        answer = QMessageBox.question(
            self,
            self.i18n.t("mesh_analysis.title"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        result = repo.delete_parsed_data_by_source_file(source_file_id)
        if not result.ok:
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), result.message or "删除解析数据失败")
            return
        local_delete_error = ""
        if delete_local_file:
            if path.exists() and path.is_file():
                try:
                    path.unlink()
                    repo.mark_source_file_deleted(source_file_id)
                except OSError as exc:
                    local_delete_error = str(exc)
                    repo.mark_source_file_delete_failed(source_file_id, local_delete_error)
            elif path.exists() and not path.is_file():
                local_delete_error = "路径是目录，已拒绝删除。"
                repo.mark_source_file_delete_failed(source_file_id, local_delete_error)
            else:
                repo.mark_source_file_deleted(source_file_id)
        if self.current_source_file_id == source_file_id:
            self.current_source_file_id = None
            self.current_source_file_name = None
            self.link_page = self.event_page = self.issue_page = 1
        current_id = self.current_profile.mr_id
        self.refresh_all(select_mr_id=current_id)
        if local_delete_error:
            QMessageBox.warning(self, self.i18n.t("mesh_analysis.title"), f"解析数据已删除，但本地源文件删除失败：{local_delete_error}")
        self.progress_label.setText(
            f"已删除解析数据：链路 {result.deleted_links} 条，事件 {result.deleted_events} 条，解析问题 {result.deleted_issues} 条。当前已切换为全部文件。"
        )

    def _find_mr_row(self, mr_id: str) -> int:
        for row in range(self.mr_table.rowCount()):
            item = self.mr_table.item(row, 0)
            if item is not None and str(item.data(Qt.UserRole)) == mr_id:
                return row
        return 0 if self.mr_table.rowCount() else -1

    def _event_label(self, event_type: str) -> str:
        return {
            "ACTIVE_SWITCH": self.i18n.t("mesh_analysis.active_switch"),
            "NO_ACTIVE": self.i18n.t("mesh_analysis.no_active"),
            "MULTI_ACTIVE": self.i18n.t("mesh_analysis.multiple_active"),
            "LINK_REESTABLISHED": self.i18n.t("mesh_analysis.link_reestablished"),
            "COUNTER_RESET": self.i18n.t("mesh_analysis.counter_reset"),
        }.get(event_type, event_type)

    def _require_profile(self) -> MeshMrProfile | None:
        if self.current_profile is None:
            QMessageBox.information(self, self.i18n.t("mesh_analysis.title"), self.i18n.t("mesh_analysis.select_mr_first"))
            return None
        return self.current_profile

    def _repo(self) -> MeshMrRepository:
        assert self.current_profile is not None
        mr_id = self.current_profile.mr_id
        repo = self.repo_cache.get(mr_id)
        if repo is not None:
            app_logger.log_info("MESH_MR_CACHE_HIT", mr_id)
            return repo
        app_logger.log_info("MESH_MR_CACHE_MISS", mr_id)
        repo = MeshMrRepository(self.paths.mesh_mr_db_path(self.site_name, self.current_profile.safe_folder_name))
        self.repo_cache[mr_id] = repo
        return repo

    def _current_tab_name(self) -> str:
        return {0: "source", 1: "link", 2: "active_build_order", 3: "event", 4: "issue"}.get(self.tabs.currentIndex(), "source")


def _display(value) -> str:
    if value is None or value == "":
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="milliseconds")
    return str(value)


def _source_file_status(row: dict[str, object]) -> str:
    if str(row.get("parsed_delete_error") or "") or str(row.get("delete_error") or ""):
        return "删除失败"
    status = str(row.get("file_status") or "").strip().lower()
    if status == "all_deleted" or (str(row.get("deleted_at") or "") and str(row.get("parsed_deleted_at") or "")):
        return "源文件和解析数据已删除"
    if status == "parsed_deleted" or str(row.get("parsed_deleted_at") or ""):
        return "解析数据已删除"
    if status == "deleted" or str(row.get("deleted_at") or ""):
        return "已删除"
    if status == "missing" or int(row.get("file_exists") or 0) == 0:
        return "文件缺失"
    if status in {"ok", "exists", ""}:
        return "正常"
    return status or "未知"


class _SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: object | None = None) -> None:
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortableTableWidgetItem) and self.sort_value is not None and other.sort_value is not None:
            return self.sort_value < other.sort_value
        return self.text() < other.text()


def _set_row(table: QTableWidget, row_index: int, values: list[object], user_data: object | None = None) -> None:
    row_height = max(table.fontMetrics().height() + 12, 32)
    table.setRowHeight(row_index, row_height)
    for column, value in enumerate(values):
        text = _display(value)
        sort_value = value if isinstance(value, int | float) else None
        if sort_value is None and column == 0 and table.property("netconsole_natural_sort_first_column"):
            sort_value = natural_text_key(value)
        item = _SortableTableWidgetItem(text, sort_value)
        item.setToolTip(text)
        if column == 0 and user_data is not None:
            item.setData(Qt.UserRole, user_data)
        if table.property("netconsole_center_cells"):
            item.setTextAlignment(Qt.AlignCenter)
        elif isinstance(value, int | float):
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        elif column in {1, 2, 6, table.columnCount() - 1}:
            item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row_index, column, item)


def _begin_table_update(table: QTableWidget) -> None:
    table.setProperty("mesh_sorting_enabled", table.isSortingEnabled())
    table.setProperty("mesh_signals_blocked", table.signalsBlocked())
    table.blockSignals(True)
    table.setSortingEnabled(False)


def _end_table_update(table: QTableWidget) -> None:
    table.setSortingEnabled(bool(table.property("mesh_sorting_enabled")))
    table.blockSignals(bool(table.property("mesh_signals_blocked")))


def _page(rows: list[dict[str, object]], current_page: int, page_size: int) -> tuple[int, list[dict[str, object]]]:
    total = len(rows)
    start = (max(current_page, 1) - 1) * page_size
    return total, rows[start : start + page_size]


def _json_dict(value) -> dict[str, object]:
    import json

    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_filename(value: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|]+', "_", value).strip(" ._")
    return safe or "MR"


def _parse_report_progress_message(message: str) -> tuple[str, int, int, str]:
    parts = str(message or "").split("|||", 3)
    stage = parts[0] if parts else ""
    try:
        file_index = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        file_index = 0
    try:
        file_total = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        file_total = 0
    file_name = parts[3] if len(parts) > 3 else ""
    return stage, file_index, file_total, file_name
