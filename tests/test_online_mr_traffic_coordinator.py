from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.models.online_mr_models import (
    FpingConfig,
    IperfTrafficConfig,
    OnlineMrConnectionConfig,
    OnlineMrTaskToggles,
)
from netconsole.services.online_mr.traffic_coordinator import OnlineMrTrafficCoordinator
from netconsole.services.online_mr_session_store import OnlineMrSessionStore


def _config() -> OnlineMrConnectionConfig:
    return OnlineMrConnectionConfig(
        site="demo",
        mr_id="1",
        mr_name="MR-Test",
        safe_mr_name="MR-Test__1",
        device_id=1,
        device_name="MR-Test",
        host="192.0.2.1",
        fping=FpingConfig(enabled=True, target="192.0.2.2", interval_ms=10),
        iperf=IperfTrafficConfig(enabled=True, server_ip="192.0.2.3", follow_collection=True),
        tasks=OnlineMrTaskToggles(
            mesh_link=False,
            channel_busy=False,
            ap_radio_statistics=False,
            switch_history=False,
            interface_rate=False,
            wireless_status=False,
        ),
    )


class _FakeIperfRunner:
    instances: list["_FakeIperfRunner"] = []

    def __init__(self, _tool, _command, log_file, **_kwargs) -> None:
        self.log_file = Path(log_file)
        self.run_id = "iperf-test"
        self.last_status = "CREATED"
        self.stop_event = threading.Event()
        self.instances.append(self)

    def start(self) -> None:
        self.last_status = "RUNNING"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("w", encoding="utf-8") as handle:
            handle.write("start\n")
            handle.flush()
            self.stop_event.wait(2)
            handle.write("final interval\n")
            handle.flush()
        self.last_status = "STOPPED_BY_COLLECTION"

    def stop(self, status: str = "STOPPED_BY_USER") -> None:
        self.last_status = status
        self.stop_event.set()


def test_traffic_coordinator_stops_and_flushes_fping_and_iperf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(_config())
    tool = tmp_path / "tool.exe"
    tool.touch()

    def fake_fping(**kwargs):
        raw_path = Path(kwargs["output_raw_log_path"])
        jsonl_path = Path(kwargs["output_jsonl_path"])
        sample = FpingV5Sample(
            ts="2026-07-13T10:00:00.000",
            target="192.0.2.2",
            seq=1,
            ok=True,
            rtt_ms=1.2,
            timeout_ms=100,
            size=64,
            error="",
            backend="fping_v5_json",
            raw_type="resp",
            raw={},
        )
        raw_path.write_text("first sample\n", encoding="utf-8")
        jsonl_path.write_text(json.dumps(sample.as_dict()) + "\n", encoding="utf-8")
        yield sample
        kwargs["stop_event"].wait(2)
        with raw_path.open("a", encoding="utf-8") as handle:
            handle.write("final sample\n")
            handle.flush()

    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_fping_tool", lambda _paths: tool)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_iperf_tool", lambda _paths: tool)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.run_fping_v5_json", fake_fping)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.IperfProcessRunner", _FakeIperfRunner)

    coordinator = OnlineMrTrafficCoordinator(paths)
    coordinator.start_for_session(session, _config())
    coordinator.stop_traffic_for_session(session.meta.session_id)
    warnings = coordinator.flush_traffic_outputs(session.meta.session_id, timeout_seconds=2)
    summary = coordinator.finalize_traffic_outputs(session.meta.session_id)

    assert warnings == []
    assert summary["flush_complete"] is True
    assert "final sample" in (session.session_dir / "raw" / "fping_v5_raw.log").read_text(encoding="utf-8")
    assert "final interval" in (session.session_dir / "raw" / "iperf_client_raw.log").read_text(encoding="utf-8")
    assert json.loads((session.session_dir / "raw" / "fping_v5_final_summary.json").read_text(encoding="utf-8"))["sent"] == 1


def test_traffic_flush_timeout_records_warning_and_never_waits_forever(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    config.iperf = IperfTrafficConfig(enabled=False)
    paths = PathResolver(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    tool = tmp_path / "fping.exe"
    tool.touch()
    release = threading.Event()

    def blocked_fping(**_kwargs):
        release.wait(2)
        if False:
            yield None

    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_fping_tool", lambda _paths: tool)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.run_fping_v5_json", blocked_fping)

    coordinator = OnlineMrTrafficCoordinator(paths)
    coordinator.start_for_session(session, config)
    started = time.monotonic()
    coordinator.force_stop_traffic_for_session(session.meta.session_id)
    warnings = coordinator.flush_traffic_outputs(session.meta.session_id, timeout_seconds=0.02)

    assert time.monotonic() - started < 0.5
    assert warnings == ["fping flush 超时，原始输出完整性未知"]
    assert coordinator.get_traffic_summary(session.meta.session_id)["flush_complete"] is False
    release.set()
    coordinator.flush_traffic_outputs(session.meta.session_id, timeout_seconds=1)
