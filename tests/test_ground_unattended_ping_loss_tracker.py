from datetime import datetime, timedelta, timezone
from collections import deque
from unittest.mock import Mock

import pytest

from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.heartbeat_state import HeartbeatTarget
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor

from netconsole.services.ground_unattended.ping_loss import PingLossTracker
from netconsole.services.ground_unattended.task_scheduler import GroundTaskScheduler
from netconsole.services.ground_unattended.ping_loss import acknowledge_loss_events, enqueue_loss_event


def test_repeated_outages_preserve_history_and_recover_after_repository_reopen(tmp_path):
    repo = GroundUnattendedRepository(tmp_path / 'ground.sqlite', site_id='demo')
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tracker = PingLossTracker('heartbeat:mr-1:127.0.0.1')
    def observe(success, seconds, ap):
        event = tracker.observe(success=success, at=start + timedelta(seconds=seconds),
                                metadata={'ap_name': ap, 'station': ap + '-station'})
        return {**event, 'run_id': 'run-1', 'mr_id': 'mr-1', 'target_ip': '127.0.0.1'}
    first = observe(False, 0, 'AP-A')
    recovered = observe(True, 1, 'AP-B')
    second = observe(False, 2, 'AP-C')
    assert first['event_key'] != second['event_key']
    batch = [first, recovered, second]
    repo.apply_ping_loss_events(batch)
    repo.apply_ping_loss_events(batch)
    repo = GroundUnattendedRepository(tmp_path / 'ground.sqlite', site_id='demo')
    rows = repo.list_ping_loss_intervals('run-1')
    assert len(rows) == 2
    assert rows[1]['state'] == 'RECOVERED'
    assert (rows[1]['ap_name'], rows[1]['station']) == ('AP-A', 'AP-A-station')
    tracker.restore(repo.list_open_ping_loss_intervals('run-1')[0])
    final = observe(True, 4, 'AP-D')
    assert final['event_key'] == second['event_key']
    repo.apply_ping_loss_events([final])
    assert not repo.list_open_ping_loss_intervals('run-1')
    assert repo.list_ping_loss_intervals('run-1')[0]['loss_count'] == 1


def test_refresh_retains_live_tracker_and_prunes_removed_target():
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor.repository = Mock()
    key = 'heartbeat:mr-1:127.0.0.1'
    tracker = PingLossTracker(key)
    tracker.observe(success=True, at=datetime.now(timezone.utc), metadata={'station': 'S1'})
    supervisor._heartbeat_loss_trackers = {key: tracker, 'removed': PingLossTracker('removed')}
    supervisor._restore_heartbeat_loss_trackers('run-1', [HeartbeatTarget('mr-1', 'train-1', 'CT', ('127.0.0.1',))])
    assert supervisor._heartbeat_loss_trackers == {key: tracker}
    assert tracker.last_success['station'] == 'S1'
    supervisor.repository.list_open_ping_loss_intervals.assert_not_called()


def test_pending_loss_updates_are_bounded_and_concurrent_ack_retains_newer_update():
    pending = deque()
    enqueue_loss_event(pending, {'event_key': 'a', 'action': 'OPEN', 'loss_count': 1})
    batch = list(pending)
    for count in range(2, 10000):
        enqueue_loss_event(pending, {'event_key': 'a', 'action': 'UPDATE', 'loss_count': count})
    assert len(pending) == 1
    assert pending[0]['action'] == 'OPEN'
    acknowledge_loss_events(pending, batch)
    assert pending[0]['loss_count'] == 9999
    enqueue_loss_event(pending, {'event_key': 'a', 'action': 'RECOVER'}, capacity=2)
    with pytest.raises(RuntimeError, match='BACKLOG_FULL'):
        enqueue_loss_event(pending, {'event_key': 'b', 'action': 'OPEN'}, capacity=2)
    assert len(pending) == 2


