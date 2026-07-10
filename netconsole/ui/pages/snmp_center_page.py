from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.ui.dialogs.input_dialog_service import InputDialog
import re
import sqlite3
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Any, Callable
import json
from uuid import uuid4

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QApplication,
    QMenu,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import is_sqlite_locked_error
from netconsole.models.device import Device
from netconsole.models.snmp_models import DictionaryRecommendation, DeviceSnmpProfileResult, ProductReferenceRecommendation, SNMP_STATUS_LABELS, SnmpProfile, SnmpQueryRequest, SnmpQueryResult, SnmpSetRequest, SnmpSetResult
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.global_mib_repository import GlobalMibRepository
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.mib_dictionary_service import MibDictionaryService
from netconsole.services.mib_index_service import MibIndexService
from netconsole.services.mib_product_reference_compare_service import COMPARE_HEADERS, MibProductReferenceCompareService, ProductReferenceCompareResult
from netconsole.services.mib_resource_service import MibImportReport
from netconsole.services.mib_translation_service import translate_mib_description
from netconsole.services.snmp_poll_service import SnmpPollService
from netconsole.services.export.export_task_builders import mib_product_compare_spec, snmp_query_result_spec
from netconsole.services.snmp_client import SnmpClient
from netconsole.services.snmp_trap_service import SnmpTrapService
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.dialogs.snmp_set_dialog import SnmpSetDialog
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.snmp_workers import DeviceSnmpDetectWorker, MibBrowserTreeLoadWorker, MibImportWorker, MibRecompileWorker, ProductReferenceCompareWorker, ProductReferenceTreeRebuildWorker, SnmpInitWorker, SnmpQueryWorker, SnmpSetWorker, SnmpStartupWorker, TopologyDiscoveryWorker
from netconsole.ui.table_utils import auto_fit_table_columns


SNMP_SERVICE_STATE: dict[str, dict[str, object]] = {}
TEMPORARY_TARGET_KEY = "__temporary_snmp_target__"
TREE_MODE_GENERAL = "general"
TREE_MODE_H3C_PRODUCT = "h3c_product"


def snmp_action_button(text: str, icon_name: str | None = None) -> QPushButton:
    button = QPushButton(text)
    apply_button_icon(button, icon_name)
    return button


def _write_snmp_result_cache(paths: PathResolver, result: SnmpQueryResult, prefix: str) -> Path:
    cache_dir = paths.runtime_cache_dir / "snmp_query_results"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{prefix}_{uuid4().hex}.json"
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
RESULT_HEADERS = ["操作", "名称/OID", "值", "类型", "IP:端口", "状态", "耗时(ms)", "原始OID", "索引", "解码索引", "模块", "时间", "错误信息"]
RESULT_COLUMN_WIDTHS = {
    "操作": 80,
    "名称/OID": 180,
    "值": 260,
    "类型": 120,
    "IP:端口": 140,
    "状态": 90,
    "耗时(ms)": 90,
    "原始OID": 240,
    "索引": 80,
    "解码索引": 120,
    "模块": 180,
    "时间": 170,
    "错误信息": 260,
}


