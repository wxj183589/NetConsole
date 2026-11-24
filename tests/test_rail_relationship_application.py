from __future__ import annotations

from contextlib import closing

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
from tests.support.rail_transit_base_data_fixture import (
    build_rail_transit_base_data_fixture,
    mark_base_data_copy,
)


def _service(tmp_path):
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    with closing(Database(db_path).connect()) as conn, conn:
        conn.executescript(
            """
            INSERT INTO rail_infra_node VALUES ('station-1', 'station', '0101', '车站A');
            INSERT INTO rail_infra_node VALUES ('station-2', 'station', '0102', '车站B');
            INSERT INTO rail_infra_project VALUES ('project-1', '一期', 'phase-1');
            INSERT INTO rail_infra_train VALUES ('train-1', '01', '列车01');
            """
        )
    guard = BaseDataWriteGuard(
        paths, feature_enabled=True, write_enabled=True, copy_write_enabled=True
    )
    service = RailRelationshipApplicationService(paths, guard)
    original_catalog = service.catalog

    def catalog(site_id):
        result = original_catalog(site_id)
        result["sections"] = [
            {"id": "section-1", "name": "区间一"},
            {"id": "section-2", "name": "区间二"},
        ]
        return result

    service.catalog = catalog
    return paths, db_path, service


def _request(
    service,
    *,
    kind,
    action,
    revision,
    source="",
    target="",
    relation_id="",
    values=None,
):
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
    created = service.mutate(
        _request(
            service,
            kind="node_project",
            action="create",
            revision=revision,
            source="station-1",
            target="project-1",
        )
    )
    assert created.relationship is not None
    relation_id = created.relationship.relationship_id
    assert created.relationship.source_uid == "station-1"
    current = service.list_current("demo", relationship_type="node_project")
    assert current.total == 1
    assert current.revision != revision
    terminated = service.mutate(
        _request(
            service,
            kind="node_project",
            action="terminate",
            revision=current.revision,
            relation_id=relation_id,
        )
    )
    assert terminated.relationship is None
    assert service.list_current("demo", relationship_type="node_project").total == 0
    history = service.list_history("demo", relationship_type="node_project")
    assert [item.action for item in history.items] == ["terminate", "create"]
    with closing(sqlite3.connect(db_path)) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM rail_infra_relation_audit").fetchone()[0]
            == 2
        )


def test_relationships_keep_device_node_and_multiple_device_sections_separate(tmp_path):
    _paths, _db_path, service = _service(tmp_path)
    revision = service.list_current("demo").revision
    service.mutate(
        _request(
            service,
            kind="device_node",
            action="create",
            revision=revision,
            source="station-1",
            target="mr-temp",
            values={"engineering_role": "交换机"},
        )
    )
    revision = service.list_current("demo").revision
    service.mutate(
        _request(
            service,
            kind="device_section",
            action="create",
            revision=revision,
            source="mr-temp",
            target="section-1",
            values={
                "engineering_role": "区间交换机",
                "installation_location": "通信机房",
            },
        )
    )
    revision = service.list_current("demo").revision
    service.mutate(
        _request(
            service,
            kind="device_section",
            action="create",
            revision=revision,
            source="mr-temp",
            target="section-2",
            values={"engineering_role": "区间交换机"},
        )
    )
    assert service.list_current("demo", relationship_type="device_section").total == 2
    assert service.list_current("demo", relationship_type="device_node").total == 1


