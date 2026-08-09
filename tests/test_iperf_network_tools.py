from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_models import IperfTrafficConfig
from netconsole.services.network_tools.iperf_parser import (
    aggregate_iperf_for_segment,
    format_iperf_log_header,
    format_iperf_log_line,
    parse_iperf_error_line,
    parse_iperf_line,
    parse_iperf_lines,
    split_iperf_log_prefix,
    summarize_iperf_zero_samples,
)
from netconsole.services.network_tools.iperf_runner import (
    FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
    IperfClientConfig,
    IperfResultStore,
    IperfProcessRunner,
    build_iperf_client_args,
    normalize_bandwidth_text,
    run_iperf_client_preflight,
)
from netconsole.services.network_tools.iperf_tool_service import detect_iperf_version, find_iperf_tool
from netconsole.services.online_mr.traffic_presets import DEFAULT_TRAFFIC_PRESET_PORT, get_traffic_preset, list_traffic_presets
from netconsole.services.online_mr.workers.iperf3_worker import build_iperf3_json_args




class FakeWheelEvent:
    def __init__(self) -> None:
        self.ignored = False

    def ignore(self) -> None:
        self.ignored = True


def test_iperf_stop_marks_already_exited_without_terminate(tmp_path: Path) -> None:
    class ExitedProcess:
        pid = 1234
        terminated = False

        def poll(self):
            return 1

        def terminate(self):
            self.terminated = True

    tool = tmp_path / "iperf3.exe"
    tool.touch()
    runner = IperfProcessRunner(tool, [str(tool), "-c", "127.0.0.1"], tmp_path / "iperf.log")
    process = ExitedProcess()
    runner.process = process

    runner.stop("STOPPED_BY_COLLECTION")

    assert runner.stop_reason == "already_exited"
    assert process.terminated is False
    assert runner.diagnostics()["exit_code"] == 1


def test_iperf_tool_discovery_from_project_tools(tmp_path: Path) -> None:
    exe = tmp_path / "tools" / "windows-x64" / "iperf3" / "iperf3.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("fake", encoding="utf-8")
    for companion in ("cygwin1.dll", "cygcrypto-3.dll", "cygz.dll"):
        (exe.parent / companion).write_bytes(b"fake")
    assert find_iperf_tool(PathResolver(tmp_path)) == exe.resolve()


def test_iperf_version_parses_3_20_with_extra_output(tmp_path: Path) -> None:
    exe = tmp_path / "iperf3.exe"
    exe.write_text("fake", encoding="utf-8")

    def runner(*args, **kwargs):
        class Result:
            stdout = "iperf 3.20 (cJSON 1.7.15)\nCYGWIN_NT-10.0-26200\n"
            stderr = "Optional features available: POSIX threads"
            returncode = 0

        return Result()

    status = detect_iperf_version(exe, runner=runner)
    assert status.found is True
    assert status.version == "3.20"


def test_tcp_auto_max_bandwidth_omits_bandwidth_arg(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="TCP", target_bandwidth=None))
    assert "-b" not in args
    assert "-d" not in args


def test_tcp_target_bandwidth_includes_bandwidth_arg(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="TCP", target_bandwidth="100M"))
    assert args[args.index("-b") + 1] == "100M"


def test_target_bandwidth_value_and_unit_formats_arg(tmp_path: Path) -> None:
    assert normalize_bandwidth_text("100", "M") == "100M"
    assert normalize_bandwidth_text("1", "G") == "1G"
    assert normalize_bandwidth_text("12.5", "M") == "12.5M"
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="TCP", target_bandwidth=normalize_bandwidth_text("1", "G")))
    assert args[args.index("-b") + 1] == "1G"


def test_invalid_target_bandwidth_is_rejected() -> None:
    for value in ("-1", "abc", "1x", ""):
        if value == "":
            assert normalize_bandwidth_text(value, "M") is None
        else:
            import pytest

            with pytest.raises(ValueError):
                normalize_bandwidth_text(value, "M")


