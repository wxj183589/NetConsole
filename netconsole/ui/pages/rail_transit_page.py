from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.car_network_diagnostic_page import CarNetworkDiagnosticPage
from netconsole.ui.pages.mesh_log_analysis_page import MeshLogAnalysisPage
from netconsole.ui.pages.trackside_ap_service_page import TracksideApServicePage
from netconsole.ui.pages.vehicle_mr_online_page import VehicleMrOnlinePage


ONLINE_MR_COLLECTION_TAB_INDEX = 4


class RailTransitPage(QWidget):
    def __init__(self, repository: DeviceRepository, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.tabs = QTabWidget()
        self.vehicle_mr_online_page = VehicleMrOnlinePage(repository, i18n, site_name, paths)
        self.car_network_page = CarNetworkDiagnosticPage(repository, i18n, site_name, paths)
        self.trackside_page = TracksideApServicePage(repository, i18n, site_name, paths)
        self.mesh_page = MeshLogAnalysisPage(repository, i18n, site_name, paths)
        self.online_mr_page = None
        self.online_mr_placeholder = QWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.addTab(self.vehicle_mr_online_page, "")
        self.tabs.addTab(self.car_network_page, "")
        self.tabs.addTab(self.trackside_page, "")
        self.tabs.addTab(self.mesh_page, "")
        self.tabs.addTab(self.online_mr_placeholder, "")
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.retranslate()

    def refresh_all(self) -> None:
        self.refresh_current_async_or_lazy()

    def refresh_current_async_or_lazy(self, force_if_empty: bool = False) -> None:
        if self.tabs.currentWidget() is self.vehicle_mr_online_page:
            self.vehicle_mr_online_page.refresh_all()
        elif self.tabs.currentWidget() is self.car_network_page:
            self.car_network_page.refresh_all()
        elif self.tabs.currentWidget() is self.trackside_page:
            force = force_if_empty and (
                not self.trackside_page.has_loaded
                or self.trackside_page.dirty
                or not self.trackside_page.trackside_rows
            )
            self.trackside_page.refresh_async(force=force)
        elif self.tabs.currentIndex() == ONLINE_MR_COLLECTION_TAB_INDEX:
            self._ensure_online_mr_page()
            if self.online_mr_page is not None:
                first_show_refresh = getattr(self.online_mr_page, "first_show_refresh", None)
                if callable(first_show_refresh):
                    first_show_refresh()
                else:
                    self.online_mr_page.refresh_all()
        else:
            self.mesh_page.refresh_all()

    def on_tab_changed(self, index: int) -> None:
        if index == ONLINE_MR_COLLECTION_TAB_INDEX:
            self._ensure_online_mr_page()
        self.refresh_current_async_or_lazy()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.site_name = site_name
        self.vehicle_mr_online_page.set_repository(repository, site_name)
        self.car_network_page.set_repository(repository, site_name)
        self.trackside_page.set_repository(repository, site_name)
        self.mesh_page.set_repository(repository, site_name)
        if self.online_mr_page is not None:
            self.online_mr_page.set_repository(repository, site_name)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.vehicle_mr_online_page.set_site(site_name)
        self.car_network_page.set_site(site_name)
        self.trackside_page.set_site(site_name)
        self.mesh_page.set_site(site_name)
        if self.online_mr_page is not None:
            self.online_mr_page.set_site(site_name)

    def retranslate(self) -> None:
        self.tabs.setTabText(0, "列车在线情况")
        self.tabs.setTabText(1, "车内通信检测")
        self.tabs.setTabText(2, self.i18n.t("rail_transit.trackside_ap_service"))
        self.tabs.setTabText(3, self.i18n.t("mesh_analysis.title"))
        self.tabs.setTabText(ONLINE_MR_COLLECTION_TAB_INDEX, self.i18n.t("rail_transit.online_mr_collection"))
        self.vehicle_mr_online_page.retranslate()
        self.car_network_page.retranslate()
        self.trackside_page.retranslate()
        self.mesh_page.retranslate()
        if self.online_mr_page is not None:
            self.online_mr_page.retranslate()

    def restyle_visible_link_rows(self) -> None:
        self.mesh_page.restyle_visible_link_rows()

    def refresh_groups(self) -> None:
        if self.online_mr_page is not None:
            self.online_mr_page.refresh_all(defer_heavy=True)

    def mark_devices_changed(self) -> None:
        self.vehicle_mr_online_page.refresh_all()
        self.car_network_page.refresh_all()
        self.trackside_page.dirty = True
        if self.tabs.currentWidget() is self.trackside_page:
            self.trackside_page.refresh_async(force=False)
        self.mesh_page.refresh_all()
        if self.online_mr_page is not None and self.tabs.currentWidget() is self.online_mr_page:
            self.online_mr_page.refresh_all(defer_heavy=True)

    def _ensure_online_mr_page(self) -> None:
        if self.online_mr_page is not None:
            return
        from netconsole.ui.pages.online_mr_collection_page import OnlineMrCollectionPage

        self.online_mr_page = OnlineMrCollectionPage(self.repository, self.i18n, self.site_name, self.paths)
        self.tabs.blockSignals(True)
        try:
            self.tabs.removeTab(ONLINE_MR_COLLECTION_TAB_INDEX)
            self.tabs.insertTab(ONLINE_MR_COLLECTION_TAB_INDEX, self.online_mr_page, self.i18n.t("rail_transit.online_mr_collection"))
            self.tabs.setCurrentIndex(ONLINE_MR_COLLECTION_TAB_INDEX)
        finally:
            self.tabs.blockSignals(False)
