from contextlib import closing
import json
import sqlite3
import pytest
from netconsole.core.database import Database
from netconsole.models.api.asset_deletion import AssetDeletionPreflightRequest
from netconsole.repositories.device_repository import (
    DeviceRepository,
    AssetDeletionBlockedError,
)
from netconsole.services.asset_deletion_preflight import AssetDeletionPreflightService
from tests.test_rail_relationship_application import _service, _mutate


def setup(tmp_path):
    paths, db, relations = _service(tmp_path)
    service = AssetDeletionPreflightService(paths, budget_seconds=5)
    request = AssetDeletionPreflightRequest(
        device_uuid="mr-temp",
        base_revision=relations.repository.revision("demo"),
        source="safety-test",
        request_id="preflight-1",
    )
    return paths, db, relations, service, request


def test_unknown_evidence_never_grants_deletion_and_reads_are_side_effect_free(
    tmp_path,
):
    paths, db, relations, service, request = setup(tmp_path)
    service.references.identity("demo")
    service.references.device("demo", "mr-temp")
    before = db.read_bytes()
    a = service.inspect("demo", request)
    b = service.inspect("demo", request)
    assert a["can_delete"] is b["can_delete"] is False
    assert a["status"] in {
        "BLOCKED_BY_EXTERNAL_REFERENCE",
        "BLOCKED_BY_UNVERIFIED_SOURCE",
    }
    assert (
        a["external_reference_checks"]["archives_reports_mac_aliases"]["status"]
        == "NOT_VERIFIED"
    )
    assert a["request_id"] == b["request_id"]
    assert a["checked_at"] <= a["expires_at"]
    assert "private-pass" not in json.dumps(a)
    assert db.read_bytes() == before
    assert not paths.site_tasks_db_path("demo").exists()


def test_active_and_historical_relationships_always_block(tmp_path):
    paths, db, relations, service, request = setup(tmp_path)
    created = _mutate(
        relations, "device_section", "mr-temp", "section-1", effective_from="2026-01-01"
    )
    request.base_revision = relations.repository.revision("demo")
    assert service.inspect("demo", request)["status"] == "BLOCKED_BY_ACTIVE_RELATION"
    _mutate(
        relations,
        "device_section",
        action="terminate",
        relation_id=created.relationship.relationship_id,
        effective_to="2026-11-01",
    )
    request.base_revision = relations.repository.revision("demo")
    assert service.inspect("demo", request)["status"] == "BLOCKED_BY_HISTORY_REFERENCE"
    assert DeviceRepository(Database(db)).get_by_uuid("mr-temp")


@pytest.mark.parametrize("domain", ["site_facts", "tasks", "ground", "mesh_index"])
def test_known_sql_evidence_blocks_without_touching_it(tmp_path, domain):
    paths, db, relations, service, request = setup(tmp_path)
    target = {
        "site_facts": db,
        "tasks": paths.site_tasks_db_path("demo"),
        "ground": paths.ground_unattended_db_path("demo"),
        "mesh_index": paths.mesh_catalog_path("demo"),
    }[domain]
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target)) as conn, conn:
        conn.execute("CREATE TABLE retained_history(device_uuid TEXT, evidence TEXT)")
        conn.execute(
            "INSERT INTO retained_history VALUES (?,?)",
            ("mr-temp", "original evidence"),
        )
    request.base_revision = relations.repository.revision("demo")
    result = service.inspect("demo", request)
    assert not result["can_delete"]
    assert any(
        x["table"] == "retained_history"
        for x in result["external_reference_checks"][domain]["matches"]
    )
    with closing(sqlite3.connect(target)) as conn:
        assert (
            conn.execute("SELECT evidence FROM retained_history").fetchone()[0]
            == "original evidence"
        )


def test_online_mr_history_and_report_are_preserved_on_exclusion(tmp_path):
    paths, db, relations, service, request = setup(tmp_path)
    session = paths.online_mr_session_dir("demo", "old-mr", "session-1")
    session.mkdir(parents=True)
    meta = session / "session_meta.json"
    meta.write_text(
        json.dumps(dict(session_id="session-1", device_uuid="mr-temp")),
        encoding="utf-8",
    )
    report = session / "report.xlsx"
    report.write_bytes(b"synthetic retained report")
    before = {p: p.read_bytes() for p in (meta, report)}
    with closing(Database(db).connect()) as conn, conn:
        conn.execute(
            "UPDATE devices SET work_scope_status='excluded' WHERE device_uuid='mr-temp'"
        )
    request.base_revision = relations.repository.revision("demo")
    result = service.inspect("demo", request)
    assert result["current_asset_state"] == "excluded"
    assert (
        result["external_reference_checks"]["online_mr"]["matches"][0]["session_id"]
        == "session-1"
    )
    assert {p: p.read_bytes() for p in before} == before
    assert result["can_delete"] is False


