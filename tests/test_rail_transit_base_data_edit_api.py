from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.application.rail_transit.base_data_application_service import (
    RailTransitBaseDataApplicationService,
)
from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataCompensationError,
    RailTransitBaseDataConstraintError,
    RailTransitBaseDataRepository,
)
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def test_trackside_ap_special_location_cannot_participate_in_mainline() -> None:
    with pytest.raises(
        RailTransitBaseDataConstraintError,
        match="不能同时设置为参与正线判断",
    ):
        RailTransitBaseDataRepository._safe_values(
            {
                "location_class": "DEPOT",
                "participates_in_mainline": True,
                "location_class_source": "MANUAL_EXPLICIT",
            }
        )


def test_new_trackside_ap_without_location_defaults_to_mainline() -> None:
    values = RailTransitBaseDataApplicationService._ap_values(
        {
            "ap_name": "AP-NEW",
            "station_name": "正线站",
        },
        "create",
    )

    assert values["location_class"] == "MAINLINE"
    assert values["participates_in_mainline"] is True
    assert values["location_class_source"] == "DEFAULT_MAINLINE"


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


def test_clear_all_removes_formal_and_legacy_locations_but_preserves_assets(
    tmp_path: Path, monkeypatch
) -> None:
    _enable_copy_write(monkeypatch)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with Database(database).connect() as connection:
        connection.execute("UPDATE ap_extension_points SET site_id = NULL")
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_name, ap_point_code, raw_payload_json,
                created_at, updated_at
            ) VALUES (NULL, '__base_station__', '正式站', '-', ?, '2026-07-28', '2026-07-28')
            """,
            (json.dumps({"sort_order": 99, "source_kind": "manual"}, ensure_ascii=False),),
        )
        connection.execute(
            """
            INSERT INTO ac_trackside_ap_plan (
                mode, station_name, ap_count, ap_management_vlans, created_at, updated_at
            ) VALUES ('unified', '正式站', 1, '101', '2026-07-28', '2026-07-28')
            """
        )
        connection.execute(
            """
            INSERT INTO rail_ap_vlan_plans (
                line_id, planning_mode, auto_group_station_count,
                address_allocation_strategy, revision, created_at, updated_at
            ) VALUES ('legacy-retained', 'line_single', 1,
                      'station_then_point', 7, '2026-07-28', '2026-07-28')
            """
        )
        connection.commit()
    with TestClient(_app(paths, tmp_path)) as client:
        preview = client.get("/api/rail-transit/base-data/clear-preview")
        first = client.post(
            "/api/rail-transit/base-data/clear-all",
            json={
                "site_id": "demo",
                "base_revision": preview.json()["base_revision"],
                "explicit_confirmation": True,
            },
        )
        stations = client.get("/api/rail-transit/base-data/stations?page_size=200")
        sections = client.get("/api/rail-transit/base-data/sections?page_size=200")
        aps = client.get("/api/rail-transit/base-data/aps?page_size=200")
        second_preview = client.get("/api/rail-transit/base-data/clear-preview")
        second = client.post(
            "/api/rail-transit/base-data/clear-all",
            json={
                "site_id": "demo",
                "base_revision": second_preview.json()["base_revision"],
                "explicit_confirmation": True,
            },
        )
        stale = client.post(
            "/api/rail-transit/base-data/clear-all",
            json={
                "site_id": "demo",
                "base_revision": preview.json()["base_revision"],
                "explicit_confirmation": True,
            },
        )

    assert preview.status_code == 200
    assert preview.json()["station_count"] == 4
    assert preview.json()["section_count"] == 3
    assert preview.json()["affected_trackside_ap_count"] == 3
    assert first.status_code == 200
    assert first.json()["deleted_station_count"] == 4
    assert first.json()["deleted_section_count"] == 3
    assert first.json()["unlinked_trackside_ap_count"] == 3
    assert stations.json()["total"] == 0
    assert sections.json()["total"] == 0
    assert aps.json()["total"] == 3
    assert second.status_code == 200
    assert second.json()["deleted_station_count"] == 0
    assert second.json()["deleted_section_count"] == 0
    assert second.json()["unlinked_trackside_ap_count"] == 0
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "BASE_DATA_REVISION_CONFLICT"
    with Database(database).connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] >= 3
        assert connection.execute("SELECT COUNT(*) FROM ac_trackside_ap_plan").fetchone()[0] == 0
        assert connection.execute(
            "SELECT revision FROM rail_ap_vlan_plans WHERE line_id = 'legacy-retained'"
        ).fetchone()[0] == 7
        rows = connection.execute(
            """
            SELECT station_name, section_name, section_start_station, section_end_station,
                   line_side, direction, raw_payload_json
            FROM ap_extension_points
            """
        ).fetchall()
    assert len(rows) == 3
    assert all(tuple(row[:6]) == ("", "", "", "", "", "") for row in rows)
    assert all(json.loads(row[6]) == {} for row in rows)


def test_delete_legacy_derived_station_unlinks_ap_and_related_section(
    tmp_path: Path, monkeypatch
 ) -> None:
    _enable_copy_write(monkeypatch)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        revision = client.get("/api/rail-transit/base-data/revision").json()["base_revision"]
        station = next(
            item
            for item in client.get("/api/rail-transit/base-data/stations?page_size=200").json()["items"]
            if item["name"] == "车站A"
        )
        response = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": revision,
                "changes": [{
                    "entity_type": "station",
                    "action": "delete",
                    "entity_id": station["id"],
                    "values": {"name": "车站A", "old_name": "车站A"},
                }],
                "explicit_confirmation": True,
            },
        )
        stations = client.get("/api/rail-transit/base-data/stations?page_size=200").json()
        sections = client.get("/api/rail-transit/base-data/sections?page_size=200").json()
        aps = client.get("/api/rail-transit/base-data/aps?page_size=200").json()

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert "车站A" not in {item["name"] for item in stations["items"]}
    assert "A-B 区间" not in {item["name"] for item in sections["items"]}
    assert aps["total"] == 3
    with Database(database).connect() as connection:
        ap = connection.execute(
            """
            SELECT station_name, section_name, section_start_station, section_end_station,
                   line_side, direction
            FROM ap_extension_points WHERE ap_name = 'AP-Online'
            """
        ).fetchone()
    assert tuple(ap) == ("", "", "", "", "", "")


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
                    "values": {
                        "line_name": "新线路",
                        "system_type": "信号",
                        "network_domain": "default",
                        "increasing_direction_leading_end": "car_1_end",
                        "remark": "已维护",
                    },
                }],
                "explicit_confirmation": True,
            },
        )
        summary = client.get("/api/rail-transit/base-data/summary").json()
    assert session_response.status_code == 303
    assert saved.status_code == 200, saved.text
    assert summary["line_name"] == "新线路"
    assert summary["project_type"] == "信号"
    assert summary["increasing_direction_leading_end"] == "car_1_end"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["custom_owner"] == "保留字段"
    assert metadata["increasing_direction_leading_end"] == "car_1_end"


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
        ap_id = next(
            row["id"]
            for row in client.get("/api/rail-transit/base-data/aps?page_size=200").json()["items"]
            if row["name"] == "AP-Online"
        )
        station_ids = {
            row["name"]: row["id"]
            for row in client.get("/api/rail-transit/base-data/stations?page_size=200").json()["items"]
        }
        new_station_id = "station:test-transaction-d"
        changes = [
            {
                "entity_type": "station",
                "action": "create",
                "entity_id": new_station_id,
                "values": {"name": "车站D", "code": "D", "sort_order": 4, "remark": "人工维护"},
            },
            {
                "entity_type": "trackside_ap",
                "action": "update",
                "entity_id": ap_id,
                "values": {
                    "name": "AP-Online",
                    "point_code": "AP001",
                    "vendor": "H3C",
                    "mac": "0000-0000-0099",
                    "station_id": new_station_id,
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
                            "station_id": station_ids["车站A"],
                            "station_name": "车站A",
                            "ap_count": 1,
                            "ap_start_address": "10.1.10.10",
                            "mask_length": 24,
                            "ap_gateway": "10.1.10.1",
                            "ap_management_vlans": "110",
                            "remark": "兼容现有站点",
                        },
                        {
                            "station_id": station_ids["车站B"],
                            "station_name": "车站B",
                            "ap_count": 1,
                            "ap_start_address": "10.1.11.10",
                            "mask_length": 24,
                            "ap_gateway": "10.1.11.1",
                            "ap_management_vlans": "111",
                            "remark": "兼容现有站点",
                        },
                        {
                            "station_id": station_ids["车站C"],
                            "station_name": "车站C",
                            "ap_count": 1,
                            "ap_start_address": "10.1.12.10",
                            "mask_length": 24,
                            "ap_gateway": "10.1.12.1",
                            "ap_management_vlans": "112",
                            "remark": "兼容现有站点",
                        },
                        {
                            "station_id": new_station_id,
                            "station_name": "车站D",
                            "ap_count": 1,
                            "ap_start_address": "10.1.1.10",
                            "mask_length": 24,
                            "ap_gateway": "10.1.1.1",
                            "ap_management_vlans": "101",
                            "remark": "统一事务",
                        },
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
    assert validation.json()["valid"] is True, validation.text
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] != session["base_revision"]
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "BASE_DATA_REVISION_CONFLICT"
    assert next(item for item in stations if item["name"] == "车站D")["code"] == "D"
    numeric_ap_id = int(ap_id.removeprefix("ap:"))
    with Database(database).connect() as connection:
        assert connection.execute("SELECT remark FROM ap_extension_points WHERE id = ?", (numeric_ap_id,)).fetchone()[0] == "统一保存"
        assert connection.execute("SELECT ap_vendor FROM ap_extension_points WHERE id = ?", (numeric_ap_id,)).fetchone()[0] == "H3C"
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM ac_trackside_ap_plan
            WHERE mode = 'unified' AND station_name = '车站D'
            """
            ).fetchone()[0]
            == 1
        )
        assert tuple(
            connection.execute(
                """
                SELECT primary_address, normalized_primary_address, remark
                FROM devices
                WHERE device_uuid = 'mr-01-ct'
                """
            ).fetchone()
        ) == ("10.10.0.11", "10.10.0.11", "统一维护")
        identity_state = connection.execute(
            """
            SELECT source_revision
            FROM ap_identity_index_state
            WHERE site_id = 'current'
            """
        ).fetchone()
        source_revision = connection.execute(
            """
            SELECT revision
            FROM ap_identity_source_state
            WHERE site_id = 'current'
            """
        ).fetchone()
        assert identity_state is not None
        assert source_revision is not None
        assert identity_state["source_revision"] == source_revision["revision"]


