from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.job_center.job_registry import registered_task_types
from tests.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture


def _fingerprint(path: Path) -> tuple[int, str]:
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def test_reads_persisted_mesh_results_without_modifying_sources(tmp_path: Path) -> None:
    paths, session_id, detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    protected = [detail, raw, report]
    before = [_fingerprint(path) for path in protected]

    summary = service.get_summary("demo")
    sessions = service.list_analysis_sessions("demo")
    links = service.list_link_details("demo", session_id, page_size=2)
    switches = service.list_switch_events("demo", session_id)
    rssi = service.get_rssi_statistics("demo", session_id, max_points=10)
    busy = service.get_channel_busy("demo", session_id, max_points=10)
    rates = service.get_rate_series("demo", session_id, max_points=10)
    counters = service.get_counter_deltas("demo", session_id, max_points=10)
    anomalies = service.list_anomalies("demo", session_id)
    location_snapshot = service.ap_location_snapshot("demo")

    assert summary.active_link_count == 3
    assert summary.standby_link_count == 1
    assert summary.short_link_count == 3
    assert summary.pingpong_count >= 1
    assert sessions.total == 1
    assert links.total == 4
    assert links.items[0].peer_ap_mac == "000000000010"
    assert links.items[0].peer_radio_mac == "00000000001f"
    assert links.items[0].local_rssi_db == 42
    assert links.items[0].peer_rssi_db == 45
    assert links.items[0].local_noise_dbm == -95
    assert links.items[0].local_signal_dbm == -53
    assert links.items[0].local_tx_busy == 2
    assert links.items[0].peer_rx_busy == 76
    assert links.items[0].source_line_number == 1
    assert not hasattr(links.items[0], "belong_source")
    assert switches.total == 2
    assert switches.items[0].after_rssi is None
    assert rssi.statistics.min_rssi == 42
    assert rssi.statistics.missing_sample_count == 1
    assert any(point.value is None for point in rssi.points)
    assert busy.items[0].tx_busy == 2
    assert busy.items[0].rx_busy == 78
    assert busy.items[0].ctl_busy is None
    assert rates.total == 4
    assert rates.items[1].local_rate_raw == 110
    assert rates.items[1].peer_rate_raw == 95
    assert counters.total == 2
    assert counters.items[0].local_retry_delta == 3
    assert counters.items[0].peer_retry_delta == 0
    assert counters.items[0].local_error_delta == 1
    assert counters.items[0].peer_error_delta == 2
    assert counters.items[1].local_retry_delta is None
    assert counters.items[1].peer_retry_delta == 5
    assert counters.items[1].local_error_delta == 0
    assert counters.items[1].peer_error_delta is None
    assert anomalies.total >= 4
    assert location_snapshot.to_serializable() == []
    assert before == [_fingerprint(path) for path in protected]


