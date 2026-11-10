"""Measure separate normal and burst Syslog position latency distributions.

This is a local evidence runner only.  It uses the production receiver, parser,
Raw writer and Position Engine with a synthetic inventory and an owned SQLite
root under the NetConsole Workspace.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from scripts.dev.ground_unattended_r2_3_2_long_stability import (  # noqa: E402
    MR_COUNT,
    _ap_mac,
    _fixture_line,
    _inventory,
    _make_ap_enricher,
)


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _run_scenario(
    *,
    root: Path,
    scenario: str,
    event_count: int,
    spacing_seconds: float,
) -> dict[str, Any]:
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
    from netconsole.services.ground_unattended.syslog_runtime import SyslogUdpReceiver

    root.mkdir(parents=True, exist_ok=False)
    repository = GroundUnattendedRepository(root / "ground" / "index.sqlite", site_id="r2-3-2-latency")
    trains, endpoints = _inventory()
    repository.sync_inventory(trains=trains, endpoints=endpoints)
    receiver = SyslogUdpReceiver(repository=repository, site_id="r2-3-2-latency")
    receiver._ap_resolver.enrich_parsed = _make_ap_enricher()  # type: ignore[method-assign]
    run_date = _now().date().isoformat()
    receiver.start(
        run_id=f"r232-latency-{scenario}",
        run_date=run_date,
        active_dir=root / "ground" / "active" / run_date,
        listen_host="127.0.0.1",
        listen_port=0,
        queue_capacity=2048,
        flush_records=64,
        flush_interval_seconds=1.0,
        event_batch_size=64,
        event_batch_interval_seconds=1.0,
    )
    port = int(str(receiver.health_snapshot()["udp_listen_address"]).rsplit(":", 1)[1])
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    started = time.monotonic()
    try:
        for sequence in range(event_count):
            index = sequence % MR_COUNT + 1
            ap = ("A", "B", "C")[sequence % 3]
            payload = _fixture_line(
                hostname=f"R232-MR-{index:03d}",
                peer_mac=_ap_mac(index, {"A": "0001", "B": "0002", "C": "0003"}[ap]),
                at=_now(),
            ) + f" validation_seq={sequence}".encode("ascii")
            sender.sendto(payload, ("127.0.0.1", port))
            sent += 1
            if spacing_seconds:
                time.sleep(spacing_seconds)
        deadline = time.monotonic() + max(120.0, event_count / 20.0)
        while time.monotonic() < deadline:
            health = receiver.health_snapshot()
            if health.get("written") == sent and health.get("parsed") == sent:
                break
            time.sleep(0.1)
        health = receiver.health_snapshot()
    finally:
        sender.close()
        stop = receiver.stop(timeout_seconds=60)
    result = {
        "scenario": scenario,
        "event_count": event_count,
        "spacing_seconds": spacing_seconds,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "sent": sent,
        "health_before_stop": health,
        "stop": stop,
        "status": "PASS" if (
            health.get("received") == sent
            and health.get("written") == sent
            and health.get("parsed") == sent
            and health.get("dropped") == 0
            and stop.get("success")
            and stop.get("data_complete")
        ) else "FAIL",
        "root": str(root),
    }
    (root / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    source_root = Path(__file__).resolve().parents[2]
    workspace_root = source_root.parent
    if workspace_root.name.casefold() == "worktrees" and workspace_root.parent.name.casefold() == "netconsole-workspace":
        workspace_root = workspace_root.parent
    run_id = f"r2_3_2-latency-{_now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    root = workspace_root / "test-data" / "NetConsole" / run_id
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    normal = _run_scenario(
        root=root / "normal",
        scenario="normal",
        event_count=100,
        spacing_seconds=0.1,
    )
    burst = _run_scenario(
        root=root / "burst",
        scenario="burst",
        event_count=2000,
        spacing_seconds=0.0,
    )
    result = {"status": "PASS" if normal["status"] == burst["status"] == "PASS" else "FAIL", "normal": normal, "burst": burst, "root": str(root)}
    (root / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
