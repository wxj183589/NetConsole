from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import sqlite3

import pytest

from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.services.ground_unattended.fleet_ping import FleetPingSupervisor
from netconsole.services.ground_unattended.heartbeat_supervisor import HEARTBEAT_STREAM_ID

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import RailTransitSummaryDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
    GroundUnattendedError,
)
from netconsole.services.ground_unattended.supervisor import (
    GroundUnattendedSupervisor,
)


class _BaseQuery:
    def get_summary(self, site_id):
        return RailTransitSummaryDTO(site_id=site_id, site_name=site_id)

    def list_mrs(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_stations(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_sections(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_ap_location_items(self, *_args, **_kwargs):
        return []


class _MeshQuery:
    def __init__(self) -> None:
        self.snapshots = [
            self._snapshot(11, "ac-1"),
            self._snapshot(21, "ac-2"),
        ]
        self.snapshot_row_calls: list[int] = []

    @staticmethod
    def _snapshot(snapshot_id: int, controller_id: str):
        return SimpleNamespace(
            id=snapshot_id,
            controller_id=controller_id,
            controller_name=controller_id,
            collected_at=f"2026-07-29T08:00:{snapshot_id % 60:02d}+08:00",
            ac_time="2026-07-29T08:00:00+08:00",
            data_status="fresh",
            source_reference=f"snapshot:{snapshot_id}",
        )

    def list_latest_snapshots_by_controller(self, _site_id):
        return list(self.snapshots)

    def list_mrs_for_snapshot(self, _site_id, snapshot_id):
        self.snapshot_row_calls.append(snapshot_id)
        return [
            SimpleNamespace(
                train_no=f"train-{snapshot_id}",
                mr_device_id=f"mr-{snapshot_id}",
                mr_id=f"mr-{snapshot_id}",
                mr_name=f"MR {snapshot_id}",
                car_end="CT",
                management_ip="",
                online_status="online",
                peer_ap_id="",
                peer_ap_name=f"ap-{snapshot_id}",
                peer_ap_mac=f"00:00:00:00:00:{snapshot_id % 100:02d}",
                station="",
                section="",
                mileage="",
                rssi=-60,
                data_status="fresh",
                last_seen_at=f"2026-07-29T08:00:{snapshot_id % 60:02d}+08:00",
            )
        ]


class _VehicleQuery:
    def list_controllers(self, *_args, **_kwargs):
        return []


def _supervisor(
    tmp_path: Path,
) -> tuple[GroundUnattendedSupervisor, GroundUnattendedRepository, _MeshQuery]:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True, exist_ok=True)
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"),
        site_id="site-a",
    )
    run = repository.create_or_get_run(
        run_id="run-1",
        run_date="2026-07-29",
        scheduled_start_at="2026-07-29T07:00:00+08:00",
        scheduled_end_at="2026-07-29T23:00:00+08:00",
    )
    repository.update_run(str(run["run_id"]), state="RUNNING")
    mesh = _MeshQuery()
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repository,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=mesh,  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
    )
    return supervisor, repository, mesh


def _heartbeat_fixture(tmp_path: Path):
    supervisor, repository, mesh = _supervisor(tmp_path)
    repository.sync_inventory(
        trains=[{"train_id": "heartbeat-train", "train_no": "001"}],
        endpoints=[{
            "device_uuid": "heartbeat-mr", "train_id": "heartbeat-train",
            "mr_role": "CT", "device_name": "Mock CT",
            "management_ip": "192.0.2.10", "backup_management_ip": "192.0.2.11",
        }],
    )

    def runner(*, targets, stop_event, **kwargs):
        sequence = 0
        while not stop_event.wait(0.01):
            sequence += 1
            for target in targets:
                yield FpingV5Sample(
                    ts=datetime.now().astimezone().isoformat(), target=target,
                    seq=sequence, ok=True, rtt_ms=2.0,
                    timeout_ms=kwargs["timeout_ms"], size=kwargs["packet_size"],
                    error="", backend=BACKEND, raw_type="response", raw={},
                )

    supervisor.heartbeat.fleet_ping = supervisor.fleet_ping = FleetPingSupervisor(
        repository=repository, site_id="site-a", runner=runner,
        sample_callback=supervisor.heartbeat._on_fleet_ping_sample,
    )
    supervisor.heartbeat._inventory_refresh_at = float("inf")
    supervisor.heartbeat.tick_seconds = 0.05
    supervisor.heartbeat._tick()
    supervisor.heartbeat.start()
    return supervisor, repository, mesh


def test_busy_heartbeat_population_persists_every_mr_and_train(tmp_path, monkeypatch):
    supervisor, repository, _ = _supervisor(tmp_path)
    ids = [f"mr-{index:03d}" for index in range(300)]
    repository.sync_inventory(
        trains=[{"train_id": item, "train_no": item} for item in ids],
        endpoints=[{"device_uuid": item, "train_id": item, "mr_role": "CT",
                    "management_ip": f"192.0.{index // 250 + 2}.{index % 250 + 1}"}
                   for index, item in enumerate(ids)],
    )
    supervisor.heartbeat._configure_heartbeat_targets("run-1")
    stored = {"MR": set(), "TRAIN": set()}

    def persist(_run_id, records, **_kwargs):
        for record in records:
            stored[record["entity_type"]].add(record["entity_id"])

    monkeypatch.setattr(repository, "upsert_heartbeat_snapshots", persist)
    now = datetime.now().astimezone()
    supervisor.heartbeat._refresh_train_heartbeat_snapshots_locked(
        [supervisor.heartbeat._heartbeat_engine.snapshot(item) for item in ids], at=now,
    )
    for _ in range(10):
        # Every probe can dirty the early IDs again before the next scheduler tick.
        supervisor.heartbeat._heartbeat_dirty_mrs.update(ids)
        supervisor.heartbeat._heartbeat_dirty_trains.update(ids)
        supervisor.heartbeat._persist_heartbeat_state(at=now)
    assert stored == {"MR": set(ids), "TRAIN": set(ids)}


