from __future__ import annotations

import hashlib
from pathlib import Path

from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from tests.mesh_analysis_test_support import EmptyBaseQuery, EmptyOnlineQuery, create_mesh_analysis_fixture


def _fingerprint(path: Path) -> tuple[int, str]:
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def test_reads_persisted_mesh_results_without_modifying_sources(tmp_path: Path) -> None:
    paths, session_id, detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery(), online_mr_query=EmptyOnlineQuery())  # type: ignore[arg-type]
    protected = [detail, raw, report]
    before = [_fingerprint(path) for path in protected]

    summary = service.get_summary("demo")
    sessions = service.list_analysis_sessions("demo")
    links = service.list_link_details("demo", session_id, page_size=2)
    switches = service.list_switch_events("demo", session_id)
    rssi = service.get_rssi_statistics("demo", session_id, max_points=10)
    busy = service.get_channel_busy("demo", session_id, max_points=10)
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
    assert anomalies.total >= 4
    assert before == [_fingerprint(path) for path in protected]


def test_link_pagination_and_existing_artifact_metadata(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery(), online_mr_query=EmptyOnlineQuery())  # type: ignore[arg-type]

    page = service.list_link_details("demo", session_id, page=2, page_size=2)
    artifacts = service.list_report_artifacts("demo", session_id)

    assert page.total == 4
    assert len(page.items) == 2
    assert {item.artifact_type for item in artifacts} == {"raw_mesh_log", "analysis_report"}
    assert all(":" not in item.name for item in artifacts)
