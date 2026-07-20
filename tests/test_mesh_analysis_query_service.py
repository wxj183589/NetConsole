from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
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

    assert summary.active_link_count == 3
    assert summary.standby_link_count == 1
    assert summary.short_link_count == 3
    assert summary.pingpong_count >= 1
    assert sessions.total == 1
    assert links.total == 4
    assert links.items[0].peer_ap_mac == "000000000010"
    assert not hasattr(links.items[0], "peer_radio_mac")
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
    assert before == [_fingerprint(path) for path in protected]


def test_link_pagination_and_existing_artifact_metadata(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    page = service.list_link_details("demo", session_id, page=2, page_size=2)
    artifacts = service.list_report_artifacts("demo", session_id)

    assert page.total == 4
    assert len(page.items) == 2
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