def test_ap_section_change_recalculates_auto_side_and_mapping_change_preserves_manual_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)

    def section_values(name: str, code: str, role: str, direction: str, side: str) -> dict[str, object]:
        return {
            "name": name,
            "section_code": code,
            "section_kind": "between_stations",
            "path_code": "MAIN",
            "direction_role": role,
            "line_direction": direction,
            "start_node_type": "legacy",
            "start_station": "高桥西",
            "end_node_type": "legacy",
            "end_station": "高桥",
            "line_side": side,
            "source_kind": "manual",
        }

    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [
            {
                "entity_type": "section",
                "action": "create",
                "entity_id": "new:up",
                "values": section_values("高桥西-高桥-上行", "SEC-UP", "increasing", "上行", "右线"),
            },
            {
                "entity_type": "section",
                "action": "create",
                "entity_id": "new:down",
                "values": section_values("高桥西-高桥-下行", "SEC-DOWN", "decreasing", "下行", "左线"),
            },
        ],
    )
    with Database(database).connect() as connection:
        section_ids = {
            str(row["section_name"]): str(row["section_id"])
            for row in connection.execute(
                """
                SELECT section_id, section_name
                FROM ap_extension_points
                WHERE belong_type = '__base_section__' AND section_name IN (?, ?)
                """,
                ("高桥西-高桥-上行", "高桥西-高桥-下行"),
            )
        }
        connection.execute(
            """
            UPDATE ap_extension_points
            SET section_id = ?, section_name = '高桥西-高桥-上行', line_side = '', raw_payload_json = '{}'
            WHERE ap_name = 'AP-Section'
            """,
            (section_ids["高桥西-高桥-上行"],),
        )
        connection.execute(
            """
            UPDATE ap_extension_points
            SET section_id = ?, section_name = '高桥西-高桥-上行', line_side = '右线',
                raw_payload_json = '{"line_side_source":"manual"}'
            WHERE ap_name = 'AP-Online'
            """,
            (section_ids["高桥西-高桥-上行"],),
        )
        connection.commit()
    mark_base_data_copy(paths)

    with TestClient(_app(paths, tmp_path)) as client:
        revision = client.get("/api/rail-transit/base-data/revision").json()["base_revision"]
        ap = next(
            item
            for item in client.get("/api/rail-transit/base-data/aps?page_size=200").json()["items"]
            if item["name"] == "AP-Section"
        )
        assert (ap["line_side"], ap["line_side_source"]) == ("右线", "section_direction")
        changed = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": revision,
                "changes": [
                    {
                        "entity_type": "trackside_ap",
                        "action": "update",
                        "entity_id": ap["id"],
                        "values": {
                            "ap_name": ap["name"],
                            "ap_point_code": ap["point_code"],
                            "ap_mac_display": ap["mac"],
                            "section_id": section_ids["高桥西-高桥-下行"],
                            "section_name": "高桥西-高桥-下行",
                            "line_side": ap["line_side"],
                            "direction": "下行",
                            "base_metadata": ap["base_metadata"],
                        },
                    }
                ],
                "explicit_confirmation": True,
            },
        )
        assert changed.status_code == 200

        next_revision = client.get("/api/rail-transit/base-data/revision").json()["base_revision"]
        reversed_mapping = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": next_revision,
                "changes": [
                    {
                        "entity_type": "site_metadata",
                        "action": "update",
                        "entity_id": "current",
                        "values": {
                            "line_name": "测试线",
                            "system_type": "PIS",
                            "network_domain": "default",
                            "increasing_direction_name": "上行",
                            "decreasing_direction_name": "下行",
                            "increasing_direction_line_side": "左线",
                            "decreasing_direction_line_side": "右线",
                        },
                    }
                ],
                "explicit_confirmation": True,
            },
        )
        summary = client.get("/api/rail-transit/base-data/summary").json()

    assert reversed_mapping.status_code == 200
    assert summary["increasing_direction_line_side"] == "左线"
    with Database(database).connect() as connection:
        auto_row = connection.execute(
            "SELECT section_name, line_side, raw_payload_json FROM ap_extension_points WHERE ap_name = 'AP-Section'"
        ).fetchone()
        manual_row = connection.execute(
            "SELECT line_side, raw_payload_json FROM ap_extension_points WHERE ap_name = 'AP-Online'"
        ).fetchone()
    assert (auto_row[0], auto_row[1]) == ("高桥西-高桥-下行", "右线")
    assert json.loads(auto_row[2])["line_side_source"] == "section_direction"
    assert manual_row[0] == "右线"
    assert json.loads(manual_row[1])["line_side_source"] == "manual"
    query_service = RailTransitBaseDataQueryService(paths)
    manual_ap = next(
        item
        for item in query_service.list_aps("demo", page_size=200).items
        if item.name == "AP-Online"
    )
    assert any(
        issue.code == "ap_line_side_section_conflict"
        for issue in query_service.get_ap("demo", manual_ap.id).issues
    )


