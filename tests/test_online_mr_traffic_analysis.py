from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openpyxl import Workbook

from netconsole.services.online_mr_analysis_report_exporter import OnlineMrAnalysisReportExporter
from netconsole.services.online_mr_chart_builder import OnlineMrChartBuilder
from netconsole.services.online_mr.traffic_analysis import build_iperf_traffic_overview


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE iperf_runs (
            run_id TEXT PRIMARY KEY,
            protocol TEXT,
            direction TEXT,
            server_ip TEXT,
            port INTEGER,
            parallel INTEGER,
            target_bandwidth TEXT,
            status TEXT,
            started_at TEXT,
            ended_at TEXT
        );
        CREATE TABLE iperf_intervals (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            interval_start_sec REAL,
            interval_end_sec REAL,
            transfer_bytes REAL,
            bitrate_mbps REAL,
            jitter_ms REAL,
            lost_packets INTEGER,
            total_packets INTEGER,
            loss_percent REAL,
            retransmits INTEGER,
            role TEXT,
            source_event_key TEXT,
            device_interval_center_time TEXT,
            device_aligned_time TEXT,
            interval_center_time TEXT,
            collector_time TEXT
        );
        """
    )
    return conn


def _insert_run(conn: sqlite3.Connection, run_id: str, protocol: str, direction: str) -> None:
    conn.execute(
        "INSERT INTO iperf_runs(run_id, protocol, direction, server_ip, port, parallel, status, started_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, protocol, direction, "10.0.0.2", 5201, 1, "COMPLETED", "2026-07-21 15:00:00", "2026-07-21 15:00:03"),
    )


def _insert_interval(
    conn: sqlite3.Connection,
    run_id: str,
    start: float,
    end: float,
    rate: float,
    *,
    transfer: float | None = None,
    jitter: float | None = None,
    lost: int | None = None,
    total: int | None = None,
    retransmits: int | None = None,
    role: str = "interval",
    timestamp: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO iperf_intervals(
            run_id, interval_start_sec, interval_end_sec, transfer_bytes, bitrate_mbps,
            jitter_ms, lost_packets, total_packets, loss_percent, retransmits, role,
            interval_center_time, collector_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            start,
            end,
            transfer,
            rate,
            jitter,
            lost,
            total,
            (lost * 100.0 / total) if lost is not None and total else None,
            retransmits,
            role,
            timestamp,
            timestamp,
        ),
    )


def test_udp_stats_are_time_weighted_and_summary_rows_are_not_double_counted() -> None:
    conn = _database()
    _insert_run(conn, "udp-1", "UDP", "upload")
    _insert_interval(conn, "udp-1", 0, 1, 2.0, jitter=1.0, lost=5, total=100, timestamp="2026-07-21 15:00:00")
    _insert_interval(conn, "udp-1", 1, 3, 4.0, jitter=3.0, lost=10, total=200, timestamp="2026-07-21 15:00:01")
    _insert_interval(conn, "udp-1", 0, 3, 3.0, transfer=300, role="sum_sent", timestamp="2026-07-21 15:00:02")
    _insert_interval(conn, "udp-1", 0, 3, 3.0, transfer=285, role="sum_received", timestamp="2026-07-21 15:00:02")
    conn.commit()

    overview = build_iperf_traffic_overview(conn)
    stats = overview["directions"][0]
    assert stats["record_count"] == 2
    assert stats["duration_seconds"] == pytest.approx(3.0)
    assert stats["average_mbps"] == pytest.approx(10 / 3)
    assert stats["minimum_mbps"] == pytest.approx(2.0)
    assert stats["maximum_mbps"] == pytest.approx(4.0)
    assert stats["sent_bytes"] == pytest.approx(300)
    assert stats["received_bytes"] == pytest.approx(285)
    assert stats["lost_packets"] == 15
    assert stats["received_packets"] == 285
    assert stats["loss_percent"] == pytest.approx(5.0)
    assert stats["average_jitter_ms"] == pytest.approx(7 / 3)
    assert stats["minimum_jitter_ms"] == pytest.approx(1.0)
    assert stats["maximum_jitter_ms"] == pytest.approx(3.0)
    assert stats["retransmits"] is None


def test_tcp_stats_keep_retransmits_but_do_not_expose_udp_metrics() -> None:
    conn = _database()
    _insert_run(conn, "tcp-1", "TCP", "download")
    _insert_interval(conn, "tcp-1", 0, 1, 8.0, transfer=1000, retransmits=2, timestamp="2026-07-21 15:00:00")
    _insert_interval(conn, "tcp-1", 1, 2, 10.0, transfer=1250, retransmits=5, timestamp="2026-07-21 15:00:01")
    _insert_interval(conn, "tcp-1", 0, 2, 9.0, transfer=2250, role="sum_sent", timestamp="2026-07-21 15:00:02")
    conn.commit()

    stats = build_iperf_traffic_overview(conn)["directions"][0]
    assert stats["protocol"] == "TCP"
    assert stats["average_mbps"] == pytest.approx(9.0)
    assert stats["sent_bytes"] == pytest.approx(2250)
    assert stats["retransmits"] == 7
    assert stats["lost_packets"] is None
    assert stats["loss_percent"] is None
    assert stats["average_jitter_ms"] is None


def test_missing_udp_packet_fields_remain_unknown_and_window_filters_samples() -> None:
    conn = _database()
    _insert_run(conn, "udp-2", "UDP", "upload")
    _insert_interval(conn, "udp-2", 0, 1, 1.0, timestamp="2026-07-21 15:00:00")
    _insert_interval(conn, "udp-2", 1, 2, 3.0, timestamp="2026-07-21 15:00:10")
    conn.commit()

    overview = build_iperf_traffic_overview(
        conn,
        start_time="2026-07-21 15:00:05",
        end_time="2026-07-21 15:00:15",
    )
    stats = overview["directions"][0]
    assert stats["record_count"] == 1
    assert stats["average_mbps"] == pytest.approx(3.0)
    assert stats["lost_packets"] is None
    assert stats["received_packets"] is None
    assert stats["loss_percent"] is None
    assert stats["average_jitter_ms"] is None


def test_multiple_runs_keep_protocol_and_direction_dimensions_separate() -> None:
    conn = _database()
    _insert_run(conn, "udp-up", "UDP", "upload")
    _insert_run(conn, "tcp-down", "TCP", "download")
    _insert_interval(conn, "udp-up", 0, 1, 2.0, lost=1, total=10, timestamp="2026-07-21 15:00:00")
    _insert_interval(conn, "tcp-down", 0, 1, 20.0, retransmits=4, timestamp="2026-07-21 15:00:01")
    conn.commit()

    overview = build_iperf_traffic_overview(conn)
    assert [(item["protocol"], item["direction"]) for item in overview["directions"]] == [("UDP", "upload"), ("TCP", "download")]
    assert overview["directions"][0]["loss_percent"] == pytest.approx(10.0)
    assert overview["directions"][1]["retransmits"] == 4
    assert overview["protocol"] == "多协议"


def test_chart_builder_and_exporter_tolerate_legacy_intervals_without_run_table_or_raw_line(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    parsed_dir = session_dir / "parsed"
    parsed_dir.mkdir(parents=True)
    db_path = parsed_dir / "online_diagnosis.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE iperf_intervals(
                id INTEGER PRIMARY KEY, run_id TEXT, interval_center_time TEXT,
                collector_time TEXT, direction TEXT, protocol TEXT,
                bitrate_mbps REAL, transfer_bytes REAL, role TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO iperf_intervals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "legacy-run", "2026-07-21 15:00:00", "2026-07-21 15:00:00", "download", "UDP", 2.5, 100, "interval"),
        )

    chart = OnlineMrChartBuilder(db_path).build_traffic_rate_series()
    assert chart.series[1].points == [("2026-07-21 15:00:00", 2.5)]
    assert chart.tooltip_rows[0]["protocol"] == "UDP"
    assert chart.tooltip_rows[0]["raw"] is None

    workbook = Workbook()
    OnlineMrAnalysisReportExporter()._append_offline_report_sheets(workbook, session_dir, db_path)
    assert "业务打流概览" in workbook.sheetnames
    overview = workbook["业务打流概览"]
    assert overview["A2"].value == "整场"
    assert overview["C2"].value == "UDP"
