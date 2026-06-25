from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.pages.iperf_bandwidth_page import IperfBandwidthPage
from netconsole.ui.pages.network_adapter_route_page import NetworkAdapterRoutePage
from netconsole.ui.pages.wireless_scan_page import WirelessScanPage


class NetworkToolsPage(QWidget):
    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.tabs = QTabWidget()
        self.iperf_page = IperfBandwidthPage(i18n, site_name, paths)
        self.wireless_scan_page = WirelessScanPage(i18n, site_name, paths)
        self.network_manager_page = NetworkAdapterRoutePage(i18n, paths)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.addTab(self.iperf_page, "")
        self.tabs.addTab(self.wireless_scan_page, "")
        self.tabs.addTab(self.network_manager_page, "")
        self.retranslate()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.iperf_page.set_site(site_name)
        self.wireless_scan_page.set_site(site_name)

    def refresh_all(self) -> None:
        self.iperf_page.refresh_tool_status()
        self.wireless_scan_page.load_adapters()
        self.network_manager_page.refresh_all()

    def retranslate(self) -> None:
        self.tabs.setTabText(0, self.i18n.t("network_tools.iperf"))
        self.tabs.setTabText(1, self.i18n.t("network_tools.wireless_scan"))
        self.tabs.setTabText(2, self.i18n.t("network_tools.local_network_manager"))
        self.iperf_page.retranslate()
        self.wireless_scan_page.retranslate()
        self.network_manager_page.retranslate()
