from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_mesh_link import AcMeshLinkRecordDTO, AcMeshMrPageDTO, AcMeshMrStatusDTO
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


def test_heartbeat_projects_multiple_real_mesh_aps_and_stations(inventory_app, monkeypatch):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    mr_uuid = str(f.devices[0].device_uuid)
    monkeypatch.setattr(AcMeshLinkQueryService, "list_mrs", lambda *_args, **_kwargs: AcMeshMrPageDTO(items=[
        AcMeshMrStatusDTO(
            mr_id=mr_uuid,
            mr_device_id=mr_uuid,
            peer_aps=[
                AcMeshLinkRecordDTO(
                    id=1, snapshot_id=1, mr_id=mr_uuid, peer_ap_name="AP-01",
                    peer_ap_mac="aa-bb-cc-dd-ee-01", bssid="aa:bb:cc:dd:ee:11",
                    rssi=-48, station="杭州南站", section="南站-区间1", mr_online_status="online",
                    last_seen_at="2026-11-07T10:00:00+00:00",
                ),
                AcMeshLinkRecordDTO(
                    id=2, snapshot_id=1, mr_id=mr_uuid, peer_ap_name="AP-02",
                    peer_ap_mac="aa-bb-cc-dd-ee-02", bssid="aa:bb:cc:dd:ee:22",
                    rssi=-55, station="杭州东站", section="区间2", mr_online_status="online",
                    last_seen_at="2026-11-07T10:00:01+00:00",
                ),
            ],
        ),
    ]))

    page = f.service.heartbeat(site)
    mr = next(item for item in page.mrs if item.mr_uuid == mr_uuid)

    assert [item.name for item in mr.associated_aps] == ["AP-01", "AP-02"]
    assert [item.bssid for item in mr.associated_aps] == ["aa:bb:cc:dd:ee:11", "aa:bb:cc:dd:ee:22"]
    assert mr.associated_stations == ["杭州东站", "杭州南站"]


def test_heartbeat_keeps_21_train_42_mr_inventory_before_sampling(inventory_app):
    f = inventory_app
    rows = []
    for train_index in range(1, 22):
        for role in ("CT", "CW"):
            device = f.assets.create(Device(
                name=f"T{train_index:02d}-{role}",
                primary_address=f"198.51.100.{len(rows) + 1}",
            ))
            rows.append(VehicleMrDTO(
                id=str(device.device_uuid), device_id=device.id, name=device.name,
                management_ip=device.primary_address, train_id=f"train-{train_index:02d}",
                train_no=f"{train_index:02d}", mr_position_code=role,
            ))
    f.service.inventory_sync.base_query = SimpleNamespace(list_mesh_import_context_mrs=lambda _site: rows)

    page = f.service.heartbeat(f.service.site_id)

    assert page.inventory_train_count == 21
    assert page.inventory_mr_count == 42
    assert page.total == 21
    assert page.total_mrs == 42
    assert {mr.status for mr in page.mrs} == {"UNKNOWN"}