def test_udp_defaults_to_10m_bandwidth(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", protocol="UDP", target_bandwidth=None))
    assert "-u" in args
    assert args[args.index("-b") + 1] == "10M"


def test_iperf_direction_args(tmp_path: Path) -> None:
    upload = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", direction="upload"))
    download = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", direction="download"))
    bidirectional = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("10.0.0.1", direction="bidirectional"))
    assert "-R" not in upload and "--bidir" not in upload
    assert "-R" in download
    assert "--bidir" in bidirectional


def test_pis_tcp_downlink_max_template_omits_bandwidth_arg(tmp_path: Path) -> None:
    preset = get_traffic_preset("pis_tcp_downlink_single")
    assert preset is not None
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig(
            "10.0.0.1",
            port=5010,
            protocol=preset.protocol,
            direction="download",
            parallel=preset.parallel,
            interval_seconds=preset.interval_sec,
            duration_seconds=preset.duration_sec,
            target_bandwidth=None,
        ),
    )
    assert "--json" in args
    assert "-R" in args
    assert args[args.index("-P") + 1] == "1"
    assert "-b" not in args


def test_online_mr_traffic_presets_default_to_iperf_standard_port() -> None:
    assert DEFAULT_TRAFFIC_PRESET_PORT == 5201
    assert list_traffic_presets()
    assert {preset.port for preset in list_traffic_presets()} == {5201}


def test_pis_tcp_parallel_template_omits_bandwidth_arg(tmp_path: Path) -> None:
    preset = get_traffic_preset("pis_tcp_downlink_parallel")
    assert preset is not None
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig(
            "10.0.0.1",
            port=5010,
            protocol=preset.protocol,
            direction="download",
            parallel=preset.parallel,
            interval_seconds=preset.interval_sec,
            duration_seconds=preset.duration_sec,
            target_bandwidth=None,
        ),
    )
    assert "-b" not in args
    assert args[args.index("-P") + 1] == "4"


def test_pis_udp_downlink_carrier_template_uses_bitrate_and_packet_length(tmp_path: Path) -> None:
    preset = get_traffic_preset("pis_udp_downlink_carrier")
    assert preset is not None
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig(
            "10.0.0.1",
            port=5010,
            protocol=preset.protocol,
            direction="download",
            parallel=preset.parallel,
            interval_seconds=preset.interval_sec,
            duration_seconds=preset.duration_sec,
            target_bandwidth=normalize_bandwidth_text(preset.udp_bitrate_mbps, "M"),
            packet_length=preset.packet_length,
        ),
    )
    assert "-u" in args
    assert "-R" in args
    assert args[args.index("-b") + 1] == "600M"
    assert args[args.index("-l") + 1] == "1400"
    assert args[args.index("-P") + 1] == "1"


def test_cbtc_dcs_traffic_presets_are_registered() -> None:
    keys = [preset.key for preset in list_traffic_presets()]

    assert keys[-5:] == [
        "cbtc_dcs_udp_1m_64b",
        "cbtc_dcs_udp_1_3m_64b",
        "cbtc_dcs_udp_1m_256b",
        "cbtc_dcs_udp_1m_1256b",
        "cbtc_dcs_tcp_observation",
    ]
    assert all(preset.duration_mode == "follow_collection" for preset in list_traffic_presets())
    assert all(preset.duration_sec == FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS for preset in list_traffic_presets())


def test_cbtc_dcs_udp_templates_generate_bitrate_packet_length_and_reverse(tmp_path: Path) -> None:
    expected = {
        "cbtc_dcs_udp_1m_64b": ("1M", "64"),
        "cbtc_dcs_udp_1_3m_64b": ("1.3M", "64"),
        "cbtc_dcs_udp_1m_256b": ("1M", "256"),
        "cbtc_dcs_udp_1m_1256b": ("1M", "1256"),
    }

    for key, (bandwidth, packet_length) in expected.items():
        preset = get_traffic_preset(key)
        assert preset is not None
        args = build_iperf3_json_args(
            tmp_path / "iperf3.exe",
            IperfClientConfig(
                "10.0.0.1",
                port=5010,
                protocol=preset.protocol,
                direction="download",
                parallel=preset.parallel,
                interval_seconds=preset.interval_sec,
                duration_seconds=preset.duration_sec,
                target_bandwidth=normalize_bandwidth_text(preset.udp_bitrate_mbps, "M"),
                packet_length=preset.packet_length,
            ),
        )
        assert "-u" in args
        assert "-R" in args
        assert args[args.index("-b") + 1] == bandwidth
        assert args[args.index("-l") + 1] == packet_length
        assert args[args.index("-P") + 1] == "1"


