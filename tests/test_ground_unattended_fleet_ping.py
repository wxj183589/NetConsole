from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.core.ping.fping_v5_runner import build_fping_v5_args
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.fleet_ping import (
    FleetPingSupervisor,
    FleetPingTarget,
)
from netconsole.services.ground_unattended.timeline import (
    GroundUnattendedTimelineCorrelator,
)


def test_fping_runner_keeps_single_target_and_supports_multiple_targets(
    tmp_path,
) -> None:
    single = build_fping_v5_args(tmp_path / "fping.exe", "192.0.2.1", 1000, 4000, 64)
    multiple = build_fping_v5_args(
        tmp_path / "fping.exe", "", 1000, 4000, 64, targets=["192.0.2.1", "192.0.2.2"]
    )
    assert single[-1:] == ["192.0.2.1"]
    assert multiple[-2:] == ["192.0.2.1", "192.0.2.2"]
    assert multiple.count("-l") == 1


def test_fping_shard_failure_reports_health_without_serial_fallback() -> None:
    repository = Mock()
    runner = Mock(side_effect=RuntimeError("process exited"))
    fleet = FleetPingSupervisor(repository=repository, site_id="site-a", runner=runner)
    fleet._run_id = "run-1"

    fleet._worker_loop(
        "shard-1", "generation", ("192.0.2.1", "192.0.2.2"),
        threading.Event(), threading.Event(),
    )

    assert runner.call_count == 1
    assert repository.add_event.call_args.kwargs["event_type"] == "ping_shard_failed"
    assert repository.add_health_event.call_args.kwargs["code"] == "HEARTBEAT_SHARD_FAILED"


def test_400_ip_mock_fleet_has_bounded_shards_and_stops(tmp_path) -> None:
    def runner(*, targets, stop_event, **kwargs):
        for target in targets:
            yield FpingV5Sample(
                ts=datetime.now().astimezone().isoformat(), target=target, seq=1,
                ok=True, rtt_ms=1.0, timeout_ms=kwargs["timeout_ms"],
                size=kwargs["packet_size"], error="", backend=BACKEND,
                raw_type="response", raw={},
            )
        stop_event.wait(30)

    repo = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    fleet = FleetPingSupervisor(repository=repo, site_id="site-a", runner=runner)
    fleet.start(
        run_id="400-ip", run_date="2026-01-01", active_dir=tmp_path / "ground" / "active",
        period_ms=1000, timeout_ms=4000, packet_size=64, shard_size=20,
        correlation_tolerance_seconds=15, switch_before_seconds=5, switch_after_seconds=5,
    )
    try:
        fleet.update_targets([
            _target(f"192.0.{index // 254 + 2}.{index % 254 + 1}", f"train-{index}", "CT")
            for index in range(400)
        ])
        _wait_until(lambda: fleet.sample_count == 400, timeout=20)
        assert fleet.process_count == 20
        assert len(fleet.target_summaries()) == 400
        assert len(fleet._sample_times) <= 4096
        assert not fleet.worker_warnings
    finally:
        result = fleet.stop()
    assert result["success"] is True
    assert fleet.process_count == 0
    assert result["sample_count"] == 400


def test_fping_runner_optional_global_interval_keeps_legacy_args_unchanged(tmp_path) -> None:
    legacy = build_fping_v5_args(tmp_path / "fping.exe", "192.0.2.1", 200, 1000, 64)
    throttled = build_fping_v5_args(
        tmp_path / "fping.exe", "192.0.2.1", 200, 1000, 64, interval_ms=32
    )

    assert "-i" not in legacy
    assert throttled[throttled.index("-i") + 1] == "32"
    assert throttled[throttled.index("-p") + 1] == "200"


def test_fleet_ping_dynamic_targets_rotation_summaries_and_stop(tmp_path) -> None:
    repo = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    fleet = FleetPingSupervisor(repository=repo, site_id="site-a", runner=_fake_runner)
    active = tmp_path / "ground" / "active" / "2026-07-25"
    fleet.start(
        run_id="run-1",
        run_date="2026-07-25",
        active_dir=active,
        period_ms=1000,
        timeout_ms=4000,
        packet_size=64,
        shard_size=2,
        correlation_tolerance_seconds=15,
        switch_before_seconds=5,
        switch_after_seconds=5,
    )
    fleet.update_targets(
        [_target("192.0.2.1", "train-1", "CT"), _target("192.0.2.2", "train-1", "CW")]
    )
    _wait_until(lambda: fleet.sample_count >= 4)
    assert fleet.process_count == 1
    before = fleet.sample_count
    fleet.update_targets(
        [_target("192.0.2.2", "train-1", "CW"), _target("192.0.2.3", "train-2", "CT")]
    )
    _wait_until(lambda: fleet.sample_count > before and all(
        row["sent_count"] > 0 for row in fleet.target_summaries()
    ))
    fleet.flush_summaries()
    live = fleet.target_summaries()
    assert {row["target_ip"] for row in live} == {"192.0.2.2", "192.0.2.3"}
    assert all(row["sent_count"] > 0 for row in live)
    fleet.stop()
    assert fleet.process_count == 0
    files = list((active / "fleet_ping").glob("*.jsonl"))
    assert files and all(path.read_text(encoding="utf-8").strip() for path in files)
    summaries = repo.list_ping_summaries("run-1")
    assert {row["target_ip"] for row in summaries} >= {"192.0.2.2", "192.0.2.3"}
    assert not any(
        thread.name.startswith("fleet-ping-") and thread.is_alive()
        for thread in __import__("threading").enumerate()
    )


