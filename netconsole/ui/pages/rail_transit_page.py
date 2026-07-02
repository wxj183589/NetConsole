from __future__ import annotations

from time import perf_counter

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from netconsole.core import app_logger
from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.feature_registry import FEATURE_BY_ID
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository


RAIL_FEATURE_ORDER = (
    "rail.train_online",
    "rail.car_network_diagnostic",
    "rail.trackside_ap_business",
    "rail.raw_mesh_log_analysis",
    "rail.online_mr_collection",
    "rail.online_mr_analysis",
)


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
        self.feature_factories = {
            "rail.train_online": self._create_vehicle_mr_online_page,
            "rail.car_network_diagnostic": self._create_car_network_page,
            "rail.trackside_ap_business": self._create_trackside_page,
            "rail.raw_mesh_log_analysis": self._create_mesh_page,
            "rail.online_mr_collection": self._create_online_mr_page,
            "rail.online_mr_analysis": self._create_online_mr_analysis_page,
        }
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.reload_from_gate(refresh_current=False)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.retranslate()

    def refresh_all(self) -> None:
        self.refresh_current_async_or_lazy()

    def refresh_current_async_or_lazy(self, force_if_empty: bool = False) -> None:
        widget = self.tabs.currentWidget()
        feature_id = self.feature_by_tab.get(widget)
        if feature_id and not self.feature_gate.is_enabled(feature_id):
            return
        if feature_id:
            widget = self._ensure_feature_page(feature_id)
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
        elif feature_id == "rail.raw_mesh_log_analysis" and self.mesh_page is not None:
            first_show_refresh = getattr(self.mesh_page, "first_show_refresh", None)
            if callable(first_show_refresh):
                first_show_refresh()
            elif not getattr(self.mesh_page, "has_loaded", False):
                self.mesh_page.refresh_all()

    def on_tab_changed(self, index: int) -> None:
        start = perf_counter()
        widget = self.tabs.widget(index)
        feature_id = self.feature_by_tab.get(widget)
        if feature_id:
            self._ensure_feature_page(feature_id)
            self._log_page_profile(feature_id, "switch", start)
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
            self.tabs.setTabText(index, self._feature_title(feature_id))
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
        current = self.tabs.currentWidget()
        if self.vehicle_mr_online_page is not None and current is self.vehicle_mr_online_page:
            self.vehicle_mr_online_page.refresh_all()
        if self.car_network_page is not None and current is self.car_network_page:
            self.car_network_page.refresh_all()
        if self.trackside_page is not None:
            self.trackside_page.dirty = True
        if self.trackside_page is not None and current is self.trackside_page:
            self.trackside_page.refresh_async(force=False)
        if self.mesh_page is not None and current is self.mesh_page:
            self.mesh_page.refresh_all()
        if self.online_mr_page is not None and current is self.online_mr_page:
            self.online_mr_page.refresh_all(defer_heavy=True)
        if self.online_mr_analysis_page is not None and current is self.online_mr_analysis_page:
            self.online_mr_analysis_page.refresh_all(defer_heavy=True)

    def _ensure_online_mr_page(self) -> None:
        self._ensure_feature_page("rail.online_mr_collection")

    def _ensure_online_mr_analysis_page(self) -> None:
        self._ensure_feature_page("rail.online_mr_analysis")

    def _refresh_online_mr_analysis_history(self) -> None:
        if self.online_mr_analysis_page is not None:
            self.online_mr_analysis_page.refresh_all(defer_heavy=True)

    def _add_feature_tab(self, feature_id: str) -> None:
        if not self.feature_gate.is_visible(feature_id):
            return
        widget = self._widget_for_feature(feature_id)
        self.tab_by_feature_id[feature_id] = widget
        self.feature_by_tab[widget] = feature_id
        self.tabs.addTab(widget, "")
        self.tabs.setTabEnabled(self.tabs.indexOf(widget), self.feature_gate.is_enabled(feature_id))

    def reload_from_gate(self, *, refresh_current: bool = True) -> None:
        current_feature = self.feature_by_tab.get(self.tabs.currentWidget())
        blocked = self.tabs.blockSignals(True)
        try:
            while self.tabs.count():
                self.tabs.removeTab(0)
            visible_features: list[str] = []
            for feature_id in RAIL_FEATURE_ORDER:
                if not self.feature_gate.is_visible(feature_id):
                    continue
                widget = self._widget_for_feature(feature_id)
                self.tab_by_feature_id[feature_id] = widget
                self.feature_by_tab[widget] = feature_id
                self.tabs.addTab(widget, self._feature_title(feature_id))
                self.tabs.setTabEnabled(self.tabs.count() - 1, self.feature_gate.is_enabled(feature_id))
                visible_features.append(feature_id)
            target = self.tabs.indexOf(self.tab_by_feature_id.get(current_feature)) if current_feature else -1
            self.tabs.setCurrentIndex(target if target >= 0 else (0 if self.tabs.count() else -1))
        finally:
            self.tabs.blockSignals(blocked)
        self.retranslate()
        app_logger.log_info(
            "RAIL_TRANSIT_FEATURE_TABS_RECONCILED",
            (
                f"session_override_active={self.feature_gate.is_session_override_active()} profile={self.feature_gate.profile} "
                f"visible_features={','.join(self._visible_feature_ids())} current_feature={self.feature_by_tab.get(self.tabs.currentWidget(), '')} "
                f"tab_count={self.tabs.count()}"
            ),
        )
        if refresh_current:
            self.refresh_current_async_or_lazy(force_if_empty=False)

    def _widget_for_feature(self, feature_id: str) -> QWidget:
        page = self._page_for_feature(feature_id)
        if page is not None:
            return page
        placeholder = self.tab_by_feature_id.get(feature_id)
        if placeholder is not None:
            return placeholder
        return QWidget()

    def _feature_title(self, feature_id: str) -> str:
        item = FEATURE_BY_ID.get(feature_id)
        return self.i18n.t(item.title_key if item is not None else feature_id)

    def _visible_feature_ids(self) -> list[str]:
        return [self.feature_by_tab.get(self.tabs.widget(index), "") for index in range(self.tabs.count())]

    def _ensure_feature_page(self, feature_id: str) -> QWidget:
        self.feature_gate.assert_enabled(feature_id)
        existing = self._page_for_feature(feature_id)
        if existing is not None:
            return existing
        factory = self.feature_factories.get(feature_id)
        placeholder = self.tab_by_feature_id.get(feature_id)
        if factory is None or placeholder is None:
            return placeholder or QWidget()
        start = perf_counter()
        page = factory()
        self._assign_feature_page(feature_id, page)
        self._replace_feature_tab(feature_id, page)
        self._log_page_profile(feature_id, "ensure", start)
        return page

    def _page_for_feature(self, feature_id: str) -> QWidget | None:
        return {
            "rail.train_online": self.vehicle_mr_online_page,
            "rail.car_network_diagnostic": self.car_network_page,
            "rail.trackside_ap_business": self.trackside_page,
            "rail.raw_mesh_log_analysis": self.mesh_page,
            "rail.online_mr_collection": self.online_mr_page,
            "rail.online_mr_analysis": self.online_mr_analysis_page,
        }.get(feature_id)

    def _assign_feature_page(self, feature_id: str, page: QWidget) -> None:
        if feature_id == "rail.train_online":
            self.vehicle_mr_online_page = page
        elif feature_id == "rail.car_network_diagnostic":
            self.car_network_page = page
        elif feature_id == "rail.trackside_ap_business":
            self.trackside_page = page
        elif feature_id == "rail.raw_mesh_log_analysis":
            self.mesh_page = page
        elif feature_id == "rail.online_mr_collection":
            self.online_mr_page = page
        elif feature_id == "rail.online_mr_analysis":
            self.online_mr_analysis_page = page

    def _create_vehicle_mr_online_page(self) -> QWidget:
        from netconsole.ui.pages.vehicle_mr_online_page import VehicleMrOnlinePage

        return VehicleMrOnlinePage(self.repository, self.i18n, self.site_name, self.paths)

    def _create_car_network_page(self) -> QWidget:
        from netconsole.ui.pages.car_network_diagnostic_page import CarNetworkDiagnosticPage

        return CarNetworkDiagnosticPage(self.repository, self.i18n, self.site_name, self.paths)

    def _create_trackside_page(self) -> QWidget:
        from netconsole.ui.pages.trackside_ap_service_page import TracksideApServicePage

        return TracksideApServicePage(self.repository, self.i18n, self.site_name, self.paths)

    def _create_mesh_page(self) -> QWidget:
        from netconsole.ui.pages.mesh_log_analysis_page import MeshLogAnalysisPage

        return MeshLogAnalysisPage(self.repository, self.i18n, self.site_name, self.paths)

    def _create_online_mr_page(self) -> QWidget:
        from netconsole.ui.pages.online_mr_collection_page import OnlineMrCollectionPage

        page = OnlineMrCollectionPage(self.repository, self.i18n, self.site_name, self.paths, feature_gate=self.feature_gate)
        page.session_history_changed.connect(self._refresh_online_mr_analysis_history)
        return page

    def _create_online_mr_analysis_page(self) -> QWidget:
        from netconsole.ui.pages.online_mr_collection_analysis_page import OnlineMrCollectionAnalysisPage

        return OnlineMrCollectionAnalysisPage(self.repository, self.i18n, self.site_name, self.paths)

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

    def _log_page_profile(self, feature_id: str, phase: str, start: float) -> None:
        elapsed_ms = (perf_counter() - start) * 1000
        rows = self._page_row_count(self._page_for_feature(feature_id))
        app_logger.log_info(
            "UI_PAGE_PROFILE",
            f"page={feature_id} phase={phase} elapsed_ms={elapsed_ms:.1f} rows={rows}",
        )

    @staticmethod
    def _page_row_count(page: QWidget | None) -> int:
        if page is None:
            return 0
        for attr in ("trackside_rows", "current_trains", "filtered_devices", "sessions"):
            value = getattr(page, attr, None)
            if isinstance(value, dict):
                return len(value)
            if isinstance(value, list):
                return len(value)
        return 0
