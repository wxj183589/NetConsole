from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import closing

import pytest

from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.fleet_ping import FleetPingSupervisor, FleetPingTarget
from netconsole.services.ground_unattended.monitoring import ac_peer_intervals, indexed_evidence, mesh_evidence, monitoring_range
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_mesh_link import AcMeshMrPageDTO, AcMeshMrStatusDTO
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from fastapi.testclient import TestClient


def test_monitoring_range_requires_zone_and_caps_duration():
    start, end = monitoring_range("", "2026-11-07T12:00:00Z")
    assert (end - start).total_seconds() == 3600
    with pytest.raises(ValueError):
        monitoring_range("2026-11-07T11:00:00", "2026-11-07T12:00:00Z")
    with pytest.raises(ValueError):
        monitoring_range("2026-11-06T00:00:00Z", "2026-11-07T12:00:00Z")


def test_mesh_intervals_close_only_on_matching_adjacent_switches():
    start, end = monitoring_range("2026-11-07T11:00:00Z", "2026-11-07T12:00:00Z")
    base = {"event_type": "MESH_ACTIVELINK_SWITCH", "event_time_source": "DEVICE_TIME", "data_quality": "COMPLETE"}
    rows = [
        {**base, "id": 1, "device_time": "2026-11-07T11:10:00Z", "receive_time": "2026-11-07T11:10:01Z", "peer_mac": "00-11-22-33-44-55", "peer_name": "A", "rssi": -50},
        {**base, "id": 2, "device_time": "2026-11-07T11:10:20Z", "receive_time": "2026-11-07T11:10:21Z", "previous_peer_mac": "00:11:22:33:44:55", "peer_mac": "00:11:22:33:44:66", "peer_name": "B"},
        {**base, "id": 3, "device_time": "2026-11-07T11:11:00Z", "receive_time": "2026-11-07T11:11:01Z", "previous_peer_mac": "00:11:22:33:44:99", "peer_mac": "00:11:22:33:44:77"},
    ]
    events, intervals = mesh_evidence(rows, start, end)
    assert len(events) == 3
    assert len(intervals) == 1
    assert intervals[0]["end"] == "2026-11-07T11:10:20+00:00"


def test_ac_peer_intervals_are_sampled_bounded_and_yield_to_syslog():
    rows = [
        {"received_at": "2026-11-07T11:01:00Z", "peer_ap_mac": "00:11:22:33:44:55", "peer_ap_name": "A", "rssi": -50, "freshness_status": "fresh"},
        {"received_at": "2026-11-07T11:01:20Z", "peer_ap_mac": "00-11-22-33-44-55", "peer_ap_name": "A", "rssi": -51, "freshness_status": "recent"},
        {"received_at": "2026-11-07T11:01:25Z", "peer_ap_mac": "00:11:22:33:44:66", "peer_ap_name": "B", "freshness_status": "fresh"},
        {"received_at": "2026-11-07T11:01:50Z", "peer_ap_mac": "00:11:22:33:44:66", "peer_ap_name": "B", "freshness_status": "fresh"},
    ]
    result = ac_peer_intervals(rows, [{"start": "2026-11-07T11:01:05Z", "end": "2026-11-07T11:01:15Z"}])
    assert [(row["peer_name"], row["sampled_interval"]) for row in result] == [("B", True)]


