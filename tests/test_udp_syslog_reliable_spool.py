from __future__ import annotations

import socket
import sqlite3
import errno
import gzip
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import netconsole.services.ground_unattended.syslog_runtime as syslog_runtime
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.syslog_runtime import (
    RawCompressionWorker,
    RawStreamWriter,
    SyslogUdpReceiver,
    UdpEnvelope,
)


@pytest.mark.parametrize("receive_time, expected_source", [
    ("2026-07-03T19:19:29.496+00:00", "DEVICE_TIME"),
    ("2026-07-03T19:20:27.496+00:00", "RECEIVE_TIME"),
])
def test_live_and_replayed_timeline_preserve_device_and_receive_times(
    tmp_path: Path, receive_time: str, expected_source: str
) -> None:
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver._run_id = "time-run"
    endpoint = {"device_uuid": "mr-ct", "device_name": "MR-CT-01", "train_id": "train-1", "mr_role": "CT"}
    receiver._endpoint_by_ip["192.0.2.1"] = [endpoint]
    receiver._endpoint_by_hostname["mr-ct-01"] = [endpoint]
    captured: list[dict] = []

    def write(record, _received):
        captured.append(record)
        return "raw-1", 1

    receiver._writer = SimpleNamespace(write=write, _files={})
    receiver._process(UdpEnvelope(
        source_ip="192.0.2.1", source_port=514, receive_time=receive_time,
        global_receive_sequence=1, source_receive_sequence=1,
        payload=(b"%Jul  3 19:19:27:496 2026 MR-CT-01 WMESH/5/MESH_LINKUP: "
                 b"Mesh link on interface WLAN-Radio1 is up: peer MAC = 0000-0000-0001, "
                 b"peer radio mode = 1, RSSI = -55"),
    ))
    assert len(receiver._timeline_batch) == 1
    recovered = receiver._recovered_projection(captured[0], raw_file_id="raw-1", raw_line_number=1)
    assert recovered is not None
    for event, timeline in [(receiver._event_batch[0], receiver._timeline_batch[0]), recovered]:
        assert timeline["details"]["device_time"] == "2026-07-03T19:19:27.496+00:00"
        assert timeline["details"]["received_at"] == receive_time
        assert timeline["details"]["event_time_source"] == expected_source
        assert timeline["ts"] == event["event_time"]
        assert timeline["ts"] == (
            "2026-07-03T19:19:27.496+00:00" if expected_source == "DEVICE_TIME" else receive_time
        )


def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_metadata_is_ordered_bounded_and_retries_transient_sqlite_lock(tmp_path: Path, monkeypatch) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    entered, release = threading.Event(), threading.Event()
    original = repository.upsert_raw_file
    calls = 0
    def blocked(values):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(5)
        if calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(values)
    monkeypatch.setattr(repository, "upsert_raw_file", blocked)
    writer = RawStreamWriter(root=tmp_path / "ground" / "raw", repository=repository, site_id="site-a", run_id="bounded", run_date="2026-11-07", data_type="syslog", defer_registry=True, max_file_size_bytes=100)
    baseline = sum(t.name == "ground-metadata-registry" for t in threading.enumerate())
    try:
        for _ in range(50):
            writer.write({"raw_text": "x" * 70}, datetime.now(timezone.utc))
        assert entered.wait(1)
        assert sum(t.name == "ground-metadata-registry" for t in threading.enumerate()) <= baseline + 1
        assert writer._metadata_queue.qsize() <= 100
        writer.close()
    finally:
        release.set()
    assert writer.flush_metadata(10)
    assert all(row["status"] == "CLOSED" for row in repository.list_raw_files())


