from __future__ import annotations

import json
import sqlite3
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.models.api.ground_unattended import HeartbeatConfigDTO
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.fleet_ping import FleetPingSupervisor
from netconsole.services.ground_unattended.heartbeat_supervisor import (
    HEARTBEAT_STREAM_ID,
    HeartbeatSupervisor,
)
from netconsole.services.ground_unattended.ping_loss import PingLossTracker
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor


def sample(address, *, at=None, ok=True, seq=1):
    return FpingV5Sample(
        ts=(at or datetime.now(timezone.utc)).isoformat(), target=address,
        seq=seq, ok=ok, rtt_ms=2.0 if ok else None, timeout_ms=4000,
        size=64, error="" if ok else "timeout", backend=BACKEND,
        raw_type="response" if ok else "timeout", raw={},
    )


def wait_for(predicate, *, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    assert predicate()


def install_runner(owner, *, emit=False):
    active = set()
    overlaps = []
    lock = threading.Lock()

    def runner(*, targets, stop_event, **_kwargs):
        with lock:
            overlaps.extend(active.intersection(targets))
            active.update(targets)
        try:
            seq = 0
            while not stop_event.wait(0.02):
                seq += 1
                if emit:
                    for address in targets:
                        yield sample(address, seq=seq)
        finally:
            with lock:
                active.difference_update(targets)

    owner.fleet_ping = FleetPingSupervisor(
        repository=owner.repository, site_id=owner.site_id, runner=runner,
        sample_callback=owner._on_fleet_ping_sample,
    )
    return active, overlaps


def seed(repo, *, count=1, dual=False):
    repo.sync_inventory(
        trains=[{"train_id": f"train-{i}", "train_no": f"{i:03d}"} for i in range(count)],
        endpoints=[{
            "device_uuid": f"mr-{i}", "train_id": f"train-{i}", "mr_role": "CT",
            "device_name": f"MR {i}", "management_ip": f"198.18.{i // 250}.{i % 250 + 1}",
            "backup_management_ip": f"198.19.{i // 250}.{i % 250 + 1}" if dual else "",
        } for i in range(count)],
    )


@pytest.fixture
def resident(tmp_path):
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repo = GroundUnattendedRepository(paths.ground_unattended_db_path("demo"), site_id="demo")
    seed(repo)
    owner = HeartbeatSupervisor(paths, site_id="demo", repository=repo,
                                base_query=SimpleNamespace(), tick_seconds=0.05)
    owner._inventory_refresh_at = float("inf")
    install_runner(owner)
    repo.save_heartbeat_config(HeartbeatConfigDTO(warmup_seconds=0))
    try:
        yield owner
    finally:
        owner.close()


def test_backend_lifespan_probes_without_run_or_renderer_and_restarts(tmp_path):
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    ground = app.state.ground_unattended_supervisor
    owner = ground.heartbeat
    seed(owner.repository)
    owner._inventory_refresh_at = float("inf")
    owner.tick_seconds = 0.05
    active, overlaps = install_runner(owner, emit=True)
    ground.fleet_ping = owner.fleet_ping
    owner.repository.save_heartbeat_config(HeartbeatConfigDTO(warmup_seconds=0))
    for _ in range(2):
        with TestClient(app):
            wait_for(lambda: owner.fleet_ping.sample_count >= 4)
            thread = owner._thread
            owner.start()
            assert owner._thread is thread
            assert app.state.heartbeat_supervisor is owner
            assert owner.repository.get_active_run() is None
            assert owner.repository.get_run(HEARTBEAT_STREAM_ID) is None
            assert owner.status().last_success_at
        assert not owner.running
        assert not active
        assert owner.fleet_ping.process_count == 0
    assert not overlaps


def test_config_is_independent_persistent_and_hot_updates_without_worker_overlap(resident):
    owner = resident
    seed(owner.repository, count=8, dual=True)
    active, overlaps = install_runner(owner, emit=True)
    owner.start()
    wait_for(lambda: owner.status().target_count == 16)
    thread = owner._thread
    config = owner.repository.get_heartbeat_config()
    config.shard_size = 2
    config.backup_policy = "PRIMARY_ONLY"
    config.interval_ms = 10000
    owner.repository.save_heartbeat_config(config)
    owner.config_updated()
    wait_for(lambda: owner.status().target_count == 8 and owner.fleet_ping.process_count == 4)
    assert owner._thread is thread
    assert owner._heartbeat_engine.sample_stale_seconds >= 30
    config.enabled = False
    owner.repository.save_heartbeat_config(config)
    owner.config_updated()
    wait_for(lambda: owner.status().state == "DISABLED")
    assert not active
    config.enabled = True
    owner.repository.save_heartbeat_config(config)
    owner.config_updated()
    wait_for(lambda: owner.status().state == "RUNNING")
    assert owner._thread is thread
    assert not overlaps
    assert owner.repository.get_heartbeat_config() == config


def test_first_start_freezes_legacy_parameters_and_does_not_overwrite_new_save(resident, monkeypatch):
    repo = resident.repository
    with repo._transaction() as conn:
        conn.execute("DELETE FROM ground_unattended_heartbeat_config")
    profile = repo.get_profile()
    profile.fleet_ping_interval_ms = 2300
    repo.save_profile(profile)
    adopted = repo.initialize_heartbeat_config()
    assert adopted.interval_ms == 2300
    profile.fleet_ping_interval_ms = 3000
    repo.save_profile(profile)
    assert repo.get_heartbeat_config().interval_ms == 2300
    original = repo.get_heartbeat_config
    saved = adopted.model_copy(update={"interval_ms": 1700})

    def concurrent_save():
        monkeypatch.setattr(repo, "get_heartbeat_config", original)
        repo.save_heartbeat_config(saved)
        return adopted

    monkeypatch.setattr(repo, "get_heartbeat_config", concurrent_save)
    assert repo.initialize_heartbeat_config() == saved


def test_inventory_fault_keeps_verified_targets_and_page_does_not_write(resident, monkeypatch):
    owner = resident
    owner._tick()
    owner._inventory_refresh_at = 0
    monkeypatch.setattr(owner.inventory_sync, "preview", lambda: (_ for _ in ()).throw(RuntimeError("source failed")))
    owner._tick()
    assert owner.status().target_count == 1
    assert owner.status().state == "HEARTBEAT_DEGRADED"
    assert "INVENTORY_REFRESH_FAILED" in owner.status().last_error


def test_read_api_is_read_only_without_starting_resident(tmp_path, monkeypatch):
    app = create_app(paths=PathResolver(tmp_path / "app", tmp_path / "data"))
    service = app.state.ground_unattended_application_service
    seed(service.repository)
    monkeypatch.setattr(service.inventory_sync, "synchronize", lambda: pytest.fail("query wrote inventory"))
    monkeypatch.setattr(service.inventory_sync, "preview", lambda: pytest.fail("query refreshed inventory"))
    monkeypatch.setattr(service.repository, "upsert_heartbeat_snapshots", lambda *_a, **_kw: pytest.fail("query persisted state"))
    page = service.heartbeat(service.site_id)
    assert page.total_mrs == 1
    assert page.mrs[0].status == "UNKNOWN"
    assert not service.supervisor.heartbeat.running
    service.close()
    service.supervisor.close()


@pytest.mark.parametrize("failure", ["exception", "stream_end"])
def test_fping_failure_is_degraded_backs_off_then_recovers(resident, failure):
    owner = resident
    attempts = []

    def runner(*, targets, stop_event, **_kwargs):
        attempts.append(time.monotonic())
        if len(attempts) == 1:
            if failure == "exception":
                raise RuntimeError("fping unavailable")
            return
        while not stop_event.wait(0.02):
            for address in targets:
                yield sample(address)

    owner.fleet_ping.runner = runner
    owner.start()
    wait_for(lambda: owner.status().state == "HEARTBEAT_DEGRADED")
    assert ("fping unavailable" if failure == "exception" else "stream ended") in owner.status().last_error
    wait_for(lambda: len(attempts) == 2)
    wait_for(lambda: owner.status().state == "RUNNING")
    assert attempts[1] - attempts[0] >= 1.9
    assert owner.running


@pytest.mark.parametrize("fault", ["ac", "mesh", "udp", "replay"])
def test_ground_component_fault_does_not_interrupt_resident(resident, monkeypatch, fault):
    owner = resident
    install_runner(owner, emit=True)
    now = datetime.fromisoformat("2026-11-10T08:00:00+08:00")
    ground = GroundUnattendedSupervisor(
        owner.paths, site_id=owner.site_id, repository=owner.repository,
        base_query=SimpleNamespace(), mesh_query=SimpleNamespace(), vehicle_query=SimpleNamespace(),
        now_provider=lambda: now,
    )
    ground.heartbeat, ground.fleet_ping = owner, owner.fleet_ping
    repo = owner.repository
    profile = repo.get_profile().model_copy(update={"enabled": True,
        "syslog_receiver_auto_start_enabled": fault == "udp"})
    repo.save_profile(profile)
    repo.create_or_get_run(run_id="component-fault", run_date="2026-11-10", state="RUNNING",
        scheduled_start_at="2026-11-10T07:00:00+08:00", scheduled_end_at="2026-11-10T23:00:00+08:00")
    monkeypatch.setattr(ground, "_ensure_ac_resident_pollers", lambda *_a: None)
    monkeypatch.setattr(ground, "_schedule_config_checks", lambda *_a: None)
    if fault != "mesh":
        monkeypatch.setattr(ground, "_latest_controller_snapshots", lambda: [])

    def fail(*_args, **_kwargs):
        raise OSError(f"injected {fault} failure")

    if fault == "ac":
        monkeypatch.setattr(ground, "_ensure_ac_resident_pollers", fail)
    elif fault == "mesh":
        ground.mesh_query.list_latest_snapshots_by_controller = fail
    elif fault == "udp":
        monkeypatch.setattr(ground.syslog_receiver, "start", fail)
    else:
        ground._syslog_recovery_pending = True
        monkeypatch.setattr(ground.syslog_receiver, "replay_pending_events", fail)
    owner.start()
    wait_for(lambda: owner.fleet_ping.sample_count >= 2)
    thread = owner._thread
    try:
        for _ in range(3):
            before = owner.fleet_ping.sample_count
            ground._last_ac_poll_monotonic = 0.0
            if fault == "replay":
                ground._tick()  # Replay failures are caught by Ground itself.
            else:
                with pytest.raises(OSError, match=f"injected {fault} failure"):
                    ground._tick()
            wait_for(lambda: owner.fleet_ping.sample_count > before)
            assert owner._thread is thread and owner.status().state == "RUNNING"
    finally:
        ground.close()


def test_restart_restores_counters_and_open_loss_without_reset(resident):
    owner = resident
    owner._tick()
    target = next(iter(owner._heartbeat_fleet_targets().values()))
    now = datetime.now(timezone.utc)
    for offset in range(3):
        owner._on_fleet_ping_sample(target, sample(target.target_ip, at=now + timedelta(seconds=offset), ok=False))
    owner.close()
    old_loss = owner.repository.list_ping_loss_intervals(HEARTBEAT_STREAM_ID)[0]
    next_owner = HeartbeatSupervisor(owner.paths, site_id=owner.site_id, repository=owner.repository,
                                    base_query=SimpleNamespace())
    next_owner._inventory_refresh_at = float("inf")
    install_runner(next_owner)
    try:
        next_owner._tick()
        assert next_owner._heartbeat_engine.snapshot("mr-0").ip_states[0].sent_count == 3
        next_owner._on_fleet_ping_sample(target, sample(target.target_ip, at=now + timedelta(seconds=10)))
        next_owner._persist_heartbeat_state(at=now + timedelta(seconds=10))
        rows = owner.repository.list_ping_loss_intervals(HEARTBEAT_STREAM_ID)
        assert len(rows) == 1
        assert rows[0]["event_key"] == old_loss["event_key"]
        assert rows[0]["state"] == "RECOVERED"
        assert rows[0]["loss_count"] == 3
        assert rows[0]["duration_seconds"] == pytest.approx(10, abs=0.002)
    finally:
        next_owner.close()


def test_upgrade_is_idempotent_preserves_runs_and_clear_does_not_resurrect(resident):
    owner = resident
    repo = owner.repository
    old = "old-run"
    repo.upsert_heartbeat_snapshot(old, {"mr_uuid": "mr-0", "status": "ONLINE"}, entity_type="MR", entity_id="mr-0")
    now = datetime.now(timezone.utc)
    for key in ("heartbeat:mr-0:198.18.0.1", "quick_ping:test:198.18.0.1"):
        tracker = PingLossTracker(key)
        event = tracker.observe(success=False, at=now)
        repo.apply_ping_loss_events([{**event, "run_id": old, "mr_id": "mr-0", "target_ip": "198.18.0.1"}])
    repo.migrate_resident_heartbeat(HEARTBEAT_STREAM_ID)
    repo.migrate_resident_heartbeat(HEARTBEAT_STREAM_ID)
    assert len(repo.list_heartbeat_snapshots(old)) == 1
    assert len(repo.list_ping_loss_intervals(old)) == 2
    assert len(repo.list_ping_loss_intervals(HEARTBEAT_STREAM_ID)) == 1
    assert len(repo.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID)) == 1
    repo.save_heartbeat_config(HeartbeatConfigDTO(enabled=False))
    owner.apply_inventory_action("CLEAR_DATA", expected_revision=repo.heartbeat_inventory_state()["revision"])
    repo.migrate_resident_heartbeat(HEARTBEAT_STREAM_ID)
    assert repo.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID) == []