def test_twenty_six_source_devices_create_eleven_stable_station_relations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    now = "2026-08-01T08:00:00+08:00"
    with Database(database).connect() as connection:
        group_id = connection.execute(
            """
            INSERT INTO device_groups (site_id, name, sort_order, created_at, updated_at)
            VALUES ('demo', '车站', 2, ?, ?)
            """,
            (now, now),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO devices (
                device_uuid, name, system_name, station, station_id, group_id,
                primary_address, device_vendor, device_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '', ?, ?, 'H3C', 'SWITCH', ?, ?)
            """,
            [
                (
                    f"source-device-{index:02d}",
                    f"来源设备{index:02d}",
                    f"SOURCE-{index:02d}",
                    (
                        f"{station_index + 20:02d}-验收站{station_index:02d}"
                        if station_index < 11
                        else "31-验收车辆段"
                    ),
                    group_id,
                    f"10.88.0.{index}",
                    now,
                    now,
                )
                for index, station_index in (
                    (index, ((index - 1) % 11) + 1)
                    for index in range(1, 27)
                )
            ],
        )
        connection.commit()
    mark_base_data_copy(paths)

    with TestClient(_app(paths, tmp_path)) as client:
        preview = client.get(
            "/api/rail-transit/base-data/station-source-preview"
        ).json()
        assert preview["scanned_device_count"] == 26
        assert len(preview["candidates"]) == 11
        assert preview["normal_station_count"] == 10
        assert preview["special_node_count"] == 1
        depot_candidate = next(
            item for item in preview["candidates"]
            if item["proposed_station"]["node_type"] == "depot"
        )
        assert depot_candidate["proposed_station"]["participates_in_direction"] is False
        assert sum(
            len(candidate["source_device_ids"])
            for candidate in preview["candidates"]
        ) == 26
        revision = client.get(
            "/api/rail-transit/base-data/revision"
        ).json()["base_revision"]
        station_changes = []
        bindings = []
        plan_rows = []
        for sequence_no, candidate in enumerate(preview["candidates"], start=1):
            proposed = candidate["proposed_station"]
            stable_id = proposed["id"]
            assert stable_id.startswith("station:")
            station_changes.append(
                {
                    "entity_type": "station",
                    "action": "create",
                    "entity_id": stable_id,
                    "values": proposed,
                }
            )
            bindings.extend(
                {
                    "device_id": device_id,
                    "station_id": stable_id,
                    "source": "station_source_preview",
                }
                for device_id in candidate["source_device_ids"]
            )
            plan_rows.append(
                {
                    "station_id": stable_id,
                    "station_name": proposed["name"],
                    "sequence_no": sequence_no,
                    "planned_ap_count": 0,
                    "management_vlan": None,
                    "remark": "来源生成",
                }
            )
        changes = [
            *station_changes,
            {
                "entity_type": "device_station_binding",
                "action": "replace",
                "entity_id": "current",
                "values": {"bindings": bindings},
            },
            {
                "entity_type": "trackside_ap_plan",
                "action": "replace",
                "entity_id": "current",
                "values": {"rows": plan_rows},
            },
        ]
        validation = client.post(
            "/api/rail-transit/base-data/validate",
            json={"site_id": "demo", "base_revision": revision, "changes": changes},
        )
        assert validation.status_code == 200, validation.text
        assert validation.json()["valid"] is True, validation.text
        saved = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": revision,
                "changes": changes,
                "explicit_confirmation": True,
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["device_binding_count"] == 26
        assert saved.json()["planning_row_count"] == 11
        snapshot = client.get("/api/rail-transit/base-data/edit-snapshot")
        assert snapshot.status_code == 200, snapshot.text
        snapshot_payload = snapshot.json()
        generated_stations = [
            item for item in snapshot_payload["stations"]
            if item["name"].startswith("验收")
        ]
        assert len(generated_stations) == 11
        assert len(snapshot_payload["trackside_ap_plans"]) == 11
        depot = next(
            item for item in generated_stations
            if item["node_type"] == "depot"
        )
        depot_plan = next(
            item for item in snapshot_payload["trackside_ap_plans"]
            if item["station_id"] == depot["id"]
        )
        assert depot["participates_in_direction"] is False
        assert depot_plan["relation_status"] == "resolved"
        assert depot_plan["planned_ap_count"] == 0
        assert depot_plan["management_vlan"] is None
        section_preview = client.post(
            "/api/rail-transit/base-data/section-generation-preview",
            json={
                "site_id": "demo",
                "base_revision": snapshot_payload["base_revision"],
                "line_metadata": {
                    "main_path_code": "MAIN",
                    "increasing_direction_name": "上行",
                    "decreasing_direction_name": "下行",
                    "increasing_direction_line_side": "右线",
                    "decreasing_direction_line_side": "左线",
                },
                "stations": generated_stations,
                "current_sections": [],
            },
        )
        assert section_preview.status_code == 200, section_preview.text
        generated_sections = [
            item["proposed_section"]
            for item in section_preview.json()["generated_sections"]
            if item["proposed_section"] is not None
        ]
        assert all(
            depot["node_uid"] not in {
                section["start_node_uid"],
                section["end_node_uid"],
            }
            for section in generated_sections
        )
        current_revision = client.get(
            "/api/rail-transit/base-data/revision"
        ).json()["base_revision"]
        preflight = client.post(
            "/api/rail-transit/base-data/stations/delete-preflight",
            json={
                "site_id": "demo",
                "base_revision": current_revision,
                "station_ids": [plan_rows[0]["station_id"]],
            },
        )
        assert preflight.status_code == 200, preflight.text
        preflight_item = preflight.json()["items"][0]
        assert preflight_item["status"] == "REQUIRES_MERGE"
        assert preflight_item["references"]["device_count"] == 3
        assert preflight_item["references"]["plan_count"] == 1

    expected_ids = {row["station_id"] for row in plan_rows}
    with Database(database).connect_readonly() as connection:
        device_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT station_id FROM devices WHERE device_uuid LIKE 'source-device-%'"
            )
        }
        master_ids = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT station_id FROM ap_extension_points
                WHERE belong_type = '__base_station__' AND station_name LIKE '验收%'
                """
            )
        }
        plan_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT station_id FROM ac_trackside_ap_plan WHERE mode = 'unified'"
            )
        }
    assert device_ids == expected_ids
    assert master_ids == expected_ids
    assert plan_ids == expected_ids


