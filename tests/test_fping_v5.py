from __future__ import annotations

import subprocess
from pathlib import Path

from netconsole.core.ping.fping_v5_parser import parse_fping_v5_json_line
from netconsole.core.ping.fping_v5_runner import check_fping_v5_available, resolve_fping_v5_paths
from netconsole.core.ping.fping_v5_stats import FpingV5Stats


def test_fping_v5_path_resolution_requires_exe_and_cygwin(tmp_path: Path) -> None:
    tools = tmp_path / "tools" / "fping_v5"
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
    tools = tmp_path / "tools" / "fping_v5"
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
