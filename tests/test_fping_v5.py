from __future__ import annotations

import json
import subprocess
from pathlib import Path

from netconsole.core.ping.fping_v5_parser import parse_fping_v5_json_line
from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.core.ping.fping_v5_runner import check_fping_v5_available, resolve_fping_v5_paths
from netconsole.core.ping.fping_v5_stats import FpingV5Stats
from netconsole.models.online_mr_models import FpingConfig
from netconsole.services.network_tools.iperf_runner import IperfClientConfig
from netconsole.services.online_mr.event_bus import EVENT_FPING_V5_SAMPLE, EVENT_IPERF3_ERROR, EVENT_IPERF3_SAMPLE, OnlineMrEvent, OnlineMrEventBus
from netconsole.services.online_mr.db.event_db_writer import OnlineMrEventDbWriter
from netconsole.services.online_mr.diagnosis_engine import OnlineMrDiagnosisEngine
from netconsole.services.online_mr.parser.event_parser_engine import EventParserEngine
from netconsole.services.online_mr.realtime.sliding_window_buffer import SlidingWindowBuffer
from netconsole.services.online_mr.session_adapter import SessionAdapter
from netconsole.services.online_mr.offline.replay_engine import replay_session
from netconsole.services.online_mr.fping_v5_probe import FpingV5ProbeRunner
from netconsole.services.online_mr.workers.iperf3_worker import build_iperf3_json_args
from netconsole.services.online_mr.workers.ssh_resilient_worker import SshResilientWorker
from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser
from datetime import datetime
import sqlite3


def test_fping_v5_path_resolution_requires_exe_and_cygwin(tmp_path: Path) -> None:
    tools = tmp_path / "resources" / "tools" / "windows-x64" / "fping"
    tools.mkdir(parents=True)
    exe = tools / "fping.exe"
    exe.write_text("fake", encoding="utf-8")

    try:
        resolve_fping_v5_paths(tmp_path)
    except FileNotFoundError as exc:
        assert "cygwin1.dll" in str(exc)
    else:
        raise AssertionError("missing cygwin1.dll should fail")

    (tools / "cygwin1.dll").write_text("fake", encoding="utf-8")
    paths = resolve_fping_v5_paths(tmp_path)
    assert paths.fping_path == exe.resolve()


def test_fping_v5_check_reports_missing_executable(tmp_path: Path) -> None:
    result = check_fping_v5_available(tmp_path)
    assert result.available is False
    assert "fping" in result.error


def test_fping_v5_check_detects_json_support(tmp_path: Path, monkeypatch) -> None:
    tools = tmp_path / "resources" / "tools" / "windows-x64" / "fping"
    tools.mkdir(parents=True)
    (tools / "fping.exe").write_text("fake", encoding="utf-8")
    (tools / "cygwin1.dll").write_text("fake", encoding="utf-8")

    def fake_run(args, **kwargs):
        if "-v" in args:
            return subprocess.CompletedProcess(args, 0, stdout="fping: Version 5.5", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="-J, --json output in JSON format", stderr="")

    monkeypatch.setattr("netconsole.core.ping.fping_v5_runner.subprocess.run", fake_run)
    result = check_fping_v5_available(tmp_path)
    assert result.available is True
    assert result.json_supported is True


def test_fping_v5_parse_resp_timeout_meta_unknown_and_non_json() -> None:
    ts = "2026-06-27T10:00:00.123"
    resp = parse_fping_v5_json_line('{"resp":{"host":"127.0.0.1","seq":0,"size":64,"rtt":0.12}}', ts, 100)
    timeout = parse_fping_v5_json_line('{"timeout":{"host":"127.0.0.1","seq":1}}', ts, 100)
    summary = parse_fping_v5_json_line('{"summary":{"host":"127.0.0.1"}}', ts, 100)
    unknown = parse_fping_v5_json_line('{"other":1}', ts, 100)

    assert resp is not None
    assert resp.raw_type == "resp"
    assert resp.ok is True
    assert resp.target == "127.0.0.1"
    assert resp.seq == 0
    assert resp.rtt_ms == 0.12
    assert timeout is not None
    assert timeout.raw_type == "timeout"
    assert timeout.ok is False
    assert timeout.error == "timeout"
    assert summary is not None
    assert summary.raw_type == "summary"
    assert unknown is not None
    assert unknown.raw_type == "unknown"
    assert parse_fping_v5_json_line("not json", ts, 100) is None


