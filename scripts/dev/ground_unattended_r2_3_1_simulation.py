"""Run the R2.3.1 Ground unattended local three-chain simulation.

This is intentionally a bounded, synthetic validation runner.  It uses only
loopback UDP, documentation-range heartbeat addresses, and a fresh SQLite
database under the Workspace test-data container.  It does not read or write
either production data root.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.ac_reconciliation import (
    AcSnapshotEnvelope,
    diff_full_snapshot,
    reconcile_syslog_ac,
)
from netconsole.services.ground_unattended.fleet_ping import (
    FleetPingSupervisor,
    FleetPingTarget,
)
from netconsole.services.ground_unattended.syslog_runtime import SyslogUdpReceiver


SITE_ID = "r2-3-1-sim-site"
MR_COUNT = 100
POSITION_EVENTS_PER_MR = 4
EXPECTED_SYSLOG_MESSAGES = MR_COUNT * POSITION_EVENTS_PER_MR + 2
EXPECTED_SYSLOG_PROJECTIONS = MR_COUNT * 3 + 2


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _wait_for(predicate, *, timeout: float, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _fixture_line(*, hostname: str, peer_mac: str, at: datetime) -> bytes:
    # This follows the sanitized H3C WMESH fixture format used by the parser
    # tests, with only synthetic host/MAC/time values.
    return (
        f"<189>{at.strftime('%b %d %H:%M:%S')}:{at.microsecond // 1000:03d} "
        f"{at.year} {hostname} %%10WMESH/5/MESH_LINKUP: "
        "Mesh Link on the interface WLAN-MeshLink841 is up: "
        f"peer MAC = {peer_mac}, peer radio mode = 3, RSSI = 25"
    ).encode("utf-8")


def _primary_ip(index: int) -> str:
    return f"127.0.1.{index}"


def _backup_ip(index: int) -> str:
    return f"127.0.2.{index}"


def _ap_mac(index: int, suffix: str) -> str:
    return f"02{index // 256:02x}-{index % 256:04x}-{suffix}"


def _ap_display(mac: str) -> str:
    return mac.replace("-", ":")


def _inventory() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    trains = [
        {
            "train_id": f"sim-train-{index:03d}",
            "train_no": f"SIM-{index:03d}",
            "train_name": f"Synthetic train {index:03d}",
        }
        for index in range(1, MR_COUNT + 1)
    ]
    endpoints = [
        {
            "device_uuid": f"sim-mr-{index:03d}",
            "device_id": index,
            "train_id": f"sim-train-{index:03d}",
            "mr_role": "CT" if index % 2 else "CW",
            "device_name": f"SIM-MR-{index:03d}",
            "source_hostname": f"SIM-MR-{index:03d}",
            "management_ip": _primary_ip(index),
            "backup_management_ip": _backup_ip(index),
        }
        for index in range(1, MR_COUNT + 1)
    ]
    return trains, endpoints


def _make_ap_enricher():
    known: dict[str, tuple[str, str]] = {}
    for index in range(1, MR_COUNT + 1):
        known[_ap_mac(index, "0001")] = (f"SIM-AP-A-{index:03d}", "A")
        known[_ap_mac(index, "0002")] = (f"SIM-AP-B-{index:03d}", "B")
        known[_ap_mac(index, "0003")] = (f"SIM-AP-C-{index:03d}", "C")

    def enrich(parsed: dict[str, Any]) -> dict[str, Any]:
        result = dict(parsed)
        details = dict(result.get("details") or {})
        peer_mac = str(result.get("peer_mac") or details.get("peer_mac") or "")
        identity = known.get(peer_mac)
        if identity is None:
            details.update(
                {
                    "identity_status": "UNKNOWN_AP",
                    "resolution_status": "UNKNOWN_AP",
                    "peer_ap_id": "",
                    "peer_ap_name": "",
                    "peer_ap_mac": "",
                }
            )
            result["details"] = details
            return result
        ap_name, section = identity
        result.update(
            {
                "peer_name": ap_name,
                "peer_mac": peer_mac,
                "station": "SIM-STATION",
                "section": f"SIM-SECTION-{section}",
            }
        )
        details.update(
            {
                "identity_status": "matched",
                "resolution_status": "PHYSICAL_AP",
                "peer_ap_id": ap_name.casefold(),
                "peer_ap_name": ap_name,
                "peer_ap_mac": _ap_display(peer_mac),
            }
        )
        result["details"] = details
        return result

    return enrich


def _fake_fping_runner(*, targets, stop_event, **_kwargs):
    sequence = 0
    while not stop_event.is_set():
        sequence += 1
        timestamp = _iso(_now())
        for target in targets:
            if stop_event.is_set():
                return
            yield FpingV5Sample(
                ts=timestamp,
                target=str(target),
                seq=sequence,
                ok=True,
                rtt_ms=1.0 + (sequence % 5) * 0.1,
                timeout_ms=1000,
                size=64,
                error="",
                backend=BACKEND,
                raw_type="response",
                raw={"simulated": True},
            )
        stop_event.wait(0.03)


def _heartbeat_targets() -> list[FleetPingTarget]:
    result: list[FleetPingTarget] = []
    for index in range(1, MR_COUNT + 1):
        for address, role in ((_primary_ip(index), "primary"), (_backup_ip(index), "backup")):
            result.append(
                FleetPingTarget(
                    target_ip=address,
                    train_id=f"sim-train-{index:03d}",
                    train_no=f"SIM-{index:03d}",
                    mr_id=f"sim-mr-{index:03d}",
                    mr_position_code="CT" if index % 2 else "CW",
                    mr_name=f"SIM-MR-{index:03d}",
                    device_id=index,
                    station="SIM-STATION",
                    section=f"SIM-{role}",
                )
            )
    return result


def _ac_row(index: int, *, ap: str, snapshot: int, received_at: str, device_time: str) -> dict[str, Any]:
    return {
        "snapshot_id": f"ac-snapshot-{snapshot}",
        "site_id": SITE_ID,
        "run_id": "sim-run-ac",
        "ac_device_id": "sim-ac-01",
        "source_snapshot_id": snapshot,
        "device_time": device_time,
        "received_at": received_at,
        "train_id": f"sim-train-{index:03d}",
        "train_no": f"SIM-{index:03d}",
        "mr_id": f"sim-mr-{index:03d}",
        "mr_position_code": "CT" if index % 2 else "CW",
        "mr_online_status": "online",
        "peer_ap_name": f"SIM-AP-{ap}-{index:03d}",
        "peer_ap_mac": f"02:00:{index // 256:02x}:{index % 256:02x}:00:01",
        "station": "SIM-STATION",
        "section": f"SIM-SECTION-{ap}",
        "mileage": str(index),
        "rssi": -40,
        "freshness_status": "fresh",
        "raw_source_reference": "synthetic-ac-fixture",
    }


def _run_ac_chain(repository: GroundUnattendedRepository, result: dict[str, Any]) -> None:
    started = time.monotonic()
    previous: AcSnapshotEnvelope | None = None
    delta_counts: list[dict[str, int]] = []
    received_at = _iso(_now())
    for snapshot_number, ap in ((1, "A"), (2, "B"), (3, "B")):
        now = _now()
        rows = [_ac_row(index, ap=ap, snapshot=snapshot_number, received_at=received_at, device_time=_iso(now - timedelta(seconds=3 - snapshot_number))) for index in range(1, MR_COUNT + 1)]
        if snapshot_number == 2:
            rows = [row for row in rows if row["mr_id"] != "sim-mr-100"]
            rows.append({**_ac_row(101, ap="B", snapshot=snapshot_number, received_at=received_at, device_time=_iso(now)), "mr_id": ""})
        current = AcSnapshotEnvelope(
            controller_id="sim-ac-01",
            snapshot_id=f"ac-snapshot-{snapshot_number}",
            rows=tuple(rows),
            device_time=rows[0]["device_time"] if rows else _iso(now),
            received_at=received_at,
            data_status="fresh",
            complete=True,
        )
        delta = diff_full_snapshot(previous, current)
        delta_counts.append(delta.counts)
        repository.insert_ac_delta_rows(
            item.to_record(
                site_id=SITE_ID,
                run_id="sim-run-ac",
                created_at=_iso(_now()),
            )
            for item in delta.records
        )
        repository.insert_ac_rows(rows)
        previous = current
    result["delta_counts"] = delta_counts
    result["delta_rows_persisted"] = len(repository.list_ac_deltas("sim-run-ac", limit=10000))
    result["duration_ms"] = round((time.monotonic() - started) * 1000.0, 3)


def _raw_record_count(repository: GroundUnattendedRepository) -> int:
    return sum(int(row.get("record_count") or 0) for row in repository.list_raw_files(data_type="syslog"))


def _run_simulation(root: Path) -> dict[str, Any]:
    repository = GroundUnattendedRepository(root / "ground" / "index.sqlite", site_id=SITE_ID)
    trains, endpoints = _inventory()
    repository.sync_inventory(trains=trains, endpoints=endpoints)
    run_id = "sim-run-syslog"
    run_date = _now().date().isoformat()
    active_dir = root / "ground" / "active" / run_date
    receiver = SyslogUdpReceiver(repository=repository, site_id=SITE_ID)
    receiver._ap_resolver.enrich_parsed = _make_ap_enricher()  # type: ignore[method-assign]
    receiver.start(
        run_id=run_id,
        run_date=run_date,
        active_dir=active_dir,
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=512,
        flush_records=32,
        flush_interval_seconds=0.05,
        event_batch_size=64,
        event_batch_interval_seconds=0.05,
    )
    address = receiver.health_snapshot()["udp_listen_address"]
    _host, port_text = str(address).rsplit(":", 1)
    port = int(port_text)

    heartbeat = FleetPingSupervisor(
        repository=repository,
        site_id=SITE_ID,
        runner=_fake_fping_runner,
    )
    heartbeat.start(
        run_id="sim-run-heartbeat",
        run_date=run_date,
        active_dir=root / "ground" / "active" / run_date,
        period_ms=100,
        timeout_ms=1000,
        packet_size=64,
        shard_size=12,
        correlation_tolerance_seconds=30,
        switch_before_seconds=5,
        switch_after_seconds=5,
        warmup_seconds=0,
    )
    heartbeat_targets = _heartbeat_targets()
    heartbeat.update_targets(heartbeat_targets)
    ac_result: dict[str, Any] = {}
    ac_thread = threading.Thread(
        target=_run_ac_chain,
        args=(repository, ac_result),
        name="r2-3-1-ac-simulator",
        daemon=True,
    )
    ac_thread.start()

    sent = 0
    base = _now() - timedelta(seconds=2)
    def known_mac(index: int, suffix: str) -> str:
        return _ap_mac(index, suffix)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as unknown_sender:
            unknown_sender.sendto(
                _fixture_line(hostname="SIM-UNKNOWN", peer_mac="0200-ffff-ffff", at=base),
                ("127.0.0.1", port),
            )
            sent += 1
        for index in range(1, MR_COUNT + 1):
            source_ip = _primary_ip(index)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.bind((source_ip, 0))
                a_time = base + timedelta(milliseconds=index)
                b_time = a_time + timedelta(milliseconds=300)
                for when, peer in (
                    (a_time, known_mac(index, "0001")),
                    (b_time, known_mac(index, "0002")),
                    (b_time, known_mac(index, "0002")),
                    (a_time - timedelta(seconds=1), known_mac(index, "0001")),
                ):
                    sender.sendto(
                        _fixture_line(hostname=f"SIM-MR-{index:03d}", peer_mac=peer, at=when),
                        ("127.0.0.1", port),
                    )
                    sent += 1
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.bind((_primary_ip(1), 0))
            sender.sendto(
                _fixture_line(hostname="SIM-MR-001", peer_mac="0200-ffff-ffff", at=base),
                ("127.0.0.1", port),
            )
            sent += 1
        received = _wait_for(
            lambda: receiver.health_snapshot()["received"] >= EXPECTED_SYSLOG_MESSAGES,
            timeout=20,
        )
        persisted = _wait_for(
            lambda: len(repository.list_wmesh_events(run_id=run_id, limit=1000))
            >= EXPECTED_SYSLOG_PROJECTIONS,
            timeout=20,
        )
        ac_thread.join(timeout=20)
        syslog_health = receiver.health_snapshot()
        heartbeat_snapshot = {
            "target_count": heartbeat.target_count,
            "process_count": heartbeat.process_count,
            "sample_count": heartbeat.sample_count,
            "sample_rate_per_second": heartbeat.sample_rate_per_second,
        }
        states = [repository.get_syslog_position_state(f"sim-mr-{index:03d}") for index in range(1, MR_COUNT + 1)]
        final_b_count = sum(1 for row in states if row and str(row.get("current_ap_name") or "").startswith("SIM-AP-B-"))
        event_rows = repository.list_wmesh_events(run_id=run_id, limit=1000)
        valid_position_rows = [
            row for row in event_rows
            if str((row.get("details") or {}).get("resolution_status") or "") == "PHYSICAL_AP"
        ]
        before_stop = {
            "received": bool(received),
            "persisted": bool(persisted),
            "health": syslog_health,
            "event_count": len(event_rows),
            "valid_position_event_count": len(valid_position_rows),
            "final_ap_b_count": final_b_count,
            "expected_final_ap_b_count": MR_COUNT,
        }
    finally:
        receiver_stop = receiver.stop(timeout_seconds=20)
        heartbeat_stop = heartbeat.stop()
        ac_thread.join(timeout=20)

    initial_raw_files = repository.list_raw_files(data_type="syslog")
    initial_raw_record_count = _raw_record_count(repository)

    # Restart the receiver on the same isolated database and prove that the
    # persisted position projection is restored before accepting a new event.
    restart_receiver = SyslogUdpReceiver(repository=repository, site_id=SITE_ID)
    restart_receiver._ap_resolver.enrich_parsed = _make_ap_enricher()  # type: ignore[method-assign]
    restart_receiver.start(
        run_id="sim-run-restart",
        run_date=run_date,
        active_dir=active_dir,
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=128,
        flush_records=1,
        flush_interval_seconds=0.05,
        event_batch_size=1,
        event_batch_interval_seconds=0.05,
    )
    restart_port = int(str(restart_receiver.health_snapshot()["udp_listen_address"]).rsplit(":", 1)[1])
    restart_time = _now()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.bind((_primary_ip(1), 0))
        sender.sendto(
            _fixture_line(hostname="SIM-MR-001", peer_mac=_ap_mac(1, "0003"), at=restart_time),
            ("127.0.0.1", restart_port),
        )
    _wait_for(lambda: len(repository.list_wmesh_events(run_id="sim-run-restart", limit=10)) >= 1, timeout=10)
    restart_stop = restart_receiver.stop(timeout_seconds=10)
    restart_state = repository.get_syslog_position_state("sim-mr-001") or {}

    reconciliation_state_rows: list[dict[str, Any]] = []
    delayed_statuses: dict[str, int] = {}
    observed_at = _iso(_now())
    for index in range(1, MR_COUNT + 1):
        state = repository.get_syslog_position_state(f"sim-mr-{index:03d}")
        if not state:
            continue
        try:
            syslog_time = datetime.fromisoformat(str(state.get("last_event_time") or ""))
        except ValueError:
            syslog_time = _now() - timedelta(seconds=10)
        ac_time = syslog_time - timedelta(seconds=1)
        ac_row = _ac_row(index, ap="A", snapshot=99, received_at=observed_at, device_time=_iso(ac_time))
        delayed = reconcile_syslog_ac(state, ac_row, now=observed_at, stale_after_seconds=120)
        delayed_statuses[delayed.state] = delayed_statuses.get(delayed.state, 0) + 1
        reconciliation_state_rows.append(delayed.to_record(site_id=SITE_ID, run_id=run_id, observed_at=observed_at))
    repository.upsert_position_reconciliations(reconciliation_state_rows)
    later_statuses: dict[str, int] = {}
    later_rows: list[dict[str, Any]] = []
    later_observed_at = _iso(_now())
    for index in range(1, MR_COUNT + 1):
        state = repository.get_syslog_position_state(f"sim-mr-{index:03d}")
        if not state:
            continue
        matching_ac = _ac_row(
            index,
            ap="B",
            snapshot=100,
            received_at=later_observed_at,
            device_time=later_observed_at,
        )
        matching_ac.update(
            {
                "peer_ap_id": state.get("current_ap_id", ""),
                "peer_ap_name": state.get("current_ap_name", ""),
                "peer_ap_mac": state.get("current_ap_mac", ""),
            }
        )
        later = reconcile_syslog_ac(
            state,
            matching_ac,
            now=later_observed_at,
            stale_after_seconds=120,
        )
        later_statuses[later.state] = later_statuses.get(later.state, 0) + 1
        later_rows.append(later.to_record(site_id=SITE_ID, run_id=run_id, observed_at=later_observed_at))
    repository.upsert_position_reconciliations(later_rows)

    raw_files = repository.list_raw_files(data_type="syslog")
    heartbeat_files = repository.list_raw_files(data_type="ping")
    raw_status_counts: dict[str, int] = {}
    for row in raw_files:
        status = str(row.get("status") or "UNKNOWN")
        raw_status_counts[status] = raw_status_counts.get(status, 0) + 1
    return {
        "status": "PASS" if (
            sent == EXPECTED_SYSLOG_MESSAGES
            and before_stop["received"]
            and before_stop["persisted"]
            and before_stop["final_ap_b_count"] == MR_COUNT
            and heartbeat_snapshot["target_count"] == 200
            and heartbeat_snapshot["process_count"] > 0
            and initial_raw_record_count == EXPECTED_SYSLOG_MESSAGES
            and receiver_stop.get("success")
            and heartbeat_stop.get("success")
            and restart_stop.get("success")
        ) else "FAIL",
        "site_id": SITE_ID,
        "root_relative": root.relative_to(root.parents[3]).as_posix() if len(root.parents) >= 4 else root.name,
        "syslog": {
            "sent": sent,
            "expected": EXPECTED_SYSLOG_MESSAGES,
            "before_stop": before_stop,
            "stop": receiver_stop,
            "raw_record_count": _raw_record_count(repository),
            "initial_raw_record_count": initial_raw_record_count,
            "initial_raw_file_count": len(initial_raw_files),
            "raw_file_count": len(raw_files),
            "raw_status_counts": raw_status_counts,
            "position_latency_ms": {
                "samples": int(before_stop["health"].get("position_update_count") or 0),
                "p50": before_stop["health"].get("position_latency_p50_ms"),
                "p95": before_stop["health"].get("position_latency_p95_ms"),
                "p99": before_stop["health"].get("position_latency_p99_ms"),
                "max_stage_parse_to_position_ms": before_stop["health"].get("stage_parse_to_position_p99_ms"),
            },
            "stages": {
                key: before_stop["health"].get(key)
                for key in (
                    "stage_receive_to_raw_p95_ms",
                    "stage_raw_to_parse_p95_ms",
                    "stage_parse_to_position_p95_ms",
                )
            },
            "queues": {
                key: before_stop["health"].get(key)
                for key in (
                    "raw_writer_queue_length",
                    "parser_queue_size",
                    "oldest_unprocessed_log_wait_seconds",
                    "udp_receive_rate_per_second",
                    "parser_rate_per_second",
                    "position_updates_per_second",
                )
            },
        },
        "heartbeat": {
            "target_count": heartbeat_snapshot["target_count"],
            "expected_target_count": 200,
            "process_count": heartbeat_snapshot["process_count"],
            "sample_count": heartbeat_snapshot["sample_count"],
            "sample_rate_per_second": heartbeat_snapshot["sample_rate_per_second"],
            "raw_file_count": len(heartbeat_files),
            "stop": heartbeat_stop,
        },
        "ac": {
            **ac_result,
            "reconciliation_statuses_after_delayed_ac": delayed_statuses,
            "reconciliation_statuses_after_later_ac": later_statuses,
        },
        "recovery": {
            "receiver_restart": restart_stop,
            "restart_current_ap": restart_state.get("current_ap_name", ""),
            "restart_expected_ap": "SIM-AP-C-001",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-root", action="store_true", help="retain the isolated run root for inspection")
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[2].parent
    parent = workspace / "test-data" / "NetConsole"
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / f"r2_3_1-sim-{_now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=False)
    try:
        result = _run_simulation(root)
        print(json.dumps({**result, "root_retained": bool(args.keep_root)}, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "root_retained": bool(args.keep_root)}, ensure_ascii=False, sort_keys=True))
        return 1
    finally:
        if not args.keep_root and root.is_dir():
            root_resolved = root.resolve()
            parent_resolved = parent.resolve()
            root_resolved.relative_to(parent_resolved)
            shutil.rmtree(root_resolved)


if __name__ == "__main__":
    raise SystemExit(main())
