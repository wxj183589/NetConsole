from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from netconsole.backend.api import main as api_main
from netconsole.backend.api.main import create_app
from netconsole.backend.web_build import FRONTEND_MISMATCH_MESSAGE, verified_frontend_commit
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.version import APP_VERSION
from scripts.build.web_frontend_meta import validate_web_frontend_meta


def _renderer_build_metadata(commit: str, *, dirty: bool = False) -> dict[str, object]:
    identity = f"{commit}-dirty" if dirty else commit
    return {
        "app_version": APP_VERSION,
        "product_version": APP_VERSION.removeprefix("v"),
        "build_number": 0,
        "file_version": f"{APP_VERSION.removeprefix('v')}.0",
        "git_commit": identity,
        "git_commit_full": commit,
        "git_commit_short": commit[:8],
        "build_time": "2026-08-14T00:00:00Z",
        "build_time_utc": "2026-08-14T00:00:00Z",
        "build_dirty": dirty,
        "build_source": "git-development" if dirty else "git-release",
        "frontend_commit": commit,
        "backend_commit": commit,
        "published": not dirty,
        "navigation_schema_version": 1,
        "build_id": f"{APP_VERSION}+{identity}",
    }


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("git_commit_full", "short"),
        ("git_commit_short", "deadbeef"),
        ("git_commit", "2" * 40),
        ("frontend_commit", "2" * 40),
        ("backend_commit", "2" * 40),
        ("build_dirty", "false"),
        ("build_id", f"{APP_VERSION}+{'2' * 40}"),
    ],
)
def test_verified_frontend_commit_rejects_internally_inconsistent_metadata(
    field: str,
    invalid: object,
) -> None:
    metadata = _renderer_build_metadata("1" * 40)
    metadata[field] = invalid

    assert verified_frontend_commit(metadata) == "unknown"


def test_verified_frontend_commit_accepts_clean_and_dirty_metadata() -> None:
    commit = "1" * 40

    assert verified_frontend_commit(_renderer_build_metadata(commit)) == commit
    assert verified_frontend_commit(_renderer_build_metadata(commit, dirty=True)) == commit


