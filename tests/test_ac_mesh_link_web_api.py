from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support.ac_mesh_link_web_fixture import build_ac_mesh_link_fixture
from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_mesh_link_get_api_is_read_only_and_raw_unavailable_is_not_an_error(tmp_path: Path) -> None:
    paths, devices_db, mesh_db = build_ac_mesh_link_fixture(tmp_path)
    tasks_db = paths.site_tasks_db_path("demo")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app) as client:
        assert client.get("/api/ac-management/mesh-links/summary").status_code == 200
        before = (_fingerprint(devices_db), _fingerprint(mesh_db), tasks_db.exists())
        summary = client.get("/api/ac-management/mesh-links/summary")
        links = client.get("/api/ac-management/mesh-links/current?match_status=matched")
        mrs = client.get("/api/ac-management/mesh-links/mrs")
        detail = client.get("/api/ac-management/mesh-links/mrs/mr-01-ct")
        snapshots = client.get("/api/ac-management/mesh-links/snapshots")
        raw_tail = client.get("/api/ac-management/mesh-links/raw-tail")
        trains = client.get("/api/rail-transit/train-online/trains")
        train_detail = client.get("/api/rail-transit/train-online/trains/01")
        after = (_fingerprint(devices_db), _fingerprint(mesh_db), tasks_db.exists())

    assert summary.status_code == 200
    assert links.status_code == 200
    assert mrs.status_code == 200
    assert detail.status_code == 200
    assert snapshots.status_code == 200
    assert raw_tail.status_code == 200
    assert trains.status_code == 200
    assert train_detail.status_code == 200
    assert {"overall_status", "ct", "tc", "reason_code", "reason_text"} <= set(train_detail.json())
    assert {"current_ap_name", "current_ap_mac", "mesh_radio", "match_status"} <= set(train_detail.json()["ct"])
    assert "status" not in train_detail.json()
    assert "tc1" not in train_detail.json()
    assert raw_tail.json()["available"] is False
    removed_fields = {"link_status", "channel", "bandwidth", "ap_online_status", "optical_status"}
    assert removed_fields.isdisjoint(links.json()["items"][0])
    assert {"link_status", "ap_online_status", "optical_status"}.isdisjoint(mrs.json()["items"][0])
    assert "client" not in "".join((summary.text, links.text, mrs.text, detail.text)).casefold()
    assert after == before


def test_mesh_link_router_exposes_one_controlled_post_operation(tmp_path: Path) -> None:
    paths, _devices_db, _mesh_db = build_ac_mesh_link_fixture(tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    routes = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/ac-management/mesh-links")
        for method in operations
    }

    assert routes
    assert {method for _path, method in routes} == {"GET", "POST"}
    assert {path for path, method in routes if method == "POST"} == {"/api/ac-management/mesh-links/refresh"}
    assert all(
        operation.get("deprecated") is True
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/ac-management/mesh-links")
        for operation in operations.values()
    )
    assert "client_count" not in str(app.openapi()).casefold()
    assert all(not path.endswith(("/collect", "/command", "/start", "/stop")) for path, _method in routes)
    parameters = {
        parameter["name"]
        for path, operations in app.openapi()["paths"].items()
        if path in {"/api/ac-management/mesh-links/current", "/api/ac-management/mesh-links/mrs"}
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
    }
    assert {"link_status", "ap_online_status", "offline_ap_only", "optical_anomaly_only"}.isdisjoint(parameters)
