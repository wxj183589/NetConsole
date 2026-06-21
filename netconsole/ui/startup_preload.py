from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from PySide6.QtWidgets import QApplication

from netconsole.core import app_logger
from netconsole.core.bootstrap import AppContext, create_demo_context
from netconsole.core.i18n import I18n
from netconsole.core.settings import SettingsStore
from netconsole.ui.main_window import MainWindow
from netconsole.ui.widgets.startup_splash import StartupSplash


@dataclass(frozen=True)
class StartupTask:
    task_id: str
    message_key: str
    weight: int
    run: Callable[[], None]
    can_fail: bool = True


class StartupPreloadManager:
    def __init__(self, i18n: I18n, splash: StartupSplash, started_at: float | None = None) -> None:
        self.i18n = i18n
        self.splash = splash
        self.started_at = started_at or perf_counter()
        self.context: AppContext | None = None
        self.window: MainWindow | None = None
        self.failed_tasks: dict[str, str] = {}
        self.settings: SettingsStore | None = None

    def run(self, mode: str = "preload_all") -> MainWindow:
        app_logger.log_info("STARTUP", f"mode={mode}")
        tasks = self._tasks_for_mode(mode)
        total_weight = max(sum(task.weight for task in tasks), 1)
        completed_weight = 0
        for task in tasks:
            self._show_progress(task.message_key, completed_weight, total_weight)
            started = perf_counter()
            app_logger.log_info("STARTUP_TASK_STARTED", f"task={task.task_id}")
            try:
                task.run()
                elapsed_ms = int((perf_counter() - started) * 1000)
                app_logger.log_info("STARTUP_TASK_FINISHED", f"task={task.task_id} status=success elapsed_ms={elapsed_ms}")
            except Exception as exc:
                elapsed_ms = int((perf_counter() - started) * 1000)
                self.failed_tasks[task.task_id] = str(exc)
                app_logger.log_error("STARTUP_TASK_FINISHED", f"task={task.task_id} status=failed elapsed_ms={elapsed_ms} error={exc}")
                if not task.can_fail:
                    raise
            completed_weight += task.weight
            self._show_progress(task.message_key, completed_weight, total_weight)
        if self.window is None:
            raise RuntimeError("MainWindow was not created")
        self.window.mark_preload_failures(self.failed_tasks)
        app_logger.log_info("STARTUP", f"main_window_ready elapsed_ms={self._elapsed_ms()}")
        return self.window

    def _tasks_for_mode(self, mode: str) -> list[StartupTask]:
        tasks = [
            StartupTask("load_current_site", "startup.loading_current_site", 10, self._load_current_site, can_fail=False),
            StartupTask("create_main_window", "startup.initializing_database", 15, self._create_main_window, can_fail=False),
        ]
        if mode == "preload_all":
            tasks.extend(
                [
                    StartupTask("preload_device_management", "startup.loading_device_management", 10, lambda: self._preload_page("devices")),
                    StartupTask("preload_ac_management", "startup.loading_ac_management", 14, lambda: self._preload_page("ac")),
                    StartupTask("preload_rail_transit", "startup.loading_rail_transit", 18, lambda: self._preload_page("rail_transit")),
                    StartupTask("preload_config_center", "startup.loading_config_center", 12, lambda: self._preload_page("config_collection")),
                    StartupTask("preload_file_management", "startup.loading_file_management", 10, lambda: self._preload_page("file_management")),
                    StartupTask("preload_network_tools", "startup.loading_network_tools", 10, lambda: self._preload_page("network_tools")),
                    StartupTask("preload_run_logs", "startup.loading_run_logs", 8, lambda: self._preload_page("logs")),
                ]
            )
        tasks.append(StartupTask("show_main_window", "startup.opening_main_window", 3, self._prepare_main_window, can_fail=False))
        return tasks

    def _load_current_site(self) -> None:
        self.context = create_demo_context()
        self.settings = SettingsStore(self.context.paths)
        app_logger.log_info("SITE_LOADED", f"site={self.context.site.name} elapsed_ms={self._elapsed_ms()}")

    def _create_main_window(self) -> None:
        if self.context is None:
            self._load_current_site()
        assert self.context is not None
        self.window = MainWindow(
            site=self.context.site,
            repository=self.context.repository,
            i18n=self.i18n,
            paths=self.context.paths,
            startup_started_at=self.started_at,
        )

    def _preload_page(self, page_id: str) -> None:
        if self.window is None:
            self._create_main_window()
        assert self.window is not None
        self.window.preload_page(page_id)

    def _prepare_main_window(self) -> None:
        if self.window is None:
            self._create_main_window()

    def _show_progress(self, message_key: str, completed_weight: int, total_weight: int) -> None:
        percent = int((completed_weight / total_weight) * 100)
        self.splash.show_message(self.i18n.t(message_key))
        self.splash.set_progress(percent)
        QApplication.processEvents()

    def _elapsed_ms(self) -> int:
        return int((perf_counter() - self.started_at) * 1000)
