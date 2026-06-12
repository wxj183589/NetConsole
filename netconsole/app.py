from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.i18n import I18n
from netconsole.ui.main_window import MainWindow


def build_window() -> MainWindow:
    context = create_demo_context()
    i18n = I18n()
    return MainWindow(site=context.site, repository=context.repository, i18n=i18n)


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("NetConsole")
    window = build_window()
    window.show()
    return app.exec()
