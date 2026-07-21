from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.train_communication_router import (
    router as train_communication_router,
)
from netconsole.core.paths import PathResolver
from netconsole.models.api.train_communication import (
    MrCommunicationDetailDTO,
    MrCommunicationStatusDTO,
    TrainCommunicationDetailDTO,
    TrainCommunicationPageDTO,
    TrainCommunicationRowDTO,
    TrainCommunicationSummaryDTO,
    TrainCommunicationTopologyDTO,
)
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO


class _ApiService:
    row = TrainCommunicationRowDTO(train_id="01", train_no="01", train_name="01车")
    mr = MrCommunicationStatusDTO(
        train_id="01", train_name="01车", mr_id="mr-1", mr_name="列车01-MR-CT"
    )

    @staticmethod
    def current_site_id() -> str:
        return "demo"

    @classmethod
    def get_summary(cls, site_id: str) -> TrainCommunicationSummaryDTO:
        return TrainCommunicationSummaryDTO(
            site_id=site_id, registered_trains=1, registered_mrs=1
        )

    @classmethod
    def list_trains(cls, _site_id: str, **_kwargs) -> TrainCommunicationPageDTO:
        return TrainCommunicationPageDTO(items=[cls.row], total=1)

    @classmethod
    def get_train_detail(cls, site_id: str, train_id: str):
        return (
            TrainCommunicationDetailDTO(train=cls.row, site_id=site_id)
            if train_id == "01"
            else None
        )

    @classmethod
    def get_train_topology(cls, _site_id: str, train_id: str):
        return TrainCommunicationTopologyDTO(train_id=train_id, train_name="01车") if train_id == "01" else None

    @classmethod
    def get_mr_detail(cls, _site_id: str, mr_id: str):
        return MrCommunicationDetailDTO(mr=cls.mr) if mr_id == "mr-1" else None

    @classmethod
    def get_communication_preview(cls, _site_id: str, mr_id: str):
        return cls.mr if mr_id == "mr-1" else None

    @staticmethod
    def get_raw_sources(*_args):
        return []

    @staticmethod
    def get_related_tasks(*_args):
        return []

    @staticmethod
    def get_related_packages(*_args):
        return []


class _ApplicationService:
    @staticmethod
    def start_car_network_diagnostic(_site_id: str, *, train_id: str = "") -> RailTransitTaskDTO:
        return RailTransitTaskDTO(task_id="task-1", status="RUNNING", action="car_network_diagnostic", message=train_id)

    @staticmethod
    def get_car_network_diagnostic(_site_id: str, task_id: str) -> RailTransitTaskDTO:
        return RailTransitTaskDTO(task_id=task_id, status="COMPLETED", action="car_network_diagnostic")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_train_communication_queries_do_not_touch_sources_and_write_routes_are_allowlisted(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.train_communication_query_service = _ApiService()
    app.state.rail_transit_web_application_service = _ApplicationService()
    protected = [
        tmp_path / name
        for name in ("devices.db", "tasks.db", "mesh.db", "session_meta.json")
    ]
    for index, path in enumerate(protected):
        path.write_bytes(f"protected-{index}".encode())
    before = [(path.stat().st_mtime_ns, _sha256(path)) for path in protected]

    with TestClient(app) as client:
        urls = [
            "/api/rail-transit/train-communication/summary",
            "/api/rail-transit/train-communication/trains",
            "/api/rail-transit/train-communication/trains/01",
            "/api/rail-transit/train-communication/trains/01/topology",
            "/api/rail-transit/train-communication/mrs/mr-1",
            "/api/rail-transit/train-communication/mrs/mr-1/preview",
            "/api/rail-transit/train-communication/mrs/mr-1/raw-sources",
            "/api/rail-transit/train-communication/mrs/mr-1/tasks",
            "/api/rail-transit/train-communication/mrs/mr-1/packages",
        ]
        responses = [client.get(url) for url in urls]

    assert all(response.status_code == 200 for response in responses)
    assert "password" not in "".join(response.text for response in responses).casefold()
    assert "token" not in "".join(response.text for response in responses).casefold()
    assert before == [(path.stat().st_mtime_ns, _sha256(path)) for path in protected]
    routes = [
        route
        for route in train_communication_router.routes
        if getattr(route, "path", "").startswith("/rail-transit/train-communication")
    ]
    assert routes
    write_routes = [route for route in routes if route.methods != {"GET"}]
    assert write_routes
    assert {route.path for route in write_routes} == {
        "/rail-transit/train-communication/trains/{train_id}/diagnostics",
        "/rail-transit/train-communication/diagnostics/{task_id}/cancel",
        "/rail-transit/train-communication/diagnostics/recover",
        "/rail-transit/train-communication/point-table/import/preview",
        "/rail-transit/train-communication/point-table/transform",
        "/rail-transit/train-communication/point-table/save",
        "/rail-transit/train-communication/point-table/generate",
        "/rail-transit/train-communication/point-table/export",
        "/rail-transit/train-communication/point-table/tasks/{task_id}/cancel",
        "/rail-transit/train-communication/point-table/tasks/recover",
    }
    assert not any("delete" in route.path for route in routes)


def test_topology_and_diagnostic_routes_use_query_and_application_services(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.train_communication_query_service = _ApiService()
    app.state.rail_transit_web_application_service = _ApplicationService()
    for feature_id in (
        "web.train_communication_monitoring",
        "web.rail_car_network_diagnostic_execute",
        "web.rail_task_control",
    ):
        app.state.feature_gate.features[feature_id] = {
            "visible": True,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        }

    with TestClient(app) as client:
        topology = client.get("/api/rail-transit/train-communication/trains/01/topology")
        missing = client.get("/api/rail-transit/train-communication/trains/missing/topology")
        started = client.post("/api/rail-transit/train-communication/trains/01/diagnostics")
        completed = client.get("/api/rail-transit/train-communication/diagnostics/task-1")

    assert topology.status_code == 200
    assert topology.json()["train_name"] == "01车"
    assert missing.status_code == 404
    assert started.status_code == 202
    assert started.json()["action"] == "car_network_diagnostic"
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    payload = topology.text + started.text + completed.text
    assert "password" not in payload.casefold()
    assert "token" not in payload.casefold()


def test_missing_iperf_raw_tail_returns_chinese_empty_state(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    session = paths.online_mr_session_dir("demo", "MR-01", "session-1")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "STOPPED",
            }
        ),
        encoding="utf-8",
    )
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        response = client.get(
            "/api/online-mr/sessions/session-1/raw-tail?name=iperf_client"
        )

    assert response.status_code == 200
    assert response.json()["data"]["exists"] is False
    assert response.json()["data"]["message"] == "文件不存在或尚未生成"
