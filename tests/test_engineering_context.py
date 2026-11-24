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