@pytest.mark.parametrize("snapshot_available", [True, False])
def test_poll_between_ac_snapshots_preserves_fresh_matching_enrichment(tmp_path, snapshot_available, monkeypatch):
    supervisor, repository, mesh = _supervisor(tmp_path)
    # This regression exercises target enrichment only; never launch network workers.
    monkeypatch.setattr(supervisor.fleet_ping, "_reconcile_shards", lambda _addresses: None)
    repository.sync_inventory(
        trains=[{"train_id": "train-1", "train_no": "001"}],
        endpoints=[{"device_uuid": "mr-1", "train_id": "train-1", "mr_role": "CT",
                    "management_ip": "192.0.2.10"}],
    )
    now = datetime.now().astimezone()
    inventory = supervisor.heartbeat._refresh_inventory_heartbeat(repository.get_run("run-1"), now)
    address = "192.0.2.10"
    enriched = replace(inventory[address], current_ap_identity="ap-a", current_ap_name="AP A",
                       ac_snapshot_id="snapshot-a", rssi=-51)
    supervisor._last_valid_ping_targets[address] = (enriched, now)
    supervisor._last_processed_snapshot_id_by_controller = {"ac-1": 11, "ac-2": 21}
    if not snapshot_available:
        mesh.snapshots = []
    supervisor._poll_ac_and_classify(repository.get_run("run-1"), repository.get_profile(),
                                     now + timedelta(seconds=1), scheduling_paused=False)
    assert supervisor.heartbeat._enrichment[address] == enriched
    supervisor._poll_ac_and_classify(repository.get_run("run-1"), repository.get_profile(),
                                     now + timedelta(seconds=repository.get_profile().ac_stale_grace_seconds + 1),
                                     scheduling_paused=False)
    assert not supervisor.heartbeat._enrichment[address].current_ap_identity
    assert supervisor.heartbeat._enrichment[address].mr_id == "mr-1"


def _wait_samples(supervisor, minimum: int) -> None:
    deadline = time.monotonic() + 5
    while supervisor.fleet_ping.sample_count < minimum and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert supervisor.fleet_ping.sample_count >= minimum