def test_ac_service_and_train_mr_conflicts_are_rejected_without_overwrite(tmp_path):
    _paths, db_path, service = _service(tmp_path)
    with closing(Database(db_path).connect()) as conn, conn:
        conn.execute(
            "UPDATE devices SET device_type = 'AC' WHERE device_uuid = 'mr-temp'"
        )
    revision = service.list_current("demo").revision
    service.mutate(
        _request(
            service,
            kind="ac_service",
            action="create",
            revision=revision,
            source="mr-temp",
            target="station-1",
        )
    )
    duplicate = service.mutate(
        _request(
            service,
            kind="ac_service",
            action="create",
            revision=service.list_current("demo").revision,
            source="mr-temp",
            target="station-1",
        )
    )
    assert not duplicate.history_event_id
    revision = service.list_current("demo").revision
    service.mutate(
        _request(
            service,
            kind="train_mr",
            action="create",
            revision=revision,
            source="train-1",
            target="mr-01-ct",
            relation_id="assign-1",
            values={"position": "CT"},
        )
    )
    with pytest.raises(RelationshipApplicationError) as conflict:
        service.mutate(
            _request(
                service,
                kind="train_mr",
                action="create",
                revision=service.list_current("demo").revision,
                source="train-1",
                target="mr-01-cw",
                relation_id="assign-2",
                values={"position": "CT"},
            )
        )
    assert conflict.value.code == "RELATION_CONFLICT"


def test_relationship_read_api_returns_current_revision_without_write_side_effect(
    tmp_path,
):
    paths, db_path, _service_instance = _service(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features["module.rail_infrastructure"] = {
        "enabled": True,
        "visible": True,
    }
    before = db_path.read_bytes()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/relationships?site_id=demo&relationship_type=node_project"
        )
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["revision"]
    assert db_path.read_bytes() == before


def _mutate(service, kind, source="", target="", action="create", **kwargs):
    req = _request(
        service,
        kind=kind,
        action=action,
        source=source,
        target=target,
        revision=service.list_current("demo").revision,
        values=kwargs.pop("values", None),
        relation_id=kwargs.pop("relation_id", ""),
    )
    return service.mutate(req.model_copy(update=kwargs))


def test_preview_rolls_back_and_replay_does_not_advance_revision(tmp_path):
    _paths, db_path, service = _service(tmp_path)
    request = _request(
        service,
        kind="device_section",
        action="create",
        source="mr-temp",
        target="section-1",
        revision=service.list_current("demo").revision,
    )
    request.idempotency_key = "one-click"
    with closing(Database(db_path).connect_readonly()) as conn:
        before = conn.serialize()
    preview = service.mutate(request, preview=True)
    assert preview.preview and len(preview.changes) == 1
    with closing(Database(db_path).connect_readonly()) as conn:
        assert conn.serialize() == before
    saved = service.mutate(request)
    assert saved.relationship.revision == saved.revision
    assert saved.relationship.created_at and saved.relationship.actor == "test"
    assert (
        service.mutate(request) == saved
    )  # Stale revision is valid only for exact replay.
    assert service.list_current("demo").revision == saved.revision
    with pytest.raises(RelationshipApplicationError, match="重复操作"):
        service.mutate(request.model_copy(update={"target_uid": "section-2"}))
    with pytest.raises(RelationshipApplicationError) as stale:
        service.mutate(
            request.model_copy(
                update={"idempotency_key": "new-operation", "target_uid": "section-2"}
            )
        )
    assert stale.value.code == "BASE_DATA_REVISION_CONFLICT"


def test_ac_batch_is_atomic_and_does_not_mix_current_resources(tmp_path):
    _paths, db_path, service = _service(tmp_path)
    with closing(Database(db_path).connect()) as conn, conn:
        conn.execute("UPDATE devices SET device_type='AC' WHERE device_uuid='mr-temp'")
        before = [tuple(r) for r in conn.execute("SELECT * FROM ac_fit_ap_resources")]
    revision = service.list_current("demo").revision
    req = _request(
        service, kind="ac_service", action="create", source="mr-temp", revision=revision
    )
    with pytest.raises(RelationshipApplicationError):
        service.mutate(req.model_copy(update={"target_uids": ["station-1", "missing"]}))
    assert service.list_current("demo", relationship_type="ac_service").total == 0
    assert service.list_current("demo").revision == revision
    result = service.mutate(
        req.model_copy(update={"target_uids": ["station-1", "station-2", "station-1"]})
    )
    assert len(result.changes) == 2
    overview = service.fit_ap_overview("demo", "mr-temp")
    assert overview["total"] == 0 and len(overview["service_stations"]) == 2
    with closing(Database(db_path).connect_readonly()) as conn:
        assert [
            tuple(r) for r in conn.execute("SELECT * FROM ac_fit_ap_resources")
        ] == before
    assert "private-pass" not in str(service.catalog("demo"))


