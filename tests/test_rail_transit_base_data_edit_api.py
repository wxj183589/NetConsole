from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataCompensationError,
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


def _desktop_app(paths, tmp_path: Path):
    return create_app(
        RuntimeMode.DESKTOP,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
        desktop_session_token="d" * 40,
        rail_base_data_write_feature_enabled=True,
        rail_base_data_desktop_write_enabled=True,
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


def test_electron_session_can_update_site_metadata_and_preserve_unknown_fields(tmp_path: Path) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    metadata_path = paths.site_dir("demo") / "site_meta.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["custom_owner"] = "保留字段"
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with TestClient(_desktop_app(paths, tmp_path)) as client:
        session_response = client.post("/__desktop_session", data={"token": "d" * 40}, follow_redirects=False)
        session = client.get("/api/rail-transit/base-data/revision").json()
        saved = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [{
                    "entity_type": "site_metadata",
                    "action": "update",
                    "entity_id": "current",
                    "values": {"line_name": "新线路", "system_type": "信号", "network_domain": "default", "remark": "已维护"},
                }],
                "explicit_confirmation": True,
            },
        )
        summary = client.get("/api/rail-transit/base-data/summary").json()
    assert session_response.status_code == 303
    assert saved.status_code == 200
    assert summary["line_name"] == "新线路"
    assert summary["project_type"] == "信号"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["custom_owner"] == "保留字段"


def test_isolated_electron_session_explains_read_only_and_rejects_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NETCONSOLE_STORAGE_MODE", "isolated_test")
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    with TestClient(_desktop_app(paths, tmp_path)) as client:
        client.post("/__desktop_session", data={"token": "d" * 40}, follow_redirects=False)
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
    assert session.json()["storage_mode"] == "isolated_test"
    assert session.json()["can_write"] is False
    assert session.json()["write_denial_code"] == "ISOLATED_TEST_READONLY"
    assert session.json()["write_denial_reason"] == "隔离测试模式下禁止修改正式局点数据。"
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ISOLATED_TEST_READONLY"


def test_server_session_defaults_to_reject_real_site_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED", raising=False)
    monkeypatch.delenv("NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE", raising=False)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
    assert session["can_write"] is False


def test_metadata_compensation_failure_is_not_silently_swallowed(tmp_path: Path, monkeypatch) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    revision = repository.base_data_revision("demo")

    def fail_save(*_args, **_kwargs) -> None:
        raise OSError("write failed")

    def fail_restore(*_args, **_kwargs) -> None:
        raise OSError("restore failed")

    monkeypatch.setattr(SiteManager, "save_site_metadata", fail_save)
    monkeypatch.setattr(repository, "_restore_metadata_file", fail_restore)

    with pytest.raises(RailTransitBaseDataCompensationError, match="compensation failed"):
        repository.apply_base_data_changes(
            "demo",
            revision,
            [{
                "entity_type": "site_metadata",
                "action": "update",
                "entity_id": "current",
                "values": {"line_name": "线路", "system_type": "信号"},
            }],
        )


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


def test_station_source_confirmation_preserves_manual_fields_and_marks_stale_without_deleting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with Database(database).connect() as connection:
        before_counts = tuple(
            connection.execute(
                "SELECT (SELECT COUNT(*) FROM devices), (SELECT COUNT(*) FROM device_groups)"
            ).fetchone()
        )
    manual_values = {
        "name": "五乡",
        "code": "32",
        "line_name": "测试线",
        "sort_order": 32,
        "remark": "人工确认字段",
        "node_type": "station",
        "path_code": "MAIN",
        "participates_in_direction": True,
        "structure_type": "underground",
        "platform_layout": "island",
        "is_line_terminal": True,
        "is_service_terminal": True,
        "turnback_capable": True,
        "turnback_type": "crossover",
        "turnback_direction": "both",
        "enabled": True,
        "source_kind": "manual",
    }
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        created = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [{
                    "entity_type": "station",
                    "action": "create",
                    "entity_id": "station:new:wuxiang",
                    "values": manual_values,
                }],
                "explicit_confirmation": True,
            },
        )
        assert created.status_code == 200
        station = next(
            item for item in client.get("/api/rail-transit/base-data/stations?page_size=200").json()["items"]
            if item["name"] == "五乡"
        )
        source_values = {
            **manual_values,
            "old_name": "五乡",
            "source_station_value": "32-五乡",
            "source_station_key": "32-五乡",
            "source_kind": "device_station_field",
        }
        next_session = client.get("/api/rail-transit/base-data/revision").json()
        confirmed = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": next_session["base_revision"],
                "changes": [{
                    "entity_type": "station",
                    "action": "update",
                    "entity_id": station["id"],
                    "values": source_values,
                }],
                "explicit_confirmation": True,
            },
        )
        stations = client.get("/api/rail-transit/base-data/stations?page_size=200").json()["items"]
    assert confirmed.status_code == 200
    saved = next(item for item in stations if item["name"] == "五乡")
    assert saved["source_station_value"] == "32-五乡"
    assert saved["source_kind"] == "device_station_field"
    assert saved["source_sync_status"] == "stale"
    assert saved["source_device_count"] == 0
    assert saved["structure_type"] == "underground"
    assert saved["platform_layout"] == "island"
    assert saved["is_line_terminal"] is True
    assert saved["is_service_terminal"] is True
    assert saved["turnback_capable"] is True
    assert saved["turnback_type"] == "crossover"
    assert saved["turnback_direction"] == "both"
    assert saved["remark"] == "人工确认字段"
    with Database(database).connect() as connection:
        after_counts = tuple(
            connection.execute(
                "SELECT (SELECT COUNT(*) FROM devices), (SELECT COUNT(*) FROM device_groups)"
            ).fetchone()
        )
    assert after_counts == before_counts


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