def test_fping_v5_stats_counts_only_resp_and_timeout() -> None:
    ts = "2026-06-27T10:00:00.123"
    samples = [
        parse_fping_v5_json_line('{"resp":{"host":"127.0.0.1","seq":0,"size":64,"rtt":0.10}}', ts, 100),
        parse_fping_v5_json_line('{"timeout":{"host":"127.0.0.1","seq":1}}', ts, 100),
        parse_fping_v5_json_line('{"summary":{"host":"127.0.0.1"}}', ts, 100),
        parse_fping_v5_json_line('{"resp":{"host":"127.0.0.1","seq":2,"size":64,"rtt":0.30}}', ts, 100),
    ]
    stats = FpingV5Stats()
    for sample in samples:
        assert sample is not None
        stats.add(sample)

    assert stats.sent_count == 3
    assert stats.success_count == 2
    assert stats.timeout_count == 1
    assert round(stats.loss_rate_percent, 2) == 33.33
    assert stats.avg_rtt_ms == 0.2
    assert stats.min_rtt_ms == 0.1
    assert stats.max_rtt_ms == 0.3


def test_online_mr_event_bus_writes_events_to_db(tmp_path: Path) -> None:
    bus = OnlineMrEventBus()
    writer = OnlineMrEventDbWriter(tmp_path / "events.sqlite")
    bus.subscribe("*", writer.write_event_to_db)

    bus.publish(
        OnlineMrEvent(
            timestamp=datetime(2026, 6, 27, 10, 0, 0),
            device_id=7,
            session_id="s1",
            source="fping_v5",
            module="fping",
            event_type=EVENT_FPING_V5_SAMPLE,
            payload={"loss_rate_percent": 0.0},
            raw='{"resp":{}}',
        )
    )

    with sqlite3.connect(tmp_path / "events.sqlite") as conn:
        row = conn.execute("SELECT session_id, device_id, source, module, event_type FROM event_stream").fetchone()
    assert row == ("s1", 7, "fping_v5", "fping", EVENT_FPING_V5_SAMPLE)


def test_iperf3_json_args_enable_json_output(tmp_path: Path) -> None:
    args = build_iperf3_json_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", interval_seconds=1))
    assert "--json" in args
    assert "--forceflush" in args


def test_session_adapter_converts_fping_v5_jsonl_to_events(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "fping_v5_samples.jsonl").write_text(
        '{"ts":"2026-06-27T10:00:00.123","target":"127.0.0.1","seq":0,"ok":true,"rtt_ms":0.2,"timeout_ms":50,"size":64,"error":"","backend":"fping_v5_json","raw_type":"resp","raw":{"resp":{"host":"127.0.0.1","seq":0,"size":64,"rtt":0.2}}}\n',
        encoding="utf-8",
    )

    events = list(SessionAdapter(session_dir, session_id="s1", device_id=7).iter_events())

    assert len(events) == 1
    assert events[0].event_type == EVENT_FPING_V5_SAMPLE
    assert events[0].source == "fping_v5"


def test_session_adapter_converts_timestamped_iperf_log_and_error_to_events(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "iperf_client_raw.log").write_text(
        "[2026-07-05 18:44:01.123] [mode=client] [  5]   0.00-1.01   sec   128 KBytes  1.03 Mbits/sec\n"
        "[2026-07-05 18:44:02.123] [mode=client] iperf3: error - the server is busy running a test. try again later\n",
        encoding="utf-8",
    )

    events = list(SessionAdapter(session_dir, session_id="s1", device_id=7).iter_events())

    assert [event.event_type for event in events] == [EVENT_IPERF3_SAMPLE, EVENT_IPERF3_ERROR]
    assert events[0].timestamp == datetime(2026, 7, 5, 18, 44, 1, 123000)
    assert events[0].payload["bitrate_mbps"] == 1.03
    assert events[1].payload["error_code"] == "server_busy"


def test_event_parser_derives_fping_quality_and_iperf_score() -> None:
    parser = EventParserEngine()
    parser.on_event(
        OnlineMrEvent(
            timestamp=datetime(2026, 6, 27, 10, 0, 0),
            session_id="s1",
            device_id=7,
            source="fping_v5",
            module="fping",
            event_type=EVENT_FPING_V5_SAMPLE,
            payload={"loss_rate_percent": 2.5, "avg_rtt_ms": 10.0},
        )
    )
    parser.on_event(
        OnlineMrEvent(
            timestamp=datetime(2026, 6, 27, 10, 0, 1),
            session_id="s1",
            device_id=7,
            source="iperf3",
            module="iperf",
            event_type=EVENT_IPERF3_SAMPLE,
            payload={"end": {"sum_received": {"bits_per_second": 88_000_000}}},
        )
    )

    assert parser.latest("fping")["link_quality"] == 97.5
    assert parser.latest("fping")["latency_score"] == 90.0
    assert parser.latest("iperf")["throughput_mbps"] == 88.0