def test_generated_section_edit_persists_overrides_and_cascades_all_named_ap_references(tmp_path: Path) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    with Database(database).connect() as connection:
        connection.execute(
            "UPDATE ap_extension_points SET section_name = '自动区间' WHERE section_name = 'A-B 区间'"
        )
        connection.commit()
    create_values = {
        "name": "自动区间",
        "section_code": "AUTO-001",
        "section_kind": "between_stations",
        "path_code": "MAIN",
        "direction_role": "increasing",
        "line_direction": "上行",
        "start_node_type": "station",
        "start_node_uid": "node-a",
        "start_station": "车站A",
        "end_node_type": "station",
        "end_node_uid": "node-b",
        "end_station": "车站B",
        "line_side": "上行",
        "auto_generated": True,
        "generation_key": "MAIN|between|node-a|node-b|increasing",
        "manual_override_fields": [],
        "section_mileage_start_m": 100,
        "section_mileage_end_m": 200,
        "section_mileage_open_end": False,
        "section_mileage_source": "generated",
        "enabled": True,
        "source_kind": "generated",
        "remark": "保留备注",
    }
    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [{"entity_type": "section", "action": "create", "entity_id": "new:auto", "values": create_values}],
    )
    update_values = {
        **create_values,
        "name": "现场专用区间",
        "old_name": "自动区间",
        "old_start_station": "车站A",
        "old_end_station": "车站B",
        "old_line_side": "上行",
        "start_node_uid": "node-a-adjusted",
        "manual_override_fields": ["name", "section_mileage_start_m", "section_mileage_source", "start_node_uid"],
        "section_mileage_start_m": 110,
        "section_mileage_source": "manual",
    }

    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [{"entity_type": "section", "action": "update", "entity_id": "section:auto", "values": update_values}],
    )

    saved = next(
        item
        for item in RailTransitBaseDataQueryService(paths).list_sections("demo", page_size=200).items
        if item.generation_key == create_values["generation_key"]
    )
    assert saved.name == "现场专用区间"
    assert saved.start_node_uid == "node-a-adjusted"
    assert set(saved.manual_override_fields) == {"name", "section_mileage_source", "section_mileage_start_m", "start_node_uid"}
    assert (saved.section_mileage_start_m, saved.section_mileage_end_m) == (110, 200)
    assert saved.section_mileage_source == "manual"
    assert saved.auto_generated is True
    assert saved.source_kind == "generated"
    assert saved.generation_key == create_values["generation_key"]
    with Database(database).connect() as connection:
        references = connection.execute(
            """
            SELECT DISTINCT section_name FROM ap_extension_points
            WHERE belong_type NOT IN ('__base_station__', '__base_section__')
              AND ap_name IN ('AP-Online', 'AP-Section')
            """
        ).fetchall()
    assert {row[0] for row in references} == {"现场专用区间"}