def test_projection_error_recovers_after_deferred_raw_registration(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver._raw_checkpoints = {"late-raw": 1}
    assert not receiver._flush_events()
    assert "raw file not found" in receiver.health_snapshot()["last_error"]
    assert receiver._raw_checkpoints == {"late-raw": 1}
    repository.upsert_raw_file({
        "file_id": "late-raw", "run_id": "late", "data_type": "syslog",
        "relative_path": "late.ndjson", "status": "CLOSED", "record_count": 1,
    })
    receiver._last_error = "unrelated receiver error"
    assert receiver._flush_events()
    assert receiver._raw_checkpoints == {}
    assert repository.get_raw_file("late-raw")["parse_status"] == "PARSED"
    assert receiver.health_snapshot()["last_error"] == "unrelated receiver error"
    receiver._last_error = ""
    assert receiver.health_snapshot()["last_error"] == ""


def test_failed_raw_fsync_retains_open_owner_for_retry(tmp_path: Path, monkeypatch) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    writer = RawStreamWriter(root=tmp_path / "ground" / "raw", repository=repository, site_id="site-a", run_id="disk", run_date="2026-11-07", data_type="syslog")
    writer.write({"raw_text": "preserve"}, datetime.now(timezone.utc))
    original = syslog_runtime.os.fsync
    def fail(_):
        raise OSError(errno.ENOSPC, "no space left")
    monkeypatch.setattr(syslog_runtime.os, "fsync", fail)
    with pytest.raises(OSError):
        writer.close()
    assert writer.open_file_count == 1
    monkeypatch.setattr(syslog_runtime.os, "fsync", original)
    assert writer.close() == 1


def test_gzip_duplicate_submission_and_transient_failure(tmp_path: Path, monkeypatch) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    worker = RawCompressionWorker(repository=repository)
    writer = RawStreamWriter(root=tmp_path / "ground" / "raw", repository=repository, site_id="site-a", run_id="gzip", run_date="2026-11-07", data_type="syslog")
    file_id, _ = writer.write({"raw_text": "preserve"}, datetime.now(timezone.utc))
    writer.close()
    values = repository.get_raw_file(file_id)
    path = repository.db_path.parent / values["relative_path"]
    entered, release = threading.Event(), threading.Event()
    original = worker._compress
    calls = 0
    def flaky(values, path):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(5)
        if calls == 1:
            raise OSError("temporary gzip failure")
        original(values, path)
    monkeypatch.setattr(worker, "_compress", flaky)
    try:
        assert worker.submit(values, path)
        assert entered.wait(1)
        for _ in range(20):
            assert worker.submit(values, path)
    finally:
        release.set()
    assert worker.stop(10)
    assert calls == 2
    assert worker.snapshot()["compression_submitted_count"] == 1
    assert worker.snapshot()["compression_completed_count"] == 1
    assert path.is_file()
    assert repository.get_raw_file(file_id)["gzip_path"]


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


def test_udp_start_bind_failure_closes_spool_handles(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        port = int(blocker.getsockname()[1])
        with pytest.raises(OSError):
            receiver.start(
                run_id="bind-failure",
                run_date="2026-09-04",
                active_dir=tmp_path / "ground" / "active" / "2026-09-04",
                listen_host="127.0.0.1",
                listen_port=port,
                queue_capacity=8,
                flush_records=100,
                flush_interval_seconds=0.05,
                event_batch_size=100,
                event_batch_interval_seconds=0.05,
            )

    assert receiver._disk_spool_handle is None
    assert receiver._parser_spool_handle is None
    assert receiver._disk_spool_read_handle is None
    assert receiver._parser_spool_read_handle is None
    assert receiver.running is False


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


def test_raw_syslog_size_rollover_compresses_closed_files_in_background(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    worker = RawCompressionWorker(repository=repository, run_id="size-run")
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active" / "realtime",
        repository=repository,
        site_id="site-a",
        run_id="size-run",
        run_date="2026-09-04",
        data_type="syslog",
        flush_records=1,
        defer_registry=True,
        max_file_size_bytes=100,
        compression_worker=worker,
    )
    received = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    record = {"train_id": "mr-01", "mr_role": "CT", "raw_text": "x" * 28}

    writer.write(record, received)
    writer.write(record, received)
    assert writer.open_file_count == 1
    assert writer.close() == 1
    assert writer.flush_metadata(timeout=5)
    assert worker.stop(timeout=5)

    files = repository.list_raw_files(data_type="syslog")
    assert len(files) == 2
    assert len({str(item["relative_path"]) for item in files}) == 2
    for item in files:
        raw_path = repository.db_path.parent / str(item["relative_path"])
        gzip_path = repository.db_path.parent / str(item["gzip_path"])
        assert raw_path.is_file()
        assert raw_path.stat().st_size <= 100
        assert gzip_path.is_file()
        with gzip.open(gzip_path, "rt", encoding="utf-8") as compressed:
            assert '"raw_text":"' + "x" * 28 + '"' in compressed.read()
    assert worker.snapshot()["compression_completed_count"] == 2


def test_raw_syslog_compression_failure_keeps_original_and_records_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    def fail_compressed_registration(file_id: str, path: str) -> bool:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(repository, "register_raw_gzip", fail_compressed_registration)
    worker = RawCompressionWorker(repository=repository, run_id="failure-run")
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active" / "realtime",
        repository=repository,
        site_id="site-a",
        run_id="failure-run",
        run_date="2026-09-04",
        data_type="syslog",
        flush_records=1,
        defer_registry=True,
        compression_worker=worker,
    )
    file_id, _ = writer.write(
        {"train_id": "mr-01", "mr_role": "CT", "raw_text": "kept raw"},
        datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
    )
    writer.close()
    assert writer.flush_metadata(timeout=5)
    assert worker.stop(timeout=5)

    raw_file = repository.get_raw_file(file_id)
    assert raw_file is not None
    raw_path = repository.db_path.parent / str(raw_file["relative_path"])
    assert raw_path.is_file()
    assert "kept raw" in raw_path.read_text(encoding="utf-8")
    assert raw_file["gzip_path"] == ""
    assert not raw_path.with_name(raw_path.name + ".gz").exists()
    assert worker.snapshot()["compression_failed_count"] == 1
    health_event = repository.latest_health_event()
    assert health_event is not None
    assert health_event["code"] == "SYSLOG_COMPRESSION_FAILED"


@pytest.mark.parametrize("archive_before_registration", [False, True])
def test_raw_gzip_registration_preserves_concurrent_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_before_registration: bool,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    register = repository.register_raw_gzip

    def update_before_register(file_id: str, relative_path: str) -> bool:
        row = repository.get_raw_file(file_id)
        assert row is not None
        repository.upsert_raw_file({**row, "parse_status": "PARSED"})
        if archive_before_registration:
            repository.mark_raw_files_archived("race-run", "archives/run.zip")
        return register(file_id, relative_path)

    monkeypatch.setattr(repository, "register_raw_gzip", update_before_register)
    worker = RawCompressionWorker(repository=repository, run_id="race-run")
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active" / "realtime",
        repository=repository,
        site_id="site-a",
        run_id="race-run",
        run_date="2026-09-04",
        data_type="syslog",
        flush_records=1,
        defer_registry=True,
        compression_worker=worker,
    )
    file_id, _ = writer.write(
        {"train_id": "mr-01", "mr_role": "CT", "raw_text": "sample"},
        datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
    )
    writer.close()
    assert writer.flush_metadata(timeout=5)
    assert worker.stop(timeout=5)
    row = repository.get_raw_file(file_id)
    assert row is not None
    assert row["parse_status"] == "PARSED"
    raw_path = repository.db_path.parent / str(row["relative_path"])
    if archive_before_registration:
        assert row["archive_status"] == "ARCHIVED"
        assert row["compressed_path"] == "archives/run.zip"
        assert row["gzip_path"] == ""
        assert not raw_path.with_name(raw_path.name + ".gz").exists()
    else:
        assert row["compressed_path"] == ""
        assert row["gzip_path"]
        assert (repository.db_path.parent / row["gzip_path"]).is_file()


