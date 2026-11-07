from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_mesh_link import AcMeshMrPageDTO
from netconsole.models.api.ground_unattended import GroundHeartbeatInventoryApplyDTO
from netconsole.models.api.rail_transit_base_data import VehicleMrDTO
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ground_unattended.application_service import GroundUnattendedError


@pytest.fixture
def inventory_app(tmp_path, monkeypatch):
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    service = app.state.ground_unattended_application_service
    assets = DeviceRepository(Database(paths.site_db_path(service.site_id)))
    devices = [assets.create(Device(name=f"T01-{role}", primary_address=f"192.0.2.{index}"))
               for index, role in enumerate(("CT", "CW"), 1)]
    rows = [VehicleMrDTO(id=str(device.device_uuid), device_id=device.id,
                         name=device.name, management_ip=device.primary_address,
                         train_id="train-01", train_no="01", mr_position_code=role)
            for device, role in zip(devices, ("CT", "CW"))]
    source = SimpleNamespace(rows=rows)
    service.inventory_sync.base_query = SimpleNamespace(
        list_mesh_import_context_mrs=lambda site_id: source.rows,
    )
    monkeypatch.setattr(AcMeshLinkQueryService, "list_mrs", lambda *args, **kwargs: AcMeshMrPageDTO())
    start = Mock(side_effect=AssertionError("inventory operations must not start probes"))
    monkeypatch.setattr(service.supervisor.fleet_ping, "start", start)
    return SimpleNamespace(app=app, paths=paths, service=service, repository=service.repository,
                           source=source, assets=assets, devices=devices, start=start)


def _apply(fixture, action: str):
    preview = fixture.service.heartbeat_inventory_preview(fixture.service.site_id, action=action)
    return fixture.service.heartbeat_inventory_apply(fixture.service.site_id, GroundHeartbeatInventoryApplyDTO(
        action=action, revision=preview.revision, confirm=True,
    ))


def _run(repository, run_id="run-1", *, state="COMPLETED"):
    return repository.create_or_get_run(run_id=run_id, run_date="2026-11-07", state=state,
                                       scheduled_start_at="2026-11-07T00:00:00Z",
                                       scheduled_end_at="2026-11-07T23:00:00Z")


def test_refresh_projects_unknown_without_run_and_is_idempotent(inventory_app):
    f = inventory_app
    site = f.service.site_id
    preview = f.service.heartbeat_inventory_preview(site)
    assert (preview.added_count, preview.train_count, preview.device_count) == (2, 1, 2)
    first = f.service.heartbeat(site)
    before = f.repository.list_inventory()
    second = f.service.heartbeat(site)
    assert first == second
    assert f.repository.list_inventory() == before
    assert first.run_id == ""
    assert [mr.status for mr in first.mrs] == ["UNKNOWN", "UNKNOWN"]
    assert first.trains[0].status == "UNKNOWN"
    assert first.trains[0].mr_states == {"CT": "UNKNOWN", "CW": "UNKNOWN"}
    assert f.service.heartbeat_inventory_preview(site).added_count == 0
    f.start.assert_not_called()


