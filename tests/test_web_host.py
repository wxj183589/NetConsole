from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from netconsole.backend.api.main import DESKTOP_SESSION_COOKIE, create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.launcher.web_server import DesktopWebServer


def _protected_app(tmp_path: Path, token: str = "desktop-test-token"):
    return create_app(
        RuntimeMode.DESKTOP,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing-dist",
        desktop_session_token=token,
    )


def test_desktop_web_requires_posted_session_token(tmp_path: Path) -> None:
    with TestClient(_protected_app(tmp_path)) as client:
        unauthorized = client.get("/api/health")
        invalid = client.post("/__desktop_session", data={"token": "wrong"})
        authorized = client.post("/__desktop_session", data={"token": "desktop-test-token"}, follow_redirects=False)

        assert unauthorized.status_code == 401
        assert invalid.status_code == 401
        assert authorized.status_code == 303
        assert DESKTOP_SESSION_COOKIE in authorized.cookies
        assert client.get("/api/health").status_code == 200


def test_desktop_web_rejects_websocket_without_session(tmp_path: Path) -> None:
    with TestClient(_protected_app(tmp_path)) as client:
        with pytest.raises(WebSocketDisconnect) as raised:
            with client.websocket_connect("/ws/tasks"):
                pass

    assert raised.value.code == 4401


def test_desktop_web_server_logs_frontend_identity_without_session_token(tmp_path: Path, monkeypatch) -> None:
    from netconsole.launcher import web_server

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(web_server.app_logger, "log_info", lambda event, message: messages.append((event, message)))
    server = DesktopWebServer(paths=PathResolver(tmp_path))
    bootstrap = server.bootstrap_html()

    assert server.base_url.startswith("http://127.0.0.1:")
    assert server.session_token
    assert server.session_token not in server.base_url
    assert 'method="post"' in bootstrap
    assert f'action="{server.base_url}/__desktop_session"' in bootstrap
    assert f'value="{server.session_token}"' in bootstrap
    event, message = next(item for item in messages if item[0] == "DESKTOP_WEB_FRONTEND_RESOURCE")
    assert event == "DESKTOP_WEB_FRONTEND_RESOURCE"
    assert all(field in message for field in ("frontend_root=", "index=", "frontend_build_id=", "backend_build_id=", "frontend_source_type="))
    assert server.session_token not in message