def test_heartbeat_events_defer_database_io_and_retry_without_losing_transition(tmp_path, monkeypatch):
    from netconsole.services.ground_unattended.heartbeat_state import HeartbeatIpObservation

    supervisor, repository, _ = _supervisor(tmp_path)
    repository.sync_inventory(
        trains=[{"train_id": "train-1", "train_no": "001"}],
        endpoints=[{"device_uuid": "mr-1", "train_id": "train-1", "mr_role": "CT",
                    "management_ip": "192.0.2.10"}],
    )
    supervisor.heartbeat._configure_heartbeat_targets("run-1")
    original_single = repository.add_event
    original_batch = repository.add_events_batch
    writes = []

    def locked(*args, **kwargs):
        writes.append(1)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(repository, "add_event", locked)
    monkeypatch.setattr(repository, "add_events_batch", locked)
    at = datetime.now().astimezone()
    # Probe callback must finish state/aggregate updates without any SQLite IO.
    with supervisor.heartbeat._heartbeat_lock:
        for second in range(11):
            moment = at + timedelta(seconds=second)
            transitions = supervisor.heartbeat._heartbeat_engine.record_observation(
                "mr-1", HeartbeatIpObservation("192.0.2.10", False), at=moment,
            )
            supervisor.heartbeat._heartbeat_dirty_mrs.add("mr-1")
            supervisor.heartbeat._mark_heartbeat_transitions_dirty(transitions)
            supervisor.heartbeat._refresh_train_heartbeat_snapshots_locked(
                (supervisor.heartbeat._heartbeat_engine.snapshot("mr-1"),), at=moment,
            )
    assert not writes
    assert supervisor.heartbeat._heartbeat_engine.snapshot("mr-1").status == "OFFLINE"
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        supervisor.heartbeat._persist_heartbeat_state(at=moment)
    monkeypatch.setattr(repository, "add_event", original_single)
    monkeypatch.setattr(repository, "add_events_batch", original_batch)
    supervisor.heartbeat._persist_heartbeat_state(at=moment)
    supervisor.heartbeat._persist_heartbeat_state(at=moment)
    events = repository.list_events("run-1", event_type="mr_offline")
    assert len(events) == 1
    assert datetime.fromisoformat(events[0]["ts"]) == moment.replace(microsecond=moment.microsecond // 1000 * 1000)
    assert not supervisor.heartbeat._heartbeat_pending_events


def test_slow_heartbeat_event_store_keeps_sampling_lock_free_and_run_ownership(tmp_path, monkeypatch):
    from netconsole.services.ground_unattended.heartbeat_state import HeartbeatTransition

    supervisor, repository, _ = _supervisor(tmp_path)
    supervisor.heartbeat._heartbeat_run_id = "run-1"
    at = datetime.now().astimezone()
    supervisor.heartbeat._on_heartbeat_transition(HeartbeatTransition(
        "MR", "mr-1", "ONLINE", "OFFLINE", "mr_offline", at,
    ))
    entered, release = threading.Event(), threading.Event()
    original = repository.add_events_batch
    failures = []

    def slow_store(records):
        entered.set()
        assert release.wait(5)
        return original(records)

    def flush():
        try:
            supervisor.heartbeat._persist_heartbeat_events()
        except Exception as exc:
            failures.append(exc)

    monkeypatch.setattr(repository, "add_events_batch", slow_store)
    worker = threading.Thread(target=flush)
    worker.start()
    try:
        assert entered.wait(3)
        acquired = supervisor.heartbeat._heartbeat_lock.acquire(timeout=1)
        assert acquired, "slow SQLite must not own the sampling lock"
        try:
            supervisor.heartbeat._heartbeat_run_id = "run-2"
            supervisor.heartbeat._on_heartbeat_transition(HeartbeatTransition(
                "MR", "mr-2", "ONLINE", "OFFLINE", "mr_offline", at,
            ))
        finally:
            supervisor.heartbeat._heartbeat_lock.release()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert not failures
    monkeypatch.setattr(repository, "add_events_batch", original)
    supervisor.heartbeat._persist_heartbeat_events()
    assert [item["mr_id"] for item in repository.list_events("run-1", event_type="mr_offline")] == ["mr-1"]
    assert [item["mr_id"] for item in repository.list_events("run-2", event_type="mr_offline")] == ["mr-2"]
    assert not supervisor.heartbeat._heartbeat_pending_events


def test_heartbeat_without_ac_or_credentials_persists_both_ip_stats(tmp_path: Path) -> None:
    supervisor, repository, mesh = _heartbeat_fixture(tmp_path)
    mesh.snapshots = []
    try:
        _wait_samples(supervisor, 8)
        supervisor._poll_ac_and_classify(
            repository.get_run("run-1"), repository.get_profile(),
            datetime.now().astimezone(), scheduling_paused=True,
        )
        service = GroundUnattendedApplicationService(
            supervisor.paths, site_id="site-a", repository=repository, supervisor=supervisor,
        )
        supervisor.heartbeat._persist_heartbeat_state(at=datetime.now().astimezone())
        page = service.heartbeat("site-a")
        assert page.mr_counts["ONLINE"] == 1
        assert page.train_counts["SINGLE_ONLINE"] == 1
        assert page.mrs[0].mr_name == "Mock CT"
        assert {row.ip for row in page.mrs[0].ip_states} == {"192.0.2.10", "192.0.2.11"}
        assert all(row.received_count > 0 for row in page.mrs[0].ip_states)
        assert not repository.list_events("run-1", event_type="mr_offline")
    finally:
        supervisor.heartbeat.close()


def test_slow_ac_query_does_not_block_fleet_heartbeat(tmp_path: Path) -> None:
    supervisor, repository, mesh = _heartbeat_fixture(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def delayed_query(_site_id):
        entered.set()
        assert release.wait(40)
        return []

    mesh.list_latest_snapshots_by_controller = delayed_query
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                supervisor._poll_ac_and_classify, repository.get_run("run-1"),
                repository.get_profile(), datetime.now().astimezone(), scheduling_paused=False,
            )
            try:
                assert entered.wait(2)
                initial = supervisor.fleet_ping.sample_count
                time.sleep(30.0)
                _wait_samples(supervisor, initial + 20)
                assert not pending.done()
                assert supervisor.heartbeat._heartbeat_engine.snapshot("heartbeat-mr").status == "ONLINE"
            finally:
                release.set()
            pending.result(timeout=5)
        assert not repository.list_events("run-1", event_type="mr_offline")
    finally:
        release.set()
        supervisor.heartbeat.close()


def test_repeated_deep_scheduler_failure_keeps_heartbeat_running_and_recovers(tmp_path: Path) -> None:
    supervisor, repository, mesh = _heartbeat_fixture(tmp_path)
    failing = [True]

    def deep_tick(*_args, **_kwargs):
        if failing[0]:
            raise RuntimeError("mock SSH deep collection failure")

    supervisor.deep_scheduler = SimpleNamespace(tick=deep_tick, stop_all=lambda *_args, **_kwargs: None)
    try:
        _wait_samples(supervisor, 4)
        for iteration in range(4):
            mesh.snapshots = [mesh._snapshot(30 + iteration, "ac-1")]
            supervisor._poll_ac_and_classify(
                repository.get_run("run-1"), repository.get_profile(),
                datetime.now().astimezone(), scheduling_paused=False,
            )
        initial = supervisor.fleet_ping.sample_count
        _wait_samples(supervisor, initial + 12)
        assert repository.get_run("run-1")["state"] == "RUNNING"
        assert supervisor.heartbeat._heartbeat_engine.snapshot("heartbeat-mr").status == "ONLINE"
        assert len(repository.list_events("run-1", event_type="deep_scheduler_failed")) == 1
        assert not repository.list_events("run-1", event_type="mr_offline")
        failing[0] = False
        mesh.snapshots = [mesh._snapshot(40, "ac-1")]
        supervisor._poll_ac_and_classify(
            repository.get_run("run-1"), repository.get_profile(),
            datetime.now().astimezone(), scheduling_paused=False,
        )
        assert supervisor._deep_scheduler_error == ""
        with repository._connection() as connection:
            codes = {row["code"] for row in connection.execute(
                "SELECT code FROM ground_unattended_health_events WHERE run_id=?", ("run-1",)
            )}
        assert {"DEEP_SCHEDULER_FAILED", "DEEP_SCHEDULER_RECOVERED"} <= codes
    finally:
        supervisor.heartbeat.close()


def test_critical_disk_space_pauses_deep_collection_but_keeps_heartbeat_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor, repository, mesh = _heartbeat_fixture(tmp_path)
    profile = repository.get_profile().model_copy(update={
        "deep_collection_master_enabled": True,
        "storage_warning_free_gb": 4,
        "storage_critical_free_gb": 2,
    })
    free_bytes = [1024**3]
    stop_calls: list[tuple[str, dict]] = []
    paused_ticks: list[bool] = []

    def stop_deep(run_id, **kwargs):
        stop_calls.append((run_id, kwargs))

    def tick_deep(_run_id, _profile, _trains, *, paused):
        paused_ticks.append(paused)

    supervisor.deep_scheduler = SimpleNamespace(tick=tick_deep, stop_all=stop_deep)
    monkeypatch.setattr(
        "netconsole.services.ground_unattended.supervisor.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=free_bytes[0]),
    )
    try:
        _wait_samples(supervisor, 4)
        supervisor._poll_ac_and_classify(
            repository.get_run("run-1"), profile,
            datetime.now().astimezone(), scheduling_paused=False,
        )
        assert stop_calls == [("run-1", {
            "reason": "critical_disk_space",
            "max_finalizing_mrs": profile.max_finalizing_mrs,
        })]
        # Paused ticks allow finalization while preventing new deep collectors.
        assert paused_ticks == [True]
        initial = supervisor.fleet_ping.sample_count
        _wait_samples(supervisor, initial + 12)
        assert supervisor.heartbeat._heartbeat_engine.snapshot("heartbeat-mr").status == "ONLINE"
        assert repository.get_run("run-1")["state"] == "RUNNING"
        assert not repository.list_events("run-1", event_type="mr_offline")

        free_bytes[0] = 8 * 1024**3
        mesh.snapshots = [mesh._snapshot(40, "ac-1")]
        supervisor._poll_ac_and_classify(
            repository.get_run("run-1"), profile,
            datetime.now().astimezone(), scheduling_paused=False,
        )
        assert paused_ticks == [True, False]
        assert len(stop_calls) == 1
        initial = supervisor.fleet_ping.sample_count
        _wait_samples(supervisor, initial + 4)
        assert supervisor.heartbeat._heartbeat_engine.snapshot("heartbeat-mr").status == "ONLINE"
    finally:
        supervisor.heartbeat.close()


@pytest.mark.parametrize("expiry_path", ["poll", "recovered_expiry"])
def test_inventory_heartbeat_never_expires_with_ac_recovery_grace(
    tmp_path: Path, expiry_path: str,
) -> None:
    supervisor, repository, _mesh = _heartbeat_fixture(tmp_path)
    profile = repository.get_profile()
    now = datetime.now().astimezone()
    try:
        restored = supervisor._restore_fleet_ping_targets(
            repository.get_run("run-1"), profile,
            now - timedelta(seconds=profile.ac_stale_grace_seconds + 1),
        )
        assert restored == 2
        assert supervisor._last_valid_ping_targets == {}
        if expiry_path == "poll":
            supervisor._poll_ac_and_classify(
                repository.get_run("run-1"), profile, now, scheduling_paused=False,
            )
        else:
            supervisor._expire_recovered_ping_targets(
                repository.get_run("run-1"), profile, now,
            )
        assert supervisor.fleet_ping.target_count == 2
        assert not repository.list_events("run-1", event_type="ping_target_grace_expired")
        initial = supervisor.fleet_ping.sample_count
        _wait_samples(supervisor, initial + 12)
        snapshot = supervisor.heartbeat._heartbeat_engine.snapshot("heartbeat-mr")
        assert snapshot.status == "ONLINE"
        assert {item.ip for item in snapshot.ip_states} == {"192.0.2.10", "192.0.2.11"}
        assert all(item.received_count > 0 for item in snapshot.ip_states)
        assert not repository.list_events("run-1", event_type="mr_offline")
    finally:
        supervisor.heartbeat.close()


@pytest.mark.parametrize("expiry_path", ["poll", "recovered_expiry"])
def test_expired_ac_enrichment_keeps_inventory_heartbeat_targets(
    tmp_path: Path, expiry_path: str,
) -> None:
    supervisor, repository, _mesh = _heartbeat_fixture(tmp_path)
    profile = repository.get_profile()
    now = datetime.now().astimezone()
    address = "192.0.2.10"
    target = replace(
        supervisor.heartbeat._heartbeat_fleet_targets()[address], current_ap_name="Mock AP",
    )
    supervisor._last_valid_ping_targets = {
        address: (target, now - timedelta(seconds=profile.ac_stale_grace_seconds + 1)),
    }
    try:
        if expiry_path == "poll":
            supervisor._poll_ac_and_classify(
                repository.get_run("run-1"), profile, now, scheduling_paused=False,
            )
        else:
            supervisor._expire_recovered_ping_targets(
                repository.get_run("run-1"), profile, now,
            )
        assert supervisor._last_valid_ping_targets == {}
        assert supervisor.fleet_ping.target_count == 2
        expired = repository.list_events("run-1", event_type="ping_target_grace_expired")
        assert len(expired) == 1
        assert "AC 辅助定位" in expired[0]["title"]
        assert "心跳检测继续" in expired[0]["title"]
        initial = supervisor.fleet_ping.sample_count
        _wait_samples(supervisor, initial + 12)
        assert supervisor.heartbeat._heartbeat_engine.snapshot("heartbeat-mr").status == "ONLINE"
        assert not repository.list_events("run-1", event_type="mr_offline")
    finally:
        supervisor.heartbeat.close()


def test_backend_restart_restores_counters_but_requires_live_recovery_evidence(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.sync_inventory(
        trains=[{"train_id": "restart-train", "train_no": "002"}],
        endpoints=[{
            "device_uuid": "restart-mr", "train_id": "restart-train",
            "mr_role": "CW", "management_ip": "192.0.2.20",
        }],
    )
    started = datetime.fromisoformat("2026-07-29T08:00:00+08:00")
    supervisor.now_provider = lambda: started
    target = supervisor.heartbeat._refresh_inventory_heartbeat(repository.get_run("run-1"), started)["192.0.2.20"]
    for second in range(11):
        supervisor.heartbeat._on_fleet_ping_sample(target, SimpleNamespace(
            ts=(started + timedelta(seconds=second)).isoformat(), ok=False, rtt_ms=None,
        ))
    supervisor.heartbeat._persist_heartbeat_state(at=started + timedelta(seconds=10))
    assert supervisor.heartbeat._heartbeat_engine.snapshot("restart-mr").status == "OFFLINE"
    assert repository.list_heartbeat_snapshots("run-1", entity_type="MR")[0]["snapshot"]["ip_states"][0]["sent_count"] == 11

    resumed, resumed_repository, _mesh = _supervisor(tmp_path)
    resumed.now_provider = lambda: started + timedelta(hours=1)
    resumed.heartbeat.now_provider = resumed.now_provider
    resumed_repository.migrate_resident_heartbeat(HEARTBEAT_STREAM_ID)
    resumed.heartbeat._configure_heartbeat_targets(HEARTBEAT_STREAM_ID)
    resumed.heartbeat._heartbeat_engine.restore_snapshots(resumed_repository.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID, entity_type="MR"))
    restored = resumed.heartbeat._heartbeat_engine.snapshot("restart-mr")
    assert restored.status == "UNKNOWN"
    assert restored.unreachable_since is None
    assert restored.ip_states[0].sent_count == 11
    assert restored.ip_states[0].last_probe_at is None
    resumed.heartbeat._refresh_inventory_heartbeat({"run_id": HEARTBEAT_STREAM_ID}, resumed.now_provider())
    for second in range(2):
        resumed.heartbeat._on_fleet_ping_sample(target, SimpleNamespace(
            ts=(started + timedelta(hours=1, seconds=second)).isoformat(), ok=True, rtt_ms=1.0,
        ))
        assert resumed.heartbeat._heartbeat_engine.snapshot("restart-mr").status == ("RECOVERING" if second == 0 else "ONLINE")
    resumed.heartbeat._persist_heartbeat_state(at=started + timedelta(hours=1, seconds=1))
    stored = resumed_repository.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID, entity_type="MR")[0]["snapshot"]
    assert stored["ip_states"][0]["sent_count"] == 13
    assert len(resumed_repository.list_events("run-1", event_type="mr_offline")) == 1
    assert len(resumed_repository.list_events(HEARTBEAT_STREAM_ID, event_type="mr_recovered")) == 1