def test_changed_ip_invalidates_mr_and_old_train_online_aggregate(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    _run(f.repository, state="RUNNING")
    for mr in f.source.rows:
        f.repository.upsert_heartbeat_snapshot("run-1", {
            "mr_uuid": mr.id, "train_id": mr.train_id, "role": mr.mr_position_code,
            "status": "ONLINE", "ip_states": [{"ip": mr.management_ip}],
        }, entity_type="MR", entity_id=mr.id)
    f.repository.upsert_heartbeat_snapshot("run-1", {
        "train_id": "train-01", "status": "BOTH_ONLINE", "mr_states": {"CT": "ONLINE", "CW": "ONLINE"},
    }, entity_type="TRAIN", entity_id="train-01")
    assert f.service.heartbeat(site).trains[0].status == "BOTH_ONLINE"
    f.source.rows[0] = f.source.rows[0].model_copy(update={"management_ip": "192.0.2.30", "train_no": "02"})
    page = f.service.heartbeat(site)
    ct = next(mr for mr in page.mrs if mr.role == "CT")
    assert ct.status == "UNKNOWN" and ct.ip_states[0].ip == "192.0.2.30"
    assert page.trains[0].status == "UNKNOWN"
    assert page.trains[0].mr_states == {"CT": "UNKNOWN", "CW": "ONLINE"}
    f.start.assert_not_called()


@pytest.mark.parametrize("conflict", ["uuid", "role"])
def test_source_conflict_does_not_write_inventory(inventory_app, conflict):
    f = inventory_app
    f.service.heartbeat(f.service.site_id)
    before = f.repository.list_inventory()
    replacement = {"id": f.source.rows[0].id} if conflict == "uuid" else {"mr_position_code": "CT"}
    f.source.rows[1] = f.source.rows[1].model_copy(update=replacement)
    preview = f.service.heartbeat_inventory_preview(f.service.site_id)
    assert preview.conflict_count == 1
    with pytest.raises(GroundUnattendedError) as error:
        _apply(f, "SYNC")
    assert error.value.code == "HEARTBEAT_INVENTORY_CONFLICT"
    assert f.service.heartbeat(f.service.site_id).source_conflicts
    assert f.repository.list_inventory() == before


def test_clear_devices_preserves_assets_inventory_and_other_site_then_sync_restores(inventory_app):
    f = inventory_app
    f.service.heartbeat(f.service.site_id)
    before = f.repository.list_inventory()
    other = GroundUnattendedRepository(f.repository.db_path, site_id="other")
    other.sync_inventory(trains=[{"train_id": "other-train"}], endpoints=[{
        "device_uuid": "other-mr", "train_id": "other-train", "mr_role": "CT",
    }])
    other_before = other.list_inventory()
    result = _apply(f, "CLEAR_DEVICES")
    assert result.applied and not result.monitoring_enabled and result.disabled_count == 2
    assert f.service.heartbeat(f.service.site_id).mrs == []
    assert f.service.supervisor._heartbeat_fleet_targets() == {}
    assert f.repository.list_inventory() == before
    assert other.list_inventory() == other_before
    assert all(f.assets.get_by_uuid(device.device_uuid) for device in f.devices)
    assert _apply(f, "SYNC").monitoring_enabled
    assert len(f.service.heartbeat(f.service.site_id).mrs) == 2
    assert len(f.service.supervisor._heartbeat_fleet_targets()) == 2
    f.start.assert_not_called()


def test_clear_data_retains_shared_ping_raw_and_nonheartbeat_events(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    _run(f.repository)
    other = GroundUnattendedRepository(f.repository.db_path, site_id="other")
    for repository in (f.repository, other):
        repository.upsert_heartbeat_snapshot("run-1", {"status": "ONLINE"}, entity_type="MR", entity_id="mr-1")
        repository.add_event_once(dedup_key="heartbeat:mr-1:online", run_id="run-1",
                                  event_type="heartbeat_mr_online", title="online")
        repository.add_event(run_id="run-1", event_type="deep_collection", title="preserved")
        repository.upsert_ping_summary({"site_id": repository.site_id, "run_id": "run-1",
                                        "bucket_kind": "daily", "bucket_start": "2026-11-07T00:00:00Z",
                                        "bucket_end": "2026-11-08T00:00:00Z", "created_at": "2026-11-07T00:00:00Z"})
    raw_path = f.repository.db_path.parent / "fixture.ndjson"
    raw_path.write_text('{"ok":true}\n', encoding="utf-8")
    f.repository.upsert_raw_file({"file_id": "raw-1", "run_id": "run-1", "data_type": "ping",
                                  "relative_path": "fixture.ndjson"})
    preview = f.service.heartbeat_inventory_preview(site, action="CLEAR_DATA")
    assert (preview.affected_history_count, preview.retained_history_count) == (2, 1)
    _apply(f, "CLEAR_DATA")
    assert f.repository.list_heartbeat_snapshots("run-1") == []
    assert [row["event_type"] for row in f.repository.list_events("run-1")] == ["deep_collection"]
    assert len(f.repository.list_ping_summaries("run-1")) == 1
    assert len(f.repository.list_raw_files_for_run("run-1")) == 1
    assert raw_path.read_text(encoding="utf-8") == '{"ok":true}\n'
    assert len(other.list_heartbeat_snapshots("run-1")) == 1
    assert len(other.list_events("run-1")) == 2
    assert len(other.list_ping_summaries("run-1")) == 1
    assert f.repository.heartbeat_inventory_state()["data_cleared_at"]
    assert len(f.service.heartbeat(site).mrs) == 2


def test_confirmation_is_action_bound_stale_checked_and_run_guarded(inventory_app):
    f = inventory_app
    site = f.service.site_id
    preview = f.service.heartbeat_inventory_preview(site)
    for action, confirm, code in (("SYNC", False, "HEARTBEAT_CONFIRM_REQUIRED"),
                                  ("CLEAR_DEVICES", True, "HEARTBEAT_PREVIEW_STALE")):
        with pytest.raises(GroundUnattendedError) as error:
            f.service.heartbeat_inventory_apply(site, GroundHeartbeatInventoryApplyDTO(
                action=action, revision=preview.revision, confirm=confirm,
            ))
        assert error.value.code == code
    f.source.rows[0] = f.source.rows[0].model_copy(update={"management_ip": "192.0.2.88"})
    with pytest.raises(GroundUnattendedError) as error:
        f.service.heartbeat_inventory_apply(site, GroundHeartbeatInventoryApplyDTO(
            action="SYNC", revision=preview.revision, confirm=True,
        ))
    assert error.value.code == "HEARTBEAT_PREVIEW_STALE"
    _run(f.repository, state="RUNNING")
    for action in ("CLEAR_DEVICES", "CLEAR_DATA"):
        with pytest.raises(GroundUnattendedError) as error:
            _apply(f, action)
        assert error.value.code == "HEARTBEAT_RUN_ACTIVE"
    with pytest.raises(GroundUnattendedError) as error:
        f.service.heartbeat_inventory_preview("other")
    assert error.value.code == "SITE_MISMATCH"


@pytest.mark.parametrize("failure", ["conflict", "changed_source"])
def test_failed_sync_does_not_reenable_selection_or_write_inventory(inventory_app, monkeypatch, failure):
    f = inventory_app
    f.service.heartbeat(f.service.site_id)
    _apply(f, "CLEAR_DEVICES")
    before = f.repository.list_inventory()
    original = f.service.inventory_sync.collect
    calls = 0

    def source_changes_after_preview():
        nonlocal calls
        calls += 1
        result = original()
        if calls == 3:
            if failure == "conflict":
                return (*result[:3], ["MR_POSITION_DUPLICATE: train-01/CT"])
            result[1][0]["management_ip"] = "192.0.2.99"
        return result

    monkeypatch.setattr(f.service.inventory_sync, "collect", source_changes_after_preview)
    preview = f.service.heartbeat_inventory_preview(f.service.site_id)
    with pytest.raises(GroundUnattendedError) as error:
        f.service.heartbeat_inventory_apply(f.service.site_id, GroundHeartbeatInventoryApplyDTO(
            action="SYNC", revision=preview.revision, confirm=True,
        ))
    assert error.value.code == ("HEARTBEAT_INVENTORY_CONFLICT" if failure == "conflict" else "HEARTBEAT_PREVIEW_STALE")
    assert not f.repository.heartbeat_inventory_state()["enabled"]
    assert f.repository.list_inventory() == before


def test_state_change_after_preview_is_rejected_inside_apply_transaction(inventory_app, monkeypatch):
    f = inventory_app
    site = f.service.site_id
    preview = f.service.heartbeat_inventory_preview(site, action="CLEAR_DATA")
    original = f.service.heartbeat_inventory_preview

    def concurrent_change(*args, **kwargs):
        result = original(*args, **kwargs)
        f.repository.apply_heartbeat_inventory_action("CLEAR_DEVICES", expected_revision=0)
        return result

    monkeypatch.setattr(f.service, "heartbeat_inventory_preview", concurrent_change)
    with pytest.raises(GroundUnattendedError) as error:
        f.service.heartbeat_inventory_apply(site, GroundHeartbeatInventoryApplyDTO(
            action="CLEAR_DATA", revision=preview.revision, confirm=True,
        ))
    assert error.value.code == "HEARTBEAT_PREVIEW_STALE"
    assert f.repository.heartbeat_inventory_state()["data_cleared_at"] == ""


def test_sync_preview_ignores_live_heartbeat_history_growth(inventory_app):
    f = inventory_app
    f.service.heartbeat(f.service.site_id)
    preview = f.service.heartbeat_inventory_preview(f.service.site_id)
    f.repository.upsert_heartbeat_snapshot("run-1", {"status": "ONLINE"}, entity_type="MR", entity_id="mr-1")
    latest = f.service.heartbeat_inventory_preview(f.service.site_id)
    assert latest.revision == preview.revision
    assert latest.retained_history_count == preview.retained_history_count + 1


def test_clear_actions_do_not_need_readable_device_source(inventory_app, monkeypatch):
    f = inventory_app
    f.service.heartbeat(f.service.site_id)
    monkeypatch.setattr(f.service.inventory_sync, "collect", Mock(side_effect=OSError("source unavailable")))
    assert _apply(f, "CLEAR_DEVICES").monitoring_enabled is False
    assert _apply(f, "CLEAR_DATA").applied


def test_inventory_api_preview_apply_round_trip(inventory_app):
    f = inventory_app
    root = "/api/rail-transit/ground-unattended/heartbeat/inventory"
    with TestClient(f.app) as client:
        preview = client.post(root + "/preview", json={"action": "SYNC"})
        assert preview.status_code == 200, preview.text
        applied = client.post(root + "/apply", json={
            "action": "SYNC", "revision": preview.json()["revision"], "confirm": True,
        })
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] is True
        assert client.get("/api/rail-transit/ground-unattended/heartbeat").json()["total_mrs"] == 2
    f.start.assert_not_called()