@pytest.mark.parametrize(
    "failure",
    [
        sqlite3.OperationalError("locked"),
        OSError("file index"),
        TimeoutError("deadline"),
    ],
)
def test_failed_sources_are_unverified(tmp_path, monkeypatch, failure):
    paths, db, relations, service, request = setup(tmp_path)

    def fail(*args):
        raise failure

    monkeypatch.setattr(service.references, "sql_references", fail)
    monkeypatch.setattr(service.references, "session_references", fail)
    result = service.inspect("demo", request)
    assert not result["can_delete"]
    assert result["external_reference_checks"]["online_mr"]["status"] == "NOT_VERIFIED"
    assert all(
        x["status"] == "NOT_VERIFIED"
        for x in result["external_reference_checks"].values()
    )


def test_timeout_stale_revision_concurrent_change_and_expired_result_cannot_authorize(
    tmp_path, monkeypatch
):
    paths, db, relations, service, request = setup(tmp_path)
    stale = request.model_copy(update={"base_revision": "stale"})
    assert service.inspect("demo", stale)["status"] == "BLOCKED_BY_REVISION_CONFLICT"
    service.budget_seconds = -1
    assert service.inspect("demo", request)["status"] == "PREFLIGHT_FAILED"
    service.budget_seconds = 5
    original = service.relationships.revision
    calls = []

    def drift(site):
        calls.append(1)
        return original(site) if len(calls) == 1 else "changed"

    monkeypatch.setattr(service.relationships, "revision", drift)
    assert service.inspect("demo", request)["status"] == "BLOCKED_BY_REVISION_CONFLICT"
    repo = DeviceRepository(Database(db))
    before = db.read_bytes()
    with pytest.raises(AssetDeletionBlockedError):
        repo.delete(999)
    with pytest.raises(AssetDeletionBlockedError):
        repo.delete_many_by_uuid(["mr-temp"])
    assert db.read_bytes() == before


def test_ap_identity_and_collection_history_are_known_references(tmp_path):
    paths, db, relations, service, request = setup(tmp_path)
    with closing(Database(db).connect()) as conn, conn:
        conn.execute(
            "INSERT INTO ap_identity_entities(entity_id,ac_device_uuid,effective_source,identity_status,created_at,updated_at) VALUES ('entity','mr-temp','test','confirmed','2026-01-01','2026-01-01')"
        )
        conn.execute("CREATE TABLE synthetic_collection_history(device_id INTEGER)")
        conn.execute(
            "INSERT INTO synthetic_collection_history SELECT id FROM devices WHERE device_uuid='mr-temp'"
        )
    result = service.inspect("demo", request)
    found = {
        m["table"] for m in result["external_reference_checks"]["site_facts"]["matches"]
    }
    assert {"ap_identity_entities", "synthetic_collection_history"} <= found
    assert not result["can_delete"]


def test_api_rejects_confirmation_and_batch_delete_even_with_forged_token(tmp_path):
    from tests.test_device_management_web_api import _fixture

    client, service, adapter, devices, facts, mr, sw = _fixture(tmp_path)
    uid = str(mr.device_uuid)
    for path, body in [
        ("delete-confirmation", {"device_uuids": [uid]}),
        (
            "batch-delete",
            {
                "device_uuids": [uid],
                "confirmation_token": "forged-token-that-has-valid-length-0123456789",
            },
        ),
    ]:
        response = client.post("/api/device-management/devices/" + path, json=body)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ASSET_DELETION_NOT_AUTHORIZED"
    assert devices.get_by_uuid(uid)