def test_section_physical_mileage_validation_rejects_invalid_ranges(tmp_path: Path) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    base_values = {
        "name": "非法范围区间",
        "section_kind": "between_stations",
        "path_code": "MAIN",
        "direction_role": "increasing",
        "line_direction": "上行",
        "start_node_type": "station",
        "start_node_uid": "node-a",
        "start_station": "车站A",
        "end_node_type": "station",
        "end_node_uid": "node-b",
        "end_station": "车站B",
        "line_side": "上行",
        "section_mileage_start_m": 200,
        "section_mileage_end_m": 100,
        "section_mileage_open_end": False,
        "section_mileage_source": "manual",
        "source_kind": "manual",
    }
    with TestClient(_app(paths, tmp_path)) as client:
        revision = client.get("/api/rail-transit/base-data/revision").json()["base_revision"]
        reversed_range = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": revision,
                "changes": [{"entity_type": "section", "action": "create", "entity_id": "new:invalid", "values": base_values}],
            },
        )
        ordinary_open_end = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": revision,
                "changes": [{
                    "entity_type": "section",
                    "action": "create",
                    "entity_id": "new:open",
                    "values": {
                        **base_values,
                        "section_mileage_start_m": 100,
                        "section_mileage_end_m": None,
                        "section_mileage_open_end": True,
                    },
                }],
            },
        )

    assert reversed_range.status_code == 200
    assert reversed_range.json()["valid"] is False
    assert reversed_range.json()["issues"][0]["code"] == "section_mileage_range_invalid"
    assert ordinary_open_end.status_code == 200
    assert ordinary_open_end.json()["valid"] is False
    assert ordinary_open_end.json()["issues"][0]["code"] == "section_mileage_open_end_invalid"


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
            "source_station_key": "五乡",
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
    assert saved["source_station_key"] == "五乡"
    assert saved["source_order_text"] == "32"
    assert saved["source_order"] == 32
    assert saved["canonical_station_name"] == "五乡"
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


