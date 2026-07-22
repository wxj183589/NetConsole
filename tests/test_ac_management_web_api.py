from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.repositories.ac_repository import AcRepository


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_ac_management_get_api_is_read_only_and_redacts_serial_number(tmp_path: Path) -> None:
    paths, db_path, files = build_ac_management_fixture(tmp_path)
    repository = AcRepository(Database(db_path))
    ap = repository.get_fit_ap_resource_by_uuid("ac-1", "ap-online")
    assert ap is not None
    repository.upsert_fit_ap_resource("ac-1", ap)
    with Database(db_path).connect() as conn:
        conn.execute("UPDATE ac_ap_summary SET cpu_usage = '16%', memory_usage = '47%' WHERE ac_device_uuid = 'ac-1'")
        conn.execute("UPDATE devices SET https_port = 10443 WHERE device_uuid = 'ac-1'")
        conn.commit()
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )

    with TestClient(app) as client:
        warmup = client.get("/api/ac-management/summary")
        assert warmup.status_code == 200
        before_db = _fingerprint(db_path)
        before_config = _fingerprint(files["running"])
        summary = client.get("/api/ac-management/summary")
        aps = client.get("/api/ac-management/aps?page=1&page_size=2&status=offline")
        detail = client.get("/api/ac-management/aps/ap-offline")
        optical_anomalies = client.get("/api/ac-management/optical-anomalies")
        radio_history = client.get("/api/ac-management/aps/ap-online/history/radio")
        invalid_history = client.get("/api/ac-management/aps/ap-online/history/unknown")
        snapshots = client.get("/api/ac-management/config-snapshots")
        running_id = next(item["id"] for item in snapshots.json()["items"] if item["type"] == "running")
        content = client.get(f"/api/ac-management/config-snapshots/{running_id}")
        diff = client.get(f"/api/ac-management/config-snapshots/{running_id}/diff")
        after_db = _fingerprint(db_path)
        after_config = _fingerprint(files["running"])

    assert summary.status_code == 200
    assert summary.json()["ap_total"] == 3
    assert summary.json()["acs"][0]["cpu_usage"] == "16%"
    assert summary.json()["acs"][0]["memory_usage"] == "47%"
    assert summary.json()["acs"][0]["https_port"] == 10443
    assert summary.json()["optical_anomalies"] == 2
    assert aps.json()["items"][0]["id"] == "ap-offline"
    assert detail.status_code == 200
    assert radio_history.status_code == 200
    assert radio_history.json()["total"] == 2
    assert radio_history.json()["items"][0]["status"] == "Up"
    assert "raw_log_path" not in radio_history.text
    assert invalid_history.status_code == 422
    assert len(detail.json()["radios"]) == 2
    assert detail.json()["radios"][0]["status"] == "Up"
    assert detail.json()["radios"][0]["usage"] == "12"
    assert detail.json()["radios"][0]["clients"] == 3
    assert detail.json()["connection"]["state"] == "Run"
    assert detail.json()["optical"]["ap_online_status"] == "offline"
    assert detail.json()["optical"]["is_current_anomaly"] is True
    assert detail.json()["optical"]["data_freshness"] == "fresh"
    assert [item["id"] for item in optical_anomalies.json()["items"]] == ["ap-online", "ap-offline"]
    assert "serial" not in detail.text.casefold()
    assert "SECRET-SN" not in detail.text
    assert content.status_code == 200
    assert diff.status_code == 200
    assert after_db == before_db
    assert after_config == before_config


def test_ac_management_router_exposes_only_fixed_controlled_posts(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    routes = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/ac-management")
        for method in operations
    }

    assert routes
    assert {path for path, method in routes if method == "POST"} == {
        "/api/ac-management/mesh-links/refresh",
        "/api/ac-management/extensions/import-preview",
        "/api/ac-management/extensions/import-apply",
        "/api/ac-management/extensions/export",
        "/api/ac-management/extensions/audits/{audit_id}/rollback",
        "/api/ac-management/fit-aps/delete",
        "/api/ac-management/fit-aps/metadata/import",
        "/api/ac-management/fit-aps/omnipeek/preview",
        "/api/ac-management/fit-aps/omnipeek/export",
        "/api/ac-management/fit-aps/{ap_id}/external-terminal",
        "/api/ac-management/aps/{ap_id}/metadata",
        "/api/ac-management/local-rebuild/{rebuild_kind}",
        "/api/ac-management/refresh/{refresh_kind}",
        "/api/ac-management/trackside-business/local-rebuild",
        "/api/ac-management/web-tasks/{task_id}/cancel",
        "/api/ac-management/web-tasks/recover",
        "/api/ac-management/actions/plans",
        "/api/ac-management/actions/plans/{plan_id}/confirm",
        "/api/ac-management/actions/plans/{plan_id}/execute",
    }
    assert all(method in {"GET", "POST"} for _path, method in routes)
    assert all(not path.endswith(("/collect", "/persistent", "/save", "/command")) for path, _method in routes)
    assert {path for path, _method in routes if "delete" in path} == {"/api/ac-management/fit-aps/delete"}
