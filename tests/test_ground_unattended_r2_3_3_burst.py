import gzip
import json
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.syslog_runtime import SyslogUdpReceiver


def _wait_until(predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _h3c_mesh_linkup(hostname: str, event_time: datetime, peer_mac: str) -> bytes:
    timestamp = (
        f"%{event_time:%b} {event_time.day:2d} {event_time:%H:%M:%S}"
        f":{event_time.microsecond // 1000:03d} {event_time.year}"
    )
    return (
        f"{timestamp} {hostname} %%10WMESH/5/MESH_LINKUP: "
        "Mesh Link on the interface WLAN-MeshLink841 is up: "
        f"peer MAC = {peer_mac}, peer radio mode = 3, RSSI = 25."
    ).encode("utf-8")


def test_short_udp_burst_50_trains_100_mrs_preserves_raw_and_position_metrics(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver.start(
        run_id="r2-3-3-burst",
        run_date="2026-11-10",
        active_dir=tmp_path / "ground" / "active" / "2026-11-10",
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=256,
        flush_records=50,
        flush_interval_seconds=0.05,
        event_batch_size=100,
        event_batch_interval_seconds=0.05,
    )
    total_mrs = 100
    total_trains = 50
    concurrent_senders = 10
    endpoints: dict[str, dict[str, object]] = {}
    for index in range(total_mrs):
        mr_index = index + 1
        hostname = f"R233-MR-{mr_index:03d}-{'CT' if index % 2 == 0 else 'CW'}"
        endpoints[hostname.casefold()] = {
            "device_uuid": f"r233-mr-{mr_index:03d}",
            "device_id": mr_index,
            "device_name": hostname,
            "train_id": f"r233-train-{(index // 2) + 1:03d}",
            "train_no": f"{(index // 2) + 1:03d}",
            "mr_role": "CT" if index % 2 == 0 else "CW",
        }
    receiver._endpoint_by_hostname = {
        hostname: [endpoint] for hostname, endpoint in endpoints.items()
    }

    def enrich(parsed: dict[str, object]) -> dict[str, object]:
        result = dict(parsed)
        details = dict(result.get("details") or {})
        raw_mac = str(result.get("peer_mac") or details.get("peer_mac") or "")
        is_b = raw_mac.casefold().startswith("0200-1000-")
        suffix = raw_mac.rsplit("-", 1)[-1]
        ap_name = f"R233-AP-{'B' if is_b else 'A'}-{suffix}"
        ap_id = f"r233-ap-{'b' if is_b else 'a'}-{suffix}"
        normalized_mac = (
            raw_mac.replace("-", ":")
            if ":" not in raw_mac
            else raw_mac
        )
        result.update(
            {
                "peer_name": ap_name,
                "station": "站点-R233",
                "section": "区间-R233",
            }
        )
        details.update(
            {
                "peer_ap_id": ap_id,
                "peer_ap_name": ap_name,
                "peer_ap_mac": normalized_mac,
                "identity_status": "matched",
                "resolution_status": "PHYSICAL_AP",
            }
        )
        result["details"] = details
        return result

    receiver._ap_resolver.enrich_parsed = enrich  # type: ignore[method-assign]
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    base_event_time = datetime.now().astimezone().replace(microsecond=0) + timedelta(
        seconds=1
    )
    plans: list[list[bytes]] = []
    for index in range(total_mrs):
        mr_index = index + 1
        hostname = f"R233-MR-{mr_index:03d}-{'CT' if index % 2 == 0 else 'CW'}"
        ap_a_mac = f"0200-0000-{mr_index:04x}"
        ap_b_mac = f"0200-1000-{mr_index:04x}"
        ap_a = _h3c_mesh_linkup(hostname, base_event_time, ap_a_mac)
        ap_b = _h3c_mesh_linkup(
            hostname, base_event_time + timedelta(seconds=2), ap_b_mac
        )
        delayed_a = _h3c_mesh_linkup(
            hostname, base_event_time + timedelta(seconds=1), ap_a_mac
        )
        records = [ap_a, ap_b]
        if index == 0:
            # Delayed arrival must remain in history but cannot move Current
            # back from the newer AP-B state.
            records.append(delayed_a)
        if index == 1:
            # The same device-time/AP event is a duplicate projection, while
            # its raw line remains part of the append-only raw stream.
            records.append(ap_b)
        plans.append(records)

    burst_started = time.monotonic()

    def sender(items: list[list[bytes]]) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for payloads in items:
                for payload in payloads:
                    sock.sendto(payload, ("127.0.0.1", port))

    groups = [plans[offset::concurrent_senders] for offset in range(concurrent_senders)]
    threads = [threading.Thread(target=sender, args=(group,)) for group in groups]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    events_sent = sum(len(items) for items in plans)

    _wait_until(lambda: receiver.health_snapshot()["received"] == events_sent)
    _wait_until(
        lambda: receiver.health_snapshot()["parsed"] == events_sent
        and receiver.health_snapshot()["database_pending_count"] == 0
    )
    elapsed = time.monotonic() - burst_started
    health_before_stop = receiver.health_snapshot()
    stop_result = receiver.stop(timeout_seconds=30)
    assert stop_result["success"] is True, stop_result
    health = receiver.health_snapshot()

    assert health["received"] == events_sent
    assert health["written"] == events_sent
    assert health["parsed"] == events_sent
    assert health["dropped"] == 0
    assert health["parse_error_count"] == 0
    assert health["position_out_of_order_count"] >= 1
    assert health["position_duplicate_count"] >= 1
    assert health["position_latency_p95_ms"] is not None
    assert health["position_latency_p99_ms"] is not None
    assert all(
        thread_name not in {thread.name for thread in threading.enumerate()}
        for thread_name in (
            "ground-syslog-recv-site-a",
            "ground-syslog-writer-site-a",
            "ground-syslog-process-site-a",
            "ground-syslog-compressor",
        )
    )

    for index in range(total_mrs):
        mr_index = index + 1
        state = repository.get_syslog_position_state(f"r233-mr-{mr_index:03d}")
        assert state is not None
        assert state["current_ap_name"].startswith("R233-AP-B-")
        assert state["position_status"] == "VALID"
        assert state["position_source"] == "SYSLOG"
        assert state["station"] == "站点-R233"
        assert state["previous_ap_name"].startswith("R233-AP-A-")

    raw_files = repository.list_raw_files(data_type="syslog")
    assert raw_files
    assert sum(int(row["record_count"] or 0) for row in raw_files) == events_sent
    for row in raw_files:
        raw_path = repository.db_path.parent / str(row["relative_path"])
        gzip_path = repository.db_path.parent / str(row["gzip_path"])
        assert raw_path.is_file()
        assert gzip_path.is_file()
        with gzip.open(gzip_path, "rb") as handle:
            assert handle.read(1)

    stats = {
        "seed": "R2.3.3-short-burst-2303",
        "train_count": total_trains,
        "mr_count": total_mrs,
        "events_sent": events_sent,
        "event_type_distribution": {"MESH_LINKUP": events_sent},
        "avg_payload_bytes": round(
            sum(len(payload) for items in plans for payload in items) / events_sent, 3
        ),
        "duration_seconds": round(elapsed, 3),
        "concurrent_senders": concurrent_senders,
        "receive_eps": round(events_sent / max(elapsed, 0.001), 3),
        "health": {
            key: health[key]
            for key in (
                "received",
                "written",
                "parsed",
                "dropped",
                "parser_queue_size",
                "raw_writer_queue_length",
                "oldest_unprocessed_log_wait_seconds",
                "position_update_count",
                "position_duplicate_count",
                "position_out_of_order_count",
                "position_latency_p50_ms",
                "position_latency_p95_ms",
                "position_latency_p99_ms",
                "stage_receive_to_raw_p95_ms",
                "stage_raw_to_parse_p95_ms",
                "stage_parse_to_position_p95_ms",
            )
        },
        "health_during_drain": {
            key: health_before_stop[key]
            for key in (
                "udp_receive_rate_per_second",
                "parser_rate_per_second",
                "parser_queue_size",
                "raw_writer_queue_length",
                "oldest_unprocessed_log_wait_seconds",
            )
        },
        "raw_file_count": len(raw_files),
        "raw_record_count": sum(int(row["record_count"] or 0) for row in raw_files),
        "raw_gzip_readable": True,
        "stop": stop_result,
    }
    print("R2_3_3_BURST_STATS=" + json.dumps(stats, ensure_ascii=False, sort_keys=True))
