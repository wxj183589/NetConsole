from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage

from apps.desktop import web_shell
from apps.desktop.web_shell import WebShellPage, _same_origin, _status_html, _stop_server


class _FakeServer:
    should_exit = False
    force_exit = False


class _FakeThread:
    def __init__(self) -> None:
        self.joins: list[float | None] = []

    def join(self, timeout: float | None = None) -> None:
        self.joins.append(timeout)

    def is_alive(self) -> bool:
        return len(self.joins) < 2


def test_web_shell_status_page_has_retry_without_business_bridge() -> None:
    value = _status_html("服务启动中", "请稍候", "http://127.0.0.1:8000")

    assert "重试" in value
    assert "http://127.0.0.1:8000" in value
    assert "startTraffic" not in value
    assert "startMR" not in value


def test_web_shell_only_keeps_same_origin_inside_qwebengine() -> None:
    base = QUrl("http://127.0.0.1:8000")

    assert _same_origin(base, QUrl("http://127.0.0.1:8000/tasks"))
    assert not _same_origin(base, QUrl("https://example.com"))
    assert not _same_origin(base, QUrl("http://127.0.0.1:9000"))


def test_web_shell_server_shutdown_escalates_after_grace_period() -> None:
    server = _FakeServer()
    thread = _FakeThread()

    _stop_server(server, thread)  # type: ignore[arg-type]

    assert server.should_exit is True
    assert server.force_exit is True
    assert thread.joins == [5, 2]


def test_web_shell_does_not_expose_business_qwebchannel_bridge() -> None:
    source = (Path(__file__).resolve().parents[1] / "apps" / "desktop" / "web_shell.py").read_text(encoding="utf-8")

    assert "QWebChannel" not in source
    assert "startTraffic" not in source
    assert "startMR" not in source


def test_web_shell_records_javascript_errors(monkeypatch) -> None:
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(web_shell, "log_error", lambda event, detail: recorded.append((event, detail)))

    WebShellPage.javaScriptConsoleMessage(
        object(),  # type: ignore[arg-type]
        QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel,
        "boom",
        12,
        "app.js",
    )

    assert recorded == [("WEB_SHELL_JAVASCRIPT", "app.js:12 boom")]
