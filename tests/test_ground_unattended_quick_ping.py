from __future__ import annotations

import json
import gzip
import base64
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.services.ground_unattended.quick_ping import (
    QuickPingConfig,
    QuickPingError,
    QuickPingRun,
    QuickPingService,
    QuickPingTarget,
)


def _sample(target: str, *, ok: bool, rtt: float | None, seq: int) -> FpingV5Sample:
    return FpingV5Sample(
        ts=f"2026-11-06T10:00:0{seq}+08:00",
        target=target,
        seq=seq,
        ok=ok,
        rtt_ms=rtt,
        timeout_ms=1000,
        size=64 if ok else None,
        error="" if ok else "timeout",
        backend="test",
        raw_type="resp" if ok else "timeout",
        raw={"seq": seq},
    )


def _target(ip: str = "192.0.2.10", *, mr_id: str = "mr-1", role: str = "CT") -> QuickPingTarget:
    return QuickPingTarget(
        target_ip=ip,
        train_id="train-1",
        train_no="001",
        mr_id=mr_id,
        mr_name="MR-1",
        mr_role=role,
        address_role="PRIMARY",
    )


def _wait_for(service: QuickPingService, run_id: str, states: set[str], timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = service.status(run_id)
        if run is not None and run.state in states and (
            run.state in {"RUNNING", "STOPPING"} or run.ended_at
        ):
            if run.ended_at and run._thread is not None:
                run._thread.join(timeout=2)
                assert not run._thread.is_alive()
            return run
        time.sleep(0.01)
    run = service.status(run_id)
    assert run is not None
    raise AssertionError(f"run did not enter {states}: {run.state}")


def test_quick_ping_defaults_and_input_validation() -> None:
    config = QuickPingConfig()
    assert (config.interval_ms, config.timeout_ms, config.packet_size) == (200, 1000, 64)
    assert config.duration_seconds is None

    with pytest.raises(QuickPingError, match="间隔"):
        QuickPingConfig(interval_ms=0)
    with pytest.raises(QuickPingError, match="目标 IP"):
        QuickPingTarget(target_ip="not-an-ip", mr_id="mr-1")
    with pytest.raises(QuickPingError, match="MR UUID"):
        QuickPingTarget(target_ip="192.0.2.1")


def test_duplicate_active_task_is_rejected_and_unexpected_sample_is_not_attributed(tmp_path: Path) -> None:
    entered = threading.Event()
    def runner(**kwargs):
        entered.set()
        kwargs["stop_event"].wait(2)
        yield _sample("192.0.2.99", ok=True, rtt=1, seq=1)
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    try:
        run_id = service.start(targets=[_target()])
        assert entered.wait(1)
        with pytest.raises(QuickPingError) as caught:
            service.start(targets=[_target()])
        assert caught.value.code == "QUICK_PING_DUPLICATE_ACTIVE"
        service.stop(run_id)
        assert service.status(run_id).stats.sent == 0
    finally:
        service.close()


def test_unexpected_sample_target_fails_without_corrupting_requested_mr(tmp_path: Path) -> None:
    def runner(**_):
        yield _sample("192.0.2.99", ok=True, rtt=1, seq=1)
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    try:
        run = _wait_for(service, service.start(targets=[_target()]), {"FAILED"})
        assert "unexpected" in run.error
        assert run.stats.sent == 0
        assert run.target_stats["192.0.2.10"].received == 0
    finally:
        service.close()


def test_quick_ping_adjustable_parameters_reach_runner(tmp_path: Path) -> None:
    observed = {}
    def runner(**kwargs):
        observed.update(kwargs)
        yield _sample("192.0.2.10", ok=True, rtt=2, seq=1)
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target()], config=QuickPingConfig(interval_ms=333, timeout_ms=2468, packet_size=512, duration_seconds=30))
    run = _wait_for(service, run_id, {"COMPLETED"})
    assert observed["period_ms"] == 333
    assert observed["timeout_ms"] == 2468
    assert observed["packet_size"] == 512
    assert run.config.duration_seconds == 30


