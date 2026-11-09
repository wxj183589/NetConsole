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
    repository.upsert_ping_summaries.side_effect = lambda rows: persisted.update(
        {_summary_key(row): dict(row) for row in rows}
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
    repository.upsert_ping_summaries.side_effect = OSError("disk full")
    with pytest.raises(OSError, match="disk full"):
        fleet.flush_summaries()
    assert len(fleet._dirty_buckets) == 5
    assert len(fleet._buckets) == 5

    repository.upsert_ping_summaries.side_effect = None
    repository.upsert_ping_summaries.reset_mock()
    fleet.flush_summaries()
    repository.upsert_ping_summaries.assert_called_once()
    assert len(repository.upsert_ping_summaries.call_args.args[0]) == 5
    assert not fleet._dirty_buckets
    assert all(row.raw == 1 for row in fleet._buckets.values())


def test_summary_batch_rolls_back_all_rows_when_one_write_fails(tmp_path):
    import sqlite3
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository

    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="site-a")
    fleet = FleetPingSupervisor(repository=repo, site_id="site-a")
    fleet._run_id = "atomic-run"
    fleet._targets["127.0.0.1"] = FleetPingTarget("127.0.0.1", "train-1", "1", "mr-1", "CT")
    fleet._record_sample(_sample(datetime(2026, 1, 1, tzinfo=timezone.utc), "127.0.0.1"), "shard-1")
    with repo._transaction() as conn:
        conn.execute("CREATE TRIGGER fail_summary BEFORE INSERT ON ground_unattended_ping_summaries WHEN NEW.bucket_kind='daily' BEGIN SELECT RAISE(ABORT, 'injected write failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected write failure"):
        fleet.flush_summaries()
    assert repo.list_ping_summaries("atomic-run", bucket_kind=None) == []
    assert len(fleet._dirty_buckets) == 5
    with repo._transaction() as conn:
        conn.execute("DROP TRIGGER fail_summary")
    fleet.flush_summaries()
    assert len(repo.list_ping_summaries("atomic-run", bucket_kind=None)) == 5
    assert not fleet._dirty_buckets


def test_unchanged_targets_do_not_repeat_activation_writes():
    repo = Mock()
    repo.ping_summary_totals.return_value = []
    repo.ensure_ping_target_activation.return_value = "2026-01-01T00:00:00+00:00"
    fleet = FleetPingSupervisor(repository=repo, site_id="site-a")
    fleet._run_id = "run-1"
    fleet._reconcile_shards = Mock()
    target = FleetPingTarget("127.0.0.1", "train-1", "1", "mr-1", "CT")
    for _ in range(20):
        fleet.update_targets([target])
    repo.ensure_ping_target_activation.assert_called_once()
    repo.ping_summary_totals.assert_called_once_with("run-1", target_ips={"127.0.0.1"})
    fleet.update_targets([])
    fleet.update_targets([target])
    assert repo.ensure_ping_target_activation.call_count == 2
    assert repo.ping_summary_totals.call_count == 2