def test_link_pagination_and_existing_artifact_metadata(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    page = service.list_link_details("demo", session_id, page=2, page_size=2)
    large_page = service.list_link_details("demo", session_id, page_size=1_000)
    artifacts = service.list_report_artifacts("demo", session_id)

    assert page.total == 4
    assert large_page.page_size == 1_000
    assert len(page.items) == 2
    assert page.items[0].timestamp == page.items[1].timestamp
    assert page.items[0].timestamp_tag == page.items[1].timestamp_tag
    assert page.items[0].sample_group_index == page.items[1].sample_group_index
    assert {item.artifact_type for item in artifacts} == {"raw_mesh_log", "analysis_report"}
    assert all(":" not in item.name for item in artifacts)


def test_legacy_missing_diagnosis_table_keeps_summary_available(tmp_path: Path) -> None:
    paths, _session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("DROP TABLE diagnosis_events")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    summary = service.get_summary("demo")
    sessions = service.list_analysis_sessions("demo")

    assert summary.session_count == 1
    assert summary.link_record_count == 4
    assert summary.rssi_anomaly_count is None
    assert sessions.items[0].parsed_status == "legacy"
    assert "diagnosis" in sessions.items[0].missing_capabilities


def test_legacy_missing_active_segments_keeps_session_list_available(tmp_path: Path) -> None:
    paths, _session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("DROP TABLE active_segments")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    sessions = service.list_analysis_sessions("demo")

    assert sessions.total == 1
    assert sessions.items[0].link_record_count == 4
    assert sessions.items[0].parsed_status == "legacy"
    assert "timeline" in sessions.items[0].missing_capabilities


def test_corrupt_detail_database_isolated_from_healthy_session(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    corrupt = detail.with_name("corrupt.mesh.sqlite")
    corrupt.write_bytes(b"not sqlite")
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        row = conn.execute("SELECT * FROM source_files WHERE id = 1").fetchone()
        placeholders = ",".join("?" for _ in row)
        values = list(row)
        values[0] = 2
        values[4] = str(corrupt)
        values[8] = "corrupt.log"
        values[9] = "corrupt-sha"
        conn.execute(f"INSERT INTO source_files VALUES ({placeholders})", values)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    sessions = service.list_analysis_sessions("demo", page_size=10)
    healthy = next(item for item in sessions.items if item.session_id == session_id)
    broken = next(item for item in sessions.items if item.session_id.endswith(":2"))

    assert sessions.total == 2
    assert healthy.link_record_count == 4
    assert broken.parsed_status == "unreadable"
    assert broken.warning_count > 0


def test_relocated_detail_path_uses_current_parsed_file_without_writing(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.execute("UPDATE source_files SET parsed_db_path = ? WHERE id = 1", (f"Z:/old-data/{detail.name}",))
    before = _fingerprint(detail)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    result = service.get_analysis_session("demo", session_id)

    assert any(warning.code == "parsed_path_relocated" for warning in result.warnings)
    assert result.session.link_record_count == 4
    assert _fingerprint(detail) == before


def test_missing_relocated_detail_query_does_not_create_database(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.execute("UPDATE source_files SET parsed_db_path = 'Z:/old-data/missing.mesh.sqlite' WHERE id = 1")
    missing = paths.mesh_mr_parsed_dir("demo", "列车01-MR-CT") / "missing.mesh.sqlite"
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    sessions = service.list_analysis_sessions("demo")

    assert sessions.items[0].parsed_status == "missing"
    assert not missing.exists()


def test_mesh_schema_rebuild_is_registered_in_existing_job_center() -> None:
    assert "mesh_schema_rebuild" in registered_task_types()


def test_active_build_order_uses_repository_result_and_snapshot(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    snapshot = '{"main_link_switch_time_ms":4000,"short_link_tolerance_ms":100}'
    with sqlite3.connect(paths.mesh_mr_db_path("demo", "列车01-MR-CT")) as conn:
        conn.execute("UPDATE source_files SET analysis_params_json = ? WHERE id = 1", (snapshot,))
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    repository = MeshMrRepository(detail, read_only=True)

    repository_rows = repository.query_active_link_build_order(source_file_id=1, analysis_params=snapshot)
    page = service.list_active_build_order("demo", session_id, sort_order="asc")

    assert page.total == len(repository_rows) == 3
    assert [item.anchor_link_id for item in page.items] == [row["anchor_link_id"] for row in repository_rows]
    assert page.items[1].pingpong_type == "AP乒乓切换异常"
    assert page.items[1].is_pingpong_abnormal is True
    assert page.items[0].main_link_switch_time_ms == 4000
    assert page.items[0].short_threshold_seconds == 3.9


def test_analysis_session_exposes_all_real_radios_for_chart_filters(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("UPDATE active_points SET radio = 2 WHERE id = 3")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    result = service.get_analysis_session("demo", session_id)

    assert result.available_radios == [1, 2]


def test_active_chart_keeps_tagged_gap_and_standby_context_isolated(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("INSERT INTO samples VALUES (4, 1, 1, '2026-07-14 10:00:03.000', '')")
        conn.execute("INSERT INTO samples VALUES (5, 1, 1, '2026-07-14 10:00:03.000', '(2)')")
        common_columns = """
            id, sample_id, source_file_id, record_seq, sample_time, radio, link_state,
            peer_mac_raw, peer_mac_normalized, peer_mac, peer_ap_name, peer_ap_mac,
            peer_site, peer_radio_label, duration_seconds, local_rssi_db,
            local_tx_busy, local_rx_busy, peer_match_rule, peer_resolve_source,
            peer_radio_mac, timestamp_tag, session_id, local_rate_raw, peer_rate_raw,
            local_retry, peer_retry, local_err, peer_err, source_line_number,
            peer_radio, duration_text, link_count, peer_rssi_db,
            peer_tx_busy, peer_rx_busy, local_signal_dbm, peer_signal_dbm
        """
        placeholders = ",".join("?" for _ in range(38))
        conn.execute(
            f"INSERT INTO mesh_links ({common_columns}) VALUES ({placeholders})",
            (5, 4, 1, 5, "2026-07-14 10:00:03.000", 1, "STANDBY", "0000-0000-004f", "00000000004f", "00000000004f", "AP-04", "000000000040", "区间B-C", "radio2", 1, 35, 5, 6, "exact", "mapping", "00000000004f", "", "session-gap", 70, 65, 1, 2, 0, 0, 5, "radio2", "1s", 1, 37, 2, 3, -60, -58),
        )
        conn.execute(
            f"INSERT INTO mesh_links ({common_columns}) VALUES ({placeholders})",
            (6, 5, 1, 6, "2026-07-14 10:00:03.000", 1, "ACTIVE", "0000-0000-005f", "00000000005f", "00000000005f", "AP-05", "000000000050", "车站C", "radio2", 1, 44, 2, 20, "exact", "mapping", "00000000005f", "", "session-tag", 120, 110, 4, 5, 0, 0, 6, "radio2", "1s", 1, 46, 3, 18, -50, -48),
        )
        conn.execute(
            f"INSERT INTO mesh_links ({common_columns}) VALUES ({placeholders})",
            (7, 5, 1, 7, "2026-07-14 10:00:03.000", 1, "STANDBY", "0000-0000-006f", "00000000006f", "00000000006f", "AP-06", "000000000060", "车站D", "radio2", 1, 38, 1, 4, "exact", "mapping", "00000000006f", "", "session-tag", 80, 75, 2, 3, 0, 0, 7, "radio2", "1s", 1, 40, 1, 3, -56, -54),
        )
    before = _fingerprint(detail)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart(
        "demo",
        session_id,
        radio=1,
        time_from="2026-07-14 10:00:03.000",
        time_to="2026-07-14 10:00:03.000",
        max_points=10,
    )

    assert chart.total_points == 2
    gap = next(item for item in chart.points if item.timestamp_tag == "")
    tagged = next(item for item in chart.points if item.timestamp_tag == "(2)")
    assert gap.link_state == ""
    assert gap.local_rssi is None
    assert gap.is_anomaly is True
    assert gap.backups == []
    assert tagged.link_state == "ACTIVE"
    assert tagged.local_rssi == 44
    assert [item.link_id for item in tagged.backups] == [7]
    assert all(item.source_file_id == 1 and item.timestamp_tag == "(2)" for item in tagged.backups)
    assert before == _fingerprint(detail)


def test_index_source_id_is_mapped_to_single_source_detail_database(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    mr_id = session_id.split(":", 1)[0]
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.execute("UPDATE source_files SET id = 2")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    mismatched_session_id = f"{mr_id}:2"

    context = service._context("demo", mismatched_session_id)
    build_order = service.list_active_build_order("demo", mismatched_session_id)
    chart = service.get_active_path_chart("demo", mismatched_session_id, max_points=10)

    assert context.source_id == 2
    assert context.detail_source_id == 1
    assert build_order.total == 3
    assert chart.total_points == 3
    assert {item.source_file_id for item in build_order.items} == {2}
    assert {item.source_file_id for item in chart.points} == {2}
    assert {
        backup.source_file_id
        for item in chart.points
        for backup in item.backups
    } <= {2}


def test_peer_chart_can_return_all_visits_with_explicit_gaps(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    builds = service.list_active_build_order("demo", session_id, sort_order="asc", page_size=100).items
    first = builds[0]

    chart = service.get_peer_segment_chart(
        "demo",
        session_id,
        anchor_link_id=int(first.anchor_link_id or 0),
        max_points=100,
        all_visits=True,
    )

    matching_sequences = {
        item.sequence
        for item in builds
        if item.physical_ap_key == first.physical_ap_key and item.local_radio == first.local_radio
    }
    assert matching_sequences <= {point.segment_sequence for point in chart.points}
    assert any(point.gap_before for point in chart.points[1:])


def test_chart_segment_index_finds_the_latest_matching_visit(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    segments = [
        {
            "source_file_id": 1,
            "radio": 1,
            "active_peer_mac": "0000-0000-0010",
            "build_start_time": "2026-07-20 10:00:00.000",
            "build_end_time": "2026-07-20 10:00:05.000",
            "sequence": 1,
        },
        {
            "source_file_id": 1,
            "radio": 1,
            "active_peer_mac": "0000-0000-0010",
            "build_start_time": "2026-07-20 11:00:00.000",
            "build_end_time": "2026-07-20 11:00:05.000",
            "sequence": 2,
        },
    ]

    index = service._chart_segment_index(segments)

    assert service._chart_segment(
        index,
        {
            "source_file_id": 1,
            "radio": 1,
            "peer_mac_normalized": "000000000010",
            "sample_time": "2026-07-20 11:00:03.000",
        },
    ) == segments[1]
    assert service._chart_segment(
        index,
        {
            "source_file_id": 1,
            "radio": 1,
            "peer_mac_normalized": "000000000010",
            "sample_time": "2026-07-20 10:30:00.000",
        },
    ) is None
