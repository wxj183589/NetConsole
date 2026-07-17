from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core import settings as settings_module
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode


TOKEN = "settings-test-session-token-123456"


def _client(tmp_path: Path) -> tuple[TestClient, PathResolver]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    app = create_app(RuntimeMode.DESKTOP, paths=paths, desktop_session_token=TOKEN)
    return TestClient(
        app, base_url="http://127.0.0.1", headers={"X-NetConsole-Session": TOKEN}
    ), paths


def _exe(tmp_path: Path, name: str) -> str:
    path = tmp_path / "tools" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"MZ")
    return str(path.resolve())


def test_default_desktop_profile_reaches_settings_and_round_trips(tmp_path: Path) -> None:
    client, paths = _client(tmp_path)
    features = client.get("/api/features")
    settings_feature = next(
        item for item in features.json()["items"] if item["feature_id"] == "web.system_settings"
    )
    assert settings_feature == {"feature_id": "web.system_settings", "visible": True, "enabled": True}

    initial = client.get("/api/settings")
    assert initial.status_code == 200
    body = initial.json()
    values = body["values"]
    values.update(
        {
            "theme": "dark",
            "language": "en_US",
            "theme_color": "#2563EB",
            "iperf_path": _exe(tmp_path, "iperf3.exe"),
            "fping_path": _exe(tmp_path, "Fping_v3.exe"),
            "ipop_path": _exe(tmp_path, "IPOP.EXE"),
            "terminal_type": "xshell",
            "terminal_paths": {
                "securecrt": _exe(tmp_path, "SecureCRT.exe"),
                "xshell": _exe(tmp_path, "Xshell.exe"),
                "putty": _exe(tmp_path, "putty.exe"),
            },
            "securecrt_sessions_root": str(tmp_path.resolve()),
            "ssh_port": 2222,
            "telnet_port": 2323,
            "crt_encoding": "GBK",
        }
    )
    saved = client.put("/api/settings", json={**values, "expected_version": body["version"]})
    assert saved.status_code == 200
    assert saved.json()["values"] == values
    assert saved.json()["language_status"] == "BLOCKED_ON_GLOBAL_I18N"

    persisted = json.loads(paths.settings_path.read_text(encoding="utf-8"))
    assert persisted["external_terminal/xshell_path"].endswith("Xshell.exe")
    assert persisted["external_terminal/securecrt_path"].endswith("SecureCRT.exe")
    assert persisted["external_terminal/putty_path"].endswith("putty.exe")


def test_rejects_malicious_tool_paths_and_stale_versions(tmp_path: Path) -> None:
    client, _paths = _client(tmp_path)
    first = client.get("/api/settings").json()
    bad = _exe(tmp_path, "cmd.exe")
    response = client.put(
        "/api/settings",
        json={**first["values"], "iperf_path": bad, "expected_version": first["version"]},
    )
    assert response.status_code == 422

    update = {**first["values"], "theme": "dark", "expected_version": first["version"]}
    assert client.put("/api/settings", json=update).status_code == 200
    stale = {**first["values"], "theme": "light", "expected_version": first["version"]}
    assert client.put("/api/settings", json=stale).status_code == 409
    assert client.get("/api/settings").json()["values"]["theme"] == "dark"


def test_corrupt_settings_are_not_overwritten_and_return_503(tmp_path: Path) -> None:
    client, paths = _client(tmp_path)
    paths.settings_path.parent.mkdir(parents=True, exist_ok=True)
    original = b"{broken-json"
    paths.settings_path.write_bytes(original)

    assert client.get("/api/settings").status_code == 503
    assert paths.settings_path.read_bytes() == original


def test_failed_api_save_rolls_back_service_get_and_disk(
    tmp_path: Path, monkeypatch
) -> None:
    client, paths = _client(tmp_path)
    initial = client.get("/api/settings").json()
    saved = client.put(
        "/api/settings",
        json={
            **initial["values"],
            "theme": "dark",
            "expected_version": initial["version"],
        },
    ).json()
    original = paths.settings_path.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(settings_module.os, "replace", fail_replace)
    failed = client.put(
        "/api/settings",
        json={
            **saved["values"],
            "language": "en_US",
            "expected_version": saved["version"],
        },
    )

    assert failed.status_code == 503
    assert paths.settings_path.read_bytes() == original
    current = client.get("/api/settings").json()
    assert current["values"]["theme"] == "dark"
    assert current["values"]["language"] == "zh_CN"
    assert current["version"] == saved["version"]


def test_feature_switch_preview_and_restore_use_real_gate(tmp_path: Path) -> None:
    client, paths = _client(tmp_path)
    profile_path = paths.app_root / "config/profiles/features/customer.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "customer",
                "build_options": {"engineer_package": True},
                "features": {},
            }
        ),
        encoding="utf-8",
    )
    snapshot = client.get("/api/settings/features")
    assert snapshot.status_code == 200
    items = snapshot.json()["items"]
    target = next(item for item in items if item["feature_id"] == "web.agent_management")
    target.update({"visible": False, "enabled": False, "client_package": False})
    settings_target = next(
        item for item in items if item["feature_id"] == "web.system_settings"
    )
    settings_target.update(
        {"visible": False, "enabled": False, "client_package": False}
    )

    assert client.post("/api/settings/features/preview", json={"items": items, "confirmed": False}).status_code == 422
    preview = client.post("/api/settings/features/preview", json={"items": items, "confirmed": True})
    assert preview.status_code == 200
    effective = client.get("/api/features").json()["items"]
    assert next(item for item in effective if item["feature_id"] == "web.agent_management")["visible"] is False

    restored = client.post("/api/settings/features/restore", json={"confirmed": True})
    assert restored.status_code == 200
    assert restored.json()["preview_active"] is False
    customer_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    restored_target = customer_profile["features"]["web.agent_management"]
    assert restored_target["visible"] is True
    assert restored_target["enabled"] is True
    assert customer_profile["build_options"] == {"engineer_package": True}


def test_browser_runtime_cannot_read_or_write_settings(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    client = TestClient(create_app(RuntimeMode.SERVER, paths=paths), base_url="http://127.0.0.1")
    assert client.get("/api/settings").status_code == 403
