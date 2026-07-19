from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataConstraintError,
    RailTransitBaseDataRepository,
)
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy


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


def _enable_copy_write(monkeypatch) -> None:
    monkeypatch.setenv("RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED", "1")
    monkeypatch.setenv("NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE", "1")
    monkeypatch.delenv("NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE", raising=False)


def test_edit_session_defaults_to_locked_and_rejects_unapproved_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED", raising=False)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision")
        response = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session.json()["base_revision"],
                "changes": [],
                "explicit_confirmation": True,
            },
        )
    assert session.status_code == 200
    assert session.json()["can_write"] is False
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "BASE_DATA_WRITE_DISABLED"


def test_transactional_save_updates_ap_station_and_plan_with_revision(tmp_path: Path, monkeypatch) -> None:
    _enable_copy_write(monkeypatch)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        ap_id = client.get("/api/rail-transit/base-data/aps?page_size=1").json()["items"][0]["id"]
        changes = [
            {
                "entity_type": "station",
                "action": "create",
                "entity_id": "station:new",
                "values": {"name": "车站D", "code": "D", "sort_order": 4, "remark": "人工维护"},
            },
            {
                "entity_type": "trackside_ap",
                "action": "update",
                "entity_id": ap_id,
                "values": {
                    "name": "AP-Online",
                    "point_code": "AP001",
                    "mac": "0000-0000-0001",
                    "station": "车站D",
                    "mileage": "ZDK1+100",
                    "line_side": "左线",
                    "direction": "下行",
                    "remark": "统一保存",
                },
            },
            {
                "entity_type": "trackside_ap_plan",
                "action": "replace",
                "values": {
                    "rows": [
                        {
                            "station_name": "车站D",
                            "ap_count": 1,
                            "ap_start_address": "10.1.1.10",
                            "mask_length": 24,
                            "ap_gateway": "10.1.1.1",
                            "ap_management_vlans": "101",
                            "remark": "统一事务",
                        }
                    ]
                },
            },
            {
                "entity_type": "vehicle_mr",
                "action": "update",
                "entity_id": "mr-01-ct",
                "values": {
                    "name": "列车01-MR-CT",
                    "station": "列车01车头",
                    "management_ip": "10.10.0.11",
                    "mac": "0011-2233-4401",
                    "protocol": "SSH",
                    "port": 22,
                    "remark": "统一维护",
                },
            },
        ]
        validation = client.post(
            "/api/rail-transit/base-data/validate",
            json={"site_id": "demo", "base_revision": session["base_revision"], "changes": changes},
        )
        saved = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": changes,
                "explicit_confirmation": True,
            },
        )
        stale = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [],
                "explicit_confirmation": True,
            },
        )
        stations = client.get("/api/rail-transit/base-data/stations?page_size=200").json()["items"]

    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert saved.status_code == 200
    assert saved.json()["revision"] != session["base_revision"]
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "BASE_DATA_REVISION_CONFLICT"
    assert next(item for item in stations if item["name"] == "车站D")["code"] == "D"
    numeric_ap_id = int(ap_id.removeprefix("ap:"))
    with Database(database).connect() as connection:
        assert connection.execute("SELECT remark FROM ap_extension_points WHERE id = ?", (numeric_ap_id,)).fetchone()[0] == "统一保存"
        assert connection.execute("SELECT station_name FROM ac_trackside_ap_plan WHERE mode = 'unified'").fetchone()[0] == "车站D"
        assert tuple(connection.execute("SELECT primary_address, remark FROM devices WHERE device_uuid = 'mr-01-ct'").fetchone()) == ("10.10.0.11", "统一维护")


def test_repository_rolls_back_all_changes_when_later_entity_fails(tmp_path: Path) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    revision = repository.database_hash("demo")
    with pytest.raises(RailTransitBaseDataConstraintError):
        repository.apply_base_data_changes(
            "demo",
            revision,
            [
                {
                    "entity_type": "trackside_ap",
                    "action": "update",
                    "entity_id": "ap:1",
                    "values": {"ap_name": "AP-Online", "remark": "不得提交"},
                },
                {
                    "entity_type": "vehicle_mr",
                    "action": "update",
                    "entity_id": "missing-device",
                    "values": {"name": "列车99-MR-CT", "primary_address": "10.9.9.9"},
                },
            ],
        )
    with Database(database).connect() as connection:
        assert connection.execute("SELECT remark FROM ap_extension_points WHERE id = 1").fetchone()[0] == ""


def test_validation_rejects_sensitive_fields(tmp_path: Path, monkeypatch) -> None:
    _enable_copy_write(monkeypatch)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        response = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [
                    {
                        "entity_type": "vehicle_mr",
                        "action": "update",
                        "entity_id": "mr-01-ct",
                        "values": {"name": "列车01-MR-CT", "primary_address": "10.10.0.1", "password": "secret"},
                    }
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["issues"][0]["code"] == "BASE_DATA_VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {"station_name": "A", "ap_count": 10, "ap_start_address": "10.0.0.1", "mask_length": 30, "ap_gateway": "10.0.0.2", "ap_management_vlans": "101"},
            ],
            "容量不足",
        ),
        (
            [
                {"station_name": "A", "ap_count": 1, "ap_start_address": "10.0.0.1", "mask_length": 24, "ap_gateway": "10.0.0.254", "ap_management_vlans": "101"},
                {"station_name": "B", "ap_count": 1, "ap_start_address": "10.0.0.129", "mask_length": 25, "ap_gateway": "10.0.0.130", "ap_management_vlans": "102"},
            ],
            "网段冲突",
        ),
    ],
)
def test_plan_validation_rejects_capacity_and_network_conflicts(
    tmp_path: Path,
    monkeypatch,
    rows: list[dict[str, object]],
    message: str,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        response = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [{"entity_type": "trackside_ap_plan", "action": "replace", "values": {"rows": rows}}],
            },
        )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert message in response.json()["issues"][0]["message"]
