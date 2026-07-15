from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.mesh_analysis_router import router as mesh_analysis_router
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from tests.mesh_analysis_test_support import EmptyBaseQuery, EmptyOnlineQuery, create_mesh_analysis_fixture


def _fingerprint(path: Path) -> tuple[int, str]:
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def test_mesh_analysis_api_is_get_only_and_keeps_analysis_files_unchanged(tmp_path: Path) -> None:
    paths, session_id, detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.mesh_analysis_query_service = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
        online_mr_query=EmptyOnlineQuery(),  # type: ignore[arg-type]
    )
    encoded = quote(session_id, safe="")
    protected = [detail, raw, report]
    before = [_fingerprint(path) for path in protected]

    with TestClient(app) as client:
        urls = [
            "/api/rail-transit/mesh-analysis/summary?site_id=demo",
            "/api/rail-transit/mesh-analysis/sessions?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/links?site_id=demo&page_size=2",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/timeline?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/switch-events?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/rssi?site_id=demo&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/channel-busy?site_id=demo&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/anomalies?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/ap-statistics?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/alignment?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/artifacts?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/raw-sources?site_id=demo",
        ]
        responses = [client.get(url) for url in urls]
        source_id = responses[-1].json()[0]["source_id"]
        responses.append(client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/raw-sources/{source_id}/tail?site_id=demo"))
        artifact_id = next(item["artifact_id"] for item in responses[-3].json() if item["artifact_type"] == "analysis_report")
        download = client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/artifacts/{artifact_id}/download?site_id=demo")

    assert all(response.status_code == 200 for response in responses)
    assert download.status_code == 200
    payload = "".join(response.text for response in responses)
    assert str(tmp_path) not in payload
    assert "peer_radio_mac" not in payload
    assert before == [_fingerprint(path) for path in protected]
    routes = [route for route in mesh_analysis_router.routes if getattr(route, "path", "").startswith("/rail-transit/mesh-analysis")]
    assert routes
    post_paths = {route.path for route in routes if route.methods == {"POST"}}
    assert post_paths == {"/rail-transit/mesh-analysis/sessions/{session_id}/report"}
    assert all(route.methods in ({"GET"}, {"POST"}) for route in routes)
    generated_report_paths = post_paths | {
        "/rail-transit/mesh-analysis/report-artifacts/{artifact_id}/download"
    }
    forbidden = ("analyze", "reparse", "export", "report", "delete", "start", "stop")
    assert not any(
        any(word in route.path for word in forbidden)
        for route in routes
        if route.path not in generated_report_paths
    )