def test_mr_replacement_preserves_intervals_asset_and_current_query(tmp_path):
    paths, db_path, service = _service(tmp_path)
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )

    query = RailTransitBaseDataQueryService(paths)
    created = _mutate(
        service,
        "train_mr",
        "train-1",
        "mr-01-ct",
        values={"position": "CT"},
        effective_from="2026-01-01",
    )
    old_id = created.relationship.relationship_id
    replaced = _mutate(
        service,
        "train_mr",
        "train-1",
        "mr-temp",
        action="replace",
        relation_id=old_id,
        values={"position": "CT"},
        effective_from="2026-11-20",
    )
    assert len(replaced.changes) == 2
    assert query.get_mr("demo", "mr-01-ct") is None
    assert query.get_mr("demo", "mr-temp").mr.role == "CT"
    assert query.get_mr("demo", "mr-01-cw") is not None
    assert (
        service.list_current("demo", relationship_type="train_mr", at_time="2026-11-19")
        .items[0]
        .target_uid
        == "mr-01-ct"
    )
    at_cutover = service.list_current(
        "demo", relationship_type="train_mr", at_time="2026-11-20"
    )
    assert [r.target_uid for r in at_cutover.items] == ["mr-temp"]
    _mutate(
        service,
        "train_mr",
        action="terminate",
        relation_id=replaced.relationship.relationship_id,
        effective_to="2026-11-21",
    )
    assert service.list_current("demo", relationship_type="train_mr").total == 0
    assert (
        service.list_current(
            "demo", relationship_type="train_mr", at_time="2026-11-22"
        ).total
        == 0
    )
    with closing(Database(db_path).connect()) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM devices WHERE device_uuid IN ('mr-01-ct','mr-temp')"
            ).fetchone()[0]
            == 2
        )
        with pytest.raises(sqlite3.IntegrityError, match="RELATION_HISTORY_PROTECTED"):
            conn.execute("DELETE FROM devices WHERE device_uuid='mr-01-ct'")
    assert service.list_history("demo", entity_uid="mr-01-ct").total == 2


def test_multiple_project_membership_rename_and_lifecycle_history(tmp_path):
    _paths, _db_path, service = _service(tmp_path)
    created = _mutate(
        service, "node_project", "station-1", "project-1", effective_from="2026-01-01"
    )
    _mutate(
        service, "node_project", "station-2", "project-1", effective_from="2026-01-01"
    )
    project = dict(
        name="二期",
        stage="phase-2",
        base_revision=service.list_current("demo").revision,
        explicit_confirmation=True,
        idempotency_key="project-new",
    )
    preview = service.save_project("demo", project, preview=True)
    assert preview["preview"] and len(service.catalog("demo")["projects"]) == 1
    saved = service.save_project("demo", project)
    assert service.save_project("demo", project) == saved
    _mutate(
        service,
        "node_project",
        "station-1",
        saved["project_id"],
        effective_from="2026-01-01",
    )
    assert service.list_current("demo", entity_uid="station-1").total == 2
    rename = dict(
        project_id="project-1",
        name="一期改名",
        stage="phase-1",
        base_revision=service.list_current("demo").revision,
        explicit_confirmation=True,
        idempotency_key="rename",
    )
    service.save_project("demo", rename)
    assert (
        service.list_current("demo", entity_uid="project-1").items[0].relationship_id
        == created.relationship.relationship_id
    )
    _mutate(
        service,
        "node_project",
        action="terminate",
        relation_id=created.relationship.relationship_id,
        effective_to="2026-02-01",
    )
    _mutate(
        service, "node_project", "station-1", "project-1", effective_from="2026-03-01"
    )
    assert (
        service.list_current("demo", entity_uid="station-1", at_time="2026-02-15").total
        == 1
    )
    assert (
        service.list_current("demo", entity_uid="station-1", at_time="2026-01-15").total
        == 2
    )