def test_selected_run_without_heartbeat_samples_keeps_inventory_visible(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    _run(f.repository, run_id="empty-run", state="COMPLETED")

    page = f.service.heartbeat(site, run_id="empty-run")

    assert page.run_id == "empty-run"
    assert page.data_state == "STOPPED"
    assert page.inventory_train_count == 1
    assert page.inventory_mr_count == 2
    assert page.total == 1 and page.total_mrs == 2
    assert {mr.status for mr in page.mrs} == {"UNKNOWN"}
    assert page.heartbeat_statistics.sent_count == 0


def test_default_page_retains_stopped_samples_and_current_inventory(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    _run(f.repository, run_id="stopped-run", state="COMPLETED")
    mr = f.source.rows[0]
    f.repository.upsert_heartbeat_snapshot("stopped-run", {
        "mr_uuid": mr.id, "train_id": mr.train_id, "role": "CT", "status": "ONLINE",
        "ip_states": [{"ip": mr.management_ip, "sent_count": 7, "received_count": 6,
                       "lost_count": 1, "avg_rtt_ms": 2.5}],
    }, entity_type="MR", entity_id=mr.id)
    cw = f.source.rows[1]
    f.repository.upsert_heartbeat_snapshot("stopped-run", {
        "mr_uuid": cw.id, "train_id": cw.train_id, "role": "CW", "status": "UNKNOWN",
        "ip_states": [{"ip": cw.management_ip}],
    }, entity_type="MR", entity_id=cw.id)
    page = f.service.heartbeat(site)
    assert page.run_id == "stopped-run" and page.data_state == "STOPPED"
    assert (page.total, page.total_mrs) == (1, 2)
    assert (page.heartbeat_statistics.sent_count, page.heartbeat_statistics.success_count,
            page.heartbeat_statistics.lost_count) == (7, 6, 1)
    f.source.rows = f.source.rows[:1]
    current = f.service.heartbeat(site)
    assert current.total_mrs == 1 and current.mrs[0].mr_uuid == mr.id
    assert f.service.heartbeat(site, run_id="stopped-run").total_mrs == 2
    _apply(f, "CLEAR_DATA")
    cleared = f.service.heartbeat(site)
    assert cleared.total_mrs == 1 and cleared.heartbeat_statistics.sent_count == 0
    f.start.assert_not_called()


def test_heartbeat_page_aggregates_real_ping_statistics(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    _run(f.repository, run_id="stats-run", state="RUNNING")
    sample_at = datetime.now(timezone.utc).replace(microsecond=0)
    f.repository.upsert_heartbeat_snapshot("stats-run", {
        "mr_uuid": str(f.devices[0].device_uuid), "train_id": "train-01", "role": "CT", "status": "ONLINE",
        "ip_states": [{"ip": "192.0.2.1", "sent_count": 4, "received_count": 3, "lost_count": 1, "avg_rtt_ms": 4.0, "last_probe_at": (sample_at - timedelta(seconds=1)).isoformat()}],
    }, entity_type="MR", entity_id=str(f.devices[0].device_uuid))
    f.repository.upsert_heartbeat_snapshot("stats-run", {
        "mr_uuid": str(f.devices[1].device_uuid), "train_id": "train-01", "role": "CW", "status": "ONLINE",
        "ip_states": [{"ip": "192.0.2.2", "sent_count": 2, "received_count": 2, "lost_count": 0, "avg_rtt_ms": 2.0, "last_probe_at": sample_at.isoformat()}],
    }, entity_type="MR", entity_id=str(f.devices[1].device_uuid))

    page = f.service.heartbeat(site, run_id="stats-run")

    assert page.data_state == "RUNNING"
    assert page.heartbeat_statistics.sent_count == 6
    assert page.heartbeat_statistics.success_count == 5
    assert page.heartbeat_statistics.lost_count == 1
    assert page.heartbeat_statistics.average_rtt_ms == pytest.approx(3.2)
    assert page.heartbeat_statistics.loss_rate_percent == pytest.approx(100 / 6)
    assert page.heartbeat_statistics.latest_sample_at == sample_at.isoformat()


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
    disabled_page = f.service.heartbeat(f.service.site_id)
    assert len(disabled_page.mrs) == 2
    assert disabled_page.data_state == "DISABLED"
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


def test_clear_hides_old_loss_episodes_without_deleting_shared_history(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    _run(f.repository)
    mr = f.source.rows[0]
    before = datetime.now(timezone.utc) - timedelta(seconds=10)
    event = {
        "event_key": "before-clear", "run_id": "run-1", "mr_id": mr.id,
        "target_ip": mr.management_ip, "started_at": before.isoformat(),
        "ap_name": "original-ap", "station": "original-station", "loss_count": 2,
    }
    f.repository.apply_ping_loss_events([event])
    assert f.service.heartbeat(site, mr_uuid=mr.id).mrs[0].loss_events
    _apply(f, "CLEAR_DATA")
    assert f.service.heartbeat(site, mr_uuid=mr.id).mrs[0].loss_events == []
    assert f.service.mr_monitoring(site, mr_uuid=mr.id).loss_events == []
    after = datetime.now(timezone.utc) + timedelta(seconds=1)
    f.repository.apply_ping_loss_events([{**event, "event_key": "after-clear",
                                         "started_at": after.isoformat()}])
    page = f.service.heartbeat(site, mr_uuid=mr.id)
    detail = f.service.mr_monitoring(site, mr_uuid=mr.id)
    assert [row["event_key"] for row in page.mrs[0].loss_events] == ["after-clear"]
    assert [row["event_key"] for row in detail.loss_events] == ["after-clear"]
    history = f.repository.list_ping_loss_intervals("run-1")
    assert len(history) == 2
    assert all(row["ap_name"] == "original-ap" and row["station"] == "original-station" for row in history)


def test_clear_restart_does_not_restore_old_open_loss_episode(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    run = _run(f.repository)
    supervisor = f.service.supervisor
    supervisor.fleet_ping.start = Mock()
    mr = f.source.rows[0]
    before = datetime.now(timezone.utc) - timedelta(seconds=10)
    f.repository.apply_ping_loss_events([{
        "event_key": "before-clear", "run_id": run["run_id"], "mr_id": mr.id,
        "target_ip": mr.management_ip, "started_at": before.isoformat(),
        "ap_name": "original-ap", "station": "original-station", "loss_count": 2,
    }])
    original = f.repository.list_open_ping_loss_intervals(run["run_id"])[0]
    profile = f.repository.get_profile()
    supervisor._start_fleet_ping(run, profile)
    supervisor._quiesce_heartbeat()
    _apply(f, "CLEAR_DATA")
    supervisor._start_fleet_ping(run, profile)
    target = supervisor._heartbeat_fleet_targets()[mr.management_ip]
    after = datetime.now(timezone.utc) + timedelta(seconds=1)
    supervisor._queue_heartbeat_loss_sample(target, SimpleNamespace(ok=False), after)
    supervisor._quiesce_heartbeat()
    visible = next(row for row in f.service.heartbeat(site, mr_uuid=mr.id).mrs
                   if row.mr_uuid == mr.id).loss_events
    assert len(visible) == 1
    assert visible[0]["event_key"] != "before-clear"
    new_key = visible[0]["event_key"]
    # Reopen durable storage and rebuild trackers, as after a Backend restart.
    supervisor.repository = GroundUnattendedRepository(f.repository.db_path, site_id=site)
    supervisor._heartbeat_loss_trackers.clear()
    supervisor._start_fleet_ping(run, profile)
    tracker = supervisor._heartbeat_loss_trackers[f"heartbeat:{mr.id}:{mr.management_ip}"]
    assert tracker.state["event_key"] == new_key
    supervisor._queue_heartbeat_loss_sample(target, SimpleNamespace(ok=True), after + timedelta(seconds=1))
    supervisor._quiesce_heartbeat()
    history = f.repository.list_ping_loss_intervals(run["run_id"])
    assert next(row for row in history if row["event_key"] == "before-clear") == original
    assert next(row for row in history if row["event_key"] == new_key)["state"] == "RECOVERED"


def test_clear_then_restart_same_daily_run_does_not_resurrect_memory_counters(inventory_app):
    f = inventory_app
    site = f.service.site_id
    f.service.heartbeat(site)
    run = _run(f.repository)
    supervisor = f.service.supervisor
    supervisor.fleet_ping.start = Mock()  # Lifecycle regression uses no network probes.
    profile = f.repository.get_profile()
    mr = f.source.rows[0]
    supervisor._start_fleet_ping(run, profile)
    supervisor._heartbeat_engine.record_cycle(mr.id, {mr.management_ip: (True, 2.0)})
    supervisor._quiesce_heartbeat()
    assert f.service.heartbeat(site).heartbeat_statistics.sent_count == 1
    f.repository.upsert_ping_summary({
        "site_id": site, "run_id": run["run_id"], "bucket_kind": "daily",
        "bucket_start": "2026-11-07T00:00:00Z", "bucket_end": "2026-11-08T00:00:00Z",
        "created_at": "2026-11-07T00:00:00Z", "sent_count": 100,
    })
    shared = f.repository.list_ping_summaries(run["run_id"])
    _apply(f, "CLEAR_DATA")
    supervisor._start_fleet_ping(run, profile)
    assert supervisor._heartbeat_engine.snapshot(mr.id).ip_states[0].sent_count == 0
    supervisor._heartbeat_engine.record_cycle(mr.id, {mr.management_ip: (True, 3.0)})
    supervisor._quiesce_heartbeat()
    page = f.service.heartbeat(site)
    assert page.total_mrs == 2 and page.heartbeat_statistics.sent_count == 1
    supervisor._start_fleet_ping(run, profile)
    assert supervisor._heartbeat_engine.snapshot(mr.id).ip_states[0].sent_count == 1
    assert f.repository.list_ping_summaries(run["run_id"]) == shared


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
