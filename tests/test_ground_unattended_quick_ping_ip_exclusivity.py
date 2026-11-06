from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.quick_ping import QuickPingConfig, QuickPingError, QuickPingService, QuickPingTarget
from netconsole.services.ground_unattended.quick_ping_ownership import matching_process, process_identity


def target(ip: str, *, mr: str = "same-mr", address: str = "PRIMARY") -> QuickPingTarget:
    return QuickPingTarget(target_ip=ip, train_id="t1", train_no="001", mr_id=mr, mr_role="CT", address_role=address)


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def test_same_mr_primary_backup_are_independent_and_stopping_one_releases_only_its_ip(tmp_path: Path):
    entered: set[str] = set()
    exited: set[str] = set()
    gate = threading.Lock()

    def runner(**kwargs):
        ip = kwargs["target"]
        with gate:
            entered.add(ip)
        try:
            kwargs["stop_event"].wait(5)
            yield from ()
        finally:
            exited.add(ip)

    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    service = QuickPingService(site_id="demo", output_root=tmp_path / "raw", repository=repo, runner=runner)
    try:
        run_id = service.start(targets=[target("192.0.2.1"), target("192.0.2.2", address="BACKUP")])
        until(lambda: len(entered) == 2)
        with pytest.raises(QuickPingError, match="192.0.2.1") as error:
            service.start(targets=[target("192.0.2.3"), target("192.0.2.1", mr="alias")], config=QuickPingConfig(interval_ms=500))
        assert error.value.status_code == 409
        assert "192.0.2.3" not in service.active_ips()  # whole batch rollback
        service.stop_target(run_id, "192.0.2.1")
        assert "192.0.2.1" in exited
        assert service.active_ips() == {"192.0.2.2": run_id}
        assert repo.get_quick_ping_run(run_id)["target_runtime"]["192.0.2.1"]["state"] == "CANCELLED"
        assert service.status(run_id).target_runtime["192.0.2.2"]["state"] == "RUNNING"
        replacement = service.start(targets=[target("192.0.2.1", mr="alias")])
        assert replacement != run_id
    finally:
        service.close()
    assert not service.active_ips()


def test_four_worker_limit_keeps_queued_ips_reserved_and_all_stops_release(tmp_path: Path):
    entered: set[str] = set()
    def runner(**kwargs):
        entered.add(kwargs["target"])
        kwargs["stop_event"].wait(5)
        yield from ()
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=runner)
    try:
        run_id = service.start(targets=[target(f"192.0.2.{i}") for i in range(1, 7)])
        until(lambda: len(entered) == 4)
        run = service.status(run_id)
        assert sum(value["state"] == "QUEUED" for value in run.target_runtime.values()) == 2
        assert len(service.active_ips()) == 6
        with pytest.raises(QuickPingError):
            service.start(targets=[target("192.0.2.6", mr="alias")])
        service.stop(run_id)
        until(lambda: not service.active_ips())
        assert len(entered) == 4
    finally:
        service.close()


