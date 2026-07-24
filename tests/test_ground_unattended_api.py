from __future__ import annotations

import json

from fastapi.testclient import TestClient

from netconsole.backend.api import main as api_main
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver


def test_ground_unattended_profile_status_and_actions_are_site_scoped(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    with TestClient(create_app(paths=paths)) as client:
        profile = client.get("/api/rail-transit/ground-unattended/profile")
        assert profile.status_code == 200
        assert profile.json()["schedule_start_time"] == "07:00"
        payload = profile.json()
        payload.update(
            {
                "enabled": True,
                "schedule_start_time": "08:00",
                "schedule_end_time": "22:30",
            }
        )
        saved = client.put("/api/rail-transit/ground-unattended/profile", json=payload)
        assert saved.status_code == 200
        assert saved.json()["schedule_end_time"] == "22:30"
        started = client.post("/api/rail-transit/ground-unattended/start")
        assert started.status_code == 202
        status = client.get("/api/rail-transit/ground-unattended/status")
        assert status.status_code == 200
        assert status.json()["site_id"] == "demo"


def test_ground_unattended_rejects_invalid_profile_and_archive_delete_without_confirmation(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    with TestClient(create_app(paths=paths)) as client:
        payload = client.get("/api/rail-transit/ground-unattended/profile").json()
        payload["schedule_end_time"] = payload["schedule_start_time"]
        response = client.put(
            "/api/rail-transit/ground-unattended/profile", json=payload
        )
        assert response.status_code == 422
        missing = client.request(
            "DELETE",
            "/api/rail-transit/ground-unattended/archives/missing",
            json={"explicit_confirmation": False},
        )
        assert missing.status_code in {404, 409}


def test_ground_unattended_empty_pages_are_stable(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    with TestClient(create_app(paths=paths)) as client:
        for path in (
            "trains",
            "ping-targets",
            "deep-collections",
            "coverage",
            "timeline",
            "archives",
        ):
            response = client.get(f"/api/rail-transit/ground-unattended/{path}")
            assert response.status_code == 200, path
            assert response.json()["items"] == []


def test_ground_unattended_repository_failure_is_feature_scoped(
    tmp_path, monkeypatch
) -> None:
    class _BrokenRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            raise OSError("index unavailable")

    monkeypatch.setattr(api_main, "GroundUnattendedRepository", _BrokenRepository)
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)

    assert app.state.ground_unattended_application_service is None
    assert app.state.ground_unattended_startup_error == "OSError"
    with TestClient(app) as client:
        health = client.get("/api/health")
        profile = client.get("/api/rail-transit/ground-unattended/profile")
    assert health.status_code == 200
    assert profile.status_code == 503
    assert profile.json()["detail"]["code"] == "GROUND_UNATTENDED_UNAVAILABLE"


def test_ground_unattended_archive_summary_download_and_desktop_action(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run = repository.create_or_get_run(
        run_id="run-download",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    summary = {"ping_sample_count": 123, "covered_train_count": 2}
    repository.upsert_archive(
        {
            "archive_id": "archive-download",
            "site_id": "demo",
            "run_id": run["run_id"],
            "run_date": run["run_date"],
            "relative_path": "archives/2026-07-25_ground_unattended.zip",
            "archive_status": "READY",
            "archive_size_bytes": 456,
            "sha256": "abc",
            "manifest_sha256": "def",
            "retention_until": "2026-08-24",
            "active_cleanup_pending": 0,
            "summary_json": json.dumps(summary),
            "message": "归档完成",
            "created_at": "2026-07-25T23:01:00+08:00",
            "updated_at": "2026-07-25T23:01:00+08:00",
        }
    )

    with TestClient(app) as client:
        download = client.get(
            "/api/rail-transit/ground-unattended/archives/"
            "archive-download/summary-download"
        )
        opened = client.post(
            "/api/rail-transit/ground-unattended/archives/open-directory"
        )

    assert download.status_code == 200
    assert download.json()["ping_sample_count"] == 123
    assert "2026-07-25_ground_unattended_summary.json" in download.headers[
        "content-disposition"
    ]
    assert opened.status_code == 200
    assert opened.json()["success"] is False
