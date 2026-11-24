from contextlib import closing

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from tests.test_rail_relationship_application import _request, _service


def _fixture(tmp_path):
    paths, db_path, relations = _service(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.rail_relationship_application_service = relations
    for name in (
        "module.rail_base_data",
        "module.rail_infrastructure",
        "capability.rail_base_data.write",
        "capability.rail_infrastructure.write",
    ):
        app.state.feature_gate.features[name] = dict(visible=True, enabled=True)
    return TestClient(app), app, db_path, relations


def _enabled(app, feature, enabled):
    app.state.feature_gate.features[feature] = dict(visible=enabled, enabled=enabled)


def test_base_data_only_cannot_open_or_write_engineering(tmp_path):
    client, app, db_path, relations = _fixture(tmp_path)
    _enabled(app, "module.rail_infrastructure", False)
    assert (
        client.get("/api/rail-transit/base-data/summary?site_id=demo").status_code
        == 200
    )
    for path in (
        "infrastructure",
        "base-data/infrastructure",
        "relationships",
        "relationships/catalog",
        "relationships/engineering-context?device_uuid=mr-temp",
        "relationships/delete-preflight?entity_uid=mr-temp",
    ):
        assert client.get("/api/rail-transit/" + path).status_code == 404
    request = _request(
        relations,
        kind="node_project",
        action="create",
        revision=relations.list_current("demo").revision,
        source="station-1",
        target="project-1",
    )
    assert (
        client.post(
            "/api/rail-transit/relationships", json=request.model_dump(mode="json")
        ).status_code
        == 404
    )
    assert relations.list_current("demo").total == 0


def test_infrastructure_only_has_own_read_and_write_permissions(tmp_path):
    client, app, db_path, relations = _fixture(tmp_path)
    _enabled(app, "module.rail_base_data", False)
    with closing(Database(db_path).connect_readonly()) as conn:
        before = conn.serialize()
    assert (
        client.get("/api/rail-transit/infrastructure?site_id=demo").status_code == 200
    )
    assert (
        client.get("/api/rail-transit/relationships/catalog?site_id=demo").status_code
        == 200
    )
    assert (
        client.get("/api/rail-transit/base-data/summary?site_id=demo").status_code
        == 404
    )
    assert (
        client.post("/api/rail-transit/base-data/changes", json={}).status_code == 404
    )
    request = _request(
        relations,
        kind="node_project",
        action="create",
        revision=relations.list_current("demo").revision,
        source="station-1",
        target="project-1",
    )
    _enabled(app, "capability.rail_base_data.write", False)
    preview = client.post(
        "/api/rail-transit/relationships/preview", json=request.model_dump(mode="json")
    )
    assert preview.status_code == 200
    with closing(Database(db_path).connect_readonly()) as conn:
        assert conn.serialize() == before
    assert (
        client.post(
            "/api/rail-transit/relationships", json=request.model_dump(mode="json")
        ).status_code
        == 200
    )
    assert relations.list_current("demo").total == 1


def test_each_write_capability_is_checked_at_http_boundary(tmp_path):
    client, app, db_path, relations = _fixture(tmp_path)
    _enabled(app, "capability.rail_infrastructure.write", False)
    request = _request(
        relations,
        kind="node_project",
        action="create",
        revision=relations.list_current("demo").revision,
        source="station-1",
        target="project-1",
    )
    for suffix in ("", "/preview"):
        assert (
            client.post(
                "/api/rail-transit/relationships" + suffix,
                json=request.model_dump(mode="json"),
            ).status_code
            == 404
        )
    assert (
        client.get("/api/rail-transit/infrastructure?site_id=demo").status_code == 200
    )
    assert (
        client.get(
            "/api/rail-transit/base-data/edit-snapshot?site_id=demo&scope=overview"
        ).status_code
        == 200
    )
    _enabled(app, "capability.rail_infrastructure.write", True)
    _enabled(app, "capability.rail_base_data.write", False)
    for path in (
        "changes",
        "clear-all",
        "import-apply",
        "import-operations/missing/rollback",
    ):
        assert (
            client.post("/api/rail-transit/base-data/" + path, json={}).status_code
            == 404
        )
    assert relations.list_current("demo").total == 0


def test_new_projection_and_legacy_api_read_same_facts_without_writes(tmp_path):
    client, app, db_path, relations = _fixture(tmp_path)
    with closing(Database(db_path).connect_readonly()) as conn:
        before = conn.serialize()
    current = client.get("/api/rail-transit/infrastructure?site_id=demo")
    legacy = client.get("/api/rail-transit/base-data/infrastructure?site_id=demo")
    assert current.status_code == legacy.status_code == 200
    assert current.json() == legacy.json()
    assert (
        client.get("/api/rail-transit/infrastructure?site_id=../outside").status_code
        == 422
    )
    assert (
        client.get(
            "/api/rail-transit/relationships/delete-preflight?site_id=demo&entity_uid=mr-temp"
        ).json()["can_delete"]
        is False
    )
    with closing(Database(db_path).connect_readonly()) as conn:
        assert conn.serialize() == before
