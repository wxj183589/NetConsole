from __future__ import annotations

import base64
import errno
import gzip
import json
import queue
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.syslog_runtime import (
    RawCompressionWorker,
    RawStreamWriter,
    SyslogUdpReceiver,
    UdpEnvelope,
    recover_raw_files,
)


def _wait(predicate, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _receiver(tmp_path: Path) -> SyslogUdpReceiver:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver.start(
        run_id="stress", run_date="2026-09-04",
        active_dir=tmp_path / "ground" / "active" / "2026-09-04",
        listen_host="127.0.0.1", listen_port=0, queue_capacity=100,
        flush_records=100, flush_interval_seconds=0.05,
        event_batch_size=500, event_batch_interval_seconds=0.05,
    )
    return receiver


def test_20000_mock_ingress_burst_keeps_raw_and_bounded_queues(tmp_path: Path, monkeypatch) -> None:
    receiver = _receiver(tmp_path)
    barrier = threading.Event()
    process = receiver._process

    def blocked_parser(*args, **kwargs):
        assert barrier.wait(30)
        return process(*args, **kwargs)

    monkeypatch.setattr(receiver, "_process", blocked_parser)
    expected = 20_000
    payloads = {}
    try:
        # Mock the UDP ingress boundary to measure application queues separately
        # from the operating system's lossy datagram buffer.
        for index in range(1, expected + 1):
            payload = f"<134>UNKNOWN/6/BURST: sample={index}".encode()
            payloads[index] = payload
            envelope = UdpEnvelope(
                source_ip=f"127.0.0.{index % 8 + 1}", source_port=514,
                receive_time="2026-09-04T10:00:00+00:00",
                global_receive_sequence=index, source_receive_sequence=(index - 1) // 8 + 1,
                payload=payload,
            )
            receiver._received_count += 1
            try:
                receiver._queue.put_nowait(envelope)
            except queue.Full:
                receiver._spool_envelope(envelope)
            assert receiver._queue.qsize() <= receiver._queue.maxsize == 100
            assert receiver._parser_queue.qsize() <= receiver._parser_queue.maxsize == 100
        _wait(lambda: receiver.health_snapshot()["written"] == expected)
        assert receiver._parser_spool_count > 0
        assert receiver.health_snapshot()["dropped"] == 0
        barrier.set()
        _wait(lambda: receiver.health_snapshot()["parsed"] == expected)
    finally:
        barrier.set()
        stopped = receiver.stop(timeout_seconds=30)
    assert stopped["success"] and stopped["data_complete"], stopped
    actual = {}
    for row in receiver.repository.list_raw_files(data_type="syslog"):
        path = receiver.repository.db_path.parent / row["relative_path"]
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                sequence = record["global_receive_sequence"]
                assert sequence not in actual
                actual[sequence] = base64.b64decode(record["raw_bytes_base64"])
    assert actual == payloads


@pytest.mark.parametrize("data_type", ["syslog", "ping"])
def test_real_10mib_rotation_and_gzip_roundtrip(tmp_path: Path, data_type: str) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    worker = RawCompressionWorker(repository=repository, run_id="ten-mib", data_type=data_type)
    limit = 10 * 1024 * 1024
    writer = RawStreamWriter(
        root=tmp_path / "ground" / "active", repository=repository, site_id="site-a",
        run_id="ten-mib", run_date="2026-09-04", data_type=data_type,
        directory_name="fleet_ping" if data_type == "ping" else "syslog",
        flush_records=100, defer_registry=True, max_file_size_bytes=limit,
        compression_worker=worker,
    )
    for index in range(200):
        writer.write(
            {"train_id": "train-a", "mr_role": "CT", "index": index, "raw_text": "x" * 65536},
            datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
        )
    writer.close()
    assert writer.flush_metadata(timeout=10)
    assert worker.stop(timeout=10)
    rows = repository.list_raw_files(data_type=data_type)
    assert len(rows) == 2
    assert max(row["size_bytes"] for row in rows) >= limit - 66000
    indexes = []
    for row in rows:
        assert 0 < row["size_bytes"] <= limit
        path = repository.db_path.parent / row["relative_path"]
        with gzip.open(repository.db_path.parent / row["gzip_path"], "rb") as compressed:
            assert compressed.read() == path.read_bytes()
        with path.open(encoding="utf-8") as handle:
            indexes.extend(json.loads(line)["index"] for line in handle)
    assert sorted(indexes) == list(range(200))
    assert worker.snapshot()["compression_completed_count"] == 2


@pytest.mark.parametrize("data_type", ["syslog", "ping"])
def test_raw_replacement_mr_and_unresolved_sources_never_share_a_segment(
    tmp_path: Path, data_type: str,
) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    active = repository.db_path.parent / "active" / "2026-09-04"
    writer = RawStreamWriter(
        root=active if data_type == "ping" else active / "realtime",
        repository=repository, site_id="site-a", run_id="per-mr",
        run_date="2026-09-04", data_type=data_type,
        directory_name="fleet_ping" if data_type == "ping" else "syslog",
    )
    now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    identities = [
        {"device_uuid": "mr-before"}, {"mr_id": "mr-after"},
        {"device_uuid": "case-MR"}, {"device_uuid": "case-mr"},
        {"device_uuid": "unsafe/mr"}, {"device_uuid": "unsafe?mr"},
        {"device_uuid": "a" * 120 + "1"}, {"device_uuid": "a" * 120 + "2"},
        {"source_ip": "192.0.2.1"}, {"source_ip": "192.0.2.2"},
        {"target_ip": "192.0.2.3"}, {},
    ]
    file_ids = []
    for index, identity in enumerate(identities):
        file_id, _line = writer.write(
            {"train_id": "train-a", "mr_role": "CT", "index": index, **identity}, now,
        )
        file_ids.append(file_id)
    assert len(set(file_ids)) == len(identities)
    again_id, line = writer.write(
        {"train_id": "train-a", "mr_role": "CT", "index": 100, "device_uuid": "mr-before"}, now,
    )
    assert (again_id, line) == (file_ids[0], 2)
    # An hour boundary closes the same MR's old segment and opens a new one.
    next_id, _line = writer.write(
        {"train_id": "train-a", "mr_role": "CT", "index": 101, "device_uuid": "mr-before"},
        now.replace(hour=11),
    )
    assert next_id != file_ids[0]
    assert writer.open_file_count == 1
    assert all(row["status"] == "CLOSED" for row in repository.list_raw_files(data_type=data_type) if row["file_id"] != next_id)
    # Late replay may reopen an old hour, but must not close the newer live file.
    writer.write({"train_id": "train-a", "mr_role": "CT", "index": 102, "device_uuid": "mr-after"}, now)
    assert any(current.file_id == next_id for current in writer._files.values())
    writer.close()
    rows = repository.list_raw_files(data_type=data_type)
    assert len(rows) == len(identities) + 2
    windows_paths = {row["relative_path"].casefold() for row in rows}
    assert len(windows_paths) == len(rows)
    for row in rows:
        records = [json.loads(line) for line in (repository.db_path.parent / row["relative_path"]).read_text(encoding="utf-8").splitlines()]
        expected_uuid = records[0].get("device_uuid") or records[0].get("mr_id") or ""
        assert row["device_uuid"] == expected_uuid
        assert all((record.get("device_uuid") or record.get("mr_id") or "") == expected_uuid for record in records)
    # A fresh registry recovers current paths from raw facts without guessing
    # MR identity from directory names; older paths remain readable too.
    recovered = GroundUnattendedRepository(repository.db_path.parent / "recovered.sqlite", site_id="site-a")
    assert recover_raw_files(active_dir=active, repository=recovered, run_id="per-mr") == len(rows)
    actual = {row["relative_path"]: row for row in recovered.list_raw_files(data_type=data_type)}
    assert set(actual) == {row["relative_path"] for row in rows}
    for row in rows:
        assert actual[row["relative_path"]]["device_uuid"] == row["device_uuid"]


def test_raw_recovery_uses_stream_prefix_instead_of_nested_identity_name(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    active = repository.db_path.parent / "active" / "2026-09-04"
    legacy_syslog = active / "realtime" / "syslog" / "fleet_ping" / "CT" / "10.ndjson"
    legacy_ping = active / "fleet_ping" / "train-a" / "CT" / "10.ndjson"
    for path, mr_id in [(legacy_syslog, "syslog-mr"), (legacy_ping, "ping-mr")]:
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"train_id": "fleet_ping", "mr_id": mr_id}) + "\n", encoding="utf-8")
    assert recover_raw_files(active_dir=active, repository=repository, run_id="legacy") == 2
    assert repository.list_raw_files(data_type="syslog")[0]["device_uuid"] == "syslog-mr"
    assert repository.list_raw_files(data_type="ping")[0]["device_uuid"] == "ping-mr"


