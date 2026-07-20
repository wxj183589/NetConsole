from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.mesh_analysis_router import router as mesh_analysis_router
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from tests.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture


def _fingerprint(path: Path) -> tuple[int, str]:
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def test_mesh_analysis_queries_keep_analysis_files_unchanged(tmp_path: Path) -> None:
    paths, session_id, detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.mesh_analysis_query_service = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
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
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/active-build-order?site_id=demo&page_size=2",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/charts/active-path?site_id=demo&radio=1&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/charts/peer-segment?site_id=demo&anchor_link_id=1&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/timeline?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/switch-events?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/rssi?site_id=demo&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/channel-busy?site_id=demo&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/rate-series?site_id=demo&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/counter-deltas?site_id=demo&max_points=10",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/anomalies?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/ap-statistics?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/artifacts?site_id=demo",
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/raw-sources?site_id=demo",
        ]
        responses = [client.get(url) for url in urls]
        removed_alignment = client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/alignment?site_id=demo")
        source = responses[-1].json()[0]
        source_id = source["source_action_id"]
        responses.append(client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/raw-sources/{source_id}/tail?site_id=demo"))
        artifact_id = next(item["artifact_id"] for item in responses[-3].json() if item["artifact_type"] == "analysis_report")
        download = client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/artifacts/{artifact_id}/download?site_id=demo")

    assert all(response.status_code == 200 for response in responses)
    assert removed_alignment.status_code == 404
    assert download.status_code == 200
    assert source["source_file_id"] == 1
    assert isinstance(source["source_action_id"], str)
    assert source["source_action_id"] == source["source_id"]
    assert responses[-1].json()["source_action_id"] == source_id
    payload = "".join(response.text for response in responses)
    assert str(tmp_path) not in payload
    assert "peer_radio_mac" in payload
    assert "timestamp_tag" in payload
    assert "standby_context_count" in payload
    assert before == [_fingerprint(path) for path in protected]
    routes = [route for route in mesh_analysis_router.routes if getattr(route, "path", "").startswith("/rail-transit/mesh-analysis")]
    assert routes
    post_paths = {route.path for route in routes if route.methods == {"POST"}}
    assert post_paths == {
        "/rail-transit/mesh-analysis/bundles/import",
        "/rail-transit/mesh-analysis/bundles/preview",
        "/rail-transit/mesh-analysis/import-context/prepare",
        "/rail-transit/mesh-analysis/import-preview",
        "/rail-transit/mesh-analysis/profiles",
        "/rail-transit/mesh-analysis/sessions/{session_id}/rebuild",
        "/rail-transit/mesh-analysis/sessions/{session_id}/report",
        "/rail-transit/mesh-analysis/sessions/{session_id}/link-details/export",
    }
    assert all(route.methods in ({"GET"}, {"POST"}) for route in routes)
    generated_report_paths = post_paths | {
        "/rail-transit/mesh-analysis/report-artifacts/{artifact_id}/download",
        "/rail-transit/mesh-analysis/sessions/{session_id}/link-details/export",
    }
    forbidden = ("analyze", "reparse", "export", "report", "delete", "start", "stop")
    assert not any(
        any(word in route.path for word in forbidden)
        for route in routes
        if route.path not in generated_report_paths
    )


def test_mesh_profile_api_lists_persisted_profiles_and_creates_real_profile(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        before = client.get("/api/rail-transit/mesh-analysis/profiles")
        created = client.post(
            "/api/rail-transit/mesh-analysis/profiles",
            json={"display_name": "列车02-MR-TC", "notes": "离线分析"},
        )
        after = client.get("/api/rail-transit/mesh-analysis/profiles")

    assert before.status_code == 200
    assert before.json()[0]["display_name"] == "列车01-MR-CT"
    assert created.status_code == 201
    assert created.json()["display_name"] == "列车02-MR-TC"
    assert created.json()["safe_folder_name"] == "列车02-MR-TC"
    assert {item["display_name"] for item in after.json()} == {"列车01-MR-CT", "列车02-MR-TC"}


def test_mesh_bundle_preview_returns_safe_token_without_server_path(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("01CTmeshlog.log", b"preview-only")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        response = client.post(
            "/api/rail-transit/mesh-analysis/bundles/preview",
            files={"file": ("bundle.zip", archive.getvalue(), "application/zip")},
        )
        missing = client.post(
            "/api/rail-transit/mesh-analysis/bundles/import",
            json={
                "preview_id": "0" * 32,
                "mappings": [
                    {
                        "member_id": "01CTmeshlog.log",
                        "train_number": "01",
                        "role": "CT",
                        "profile_id": "missing",
                    }
                ],
                "explicit_confirmation": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["preview_id"]) == 32
    assert payload["items"][0]["original_name"] == "01CTmeshlog.log"
    assert str(tmp_path) not in response.text
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "PREVIEW_NOT_FOUND"
