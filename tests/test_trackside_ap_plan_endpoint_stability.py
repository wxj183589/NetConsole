from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from netconsole.backend.api.main import create_app
from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.trackside_ap_business import (
    ApManagementVlanAllocationDTO,
    ApManagementVlanAssignmentDTO,
    ApManagementVlanPlanningDTO,
)
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE


PLAN_PATH = "/api/rail-transit/trackside-ap-business/plan"


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _database_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fixture(tmp_path: Path) -> tuple[PathResolver, Database, object]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text(
        json.dumps({"current_site": "demo"}),
        encoding="utf-8",
    )
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing-frontend",
    )
    app.state.feature_gate.features["web.rail_trackside_ap_plan"] = {
        "visible": True,
        "enabled": True,
        "client_package": True,
        "internal_only": False,
    }
    return paths, database, app


def _seed_stations(
    repository: AcRepository,
    station_names: list[str],
) -> dict[str, str]:
    result = repository.import_ap_extension_points(
        [
            {
                "site_id": "demo",
                "belong_type": "__base_station__",
                "station_name": station_name,
                "raw_payload_json": json.dumps(
                    {
                        "node_uid": f"station-{index}",
                        "canonical_station_name": station_name,
                        "sort_order": index,
                    },
                    ensure_ascii=False,
                ),
            }
            for index, station_name in enumerate(station_names, start=1)
        ],
        source_file="station-fixture.xlsx",
        template_type="station_fixture",
    )
    assert result["error_rows"] == 0
    return {
        str(row["station_name"]): str(row["id"])
        for row in repository.list_ap_extension_points()
        if str(row.get("belong_type") or "") == "__base_station__"
    }


def _plan_rows(station_names: list[str]) -> list[dict[str, object]]:
    return [
        {
            "sequence_no": index,
            "station_name": station_name,
            "ap_count": index,
            "management_vlan": 71,
            "remark": "",
            "sort_order": index - 1,
        }
        for index, station_name in enumerate(station_names, start=1)
    ]


def _checkpoint(database: Database) -> None:
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def test_database_readonly_connection_rejects_writes(tmp_path: Path) -> None:
    database = Database(tmp_path / "devices.db")
    database.initialize()

    with database.connect_readonly() as connection:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute(
                "INSERT INTO schema_metadata (key, value, created_at, updated_at) "
                "VALUES ('readonly-test', '1', 'now', 'now')"
            )


def test_database_readonly_connection_does_not_create_missing_database(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "missing" / "devices.db")

    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        database.connect_readonly()

    assert not database.path.exists()
    assert not database.path.parent.exists()


def test_plan_endpoint_returns_only_saved_sparse_rows_without_writing_database(
    tmp_path: Path,
) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    all_stations = [f"站点{index:02d}" for index in range(1, 30)]
    planned_stations = all_stations[14:]
    _seed_stations(repository, all_stations)
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        _plan_rows(planned_stations),
    )
    _checkpoint(database)
    hash_before = _database_hash(database.path)
    stat_before = database.path.stat()

    with TestClient(app) as client:
        response = client.get(PLAN_PATH)

    assert response.status_code == 200
    assert response.json()["total"] == 15
    assert [row["station_name"] for row in response.json()["items"]] == planned_stations
    assert response.headers["x-request-id"]
    assert response.headers["x-netconsole-backend-pid"] == str(os.getpid())
    assert _database_hash(database.path) == hash_before
    assert database.path.stat().st_mtime_ns == stat_before.st_mtime_ns


def test_empty_plan_does_not_generate_station_rows(tmp_path: Path) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    _seed_stations(repository, [f"站点{index:02d}" for index in range(1, 30)])

    with TestClient(app) as client:
        response = client.get(PLAN_PATH)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM ac_trackside_ap_plan WHERE mode = ?",
                (TRACKSIDE_AP_PLAN_MODE,),
            ).fetchone()[0]
            == 0
        )


