from __future__ import annotations

import threading
import gc
import tracemalloc
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from netconsole.services.ground_unattended.fleet_ping import FleetPingTarget
from netconsole.services.ground_unattended.heartbeat_state import (
    HeartbeatMrSnapshot,
    HeartbeatIpObservation,
    HeartbeatStateEngine,
    HeartbeatTarget,
    TrainConnectivityAggregator,
)
from netconsole.services.ground_unattended.supervisor import (
    GroundUnattendedSupervisor,
    _merge_heartbeat_targets,
)


UTC = timezone.utc


def test_heartbeat_targets_keep_inventory_identity_over_stale_ac_data() -> None:
    def target(ip: str, mr: str, *, ap: str = "") -> FleetPingTarget:
        return FleetPingTarget(ip, "train-1", "1", mr, "CT", current_ap_name=ap)

    inventory = {
        "192.0.2.1": target("192.0.2.1", "mr-1"),
        "192.0.2.2": target("192.0.2.2", "mr-2"),
        "192.0.2.3": target("192.0.2.3", "mr-3"),
    }
    supplemental = {
        "192.0.2.1": target("192.0.2.1", "wrong-mr", ap="stale"),
        "192.0.2.2": target("192.0.2.2", "mr-2", ap="current"),
        "192.0.2.4": target("192.0.2.4", "removed-mr"),
    }

    merged = _merge_heartbeat_targets(inventory, supplemental)

    assert merged["192.0.2.1"] == inventory["192.0.2.1"]
    assert merged["192.0.2.2"].current_ap_name == "current"
    assert merged["192.0.2.3"] == inventory["192.0.2.3"]
    assert "192.0.2.4" not in merged


def _at(seconds: float) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def _engine(*ips: str) -> HeartbeatStateEngine:
    engine = HeartbeatStateEngine(sample_stale_seconds=5)
    engine.configure_targets(
        [HeartbeatTarget("mr-1", "train-1", "CT", tuple(ips))]
    )
    engine.set_engine_state("RUNNING", at=_at(0))
    return engine


def test_arriving_probe_cannot_bridge_a_sampler_pause() -> None:
    for live in (False, True):
        engine = _engine("192.0.2.1")
        def sample(second: int, success: bool) -> None:
            if live:
                engine.record_observation("mr-1", HeartbeatIpObservation("192.0.2.1", success), at=_at(second))
            else:
                engine.record_cycle("mr-1", {"192.0.2.1": success}, at=_at(second))
        sample(0, True)
        sample(1, False)
        sample(100, False)  # callback can arrive before the supervisor's stale tick
        assert engine.snapshot("mr-1").status != "OFFLINE"
        assert engine.snapshot("mr-1").unreachable_since == _at(100)
        for second in range(101, 111):
            sample(second, False)
        assert engine.snapshot("mr-1").status == "OFFLINE"


def test_reconfigured_address_and_duplicate_ip_fail_closed() -> None:
    engine = _engine("192.0.2.1")
    engine.record_cycle("mr-1", {"192.0.2.1": True}, at=_at(0))
    engine.configure_targets([HeartbeatTarget("mr-1", "train-1", "CT", ("192.0.2.2",))])
    assert engine.snapshot("mr-1").status == "UNKNOWN"
    engine.configure_targets([
        HeartbeatTarget("mr-1", "train-1", "CT", ("192.0.2.2",)),
        HeartbeatTarget("mr-2", "train-1", "CW", ("192.0.2.2", "192.0.2.3")),
    ])
    assert engine.snapshot("mr-1").ip_states == ()
    assert [state.ip for state in engine.snapshot("mr-2").ip_states] == ["192.0.2.3"]


def test_train_membership_reconciliation_removes_departed_endpoint() -> None:
    engine = _engine("192.0.2.1")
    engine.record_cycle("mr-1", {"192.0.2.1": True}, at=_at(0))
    trains = TrainConnectivityAggregator()
    trains.update(engine.snapshot("mr-1"), at=_at(0))
    trains.reconcile_targets([])
    assert trains.evaluate(at=_at(1)) == ()
    assert trains.snapshot("train-1") is None


