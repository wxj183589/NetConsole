from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.services.ground_unattended.fleet_ping import (
    FleetPingSupervisor,
    FleetPingTarget,
)


def _summary_key(row):
    return tuple(row[field] for field in (
        "bucket_kind", "bucket_start", "target_ip", "ap_identity"
    ))


def _sample(ts, target_ip):
    return FpingV5Sample(
        ts=ts.isoformat(), target=target_ip, seq=int(ts.timestamp()),
        ok=True, rtt_ms=1.0, timeout_ms=4000, size=64,
        error="", backend=BACKEND, raw_type="response", raw={},
    )


def test_day_of_minute_and_ap_churn_keeps_fleet_cache_bounded_and_reloads_late_samples():
    persisted = {}
    repository = Mock()
    repository.get_ping_summary.side_effect = lambda _run_id, **key: persisted.get(
        _summary_key(key)
    )
    repository.upsert_ping_summary.side_effect = lambda row: persisted.__setitem__(
        _summary_key(row), dict(row)
    )
    fleet = FleetPingSupervisor(repository=repository, site_id="site-a")
    fleet._run_id = "day-run"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    addresses = ("192.0.2.1", "192.0.2.2")
    for minute in range(24 * 60):
        ts = start + timedelta(minutes=minute)
        for address in addresses:
            fleet._targets[address] = FleetPingTarget(
                address, "train-1", "train-1", f"mr-{address}", "CT",
                ac_received_at=ts.isoformat(), same_ap_since=ts.isoformat(),
                ac_snapshot_id=minute, current_ap_identity=f"ap-{minute}",
            )
            fleet._record_sample(_sample(ts, address), "shard-001")
        fleet.flush_summaries()
        assert len(fleet._buckets) <= 5 * len(addresses)
        assert not fleet._dirty_buckets

    old_key = ("1m", start.isoformat(timespec="seconds"), addresses[0], "")
    assert persisted[old_key]["raw_sample_count"] == 1
    fleet._record_sample(_sample(start, addresses[0]), "shard-001")
    fleet.flush_summaries()
    assert persisted[old_key]["raw_sample_count"] == 2
    assert len(fleet._buckets) <= 10
    daily_key = ("daily", start.isoformat(timespec="seconds"), addresses[0], "")
    assert persisted[daily_key]["raw_sample_count"] == 1441
    fleet._targets = {}
    fleet.flush_summaries()
    assert not fleet._buckets


def test_failed_summary_write_retains_unpersisted_buckets_for_retry():
    repository = Mock()
    repository.get_ping_summary.return_value = None
    fleet = FleetPingSupervisor(repository=repository, site_id="site-a")
    fleet._run_id = "retry-run"
    address = "192.0.2.1"
    fleet._targets[address] = FleetPingTarget(
        address, "train-1", "train-1", "mr-1", "CT"
    )
    fleet._record_sample(
        _sample(datetime(2026, 1, 1, tzinfo=timezone.utc), address), "shard-001"
    )
    repository.upsert_ping_summary.side_effect = [None, OSError("disk full")]
    with pytest.raises(OSError, match="disk full"):
        fleet.flush_summaries()
    assert len(fleet._dirty_buckets) == 4
    assert len(fleet._buckets) == 5

    repository.upsert_ping_summary.side_effect = None
    repository.upsert_ping_summary.reset_mock()
    fleet.flush_summaries()
    assert repository.upsert_ping_summary.call_count == 4
    assert not fleet._dirty_buckets
    assert all(row.raw == 1 for row in fleet._buckets.values())
