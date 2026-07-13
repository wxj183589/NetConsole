from __future__ import annotations

import asyncio
import html
import json
import signal
import socket
import sys
import threading

import uvicorn
from PySide6.QtCore import QElapsedTimer, QTimer, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from netconsole.backend.api.main import create_app
from netconsole.core.app_logger import log_error, log_warning
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.version import APP_TITLE_DISPLAY


def _available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _same_origin(base_url: QUrl, target: QUrl) -> bool:
    return (
        target.scheme().casefold() == base_url.scheme().casefold()
        and target.host().casefold() == base_url.host().casefold()
        and target.port() == base_url.port()
    )


def _status_html(title: str, detail: str, retry_url: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{display:grid;place-items:center;min-height:100vh;margin:0;background:#f3f6fb;color:#172033;font-family:Segoe UI,Microsoft YaHei,sans-serif}}
main{{width:min(520px,calc(100vw - 48px));padding:36px;background:#fff;border:1px solid #dfe7f1;border-radius:14px;box-shadow:0 16px 44px #10213b14;text-align:center}}
h1{{font-size:22px;margin:0 0 12px}}p{{color:#64748b;line-height:1.7;margin:0 0 22px}}a{{display:inline-block;padding:9px 20px;border-radius:8px;background:#1677a8;color:#fff;text-decoration:none}}
</style></head><body><main><h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p><a href="{html.escape(retry_url, quote=True)}">重试</a></main></body></html>"""


def _stop_server(server: uvicorn.Server, server_thread: threading.Thread) -> None:
    server.should_exit = True
    server_thread.join(timeout=5)
    if server_thread.is_alive():
        server.force_exit = True
        server_thread.join(timeout=2)


def _run_server(server: uvicorn.Server) -> None:
    async def serve() -> None:
        loop = asyncio.get_running_loop()

        def handle_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
            error = context.get("exception")
            if isinstance(error, ConnectionResetError) and getattr(error, "winerror", None) == 10054:
                return
            current_loop.default_exception_handler(context)

        loop.set_exception_handler(handle_exception)
        await server.serve()

    asyncio.run(serve())


class WebShellPage(QWebEnginePage):
    def __init__(self, base_url: QUrl, parent: QWebEngineView) -> None:
        super().__init__(parent)
        self._base_url = base_url

    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        is_external_link = (
            is_main_frame
            and navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            and not _same_origin(self._base_url, url)
        )
        if is_external_link:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    def createWindow(self, _window_type: QWebEnginePage.WebWindowType) -> QWebEnginePage:
        return self

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        detail = f"{source_id}:{line_number} {message}"
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            log_error("WEB_SHELL_JAVASCRIPT", detail)
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
            log_warning("WEB_SHELL_CONSOLE", detail)


class WebShellWindow(QMainWindow):
    def __init__(
        self,
        server: uvicorn.Server,
        server_thread: threading.Thread,
        base_url: str,
        *,
        startup_timeout_ms: int = 8_000,
        smoke_test: bool = False,
        window_size: tuple[int, int] = (1280, 800),
    ) -> None:
        super().__init__()
        self.server = server
        self.server_thread = server_thread
        self.base_url = QUrl(base_url)
        self.startup_timeout_ms = startup_timeout_ms
        self.smoke_test = smoke_test
        self.smoke_failed = False
        self._status_page_pending = False
        self._closing = False
        self._close_scheduled = False
        self._smoke_routes = ("/", "/tasks", "/agents", "/network-tools/traffic")
        self._smoke_index = 0

        self.setWindowTitle(f"{APP_TITLE_DISPLAY} - Web Shell")
        self.resize(*window_size)
        self.browser = QWebEngineView(self)
        self.browser.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.browser.setPage(WebShellPage(self.base_url, self.browser))
        self.browser.loadFinished.connect(self._on_load_finished)
        self.setCentralWidget(self.browser)

        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._startup_timer = QTimer(self)
        self._startup_timer.setInterval(50)
        self._startup_timer.timeout.connect(self._poll_server)
        self._startup_timer.start()
        self._show_status("NetConsole Web 服务启动中", "正在启动本地 FastAPI，请稍候。")

    def _poll_server(self) -> None:
        if self.server.started:
            if self._status_page_pending:
                return
            self._startup_timer.stop()
            self.browser.setUrl(self.base_url)
            return
        if not self.server_thread.is_alive():
            self._startup_timer.stop()
            self._show_failure("本地 Web 服务启动失败，请重试。")
            return
        if self._elapsed.elapsed() >= self.startup_timeout_ms:
            self._startup_timer.stop()
            self._show_failure("本地 Web 服务启动超时，请重试。")

    def _on_load_finished(self, ok: bool) -> None:
        if self._closing:
            self._schedule_close(500)
            return
        if self._status_page_pending:
            self._status_page_pending = False
            return
        if not ok:
            self._show_failure("Vue 页面加载失败，请确认本地 Web 服务状态后重试。")
            return
        if self.smoke_test:
            QTimer.singleShot(300, self._capture_smoke_route)

    def _capture_smoke_route(self) -> None:
        expected = self._smoke_routes[self._smoke_index]
        script = """JSON.stringify({
            route: location.pathname,
            app: Boolean(document.querySelector('#app')),
            title: document.title,
            text: document.body.innerText.slice(0, 200)
        })"""

        def captured(value: object) -> None:
            try:
                payload = json.loads(str(value or "{}"))
            except (TypeError, json.JSONDecodeError):
                payload = {}
            valid = bool(payload.get("app")) and str(payload.get("route") or "") == expected
            state = "OK" if valid else "FAIL"
            print(f"[{state}] web-shell {json.dumps(payload, ensure_ascii=False)}", flush=True)
            if not valid:
                self.smoke_failed = True
                self.begin_shutdown()
                return
            self._smoke_index += 1
            if self._smoke_index >= len(self._smoke_routes):
                self.begin_shutdown()
                return
            self._navigate_smoke_route(self._smoke_routes[self._smoke_index])

        self.browser.page().runJavaScript(script, captured)

    def _navigate_smoke_route(self, route: str) -> None:
        encoded_route = json.dumps(route)
        script = f"""(() => {{
            const route = {encoded_route};
            const link = Array.from(document.querySelectorAll('a')).find(item => item.pathname === route);
            if (!link) return false;
            link.click();
            return true;
        }})()"""

        def navigated(value: object) -> None:
            if value is True:
                QTimer.singleShot(300, self._capture_smoke_route)
                return
            self.browser.setUrl(self.base_url.resolved(QUrl(route)))

        self.browser.page().runJavaScript(script, navigated)

    def _show_failure(self, detail: str) -> None:
        log_error("WEB_SHELL_LOAD_FAILED", detail)
        self._show_status("NetConsole Web 页面暂不可用", detail)
        if self.smoke_test:
            self.smoke_failed = True
            QTimer.singleShot(0, self.begin_shutdown)

    def _show_status(self, title: str, detail: str) -> None:
        self._status_page_pending = True
        self.browser.setHtml(_status_html(title, detail, self.base_url.toString()), self.base_url)

    def begin_shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.browser.stop()
        self.browser.setUrl(QUrl("about:blank"))
        QTimer.singleShot(2_000, self._finish_close)

    def _schedule_close(self, delay_ms: int) -> None:
        if self._close_scheduled:
            return
        self._close_scheduled = True
        QTimer.singleShot(delay_ms, self._finish_close)

    def _finish_close(self) -> None:
        if self.isVisible():
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        event.ignore()
        self.begin_shutdown()


def run_web_shell(*, smoke_test: bool = False, window_size: tuple[int, int] = (1280, 800)) -> int:
    qt_app = QApplication(sys.argv)
    port = _available_local_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(RuntimeMode.DESKTOP),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server_thread = threading.Thread(target=_run_server, args=(server,), name="netconsole-web-api", daemon=True)
    window = WebShellWindow(
        server,
        server_thread,
        f"http://127.0.0.1:{port}",
        smoke_test=smoke_test,
        window_size=window_size,
    )
    server_thread.start()
    window.show()

    signal_timer = QTimer()
    signal_timer.setInterval(250)
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start()
    previous_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda *_args: window.begin_shutdown())
    qt_app.aboutToQuit.connect(lambda: _stop_server(server, server_thread))
    try:
        result = qt_app.exec()
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        _stop_server(server, server_thread)
    return 1 if window.smoke_failed else result
