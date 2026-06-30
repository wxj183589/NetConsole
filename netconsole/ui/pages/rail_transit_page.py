from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.car_network_diagnostic_page import CarNetworkDiagnosticPage
from netconsole.ui.pages.mesh_log_analysis_page import MeshLogAnalysisPage
from netconsole.ui.pages.trackside_ap_service_page import TracksideApServicePage
from netconsole.ui.pages.vehicle_mr_online_page import VehicleMrOnlinePage


class RailTransitPage(QWidget):
    def __init__(
        self,
        repository: DeviceRepository,
        i18n: I18n,
        site_name: str,
        paths: PathResolver,
        feature_gate: FeatureGate | None = None,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.feature_gate = feature_gate or default_feature_gate()
        self.tabs = QTabWidget()
        self.tab_by_feature_id: dict[str, QWidget] = {}
        self.feature_by_tab: dict[QWidget, str] = {}
        self.vehicle_mr_online_page = None
        self.car_network_page = None
        self.trackside_page = None
        self.mesh_page = None
        self.online_mr_page = None
        self.online_mr_analysis_page = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self._add_feature_tab("rail.train_online", lambda: VehicleMrOnlinePage(repository, i18n, site_name, paths))
        self._add_feature_tab("rail.car_network_diagnostic", lambda: CarNetworkDiagnosticPage(repository, i18n, site_name, paths))
        self._add_feature_tab("rail.trackside_ap_business", lambda: TracksideApServicePage(repository, i18n, site_name, paths))
        self._add_feature_tab("rail.raw_mesh_log_analysis", lambda: MeshLogAnalysisPage(repository, i18n, site_name, paths))
        self._add_feature_tab("rail.online_mr_collection", QWidget, lazy=True)
        self._add_feature_tab("rail.online_mr_analysis", QWidget, lazy=True)
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.retranslate()

    def refresh_all(self) -> None:
        self.refresh_current_async_or_lazy()

    def refresh_current_async_or_lazy(self, force_if_empty: bool = False) -> None:
        widget = self.tabs.currentWidget()
        feature_id = self.feature_by_tab.get(widget)
        if feature_id and not self.feature_gate.is_enabled(feature_id):
            return
        if widget is self.vehicle_mr_online_page and self.vehicle_mr_online_page is not None:
            self.vehicle_mr_online_page.refresh_all()
        elif widget is self.car_network_page and self.car_network_page is not None:
            self.car_network_page.refresh_all()
        elif widget is self.trackside_page and self.trackside_page is not None:
            force = force_if_empty and (
                not self.trackside_page.has_loaded
                or self.trackside_page.dirty
                or not self.trackside_page.trackside_rows
            )
            self.trackside_page.refresh_async(force=force)
        elif feature_id == "rail.online_mr_collection":
            self._ensure_online_mr_page()
            if self.online_mr_page is not None:
                first_show_refresh = getattr(self.online_mr_page, "first_show_refresh", None)
                if callable(first_show_refresh):
                    first_show_refresh()
                else:
                    self.online_mr_page.refresh_all()
        elif feature_id == "rail.online_mr_analysis":
            self._ensure_online_mr_analysis_page()
            if self.online_mr_analysis_page is not None:
                first_show_refresh = getattr(self.online_mr_analysis_page, "first_show_refresh", None)
                if callable(first_show_refresh):
                    first_show_refresh()
                else:
                    self.online_mr_analysis_page.refresh_all()
        elif self.mesh_page is not None:
            self.mesh_page.refresh_all()

    def on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        feature_id = self.feature_by_tab.get(widget)
        if feature_id == "rail.online_mr_collection":
            self._ensure_online_mr_page()
        elif feature_id == "rail.online_mr_analysis":
            self._ensure_online_mr_analysis_page()
        self.refresh_current_async_or_lazy()

    def set_repository(self, repository: DeviceRepository, site_name: str) -> None:
        self.repository = repository
        self.site_name = site_name
        self._call_visible_pages("set_repository", repository, site_name)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self._call_visible_pages("set_site", site_name)

    def retranslate(self) -> None:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            feature_id = self.feature_by_tab.get(widget, "")
            item = self.feature_gate.visible_children("module.rail_transit")
            title_key = next((feature.title_key for feature in item if feature.feature_id == feature_id), feature_id)
            self.tabs.setTabText(index, self.i18n.t(title_key))
        self._call_visible_pages("retranslate")

    def restyle_visible_link_rows(self) -> None:
        if self.mesh_page is not None:
            self.mesh_page.restyle_visible_link_rows()

    def refresh_groups(self) -> None:
        if self.online_mr_page is not None:
            self.online_mr_page.refresh_all(defer_heavy=True)
        if self.online_mr_analysis_page is not None:
            self.online_mr_analysis_page.refresh_all(defer_heavy=True)

    def mark_devices_changed(self) -> None:
        if self.vehicle_mr_online_page is not None:
            self.vehicle_mr_online_page.refresh_all()
        if self.car_network_page is not None:
            self.car_network_page.refresh_all()
        if self.trackside_page is not None:
            self.trackside_page.dirty = True
        if self.trackside_page is not None and self.tabs.currentWidget() is self.trackside_page:
            self.trackside_page.refresh_async(force=False)
        if self.mesh_page is not None:
            self.mesh_page.refresh_all()
        if self.online_mr_page is not None and self.tabs.currentWidget() is self.online_mr_page:
            self.online_mr_page.refresh_all(defer_heavy=True)
        if self.online_mr_analysis_page is not None:
            self.online_mr_analysis_page.refresh_all(defer_heavy=True)

    def _ensure_online_mr_page(self) -> None:
        self.feature_gate.assert_enabled("rail.online_mr_collection")
        if self.online_mr_page is not None:
            return
        from netconsole.ui.pages.online_mr_collection_page import OnlineMrCollectionPage

        self.online_mr_page = OnlineMrCollectionPage(self.repository, self.i18n, self.site_name, self.paths, feature_gate=self.feature_gate)
        self.online_mr_page.session_history_changed.connect(self._refresh_online_mr_analysis_history)
        self._replace_feature_tab("rail.online_mr_collection", self.online_mr_page)

    def _ensure_online_mr_analysis_page(self) -> None:
        self.feature_gate.assert_enabled("rail.online_mr_analysis")
        if self.online_mr_analysis_page is not None:
            return
        from netconsole.ui.pages.online_mr_collection_analysis_page import OnlineMrCollectionAnalysisPage

        self.online_mr_analysis_page = OnlineMrCollectionAnalysisPage(self.repository, self.i18n, self.site_name, self.paths)
        self._replace_feature_tab("rail.online_mr_analysis", self.online_mr_analysis_page)

    def _refresh_online_mr_analysis_history(self) -> None:
        if self.online_mr_analysis_page is not None:
            self.online_mr_analysis_page.refresh_all(defer_heavy=True)

    def _add_feature_tab(self, feature_id: str, factory, *, lazy: bool = False) -> None:
        if not self.feature_gate.is_visible(feature_id):
            return
        widget = QWidget() if lazy else factory()
        if feature_id == "rail.train_online":
            self.vehicle_mr_online_page = widget
        elif feature_id == "rail.car_network_diagnostic":
            self.car_network_page = widget
        elif feature_id == "rail.trackside_ap_business":
            self.trackside_page = widget
        elif feature_id == "rail.raw_mesh_log_analysis":
            self.mesh_page = widget
        self.tab_by_feature_id[feature_id] = widget
        self.feature_by_tab[widget] = feature_id
        self.tabs.addTab(widget, "")
        self.tabs.setTabEnabled(self.tabs.indexOf(widget), self.feature_gate.is_enabled(feature_id))

    def _replace_feature_tab(self, feature_id: str, page: QWidget) -> None:
        placeholder = self.tab_by_feature_id.get(feature_id)
        index = self.tabs.indexOf(placeholder) if placeholder is not None else -1
        if index < 0:
            return
        title = self.tabs.tabText(index)
        self.tabs.blockSignals(True)
        try:
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, page, title)
            self.tabs.setCurrentIndex(index)
            self.tab_by_feature_id[feature_id] = page
            self.feature_by_tab.pop(placeholder, None)
            self.feature_by_tab[page] = feature_id
        finally:
            self.tabs.blockSignals(False)

    def _call_visible_pages(self, method_name: str, *args) -> None:
        for page in list(self.tab_by_feature_id.values()):
            method = getattr(page, method_name, None)
            if callable(method):
                method(*args)
