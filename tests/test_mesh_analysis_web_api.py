from __future__ import annotations

import hashlib
import io
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.mesh_analysis_router import router as mesh_analysis_router
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.rail_transit_base_data import VehicleMrDTO, VehicleMrPageDTO
from netconsole.services.mesh_chart_payload import MeshChartSelectionLimitError
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
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/charts/trackside-signal?site_id=demo&radio=1&max_points=10",
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
        invalid_range = client.get(
            f"/api/rail-transit/mesh-analysis/sessions/{encoded}/charts/active-path"
            "?site_id=demo&time_from=2026-07-14%2010%3A00%3A01.000&time_to=2026-07-14%2010%3A00%3A01.000"
        )
        removed_alignment = client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/alignment?site_id=demo")
        source = responses[-1].json()[0]
        source_id = source["source_action_id"]
        responses.append(client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/raw-sources/{source_id}/tail?site_id=demo"))
        artifact_id = next(item["artifact_id"] for item in responses[-3].json() if item["artifact_type"] == "analysis_report")
        download = client.get(f"/api/rail-transit/mesh-analysis/sessions/{encoded}/artifacts/{artifact_id}/download?site_id=demo")

    assert all(response.status_code == 200 for response in responses)
    assert invalid_range.status_code == 422
    active_chart = responses[5].json()
    assert active_chart["total_points_in_range"] == active_chart["total_points"]
    assert active_chart["effective_time_from"] == active_chart["first_sample_time"]
    assert active_chart["requested_max_points"] == 10
    assert active_chart["effective_max_points"] == 10
    assert active_chart["downsample_warning"] is None
    assert active_chart["payload_bytes"] > 0
    assert active_chart["query_duration_ms"] >= 0
    trackside_chart = responses[6].json()
    assert trackside_chart["included_roles"] == ["ACTIVE", "STANDBY"]
    assert trackside_chart["include_standby"] is True
    assert trackside_chart["total_frames"] >= trackside_chart["returned_frames"]
    assert trackside_chart["total_link_points"] == (
        trackside_chart["active_link_points"] + trackside_chart["standby_link_points"]
    )
    assert trackside_chart["returned_link_points"] == trackside_chart["returned_points"]
    assert trackside_chart["requested_max_frames"] == trackside_chart["requested_max_points"] == 10
    assert trackside_chart["payload_bytes"] > 0
    assert trackside_chart["query_duration_ms"] >= 0
    returned_points = {
        (point["timestamp"], point["link_id"], point["timestamp_tag"], point["local_radio"]): point["local_rssi"]
        for point in active_chart["points"]
    }
    for event in active_chart["events"]:
        if not event["render_aligned"]:
            continue
        context = event["point_context"]
        key = (
            event["render_point_timestamp"],
            context["link_id"],
            context["timestamp_tag"],
            event["local_radio"],
        )
        assert key in returned_points
        assert event["render_point_rssi"] == returned_points[key]
    trackside_chart = responses[6].json()
    assert trackside_chart["series"]
    assert trackside_chart["series"][0]["data_source"] == "peer_rssi_db"
    assert trackside_chart["series"][0]["points"]
    assert "events" in trackside_chart
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
        "/rail-transit/mesh-analysis/ap-coverage/audit",
        "/rail-transit/mesh-analysis/ap-coverage/export",
        "/rail-transit/mesh-analysis/bundles/import",
        "/rail-transit/mesh-analysis/bundles/preview",
        "/rail-transit/mesh-analysis/import-context/prepare",
        "/rail-transit/mesh-analysis/import-preview",
        "/rail-transit/mesh-analysis/profiles",
        "/rail-transit/mesh-analysis/sessions/{session_id}/rebuild",
        "/rail-transit/mesh-analysis/sessions/{session_id}/desktop-location",
        "/rail-transit/mesh-analysis/sessions/{session_id}/report",
        "/rail-transit/mesh-analysis/sessions/{session_id}/link-details/export",
        "/rail-transit/mesh-analysis/local-scans",
        "/rail-transit/mesh-analysis/local-scans/{scan_id}/import",
        "/rail-transit/mesh-analysis/local-scans/{scan_id}/ignore",
        "/rail-transit/mesh-analysis/local-scans/{scan_id}/candidates/{candidate_id}/open-directory",
    }
    assert all(route.methods in ({"GET"}, {"POST"}, {"PUT"}, {"DELETE"}) for route in routes)
    generated_report_paths = post_paths | {
        "/rail-transit/mesh-analysis/report-artifacts/{artifact_id}/download",
        "/rail-transit/mesh-analysis/sessions/{session_id}/link-details/export",
        "/rail-transit/mesh-analysis/sources/{source_id}",
    }
    forbidden = ("analyze", "reparse", "export", "report", "delete", "start", "stop")
    assert not any(
        any(word in route.path for word in forbidden)
        for route in routes
        if route.path not in generated_report_paths
    )


