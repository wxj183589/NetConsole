from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy
from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _app(paths, tmp_path: Path):
    return create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
        rail_base_data_write_feature_enabled=True,
    )


def _preview(client: TestClient, suffix: str = "61") -> dict:
    response = client.post(
        "/api/rail-transit/base-data/import-preview",
        files={
            "file": (
                "copy-preview.json",
                json.dumps(
                    [{"ap_name": f"AP-API-{suffix}", "ap_mac_display": f"0011-2233-66{int(suffix):02d}"}]
                ).encode("utf-8"),
                "application/json",
            )
        },
    )
    assert response.status_code == 200
    return response.json()


def test_production_defaults_return_write_disabled(tmp_path: Path, monkeypatch) -> None:
    for name in (
        "RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED",
        "NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE",
        "NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE",
    ):
        monkeypatch.delenv(name, raising=False)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    with TestClient(_app(paths, tmp_path)) as client:
        preview = _preview(client, "62")
        response = client.post(
            "/api/rail-transit/base-data/import-apply",
            json={
                "preview_id": preview["preview_id"],
                "site_id": "demo",
                "explicit_confirmation": True,
                "decisions": [],
                "expected_database_sha256": preview["database_hash"],
            },
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "BASE_DATA_WRITE_DISABLED"


def test_copy_apply_operation_queries_and_idempotency(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED", "1")
    monkeypatch.setenv("NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE", "1")
    monkeypatch.delenv("NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE", raising=False)
    monkeypatch.delenv("RAIL_TRANSIT_BASE_DATA_ROLLBACK_ENABLED", raising=False)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    app = _app(paths, tmp_path)
    with TestClient(app) as client:
        preview = _preview(client, "63")
        payload = {
            "preview_id": preview["preview_id"],
            "site_id": "demo",
            "explicit_confirmation": True,
            "decisions": [],
            "expected_database_sha256": preview["database_hash"],
        }
        applied = client.post("/api/rail-transit/base-data/import-apply", json=payload)
        duplicate = client.post("/api/rail-transit/base-data/import-apply", json=payload)
        invalid = client.post(
            "/api/rail-transit/base-data/import-apply",
            json={**payload, "database_path": "forbidden.sqlite"},
        )
        operation_id = applied.json()["operation_id"]
        operations = client.get("/api/rail-transit/base-data/import-operations")
        operation = client.get(f"/api/rail-transit/base-data/import-operations/{operation_id}")
        changes = client.get(f"/api/rail-transit/base-data/import-operations/{operation_id}/changes")
        rollback = client.post(
            f"/api/rail-transit/base-data/import-operations/{operation_id}/rollback",
            json={"explicit_confirmation": True},
        )

    assert applied.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ALREADY_APPLIED"
    assert invalid.status_code == 422
    assert operations.json()["total"] == 1
    assert operation.json()["status"] == "APPLIED"
    assert changes.json()["total"] >= 2
    assert rollback.status_code == 403
    assert rollback.json()["detail"]["code"] == "BASE_DATA_ROLLBACK_DISABLED"
    routes = app.openapi()["paths"]
    assert "/api/rail-transit/base-data/import-apply" in routes
    assert not any(path.endswith(("/sql", "/aps", "/devices", "/trains", "/stations")) and "delete" in methods for path, methods in routes.items())


def test_import_apply_persists_valid_rows_and_reports_skipped_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED", "1")
    monkeypatch.setenv("NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE", "1")
    monkeypatch.delenv("NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE", raising=False)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        preview_response = client.post(
            "/api/rail-transit/base-data/import-preview",
            files={
                "file": (
                    "partial.json",
                    json.dumps(
                        [
                            {
                                "ap_name": "",
                                "ap_point_code": "PARTIAL-NEW",
                                "ap_mac_display": "aa00-0000-0001",
                                "station_name": "车站A",
                            },
                            {
                                "ap_point_code": "AP002",
                                "ap_mac_display": "aa00-0000-0002",
                            },
                            {
                                "ap_point_code": "PARTIAL-BAD",
                                "ap_mac_display": "not-a-mac",
                            },
                        ],
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "application/json",
                )
            },
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["merge_plan"]["summary"]["importable_count"] == 1

        applied = client.post(
            "/api/rail-transit/base-data/import-apply",
            json={
                "preview_id": preview["preview_id"],
                "site_id": "demo",
                "explicit_confirmation": True,
                "decisions": [],
                "expected_database_sha256": preview["database_hash"],
            },
        )

    assert applied.status_code == 200
    payload = applied.json()
    assert payload["total_rows"] == 3
    assert payload["imported_rows"] == 1
    assert payload["created_rows"] == 1
    assert payload["updated_rows"] == 0
    assert payload["unchanged_rows"] == 0
    assert payload["skipped_conflict_rows"] == 1
    assert payload["skipped_invalid_rows"] == 1
    assert payload["unmatched_fit_ap_rows"] == 2
    assert payload["issues"]
    with sqlite3.connect(database) as connection:
        imported = connection.execute(
            "SELECT ap_name, ap_point_code, ap_mac_norm FROM ap_extension_points WHERE ap_point_code = ?",
            ("PARTIAL-NEW",),
        ).fetchone()
    assert imported == ("", "PARTIAL-NEW", "aa0000000001")