def test_fleet_ping_restart_preserves_run_count_and_overlapping_summary(
    tmp_path,
) -> None:
    repo = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    now = datetime.now().astimezone()
    run_date = now.date().isoformat()
    repo.create_or_get_run(
        run_id="run-restart",
        run_date=run_date,
        scheduled_start_at=now.isoformat(timespec="seconds"),
        scheduled_end_at=(now + timedelta(hours=1)).isoformat(timespec="seconds"),
        state="RUNNING",
    )
    repo.update_run("run-restart", ping_sample_count=41)
    bucket_start = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat(timespec="seconds")
    repo.upsert_ping_summary(
        {
            "site_id": "site-a",
            "run_id": "run-restart",
            "bucket_kind": "daily",
            "bucket_start": bucket_start,
            "bucket_end": (
                now.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            ).isoformat(timespec="seconds"),
            "target_ip": "192.0.2.10",
            "train_id": "train-1",
            "train_no": "train-1",
            "mr_id": "train-1-CT",
            "mr_position_code": "CT",
            "ac_snapshot_id": 1,
            "ap_identity": "",
            "raw_sample_count": 10,
            "warmup_ignored_count": 0,
            "sent_count": 10,
            "success_count": 8,
            "loss_count": 2,
            "loss_rate_percent": 20.0,
            "min_rtt_ms": 10.0,
            "avg_rtt_ms": 15.0,
            "max_rtt_ms": 20.0,
            "continuous_loss_max_count": 2,
            "continuous_loss_max_seconds": 2.0,
            "created_at": now.isoformat(timespec="seconds"),
        }
    )

    fleet = FleetPingSupervisor(repository=repo, site_id="site-a", runner=_idle_runner)
    active = tmp_path / "ground" / "active" / run_date
    fleet.start(
        run_id="run-restart",
        run_date=run_date,
        active_dir=active,
        period_ms=1000,
        timeout_ms=4000,
        packet_size=64,
        shard_size=2,
        correlation_tolerance_seconds=15,
        switch_before_seconds=5,
        switch_after_seconds=5,
    )
    assert fleet.sample_count == 41
    fleet.update_targets([_target("192.0.2.10", "train-1", "CT")])
    assert fleet.target_summaries()[0]["sent_count"] == 10

    fleet._record_sample(
        FpingV5Sample(
            ts=now.isoformat(timespec="milliseconds"),
            target="192.0.2.10",
            seq=42,
            ok=True,
            rtt_ms=30.0,
            timeout_ms=4000,
            size=64,
            error="",
            backend=BACKEND,
            raw_type="response",
            raw={},
        ),
        "shard-001",
    )
    fleet.flush_summaries()

    summary = repo.get_ping_summary(
        "run-restart",
        bucket_kind="daily",
        bucket_start=bucket_start,
        target_ip="192.0.2.10",
    )
    assert fleet.sample_count == 42
    assert summary is not None
    assert summary["raw_sample_count"] == 11
    assert summary["sent_count"] == 11
    assert summary["success_count"] == 9
    assert summary["loss_count"] == 2
    assert summary["avg_rtt_ms"] == pytest.approx(16.6667)
    fleet.stop()


def test_fleet_ping_only_marks_real_ap_changes_as_transition(tmp_path) -> None:
    repo = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    fleet = FleetPingSupervisor(repository=repo, site_id="site-a", runner=_fake_runner)
    active = tmp_path / "ground" / "active" / "2026-07-25"
    fleet.start(
        run_id="run-transition",
        run_date="2026-07-25",
        active_dir=active,
        period_ms=1000,
        timeout_ms=4000,
        packet_size=64,
        shard_size=2,
        correlation_tolerance_seconds=15,
        switch_before_seconds=5,
        switch_after_seconds=5,
    )
    fleet.update_targets([_target("192.0.2.10", "train-1", "CT")])
    _wait_until(lambda: fleet.sample_count >= 70)
    first_lines = _timeline_rows(active)
    assert first_lines
    assert all(row["ap_transition_context"] == "same_ap" for row in first_lines)

    fleet.update_targets(
        [_target("192.0.2.10", "train-1", "CT", ap_identity="ap:2", ap_name="AP-2")]
    )
    before = fleet.sample_count
    _wait_until(lambda: fleet.sample_count > before)
    fleet.stop()
    assert any(
        row.get("ap_transition_context") == "after_transition"
        for row in _timeline_rows(active)
        if row.get("record_type") == "correlation"
    )