def test_mesh_chart_safety_limit_maps_to_http_413(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    def reject_oversized_chart(*_args: object, **_kwargs: object) -> None:
        raise MeshChartSelectionLimitError(critical_count=20_001, max_points=20_000)

    app.state.mesh_analysis_query_service = SimpleNamespace(
        get_active_path_chart=reject_oversized_chart,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/rail-transit/mesh-analysis/sessions/{quote(session_id, safe='')}"
            "/charts/active-path?site_id=demo&max_points=600"
        )

    assert response.status_code == 413
    assert "关键业务点超过安全渲染上限" in response.json()["detail"]


def test_mesh_source_delete_api_submits_confirmed_scope_to_application_service(
    tmp_path: Path,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    calls: list[dict[str, object]] = []

    def start_mesh_source_delete(
        site_id: str,
        source_id: str,
        **scope: object,
    ) -> RailTransitTaskDTO:
        calls.append({"site_id": site_id, "source_id": source_id, **scope})
        return RailTransitTaskDTO(
            task_id="mesh-delete-api",
            status="PENDING",
            action="mesh_analysis_source_delete",
        )

    app.state.rail_transit_web_application_service = SimpleNamespace(
        start_mesh_source_delete=start_mesh_source_delete,
    )

    with TestClient(app) as client:
        response = client.request(
            "DELETE",
            f"/api/rail-transit/mesh-analysis/sources/{quote(session_id, safe='')}",
            json={
                "delete_raw_archive": True,
                "delete_parsed_data": True,
                "delete_generated_reports": True,
                "explicit_confirmation": True,
            },
        )

    assert response.status_code == 202
    assert response.json()["task_id"] == "mesh-delete-api"
    assert calls == [
        {
            "site_id": "demo",
            "source_id": session_id,
            "delete_raw_archive": True,
            "delete_parsed_data": True,
            "delete_generated_reports": True,
            "explicit_confirmation": True,
        }
    ]


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


class _VehicleMrPages:
    def list_mrs(self, _site_id: str, *, page: int, page_size: int) -> VehicleMrPageDTO:
        rows = [
            VehicleMrDTO(id="vehicle-34-ct", device_id=34, name="列车34-MR-CT", train_no="34", role="CT"),
            VehicleMrDTO(id="vehicle-34-cw", device_id=35, name="列车34-MR-CW", train_no="34", role="CW"),
        ]
        start = (page - 1) * page_size
        return VehicleMrPageDTO(items=rows[start:start + page_size], total=len(rows), page=page, page_size=page_size)


def test_prepare_import_context_api_is_json_idempotent_and_keeps_backend_available(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.mesh_bundle_application_service.base_data_query_service = _VehicleMrPages()

    with TestClient(app) as client:
        first = client.post("/api/rail-transit/mesh-analysis/import-context/prepare")
        profiles = client.get("/api/rail-transit/mesh-analysis/profiles")
        second = client.post("/api/rail-transit/mesh-analysis/import-context/prepare")
        health = client.get("/api/health")

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("application/json")
    assert first.json()["created_count"] == 2
    assert first.json()["skipped_count"] == 0
    assert second.status_code == 200
    assert second.json()["created_count"] == 0
    assert {item["linked_device_uuid"] for item in profiles.json()} >= {"vehicle-34-ct", "vehicle-34-cw"}
    assert health.status_code == 200


def test_prepare_import_context_api_returns_structured_json_for_missing_or_failed_service(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.mesh_bundle_application_service = None

    with TestClient(app) as client:
        missing = client.post("/api/rail-transit/mesh-analysis/import-context/prepare")
        profiles = client.get("/api/rail-transit/mesh-analysis/profiles")

    assert missing.status_code == 503
    assert missing.headers["content-type"].startswith("application/json")
    assert missing.json()["detail"] == {
        "code": "MESH_IMPORT_CONTEXT_SERVICE_UNAVAILABLE",
        "message": "MESH 导入上下文服务未就绪",
        "details": {"stage": "application_state"},
    }
    assert profiles.status_code == 200


def test_prepare_import_context_api_maps_sqlite_failure_to_structured_json(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    class _BrokenBaseQuery:
        def list_mrs(self, _site_id: str, *, page: int, page_size: int):
            raise sqlite3.OperationalError("database is locked")

    app.state.mesh_bundle_application_service.base_data_query_service = _BrokenBaseQuery()

    with TestClient(app) as client:
        response = client.post("/api/rail-transit/mesh-analysis/import-context/prepare")
        health = client.get("/api/health")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == {
        "code": "MESH_IMPORT_CONTEXT_PREPARE_FAILED",
        "message": "MESH 导入上下文准备失败",
        "details": {"stage": "sync_vehicle_mr_profiles"},
    }
    assert health.status_code == 200


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


def test_mesh_import_preview_accepts_four_multipart_files_with_same_basename(
    tmp_path: Path,
) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    timestamps = (
        "2026/07/27 08:10:01.001",
        "2026/07/28 00:18:56.311",
        "2026/07/28 13:20:16.625",
        "2026/07/29 00:03:11.002",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/rail-transit/mesh-analysis/import-preview",
            files=[
                (
                    "files",
                    (
                        "meshlog.log",
                        f"[1] {timestamp}\n".encode(),
                        "text/plain",
                    ),
                )
                for timestamp in timestamps
            ],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["member_count"] == 4
    assert len(payload["items"]) == 4
    assert len({item["member_id"] for item in payload["items"]}) == 4
    assert [item["original_name"] for item in payload["items"]] == ["meshlog.log"] * 4
    assert all("__uploads__" not in item["stored_filename"] for item in payload["items"])