def test_quick_ping_pages_full_raw_range_across_segments_and_budget(tmp_path: Path) -> None:
    start = datetime(2026, 11, 7, 1, 59, tzinfo=timezone.utc)
    def runner(**_):
        for index in range(350):
            yield replace(_sample("192.0.2.10", ok=index % 3 != 0, rtt=float(index), seq=1),
                          ts=(start + timedelta(seconds=index)).isoformat(), seq=index)
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target()])
    run = _wait_for(service, run_id, {"COMPLETED"})
    assert len(run.recent_samples) == 256
    assert len(run.segment_paths) == 2  # hour rollover
    first = service.query_samples(run_id, limit=200)
    second = service.query_samples(run_id, limit=200, cursor=first["next_cursor"])
    assert len(first["items"]) == 200 and len(second["items"]) == 150
    assert not second["has_more"]
    assert [row["sample"]["seq"] for row in first["items"] + second["items"]] == list(range(350))
    ranged = service.query_samples(run_id, target_ip="192.0.2.10", start_time="2026-11-07T10:00:00+08:00", end_time="2026-11-07T02:00:09Z")
    assert [row["sample"]["seq"] for row in ranged["items"]] == list(range(60, 70))
    budget = service.query_samples(run_id, scan_budget_bytes=1)
    assert len(budget["items"]) == 1
    assert budget["scan_budget_exhausted"]
    resumed = service.query_samples(run_id, cursor=budget["next_cursor"], limit=1)
    assert resumed["items"][0]["sample"]["seq"] == 1
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id, target_ip="192.0.2.10", cursor=budget["next_cursor"])
    assert caught.value.code == "QUICK_PING_CURSOR_INVALID"
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id, start_time="2026-11-07")
    assert caught.value.code == "QUICK_PING_TIME_INVALID"
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id, start_time="2026-11-08T00:00:00Z", end_time="2026-11-07T00:00:00Z")
    assert caught.value.code == "QUICK_PING_TIME_RANGE_INVALID"


@pytest.mark.parametrize("page_limit", [1, 1000])
def test_quick_ping_active_multi_mr_cursor_retains_appends(tmp_path: Path, page_limit: int) -> None:
    barrier = threading.Barrier(3, timeout=5)
    release = threading.Event()

    def runner(**kwargs):
        for seq in (1, 2):
            yield _sample(kwargs["target"], ok=True, rtt=1, seq=seq)
            barrier.wait()
            barrier.wait()
        release.wait(5)

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target(), _target("192.0.2.11", mr_id="mr-2")])
    try:
        barrier.wait()  # Both files contain their first sample.
        first = service.query_samples(run_id, limit=1)
        assert [(row["target_ip"], row["sample"]["seq"]) for row in first["items"]] == [("192.0.2.10", 1)]
        barrier.wait()
        barrier.wait()  # Both files have appended after the first page's EOF.
        second = first
        items = []
        for _ in range(3 if page_limit == 1 else 1):
            second = service.query_samples(run_id, cursor=second["next_cursor"], limit=page_limit)
            items.extend(second["items"])
        assert len(items) == 3
        assert {(row["target_ip"], row["sample"]["seq"]) for row in items} == {
            ("192.0.2.10", 2), ("192.0.2.11", 1), ("192.0.2.11", 2),
        }
        assert second["has_more"] and second["next_cursor"]
        with pytest.raises(QuickPingError) as caught:
            service.query_samples(run_id, cursor=second["next_cursor"], target_ip="192.0.2.10")
        assert caught.value.code == "QUICK_PING_CURSOR_INVALID"
        idle = service.query_samples(run_id, cursor=second["next_cursor"])
        assert idle["items"] == []
        barrier.wait()
        release.set()
        _wait_for(service, run_id, {"COMPLETED"})
        final = service.query_samples(run_id, cursor=idle["next_cursor"])
        assert final["items"] == [] and not final["has_more"]
    finally:
        release.set()
        barrier.abort()
        service.close()


