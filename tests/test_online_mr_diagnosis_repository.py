from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from netconsole.models.ap_identity_index import ApIdentityBatchResult, ApIdentityMatch
from netconsole.repositories.online_mr_diagnosis_repository import OnlineMrDiagnosisRepository
from netconsole.services.ap_identity.normalizers import normalize_mac_key
from netconsole.services.rail_transit.online_mr_identity_remap_service import OnlineMrIdentityRemapService


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
    business_tables = {
        "main_link_samples",
        "channel_busy_records",
        "radio_statistics_samples",
        "interface_rate_samples",
        "time_sync_samples",
        "switch_history_events",
        "switch_realtime_events",
        "iperf_runs",
        "iperf_intervals",
    }
    forbidden = {
        "raw_file",
        "source_file",
        "source_path",
        "relative_file",
        "relative_path",
        "raw_path",
        "raw_line",
        "raw_line_start",
        "raw_line_end",
        "line_number",
        "log_file",
    }
    with sqlite3.connect(db_path) as conn:
        for table in business_tables:
            columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
            assert columns.isdisjoint(forbidden), table


def test_online_mr_diagnosis_repository_additively_upgrades_main_link_identity_columns(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "session" / "parsed" / "online_diagnosis.sqlite"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE main_link_samples (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                collector_time TEXT,
                link_state TEXT,
                peer_mac TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO main_link_samples (session_id, collector_time, link_state, peer_mac) VALUES (?, ?, ?, ?)",
            ("session-1", "2026-07-19 10:00:00.000", "ACTIVE", "30f5-277a-169f"),
        )

    OnlineMrDiagnosisRepository(db_path).initialize()

    with sqlite3.connect(db_path) as conn:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(main_link_samples)")}
        count = conn.execute("SELECT COUNT(*) FROM main_link_samples").fetchone()[0]
        schema_version = conn.execute("SELECT value FROM online_schema_meta WHERE key = 'schema_version'").fetchone()[0]

    assert {
        "peer_ap_mac",
        "canonical_ap_mac",
        "peer_radio_mac",
        "identity_status",
        "identity_source",
        "identity_reason",
        "identity_match_rule",
        "identity_match_confidence",
    }.issubset(columns)
    assert count == 1
    assert schema_version == "online_mr_business_tables_v12_identity_channel_busy"


def test_online_mr_identity_remap_batches_all_fact_endpoints_and_preserves_facts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "parsed" / "online_diagnosis.sqlite"
    repository = OnlineMrDiagnosisRepository(db_path)
    repository.initialize()
    session_id = "session-1"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO main_link_samples (
                session_id, collector_time, link_state, peer_name, peer_mac,
                peer_mac_normalized, mr_rssi, bssid, mesh_interface, online_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, "2026-07-19 10:00:00.000", "ACTIVE", "AP-A", "0200-0000-0001", "020000000001", -42, "", "WLAN-MeshLink1", ""),
        )
        conn.execute(
            """
            INSERT INTO switch_history_events (
                session_id, event_time_device, event_time_local,
                old_peer_name, old_peer_mac, new_peer_name, new_peer_mac,
                old_rssi, new_rssi
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, "2026-07-19 10:00:01", "2026-07-19 10:00:01", "AP-A", "020000000001", "AP-B", "020000000002", -45, -40),
        )
        conn.execute(
            """
            INSERT INTO switch_realtime_events (
                session_id, device_time, old_peer_name, old_peer_mac,
                new_peer_name, new_peer_mac, old_rssi, new_rssi
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, "2026-07-19 10:00:02", "AP-B", "020000000002", "AP-C", "020000000003", -41, -39),
        )

    class QueryService:
        def __init__(self) -> None:
            self.calls: list[tuple[list[object], str | None]] = []
            self.revision = 80

        def resolve_peer_macs(self, values, *, ap_role=None):
            self.calls.append((list(values), ap_role))
            keys = tuple(dict.fromkeys(key for value in values if (key := normalize_mac_key(value))))
            matches = {
                key: ApIdentityMatch(
                    status="matched" if key != "020000000002" else "ambiguous",
                    identity_revision=self.revision,
                    query_mac=key,
                    matched_entity_id=f"entity-{key}" if key != "020000000002" else "",
                    effective_ap_name=f"AP-{key[-2:]}",
                    effective_ap_mac="020000000000",
                    station="鼓楼站",
                    section="鼓楼-东门口",
                    matched_alias_type="ac_radio_mac",
                    matched_source="ac_runtime",
                    match_rule="ac_radio_mac",
                    match_confidence=100,
                    radio_id=1,
                    unresolved_reason="duplicate_exact_alias" if key == "020000000002" else "",
                )
                for key in keys
            }
            return ApIdentityBatchResult(
                revision=self.revision,
                index_status="ready",
                requested_count=len(values),
                normalized_count=len(keys),
                distinct_count=len(keys),
                matched_count=sum(match.status == "matched" for match in matches.values()),
                unresolved_count=sum(match.status == "unresolved" for match in matches.values()),
                ambiguous_count=sum(match.status == "ambiguous" for match in matches.values()),
                invalid_count=sum(normalize_mac_key(value) is None for value in values),
                matches=matches,
            )

    query = QueryService()
    before = repository.identity_fact_fingerprint(session_id)
    result = OnlineMrIdentityRemapService(repository, query).remap(session_id)  # type: ignore[arg-type]
    after = repository.identity_fact_fingerprint(session_id)

    assert len(query.calls) == 1
    assert query.calls[0][1] == "trackside"
    assert result.revision == 80
    assert result.mapping_status == "partial"
    assert result.fact_fingerprint_before == before == after == result.fact_fingerprint_after
    assert result.updated_rows == 3
    with sqlite3.connect(db_path) as conn:
        main = conn.execute(
            "SELECT identity_entity_id, identity_revision, identity_status, matched_alias_type, belong_station FROM main_link_samples"
        ).fetchone()
        history = conn.execute(
            "SELECT old_identity_status, old_identity_revision, new_identity_status, new_identity_revision FROM switch_history_events"
        ).fetchone()
        realtime = conn.execute(
            "SELECT old_identity_status, old_identity_revision, new_identity_status, new_identity_revision FROM switch_realtime_events"
        ).fetchone()
        metadata = conn.execute(
            "SELECT identity_index_revision, identity_mapping_status, identity_distinct_count, identity_ambiguous_count FROM online_identity_metadata"
        ).fetchone()
    assert main == ("entity-020000000001", 80, "matched", "ac_radio_mac", "鼓楼站")
    assert history == ("matched", 80, "ambiguous", 80)
    assert realtime == ("ambiguous", 80, "matched", 80)
    assert metadata == (80, "partial", 3, 1)

    query.revision = 81
    second = OnlineMrIdentityRemapService(repository, query).remap(session_id)  # type: ignore[arg-type]
    assert len(query.calls) == 2
    assert second.revision == 81
    assert second.fact_fingerprint_before == before == second.fact_fingerprint_after


