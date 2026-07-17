from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from netconsole.backend.api import main as api_main
from netconsole.backend.api.main import create_app
from netconsole.backend.web_build import FRONTEND_MISMATCH_MESSAGE
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.version import APP_VERSION, GIT_COMMIT
from scripts.build.web_frontend_meta import validate_web_frontend_meta


def test_source_mode_uses_only_current_project_web_dist(tmp_path: Path, monkeypatch) -> None:
    paths = PathResolver(tmp_path)
    monkeypatch.setattr(api_main, "is_packaged_runtime", lambda: False)
    monkeypatch.setattr(api_main, "package_resource_path", lambda *_parts: tmp_path / "old-package-web")

    assert api_main._frontend_dist(paths) == paths.app_root / "apps" / "web" / "dist"
    assert api_main._frontend_source_type() == "source"


def test_packaged_mode_uses_only_embedded_web_resources(tmp_path: Path, monkeypatch) -> None:
    paths = PathResolver(tmp_path)
    packaged = tmp_path / "_internal" / "netconsole" / "assets" / "web"
    monkeypatch.setattr(api_main, "is_packaged_runtime", lambda: True)
    monkeypatch.setattr(api_main, "package_resource_path", lambda *_parts: packaged)

    assert api_main._frontend_dist(paths) == packaged
    assert api_main._frontend_source_type() == "packaged"


def test_missing_legacy_frontend_metadata_shows_rebuild_warning(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><body><div id=\"app\"></div></body></html>", encoding="utf-8")
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist)

    with TestClient(app) as client:
        root = client.get("/")
        health = client.get("/api/health")

    assert root.status_code == 200
    assert FRONTEND_MISMATCH_MESSAGE in root.text
    assert health.json()["build_id"] == app.state.backend_build_id
    assert app.state.frontend_source_type == "override"
    assert app.state.frontend_build_id == ""


def test_matching_frontend_metadata_serves_clean_index(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    build_id = f"{APP_VERSION}+{GIT_COMMIT}"
    (dist / "index.html").write_text("<!doctype html><html><body><div id=\"app\">current</div></body></html>", encoding="utf-8")
    (dist / "web-build-meta.json").write_text(
        json.dumps(
            {
                "app_version": APP_VERSION,
                "git_commit": GIT_COMMIT,
                "build_time": "2026-07-15T00:00:00Z",
                "navigation_schema_version": 1,
                "build_id": build_id,
            }
        ),
        encoding="utf-8",
    )
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist)

    with TestClient(app) as client:
        root = client.get("/")

    assert root.status_code == 200
    assert FRONTEND_MISMATCH_MESSAGE not in root.text
    assert app.state.frontend_build_id == build_id
    assert app.state.frontend_build_mismatch is False


def test_stale_frontend_metadata_still_gets_server_side_warning(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><body class=\"legacy\"><div id=\"app\"></div></body></html>", encoding="utf-8")
    (dist / "web-build-meta.json").write_text(
        json.dumps(
            {
                "app_version": APP_VERSION,
                "git_commit": "old-commit",
                "build_time": "2026-07-15T00:00:00Z",
                "navigation_schema_version": 1,
                "build_id": f"{APP_VERSION}+old-commit",
            }
        ),
        encoding="utf-8",
    )
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist)

    with TestClient(app) as client:
        root = client.get("/")

    assert root.status_code == 200
    assert FRONTEND_MISMATCH_MESSAGE in root.text
    assert 'data-netconsole-build-warning="1"' in root.text
    assert app.state.frontend_build_mismatch is True


@pytest.mark.parametrize(
    ("feature_id", "path"),
    [
        ("web.ac_fit_ap_resources", "/api/ac-management/summary"),
        ("web.ac_mesh_links", "/api/ac-management/mesh-links/summary"),
        ("web.job_center", "/api/job-center/summary"),
        ("web.agent_management", "/api/agents"),
        ("network_tools.traffic", "/api/traffic/runs"),
        ("web.rail_transit_base_data", "/api/rail-transit/base-data/summary"),
        ("web.train_communication_monitoring", "/api/rail-transit/train-communication/summary"),
        ("web.mesh_analysis", "/api/rail-transit/mesh-analysis/summary"),
        ("web.rail_transit_wireless_dashboard", "/api/rail-transit/wireless-dashboard/summary"),
    ],
)
def test_disabled_web_page_cannot_bypass_backend_feature_gate(
    tmp_path: Path,
    feature_id: str,
    path: str,
) -> None:
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features[feature_id] = {"visible": False, "enabled": False}

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404