def test_quick_ping_active_cursor_survives_many_compressed_rotations(tmp_path: Path) -> None:
    barrier = threading.Barrier(3, timeout=5)

    def runner(**kwargs):
        for sequence in range(40):
            yield replace(_sample(kwargs["target"], ok=True, rtt=1, seq=1), seq=sequence,
                          ts=(datetime(2026, 11, 7, tzinfo=timezone.utc) + timedelta(hours=sequence)).isoformat())
            barrier.wait()
            barrier.wait()

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target(), _target("192.0.2.11", mr_id="mr-2")])
    cursor, items = "", []
    try:
        for _ in range(40):
            barrier.wait()
            page = service.query_samples(run_id, cursor=cursor, limit=1)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            assert len(cursor) <= 8192
            assert len(json.loads(base64.urlsafe_b64decode(cursor))[3]) <= 32
            barrier.wait()
        run = _wait_for(service, run_id, {"COMPLETED"})
        assert len(run.segment_paths) == 80
        assert list(tmp_path.rglob("*.ndjson.gz"))
        while cursor:
            page = service.query_samples(run_id, cursor=cursor, limit=1)
            items.extend(page["items"])
            cursor = page["next_cursor"]
        assert len(items) == 80
        assert {(row["target_ip"], row["sample"]["seq"]) for row in items} == {
            (ip, sequence) for ip in ("192.0.2.10", "192.0.2.11") for sequence in range(40)
        }
    finally:
        barrier.abort()
        service.close()


def test_quick_ping_raw_guards_and_active_partial_record(tmp_path: Path) -> None:
    def runner(**_):
        yield _sample("192.0.2.10", ok=True, rtt=2, seq=1)
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target()])
    run = _wait_for(service, run_id, {"COMPLETED"})
    path = tmp_path / run.segment_paths[0]
    original = gzip.decompress(path.with_name(path.name + ".gz").read_bytes())
    path.write_bytes(original + b'{"unfinished":')
    run.state, run.ended_at = "RUNNING", ""
    page = service.query_samples(run_id)
    assert len(page["items"]) == 1 and page["has_more"]
    assert service.query_samples(run_id, cursor=page["next_cursor"])["items"] == []
    run.state, run.ended_at = "COMPLETED", "2026-11-07T00:00:00Z"
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id)
    assert caught.value.code == "QUICK_PING_RAW_CORRUPT" and caught.value.status_code == 503
    payload = json.loads(original)
    payload["received_at"] = "bad"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id)
    assert caught.value.code == "QUICK_PING_RAW_CORRUPT"
    run.segment_paths = ["../outside.ndjson"]
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id)
    assert caught.value.code == "QUICK_PING_RAW_PATH_INVALID"


@pytest.mark.parametrize("quick_fails", [False, True])
def test_quick_ping_stop_or_failure_does_not_stop_concurrent_heartbeat(tmp_path: Path, quick_fails: bool) -> None:
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
    from netconsole.services.ground_unattended.fleet_ping import FleetPingSupervisor, FleetPingTarget

    heartbeat_events = []
    def heartbeat_runner(*, targets, stop_event, **_):
        heartbeat_events.append(stop_event)
        sequence = 0
        while not stop_event.is_set():
            sequence += 1
            yield replace(_sample(targets[0], ok=True, rtt=1, seq=1), seq=sequence, ts=datetime.now(timezone.utc).isoformat())
            stop_event.wait(0.01)
    quick_started = threading.Event()
    def quick_runner(*, stop_event, **_):
        quick_started.set()
        yield _sample("192.0.2.10", ok=True, rtt=2, seq=1)
        if quick_fails:
            raise RuntimeError("quick-only failure")
        stop_event.wait(2)
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="demo")
    fleet = FleetPingSupervisor(repository=repository, site_id="demo", runner=heartbeat_runner)
    service = QuickPingService(site_id="demo", output_root=tmp_path / "quick", runner=quick_runner, repository=repository)
    fleet.start(run_id="heartbeat", run_date="2026-11-07", active_dir=tmp_path / "active", period_ms=1000, timeout_ms=4000, packet_size=64, shard_size=20, correlation_tolerance_seconds=15, switch_before_seconds=5, switch_after_seconds=5)
    try:
        fleet.update_targets([FleetPingTarget("192.0.2.10", "train-1", "001", "mr-1", "CT")])
        run_id = service.start(targets=[_target()])
        assert quick_started.wait(2)
        if quick_fails:
            _wait_for(service, run_id, {"FAILED"})
        else:
            service.stop(run_id)
            _wait_for(service, run_id, {"CANCELLED"})
        before = fleet.sample_count
        deadline = time.monotonic() + 3
        while fleet.sample_count <= before and time.monotonic() < deadline:
            time.sleep(0.01)
        assert fleet.sample_count > before
        assert heartbeat_events and all(not event.is_set() for event in heartbeat_events)
        assert fleet.process_count == 1
    finally:
        service.close()
        fleet.stop()


