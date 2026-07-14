from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_ac_management_get_api_is_read_only_and_redacts_serial_number(tmp_path: Path) -> None:
    paths, db_path, files = build_ac_management_fixture(tmp_path)
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
        snapshots = client.get("/api/ac-management/config-snapshots")
        running_id = next(item["id"] for item in snapshots.json()["items"] if item["type"] == "running")
        content = client.get(f"/api/ac-management/config-snapshots/{running_id}")
        diff = client.get(f"/api/ac-management/config-snapshots/{running_id}/diff")
        after_db = _fingerprint(db_path)
        after_config = _fingerprint(files["running"])

    assert summary.status_code == 200
    assert summary.json()["ap_total"] == 3
    assert aps.json()["items"][0]["id"] == "ap-offline"
    assert detail.status_code == 200
    assert len(detail.json()["radios"]) == 2
    assert "serial" not in detail.text.casefold()
    assert "SECRET-SN" not in detail.text
    assert "client" not in aps.text.casefold()
    assert "client" not in detail.text.casefold()
    assert content.status_code == 200
    assert diff.status_code == 200
    assert after_db == before_db
    assert after_config == before_config


def test_ac_management_router_keeps_only_mesh_link_refresh_as_controlled_post(tmp_path: Path) -> None:
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
    assert {path for path, method in routes if method == "POST"} == {"/api/ac-management/mesh-links/refresh"}
    assert all(method == "GET" for path, method in routes if not path.startswith("/api/ac-management/mesh-links"))
    assert "client_count" not in str(app.openapi()).casefold()
    assert all(not path.endswith(("/collect", "/persistent", "/save", "/command")) for path, _method in routes)
    assert all("delete" not in path for path, _method in routes)