def test_raw_metadata_preserves_open_close_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    upsert = repository.upsert_raw_file
    open_started = threading.Event()
    release_open = threading.Event()

    def delayed_open(values: dict[str, object]) -> None:
        if values.get("status") == "OPEN":
            open_started.set()
            assert release_open.wait(5)
        upsert(values)

    monkeypatch.setattr(repository, "upsert_raw_file", delayed_open)
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active" / "realtime", repository=repository,
        site_id="site-a", run_id="order-run", run_date="2026-09-04",
        data_type="syslog", defer_registry=True,
    )
    file_id, _ = writer.write(
        {"train_id": "mr-01", "mr_role": "CT", "raw_text": "sample"},
        datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
    )
    assert open_started.wait(5)
    writer.close()
    release_open.set()
    assert writer.flush_metadata(timeout=5)
    assert repository.get_raw_file(file_id)["status"] == "CLOSED"


@pytest.mark.parametrize("blocked_status", ["OPEN", "CLOSED"])
def test_receiver_metadata_timeout_keeps_owner_and_compressor_until_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_status: str,
) -> None:
    receiver = _receiver(tmp_path)
    repository = receiver.repository
    upsert = repository.upsert_raw_file
    metadata_started = threading.Event()
    release_metadata = threading.Event()

    def blocked_metadata(values: dict[str, object]) -> None:
        if values.get("status") == blocked_status:
            metadata_started.set()
            assert release_metadata.wait(15)
        upsert(values)

    monkeypatch.setattr(repository, "upsert_raw_file", blocked_metadata)
    writer, compressor = receiver._writer, receiver._compression_worker
    assert writer is not None and compressor is not None
    try:
        port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
        _send(port, 1)
        _wait_until(lambda: receiver.health_snapshot()["parsed"] == 1)
        if blocked_status == "OPEN":
            assert metadata_started.wait(5)
        incomplete = receiver.stop(timeout_seconds=0.5)
        assert metadata_started.wait(5)
        assert not incomplete["success"]
        assert not incomplete["metadata_flushed"]
        assert not incomplete["compression_flushed"]
        assert receiver._writer is writer
        assert receiver._compression_worker is compressor
        assert receiver._run_id == "stress-run"
        assert compressor.alive
        assert not compressor._stop.is_set()

        release_metadata.set()
        stopped = receiver.stop(timeout_seconds=10)
        assert stopped["success"], stopped
        assert stopped["metadata_flushed"] and stopped["compression_flushed"]
        assert stopped["data_complete"]
        assert receiver._writer is None and receiver._compression_worker is None
        assert receiver._run_id == ""
        assert not compressor.alive
        assert writer.flush_metadata(timeout=0)
        assert compressor.snapshot()["compression_submitted_count"] == 1
        assert compressor.snapshot()["compression_completed_count"] == 1
        row = repository.list_raw_files(data_type="syslog")[0]
        assert row["status"] == "CLOSED"
        assert row["gzip_path"]
        with gzip.open(repository.db_path.parent / row["gzip_path"], "rb") as handle:
            assert handle.read() == (repository.db_path.parent / row["relative_path"]).read_bytes()
    finally:
        release_metadata.set()
        receiver.stop(timeout_seconds=10)


