from __future__ import annotations

import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.quick_ping import (
    QuickPingService,
    QuickPingTarget,
    QuickPingRun,
    QuickPingConfig,
)


def _target() -> QuickPingTarget:
    return QuickPingTarget(
        target_ip="192.0.2.10",
        train_id="train-1",
        train_no="001",
        mr_id="mr-1",
        mr_role="CT",
        address_role="PRIMARY",
    )


def _wait_terminal(service: QuickPingService, run_id: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        run = service.status(run_id)
        if run is not None and run.ended_at:
            if run._thread is not None:
                run._thread.join(timeout=2)
                assert not run._thread.is_alive()
            return
        time.sleep(0.01)
    raise AssertionError("Quick Ping run did not finish")


def test_quick_ping_persists_metadata_aggregates_events_and_restores(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")

    def runner(**_: object):
        yield FpingV5Sample(
            ts="2026-11-07T10:00:00+08:00",
            target="192.0.2.10",
            seq=1,
            ok=True,
            rtt_ms=2.5,
            timeout_ms=1000,
            size=64,
            error="",
            backend="test",
            raw_type="resp",
            raw={},
        )

    service = QuickPingService(
        site_id="demo",
        output_root=tmp_path / "output",
        runner=runner,
        repository=repository,
    )
    run_id = service.start(targets=[_target()], run_date="2026-11-07")
    _wait_terminal(service, run_id)

    saved = repository.get_quick_ping_run(run_id)
    assert saved is not None
    assert saved["state"] == "COMPLETED"
    assert saved["stats"]["received"] == 1
    assert saved["target_stats"]["192.0.2.10"]["avg_rtt_ms"] == 2.5
    assert saved["recent_samples"] == []
    assert {item["event_type"] for item in repository.list_quick_ping_events(run_id)} >= {
        "STARTED",
        "COMPLETED",
    }

    restarted = QuickPingService(
        site_id="demo",
        output_root=tmp_path / "missing-output",
        runner=lambda **_: iter(()),
        repository=repository,
    )
    restored = restarted.status(run_id)
    assert restored is not None
    assert restored.state == "COMPLETED"
    assert restored.stats.received == 1
    assert restored.stats.as_dict()["avg_rtt_ms"] == 2.5


def test_quick_ping_repository_keeps_samples_out_of_sqlite(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    repository.save_quick_ping_state(
        {
            "run_id": "quick-ping-samples",
            "site_id": "demo",
            "run_date": "2026-11-07",
            "state": "COMPLETED",
            "targets": [_target().__dict__],
            "config": {"interval_ms": 200},
            "segment_paths": ["quick_ping/2026-11-07/sample.ndjson"],
            "started_at": "2026-11-07T10:00:00+08:00",
            "ended_at": "2026-11-07T10:00:01+08:00",
        },
        {
            "": {"sent": 1, "received": 1, "raw_samples": 1, "avg_rtt_ms": 1.0},
        },
        {"": {"rtt_sum_ms": 1.0}},
    )

    with repository.db_path.open("rb") as handle:
        database_bytes = handle.read()
    assert b"192.0.2.10" in database_bytes  # indexed target metadata is expected
    assert b'"sample"' not in database_bytes


def test_quick_ping_history_pages_beyond_runtime_limit_and_scopes_targets(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    start = datetime(2026, 11, 7, tzinfo=timezone.utc)
    for index in range(521):
        repository.save_quick_ping_state({
            "run_id": f"quick-{index:04}", "site_id": "demo", "run_date": "2026-11-07",
            "state": "COMPLETED", "targets": [_target().__dict__], "config": {},
            "started_at": (start + timedelta(minutes=index)).isoformat(), "ended_at": "",
        }, {}, {})
    rows, total = repository.query_quick_ping_runs(limit=20, offset=500)
    assert total == 521
    assert [row["run_id"] for row in rows] == [f"quick-{index:04}" for index in range(20, 0, -1)]
    rows, total = repository.query_quick_ping_runs(
        start_time="2026-11-07T08:00:00+08:00", end_time="2026-11-07T08:02:00+08:00",
        train_id="train-1", mr_id="mr-1", mr_role="CT",
    )
    assert total == 3
    assert [row["run_id"] for row in rows] == ["quick-0002", "quick-0001", "quick-0000"]
    assert repository.query_quick_ping_runs(query="%' OR 1=1 --")[1] == 0
    assert repository.query_quick_ping_runs(mr_id="missing")[1] == 0
    repository.save_quick_ping_state({
        "run_id": "mixed", "site_id": "demo", "run_date": "2026-11-07", "state": "COMPLETED",
        "started_at": "2026-11-07T10:00:00Z", "targets": [
            {"train_id": "train-a", "mr_id": "mr-a", "mr_role": "CT"},
            {"train_id": "train-b", "mr_id": "mr-b", "mr_role": "CW"},
        ], "config": {},
    }, {}, {})
    assert repository.query_quick_ping_runs(train_id="train-a", mr_role="CW")[1] == 0
    other = GroundUnattendedRepository(repository.db_path, site_id="other")
    assert other.query_quick_ping_runs()[1] == 0


def _retention_run(service: QuickPingService, run_id: str, ended: datetime, *, state: str = "COMPLETED") -> tuple[QuickPingRun, Path, Path]:
    run = QuickPingRun(run_id=run_id, site_id=service.site_id, run_date=ended.date().isoformat(),
                       targets=(_target(),), config=QuickPingConfig(), state=state,
                       started_at=(ended - timedelta(seconds=5)).isoformat(), ended_at=ended.isoformat())
    path = service._run_output_root(run, _target()) / "quick_ping_00.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"quick_ping_run_id": run_id, "site_id": service.site_id}) + "\n", encoding="utf-8")
    run.segment_paths = [path.relative_to(service.output_root).as_posix()]
    service._write_manifest(run)
    service._persist_run(run, event_type="IMPORTANT", force=True)
    manifest = service.output_root / "quick_ping" / run.run_date / "runs" / f"{run_id}.json"
    return run, path, manifest


def test_quick_ping_retention_uses_live_profile_retains_events_and_never_revives_summary(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    service = QuickPingService(site_id="demo", output_root=tmp_path / "output", repository=repository)
    service.close()  # finish startup maintenance before constructing historical fixtures
    now = datetime.now(timezone.utc)
    summary, raw, manifest = _retention_run(service, "quick-summary", now - timedelta(days=31))
    expired, expired_raw, expired_manifest = _retention_run(service, "quick-expired", now - timedelta(days=181))
    active, active_raw, _ = _retention_run(service, "quick-active", now - timedelta(days=181), state="RUNNING")
    recent, recent_raw, _ = _retention_run(service, "quick-recent", now - timedelta(days=1))
    unregistered = raw.parent / "unregistered.ndjson"
    unregistered.write_text("keep evidence", encoding="utf-8")
    service._compress_segment(summary.run_id, raw)
    service.apply_retention(now=now)
    assert not raw.with_name(raw.name + ".gz").exists()
    assert not raw.with_name(raw.name + ".gz.json").exists()
    assert manifest.exists() and repository.get_quick_ping_run(summary.run_id)
    assert not expired_raw.exists() and not expired_manifest.exists()
    assert repository.get_quick_ping_run(expired.run_id) is None
    assert repository.list_quick_ping_events(expired.run_id)[0]["event_type"] == "IMPORTANT"
    assert active_raw.exists() and recent_raw.exists() and unregistered.exists()
    profile = repository.get_profile()
    repository.save_profile(profile.model_copy(update={"ping_raw_retention_days": 1, "summary_retention_days": 10, "detail_retention_days": 1}))
    service.apply_retention(now=now + timedelta(seconds=1))
    assert not manifest.exists() and repository.get_quick_ping_run(summary.run_id) is None
    assert not recent_raw.exists() and repository.get_quick_ping_run(recent.run_id)
    assert active_raw.exists()
    restarted = QuickPingService(site_id="demo", output_root=service.output_root, repository=repository)
    restarted.close()
    assert restarted.status(expired.run_id) is None
    assert restarted.status(summary.run_id) is None
    other = GroundUnattendedRepository(repository.db_path, site_id="other")
    assert other.get_quick_ping_run(recent.run_id) is None


@pytest.mark.parametrize("failure", ["identity", "outside", "delete"])
def test_quick_ping_retention_failure_preserves_summary_manifest_and_records_health(tmp_path: Path, monkeypatch, failure: str) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    service = QuickPingService(site_id="demo", output_root=tmp_path / "output", repository=repository)
    service.close()
    now = datetime.now(timezone.utc)
    run, raw, manifest = _retention_run(service, "quick-failed-retention", now - timedelta(days=181))
    outside = tmp_path / "outside.ndjson"
    outside.write_text("keep outside evidence", encoding="utf-8")
    if failure == "identity":
        manifest.write_text(json.dumps({"site_id": "other", "run_id": run.run_id}), encoding="utf-8")
    elif failure == "outside":
        run.segment_paths = [str(outside)]
        service._persist_run(run, force=True)
    else:
        original_unlink = Path.unlink
        def fail_one_path(path, *args, **kwargs):
            if path == raw:
                raise PermissionError("file busy")
            return original_unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail_one_path)
    service.apply_retention(now=now)
    assert raw.exists() and manifest.exists() and outside.exists()
    assert repository.get_quick_ping_run(run.run_id)
    assert repository.latest_health_event()["code"] == "QUICK_PING_RETENTION_FAILED"


def test_quick_ping_compression_verification_failure_preserves_raw_and_reports_health(tmp_path: Path, monkeypatch) -> None:
    import netconsole.services.ground_unattended.quick_ping as module

    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    def corrupt(*args, **kwargs):
        raise OSError("gzip verification read failed")
    monkeypatch.setattr(module.gzip, "open", corrupt)
    service = QuickPingService(site_id="demo", output_root=tmp_path / "output", repository=repository,
                               runner=lambda **_: iter([FpingV5Sample(ts="2026-11-07T10:00:00Z", target="192.0.2.10", seq=1,
                                                                    ok=True, rtt_ms=1, timeout_ms=1000, size=64,
                                                                    error="", backend="test", raw_type="resp", raw={})]))
    try:
        run_id = service.start(targets=[_target()])
        _wait_terminal(service, run_id)
        run = service.status(run_id)
        assert run.state == "COMPLETED"
        assert (service.output_root / run.segment_paths[0]).exists()
        assert not list(service.output_root.rglob("*.gz"))
        assert not list(service.output_root.rglob("*.part"))
        assert repository.latest_health_event()["code"] == "QUICK_PING_COMPRESSION_FAILED"
        assert service.query_samples(run_id)["items"][0]["sample"]["seq"] == 1
    finally:
        service.close()


def test_quick_ping_summary_delete_guards_exact_site_state_time(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    ended = "2026-01-01T00:00:00Z"
    def save(state):
        repository.save_quick_ping_state({"site_id": "demo", "run_id": "guarded", "run_date": "2026-01-01",
                                          "state": state, "started_at": ended, "ended_at": ended,
                                          "targets": [_target().__dict__], "config": {}}, {}, {})
    for state in ("RUNNING", "STOPPING", "UNKNOWN"):
        save(state)
        assert not repository.delete_terminal_quick_ping_summary("guarded", ended_at=ended, cutoff="2026-11-07T00:00:00Z")
    save("COMPLETED")
    assert not repository.delete_terminal_quick_ping_summary("guarded", ended_at=ended, cutoff=ended)
    assert not repository.delete_terminal_quick_ping_summary("guarded", ended_at="2026-01-02T00:00:00Z", cutoff="2026-11-07T00:00:00Z")
    other = GroundUnattendedRepository(repository.db_path, site_id="other")
    assert not other.delete_terminal_quick_ping_summary("guarded", ended_at=ended, cutoff="2026-11-07T00:00:00Z")
    assert repository.delete_terminal_quick_ping_summary("guarded", ended_at=ended, cutoff="2026-11-07T00:00:00Z")