def test_saved_disable_cannot_clear_until_workers_have_stopped(resident):
    owner = resident
    owner._tick()
    config = owner.repository.get_heartbeat_config()
    config.enabled = False
    owner.repository.save_heartbeat_config(config)
    revision = owner.repository.heartbeat_inventory_state()["revision"]
    with pytest.raises(ValueError, match="HEARTBEAT_MONITORING_ACTIVE"):
        owner.apply_inventory_action("CLEAR_DATA", expected_revision=revision)
    owner._tick()
    owner.apply_inventory_action("CLEAR_DATA", expected_revision=revision)
    config.enabled = True
    owner.repository.save_heartbeat_config(config)
    owner._tick()
    assert owner._heartbeat_engine.snapshot("mr-0").ip_states[0].sent_count == 0


@pytest.mark.parametrize("ending", ["stop", "window_end", "error"])
def test_ground_run_lifecycle_does_not_stop_resident(resident, monkeypatch, ending):
    owner = resident
    install_runner(owner, emit=True)
    clock = [datetime.fromisoformat("2026-11-10T08:00:00+08:00")]
    ground = GroundUnattendedSupervisor(
        owner.paths, site_id=owner.site_id, repository=owner.repository,
        base_query=SimpleNamespace(), mesh_query=SimpleNamespace(), vehicle_query=SimpleNamespace(),
        now_provider=lambda: clock[0],
    )
    ground.heartbeat = owner
    ground.fleet_ping = owner.fleet_ping
    monkeypatch.setattr(ground, "_network_profile_error", lambda *_a: None)
    monkeypatch.setattr(ground, "_start_syslog", lambda *_a: None)
    monkeypatch.setattr(ground, "_ensure_ac_resident_pollers", lambda *_a: None)
    monkeypatch.setattr(ground, "_poll_if_due", lambda *_a, **_kw: None)
    monkeypatch.setattr(ground.inventory_sync, "synchronize", lambda: SimpleNamespace(model_dump=lambda **_kw: {}))
    repo = owner.repository
    repo.save_profile(repo.get_profile().model_copy(update={"enabled": True}))
    owner.start()
    wait_for(lambda: owner.fleet_ping.sample_count >= 2)
    thread = owner._thread
    try:
        ground._tick()
        run = repo.get_active_run()
        assert run["state"] == "RUNNING"
        for action, state in (("pause", "PAUSED"), ("resume", "RUNNING")):
            before = owner.fleet_ping.sample_count
            ground.request(action)
            ground._tick()
            assert repo.get_active_run()["state"] == state
            wait_for(lambda: owner.fleet_ping.sample_count > before)
        if ending == "window_end":
            clock[0] = datetime.fromisoformat("2026-11-10T23:00:00+08:00")
        elif ending == "error":
            repo.update_run(run["run_id"], state="ERROR")
        else:
            ground.request("stop")
        ground._tick()
        if repo.get_active_run() is not None:
            ground._tick()
        assert repo.get_active_run() is None
        before = owner.fleet_ping.sample_count
        ground.close()
        wait_for(lambda: owner.fleet_ping.sample_count > before)
        assert owner._thread is thread
        assert owner.status().state == "RUNNING"
    finally:
        ground.close()