def test_disabled_network_toolbox_cannot_start_tcp_port_test(tmp_path: Path) -> None:
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features["web.network_tools_toolbox"] = {"visible": False, "enabled": False}

    with TestClient(app) as client:
        response = client.post(
            "/api/network-tools/tcp-port-test",
            json={"target": "127.0.0.1", "port": 22},
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("feature_id", "path"),
    [
        ("web.agent_management", "/ws/agents"),
        ("network_tools.traffic", "/ws/traffic/missing-run"),
    ],
)
def test_disabled_web_page_cannot_bypass_websocket_feature_gate(
    tmp_path: Path,
    feature_id: str,
    path: str,
) -> None:
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features[feature_id] = {"visible": False, "enabled": False}

    with TestClient(app) as client, pytest.raises(WebSocketDenialResponse) as exc_info:
        with client.websocket_connect(path):
            pass

    assert exc_info.value.status_code == 404


def test_shared_task_api_stays_available_when_job_center_page_is_disabled(tmp_path: Path) -> None:
    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features["web.job_center"] = {"visible": False, "enabled": False}

    with TestClient(app) as client:
        response = client.get("/api/tasks")
        with client.websocket_connect("/ws/tasks") as websocket:
            snapshot = websocket.receive_json()

    assert response.status_code == 200
    assert snapshot["type"] == "snapshot"


def test_unimplemented_web_features_are_registered_but_hidden(tmp_path: Path) -> None:
    gate = FeatureGate(tmp_path)
    for feature_id in (
        "web.ac_trackside_ap_plan",
        "web.network_tools_wireless_scan",
        "web.command_reference",
        "web.logs",
        "web.system_settings",
        "web.feature_switch",
    ):
        assert gate.is_visible(feature_id) is False
        assert gate.is_enabled(feature_id) is False
        assert gate.is_in_client_package(feature_id) is False


def test_release_validation_rejects_stale_frontend_metadata(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("web", encoding="utf-8")
    (tmp_path / "web-build-meta.json").write_text(
        json.dumps(
            {
                "app_version": APP_VERSION,
                "git_commit": "old-commit",
                "build_time": "2026-07-15T00:00:00Z",
                "navigation_schema_version": 1,
                "build_id": f"{APP_VERSION}+old-commit",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="构建身份与后端不一致"):
        validate_web_frontend_meta(
            tmp_path,
            expected_version=APP_VERSION,
            expected_commit=GIT_COMMIT,
        )


def test_parity_matrix_covers_fixed_modules_and_allowed_states() -> None:
    matrix = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "development"
        / "qt-electron-parity-matrix.md"
    ).read_text(encoding="utf-8")
    for title in (
        "设备管理",
        "AC 管理",
        "轨道交通",
        "配置采集中心",
        "文件管理",
        "网络工具",
        "命令说明",
        "日志中心",
        "系统设置",
        "功能开关",
        "SNMP Center",
        "无线勘测",
        "无线扫描",
    ):
        assert title in matrix
    for state in (
        "NOT_STARTED",
        "UI_ONLY",
        "READ_ONLY",
        "FAKE",
        "PARTIAL",
        "IMPLEMENTED_UNVERIFIED",
        "REAL_DEVICE_PENDING",
        "COMPLETE",
        "BLOCKED",
    ):
        assert state in matrix
    for legacy_state in (
        "IN_PROGRESS",
        "CONTROLLED_WRITE",
        "FAKE_ACCEPTED",
        "FOUNDATION_READY",
        "FUTURE_REBUILD",
    ):
        assert f"`{legacy_state}`" not in matrix
    assert "| 设备管理 | 设备管理 |" in matrix
    assert "| `IMPLEMENTED_UNVERIFIED` |" in matrix


def test_module_migration_matrix_uses_canonical_states_and_electron_product() -> None:
    matrix = (
        Path(__file__).resolve().parents[1] / "docs" / "WEB_MIGRATION_MATRIX.md"
    ).read_text(encoding="utf-8")
    for legacy_state in (
        "IN_PROGRESS",
        "CONTROLLED_WRITE",
        "FAKE_ACCEPTED",
        "FOUNDATION_READY",
        "FUTURE_REBUILD",
    ):
        assert f"`{legacy_state}`" not in matrix
    assert "先将 Electron 设为默认入口" in matrix
    assert "普通浏览器只保留源码开发、诊断和 API 联调用途" in matrix


def test_current_architecture_docs_do_not_reintroduce_legacy_parity_states() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    content = "\n".join(
        (docs_root / name).read_text(encoding="utf-8")
        for name in (
            "ARCHITECTURE_NEXT.md",
            "ELECTRON_DESKTOP.md",
            "WEB_ARCHITECTURE.md",
            "WEB_MIGRATION_PLAN.md",
            "WEB_MIGRATION_MATRIX.md",
        )
    )
    for legacy_state in (
        "FOUNDATION_READY",
        "EXCLUDED/FUTURE_REBUILD",
        "FAKE_ACCEPTED",
        "CONTROLLED_WRITE",
        "IN_PROGRESS",
    ):
        assert legacy_state not in content
