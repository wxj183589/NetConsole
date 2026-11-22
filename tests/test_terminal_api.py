from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.terminal_router import router
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.terminal_profiles import TerminalProfileStore


PROFILE_VALUES = {
    "name": "LAB-SW",
    "host": "192.0.2.10",
    "port": 22,
    "protocol": "SSH",
    "username": "operator",
    "encoding": "gb18030",
    "vendor": "H3C",
    "device_type": "SW",
    "folder_id": "",
    "favorite": True,
}


class _Manager:
    def __init__(self, profiles: TerminalProfileStore) -> None:
        self.profiles = profiles
        self.received_passwords: list[str] = []

    def create_quick_session(self, _values, *, password: str, cols: int, rows: int):
        self.received_passwords.append(password)
        return (
            {
                "session_id": "session-a",
                "device_name": "LAB-SW",
                "cols": cols,
                "rows": rows,
            },
            SimpleNamespace(ticket="ticket-a", expires_at_ms=123),
        )

    def create_profile_session(
        self,
        profile_id: str,
        *,
        password_override: str,
        cols: int,
        rows: int,
    ):
        _profile, password = self.profiles.resolve(profile_id, password_override)
        return self.create_quick_session({}, password=password, cols=cols, rows=rows)


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, _Manager]:
    monkeypatch.setattr(
        "netconsole.services.terminal_profiles.protect_windows_data",
        lambda value, entropy: b"encrypted:" + entropy + b":" + value,
    )
    monkeypatch.setattr(
        "netconsole.services.terminal_profiles.unprotect_windows_data",
        lambda value, entropy: value.removeprefix(b"encrypted:" + entropy + b":"),
    )
    profiles = TerminalProfileStore(
        PathResolver(
            app_root=tmp_path / "app",
            data_root=tmp_path / "data",
            runtime_root=tmp_path / "runtime",
        )
    )
    manager = _Manager(profiles)
    app = FastAPI()
    app.state.terminal_session_manager = manager
    app.include_router(router, prefix="/api")
    return TestClient(app), manager


def test_quick_connect_and_saved_profile_api_never_return_plaintext_password(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    client, manager = _client(tmp_path, monkeypatch)
    password = "api-secret-value"

    response = client.post(
        "/api/terminal/sessions/quick-connect",
        json={
            **PROFILE_VALUES,
            "password": password,
            "save_profile": True,
            "remember_password": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["password_configured"] is True
    assert password not in json.dumps(body, ensure_ascii=False)
    assert password not in caplog.text
    assert manager.received_passwords == [password]
    assert password not in manager.profiles.path.read_text(encoding="utf-8")
    assert password not in manager.profiles.secret_path.read_text(encoding="utf-8")

    listed = client.get("/api/terminal/profiles")
    assert listed.status_code == 200
    assert password not in json.dumps(listed.json(), ensure_ascii=False)


def test_password_is_redacted_from_terminal_api_error_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, manager = _client(tmp_path, monkeypatch)
    password = "do-not-echo-this"

    def fail(_values, *, password: str, cols: int, rows: int):
        del cols, rows
        raise ValueError(f"connection failed with password {password}")

    manager.create_quick_session = fail
    response = client.post(
        "/api/terminal/sessions/quick-connect",
        json={
            **PROFILE_VALUES,
            "password": password,
            "save_profile": False,
            "remember_password": False,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "connection failed with password [REDACTED]"
    assert password not in response.text


def test_console_feature_gate_is_independent_from_device_management(tmp_path: Path) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )
    app.state.feature_gate.features["module.devices"]["enabled"] = True
    app.state.feature_gate.features["module.console"]["enabled"] = False

    with TestClient(app) as client:
        console = client.get("/api/terminal/settings")
        devices = client.get("/api/device-management/devices")

    assert console.status_code == 404
    assert devices.status_code == 200
