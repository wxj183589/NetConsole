from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.i18n import I18n
from netconsole.core import app_logger
from netconsole.core.resources import icon_path
from netconsole.core.version import APP_VERSION
from netconsole.ui.main_window import MainWindow


def build_window() -> MainWindow:
    context = create_demo_context()
    i18n = I18n()
    return MainWindow(site=context.site, repository=context.repository, i18n=i18n, paths=context.paths)


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("NetConsole")
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(icon_path("love.ico"))))
    app_logger.log_info("APP_START", "软件启动")
    window = build_window()
    window.show()
    return app.exec()
