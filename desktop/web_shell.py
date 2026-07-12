from __future__ import annotations

import socket
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView

from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.version import APP_TITLE_DISPLAY


def _available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until_ready(url: str, timeout_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.05)
    raise RuntimeError("FastAPI 本地服务启动超时")


def run_web_shell() -> int:
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
    server_thread = threading.Thread(target=server.run, name="netconsole-web-api", daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{port}"
    _wait_until_ready(f"{base_url}/api/health")

    window = QMainWindow()
    window.setWindowTitle(f"{APP_TITLE_DISPLAY} - Web Shell")
    window.resize(1280, 800)
    browser = QWebEngineView(window)
    browser.setUrl(QUrl(base_url))
    window.setCentralWidget(browser)
    window.show()

    def stop_server() -> None:
        server.should_exit = True
        server_thread.join(timeout=5)

    qt_app.aboutToQuit.connect(stop_server)
    return qt_app.exec()