def test_quick_ping_collects_stats_and_writes_mr_ndjson(tmp_path: Path) -> None:
    targets = [_target("192.0.2.10", mr_id="mr-ct", role="CT"), _target("192.0.2.11", mr_id="mr-cw", role="CW")]

    def runner(**kwargs):
        assert kwargs["period_ms"] == 200
        assert kwargs["timeout_ms"] == 1000
        assert kwargs["packet_size"] == 64
        if kwargs["target"] == "192.0.2.10":
            yield _sample("192.0.2.10", ok=True, rtt=2.0, seq=1)
            yield _sample("192.0.2.10", ok=False, rtt=None, seq=2)
            yield _sample("192.0.2.10", ok=True, rtt=5.0, seq=3)
        else:
            yield _sample("192.0.2.11", ok=True, rtt=7.0, seq=4)

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=targets, run_date="2026-11-06")
    run = _wait_for(service, run_id, {"COMPLETED"})

    assert run.stats.sent == 4
    assert run.stats.received == 3
    assert run.stats.lost == 1
    assert run.stats.min_rtt_ms == 2.0
    assert run.stats.max_rtt_ms == 7.0
    assert run.stats.jitter_count == 2
    assert run.stats.max_consecutive_loss == 1
    assert len(run.segment_paths) == 2
    assert all(path.startswith("quick_ping/") for path in run.segment_paths)

    records = []
    for path in run.segment_paths:
        file_path = tmp_path / path
        assert not file_path.exists()
        with gzip.open(file_path.with_name(file_path.name + ".gz"), "rt", encoding="utf-8") as source:
            records.extend(json.loads(line) for line in source)
    assert len(records) == 4
    assert {item["quick_ping_run_id"] for item in records} == {run_id}
    assert {item["mr_id"] for item in records} == {"mr-ct", "mr-cw"}
    manifest = tmp_path / "quick_ping" / "2026-11-06" / "runs" / f"{run_id}.json"
    assert manifest.is_file()


def test_quick_ping_manual_stop_closes_stream_and_records_cancelled(tmp_path: Path) -> None:
    started = threading.Event()

    def runner(**kwargs):
        started.set()
        sequence = 0
        while not kwargs["stop_event"].is_set():
            sequence += 1
            yield _sample("192.0.2.10", ok=True, rtt=1.0, seq=sequence)
            time.sleep(0.005)

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target()])
    assert started.wait(1)
    run = service.stop(run_id)
    assert run.state == "CANCELLED"
    assert run.ended_at
    assert run.stats.received > 0
    assert run.segment_paths
    service.close()


def test_quick_ping_duration_enters_time_limit(tmp_path: Path) -> None:
    def runner(**kwargs):
        sequence = 0
        while not kwargs["stop_event"].is_set():
            sequence += 1
            yield _sample("192.0.2.10", ok=True, rtt=1.0, seq=sequence)
            time.sleep(0.005)

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(
        targets=[_target()],
        config=QuickPingConfig(duration_seconds=0.05),
    )
    run = _wait_for(service, run_id, {"TIME_LIMIT"})
    assert run.ended_at
    assert run.stats.received > 0


