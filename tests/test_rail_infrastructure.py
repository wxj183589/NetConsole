import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.rail_infrastructure_schema import RAIL_INFRASTRUCTURE_TABLES
from netconsole.repositories.rail_infrastructure_repository import RailInfrastructureRepository
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from tests.support.rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


def test_official_initialization_and_additive_legacy_upgrade(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    with closing(database.connect()) as conn, conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert RAIL_INFRASTRUCTURE_TABLES <= tables
        conn.execute("INSERT INTO devices (device_uuid, name, primary_address, normalized_primary_address, created_at, updated_at) VALUES ('legacy', '旧设备', '192.0.2.1', '192.0.2.1', '2026-07-14', '2026-07-14')")
        for table in (
            "rail_infra_train_mr", "rail_infra_device_link", "rail_infra_ac_service",
            "rail_infra_node_name", "rail_infra_node_project", "rail_infra_device_project",
            "rail_infra_train", "rail_infra_node", "rail_infra_project",
        ):
            conn.execute(f"DROP TABLE {table}")
    assert not RailInfrastructureRepository(database).read().schema_available
    database.initialize(startup_policy="production_safe")
    assert not RailInfrastructureRepository(database).read().schema_available
    database.initialize()
    database.initialize()
    facts = RailInfrastructureRepository(database).read()
    assert facts.schema_available
    assert facts.devices[0]["device_uuid"] == "legacy"
    with closing(database.connect_readonly()) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_stable_nodes_multiple_projects_and_exact_device_projection(tmp_path):
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    with closing(database.connect()) as conn, conn:
        conn.executescript("""
            INSERT INTO rail_infra_node VALUES
                ('node-101', 'station', '0101', '大道站'),
                ('node-102', 'depot', '0102', '实验车辆段'),
                ('center-1', 'cocc', '', '控制中心');
            INSERT INTO rail_infra_node_name VALUES
                ('name-1', 'node-101', '大道东站', 'engineering', '工程图纸', '2020-01-01', '2024-01-01'),
                ('name-2', 'node-101', '东站', 'historical', '运营记录', NULL, NULL);
            INSERT INTO rail_infra_project VALUES ('phase-1', '初建', '一期'), ('phase-2', '扩建', '二期');
            INSERT INTO rail_infra_node_project VALUES ('node-101','phase-1'), ('node-101','phase-2');
            INSERT INTO devices (device_uuid, name, device_type, station, primary_address, created_at, updated_at) VALUES
                ('infra-switch-1', 'SW-1', 'switch', '', '192.0.2.10', '2026-07-14', '2026-07-14'),
                ('switch-guess', '大道站-SW', 'switch', '大道站', '192.0.2.11', '2026-07-14', '2026-07-14'),
                ('infra-ac-1', 'AC-1', 'wireless_controller', '', '192.0.2.12', '2026-07-14', '2026-07-14');
            INSERT INTO rail_infra_device_link VALUES
                ('node-101', 'infra-switch-1', '车站交换机', NULL),
                ('center-1', 'infra-ac-1', '无线控制器', NULL);
            INSERT INTO rail_infra_ac_service VALUES ('infra-ac-1', 'node-101'), ('infra-ac-1', 'node-102');
            UPDATE rail_infra_node SET official_name='大道开通站' WHERE node_uid='node-101';
        """)
    source = RailTransitBaseDataQueryService(paths)
    result = source.infrastructure("demo")
    station = next(node for node in result.nodes if node.uid == "node-101")
    center = next(node for node in result.nodes if node.uid == "center-1")
    assert (station.code, station.name) == ("0101", "大道开通站")
    assert {alias.name for alias in station.aliases} == {"大道东站", "东站"}
    assert {project.project_id for project in station.projects} == {"phase-1", "phase-2"}
    assert [device.device_uuid for device in station.devices] == ["infra-switch-1"]
    assert center.ac_service_stations == ["0101 大道开通站", "0102 实验车辆段"]
    assert any(device.device_uuid == "switch-guess" for device in result.unassociated_devices)
    assert not any(node.name == "车站A" for node in result.nodes)
    assert "private-pass" not in result.model_dump_json()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features["module.rail_base_data"] = {"enabled": True, "visible": True}
    with TestClient(app) as client:
        response = client.get("/api/rail-transit/base-data/infrastructure?site_id=demo")
        assert response.status_code == 200
        assert response.json()["device_count"] == result.device_count


def test_train_unlink_ends_current_mapping_and_preserves_historical_identity(tmp_path):
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    with closing(database.connect()) as conn, conn:
        conn.execute("INSERT INTO rail_infra_train VALUES ('train-01', '01', '列车01')")
        conn.execute(
            "INSERT INTO rail_infra_train_mr VALUES ('assign-1', 'train-01', 'mr-01-ct', 'CT', '2026-07-14', NULL)"
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO rail_infra_train_mr VALUES ('assign-2', 'train-01', 'mr-01-cw', 'CT', '2026-07-14', NULL)"
            )
    from netconsole.repositories.rail_transit_base_data_repository import (
        RailTransitBaseDataConstraintError,
        RailTransitBaseDataRepository,
    )

    legacy_repository = RailTransitBaseDataRepository(paths)
    with pytest.raises(RailTransitBaseDataConstraintError, match="设备管理"):
        legacy_repository.apply_base_data_changes(
            "demo", legacy_repository.base_data_revision("demo"), [{
                "entity_type": "vehicle_mr", "action": "delete", "entity_id": "mr-01-ct",
            }],
        )
    repository = RailInfrastructureRepository(database)
    source = RailTransitBaseDataQueryService(paths)
    before = source.get_mr("demo", "mr-01-ct")
    assert before is not None
    assert not repository.end_train_mr_assignment("assign-1", "mr-01-cw", "2026-07-15")
    assert repository.end_train_mr_assignment("assign-1", "mr-01-ct", "2026-07-15")
    assert not repository.end_train_mr_assignment("assign-1", "mr-01-ct", "2026-07-16")
    with closing(database.connect_readonly()) as conn:
        assert conn.execute("SELECT active_to FROM rail_infra_train_mr").fetchone()[0] == "2026-07-15"
        assert conn.execute("SELECT COUNT(*) FROM devices WHERE device_uuid='mr-01-ct'").fetchone()[0] == 1
    assert source.get_mr("demo", "mr-01-ct") is None
    from netconsole.repositories.rail_relationship_repository import RailRelationshipRepository
    historical = RailRelationshipRepository(paths).list_current(
        "demo", relationship_type="train_mr", at_time="2026-07-14T12:00:00Z")
    assert historical.items[0].target_uid == "mr-01-ct"
    assert source.get_mr("demo", "mr-01-cw") is not None
    train = next(node for node in source.infrastructure("demo").nodes if node.uid == "train-01")
    assert train.devices == []


def test_organization_initializes_once_and_later_assets_require_link(tmp_path):
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    with closing(database.connect()) as conn, conn:
        group_id = conn.execute(
            "INSERT INTO device_groups(site_id, name, created_at, updated_at) "
            "VALUES ('demo', 'COCC', '2026-11-25', '2026-11-25')"
        ).lastrowid
        conn.execute("UPDATE devices SET group_id=? WHERE device_uuid='mr-01-ct'", (group_id,))
        conn.execute(
            "INSERT INTO devices(device_uuid, name, device_type, group_id, primary_address, created_at, updated_at) "
            "VALUES ('first-sw', 'CORE-SW', 'switch', ?, '192.0.2.51', '2026-11-25', '2026-11-25')",
            (group_id,),
        )
    from netconsole.application.rail_transit.infrastructure_application_service import (
        RailInfrastructureApplicationService,
    )

    service = RailInfrastructureApplicationService(RailTransitBaseDataQueryService(paths), None)
    assert not service.infrastructure("demo").organization_initialized
    first = service.initialize("demo")
    assert first.organization_initialized
    center = next(node for node in first.nodes if node.kind == "cocc")
    assert [device.device_uuid for device in center.devices] == ["first-sw"]
    with closing(database.connect()) as conn, conn:
        conn.execute(
            "INSERT INTO devices(device_uuid, name, device_type, group_id, primary_address, created_at, updated_at) "
            "VALUES ('new-sw', 'NEW-SW', 'switch', ?, '192.0.2.52', '2026-11-25', '2026-11-25')",
            (group_id,),
        )
    repeated = service.initialize("demo")
    assert [node.uid for node in repeated.nodes if node.kind == "cocc"] == [center.uid]
    assert "new-sw" in {device.device_uuid for device in repeated.unassociated_devices}