def test_repository_vehicle_mr_write_uses_normalized_unique_address(
    tmp_path: Path,
) -> None:
    paths, database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    first_revision = repository.database_hash("demo")
    repository.apply_base_data_changes(
        "demo",
        first_revision,
        [
            {
                "entity_type": "vehicle_mr",
                "action": "update",
                "entity_id": "mr-01-ct",
                "values": {
                    "name": "列车01-MR-CT",
                    "station": "列车01车头",
                    "primary_address": "2001:0db8:0:0:0:0:0:1",
                },
            }
        ],
    )

    with pytest.raises(
        RailTransitBaseDataConstraintError,
        match="车载 MR 管理地址 2001:db8::1 在当前局点内已被其他设备使用",
    ):
        repository.apply_base_data_changes(
            "demo",
            repository.database_hash("demo"),
            [
                {
                    "entity_type": "vehicle_mr",
                    "action": "update",
                    "entity_id": "mr-01-cw",
                    "values": {
                        "name": "列车01-MR-CW",
                        "station": "列车01车尾",
                        "primary_address": "2001:db8::1",
                    },
                }
            ],
        )

    with Database(database).connect() as connection:
        rows = connection.execute(
            """
            SELECT device_uuid, primary_address, normalized_primary_address
            FROM devices
            WHERE device_uuid IN ('mr-01-ct', 'mr-01-cw')
            ORDER BY device_uuid
            """
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("mr-01-ct", "2001:db8::1", "2001:db8::1"),
            ("mr-01-cw", "10.10.0.2", "10.10.0.2"),
        ]


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


