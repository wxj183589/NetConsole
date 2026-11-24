from contextlib import closing
from netconsole.core.database import Database
from netconsole.services.rail_transit.engineering_context_query_service import (
    EngineeringContextQueryService,
)
from tests.test_rail_relationship_application import _service, _mutate


def test_current_history_revision_and_unavailable_are_distinct(tmp_path, monkeypatch):
    paths, db, relations = _service(tmp_path)
    context = EngineeringContextQueryService(paths)
    with closing(Database(db).connect_readonly()) as conn:
        before = conn.serialize()
    assert context.one("demo", "mr-temp").affiliation_status == "unassociated"
    assert context.one("demo", "missing").affiliation_status == "not_found"
    with closing(Database(db).connect_readonly()) as conn:
        assert conn.serialize() == before
    first = _mutate(
        relations,
        "train_mr",
        "train-1",
        "mr-01-ct",
        values={"position": "CT"},
        effective_from="2026-01-01",
    )
    _mutate(
        relations,
        "train_mr",
        "train-1",
        "mr-temp",
        action="replace",
        relation_id=first.relationship.relationship_id,
        values={"position": "CT"},
        effective_from="2026-11-20",
    )
    assert context.one("demo", "mr-temp").node_uid == "train-1"
    old = context.one("demo", "mr-01-ct", at_time="2026-11-01")
    assert old.affiliation_status == "historical" and old.node_uid == "train-1"
    assert (
        context.one("demo", "mr-temp", at_time="2026-11-01").affiliation_status
        == "unconfirmed"
    )
    assert (
        context.one("demo", "mr-temp", expected_revision="old").affiliation_status
        == "stale"
    )
    monkeypatch.setattr(
        context.base_query,
        "infrastructure",
        lambda *a: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert context.one("demo", "mr-temp").affiliation_status == "unavailable"


def test_context_api_is_readonly_bounded_and_feature_gated(tmp_path):
    from fastapi.testclient import TestClient
    from netconsole.backend.api.main import create_app

    paths, db, relations = _service(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.rail_relationship_application_service = relations
    app.state.feature_gate.features["module.rail_infrastructure"] = dict(
        enabled=True, visible=True
    )
    client = TestClient(app)
    with closing(Database(db).connect_readonly()) as conn:
        before = conn.serialize()
    response = client.get(
        "/api/rail-transit/relationships/engineering-context",
        params={"site_id": "demo", "device_uuid": "mr-temp"},
    )
    assert response.status_code == 200
    assert response.json()["mr-temp"]["affiliation_status"] == "unassociated"
    assert "private-pass" not in response.text
    with closing(Database(db).connect_readonly()) as conn:
        assert conn.serialize() == before
    assert (
        client.get(
            "/api/rail-transit/relationships/engineering-context",
            params=[("device_uuid", str(i)) for i in range(201)],
        ).status_code
        == 422
    )
    app.state.feature_gate.features["module.rail_infrastructure"] = dict(
        enabled=False, visible=True
    )
    assert (
        client.get(
            "/api/rail-transit/relationships/engineering-context",
            params={"device_uuid": "mr-temp"},
        ).status_code
        == 404
    )
    app.state.feature_gate.features["module.rail_infrastructure"] = dict(
        enabled=False, visible=False
    )
    assert (
        client.get(
            "/api/rail-transit/relationships/engineering-context",
            params={"device_uuid": "mr-temp"},
        ).status_code
        == 404
    )


def test_batch_conflict_service_scope_and_revision_drift(tmp_path, monkeypatch):
    paths, db, relations = _service(tmp_path)
    _mutate(
        relations,
        "device_node",
        "station-1",
        "mr-temp",
        values={"engineering_role": "switch", "installation_location": "room"},
    )
    _mutate(relations, "node_project", "station-1", "project-1")
    context = EngineeringContextQueryService(paths)
    item = context.one("demo", "mr-temp")
    assert item.project_ids == ["project-1"] and item.physical_location == "room"
    with closing(Database(db).connect()) as conn, conn:
        conn.execute(
            "INSERT INTO rail_infra_device_link VALUES ('station-2','mr-temp','other',NULL)"
        )
    assert context.one("demo", "mr-temp").affiliation_status == "conflict"
    original = context.base_query.repository.base_data_revision
    calls = []

    def revision(site):
        calls.append(1)
        return original(site) if len(calls) == 1 else "drift"

    monkeypatch.setattr(context.base_query.repository, "base_data_revision", revision)
    assert context.one("demo", "mr-temp").affiliation_status == "stale"


def test_ground_scale_100_mrs_50_trains_and_revision_replacement(tmp_path):
    from netconsole.models.device import Device
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.repositories.ground_unattended_repository import (
        GroundUnattendedRepository,
    )
    from netconsole.services.ground_unattended.inventory import (
        TrainInventorySyncService,
    )
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )

    paths, db, relations = _service(tmp_path)
    repo = DeviceRepository(Database(db))
    with closing(Database(db).connect()) as conn, conn:
        conn.execute("DELETE FROM rail_infra_train")
    ids = []
    for index in range(50):
        train = f"formal-train-{index}"
        with closing(Database(db).connect()) as conn, conn:
            conn.execute(
                "INSERT INTO rail_infra_train VALUES(?,?,?)",
                (train, str(index + 100), f"T{index}"),
            )
        for role in ("CT", "CW"):
            d = repo.create(
                Device(
                    name=f"MR{index}{role}",
                    device_type="MR",
                    primary_address=f"192.0.2.{index * 2 + (1 if role == 'CT' else 2)}",
                )
            )
            ids.append(str(d.device_uuid))
            with closing(Database(db).connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO rail_infra_train_mr VALUES(?,?,?,?,?,NULL)",
                    (
                        f"assign-{index}-{role}",
                        train,
                        str(d.device_uuid),
                        role,
                        "2026-01-01",
                    ),
                )
    context = EngineeringContextQueryService(paths)
    result = context.contexts("demo", ids)
    assert len(result) == 100 and all(
        c.affiliation_status == "associated" for c in result.values()
    )
    ground = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    ground.initialize()
    sync = TrainInventorySyncService(
        paths,
        site_id="demo",
        repository=ground,
        base_query=RailTransitBaseDataQueryService(paths),
    )
    sync.collection_ttl = 3600
    first = sync.collect()
    assert len([m for m in first.mrs if m["id"] in ids]) == 100
    with closing(Database(db).connect()) as conn, conn:
        conn.execute(
            "UPDATE rail_infra_train_mr SET active_to='2026-11-20' WHERE assignment_id='assign-0-CT'"
        )
    second = sync.collect()
    assert first.source_revision != second.source_revision
    assert ids[0] not in {m["id"] for m in second.mrs}
    assert repo.get_by_uuid(ids[0]) is not None


def test_ground_context_failure_does_not_erase_runtime_inventory(tmp_path, monkeypatch):
    from netconsole.backend.api.main import create_app
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )

    paths, db, relations = _service(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    ground = app.state.ground_unattended_application_service
    before = ground.list_trains("demo")
    monkeypatch.setattr(
        RailTransitBaseDataQueryService,
        "infrastructure",
        lambda *a: (_ for _ in ()).throw(RuntimeError("context offline")),
    )
    after = ground.list_trains("demo")
    assert [t.train_id for t in before.items] == [t.train_id for t in after.items]
    assert all(
        t.engineering_context_status == "unavailable"
        for t in after.items
        if any(e.mr_id for e in t.endpoints)
    )


def test_trackside_snapshot_context_uses_stable_ids_and_keeps_runtime_independent(
    tmp_path,
):
    paths, db, relations = _service(tmp_path)
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.trackside_ap_export_service import (
        load_trackside_ap_business_snapshot,
    )
    from netconsole.services.rail_transit.trackside_ap_business_snapshot import (
        read_trackside_ap_source_revisions,
    )

    context = EngineeringContextQueryService.from_site_database(Database(db), "demo")
    assert context is not None
    relations.query = context.base_query
    from netconsole.repositories.device_fact_repository import DeviceFactRepository
    from netconsole.repositories.rail_transit_base_data_repository import (
        RailTransitBaseDataRepository,
    )

    with closing(Database(db).connect()) as conn, conn:
        master = RailTransitBaseDataRepository(paths)
        master._replace_metadata_row(
            conn,
            "demo",
            "station",
            "",
            dict(
                station_id="station-meta-1",
                node_uid="station-1",
                name="车站A",
                code="0101",
                node_type="station",
                source_kind="manual",
            ),
        )
        master._replace_metadata_row(
            conn,
            "demo",
            "station",
            "",
            dict(
                station_id="station-meta-2",
                node_uid="station-2",
                name="车站B",
                code="0102",
                node_type="station",
                source_kind="manual",
            ),
        )
        cursor = conn.execute(
            "INSERT INTO device_groups(site_id,name,sort_order,created_at,updated_at) VALUES('demo','车站',0,'2026-01-01','2026-01-01')"
        )
        conn.execute(
            "UPDATE devices SET group_id=?,station='车站A',station_id='station-meta-1' WHERE device_uuid='switch-1'",
            (cursor.lastrowid,),
        )
        conn.execute("DELETE FROM ap_extension_points WHERE ap_name='AP-Duplicate'")
    facts = DeviceFactRepository(Database(db))
    interfaces = facts.list_device_interfaces("switch-1")
    for interface in interfaces:
        interface["description"] = "AP uplink"
    facts.replace_device_interfaces("switch-1", interfaces)
    before = read_trackside_ap_source_revisions(Database(db))
    _mutate(
        relations,
        "device_node",
        "station-1",
        "switch-1",
        values={"installation_location": "通信机房"},
    )
    after = read_trackside_ap_source_revisions(Database(db))
    assert before["base_data_revision"] != after["base_data_revision"]
    snapshot = load_trackside_ap_business_snapshot(
        DeviceRepository(Database(db)), "demo", 1
    )
    assert snapshot.rows
    assert snapshot.rows[0]["switch_engineering_context"]["node_uid"] == "station-1"
    assert (
        snapshot.rows[0]["switch_engineering_context"]["physical_location"]
        == "通信机房"
    )
    assert all(
        "switch_engineering_context" in r and "point_engineering_context" in r
        for r in snapshot.rows
    )
    assert all(
        r["point_engineering_context"]["affiliation_status"]
        in {"unconfirmed", "associated", "conflict", "stale", "unavailable"}
        for r in snapshot.rows
    )


def test_ac_services_remain_separate_from_current_and_wireless_revision_refreshes(
    tmp_path,
):
    from netconsole.services.ac.query_service import AcManagementQueryService
    from netconsole.services.rail_transit.wireless_dashboard_query_service import (
        WirelessDashboardQueryService,
    )

    paths, db, relations = _service(tmp_path)
    _mutate(relations, "ac_service", "ac-1", "station-1", effective_from="2026-01-01")
    ac = AcManagementQueryService(paths).get_summary("demo")
    selected = next(a for a in ac.acs if a.id == "ac-1")
    assert selected.engineering_context.service_stations == ["车站A"]
    with closing(Database(db).connect()) as conn, conn:
        conn.execute(
            "UPDATE rail_infra_node SET official_name='车站A新名' WHERE node_uid='station-1'"
        )
    engineering = EngineeringContextQueryService(paths)
    assert engineering.one("demo", "ac-1").service_stations == ["车站A新名"]
    assert engineering.one("demo", "ac-1", at_time="2026-11-01").service_stations == [
        "车站A"
    ]
    wireless = WirelessDashboardQueryService(paths, cache_ttl_seconds=3600)
    first = wireless.get_dashboard("demo")
    assert 'ac-1' in wireless.get_dashboard('demo',station_id='station-1').engineering_contexts
    _mutate(relations, "node_project", "station-1", "project-1")
    second = wireless.get_dashboard("demo")
    assert first.engineering_revision != second.engineering_revision
    assert not second.summary.cached
    assert wireless.get_dashboard("demo", section_id="missing").trains.total == 0
    assert first.summary.ap_total == second.summary.ap_total


def test_online_mr_history_keeps_original_identity_after_replacement_and_context_failure(
    tmp_path, monkeypatch
):
    import json
    from tests.test_online_mr_query_service import _session
    from netconsole.services.online_mr.query_service import OnlineMrQueryService
    from netconsole.services.rail_transit.base_data_query_service import (
        RailTransitBaseDataQueryService,
    )

    paths, db, relations = _service(tmp_path)
    online = OnlineMrQueryService(paths)
    folder = _session(
        online, "retained", site="demo", mr="old-MR", started_at="2026-11-01T00:00:00Z"
    )
    meta = folder / "session_meta.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["mr_id"] = "mr-01-ct"
    meta.write_text(json.dumps(data), encoding="utf-8")
    original = meta.read_bytes()
    first = _mutate(
        relations,
        "train_mr",
        "train-1",
        "mr-01-ct",
        values={"position": "CT"},
        effective_from="2026-01-01",
    )
    _mutate(
        relations,
        "train_mr",
        "train-1",
        "mr-temp",
        action="replace",
        relation_id=first.relationship.relationship_id,
        values={"position": "CT"},
        effective_from="2026-11-20",
    )
    result = online.get_session("demo", "retained")
    assert result.mr_name == "old-MR"
    assert result.historical_engineering_context.node_uid == "train-1"
    assert result.historical_engineering_context.affiliation_status == "historical"
    assert result.current_engineering_context.node_uid != "train-1"
    monkeypatch.setattr(
        RailTransitBaseDataQueryService,
        "infrastructure",
        lambda *a: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    result = online.get_session("demo", "retained")
    assert (
        result.session_id == "retained"
        and result.current_engineering_context.affiliation_status == "unavailable"
    )
    assert meta.read_bytes() == original


def test_mesh_history_uses_only_explicit_uuid_and_preserves_evidence(tmp_path):
    from tests.support.mesh_analysis_test_support import create_mesh_analysis_fixture
    from netconsole.services.rail_transit.mesh_analysis_query_service import (
        MeshAnalysisQueryService,
    )

    paths, db, relations = _service(tmp_path)
    paths, session_id, detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths)
    protected = {p: p.read_bytes() for p in (detail, raw, report)}
    legacy = service.get_analysis_session("demo", session_id)
    assert legacy.historical_engineering_context.affiliation_status == "unconfirmed"
    with closing(Database(paths.mesh_catalog_path("demo")).connect()) as conn, conn:
        conn.execute("ALTER TABLE mr_profiles ADD COLUMN linked_device_uuid TEXT")
        conn.execute("UPDATE mr_profiles SET linked_device_uuid='mr-01-ct'")
    first = _mutate(
        relations,
        "train_mr",
        "train-1",
        "mr-01-ct",
        values={"position": "CT"},
        effective_from="2026-01-01",
    )
    _mutate(
        relations,
        "train_mr",
        "train-1",
        "mr-temp",
        action="replace",
        relation_id=first.relationship.relationship_id,
        values={"position": "CT"},
        effective_from="2026-11-20",
    )
    result = service.get_analysis_session("demo", session_id)
    assert result.historical_engineering_context.node_uid == "train-1"
    assert result.current_engineering_context.node_uid != "train-1"
    assert result.session == legacy.session
    assert all(p.read_bytes() == content for p, content in protected.items())
