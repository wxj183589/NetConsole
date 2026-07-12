from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.services.app_auto_cleanup import APP_CLEANUP_RETENTION_DAYS, AppCleanupResult, run_app_auto_cleanup


class AppAutoCleanupThread(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, paths: PathResolver, retention_days: int = APP_CLEANUP_RETENTION_DAYS) -> None:
        super().__init__()
        self.paths = paths
        self.retention_days = retention_days

    def run(self) -> None:
        try:
            self.result_ready.emit(run_app_auto_cleanup(self.paths, self.retention_days))
        except Exception as exc:
            from netconsole.core import app_logger

            app_logger.log_warning("APP_AUTO_CLEANUP_FAILED", str(exc))
            self.failed.emit(str(exc))


def start_app_auto_cleanup(owner: object, paths: PathResolver, retention_days: int = APP_CLEANUP_RETENTION_DAYS) -> bool:
    current = getattr(owner, "_app_auto_cleanup_thread", None)
    if current is not None and current.isRunning():
        return False
    thread = AppAutoCleanupThread(paths, retention_days)
    setattr(owner, "_app_auto_cleanup_thread", thread)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda: setattr(owner, "_app_auto_cleanup_thread", None))
    thread.start()
    return True
