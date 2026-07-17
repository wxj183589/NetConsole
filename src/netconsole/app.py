from __future__ import annotations

import sys
from time import perf_counter
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.admin import ADMIN_NETWORK_MANAGER_ARG
from netconsole.core.database import DatabaseSchemaMismatchError
from netconsole.core.i18n import I18n
from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.resources import icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core import version as version_info
from netconsole.services.site_database_recovery import SiteDatabaseRecoveryService
from netconsole.ui.widgets.startup_splash import StartupSplash

if TYPE_CHECKING:
    from netconsole.ui.main_window import MainWindow
    from netconsole.ui.web_host.web_server import DesktopWebServer


def _elapsed_detail(started_at: float) -> str:
    return f"elapsed_ms={int((perf_counter() - started_at) * 1000)}"


def build_window(
    started_at: float | None = None,
    *,
    web_server: DesktopWebServer | None = None,
) -> MainWindow:
    started_at = started_at or perf_counter()
    context = create_demo_context()
    app_logger.log_info("BOOT_DB_CORE_READY", f"site={context.site.name} {_elapsed_detail(started_at)}")
    i18n = I18n(SettingsStore(context.paths).language)
    from netconsole.ui.app_window_factory import create_app_window

    return create_app_window(
        site=context.site,
        repository=context.repository,
        i18n=i18n,
        paths=context.paths,
        startup_started_at=started_at,
        web_server=web_server,
    )


def open_admin_network_manager(window: MainWindow) -> None:
    page = window.get_or_create_page("network_tools")
    window.stack.setCurrentWidget(page)
    navigation = getattr(window, "navigation", None)
    find_page = getattr(navigation, "find_page", None)
    if callable(find_page):
        index = find_page("network_tools")
        if index >= 0:
            navigation.setCurrentRow(index)


def _start_app_auto_cleanup(window: object, paths: PathResolver) -> None:
    from netconsole.ui.app_auto_cleanup_runner import start_app_auto_cleanup

    start_app_auto_cleanup(window, paths)


def _handle_schema_mismatch(exc: DatabaseSchemaMismatchError, paths: PathResolver) -> str:
    message = QMessageBox()
    message.setWindowTitle("数据库无法自动升级")
    message.setIcon(QMessageBox.Warning)
    message.setText("当前数据库缺少基础元数据，无法安全自动升级。")
    message.setInformativeText(
        f"{exc}\n\n"
        "普通新增表、索引类更新会在启动时自动完成。"
        "如果看到此提示，说明该库过旧或结构不完整，需要先备份后重建。"
    )
    rebuild_button = message.addButton("备份并重建数据库", QMessageBox.AcceptRole)
    backup_button = message.addButton("仅备份", QMessageBox.ActionRole)
    message.addButton("取消", QMessageBox.RejectRole)
    message.exec()
    clicked = message.clickedButton()
    recovery_service = SiteDatabaseRecoveryService(paths)
    if clicked is rebuild_button:
        backups = recovery_service.backup_and_remove_databases()
        app_logger.log_info("DATABASE_REBUILT", f"backups={len(backups)}")
        return "rebuild"
    if clicked is backup_button:
        backups = recovery_service.backup_databases()
        QMessageBox.information(None, "数据库已备份", f"已备份 {len(backups)} 个数据库文件。")
        return "backup"
    return "cancel"


def run(*, web_server: DesktopWebServer | None = None) -> int:
    started_at = perf_counter()
    app = QApplication(sys.argv)
    app.setApplicationName(version_info.APP_NAME)
    app.setApplicationVersion(version_info.APP_VERSION_DISPLAY)
    app.setWindowIcon(QIcon(str(icon_path("love.ico"))))
    paths = PathResolver()
    settings = SettingsStore(paths)
    i18n = I18n(settings.language)
    splash = StartupSplash(i18n)
    splash.show_centered()
    splash.show_message(i18n.t("startup.loading_config"))
    splash.set_progress(10)
    app_logger.log_info("APP_START", _elapsed_detail(started_at))
    app_logger.log_info("BOOT_START", _elapsed_detail(started_at))
    app_logger.log_info("BOOT_CONFIG_LOADED", _elapsed_detail(started_at))
    startup_mode = settings.startup_mode
    app_logger.log_info("STARTUP", f"mode={startup_mode}")
    while True:
        try:
            if startup_mode == "preload_all":
                from netconsole.ui.startup_preload import StartupPreloadManager

                manager_kwargs = {"i18n": i18n, "splash": splash, "started_at": started_at}
                if web_server is not None:
                    manager_kwargs["web_server"] = web_server
                manager = StartupPreloadManager(**manager_kwargs)
                window = manager.run(startup_mode)
            else:
                splash.show_message(i18n.t("startup.loading_current_site"))
                splash.set_progress(25)
                window = build_window(started_at, web_server=web_server) if web_server is not None else build_window(started_at)
            break
        except DatabaseSchemaMismatchError as exc:
            splash.hide()
            action = _handle_schema_mismatch(exc, paths)
            if action == "rebuild":
                splash.show_centered()
                splash.show_message(i18n.t("app.initializing_site"))
                splash.set_progress(35)
                continue
            return 1
    app_logger.log_info("MAIN_WINDOW_CREATED", _elapsed_detail(started_at))
    app_logger.log_info("BOOT_MAIN_WINDOW_CREATED", _elapsed_detail(started_at))
    splash.show_message(i18n.t("startup.opening_main_window"))
    splash.set_progress(100 if startup_mode == "preload_all" else 80)
    log_geometry = getattr(window, "log_startup_geometry_checkpoint", None)
    if callable(log_geometry):
        log_geometry("before show")
    splash.show_message(i18n.t("startup.showing_main_window"))
    splash.set_progress(90)
    window.show()
    QTimer.singleShot(8000, lambda: _start_app_auto_cleanup(window, paths))
    app_logger.log_info("BOOT_BACKGROUND_TASKS_STARTED", f"task=app_auto_cleanup delay_ms=8000 {_elapsed_detail(started_at)}")
    schedule_geometry_checks = getattr(window, "schedule_startup_geometry_checks", None)
    if callable(schedule_geometry_checks):
        QTimer.singleShot(0, schedule_geometry_checks)
    if ADMIN_NETWORK_MANAGER_ARG in sys.argv:
        open_admin_network_manager(window)
    app_logger.log_info("MAIN_WINDOW_SHOWN", _elapsed_detail(started_at))
    app_logger.log_info("BOOT_MAIN_WINDOW_SHOWN", _elapsed_detail(started_at))
    splash.set_progress(100)
    splash.close_after_main_window_shown()
    return app.exec()
