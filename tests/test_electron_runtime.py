from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import DESKTOP_SESSION_HEADER
from netconsole.backend.electron_runtime import (
    ElectronRuntimeOptions,
    build_app,
    emit_shutdown_ack,
    parse_options,
    read_session_token,
    wait_for_exit_command,
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
        development=False,
    )


def test_electron_runtime_accepts_explicit_loopback_development_mode() -> None:
    options = parse_options(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--renderer-origin",
            "http://127.0.0.1:5173",
            "--dev-mode",
        ]
    )

    assert options == ElectronRuntimeOptions(
        host="127.0.0.1",
        port=8000,
        renderer_origin="http://127.0.0.1:5173",
        development=True,
    )


def test_packaged_electron_runtime_rejects_development_mode(monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    monkeypatch.setattr(electron_runtime, "is_packaged_runtime", lambda: True)

    with pytest.raises(SystemExit):
        parse_options(["--host", "127.0.0.1", "--port", "8000", "--dev-mode"])


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


def test_shutdown_ack_is_emitted_as_bounded_json_event() -> None:
    output = io.StringIO()

    emit_shutdown_ack(output)

    assert json.loads(output.getvalue()) == {
        "event": "netconsole.electron_backend.shutdown_ack"
    }


def test_exit_command_wait_ignores_unknown_messages_and_eof() -> None:
    wait_for_exit_command(io.StringIO('not-json\n{"command":"unknown"}\n{"command":"exit"}\n'))
    wait_for_exit_command(io.StringIO(""))


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
    assert response.json()["data_root"]
    assert response.json()["active_site_id"]
    assert response.json()["storage_schema_version"] == 1
    assert response.json()["status"] == "ok"


def test_electron_runtime_does_not_publish_api_documentation(tmp_path, monkeypatch) -> None:
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
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = client.get(path, headers={DESKTOP_SESSION_HEADER: TOKEN})
            assert response.status_code == 404
        assert client.get(
            "/api/dev/runtime-status",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        ).status_code == 404

    assert app.state.api_documentation_enabled is False


def test_electron_development_runtime_is_authenticated_and_redacted(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(
        ElectronRuntimeOptions(
            "127.0.0.1",
            8000,
            "http://127.0.0.1:5173",
            development=True,
        ),
        TOKEN,
    )

    with TestClient(app, client=("127.0.0.1", 50123)) as client:
        assert client.get("/api/dev/runtime-status").status_code == 401
        response = client.get(
            "/api/dev/runtime-status",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )
        session = client.post(
            "/api/dev/session",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )
        cookie_status = client.get("/api/dev/runtime-status")
        docs = client.get("/openapi.json")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_mode"] == "electron-development"
    assert body["frontend_mode"] == "vite"
    assert body["data_root"] == "<redacted>"
    assert body["storage_mode"] == "persistent"
    assert body["data_root_kind"] == "persistent"
    assert body["persistent"] is True
    assert str(tmp_path) not in response.text
    assert TOKEN not in response.text
    assert session.status_code == 204
    set_cookie = session.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/" in set_cookie
    assert cookie_status.status_code == 200
    assert docs.status_code == 200
    assert app.state.api_documentation_enabled is True


def test_electron_development_api_rejects_non_loopback_client(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(
        ElectronRuntimeOptions("127.0.0.1", 8000, development=True),
        TOKEN,
    )

    with TestClient(app, client=("192.0.2.10", 50123)) as client:
        response = client.get(
            "/api/dev/runtime-status",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )

    assert response.status_code == 403


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