def test_quick_ping_recovers_manifests_and_bounds_recent_samples(tmp_path: Path) -> None:
    def runner(**kwargs):
        for sequence in range(1, 301):
            yield _sample("192.0.2.10", ok=True, rtt=float(sequence), seq=sequence)

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target()], run_date="2026-11-06")
    completed = _wait_for(service, run_id, {"COMPLETED"})
    assert len(completed.recent_samples) == 256
    assert completed.recent_samples[0]["sample"]["seq"] == 45
    assert completed.recent_samples[-1]["sample"]["seq"] == 300

    manifest = tmp_path / "quick_ping" / "2026-11-06" / "runs" / f"{run_id}.json"
    completed_payload = json.loads(manifest.read_text(encoding="utf-8"))
    interrupted_id = "quick-ping-interrupted"
    interrupted_payload = {
        **completed_payload,
        "run_id": interrupted_id,
        "state": "RUNNING",
        "ended_at": "",
        "error": "",
    }
    interrupted_manifest = manifest.with_name(f"{interrupted_id}.json")
    interrupted_manifest.write_text(json.dumps(interrupted_payload), encoding="utf-8")
    (manifest.parent / "malformed.json").write_text("{broken", encoding="utf-8")

    restarted = QuickPingService(
        site_id="demo",
        output_root=tmp_path,
        runner=lambda **_: pytest.fail("recovered task must not restart pinging"),
    )
    restored_completed = restarted.status(run_id)
    assert restored_completed is not None
    assert restored_completed.state == "COMPLETED"
    assert restored_completed.stats.received == 300
    assert restored_completed.stats.as_dict()["avg_rtt_ms"] == 150.5
    assert restored_completed.stats.as_dict()["jitter_ms"] == 1.0
    assert restored_completed.target_stats["192.0.2.10"].as_dict()["avg_rtt_ms"] == 150.5
    assert len(restored_completed.recent_samples) == 256
    assert restored_completed.recent_samples[-1]["sample"]["seq"] == 300

    restored_interrupted = restarted.status(interrupted_id)
    assert restored_interrupted is not None
    assert restored_interrupted.state == "FAILED"
    assert restored_interrupted.error.startswith("INTERRUPTED:")
    assert restored_interrupted.ended_at
    rewritten = json.loads(interrupted_manifest.read_text(encoding="utf-8"))
    assert rewritten["state"] == "FAILED"
    assert rewritten["ended_at"] == restored_interrupted.ended_at
    assert len(restarted.list_runs()) == 2


def test_quick_ping_rejects_ambiguous_ip_and_active_run_limit(tmp_path: Path) -> None:
    with pytest.raises(QuickPingError, match="多个 MR"):
        QuickPingService(site_id="demo", output_root=tmp_path, runner=lambda **_: iter(())).start(
            targets=[_target(mr_id="mr-a"), _target(mr_id="mr-b")]
        )

    hold = threading.Event()

    def blocked_runner(**kwargs):
        while not hold.is_set() and not kwargs["stop_event"].is_set():
            time.sleep(0.01)
        return
        yield  # pragma: no cover

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=blocked_runner, max_active_runs=1)
    first = service.start(targets=[_target()])
    with pytest.raises(QuickPingError, match="活动任务数"):
        service.start(targets=[_target("192.0.2.11", mr_id="mr-2")])
    hold.set()
    service.stop(first)


def test_quick_ping_throttles_global_probe_rate_without_changing_target_period(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def runner(**kwargs):
        calls.append(kwargs)
        return iter(())

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    targets = [_target(f"192.0.2.{index}", mr_id=f"mr-{index}") for index in range(1, 7)]
    run_id = service.start(targets=targets)
    run = _wait_for(service, run_id, {"COMPLETED"})

    assert len(calls) == 6
    assert {call["target"] for call in calls} == {target.target_ip for target in targets}
    assert all(call["targets"] == [call["target"]] for call in calls)
    assert calls[0]["interval_ms"] == 32
    assert calls[0]["period_ms"] == 200
    assert run.state == "COMPLETED"

    next_id = service.start(targets=[_target(f"192.0.2.{index}", mr_id=f"mr-{index}") for index in range(1, 8)])
    _wait_for(service, next_id, {"COMPLETED"})


def test_quick_ping_service_enforces_target_limit_beyond_api_dto(tmp_path: Path) -> None:
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=lambda **_: iter(()))
    targets = [_target(f"192.0.2.{index}", mr_id=f"mr-{index}") for index in range(1, 34)]

    with pytest.raises(QuickPingError) as error:
        service.start(targets=targets)

    assert error.value.code == "QUICK_PING_TARGET_LIMIT"


