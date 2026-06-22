from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.background_tasks import background_task_manager
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.resources import icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import Site, SiteManager
from netconsole.core import version as version_info
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.dialogs.about_dialog import AboutRepositoryDialog
from netconsole.ui.dialogs.changelog_dialog import ChangelogDialog
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.device_management_page import DeviceManagementPage
from netconsole.ui.theme import apply_global_theme
from netconsole.ui.widgets.loading_overlay import LoadingOverlay
from netconsole.ui.window_manager import window_manager
from netconsole.ui.windowing import fit_default_window_size


class MainWindow(QMainWindow):
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
        self.about_dialog: AboutRepositoryDialog | None = None
        self.changelog_dialog: ChangelogDialog | None = None
        self.pages: dict[str, QWidget] = {}
        self.activated_pages: set[str] = set()
        self.preloaded_pages: set[str] = set()
        self.preload_failures: dict[str, str] = {}
        self.app_is_exiting = False
        self.tray_notice_shown_this_session = False

        self.navigation = Navigation(i18n)
        self.stack = QStackedWidget()
        self.loading_overlay = LoadingOverlay(self.stack)
        self.device_page = DeviceManagementPage(repository, i18n, site.name)
        self.config_collection_page: QWidget | None = None
        self.file_management_page: QWidget | None = None
        self.rail_transit_page: QWidget | None = None
        self.network_tools_page: QWidget | None = None
        self.ac_page: QWidget | None = None
        self.log_page: QWidget | None = None
        self.pages["devices"] = self.device_page
        self.stack.addWidget(self.device_page)

        self.site_label = QLabel()
        self.new_site_button = QPushButton()
        self.switch_site_button = QPushButton()
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

        self.navigation.currentRowChanged.connect(self.open_current_page)
        self.device_page.groups_changed.connect(self.refresh_group_filters)
        self.device_page.devices_changed.connect(self.refresh_device_dependents)
        self.new_site_button.clicked.connect(self.create_site)
        self.switch_site_button.clicked.connect(self.switch_site_dialog)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        self.zh_button.clicked.connect(lambda: self.switch_language("zh_CN"))
        self.en_button.clicked.connect(lambda: self.switch_language("en_US"))
        self.light_theme_button.clicked.connect(lambda: self.set_theme("light"))
        self.dark_theme_button.clicked.connect(lambda: self.set_theme("dark"))
        self.about_button.clicked.connect(self.show_about_dialog)
        self.version_button.clicked.connect(self.show_changelog_dialog)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.site_label)
        top_bar.addWidget(self.new_site_button)
        top_bar.addWidget(self.switch_site_button)
        top_bar.addStretch(1)
        top_bar.addWidget(self.always_on_top_button)
        top_bar.addWidget(self.zh_button)
        top_bar.addWidget(self.en_button)

        content_layout = QVBoxLayout()
        content_layout.addLayout(top_bar)
        content_layout.addWidget(self.stack)

        root_layout = QHBoxLayout()
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.navigation, 1)
        left_layout.addWidget(self._system_panel())
        root_layout.addWidget(left_panel)
        content = QWidget()
        content.setLayout(content_layout)
        root_layout.addWidget(content, 1)

        root = QWidget()
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self.setWindowIcon(QIcon(str(icon_path("love.ico"))))
        self.setMinimumSize(1200, 760)
        self.apply_initial_geometry()
        self.apply_style(self.current_theme)
        self.retranslate()
        self._setup_tray()
        window_manager.set_main_window(self)
        app_logger.log_info("DEVICE_PAGE_OPENED", self.site.name)

    def open_current_page(self, row: int) -> None:
        if row < 0:
            return
        page_id = self.navigation.item(row).data(256)
        page = self.get_or_create_page(str(page_id))
        if page_id == "rail_transit":
            app_logger.log_info("RAIL_TRANSIT_OPEN_REQUESTED", self.site.name)
        self.stack.setCurrentWidget(page)
        if page_id == "rail_transit":
            app_logger.log_info("RAIL_TRANSIT_PAGE_SHOWN", self.site.name)
        else:
            event = {
                "logs": "LOG_PAGE_OPENED",
                "ac": "AC_PAGE_OPENED",
                "config_collection": "CONFIG_COLLECTION_PAGE_OPENED",
                "file_management": "FILE_MANAGEMENT_PAGE_OPENED",
                "network_tools": "NETWORK_TOOLS_PAGE_OPENED",
            }.get(str(page_id), "DEVICE_PAGE_OPENED")
            app_logger.log_info(event, self.site.name)
        if page_id != "devices":
            self.show_page_loading(str(page_id))
        if page_id == "rail_transit":
            QTimer.singleShot(0, lambda: self.activate_page("rail_transit", force_if_empty=True))
        elif page_id == "ac":
            QTimer.singleShot(0, lambda: self.activate_page("ac"))
        elif str(page_id) not in self.preloaded_pages:
            QTimer.singleShot(0, lambda page_id=str(page_id): self.activate_page(page_id))
        else:
            self.hide_page_loading()

    def get_or_create_page(self, page_id: str) -> QWidget:
        if page_id in self.pages:
            return self.pages[page_id]
        if page_id == "ac":
            from netconsole.ui.pages.ac_management_page import AcManagementPage

            page = AcManagementPage(self.repository, self.i18n, self.site.name)
            self.ac_page = page
        elif page_id == "config_collection":
            from netconsole.ui.pages.config_collection_center_page import ConfigCollectionCenterPage

            page = ConfigCollectionCenterPage(self.repository, self.i18n, self.site.name, self.paths)
            self.config_collection_page = page
        elif page_id == "file_management":
            from netconsole.ui.pages.file_management_page import FileManagementPage

            page = FileManagementPage(self.repository, self.i18n, self.site.name, self.paths)
            self.file_management_page = page
        elif page_id == "rail_transit":
            from netconsole.ui.pages.rail_transit_page import RailTransitPage

            page = RailTransitPage(self.repository, self.i18n, self.site.name, self.paths)
            self.rail_transit_page = page
        elif page_id == "network_tools":
            from netconsole.ui.pages.network_tools_page import NetworkToolsPage

            page = NetworkToolsPage(self.i18n, self.site.name, self.paths)
            self.network_tools_page = page
        elif page_id == "logs":
            from netconsole.ui.pages.app_log_page import AppLogPage

            page = AppLogPage(self.i18n, auto_refresh=False)
            self.log_page = page
        else:
            return self.device_page
        self.pages[page_id] = page
        self.stack.addWidget(page)
        app_logger.log_info(f"PAGE_CREATED:{page_id}", self._startup_elapsed_detail())
        return page

    def preload_page(self, page_id: str) -> QWidget:
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
                self.ac_page.refresh_devices()
            elif page_id == "config_collection" and self.config_collection_page is not None:
                self.config_collection_page.refresh()
            elif page_id == "file_management" and self.file_management_page is not None:
                self.file_management_page.refresh_devices()
            elif page_id == "rail_transit" and self.rail_transit_page is not None:
                self.rail_transit_page.refresh_current_async_or_lazy(force_if_empty=force_if_empty)
            elif page_id == "network_tools" and self.network_tools_page is not None:
                self.network_tools_page.refresh_all()
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
            "network_tools": "app.loading_network_tools",
            "logs": "app.loading_logs",
        }.get(page_id, "app.loading")
        self.loading_overlay.show_loading(self.i18n.t(message_key))

    def hide_page_loading(self) -> None:
        self.loading_overlay.hide_loading()

    def create_site(self) -> None:
        name, accepted = QInputDialog.getText(self, self.i18n.t("site.new"), self.i18n.t("site.name"))
        if not accepted:
            return
        try:
            site = self.site_manager.create_site(name)
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
        if self.network_tools_page is not None:
            self.network_tools_page.set_site(site.name)
        if self.ac_page is not None:
            self.ac_page.set_repository(self.repository, site.name)
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site.name}")

    def refresh_group_filters(self) -> None:
        if self.config_collection_page is not None:
            self.config_collection_page.refresh_groups()
            self.config_collection_page.refresh()
        if self.file_management_page is not None:
            self.file_management_page.refresh_groups()
            self.file_management_page.refresh_devices(trigger_device_change=False)
        if self.rail_transit_page is not None and hasattr(self.rail_transit_page, "refresh_groups"):
            self.rail_transit_page.refresh_groups()

    def refresh_device_dependents(self) -> None:
        if self.ac_page is not None:
            self.ac_page.refresh_devices()
        if self.config_collection_page is not None:
            self.config_collection_page.refresh()
        if self.file_management_page is not None:
            self.file_management_page.refresh_devices(trigger_device_change=False)
        if self.rail_transit_page is not None and hasattr(self.rail_transit_page, "mark_devices_changed"):
            self.rail_transit_page.mark_devices_changed()

    def switch_language(self, language: str) -> None:
        self.i18n.set_language(language)
        app_logger.log_info("LANGUAGE_CHANGED", language)
        self.retranslate()

    def set_theme(self, theme: str) -> None:
        self.current_theme = theme
        self.settings.set_theme(theme)
        self.apply_style(theme)
        if self.rail_transit_page is not None:
            self.rail_transit_page.restyle_visible_link_rows()
        self._sync_theme_buttons()
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

    def set_always_on_top(self, enabled: bool) -> None:
        window_manager.apply_main_window_on_top(enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))

    def closeEvent(self, event) -> None:
        if self.app_is_exiting:
            background_task_manager.stop_all()
            app_logger.log_info("APP_EXIT", "software closed")
            super().closeEvent(event)
            return
        behavior = self.settings.close_behavior
        has_tasks = self.has_background_tasks()
        if behavior == "minimize_to_tray" and self.tray_available:
            self.hide_to_tray()
            event.ignore()
            return
        if behavior == "exit" and not has_tasks:
            self.app_is_exiting = True
            background_task_manager.stop_all()
            app_logger.log_info("APP_EXIT", "software closed")
            super().closeEvent(event)
            return
        choice = self.ask_close_behavior(has_tasks)
        if choice == "minimize_to_tray" and self.tray_available:
            self.hide_to_tray()
            event.ignore()
        elif choice == "exit":
            self.app_is_exiting = True
            background_task_manager.stop_all()
            app_logger.log_info("APP_EXIT", "software closed")
            super().closeEvent(event)
        else:
            event.ignore()

    def apply_initial_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1440, 900)
            return
        available = screen.availableGeometry()
        size = fit_default_window_size(available.width(), available.height(), 1440, 900)
        self.resize(size.width, size.height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def retranslate(self) -> None:
        self.setWindowTitle(f"{version_info.APP_NAME} {version_info.APP_VERSION_DISPLAY}")
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site.name}")
        self.new_site_button.setText(self.i18n.t("site.new"))
        self.switch_site_button.setText(self.i18n.t("site.switch"))
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
        self._sync_theme_buttons()
        self.navigation.blockSignals(True)
        self.navigation.retranslate()
        self.navigation.blockSignals(False)
        for page in self.pages.values():
            retranslate = getattr(page, "retranslate", None)
            if callable(retranslate):
                retranslate()
        self._update_tray_text()

    def apply_style(self, theme: str) -> None:
        apply_global_theme(theme)

    def _system_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("systemPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        theme_row = QHBoxLayout()
        theme_row.addWidget(self.light_theme_button)
        theme_row.addWidget(self.dark_theme_button)
        layout.addLayout(theme_row)
        about_row = QHBoxLayout()
        about_row.addWidget(self.version_button, 1)
        about_row.addWidget(self.about_button)
        layout.addLayout(about_row)
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
        self.app_is_exiting = True
        background_task_manager.stop_all()
        QApplication.quit()
