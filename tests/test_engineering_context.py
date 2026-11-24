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
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
    from netconsole.services.ground_unattended.inventory import TrainInventorySyncService
    from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
    paths, db, relations = _service(tmp_path)
    repo=DeviceRepository(Database(db))
    with closing(Database(db).connect()) as conn, conn:
        conn.execute('DELETE FROM rail_infra_train')
    ids=[]
    for index in range(50):
        train=f'formal-train-{index}'
        with closing(Database(db).connect()) as conn, conn:
            conn.execute('INSERT INTO rail_infra_train VALUES(?,?,?)',(train,str(index+100),f'T{index}'))
        for role in ('CT','CW'):
            d=repo.create(Device(name=f'MR{index}{role}',device_type='MR',primary_address=f'192.0.2.{index*2+(1 if role=="CT" else 2)}'))
            ids.append(str(d.device_uuid))
            with closing(Database(db).connect()) as conn, conn:
                conn.execute('INSERT INTO rail_infra_train_mr VALUES(?,?,?,?,?,NULL)',(f'assign-{index}-{role}',train,str(d.device_uuid),role,'2026-01-01'))
    context=EngineeringContextQueryService(paths)
    result=context.contexts('demo',ids)
    assert len(result)==100 and all(c.affiliation_status=='associated' for c in result.values())
    ground=GroundUnattendedRepository(tmp_path/'ground.sqlite',site_id='demo');ground.initialize()
    sync=TrainInventorySyncService(paths,site_id='demo',repository=ground,base_query=RailTransitBaseDataQueryService(paths))
    sync.collection_ttl=3600
    first=sync.collect()
    assert len([m for m in first.mrs if m['id'] in ids])==100
    with closing(Database(db).connect()) as conn, conn:
        conn.execute("UPDATE rail_infra_train_mr SET active_to='2026-11-20' WHERE assignment_id='assign-0-CT'")
    second=sync.collect()
    assert first.source_revision!=second.source_revision
    assert ids[0] not in {m['id'] for m in second.mrs}
    assert repo.get_by_uuid(ids[0]) is not None


def test_ground_context_failure_does_not_erase_runtime_inventory(tmp_path,monkeypatch):
    from netconsole.backend.api.main import create_app
    from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
    paths,db,relations=_service(tmp_path)
    app=create_app(paths=paths,frontend_dist=tmp_path/'missing')
    ground=app.state.ground_unattended_application_service
    before=ground.list_trains('demo')
    monkeypatch.setattr(RailTransitBaseDataQueryService,'infrastructure',lambda *a: (_ for _ in ()).throw(RuntimeError('context offline')))
    after=ground.list_trains('demo')
    assert [t.train_id for t in before.items]==[t.train_id for t in after.items]
    assert all(t.engineering_context_status=='unavailable' for t in after.items if any(e.mr_id for e in t.endpoints))
