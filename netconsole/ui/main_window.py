from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.resources import icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import Site, SiteManager
from netconsole.core.version import APP_VERSION
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.dialogs.about_dialog import AboutRepositoryDialog
from netconsole.ui.dialogs.changelog_dialog import ChangelogDialog
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.ac_management_page import AcManagementPage
from netconsole.ui.pages.app_log_page import AppLogPage
from netconsole.ui.pages.device_management_page import DeviceManagementPage
from netconsole.ui.theme import apply_global_theme
from netconsole.ui.window_manager import window_manager
from netconsole.ui.windowing import fit_default_window_size


class MainWindow(QMainWindow):
    def __init__(self, site: Site, repository: DeviceRepository, i18n: I18n, paths: PathResolver) -> None:
        super().__init__()
        self.paths = paths
        self.site_manager = SiteManager(paths)
        self.settings = SettingsStore(paths)
        self.site = site
        self.repository = repository
        self.i18n = i18n
        self.current_theme = self.settings.theme
        self.about_dialog: AboutRepositoryDialog | None = None
        self.changelog_dialog: ChangelogDialog | None = None

        self.navigation = Navigation(i18n)
        self.stack = QStackedWidget()
        self.device_page = DeviceManagementPage(repository, i18n, site.name)
        self.ac_page = AcManagementPage(repository, i18n, site.name)
        self.log_page = AppLogPage(i18n)
        self.stack.addWidget(self.device_page)
        self.stack.addWidget(self.ac_page)
        self.stack.addWidget(self.log_page)

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
        window_manager.set_main_window(self)
        app_logger.log_info("DEVICE_PAGE_OPENED", self.site.name)

    def open_current_page(self, row: int) -> None:
        if row < 0:
            return
        page_id = self.navigation.item(row).data(256)
        if page_id == "logs":
            self.log_page.refresh()
            self.stack.setCurrentWidget(self.log_page)
            app_logger.log_info("LOG_PAGE_OPENED", self.site.name)
        elif page_id == "ac":
            self.ac_page.refresh_devices()
            self.stack.setCurrentWidget(self.ac_page)
            app_logger.log_info("AC_PAGE_OPENED", self.site.name)
        else:
            self.stack.setCurrentWidget(self.device_page)
            app_logger.log_info("DEVICE_PAGE_OPENED", self.site.name)

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
        self.ac_page.set_repository(self.repository, site.name)
        self.site_label.setText(f"{self.i18n.t('site.current')}: {self.site.name}")

    def switch_language(self, language: str) -> None:
        self.i18n.set_language(language)
        app_logger.log_info("LANGUAGE_CHANGED", language)
        self.retranslate()

    def set_theme(self, theme: str) -> None:
        self.current_theme = theme
        self.settings.set_theme(theme)
        self.apply_style(theme)
        self._sync_theme_buttons()
        app_logger.log_info("THEME_CHANGED", theme)

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
        app_logger.log_info("APP_EXIT", "软件关闭")
        super().closeEvent(event)

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
        self.setWindowTitle(f"{self.i18n.t('app.title')} {APP_VERSION}")
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
        self.version_button.setText(APP_VERSION)
        self.version_button.setToolTip(self.i18n.t("changelog.open"))
        self._sync_theme_buttons()
        self.navigation.retranslate()
        self.device_page.retranslate()
        self.ac_page.retranslate()
        self.log_page.retranslate()

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