def test_event_parser_keeps_iperf_error_as_latest_status() -> None:
    parser = EventParserEngine()
    parser.on_event(
        OnlineMrEvent(
            timestamp=datetime(2026, 7, 5, 18, 44, 1),
            session_id="s1",
            device_id=7,
            source="iperf3",
            module="iperf",
            event_type=EVENT_IPERF3_ERROR,
            payload={"error_code": "server_busy", "error_message": "busy"},
        )
    )

    latest = parser.latest("iperf")
    assert latest is not None
    assert latest["iperf_error"] is True
    assert latest["error_code"] == "server_busy"


def test_diagnosis_engine_scores_fping_and_iperf() -> None:
    engine = OnlineMrDiagnosisEngine(ping_loss_threshold_percent=1.0)
    engine.on_event(
        OnlineMrEvent(
            timestamp=datetime(2026, 6, 27, 10, 0, 0),
            session_id="s1",
            device_id=7,
            source="fping_v5",
            module="fping",
            event_type=EVENT_FPING_V5_SAMPLE,
            payload={"loss_rate_percent": 5.0},
        )
    )
    engine.on_event(
        OnlineMrEvent(
            timestamp=datetime(2026, 6, 27, 10, 0, 1),
            session_id="s1",
            device_id=7,
            source="iperf3",
            module="iperf",
            event_type=EVENT_IPERF3_SAMPLE,
            payload={"throughput_mbps": 80.0},
        )
    )

    assert engine.module_scores["fping"] == 95.0
    assert engine.module_scores["iperf"] == 80.0
    assert engine.score < 100.0
    assert engine.issues[0].issue_type == "PING_LOSS"


def test_sliding_window_buffer_trims_old_events() -> None:
    buffer = SlidingWindowBuffer(window_seconds=5)
    old = OnlineMrEvent(datetime(2026, 6, 27, 10, 0, 0), "s1", 1, "ssh", "mesh", "MESH_SAMPLE")
    new = OnlineMrEvent(datetime(2026, 6, 27, 10, 0, 10), "s1", 1, "ssh", "mesh", "MESH_SAMPLE")

    buffer.add(old)
    buffer.add(new)

    rows = buffer.get_window()
    assert rows[-1] == new
    assert old not in rows


def test_ssh_resilient_worker_reconnects_on_10054(monkeypatch) -> None:
    calls = {"read": 0, "reconnect": 0}

    def read_stream() -> None:
        calls["read"] += 1
        if calls["read"] == 1:
            raise OSError("WinError 10054 connection reset")

    def reconnect() -> None:
        calls["reconnect"] += 1

    monkeypatch.setattr("netconsole.services.online_mr.workers.ssh_resilient_worker.time.sleep", lambda _seconds: None)
    worker = SshResilientWorker(read_stream, reconnect, max_reconnects=2)
    worker.run()

    assert calls == {"read": 2, "reconnect": 1}


def test_offline_replay_engine_writes_fping_events_and_diagnosis(tmp_path: Path) -> None:
    session_dir = _write_fping_only_session(tmp_path)

    result = replay_session(session_dir, session_id="s1", device_id=7)

    assert result.events == 1
    assert result.fping["link_quality"] == 100.0
    assert result.diagnosis_score == 100.0
    with sqlite3.connect(session_dir / "parsed" / "online_diagnosis.sqlite") as conn:
        row = conn.execute("SELECT source, module, event_type FROM event_stream").fetchone()
    assert row == ("fping_v5", "fping", EVENT_FPING_V5_SAMPLE)


def test_diagnosis_parser_creates_replay_segment_for_fping_only_session(tmp_path: Path) -> None:
    session_dir = _write_fping_only_session(tmp_path)

    summary = OnlineMrDiagnosisParser(session_dir).parse()

    assert summary.ping_samples == 1
    assert summary.active_segments == 1
    with sqlite3.connect(session_dir / "parsed" / "online_diagnosis.sqlite") as conn:
        row = conn.execute(
            """
            SELECT s.event_type, m.ping_loss_percent, m.avg_latency_ms
            FROM active_segments s
            JOIN active_segment_metrics m ON m.segment_id = s.id
            """
        ).fetchone()
    assert row == ("NORMAL", 0.0, 0.2)


