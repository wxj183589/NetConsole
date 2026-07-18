from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from netconsole.repositories.online_mr_diagnosis_repository import OnlineMrDiagnosisRepository


def test_online_mr_diagnosis_repository_initializes_existing_schema_and_indexes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "session" / "parsed" / "online_diagnosis.sqlite"
    repository = OnlineMrDiagnosisRepository(db_path)

    repository.initialize()
    repository.initialize()

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        indexes = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }

    assert {
        "main_link_samples",
        "channel_busy_records",
        "radio_statistics_samples",
        "interface_rate_samples",
        "time_sync_samples",
        "fping_samples",
        "fping_1s_summary",
        "iperf_runs",
        "iperf_intervals",
        "online_parse_issues",
        "analysis_events",
        "online_parse_metadata",
        "switch_history_events",
        "switch_realtime_events",
        "active_segments",
        "active_segment_metrics",
    }.issubset(tables)
    assert {
        "idx_main_link_samples_time",
        "idx_main_link_samples_active",
        "idx_channel_busy_records_time",
        "idx_interface_rate_samples_time",
        "idx_time_sync_samples_collector_time",
        "idx_fping_samples_time",
        "idx_fping_samples_device_time",
        "idx_fping_1s_summary_time",
        "idx_fping_1s_summary_device_time",
        "idx_analysis_events_time",
        "idx_switch_history_events_time",
        "idx_switch_realtime_events_time",
    }.issubset(indexes)


def test_online_mr_diagnosis_repository_preserves_write_query_and_reset_contract(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "parsed" / "online_diagnosis.sqlite"
    repository = OnlineMrDiagnosisRepository(db_path)
    repository.initialize()
    repository.insert_rows(
        "main_link_samples",
        [
            (
                "session-1",
                "2026-07-19 10:00:00.000",
                "2026-07-19 10:00:00.000",
                "10:00:00 BeiJing Sun 07/19/2026",
                "device_clock",
                1,
                "ACTIVE",
                "AP-1",
                "1111-2222-3333",
                "1111-2222-3333",
                "AP-1",
                -42,
                "",
                "WLAN-MeshLink1",
                "站点A",
                "区间A",
                "station",
                "fixture",
                "00h 01m 00s",
                "raw/mesh_link_raw.log",
                0,
                100,
            )
        ],
    )
    repository.replace_parse_metadata(
        (
            "session-1",
            "2026-07-19 10:01:00.000",
            "parser-v1",
            "fingerprint-1",
            '{"mesh_samples": 1}',
            "OK",
            "",
        )
    )
    switch_history_row = (
        "session-1",
        "2026-07-19 10:00:01.000",
        None,
        "2026-07-19 10:00:01",
        "2026-07-19 10:00:01",
        "device_clock",
        1,
        "AP-1",
        "1111-2222-3333",
        -42,
        "站点A",
        "区间A",
        "AP-2",
        "4444-5555-6666",
        -40,
        "站点B",
        "区间A",
        2,
        1,
        2,
        "主动切换",
        "00h 01m 00s",
        "raw/switch_history_latest.log",
        0,
        100,
    )
    repository.insert_rows("switch_history_events", [switch_history_row])
    repository.insert_rows("switch_history_events", [switch_history_row])

    metadata = repository.cached_parse_metadata(
        "session-1",
        "parser-v1",
        "fingerprint-1",
    )
    health = repository.parsed_health_snapshot("session-1")
    main_link = repository.main_link_metadata("session-1")

    assert metadata == ('{"mesh_samples": 1}', "OK")
    assert health == {
        "required_tables_present": True,
        "mesh_sample_count": 1,
        "mesh_link_count": 1,
        "active_link_count": 1,
        "distinct_time_count": 1,
        "has_bad_segment": False,
    }
    assert main_link == {
        "main_link_sample_count": 1,
        "active_link_count": 1,
        "analysis_start": "2026-07-19 10:00:00.000",
        "analysis_end": "2026-07-19 10:00:00.000",
    }
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM switch_history_events").fetchone()[0] == 1

    repository.reset_parsed_tables()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM switch_history_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM main_link_samples").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM online_parse_metadata").fetchone()[0] == 0


def test_online_mr_diagnosis_repository_rolls_back_fping_batch_on_error(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "parsed" / "online_diagnosis.sqlite"
    repository = OnlineMrDiagnosisRepository(db_path)
    repository.initialize()
    sample = (
        "session-1",
        "2026-07-19 10:00:00.000",
        "2026-07-19 10:00:00.000",
        None,
        None,
        "none",
        "local_tool",
        "10.0.0.1",
        "",
        1,
        1,
        1.2,
        0.0,
        "OK",
    )

    with pytest.raises(sqlite3.ProgrammingError):
        repository.insert_fping_sampling_rows([sample], [("invalid",)])

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fping_samples").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM fping_1s_summary").fetchone()[0] == 0


def test_online_mr_diagnosis_repository_preserves_iperf_wal_and_run_contract(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "parsed" / "online_diagnosis.sqlite"
    raw_path = tmp_path / "raw" / "iperf_client_raw.log"
    repository = OnlineMrDiagnosisRepository(db_path)
    repository.initialize()
    repository.start_iperf_run(
        "parsed_session-1",
        mode="client",
        command=["iperf3", "parsed"],
        log_file=raw_path,
        started_at=datetime(2026, 7, 19, 10, 0, 0),
        session_id="session-1",
        device_id=7,
    )
    repository.append_iperf_interval(
        "parsed_session-1",
        {
            "collector_time": "2026-07-19 10:00:00.500",
            "interval_start_sec": 0.0,
            "interval_end_sec": 1.0,
            "interval_center_time": "2026-07-19 10:00:00.500",
            "device_aligned_time": "2026-07-19 10:00:01.000",
            "device_interval_center_time": "2026-07-19 10:00:01.000",
            "clock_offset_ms": 500.0,
            "offset_source": "last_sample",
            "time_source": "mr_device_clock_aligned",
            "transfer_bytes": 1024.0,
            "bitrate_mbps": 8.0,
            "retransmits": 0,
            "raw_line": "iperf interval 0.0-1.0s",
        },
        "session-1",
    )
    repository.finish_iperf_run(
        "parsed_session-1",
        "PARSED",
        ended_at=datetime(2026, 7, 19, 10, 0, 1),
    )

    with sqlite3.connect(db_path) as conn:
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        run = conn.execute(
            "SELECT status, command_json, log_file, raw_file FROM iperf_runs"
        ).fetchone()
        interval = conn.execute(
            """
            SELECT session_id, bitrate_mbps, clock_offset_ms, offset_source, time_source
            FROM iperf_intervals
            """
        ).fetchone()
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(iperf_intervals)")
        }
        indexes = {
            str(row[1]) for row in conn.execute("PRAGMA index_list(iperf_intervals)")
        }

    assert journal_mode == "wal"
    assert run == (
        "PARSED",
        '["iperf3", "parsed"]',
        str(raw_path),
        str(raw_path),
    )
    assert interval == (
        "session-1",
        8.0,
        500.0,
        "last_sample",
        "mr_device_clock_aligned",
    )
    assert "source_event_key" in columns
    assert {
        "idx_iperf_intervals_time",
        "idx_iperf_intervals_run",
        "idx_iperf_intervals_source_event",
    }.issubset(indexes)