def test_attribute_effective_time_and_physical_station_preservation(tmp_path):
    _paths, db_path, service = _service(tmp_path)
    with closing(Database(db_path).connect()) as conn, conn:
        conn.execute(
            "UPDATE devices SET station_id='legacy-station' WHERE device_uuid='mr-temp'"
        )
    with pytest.raises(RelationshipApplicationError, match="单站点绑定"):
        _mutate(service, "device_node", "station-1", "mr-temp")
    first = _mutate(
        service,
        "device_section",
        "mr-temp",
        "section-1",
        effective_from="2026-01-01",
        values={"engineering_role": "old"},
    )
    _mutate(
        service,
        "device_section",
        action="update",
        relation_id=first.relationship.relationship_id,
        effective_from="2026-02-01",
        values={"engineering_role": "new"},
    )
    assert (
        service.list_current("demo", at_time="2026-01-15")
        .items[0]
        .values["engineering_role"]
        == "old"
    )
    assert (
        service.list_current("demo", at_time="2026-02-15")
        .items[0]
        .values["engineering_role"]
        == "new"
    )
    with closing(Database(db_path).connect_readonly()) as conn:
        assert (
            conn.execute(
                "SELECT station_id FROM devices WHERE device_uuid='mr-temp'"
            ).fetchone()[0]
            == "legacy-station"
        )
    assert service.deletion_preflight("demo", "section-1")["can_delete"] is False


def test_two_writers_cannot_overwrite_the_same_revision(tmp_path):
    _paths, _db_path, service = _service(tmp_path)
    from concurrent.futures import ThreadPoolExecutor

    revision = service.list_current("demo").revision

    def write(target):
        try:
            service.mutate(
                _request(
                    service,
                    kind="node_project",
                    action="create",
                    source=target,
                    target="project-1",
                    revision=revision,
                )
            )
            return "saved"
        except RelationshipApplicationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["station-1", "station-2"]))
    assert sorted(results) == ["BASE_DATA_REVISION_CONFLICT", "saved"]


def test_nonstation_catalog_keeps_legacy_station_conflict_explicit(tmp_path):
    from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
    paths, db_path, service = _service(tmp_path)
    with closing(Database(db_path).connect()) as conn, conn:
        conn.execute("INSERT INTO rail_infra_node VALUES('center-1','cocc','','控制中心')")
        conn.execute("UPDATE devices SET station_id='legacy-station' WHERE device_uuid='mr-temp'")
    service.query = RailTransitBaseDataQueryService(paths)
    with pytest.raises(RelationshipApplicationError) as error:
        _mutate(service, 'device_node', 'center-1', 'mr-temp')
    assert error.value.code == 'RELATION_CONFLICT'


