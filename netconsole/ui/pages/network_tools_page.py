from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.pages.iperf_bandwidth_page import IperfBandwidthPage
from netconsole.ui.pages.network_adapter_route_page import NetworkAdapterRoutePage
from netconsole.ui.pages.network_toolbox_page import NetworkToolboxPage
from netconsole.ui.pages.wireless_scan_page import WirelessScanPage


class NetworkToolsPage(QWidget):
    TAB_DEFINITIONS = (
        ("network_tools.iperf", None, "iperf_page"),
        ("network_tools.wireless_scan", None, "wireless_scan_page"),
        ("network_tools.local_network_manager", None, "network_manager_page"),
        ("network_tools.toolbox", "network_tools.toolbox", "toolbox_page"),
    )

    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver, feature_gate: FeatureGate | None = None) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.feature_gate = feature_gate or default_feature_gate()
        self.tabs = QTabWidget()
        self.iperf_page = IperfBandwidthPage(i18n, site_name, paths)
        self.wireless_scan_page = WirelessScanPage(i18n, site_name, paths)
        self.network_manager_page = NetworkAdapterRoutePage(i18n, paths)
        self.toolbox_page = NetworkToolboxPage(i18n, site_name, paths)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self._apply_feature_gate()
        self.retranslate()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.iperf_page.set_site(site_name)
        self.wireless_scan_page.set_site(site_name)
        self.toolbox_page.set_site(site_name)

    def refresh_all(self) -> None:
        self.iperf_page.refresh_tool_status()
        self.wireless_scan_page.load_adapters()
        self.network_manager_page.refresh_all()

    def retranslate(self) -> None:
        self._apply_feature_gate()
        self.iperf_page.retranslate()
        self.wireless_scan_page.retranslate()
        self.network_manager_page.retranslate()
        self.toolbox_page.retranslate()

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