def test_live_observations_require_consecutive_recovery_successes() -> None:
    engine = _engine("192.0.2.1")
    for second in range(11):
        engine.record_observation(
            "mr-1", HeartbeatIpObservation("192.0.2.1", False), at=_at(second)
        )
    assert engine.snapshot("mr-1").status == "OFFLINE"
    for second, success in [(11, True), (12, False), (13, True)]:
        engine.record_observation(
            "mr-1", HeartbeatIpObservation("192.0.2.1", success), at=_at(second)
        )
    assert engine.snapshot("mr-1").status == "RECOVERING"
    engine.record_observation(
        "mr-1", HeartbeatIpObservation("192.0.2.1", True), at=_at(14)
    )
    assert engine.snapshot("mr-1").status == "ONLINE"


def test_24_hour_virtual_heartbeat_keeps_state_and_events_bounded() -> None:
    events = []
    engine = HeartbeatStateEngine(event_sink=events.append)
    engine.configure_targets([
        HeartbeatTarget("ct", "train-1", "CT", ("192.0.2.1",)),
        HeartbeatTarget("cw", "train-1", "CW", ("192.0.2.2",)),
    ])
    engine.set_engine_state("RUNNING", at=_at(0))
    trains = TrainConnectivityAggregator(event_sink=events.append)
    tracemalloc.start()
    try:
        baseline = 0
        for second in range(86_400):
            timestamp = _at(second)
            engine.record_cycle("ct", {"192.0.2.1": (True, 1.0)}, at=timestamp)
            engine.record_cycle("cw", {"192.0.2.2": (True, 2.0)}, at=timestamp)
            if second % 10 == 0:
                for snapshot in engine.snapshots():
                    trains.update(snapshot, at=timestamp)
            if second == 3_600:
                gc.collect()
                baseline = tracemalloc.get_traced_memory()[0]
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0]
        assert retained - baseline < 1_048_576
        assert len(engine.snapshots()) == 2
        assert all(snapshot.ip_states[0].sent_count == 86_400 for snapshot in engine.snapshots())
        assert len(events) <= 5
    finally:
        tracemalloc.stop()


def test_dual_ip_any_success_keeps_mr_online_and_tracks_each_ip() -> None:
    engine = _engine("192.0.2.1", "192.0.2.2")

    engine.record_cycle(
        "mr-1", {"192.0.2.1": (True, 2.0), "192.0.2.2": (False, None)}, at=_at(0)
    )
    snapshot = engine.snapshot("mr-1")

    assert snapshot.status == "ONLINE"
    assert snapshot.ip_states[0].received_count == 1
    assert snapshot.ip_states[1].lost_count == 1


def test_mr_offline_after_ten_seconds_and_recovers_after_two_successes() -> None:
    engine = _engine("192.0.2.1", "192.0.2.2")
    engine.record_cycle(
        "mr-1", {"192.0.2.1": True, "192.0.2.2": True}, at=_at(0)
    )
    engine.record_cycle(
        "mr-1", {"192.0.2.1": False, "192.0.2.2": False}, at=_at(1)
    )
    for second in range(2, 10):
        engine.record_cycle(
            "mr-1", {"192.0.2.1": False, "192.0.2.2": False}, at=_at(second)
        )
    assert engine.snapshot("mr-1").status == "OFFLINE_PENDING"

    transitions = engine.evaluate(at=_at(10))
    assert engine.snapshot("mr-1").status == "OFFLINE"
    assert [item.event_type for item in transitions] == ["mr_offline"]

    first = engine.record_cycle(
        "mr-1", {"192.0.2.1": True, "192.0.2.2": False}, at=_at(11)
    )
    assert engine.snapshot("mr-1").status == "RECOVERING"
    assert [item.event_type for item in first] == ["mr_recovering"]
    second = engine.record_cycle(
        "mr-1", {"192.0.2.1": True, "192.0.2.2": False}, at=_at(12)
    )
    assert engine.snapshot("mr-1").status == "ONLINE"
    assert [item.event_type for item in second] == ["mr_recovered"]


