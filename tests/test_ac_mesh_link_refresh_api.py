from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support.ac_mesh_link_web_fixture import build_ac_mesh_link_fixture
from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.services.ac.mesh_link_refresh_service import AcMeshLinkRefreshStart


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _RefreshService(_NoopAsyncService):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start_refresh(self, **values) -> AcMeshLinkRefreshStart:
        self.calls.append(values)
        now = datetime.now(UTC).isoformat()
        return AcMeshLinkRefreshStart(
            TaskSnapshot(
                task_id="refresh-1",
                task_type="ac_mesh_link_refresh",
                task_name="AC Mesh-Link 刷新",
                status=TaskState.RUNNING,
                created_time=now,
                updated_time=now,
            )
        )


class _ResidentRefreshService(_RefreshService):
    def start_refresh(self, **values) -> AcMeshLinkRefreshStart:
        result = super().start_refresh(**values)
        return AcMeshLinkRefreshStart(
            task=result.task,
            resident=True,
            request_id="acpollreq-1",
        )


def _client(tmp_path: Path, refresh: _RefreshService) -> TestClient:
    paths, _devices, _mesh = build_ac_mesh_link_fixture(tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        ac_mesh_link_refresh_service=refresh,  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    return TestClient(app)


def test_refresh_api_accepts_only_controller_and_history_flag(tmp_path: Path) -> None:
    refresh = _RefreshService()
    with _client(tmp_path, refresh) as client:
        response = client.post(
            "/api/ac-management/mesh-links/refresh",
            json={"controller_id": "ac-1", "include_switch_history": True},
        )
        train_response = client.post(
            "/api/rail-transit/train-online/refresh",
            json={"controller_id": "ac-1", "include_switch_history": False},
        )
        rejected = client.post(
            "/api/ac-management/mesh-links/refresh",
            json={"controller_id": "ac-1", "command": "system-view", "password": "secret"},
        )

    assert response.status_code == 202
    assert response.json()["task_id"] == "refresh-1"
    assert train_response.status_code == 202
    assert train_response.json()["task_id"] == "refresh-1"
    assert refresh.calls == [
        {"site_name": "demo", "controller_id": "ac-1", "include_switch_history": True},
        {"site_name": "demo", "controller_id": "ac-1", "include_switch_history": False},
    ]
    assert rejected.status_code == 422


def test_refresh_api_reports_resident_immediate_request(tmp_path: Path) -> None:
    refresh = _ResidentRefreshService()
    with _client(tmp_path, refresh) as client:
        response = client.post(
            "/api/ac-management/mesh-links/refresh",
            json={"controller_id": "ac-1"},
        )

    assert response.status_code == 202
    assert response.json() == {
        "success": True,
        "task_id": "refresh-1",
        "status": "RUNNING",
        "already_running": False,
        "task_mode": "resident",
        "request_id": "acpollreq-1",
        "message": "已请求常驻 AC 会话立即刷新",
    }


def test_mesh_link_routes_have_one_controlled_post_only(tmp_path: Path) -> None:
    refresh = _RefreshService()
    with _client(tmp_path, refresh) as client:
        routes = {
            (path, method.upper())
            for path, operations in client.app.openapi()["paths"].items()
            if path.startswith("/api/ac-management/mesh-links")
            for method in operations
        }

    posts = {path for path, method in routes if method == "POST"}
    assert posts == {"/api/ac-management/mesh-links/refresh"}
    assert not any(token in path for path, _method in routes for token in ("command", "save", "delete", "update"))
