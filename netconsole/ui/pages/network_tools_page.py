from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QTabWidget, QVBoxLayout, QWidget

from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.pages.iperf_bandwidth_page import IperfBandwidthPage
from netconsole.ui.pages.network_toolbox_page import NetworkToolboxPage
from netconsole.ui.pages.wireless_scan_page import WirelessScanPage
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool


class NetworkToolsInitWorker(QThread):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths

    def run(self) -> None:
        try:
            tool = find_iperf_tool(self.paths)
            status = detect_iperf_version(tool) if tool is not None else None
            self.completed.emit(tool, status)
        except Exception as exc:
            self.failed.emit(str(exc))


class NetworkToolsPage(QWidget):
    TAB_DEFINITIONS = (
        ("network_tools.iperf", None, "iperf_page"),
        ("network_tools.wireless_scan", None, "wireless_scan_page"),
        ("network_tools.toolbox", "network_tools.toolbox", "toolbox_page"),
    )

    def __init__(
        self,
        i18n: I18n,
        site_name: str,
        paths: PathResolver,
        feature_gate: FeatureGate | None = None,
        *,
        open_external_tools_settings_callback=None,
    ) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.feature_gate = feature_gate or default_feature_gate()
        self.tabs = QTabWidget()
        self.iperf_page = IperfBandwidthPage(i18n, site_name, paths)
        self.wireless_scan_page = WirelessScanPage(i18n, site_name, paths)
        self.toolbox_page = NetworkToolboxPage(
            i18n,
            site_name,
            paths,
            feature_gate=self.feature_gate,
            open_external_tools_settings_callback=open_external_tools_settings_callback,
        )
        self.loading_label = QLabel("网络工具正在后台初始化...")
        self.loading_progress = QProgressBar()
        self.loading_progress.setRange(0, 0)
        self.loading_label.hide()
        self.loading_progress.hide()
        self.init_worker: NetworkToolsInitWorker | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.loading_label)
        layout.addWidget(self.loading_progress)
        layout.addWidget(self.tabs)
        self._apply_feature_gate()
        self.retranslate()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.iperf_page.set_site(site_name)
        self.wireless_scan_page.set_site(site_name)
        self.toolbox_page.set_site(site_name)

    def refresh_all(self) -> None:
        if self.init_worker is not None and self.init_worker.isRunning():
            return
        self._set_loading(True, "网络工具正在后台初始化...")
        self.init_worker = NetworkToolsInitWorker(self.paths, self)
        self.init_worker.completed.connect(self._init_completed)
        self.init_worker.failed.connect(self._init_failed)
        self.init_worker.finished.connect(self._init_finished)
        self.init_worker.start()
        self.wireless_scan_page.load_adapters()

    def retranslate(self) -> None:
        self._apply_feature_gate()
        self.iperf_page.retranslate()
        self.wireless_scan_page.retranslate()
        self.toolbox_page.retranslate()

    def _init_completed(self, tool: object, status: object) -> None:
        self.iperf_page.apply_tool_status(tool, status)
        self.loading_label.setText("网络工具初始化完成")

    def _init_failed(self, message: str) -> None:
        self.loading_label.setText(f"网络工具初始化失败：{message}")

    def _init_finished(self) -> None:
        worker = self.init_worker
        self.init_worker = None
        self._set_loading(False, self.loading_label.text())
        if worker is not None:
            worker.deleteLater()

    def _set_loading(self, loading: bool, message: str) -> None:
        self.loading_label.setText(message)
        self.loading_label.setVisible(True)
        self.loading_progress.setVisible(loading)
        self.tabs.setEnabled(not loading)

    def _apply_feature_gate(self) -> None:
        current = self.tabs.currentWidget()
        self.tabs.clear()
        for title_key, feature_id, attr in self.TAB_DEFINITIONS:
            if feature_id and not self.feature_gate.is_visible(feature_id):
                continue
            widget = getattr(self, attr)
            self.tabs.addTab(widget, self.i18n.t(title_key))
            if feature_id:
                self.tabs.setTabEnabled(self.tabs.count() - 1, self.feature_gate.is_enabled(feature_id))
        if current is not None:
            index = self.tabs.indexOf(current)
            if index >= 0:
                self.tabs.setCurrentIndex(index)
