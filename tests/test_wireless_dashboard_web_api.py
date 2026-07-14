from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.wireless_dashboard_router import router as wireless_dashboard_router
from netconsole.core.paths import PathResolver

from tests.test_wireless_dashboard_query_service import _service


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_wireless_dashboard_api_is_get_only_and_preserves_sources(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.wireless_dashboard_query_service = _service(tmp_path)
    protected = [tmp_path / name for name in ("devices.db", "tasks.db", "mesh_link.sqlite", "session_meta.json", "mesh_raw.log")]
    for index, path in enumerate(protected):
        path.write_bytes(f"protected-{index}".encode("utf-8"))
    before = [(path.stat().st_mtime_ns, _sha256(path)) for path in protected]
    suffixes = ("", "/summary", "/infrastructure", "/trains", "/alerts", "/freshness", "/recent-operations", "/analysis", "/agents")

    with TestClient(app) as client:
        responses = [client.get(f"/api/rail-transit/wireless-dashboard{suffix}") for suffix in suffixes]

    assert all(response.status_code == 200 for response in responses)
    body = "".join(response.text for response in responses).casefold()
    assert "password" not in body
    assert "token" not in body
    assert before == [(path.stat().st_mtime_ns, _sha256(path)) for path in protected]
    routes = [route for route in wireless_dashboard_router.routes if getattr(route, "path", "").startswith("/rail-transit/wireless-dashboard")]
    assert routes
    assert all(route.methods == {"GET"} for route in routes)
    assert not any(any(word in route.path for word in ("start", "stop", "refresh", "delete", "import", "probe")) for route in routes)