def test_fleet_hour_segments_compress_and_stop_timeout_keeps_run_for_retry(tmp_path, monkeypatch) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    fleet = FleetPingSupervisor(repository=repository, site_id="site-a", runner=_idle_runner)
    options = dict(
        run_date="2026-07-25", active_dir=repository.db_path.parent / "active" / "2026-07-25",
        period_ms=1000, timeout_ms=4000, packet_size=64, shard_size=12,
        correlation_tolerance_seconds=15, switch_before_seconds=5, switch_after_seconds=5,
    )
    fleet.start(run_id="compression-stop", **options)
    target = _target("192.0.2.10", "train-1", "CT")
    compressor = fleet._raw_compressor
    assert compressor is not None
    real_stop = compressor.stop
    try:
        fleet.update_targets([target])
        assert fleet._raw_writer.max_file_size_bytes == 10 * 1024 * 1024
        for seq, hour in enumerate((10, 11), start=1):
            fleet._record_sample(FpingV5Sample(
                ts=f"2026-07-25T{hour}:00:00+08:00", target=target.target_ip,
                seq=seq, ok=True, rtt_ms=2.0, timeout_ms=4000, size=64,
                error="", backend=BACKEND, raw_type="response", raw={},
            ), "mock-shard")
        monkeypatch.setattr(compressor, "stop", lambda timeout: False)
        incomplete = fleet.stop()
        assert not incomplete["success"]
        assert incomplete["fping_processes_exited"]
        assert not incomplete["compression_stopped"]
        assert fleet._run_id == "compression-stop"
        assert fleet._raw_writer is not None
        assert fleet._raw_compressor is compressor
        with pytest.raises(RuntimeError, match="raw compression"):
            fleet.start(run_id="another-run", **options)
        monkeypatch.setattr(compressor, "stop", real_stop)
        stopped = fleet.stop()
        assert stopped["success"] and stopped["compression_stopped"]
        assert stopped["compression_completed_count"] == 2
        assert fleet._run_id == ""
        assert fleet._raw_compressor is None
        rows = repository.list_raw_files(data_type="ping")
        assert len(rows) == 2
        assert all(row["gzip_path"] for row in rows)
        assert all(row["device_uuid"] == target.mr_id for row in rows)
    finally:
        monkeypatch.setattr(compressor, "stop", real_stop)
        fleet.stop()


def test_timeline_marks_loss_unknown_when_snapshot_exceeds_tolerance(tmp_path) -> None:
    correlator = GroundUnattendedTimelineCorrelator(
        tmp_path / "timeline",
        tolerance_seconds=15,
        switch_before_seconds=5,
        switch_after_seconds=5,
    )
    now = datetime.now().astimezone()
    result = correlator.correlate(
        {
            "sample_id": "sample-1",
            "ts": now.isoformat(timespec="milliseconds"),
            "target_ip": "192.0.2.10",
            "ok": False,
        },
        {
            "ac_snapshot_id": 99,
            "ac_received_at": (now - timedelta(seconds=30)).isoformat(),
            "train_id": "train-1",
            "mr_id": "mr-ct",
            "mr_position_code": "CT",
        },
    )
    correlator.close()
    assert result["ac_position_status"] == "unknown"
    assert result["loss_pattern"] == "AC_POSITION_UNKNOWN_LOSS"


def _fake_runner(
    *, target="", targets=None, stop_event, timeout_ms, packet_size, **_kwargs
):
    values = list(targets or [target])
    sequence = 0
    while not stop_event.is_set():
        for address in values:
            sequence += 1
            yield FpingV5Sample(
                ts=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                target=address,
                seq=sequence,
                ok=sequence % 5 != 0,
                rtt_ms=None if sequence % 5 == 0 else float(sequence),
                timeout_ms=timeout_ms,
                size=packet_size,
                error="timeout" if sequence % 5 == 0 else "",
                backend=BACKEND,
                raw_type="timeout" if sequence % 5 == 0 else "response",
                raw={},
            )
        stop_event.wait(0.005)


def _idle_runner(*, stop_event, **_kwargs):
    while not stop_event.wait(0.01):
        pass
    return
    yield


def _target(
    address: str,
    train: str,
    endpoint: str,
    *,
    ap_identity: str = "ap:1",
    ap_name: str = "AP-1",
) -> FleetPingTarget:
    return FleetPingTarget(
        address,
        train,
        train,
        f"{train}-{endpoint}",
        endpoint,
        ac_snapshot_id=1,
        ac_received_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        current_ap_identity=ap_identity,
        current_ap_name=ap_name,
        station="S1",
        same_ap_since=datetime.now().astimezone().isoformat(),
    )


def _timeline_rows(active):
    rows = []
    for path in (active / "timeline").glob("*.jsonl"):
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        )
    return [row for row in rows if row.get("record_type") == "correlation"]


def _wait_until(predicate, timeout=3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met")