def test_quick_ping_close_visits_active_runs_older_than_list_window(tmp_path: Path, monkeypatch) -> None:
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=lambda **_: iter(()))
    target = _target()
    old_active = QuickPingRun(
        run_id="quick-ping-old-active",
        site_id="demo",
        run_date="2026-11-06",
        targets=(target,),
        config=QuickPingConfig(),
        state="RUNNING",
        started_at="2026-11-06T00:00:00+08:00",
    )
    # A local dispatcher is alive; restored foreign owners have no local thread.
    old_active._thread = type("AliveThread", (), {"is_alive": lambda self: True})()
    service._runs[old_active.run_id] = old_active
    for index in range(501):
        run = QuickPingRun(
            run_id=f"quick-ping-completed-{index:03d}",
            site_id="demo",
            run_date="2026-11-06",
            targets=(target,),
            config=QuickPingConfig(),
            state="COMPLETED",
            started_at=f"2026-11-06T00:{index // 60:02d}:{index % 60:02d}+08:00",
        )
        service._runs[run.run_id] = run
    stopped: list[str] = []
    monkeypatch.setattr(service, "stop", lambda run_id: stopped.append(run_id))

    service.close()

    assert stopped == [old_active.run_id]


def test_quick_ping_active_run_limit_is_independent_per_run_concurrency(tmp_path: Path) -> None:
    started: list[int] = []
    all_started = threading.Event()

    def blocked_runner(**kwargs):
        started.append(kwargs["interval_ms"])
        if len(started) == 4:
            all_started.set()
        while not kwargs["stop_event"].is_set():
            time.sleep(0.005)
        return
        yield  # pragma: no cover

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=blocked_runner)
    config = QuickPingConfig(interval_ms=500, timeout_ms=1000, max_in_flight=2)
    run_ids = [
        service.start(targets=[_target(f"192.0.2.{index}", mr_id=f"mr-{index}")], config=config)
        for index in range(1, 5)
    ]
    assert all_started.wait(1)
    assert started == [500, 500, 500, 500]
    with pytest.raises(QuickPingError) as error:
        service.start(targets=[_target("192.0.2.20", mr_id="mr-20")], config=config)
    assert error.value.code == "QUICK_PING_ACTIVE_LIMIT"

    service.close()
    assert all(service.status(run_id).state == "CANCELLED" for run_id in run_ids)


def test_quick_ping_finalizes_all_writers_when_one_close_fails(tmp_path: Path, monkeypatch) -> None:
    import netconsole.services.ground_unattended.quick_ping as quick_ping_module

    original_close = quick_ping_module._QuickPingSegmentWriter.close
    closed: list[str] = []

    def close_with_one_failure(writer):
        closed.append(str(writer.root))
        if len(closed) == 1:
            raise OSError("disk full")
        original_close(writer)

    monkeypatch.setattr(quick_ping_module._QuickPingSegmentWriter, "close", close_with_one_failure)

    def runner(**_kwargs):
        yield _sample("192.0.2.10", ok=True, rtt=1.0, seq=1)
        yield _sample("192.0.2.11", ok=True, rtt=2.0, seq=2)

    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(
        targets=[_target("192.0.2.10", mr_id="mr-1"), _target("192.0.2.11", mr_id="mr-2", role="CW")]
    )
    run = _wait_for(service, run_id, {"FAILED"})

    assert len(closed) == 2
    assert run.state == "FAILED"
    assert "writer close failed" in run.error
    assert run.ended_at