def test_relationship_api_permissions_confirmation_and_strict_values(tmp_path):
    paths, _db_path, service = _service(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.rail_relationship_application_service = service
    app.state.feature_gate.features["module.rail_infrastructure"] = dict(
        enabled=True, visible=True
    )
    app.state.feature_gate.features["capability.rail_infrastructure.write"] = dict(
        enabled=True, visible=True
    )
    req = _request(
        service,
        kind="node_project",
        action="create",
        source="station-1",
        target="project-1",
        revision=service.list_current("demo").revision,
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        denied = req.model_dump(mode="json")
        denied["values"] = {"password": "must-not-persist"}
        assert (
            client.post("/api/rail-transit/relationships", json=denied).status_code
            == 422
        )
        service.guard.write_enabled = False
        assert (
            client.post(
                "/api/rail-transit/relationships/preview",
                json=req.model_dump(mode="json"),
            ).status_code
            == 403
        )
        service.guard.write_enabled = True
        assert (
            client.post(
                "/api/rail-transit/relationships",
                json=req.model_copy(update={"explicit_confirmation": False}).model_dump(
                    mode="json"
                ),
            ).status_code
            == 422
        )
        preview = client.post(
            "/api/rail-transit/relationships/preview", json=req.model_dump(mode="json")
        )
        assert preview.status_code == 200 and service.list_current("demo").total == 0
        assert (
            client.post(
                "/api/rail-transit/relationships", json=req.model_dump(mode="json")
            ).status_code
            == 200
        )
        stale = req.model_copy(
            update={"target_uid": "missing", "idempotency_key": "second-click"}
        )
        assert (
            client.post(
                "/api/rail-transit/relationships", json=stale.model_dump(mode="json")
            ).status_code
            == 409
        )
        app.state.feature_gate.features["capability.rail_infrastructure.write"][
            "enabled"
        ] = False
        assert (
            client.post(
                "/api/rail-transit/relationships", json=req.model_dump(mode="json")
            ).status_code
            == 404
        )  # Canonical disabled-feature response.


def test_phase1_additive_migration_is_idempotent_and_rolls_back_on_failure(
    tmp_path, monkeypatch
):
    _paths, db_path, _service_instance = _service(tmp_path)
    database = Database(db_path)
    with closing(database.connect()) as conn, conn:
        for table in (
            "rail_infra_relation_audit",
            "rail_infra_relation_state",
            "rail_infra_relation_history",
            "rail_infra_device_section",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute(
            "UPDATE schema_metadata SET value='1' WHERE key='rail_infrastructure_schema_version'"
        )
        counts = {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in (
                "devices",
                "rail_infra_node",
                "rail_infra_train",
                "ap_extension_points",
            )
        }
    import netconsole.core.database as module

    original = module._execute_sql_script_in_transaction

    def fail(conn, script):
        original(conn, script)
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(module, "_execute_sql_script_in_transaction", fail)
    with pytest.raises(RuntimeError, match="injected"):
        database.initialize()
    with closing(database.connect_readonly()) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='rail_infra_device_section'"
        ).fetchone()
        assert (
            conn.execute(
                "SELECT value FROM schema_metadata WHERE key='rail_infrastructure_schema_version'"
            ).fetchone()[0]
            == "1"
        )
    monkeypatch.setattr(module, "_execute_sql_script_in_transaction", original)
    database.initialize()
    database.initialize()
    with closing(database.connect_readonly()) as conn:
        assert {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in counts
        } == counts
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert (
            conn.execute(
                "SELECT value FROM schema_metadata WHERE key='rail_infrastructure_schema_version'"
            ).fetchone()[0]
            == "2"
        )


def test_relationship_revision_refreshes_ground_without_rewriting_archives(tmp_path):
    paths, _db_path, service = _service(tmp_path)
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )
    from netconsole.services.ground_unattended.inventory import (
        TrainInventorySyncService,
    )
    from netconsole.repositories.ground_unattended_repository import (
        GroundUnattendedRepository,
    )
    from netconsole.services.online_mr.query_service import OnlineMrQueryService
    from tests.test_online_mr_query_service import _session

    online = OnlineMrQueryService(paths)
    session_path = _session(online, "old-mr-session", site="demo", mr="列车01-MR-CT")
    raw = session_path / "raw" / "mesh.log"
    raw.write_bytes(b"synthetic original MR-A evidence")
    before_files = {p: p.read_bytes() for p in session_path.rglob("*") if p.is_file()}
    ground = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    ground.initialize()
    sync = TrainInventorySyncService(
        paths,
        site_id="demo",
        repository=ground,
        base_query=RailTransitBaseDataQueryService(paths),
    )
    sync.collection_ttl = 3600
    before = sync.collect()
    created = _mutate(
        service,
        "train_mr",
        "train-1",
        "mr-01-ct",
        values={"position": "CT"},
        effective_from="2026-01-01",
    )
    _mutate(
        service,
        "train_mr",
        "train-1",
        "mr-temp",
        action="replace",
        relation_id=created.relationship.relationship_id,
        values={"position": "CT"},
        effective_from="2026-11-20",
    )
    after = sync.collect()
    assert before.source_revision != after.source_revision
    assert {mr.id for mr in sync.current_mrs()} == {"mr-temp", "mr-01-cw"}
    assert {p: p.read_bytes() for p in before_files} == before_files
    old = online.get_session("demo", "old-mr-session")
    assert old.mr_name == "列车01-MR-CT" and old.device_id == 7
    # Historical sessions are read independently of the current relationship service.
    service.list_current = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("relation offline")
    )
    assert online.get_session("demo", "old-mr-session").session_id == old.session_id