def test_atomic_reservations_across_connections_have_one_winner(tmp_path: Path):
    repos = [GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo") for _ in range(2)]
    barrier = threading.Barrier(3)
    results = []
    def reserve(index):
        barrier.wait()
        results.append((index, repos[index].reserve_quick_ping_ips(f"run-{index}", ["192.0.2.1", f"192.0.2.{index + 2}"], owner_pid=os.getpid(), owner_identity=process_identity(os.getpid()), max_active_runs=4)))
    threads = [threading.Thread(target=reserve, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    winners = [index for index, conflict in results if conflict is None]
    assert len(winners) == 1
    rows = repos[0].quick_ping_reservations()
    assert len(rows) == 2
    assert {row["run_id"] for row in rows} == {f"run-{winners[0]}"}
    assert all(row["lock_key"] == f"quick_ping:ip:{row['target_ip']}" for row in rows)


def test_live_owner_is_not_interrupted_by_second_service_restore(tmp_path: Path):
    def runner(**kwargs):
        kwargs["stop_event"].wait(5)
        yield from ()
    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    first = QuickPingService(site_id="demo", output_root=tmp_path / "raw", repository=repo, runner=runner)
    second = None
    try:
        run_id = first.start(targets=[target("192.0.2.1")])
        second = QuickPingService(site_id="demo", output_root=tmp_path / "raw", repository=repo, runner=runner)
        assert second.status(run_id).state == "RUNNING"
        with pytest.raises(QuickPingError):
            second.start(targets=[target("192.0.2.1", mr="alias")])
        second.close()
        assert first.active_ips() == {"192.0.2.1": run_id}
        assert first.status(run_id).state == "RUNNING"
        first.stop(run_id)
        assert second.status(run_id).state == "CANCELLED"
    finally:
        first.close()
        if second:
            second.close()


def test_recovery_retains_surviving_child_then_releases_after_actual_exit(tmp_path: Path):
    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    identity = process_identity(child.pid)
    assert matching_process(child.pid, identity)
    repo.reserve_quick_ping_ips("orphan", ["192.0.2.1"], owner_pid=2147483646, owner_identity="gone", max_active_runs=4)
    repo.record_quick_ping_child("orphan", "192.0.2.1", child.pid, identity)
    service = QuickPingService(site_id="demo", output_root=tmp_path / "raw", repository=repo, runner=lambda **_: iter(()))
    try:
        assert service.active_ips() == {"192.0.2.1": "orphan"}
        child.terminate()
        child.wait(timeout=5)
        assert not matching_process(child.pid, identity)
        service._recover_reservations()
        assert not service.active_ips()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        service.close()


def test_duplicate_ip_in_batch_is_rejected_before_any_reservation(tmp_path: Path):
    service = QuickPingService(site_id="demo", output_root=tmp_path, runner=lambda **_: iter(()))
    with pytest.raises(QuickPingError):
        service.start(targets=[target("192.0.2.1"), target("192.0.2.1", address="BACKUP")])
    assert not service.active_ips()
    service.close()


def test_retries_terminal_persistence_before_releasing_locally_owned_ip(tmp_path: Path, monkeypatch):
    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    service = QuickPingService(site_id="demo", output_root=tmp_path / "raw", repository=repo, runner=lambda **_: iter(()))
    original = service._write_manifest
    attempts = 0
    def fail_final_writes(run):
        nonlocal attempts
        attempts += 1
        if attempts in (2, 3):
            raise OSError("temporarily unavailable")
        original(run)
    monkeypatch.setattr(service, "_write_manifest", fail_final_writes)
    run_id = service.start(targets=[target("192.0.2.1")])
    until(lambda: service.status(run_id)._thread is not None and not service.status(run_id)._thread.is_alive())
    assert service.active_ips() == {"192.0.2.1": run_id}
    service._recover_reservations()
    assert not service.active_ips()
    assert repo.get_quick_ping_run(run_id)["target_runtime"]["192.0.2.1"]["state"] == "FAILED"
    service.close()


def test_real_fping_loopback_primary_backup_exit_precedes_ip_unlock(tmp_path: Path, monkeypatch):
    from netconsole.core.ping import fping_v5_runner
    executable = Path(__file__).resolve().parents[1] / "resources/tools/windows-x64/fping/fping.exe"
    if os.name != "nt" or not executable.is_file():
        pytest.skip("Windows bundled fping required")
    resolve = fping_v5_runner.resolve_fping_v5_paths
    monkeypatch.setattr(fping_v5_runner, "resolve_fping_v5_paths", lambda *_: resolve(fping_path=executable))
    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="demo")
    service = QuickPingService(site_id="demo", output_root=tmp_path / "raw", repository=repo)
    try:
        run_id = service.start(targets=[target("127.0.0.1"), target("127.0.0.2", address="BACKUP")])
        until(lambda: len(repo.quick_ping_reservations()) == 2 and all(row["child_pid"] for row in repo.quick_ping_reservations()))
        rows = {row["target_ip"]: row for row in repo.quick_ping_reservations()}
        assert rows["127.0.0.1"]["child_pid"] != rows["127.0.0.2"]["child_pid"]
        assert all(matching_process(row["child_pid"], row["child_identity"]) for row in rows.values())
        until(lambda: all(stats.received > 0 for stats in service.status(run_id).target_stats.values()))
        service.stop_target(run_id, "127.0.0.1")
        assert not matching_process(rows["127.0.0.1"]["child_pid"], rows["127.0.0.1"]["child_identity"])
        assert service.active_ips() == {"127.0.0.2": run_id}
        assert matching_process(rows["127.0.0.2"]["child_pid"], rows["127.0.0.2"]["child_identity"])
        service.stop(run_id)
        assert not service.active_ips()
        assert not matching_process(rows["127.0.0.2"]["child_pid"], rows["127.0.0.2"]["child_identity"])
    finally:
        service.close()