def test_plan_validation_and_save_ignore_ip_reference_conflicts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        stations = client.get(
            "/api/rail-transit/base-data/stations?page_size=200"
        ).json()["items"]
        changes = [
            {
                "entity_type": "trackside_ap_plan",
                "action": "replace",
                "values": {
                    "planning": {
                        "line_id": "current",
                        "planning_mode": "line_single",
                        "auto_group_station_count": 1,
                        "revision": 0,
                    },
                    "groups": [
                        {
                            "group_id": "all-stations",
                            "group_code": "G001",
                            "group_name": "全线统一 VLAN",
                            "sequence": 0,
                            "management_vlan": 71,
                            "network_address": "10.92.68.0",
                            "prefix_length": 99,
                            "subnet_mask": "invalid-mask-reference",
                            "default_gateway": "10.92.71.254",
                            "ap_start_ip": "192.0.2.9",
                            "ap_end_ip": "invalid-end-reference",
                            "members": [
                                {
                                    "station_id": station["id"],
                                    "station_name": station["name"],
                                    "station_sequence": station["sort_order"],
                                    "ap_count": station["ap_count"],
                                }
                                for station in stations
                            ],
                        }
                    ],
                    "assignments": [],
                    "allocations": [],
                },
            }
        ]
        response = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": changes,
            },
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
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert not response.json()["issues"]
    assert saved.status_code == 200