def test_enospc_raw_write_is_counted_and_reported_then_receiver_recovers(tmp_path: Path, monkeypatch) -> None:
    receiver = _receiver(tmp_path)
    health_events = []
    add_health = receiver.repository.add_health_event

    def collect_health(**kwargs):
        health_events.append(kwargs)
        return add_health(**kwargs)

    monkeypatch.setattr(receiver.repository, "add_health_event", collect_health)
    writer = receiver._writer
    assert writer is not None
    write = writer.write

    def fail_write(*args, **kwargs):
        raise OSError(errno.ENOSPC, "injected disk full")

    monkeypatch.setattr(writer, "write", fail_write)
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(b"<134>UNKNOWN/6/DISK: unavailable", ("127.0.0.1", port))
        _wait(lambda: receiver.health_snapshot()["raw_write_failed_count"] == 1)
        _wait(lambda: any(event["code"] == "SYSLOG_RAW_WRITE_FAILED" for event in health_events))
        assert receiver.health_snapshot()["dropped"] == 1
        assert receiver.health_snapshot()["parsed"] == 0
        monkeypatch.setattr(writer, "write", write)
        sender.sendto(b"<134>UNKNOWN/6/DISK: recovered", ("127.0.0.1", port))
        _wait(lambda: receiver.health_snapshot()["parsed"] == 1)
    stopped = receiver.stop(timeout_seconds=10)
    assert stopped["success"]
    assert stopped["data_complete"] is False
    assert stopped["raw_write_failed_count"] == stopped["dropped_count"] == 1
    errors = [event for event in health_events if event["code"] == "SYSLOG_RAW_WRITE_FAILED"]
    assert errors[0]["severity"] == "error"
    assert "injected disk full" in errors[0]["details"]["error"]
    rows = receiver.repository.list_raw_files(data_type="syslog")
    assert sum(row["record_count"] for row in rows) == 1
    raw = (receiver.repository.db_path.parent / rows[0]["relative_path"]).read_text(encoding="utf-8")
    assert "recovered" in raw and "unavailable" not in raw
