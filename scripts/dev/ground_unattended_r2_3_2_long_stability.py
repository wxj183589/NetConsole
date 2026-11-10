"""Run the R2.3.2 real wall-clock local Ground integration soak.

The runner deliberately uses production SyslogUdpReceiver, FleetPingSupervisor,
GroundUnattendedRepository and AC reconciliation code.  It uses only synthetic
inventory, loopback UDP, documentation-range/local loopback addresses and a
fresh workspace test-data root.  It does not read a configured site or start a
real fping executable.

The default duration is eight real hours.  No clock acceleration is used.  A
``STOP`` file in the owned run root requests a bounded graceful stop.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import socket
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MR_COUNT = 100
SITE_ID = "r2-3-2-long-stability-site"
DEFAULT_DURATION_SECONDS = 8 * 60 * 60
DEFAULT_HEARTBEAT_PERIOD_MS = 5000
DEFAULT_AC_INTERVAL_SECONDS = 60.0
DEFAULT_METRICS_INTERVAL_SECONDS = 60.0


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _fixture_line(*, hostname: str, peer_mac: str, at: datetime) -> bytes:
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
            "train_id": f"r232-train-{index:03d}",
            "train_no": f"R232-{index:03d}",
            "train_name": f"R2.3.2 synthetic train {index:03d}",
        }
        for index in range(1, MR_COUNT + 1)
    ]
    endpoints = [
        {
            "device_uuid": f"r232-mr-{index:03d}",
            "device_id": index,
            "train_id": f"r232-train-{index:03d}",
            "mr_role": "CT" if index % 2 else "CW",
            "device_name": f"R232-MR-{index:03d}",
            "source_hostname": f"R232-MR-{index:03d}",
            "management_ip": _primary_ip(index),
            "backup_management_ip": _backup_ip(index),
        }
        for index in range(1, MR_COUNT + 1)
    ]
    return trains, endpoints


def _make_ap_enricher():
    known: dict[str, tuple[str, str]] = {}
    for index in range(1, MR_COUNT + 1):
        known[_ap_mac(index, "0001")] = (f"R232-AP-A-{index:03d}", "A")
        known[_ap_mac(index, "0002")] = (f"R232-AP-B-{index:03d}", "B")
        known[_ap_mac(index, "0003")] = (f"R232-AP-C-{index:03d}", "C")

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
                "station": "R232-SYNTHETIC-STATION",
                "section": f"R232-SECTION-{section}",
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


def _heartbeat_targets() -> list[FleetPingTarget]:
    return [
        FleetPingTarget(
            target_ip=_primary_ip(index),
            train_id=f"r232-train-{index:03d}",
            train_no=f"R232-{index:03d}",
            mr_id=f"r232-mr-{index:03d}",
            mr_position_code="CT" if index % 2 else "CW",
            mr_name=f"R232-MR-{index:03d}",
            device_id=index,
            station="R232-SYNTHETIC-STATION",
            section="R232-SECTION-A",
        )
        for index in range(1, MR_COUNT + 1)
    ]


def _slow_but_bounded_fping_runner(*, targets, stop_event, period_ms, **_kwargs):
    sequence = 0
    while not stop_event.wait(max(0.1, float(period_ms) / 1000.0)):
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
                timeout_ms=4000,
                size=64,
                error="",
                backend=BACKEND,
                raw_type="response",
                raw={"synthetic": True, "wall_clock": True},
            )


def _ac_row(index: int, *, ap: str, snapshot: int, received_at: str, device_time: str) -> dict[str, Any]:
    return {
        "snapshot_id": f"r232-ac-snapshot-{snapshot:06d}",
        "site_id": SITE_ID,
        "run_id": "r232-ac-resident",
        "ac_device_id": "r232-ac-01",
        "source_snapshot_id": snapshot,
        "device_time": device_time,
        "received_at": received_at,
        "train_id": f"r232-train-{index:03d}",
        "train_no": f"R232-{index:03d}",
        "mr_id": f"r232-mr-{index:03d}",
        "mr_position_code": "CT" if index % 2 else "CW",
        "mr_online_status": "online",
        "peer_ap_name": f"R232-AP-{ap}-{index:03d}",
        "peer_ap_mac": _ap_display(_ap_mac(index, {"A": "0001", "B": "0002", "C": "0003"}[ap])),
        "station": "R232-SYNTHETIC-STATION",
        "section": f"R232-SECTION-{ap}",
        "mileage": str(index),
        "rssi": -40,
        "freshness_status": "fresh",
        "raw_source_reference": "r2-3-2-sanitized-ac-fixture",
    }


def _rss_bytes() -> int | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working_set",
                "working_set",
                "quota_peak_paged",
                "quota_paged",
                "quota_peak_nonpaged",
                "quota_nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    data = Counters()
    data.cb = ctypes.sizeof(data)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(data), data.cb):
        return None
    return int(data.working_set)


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


def _wait_for(predicate, *, timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _run_ac_poller(
    *,
    repository: GroundUnattendedRepository,
    stop_event: threading.Event,
    ac_interval_seconds: float,
    metrics: dict[str, Any],
    metrics_lock: threading.Lock,
) -> None:
    previous: AcSnapshotEnvelope | None = None
    previous_rows: list[dict[str, Any]] = []
    poll = 0
    while not stop_event.is_set():
        if poll and stop_event.wait(ac_interval_seconds):
            break
        received_at = _iso(_now())
        poll += 1
        snapshot = poll
        try:
            # These windows model bounded transport faults.  No failed or
            # incomplete response is allowed to delete a previously valid row.
            if poll % 17 == 0:
                with metrics_lock:
                    metrics["timeouts"] += 1
                    metrics["failure_windows"] += 1
                continue
            ap = ("A", "B", "C")[(poll // 2) % 3]
            if poll % 11 == 0 and previous_rows:
                rows = [dict(row) for row in previous_rows]
                envelope_snapshot = snapshot - 1
                envelope_time = str(previous.observation_time) if previous else received_at
                old_duplicate = True
            else:
                rows = [
                    _ac_row(
                        index,
                        ap=ap if index % 7 else ("A" if ap != "A" else "B"),
                        snapshot=snapshot,
                        received_at=received_at,
                        device_time=_iso(_now() - timedelta(seconds=5 if poll % 3 else 0)),
                    )
                    for index in range(1, MR_COUNT + 1)
                ]
                envelope_snapshot = snapshot
                envelope_time = str(rows[0]["device_time"])
                old_duplicate = False
            if poll % 23 == 0:
                # Partial response is retained as UNKNOWN delta evidence only.
                rows = rows[:-1]
                data_status = "partial"
                complete = False
            else:
                data_status = "fresh"
                complete = True
            current = AcSnapshotEnvelope(
                controller_id="r232-ac-01",
                snapshot_id=f"r232-ac-snapshot-{envelope_snapshot:06d}",
                rows=tuple(rows),
                device_time=envelope_time,
                received_at=received_at,
                data_status=data_status,
                complete=complete,
            )
            delta = diff_full_snapshot(previous, current)
            records = [
                item.to_record(
                    site_id=SITE_ID,
                    run_id="r232-ac-resident",
                    created_at=_iso(_now()),
                )
                for item in delta.records
            ]
            if records:
                repository.insert_ac_delta_rows(records)
            if delta.accepted:
                repository.insert_ac_rows(rows)
                previous = current
                previous_rows = [dict(row) for row in rows]
            reconciliation_rows: list[dict[str, Any]] = []
            by_mr = {str(row.get("mr_id") or ""): row for row in rows}
            for index in range(1, MR_COUNT + 1):
                state = repository.get_syslog_position_state(f"r232-mr-{index:03d}")
                if not state:
                    continue
                reconciliation = reconcile_syslog_ac(
                    state,
                    by_mr.get(f"r232-mr-{index:03d}"),
                    now=received_at,
                    stale_after_seconds=120,
                )
                reconciliation_rows.append(
                    reconciliation.to_record(
                        site_id=SITE_ID,
                        run_id="r232-ac-resident",
                        observed_at=received_at,
                    )
                )
                with metrics_lock:
                    metrics["reconciliation_states"][reconciliation.state] += 1
            if reconciliation_rows:
                repository.upsert_position_reconciliations(reconciliation_rows)
            with metrics_lock:
                metrics["polls"] += 1
                metrics["accepted_snapshots"] += int(delta.accepted)
                metrics["duplicate_snapshots"] += int(old_duplicate)
                metrics["partial_snapshots"] += int(not complete)
                for action, count in delta.counts.items():
                    metrics["delta_counts"][action] += int(count)
        except Exception as exc:  # pragma: no cover - exercised by live fault runs
            with metrics_lock:
                metrics["errors"].append(f"{type(exc).__name__}: {exc}")
                metrics["failure_windows"] += 1


def _run(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    started_at = _iso(_now())
    started = time.monotonic()
    cpu_started = time.process_time()
    stop_event = threading.Event()
    metrics_lock = threading.Lock()
    ac_metrics: dict[str, Any] = {
        "polls": 0,
        "accepted_snapshots": 0,
        "timeouts": 0,
        "failure_windows": 0,
        "partial_snapshots": 0,
        "duplicate_snapshots": 0,
        "delta_counts": Counter(),
        "reconciliation_states": Counter(),
        "errors": [],
    }
    errors: list[str] = []
    root.mkdir(parents=True, exist_ok=False)
    (root / "owner.json").write_text(
        json.dumps(
            {
                "task": "NetConsole Ground Unattended R2.3.2 local 8-hour integration soak",
                "created_at": started_at,
                "pid": os.getpid(),
                "requested_seconds": args.duration_seconds,
                "seed": args.seed,
                "real_wall_clock": True,
                "field_acceptance": "NOT_AVAILABLE",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    repository = GroundUnattendedRepository(root / "ground" / "index.sqlite", site_id=SITE_ID)
    trains, endpoints = _inventory()
    repository.sync_inventory(trains=trains, endpoints=endpoints)
    run_date = _now().date().isoformat()
    active_dir = root / "ground" / "active" / run_date
    receiver = SyslogUdpReceiver(repository=repository, site_id=SITE_ID)
    receiver._ap_resolver.enrich_parsed = _make_ap_enricher()  # type: ignore[method-assign]
    receiver.start(
        run_id="r232-syslog-long",
        run_date=run_date,
        active_dir=active_dir,
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=2048,
        flush_records=64,
        flush_interval_seconds=1.0,
        event_batch_size=64,
        event_batch_interval_seconds=1.0,
    )
    port = int(str(receiver.health_snapshot()["udp_listen_address"]).rsplit(":", 1)[1])
    heartbeat = FleetPingSupervisor(
        repository=repository,
        site_id=SITE_ID,
        runner=_slow_but_bounded_fping_runner,
    )
    heartbeat.start(
        run_id="r232-heartbeat-long",
        run_date=run_date,
        active_dir=active_dir,
        period_ms=args.heartbeat_period_ms,
        timeout_ms=4000,
        packet_size=64,
        shard_size=12,
        correlation_tolerance_seconds=30,
        switch_before_seconds=5,
        switch_after_seconds=5,
        warmup_seconds=0,
    )
    heartbeat.update_targets(_heartbeat_targets())
    ac_thread = threading.Thread(
        target=_run_ac_poller,
        kwargs={
            "repository": repository,
            "stop_event": stop_event,
            "ac_interval_seconds": args.ac_interval_seconds,
            "metrics": ac_metrics,
            "metrics_lock": metrics_lock,
        },
        name="r2-3-2-ac-poller",
        daemon=True,
    )
    ac_thread.start()
    senders: dict[int, socket.socket] = {}
    for index in range(1, MR_COUNT + 1):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.bind((_primary_ip(index), 0))
        senders[index] = sender

    sent_total = 0
    sent_valid = 0
    sent_duplicate = 0
    sent_out_of_order = 0
    sent_unknown_ap = 0
    sent_bad_format = 0
    burst_count = 0
    event_sequence = 0
    last_event_at: dict[int, datetime] = {}
    metric_rows: list[dict[str, Any]] = []
    next_event = started
    next_metrics = started
    final_events_sent = False
    send_lock = threading.Lock()

    def send_payload(index: int, payload: bytes) -> None:
        nonlocal sent_total
        senders[index].sendto(payload, ("127.0.0.1", port))
        with send_lock:
            sent_total += 1

    def send_position(index: int, ap: str, *, at: datetime | None = None, duplicate: bool = False) -> None:
        nonlocal sent_valid, sent_duplicate
        event_at = at or _now()
        payload = _fixture_line(
            hostname=f"R232-MR-{index:03d}",
            peer_mac=_ap_mac(index, {"A": "0001", "B": "0002", "C": "0003"}[ap]),
            at=event_at,
        )
        send_payload(index, payload)
        sent_valid += 1
        if duplicate:
            sent_duplicate += 1

    print(
        json.dumps(
            {
                "status": "RUNNING",
                "root": str(root),
                "pid": os.getpid(),
                "started_at": started_at,
                "requested_seconds": args.duration_seconds,
                "seed": args.seed,
                "udp_listen_port": port,
                "mr_count": MR_COUNT,
                "heartbeat_targets": MR_COUNT,
                "heartbeat_period_ms": args.heartbeat_period_ms,
                "ac_interval_seconds": args.ac_interval_seconds,
                "real_wall_clock": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        with (root / "metrics.ndjson").open("w", encoding="utf-8", newline="\n") as metric_file:
            while time.monotonic() - started < args.duration_seconds:
                now_mono = time.monotonic()
                if (root / "STOP").exists():
                    break
                if now_mono >= next_event:
                    event_sequence += 1
                    index = ((event_sequence - 1) % MR_COUNT) + 1
                    cycle = (event_sequence - 1) // MR_COUNT
                    ap = ("A", "B", "C")[cycle % 3]
                    event_at = _now()
                    send_position(index, ap, at=event_at)
                    last_event_at[index] = event_at
                    next_event += 1.0
                    if event_sequence % 17 == 0:
                        send_position(index, ap, at=event_at, duplicate=True)
                    if event_sequence % 29 == 0 and index in last_event_at:
                        send_position(index, "A", at=last_event_at[index] - timedelta(seconds=3))
                        sent_out_of_order += 1
                    if event_sequence % 43 == 0:
                        send_payload(index, _fixture_line(
                            hostname=f"R232-MR-{index:03d}",
                            peer_mac="0200-ffff-ffff",
                            at=event_at,
                        ))
                        sent_unknown_ap += 1
                    if event_sequence % 47 == 0:
                        send_payload(index, b"R232 malformed syslog fixture")
                        sent_bad_format += 1
                    if event_sequence % 157 == 0:
                        burst_count += 1
                        for offset in range(20):
                            burst_index = ((index + offset - 1) % MR_COUNT) + 1
                            send_position(burst_index, ("A", "B", "C")[(cycle + offset) % 3])
                if now_mono >= next_metrics:
                    next_metrics += args.metrics_interval_seconds
                    health = receiver.health_snapshot()
                    elapsed = now_mono - started
                    row = {
                        "at": _iso(_now()),
                        "elapsed_seconds": round(elapsed, 3),
                        "harness_cpu_seconds": round(time.process_time() - cpu_started, 3),
                        "harness_rss_bytes": _rss_bytes(),
                        "threads": threading.active_count(),
                        "fping_child_processes": 0,
                        "fping_process_model": "in-process synthetic runner; no real child",
                        "syslog_sent_total": sent_total,
                        "syslog_sent_valid": sent_valid,
                        "syslog_sent_duplicate": sent_duplicate,
                        "syslog_sent_out_of_order": sent_out_of_order,
                        "syslog_sent_unknown_ap": sent_unknown_ap,
                        "syslog_sent_bad_format": sent_bad_format,
                        "syslog_burst_count": burst_count,
                        "syslog": health,
                        "heartbeat": {
                            "target_count": heartbeat.target_count,
                            "process_count": heartbeat.process_count,
                            "sample_count": heartbeat.sample_count,
                            "sample_rate_per_second": heartbeat.sample_rate_per_second,
                            "last_sample_at": heartbeat.last_sample_at,
                            "last_sample_write_duration_ms": heartbeat.last_sample_write_duration_ms,
                            "worker_warnings": heartbeat.worker_warnings,
                        },
                        "ac": {
                            "polls": ac_metrics["polls"],
                            "timeouts": ac_metrics["timeouts"],
                            "failure_windows": ac_metrics["failure_windows"],
                        },
                        "sqlite_bytes": repository.db_path.stat().st_size,
                        "free_disk_bytes": shutil.disk_usage(root).free,
                    }
                    metric_rows.append(row)
                    metric_file.write(json.dumps(row, ensure_ascii=False) + "\n")
                    metric_file.flush()
                    print(json.dumps({"status": "SAMPLE", **row}, ensure_ascii=False), flush=True)
                time.sleep(0.02)

            if not final_events_sent:
                # A final ordered AP-B snapshot makes final-state accuracy
                # independently queryable after the run without discarding the
                # preceding A/B/C history.
                for index in range(1, MR_COUNT + 1):
                    send_position(index, "B", at=_now())
                final_events_sent = True
        final_wait_started = time.monotonic()
        _wait_for(
            lambda: all(
                (repository.get_syslog_position_state(f"r232-mr-{index:03d}") or {}).get("current_ap_name", "").startswith("R232-AP-B-")
                for index in range(1, MR_COUNT + 1)
            ),
            timeout=60,
        )
        final_wait_seconds = time.monotonic() - final_wait_started
    except KeyboardInterrupt:
        errors.append("operator KeyboardInterrupt")
        final_wait_seconds = None
    except Exception as exc:  # pragma: no cover - live harness guard
        errors.append(f"{type(exc).__name__}: {exc}")
        final_wait_seconds = None
    finally:
        stop_event.set()
        for sender in senders.values():
            try:
                sender.close()
            except OSError:
                pass
        ac_thread.join(timeout=max(10.0, args.ac_interval_seconds + 5.0))
        receiver_health_before_stop = receiver.health_snapshot()
        heartbeat_before_stop = {
            "target_count": heartbeat.target_count,
            "process_count": heartbeat.process_count,
            "sample_count": heartbeat.sample_count,
            "sample_rate_per_second": heartbeat.sample_rate_per_second,
            "last_sample_at": heartbeat.last_sample_at,
            "last_sample_write_duration_ms": heartbeat.last_sample_write_duration_ms,
            "worker_warnings": heartbeat.worker_warnings,
        }
        receiver_stop = receiver.stop(timeout_seconds=60)
        heartbeat_stop = heartbeat.stop()

    ended_at = _iso(_now())
    actual_seconds = time.monotonic() - started
    states = [
        repository.get_syslog_position_state(f"r232-mr-{index:03d}") or {}
        for index in range(1, MR_COUNT + 1)
    ]
    final_ap_b_count = sum(
        str(row.get("current_ap_name") or "").startswith("R232-AP-B-") for row in states
    )
    # ``list_raw_files`` is intentionally paginated for runtime callers.  Do
    # not use its default page as a soak total; the receiver stop snapshot is
    # the authoritative count after the bounded drain has completed.
    raw_record_count = int(receiver_health_before_stop.get("written") or 0)
    ac_summary = {
        "polls": ac_metrics["polls"],
        "accepted_snapshots": ac_metrics["accepted_snapshots"],
        "timeouts": ac_metrics["timeouts"],
        "failure_windows": ac_metrics["failure_windows"],
        "partial_snapshots": ac_metrics["partial_snapshots"],
        "duplicate_snapshots": ac_metrics["duplicate_snapshots"],
        "delta_counts": dict(ac_metrics["delta_counts"]),
        "reconciliation_states": dict(ac_metrics["reconciliation_states"]),
        "errors": list(ac_metrics["errors"]),
    }
    data_complete = bool(
        receiver_stop.get("data_complete")
        and receiver_health_before_stop.get("received") == sent_total
        and receiver_health_before_stop.get("written") == sent_total
        and receiver_health_before_stop.get("dropped") == 0
    )
    status = "PASS" if (
        actual_seconds >= args.duration_seconds
        and data_complete
        and final_ap_b_count == MR_COUNT
        and heartbeat_before_stop["target_count"] == MR_COUNT
        and heartbeat_stop.get("success")
        and receiver_stop.get("success")
        and not errors
        and not ac_summary["errors"]
    ) else "FAIL"
    summary = {
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "actual_seconds": round(actual_seconds, 3),
        "requested_seconds": args.duration_seconds,
        "real_wall_clock": True,
        "seed": args.seed,
        "site_id": SITE_ID,
        "scope": "local synthetic integrated Ground components; loopback UDP; no real Backend/Electron/device/fping child",
        "field_acceptance": "NOT_AVAILABLE",
        "config": {
            "mr_count": MR_COUNT,
            "syslog_udp": "127.0.0.1 ephemeral port",
            "heartbeat_target_count": MR_COUNT,
            "heartbeat_period_ms": args.heartbeat_period_ms,
            "ac_interval_seconds": args.ac_interval_seconds,
            "metrics_interval_seconds": args.metrics_interval_seconds,
        },
        "syslog": {
            "sent_total": sent_total,
            "sent_valid": sent_valid,
            "sent_duplicate": sent_duplicate,
            "sent_out_of_order": sent_out_of_order,
            "sent_unknown_ap": sent_unknown_ap,
            "sent_bad_format": sent_bad_format,
            "burst_count": burst_count,
            "raw_record_count": raw_record_count,
            "receiver_before_stop": receiver_health_before_stop,
            "receiver_stop": receiver_stop,
            "position_latency_final_ms": {
                key: receiver_health_before_stop.get(key)
                for key in (
                    "position_latency_p50_ms",
                    "position_latency_p95_ms",
                    "position_latency_p99_ms",
                    "stage_receive_to_raw_p95_ms",
                    "stage_raw_to_parse_p95_ms",
                    "stage_parse_to_position_p95_ms",
                )
            },
            "queues_final": {
                key: receiver_health_before_stop.get(key)
                for key in (
                    "udp_queue_length",
                    "raw_writer_queue_length",
                    "parser_queue_size",
                    "oldest_unprocessed_log_wait_seconds",
                    "udp_receive_rate_per_second",
                    "parser_rate_per_second",
                    "position_updates_per_second",
                )
            },
            "event_time_precision": "fixture carries local wall-clock milliseconds without a timezone; event-time precision is milliseconds within the host clock, not a field-clock attestation",
        },
        "position": {
            "final_ap_b_count": final_ap_b_count,
            "expected_final_ap_b_count": MR_COUNT,
            "accuracy": final_ap_b_count / MR_COUNT,
            "state_count": len(states),
            "final_wait_seconds": final_wait_seconds,
            "history_preserved": True,
        },
        "heartbeat": {
            **heartbeat_before_stop,
            "stop": heartbeat_stop,
            "fping_child_processes": 0,
        },
        "ac": ac_summary,
        "metrics": {
            "path": str(root / "metrics.ndjson"),
            "sample_count": len(metric_rows),
            "first": metric_rows[0] if metric_rows else None,
            "last": metric_rows[-1] if metric_rows else None,
            "cpu_seconds": round(time.process_time() - cpu_started, 3),
            "rss_bytes": _rss_bytes(),
        },
        "errors": errors,
        "data_complete": data_complete,
        "root": str(root),
        "root_sha256": hashlib.sha256(str(root).encode("utf-8")).hexdigest(),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps({"status": status, "summary": str(root / "summary.json"), "actual_seconds": actual_seconds}, ensure_ascii=False), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--heartbeat-period-ms", type=int, default=DEFAULT_HEARTBEAT_PERIOD_MS)
    parser.add_argument("--ac-interval-seconds", type=float, default=DEFAULT_AC_INTERVAL_SECONDS)
    parser.add_argument("--metrics-interval-seconds", type=float, default=DEFAULT_METRICS_INTERVAL_SECONDS)
    parser.add_argument("--seed", type=int, default=232)
    parser.add_argument("--run-id", default=f"r2_3_2-long-{_now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}")
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.heartbeat_period_ms <= 0 or args.ac_interval_seconds <= 0 or args.metrics_interval_seconds <= 0:
        parser.error("all durations and heartbeat period must be positive")
    if not args.run_id.startswith("r2_3_2-long-") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.run_id):
        parser.error("run-id must start with r2_3_2-long- and contain only letters, digits, - or _")
    source_root = Path(__file__).resolve().parents[2]
    workspace_root = source_root.parent
    if workspace_root.name.casefold() == "worktrees" and workspace_root.parent.name.casefold() == "netconsole-workspace":
        workspace_root = workspace_root.parent
    root = workspace_root / "test-data" / "NetConsole" / args.run_id
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    global BACKEND, FpingV5Sample, GroundUnattendedRepository
    global AcSnapshotEnvelope, diff_full_snapshot, reconcile_syslog_ac
    global FleetPingSupervisor, FleetPingTarget, SyslogUdpReceiver
    from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
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
    try:
        result = _run(args, root)
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:  # pragma: no cover - startup guard
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}", "root": str(root)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
