from __future__ import annotations

import html
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.version import APP_TITLE_DISPLAY

if TYPE_CHECKING:
    from netconsole.ui.web_host.web_server import DesktopWebServer

try:
    if os.environ.get("NETCONSOLE_QT_WEBENGINE_AVAILABLE") == "0":
        raise ImportError("Qt WebEngine capability probe failed")
    from PySide6.QtWebEngineWidgets import QWebEngineView
except (ImportError, OSError):  # pragma: no cover - depends on packaged Qt components
    QWebEngineView = None  # type: ignore[assignment,misc]


def _status_html(title: str, detail: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head>
<body style="font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:48px">
<h2>{html.escape(title)}</h2><p>{html.escape(detail)}</p></body></html>"""


class BrowserHostWidget(QWidget):
    def __init__(self, server: DesktopWebServer, paths: PathResolver, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.server = server
        self.paths = paths
        self._temporary_bootstrap_files: list[Path] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.browser = None
        if QWebEngineView is not None:
            try:
                self.browser = QWebEngineView(self)
                self.browser.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
                self.browser.setHtml(_status_html("NetConsole Web 服务启动中", "正在启动本地服务，请稍候。"))
            except Exception as exc:  # pragma: no cover - depends on packaged Qt runtime
                app_logger.log_warning("DESKTOP_WEBENGINE_UNAVAILABLE", str(exc))
                self.browser = None

        if self.browser is not None:
            layout.addWidget(self.browser)
            self.external_button = None
        else:
            self.browser = None
            message = QLabel("当前环境没有 Qt WebEngine，将使用系统默认浏览器打开 NetConsole Web。")
            message.setWordWrap(True)
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.external_button = QPushButton("在浏览器中打开")
            self.external_button.setEnabled(False)
            self.external_button.clicked.connect(self.open_external_browser)
            layout.addStretch(1)
            layout.addWidget(message)
            layout.addWidget(self.external_button, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addStretch(1)

        self._startup_timer = QTimer(self)
        self._startup_timer.setInterval(50)
        self._startup_timer.timeout.connect(self._poll_server)
        self._startup_timer.start()

    def _poll_server(self) -> None:
        if self.server.started:
            self._startup_timer.stop()
            if self.browser is not None:
                self.browser.setHtml(self.server.bootstrap_html(), QUrl(self.server.base_url))
            elif self.external_button is not None:
                self.external_button.setEnabled(True)
                self.open_external_browser()
            return
        if not self.server.thread_alive:
            self._startup_timer.stop()
            if self.browser is not None:
                self.browser.setHtml(_status_html("NetConsole Web 启动失败", "本地服务未能启动，请查看应用日志。"))
            app_logger.log_error("DESKTOP_WEB_HOST_START_FAILED", "server thread stopped before startup")

    def open_external_browser(self) -> None:
        if not self.server.started:
            return
        self.paths.runtime_cache_dir.mkdir(parents=True, exist_ok=True)
        bootstrap_path = self.paths.runtime_cache_dir / f"web-console-{self.server.port}.html"
        bootstrap_path.write_text(self.server.bootstrap_html(), encoding="utf-8")
        if bootstrap_path not in self._temporary_bootstrap_files:
            self._temporary_bootstrap_files.append(bootstrap_path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(bootstrap_path)))
        QTimer.singleShot(60_000, lambda path=bootstrap_path: self._remove_bootstrap_file(path))

    def _remove_bootstrap_file(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            app_logger.log_warning("DESKTOP_WEB_BOOTSTRAP_CLEANUP_FAILED", str(exc))
        if path in self._temporary_bootstrap_files:
            self._temporary_bootstrap_files.remove(path)

    def suspend(self) -> None:
        self._startup_timer.stop()
        if self.browser is not None:
            self.browser.stop()
            self.browser.setUrl(QUrl("about:blank"))

    def resume(self) -> None:
        if self.server.started:
            if self.browser is not None:
                self.browser.setHtml(self.server.bootstrap_html(), QUrl(self.server.base_url))
            return
        self._startup_timer.start()

    def shutdown(self) -> None:
        self.suspend()
        for path in list(self._temporary_bootstrap_files):
            self._remove_bootstrap_file(path)


class _BrowserHostWindow(QMainWindow):
    def __init__(self, server: DesktopWebServer, paths: PathResolver) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE_DISPLAY} - Web")
        self.resize(1360, 860)
        self.setMinimumSize(1024, 680)
        self.host_widget = BrowserHostWidget(server, paths, self)
        self.setCentralWidget(self.host_widget)

    def closeEvent(self, event) -> None:
        self.host_widget.suspend()
        event.accept()


class WebConsoleHost(QObject):
    def __init__(
        self,
        *,
        paths: PathResolver,
        server: DesktopWebServer | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.server = server
        self._owns_server = server is None
        self.window: _BrowserHostWindow | None = None

    def open(self) -> None:
        if self.server is None:
            from netconsole.ui.web_host.web_server import DesktopWebServer

            self.server = DesktopWebServer(paths=self.paths)
        self.server.start()
        if self.window is None:
            self.window = _BrowserHostWindow(self.server, self.paths)
        self.window.host_widget.resume()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def stop(self) -> None:
        if self.window is not None:
            self.window.host_widget.shutdown()
            self.window.close()
            self.window = None
        if self.server is not None and self._owns_server:
            self.server.stop()
            self.server = None