def test_sampling_engine_gap_becomes_unknown_without_device_offline_event() -> None:
    events = []
    engine = HeartbeatStateEngine(event_sink=events.append)
    engine.configure_targets(
        [HeartbeatTarget("mr-1", "train-1", "CT", ("192.0.2.1",))]
    )
    engine.set_engine_state("RUNNING", at=_at(0))
    engine.record_cycle("mr-1", {"192.0.2.1": True}, at=_at(0))

    transitions = engine.set_engine_state("DEGRADED", at=_at(1))

    assert engine.snapshot("mr-1").status == "UNKNOWN"
    assert [item.event_type for item in transitions] == ["heartbeat_engine_unavailable"]
    assert all(item.event_type != "mr_offline" for item in events)


def _mr(
    *, role: str, status: str, unreachable_since: datetime | None = None
) -> HeartbeatMrSnapshot:
    return HeartbeatMrSnapshot(
        mr_uuid=f"mr-{role.lower()}",
        train_id="train-1",
        role=role,
        status=status,
        unreachable_since=unreachable_since,
        last_success_at=None,
        last_recovery_at=None,
        consecutive_recovery_successes=0,
        engine_state="RUNNING",
        ip_states=(),
    )


def test_train_offline_uses_intersection_and_resets_when_one_side_recovers() -> None:
    aggregator = TrainConnectivityAggregator()
    aggregator.update(
        _mr(role="CT", status="OFFLINE_PENDING", unreachable_since=_at(0)), at=_at(0)
    )
    pending, _ = aggregator.update(
        _mr(role="CW", status="OFFLINE_PENDING", unreachable_since=_at(60)), at=_at(60)
    )
    assert pending.status == "BOTH_UNREACHABLE_PENDING"
    assert pending.both_unreachable_since == _at(60)

    pending, _ = aggregator.update(
        _mr(role="CT", status="OFFLINE_PENDING", unreachable_since=_at(0)), at=_at(179)
    )
    assert pending.status == "BOTH_UNREACHABLE_PENDING"

    offline, events = aggregator.update(
        _mr(role="CW", status="OFFLINE", unreachable_since=_at(60)), at=_at(180)
    )
    assert offline.status == "TRAIN_OFFLINE"
    assert [item.event_type for item in events] == ["train_offline"]

    recovered, events = aggregator.update(
        _mr(role="CT", status="ONLINE"), at=_at(181)
    )
    assert recovered.status == "CT_ONLY"
    assert recovered.both_unreachable_since is None
    assert [item.event_type for item in events] == ["train_recovered"]


def test_train_sampling_gap_keeps_alarm_open_until_reachability_returns() -> None:
    events = []
    aggregator = TrainConnectivityAggregator(event_sink=events.append)
    for role in ("CT", "CW"):
        aggregator.update(
            _mr(role=role, status="OFFLINE", unreachable_since=_at(0)), at=_at(120)
        )
    assert aggregator.snapshot("train-1").status == "TRAIN_OFFLINE"
    assert [event.event_type for event in events].count("train_offline") == 1

    # An unavailable sampler cannot prove recovery of a previously offline train.
    for role in ("CT", "CW"):
        aggregator.update(_mr(role=role, status="UNKNOWN"), at=_at(121))
    assert aggregator.snapshot("train-1").status == "UNKNOWN"
    assert "train_recovered" not in [event.event_type for event in events]

    for role in ("CT", "CW"):
        aggregator.update(
            _mr(role=role, status="OFFLINE_PENDING", unreachable_since=_at(122)),
            at=_at(122),
        )
    assert aggregator.snapshot("train-1").status == "BOTH_UNREACHABLE_PENDING"
    assert "train_recovered" not in [event.event_type for event in events]
    aggregator.evaluate(at=_at(242))
    assert aggregator.snapshot("train-1").status == "TRAIN_OFFLINE"
    assert [event.event_type for event in events].count("train_offline") == 1

    recovered, transitions = aggregator.update(
        _mr(role="CT", status="RECOVERING"), at=_at(243)
    )
    assert recovered.status == "CT_ONLY"
    assert [event.event_type for event in transitions] == ["train_recovered"]
    aggregator.update(_mr(role="CT", status="ONLINE"), at=_at(244))
    assert [event.event_type for event in events].count("train_recovered") == 1