def test_preflight_api_and_readonly_feature_enforcement(tmp_path):
    from tests.test_device_management_web_api import _fixture

    client, service, adapter, devices, facts, mr, sw = _fixture(tmp_path)
    preflight = AssetDeletionPreflightService(service.paths, budget_seconds=5)
    request = AssetDeletionPreflightRequest(
        device_uuid=str(mr.device_uuid),
        base_revision=preflight.relationships.revision(service.current_site_id()),
        source="api",
        request_id="same-request",
    )
    response = client.post(
        "/api/device-management/devices/deletion-preflight", json=request.model_dump()
    )
    assert response.status_code == 200
    assert response.json()["can_delete"] is False
    assert response.json()["request_id"] == "same-request"
    assert "secret-password" not in response.text


def test_source_symlink_cannot_escape_or_be_considered_empty(tmp_path):
    paths, db, relations, service, request = setup(tmp_path)
    outside = tmp_path / "outside.sqlite"
    try:
        paths.site_tasks_db_path("demo").symlink_to(outside)
    except OSError:
        # Windows hosts may prohibit unprivileged symlink creation; path escape remains testable.
        with pytest.raises(ValueError):
            service.references._check_path(outside)
    else:
        result = service.inspect("demo", request)
        assert result["external_reference_checks"]["tasks"]["status"] == "NOT_VERIFIED"
        assert not result["can_delete"]


def test_ac_unlink_preserves_current_and_optical_history(tmp_path):
    paths, db, relations, service, request = setup(tmp_path)
    with closing(Database(db).connect()) as conn, conn:
        conn.execute("UPDATE devices SET device_type='AC' WHERE device_uuid='mr-temp'")
        before = [tuple(r) for r in conn.execute("SELECT * FROM ac_fit_ap_resources")]
    created = _mutate(
        relations, "ac_service", "mr-temp", "station-1", effective_from="2026-01-01"
    )
    _mutate(
        relations,
        "ac_service",
        action="terminate",
        relation_id=created.relationship.relationship_id,
        effective_to="2026-11-01",
    )
    with closing(Database(db).connect_readonly()) as conn:
        assert [
            tuple(r) for r in conn.execute("SELECT * FROM ac_fit_ap_resources")
        ] == before
    assert DeviceRepository(Database(db)).get_by_uuid("mr-temp")


def test_legacy_job_cannot_bypass_repository_deletion_policy(tmp_path):
    from netconsole.services.job_center.handlers.legacy_tasks import _device_mutation

    paths, db, relations, service, request = setup(tmp_path)
    device = DeviceRepository(Database(db)).get_by_uuid("mr-temp")
    result = _device_mutation(
        {"db_path": str(db), "action": "delete", "device_ids": [device.id]}, None, None
    )
    assert result["deleted"] == 0 and result["failed"] == 1
    assert DeviceRepository(Database(db)).get_by_uuid("mr-temp")


def test_malformed_metadata_missing_asset_and_failed_initial_query(
    tmp_path, monkeypatch
):
    paths, db, relations, service, request = setup(tmp_path)
    session = paths.online_mr_session_dir("demo", "mr", "session")
    session.mkdir(parents=True)
    (session / "session_meta.json").write_text("[]", encoding="utf-8")
    result = service.inspect("demo", request)
    assert result["external_reference_checks"]["online_mr"]["status"] == "NOT_VERIFIED"
    missing = request.model_copy(update={"device_uuid": "missing"})
    assert service.inspect("demo", missing)["status"] == "PREFLIGHT_FAILED"

    def fail(*args):
        raise sqlite3.OperationalError("broken initial db")

    monkeypatch.setattr(service.references, "identity", fail)
    assert service.inspect("demo", request)["status"] == "PREFLIGHT_FAILED"


def test_untrusted_expired_preflight_is_not_an_execution_permit(tmp_path):
    from tests.test_device_management_web_api import _fixture

    client, service, adapter, devices, facts, mr, sw = _fixture(tmp_path)
    uid = str(mr.device_uuid)
    response = client.post(
        "/api/device-management/devices/batch-delete",
        json={
            "device_uuids": [uid],
            "confirmation_token": "expired-token-000000000000000000000000000000",
        },
    )
    assert response.status_code == 409
    client.app.state.feature_gate.features["capability.devices.write"] = {
        "enabled": False,
        "visible": False,
    }
    response = client.post(
        "/api/device-management/devices/deletion-preflight",
        json={
            "device_uuid": uid,
            "source": "test",
            "request_id": "x",
            "base_revision": "x",
        },
    )
    assert response.status_code == 404
    assert devices.get_by_uuid(uid)
