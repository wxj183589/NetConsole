from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.syslog_runtime import (
    RawStreamWriter,
    SyslogUdpReceiver,
)


def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _send(port: int, count: int, source: str = "127.0.0.1") -> None:
    payload = (
        b"%Jul  3 19:19:27:496 2026 MR-CT-01 "
        b"WMESH/5/MESH_LINKUP: Mesh link on interface WLAN-Radio1 is up: "
        b"peer MAC = 0000-0000-0001, peer radio mode = 1, RSSI = -55"
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        if source != "127.0.0.1":
            sender.bind((source, 0))
        for index in range(count):
            sender.sendto(payload, ("127.0.0.1", port))
            if index % 10 == 9:
                time.sleep(0.001)


def _fixture_payloads() -> list[bytes]:
    fixture = Path(__file__).parent / "fixtures" / "ground_unattended" / "h3c_mr_syslog_3cd.txt"
    return [line.encode("utf-8") for line in fixture.read_text(encoding="utf-8").splitlines()]


def _send_fixture(port: int, *, source: str, repeats: int = 1) -> int:
    payloads = _fixture_payloads()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.bind((source, 0))
        for _ in range(repeats):
            for payload in payloads:
                sender.sendto(payload, ("127.0.0.1", port))
    return len(payloads) * repeats


def _receiver(tmp_path: Path, capacity: int = 8) -> SyslogUdpReceiver:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver.start(
        run_id="stress-run",
        run_date="2026-09-04",
        active_dir=tmp_path / "ground" / "active" / "2026-09-04",
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=capacity,
        flush_records=100,
        flush_interval_seconds=0.05,
        event_batch_size=100,
        event_batch_interval_seconds=0.05,
    )
    return receiver


def test_udp_stress_1000_messages_has_no_application_drop(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    _send(port, 1000)
    _wait_until(lambda: receiver.health_snapshot()["written"] == 1000, timeout=30)
    health = receiver.health_snapshot()
    assert health["received"] == 1000
    assert health["written"] == 1000
    assert health["dropped"] == 0
    assert health["disk_queue_count"] >= 0
    _wait_until(lambda: receiver.health_snapshot()["parsed"] == 1000, timeout=60)
    stop_result = receiver.stop(timeout_seconds=30)
    assert stop_result["success"] is True, stop_result


def test_udp_stress_5000_messages_spools_when_parser_is_blocked(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    barrier = threading.Event()
    original = receiver.repository.commit_wmesh_projection_batch

    def blocked(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    receiver.repository.commit_wmesh_projection_batch = blocked  # type: ignore[method-assign]
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    _send(port, 5000)
    _wait_until(lambda: receiver.health_snapshot()["received"] == 5000, timeout=30)
    health = receiver.health_snapshot()
    assert health["received"] == 5000
    assert health["dropped"] == 0
    assert health["written"] > 0
    _wait_until(
        lambda: receiver.health_snapshot()["disk_queue_count"]
        + receiver.health_snapshot()["written"]
        + receiver._parser_spool_count
        + receiver.health_snapshot()["parser_queue_size"]
        >= 5000,
        timeout=30,
    )
    assert health["parser_queue_size"] >= 0
    barrier.set()
    _wait_until(lambda: receiver.health_snapshot()["written"] == 5000, timeout=60)
    _wait_until(lambda: receiver.health_snapshot()["parsed"] == 5000, timeout=60)
    stop_result = receiver.stop(timeout_seconds=30)
    assert stop_result["success"] is True, stop_result


def test_udp_clean_stop_restart_does_not_replay_consumed_spool(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    _send(port, 20)
    _wait_until(lambda: receiver.health_snapshot()["written"] == 20)
    _wait_until(lambda: receiver.health_snapshot()["parsed"] == 20)
    assert receiver.stop(timeout_seconds=10)["success"] is True

    repository = receiver.repository
    restarted = SyslogUdpReceiver(repository=repository, site_id="site-a")
    restarted.start(
        run_id="stress-run",
        run_date="2026-09-04",
        active_dir=tmp_path / "ground" / "active" / "2026-09-04",
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=8,
        flush_records=100,
        flush_interval_seconds=0.05,
        event_batch_size=100,
        event_batch_interval_seconds=0.05,
    )
    time.sleep(0.2)
    assert restarted.health_snapshot()["written"] == 0
    assert restarted.health_snapshot()["disk_queue_count"] == 0
    assert restarted.health_snapshot()["dropped"] == 0
    assert restarted.stop(timeout_seconds=10)["success"] is True


def test_udp_replay_existing_syslog_sample_one_mr(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    expected = _send_fixture(port, source="127.0.0.1", repeats=20)
    _wait_until(lambda: receiver.health_snapshot()["received"] == expected)
    _wait_until(lambda: receiver.health_snapshot()["parsed"] == expected)
    health = receiver.health_snapshot()
    assert {
        "received": health["received"],
        "raw_written": health["written"],
        "parsed": health["parsed"],
        "db_saved": health["db_saved"],
        "drop": health["dropped"],
    } == {
        "received": expected,
        "raw_written": expected,
        "parsed": expected,
        "db_saved": expected,
        "drop": 0,
    }
    assert receiver.stop(timeout_seconds=10)["success"] is True


def test_udp_replay_existing_syslog_sample_seven_mr_concurrent(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    expected_each = len(_fixture_payloads()) * 20
    workers = [
        threading.Thread(
            target=_send_fixture,
            kwargs={"port": port, "source": f"127.0.0.{index}", "repeats": 20},
        )
        for index in range(2, 9)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()
    expected = expected_each * 7
    _wait_until(lambda: receiver.health_snapshot()["received"] == expected, timeout=30)
    _wait_until(lambda: receiver.health_snapshot()["parsed"] == expected, timeout=30)
    health = receiver.health_snapshot()
    assert health["received"] == expected
    assert health["written"] == expected
    assert health["parsed"] == expected
    assert health["db_saved"] == expected
    assert health["dropped"] == 0
    assert receiver.stop(timeout_seconds=20)["success"] is True


def test_raw_syslog_rollover_closes_previous_hour(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active" / "realtime",
        repository=repository,
        site_id="site-a",
        run_id="rollover-run",
        run_date="2026-09-04",
        data_type="syslog",
        flush_records=1,
    )
    first = datetime(2026, 9, 4, 10, 59, tzinfo=timezone.utc)
    second = datetime(2026, 9, 4, 11, 0, tzinfo=timezone.utc)
    record = {"train_id": "mr-01", "mr_role": "CT", "raw_text": "sample"}
    writer.write(record, first)
    writer.write(record, second)
    assert writer.records_written == 2
    assert writer.open_file_count == 1
    assert len(repository.list_raw_files(data_type="syslog")) == 2
    assert writer.close() == 1
    assert writer.open_file_count == 0


def test_spool_is_managed_under_active_syslog_and_not_raw_recovery_input(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    spool_path = receiver._disk_spool_path
    parser_spool_path = receiver._parser_spool_path
    assert spool_path is not None and parser_spool_path is not None
    active_root = (tmp_path / "ground" / "active" / "2026-09-04").resolve()
    assert spool_path.resolve().is_relative_to(active_root)
    assert parser_spool_path.resolve().is_relative_to(active_root)
    assert spool_path.parent.name == "_spool"
    assert parser_spool_path.parent == spool_path.parent
    assert receiver.stop(timeout_seconds=10)["success"] is True
