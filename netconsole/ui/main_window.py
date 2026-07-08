from __future__ import annotations

import getpass
from time import perf_counter

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.background_tasks import background_task_manager
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureDisabledError, FeatureGate, default_feature_gate
from netconsole.core.feature_registry import PAGE_FEATURE_BY_PAGE_ID
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.resources import icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core.shutdown_manager import CallbackTask, shutdown_manager
from netconsole.core.sites import Site, SiteManager
from netconsole.core import version as version_info
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.dialogs.about_dialog import AboutRepositoryDialog
from netconsole.ui.dialogs.changelog_dialog import ChangelogDialog
from netconsole.ui.dialogs.shutdown_progress_dialog import ShutdownProgressDialog
from netconsole.ui.dialogs.mesh_analysis_params_dialog import MeshAnalysisParamsEditor
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.device_management_page import DeviceManagementPage
from netconsole.ui.shell import AppFramelessMainWindow
from netconsole.ui.theme import apply_global_theme
from netconsole.ui.widgets.loading_overlay import LoadingOverlay
from netconsole.ui.window_manager import window_manager
from netconsole.ui.windowing import fit_default_window_size


class MainWindow(AppFramelessMainWindow):
    def __init__(
        self,
        site: Site,
        repository: DeviceRepository,
        i18n: I18n,
        paths: PathResolver,
        startup_started_at: float | None = None,
    ) -> None:
        super().__init__()
        self.startup_started_at = startup_started_at or perf_counter()
        self.paths = paths
        self.site_manager = SiteManager(paths)
        self.settings = SettingsStore(paths)
        self.site = site
        self.repository = repository
        self.i18n = i18n
        self.current_theme = self.settings.theme
        self.feature_gate: FeatureGate = default_feature_gate()
        self.about_dialog: AboutRepositoryDialog | None = None
        self.changelog_dialog: ChangelogDialog | None = None
        self.pages: dict[str, QWidget] = {}
        self.detached_windows: list[QMainWindow] = []
        self.activated_pages: set[str] = set()
        self.preloaded_pages: set[str] = set()
        self.preload_failures: dict[str, str] = {}
        self.current_page_id = "devices"
        self._module_switch_generation = 0
        self._activation_generation = 0
        self.app_is_exiting = False
        self.tray_notice_shown_this_session = False
        self.sidebar_collapsed = self._read_sidebar_collapsed_setting()

        self.navigation = Navigation(i18n, self.feature_gate)
        self.stack = QStackedWidget()
        self.loading_overlay = LoadingOverlay(self.stack)
        self.device_page = DeviceManagementPage(repository, i18n, site.name)
        self.disabled_pages: dict[str, QWidget] = {}
        self.loading_pages: dict[str, QWidget] = {}
        self.config_collection_page: QWidget | None = None
        self.file_management_page: QWidget | None = None
        self.snmp_center_page: QWidget | None = None
        self.rail_transit_page: QWidget | None = None
        self.network_tools_page: QWidget | None = None
        self.wifi_survey_page: QWidget | None = None
        self.ac_page: QWidget | None = None
        self.log_page: QWidget | None = None
        self.settings_page: QWidget | None = None
        self.pages["devices"] = self.device_page
        self.stack.addWidget(self.device_page)

        self.site_label = QLabel()
        self.new_site_button = QPushButton()
        self.switch_site_button = QPushButton()
        self.detach_page_button = QPushButton()
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.zh_button = QPushButton()
        self.en_button = QPushButton()
        self.light_theme_button = QPushButton()
        self.light_theme_button.setCheckable(True)
        self.light_theme_button.setObjectName("lightThemeButton")
        self.dark_theme_button = QPushButton()
        self.dark_theme_button.setCheckable(True)
        self.dark_theme_button.setObjectName("darkThemeButton")
        self.about_button = QPushButton()
        self.about_button.setObjectName("aboutRepositoryButton")
        self.version_button = QPushButton()
        self.version_button.setObjectName("versionButton")
        self.version_button.installEventFilter(self)
        self.data_disk_button = QPushButton()
        self.sidebar_toggle_button = QPushButton()
        self.sidebar_toggle_button.setObjectName("sidebarToggleButton")
        self.data_disk_dialog = None
        self.shutdown_dialog: ShutdownProgressDialog | None = None
        self._force_close = False

        self.navigation.currentRowChanged.connect(self.open_current_page)
        self.device_page.groups_changed.connect(self.refresh_group_filters)
        self.device_page.devices_changed.connect(self.refresh_device_dependents)
        self.new_site_button.clicked.connect(self.create_site)
        self.switch_site_button.clicked.connect(self.switch_site_dialog)
        self.detach_page_button.clicked.connect(self.detach_current_page)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.zh_button.clicked.connect(lambda: self.switch_language("zh_CN"))
        self.en_button.clicked.connect(lambda: self.switch_language("en_US"))
        self.light_theme_button.clicked.connect(lambda: self.set_theme("light"))
        self.dark_theme_button.clicked.connect(lambda: self.set_theme("dark"))
        self.title_bar.theme_requested.connect(self.set_theme)
        self.about_button.clicked.connect(self.show_about_dialog)
        self.version_button.clicked.connect(self.show_changelog_dialog)
        self.data_disk_button.clicked.connect(self.show_data_disk_manager)
        self.sidebar_toggle_button.clicked.connect(self.toggle_sidebar)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.site_label)
        top_bar.addWidget(self.new_site_button)
        top_bar.addWidget(self.switch_site_button)
        top_bar.addWidget(self.detach_page_button)
        top_bar.addStretch(1)
        top_bar.addWidget(self.always_on_top_button)
        top_bar.addWidget(self.zh_button)
        top_bar.addWidget(self.en_button)

        content_layout = QVBoxLayout()
        content_layout.addLayout(top_bar)
        content_layout.addWidget(self.stack)

        root_layout = QHBoxLayout()
        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftSidebar")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(6, 6, 6, 0)
        toggle_row.addStretch(1)
        toggle_row.addWidget(self.sidebar_toggle_button)
        left_layout.addLayout(toggle_row)
        left_layout.addWidget(self.navigation, 1)
        self.system_panel = self._system_panel()
        left_layout.addWidget(self.system_panel)
        root_layout.addWidget(self.left_panel)
        content = QWidget()
        content.setLayout(content_layout)
        root_layout.addWidget(content, 1)

        root = QWidget()
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self.setWindowIcon(QIcon(str(icon_path("love.ico"))))
        self.setMinimumSize(1280, 760)
        self.apply_initial_geometry()
        self.apply_style(self.current_theme)
        self.retranslate()
        self.set_sidebar_collapsed(self.sidebar_collapsed, persist=False)
        self._setup_tray()
        window_manager.set_main_window(self)
        app_logger.log_info("DEVICE_PAGE_OPENED", self.site.name)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.version_button and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier and event.modifiers() & Qt.AltModifier:
                self.show_admin_unlock_dialog()
                return True
        return super().eventFilter(watched, event)

    def open_current_page(self, row: int) -> None:
        if row < 0:
            return
        page_id = self.navigation.item(row).data(256)
        page_id = str(page_id)
        if not self._is_page_enabled(page_id):
            page = self.get_or_create_page(page_id)
            self.stack.setCurrentWidget(page)
            return
        if page_id == self.current_page_id and page_id in self.pages:
            return
        self.current_page_id = page_id
        self._module_switch_generation += 1
        switch_generation = self._module_switch_generation
        if page_id == "rail_transit":
            app_logger.log_info("RAIL_TRANSIT_OPEN_REQUESTED", self.site.name)
        if page_id in {"ac", "rail_transit"} and page_id not in self.pages:
            self.show_page_loading(page_id)
            self.stack.setCurrentWidget(self._loading_page(page_id))
            QTimer.singleShot(0, lambda page_id=page_id, generation=switch_generation: self._finish_deferred_page_open(page_id, generation))
            return
        page = self.get_or_create_page(page_id)
        self.stack.setCurrentWidget(page)
        if page_id == "devices":
            self.hide_page_loading()
        if page_id == "rail_transit":
            app_logger.log_info("RAIL_TRANSIT_PAGE_SHOWN", self.site.name)
        else:
            event = {
                "logs": "LOG_PAGE_OPENED",
                "ac": "AC_PAGE_OPENED",
                "config_collection": "CONFIG_COLLECTION_PAGE_OPENED",
                "file_management": "FILE_MANAGEMENT_PAGE_OPENED",
                "snmp_center": "SNMP_CENTER_PAGE_OPENED",
                "network_tools": "NETWORK_TOOLS_PAGE_OPENED",
            }.get(str(page_id), "DEVICE_PAGE_OPENED")
            app_logger.log_info(event, self.site.name)
        if page_id != "devices":
            self.show_page_loading(page_id)
        if page_id == "rail_transit":
            self._schedule_page_activation("rail_transit", force_if_empty=True)
        elif page_id == "ac":
            self._schedule_page_activation("ac")
        elif page_id not in self.preloaded_pages:
            self._schedule_page_activation(page_id)
        else:
            self.hide_page_loading()

    def _finish_deferred_page_open(self, page_id: str, generation: int) -> None:
        if generation != self._module_switch_generation or page_id != self.current_page_id:
            return
        page = self.get_or_create_page(page_id, activate_on_create=False)
        if generation != self._module_switch_generation or page_id != self.current_page_id:
            return
        self.stack.setCurrentWidget(page)
        if page_id == "rail_transit":
            app_logger.log_info("RAIL_TRANSIT_PAGE_SHOWN", self.site.name)
            self._schedule_page_activation("rail_transit", force_if_empty=True)
        elif page_id == "ac":
            app_logger.log_info("AC_PAGE_OPENED", self.site.name)
            self._schedule_page_activation("ac")

    def _schedule_page_activation(self, page_id: str, *, force_if_empty: bool = False) -> None:
        self._activation_generation += 1
        activation_generation = self._activation_generation
        QTimer.singleShot(
            0,
            lambda page_id=page_id, generation=activation_generation, force_if_empty=force_if_empty: self._activate_page_if_current(
                page_id,
                generation,
                force_if_empty=force_if_empty,
            ),
        )

    def _activate_page_if_current(self, page_id: str, generation: int, *, force_if_empty: bool = False) -> None:
        if generation != self._activation_generation or page_id != self.current_page_id:
            return
        self.activate_page(page_id, force_if_empty=force_if_empty)

    def get_or_create_page(self, page_id: str, *, activate_on_create: bool = True) -> QWidget:
        if not self._is_page_enabled(page_id):
            return self._disabled_page(page_id)
        if page_id in self.pages:
            return self.pages[page_id]
        if page_id == "ac":
            from netconsole.ui.pages.ac_management_page import AcManagementPage

            page = AcManagementPage(self.repository, self.i18n, self.site.name, self.feature_gate, eager_load=activate_on_create)
            self.ac_page = page
        elif page_id == "config_collection":
            from netconsole.ui.pages.config_collection_center_page import ConfigCollectionCenterPage

            page = ConfigCollectionCenterPage(self.repository, self.i18n, self.site.name, self.paths)
            self.config_collection_page = page
        elif page_id == "file_management":
            from netconsole.ui.pages.file_management_page import FileManagementPage

            page = FileManagementPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
            self.file_management_page = page
        elif page_id == "rail_transit":
            from netconsole.ui.pages.rail_transit_page import RailTransitPage

            page = RailTransitPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
            self.rail_transit_page = page
        elif page_id == "snmp_center":
            from netconsole.ui.pages.snmp_center_page import SnmpCenterPage

            page = SnmpCenterPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
            self.snmp_center_page = page
        elif page_id == "network_tools":
            from netconsole.ui.pages.network_tools_page import NetworkToolsPage

            page = NetworkToolsPage(self.i18n, self.site.name, self.paths, self.feature_gate)
            self.network_tools_page = page
        elif page_id == "wifi_survey":
            from netconsole.ui.pages.wifi_survey_page import WifiSurveyPage

            page = WifiSurveyPage(self.i18n, self.site.name, self.paths)
            self.wifi_survey_page = page
        elif page_id == "logs":
            from netconsole.ui.pages.app_log_page import AppLogPage

            page = AppLogPage(self.i18n, auto_refresh=False)
            self.log_page = page
        elif page_id == "system_settings":
            from netconsole.ui.pages.settings_page import SettingsPage

            page = SettingsPage(
                self.settings,
                self.site,
                self.paths,
                apply_theme_callback=self.set_theme,
                apply_language_callback=self.switch_language,
                create_site_callback=self.create_site,
                switch_site_callback=self.switch_site_dialog,
            )
            self.settings_page = page
        elif page_id == "feature_flags":
            from netconsole.ui.pages.feature_flags_page import FeatureFlagsPage

            page = FeatureFlagsPage(self.i18n, self.feature_gate, on_profile_saved=self.refresh_feature_flags)
        else:
            return self.device_page
        self.pages[page_id] = page
        self.stack.addWidget(page)
        app_logger.log_info(f"PAGE_CREATED:{page_id}", self._startup_elapsed_detail())
        return page

    def _loading_page(self, page_id: str) -> QWidget:
        page = self.loading_pages.get(page_id)
        if page is None:
            label = QLabel(self.i18n.t({"ac": "app.loading_ac", "rail_transit": "app.loading_rail_transit"}.get(page_id, "app.loading")))
            label.setAlignment(Qt.AlignCenter)
            self.loading_pages[page_id] = label
            self.stack.addWidget(label)
            page = label
        return page

    def create_detached_page(self, page_id: str) -> QWidget:
        self._assert_page_enabled(page_id)
        if page_id == "devices":
            return DeviceManagementPage(self.repository, self.i18n, self.site.name)
        if page_id == "ac":
            from netconsole.ui.pages.ac_management_page import AcManagementPage

            return AcManagementPage(self.repository, self.i18n, self.site.name, self.feature_gate)
        if page_id == "config_collection":
            from netconsole.ui.pages.config_collection_center_page import ConfigCollectionCenterPage

            return ConfigCollectionCenterPage(self.repository, self.i18n, self.site.name, self.paths)
        if page_id == "file_management":
            from netconsole.ui.pages.file_management_page import FileManagementPage

            return FileManagementPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
        if page_id == "rail_transit":
            from netconsole.ui.pages.rail_transit_page import RailTransitPage

            return RailTransitPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
        if page_id == "snmp_center":
            from netconsole.ui.pages.snmp_center_page import SnmpCenterPage

            return SnmpCenterPage(self.repository, self.i18n, self.site.name, self.paths, self.feature_gate)
        if page_id == "network_tools":
            from netconsole.ui.pages.network_tools_page import NetworkToolsPage

            return NetworkToolsPage(self.i18n, self.site.name, self.paths, self.feature_gate)
        if page_id == "wifi_survey":
            from netconsole.ui.pages.wifi_survey_page import WifiSurveyPage

            return WifiSurveyPage(self.i18n, self.site.name, self.paths)
        if page_id == "logs":
            from netconsole.ui.pages.app_log_page import AppLogPage

            return AppLogPage(self.i18n, auto_refresh=False)
        if page_id == "system_settings":
            from netconsole.ui.pages.settings_page import SettingsPage

            return SettingsPage(
                self.settings,
                self.site,
                self.paths,
                apply_theme_callback=self.set_theme,
                apply_language_callback=self.switch_language,
                create_site_callback=self.create_site,
                switch_site_callback=self.switch_site_dialog,
            )
        if page_id == "feature_flags":
            from netconsole.ui.pages.feature_flags_page import FeatureFlagsPage

            return FeatureFlagsPage(self.i18n, self.feature_gate, on_profile_saved=self.refresh_feature_flags)
        return DeviceManagementPage(self.repository, self.i18n, self.site.name)

    def detach_current_page(self) -> None:
        row = self.navigation.currentRow()
        item = self.navigation.item(row) if row >= 0 else None
        if item is None:
            return
        page_id = str(item.data(256) or "devices")
        title = item.text() or page_id
        try:
            page = self.create_detached_page(page_id)
        except FeatureDisabledError:
            QMessageBox.information(self, self.i18n.t("app.title"), self.i18n.t("feature_flags.disabled_message"))
            return
        except Exception as exc:
            app_logger.log_error("DETACHED_PAGE_CREATE_FAILED", f"page={page_id}, error={exc}")
            QMessageBox.warning(self, self.i18n.t("app.title"), str(exc))
            return
        window = QMainWindow()
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.setWindowTitle(f"NetConsole - {title}")
        window.resize(1600, 900)
        window.setMinimumSize(1100, 720)
        window.setCentralWidget(page)
        self.detached_windows.append(window)
        window.destroyed.connect(lambda _=None, detached=window: self._remove_detached_window(detached))
        window_manager.register_child_window(window)
        window.show()
        QTimer.singleShot(0, lambda page_id=page_id, page=page: self.activate_detached_page(page_id, page))

    def activate_detached_page(self, page_id: str, page: QWidget) -> None:
        try:
            if page_id == "logs" and hasattr(page, "refresh"):
                page.refresh()
            elif page_id == "ac" and hasattr(page, "refresh_devices"):
                page.refresh_devices()
            elif page_id == "config_collection" and hasattr(page, "refresh"):
                page.refresh()
            elif page_id == "file_management" and hasattr(page, "refresh_devices"):
                page.refresh_devices()
            elif page_id == "rail_transit":
                enter = getattr(page, "on_enter", None)
                if callable(enter):
                    enter(force_if_empty=True)
                elif hasattr(page, "refresh_current_async_or_lazy"):
                    page.refresh_current_async_or_lazy(force_if_empty=True)
            elif page_id == "snmp_center" and hasattr(page, "start_snmp_service_async"):
                page.start_snmp_service_async()
            elif page_id == "network_tools" and hasattr(page, "refresh_all"):
                page.refresh_all()
            elif page_id == "system_settings" and hasattr(page, "reload_settings"):
                page.reload_settings()
        except Exception as exc:
            app_logger.log_warning("DETACHED_PAGE_ACTIVATE_FAILED", f"page={page_id}, error={exc}")

    def _remove_detached_window(self, window: QMainWindow) -> None:
        if window in self.detached_windows:
            self.detached_windows.remove(window)
        window_manager.unregister_child_window(window)

    def _sync_detached_pages_to_current_site(self) -> None:
        for window in list(self.detached_windows):
            page = window.centralWidget()
            if page is not None:
                self._set_page_context(page)

    def _set_page_context(self, page: QWidget) -> None:
        setter = getattr(page, "set_repository", None)
        if callable(setter):
            try:
                setter(self.repository, self.site.name)
                return
            except TypeError:
                pass
        site_setter = getattr(page, "set_site", None)
        if callable(site_setter):
            site_setter(self.site.name)

    def _refresh_detached_group_filters(self) -> None:
        for window in list(self.detached_windows):
            page = window.centralWidget()
            if page is None:
                continue
            refresh_groups = getattr(page, "refresh_groups", None)
            if callable(refresh_groups):
                refresh_groups()
            refresh_devices = getattr(page, "refresh_devices", None)
            if callable(refresh_devices):
                try:
                    refresh_devices(trigger_device_change=False)
                except TypeError:
                    refresh_devices()

    def _refresh_detached_device_dependents(self) -> None:
        for window in list(self.detached_windows):
            page = window.centralWidget()
            if page is None:
                continue
            for method_name in ("mark_devices_changed", "refresh_devices", "refresh_all", "refresh"):
                method = getattr(page, method_name, None)
                if callable(method):
                    try:
                        if method_name == "refresh_devices":
                            method(trigger_device_change=False)
                        else:
                            method()
                    except TypeError:
                        method()
                    break

    def preload_page(self, page_id: str) -> QWidget:
        self._assert_page_enabled(page_id)
        page = self.get_or_create_page(page_id)
        if page_id == "logs" and self.log_page is not None:
            self.log_page.refresh()
        self.preloaded_pages.add(page_id)
        self.activated_pages.add(page_id)
        app_logger.log_info(f"PAGE_PRELOADED:{page_id}", self._startup_elapsed_detail())
        return page

    def mark_preload_failures(self, failures: dict[str, str]) -> None:
        self.preload_failures = dict(failures)
        if failures:
            app_logger.log_warning("STARTUP_PRELOAD_PARTIAL_FAILURE", ", ".join(sorted(failures)))

    def activate_page(self, page_id: str, *, force_if_empty: bool = False) -> None:
        if not self._is_page_enabled(page_id):
            self.hide_page_loading()
            return
        if page_id not in self.activated_pages:
            self.activated_pages.add(page_id)
            app_logger.log_info(f"PAGE_FIRST_ACTIVATED:{page_id}", self._startup_elapsed_detail())
        task_name = f"page_activation:{page_id}"
        task_started_at = perf_counter()
        app_logger.log_info("BACKGROUND_TASK_STARTED", f"task={task_name} {self._startup_elapsed_detail()}")
        try:
            if page_id == "logs" and self.log_page is not None:
                self.log_page.refresh()
            elif page_id == "ac" and self.ac_page is not None:
                refresh_current = getattr(self.ac_page, "refresh_current_async_or_lazy", None)
                if callable(refresh_current):
                    refresh_current(force_if_empty=force_if_empty)
                else:
                    self.ac_page.refresh_devices()
            elif page_id == "config_collection" and self.config_collection_page is not None:
                self.config_collection_page.refresh()
            elif page_id == "file_management" and self.file_management_page is not None:
                self.file_management_page.refresh_devices()
            elif page_id == "rail_transit" and self.rail_transit_page is not None:
                enter = getattr(self.rail_transit_page, "on_enter", None)
                if callable(enter):
                    enter(force_if_empty=force_if_empty)
                else:
                    self.rail_transit_page.refresh_current_async_or_lazy(force_if_empty=force_if_empty)
            elif page_id == "snmp_center" and self.snmp_center_page is not None:
                self.snmp_center_page.start_snmp_service_async()
            elif page_id == "network_tools" and self.network_tools_page is not None:
                self.network_tools_page.refresh_all()
            elif page_id == "wifi_survey":
                pass
        except Exception as exc:
            app_logger.log_error(f"PAGE_ACTIVATE_FAILED:{page_id}", str(exc))
        finally:
            elapsed_ms = int((perf_counter() - task_started_at) * 1000)
            app_logger.log_info("BACKGROUND_TASK_FINISHED", f"task={task_name} elapsed_ms={elapsed_ms}")
            self.hide_page_loading()

    def show_page_loading(self, page_id: str) -> None:
        message_key = {
            "rail_transit": "app.loading_rail_transit",
            "ac": "app.loading_ac",
            "file_management": "app.loading_file_management",
            "snmp_center": "app.loading",
            "network_tools": "app.loading_network_tools",
            "logs": "app.loading_logs",
        }.get(page_id, "app.loading")
        self.loading_overlay.show_loading(self.i18n.t(message_key))

    def hide_page_loading(self) -> None:
        self.loading_overlay.hide_loading()

    def create_site(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self.i18n.t("site.new"))
        form = QFormLayout()
        name_input = QLineEdit()
        line_input = QLineEdit()
        system_combo = QComboBox()
        system_combo.addItems(["PIS", "信号", "其他"])
        network_combo = QComboBox()
        network_combo.addItems(["default", "A网", "B网", "红网", "蓝网", "其他"])
        remark_input = QLineEdit()
        form.addRow(self.i18n.t("site.name"), name_input)
        form.addRow("线路名称", line_input)
        form.addRow("系统类型", system_combo)
        form.addRow("网络域", network_combo)
        form.addRow("备注", remark_input)
        basic_page = QWidget()
        basic_page.setLayout(form)
        mesh_params_editor = MeshAnalysisParamsEditor()
        tabs = QTabWidget()
        tabs.addTab(basic_page, "基础信息")
        tabs.addTab(mesh_params_editor, "MR / MESH 分析参数")
        buttons = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        buttons.addStretch(1)
        buttons.addWidget(ok_button)
        buttons.addWidget(cancel_button)
        layout = QVBoxLayout()
        layout.addWidget(tabs)
        layout.addLayout(buttons)
        dialog.setLayout(layout)
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        name = name_input.text().strip()
        try:
            site = self.site_manager.create_site(
                name,
                display_name=name,
                line_name=line_input.text().strip(),
                system_type=str(system_combo.currentText() or "").strip(),
                network_domain=str(network_combo.currentText() or "default").strip(),
                remark=remark_input.text().strip(),
                mesh_analysis_params=mesh_params_editor.params().to_dict(),
            )
        except Exception as exc:
            app_logger.log_warning("SITE_CREATE_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("site.new"), self.i18n.t("site.invalid", error=str(exc)))
            return
        app_logger.log_info("SITE_CREATED", site.name)
        self._switch_to_site(site)
        QMessageBox.information(self, self.i18n.t("site.new"), self.i18n.t("site.create_success", site=site.name))

    def switch_site_dialog(self) -> None:
        sites = self.site_manager.list_sites()
        if not sites:
            return
        current_index = sites.index(self.site.name) if self.site.name in sites else 0
        name, accepted = QInputDialog.getItem(
            self,
            self.i18n.t("site.switch"),
            self.i18n.t("site.select"),
            sites,
            current_index,
            False,
        )
        if not accepted or not name or name == self.site.name:
            return
        try:
            site = self.site_manager.switch_site(name)
        except Exception as exc:
            app_logger.log_warning("SITE_SWITCH_FAILED", str(exc))
            QMessageBox.warning(self, self.i18n.t("site.switch"), str(exc))
            return
        self._switch_to_site(site)
        app_logger.log_info("SITE_SWITCHED", site.name)
        QMessageBox.information(self, self.i18n.t("site.switch"), self.i18n.t("site.switch_success", site=site.name))

    def _switch_to_site(self, site: Site) -> None:
        self.site = site
        self.repository = DeviceRepository(Database(site.database_path))
        self.device_page.set_repository(self.repository, site.name)
        if self.config_collection_page is not None:
            self.config_collection_page.set_repository(self.repository, site.name)
        if self.file_management_page is not None:
            self.file_management_page.set_repository(self.repository, site.name)
        if self.rail_transit_page is not None:
            self.rail_transit_page.set_repository(self.repository, site.name)
        if self.snmp_center_page is not None:
            self.snmp_center_page.set_repository(self.repository, site.name)
        if self.network_tools_page is not None:
            self.network_tools_page.set_site(site.name)
        if self.wifi_survey_page is not None:
            self.wifi_survey_page.set_site(site.name)
        if self.ac_page is not None:
            self.ac_page.set_repository(self.repository, site.name)
        if self.settings_page is not None and hasattr(self.settings_page, "update_site"):
            self.settings_page.update_site(site)
        self._sync_detached_pages_to_current_site()
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site.name}")
        self.set_title_bar_context(site_name=self.site.name, status="就绪")

    def refresh_group_filters(self) -> None:
        if self.config_collection_page is not None:
            self.config_collection_page.refresh_groups()
            self.config_collection_page.refresh()
        if self.file_management_page is not None:
            self.file_management_page.refresh_groups()
            self.file_management_page.refresh_devices(trigger_device_change=False)
        if self.rail_transit_page is not None and hasattr(self.rail_transit_page, "refresh_groups"):
            self.rail_transit_page.refresh_groups()
        self._refresh_detached_group_filters()

    def refresh_device_dependents(self) -> None:
        if self.ac_page is not None:
            self.ac_page.refresh_devices()
        if self.config_collection_page is not None:
            self.config_collection_page.refresh()
        if self.file_management_page is not None:
            self.file_management_page.refresh_devices(trigger_device_change=False)
        if self.rail_transit_page is not None and hasattr(self.rail_transit_page, "mark_devices_changed"):
            self.rail_transit_page.mark_devices_changed()
        if self.snmp_center_page is not None:
            self.snmp_center_page.refresh_all()
        self._refresh_detached_device_dependents()

    def switch_language(self, language: str) -> None:
        self.i18n.set_language(language)
        app_logger.log_info("LANGUAGE_CHANGED", language)
        self.retranslate()

    def set_theme(self, theme: str) -> None:
        if theme == self.current_theme:
            self._sync_theme_buttons()
            return
        self.current_theme = theme
        self.settings.set_theme(theme)
        self.apply_style(theme)
        if self.rail_transit_page is not None:
            self.rail_transit_page.restyle_visible_link_rows()
        self._sync_theme_buttons()
        self.set_title_bar_theme(theme)
        app_logger.log_info("THEME_CHANGED", theme)
        self._update_tray_text()

    def show_about_dialog(self) -> None:
        if self.about_dialog is None:
            self.about_dialog = AboutRepositoryDialog(self.i18n, self)
            self.about_dialog.destroyed.connect(lambda _=None: setattr(self, "about_dialog", None))
        self.about_dialog.show()
        self.about_dialog.raise_()
        self.about_dialog.activateWindow()

    def show_changelog_dialog(self) -> None:
        if self.changelog_dialog is None:
            self.changelog_dialog = ChangelogDialog(self.i18n, self)
            self.changelog_dialog.destroyed.connect(lambda _=None: setattr(self, "changelog_dialog", None))
        self.changelog_dialog.show()
        self.changelog_dialog.raise_()
        self.changelog_dialog.activateWindow()

    def show_data_disk_manager(self) -> None:
        if self.data_disk_dialog is None:
            from netconsole.ui.dialogs.data_disk_manager_dialog import DataDiskManagerDialog

            self.data_disk_dialog = DataDiskManagerDialog(self.i18n, self.paths, self)
            self.data_disk_dialog.destroyed.connect(lambda _=None: setattr(self, "data_disk_dialog", None))
        self.data_disk_dialog.show()
        self.data_disk_dialog.raise_()
        self.data_disk_dialog.activateWindow()

    def show_admin_unlock_dialog(self) -> None:
        if not self.feature_gate.is_admin_unlock_configured():
            QMessageBox.information(self, "内部调试解锁", "当前版本未启用内部解锁。")
            self.feature_gate.verify_admin_unlock_password("")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("内部调试解锁")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("请输入内部解锁口令。本次启动有效，重启后恢复定制版。"))
        form = QFormLayout()
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)
        form.addRow("口令", password_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        password_input.setFocus()
        if dialog.exec() != QDialog.Accepted:
            return
        if not self.feature_gate.verify_admin_unlock_password(password_input.text()):
            QMessageBox.warning(self, "内部调试解锁", "口令错误，未启用临时完整模式。")
            return
        self.feature_gate.enable_session_full_mode(reason="version_button_unlock", operator=getpass.getuser())
        self.refresh_feature_flags()
        QMessageBox.information(self, "内部调试解锁", "已启用临时完整模式。本次启动有效，重启后恢复定制版。")

    def toggle_sidebar(self) -> None:
        self.set_sidebar_collapsed(not self.sidebar_collapsed, persist=True)

    def set_sidebar_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        self.sidebar_collapsed = bool(collapsed)
        self._apply_sidebar_visual_state()
        if persist:
            self.settings.set_value("sidebar_collapsed", self.sidebar_collapsed)

    def _read_sidebar_collapsed_setting(self) -> bool:
        value = self.settings.get_value("sidebar_collapsed", False)
        return value if isinstance(value, bool) else False

    def _apply_sidebar_visual_state(self) -> None:
        width = Navigation.COLLAPSED_WIDTH if self.sidebar_collapsed else Navigation.EXPANDED_WIDTH
        self.left_panel.setFixedWidth(width)
        self.navigation.set_collapsed(self.sidebar_collapsed)
        self.sidebar_toggle_button.setText(">>" if self.sidebar_collapsed else "<<")
        self.sidebar_toggle_button.setToolTip("Expand navigation" if self.sidebar_collapsed else "Collapse navigation")
        if self.sidebar_collapsed:
            self.light_theme_button.setText("L")
            self.dark_theme_button.setText("D")
            self.version_button.setText(version_info.APP_VERSION_DISPLAY)
            self.data_disk_button.setText("Disk")
        else:
            self.light_theme_button.setText(self.i18n.t("theme.light"))
            self.dark_theme_button.setText(self.i18n.t("theme.dark"))
            self.version_button.setText(version_info.APP_VERSION_DISPLAY)
            self.data_disk_button.setText(self.i18n.t("data_disk.button"))
        self.light_theme_button.setToolTip(self.i18n.t("theme.light"))
        self.dark_theme_button.setToolTip(self.i18n.t("theme.dark"))
        self.data_disk_button.setToolTip(self.i18n.t("data_disk.title"))

    def set_always_on_top(self, enabled: bool) -> None:
        window_manager.apply_main_window_on_top(enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))

    def closeEvent(self, event) -> None:
        if self._force_close:
            event.accept()
            return
        if self.app_is_exiting and shutdown_manager.is_shutting_down():
            event.ignore()
            return
        behavior = self.settings.close_behavior
        has_tasks = self.has_background_tasks()
        if behavior == "minimize_to_tray" and self.tray_available:
            self.hide_to_tray()
            event.ignore()
            return
        if behavior == "exit" and not has_tasks:
            event.ignore()
            self.request_app_exit("main_window_close")
            return
        choice = self.ask_close_behavior(has_tasks)
        if choice == "minimize_to_tray" and self.tray_available:
            self.hide_to_tray()
            event.ignore()
        elif choice == "exit":
            event.ignore()
            self.request_app_exit("main_window_close_confirmed")
        else:
            event.ignore()

    def _close_detached_windows(self) -> None:
        for window in list(self.detached_windows):
            window.close()

    def request_app_exit(self, reason: str) -> None:
        if not shutdown_manager.request_exit(reason):
            if self.shutdown_dialog is not None:
                self.shutdown_dialog.show()
                self.shutdown_dialog.raise_()
            return
        self.app_is_exiting = True
        background_task_manager.app_is_exiting = True
        shutdown_manager.register_task(
            CallbackTask(
                "background_tasks",
                background_task_manager.stop_all,
                lambda: background_task_manager.active_count() > 0,
            ),
            allow_during_shutdown=True,
        )
        self.shutdown_dialog = ShutdownProgressDialog(shutdown_manager, self)
        self.shutdown_dialog.finished.connect(self._finish_app_exit)
        self.shutdown_dialog.start()

    def _finish_app_exit(self) -> None:
        app_logger.log_info("APP_EXIT", "software closed")
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self._force_close = True
        self.close()
        QApplication.quit()

    def apply_initial_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1600, 900)
            return
        available = screen.availableGeometry()
        size = fit_default_window_size(available.width(), available.height(), 1600, 900)
        self.resize(size.width, size.height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def retranslate(self) -> None:
        self.setWindowTitle(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}")
        self.set_title_bar_context(site_name=self.site.name, status="就绪")
        self.set_title_bar_theme(self.current_theme)
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site.name}")
        self.new_site_button.setText(self.i18n.t("site.new"))
        self.switch_site_button.setText(self.i18n.t("site.switch"))
        self.detach_page_button.setText("弹出当前模块")
        self.detach_page_button.setToolTip("在独立窗口打开当前功能模块")
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))
        self.zh_button.setText(self.i18n.t("language.zh"))
        self.en_button.setText(self.i18n.t("language.en"))
        self.light_theme_button.setText(self.i18n.t("theme.light"))
        self.dark_theme_button.setText(self.i18n.t("theme.dark"))
        self.about_button.setText("")
        self.about_button.setIcon(QIcon(str(icon_path("love.png"))))
        self.about_button.setToolTip(self.i18n.t("about.title"))
        self.version_button.setText(version_info.APP_VERSION_DISPLAY)
        self.version_button.setToolTip(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}")
        self.data_disk_button.setText(self.i18n.t("data_disk.button"))
        self.data_disk_button.setToolTip(self.i18n.t("data_disk.title"))
        self._sync_theme_buttons()
        self.navigation.blockSignals(True)
        self.navigation.retranslate()
        self.navigation.blockSignals(False)
        for page in self.pages.values():
            retranslate = getattr(page, "retranslate", None)
            if callable(retranslate):
                retranslate()
        self._apply_sidebar_visual_state()
        self._update_tray_text()

    def refresh_feature_flags(self) -> None:
        self.feature_gate.reload()
        blocked = self.navigation.blockSignals(True)
        try:
            self.navigation.retranslate()
        finally:
            self.navigation.blockSignals(blocked)
        for page_id in list(self.pages):
            if not self._is_page_enabled(page_id):
                page = self.pages.pop(page_id)
                self.stack.removeWidget(page)
                page.deleteLater()
                continue
            self._refresh_page_feature_gate(self.pages[page_id], page_id=page_id)
        for index, window in enumerate(list(self.detached_windows)):
            page = window.centralWidget()
            if page is not None:
                self._refresh_page_feature_gate(page, page_id=f"detached:{index}")
        current = self.stack.currentWidget()
        if current is None or current not in self.pages.values():
            self.navigation.setCurrentRow(0)

    def _refresh_page_feature_gate(self, page: QWidget, *, page_id: str) -> None:
        try:
            apply_gate = getattr(page, "_apply_feature_gate", None)
            if callable(apply_gate):
                apply_gate()
            reload_from_gate = getattr(page, "reload_from_gate", None)
            if callable(reload_from_gate):
                reload_from_gate()
            app_logger.log_info(
                "FEATURE_GATE_UI_REFRESH",
                (
                    f"page_id={page_id} page_class={page.__class__.__name__} "
                    f"session_override_active={self.feature_gate.is_session_override_active()} profile={self.feature_gate.profile} "
                    f"visible_tabs={self._page_tab_summary(page, enabled=False)} enabled_tabs={self._page_tab_summary(page, enabled=True)}"
                ),
            )
        except Exception as exc:
            app_logger.log_error(
                "FEATURE_GATE_PAGE_REFRESH_FAILED",
                f"page_id={page_id} page_class={page.__class__.__name__} error={exc}",
            )

    @staticmethod
    def _page_tab_summary(page: QWidget, *, enabled: bool) -> str:
        tabs = getattr(page, "tabs", None)
        if tabs is None or not hasattr(tabs, "count"):
            return ""
        values: list[str] = []
        for index in range(tabs.count()):
            text = tabs.tabText(index) if hasattr(tabs, "tabText") else str(index)
            if enabled:
                if hasattr(tabs, "isTabEnabled") and tabs.isTabEnabled(index):
                    values.append(text)
            else:
                values.append(text)
        return ",".join(values)

    def _feature_for_page(self, page_id: str) -> str | None:
        return PAGE_FEATURE_BY_PAGE_ID.get(page_id)

    def _is_page_enabled(self, page_id: str) -> bool:
        feature_id = self._feature_for_page(page_id)
        return True if feature_id is None else self.feature_gate.is_enabled(feature_id)

    def _assert_page_enabled(self, page_id: str) -> None:
        feature_id = self._feature_for_page(page_id)
        if feature_id is not None:
            self.feature_gate.assert_enabled(feature_id)

    def _disabled_page(self, page_id: str) -> QWidget:
        page = self.disabled_pages.get(page_id)
        if page is None:
            page = QLabel(self.i18n.t("feature_flags.disabled_message"))
            page.setAlignment(Qt.AlignCenter)
            self.disabled_pages[page_id] = page
            self.stack.addWidget(page)
        return page

    def apply_style(self, theme: str) -> None:
        apply_global_theme(theme)

    def _system_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("systemPanel")
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(6)
        theme_row.addWidget(self.light_theme_button)
        theme_row.addWidget(self.dark_theme_button)
        layout.addLayout(theme_row)
        about_row = QHBoxLayout()
        about_row.setSpacing(6)
        about_row.addWidget(self.version_button, 1)
        about_row.addWidget(self.about_button)
        layout.addLayout(about_row)
        layout.addWidget(self.data_disk_button)
        return panel

    def _sync_theme_buttons(self) -> None:
        self.light_theme_button.setChecked(self.current_theme == "light")
        self.dark_theme_button.setChecked(self.current_theme == "dark")

    def _startup_elapsed_detail(self) -> str:
        elapsed_ms = int((perf_counter() - self.startup_started_at) * 1000)
        return f"elapsed_ms={elapsed_ms}"

    def _setup_tray(self) -> None:
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None
        self.tray_actions: dict[str, QAction] = {}
        if not self.tray_available:
            app_logger.log_warning("TRAY_UNAVAILABLE", "")
            return
        self.tray_icon = QSystemTrayIcon(QIcon(str(icon_path("love.ico"))), self)
        self.tray_menu = QMenu(self)
        self.tray_actions = {
            "show": QAction(self),
            "hide": QAction(self),
            "logs": QAction(self),
            "stop": QAction(self),
            "exit": QAction(self),
        }
        self.tray_actions["show"].triggered.connect(self.show_main_window)
        self.tray_actions["hide"].triggered.connect(self.hide_to_tray)
        self.tray_actions["logs"].triggered.connect(self.open_log_folder)
        self.tray_actions["stop"].triggered.connect(self.confirm_stop_all_background_tasks)
        self.tray_actions["exit"].triggered.connect(self.exit_from_tray)
        for key in ("show", "hide", "logs", "stop"):
            self.tray_menu.addAction(self.tray_actions[key])
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.tray_actions["exit"])
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self._update_tray_text()
        self.tray_icon.show()

    def _update_tray_text(self) -> None:
        if not getattr(self, "tray_icon", None):
            return
        task_count = self.background_task_count()
        self.tray_icon.setToolTip(f"NetConsole\n{self.i18n.t('tray.tasks', count=task_count)}")
        if self.tray_actions:
            self.tray_actions["show"].setText(self.i18n.t("tray.show_window"))
            self.tray_actions["hide"].setText(self.i18n.t("tray.hide_to_tray"))
            self.tray_actions["logs"].setText(self.i18n.t("tray.open_log_folder"))
            self.tray_actions["stop"].setText(self.i18n.t("tray.stop_all_tasks"))
            self.tray_actions["stop"].setEnabled(task_count > 0)
            self.tray_actions["exit"].setText(self.i18n.t("tray.exit"))

    def background_task_count(self) -> int:
        count = background_task_manager.active_count()
        for page in self.pages.values():
            workers = getattr(page, "workers_by_device_id", None)
            if isinstance(workers, dict):
                count += len(workers)
            for name in ("active_worker", "connect_worker", "list_worker", "load_thread", "collect_thread"):
                worker = getattr(page, name, None)
                if worker is not None and (not hasattr(worker, "isRunning") or worker.isRunning()):
                    count += 1
        return count

    def has_background_tasks(self) -> bool:
        return self.background_task_count() > 0

    def ask_close_behavior(self, has_tasks: bool) -> str:
        message = self.i18n.t("app.exit_message")
        if has_tasks:
            message = f"{message}\n\n{self.i18n.t('app.background_tasks_running')}"
        box = QMessageBox(self)
        box.setWindowTitle(self.i18n.t("app.exit_title"))
        box.setText(message)
        box.setIcon(QMessageBox.Question)
        minimize_button = None
        if self.tray_available:
            minimize_button = box.addButton(self.i18n.t("app.minimize_to_tray"), QMessageBox.ActionRole)
        exit_button = box.addButton(self.i18n.t("app.exit_app"), QMessageBox.DestructiveRole)
        box.addButton(self.i18n.t("app.cancel"), QMessageBox.RejectRole)
        remember = QCheckBox(self.i18n.t("app.remember_choice"))
        box.setCheckBox(remember)
        box.exec()
        clicked = box.clickedButton()
        if clicked == minimize_button:
            if remember.isChecked():
                self.settings.set_close_behavior("minimize_to_tray")
            return "minimize_to_tray"
        if clicked == exit_button:
            if remember.isChecked():
                self.settings.set_close_behavior("exit")
            return "exit"
        return "cancel"

    def hide_to_tray(self) -> None:
        if not self.tray_available:
            return
        self.hide()
        if self.tray_icon is not None and not (self.settings.tray_notice_shown or self.tray_notice_shown_this_session):
            self.tray_icon.showMessage(
                self.i18n.t("tray.running_in_background"),
                self.i18n.t("tray.reopen_hint"),
                QSystemTrayIcon.Information,
                3000,
            )
            self.tray_notice_shown_this_session = True
            self.settings.set_tray_notice_shown(True)

    def show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_main_window()

    def open_log_folder(self) -> None:
        self.paths.app_log_path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.app_log_path.parent)))

    def confirm_stop_all_background_tasks(self) -> None:
        if not self.has_background_tasks():
            return
        answer = QMessageBox.question(self, self.i18n.t("tray.stop_all_tasks"), self.i18n.t("tray.stop_all_confirm"))
        if answer == QMessageBox.Yes:
            background_task_manager.stop_all()
            self._update_tray_text()

    def exit_from_tray(self) -> None:
        self.request_app_exit("tray_exit")