def test_supervisor_processes_each_controller_snapshot_only_once(
    tmp_path: Path,
) -> None:
    supervisor, repository, mesh = _supervisor(tmp_path)
    run = repository.get_active_run()
    assert run is not None
    profile = repository.get_profile()
    now = datetime.fromisoformat("2026-07-29T08:01:00+08:00")

    supervisor._poll_ac_and_classify(
        run, profile, now, scheduling_paused=False
    )
    supervisor._poll_ac_and_classify(
        run, profile, now, scheduling_paused=True
    )

    assert mesh.snapshot_row_calls == [11, 21]
    assert supervisor._last_processed_snapshot_id_by_controller == {
        "ac-1": 11,
        "ac-2": 21,
    }
    saved = repository.get_run("run-1")
    assert saved is not None
    assert saved["summary"]["ac_last_processed_snapshot_ids"] == {
        "ac-1": 11,
        "ac-2": 21,
    }
    assert saved["state"] == "PAUSED"
    first_ac_2_row = repository.latest_ac_snapshot(
        "run-1", "mesh:train:21", "mr-21"
    )
    assert first_ac_2_row is not None

    mesh.snapshots[0] = mesh._snapshot(12, "ac-1")
    supervisor._poll_ac_and_classify(
        saved, profile, now, scheduling_paused=False
    )
    assert mesh.snapshot_row_calls == [11, 21, 12, 21]
    assert supervisor._last_processed_snapshot_id_by_controller == {
        "ac-1": 12,
        "ac-2": 21,
    }
    second_ac_2_row = repository.latest_ac_snapshot(
        "run-1", "mesh:train:21", "mr-21"
    )
    assert second_ac_2_row is not None
    assert second_ac_2_row["id"] == first_ac_2_row["id"]


