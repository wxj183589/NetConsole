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


class _FakeFailingClientIperfRunner(_FakeIperfRunner):
    def __init__(self, _tool, _command, log_file, **kwargs) -> None:
        super().__init__(_tool, _command, log_file, **kwargs)
        self.mode = kwargs.get("mode", "client")

    def start(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        if self.mode == "server":
            self.last_status = "RUNNING"
            self.stop_event.wait(2)
            self.last_status = "STOPPED_BY_COLLECTION" if self.stop_event.is_set() else "RUNNING"
            return
        self.last_status = "FAILED:1"
        self.log_file.write_text("client failed\n", encoding="utf-8")


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
    fping_view = json.loads((session.session_dir / "view" / "live_fping_status.json").read_text(encoding="utf-8"))
    iperf_view = json.loads((session.session_dir / "view" / "live_iperf_status.json").read_text(encoding="utf-8"))
    assert fping_view["summary"]["sent_count"] == 1
    assert iperf_view["status"] == "stopped_by_collection"


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


def test_loopback_iperf_starts_and_stops_managed_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    config.fping = FpingConfig(enabled=False)
    config.iperf = IperfTrafficConfig(
        enabled=True,
        server_ip="127.0.0.1",
        protocol="TCP",
        target_bandwidth="2M",
        tcp_pacing_enabled=True,
        tcp_pacing_mbps=2,
        follow_collection=True,
    )
    paths = PathResolver(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    tool = tmp_path / "iperf3.exe"
    tool.touch()
    _FakeIperfRunner.instances.clear()
    listener_checks = iter([False, True])

    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_iperf_tool", lambda _paths: tool)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.IperfProcessRunner", _FakeIperfRunner)
    monkeypatch.setattr(
        OnlineMrTrafficCoordinator,
        "_is_tcp_listener",
        staticmethod(lambda _host, _port: next(listener_checks, True)),
    )

    coordinator = OnlineMrTrafficCoordinator(paths)
    coordinator.start_for_session(session, config)
    coordinator.stop_traffic_for_session(session.meta.session_id)
    coordinator.flush_traffic_outputs(session.meta.session_id, timeout_seconds=2)
    coordinator.finalize_traffic_outputs(session.meta.session_id)

    assert len(_FakeIperfRunner.instances) == 2
    assert (session.session_dir / "raw" / "iperf_server_raw.log").is_file()
    assert (session.session_dir / "raw" / "iperf_client_raw.log").is_file()
    assert all(instance.last_status == "STOPPED_BY_COLLECTION" for instance in _FakeIperfRunner.instances)
    view = json.loads((session.session_dir / "view" / "live_iperf_status.json").read_text(encoding="utf-8"))
    assert view["server_ip"] == "127.0.0.1"
    assert view["protocol"] == "TCP"
    assert view["target_bandwidth"] == "2M"


def test_failed_client_does_not_stop_managed_server_until_session_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    config.fping = FpingConfig(enabled=False)
    config.iperf = IperfTrafficConfig(enabled=True, server_ip="127.0.0.1", follow_collection=True)
    paths = PathResolver(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    tool = tmp_path / "iperf3.exe"
    tool.touch()
    _FakeFailingClientIperfRunner.instances.clear()
    listener_checks = iter([False, True])
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_iperf_tool", lambda _paths: tool)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.IperfProcessRunner", _FakeFailingClientIperfRunner)
    monkeypatch.setattr(OnlineMrTrafficCoordinator, "_is_tcp_listener", staticmethod(lambda _host, _port: next(listener_checks, True)))

    coordinator = OnlineMrTrafficCoordinator(paths)
    coordinator.start_for_session(session, config)
    time.sleep(0.05)
    assert coordinator.get_traffic_summary(session.meta.session_id)["iperf"]["status"] == "failed:1"
    assert coordinator.get_traffic_summary(session.meta.session_id)["iperf"]["server_status"] == "running"
    assert coordinator.get_traffic_summary(session.meta.session_id)["iperf"]["server_ownership"] == "managed"
    assert _FakeFailingClientIperfRunner.instances[0].last_status == "RUNNING"

    coordinator.stop_traffic_for_session(session.meta.session_id)
    coordinator.flush_traffic_outputs(session.meta.session_id, timeout_seconds=2)
    assert _FakeFailingClientIperfRunner.instances[0].last_status == "STOPPED_BY_COLLECTION"


def test_debug_stdout_is_snapshot_throttled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    config.fping = FpingConfig(enabled=False)
    config.iperf = IperfTrafficConfig(enabled=True, server_ip="192.0.2.3", follow_collection=False)
    paths = PathResolver(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    tool = tmp_path / "iperf3.exe"
    tool.touch()
    snapshot_calls = 0

    class FakeDebugRunner:
        def __init__(self, _tool, _command, _log_file, *, line_callback=None, **_kwargs) -> None:
            self.line_callback = line_callback
            self.last_status = "CREATED"
            self.run_id = "debug-run"

        def start(self) -> None:
            self.last_status = "RUNNING"
            for index in range(5_000):
                self.line_callback(f"sent 131072 bytes, total {index}", None, None)
            self.last_status = "DONE"

        def stop(self, _status: str = "STOPPED_BY_USER") -> None:
            self.last_status = "STOPPED_BY_USER"

    def count_snapshot(*_args, **_kwargs) -> None:
        nonlocal snapshot_calls
        snapshot_calls += 1

    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_iperf_tool", lambda _paths: tool)
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.IperfProcessRunner", FakeDebugRunner)
    monkeypatch.setattr(OnlineMrTrafficCoordinator, "_safe_write_iperf_snapshot", staticmethod(count_snapshot))

    coordinator = OnlineMrTrafficCoordinator(paths)
    coordinator.start_for_session(session, config)
    coordinator.flush_traffic_outputs(session.meta.session_id, timeout_seconds=2)

    assert snapshot_calls <= 3


def test_non_iperf_listener_is_reported_as_port_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    config.fping = FpingConfig(enabled=False)
    config.iperf = IperfTrafficConfig(enabled=True, server_ip="127.0.0.1", follow_collection=True)
    paths = PathResolver(tmp_path)
    session = OnlineMrSessionStore(paths).create_session(config)
    tool = tmp_path / "iperf3.exe"
    tool.touch()
    monkeypatch.setattr("netconsole.services.online_mr.traffic_coordinator.find_iperf_tool", lambda _paths: tool)
    monkeypatch.setattr(OnlineMrTrafficCoordinator, "_is_tcp_listener", staticmethod(lambda _host, _port: True))
    monkeypatch.setattr(OnlineMrTrafficCoordinator, "_listener_metadata", staticmethod(lambda _host, _port: {
        "listener_pid": 4321,
        "listener_process_name": "other.exe",
        "listener_executable": "C:/other.exe",
        "listener_command_line": "other.exe --listen",
        "listener_owner": "external",
        "listener_started_at": "2026-08-10 10:00:00",
    }))
    monkeypatch.setattr(OnlineMrTrafficCoordinator, "_verify_external_iperf_server", staticmethod(lambda _tool, _port: False))

    coordinator = OnlineMrTrafficCoordinator(paths)
    coordinator.start_for_session(session, config)
    view = json.loads((session.session_dir / "view" / "live_iperf_status.json").read_text(encoding="utf-8"))

    assert view["server_status"] == "port_conflict"
    assert view["server_ownership"] == "port_conflict"
    assert view["server_error_code"] == "IPERF_PORT_OCCUPIED_BY_NON_IPERF"
    assert view["listener_pid"] == 4321
    assert view["listener_process_name"] == "other.exe"