def test_heartbeat_api_validates_config_without_changing_ground_profile(tmp_path):
    app = create_app(paths=PathResolver(tmp_path / "app", tmp_path / "data"))
    repo = app.state.ground_unattended_repository
    before = repo.get_profile()
    prefix = "/api/rail-transit/ground-unattended/heartbeat"
    with TestClient(app) as client:
        config = client.get(prefix + "/config").json()
        for field, value in (("interval_ms", 99), ("timeout_ms", 60001), ("shard_size", 1), ("backup_policy", "invalid")):
            assert client.put(prefix + "/config", json={**config, field: value}).status_code == 422
        response = client.put(prefix + "/config", json={**config, "enabled": False, "interval_ms": 2000})
        assert response.status_code == 200, response.text
        wait_for(lambda: app.state.heartbeat_supervisor.status().state == "DISABLED")
        runtime = client.get(prefix + "/runtime").json()
        assert runtime["enabled"] is False
        assert runtime["process_count"] == 0
        assert client.get(prefix + "/config").json()["interval_ms"] == 2000
        assert repo.get_profile() == before


def test_site_switch_closes_old_heartbeat_and_shutdown_closes_new(tmp_path):
    token = "heartbeat-site-switch-test-token"
    app = create_app(RuntimeMode.DESKTOP, paths=PathResolver(tmp_path / "app", tmp_path / "data"), desktop_session_token=token)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-NetConsole-Session": token}) as client:
        wait_for(lambda: app.state.unattended_ready)
        old = app.state.heartbeat_supervisor
        wait_for(lambda: old.running)
        app.state.site_application_service.create_site("line-2", "二号线")
        response = client.post("/api/v1/sites/line-2/activate", json={"confirmed": True})
        assert response.status_code == 200, response.text
        new = app.state.heartbeat_supervisor
        assert new is not old and new.site_id == "line-2"
        wait_for(lambda: new.running)
        assert not old.running and old.fleet_ping.process_count == 0
    assert not new.running and new.fleet_ping.process_count == 0