def test_train_with_one_member_does_not_fabricate_dual_endpoint_offline() -> None:
    aggregator = TrainConnectivityAggregator()
    snapshot, _ = aggregator.update(
        _mr(role="CT", status="OFFLINE", unreachable_since=_at(0)), at=_at(120)
    )

    assert snapshot.status == "SINGLE_OFFLINE"


def test_snapshots_are_persistence_ready() -> None:
    engine = _engine("192.0.2.1")
    engine.record_cycle("mr-1", {"192.0.2.1": (True, 1.5)}, at=_at(0))

    payload = engine.snapshot("mr-1").to_payload()

    assert payload["status"] == "ONLINE"
    assert payload["ip_states"][0]["avg_rtt_ms"] == 1.5


def test_restore_snapshots_keeps_history_but_drops_live_outage_evidence() -> None:
    events = []
    engine = HeartbeatStateEngine(clock=lambda: _at(20), event_sink=events.append)
    engine.configure_targets(
        [HeartbeatTarget("mr-1", "train-1", "CT", ("192.0.2.1",))]
    )
    payload = {
        "status": "OFFLINE",
        "last_success_at": _at(0).isoformat(),
        "last_recovery_at": "2026-01-01T00:00:10Z",
        "offline_event_open": True,
        "ip_states": [
            {
                "ip": "192.0.2.1",
                "sent_count": 12,
                "received_count": 7,
                "lost_count": 5,
                "min_rtt_ms": 1.0,
                "avg_rtt_ms": 2.0,
                "max_rtt_ms": 3.0,
                "last_probe_at": "malformed timestamp",
                "last_success_at": _at(0).isoformat(),
                "unreachable_since": _at(1).isoformat(),
            }
        ],
    }

    transitions = engine.restore_snapshots(
        [{"entity_id": "mr-1", "snapshot": payload}]
    )

    snapshot = engine.snapshot("mr-1")
    ip = snapshot.ip_states[0]
    assert snapshot.status == "UNKNOWN"
    assert snapshot.engine_state == "DEGRADED"
    assert snapshot.last_success_at == _at(0)
    assert snapshot.last_recovery_at == _at(10)
    assert snapshot.offline_event_open
    assert snapshot.previously_confirmed_offline
    assert (ip.sent_count, ip.received_count, ip.lost_count) == (12, 7, 5)
    assert ip.avg_rtt_ms == 2.0
    assert ip.last_probe_at is None
    assert ip.last_success_at == _at(0)
    assert ip.unreachable_since is None
    assert len(transitions) == 1
    assert transitions[0].event_type == "heartbeat_sampling_interrupted"
    assert transitions[0].occurred_at == _at(20)
    assert events == transitions