class _DeepScheduler:
    def __init__(
        self,
        *,
        active: bool,
        active_ids: list[str] | None = None,
        force_completes: bool = True,
    ) -> None:
        self.active = active
        self.active_ids = active_ids or (["deep-1"] if active else [])
        self.force_completes = force_completes
        self.stop_calls = 0
        self.force_stop_calls: list[str] = []
        self.recover_calls: list[str] = []

    def recover(self, run_id: str) -> None:
        self.recover_calls.append(run_id)

    def stop_all(self, *_args, **_kwargs) -> None:
        self.stop_calls += 1

    def tick(self, *_args, **_kwargs) -> None:
        return None

    def has_active_automated(self) -> bool:
        return self.active

    def active_automated_operation_ids(self) -> list[str]:
        return list(self.active_ids)

    def force_stop_all(self, run_id: str, *, reason: str) -> list[str]:
        self.force_stop_calls.append(reason)
        operation_ids = list(self.active_ids)
        if self.force_completes:
            self.active = False
            self.active_ids = []
        return operation_ids


class _ResidentService:
    def __init__(
        self,
        *,
        stop_success: bool = True,
        statuses: list[dict[str, object]] | None = None,
    ) -> None:
        self.stop_success = stop_success
        self.statuses = statuses or []
        self.stop_calls: list[dict[str, object]] = []

    def request_stop_run(self, **values):
        self.stop_calls.append(values)
        return SimpleNamespace(
            success=self.stop_success,
            pollers=(
                {
                    "controller_id": "ac-1",
                    "task_id": "resident-1",
                    "connection_state": "BACKOFF",
                    "stopped": self.stop_success,
                    "forced": not self.stop_success,
                },
            ),
        )

    def list_statuses(self, **_values):
        return list(self.statuses)


class _FleetPingRecorder:
    def __init__(self) -> None:
        self.started = False
        self.target_updates: list[list[object]] = []

    def start(self, **_values) -> None:
        self.started = True

    def update_targets(self, targets) -> None:
        self.target_updates.append(list(targets))


