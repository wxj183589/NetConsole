from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.pages.iperf_bandwidth_page import IperfBandwidthPage


class NetworkToolsPage(QWidget):
    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.tabs = QTabWidget()
        self.iperf_page = IperfBandwidthPage(i18n, site_name, paths)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.addTab(self.iperf_page, "")
        self.retranslate()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.iperf_page.set_site(site_name)

    def refresh_all(self) -> None:
        self.iperf_page.refresh_tool_status()

    def retranslate(self) -> None:
        self.tabs.setTabText(0, self.i18n.t("network_tools.iperf"))
        self.iperf_page.retranslate()
