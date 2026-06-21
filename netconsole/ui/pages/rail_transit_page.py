from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.mesh_log_analysis_page import MeshLogAnalysisPage
from netconsole.ui.pages.online_mr_collection_page import OnlineMrCollectionPage
from netconsole.ui.pages.trackside_ap_service_page import TracksideApServicePage


class RailTransitPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.tabs = QTabWidget()
        self.trackside_page = TracksideApServicePage(repository, i18n, site_name, paths)
        self.mesh_page = MeshLogAnalysisPage(i18n, site_name, paths)
        self.online_mr_page = OnlineMrCollectionPage(repository, i18n, site_name, paths)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.addTab(self.trackside_page, "")
        self.tabs.addTab(self.mesh_page, "")
        self.tabs.addTab(self.online_mr_page, "")
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.retranslate()

    def refresh_all(self) -> None:
        self.refresh_current_async_or_lazy()

    def refresh_current_async_or_lazy(self, force_if_empty: bool = False) -> None:
        if self.tabs.currentWidget() is self.trackside_page:
            force = force_if_empty and (
                not self.trackside_page.has_loaded
                or self.trackside_page.dirty
                or not self.trackside_page.trackside_rows
            )
            self.trackside_page.refresh_async(force=force)
        elif self.tabs.currentWidget() is self.online_mr_page:
            self.online_mr_page.refresh_all()
        else:
            self.mesh_page.refresh_all()

    def on_tab_changed(self, _index: int) -> None:
        self.refresh_current_async_or_lazy()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.trackside_page.set_repository(repository, site_name)
        self.mesh_page.set_site(site_name)
        self.online_mr_page.set_repository(repository, site_name)

    def set_site(self, site_name: str) -> None:
        self.trackside_page.set_site(site_name)
        self.mesh_page.set_site(site_name)
        self.online_mr_page.set_site(site_name)

    def retranslate(self) -> None:
        self.tabs.setTabText(0, self.i18n.t("rail_transit.trackside_ap_service"))
        self.tabs.setTabText(1, self.i18n.t("mesh_analysis.title"))
        self.tabs.setTabText(2, self.i18n.t("rail_transit.online_mr_collection"))
        self.trackside_page.retranslate()
        self.mesh_page.retranslate()
        self.online_mr_page.retranslate()

    def restyle_visible_link_rows(self) -> None:
        self.mesh_page.restyle_visible_link_rows()
