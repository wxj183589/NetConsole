from __future__ import annotations

import sqlite3

import pytest

from netconsole.application.rail_transit.relationship_application_service import (
    RailRelationshipApplicationService,
    RelationshipApplicationError,
)
from netconsole.core.database import Database
from netconsole.backend.api.main import create_app
from netconsole.models.api.rail_relationship import RelationshipMutationRequest
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard
from tests.support.rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy


def _service(tmp_path):
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with Database(db_path).connect() as conn:
        conn.executescript(
            """
            INSERT INTO rail_infra_node VALUES ('station-1', 'station', '0101', '车站A');
            INSERT INTO rail_infra_node VALUES ('station-2', 'station', '0102', '车站B');
            INSERT INTO rail_infra_project VALUES ('project-1', '一期', 'phase-1');
            INSERT INTO rail_infra_train VALUES ('train-1', '01', '列车01');
            """
        )
    guard = BaseDataWriteGuard(paths, feature_enabled=True, write_enabled=True, copy_write_enabled=True)
    return paths, db_path, RailRelationshipApplicationService(paths, guard)


def _request(service, *, kind, action, revision, source="", target="", relation_id="", values=None):
    return RelationshipMutationRequest(
        relationship_type=kind,
        action=action,
        relationship_id=relation_id,
        source_uid=source,
        target_uid=target,
        values=values or {},
        base_revision=revision,
        explicit_confirmation=True,
        reason="phase3 test",
        actor="test",
        site_id="demo",
    )


def test_relationships_have_transactional_revision_history_and_termination(tmp_path):
    _paths, db_path, service = _service(tmp_path)
    revision = service.list_current("demo").revision
    created = service.mutate(_request(service, kind="node_project", action="create", revision=revision, source="station-1", target="project-1"))
    assert created.relationship is not None
    assert created.relationship.relationship_id == "station-1:project-1"
    current = service.list_current("demo", relationship_type="node_project")
    assert current.total == 1
    assert current.revision != revision
    terminated = service.mutate(_request(service, kind="node_project", action="terminate", revision=current.revision, relation_id="station-1:project-1"))
    assert terminated.relationship is None
    assert service.list_current("demo", relationship_type="node_project").total == 0
    history = service.list_history("demo", relationship_type="node_project")
    assert [item.action for item in history.items] == ["terminate", "create"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rail_infra_relation_audit").fetchone()[0] == 2


def test_relationships_keep_device_node_and_multiple_device_sections_separate(tmp_path):
    _paths, _db_path, service = _service(tmp_path)
    revision = service.list_current("demo").revision
    service.mutate(_request(service, kind="device_node", action="create", revision=revision, source="station-1", target="mr-temp", values={"engineering_role": "交换机"}))
    revision = service.list_current("demo").revision
    service.mutate(_request(service, kind="device_section", action="create", revision=revision, source="mr-temp", target="section-1", values={"engineering_role": "区间交换机", "installation_location": "通信机房"}))
    revision = service.list_current("demo").revision
    service.mutate(_request(service, kind="device_section", action="create", revision=revision, source="mr-temp", target="section-2", values={"engineering_role": "区间交换机"}))
    assert service.list_current("demo", relationship_type="device_section").total == 2
    assert service.list_current("demo", relationship_type="device_node").total == 1


def test_ac_service_and_train_mr_conflicts_are_rejected_without_overwrite(tmp_path):
    _paths, db_path, service = _service(tmp_path)
    with Database(db_path).connect() as conn:
        conn.execute("UPDATE devices SET device_type = 'AC' WHERE device_uuid = 'mr-temp'")
    revision = service.list_current("demo").revision
    service.mutate(_request(service, kind="ac_service", action="create", revision=revision, source="mr-temp", target="station-1"))
    with pytest.raises(RelationshipApplicationError) as duplicate:
        service.mutate(_request(service, kind="ac_service", action="create", revision=service.list_current("demo").revision, source="mr-temp", target="station-1"))
    assert duplicate.value.code == "RELATION_ALREADY_EXISTS"
    revision = service.list_current("demo").revision
    service.mutate(_request(service, kind="train_mr", action="create", revision=revision, source="train-1", target="mr-01-ct", relation_id="assign-1", values={"position": "CT"}))
    with pytest.raises(RelationshipApplicationError) as conflict:
        service.mutate(_request(service, kind="train_mr", action="create", revision=service.list_current("demo").revision, source="train-1", target="mr-01-cw", relation_id="assign-2", values={"position": "CT"}))
    assert conflict.value.code == "RELATION_CONFLICT"


def test_relationship_read_api_returns_current_revision_without_write_side_effect(tmp_path):
    paths, db_path, _service_instance = _service(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features["module.rail_base_data"] = {"enabled": True, "visible": True}
    before = db_path.read_bytes()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/api/rail-transit/relationships?site_id=demo&relationship_type=node_project")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["revision"]
    assert db_path.read_bytes() == before