def test_quick_ping_manifest_write_failure_still_sets_terminal_state(tmp_path: Path, monkeypatch) -> None:
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=lambda **_: iter(()))
    original_write = service._write_manifest
    calls = 0

    def fail_final_write(run):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("manifest volume unavailable")
        original_write(run)

    monkeypatch.setattr(service, "_write_manifest", fail_final_write)
    run_id = service.start(targets=[_target()], run_date="2026-11-06")
    run = _wait_for(service, run_id, {"FAILED"})
    assert run._thread is not None
    run._thread.join(timeout=1)

    assert calls == 3
    assert run.ended_at
    assert "final persistence failed" in run.error
    manifest = tmp_path / "quick_ping" / "2026-11-06" / "runs" / f"{run_id}.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["state"] == "FAILED"


def test_unlimited_quick_ping_compresses_closed_size_segments_while_current_is_active(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    import netconsole.services.ground_unattended.quick_ping as module

    original_init = module._QuickPingSegmentWriter.__init__
    def small_segments(writer, root, **kwargs):
        original_init(writer, root, max_bytes=1100, **kwargs)
    monkeypatch.setattr(module._QuickPingSegmentWriter, "__init__", small_segments)
    waiting = threading.Event()
    compression_threads = []
    original_compress = QuickPingService._compress_segment
    def record_compression(service, run_id, path):
        compression_threads.append(threading.current_thread().name)
        original_compress(service, run_id, path)
    monkeypatch.setattr(QuickPingService, "_compress_segment", record_compression)
    def runner(**kwargs):
        for seq in range(12):
            yield replace(_sample("192.0.2.10", ok=True, rtt=1, seq=seq), ts="2026-11-07T10:00:00Z")
        waiting.set()
        while not kwargs["stop_event"].is_set():
            time.sleep(0.005)
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    run_id = service.start(targets=[_target()])
    try:
        assert waiting.wait(2)
        deadline = time.monotonic() + 2
        while not list(tmp_path.rglob("*.gz.json")) and time.monotonic() < deadline:
            time.sleep(0.01)
        run = service.status(run_id)
        assert run.config.duration_seconds is None and run.state == "RUNNING"
        assert list(tmp_path.rglob("*.ndjson"))  # the current segment remains writable
        sidecars = list(tmp_path.rglob("*.gz.json"))
        assert sidecars
        for sidecar in sidecars:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            compressed = sidecar.with_suffix("").read_bytes()
            content = gzip.decompress(compressed)
            assert metadata["size_bytes"] == len(content)
            assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
            assert metadata["gzip_sha256"] == hashlib.sha256(compressed).hexdigest()
            assert metadata["site_id"] == "demo" and metadata["run_id"] == run_id
        assert set(compression_threads) == {"quick-ping-compressor"}
    finally:
        service.close()
    restarted = QuickPingService(site_id="demo", output_root=tmp_path, runner=lambda **_: iter(()))
    page, samples = restarted.query_samples(run_id, limit=5), []
    while True:
        samples.extend(page["items"])
        if not page["has_more"]:
            break
        page = restarted.query_samples(run_id, cursor=page["next_cursor"], limit=5)
    assert [row["sample"]["seq"] for row in samples] == list(range(12))


def test_quick_ping_compressed_tamper_and_metadata_fail_closed(tmp_path: Path) -> None:
    service = QuickPingService(site_id="demo", output_root=tmp_path,
                               runner=lambda **_: iter([_sample("192.0.2.10", ok=True, rtt=1, seq=1)]))
    run_id = service.start(targets=[_target()])
    run = _wait_for(service, run_id, {"COMPLETED"})
    target = (tmp_path / run.segment_paths[0]).with_suffix(".ndjson.gz")
    original = target.read_bytes()
    target.write_bytes(original + b"tampered")
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id)
    assert caught.value.code == "QUICK_PING_RAW_CORRUPT"
    target.write_bytes(original)
    target.with_name(target.name + ".json").write_text("{}", encoding="utf-8")
    with pytest.raises(QuickPingError) as caught:
        service.query_samples(run_id)
    assert caught.value.status_code == 503