def test_application_shutdown_quiesces_process_without_stopping_business_run(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    resident = _ResidentService()
    deep = _DeepScheduler(active=True)
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    supervisor.deep_scheduler = deep  # type: ignore[assignment]

    supervisor._shutdown_active_run()

    assert deep.stop_calls == 0
    assert resident.stop_calls == []
    run = repository.get_run("run-1")
    assert run is not None
    assert run["state"] == "RUNNING"
    operation = repository.latest_operation(run_id="run-1")
    assert operation is None
    events = repository.list_events("run-1", event_type="backend_shutdown_quiesced")
    assert len(events) == 1
    assert events[0]["details"]["stop_trigger"] == "BACKEND_SHUTDOWN"


def test_user_stop_intent_is_persisted_before_supervisor_command_runs(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    response = service.stop("site-a", archive=True)

    run = repository.get_run("run-1")
    operation = repository.get_operation(response.operation_id)
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "stop_and_archive"
    assert operation is not None and operation["operation_state"] == "PENDING"
    assert operation["stop_trigger"] == "USER_STOP_AND_ARCHIVE"

    supervisor._handle_commands()
    operation = repository.get_operation(response.operation_id)
    assert operation is not None and operation["previous_state"] == "RUNNING"


def test_concurrent_stop_requests_share_one_durable_operation(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda archive: service.stop("site-a", archive=archive), [False, True])
        )

    active = repository.list_operations(run_id="run-1", active_only=True)
    assert len(active) == 1
    assert {response.operation_id for response in responses} == {active[0]["operation_id"]}
    assert len(supervisor._commands) == 1


def test_stop_intent_is_not_overwritten_by_pause_or_resume(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    response = service.stop("site-a", archive=True)

    with pytest.raises(GroundUnattendedError, match="仅运行中的") as pause_error:
        service.pause("site-a")
    assert pause_error.value.code == "RUN_NOT_PAUSABLE"
    with pytest.raises(GroundUnattendedError, match="仅已暂停的") as resume_error:
        service.resume("site-a")
    assert resume_error.value.code == "RUN_NOT_RESUMABLE"

    # 模拟在 stop 已持久化后仍滞留于队列中的旧命令，消费端必须再次校验状态。
    supervisor.request("pause")
    supervisor.request("resume")
    supervisor._handle_commands()

    run = repository.get_run("run-1")
    operation = repository.get_operation(response.operation_id)
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "stop_and_archive"
    assert operation is not None and operation["operation_state"] == "RUNNING"


def test_pause_and_resume_only_allow_exact_state_transitions(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    with pytest.raises(GroundUnattendedError) as resume_error:
        service.resume("site-a")
    assert resume_error.value.code == "RUN_NOT_RESUMABLE"

    service.pause("site-a")
    supervisor._handle_commands()
    assert repository.get_run("run-1")["state"] == "PAUSED"

    with pytest.raises(GroundUnattendedError) as pause_error:
        service.pause("site-a")
    assert pause_error.value.code == "RUN_NOT_PAUSABLE"

    service.resume("site-a")
    supervisor._handle_commands()
    assert repository.get_run("run-1")["state"] == "RUNNING"


def test_ac_poller_stop_timeout_keeps_controller_diagnostics(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    supervisor.ac_resident_service = _ResidentService(  # type: ignore[assignment]
        stop_success=False
    )
    run = repository.get_active_run()
    assert run is not None

    supervisor._finalize_run(run, archive=False)

    operation = repository.latest_operation(run_id="run-1")
    assert operation is not None
    assert operation["operation_state"] == "FAILED"
    assert operation["failure_code"] == "AC_POLLER_STOP_TIMEOUT"
    assert operation["result_summary"]["ac_pollers"][0] == {
        "controller_id": "ac-1",
        "task_id": "resident-1",
        "connection_state": "BACKOFF",
        "stopped": False,
        "forced": True,
    }


def test_restart_recovers_legacy_application_shutdown_inside_frozen_window(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(repository.get_profile().model_copy(update={"enabled": True}))
    repository.update_run(
        "run-1", state="FINALIZING", requested_action="application_shutdown"
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor._start_fleet_ping = lambda *_args: None  # type: ignore[method-assign]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    assert run is not None and run["state"] == "RUNNING"
    assert run["requested_action"] == "recovered_after_shutdown"
    assert deep.recover_calls == ["run-1"]


def test_restart_keeps_persisted_user_archive_intent_over_shutdown_marker(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(repository.get_profile().model_copy(update={"enabled": True}))
    repository.update_run(
        "run-1", state="FINALIZING", requested_action="application_shutdown"
    )
    repository.save_operation(
        {
            "operation_id": "user-archive",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP_AND_ARCHIVE",
            "operation_state": "PENDING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 0,
            "message": "停止并归档请求已提交",
            "stop_trigger": "USER_STOP_AND_ARCHIVE",
            "requested_by": "local_user",
            "started_at": "2026-07-29T11:45:00+08:00",
            "updated_at": "2026-07-29T11:45:00+08:00",
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    operation = repository.get_operation("user-archive")
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "stop_and_archive"
    assert operation is not None and operation["operation_state"] == "PENDING"
    assert operation["stop_trigger"] == "USER_STOP_AND_ARCHIVE"
    assert deep.recover_calls == ["run-1"]


def test_legacy_backend_shutdown_operation_keeps_backend_reason_and_continues(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.update_run(
        "run-1", state="FINALIZING", requested_action="application_shutdown"
    )
    repository.save_operation(
        {
            "operation_id": "legacy-backend-stop",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOPPING_AC_POLLER",
            "progress_percent": 22,
            "message": "正在停止 AC 常驻轮询",
            "started_at": "2026-07-29T11:45:00+08:00",
            "updated_at": "2026-07-29T11:45:00+08:00",
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    operation = repository.get_operation("legacy-backend-stop")
    assert run is not None and run["state"] == "FINALIZING"
    assert operation is not None
    assert operation["stop_trigger"] == "BACKEND_SHUTDOWN"
    assert "旧版本 Backend 退出" in operation["stop_reason"]
    assert deep.recover_calls == ["run-1"]


def test_restart_backfills_missing_frozen_window_before_next_tick(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(repository.get_profile().model_copy(update={"enabled": True}))
    repository.update_run("run-1", scheduled_start_at="", scheduled_end_at="")
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor._start_fleet_ping = lambda *_args: None  # type: ignore[method-assign]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]
    supervisor._poll_if_due = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    supervisor._recover_on_start()
    supervisor._tick()

    run = repository.get_run("run-1")
    assert run is not None and run["state"] == "RUNNING"
    assert run["scheduled_start_at"].startswith("2026-07-29T07:00:00")
    assert run["scheduled_end_at"].startswith("2026-07-29T23:00:00")
    assert repository.latest_operation(run_id="run-1") is None


@pytest.mark.parametrize("expiry_path", ["poll", "recovered_expiry"])
def test_restart_restores_persisted_ping_targets_without_new_ac_snapshot(
    tmp_path: Path, expiry_path: str,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.sync_inventory(
        trains=[{"train_id": "train-02", "train_no": "02"}],
        endpoints=[{
            "device_uuid": "mr-cw-02", "train_id": "train-02", "mr_role": "CW",
            "management_ip": "192.168.100.232",
        }],
    )
    repository.save_profile(
        repository.get_profile().model_copy(
            update={"enabled": True, "ac_stale_grace_seconds": 180}
        )
    )
    repository.update_run(
        "run-1",
        summary_json={"ac_last_processed_snapshot_ids": {"ac-1": 11, "ac-2": 21}},
    )
    repository.upsert_train_state(
        "run-1",
        "2026-07-29",
        {
            "train_id": "train-02",
            "train_no": "02",
            "train_name": "列车02",
            "ping_eligible": True,
            "current_ap_name": "AP0808",
            "current_ap_mac": "0011-2233-4455",
            "station": "泽民",
            "section": "泽民-大卿桥-下行",
            "rssi": -61,
            "ac_snapshot_id": 21,
            "ac_received_at": "2026-07-29T11:45:00+08:00",
            "endpoints": [
                {
                    "endpoint": "CW",
                    "mr_id": "mr-cw-02",
                    "mr_name": "列车02-MR-CW",
                    "device_id": 22,
                    "management_ip": "192.168.100.232",
                    "ping_target_eligible": True,
                }
            ],
            "ap_identity_diagnostics": {"identity_revision": 8743},
        },
        ap_identity="ap-identity-0808",
        same_ap_since="2026-07-29T11:40:00+08:00",
    )
    repository.insert_wmesh_events(
        [
            {
                "run_id": "run-1",
                "device_uuid": "mr-cw-02",
                "train_id": "train-02",
                "mr_role": "CW",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:45:30+08:00",
            }
        ]
    )
    ping = _FleetPingRecorder()
    supervisor.fleet_ping = ping  # type: ignore[assignment]
    clock = [datetime.fromisoformat("2026-07-29T11:46:00+08:00")]
    supervisor.now_provider = lambda: clock[0]
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]

    supervisor._recover_on_start()

    assert ping.started is False
    assert not ping.target_updates
    assert len(supervisor.heartbeat._enrichment) == 1
    recovered = next(iter(supervisor.heartbeat._enrichment.values()))
    assert recovered.target_ip == "192.168.100.232"
    assert recovered.current_ap_name == "AP0808"
    assert recovered.station == "泽民"
    assert recovered.section == "泽民-大卿桥-下行"
    run = repository.get_run("run-1")
    assert run is not None
    assert run["summary"]["recovered_from_restart"] is True
    assert run["summary"]["ping_recovered_target_count"] == 1
    assert run["summary"]["main_link_recovered"] is True
    assert run["summary"]["main_link_state"] == "MESH_LINKUP"
    assert run["summary"]["main_link_last_event_at"] == (
        "2026-07-29T11:45:30+08:00"
    )
    assert run["summary"]["ap_identity_revision"] == 8743

    clock[0] = datetime.fromisoformat("2026-07-29T11:49:01+08:00")
    if expiry_path == "poll":
        supervisor._poll_ac_and_classify(
            repository.get_run("run-1"),
            repository.get_profile(),
            clock[0],
            scheduling_paused=False,
        )
    else:
        supervisor._expire_recovered_ping_targets(
            repository.get_run("run-1"), repository.get_profile(), clock[0],
        )

    assert list(supervisor.heartbeat._enrichment) == ["192.168.100.232"]
    assert supervisor.heartbeat._enrichment["192.168.100.232"].current_ap_name == ""
    assert not ping.target_updates
    expired = repository.list_events("run-1", event_type="ping_target_grace_expired")
    assert len(expired) == 1
    assert "AC 辅助定位" in expired[0]["title"]
    assert "心跳检测继续" in expired[0]["title"]


def test_restart_marks_persisted_main_link_stale_after_existing_grace(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(
        repository.get_profile().model_copy(
            update={"enabled": True, "ac_stale_grace_seconds": 120}
        )
    )
    repository.insert_wmesh_events(
        [
            {
                "run_id": "run-1",
                "device_uuid": "mr-cw-02",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:40:00+08:00",
                "peer_name": "AP0808",
            }
        ]
    )
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor.fleet_ping = _FleetPingRecorder()  # type: ignore[assignment]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]
    supervisor.deep_scheduler = None

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    assert run is not None
    assert run["summary"]["main_link_state"] == "STALE"
    assert run["summary"]["main_link_recovered"] is False


def test_endpoint_snapshot_scopes_persisted_wmesh_to_current_run(
    tmp_path: Path,
) -> None:
    _supervisor_instance, repository, _mesh = _supervisor(tmp_path)
    repository.insert_wmesh_events(
        [
            {
                "run_id": "run-1",
                "device_uuid": "mr-cw-02",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:45:00+08:00",
                "peer_name": "AP-CURRENT-RUN",
            },
            {
                "run_id": "run-other",
                "device_uuid": "mr-cw-02",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:46:00+08:00",
                "peer_name": "AP-OTHER-RUN",
            },
        ]
    )

    snapshot = repository.train_endpoint_snapshot(
        ["mr-cw-02"], run_id="run-1"
    )

    assert snapshot["wmesh_by_device"]["mr-cw-02"]["peer_name"] == (
        "AP-CURRENT-RUN"
    )


def test_restart_inside_frozen_window_records_profile_disabled_reason(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    operation = repository.latest_operation(run_id="run-1")
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "disabled"
    assert operation is not None
    assert operation["stop_trigger"] == "PROFILE_DISABLED"
    assert operation["operation_type"] == "STOP"


def test_restart_retries_legacy_error_with_failed_stop_operation(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.update_run("run-1", state="ERROR", requested_action="fatal_error")
    repository.save_operation(
        {
            "operation_id": "legacy-failed-stop",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "FAILED",
            "operation_stage": "FAILED",
            "progress_percent": 100,
            "message": "旧版本停止失败",
            "failure_code": "DEEP_COLLECTION_STOP_TIMEOUT",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:43:00+08:00",
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = _ResidentService()  # type: ignore[assignment]

    supervisor._recover_on_start()
    recovered = repository.latest_operation(run_id="run-1", active_only=True)
    assert recovered is not None
    assert recovered["operation_id"] != "legacy-failed-stop"
    assert recovered["stop_trigger"] == "RECOVERY"
    assert repository.get_run("run-1")["state"] == "STOPPING"

    supervisor._tick()

    run = repository.get_run("run-1")
    operation = repository.get_operation(str(recovered["operation_id"]))
    assert run is not None and run["state"] == "COMPLETED"
    assert operation is not None and operation["operation_state"] == "COMPLETED"


def test_deep_collection_stop_deadline_continues_other_component_cleanup(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    deep = _DeepScheduler(active=True)
    resident = _ResidentService()
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    repository.update_run("run-1", state="STOPPING", requested_action="stop")
    repository.save_operation(
        {
            "operation_id": "stop-timeout",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "停止",
            "stop_trigger": "USER_NORMAL_STOP",
            "stop_reason": "用户请求正常停止",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:40:00+08:00",
        }
    )
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:43:00+08:00"
    )
    run = repository.get_active_run()
    assert run is not None

    supervisor._finalize_run(run, archive=False)

    operation = repository.get_operation("stop-timeout")
    assert operation is not None
    assert operation["operation_state"] == "FAILED"
    assert operation["failure_code"] == "DEEP_COLLECTION_STOP_TIMEOUT"
    assert operation["result_summary"]["stop_failures"][0]["component"] == "deep_collection"
    assert operation["result_summary"]["deep_collection_stop_state"] == "TIMED_OUT"
    assert resident.stop_calls
    run = repository.get_run("run-1")
    assert run is not None and run["state"] == "COMPLETED"


def test_deep_collection_deadline_accounts_for_bounded_finalizing_waves(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    deep = _DeepScheduler(
        active=True,
        active_ids=["deep-1", "deep-2", "deep-3", "deep-4"],
    )
    resident = _ResidentService()
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    repository.save_profile(
        repository.get_profile().model_copy(update={"max_finalizing_mrs": 2})
    )
    repository.update_run("run-1", state="STOPPING", requested_action="stop")
    repository.save_operation(
        {
            "operation_id": "stop-waves",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "停止",
            "stop_trigger": "USER_NORMAL_STOP",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:40:00+08:00",
        }
    )
    clock = [datetime.fromisoformat("2026-07-29T11:42:30+08:00")]
    supervisor.now_provider = lambda: clock[0]

    supervisor._finalize_run(repository.get_active_run(), archive=False)

    waiting = repository.get_operation("stop-waves")
    assert waiting is not None and waiting["operation_state"] == "RUNNING"
    assert waiting["result_summary"]["deep_collection_stop_timeout_seconds"] == 160.0
    assert resident.stop_calls == []

    clock[0] = datetime.fromisoformat("2026-07-29T11:42:41+08:00")
    supervisor._finalize_run(repository.get_active_run(), archive=False)
    completed = repository.get_operation("stop-waves")
    assert completed is not None and completed["operation_state"] == "FAILED"
    assert resident.stop_calls


def test_deep_collection_force_stop_keeps_run_owned_until_mapping_terminal(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    deep = _DeepScheduler(active=True, force_completes=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = _ResidentService()  # type: ignore[assignment]
    repository.update_run("run-1", state="STOPPING", requested_action="stop")
    repository.save_operation(
        {
            "operation_id": "stop-force-wait",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "停止",
            "stop_trigger": "USER_NORMAL_STOP",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:40:00+08:00",
        }
    )
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:43:00+08:00"
    )

    supervisor._finalize_run(repository.get_active_run(), archive=False)

    run = repository.get_run("run-1")
    operation = repository.get_operation("stop-force-wait")
    assert run is not None and run["state"] == "FINALIZING"
    assert operation is not None and operation["operation_state"] == "RUNNING"
    assert operation["operation_stage"] == "WAITING_DEEP_COLLECTION_TERMINAL"
    assert deep.force_stop_calls == ["normal_stop_deadline_exceeded"]


def test_restart_from_deep_wait_preserves_persisted_ping_count(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.update_run(
        "run-1",
        state="FINALIZING",
        requested_action="stop",
        ping_sample_count=47,
    )
    repository.save_operation(
        {
            "operation_id": "stop-restart-count",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "WAITING_DEEP_COLLECTION_TERMINAL",
            "progress_percent": 90,
            "message": "等待深度采集映射进入终态",
            "stop_trigger": "USER_NORMAL_STOP",
            "stop_reason": "用户请求正常停止",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:43:00+08:00",
            "result_summary": {
                "ping_sample_count": 47,
                "deep_collection_stop_state": "FORCE_STOPPING",
                "stop_failures": [
                    {
                        "component": "deep_collection",
                        "code": "DEEP_COLLECTION_STOP_TIMEOUT",
                        "message": "深度采集任务未在停止预算内终结",
                        "state": "TIMED_OUT",
                    }
                ],
            },
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = _ResidentService()  # type: ignore[assignment]

    supervisor._recover_on_start()
    supervisor._tick()

    run = repository.get_run("run-1")
    operation = repository.get_operation("stop-restart-count")
    assert run is not None and run["state"] == "COMPLETED"
    assert run["ping_sample_count"] == 47
    assert operation is not None and operation["operation_state"] == "FAILED"
    assert operation["result_summary"]["ping_sample_count"] == 47
    assert deep.recover_calls == ["run-1"]


def test_ac_health_marks_backoff_degraded_and_keeps_failed_poller(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    now = datetime.now().astimezone()
    resident = _ResidentService(
        statuses=[
            {
                "controller_id": "ac-1",
                "controller_name": "AC 1",
                "task_id": "resident-1",
                "run_id": "run-1",
                "connection_state": "BACKOFF",
                "heartbeat_at": now.isoformat(timespec="milliseconds"),
                "last_success_at": (now - timedelta(seconds=1)).isoformat(
                    timespec="milliseconds"
                ),
                "poll_interval_seconds": 10,
            },
            {
                "controller_id": "ac-2",
                "controller_name": "AC 2",
                "task_id": "resident-2",
                "run_id": "run-1",
                "connection_state": "FAILED",
                "heartbeat_at": now.isoformat(timespec="milliseconds"),
                "last_error_message": "凭据不可用",
            },
        ]
    )
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
    )

    health = service.health("site-a")

    assert [(item.controller_id, item.status) for item in health.ac_pollers] == [
        ("ac-1", "DEGRADED"),
        ("ac-2", "CRITICAL"),
    ]
    # This fixture does not start the supervisor thread; the auxiliary poller
    # health itself remains independent of the overall runtime lifecycle.
    assert health.status == "CRITICAL"
    assert health.ac_pollers[1].last_error == "凭据不可用"