def test_corrupt_compressed_syslog_is_not_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    verify = syslog_runtime._verify_compressed_raw

    def corrupt_then_verify(path: Path, size: int, digest: str) -> None:
        with path.open("r+b") as handle:
            handle.seek(-8, 2)
            handle.write(b"\x00\x00\x00\x00")
        verify(path, size, digest)

    monkeypatch.setattr(syslog_runtime, "_verify_compressed_raw", corrupt_then_verify)
    worker = RawCompressionWorker(repository=repository, run_id="corrupt-run")
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active" / "realtime",
        repository=repository,
        site_id="site-a",
        run_id="corrupt-run",
        run_date="2026-09-04",
        data_type="syslog",
        flush_records=1,
        defer_registry=True,
        compression_worker=worker,
    )
    file_id, _ = writer.write(
        {"train_id": "mr-01", "mr_role": "CT", "raw_text": "kept raw"},
        datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
    )
    writer.close()
    assert writer.flush_metadata(timeout=5)
    assert worker.stop(timeout=5)
    raw_file = repository.get_raw_file(file_id)
    assert raw_file is not None
    raw_path = repository.db_path.parent / str(raw_file["relative_path"])
    assert "kept raw" in raw_path.read_text(encoding="utf-8")
    assert raw_file["gzip_path"] == ""
    assert not raw_path.with_name(raw_path.name + ".gz").exists()
    assert worker.snapshot()["compression_failed_count"] == 1
    assert repository.latest_health_event()["code"] == "SYSLOG_COMPRESSION_FAILED"


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


def test_spool_metrics_report_growth_without_changing_raw_pipeline(tmp_path: Path) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    spool_path = receiver._disk_spool_path
    assert spool_path is not None
    extra = spool_path.parent / "pending.ndjson"
    extra.write_text('{"pending":true}\n', encoding="utf-8")
    health = receiver.health_snapshot()
    assert health["spool_bytes"] >= extra.stat().st_size
    assert health["spool_files"] >= 3
    assert health["spool_guard_state"] == "NORMAL"
    assert receiver.stop(timeout_seconds=10)["success"] is True


def test_spool_disk_guard_emits_threshold_and_recovery_events(tmp_path: Path, monkeypatch) -> None:
    receiver = _receiver(tmp_path, capacity=8)
    usage_percent = {"value": 10.0}

    def fake_disk_usage(_path):
        used = usage_percent["value"]
        return SimpleNamespace(total=100, used=used, free=100 - used)

    monkeypatch.setattr(syslog_runtime.shutil, "disk_usage", fake_disk_usage)
    assert receiver.health_snapshot()["spool_guard_state"] == "NORMAL"
    for expected_usage, expected_state, expected_code in (
        (70.0, "WARNING", "SYSLOG_SPOOL_DISK_WARNING"),
        (85.0, "CRITICAL", "SYSLOG_SPOOL_DISK_CRITICAL"),
        (95.0, "EMERGENCY", "SYSLOG_SPOOL_DISK_EMERGENCY"),
    ):
        usage_percent["value"] = expected_usage
        health = receiver.health_snapshot()
        assert health["disk_usage_percent"] == expected_usage
        assert health["disk_free_bytes"] == int(100 - expected_usage)
        assert health["spool_guard_state"] == expected_state
        assert receiver.repository.latest_health_event()["code"] == expected_code  # type: ignore[index]
    usage_percent["value"] = 10.0
    assert receiver.health_snapshot()["spool_guard_state"] == "NORMAL"
    assert receiver.repository.latest_health_event()["code"] == "SYSLOG_SPOOL_DISK_RECOVERED"  # type: ignore[index]
    assert receiver.stop(timeout_seconds=10)["success"] is True