def test_online_mr_identity_remap_skips_empty_switch_endpoint_and_persists_null_location(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "parsed" / "online_diagnosis.sqlite"
    repository = OnlineMrDiagnosisRepository(db_path)
    repository.initialize()
    session_id = "session-empty-endpoint"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO switch_history_events (
                session_id, event_time_device, old_peer_name, old_peer_mac,
                new_peer_name, new_peer_mac
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, "2026-07-19 10:00:00", "", "", "bc5a-3457-61e0", "bc5a-3457-61ff"),
        )

    class QueryService:
        def resolve_peer_macs(self, values, *, ap_role=None):
            assert list(values) == ["bc5a345761ff"]
            match = ApIdentityMatch(
                status="matched",
                identity_revision=82,
                query_mac="bc5a345761ff",
                matched_entity_id="entity-61e0",
                effective_ap_name="bc5a-3457-61e0",
                effective_ap_mac="bc5a345761e0",
                matched_alias_type="h3c_r2_derived",
                matched_source="ac_runtime",
                match_rule="h3c_physical_mac_to_r2_exact_v1",
                match_confidence=95,
            )
            return ApIdentityBatchResult(
                revision=82,
                index_status="ready",
                requested_count=1,
                normalized_count=1,
                distinct_count=1,
                matched_count=1,
                unresolved_count=0,
                ambiguous_count=0,
                invalid_count=0,
                matches={"bc5a345761ff": match},
            )

    result = OnlineMrIdentityRemapService(repository, QueryService()).remap(session_id)  # type: ignore[arg-type]

    assert result.invalid_count == 0
    assert result.unresolved_count == 0
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT old_identity_status, old_belong_station, new_identity_status, "
            "new_matched_ap_name, new_belong_station FROM switch_history_events"
        ).fetchone()
    assert row == ("empty", None, "matched", "bc5a-3457-61e0", None)


def test_online_mr_identity_remap_rejects_zero_matched_writeback_and_rolls_back(
    tmp_path: Path,
) -> None:
    repository = OnlineMrDiagnosisRepository(tmp_path / "parsed" / "online_diagnosis.sqlite")
    repository.initialize()
    fingerprint = repository.identity_fact_fingerprint("session-1")
    with pytest.raises(RuntimeError, match="matched"):
        repository.apply_identity_projection(
            "session-1",
            {"main_link_samples": [], "switch_history_events": [], "switch_realtime_events": []},
            {
                "identity_index_revision": 90,
                "identity_index_status": "ready",
                "identity_mapping_status": "mapped",
                "identity_matched_count": 1,
            },
            expected_fact_fingerprint=fingerprint,
            matched_updated_rows=0,
        )
    assert repository.identity_metadata("session-1") == {}


