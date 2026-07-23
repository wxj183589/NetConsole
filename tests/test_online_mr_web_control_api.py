from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.online_mr_control import OnlineMrWebControlStatusDTO, OnlineMrWebOperationDTO
from support.online_mr_api import wire_online_mr_api_facade


class _ControlService:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.started = 0
        self.stopped = 0
        self.force_stopped = 0
        self.recovered = 0
        self.operation = OnlineMrWebOperationDTO(
            operation_id="task-1",
            task_id="task-1",
            site_id="demo",
            device_id=7,
            device_name="列车07 MR",
            mr_id="mr-7",
            mr_name="列车07 MR",
            owner="web_local",
            state="running",
            phase="COLLECTING",
            mapping_status="LINKED",
            updated_at="2026-07-14T12:00:00Z",
        )

    def status(self, site_id: str):
        return OnlineMrWebControlStatusDTO(enabled=self.enabled, site_id=site_id, operations=[self.operation])

    def get_operation(self, operation_id: str, *, site_id: str | None = None):
        assert operation_id == "task-1" and site_id is None
        return self.operation

    def start(self, payload, *, current_site_id: str):
        assert payload.executor == "LOCAL" and current_site_id == "demo"
        self.started += 1
        return self.operation

    def stop(self, operation_id: str, *, site_id: str | None = None):
        assert operation_id == "task-1" and site_id is None
        self.stopped += 1
        return self.operation.model_copy(update={"state": "stopped", "phase": "TERMINAL"})

    def force_stop(self, operation_id: str, *, site_id: str | None = None):
        assert operation_id == "task-1" and site_id is None
        self.force_stopped += 1
        return self.operation.model_copy(update={"state": "aborted", "phase": "TERMINAL", "data_integrity": "partial"})

    def recover(self, site_id: str):
        assert site_id == "demo"
        self.recovered += 1
        return [self.operation]


def _app(tmp_path: Path, service: _ControlService, *, mode: RuntimeMode = RuntimeMode.DESKTOP):
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("demo").mkdir(parents=True, exist_ok=True)
    paths.app_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(
        mode,
        paths=paths,
        frontend_dist=tmp_path / "missing-dist",
        desktop_session_token="desktop-token" if mode is RuntimeMode.DESKTOP else None,
        online_mr_web_control_service=service,
    )
    return wire_online_mr_api_facade(app, paths)


def _authorized_client(app, *, base_url: str = "http://127.0.0.1"):
    client = TestClient(app, base_url=base_url)
    response = client.post("/__desktop_session", data={"token": "desktop-token"}, follow_redirects=False)
    assert response.status_code == 303
    return client


def _payload() -> dict[str, object]:
    return {"site_id": "demo", "device_id": 7, "mr_id": "mr-7", "executor": "LOCAL"}


def test_control_api_requires_desktop_cookie_and_loopback(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path / "missing-cookie", _ControlService()), base_url="http://127.0.0.1") as client:
        unauthorized = client.get("/api/rail-transit/online-mr-control/status")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "ONLINE_MR_WEB_AUTH_REQUIRED"
    with _authorized_client(_app(tmp_path / "non-loopback", _ControlService()), base_url="http://localhost") as client:
        response = client.get("/api/rail-transit/online-mr-control/status")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ONLINE_MR_WEB_LOCAL_ONLY"


def test_control_api_start_stop_force_stop_recover_status_and_detail(tmp_path: Path) -> None:
    service = _ControlService()
    with _authorized_client(_app(tmp_path, service)) as client:
        status = client.get("/api/rail-transit/online-mr-control/status")
        presets = client.get("/api/rail-transit/online-mr-control/presets")
        started = client.post("/api/rail-transit/online-mr-control/start", json=_payload())
        detail = client.get("/api/rail-transit/online-mr-control/task-1")
        stopped = client.post("/api/rail-transit/online-mr-control/task-1/stop")
        forced = client.post("/api/rail-transit/online-mr-control/task-1/force-stop")
        recovered = client.post("/api/rail-transit/online-mr-control/recover")

    assert status.status_code == presets.status_code == started.status_code == detail.status_code == stopped.status_code == forced.status_code == recovered.status_code == 200
    preset_data = presets.json()
    assert preset_data["ping"][0]["interval_ms"] == 10
    assert preset_data["ping"][0]["timeout_ms"] == 100
    assert preset_data["traffic"][0]["key"] == "pis_tcp_downlink_single"
    assert started.json()["owner"] == "web_local"
    assert stopped.json()["state"] == "stopped"
    assert service.started == service.stopped == 1
    assert forced.json()["data_integrity"] == "partial"
    assert recovered.json()[0]["operation_id"] == "task-1"
    assert service.force_stopped == service.recovered == 1


def test_control_api_rejects_unknown_sensitive_fields_and_agent_executor(tmp_path: Path) -> None:
    with _authorized_client(_app(tmp_path, _ControlService())) as client:
        for field in ("username", "password", "command", "commands", "output_dir", "database_path", "agent_url", "token"):
            response = client.post("/api/rail-transit/online-mr-control/start", json={**_payload(), field: "secret"})
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "ONLINE_MR_WEB_INVALID_REQUEST"
            assert "secret" not in response.text
        agent = client.post(
            "/api/rail-transit/online-mr-control/start",
            json={**_payload(), "executor": "AGENT"},
        )
    assert agent.status_code == 422
    assert agent.json()["error"]["code"] == "ONLINE_MR_WEB_INVALID_REQUEST"
    assert "secret" not in agent.text


def test_control_api_default_feature_is_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ONLINE_MR_WEB_CONTROL_ENABLED", raising=False)
    app = _app(tmp_path, _ControlService(enabled=False))
    with _authorized_client(app) as client:
        response = client.get("/api/rail-transit/online-mr-control/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_control_application_service_is_created_only_for_protected_desktop_mode(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    desktop = create_app(
        RuntimeMode.DESKTOP,
        paths=paths,
        frontend_dist=tmp_path / "missing-dist",
        desktop_session_token="desktop-token",
        online_mr_web_control_enabled=True,
    )
    server = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        frontend_dist=tmp_path / "missing-dist",
        online_mr_web_control_enabled=True,
    )

    assert desktop.state.online_mr_web_control_enabled is True
    assert desktop.state.online_mr_application_service is not None
    assert server.state.online_mr_web_control_enabled is False
    assert server.state.online_mr_application_service is None
    desktop.state.online_mr_application_service.close()