def test_plan_endpoint_ignores_historical_vlan_groups(
    tmp_path: Path,
) -> None:
    _paths, database, app = _fixture(tmp_path)
    stamp = "2026-07-30T05:45:23.081241+00:00"
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO rail_ap_vlan_plans (
                line_id, planning_mode, auto_group_station_count,
                address_allocation_strategy, revision, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "current",
                "station_independent",
                1,
                "station_then_point",
                1,
                stamp,
                stamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO rail_ap_vlan_groups (
                group_id, line_id, group_code, group_name, sequence,
                management_vlan, created_at, updated_at
            )
            VALUES ('legacy-group', 'current', 'G001', '历史分组', 1, 71, ?, ?)
            """,
            (stamp, stamp),
        )
        connection.execute(
            """
            INSERT INTO rail_ap_vlan_group_members (
                group_id, station_id, station_name, station_sequence,
                ap_count, created_at, updated_at
            )
            VALUES ('legacy-group', 'legacy-station', '历史站点', 1, 11, ?, ?)
            """,
            (stamp, stamp),
        )
        connection.commit()

    with TestClient(app) as client:
        response = client.get(PLAN_PATH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0
    assert payload["planning"]["created_at"] == ""
    assert payload["planning"]["updated_at"] == ""


def test_vlan_planning_dtos_accept_timestamps_and_reject_unknown_fields() -> None:
    stamp = "2026-07-30T05:45:23+00:00"

    planning = ApManagementVlanPlanningDTO.model_validate(
        {"line_id": "current", "created_at": stamp, "updated_at": stamp}
    )
    assignment = ApManagementVlanAssignmentDTO.model_validate(
        {
            "assignment_id": "assignment-1",
            "target_id": "ap-1",
            "group_id": "group-1",
            "created_at": stamp,
            "updated_at": stamp,
        }
    )
    allocation = ApManagementVlanAllocationDTO.model_validate(
        {
            "ap_id": "ap-1",
            "group_id": "group-1",
            "created_at": stamp,
            "updated_at": stamp,
        }
    )

    assert planning.created_at == stamp
    assert assignment.created_at == stamp
    assert allocation.created_at == stamp
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ApManagementVlanPlanningDTO.model_validate(
            {"line_id": "current", "unknown_field": "should-fail"}
        )


def test_legacy_mode_rows_are_not_projected_during_write_lock(
    tmp_path: Path,
) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    _seed_stations(repository, ["站点A"])
    repository.replace_trackside_ap_plan_rows(
        "multi_vlan",
        _plan_rows(["站点A"]),
    )
    writer = database.connect()
    writer.execute("BEGIN IMMEDIATE")
    try:
        with TestClient(app) as client:
            response = client.get(PLAN_PATH)
    finally:
        writer.rollback()
        writer.close()

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM ac_trackside_ap_plan WHERE mode = ?",
                (TRACKSIDE_AP_PLAN_MODE,),
            ).fetchone()[0]
            == 0
        )


def test_old_station_name_is_bound_in_memory_without_persisting_station_id(
    tmp_path: Path,
) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    _seed_stations(repository, ["舞阳车辆段"])
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        _plan_rows(["15-舞阳车辆段"]),
    )

    with TestClient(app) as client:
        response = client.get(PLAN_PATH)

    assert response.status_code == 200
    assert response.json()["items"][0]["station_id"].startswith("station:")
    assert response.json()["items"][0]["station_name"] == "舞阳车辆段"
    with database.connect() as connection:
        stored = connection.execute(
            """
            SELECT station_id, station_name
            FROM ac_trackside_ap_plan
            WHERE mode = ?
            """,
            (TRACKSIDE_AP_PLAN_MODE,),
        ).fetchone()
    assert stored["station_id"] in {None, ""}
    assert stored["station_name"] == "15-舞阳车辆段"


def test_unmatched_old_station_is_returned_for_ui_diagnosis(tmp_path: Path) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    _seed_stations(repository, ["站点A"])
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        _plan_rows(["历史未匹配站"]),
    )

    with TestClient(app) as client:
        response = client.get(PLAN_PATH)

    assert response.status_code == 200
    assert response.json()["items"][0]["station_id"] == ""
    assert response.json()["items"][0]["station_name"] == "历史未匹配站"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    (
        (sqlite3.OperationalError("database is locked"), 503, "DEVICE_DATABASE_BUSY"),
        (RuntimeError("DTO serialization failed"), 500, "TRACKSIDE_AP_PLAN_LOAD_FAILED"),
    ),
)
def test_plan_endpoint_maps_failures_to_structured_response_and_keeps_backend_alive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    _paths, _database, app = _fixture(tmp_path)
    service = app.state.rail_transit_web_application_service

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(service, "get_trackside_ap_plan", fail)
    with TestClient(app) as client:
        response = client.get(PLAN_PATH)
        health = client.get("/api/health")

    assert response.status_code == status_code
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["path"] == PLAN_PATH
    assert detail["status"] == status_code
    assert detail["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-netconsole-backend-pid"] == str(os.getpid())
    assert health.status_code == 200


def test_plan_failure_log_redacts_credentials_and_contains_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, _database, app = _fixture(tmp_path)
    events: list[tuple[str, str]] = []
    service = app.state.rail_transit_web_application_service

    def fail(*_args, **_kwargs):
        raise RuntimeError("password=plain-secret")

    monkeypatch.setattr(service, "get_trackside_ap_plan", fail)
    monkeypatch.setattr(
        app_logger,
        "log_error",
        lambda event, detail="", **_kwargs: events.append((event, detail)),
    )
    with TestClient(app) as client:
        response = client.get(PLAN_PATH)

    assert response.status_code == 500
    failed = next(detail for event, detail in events if event == "trackside_ap_plan.request_failed")
    assert "plain-secret" not in failed
    assert "password=***" in failed
    assert "request_id=" in failed
    assert "traceback=Traceback" in failed


def test_plan_endpoint_is_stable_across_one_hundred_requests(tmp_path: Path) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    _seed_stations(repository, ["站点A"])
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        _plan_rows(["站点A"]),
    )
    _checkpoint(database)
    hash_before = _database_hash(database.path)

    with TestClient(app) as client:
        responses = [client.get(PLAN_PATH) for _ in range(100)]

    assert {response.status_code for response in responses} == {200}
    assert {response.json()["total"] for response in responses} == {1}
    assert {
        response.headers["x-netconsole-backend-pid"] for response in responses
    } == {str(os.getpid())}
    assert len({response.headers["x-request-id"] for response in responses}) == 100
    assert _database_hash(database.path) == hash_before


def test_plan_endpoint_supports_concurrent_readers(tmp_path: Path) -> None:
    _paths, database, app = _fixture(tmp_path)
    repository = AcRepository(database)
    _seed_stations(repository, ["站点A", "站点B"])
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        _plan_rows(["站点A", "站点B"]),
    )
    _checkpoint(database)
    hash_before = _database_hash(database.path)

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(lambda _index: client.get(PLAN_PATH), range(40)))

    assert {response.status_code for response in responses} == {200}
    assert {response.json()["total"] for response in responses} == {2}
    assert len({response.headers["x-request-id"] for response in responses}) == 40
    assert _database_hash(database.path) == hash_before