def test_source_mode_uses_only_current_project_desktop_renderer_dist(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathResolver(tmp_path)
    monkeypatch.setattr(api_main, "is_packaged_runtime", lambda: False)
    monkeypatch.setattr(
        api_main, "package_resource_path", lambda *_parts: tmp_path / "old-package-web"
    )

    assert api_main._frontend_dist(paths) == paths.app_root / "apps" / "desktop_renderer" / "dist"
    assert api_main._frontend_source_type() == "source"


def test_packaged_mode_uses_only_embedded_desktop_renderer_resources(
    tmp_path: Path, monkeypatch
) -> None:
    paths = PathResolver(tmp_path)
    packaged = tmp_path / "_internal" / "netconsole" / "assets" / "desktop_renderer"
    monkeypatch.setattr(api_main, "is_packaged_runtime", lambda: True)
    monkeypatch.setattr(api_main, "package_resource_path", lambda *_parts: packaged)

    assert api_main._frontend_dist(paths) == packaged
    assert api_main._frontend_source_type() == "packaged"


def test_missing_legacy_frontend_metadata_shows_rebuild_warning(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="app"></div></body></html>',
        encoding="utf-8",
    )
    app = create_app(
        RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist
    )

    with TestClient(app) as client:
        root = client.get("/")
        health = client.get("/api/health")

    assert root.status_code == 200
    assert FRONTEND_MISMATCH_MESSAGE in root.text
    assert health.json()["build_id"] == app.state.backend_build_id
    assert health.json()["frontend_commit"] == "unknown"
    assert app.state.frontend_source_type == "override"
    assert app.state.frontend_build_id == ""


def test_matching_frontend_metadata_serves_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    commit = "1" * 40
    build_id = f"{APP_VERSION}+{commit}"
    monkeypatch.setattr(
        "netconsole.backend.web_build.current_build_metadata",
        lambda _root: {"backend_commit": commit, "build_dirty": False},
    )
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="app">current</div></body></html>',
        encoding="utf-8",
    )
    (dist / "desktop-renderer-build-meta.json").write_text(
        json.dumps(
            {
                "app_version": APP_VERSION,
                "git_commit": commit,
                "build_time": "2026-07-15T00:00:00Z",
                "navigation_schema_version": 1,
                "build_id": build_id,
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist
    )

    with TestClient(app) as client:
        root = client.get("/")

    assert root.status_code == 200
    assert FRONTEND_MISMATCH_MESSAGE not in root.text
    assert app.state.frontend_build_id == build_id
    assert app.state.frontend_build_mismatch is False


def test_stale_frontend_metadata_still_gets_server_side_warning(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!doctype html><html><body class="legacy"><div id="app"></div></body></html>',
        encoding="utf-8",
    )
    (dist / "desktop-renderer-build-meta.json").write_text(
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
    app = create_app(
        RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist
    )

    with TestClient(app) as client:
        root = client.get("/")

    assert root.status_code == 200
    assert FRONTEND_MISMATCH_MESSAGE in root.text
    assert 'data-netconsole-build-warning="1"' in root.text
    assert app.state.frontend_build_mismatch is True


def test_health_and_backend_log_report_the_actual_stale_renderer_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_commit = "1" * 40
    renderer_commit = "2" * 40
    backend_metadata = {
        "app_version": APP_VERSION,
        "git_commit_full": backend_commit,
        "git_commit_short": backend_commit[:8],
        "build_time_utc": "2026-08-14T00:00:00Z",
        "build_dirty": False,
        "build_source": "git-release",
        "frontend_commit": backend_commit,
        "backend_commit": backend_commit,
    }
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>stale</body></html>", encoding="utf-8")
    (dist / "desktop-renderer-build-meta.json").write_text(
        json.dumps(_renderer_build_metadata(renderer_commit)),
        encoding="utf-8",
    )
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(api_main, "current_build_metadata", lambda _root: backend_metadata)
    monkeypatch.setattr(
        "netconsole.backend.web_build.current_build_metadata",
        lambda _root: backend_metadata,
    )
    monkeypatch.setattr(
        api_main.app_logger,
        "log_info",
        lambda event, detail="", **_kwargs: events.append((event, detail)),
    )

    app = create_app(RuntimeMode.SERVER, paths=PathResolver(tmp_path), frontend_dist=dist)
    with TestClient(app) as client:
        response = client.get("/api/health")

    identity_events = [detail for event, detail in events if event == "BUILD_IDENTITY"]
    assert response.status_code == 200
    assert response.json()["backend_commit"] == backend_commit
    assert response.json()["frontend_commit"] == renderer_commit
    assert app.state.frontend_build_mismatch is True
    assert len(identity_events) == 1
    assert f"backend_commit={backend_commit}" in identity_events[0]
    assert f"frontend_commit={renderer_commit}" in identity_events[0]


@pytest.mark.parametrize(
    ("feature_id", "path"),
    [
        ("module.fit_ap", "/api/ac-management/summary"),
        ("module.train_online", "/api/rail-transit/train-online/trains"),
        ("module.ground_unattended", "/api/rail-transit/ground-unattended/status"),
        ("module.task_center", "/api/job-center/summary"),
        ("module.agent", "/api/agents"),
        ("network_tools.traffic", "/api/traffic/runs"),
        ("module.rail_base_data", "/api/rail-transit/base-data/summary"),
        (
            "module.train_communication",
            "/api/rail-transit/train-communication/summary",
        ),
        ("module.mesh_analysis", "/api/rail-transit/mesh-analysis/summary"),
        (
            "capability.rail_transit.wireless_dashboard",
            "/api/rail-transit/wireless-dashboard/summary",
        ),
    ],
)
def test_disabled_web_page_cannot_bypass_backend_feature_gate(
    tmp_path: Path,
    feature_id: str,
    path: str,
) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )
    app.state.feature_gate.features[feature_id] = {"visible": False, "enabled": False}

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404


def test_disabled_network_toolbox_cannot_start_tcp_port_test(tmp_path: Path) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )
    app.state.feature_gate.features["capability.network_tools.toolbox"] = {
        "visible": False,
        "enabled": False,
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/network-tools/tcp-port-test",
            json={"target": "127.0.0.1", "port": 22},
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("feature_id", "path"),
    [
        ("module.agent", "/ws/agents"),
        ("network_tools.traffic", "/ws/traffic/missing-run"),
    ],
)
def test_disabled_web_page_cannot_bypass_websocket_feature_gate(
    tmp_path: Path,
    feature_id: str,
    path: str,
) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )
    app.state.feature_gate.features[feature_id] = {"visible": False, "enabled": False}

    with TestClient(app) as client, pytest.raises(WebSocketDenialResponse) as exc_info:
        with client.websocket_connect(path):
            pass

    assert exc_info.value.status_code == 404