def test_snapshot_sqlite_failure_retains_dirty_records_and_recovers(resident, monkeypatch):
    owner = resident
    owner._tick()
    target = next(iter(owner._heartbeat_fleet_targets().values()))
    owner._on_fleet_ping_sample(target, sample(target.target_ip))
    original = owner.repository.upsert_heartbeat_snapshots
    monkeypatch.setattr(owner.repository, "upsert_heartbeat_snapshots", lambda *_a, **_kw: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    with pytest.raises(sqlite3.OperationalError):
        owner._persist_heartbeat_state(at=datetime.now(timezone.utc))
    assert "mr-0" in owner._heartbeat_dirty_mrs
    monkeypatch.setattr(owner.repository, "upsert_heartbeat_snapshots", original)
    owner._persist_heartbeat_state(at=datetime.now(timezone.utc))
    row = owner.repository.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID, entity_type="MR")[0]
    assert row["snapshot"]["ip_states"][0]["sent_count"] == 1


@pytest.mark.parametrize("dual", [False, True])
def test_400_mr_concurrent_callbacks_preserve_counts_and_loss(resident, dual, capsys):
    owner = resident
    seed(owner.repository, count=400, dual=dual)
    owner._tick()
    targets = list(owner._heartbeat_fleet_targets().values())
    assert len(targets) == (800 if dual else 400)
    assert len({target.target_ip for target in targets}) == len(targets)
    started = time.perf_counter()
    cpu_started = time.process_time()
    tracemalloc.start()
    now = datetime.now(timezone.utc)
    queue_peak = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        for offset, ok in enumerate((False, False, True)):
            list(pool.map(lambda target: owner._on_fleet_ping_sample(
                target, sample(target.target_ip, at=now + timedelta(seconds=offset), ok=ok)), targets))
            queue_peak = max(queue_peak, len(owner._heartbeat_pending_loss_events))
    callback_seconds = time.perf_counter() - started
    persist_started = time.perf_counter()
    while owner._heartbeat_dirty_mrs or owner._heartbeat_dirty_trains or owner._heartbeat_pending_loss_events:
        owner._persist_heartbeat_state(at=now + timedelta(seconds=3))
    persist_seconds = time.perf_counter() - persist_started
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rows = owner.repository.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID, entity_type="MR")
    assert len(rows) == 400
    assert sum(ip["sent_count"] for row in rows for ip in row["snapshot"]["ip_states"]) == len(targets) * 3
    losses = owner.repository.list_ping_loss_intervals(HEARTBEAT_STREAM_ID, limit=2000)
    assert len(losses) == len(targets)
    assert all(row["loss_count"] == 2 and row["state"] == "RECOVERED" for row in losses)
    assert queue_peak <= 4096
    metrics = {
        "mrs": 400, "ips": len(targets), "samples": len(targets) * 3,
        "callback_seconds": round(callback_seconds, 4), "persist_seconds": round(persist_seconds, 4),
        "cpu_seconds": round(time.process_time() - cpu_started, 4),
        "python_memory_current_bytes": current, "python_memory_peak_bytes": peak,
        "loss_queue_peak": queue_peak, "loss_records": len(losses),
        "shards": owner.fleet_ping.process_count, "threads": threading.active_count(),
        "duplicate_ips": 0,
    }
    with capsys.disabled():
        print("R2_2_CALLBACK_METRICS " + json.dumps(metrics, sort_keys=True))
