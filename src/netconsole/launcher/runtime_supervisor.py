from __future__ import annotations

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.launcher.web_server import DesktopWebServer


class RuntimeSupervisor:
    def __init__(
        self,
        host_mode: RuntimeMode,
        *,
        paths: PathResolver | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
    ) -> None:
        self.host_mode = host_mode
        self.paths = paths or PathResolver()
        self.web_server = DesktopWebServer(
            paths=self.paths,
            runtime_mode=host_mode,
            host=host,
            port=port,
            protect_session=host_mode is RuntimeMode.DESKTOP,
        )

    @property
    def base_url(self) -> str:
        return self.web_server.base_url

    def start(self, timeout_seconds: float = 8.0) -> bool:
        self.web_server.start()
        started = self.web_server.wait_started(timeout_seconds)
        event = "CORE_RUNTIME_STARTED" if started else "CORE_RUNTIME_START_FAILED"
        log = app_logger.log_info if started else app_logger.log_error
        log(event, f"host_mode={self.host_mode.value} base_url={self.base_url}")
        return started

    def wait(self) -> int:
        try:
            while self.web_server.thread_alive:
                self.web_server.thread.join(timeout=0.25)
        except KeyboardInterrupt:
            return 0
        return 0 if self.web_server.server.should_exit else 1

    def stop(self) -> None:
        self.web_server.stop()
        app_logger.log_info("CORE_RUNTIME_STOPPED", f"host_mode={self.host_mode.value}")