def test_cbtc_dcs_tcp_observation_template_omits_bandwidth_arg(tmp_path: Path) -> None:
    preset = get_traffic_preset("cbtc_dcs_tcp_observation")
    assert preset is not None
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig(
            "10.0.0.1",
            port=5010,
            protocol=preset.protocol,
            direction="download",
            parallel=preset.parallel,
            interval_seconds=preset.interval_sec,
            duration_seconds=preset.duration_sec,
            target_bandwidth=None,
        ),
    )

    assert "-R" in args
    assert "-b" not in args
    assert args[args.index("-P") + 1] == "1"


def test_online_mr_tcp_threshold_does_not_generate_bandwidth_arg(tmp_path: Path) -> None:
    traffic = IperfTrafficConfig(protocol="TCP", tcp_report_threshold_mbps=800.0, tcp_pacing_enabled=False).normalized()
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig("10.0.0.1", protocol=traffic.protocol, target_bandwidth=traffic.target_bandwidth, debug_output_enabled=traffic.debug_output_enabled),
    )
    assert traffic.tcp_report_threshold_mbps == 800.0
    assert "-b" not in args
    assert args.count("-d") == 1


def test_online_mr_tcp_rate_limit_generates_bandwidth_arg_without_parallel_split(tmp_path: Path) -> None:
    traffic = IperfTrafficConfig(protocol="TCP", tcp_report_threshold_mbps=600.0, tcp_rate_limit_mbps=600.0, parallel=4).normalized()
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig(
            "10.0.0.1",
            protocol=traffic.protocol,
            parallel=traffic.parallel,
            target_bandwidth=traffic.target_bandwidth,
            debug_output_enabled=traffic.debug_output_enabled,
        ),
    )
    assert args[args.index("-b") + 1] == "600M"
    assert args[args.index("-P") + 1] == "4"
    assert "150M" not in args
    assert args.count("-d") == 1


def test_online_mr_tcp_rate_limit_zero_means_unlimited(tmp_path: Path) -> None:
    traffic = IperfTrafficConfig(protocol="TCP", tcp_rate_limit_mbps=0).normalized()
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig("10.0.0.1", protocol=traffic.protocol, target_bandwidth=traffic.target_bandwidth, debug_output_enabled=traffic.debug_output_enabled),
    )
    assert traffic.tcp_rate_limit_mbps == 0
    assert "-b" not in args
    assert args.count("-d") == 1


def test_online_mr_legacy_tcp_pacing_maps_to_rate_limit(tmp_path: Path) -> None:
    traffic = IperfTrafficConfig(protocol="TCP", tcp_report_threshold_mbps=600.0, tcp_pacing_enabled=True, tcp_pacing_mbps=600.0).normalized()
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig("10.0.0.1", protocol=traffic.protocol, target_bandwidth=traffic.target_bandwidth, debug_output_enabled=traffic.debug_output_enabled),
    )
    assert traffic.tcp_rate_limit_mbps == 600.0
    assert args[args.index("-b") + 1] == "600M"


def test_online_mr_udp_bitrate_and_threshold_are_separate(tmp_path: Path) -> None:
    traffic = IperfTrafficConfig(protocol="UDP", udp_bitrate_mbps=800.0, udp_report_threshold_mbps=600.0, packet_length=1400).normalized()
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig("10.0.0.1", protocol=traffic.protocol, target_bandwidth=traffic.target_bandwidth, packet_length=traffic.packet_length, debug_output_enabled=traffic.debug_output_enabled),
    )
    assert traffic.udp_bitrate_mbps == 800.0
    assert traffic.udp_report_threshold_mbps == 600.0
    assert traffic.report_threshold_mbps == 600.0
    assert args[args.index("-b") + 1] == "800M"
    assert args[args.index("-l") + 1] == "1400"


