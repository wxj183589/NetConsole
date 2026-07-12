from __future__ import annotations

import sys
from time import perf_counter

from PySide6.QtWidgets import QWidget

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.sites import Site
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.main_window import MainWindow
from netconsole.ui.shell.fluent_bridge import FLUENT_RUNTIME, fluent_available


def create_app_window(
    *,
    site: Site,
    repository: DeviceRepository,
    i18n: I18n,
    paths: PathResolver,
    startup_started_at: float | None = None,
) -> QWidget:
    started_at = startup_started_at or perf_counter()
    if fluent_available():
        try:
            from netconsole.ui.app_fluent_window import AppFluentWindow

            window = AppFluentWindow(site, repository, i18n, paths, started_at)
            app_logger.log_info("MAIN_WINDOW_CLASS", window.__class__.__name__)
            print(f"[NetConsole] MAIN_WINDOW_CLASS={window.__class__.__name__}", file=sys.stderr)
            return window
        except Exception as exc:
            detail = f"class=MainWindow reason={exc.__class__.__name__}: {exc}"
            app_logger.log_error("FLUENT_WINDOW_FALLBACK", detail)
            print(f"[NetConsole] FLUENT_WINDOW_FALLBACK {detail}", file=sys.stderr)
    else:
        detail = f"class=MainWindow reason=qfluentwidgets_unavailable:{FLUENT_RUNTIME.error}"
        app_logger.log_warning("FLUENT_WINDOW_FALLBACK", detail)
        print(f"[NetConsole] FLUENT_WINDOW_FALLBACK {detail}", file=sys.stderr)
    window = MainWindow(site=site, repository=repository, i18n=i18n, paths=paths, startup_started_at=started_at)
    app_logger.log_info("MAIN_WINDOW_CLASS", window.__class__.__name__)
    return window