def test_online_mr_identity_remap_batches_50000_facts_with_200_distinct_macs(
    tmp_path: Path,
) -> None:
    repository = OnlineMrDiagnosisRepository(
        tmp_path / "parsed" / "online_diagnosis.sqlite"
    )
    repository.initialize()
    session_id = "session-scale"
    macs = [f"02000000{index:04x}" for index in range(200)]
    with sqlite3.connect(repository.db_path) as conn:
        conn.executemany(
            """
            INSERT INTO main_link_samples (
                session_id, collector_time, link_state, peer_name,
                peer_mac, peer_mac_normalized, mr_rssi
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    f"2026-07-19 10:{index % 60:02d}:{index % 60:02d}.000",
                    "ACTIVE",
                    f"AP-{index % 200}",
                    macs[index % 200],
                    macs[index % 200],
                    -40,
                )
                for index in range(50_000)
            ],
        )

    class QueryService:
        def __init__(self) -> None:
            self.calls: list[tuple[list[object], str | None]] = []

        def resolve_peer_macs(self, values, *, ap_role=None):
            self.calls.append((list(values), ap_role))
            keys = tuple(
                dict.fromkeys(
                    key for value in values if (key := normalize_mac_key(value))
                )
            )
            matches = {
                key: ApIdentityMatch(
                    status="matched",
                    identity_revision=101,
                    query_mac=key,
                    matched_entity_id=f"entity-{key}",
                    effective_ap_name=f"AP-{key[-4:]}",
                    effective_ap_mac=key,
                    station="站点A",
                    matched_alias_type="ac_radio_mac",
                    matched_source="ac_runtime",
                    match_rule="ac_radio_mac",
                    match_confidence=100,
                )
                for key in keys
            }
            return ApIdentityBatchResult(
                revision=101,
                index_status="ready",
                requested_count=len(values),
                normalized_count=len(values),
                distinct_count=len(keys),
                matched_count=len(keys),
                unresolved_count=0,
                ambiguous_count=0,
                invalid_count=0,
                matches=matches,
            )

    query = QueryService()
    result = OnlineMrIdentityRemapService(repository, query).remap(session_id)  # type: ignore[arg-type]

    assert len(query.calls) == 1
    assert len(query.calls[0][0]) == 200
    assert query.calls[0][1] == "trackside"
    assert result.requested_count == 200
    assert result.distinct_count == 200
    assert result.updated_rows == 50_000
    assert result.fact_fingerprint_before == result.fact_fingerprint_after
    with sqlite3.connect(repository.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM main_link_samples WHERE identity_revision = 101"
        ).fetchone()[0] == 50_000


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
                "111122223333",
                "111122223333",
                "11112222333f",
                "matched",
                "ac_runtime",
                "",
                "ac_radio_mac",
                100,
                "",
                "WLAN-MeshLink1",
                "站点A",
                "区间A",
                "station",
                "fixture",
                "00h 01m 00s",
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


def test_online_mr_diagnosis_repository_reads_bounded_identity_shadow_rows(
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
                f"2026-07-19 10:00:0{index}.000",
                "",
                "",
                "collector_prefix",
                1,
                "ACTIVE",
                f"AP-{index}",
                f"1111-2222-333{index}",
                f"1111-2222-333{index}",
                f"AP-{index}",
                -40 - index,
                f"11112222333{index}",
                f"11112222333{index}",
                f"11112222333{index}",
                "matched",
                "ac_runtime",
                "",
                "ac_radio_mac",
                100,
                "",
                "WLAN-MeshLink1",
                "站点A",
                "区间A",
                "station",
                "fixture",
                "",
            )
            for index in range(3)
        ],
    )

    rows = repository.load_identity_shadow_rows(limit=2)

    assert len(rows) == 2
    assert set(rows[0]) == {
        "session_id",
        "radio",
        "peer_name",
        "peer_mac",
        "peer_mac_normalized",
        "resolved_peer_name",
        "peer_ap_mac",
        "canonical_ap_mac",
        "peer_radio_mac",
        "identity_status",
        "identity_source",
        "identity_reason",
        "identity_match_rule",
        "identity_match_confidence",
        "bssid",
        "mesh_interface",
        "belong_station",
        "belong_section",
        "belong_type",
        "belonging_source",
    }


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
            "SELECT status, command_json FROM iperf_runs"
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
        run_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(iperf_runs)")
        }
        indexes = {
            str(row[1]) for row in conn.execute("PRAGMA index_list(iperf_intervals)")
        }

    assert journal_mode == "wal"
    assert run == (
        "PARSED",
        '["iperf3", "parsed"]',
    )
    assert interval == (
        "session-1",
        8.0,
        500.0,
        "last_sample",
        "mr_device_clock_aligned",
    )
    assert "source_event_key" in columns
    assert {"raw_line", "raw_file"}.isdisjoint(columns)
    assert {"log_file", "raw_file"}.isdisjoint(run_columns)
    assert {
        "idx_iperf_intervals_time",
        "idx_iperf_intervals_run",
        "idx_iperf_intervals_source_event",
    }.issubset(indexes)