def test_diagnosis_parser_records_iperf_busy_error_without_intervals(tmp_path: Path) -> None:
    session_dir = _write_fping_only_session(tmp_path)
    (session_dir / "raw" / "fping_v5_samples.jsonl").unlink()
    (session_dir / "raw" / "iperf_client_raw.log").write_text(
        "[2026-07-05 18:44:02.123] [mode=client] iperf3: error - the server is busy running a test. try again later\n",
        encoding="utf-8",
    )

    summary = OnlineMrDiagnosisParser(session_dir).parse()

    assert summary.iperf_samples == 0
    assert summary.iperf_error_count == 1
    with sqlite3.connect(session_dir / "parsed" / "online_diagnosis.sqlite") as conn:
        row = conn.execute("SELECT event_type, details_json FROM analysis_events WHERE event_type = 'IPERF_ERROR'").fetchone()
    assert row is not None
    assert "server_busy" in row[1]


def test_fping_v5_runner_publishes_source_device_and_target(tmp_path: Path) -> None:
    events = []
    bus = OnlineMrEventBus()
    bus.subscribe("*", events.append)
    session = type("Session", (), {"meta": type("Meta", (), {"device_id": 7, "session_id": "s1"})()})()
    runner = FpingV5ProbeRunner(
        session,
        FpingConfig(target="127.0.0.1"),
        tmp_path / "fping.exe",
        event_bus=bus,
        source_device_id=7,
    )

    runner.handle_sample(
        FpingV5Sample(
            ts="2026-06-27T10:00:00.123",
            target="127.0.0.1",
            seq=1,
            ok=True,
            rtt_ms=0.2,
            timeout_ms=100,
            size=64,
            error="",
            backend="fping_v5_json",
            raw_type="resp",
            raw={"resp": {"host": "127.0.0.1"}},
        )
    )

    assert events[0].device_id == 7
    assert events[0].payload["source_device_id"] == 7
    assert events[0].payload["target_ip"] == "127.0.0.1"


def test_fping_v5_runner_handles_disabled_probe_without_qt(tmp_path: Path) -> None:
    summaries: list[str] = []
    session = type(
        "Session",
        (),
        {
            "meta": type("Meta", (), {"device_id": 7, "session_id": "s1"})(),
            "write_fping_final_summary": summaries.append,
        },
    )()
    runner = FpingV5ProbeRunner(session, FpingConfig(enabled=False), tmp_path / "fping.exe")

    result = runner.run()

    assert result.status == "disabled"
    assert result.error == ""
    assert summaries == ["Status: high frequency ping disabled"]


def test_fping_config_serializes_high_ping_preset_and_compat_keys() -> None:
    cfg = FpingConfig(
        target=" 127.0.0.1 ",
        preset_key="cbtc_dcs_attkping_1256b",
        preset_name="CBTC/DCS Attkping 等效 1256B",
        packet_size=1256,
        interval_ms=30,
        loss_threshold_ms=100,
        loss_warn_percent=5.0,
        latency_warn_ms=100,
    )

    data = cfg.as_dict()

    assert data["target"] == "127.0.0.1"
    assert data["preset_key"] == "cbtc_dcs_attkping_1256b"
    assert data["preset_name"] == "CBTC/DCS Attkping 等效 1256B"
    assert data["packet_size"] == 1256
    assert data["packet_size_bytes"] == 1256
    assert data["loss_threshold_ms"] == 100
    assert data["timeout_ms"] == 100
    assert data["loss_warn_percent"] == 5.0
    assert data["latency_warn_ms"] == 100


def _write_fping_only_session(tmp_path: Path) -> Path:
    session_dir = tmp_path / "session"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (session_dir / "parsed").mkdir()
    (session_dir / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "s1",
                "site": "site",
                "mr_id": "mr1",
                "mr_name": "MR1",
                "device_id": 7,
                "device_name": "MR1",
                "host": "127.0.0.1",
                "protocol": "SSH",
                "port": 22,
                "connection_method": "",
                "started_at": "2026-06-27 10:00:00",
                "ended_at": None,
                "status": "STOPPED",
                "intervals": {},
                "radio": {},
                "fping": {"target": "127.0.0.1", "packet_size": 64, "interval_ms": 10, "loss_threshold_ms": 100},
                "iperf": {},
                "stats": {},
            }
        ),
        encoding="utf-8",
    )
    (raw_dir / "fping_v5_samples.jsonl").write_text(
        '{"ts":"2026-06-27T10:00:00.123","target":"127.0.0.1","seq":0,"ok":true,"rtt_ms":0.2,"timeout_ms":50,"size":64,"error":"","backend":"fping_v5_json","raw_type":"resp","raw":{"resp":{"host":"127.0.0.1","seq":0,"size":64,"rtt":0.2}}}\n',
        encoding="utf-8",
    )
    return session_dir
