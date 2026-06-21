from __future__ import annotations

import sys
from time import perf_counter

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.i18n import I18n
from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.resources import icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core import version as version_info
from netconsole.ui.main_window import MainWindow
from netconsole.ui.startup_preload import StartupPreloadManager
from netconsole.ui.widgets.startup_splash import StartupSplash


def _elapsed_detail(started_at: float) -> str:
    return f"elapsed_ms={int((perf_counter() - started_at) * 1000)}"


def build_window(started_at: float | None = None) -> MainWindow:
    started_at = started_at or perf_counter()
    context = create_demo_context()
    app_logger.log_info("SITE_LOADED", f"site={context.site.name} {_elapsed_detail(started_at)}")
    i18n = I18n()
    return MainWindow(site=context.site, repository=context.repository, i18n=i18n, paths=context.paths, startup_started_at=started_at)


def run() -> int:
    started_at = perf_counter()
    app = QApplication(sys.argv)
    app.setApplicationName(version_info.APP_NAME)
    app.setApplicationVersion(version_info.APP_VERSION_DISPLAY)
    app.setWindowIcon(QIcon(str(icon_path("love.ico"))))
    i18n = I18n()
    splash = StartupSplash(i18n)
    splash.show_centered()
    splash.show_message(i18n.t("app.starting"))
    splash.set_progress(15)
    app_logger.log_info("APP_START", _elapsed_detail(started_at))
    startup_mode = SettingsStore(PathResolver()).startup_mode
    app_logger.log_info("STARTUP", f"mode={startup_mode}")
    if startup_mode == "preload_all":
        manager = StartupPreloadManager(i18n=i18n, splash=splash, started_at=started_at)
        window = manager.run(startup_mode)
    else:
        splash.show_message(i18n.t("app.initializing_site"))
        splash.set_progress(45)
        window = build_window(started_at)
    app_logger.log_info("MAIN_WINDOW_CREATED", _elapsed_detail(started_at))
    splash.show_message(i18n.t("startup.opening_main_window"))
    splash.set_progress(100 if startup_mode == "preload_all" else 80)
    window.show()
    app_logger.log_info("MAIN_WINDOW_SHOWN", _elapsed_detail(started_at))
    splash.set_progress(100)
    splash.close_after_main_window_shown()
    return app.exec()