def test_engineering_section_cannot_be_deleted_with_current_or_historical_references(
    tmp_path,
):
    _paths, db_path, service = _service(tmp_path)
    from netconsole.repositories.rail_transit_base_data_repository import (
        RailTransitBaseDataRepository,
        RailTransitBaseDataConstraintError,
    )

    created = _mutate(
        service, "device_section", "mr-temp", "section-1", effective_from="2026-01-01"
    )
    with closing(Database(db_path).connect()) as conn:
        with pytest.raises(RailTransitBaseDataConstraintError):
            RailTransitBaseDataRepository._ensure_engineering_unreferenced(
                conn, "section-1"
            )
    _mutate(
        service,
        "device_section",
        action="terminate",
        relation_id=created.relationship.relationship_id,
        effective_to="2026-11-20",
    )
    with closing(Database(db_path).connect()) as conn:
        with pytest.raises(RailTransitBaseDataConstraintError, match="历史"):
            RailTransitBaseDataRepository._ensure_engineering_unreferenced(
                conn, "section-1"
            )


def test_ac_entry_uses_vendor_aware_canonical_role_and_per_device_services(tmp_path):
    paths, db_path, service = _service(tmp_path)
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )

    with closing(Database(db_path).connect()) as conn, conn:
        conn.execute(
            "UPDATE devices SET device_vendor='H3C',device_type='AC' WHERE device_uuid='mr-temp'"
        )
    _mutate(service, "device_node", "station-1", "mr-temp")
    _mutate(service, "ac_service", "mr-temp", "station-2")
    facts = RailTransitBaseDataQueryService(paths).infrastructure("demo")
    ac = next(d for n in facts.nodes for d in n.devices if d.device_uuid == "mr-temp")
    assert ac.device_role == "wireless_controller"
    assert ac.service_stations == ["0102 车站B"]


def test_section_service_does_not_hide_legacy_physical_station(tmp_path):
    paths, db_path, service = _service(tmp_path)
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )
    from netconsole.repositories.rail_transit_base_data_repository import (
        RailTransitBaseDataRepository,
    )

    query = RailTransitBaseDataQueryService(paths)
    repo = RailTransitBaseDataRepository(paths)
    with closing(Database(db_path).connect()) as conn, conn:
        repo._replace_metadata_row(
            conn,
            "demo",
            "station",
            "",
            dict(
                station_id="physical-id",
                node_uid="physical-node",
                name="真实安装站",
                node_type="station",
                source_kind="manual",
            ),
        )
        repo._replace_metadata_row(
            conn,
            "demo",
            "section",
            "",
            dict(
                section_id="section-1",
                name="服务区间",
                source_kind="manual",
                section_kind="manual",
            ),
        )
        conn.execute(
            "UPDATE devices SET station_id='physical-id' WHERE device_uuid='mr-temp'"
        )
    _mutate(service, "device_section", "mr-temp", "section-1")
    facts = query.infrastructure("demo")
    owners = {
        n.uid for n in facts.nodes if any(d.device_uuid == "mr-temp" for d in n.devices)
    }
    assert owners == {"physical-node", "section-1"}
    assert not any(d.device_uuid == "mr-temp" for d in facts.unassociated_devices)


def test_service_only_ac_preserves_service_context_without_installation(tmp_path):
    paths, db_path, service = _service(tmp_path)
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )

    with closing(Database(db_path).connect()) as conn, conn:
        conn.execute("UPDATE devices SET device_type='AC' WHERE device_uuid='mr-temp'")
    _mutate(service, "ac_service", "mr-temp", "station-1")
    facts = RailTransitBaseDataQueryService(paths).infrastructure("demo")
    ac = next(d for d in facts.unassociated_devices if d.device_uuid == "mr-temp")
    assert ac.service_stations == ["0101 车站A"]