def test_plan_only_save_does_not_rebuild_ap_identity_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("规划-only 保存不应触发 AP Identity 索引重建")

    monkeypatch.setattr(
        RailTransitBaseDataApplicationService,
        "_ensure_ap_identity_index",
        fail_rebuild,
    )

    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        station = client.get(
            "/api/rail-transit/base-data/stations?page_size=200"
        ).json()["items"][0]
        response = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [{
                    "entity_type": "trackside_ap_plan",
                    "action": "replace",
                    "values": {
                        "rows": [{
                            "station_id": station["id"],
                            "sequence_no": 1,
                            "station_name": station["name"],
                            "planned_ap_count": 1,
                            "management_vlan": 71,
                            "remark": "",
                        }],
                    },
                }],
                "explicit_confirmation": True,
            },
        )

    assert response.status_code == 200


def test_identity_refresh_is_invoked_once_after_multi_domain_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    calls: list[tuple[str, str]] = []

    def record_refresh(_self, site_id: str, reason: str) -> bool:
        calls.append((site_id, reason))
        return True

    monkeypatch.setattr(
        RailTransitBaseDataApplicationService,
        "_ensure_ap_identity_index",
        record_refresh,
    )

    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        station = client.get(
            "/api/rail-transit/base-data/stations?page_size=200"
        ).json()["items"][0]
        response = client.post(
            "/api/rail-transit/base-data/changes",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": [
                    {
                        "entity_type": "station",
                        "action": "update",
                        "entity_id": station["id"],
                        "values": {
                            **station,
                            "old_name": station["name"],
                            "remark": "统一事务刷新一次",
                        },
                    },
                    {
                        "entity_type": "trackside_ap_plan",
                        "action": "replace",
                        "entity_id": "current",
                        "values": {
                            "rows": [
                                {
                                    "station_id": station["id"],
                                    "sequence_no": 1,
                                    "station_name": station["name"],
                                    "planned_ap_count": 0,
                                    "management_vlan": None,
                                    "remark": "",
                                }
                            ]
                        },
                    },
                ],
                "explicit_confirmation": True,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["ap_identity_refreshed"] is True
    assert calls == [("demo", "base_data_changes_saved")]


def test_zero_count_trackside_plan_saves_null_management_vlan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_copy_write(monkeypatch)
    paths, database_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with TestClient(_app(paths, tmp_path)) as client:
        session = client.get("/api/rail-transit/base-data/revision").json()
        station = client.get(
            "/api/rail-transit/base-data/stations?page_size=200"
        ).json()["items"][0]
        changes = [
            {
                "entity_type": "trackside_ap_plan",
                "action": "replace",
                "values": {
                    "rows": [
                        {
                            "station_id": station["id"],
                            "sequence_no": 1,
                            "station_name": station["name"],
                            "planned_ap_count": 0,
                            "management_vlan": None,
                            "remark": "尚未规划",
                        }
                    ]
                },
            }
        ]
        validation = client.post(
            "/api/rail-transit/base-data/validate",
            json={
                "site_id": "demo",
                "base_revision": session["base_revision"],
                "changes": changes,
            },
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

    with Database(database_path).connect() as connection:
        row = connection.execute(
            """
            SELECT ap_count, management_vlan, ap_management_vlans
            FROM ac_trackside_ap_plan
            WHERE mode = 'unified'
            """
        ).fetchone()

    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert saved.status_code == 200
    assert tuple(row) == (0, None, "")