def test_online_mr_legacy_tcp_bandwidth_maps_to_threshold_not_pacing(tmp_path: Path) -> None:
    traffic = IperfTrafficConfig(protocol="TCP", target_bandwidth="600M").normalized()
    args = build_iperf3_json_args(
        tmp_path / "iperf3.exe",
        IperfClientConfig("10.0.0.1", protocol=traffic.protocol, target_bandwidth=traffic.target_bandwidth, debug_output_enabled=traffic.debug_output_enabled),
    )
    assert traffic.tcp_report_threshold_mbps == 600.0
    assert traffic.tcp_pacing_enabled is False
    assert traffic.target_bandwidth is None
    assert "-b" not in args
    assert args.count("-d") == 1


def test_follow_collection_manual_duration_uses_long_duration(tmp_path: Path) -> None:
    config = IperfClientConfig("10.0.0.1", duration_seconds=600, follow_collection=True)
    args = build_iperf_client_args(tmp_path / "iperf3.exe", config)
    assert args[args.index("-t") + 1] == str(FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS)


def test_low_rate_tcp_client_uses_smaller_block_size(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("127.0.0.1", protocol="TCP", target_bandwidth="1M"))
    assert args[args.index("-l") + 1] == "16K"


def test_high_rate_tcp_client_does_not_force_small_block_size(tmp_path: Path) -> None:
    args = build_iperf_client_args(tmp_path / "iperf3.exe", IperfClientConfig("127.0.0.1", protocol="TCP", target_bandwidth="100M"))
    assert "-l" not in args


def test_iperf_output_parser_extracts_interval_fields() -> None:
    row = parse_iperf_line("[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes")
    assert row is not None
    assert row["interval_start_sec"] == 0
    assert row["interval_end_sec"] == 1
    assert row["bitrate_mbps"] == 88.1
    assert row["retransmits"] == 0


def test_iperf_parser_accepts_netconsole_timestamp_prefix() -> None:
    row = parse_iperf_line("[2026-07-05 18:44:01.123] [mode=client] [  5]   0.00-1.01   sec   128 KBytes  1.03 Mbits/sec")
    assert row is not None
    assert row["bitrate_mbps"] == 1.03
    assert row["collector_time"] == "2026-07-05 18:44:01.123"
    assert row["raw_iperf_line"].startswith("[  5]")


def test_iperf_error_parser_detects_server_busy_with_timestamp() -> None:
    event = parse_iperf_error_line(
        "[2026-07-05 18:44:01.123] [mode=client] iperf3: error - the server is busy running a test. try again later"
    )
    assert event is not None
    assert event["event_type"] == "error"
    assert event["error_code"] == "server_busy"
    assert event["collector_time"] == "2026-07-05 18:44:01.123"


def test_format_iperf_log_line_keeps_parseable_iperf_payload() -> None:
    stamped = format_iperf_log_line(
        datetime(2026, 7, 5, 18, 44, 1, 123000),
        "[  5]   0.00-1.01   sec   128 KBytes  1.03 Mbits/sec",
        {"mode": "client", "run_id": "r1"},
    )
    stamp, payload = split_iperf_log_prefix(stamped)
    assert stamp == datetime(2026, 7, 5, 18, 44, 1, 123000)
    assert payload.startswith("[  5]")
    assert parse_iperf_line(stamped)["bitrate_mbps"] == 1.03
    assert "[run_id=" not in stamped