def test_interleaved_loss_updates_coalesce_and_rejected_recovery_is_retryable() -> None:
    from collections import deque
    import pytest

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = deque()
    trackers = [PingLossTracker(str(index)) for index in range(42)]
    for tick in range(100):
        for tracker in trackers:
            tracker.enqueue_observation(pending, success=False, at=start + timedelta(seconds=tick))
    assert len(pending) == 42
    assert all(event["loss_count"] == 100 for event in pending)
    tracker = trackers[0]
    with pytest.raises(RuntimeError, match="BACKLOG_FULL"):
        tracker.enqueue_observation(pending, success=True, at=start + timedelta(seconds=101), capacity=42)
    assert tracker.state is not None
    assert tracker.state["loss_count"] == 100
    pending.clear()
    tracker.enqueue_observation(pending, success=True, at=start + timedelta(seconds=102))
    assert pending[0]["action"] == "RECOVER"
    assert tracker.state is None


def test_loss_tracker_records_episode_and_recovery_context() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tracker = PingLossTracker("quick_ping:run-1:192.0.2.1")
    opened = tracker.observe(success=False, at=start, metadata={"ap_name": "AP-A", "station": "S1", "section": "K1"})
    assert opened["action"] == "OPEN"
    assert opened["loss_count"] == 1
    updated = tracker.observe(success=False, at=start + timedelta(seconds=2), metadata={"ap_name": "AP-A", "station": "S1", "section": "K1"})
    assert updated["loss_count"] == 2
    switched = tracker.observe(success=False, at=start + timedelta(seconds=3), metadata={"ap_name": "AP-B", "station": "S2", "section": "K2"})
    assert switched["ap_name"] == "AP-A"
    assert switched["station"] == "S1"
    assert switched["duration_seconds"] == 3
    recovered = tracker.observe(success=True, at=start + timedelta(seconds=5), metadata={"ap_name": "AP-B", "station": "S2", "section": "K2"})
    assert recovered["action"] == "RECOVER"
    assert recovered["duration_seconds"] == 5
    assert recovered["last_success_station"] == "S2"
    assert tracker.state is None


def test_scheduler_keeps_domains_bounded_and_deduplicated() -> None:
    scheduler = GroundTaskScheduler(capacities={"HEARTBEAT": 1})
    seen: list[str] = []
    first = scheduler.submit("HEARTBEAT", lambda: seen.append("first"), priority=10, dedupe_key="same")
    assert scheduler.submit("HEARTBEAT", lambda: seen.append("duplicate"), dedupe_key="same") == first
    try:
        scheduler.submit("HEARTBEAT", lambda: None)
    except RuntimeError as exc:
        assert str(exc) == "HEARTBEAT_QUEUE_FULL"
    else:
        raise AssertionError("bounded scheduler accepted a task past capacity")
    scheduler.run_once("HEARTBEAT")
    assert seen == ["first"]
    assert scheduler.snapshot()["completed_tasks"] == 1


def test_scheduler_runs_higher_priority_first_and_failed_tasks_are_observable() -> None:
    scheduler = GroundTaskScheduler(capacities={"QUICK_PING": 3})
    seen: list[str] = []
    scheduler.submit("QUICK_PING", lambda: seen.append("low"), priority=1)
    scheduler.submit("QUICK_PING", lambda: seen.append("high"), priority=10)
    scheduler.submit("QUICK_PING", lambda: (_ for _ in ()).throw(RuntimeError("boom")), priority=5)

    scheduler.run_once("QUICK_PING")
    scheduler.run_once("QUICK_PING")
    scheduler.run_once("QUICK_PING")

    assert seen == ["high", "low"]
    snapshot = scheduler.snapshot()
    assert snapshot["completed_tasks"] == 2
    assert snapshot["failed_tasks"] == 1


def test_scheduler_cancelled_entry_releases_capacity_and_stays_cancelled() -> None:
    scheduler = GroundTaskScheduler(capacities={"HEARTBEAT": 1})
    first = scheduler.submit("HEARTBEAT", lambda: (_ for _ in ()).throw(AssertionError("cancelled callback ran")))
    assert scheduler.cancel(first)
    second = scheduler.submit("HEARTBEAT", lambda: None)
    assert second != first
    scheduler.run_once("HEARTBEAT")
    assert scheduler.snapshot()["cancelled_tasks"] == 1
    assert scheduler.snapshot()["completed_tasks"] == 1
