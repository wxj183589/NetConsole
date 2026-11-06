"""Wall-clock Ground V2 component soak; never contacts a device or starts fping.

Run with ``python -m scripts.dev.ground_v2_soak --seconds 86400``.
This exercises production state/storage components with synthetic observations;
it does not certify Electron, a real Backend restart, SSH or native DPI.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import sqlite3
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

from netconsole.core.runtime_environment import test_data_root_base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rss_bytes() -> int | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in (
                "peak_working_set", "working_set", "quota_peak_paged", "quota_paged",
                "quota_peak_nonpaged", "quota_nonpaged", "pagefile", "peak_pagefile",
            )
        ]

    data = Counters()
    data.cb = ctypes.sizeof(data)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(data), data.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(data.working_set)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=86400)
    parser.add_argument("--metrics-seconds", type=float, default=10)
    parser.add_argument("--run-id", default="ground-v2-soak-" + uuid.uuid4().hex[:12])
    args = parser.parse_args()
    if args.seconds <= 0 or args.metrics_seconds <= 0:
        parser.error("durations must be positive")
    if not args.run_id.startswith("ground-v2-soak-") or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.run_id
    ):
        parser.error("run-id must start with ground-v2-soak- and contain only letters, digits, - or _")
    root = test_data_root_base() / args.run_id
    # Exclusive ownership: refuse all existing roots, never clean or reuse data.
    root.mkdir(parents=True, exist_ok=False)
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    (root / "owner.json").write_text(json.dumps({
        "task": "Ground V2 synthetic component soak", "created_at": _now(),
        "pid": os.getpid(), "requested_seconds": args.seconds,
        "retention": "Keep until audit reviewed; remove only this owned run after review",
    }, indent=2), encoding="utf-8")

    from netconsole.core.ping.fping_v5_models import FpingV5Sample
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
    from netconsole.services.ground_unattended.heartbeat_state import (
        HeartbeatIpObservation, HeartbeatStateEngine, HeartbeatTarget, TrainConnectivityAggregator,
    )
    from netconsole.services.ground_unattended.quick_ping import QuickPingService, QuickPingTarget
    from netconsole.services.ground_unattended.syslog_runtime import SyslogUdpReceiver

    started_at = _now()
    started = time.monotonic()
    cpu_started = time.process_time()
    transitions: Counter[str] = Counter()
    errors: list[str] = []
    repo = GroundUnattendedRepository(root / "ground" / "index.sqlite", site_id="soak")
    targets = [HeartbeatTarget(
        f"mr-{i}", f"train-{i // 2}", "CT" if i % 2 == 0 else "CW",
        tuple(f"192.0.{2 + i // 200}.{1 + i % 200}" for _ in [0])
        + ((f"198.51.{100 + i // 200}.{1 + i % 200}",) if i % 2 == 0 else ()),
    ) for i in range(200)]
    engine = HeartbeatStateEngine(event_sink=lambda event: transitions.update([event.event_type]))
    engine.configure_targets(targets)
    engine.set_engine_state("RUNNING")
    aggregator = TrainConnectivityAggregator(event_sink=lambda event: transitions.update([event.event_type]))

    def runner(*, targets, stop_event, interval_ms, timeout_ms, packet_size, **_kwargs):
        sequence = 0
        while not stop_event.wait(interval_ms / 1000):
            sequence += 1
            for target in targets:
                ok = sequence % 37 != 0
                yield FpingV5Sample(
                    ts=_now(), target=target, seq=sequence, ok=ok, rtt_ms=1.2 if ok else None,
                    timeout_ms=timeout_ms, size=packet_size if ok else None,
                    error="" if ok else "synthetic timeout", backend="mock", raw_type="mock", raw={},
                )

    quick = QuickPingService(site_id="soak", output_root=root / "quick", runner=runner, repository=repo)
    quick_ids = [quick.start(targets=[QuickPingTarget(
        target_ip=f"192.0.2.{i + 1}", mr_id=f"quick-mr-{i}", train_id=f"quick-train-{i}", mr_role="CT",
    )]) for i in range(3)]
    receiver = SyslogUdpReceiver(repository=repo, site_id="soak")
    receiver.start(
        run_id=args.run_id, run_date=datetime.now().date().isoformat(),
        active_dir=root / "ground" / "active", listen_host="127.0.0.1", listen_port=0,
        queue_capacity=100, flush_records=100, flush_interval_seconds=.05,
        event_batch_size=100, event_batch_interval_seconds=.05,
    )
    port = receiver._socket.getsockname()[1]
    sent_udp = samples = ticks = 0
    resource_first = resource_last = None
    peak_rss = peak_threads = metric_count = 0
    workload_seconds = 0.0
    stop_result: dict = {}
    mock_deep_failures = 0
    manual_stopped = False
    component_restarts = 0
    print(json.dumps({"root": str(root), "pid": os.getpid(), "started_at": started_at}), flush=True)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender, (root / "metrics.ndjson").open("w", encoding="utf-8") as output:
            next_tick = next_metrics = started
            while time.monotonic() - started < args.seconds and not (root / "STOP").exists():
                now_mono = time.monotonic()
                if now_mono < next_tick:
                    time.sleep(min(.1, next_tick - now_mono))
                    continue
                next_tick = now_mono + 1
                elapsed = now_mono - started
                phase = int(elapsed) % 300
                at = datetime.now(timezone.utc)
                # Distinct failure windows cover dual-IP, 5s/10s losses, and
                # >120s CT/CW overlap. Each interval uses actual wall clock.
                for index, target in enumerate(targets):
                    observations = {}
                    for ip_index, ip in enumerate(target.management_ips):
                        fail = (
                            (index in {0, 1} and 10 <= phase < 145)
                            or (index == 2 and ip_index == 0 and 5 <= phase < 160)
                            or (index == 3 and 20 <= phase < 25)
                            or (index == 4 and 30 <= phase < 41)
                            or (index == 5 and phase == 5)
                        )
                        observations[ip] = HeartbeatIpObservation(ip, not fail, None if fail else 1.5)
                    engine.record_cycle(target.mr_uuid, observations, at=at)
                    samples += len(observations)
                    aggregator.update(engine.snapshot(target.mr_uuid), at=at)
                aggregator.evaluate(at=at)
                ticks += 1
                # Bounded batches persist real snapshots, alongside Quick Ping
                # and Syslog writes to the same SQLite file.
                repo.upsert_heartbeat_snapshots(args.run_id, [{
                    "entity_type": "MR", "entity_id": snapshot.mr_uuid, "snapshot": snapshot.to_payload(),
                } for snapshot in engine.snapshots()])
                for index in range(500 if phase == 60 else 50):
                    payload = f"<134>UNKNOWN/6/SOAK: sequence={sent_udp + 1} mesh={phase % 3}".encode()
                    sender.sendto(payload, ("127.0.0.1", port))
                    sent_udp += 1
                if phase % 30 == 0:
                    mock_deep_failures += 1  # Synthetic task outcome; no SSH worker.
                if elapsed >= 45 and not manual_stopped:
                    quick.stop(quick_ids[-1])
                    manual_stopped = True
                if phase == 200:
                    engine.set_engine_state("DEGRADED", at=at)
                    engine.set_engine_state("RUNNING", at=at)
                if phase == 230:
                    snapshots = [{"entity_id": s.mr_uuid, "snapshot": s.to_payload()} for s in engine.snapshots()]
                    engine = HeartbeatStateEngine(event_sink=lambda event: transitions.update([event.event_type]))
                    engine.configure_targets(targets)
                    engine.restore_snapshots(snapshots)
                    engine.set_engine_state("RUNNING", at=at)
                    aggregator = TrainConnectivityAggregator()
                    component_restarts += 1
                if now_mono >= next_metrics:
                    next_metrics = now_mono + args.metrics_seconds
                    files = list(root.rglob("*"))
                    metric = {
                        "at": _now(), "elapsed_seconds": elapsed, "harness_cpu_seconds": time.process_time() - cpu_started,
                        "harness_rss_bytes": _rss_bytes(), "threads": threading.active_count(),
                        "electron_rss_bytes": None, "backend_rss_bytes": None,
                        "fping_processes": 0, "note": "no child processes; synthetic runner",
                        "targets": 200, "management_ips": 300, "heartbeat_samples": samples,
                        "heartbeat_samples_per_second": samples / max(elapsed, 1),
                        "udp_sent": sent_udp, "syslog": receiver.health_snapshot(),
                        "sqlite_bytes": repo.db_path.stat().st_size,
                        "raw_files": sum(p.suffix == ".ndjson" for p in files),
                        "gzip_files": sum(p.suffix == ".gz" for p in files),
                        "free_disk_bytes": shutil.disk_usage(root).free,
                        "tasks": Counter(run.state for run in quick.list_runs()),
                        "mock_ac": [{"controller": i, "delay_seconds": (0, 30, 120)[(phase // 30 + i) % 3],
                                     "offline": phase >= 180} for i in range(3)],
                        "mock_deep_failures": mock_deep_failures, "errors": len(errors),
                    }
                    output.write(json.dumps(metric, ensure_ascii=False) + "\n")
                    output.flush()
                    resource_first = resource_first or metric
                    resource_last = metric
                    peak_rss = max(peak_rss, metric["harness_rss_bytes"] or 0)
                    peak_threads = max(peak_threads, metric["threads"])
                    metric_count += 1
    except KeyboardInterrupt:
        errors.append("operator KeyboardInterrupt")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        workload_seconds = time.monotonic() - started
        quick.close()
        stop_result = receiver.stop(timeout_seconds=30)
    with sqlite3.connect(repo.db_path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    health = receiver.health_snapshot()
    if health.get("last_error"):
        errors.append("Syslog health: " + str(health["last_error"]))
    if health.get("compression_failed_count"):
        errors.append("Syslog compression failed")
    elapsed = time.monotonic() - started
    complete = bool(stop_result.get("data_complete")) and health["received"] == sent_udp and health["written"] == sent_udp
    summary = {
        "started_at": started_at, "ended_at": _now(), "actual_seconds": elapsed,
        "requested_seconds": args.seconds, "workload_seconds": workload_seconds,
        "24H_TEST": "NOT_RUN",  # Component harness cannot certify a full-system 24h run.
        "COMPONENT_24H_TEST": "PASS" if (
            args.seconds >= 86400 and workload_seconds >= 86400
            and not (root / "STOP").exists() and complete and integrity == "ok" and not errors
        ) else "NOT_RUN",
        "result": "PASS" if complete and integrity == "ok" and not errors else "FAIL",
        "scope": "production heartbeat/quick-ping/syslog components; synthetic AC/deep; no Electron or Backend process",
        "component_restarts": component_restarts, "real_backend_restarts": 0,
        "ticks": ticks, "samples": samples, "udp_sent": sent_udp, "syslog": health,
        "stop_result": stop_result, "sqlite_integrity": integrity, "data_complete": complete,
        "transitions": transitions, "errors": errors,
        "quick_runs": [run.as_dict() for run in quick.list_runs()],
        "resource_first": resource_first, "resource_last": resource_last, "metric_count": metric_count,
        "resource_peak_rss": peak_rss, "resource_peak_threads": peak_threads,
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": summary["result"], "summary": str(root / "summary.json")}), flush=True)
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
