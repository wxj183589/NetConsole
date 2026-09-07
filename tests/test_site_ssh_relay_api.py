from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services import site_ssh_relay


TOKEN = "site-ssh-relay-session-token-123456"


def _client(tmp_path: Path) -> tuple[TestClient, PathResolver]:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    app = create_app(
        RuntimeMode.DESKTOP,
        paths=paths,
        desktop_session_token=TOKEN,
        api_documentation_enabled=True,
    )
    return (
        TestClient(
            app,
            base_url="http://127.0.0.1",
            headers={"X-NetConsole-Session": TOKEN},
        ),
        paths,
    )


def _fake_protect(data: bytes, _entropy: bytes) -> bytes:
    return bytes(value ^ 0x5A for value in data)


def test_site_ssh_relay_api_defaults_off_without_creating_credential_db(
    tmp_path: Path,
) -> None:
    client, paths = _client(tmp_path)
    with client:
        response = client.get("/api/v1/sites/demo/ssh-relay")

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert response.json()["password_configured"] is False
    assert not (paths.site_dir("demo") / "db" / "site_ssh_credentials.sqlite3").exists()


def test_site_ssh_relay_api_persists_non_secret_config_and_dpapi_ciphertext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_ssh_relay, "protect_windows_data", _fake_protect)
    monkeypatch.setattr(site_ssh_relay, "unprotect_windows_data", lambda data, _entropy: _fake_protect(data, b""))
    client, paths = _client(tmp_path)
    with client:
        response = client.put(
            "/api/v1/sites/demo/ssh-relay",
            json={
                "enabled": True,
                "host": "10.81.40.10",
                "port": 22,
                "username": "jump",
                "password": "jump-secret",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["enabled"] is True
        assert payload["password_configured"] is True
        assert "jump-secret" not in response.text

        loaded = client.get("/api/v1/sites/demo/ssh-relay")
        assert loaded.status_code == 200, loaded.text
        assert loaded.json()["host"] == "10.81.40.10"
        assert "jump-secret" not in loaded.text

    metadata = json.loads(
        (paths.site_dir("demo") / "site_meta.json").read_text(encoding="utf-8")
    )
    assert metadata["ssh_relay_username"] == "jump"
    assert "jump-secret" not in json.dumps(metadata, ensure_ascii=False)


def test_site_ssh_relay_api_is_site_scoped(tmp_path: Path) -> None:
    client, _paths = _client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/sites",
            json={"site_id": "line-2", "display_name": "二号线"},
        )
        assert created.status_code == 201, created.text
        demo = client.get("/api/v1/sites/demo/ssh-relay")
        other = client.get("/api/v1/sites/line-2/ssh-relay")

    assert demo.status_code == 200
    assert other.status_code == 200
    assert demo.json()["site_id"] == "demo"
    assert other.json()["site_id"] == "line-2"
    assert demo.json()["enabled"] is False
    assert other.json()["enabled"] is False