def test_format_iperf_log_header_keeps_repeated_metadata_out_of_interval_lines() -> None:
    context = {
        "mode": "client",
        "run_id": "r1",
        "session_id": "s1",
        "device_id": 7,
        "batch_key": "demo|127.0.0.1|5201|TCP|upload|1|1M|86400|True",
        "batch_key_hash": "abcd1234",
    }
    header = format_iperf_log_header(context, datetime(2026, 7, 5, 19, 23, 4, 116000))
    line = format_iperf_log_line(
        datetime(2026, 7, 5, 19, 23, 5, 116000),
        "[  5] 548.01-549.00 sec   128 KBytes  1.05 Mbits/sec",
        context,
    )
    assert header[0] == "# NETCONSOLE_IPERF_LOG_VERSION=2"
    assert "# batch_key_hash=abcd1234" in header
    assert "batch_key=" in "\n".join(header)
    assert line.startswith("IPERF [2026-07-05 19:23:05.116] [client] [  5]")
    assert "run_id" not in line
    assert "session_id" not in line
    assert "batch_key" not in line


def test_format_iperf_log_header_records_follow_collection_policy() -> None:
    context = {
        "mode": "client",
        "duration_mode": "follow_collection",
        "protection_duration_seconds": FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        "stop_policy": "stop_with_collection",
    }
    header = format_iperf_log_header(context, datetime(2026, 7, 6, 9, 1, 2))
    assert "# duration_mode=follow_collection" in header
    assert f"# protection_duration_seconds={FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS}" in header
    assert "# stop_policy=stop_with_collection" in header


def test_iperf_parser_accepts_compact_log_format() -> None:
    row = parse_iperf_line("IPERF [2026-07-05 19:23:04.116] [client] [  5] 548.01-549.00 sec   128 KBytes  1.05 Mbits/sec")
    assert row is not None
    assert row["collector_time"] == "2026-07-05 19:23:04.116"
    assert row["bitrate_mbps"] == 1.05


def test_iperf_parser_keeps_verbose_log_compatibility() -> None:
    row = parse_iperf_line("IPERF: [2026-07-05 19:23:04.116] [mode=client] [run_id=xxx] [session_id=yyy] [device_id=217] [batch_id=demo] [  5] 548.01-549.00 sec   128 KBytes  1.05 Mbits/sec")
    assert row is not None
    assert row["collector_time"] == "2026-07-05 19:23:04.116"
    assert row["bitrate_mbps"] == 1.05


def test_iperf_parser_skips_header_lines() -> None:
    assert parse_iperf_line("# run_id=20260705_191355_080700") is None
    assert parse_iperf_lines(["# run_id=20260705_191355_080700"]) == []


def test_iperf_error_parser_accepts_compact_error_format() -> None:
    event = parse_iperf_error_line(
        "IPERF [2026-07-05 19:23:10.001] [client] ERROR server_busy: iperf3: error - the server is busy running a test. try again later"
    )
    assert event is not None
    assert event["event_type"] == "error"
    assert event["error_code"] == "server_busy"
    assert event["collector_time"] == "2026-07-05 19:23:10.001"


def test_iperf_preflight_reports_connection_refused(tmp_path: Path, monkeypatch) -> None:
    tool = tmp_path / "iperf3.exe"
    tool.write_text("fake", encoding="utf-8")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="iperf3: error - unable to connect to server - Connection refused\n",
        )

    monkeypatch.setattr("netconsole.services.network_tools.iperf_runner.subprocess.run", fake_run)

    result = run_iperf_client_preflight(tool, IperfClientConfig("127.0.0.1", port=5010))

    assert result.ok is False
    assert result.error_code == "unable_to_connect"
    assert "Connection refused" in result.message


def test_iperf_interval_center_time_aligns_to_started_at() -> None:
    row = parse_iperf_line("[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes", datetime(2025, 1, 1, 10, 0, 0))
    assert row is not None
    assert row["interval_center_time"] == "2025-01-01 10:00:00.500"


def test_iperf_isolated_zero_sample_is_report_gap() -> None:
    rows = parse_iperf_lines(
        [
            "[  5] 0.00-1.00 sec 128 KBytes 1.05 Mbits/sec",
            "[  5] 1.00-2.00 sec 128 KBytes 1.06 Mbits/sec",
            "[  5] 2.00-3.00 sec 0.00 Bytes 0.00 bits/sec",
            "[  5] 3.00-4.00 sec 128 KBytes 1.05 Mbits/sec",
            "[  5] 4.00-5.00 sec 128 KBytes 1.04 Mbits/sec",
        ]
    )
    assert rows[2]["zero_sample"] is True
    assert rows[2]["zero_sample_type"] == "isolated_report_gap"
    assert summarize_iperf_zero_samples(rows)["iperf_isolated_gap_count"] == 1


