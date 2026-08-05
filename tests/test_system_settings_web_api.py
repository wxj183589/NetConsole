from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api import system_settings_router
from netconsole.backend.api.main import create_app
from netconsole.core import settings as settings_module
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.i18n import TRANSLATIONS
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.external_tool_service import ExternalToolLaunchResult


TOKEN = "settings-test-session-token-123456"


def _runtime_updates(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "feature_id": item["feature_id"],
            "visible": item["visible"],
            "enabled": item["enabled"],
        }
        for item in items
    ]


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
                "putty": _exe(tmp_path, "PuTTY64.exe"),
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
    assert persisted["external_terminal/putty_path"].endswith("PuTTY64.exe")


def test_runtime_self_check_returns_safe_unicode_and_release_contract(tmp_path: Path) -> None:
    client, _paths = _client(tmp_path)

    response = client.get("/api/settings/self-check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["unicode_sample"] == "宁波地铁1号线 · 中文设备 · 任务已完成"
    assert payload["status"] in {"normal", "warning", "error"}
    checks = {item["check_id"]: item for item in payload["items"]}
    assert {
        "backend_executable",
        "build_contract",
        "production_feature_policy",
        "current_site",
        "data_root_writable",
        "tasks_database",
        "devices_database",
        "credential_storage",
        "tool_fping",
        "tool_iperf3",
        "unicode_round_trip",
    } <= checks.keys()
    assert str(_paths.data_root) not in response.text


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


def test_network_components_endpoint_supports_custom_and_builtin_modes(tmp_path: Path) -> None:
    client, paths = _client(tmp_path)
    initial = client.get("/api/settings/network-components")
    assert initial.status_code == 200
    snapshot = initial.json()
    assert [item["component_name"] for item in snapshot["components"]] == ["iperf3", "fping"]

    custom = _exe(tmp_path, "fping.exe")
    saved = client.put(
        "/api/settings/network-components/fping",
        json={"mode": "custom", "custom_path": custom, "expected_version": snapshot["version"]},
    )
    assert saved.status_code == 200
    fping = next(item for item in saved.json()["components"] if item["component_name"] == "fping")
    assert fping["mode"] == "custom"
    assert fping["source"] == "custom"
    assert fping["effective_path"].endswith("fping.exe")

    restored = client.put(
        "/api/settings/network-components/fping",
        json={"mode": "builtin", "custom_path": "", "expected_version": saved.json()["version"]},
    )
    assert restored.status_code == 200
    assert next(item for item in restored.json()["components"] if item["component_name"] == "fping")["mode"] == "builtin"
    persisted = json.loads(paths.settings_path.read_text(encoding="utf-8"))
    assert persisted["online_mr.fping_path"] == ""
    assert persisted["network_components/fping_mode"] == "builtin"

    stale = client.put(
        "/api/settings/network-components/fping",
        json={"mode": "builtin", "custom_path": "", "expected_version": snapshot["version"]},
    )
    assert stale.status_code == 409


def test_legacy_ipop_path_round_trips_without_blocking_other_settings(
    tmp_path: Path,
) -> None:
    client, paths = _client(tmp_path)
    initial = client.get("/api/settings").json()
    legacy_path = str((tmp_path / "removed" / "IPOP.EXE").resolve())

    response = client.put(
        "/api/settings",
        json={
            **initial["values"],
            "theme": "dark",
            "ipop_path": legacy_path,
            "expected_version": initial["version"],
        },
    )

    assert response.status_code == 200
    assert response.json()["values"]["ipop_path"] == legacy_path
    persisted = json.loads(paths.settings_path.read_text(encoding="utf-8"))
    assert persisted["external_tools/ipop_path"] == legacy_path


def test_ipop_native_action_uses_latest_cas_persisted_path(
    tmp_path: Path, monkeypatch
) -> None:
    client, _paths = _client(tmp_path)
    initial = client.get("/api/settings").json()
    selected = _exe(tmp_path, "IPOP.EXE")
    saved = client.put(
        "/api/settings",
        json={
            **initial["values"],
            "ipop_path": selected,
            "expected_version": initial["version"],
        },
    )
    assert saved.status_code == 200
    launched: list[str] = []

    def capture_launch(_paths, *, settings):
        launched.append(str(settings.get_value("external_tools/ipop_path", "")))
        return ExternalToolLaunchResult(True, "started", Path(selected))

    monkeypatch.setattr(system_settings_router, "launch_ipop", capture_launch)

    response = client.post(
        "/api/settings/native-action", json={"action": "launch_ipop"}
    )

    assert response.status_code == 200
    assert launched == [selected]


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

    updates = _runtime_updates(items)
    assert client.post("/api/settings/features/preview", json={"items": updates, "confirmed": False}).status_code == 422
    preview = client.post("/api/settings/features/preview", json={"items": updates, "confirmed": True})
    assert preview.status_code == 200
    effective = client.get("/api/features").json()["items"]
    assert next(item for item in effective if item["feature_id"] == "web.agent_management")["visible"] is False

    restored = client.post("/api/settings/features/restore", json={"confirmed": True})
    assert restored.status_code == 200
    assert restored.json()["preview_active"] is False
    customer_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert customer_profile["features"] == {}
    assert customer_profile["build_options"] == {"engineer_package": True}
    runtime_override = json.loads(
        (paths.runtime_dir / "feature_flags.local.json").read_text(encoding="utf-8")
    )
    assert runtime_override["features"] == {}


def test_feature_save_reloads_effective_gate_from_runtime_override(
    tmp_path: Path, monkeypatch
) -> None:
    client, _paths = _client(tmp_path)
    gate = client.app.state.feature_gate
    original_reload = gate.reload
    reload_count = 0

    def tracked_reload() -> None:
        nonlocal reload_count
        reload_count += 1
        original_reload()

    monkeypatch.setattr(gate, "reload", tracked_reload)
    snapshot = client.get("/api/settings/features").json()
    assert all(item["title"] for item in snapshot["items"])
    assert all(
        re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", item["title"])
        is None
        for item in snapshot["items"]
    )
    devices_module = next(
        item for item in snapshot["items"] if item["feature_id"] == "module.devices"
    )
    assert devices_module["title"] != "nav.devices"
    target = next(
        item for item in snapshot["items"] if item["feature_id"] == "web.agent_management"
    )
    assert target["group_title"] == "任务与 Agent"
    assert target["scope"] == "global"
    assert target["dependencies"] == ["web.job_center"]
    target.update({"visible": False, "enabled": True, "client_package": False})

    saved = client.put(
        "/api/settings/features",
        json={"items": _runtime_updates(snapshot["items"]), "confirmed": True},
    )

    assert saved.status_code == 200
    assert reload_count == 1
    saved_target = next(
        item for item in saved.json()["items"] if item["feature_id"] == "web.agent_management"
    )
    assert saved_target["client_package"] is True
    assert saved_target["package_range"] == "customer_internal"
    effective = client.get("/api/features").json()["items"]
    effective_target = next(
        item for item in effective if item["feature_id"] == "web.agent_management"
    )
    assert effective_target == {
        "feature_id": "web.agent_management",
        "visible": False,
        "enabled": True,
    }
    runtime_override = json.loads(
        (_paths.runtime_dir / "feature_flags.local.json").read_text(encoding="utf-8")
    )
    assert runtime_override["features"]["web.agent_management"] == {
        "visible": False,
        "enabled": True,
    }


def test_feature_update_rejects_release_fields(tmp_path: Path) -> None:
    client, _paths = _client(tmp_path)
    snapshot = client.get("/api/settings/features").json()

    response = client.put(
        "/api/settings/features",
        json={"items": snapshot["items"], "confirmed": True},
    )

    assert response.status_code == 422
    assert "client_package" in response.text


def test_feature_title_uses_readable_fallback_when_translation_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delitem(TRANSLATIONS["zh_CN"], "nav.devices")
    client, _paths = _client(tmp_path)

    snapshot = client.get("/api/settings/features").json()
    devices_module = next(
        item for item in snapshot["items"] if item["feature_id"] == "module.devices"
    )

    assert devices_module["title"] == "Devices"


def test_browser_runtime_cannot_read_or_write_settings(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    client = TestClient(create_app(RuntimeMode.SERVER, paths=paths), base_url="http://127.0.0.1")
    assert client.get("/api/settings").status_code == 403


def test_packaged_runtime_keeps_settings_but_rejects_feature_configuration(
    tmp_path: Path,
) -> None:
    client, _paths = _client(tmp_path)
    client.app.state.feature_gate = FeatureGate(tmp_path, packaged_runtime=True)

    assert client.get("/api/settings").status_code == 200
    for method, path, payload in (
        ("get", "/api/settings/features", None),
        ("put", "/api/settings/features", {"items": []}),
        ("post", "/api/settings/features/preview", {"items": []}),
        ("post", "/api/settings/features/restore", {"confirmed": True}),
    ):
        response = client.request(method, path, json=payload)
        assert response.status_code == 403
        assert "固定生产功能集" in response.json()["detail"]