def test_shared_task_api_stays_available_when_job_center_page_is_disabled(
    tmp_path: Path,
) -> None:
    app = create_app(
        RuntimeMode.SERVER,
        paths=PathResolver(tmp_path),
        frontend_dist=tmp_path / "missing",
    )
    app.state.feature_gate.features["module.task_center"] = {
        "visible": False,
        "enabled": False,
    }

    with TestClient(app) as client:
        response = client.get("/api/tasks")
        with client.websocket_connect("/ws/tasks") as websocket:
            snapshot = websocket.receive_json()

    assert response.status_code == 200
    assert snapshot["type"] == "snapshot"


def test_wave2_features_are_released_while_unimplemented_features_stay_hidden(
    tmp_path: Path,
) -> None:
    gate = FeatureGate(tmp_path)
    assert gate.is_visible("module.system_settings") is True
    assert gate.is_enabled("module.system_settings") is True
    assert gate.is_in_client_package("module.system_settings") is True

    assert gate.is_visible("internal.feature_switch") is True
    assert gate.is_enabled("internal.feature_switch") is True
    assert gate.is_in_client_package("internal.feature_switch") is False

    for feature_id in ("module.command_reference", "module.logs"):
        assert gate.is_visible(feature_id) is True
        assert gate.is_enabled(feature_id) is True
        assert gate.is_in_client_package(feature_id) is True


def test_release_validation_rejects_stale_frontend_metadata(tmp_path: Path) -> None:
    expected_commit = "1" * 40
    old_commit = "2" * 40
    (tmp_path / "index.html").write_text("web", encoding="utf-8")
    (tmp_path / "desktop-renderer-build-meta.json").write_text(
        json.dumps(
            {
                "app_version": APP_VERSION,
                "git_commit": old_commit,
                "git_commit_full": old_commit,
                "git_commit_short": old_commit[:8],
                "build_time": "2026-07-15T00:00:00Z",
                "build_time_utc": "2026-07-15T00:00:00Z",
                "build_dirty": False,
                "build_source": "git-release",
                "frontend_commit": old_commit,
                "backend_commit": old_commit,
                "navigation_schema_version": 1,
                "build_id": f"{APP_VERSION}+{old_commit}",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="构建身份与后端不一致"):
        validate_web_frontend_meta(
            tmp_path,
            expected_version=APP_VERSION,
            expected_commit=expected_commit,
        )


def test_current_product_architecture_contract_is_stable_and_resolvable() -> None:
    contract = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "architecture" / "product_architecture.json").read_text(
            encoding="utf-8"
        )
    )
    root = Path(__file__).resolve().parents[1]
    assert contract["product_model"] == "ELECTRON_DESKTOP_ONLY"
    assert contract["maintenance_state"] == "LONG_TERM_MAINTENANCE"
    assert contract["historical_migration"]["status"] == "CLOSED"
    assert all(root.joinpath(path).is_file() for item in contract["components"] for path in item["required_paths"])
    assert all(root.joinpath(path).is_file() for path in contract["authoritative_sources"].values())


def test_frozen_migration_archive_is_historical_only() -> None:
    archive = Path(__file__).resolve().parents[1] / "docs" / "archive" / "migrations" / "qt-to-electron" / "MIGRATION_MATRIX.md"
    text = archive.read_text(encoding="utf-8")
    assert "历史" in text
    assert "不作为后续当前状态源" in text


def test_module_migration_matrix_uses_canonical_states_and_electron_product() -> None:
    matrix = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "archive"
        / "migrations"
        / "qt-to-electron"
        / "MIGRATION_MATRIX.md"
    ).read_text(encoding="utf-8")
    for legacy_state in (
        "IN_PROGRESS",
        "CONTROLLED_WRITE",
        "FAKE_ACCEPTED",
        "FOUNDATION_READY",
        "FUTURE_REBUILD",
    ):
        assert f"`{legacy_state}`" not in matrix
    assert "Electron Main/Preload + Vue" in matrix
    assert "Browser" in matrix


def test_current_architecture_docs_do_not_reintroduce_legacy_parity_states() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    content = "\n".join(
        (docs_root / name).read_text(encoding="utf-8")
        for name in (
            "ARCHITECTURE.md",
            "architecture/DESKTOP.md",
            "architecture/RUNTIME.md",
            "architecture/COMPLIANCE.md",
            "archive/migrations/qt-to-electron/MIGRATION_MATRIX.md",
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