def test_indexed_evidence_is_site_run_mr_scoped_and_read_only(tmp_path):
    path = tmp_path / "ground.sqlite"
    GroundUnattendedRepository(path, site_id="demo")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO ground_unattended_wmesh_events(site_id,run_id,device_uuid,event_type,event_family,device_time,receive_time,details_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     ("demo", "run-1", "mr-1", "MESH_ACTIVELINK_SWITCH", "WMESH", "2026-11-07T11:10:00Z", "2026-11-07T11:10:01Z", json.dumps({"rssi": -48}), "2026-11-07T11:10:01Z"))
        conn.execute("INSERT INTO ground_unattended_wmesh_events(site_id,run_id,device_uuid,event_type,event_family,receive_time,created_at) VALUES(?,?,?,?,?,?,?)",
                     ("other", "run-1", "mr-1", "MESH_ACTIVELINK_SWITCH", "WMESH", "2026-11-07T11:10:01Z", "2026-11-07T11:10:01Z"))
        conn.execute("INSERT INTO ground_unattended_ac_snapshots(snapshot_id,site_id,run_id,mr_id,received_at,peer_ap_mac,freshness_status) VALUES(?,?,?,?,?,?,?)",
                     ("ac-1", "demo", "run-1", "mr-1", "2026-11-07T11:10:00Z", "00:11:22:33:44:55", "fresh"))
        conn.commit()
    start, end = monitoring_range("2026-11-07T11:00:00Z", "2026-11-07T12:00:00Z")
    mesh, ac, truncated = indexed_evidence(path, site_id="demo", run_id="run-1", mr_uuid="mr-1", start=start, end=end)
    assert len(mesh) == len(ac) == 1 and not truncated
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO ground_unattended_ac_snapshots(snapshot_id,site_id,run_id,mr_id,received_at,peer_ap_mac,freshness_status) VALUES(?,?,?,?,?,?,?)",
                     ("ac-2", "demo", "run-2", "mr-1", "2026-11-07T11:11:00Z", "00:11:22:33:44:66", "fresh"))
        conn.commit()
    _, resident_ac, _ = indexed_evidence(path, site_id="demo", run_id=None, mr_uuid="mr-1", start=start, end=end)
    assert {row["snapshot_id"] for row in resident_ac} == {"ac-1", "ac-2"}
    _, old_ac, _ = indexed_evidence(path, site_id="demo", run_id="run-1", mr_uuid="mr-1", start=start, end=end)
    assert [row["snapshot_id"] for row in old_ac] == ["ac-1"]
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ground_unattended_wmesh_events").fetchone()[0] == 2


def test_evidence_filters_offsets_and_time_window_before_limiting(tmp_path):
    path = tmp_path / "ground.sqlite"
    GroundUnattendedRepository(path, site_id="demo")
    with closing(sqlite3.connect(path)) as conn:
        stamps = ["2026-11-07T19:10:00+08:00"] + ["2026-11-07T13:00:00Z"] * 501
        for index, stamp in enumerate(stamps):
            conn.execute("INSERT INTO ground_unattended_wmesh_events(site_id,run_id,device_uuid,event_type,event_family,receive_time,created_at) VALUES(?,?,?,?,?,?,?)",
                         ("demo", "run-1", "mr-1", "MESH_ACTIVELINK_SWITCH", "WMESH", stamp, stamp))
            conn.execute("INSERT INTO ground_unattended_ac_snapshots(snapshot_id,site_id,run_id,mr_id,received_at,peer_ap_mac,freshness_status) VALUES(?,?,?,?,?,?,?)",
                         (f"ac-{index}", "demo", "run-1", "mr-1", stamp, "00:11:22:33:44:55", "fresh"))
        conn.commit()
    start, end = monitoring_range("2026-11-07T11:00:00Z", "2026-11-07T12:00:00Z")
    mesh, ac, truncated = indexed_evidence(path, site_id="demo", run_id="run-1", mr_uuid="mr-1", start=start, end=end)
    assert len(mesh) == len(ac) == 1
    assert ac[0]["snapshot_id"] == "ac-0"
    assert not truncated
    start, end = monitoring_range("2026-11-07T12:00:00Z", "2026-11-07T14:00:00Z")
    mesh, ac, truncated = indexed_evidence(path, site_id="demo", run_id="run-1", mr_uuid="mr-1", start=start, end=end)
    assert len(mesh) == len(ac) == 500 and truncated


def test_latest_rtt_is_fresh_and_current_run_only():
    fleet = FleetPingSupervisor(repository=object(), site_id="demo")
    fleet._run_id = "current"
    fleet._targets = {"192.0.2.1": FleetPingTarget("192.0.2.1", "train", "001", "mr-1", "CT")}
    fleet._latest_samples = {"192.0.2.1": (datetime.now(timezone.utc).isoformat(), 4.2)}
    assert fleet.latest_mr_rtts("other") == {}
    assert fleet.latest_mr_rtts("current") == {"mr-1": 4.2}
    fleet._latest_samples["192.0.2.1"] = ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), 4.2)
    assert fleet.latest_mr_rtts("current") == {}