def test_iperf_consecutive_zero_samples_are_stall() -> None:
    rows = parse_iperf_lines(
        [
            "[  5] 0.00-1.00 sec 128 KBytes 1.05 Mbits/sec",
            "[  5] 1.00-2.00 sec 0.00 Bytes 0.00 bits/sec",
            "[  5] 2.00-3.00 sec 0.00 Bytes 0.00 bits/sec",
            "[  5] 3.00-4.00 sec 0.00 Bytes 0.00 bits/sec",
            "[  5] 4.00-5.00 sec 128 KBytes 1.04 Mbits/sec",
        ]
    )
    assert [row["zero_sample_type"] for row in rows[1:4]] == ["consecutive_stall", "consecutive_stall", "consecutive_stall"]
    assert summarize_iperf_zero_samples(rows)["iperf_stall_count"] == 3


def test_iperf_active_segment_aggregation() -> None:
    start = datetime(2025, 1, 1, 10, 0, 0)
    rows = []
    for index in range(10):
        row = parse_iperf_line(f"[  5]   {index:.2f}-{index + 1:.2f}   sec  1.0 MBytes  {10 + index}.0 Mbits/sec  {index}   256 KBytes", start)
        assert row is not None
        rows.append(row)
    result = aggregate_iperf_for_segment(rows, start, start + timedelta(seconds=10))
    assert result["sample_count"] == 10
    assert result["avg_mbps"] == 14.5
    assert result["max_mbps"] == 19.0
    assert result["retransmits"] == 45


def test_iperf_result_store_creates_required_tables(tmp_path: Path) -> None:
    store = IperfResultStore(tmp_path / "iperf_results.sqlite")
    store.start_run("run1", mode="client", command=["iperf3"], log_file=tmp_path / "raw.log", started_at=datetime(2025, 1, 1), device_id=7, config=IperfClientConfig("10.0.0.1"))
    row = parse_iperf_line("[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes", datetime(2025, 1, 1))
    assert row is not None
    store.append_interval("run1", row)
    store.finish_run("run1", "DONE")
    with sqlite3.connect(tmp_path / "iperf_results.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM iperf_runs").fetchone()[0] == 1
        assert conn.execute("SELECT device_id FROM iperf_runs").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1
        columns = {item[1] for item in conn.execute("PRAGMA table_info(iperf_intervals)")}
        assert {
            "device_aligned_time",
            "device_interval_center_time",
            "clock_offset_ms",
            "offset_source",
            "time_source",
            "source_event_key",
        } <= columns


def test_iperf_result_store_deduplicates_agent_event_key(tmp_path: Path) -> None:
    store = IperfResultStore(tmp_path / "iperf_results.sqlite")
    store.start_run(
        "agent-run",
        mode="agent_client",
        command=["agent", "iperf_client"],
        log_file=tmp_path / "agent.log",
        started_at=datetime(2025, 1, 1),
        config=IperfClientConfig("10.0.0.1"),
    )
    row = parse_iperf_line(
        "[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes",
        datetime(2025, 1, 1),
    )
    assert row is not None

    assert store.append_interval("agent-run", row, source_event_key="agent-task:7") is True
    assert store.append_interval("agent-run", row, source_event_key="agent-task:7") is False

    with sqlite3.connect(tmp_path / "iperf_results.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1


def test_iperf_result_store_migrates_old_interval_table(tmp_path: Path) -> None:
    db_path = tmp_path / "old_iperf.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE iperf_intervals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                interval_center_time TEXT
            )
            """
        )

    IperfResultStore(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {item[1] for item in conn.execute("PRAGMA table_info(iperf_intervals)")}
    assert {
        "device_aligned_time",
        "device_interval_center_time",
        "clock_offset_ms",
        "offset_source",
        "time_source",
        "source_event_key",
    } <= columns
