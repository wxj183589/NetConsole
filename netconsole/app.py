from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from time import sleep

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


def open_admin_network_manager(window: MainWindow) -> None:
    index = window.navigation.find_page("network_tools")
    if index >= 0:
        window.navigation.setCurrentRow(index)
    page = window.get_or_create_page("network_tools")
    window.stack.setCurrentWidget(page)
    tabs = getattr(page, "tabs", None)
    if tabs is not None and tabs.count() >= 3:
        tabs.setCurrentIndex(2)


def _site_database_paths(paths: PathResolver) -> list[Path]:
    if not paths.sites_dir.exists():
        return []
    return sorted(paths.sites_dir.glob("*/db/*.db"))


def _backup_site_databases(paths: PathResolver) -> list[Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups: list[Path] = []
    for database_path in _site_database_paths(paths):
        backup_dir = database_path.parents[1] / "db_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{database_path.stem}_{timestamp}{database_path.suffix}"
        shutil.copy2(database_path, backup_path)
        backups.append(backup_path)
    return backups


def _delete_site_databases(paths: PathResolver) -> None:
    for database_path in _site_database_paths(paths):
        for attempt in range(3):
            try:
                database_path.unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                sleep(0.2)


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
    if clicked is rebuild_button:
        backups = _backup_site_databases(paths)
        _delete_site_databases(paths)
        app_logger.log_info("DATABASE_REBUILT", f"backups={len(backups)}")
        return "rebuild"
    if clicked is backup_button:
        backups = _backup_site_databases(paths)
        QMessageBox.information(None, "数据库已备份", f"已备份 {len(backups)} 个数据库文件。")
        return "backup"
    return "cancel"


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
    paths = PathResolver()
    startup_mode = SettingsStore(paths).startup_mode
    app_logger.log_info("STARTUP", f"mode={startup_mode}")
    while True:
        try:
            if startup_mode == "preload_all":
                manager = StartupPreloadManager(i18n=i18n, splash=splash, started_at=started_at)
                window = manager.run(startup_mode)
            else:
                splash.show_message(i18n.t("app.initializing_site"))
                splash.set_progress(45)
                window = build_window(started_at)
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
    splash.show_message(i18n.t("startup.opening_main_window"))
    splash.set_progress(100 if startup_mode == "preload_all" else 80)
    window.show()
    if ADMIN_NETWORK_MANAGER_ARG in sys.argv:
        open_admin_network_manager(window)
    app_logger.log_info("MAIN_WINDOW_SHOWN", _elapsed_detail(started_at))
    splash.set_progress(100)
    splash.close_after_main_window_shown()
    return app.exec()
