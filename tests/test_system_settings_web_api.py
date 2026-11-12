from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api import system_settings_router
from netconsole.backend.api.main import create_app
from netconsole.core import settings as settings_module
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.external_tool_service import ExternalToolLaunchResult
from netconsole.services import runtime_self_check_service as self_check_module


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
        item for item in features.json()["items"] if item["feature_id"] == "module.system_settings"
    )
    assert settings_feature == {"feature_id": "module.system_settings", "visible": True, "enabled": True}
    internal_feature = next(
        item for item in features.json()["items"] if item["feature_id"] == "internal.feature_switch"
    )
    assert internal_feature == {"feature_id": "internal.feature_switch", "visible": True, "enabled": True}

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


def test_runtime_self_check_marks_slow_item_without_blocking_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _paths = _client(tmp_path)
    service = client.app.state.runtime_self_check_service
    monkeypatch.setattr(self_check_module, "SELF_CHECK_TIMEOUT_SECONDS", 0.05)
    original_tool = service._tool

    def slow_tool(name: str, title: str):
        time.sleep(0.2)
        return original_tool(name, title)

    monkeypatch.setattr(service, "_tool", slow_tool)
    started = time.perf_counter()

    snapshot = service.run(backend_build_id="", frontend_build_id="")

    elapsed = time.perf_counter() - started
    assert elapsed < 0.15
    timed_out = {
        item.check_id
        for item in snapshot.items
        if "超时" in item.message
    }
    assert {"tool_fping", "tool_iperf3"} <= timed_out


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


def test_retired_feature_delivery_endpoints_are_not_exposed(tmp_path: Path) -> None:
    client, _paths = _client(tmp_path)

    for method, path, payload in (
        ("get", "/api/settings/features", None),
        ("put", "/api/settings/features", {"items": []}),
        ("post", "/api/settings/features/check", {"items": []}),
        ("post", "/api/settings/features/auto-fix", {"items": []}),
        ("post", "/api/settings/features/preview", {"items": []}),
        ("post", "/api/settings/features/preview/exit", None),
        ("post", "/api/settings/features/restore", {"confirmed": True}),
        ("get", "/api/settings/features/runtime-status", None),
        ("post", "/api/settings/features/runtime-overrides/clear", {"confirmed": True}),
        ("post", "/api/settings/features/reload", None),
    ):
        response = client.request(method, path, json=payload)
        assert response.status_code == 404, (method, path, response.text)

    for method, path, payload in (
        ("get", "/api/features/edition", None),
        ("post", "/api/features/edition/unlock", {"password": "legacy"}),
        ("post", "/api/features/edition/lock", {}),
    ):
        response = client.request(method, path, json=payload)
        assert response.status_code == 404, (method, path, response.text)


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
    packaged_feature_ids = {
        item["feature_id"] for item in client.get("/api/features").json()["items"]
    }
    assert "internal.feature_switch" not in packaged_feature_ids
    for method, path, payload in (
        ("get", "/api/settings/features", None),
        ("put", "/api/settings/features", {"items": []}),
        ("post", "/api/settings/features/preview", {"items": []}),
        ("post", "/api/settings/features/restore", {"confirmed": True}),
    ):
        response = client.request(method, path, json=payload)
        assert response.status_code == 404
