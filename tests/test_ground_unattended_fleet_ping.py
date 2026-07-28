from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

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
    _wait_until(lambda: fleet.sample_count > before)
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