def test_heartbeat_filters_before_paging_and_uses_resolved_body_identity(tmp_path, monkeypatch):
    app = create_app(paths=PathResolver(tmp_path / "app", tmp_path / "data"))
    repository = app.state.ground_unattended_repository
    repository.create_or_get_run(run_id="run-monitor", run_date="2026-11-07", scheduled_start_at="2026-11-07T00:00:00Z", scheduled_end_at="2026-11-07T23:00:00Z")
    repository.update_run("run-monitor", state="COMPLETED")
    for number in (10, 2, 1):
        repository.upsert_heartbeat_snapshot("run-monitor", {"mr_uuid": f"mr-{number}", "train_id": f"T{number}", "role": "CT", "status": "OFFLINE", "engine_state": "STOPPED", "ip_states": [{"ip": f"192.0.2.{number}"}]}, entity_type="MR", entity_id=f"mr-{number}")
    monkeypatch.setattr(AcMeshLinkQueryService, "list_mrs", lambda *_args, **_kwargs: AcMeshMrPageDTO(items=[
        AcMeshMrStatusDTO(mr_id=f"mr-{number}", mr_device_id=f"mr-{number}", resolved_ap=f"BODY-{number}", resolved_ap_station="Station", resolved_ap_section="Section", identity_status="matched", data_status="stale", station="WRONG PEER STATION") for number in (1, 2, 10)
    ], total=3))
    with TestClient(app) as client:
        page = client.get("/api/rail-transit/ground-unattended/heartbeat", params={"run_id": "run-monitor", "query": "BODY-10", "page_size": 1}).json()
        assert page["total"] == 1 and page["total_mrs"] == 3
        assert page["mrs"][0]["resolved_ap_name"] == "BODY-10"
        assert page["mrs"][0]["station"] == "Station"
        assert page["mrs"][0]["status"] == "OFFLINE"
        assert page["mrs"][0]["current_rtt_ms"] is None
        by_ip = client.get("/api/rail-transit/ground-unattended/heartbeat", params={"run_id": "run-monitor", "query": "192.0.2.2"}).json()
        assert by_ip["total"] == 1
        missing = client.get("/api/rail-transit/ground-unattended/mr/absent/monitoring", params={"run_id": "run-monitor"})
        assert missing.status_code == 422


def test_monitoring_windows_count_actual_samples_without_warmup_or_downsample_loss(tmp_path):
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    repository.create_or_get_run(run_id="run-window", run_date="2026-11-07", scheduled_start_at="2026-11-07T00:00:00Z", scheduled_end_at="2026-11-07T23:00:00Z")
    repository.update_run("run-window", state="COMPLETED")
    repository.upsert_heartbeat_snapshot("run-window", {"mr_uuid": "mr-1", "train_id": "T1", "role": "CT", "status": "OFFLINE", "engine_state": "STOPPED", "ip_states": [{"ip": "192.0.2.1", "sent_count": 9, "lost_count": 1}]}, entity_type="MR", entity_id="mr-1")
    root = repository.db_path.parent
    path = root / "fixture-ping.ndjson"
    end = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    samples = [
        {"ts": (end - timedelta(seconds=seconds)).isoformat(), "mr_id": "mr-1", "train_id": "T1", "target_ip": "192.0.2.1", "seq": index, "ok": ok, "rtt_ms": 3 if ok else None, "warmup_ignored": ignored}
        for index, (seconds, ok, ignored) in enumerate([(1, False, False), (2, True, False), (3, False, True), (100, True, False), (700, True, False), (1900, True, False)])
    ]
    path.write_text("\n".join(json.dumps(item) for item in samples) + "\n", encoding="utf-8")
    repository.upsert_raw_file({"file_id": "raw-monitor", "run_id": "run-window", "train_id": "T1", "device_uuid": "mr-1", "mr_role": "CT", "data_type": "ping", "relative_path": "fixture-ping.ndjson", "start_time": "2026-11-07T11:00:00Z", "end_time": end.isoformat(), "record_count": len(samples), "size_bytes": path.stat().st_size, "status": "CLOSED"})
    with TestClient(app) as client:
        response = client.get("/api/rail-transit/ground-unattended/mr/mr-1/monitoring", params={"run_id": "run-window", "start_time": "2026-11-07T11:59:00Z", "end_time": end.isoformat()})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["series"]["window_statistics"]["1"] == {"sent_count": 2, "lost_count": 1, "loss_rate_percent": 50.0}
    assert payload["series"]["window_statistics"]["10"]["sent_count"] == 3
    assert payload["series"]["window_statistics"]["30"]["sent_count"] == 4
    assert payload["series"]["window_statistics"]["60"]["sent_count"] == 5
    assert payload["run_sent_count"] == 9 and payload["run_lost_count"] == 1