def test_stopped_fleet_ping_callback_does_not_mutate_heartbeat_state() -> None:
    engine = HeartbeatStateEngine()
    engine.configure_targets(
        [HeartbeatTarget("mr-1", "train-1", "CT", ("192.0.2.1",))]
    )
    engine.set_engine_state("RUNNING", at=_at(0))
    engine.record_cycle("mr-1", {"192.0.2.1": True}, at=_at(0))
    repository = SimpleNamespace(
        add_health_event=Mock(),
        upsert_heartbeat_snapshot=Mock(),
    )
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._heartbeat_lock = threading.RLock()
    supervisor._heartbeat_run_id = "run-1"
    supervisor._heartbeat_engine = engine
    supervisor._heartbeat_dirty_mrs = set()
    supervisor._heartbeat_dirty_trains = set()
    supervisor._heartbeat_force_persist = False
    supervisor._heartbeat_pending_events = []
    supervisor._heartbeat_event_flush_lock = threading.Lock()
    supervisor._train_connectivity = TrainConnectivityAggregator()
    supervisor.repository = repository
    supervisor.now_provider = lambda: _at(1)

    GroundUnattendedSupervisor._quiesce_heartbeat(supervisor)

    GroundUnattendedSupervisor._on_fleet_ping_sample(
        supervisor,
        FleetPingTarget(
            target_ip="192.0.2.1",
            train_id="train-1",
            train_no="T1",
            mr_id="mr-1",
            mr_position_code="CT",
        ),
        SimpleNamespace(ts=_at(1).isoformat(), ok=False, rtt_ms=None),
    )

    snapshot = engine.snapshot("mr-1")
    assert snapshot.engine_state == "STOPPED"
    assert snapshot.status == "UNKNOWN"
    assert snapshot.ip_states[0].sent_count == 1
    persisted_mr = next(
        call.args[1]
        for call in repository.upsert_heartbeat_snapshot.call_args_list
        if call.kwargs["entity_type"] == "MR"
    )
    persisted_train = next(
        call.args[1]
        for call in repository.upsert_heartbeat_snapshot.call_args_list
        if call.kwargs["entity_type"] == "TRAIN"
    )
    assert persisted_mr["engine_state"] == "STOPPED"
    assert persisted_mr["status"] == "UNKNOWN"
    assert persisted_train["status"] == "UNKNOWN"
    assert not supervisor._heartbeat_dirty_mrs
    assert not supervisor._heartbeat_dirty_trains
    assert not getattr(supervisor, "_heartbeat_pending_loss_events", ())
    assert not getattr(supervisor, "_heartbeat_loss_trackers", {})
    repository.add_health_event.assert_not_called()


def test_train_offline_timer_advances_during_heartbeat_refresh() -> None:
    engine = HeartbeatStateEngine()
    engine.configure_targets(
        [
            HeartbeatTarget("mr-ct", "train-1", "CT", ("192.0.2.1",)),
            HeartbeatTarget("mr-cw", "train-1", "CW", ("192.0.2.2",)),
        ]
    )
    engine.set_engine_state("RUNNING", at=_at(0))
    engine.record_cycle("mr-ct", {"192.0.2.1": False}, at=_at(0))
    engine.record_cycle("mr-cw", {"192.0.2.2": False}, at=_at(0))
    train_connectivity = TrainConnectivityAggregator()
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._heartbeat_engine = engine
    supervisor._train_connectivity = train_connectivity
    supervisor._heartbeat_dirty_mrs = set()
    supervisor._heartbeat_dirty_trains = set()

    GroundUnattendedSupervisor._refresh_train_heartbeat_snapshots_locked(
        supervisor, engine.snapshots(), at=_at(0)
    )
    assert train_connectivity.snapshot("train-1").status == "BOTH_UNREACHABLE_PENDING"

    supervisor._heartbeat_dirty_trains.clear()
    GroundUnattendedSupervisor._refresh_train_heartbeat_snapshots_locked(
        supervisor, (), at=_at(120)
    )

    assert train_connectivity.snapshot("train-1").status == "TRAIN_OFFLINE"
    assert "train-1" in supervisor._heartbeat_dirty_trains


def test_occasional_loss_does_not_raise_offline_and_single_ip_is_monitored() -> None:
    events = []
    engine = HeartbeatStateEngine(event_sink=events.append)
    engine.configure_targets([HeartbeatTarget("mr-1", "train-1", "CT", ("192.0.2.1",))])
    engine.set_engine_state("RUNNING", at=_at(0))
    for second in range(30):
        engine.record_cycle("mr-1", {"192.0.2.1": (second % 7 != 3, 1.0)}, at=_at(second))
    assert engine.snapshot("mr-1").status == "ONLINE"
    assert engine.snapshot("mr-1").ip_states[0].sent_count == 30
    assert not any(event.event_type == "mr_offline" for event in events)


def test_ct_offline_cw_online_keeps_train_partially_online() -> None:
    aggregator = TrainConnectivityAggregator()
    aggregator.update(_mr(role="CT", status="OFFLINE", unreachable_since=_at(0)), at=_at(150))
    snapshot, events = aggregator.update(_mr(role="CW", status="ONLINE"), at=_at(150))
    assert snapshot.status == "CW_ONLY"
    assert snapshot.both_unreachable_since is None
    assert not any(event.event_type == "train_offline" for event in events)