class SimpleTableModel(QAbstractTableModel):
    def __init__(self, headers: list[str] | None = None, rows: list[list[Any]] | None = None) -> None:
        super().__init__()
        self.headers = list(headers or [])
        self.rows = list(rows or [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self.rows) or index.column() >= len(self.headers):
            return None
        value = self.rows[index.row()][index.column()]
        if role in {Qt.DisplayRole, Qt.ToolTipRole}:
            return "" if value is None else str(value)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and section < len(self.headers):
            return self.headers[section]
        return None

    def set_rows(self, headers: list[str], rows: list[list[Any]]) -> None:
        self.beginResetModel()
        self.headers = list(headers)
        self.rows = list(rows)
        self.endResetModel()


@dataclass(frozen=True)
class SnmpTargetContext:
    profile: SnmpProfile
    device_id: str
    device_name: str
    source: str
    device: Device | None = None


class SnmpAdvancedParametersDialog(QDialog):
    def __init__(self, *, profile: SnmpProfile, target_name: str, temporary: bool = False, max_repetitions: int = 10, max_rows: int = 200, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("高级参数")
        self.host_input = QLineEdit(profile.host)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(int(profile.port or 161))
        self.version_combo = QComboBox()
        self.version_combo.addItems(["v2c", "v1", "v3"])
        self.version_combo.setCurrentText(str(profile.version or "v2c"))
        self.read_community_input = QLineEdit(profile.community_ro or "public")
        self.write_community_input = QLineEdit(profile.community_rw or "")
        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(100, 60000)
        self.timeout_input.setSuffix(" ms")
        self.timeout_input.setValue(int(profile.timeout_ms or 2000))
        self.retries_input = QSpinBox()
        self.retries_input.setRange(0, 10)
        self.retries_input.setValue(int(profile.retries or 1))
        self.max_rep_input = QSpinBox()
        self.max_rep_input.setRange(1, 50)
        self.max_rep_input.setValue(int(max_repetitions or 10))
        self.max_rows_input = QSpinBox()
        self.max_rows_input.setRange(1, 10000)
        self.max_rows_input.setValue(int(max_rows or 200))
        self.username_input = QLineEdit(profile.username or "")
        self.auth_protocol_input = QLineEdit(profile.auth_protocol or "SHA")
        self.auth_key_input = QLineEdit(profile.auth_key or "")
        self.priv_protocol_input = QLineEdit(profile.priv_protocol or "AES128")
        self.priv_key_input = QLineEdit(profile.priv_key or "")
        self.context_input = QLineEdit(profile.context_name or "")
        self.set_enabled_checkbox = QCheckBox("启用 SNMP Set 写操作")
        self.set_enabled_checkbox.setChecked(bool(getattr(getattr(parent, "center", None), "snmp_set_enabled", False)))
        self.status_label = QLabel(f"目标：{target_name}{'（临时，不写入设备管理）' if temporary else ''}")
        self.status_label.setWordWrap(True)
        form = QFormLayout()
        form.addRow("地址", self.host_input)
        form.addRow("端口", self.port_input)
        form.addRow("SNMP版本", self.version_combo)
        form.addRow("读团体字", self.read_community_input)
        form.addRow("写团体字", self.write_community_input)
        form.addRow("超时时间", self.timeout_input)
        form.addRow("重试次数", self.retries_input)
        form.addRow("MaxRepetitions 默认值", self.max_rep_input)
        form.addRow("最大返回默认值", self.max_rows_input)
        form.addRow("用户名", self.username_input)
        form.addRow("认证协议", self.auth_protocol_input)
        form.addRow("认证密码", self.auth_key_input)
        form.addRow("加密协议", self.priv_protocol_input)
        form.addRow("加密密码", self.priv_key_input)
        form.addRow("上下文名称", self.context_input)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addLayout(form)
        layout.addWidget(self.set_enabled_checkbox)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        test_button = button_box.addButton("测试连通性", QDialogButtonBox.ActionRole)
        copy_button = button_box.addButton("复制参数", QDialogButtonBox.ActionRole)
        test_button.clicked.connect(self.test_connectivity)
        copy_button.clicked.connect(self.copy_parameters)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def profile(self) -> SnmpProfile:
        return SnmpProfile(
            host=self.host_input.text().strip(),
            version=self.version_combo.currentText(),
            port=self.port_input.value(),
            community_ro=self.read_community_input.text().strip() or "public",
            community_rw=self.write_community_input.text().strip(),
            username=self.username_input.text().strip(),
            auth_protocol=self.auth_protocol_input.text().strip() or "SHA",
            auth_key=self.auth_key_input.text().strip(),
            priv_protocol=self.priv_protocol_input.text().strip() or "AES128",
            priv_key=self.priv_key_input.text().strip(),
            context_name=self.context_input.text().strip(),
            timeout_ms=self.timeout_input.value(),
            retries=self.retries_input.value(),
        )

    def test_connectivity(self) -> None:
        profile = self.profile()
        if not profile.host:
            self.status_label.setText("请先填写地址。")
            return
        result = SnmpClient().test_device(profile)
        if result.get("status") == "success":
            self.status_label.setText(f"测试成功：{profile.host}:{profile.port}，耗时 {result.get('latency_ms')} ms")
        else:
            self.status_label.setText(f"测试失败：{status_label(result.get('status'))}；{result.get('error_message') or ''}")

    def copy_parameters(self) -> None:
        profile = self.profile()
        QApplication.clipboard().setText(
            "\n".join(
                [
                    f"Address: {profile.host}",
                    f"Port: {profile.port}",
                    f"SNMP Version: {profile.version}",
                    f"Read Community: {profile.community_ro}",
                    f"Write Community: {'***' if profile.community_rw else ''}",
                    f"Timeout: {profile.timeout_ms} ms",
                    f"Retries: {profile.retries}",
                ]
            )
        )
        self.status_label.setText("参数已复制，写团体字已脱敏。")


class SnmpCenterPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver, feature_gate=None) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.feature_gate = feature_gate
        self.global_repo = GlobalMibRepository(paths.global_mib_db_path())
        self.site_repo = SiteSnmpRepository(paths.site_snmp_db_path(site_name))
        self.background_manager = BackgroundProcessManager(self, paths=paths)
        self.background_manager.finished.connect(self._background_refresh_finished)
        self.background_manager.failed.connect(self._background_refresh_failed)
        self._background_refresh_callbacks: dict[str, tuple[str, Callable[[dict[str, object]], None]]] = {}
        self._background_action_callbacks: dict[str, tuple[str, Callable[[dict[str, object]], None] | None]] = {}
        self.startup_worker: SnmpStartupWorker | None = None
        self._snmp_ready = False
        self._startup_running = False
        self.snmp_set_enabled = False
        self.tabs = QTabWidget()
        self.overview_page = SnmpOverviewPage(self)
        self.resource_page = MibResourcePage(self)
        self.dictionary_page = MibDictionaryPage(self)
        self.recommend_page = DeviceDictionaryRecommendPage(self)
        self.browser_page = MibBrowserPage(self)
        self.query_page = SnmpQueryPage(self)
        self.template_page = OidTemplatePage(self)
        self.monitor_page = SnmpMonitorPage(self)
        self.trap_page = SnmpTrapPage(self)
        self.topology_page = TopologyPage(self)
        for page, title in (
            (self.overview_page, "SNMP 总览"),
            (self.resource_page, "H3C MIB 资源库"),
            (self.dictionary_page, "MIB 字典集 / 当前设备视图"),
            (self.browser_page, "MIB 浏览器"),
            (self.template_page, "OID 模板库"),
            (self.monitor_page, "SNMP 监控任务"),
            (self.trap_page, "Trap / 告警"),
            (self.topology_page, "拓扑发现"),
        ):
            self.tabs.addTab(page, title)
        self._loaded_tabs: set[int] = set()
        self.tabs.currentChanged.connect(self._refresh_current_tab)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self._set_tabs_enabled(False)
        self.overview_page.show_startup_message("正在启动 SNMP 服务...", 0)
        QTimer.singleShot(0, self.start_snmp_service_async)

    def start_data_refresh(self, view: str, callback: Callable[[dict[str, object]], None], *, limit: int = 500, params: dict[str, object] | None = None) -> str | None:
        job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type="snmp_center_data_refresh",
                params={
                    "view": view,
                    "global_db_path": str(self.paths.global_mib_db_path()),
                    "site_snmp_db_path": str(self.paths.site_snmp_db_path(self.site_name)),
                    "site_db_path": str(self.repository.database.path),
                    "site_name": self.site_name,
                    "limit": limit,
                    **dict(params or {}),
                },
            )
        )
        self._background_refresh_callbacks[job_id] = (view, callback)
        return job_id

    def start_data_action(
        self,
        action: str,
        params: dict[str, object],
        callback: Callable[[dict[str, object]], None] | None = None,
    ) -> str:
        job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type="snmp_center_data_action",
                params={
                    "action": action,
                    "global_db_path": str(self.paths.global_mib_db_path()),
                    "site_snmp_db_path": str(self.paths.site_snmp_db_path(self.site_name)),
                    **dict(params),
                },
            )
        )
        if action == "set_snmp_set_enabled":
            requested = bool(params.get("enabled"))
            original_callback = callback

            def apply_setting(result: dict[str, object]) -> None:
                self.snmp_set_enabled = requested
                if original_callback is not None:
                    original_callback(result)

            callback = apply_setting
        self._background_action_callbacks[job_id] = (action, callback)
        return job_id

    def _background_refresh_finished(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        action_context = self._background_action_callbacks.pop(job_id, None)
        if action_context is not None:
            _action, callback = action_context
            if callback is not None:
                callback(dict(event.get("result") or {}))
            return
        context = self._background_refresh_callbacks.pop(job_id, None)
        if context is None:
            return
        _view, callback = context
        callback(dict(event.get("result") or {}))

    def _background_refresh_failed(self, event: dict) -> None:
        job_id = str(event.get("job_id") or "")
        action_context = self._background_action_callbacks.pop(job_id, None)
        if action_context is not None:
            action, _callback = action_context
            message = str(event.get("message") or event.get("error") or "后台操作失败")
            MessageBox.warning(self, "SNMP Center", f"{action} 执行失败：{message}")
            return
        context = self._background_refresh_callbacks.pop(job_id, None)
        if context is None:
            return
        view, _callback = context
        message = str(event.get("message") or event.get("error") or "后台刷新失败")
        if view == "devices" and hasattr(self.browser_page, "_refreshing_devices"):
            self.browser_page._refreshing_devices = False
        MessageBox.warning(self, "SNMP Center", f"{view} 刷新失败：{message}")

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.site_name = site_name
        self.site_repo = SiteSnmpRepository(self.paths.site_snmp_db_path(site_name))
        self._snmp_ready = False
        self._startup_running = False
        self._loaded_tabs.clear()
        self._set_tabs_enabled(False)
        self.overview_page.show_startup_message("正在启动 SNMP 服务...", 0)
        QTimer.singleShot(0, self.start_snmp_service_async)

    def refresh_all(self) -> None:
        if not self._snmp_ready:
            self.start_snmp_service_async()
            return
        self._refresh_current_tab(self.tabs.currentIndex())

    def _refresh_current_tab(self, index: int) -> None:
        if not self._snmp_ready:
            return
        if index in self._loaded_tabs:
            return
        page = self.tabs.widget(index)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()
        self._loaded_tabs.add(index)

    def _set_tabs_enabled(self, enabled: bool) -> None:
        for index in range(self.tabs.count()):
            self.tabs.setTabEnabled(index, enabled or index == 0)

    def start_snmp_service_async(self) -> None:
        if self._snmp_ready or self._startup_running:
            return
        cached = SNMP_SERVICE_STATE.get(self.site_name)
        if cached and cached.get("status") == "ready":
            self._startup_finished(dict(cached.get("summary") or {}))
            return
        self._startup_running = True
        self._set_tabs_enabled(False)
        self.overview_page.show_startup_message("正在启动 SNMP 服务...", 0)
        self.startup_worker = SnmpStartupWorker(self.paths, self.site_name, self)
        self.startup_worker.progress_changed.connect(self.overview_page.show_startup_message)
        self.startup_worker.log_emitted.connect(self.overview_page.append_startup_log)
        self.startup_worker.finished_with_result.connect(self._startup_finished)
        self.startup_worker.finished.connect(self.startup_worker.deleteLater)
        self.startup_worker.start()

    def _startup_finished(self, result: object) -> None:
        self._startup_running = False
        self.startup_worker = None
        if isinstance(result, Exception):
            self._snmp_ready = False
            self._set_tabs_enabled(False)
            self.overview_page.show_startup_failed(str(result))
            app_logger.log_error("SNMP_STARTUP_FAILED", str(result))
            return
        summary = dict(result) if isinstance(result, dict) else {}
        self.snmp_set_enabled = bool(summary.get("snmp_set_enabled"))
        self._snmp_ready = True
        SNMP_SERVICE_STATE[self.site_name] = {"status": "ready", "summary": summary}
        self._set_tabs_enabled(True)
        self.overview_page.apply_startup_summary(summary)
        self._refresh_current_tab(self.tabs.currentIndex())

    def switch_to_query_from_mib(self, oid: str, method: str, object_name: str = "", module_name: str = "", run_now: bool = False) -> None:
        index = self.tabs.indexOf(self.browser_page)
        if index >= 0:
            self.tabs.setCurrentIndex(index)
        self.browser_page.set_query_from_mib(oid, method, object_name, module_name)
        if run_now:
            self.browser_page.run_browser_query()


class SnmpOverviewPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: SnmpInitWorker | None = None
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.status_label = QLabel("初始化状态：未运行")
        self.step_label = QLabel("当前步骤：")
        self.elapsed_label = QLabel("耗时：")
        self.error_label = QLabel("错误：")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.init_button = snmp_action_button("初始化 / 检查 SNMP 资源", "SYNC")
        self.rebuild_button = snmp_action_button("重建内置 H3C MIB 库", "SYNC")
        self.reset_button = snmp_action_button("清空并重建 SNMP 资源库", "DELETE")
        self.init_button.clicked.connect(lambda: self.start_worker("initialize"))
        self.rebuild_button.clicked.connect(lambda: self.start_worker("rebuild_h3c"))
        self.reset_button.clicked.connect(self.confirm_reset)
        buttons = QHBoxLayout()
        buttons.addWidget(self.init_button)
        buttons.addWidget(self.rebuild_button)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.status_label)
        layout.addWidget(self.step_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("日志："))
        layout.addWidget(self.log_text, 1)

    def refresh(self) -> None:
        if not self.center._snmp_ready:
            self.show_startup_message("SNMP 服务启动中，请稍候...", self.progress_bar.value())
            return
        self.status_label.setText("SNMP 服务状态：正在后台刷新")
        self.center.start_data_refresh("overview", lambda result: self.apply_startup_summary(dict(result.get("summary") or {})))

    def show_startup_message(self, message: str, percent: int) -> None:
        self.status_label.setText("SNMP 服务状态：启动中")
        self.step_label.setText(f"当前步骤：{message}")
        self.progress_bar.setValue(max(0, min(100, int(percent))))

    def append_startup_log(self, message: str) -> None:
        self.log_text.append(message)

    def show_startup_failed(self, error_message: str) -> None:
        self.status_label.setText("SNMP 服务状态：启动失败")
        self.error_label.setText(f"错误：{error_message}")
        self.progress_bar.setValue(0)
        self.append_startup_log(f"SNMP 服务启动失败：{error_message}")
        for button in (self.init_button, self.rebuild_button, self.reset_button):
            button.setEnabled(True)

    def apply_startup_summary(self, summary: dict[str, object]) -> None:
        modules = int(summary.get("module_count") or 0)
        objects = int(summary.get("object_count") or 0)
        dictionaries = int(summary.get("dictionary_count") or 0)
        references = int(summary.get("product_reference_count") or 0)
        history = int(summary.get("query_history_count") or 0)
        set_history = int(summary.get("set_history_count") or 0)
        devices = int(summary.get("device_count") or 0)
        set_enabled = bool(summary.get("snmp_set_enabled"))
        v5_loaded = bool(summary.get("h3c_v5_registered"))
        v7v9_loaded = bool(summary.get("h3c_v7v9_registered"))
        elapsed_ms = int(summary.get("elapsed_ms") or 0)
        self.status_label.setText("SNMP 服务状态：已就绪")
        self.step_label.setText("当前步骤：SNMP 服务启动完成")
        self.progress_bar.setValue(100)
        self.elapsed_label.setText(f"耗时：{elapsed_ms} ms" if elapsed_ms else "耗时：-")
        self.error_label.setText("错误：")
        self.summary.setText(
            "\n".join(
                [
                    "SNMP 中心面向 H3C Comware 设备，MIB 与产品参考表为全局资源，局点仅保存绑定、验证、查询历史、Trap 和拓扑数据。",
                    "内置通用 MIB：已加载",
                    f"H3C V5 MIB：{'已加载' if v5_loaded else '未加载'}",
                    f"H3C V7/V9 MIB：{'已加载' if v7v9_loaded else '未加载'}",
                    f"产品 MIB 参考表：{references}",
                    f"全局 MIB 模块：{modules}",
                    f"全局 MIB 对象：{objects}",
                    f"字典集：{dictionaries}",
                    f"当前局点 SNMP 设备：{devices}",
                    f"当前局点查询历史：{history}",
                    f"SNMP Set 写操作：{'已启用' if set_enabled else '默认关闭'}",
                    f"当前局点 Set 历史：{set_history}",
                    "提示：MIB 已导入不代表设备一定支持该 OID，必须通过实机 Get / Walk 验证。",
                ]
            )
        )
        for button in (self.init_button, self.rebuild_button, self.reset_button):
            button.setEnabled(True)

    def start_worker(self, action: str, clear_raw_files: bool = False) -> None:
        if self.worker is not None:
            return
        self.log_text.clear()
        self.status_label.setText("初始化状态：运行中")
        self.error_label.setText("错误：")
        for button in (self.init_button, self.rebuild_button, self.reset_button):
            button.setEnabled(False)
        self.worker = SnmpInitWorker(self.center.paths, action=action, clear_raw_files=clear_raw_files, parent=self)
        self.worker.progress.connect(self._append_log)
        self.worker.finished_with_result.connect(self._worker_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def confirm_reset(self) -> None:
        box = MessageBox(self)
        box.setIcon(MessageBox.Warning)
        box.setWindowTitle("清空并重建 SNMP 资源库")
        box.setText("该操作会清空 data/global/mibs/global_mib.db、用户导入的 MIB 索引、编译结果、字典集和产品 MIB 参考表索引。不会删除局点设备、配置备份、任务中心或 MR 数据。")
        box.setInformativeText("确认后将自动重建内置通用 MIB 字典和 H3C V5 / V7/V9 字典。")
        clear_raw = QCheckBox("同时清空用户导入的 raw_files / raw_archives / references")
        box.setCheckBox(clear_raw)
        box.setStandardButtons(MessageBox.Cancel | MessageBox.Yes)
        box.button(MessageBox.Yes).setText("确认清空并重建")
        box.button(MessageBox.Cancel).setText("取消")
        if box.exec() == MessageBox.Yes:
            self.start_worker("reset", clear_raw_files=clear_raw.isChecked())

    def _append_log(self, text: str) -> None:
        self.step_label.setText(f"当前步骤：{text}")
        self.log_text.append(text)

    def _worker_finished(self, result: object) -> None:
        self.worker = None
        for button in (self.init_button, self.rebuild_button, self.reset_button):
            button.setEnabled(True)
        if isinstance(result, Exception):
            self.status_label.setText("初始化状态：失败")
            self.error_label.setText(f"错误：{result}")
        else:
            self.status_label.setText("初始化状态：完成")
            self.error_label.setText("错误：")
        self.refresh()


class MibResourcePage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: MibImportWorker | None = None
        self.recompile_worker: MibRecompileWorker | None = None
        self.refresh_job_id: str | None = None
        self.background_manager = BackgroundProcessManager(self, paths=center.paths)
        self.background_manager.progress.connect(self._refresh_progress)
        self.background_manager.finished.connect(self._refresh_finished)
        self.background_manager.failed.connect(self._refresh_failed)
        self.background_manager.cancelled.connect(self._refresh_failed)
        self.vendor_input = QLineEdit()
        self.source_input = QLineEdit("用户手动导入")
        self.url_input = QLineEdit()
        self.status = QLabel()
        self.file_table = make_table(["类型", "文件", "模块/参考", "状态", "Hash", "错误"])
        self.module_table = make_table(["模块 / 来源", "状态", "对象数", "表", "Trap", "错误"])
        self.missing_summary = QTextEdit()
        self.missing_summary.setReadOnly(True)
        self.only_missing = QCheckBox("只显示缺依赖模块")
        import_file = snmp_action_button("导入 MIB / 产品参考表", "DOWNLOAD")
        import_dir = snmp_action_button("目录批量导入", "FOLDER")
        recompile_missing = snmp_action_button("重新编译缺依赖模块", "SYNC")
        reindex = snmp_action_button("刷新列表", "SYNC")
        import_file.clicked.connect(self.import_file)
        import_dir.clicked.connect(self.import_dir)
        recompile_missing.clicked.connect(self.recompile_missing)
        reindex.clicked.connect(self.refresh)
        self.only_missing.stateChanged.connect(lambda _state: self.refresh())
        form = QFormLayout()
        form.addRow("厂商", self.vendor_input)
        form.addRow("来源名称", self.source_input)
        form.addRow("官网下载 URL", self.url_input)
        buttons = QHBoxLayout()
        buttons.addWidget(import_file)
        buttons.addWidget(import_dir)
        buttons.addWidget(recompile_missing)
        buttons.addWidget(self.only_missing)
        buttons.addWidget(reindex)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        splitter = QSplitter(Qt.Vertical)
        files_box = titled_box("导入历史", self.file_table)
        missing_box = titled_box("缺失依赖汇总", self.missing_summary)
        modules_box = titled_box("MIB 模块", self.module_table)
        splitter.addWidget(files_box)
        splitter.addWidget(missing_box)
        splitter.addWidget(modules_box)
        splitter.setSizes([260, 160, 420])
        layout.addWidget(splitter, 1)

    def import_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "导入 MIB / 产品参考表", "", "MIB / Reference / Archive (*.mib *.txt *.my *.xlsx *.zip *.tar *.tgz *.gz);;All Files (*)")
        if paths:
            self._start_import(paths)

    def import_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 MIB 目录")
        if path:
            self._start_import([path])

    def _start_import(self, paths: list[str]) -> None:
        if self.worker is not None:
            MessageBox.information(self, "MIB 资源库", "当前已有导入任务正在执行。")
            return
        metadata = {
            "vendor": self.vendor_input.text().strip(),
            "source_name": self.source_input.text().strip() or "用户手动导入",
            "source_url": self.url_input.text().strip(),
        }
        self.worker = MibImportWorker(self.center.paths, paths, metadata, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished_with_result.connect(self._import_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _import_finished(self, result: object) -> None:
        self.worker = None
        if isinstance(result, Exception):
            self.status.setText(f"导入失败：{result}")
            MessageBox.warning(self, "MIB 资源库", str(result))
            return
        report = result if isinstance(result, MibImportReport) else None
        if report is not None:
            self.status.setText(f"导入完成：总数 {report.total}，新增 {report.imported}，重复 {report.duplicated}，失败 {report.failed}。报告：{report.report_path}")
        self.refresh()

    def recompile_missing(self) -> None:
        if self.recompile_worker is not None:
            MessageBox.information(self, "MIB 资源库", "当前已有重新编译任务正在执行。")
            return
        self.recompile_worker = MibRecompileWorker(self.center.paths, self)
        self.recompile_worker.progress.connect(self.status.setText)
        self.recompile_worker.finished_with_result.connect(self._recompile_finished)
        self.recompile_worker.finished.connect(self.recompile_worker.deleteLater)
        self.recompile_worker.start()

    def _recompile_finished(self, result: object) -> None:
        self.recompile_worker = None
        if isinstance(result, Exception):
            self.status.setText(f"重新编译失败：{result}")
            MessageBox.warning(self, "MIB 资源库", str(result))
            return
        report = result if isinstance(result, MibImportReport) else None
        if report is not None:
            self.status.setText(f"重新编译完成：总数 {report.total}，成功/仍缺依赖 {report.imported}，失败 {report.failed}。报告：{report.report_path}")
        self.refresh()

    def refresh(self) -> None:
        if self.refresh_job_id is not None:
            self.status.setText("MIB 资源库正在后台刷新...")
            return
        params = {
            "db_path": str(self.center.paths.global_mib_db_path()),
            "only_missing": self.only_missing.isChecked(),
            "app_root": str(self.center.paths.app_root),
            "data_root": str(self.center.paths.data_root),
        }
        self.status.setText("MIB 资源库正在后台刷新...")
        self.refresh_job_id = self.background_manager.start_job(
            BackgroundJob(task_type="snmp_mib_resource_refresh", params=params)
        )

    def _refresh_progress(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.refresh_job_id or ""):
            return
        message = str(event.get("message") or "")
        if message:
            self.status.setText(message)

    def _refresh_finished(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.refresh_job_id or ""):
            return
        self.refresh_job_id = None
        result = dict(event.get("result") or {})
        fill_table(self.file_table, [list(row) for row in result.get("file_rows") or [] if isinstance(row, list)])
        fill_table(self.module_table, [list(row) for row in result.get("module_rows") or [] if isinstance(row, list)])
        self.missing_summary.setPlainText(str(result.get("missing_summary") or "当前没有缺失依赖。"))
        self.file_table.setColumnWidth(3, 190)
        self.module_table.setColumnWidth(1, 190)
        self.status.setText("MIB 资源库刷新完成。")

    def _refresh_failed(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.refresh_job_id or ""):
            return
        self.refresh_job_id = None
        message = str(event.get("message") or event.get("error") or "MIB 资源库刷新失败")
        self.status.setText(message)
        MessageBox.warning(self, "MIB 资源库", message)


class ProductReferenceComparePage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: ProductReferenceCompareWorker | None = None
        self.last_compare: ProductReferenceCompareResult | None = None
        self.references: list[dict[str, object]] = []
        self.refresh_job_id: str | None = None
        self.background_manager = BackgroundProcessManager(self, paths=center.paths)
        self.background_manager.progress.connect(self._refresh_progress)
        self.background_manager.finished.connect(self._refresh_finished)
        self.background_manager.failed.connect(self._refresh_failed)
        self.background_manager.cancelled.connect(self._refresh_failed)
        self.page_offset = 0
        self.left_combo = QComboBox()
        self.right_combo = QComboBox()
        self.diff_filter = QComboBox()
        self.diff_filter.addItem("全部差异", "")
        self.diff_filter.addItem("右侧新增", "added")
        self.diff_filter.addItem("右侧缺失", "removed")
        self.diff_filter.addItem("字段变化", "changed")
        self.diff_filter.addItem("分册编号变化", "category_changed")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索模块、OID、对象名或说明")
        self.page_size = QSpinBox()
        self.page_size.setRange(50, 2000)
        self.page_size.setValue(500)
        self.summary_label = QLabel("请选择两个产品 MIB 参考表后开始对比。")
        self.summary_label.setWordWrap(True)
        self.status_label = QLabel()
        self.page_label = QLabel("第 1 页")
        self.result_model = SimpleTableModel(COMPARE_HEADERS, [])
        self.result_table = QTableView()
        self.result_table.setModel(self.result_model)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.result_table.horizontalHeader().setStretchLastSection(False)
        self.result_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.compare_button = snmp_action_button("开始对比", "PLAY")
        self.export_button = snmp_action_button("导出结果", "SHARE")
        self.prev_button = snmp_action_button("上一页", "LEFT_ARROW")
        self.next_button = snmp_action_button("下一页", "RIGHT_ARROW")
        self.refresh_button = snmp_action_button("刷新参考表", "SYNC")
        self.export_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.compare_button.clicked.connect(self.start_compare)
        self.export_button.clicked.connect(self.export_results)
        self.prev_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.refresh_button.clicked.connect(self.refresh)
        self.search_input.returnPressed.connect(self.reload_page)
        self.diff_filter.currentIndexChanged.connect(lambda _index: self.reload_page(reset=True))
        self.page_size.valueChanged.connect(lambda _value: self.reload_page(reset=True))

        selector = QHBoxLayout()
        selector.addWidget(QLabel("左侧参考表"))
        selector.addWidget(self.left_combo, 2)
        selector.addWidget(QLabel("右侧参考表"))
        selector.addWidget(self.right_combo, 2)
        selector.addWidget(self.compare_button)
        selector.addWidget(self.export_button)
        selector.addWidget(self.refresh_button)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("差异类型"))
        filters.addWidget(self.diff_filter)
        filters.addWidget(self.search_input, 2)
        filters.addWidget(QLabel("每页"))
        filters.addWidget(self.page_size)
        filters.addWidget(self.prev_button)
        filters.addWidget(self.page_label)
        filters.addWidget(self.next_button)
        filters.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(selector)
        layout.addLayout(filters)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.result_table, 1)

    def refresh(self) -> None:
        if self.refresh_job_id is not None:
            self.status_label.setText("正在后台刷新产品 MIB 参考表...")
            return
        self.status_label.setText("正在后台刷新产品 MIB 参考表...")
        self.refresh_job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type="snmp_product_references_refresh",
                params={
                    "db_path": str(self.center.paths.global_mib_db_path()),
                    "app_root": str(self.center.paths.app_root),
                    "data_root": str(self.center.paths.data_root),
                },
            )
        )

    def _refresh_progress(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.refresh_job_id or ""):
            return
        message = str(event.get("message") or "")
        if message:
            self.status_label.setText(message)

    def _refresh_finished(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.refresh_job_id or ""):
            return
        self.refresh_job_id = None
        result = dict(event.get("result") or {})
        references = [dict(row) for row in result.get("references") or [] if isinstance(row, dict)]
        self.references = references
        current_left = self.left_combo.currentData()
        current_right = self.right_combo.currentData()
        for combo, current in ((self.left_combo, current_left), (self.right_combo, current_right)):
            combo.blockSignals(True)
            combo.clear()
            for reference in references:
                label = self._reference_label(reference)
                combo.addItem(label, int(reference["id"]))
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if self.right_combo.count() > 1 and self.right_combo.currentIndex() == self.left_combo.currentIndex():
            self.right_combo.setCurrentIndex(1)
        self.status_label.setText(f"已加载 {len(references)} 份产品 MIB 参考表。")

    def _refresh_failed(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.refresh_job_id or ""):
            return
        self.refresh_job_id = None
        message = str(event.get("message") or event.get("error") or "产品 MIB 参考表刷新失败")
        self.status_label.setText(message)
        MessageBox.warning(self, "产品参考对比", message)

    def start_compare(self) -> None:
        left_id = self.left_combo.currentData()
        right_id = self.right_combo.currentData()
        if left_id is None or right_id is None:
            MessageBox.information(self, "产品参考对比", "请先导入并选择两个产品 MIB 参考表。")
            return
        if int(left_id) == int(right_id):
            MessageBox.information(self, "产品参考对比", "左右两侧不能选择同一份产品 MIB 参考表。")
            return
        if self.worker is not None:
            MessageBox.information(self, "产品参考对比", "当前已有对比任务正在执行。")
            return
        self.compare_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status_label.setText("正在后台对比产品 MIB 参考表...")
        self.worker = ProductReferenceCompareWorker(self.center.paths.global_mib_db_path(), int(left_id), int(right_id), self)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished_with_result.connect(self._compare_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _compare_finished(self, result: object) -> None:
        self.worker = None
        self.compare_button.setEnabled(True)
        if isinstance(result, Exception):
            self.status_label.setText(f"对比失败：{result}")
            MessageBox.warning(self, "产品参考对比", str(result))
            return
        self.last_compare = result if isinstance(result, ProductReferenceCompareResult) else None
        if self.last_compare is None:
            self.status_label.setText("对比失败：返回结果无效。")
            return
        self.export_button.setEnabled(True)
        self.page_offset = 0
        self.summary_label.setText(self._summary_text(self.last_compare))
        self.status_label.setText("对比完成。")
        self.reload_page(reset=True)

    def reload_page(self, reset: bool = False) -> None:
        if self.last_compare is None:
            return
        if reset:
            self.page_offset = 0
        service = MibProductReferenceCompareService(self.center.global_repo)
        rows = service.list_results(
            self.last_compare.left_reference_id,
            self.last_compare.right_reference_id,
            diff_type=str(self.diff_filter.currentData() or ""),
            keyword=self.search_input.text().strip(),
            limit=self.page_size.value(),
            offset=self.page_offset,
        )
        self.result_model.set_rows(COMPARE_HEADERS, [_compare_table_row(row) for row in rows])
        auto_resize_table_view_columns(self.result_table)
        page = self.page_offset // max(1, self.page_size.value()) + 1
        self.page_label.setText(f"第 {page} 页")
        self.prev_button.setEnabled(self.page_offset > 0)
        self.next_button.setEnabled(len(rows) >= self.page_size.value())

    def previous_page(self) -> None:
        self.page_offset = max(0, self.page_offset - self.page_size.value())
        self.reload_page()

    def next_page(self) -> None:
        self.page_offset += self.page_size.value()
        self.reload_page()

    def export_results(self) -> None:
        if self.last_compare is None:
            return
        target, _ = QFileDialog.getSaveFileName(self, "导出产品参考对比结果", "", "Excel (*.xlsx);;CSV (*.csv)")
        if not target:
            return
        submit_export_task(
            self,
            mib_product_compare_spec(
                target,
                db_path=self.center.paths.global_mib_db_path(),
                left_reference_id=self.last_compare.left_reference_id,
                right_reference_id=self.last_compare.right_reference_id,
                title="导出产品参考对比结果",
                open_dir_on_success=True,
            ),
            success_title="导出产品参考对比结果",
            paths=self.center.paths,
        )
        self.status_label.setText("产品参考对比结果导出任务已提交。")

    @staticmethod
    def _reference_label(reference: dict[str, object]) -> str:
        parts = [
            str(reference.get("reference_name") or ""),
            str(reference.get("release_series") or ""),
            str(reference.get("doc_version") or ""),
        ]
        return " / ".join(part for part in parts if part)

    @staticmethod
    def _summary_text(result: ProductReferenceCompareResult) -> str:
        summary = result.summary
        return (
            f"左侧：{result.left_reference_name}；右侧：{result.right_reference_name}\n"
            f"对象：左侧 {summary.get('left_objects', 0)}，右侧 {summary.get('right_objects', 0)}，"
            f"新增 {summary.get('objects_added', 0)}，缺失 {summary.get('objects_removed', 0)}，变化 {summary.get('objects_changed', 0)}。\n"
            f"Trap：左侧 {summary.get('left_traps', 0)}，右侧 {summary.get('right_traps', 0)}，"
            f"新增 {summary.get('traps_added', 0)}，缺失 {summary.get('traps_removed', 0)}，变化 {summary.get('traps_changed', 0)}。\n"
            f"模块/分册变化：{summary.get('modules_changed', 0)}；差异明细：{summary.get('diff_rows', 0)}。"
        )


class MibDictionaryPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.table = make_table(["ID", "名称", "厂商", "设备类型", "内置", "默认启用", "说明"])
        create_button = snmp_action_button("新建字典集", "ADD")
        refresh_button = snmp_action_button("刷新", "SYNC")
        create_button.clicked.connect(self.create_dictionary)
        refresh_button.clicked.connect(self.refresh)
        buttons = QHBoxLayout()
        buttons.addWidget(create_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table, 1)

    def create_dictionary(self) -> None:
        name, ok = InputDialog.getText(self, "新建字典集", "字典集名称")
        if not ok or not name.strip():
            return
        self.center.start_data_action("create_dictionary", {"name": name.strip()}, lambda _result: self.refresh())

    def refresh(self) -> None:
        self.center.start_data_refresh("dictionary_sets", self._apply_rows)

    def _apply_rows(self, result: dict[str, object]) -> None:
        fill_table(
            self.table,
            [
                [row.get("id"), row.get("name"), row.get("vendor"), row.get("device_type"), yes_no(row.get("is_builtin")), yes_no(row.get("enabled_by_default")), row.get("description")]
                for row in result.get("rows") or []
                if isinstance(row, dict)
            ],
        )


class DeviceDictionaryRecommendPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: DeviceSnmpDetectWorker | None = None
        self.devices: list[Device] = []
        self.last_profile: DeviceSnmpProfileResult | None = None
        self.last_recommendations = []
        self.last_reference_recommendations = []
        self.device_combo = QComboBox()
        self.profile_text = QTextEdit()
        self.profile_text.setReadOnly(True)
        self.table = make_table(["字典集ID", "字典集", "匹配度", "依据", "状态"])
        self.reference_table = make_table(["参考表ID", "产品 MIB 参考", "匹配度", "依据", "状态"])
        detect_button = snmp_action_button("识别设备并推荐", "SEARCH")
        apply_button = snmp_action_button("一键启用推荐字典", "ACCEPT")
        refresh_button = snmp_action_button("刷新设备", "SYNC")
        detect_button.clicked.connect(self.detect)
        apply_button.clicked.connect(self.apply_recommendations)
        refresh_button.clicked.connect(self.refresh)
        top = QHBoxLayout()
        top.addWidget(QLabel("设备"))
        top.addWidget(self.device_combo, 1)
        top.addWidget(refresh_button)
        top.addWidget(detect_button)
        top.addWidget(apply_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.profile_text)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(titled_box("推荐字典集", self.table))
        splitter.addWidget(titled_box("推荐产品 MIB 参考", self.reference_table))
        splitter.setSizes([320, 180])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        self.center.start_data_refresh("devices", self._apply_devices)

    def _apply_devices(self, result: dict[str, object]) -> None:
        current = self.device_combo.currentData()
        self.devices = [Device.from_mapping(dict(row)) for row in result.get("devices") or [] if isinstance(row, dict)]
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self.devices:
            self.device_combo.addItem(f"{device.name} / {device.primary_address}", device.id)
        index = self.device_combo.findData(current)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)

    def _current_device(self) -> Device | None:
        device_id = self.device_combo.currentData()
        return next((device for device in self.devices if device.id == device_id), None)

    def detect(self) -> None:
        device = self._current_device()
        if device is None:
            return
        self.worker = DeviceSnmpDetectWorker(device, self)
        self.worker.progress.connect(self.profile_text.setPlainText)
        self.worker.finished_with_result.connect(lambda result, device=device: self._detect_finished(device, result))
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _detect_finished(self, device: Device, result: object) -> None:
        self.worker = None
        if isinstance(result, Exception):
            self.profile_text.setPlainText(f"识别失败：{result}")
            return
        profile = result if isinstance(result, DeviceSnmpProfileResult) else DeviceSnmpProfileResult(status="failed", error_message=str(result))
        self.last_profile = profile
        self.center.start_data_action(
            "save_profile_recommendations",
            {
                "device_id": str(device.device_uuid or device.id),
                "device": device.to_record(),
                "profile": asdict(profile),
            },
            lambda payload, profile=profile: self._recommendations_finished(profile, payload),
        )

    def _recommendations_finished(self, profile: DeviceSnmpProfileResult, payload: dict[str, object]) -> None:
        recommendations = [DictionaryRecommendation(**dict(row)) for row in payload.get("recommendations") or [] if isinstance(row, dict)]
        reference_recommendations = [ProductReferenceRecommendation(**dict(row)) for row in payload.get("reference_recommendations") or [] if isinstance(row, dict)]
        self.last_recommendations = recommendations
        self.last_reference_recommendations = reference_recommendations
        reference_lines = [f"{item.reference_name}（{item.score}%）：{'；'.join(item.reasons)}" for item in reference_recommendations[:3]]
        if not reference_lines and (profile.release_series or profile.release):
            reference_lines = [
                f"检测到设备属于 H3C 无线控制器 {profile.release_series or profile.release} 系列，但当前未导入对应产品 MIB 参考表。",
                f"建议导入：H3C 无线控制器产品 MIB参考-{profile.release_series or '对应 Release'}-6W100.xlsx",
            ]
        self.profile_text.setPlainText(
            "\n".join(
                [
                    "检测到设备：",
                    f"设备名称：{profile.device_name}",
                    f"厂商：{profile.vendor}",
                    f"设备类型：{profile.device_type}",
                    f"型号：{profile.model}",
                    f"系统：{profile.system or profile.os_family} {profile.system_version}",
                    f"Comware 大版本：{profile.os_major}",
                    f"Version：{profile.system_version}",
                    f"Release：{profile.release}",
                    f"Release 系列：{profile.release_series}",
                    f"sysObjectID：{profile.sys_object_id}",
                    f"sysDescr：{profile.sys_descr}",
                    f"sysUpTime：{profile.sys_up_time}",
                    f"接口数量：{profile.interface_count}",
                    f"状态：{profile.status} {profile.error_message}",
                    "",
                    "推荐产品 MIB 参考：",
                    *(reference_lines or ["暂无匹配产品参考表，可手动导入或选择参考表。"]),
                ]
            )
        )
        fill_table(self.table, [[item.dictionary_set_id, item.name, f"{item.score}%", "；".join(item.reasons), item.status] for item in recommendations])
        fill_table(self.reference_table, [[item.reference_id, item.reference_name, f"{item.score}%", "；".join(item.reasons), item.status] for item in reference_recommendations])

    def apply_recommendations(self) -> None:
        device = self._current_device()
        if device is None or not self.last_recommendations:
            return
        self.center.start_data_action(
            "apply_recommendations",
            {
                "device_id": str(device.device_uuid or device.id),
                "recommendations": [asdict(item) for item in self.last_recommendations],
            },
            lambda _result: MessageBox.information(self, "设备字典推荐", "已启用推荐字典。"),
        )


class MibBrowserPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: SnmpQueryWorker | None = None
        self.set_worker: SnmpSetWorker | None = None
        self.tree_worker: MibBrowserTreeLoadWorker | None = None
        self.child_tree_workers: dict[int, tuple[MibBrowserTreeLoadWorker, QTreeWidgetItem]] = {}
        self.product_tree_rebuild_worker: ProductReferenceTreeRebuildWorker | None = None
        self.last_result: SnmpQueryResult | None = None
        self.devices: list[Device] = []
        self.product_references: list[dict[str, object]] = []
        self.product_reference_tree_nodes: list[dict[str, object]] = []
        self.product_references_loaded = False
        self.product_reference_job_id: str | None = None
        self.enabled_dictionary_ids_by_device: dict[str, list[int]] = {}
        self.background_manager = BackgroundProcessManager(self, paths=center.paths)
        self.background_manager.progress.connect(self._product_reference_progress)
        self.background_manager.finished.connect(self._product_reference_finished)
        self.background_manager.failed.connect(self._product_reference_failed)
        self.background_manager.cancelled.connect(self._product_reference_failed)
        self.profile_overrides: dict[str, SnmpProfile] = {}
        self.temporary_profile: SnmpProfile | None = None
        self.temporary_name = ""
        self._refreshing_devices = False
        self._refreshing_device_groups = False
        self._device_refresh_retry_count = 0
        self._device_group_refresh_retry_count = 0
        self._tree_task_id = 0
        self._query_task_id = 0
        self._product_tree_rebuild_task_id = 0
        self._set_task_id = 0
        self.device_search_timer = QTimer(self)
        self.device_search_timer.setSingleShot(True)
        self.device_search_timer.setInterval(300)
        self.device_search_timer.timeout.connect(self.refresh_devices)
        self.device_group_filter = QComboBox()
        self.device_search_input = QLineEdit()
        self.device_search_input.setPlaceholderText("设备名称 / 系统名称 / IP / 备注 / 厂商 / 类型")
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(240)
        self.oid_input = QLineEdit()
        self.operation_combo = QComboBox()
        self.operation_combo.addItems(["Get", "Get Next", "Get Bulk", "Get Subtree", "Walk", "Bulk Walk", "Table Walk", "Set"])
        self.max_repetitions = QSpinBox()
        self.max_repetitions.setRange(1, 50)
        self.max_repetitions.setValue(10)
        self.max_rows = QSpinBox()
        self.max_rows.setRange(1, 10000)
        self.max_rows.setValue(200)
        self.search_input = QLineEdit()
        self.tree_mode_combo = QComboBox()
        self.tree_mode_combo.addItem("通用", TREE_MODE_GENERAL)
        self.tree_mode_combo.addItem("H3C 产品目录", TREE_MODE_H3C_PRODUCT)
        self.tree_mode_combo.setCurrentIndex(self.tree_mode_combo.findData(TREE_MODE_H3C_PRODUCT))
        self.rebuild_product_tree_button = snmp_action_button("重建产品目录树", "SYNC")
        self.rebuild_product_tree_button.setVisible(False)
        self.module_filter = QComboBox()
        self.module_filter.setVisible(False)
        self.source_filter = QComboBox()
        self.source_filter.addItem("标准 MIB 库", "standard")
        self.source_filter.addItem("H3C V5 MIB 库", "h3c_v5")
        self.source_filter.addItem("H3C V7/V9 MIB 库", "h3c_v7v9")
        self.source_filter.setCurrentIndex(self.source_filter.findData("h3c_v7v9"))
        self.only_device_dict = QCheckBox("仅显示当前设备启用字典")
        self.only_device_dict.setVisible(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "OID", "类型"])
        configure_tree_widget(self.tree, {0: 220, 1: 220, 2: 120})
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.property_table = make_table(["属性", "值"])
        self.operation_label = QLabel("当前对象：未选择")
        self.operation_label.setWordWrap(True)
        self.path_label = QLabel("路径：")
        self.path_label.setWordWrap(True)
        self.view_hint = QLabel()
        self.view_hint.setWordWrap(True)
        self.generate_view_button = snmp_action_button("生成推荐 MIB 视图", "SETTING")
        self.use_h3c_v7v9_button = snmp_action_button("使用 H3C V7/V9 无线 AC 默认视图", "ACCEPT")
        self.use_global_h3c_button = snmp_action_button("使用全局 H3C MIB 浏览", "GLOBE")
        self.generate_view_button.clicked.connect(self.generate_recommended_view)
        self.use_h3c_v7v9_button.clicked.connect(self.use_h3c_v7v9_view)
        self.use_global_h3c_button.clicked.connect(self.use_global_h3c_view)
        copy_oid_button = snmp_action_button("复制 OID", "COPY")
        copy_query_oid_button = snmp_action_button("复制实际查询 OID", "COPY")
        fill_query_button = snmp_action_button("填入顶部查询栏", "EDIT")
        run_query_button = snmp_action_button("立即查询", "PLAY")
        back_to_column_button = snmp_action_button("回到列 OID", "RETURN")
        run_query_button.setVisible(False)
        self.run_query_button = run_query_button
        set_current_button = snmp_action_button("Set 当前 OID", "EDIT")
        translate_button = snmp_action_button("翻译描述", "LANGUAGE")
        self.set_current_button = set_current_button
        self.back_to_column_button = back_to_column_button
        copy_oid_button.clicked.connect(lambda: self.copy_selected_oid(False))
        copy_query_oid_button.clicked.connect(lambda: self.copy_selected_oid(True))
        fill_query_button.clicked.connect(lambda: self.fill_query_tool(False))
        back_to_column_button.clicked.connect(self.back_to_column_oid)
        run_query_button.clicked.connect(lambda: self.fill_query_tool(True))
        set_current_button.clicked.connect(self.set_selected_oid)
        translate_button.clicked.connect(self.translate_selected_description)
        self._selected_method = ""
        self._selected_query_oid = ""
        self.result_model = SimpleTableModel(RESULT_HEADERS, [])
        self.result_table = QTableView()
        self.result_table.setModel(self.result_model)
        configure_table_view(self.result_table, RESULT_COLUMN_WIDTHS)
        self.result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        refresh_button = snmp_action_button("搜索 / 刷新", "SEARCH")
        save_template_button = snmp_action_button("保存为 OID 模板", "SAVE")
        go_button = snmp_action_button("执行查询", "PLAY")
        self.go_button = go_button
        cancel_button = snmp_action_button("取消", "CANCEL")
        self.cancel_button = cancel_button
        export_button = snmp_action_button("导出结果", "SHARE")
        advanced_button = snmp_action_button("高级参数", "SETTING")
        temporary_button = snmp_action_button("临时 IP", "EDIT")
        refresh_button.clicked.connect(self.refresh)
        save_template_button.clicked.connect(self.save_selected_template)
        go_button.clicked.connect(self.run_browser_query)
        cancel_button.clicked.connect(self.cancel_query)
        export_button.clicked.connect(self.export_result)
        advanced_button.clicked.connect(self.show_advanced_parameters)
        temporary_button.clicked.connect(self.configure_temporary_target)
        self.device_group_filter.currentIndexChanged.connect(self._on_device_group_changed)
        self.device_search_input.returnPressed.connect(self._refresh_devices_from_search)
        self.device_search_input.textChanged.connect(lambda _text: self.device_search_timer.start())
        self.device_combo.currentIndexChanged.connect(lambda _index: self._handle_device_changed())
        self.search_input.returnPressed.connect(self.refresh)
        self.tree_mode_combo.currentIndexChanged.connect(lambda _index: self.refresh_mib_tree())
        self.rebuild_product_tree_button.clicked.connect(self._start_rebuild_product_tree)
        self.source_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.tree.currentItemChanged.connect(self._show_detail)
        self.tree.itemExpanded.connect(self._load_tree_children)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        self.result_table.customContextMenuRequested.connect(self._open_result_menu)
        target_bar = QHBoxLayout()
        target_bar.addWidget(QLabel("分组"))
        target_bar.addWidget(self.device_group_filter)
        target_bar.addWidget(QLabel("设备搜索"))
        target_bar.addWidget(self.device_search_input, 1)
        target_bar.addWidget(QLabel("设备/地址"))
        target_bar.addWidget(self.device_combo, 1)
        target_bar.addWidget(temporary_button)
        target_bar.addWidget(advanced_button)
        self.cancel_button.setEnabled(False)
        top = QHBoxLayout()
        top.addWidget(QLabel("OID"))
        top.addWidget(self.oid_input, 2)
        top.addWidget(QLabel("操作"))
        top.addWidget(self.operation_combo)
        top.addWidget(QLabel("MaxRep"))
        top.addWidget(self.max_repetitions)
        top.addWidget(QLabel("最大返回"))
        top.addWidget(self.max_rows)
        top.addWidget(go_button)
        top.addWidget(cancel_button)
        top.addWidget(export_button)
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("搜索"))
        filter_bar.addWidget(self.search_input, 1)
        filter_bar.addWidget(QLabel("树模式"))
        filter_bar.addWidget(self.tree_mode_combo)
        filter_bar.addWidget(self.rebuild_product_tree_button)
        filter_bar.addWidget(QLabel("来源"))
        filter_bar.addWidget(self.source_filter)
        filter_bar.addWidget(refresh_button)
        hint_bar = QHBoxLayout()
        hint_bar.addWidget(self.view_hint, 1)
        hint_bar.addWidget(self.generate_view_button)
        hint_bar.addWidget(self.use_h3c_v7v9_button)
        hint_bar.addWidget(self.use_global_h3c_button)
        splitter = QSplitter()
        left = QSplitter(Qt.Vertical)
        left.addWidget(titled_box("SNMP MIBs", self.tree))
        left.addWidget(titled_box("对象属性", self.property_table))
        left.setSizes([560, 240])
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.operation_label)
        op_buttons = QHBoxLayout()
        for button in (copy_oid_button, copy_query_oid_button, fill_query_button, back_to_column_button, run_query_button, set_current_button, translate_button, save_template_button):
            op_buttons.addWidget(button)
        op_buttons.addStretch(1)
        right_layout.addLayout(op_buttons)
        right_layout.addWidget(QLabel("Result Table"))
        right_layout.addWidget(self.result_table)
        splitter.addWidget(right)
        splitter.setSizes([520, 760])
        layout = QVBoxLayout(self)
        layout.addLayout(target_bar)
        layout.addLayout(top)
        layout.addLayout(filter_bar)
        layout.addLayout(hint_bar)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.path_label)
        self._set_view_hint_visible(False)

    def refresh(self) -> None:
        self.product_references_loaded = False
        self.refresh_devices()
        self.refresh_mib_tree()

    def _on_device_group_changed(self, _index: int) -> None:
        if self._refreshing_device_groups:
            return
        self.refresh_devices()

    def _refresh_devices_from_search(self) -> None:
        self.device_search_timer.stop()
        self.refresh_devices()

    def refresh_devices(self) -> None:
        if self._refreshing_devices:
            return
        self._refreshing_devices = True
        group_filter = self.device_group_filter.currentData()
        self.center.start_data_refresh(
            "devices",
            self._refresh_devices_impl,
            params={
                "filters": {
                    "search": self.device_search_input.text().strip() or None,
                    "group_filter": group_filter if group_filter not in {"", None} else None,
                }
            },
        )

    def _refresh_devices_impl(self, result: dict[str, object]) -> None:
        self._refreshing_devices = False
        current_device = self.device_combo.currentData()
        current_group = self.device_group_filter.currentData()
        self.devices = [Device.from_mapping(dict(row)) for row in result.get("devices") or [] if isinstance(row, dict)]
        self.enabled_dictionary_ids_by_device = {
            str(key): [int(value) for value in values]
            for key, values in dict(result.get("enabled_dictionary_ids") or {}).items()
            if isinstance(values, list)
        }
        self.device_group_filter.blockSignals(True)
        self.device_group_filter.clear()
        self.device_group_filter.addItem("全部分组", "")
        for row in result.get("groups") or []:
            if isinstance(row, dict) and row.get("id") is not None:
                self.device_group_filter.addItem(str(row.get("name") or ""), int(row.get("id")))
        group_index = self.device_group_filter.findData(current_group)
        self.device_group_filter.setCurrentIndex(group_index if group_index >= 0 else 0)
        self.device_group_filter.blockSignals(False)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if self.temporary_profile is not None:
            self.device_combo.addItem(self.temporary_name or f"临时：{self.temporary_profile.host}", TEMPORARY_TARGET_KEY)
        for device in self.devices:
            self.device_combo.addItem(f"{device.name} / {device.primary_address}", device.id)
        if self.device_combo.count() == 0:
            self.device_combo.addItem("当前分组无设备", None)
        index = self.device_combo.findData(current_device)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        elif current_device == TEMPORARY_TARGET_KEY and self.temporary_profile is not None:
            self.device_combo.setCurrentIndex(0)
        elif self.device_combo.count() > 0:
            self.device_combo.setCurrentIndex(0)
        self.device_combo.blockSignals(False)
        self.go_button.setEnabled(self.device_combo.currentData() is not None)
        if current_device != self.device_combo.currentData() or self.device_combo.currentData() is None:
            self._handle_device_changed()

    def refresh_device_groups(self) -> None:
        self.refresh_devices()

    def _refresh_device_groups(self) -> None:
        self.refresh_devices()

    def _handle_database_locked(self, context: str, retry_fn, counter_name: str, exc: sqlite3.OperationalError) -> None:
        app_logger.log_warning("SNMP_MIB_BROWSER_DATABASE_LOCKED", f"context={context}; error={exc}")
        self.path_label.setText("数据库正忙，设备列表/分组稍后自动刷新")
        retry_count = int(getattr(self, counter_name, 0))
        if retry_count >= 2:
            return
        setattr(self, counter_name, retry_count + 1)
        QTimer.singleShot(500, retry_fn)

    def _handle_device_changed(self) -> None:
        return

    def refresh_mib_tree(self) -> None:
        self.tree.clear()
        keyword = self.search_input.text().strip()
        source_filter = self._source_filter_key()
        tree_mode = str(self.tree_mode_combo.currentData() or TREE_MODE_GENERAL)
        if tree_mode == TREE_MODE_H3C_PRODUCT:
            self.rebuild_product_tree_button.setVisible(True)
            self._set_view_hint_visible(False)
            if not self.product_references_loaded:
                self._start_product_references_refresh()
                return
            self._build_product_reference_tree()
            return
        if not keyword:
            self.rebuild_product_tree_button.setVisible(False)
            self._set_view_hint_visible(False)
            self._build_base_tree(include_h3c=source_filter != "standard")
            self.tree.expandToDepth(2)
            auto_resize_tree_columns(self.tree, {0: 220, 1: 220, 2: 120})
            return
        self._set_view_hint_visible(False)
        self.rebuild_product_tree_button.setVisible(False)
        self._start_tree_load("search", keyword=keyword, source_filter=source_filter, limit=500)

    def _start_product_references_refresh(self) -> None:
        if self.product_reference_job_id is not None:
            self.path_label.setText("正在后台加载产品 MIB 参考表...")
            return
        self.path_label.setText("正在后台加载产品 MIB 参考表...")
        self.product_reference_job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type="snmp_product_references_refresh",
                params={
                    "db_path": str(self.center.paths.global_mib_db_path()),
                    "app_root": str(self.center.paths.app_root),
                    "data_root": str(self.center.paths.data_root),
                },
            )
        )

    def _product_reference_progress(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.product_reference_job_id or ""):
            return
        message = str(event.get("message") or "")
        if message:
            self.path_label.setText(message)

    def _product_reference_finished(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.product_reference_job_id or ""):
            return
        self.product_reference_job_id = None
        result = dict(event.get("result") or {})
        self.product_references = [dict(row) for row in result.get("references") or [] if isinstance(row, dict)]
        self.product_reference_tree_nodes = [dict(row) for row in result.get("tree_nodes") or [] if isinstance(row, dict)]
        self.product_references_loaded = True
        self._build_product_reference_tree()

    def _product_reference_failed(self, event: dict) -> None:
        if str(event.get("job_id") or "") != str(self.product_reference_job_id or ""):
            return
        self.product_reference_job_id = None
        message = str(event.get("message") or event.get("error") or "产品 MIB 参考表加载失败")
        self.path_label.setText(message)
        MessageBox.warning(self, "MIB 浏览器", message)

    def _enabled_dictionary_ids(self) -> list[int]:
        device = self._current_device()
        if device is None:
            return []
        return list(self.enabled_dictionary_ids_by_device.get(str(device.device_uuid or device.id), []))

    def _current_device(self) -> Device | None:
        device_id = self.device_combo.currentData()
        if device_id == TEMPORARY_TARGET_KEY:
            return None
        return next((device for device in self.devices if device.id == device_id), None)

    def _source_filter_key(self) -> str:
        value = self.source_filter.currentData()
        return str(value or source_filter_key(self.source_filter.currentText()))

    def _current_target_context(self) -> SnmpTargetContext | None:
        current = self.device_combo.currentData()
        if current == TEMPORARY_TARGET_KEY:
            if self.temporary_profile is None:
                return None
            name = self.temporary_name or f"临时：{self.temporary_profile.host}"
            return SnmpTargetContext(self.temporary_profile, TEMPORARY_TARGET_KEY, name, "temporary")
        device = self._current_device()
        if device is None:
            return None
        key = str(device.device_uuid or device.id)
        profile = self.profile_overrides.get(key) or SnmpProfile.from_device(device)
        return SnmpTargetContext(profile, key, device.name, "device", device)

    def configure_temporary_target(self) -> None:
        profile = self.temporary_profile or SnmpProfile(host="", version="v2c", community_ro="public")
        dialog = SnmpAdvancedParametersDialog(profile=profile, target_name="临时 IP 测试", temporary=True, max_repetitions=self.max_repetitions.value(), max_rows=self.max_rows.value(), parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        profile = dialog.profile()
        if not profile.host:
            MessageBox.information(self, "临时 IP", "请填写临时目标地址。")
            return
        self.temporary_profile = profile
        self.temporary_name = f"临时：{profile.host}"
        self.center.start_data_action("set_snmp_set_enabled", {"enabled": dialog.set_enabled_checkbox.isChecked()})
        self.max_repetitions.setValue(dialog.max_rep_input.value())
        self.max_rows.setValue(dialog.max_rows_input.value())
        self.refresh_devices()
        index = self.device_combo.findData(TEMPORARY_TARGET_KEY)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)

    def _start_tree_load(
        self,
        mode: str,
        *,
        keyword: str = "",
        source_filter: str = "",
        dictionary_ids: list[int] | None = None,
        module_id: int | None = None,
        parent_oid: str = "",
        limit: int = 500,
    ) -> None:
        if self.tree_worker is not None:
            self.tree_worker.cancel()
            self.tree_worker = None
        self._tree_task_id += 1
        task_id = self._tree_task_id
        self.tree.clear()
        self.tree.addTopLevelItem(QTreeWidgetItem(["正在后台加载 MIB 节点...", "", ""]))
        self.tree_worker = MibBrowserTreeLoadWorker(
            self.center.paths.global_mib_db_path(),
            mode=mode,
            keyword=keyword,
            source_filter=source_filter,
            dictionary_ids=dictionary_ids,
            module_id=module_id,
            parent_oid=parent_oid,
            limit=limit,
            task_id=task_id,
            parent=self,
        )
        self.tree_worker.finished_with_result.connect(self._tree_load_finished)
        self.tree_worker.finished.connect(self.tree_worker.deleteLater)
        self.tree_worker.start()

    def _tree_load_finished(self, result: object) -> None:
        if isinstance(result, Exception):
            self.tree_worker = None
            self.tree.clear()
            self.tree.addTopLevelItem(QTreeWidgetItem([f"加载失败：{result}", "", ""]))
            return
        payload = dict(result) if isinstance(result, dict) else {}
        if int(payload.get("task_id") or 0) != self._tree_task_id:
            return
        self.tree_worker = None
        self.tree.clear()
        if payload.get("cancelled"):
            self.tree.addTopLevelItem(QTreeWidgetItem(["已取消", "", ""]))
            return
        if payload.get("error"):
            self.tree.addTopLevelItem(QTreeWidgetItem([f"加载失败：{payload.get('error')}", "", ""]))
            return
        rows = list(payload.get("rows") or [])
        mode = str(payload.get("mode") or "")
        if mode == "module":
            self._build_module_tree(int(payload.get("module_id") or 0), rows)
        else:
            seen: set[tuple[str, str, str]] = set()
            inserted = 0
            for item in rows:
                oid = normalize_tree_oid(item.get("oid"))
                if not oid:
                    continue
                item = {**item, "oid": oid}
                key = (str(item.get("module_name") or ""), oid, str(item.get("name") or ""))
                if key in seen:
                    continue
                seen.add(key)
                self._insert_oid_path(item)
                inserted += 1
            if not inserted:
                self.tree.addTopLevelItem(QTreeWidgetItem(["未找到匹配的 MIB 节点", "", ""]))
        self.tree.expandToDepth(0)
        auto_resize_tree_columns(self.tree, {0: 220, 1: 220, 2: 120})

    def _build_module_tree(self, module_id: int, rows: list[dict[str, object]]) -> None:
        label = self.module_filter.currentText() or f"Module {module_id}"
        module_name = label.split(" [", 1)[0]
        root = QTreeWidgetItem([module_name, "", "module"])
        root.setData(0, Qt.UserRole, {"name": module_name, "oid": "", "module_name": module_name, "syntax": "module", "access": "", "status": ""})
        self.tree.addTopLevelItem(root)
        if not rows:
            root.addChild(QTreeWidgetItem(["该模块尚未编译出对象，可能仍处于缺依赖状态。", "", ""]))
            root.setExpanded(True)
            return
        by_oid: dict[str, QTreeWidgetItem] = {}
        sorted_rows = sorted(rows, key=lambda row: [int(part) if part.isdigit() else 0 for part in str(row.get("oid") or "").split(".")])
        seen: set[tuple[str, str]] = set()
        for row in sorted_rows:
            oid = str(row.get("oid") or "")
            name = str(row.get("name") or oid)
            key = (oid, name)
            if key in seen:
                continue
            seen.add(key)
            node_type = mib_node_type(row)
            item = QTreeWidgetItem([name, oid, node_type])
            item.setData(0, Qt.UserRole, row)
            item.setData(0, Qt.UserRole + 1, True)
            for column in range(3):
                item.setToolTip(column, mib_tooltip(row))
            parent = by_oid.get(str(row.get("parent_oid") or ""))
            if parent is None:
                root.addChild(item)
            else:
                parent.addChild(item)
            if oid:
                by_oid[oid] = item
        root.setExpanded(True)
        if root.childCount() == 1:
            root.child(0).setExpanded(True)

    def _set_view_hint_visible(self, visible: bool) -> None:
        for widget in (self.view_hint, self.generate_view_button, self.use_h3c_v7v9_button, self.use_global_h3c_button):
            widget.setVisible(visible)

    def _show_empty_device_view_hint(self) -> None:
        self.view_hint.setText(
            "当前设备尚未生成 MIB 视图。可根据设备版本自动生成推荐视图，或先使用 H3C V7/V9 无线 AC 默认视图、全局 H3C MIB 浏览。"
        )
        self._set_view_hint_visible(True)
        fill_table(self.property_table, [["提示", "当前设备没有启用字典，左侧显示 H3C 推荐 MIB 视图。"]])

    def generate_recommended_view(self) -> None:
        device = self._current_device()
        if device is None:
            MessageBox.information(self, "MIB 视图", "请先选择设备。")
            return
        self.center.start_data_action(
            "generate_recommended_view",
            {"device": device.to_record()},
            self._recommended_view_finished,
        )

    def _recommended_view_finished(self, result: dict[str, object]) -> None:
        if int(result.get("applied") or 0) <= 0:
            MessageBox.information(self, "MIB 视图", "当前设备暂无可用推荐字典，请先导入或初始化 H3C MIB 包。")
            return
        index = self.source_filter.findData("h3c_v7v9")
        if index >= 0:
            self.source_filter.setCurrentIndex(index)
        self.refresh()

    def use_h3c_v7v9_view(self) -> None:
        index = self.source_filter.findData("h3c_v7v9")
        if index >= 0:
            self.source_filter.setCurrentIndex(index)
        self.refresh()

    def use_global_h3c_view(self) -> None:
        index = self.source_filter.findData("h3c_v7v9")
        if index >= 0:
            self.source_filter.setCurrentIndex(index)
        self.refresh()

    def set_query_from_mib(self, oid: str, method: str, object_name: str = "", module_name: str = "") -> None:
        self.oid_input.setText(oid)
        index = self.operation_combo.findText(method_to_operation(method))
        if index >= 0:
            self.operation_combo.setCurrentIndex(index)
        self.operation_label.setText(
            "\n".join(
                [
                    f"当前对象：{object_name or oid}",
                    f"实际查询 OID：{oid}",
                    f"建议查询方式：{method}",
                    f"模块：{module_name}",
                ]
            )
        )

    def _build_base_tree(self, title: str = "OID 标准树", *, include_h3c: bool = True) -> None:
        _ = title

        def add_node(parent: QTreeWidgetItem | None, name: str, oid: str, *, lazy: bool = False, loaded: bool = True) -> QTreeWidgetItem:
            item = QTreeWidgetItem([name, oid, "OBJECT IDENTIFIER"])
            item.setData(0, Qt.UserRole, {"name": name, "oid": oid, "syntax": "OBJECT IDENTIFIER", "access": "not-accessible", "status": "current"})
            item.setData(0, Qt.UserRole + 1, loaded)
            if lazy:
                item.addChild(QTreeWidgetItem(["加载中...", "", ""]))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            return item

        iso = add_node(None, "iso", "1")
        org = add_node(iso, "org", "1.3")
        dod = add_node(org, "dod", "1.3.6")
        internet = add_node(dod, "internet", "1.3.6.1")
        add_node(internet, "directory", "1.3.6.1.1", lazy=True, loaded=False)
        mgmt = add_node(internet, "mgmt", "1.3.6.1.2")
        mib2 = add_node(mgmt, "mib-2", "1.3.6.1.2.1")
        for name, oid in (
            ("system", "1.3.6.1.2.1.1"),
            ("interfaces", "1.3.6.1.2.1.2"),
            ("at", "1.3.6.1.2.1.3"),
            ("ip", "1.3.6.1.2.1.4"),
            ("icmp", "1.3.6.1.2.1.5"),
            ("tcp", "1.3.6.1.2.1.6"),
            ("udp", "1.3.6.1.2.1.7"),
            ("egp", "1.3.6.1.2.1.8"),
            ("transmission", "1.3.6.1.2.1.10"),
            ("snmp", "1.3.6.1.2.1.11"),
            ("host", "1.3.6.1.2.1.25"),
        ):
            add_node(mib2, name, oid, lazy=True, loaded=False)
        add_node(internet, "experimental", "1.3.6.1.3", lazy=True, loaded=False)
        if not include_h3c:
            for item in (iso, org, dod, internet):
                item.setExpanded(True)
            return
        private = add_node(internet, "private", "1.3.6.1.4")
        enterprises = add_node(private, "enterprises", "1.3.6.1.4.1")
        h3c = add_node(enterprises, "h3c", "1.3.6.1.4.1.25506")
        common = add_node(h3c, "hh3cCommon", "1.3.6.1.4.1.25506.2")
        add_node(common, "hh3cDot11", "1.3.6.1.4.1.25506.2.75", lazy=True, loaded=False)
        for item in (iso, org, dod, internet, private, enterprises, h3c, common):
            item.setExpanded(True)

    def _insert_oid_path(self, data: dict[str, object]) -> None:
        oid = normalize_tree_oid(data.get("oid"))
        if not oid:
            return
        data = {**data, "oid": oid}
        parts = oid.split(".")
        parent: QTreeWidgetItem | None = None
        path = ""
        for index, part in enumerate(parts):
            path = part if not path else f"{path}.{part}"
            name = str(data.get("name") or "") if index == len(parts) - 1 else oid_label(path)
            existing = self._find_child(parent, path)
            if existing is None:
                existing = QTreeWidgetItem([name or path, path, mib_node_type(data) if index == len(parts) - 1 else "object_identifier"])
                existing.setData(0, Qt.UserRole, data if index == len(parts) - 1 else {"name": name or path, "oid": path, "syntax": "OBJECT IDENTIFIER", "access": "not-accessible", "status": "current"})
                if parent is None:
                    self.tree.addTopLevelItem(existing)
                else:
                    parent.addChild(existing)
            parent = existing
        if parent is not None:
            for column in range(3):
                parent.setToolTip(column, mib_tooltip(data))

    def _find_child(self, parent: QTreeWidgetItem | None, oid: str) -> QTreeWidgetItem | None:
        count = self.tree.topLevelItemCount() if parent is None else parent.childCount()
        for index in range(count):
            child = self.tree.topLevelItem(index) if parent is None else parent.child(index)
            data = child.data(0, Qt.UserRole)
            if isinstance(data, dict) and str(data.get("oid") or "") == oid:
                return child
        return None

    def _load_tree_children(self, item: QTreeWidgetItem) -> None:
        if item.data(0, Qt.UserRole + 1):
            return
        data = item.data(0, Qt.UserRole)
        if not isinstance(data, dict):
            return
        parent_oid = normalize_tree_oid(data.get("oid"))
        if not parent_oid:
            return
        item.takeChildren()
        item.addChild(QTreeWidgetItem(["正在后台加载...", "", ""]))
        task_id = id(item)
        worker = MibBrowserTreeLoadWorker(
            self.center.paths.global_mib_db_path(),
            mode="children",
            parent_oid=parent_oid,
            source_filter=self._source_filter_key(),
            limit=500,
            task_id=task_id,
            parent=self,
        )
        self.child_tree_workers[task_id] = (worker, item)
        worker.finished_with_result.connect(lambda result, task_id=task_id: self._tree_children_loaded(task_id, result))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _tree_children_loaded(self, task_id: int, result: object) -> None:
        context = self.child_tree_workers.pop(task_id, None)
        if context is None:
            return
        _worker, item = context
        payload = dict(result) if isinstance(result, dict) else {}
        item.takeChildren()
        if payload.get("error"):
            item.addChild(QTreeWidgetItem([f"加载失败：{payload.get('error')}", "", ""]))
            return
        seen: set[tuple[str, str, str]] = set()
        for child_data in payload.get("rows") or []:
            if not isinstance(child_data, dict):
                continue
            child_oid = normalize_tree_oid(child_data.get("oid"))
            if not child_oid:
                continue
            child_data = {**child_data, "oid": child_oid}
            key = (str(child_data.get("module_name") or ""), child_oid, str(child_data.get("name") or ""))
            if key in seen:
                continue
            seen.add(key)
            child = QTreeWidgetItem([str(child_data.get("name") or ""), child_oid, mib_node_type(child_data)])
            child.setData(0, Qt.UserRole, child_data)
            child.setData(0, Qt.UserRole + 1, False)
            if not int(child_data.get("is_scalar") or 0):
                child.addChild(QTreeWidgetItem(["加载中...", "", ""]))
            for column in range(3):
                child.setToolTip(column, mib_tooltip(child_data))
            item.addChild(child)
        item.setData(0, Qt.UserRole + 1, True)

    def _build_product_reference_tree(self) -> None:
        self.tree.clear()
        references = list(self.product_references)
        nodes_by_parent: dict[tuple[int, int | None], list[dict[str, object]]] = {}
        for node in self.product_reference_tree_nodes:
            reference_id = int(node.get("reference_id") or 0)
            parent_value = node.get("parent_id")
            parent_id = int(parent_value) if parent_value not in (None, "") else None
            nodes_by_parent.setdefault((reference_id, parent_id), []).append(node)
        if not references:
            self.tree.addTopLevelItem(QTreeWidgetItem(["尚未导入 H3C 产品 MIB 参考表", "", "product_reference"]))
            auto_resize_tree_columns(self.tree, {0: 260, 1: 220, 2: 120})
            return

        def node_label(row: dict[str, object]) -> str:
            node_type = str(row.get("node_type") or "")
            value = str(
                row.get("display_name")
                or row.get("node_name")
                or row.get("object_name")
                or row.get("module_name")
                or row.get("numeric_oid")
                or row.get("id")
                or ""
            )
            if node_type in {"module", "mib_module"}:
                return normalize_h3c_module_display_name(value)
            return value

        def add_reference_node(parent: QTreeWidgetItem, row: dict[str, object]) -> QTreeWidgetItem:
            node_type = str(row.get("node_type") or "reference")
            oid = normalize_tree_oid(row.get("numeric_oid")) if node_type in {"object", "trap"} else ""
            label = node_label(row)
            module_name = normalize_h3c_module_display_name(row.get("module_name")) if node_type in {"module", "mib_module"} else str(row.get("module_name") or "")
            data = {
                "name": str(row.get("object_name") or label),
                "oid": oid,
                "module_name": module_name,
                "syntax": str(row.get("data_type_from_reference") or node_type),
                "access": str(row.get("access_from_reference") or ""),
                "status": str(row.get("operation_support") or ""),
                "description": str(row.get("meaning") or row.get("function_description") or row.get("implementation_spec") or ""),
                "reference_name": parent.text(0),
                "is_trap": 1 if node_type == "trap" else 0,
                "is_notification": 1 if node_type == "notification" else 0,
            }
            item = QTreeWidgetItem([label, oid, node_type])
            item.setData(0, Qt.UserRole, data)
            item.setData(0, Qt.UserRole + 1, True)
            for column in range(3):
                item.setToolTip(column, mib_tooltip(data))
            parent.addChild(item)
            for child_row in nodes_by_parent.get((int(row["reference_id"]), int(row["id"])), []):
                add_reference_node(item, child_row)
            return item

        for reference in references:
            reference_id = int(reference.get("id") or 0)
            if not reference_id:
                continue
            label = str(reference.get("reference_name") or reference.get("source_file") or f"Reference {reference_id}")
            root = QTreeWidgetItem([label, "", "product_reference"])
            root.setData(0, Qt.UserRole, {"name": label, "oid": "", "syntax": "product_reference", "access": "", "status": "", "reference_id": reference_id})
            root.setData(0, Qt.UserRole + 1, True)
            self.tree.addTopLevelItem(root)
            top_nodes = list(nodes_by_parent.get((reference_id, None), []))
            if len(top_nodes) == 1 and str(top_nodes[0].get("node_type") or "") == "reference_root":
                top_nodes = list(nodes_by_parent.get((reference_id, int(top_nodes[0]["id"])), []))
            if not top_nodes:
                object_count = int(reference.get("object_override_count") or reference.get("object_count") or 0)
                if object_count > 0:
                    root.addChild(QTreeWidgetItem(["目录树未生成，可点击“重建产品目录树”修复", "", "rebuild_available"]))
                else:
                    root.addChild(QTreeWidgetItem(["参考表未解析到对象，请重新导入 Excel", "", "need_reimport"]))
            for row in top_nodes:
                add_reference_node(root, row)
            root.setExpanded(True)
        self.tree.expandToDepth(1)
        auto_resize_tree_columns(self.tree, {0: 260, 1: 220, 2: 140})

    def _selected_product_reference_id(self) -> int | None:
        current = self.tree.currentItem()
        while current is not None:
            data = current.data(0, Qt.UserRole)
            if isinstance(data, dict) and data.get("reference_id"):
                return int(data["reference_id"])
            current = current.parent()
        references = list(self.product_references)
        return int(references[0]["id"]) if references else None

    def _start_rebuild_product_tree(self) -> None:
        reference_id = self._selected_product_reference_id()
        if reference_id is None:
            MessageBox.information(self, "产品目录树", "当前没有可重建的产品 MIB 参考表。")
            return
        if self.product_tree_rebuild_worker is not None:
            return
        self._product_tree_rebuild_task_id += 1
        task_id = self._product_tree_rebuild_task_id
        self.rebuild_product_tree_button.setEnabled(False)
        self.path_label.setText("正在后台重建产品 MIB 参考目录树...")
        self.product_tree_rebuild_worker = ProductReferenceTreeRebuildWorker(self.center.paths.global_mib_db_path(), reference_id, self)
        self.product_tree_rebuild_worker.finished_with_result.connect(lambda result, task_id=task_id: self._product_tree_rebuild_finished(result, task_id))
        self.product_tree_rebuild_worker.finished.connect(self.product_tree_rebuild_worker.deleteLater)
        self.product_tree_rebuild_worker.start()

    def _product_tree_rebuild_finished(self, result: object, task_id: int | None = None) -> None:
        if task_id is not None and task_id != self._product_tree_rebuild_task_id:
            return
        self.product_tree_rebuild_worker = None
        self.rebuild_product_tree_button.setEnabled(True)
        if isinstance(result, Exception):
            self.path_label.setText(f"产品目录树重建失败：{result}")
            MessageBox.warning(self, "产品目录树", f"产品目录树重建失败：{result}")
            return
        payload = dict(result) if isinstance(result, dict) else {}
        self.path_label.setText(
            "产品目录树重建完成："
            f"分类 {payload.get('category_count', 0)}，"
            f"模块 {payload.get('module_count', 0)}，"
            f"对象 {payload.get('object_count', 0)}，"
            f"树节点 {payload.get('node_count', 0)}"
        )
        self.refresh_mib_tree()

    def _show_detail(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None = None) -> None:
        _ = previous
        if current is None:
            return
        item = current.data(0, Qt.UserRole)
        if not isinstance(item, dict):
            fill_table(self.property_table, [])
            return
        lookup = current.data(0, Qt.UserRole + 2)
        if not isinstance(lookup, dict):
            current.setData(0, Qt.UserRole + 2, {"loading": True})
            self.center.start_data_refresh(
                "mib_detail_lookup",
                lambda result, tree_item=current: self._detail_lookup_finished(tree_item, result),
                params={
                    "module_name": str(item.get("module_name") or ""),
                    "object_name": str(item.get("name") or ""),
                    "oid": str(item.get("oid") or ""),
                    "syntax": str(item.get("syntax") or ""),
                    "source_text": str(item.get("description") or ""),
                    "is_trap": bool(item.get("is_trap") or item.get("is_notification")),
                },
            )
            return
        if lookup.get("loading"):
            return
        method, query_oid = MibIndexService(self.center.global_repo).object_query_method(item)
        self._selected_method = method
        self._selected_query_oid = query_oid if method else ""
        hints = []
        syntax = str(item.get("syntax") or "")
        module_name = str(item.get("module_name") or "")
        object_name = str(item.get("name") or "")
        oid = str(item.get("oid") or "")
        object_override = lookup.get("object_override") if isinstance(lookup.get("object_override"), dict) else None
        trap_override = lookup.get("trap_override") if isinstance(lookup.get("trap_override"), dict) else None
        if "Counter" in syntax:
            hints.append("这是 Counter / Counter64 类型，单次查询只能看到累计值。如需速率，请创建周期采集任务。")
        if int(item.get("is_trap") or 0) or int(item.get("is_notification") or 0):
            hints.append("这是 Trap / Notification 定义，不支持 Get。可以加入 Trap 解析规则。")
        reference = trap_override or object_override
        reference_status = "未匹配"
        if reference:
            support = str(reference.get("operation_support") or reference.get("access_from_reference") or reference.get("implementation_spec") or reference.get("trap_level") or "已匹配")
            version = str(reference.get("software_version") or reference.get("reference_name") or "产品参考")
            reference_status = f"{version} {support}"
        chinese_description = ""
        implementation_spec = ""
        if object_override:
            chinese_description = str(object_override.get("chinese_description") or "")
            implementation_spec = str(object_override.get("implementation_spec") or "")
        if trap_override:
            chinese_description = str(trap_override.get("trap_title") or "")
            implementation_spec = str(trap_override.get("trigger_reason") or "")
        fill_table(
            self.property_table,
            [
                ["Name", item.get("name")],
                ["OID", item.get("oid")],
                ["MIB", item.get("module_name")],
                ["Syntax", item.get("syntax")],
                ["Access", item.get("access")],
                ["Status", item.get("status")],
                ["DefVal", ""],
                ["Indexes", item.get("index_def")],
                ["Descr", item.get("description")],
                ["中文含义", chinese_description or "未匹配产品参考"],
                ["实现规格", implementation_spec or (str(object_override.get("function_description") or "") if object_override else "")],
                ["操作支持情况", str(object_override.get("operation_support") or "") if object_override else ""],
                ["产品参考来源", str(reference.get("reference_name") or "") if reference else "未匹配"],
                ["匹配状态", str(reference.get("match_status") or "mib_definition") if reference else "mib_definition"],
                ["实机验证", "未验证"],
                ["来源版本", module_display_name(item)],
                ["提示", "；".join(hints)],
            ],
        )
        if method:
            self.oid_input.setText(query_oid)
            index = self.operation_combo.findText(method_to_operation(method))
            if index >= 0:
                self.operation_combo.setCurrentIndex(index)
        self.operation_label.setText(
            "\n".join(
                [
                    f"当前对象：{object_name}",
                    f"当前 OID：{oid}",
                    f"建议查询方式：{method or '不可查询'}",
                    f"实际查询 OID：{query_oid if method else 'Trap / Notification 不支持查询'}",
                    f"模块：{module_name}",
                    f"来源：{module_display_name(item)}",
                ]
            )
        )
        self.path_label.setText(f"路径：{self._tree_path(current)}    当前 OID：{oid}    建议操作：{method or '不可查询'}")
        allowed, reason = can_set_mib_object(item, query_oid if method else oid)
        self.set_current_button.setEnabled(allowed)
        self.set_current_button.setToolTip(reason)

    def _detail_lookup_finished(self, tree_item: QTreeWidgetItem, result: dict[str, object]) -> None:
        tree_item.setData(0, Qt.UserRole + 2, dict(result))
        if self.tree.currentItem() is tree_item:
            self._show_detail(tree_item)

    def copy_selected_oid(self, query_oid: bool) -> None:
        data = self._selected_data()
        if not data:
            return
        text = self._selected_query_oid if query_oid else str(data.get("oid") or "")
        if text:
            QApplication.clipboard().setText(text)

    def back_to_column_oid(self) -> None:
        oid = self.oid_input.text().strip()
        if not oid:
            return
        resolved = self._resolve_result_oid(oid)
        base_oid = str(resolved.get("oid") or "").strip()
        if base_oid and base_oid != oid and oid.startswith(base_oid + "."):
            self.oid_input.setText(base_oid)
            index = self.operation_combo.findText("Bulk Walk")
            if index >= 0:
                self.operation_combo.setCurrentIndex(index)
            self.operation_label.setText(f"已回到列 OID：{base_oid}。可使用 Walk / Bulk Walk 遍历整列。")
            return
        MessageBox.information(self, "MIB 浏览器", "当前 OID 未识别出可回退的实例后缀。")

    def fill_query_tool(self, run_now: bool) -> None:
        data = self._selected_data()
        if not data or not self._selected_method:
            MessageBox.information(self, "MIB 浏览器", "Trap / Notification 不支持填入查询栏，只能加入 Trap 解析规则。")
            return
        self.center.switch_to_query_from_mib(self._selected_query_oid, self._selected_method, str(data.get("name") or ""), str(data.get("module_name") or ""), run_now=run_now)

    def set_selected_oid(self) -> None:
        data = self._selected_data()
        if not data:
            return
        oid = self._selected_query_oid or str(data.get("oid") or "")
        allowed, reason = can_set_mib_object(data, oid)
        if not allowed:
            MessageBox.information(self, "SNMP Set", reason)
            return
        self.open_set_dialog(data, oid=oid)

    def open_set_dialog(self, data: dict[str, object], *, oid: str, current_value: str = "") -> None:
        target = self._current_target_context()
        if target is None:
            MessageBox.information(self, "SNMP Set", "请先选择设备或临时 IP。")
            return
        if target.profile.version.lower() in {"v1", "v2", "v2c"} and not target.profile.community_rw:
            MessageBox.information(self, "SNMP Set", "未配置写团体字，无法执行 SNMP SET")
            return
        dialog = SnmpSetDialog(
            oid=oid,
            object_name=str(data.get("name") or ""),
            module_name=str(data.get("module_name") or ""),
            access=str(data.get("access") or ""),
            syntax=str(data.get("syntax") or ""),
            current_value=current_value,
            write_community=target.profile.community_rw,
            target_name=f"{target.device_name} / {target.profile.host}:{target.profile.port}",
            description=str(data.get("description") or ""),
            enum_map_json=str(data.get("enum_map_json") or ""),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.result_data()
        old_value = current_value or "-"
        confirm = MessageBox(self)
        confirm.setIcon(MessageBox.Warning)
        confirm.setWindowTitle("确认执行 SNMP Set")
        confirm.setText(
            "\n".join(
                [
                    "确认执行 SNMP Set：",
                    "",
                    f"目标：{target.device_name} / {target.profile.host}:{target.profile.port}",
                    f"OID：{values.oid}",
                    f"对象：{data.get('name') or ''}",
                    f"类型：{values.data_type}",
                    f"旧值：{old_value}",
                    f"新值：{values.value}",
                    "",
                    "该操作会修改设备运行状态。确认继续？",
                ]
            )
        )
        confirm.setStandardButtons(MessageBox.Cancel | MessageBox.Yes)
        confirm.button(MessageBox.Yes).setText("确认执行")
        confirm.button(MessageBox.Cancel).setText("取消")
        if confirm.exec() != MessageBox.Yes:
            return
        request = SnmpSetRequest(
            profile=target.profile,
            oid=values.oid,
            data_type=values.data_type,
            value=values.value,
            device_id=target.device_id,
            device_name=target.device_name,
            object_name=str(data.get("name") or ""),
            module_name=str(data.get("module_name") or ""),
            access=str(data.get("access") or ""),
            old_value=old_value,
        )
        if self.set_worker is not None:
            self.set_worker.cancel()
        self._set_task_id += 1
        task_id = self._set_task_id
        self.set_worker = SnmpSetWorker(self.center.paths.site_snmp_db_path(self.center.site_name), request, self)
        self.set_worker.progress.connect(lambda text, task_id=task_id: self.operation_label.setText(text) if task_id == self._set_task_id else None)
        self.set_worker.finished_with_result.connect(lambda result, task_id=task_id: self._set_finished(result, task_id))
        self.set_worker.finished.connect(self.set_worker.deleteLater)
        self.set_worker.start()

    def _set_finished(self, result: object, task_id: int | None = None) -> None:
        if task_id is not None and task_id != self._set_task_id:
            return
        self.set_worker = None
        if isinstance(result, Exception):
            self.operation_label.setText(f"Set 执行失败：{result}")
            return
        if not isinstance(result, SnmpSetResult):
            self.operation_label.setText("Set 执行失败：返回结果异常。")
            return
        self.operation_label.setText(f"Set 完成：{result.status}；旧值：{result.old_value}；新值：{result.new_value}；验证值：{result.result_value}。{result.error_message}")
        self._append_set_result_row(result)
        if result.status == "success":
            self.oid_input.setText(result.request.oid)
            index = self.operation_combo.findText("Get")
            if index >= 0:
                self.operation_combo.setCurrentIndex(index)
            self.run_browser_query()

    def translate_selected_description(self) -> None:
        data = self._selected_data()
        if not data:
            return
        source_text = str(data.get("description") or "")
        if not source_text:
            return
        module_name = str(data.get("module_name") or "")
        object_name = str(data.get("name") or "")
        oid = str(data.get("oid") or "")
        current = self.tree.currentItem()
        lookup = current.data(0, Qt.UserRole + 2) if current is not None else {}
        cached = lookup.get("translation") if isinstance(lookup, dict) and isinstance(lookup.get("translation"), dict) else None
        translated = str(cached.get("translated_text") or "") if cached else translate_mib_description(source_text)
        if not cached:
            self.center.start_data_action(
                "upsert_translation",
                {
                    "object_id": int(data.get("id") or 0) or None,
                    "module_name": module_name,
                    "object_name": object_name,
                    "numeric_oid": oid,
                    "source_text": source_text,
                    "translated_text": translated,
                },
            )
        fill_table(self.property_table, [[self.property_table.item(row, 0).text(), translated if self.property_table.item(row, 0).text() == "中文描述" else self.property_table.item(row, 1).text()] for row in range(self.property_table.rowCount())])

    def _tree_path(self, item: QTreeWidgetItem) -> str:
        names: list[str] = []
        current: QTreeWidgetItem | None = item
        while current is not None:
            names.append(current.text(0))
            current = current.parent()
        return ".".join(reversed(names))

    def _selected_data(self) -> dict[str, object] | None:
        item = self.tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        return data if isinstance(data, dict) else None

    def _open_context_menu(self, position) -> None:
        data = self._selected_data()
        if not data:
            return
        menu = QMenu(self)
        menu.addAction("复制 OID", lambda: self.copy_selected_oid(False))
        menu.addAction("复制对象名", lambda: QApplication.clipboard().setText(str(data.get("name") or "")))
        menu.addAction("填入顶部查询栏", lambda: self.fill_query_tool(False))
        menu.addAction("保存为 OID 模板", self.save_selected_template)
        menu.addAction("查看所属模块", lambda: MessageBox.information(self, "所属模块", module_display_name(data)))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def run_browser_query(self) -> None:
        target = self._current_target_context()
        if target is None:
            MessageBox.information(self, "MIB 浏览器", "请先选择设备或临时 IP。")
            return
        oid = self.oid_input.text().strip()
        if not oid:
            return
        method = operation_to_method(self.operation_combo.currentText())
        data = self._selected_data() or self._resolve_result_oid(oid)
        base_oid = str(data.get("oid") or "").strip()
        if method == "Get" and int(data.get("is_scalar") or 0) and oid == base_oid and not oid.endswith(".0"):
            oid = f"{oid}.0"
            self.oid_input.setText(oid)
        if method == "Get" and (int(data.get("is_table") or 0) or int(data.get("is_table_entry") or 0) or int(data.get("is_column") or 0)) and oid == base_oid:
            MessageBox.information(self, "MIB 浏览器", "当前对象是表或表字段根 OID，Get 需要具体实例。请改用 Walk / Get Bulk / Bulk Walk。")
            return
        if method == "Set":
            allowed, reason = can_set_mib_object(data, oid)
            if not allowed and str(data.get("name") or "") != oid:
                MessageBox.information(self, "SNMP Set", reason)
                return
            self.open_set_dialog(data, oid=oid)
            return
        request = SnmpQueryRequest(
            profile=target.profile,
            method=method,
            oid=oid,
            max_repetitions=self.max_repetitions.value(),
            max_rows=self.max_rows.value(),
            save_history=True,
            device_id=target.device_id,
            device_name=target.device_name,
        )
        if self.worker is not None:
            self.worker.cancel()
        self._query_task_id += 1
        task_id = self._query_task_id
        self.worker = SnmpQueryWorker(self.center.paths.site_snmp_db_path(self.center.site_name), request, self)
        self.worker.progress.connect(lambda text, task_id=task_id: self.operation_label.setText(text) if task_id == self._query_task_id else None)
        self.worker.finished_with_result.connect(lambda result, task_id=task_id: self._browser_query_finished(result, task_id))
        self.worker.finished.connect(self.worker.deleteLater)
        self.go_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.operation_label.setText(f"正在执行 {self.operation_combo.currentText()}...")
        self.worker.start()

    def show_advanced_parameters(self) -> None:
        target = self._current_target_context()
        if target is None:
            MessageBox.information(self, "高级参数", "请先选择设备或临时 IP。")
            return
        dialog = SnmpAdvancedParametersDialog(
            profile=target.profile,
            target_name=f"{target.device_name} / {target.profile.host}:{target.profile.port}",
            temporary=target.source == "temporary",
            max_repetitions=self.max_repetitions.value(),
            max_rows=self.max_rows.value(),
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            if dialog.set_enabled_checkbox.isChecked() and not self.center.snmp_set_enabled:
                confirm = MessageBox.warning(self, "启用写操作", "启用 SNMP Set 后可以修改设备配置。确认启用？", MessageBox.Yes | MessageBox.No)
                if confirm != MessageBox.Yes:
                    return
            profile = dialog.profile()
            if target.source == "temporary":
                self.temporary_profile = profile
                self.temporary_name = f"临时：{profile.host}"
                self.refresh_devices()
                index = self.device_combo.findData(TEMPORARY_TARGET_KEY)
                if index >= 0:
                    self.device_combo.setCurrentIndex(index)
            else:
                self.profile_overrides[target.device_id] = profile
            self.max_repetitions.setValue(dialog.max_rep_input.value())
            self.max_rows.setValue(dialog.max_rows_input.value())
            self.center.start_data_action("set_snmp_set_enabled", {"enabled": dialog.set_enabled_checkbox.isChecked()})

    def cancel_query(self) -> None:
        cancelled = False
        if self.worker is not None:
            self.worker.cancel()
            self._query_task_id += 1
            cancelled = True
        if self.tree_worker is not None:
            self.tree_worker.cancel()
            self._tree_task_id += 1
            self.tree.clear()
            self.tree.addTopLevelItem(QTreeWidgetItem(["已取消", "", ""]))
            cancelled = True
        if self.product_tree_rebuild_worker is not None:
            self.product_tree_rebuild_worker.cancel()
            self._product_tree_rebuild_task_id += 1
            self.rebuild_product_tree_button.setEnabled(True)
            cancelled = True
        if self.set_worker is not None:
            self.set_worker.cancel()
            self._set_task_id += 1
            cancelled = True
        if cancelled:
            self.go_button.setEnabled(self.device_combo.currentData() is not None)
            self.cancel_button.setEnabled(False)
        self.operation_label.setText("已取消" if cancelled else "没有正在执行的任务")
        if cancelled:
            self.path_label.setText("已取消当前后台任务")

    def _browser_query_finished(self, result: object, task_id: int | None = None) -> None:
        if task_id is not None and task_id != self._query_task_id:
            return
        self.worker = None
        self.go_button.setEnabled(self.device_combo.currentData() is not None)
        self.cancel_button.setEnabled(False)
        if isinstance(result, Exception):
            self.operation_label.setText(f"查询失败：{result}")
            return
        if not isinstance(result, SnmpQueryResult):
            self.operation_label.setText("查询失败：返回结果异常。")
            return
        self.last_result = result
        self.operation_label.setText(f"查询完成：{status_label(result.status)}，返回 {len(result.rows)} 条，耗时 {result.elapsed_ms} ms。{result.error_message}")
        message = f"查询完成：{status_label(result.status)}，返回 {len(result.rows)} 条，耗时 {result.elapsed_ms} ms。{result.error_message}"
        if not result.rows and not result.error_message:
            message += "返回 0 条：可能 OID 不是可查询子树、对象仅用于 Trap、表为空、SNMP view 限制或当前设备不支持。"
        if result.rows and result.request.method in {"Walk", "BulkWalk", "TableWalk", "Table Walk", "GetSubtree"}:
            resolved = self._resolve_result_oid(result.request.oid)
            base_oid = str(resolved.get("oid") or "")
            if base_oid and base_oid != result.request.oid and result.request.oid.startswith(base_oid + "."):
                message += " 当前 OID 看起来是表字段实例；若要遍历整列，请点击“回到列 OID”。"
        self.operation_label.setText(message)
        rows = []
        for row in result.rows:
            resolved = self._resolve_result_oid(row.oid)
            instance_raw = instance_suffix(row.oid, str(resolved.get("oid") or ""))
            decoded_instance = decode_octet_string_instance(instance_raw)
            name_oid = f"{resolved.get('name')}.{instance_raw}" if resolved.get("name") and instance_raw else str(resolved.get("name") or row.oid)
            rows.append(
                [
                    result.request.method,
                    name_oid,
                    row.decoded_value or row.value,
                    row.value_type,
                    f"{result.request.profile.host}:{result.request.profile.port}",
                    status_label(row.status),
                    row.latency_ms,
                    row.oid,
                    instance_raw,
                    decoded_instance,
                    resolved.get("module_name") or "",
                    result.request.started_at,
                    compact_error_message(row.error_message),
                ]
            )
        self.result_model.set_rows(RESULT_HEADERS, rows)
        auto_resize_table_view_columns(self.result_table, RESULT_COLUMN_WIDTHS)

    def _append_set_result_row(self, result: SnmpSetResult) -> None:
        rows = list(self.result_model.rows)
        rows.append(
            [
                "Set",
                result.request.object_name or result.request.oid,
                result.new_value or result.request.value,
                result.request.data_type,
                f"{result.request.profile.host}:{result.request.profile.port}",
                "SET 成功" if result.status == "success" else "SET 失败",
                result.elapsed_ms,
                result.request.oid,
                "",
                "",
                result.request.module_name,
                result.request.started_at,
                compact_error_message(result.error_message),
            ]
        )
        self.result_model.set_rows(RESULT_HEADERS, rows)
        auto_resize_table_view_columns(self.result_table, RESULT_COLUMN_WIDTHS)

    def _resolve_result_oid(self, oid: str) -> dict[str, object]:
        parts = oid.split(".")
        prefixes = {".".join(parts[:end]): end for end in range(len(parts), 0, -1)}
        iterator = QTreeWidgetItemIterator(self.tree)
        best: tuple[int, dict[str, object]] | None = None
        while iterator.value() is not None:
            data = iterator.value().data(0, Qt.UserRole)
            if isinstance(data, dict):
                candidate_oid = str(data.get("oid") or "").strip(".")
                if candidate_oid in prefixes and (best is None or prefixes[candidate_oid] > best[0]):
                    best = (prefixes[candidate_oid], data)
            iterator += 1
        if best is not None:
            return best[1]
        return {"oid": oid, "name": oid, "module_name": ""}

    def export_result(self) -> None:
        if self.last_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 SNMP 查询结果", str(Path.home() / "snmp_browser_result.xlsx"), "Excel (*.xlsx);;CSV (*.csv);;JSON (*.json)")
        if not path:
            return
        result_file = _write_snmp_result_cache(self.center.paths, self.last_result, "mib_browser")
        submit_export_task(
            self,
            snmp_query_result_spec(path, result_file=result_file, title="导出 SNMP 查询结果", open_dir_on_success=True),
            success_title="MIB 浏览器",
            paths=self.center.paths,
        )

    def _open_result_menu(self, position) -> None:
        index = self.result_table.indexAt(position)
        if not index.isValid():
            return
        row = index.row()
        raw_oid = str(self.result_model.rows[row][7])
        value = str(self.result_model.rows[row][2])
        menu = QMenu(self)
        menu.addAction("复制当前行", lambda: QApplication.clipboard().setText("\t".join(str(item) for item in self.result_model.rows[row])))
        menu.addAction("复制 OID", lambda: QApplication.clipboard().setText(raw_oid))
        menu.addAction("复制 Value", lambda: QApplication.clipboard().setText(value))
        menu.addAction("使用此 OID 再次 Get", lambda: self._rerun_result_oid(raw_oid, "Get"))
        menu.addAction("使用此 OID GetNext", lambda: self._rerun_result_oid(raw_oid, "Get Next"))
        menu.addAction("从此 OID Walk", lambda: self._rerun_result_oid(raw_oid, "Walk"))
        menu.addAction("Set 此 OID", lambda: self._set_result_oid(row))
        menu.exec(self.result_table.viewport().mapToGlobal(position))

    def _rerun_result_oid(self, oid: str, operation: str) -> None:
        self.oid_input.setText(oid)
        index = self.operation_combo.findText(operation)
        if index >= 0:
            self.operation_combo.setCurrentIndex(index)
        self.run_browser_query()

    def _set_result_oid(self, row: int) -> None:
        raw_oid = str(self.result_model.rows[row][7])
        value = str(self.result_model.rows[row][2])
        resolved = self._resolve_result_oid(raw_oid)
        allowed, reason = can_set_mib_object(resolved, raw_oid)
        if not allowed and str(resolved.get("name") or "") != raw_oid:
            MessageBox.information(self, "SNMP Set", reason)
            return
        self.open_set_dialog(resolved, oid=raw_oid, current_value=value)

    def save_selected_template(self) -> None:
        item = self.tree.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not isinstance(data, dict):
            return
        method, query_oid = MibIndexService(self.center.global_repo).object_query_method(data)
        if not method:
            MessageBox.information(self, "OID 模板", "Trap / Notification 不支持保存为查询模板。")
            return
        name, ok = InputDialog.getText(self, "保存为 OID 模板", "模板名称", text=str(data.get("name") or ""))
        if ok and name.strip():
            self.center.start_data_action(
                "create_template",
                {
                    "name": name.strip(),
                    "oid": query_oid,
                    "method": method,
                    "module_name": str(data.get("module_name") or ""),
                    "object_name": str(data.get("name") or ""),
                },
                lambda _result: MessageBox.information(self, "OID 模板", "已保存模板。"),
            )


class SnmpQueryPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: SnmpQueryWorker | None = None
        self.set_worker: SnmpSetWorker | None = None
        self.last_result: SnmpQueryResult | None = None
        self.devices: list[Device] = []
        self.device_combo = QComboBox()
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Get", "GetNext", "Walk", "BulkWalk", "Table Walk", "Set"])
        self.oid_input = QLineEdit("1.3.6.1.2.1.1.5.0")
        self.max_repetitions = QSpinBox()
        self.max_repetitions.setRange(1, 50)
        self.max_repetitions.setValue(10)
        self.max_rows = QSpinBox()
        self.max_rows.setRange(1, 10000)
        self.max_rows.setValue(200)
        self.save_history = QCheckBox("保存历史")
        self.save_history.setChecked(True)
        self.status = QLabel()
        self.model = SimpleTableModel(["时间", "设备", "OID", "名称", "实例", "类型", "原始值", "解码值", "延迟", "状态", "错误信息"], [])
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        run_button = snmp_action_button("执行查询", "PLAY")
        cancel_button = snmp_action_button("取消", "CANCEL")
        export_button = snmp_action_button("导出结果", "SHARE")
        refresh_button = snmp_action_button("刷新设备", "SYNC")
        choose_mib_button = snmp_action_button("从 MIB 选择", "SEARCH")
        run_button.clicked.connect(self.run_query)
        cancel_button.clicked.connect(self.cancel_query)
        export_button.clicked.connect(self.export_result)
        refresh_button.clicked.connect(self.refresh)
        choose_mib_button.clicked.connect(self.open_mib_browser)
        form = QHBoxLayout()
        for label, widget in (("设备", self.device_combo), ("方式", self.method_combo), ("OID", self.oid_input), ("MaxRep", self.max_repetitions), ("最大返回", self.max_rows)):
            form.addWidget(QLabel(label))
            form.addWidget(widget)
        form.addWidget(self.save_history)
        form.addWidget(refresh_button)
        form.addWidget(choose_mib_button)
        form.addWidget(run_button)
        form.addWidget(cancel_button)
        form.addWidget(export_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.center.start_data_refresh("devices", self._apply_devices)

    def _apply_devices(self, result: dict[str, object]) -> None:
        current = self.device_combo.currentData()
        self.devices = [Device.from_mapping(dict(row)) for row in result.get("devices") or [] if isinstance(row, dict)]
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self.devices:
            self.device_combo.addItem(f"{device.name} / {device.primary_address}", device.id)
        index = self.device_combo.findData(current)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)

    def _current_device(self) -> Device | None:
        device_id = self.device_combo.currentData()
        return next((device for device in self.devices if device.id == device_id), None)

    def set_query_from_mib(self, oid: str, method: str, object_name: str = "", module_name: str = "") -> None:
        self.oid_input.setText(oid)
        index = self.method_combo.findText(method)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)
        self.status.setText(f"已从 MIB 选择：{module_name} / {object_name}，{method} {oid}")

    def open_mib_browser(self) -> None:
        index = self.center.tabs.indexOf(self.center.browser_page)
        self.center.tabs.setCurrentIndex(index)

    def run_query(self) -> None:
        device = self._current_device()
        if device is None:
            MessageBox.information(self, "SNMP 查询工具", "请先选择设备。")
            return
        if self.method_combo.currentText() == "Set":
            self.run_set(device)
            return
        request = SnmpQueryRequest(
            profile=SnmpProfile.from_device(device),
            method=self.method_combo.currentText(),
            oid=self.oid_input.text().strip(),
            max_repetitions=self.max_repetitions.value(),
            max_rows=self.max_rows.value(),
            save_history=self.save_history.isChecked(),
            device_id=str(device.device_uuid or device.id),
            device_name=device.name,
        )
        self.worker = SnmpQueryWorker(self.center.paths.site_snmp_db_path(self.center.site_name), request, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished_with_result.connect(self._query_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def run_set(self, device: Device) -> None:
        oid = self.oid_input.text().strip()
        data = self.center.browser_page._resolve_result_oid(oid) if oid else {}
        if data and int(data.get("is_scalar") or 0) and oid == str(data.get("oid") or ""):
            oid = f"{oid}.0"
        allowed, reason = can_set_mib_object(data, oid)
        if not allowed and str(data.get("name") or "") != oid:
            MessageBox.information(self, "SNMP Set", reason)
            return
        dialog = SnmpSetDialog(
            oid=oid,
            object_name=str(data.get("name") or ""),
            access=str(data.get("access") or ""),
            syntax=str(data.get("syntax") or ""),
            description=str(data.get("description") or ""),
            enum_map_json=str(data.get("enum_map_json") or ""),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.result_data()
        confirm = MessageBox(self)
        confirm.setIcon(MessageBox.Warning)
        confirm.setWindowTitle("确认执行 SNMP Set")
        confirm.setText(
            "\n".join(
                [
                    "确认执行 SNMP Set：",
                    "",
                    f"设备：{device.name} / {device.primary_address}",
                    f"OID：{values.oid}",
                    f"对象：{data.get('name') or '未识别'}",
                    f"类型：{values.data_type}",
                    f"新值：{values.value}",
                    "",
                    "该操作会修改设备运行状态。确认继续？",
                ]
            )
        )
        confirm.setStandardButtons(MessageBox.Cancel | MessageBox.Yes)
        confirm.button(MessageBox.Yes).setText("确认执行")
        confirm.button(MessageBox.Cancel).setText("取消")
        if confirm.exec() != MessageBox.Yes:
            return
        request = SnmpSetRequest(
            profile=SnmpProfile.from_device(device),
            oid=values.oid,
            data_type=values.data_type,
            value=values.value,
            device_id=str(device.device_uuid or device.id),
            device_name=device.name,
            object_name=str(data.get("name") or ""),
            module_name=str(data.get("module_name") or ""),
            access=str(data.get("access") or ""),
        )
        self.set_worker = SnmpSetWorker(self.center.paths.site_snmp_db_path(self.center.site_name), request, self)
        self.set_worker.progress.connect(self.status.setText)
        self.set_worker.finished_with_result.connect(self._set_finished)
        self.set_worker.finished.connect(self.set_worker.deleteLater)
        self.set_worker.start()

    def _set_finished(self, result: object) -> None:
        self.set_worker = None
        if isinstance(result, Exception):
            self.status.setText(f"Set 执行失败：{result}")
            return
        if not isinstance(result, SnmpSetResult):
            self.status.setText("Set 执行失败：返回结果异常。")
            return
        self.status.setText(f"Set 完成：{result.status}；旧值：{result.old_value}；新值：{result.new_value}；验证值：{result.result_value}。{result.error_message}")

    def cancel_query(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.status.setText("正在取消查询...")

    def _query_finished(self, result: object) -> None:
        self.worker = None
        if isinstance(result, Exception):
            self.status.setText(f"查询失败：{result}")
            return
        if not isinstance(result, SnmpQueryResult):
            self.status.setText("查询失败：返回结果异常。")
            return
        self.last_result = result
        self.status.setText(f"查询完成：状态 {result.status}，返回 {len(result.rows)} 条，耗时 {result.elapsed_ms} ms。{result.error_message}")
        rows = [
            [result.request.started_at, result.request.device_name, row.oid, row.name, row.instance, row.value_type, row.value, row.decoded_value, row.latency_ms, row.status, row.error_message]
            for row in result.rows
        ]
        self.model.set_rows(self.model.headers, rows)

    def export_result(self) -> None:
        if self.last_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 SNMP 查询结果", str(Path.home() / "snmp_query.xlsx"), "Excel (*.xlsx);;CSV (*.csv);;JSON (*.json)")
        if not path:
            return
        result_file = _write_snmp_result_cache(self.center.paths, self.last_result, "snmp_query")
        submit_export_task(
            self,
            snmp_query_result_spec(path, result_file=result_file, title="导出 SNMP 查询结果", open_dir_on_success=True),
            success_title="SNMP 查询工具",
            paths=self.center.paths,
        )


class OidTemplatePage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.table = make_table(["范围", "名称", "模块", "对象", "OID", "方式"])
        refresh_button = snmp_action_button("刷新", "SYNC")
        add_button = snmp_action_button("手动新增全局模板", "ADD")
        refresh_button.clicked.connect(self.refresh)
        add_button.clicked.connect(self.add_template)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table, 1)

    def add_template(self) -> None:
        name, ok = InputDialog.getText(self, "新增模板", "模板名称")
        if not ok or not name.strip():
            return
        oid, ok = InputDialog.getText(self, "新增模板", "数字 OID")
        if ok and oid.strip():
            self.center.start_data_action(
                "create_template",
                {"name": name.strip(), "oid": oid.strip(), "method": "Get"},
                lambda _result: self.refresh(),
            )

    def refresh(self) -> None:
        self.center.start_data_refresh("templates", self._apply_rows)

    def _apply_rows(self, result: dict[str, object]) -> None:
        rows = []
        for item in result.get("global_rows") or []:
            if not isinstance(item, dict):
                continue
            rows.append(["全局", item.get("template_name"), item.get("module_name"), item.get("object_name"), item.get("numeric_oid"), item.get("query_method")])
        for item in result.get("site_rows") or []:
            if not isinstance(item, dict):
                continue
            rows.append(["局点", item.get("template_name"), item.get("module_name"), item.get("object_name"), item.get("numeric_oid"), item.get("query_method")])
        fill_table(self.table, rows)


class SnmpMonitorPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.table = make_table(["任务", "设备", "模板", "间隔", "启用", "状态"])
        self.note = QLabel("周期监控任务已预留数据结构。第一阶段建议先通过 SNMP 查询和 OID 模板验证对象，再创建周期采集。")
        refresh_button = snmp_action_button("刷新", "SYNC")
        refresh_button.clicked.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addWidget(self.note)
        layout.addWidget(refresh_button)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.center.start_data_refresh("monitor_jobs", self._apply_rows)

    def _apply_rows(self, result: dict[str, object]) -> None:
        fill_table(self.table, [[row.get("job_name"), row.get("device_id"), row.get("template_id"), row.get("interval_seconds"), yes_no(row.get("enabled")), row.get("status")] for row in result.get("rows") or [] if isinstance(row, dict)])


class SnmpTrapPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.table = make_table(["时间", "来源IP", "来源设备", "Trap OID", "名称", "级别", "内容"])
        self.note = QLabel("Trap Receiver 默认建议端口 1162；Windows 下监听 162 可能需要管理员权限。")
        refresh_button = snmp_action_button("刷新 Trap", "SYNC")
        refresh_button.clicked.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addWidget(self.note)
        layout.addWidget(refresh_button)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.center.start_data_refresh("traps", self._apply_rows)

    def _apply_rows(self, result: dict[str, object]) -> None:
        fill_table(self.table, [[row.get("trap_time"), row.get("source_ip"), row.get("source_device"), row.get("trap_oid"), row.get("trap_name"), row.get("severity"), row.get("content")] for row in result.get("rows") or [] if isinstance(row, dict)])


class TopologyPage(QWidget):
    def __init__(self, center: SnmpCenterPage) -> None:
        super().__init__()
        self.center = center
        self.worker: TopologyDiscoveryWorker | None = None
        self.node_table = make_table(["节点", "类型", "地址", "UUID"])
        self.edge_table = make_table(["本端", "对端", "类型", "本端接口", "对端接口", "来源", "可信度"])
        discover_button = snmp_action_button("发现拓扑", "SEARCH")
        refresh_button = snmp_action_button("刷新", "SYNC")
        discover_button.clicked.connect(self.discover)
        refresh_button.clicked.connect(self.refresh)
        buttons = QHBoxLayout()
        buttons.addWidget(discover_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch(1)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(titled_box("节点", self.node_table))
        splitter.addWidget(titled_box("链路", self.edge_table))
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(splitter, 1)

    def discover(self) -> None:
        self.worker = TopologyDiscoveryWorker(
            self.center.paths.site_db_path(self.center.site_name),
            self.center.paths.site_snmp_db_path(self.center.site_name),
            self,
        )
        self.worker.finished_with_result.connect(self._discovery_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _discovery_finished(self, result: object) -> None:
        self.worker = None
        if isinstance(result, Exception):
            MessageBox.warning(self, "拓扑发现", str(result))
            return
        self.refresh()

    def refresh(self) -> None:
        self.center.start_data_refresh("topology", self._apply_rows)

    def _apply_rows(self, result: dict[str, object]) -> None:
        fill_table(self.node_table, [[row.get("name"), row.get("node_type"), row.get("address"), row.get("device_uuid")] for row in result.get("nodes") or [] if isinstance(row, dict)])
        fill_table(self.edge_table, [[row.get("source_id"), row.get("target_id"), row.get("edge_type"), row.get("local_interface"), row.get("remote_interface"), row.get("discovery_source"), row.get("confidence")] for row in result.get("edges") or [] if isinstance(row, dict)])


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setAlternatingRowColors(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    table.horizontalHeader().setStretchLastSection(False)
    return table


def fill_table(table: QTableWidget, rows: list[list[Any]]) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            item = QTableWidgetItem("" if value is None else str(value))
            item.setToolTip(item.text())
            table.setItem(row_index, column, item)
    auto_fit_table_columns(table, max_rows=200, default_min_width=90, default_max_width=520)


def _compare_table_row(row: dict[str, object]) -> list[Any]:
    return [
        row.get("item_type") or "",
        row.get("diff_type") or "",
        row.get("module_name") or "",
        row.get("mib_file_name") or "",
        row.get("object_name") or "",
        row.get("numeric_oid") or "",
        row.get("field_name") or "",
        row.get("left_value") or "",
        row.get("right_value") or "",
        row.get("summary") or "",
    ]


def titled_box(title: str, widget: QWidget) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.addWidget(widget)
    return box


def configure_table_view(table: QTableView, width_by_header: dict[str, int] | None = None) -> None:
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    if width_by_header:
        for column in range(table.model().columnCount() if table.model() is not None else 0):
            header_text = str(table.model().headerData(column, Qt.Horizontal) or "")
            if header_text in width_by_header:
                table.setColumnWidth(column, int(width_by_header[header_text]))


def auto_resize_table_view_columns(table: QTableView, width_by_header: dict[str, int] | None = None) -> None:
    configure_table_view(table, width_by_header)
    if table.model() is None:
        return
    for column in range(table.model().columnCount()):
        header = str(table.model().headerData(column, Qt.Horizontal) or "")
        minimum = int((width_by_header or {}).get(header, 90))
        header_width = table.horizontalHeader().fontMetrics().horizontalAdvance(header) + 32
        table.setColumnWidth(column, min(max(minimum, header_width), 520))


def configure_tree_widget(tree: QTreeWidget, width_by_column: dict[int, int] | None = None) -> None:
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    tree.setTextElideMode(Qt.TextElideMode.ElideRight)
    header = tree.header()
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    for column, width in (width_by_column or {}).items():
        tree.setColumnWidth(int(column), int(width))


def auto_resize_tree_columns(tree: QTreeWidget, minimums: dict[int, int] | None = None, maximum: int = 520) -> None:
    configure_tree_widget(tree, minimums)
    for column in range(tree.columnCount()):
        tree.resizeColumnToContents(column)
        minimum = int((minimums or {}).get(column, 90))
        tree.setColumnWidth(column, max(minimum, min(tree.columnWidth(column), maximum)))


def status_label(status: object) -> str:
    text = str(status or "")
    return SNMP_STATUS_LABELS.get(text, {"error": "失败", "failed": "失败", "cancelled": "已取消"}.get(text.lower(), text or "-"))


def compact_error_message(message: object) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    return text.splitlines()[0][:160]


def yes_no(value: object) -> str:
    return "是" if bool(value) else "否"


def module_display_name(row: dict[str, object]) -> str:
    module = str(row.get("module_name") or "未归属")
    version = str(row.get("version_line") or "")
    package_version = str(row.get("package_version") or "")
    if version or package_version:
        return f"{module} [H3C {version or '用户导入'} / {package_version or '-'}]"
    if row.get("file_id") is None:
        return f"{module} [内置通用]"
    return module


def mib_node_type(row: dict[str, object]) -> str:
    if int(row.get("is_trap") or 0):
        return "trap"
    if int(row.get("is_notification") or 0):
        return "notification"
    if str(row.get("match_status") or "") == "product_reference_only":
        return "product_reference_only"
    if int(row.get("is_table") or 0):
        return "table"
    if int(row.get("is_table_entry") or 0):
        return "entry"
    if int(row.get("is_column") or 0):
        return "column"
    if int(row.get("is_scalar") or 0):
        return "scalar"
    return "object_identifier"


def source_filter_key(label: str) -> str:
    return {
        "标准 MIB 库": "standard",
        "H3C V5 MIB 库": "h3c_v5",
        "H3C V7/V9 MIB 库": "h3c_v7v9",
        "当前设备启用字典": "current_device",
        "标准 MIB": "standard",
        "H3C 通用": "h3c_common",
        "H3C 无线控制器": "h3c_wireless",
        "H3C V5": "h3c_v5",
        "H3C V7/V9": "h3c_v7v9",
        "内置通用": "builtin_common",
        "导入 MIB": "user_import",
        "用户导入": "user_import",
    }.get(label, "")


def method_to_operation(method: str) -> str:
    return {
        "GetNext": "Get Next",
        "GetBulk": "Get Bulk",
        "GetSubtree": "Get Subtree",
        "BulkWalk": "Bulk Walk",
        "TableWalk": "Table Walk",
        "Table Walk": "Table Walk",
    }.get(method, method)


def operation_to_method(operation: str) -> str:
    return {"Get Next": "GetNext", "Get Bulk": "GetBulk", "Get Subtree": "GetSubtree", "Bulk Walk": "BulkWalk", "Table Walk": "TableWalk"}.get(operation, operation)


def normalize_h3c_module_display_name(value: object) -> str:
    text = str(value or "").strip()
    match = re.match(r"^\s*\d{1,3}\s*[-_－–—]\s*(HH3C-.+?MIB)\s*$", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def normalize_tree_oid(value: object) -> str:
    text = str(value or "").strip().strip(".")
    text = text.replace(" ", "")
    if not text or not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return ""
    if text.split(".", 1)[0] == "0":
        return ""
    return text


def can_set_mib_object(item: dict[str, object], oid: str) -> tuple[bool, str]:
    if not item:
        return False, "当前 OID 未匹配到 MIB 定义，无法确认是否可写。"
    access = str(item.get("access") or "").lower()
    if int(item.get("is_trap") or 0) or int(item.get("is_notification") or 0):
        return False, "Trap / Notification 对象不能执行 Set。"
    if int(item.get("is_table") or 0) or int(item.get("is_table_entry") or 0):
        return False, "Table / Entry 节点本身不能执行 Set，只允许具体 column 实例。"
    if not access or access not in {"read-write", "read-create", "write-only"}:
        return False, f"当前对象访问权限为 {item.get('access') or '未知'}，不能执行 Set。"
    base_oid = str(item.get("oid") or "")
    if int(item.get("is_column") or 0) and (not oid or oid == base_oid):
        return False, "当前对象是表字段，需要选择具体实例后才能 Set。请先 Walk 该字段，再在结果表右键 Set。"
    return True, "允许 Set。"


def oid_label(oid: str) -> str:
    return {
        "1": "iso",
        "1.3": "org",
        "1.3.6": "dod",
        "1.3.6.1": "internet",
        "1.3.6.1.1": "directory",
        "1.3.6.1.2": "mgmt",
        "1.3.6.1.2.1": "mib-2",
        "1.3.6.1.2.1.1": "system",
        "1.3.6.1.2.1.2": "interfaces",
        "1.3.6.1.2.1.3": "at",
        "1.3.6.1.2.1.4": "ip",
        "1.3.6.1.2.1.5": "icmp",
        "1.3.6.1.2.1.6": "tcp",
        "1.3.6.1.2.1.7": "udp",
        "1.3.6.1.2.1.8": "egp",
        "1.3.6.1.2.1.10": "transmission",
        "1.3.6.1.2.1.11": "snmp",
        "1.3.6.1.2.1.25": "host",
        "1.3.6.1.3": "experimental",
        "1.3.6.1.4": "private",
        "1.3.6.1.4.1": "enterprises",
        "1.3.6.1.4.1.25506": "h3c",
        "1.3.6.1.4.1.25506.2": "hh3cCommon",
        "1.3.6.1.4.1.25506.2.75": "hh3cDot11",
    }.get(oid, oid.rsplit(".", 1)[-1])


def mib_tooltip(item: dict[str, object]) -> str:
    return "\n".join(
        [
            f"名称：{item.get('name') or ''}",
            f"OID：{item.get('oid') or ''}",
            f"模块：{item.get('module_name') or ''}",
            f"类型：{item.get('syntax') or ''}",
            f"Access：{item.get('access') or ''}",
            f"来源：{module_display_name(item)}",
        ]
    )


def instance_suffix(oid: str, base_oid: str) -> str:
    if not base_oid or oid == base_oid:
        return ""
    prefix = f"{base_oid}."
    return oid[len(prefix) :] if oid.startswith(prefix) else ""


def decode_octet_string_instance(instance: str) -> str:
    if not instance:
        return ""
    try:
        numbers = [int(part) for part in instance.split(".") if part]
    except ValueError:
        return ""
    if len(numbers) >= 2 and 0 <= numbers[0] <= 255 and len(numbers) >= numbers[0] + 1:
        payload = numbers[1 : 1 + numbers[0]]
    else:
        payload = numbers
    if not payload or any(value < 32 or value > 126 for value in payload):
        return ""
    return "".join(chr(value) for value in payload)
