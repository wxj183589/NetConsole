from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import DESKTOP_SESSION_HEADER
from netconsole.backend.electron_runtime import (
    ElectronRuntimeOptions,
    build_app,
    parse_options,
    read_session_token,
    watch_control_stream,
)


TOKEN = "electron-test-token-abcdefghijklmnopqrstuvwxyz"


def test_electron_runtime_accepts_only_loopback_configuration() -> None:
    options = parse_options(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--renderer-origin",
            "http://127.0.0.1:5173",
        ]
    )

    assert options == ElectronRuntimeOptions(
        host="127.0.0.1",
        port=0,
        renderer_origin="http://127.0.0.1:5173",
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--host", "0.0.0.0", "--port", "43123"],
        ["--port", "-1"],
        ["--port", "43123", "--renderer-origin", "https://127.0.0.1:5173"],
        ["--port", "43123", "--renderer-origin", "http://localhost:5173"],
        ["--port", "43123", "--renderer-origin", "http://127.0.0.1:5173/path"],
    ],
)
def test_electron_runtime_rejects_unsafe_configuration(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_options(arguments)


def test_session_token_is_read_from_bounded_stdin_json() -> None:
    assert read_session_token(io.StringIO(f'{{"session_token":"{TOKEN}"}}\n')) == TOKEN


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not-json\n",
        '{"session_token":"short"}\n',
        '{"session_token":"contains spaces and is deliberately long enough"}\n',
    ],
)
def test_session_token_rejects_invalid_handshake(payload: str) -> None:
    with pytest.raises(ValueError):
        read_session_token(io.StringIO(payload))


def test_control_stream_requests_shutdown_and_ignores_unknown_messages() -> None:
    server = SimpleNamespace(should_exit=False)
    watch_control_stream(
        io.StringIO('not-json\n{"command":"unknown"}\n{"command":"shutdown"}\n'),
        server,
    )

    assert server.should_exit is True


def test_control_stream_eof_also_requests_shutdown() -> None:
    server = SimpleNamespace(should_exit=False)
    watch_control_stream(io.StringIO(""), server)

    assert server.should_exit is True


def test_electron_runtime_authenticates_http_with_ephemeral_header(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(ElectronRuntimeOptions("127.0.0.1", 43123), TOKEN)

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        response = client.get(
            "/api/health",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_electron_runtime_cors_is_limited_to_declared_vite_origin(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(
        ElectronRuntimeOptions("127.0.0.1", 43123, "http://127.0.0.1:5173"),
        TOKEN,
    )

    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": DESKTOP_SESSION_HEADER,
            },
        )
        denied = client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": DESKTOP_SESSION_HEADER,
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in denied.headers
