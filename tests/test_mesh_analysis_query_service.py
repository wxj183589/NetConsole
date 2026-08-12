from __future__ import annotations

import hashlib
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import pytest

import netconsole.services.rail_transit.mesh_analysis_query_service as mesh_query_module
from netconsole.models.api.mesh_analysis import MeshChartPointDTO, MeshPathChartDTO
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisPayloadLimitError,
    MeshAnalysisQueryError,
    MeshAnalysisQueryService,
    MeshAnalysisTimeRangeError,
)
from netconsole.services.rail_transit.mesh_ap_location_service import MeshApLocationSnapshot
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, _active_build_order_rows_from_points
from netconsole.models.mesh_analysis_params import mesh_analysis_params_to_json
from netconsole.services.mesh_analysis_params_service import save_site_mesh_analysis_params
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.mesh_chart_payload import (
    MeshChartSelectionLimitError,
    prioritized_render_indices,
    render_indices,
)
from netconsole.services.mesh_catalog_index_service import MeshCatalogIndexService
from tests.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture


def _fingerprint(path: Path) -> tuple[int, str]:
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def _clear_mesh_chart_rows(conn: sqlite3.Connection) -> None:
    for table in ("mesh_links", "samples", "active_points", "active_segments", "switch_events"):
        conn.execute(f"DELETE FROM {table}")


def _insert_active_mesh_link(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    sample_time: str,
    radio: int,
    peer_name: str,
    peer_mac: str,
    peer_rssi: int | None,
    peer_signal: int | None = None,
    link_state: str = "ACTIVE",
    peer_radio_mac: str | None = None,
    link_count: int = 1,
) -> None:
    ap_mac = f"{int(peer_mac, 16) + 0x1000:012x}"
    conn.execute("INSERT INTO samples VALUES (?, 1, ?, ?, '')", (row_id, radio, sample_time))
    conn.execute(
        """
        INSERT INTO mesh_links (
            id, sample_id, source_file_id, record_seq, source_line_number, sample_time, radio, link_state,
            peer_mac_raw, peer_mac_normalized, peer_mac, peer_ap_name, peer_ap_mac, peer_site,
            peer_radio_label, peer_radio, duration_seconds, link_count, local_rssi_db, peer_rssi_db,
            local_tx_busy, peer_tx_busy, local_rx_busy, peer_rx_busy, peer_match_rule, peer_resolve_source,
            peer_radio_mac, timestamp_tag, session_id, local_signal_dbm, peer_signal_dbm
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '',
            'radio', 'radio', 1, ?, ?, ?, 1, 1, 1, 1, 'exact', 'mapping',
            ?, '', 'session-trackside', -50, ?)
        """,
        (
            row_id,
            row_id,
            row_id,
            row_id,
            sample_time,
            radio,
            link_state,
            peer_mac,
            peer_mac,
            peer_mac,
            peer_name,
            ap_mac,
            link_count,
            (peer_rssi or 0) - 5,
            peer_rssi,
            peer_radio_mac or peer_mac,
            peer_signal,
        ),
    )


def _active_chart_row(
    row_id: int,
    sample_time: str,
    peer_mac: str,
    *,
    local_rssi: int = 40,
    link_state: str = "ACTIVE",
    link_count: int = 1,
) -> dict[str, object]:
    return {
        "id": row_id,
        "source_file_id": 1,
        "sample_time": sample_time,
        "timestamp_tag": "",
        "radio": 1,
        "link_state": link_state,
        "link_count": link_count,
        "peer_mac_raw": peer_mac,
        "peer_mac_normalized": peer_mac,
        "peer_mac": peer_mac,
        "peer_ap_name": f"AP-{peer_mac[-2:]}",
        "peer_ap_mac": peer_mac,
        "peer_radio_mac": peer_mac,
        "local_rssi_db": local_rssi,
        "peer_rssi_db": local_rssi - 5,
    }


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
    assert summary.short_link_count == 2
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


def test_switch_event_filters_are_sql_scoped_and_do_not_require_full_build_order(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    save_site_mesh_analysis_params(
        paths,
        "demo",
        {"link_time_window": 4_000, "pingpong_return_window_ms": 1_500},
    )
    with sqlite3.connect(detail) as conn:
        conn.executemany(
            """
            INSERT INTO active_segments (
                id, radio, peer_mac, peer_mac_normalized, peer_ap_name,
                belong_station, belong_section, belong_type, start_time, end_time,
                duration_sec, sample_count, event_type, source_file_id
            ) VALUES (?, 1, ?, ?, ?, '', '', '', ?, ?, ?, 1, 'stable', 1)
            """,
            (
                (
                    2,
                    "00000000002f",
                    "00000000002f",
                    "AP-02",
                    "2026-07-14 10:00:01.000",
                    "2026-07-14 10:00:01.999",
                    1.0,
                ),
                (
                    3,
                    "00000000001f",
                    "00000000001f",
                    "AP-01",
                    "2026-07-14 10:00:02.000",
                    "2026-07-14 10:00:11.999",
                    10.0,
                ),
            ),
        )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    service._build_rows = lambda _context: (_ for _ in ()).throw(AssertionError("不得全量构造 build_rows"))  # type: ignore[method-assign]

    short = service.list_switch_events("demo", session_id, radio=1, switch_result="short")
    normal = service.list_switch_events("demo", session_id, radio=1, switch_result="normal")
    pingpong = service.list_switch_events("demo", session_id, radio=1, switch_result="pingpong")
    other_radio = service.list_switch_events("demo", session_id, radio=2)

    assert [item.event_id for item in short.items] == [1]
    assert [item.event_id for item in normal.items] == [2]
    assert [item.event_id for item in pingpong.items] == [1]
    assert other_radio.total == 0


def test_chart_payload_automatically_reduces_lod_before_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mesh_query_module, "_TARGET_CHART_PAYLOAD_BYTES", 64 * 1024)
    monkeypatch.setattr(mesh_query_module, "_MAX_CHART_PAYLOAD_BYTES", 128 * 1024)
    chart = MeshPathChartDTO(
        mode="active_path",
        points=[
            MeshChartPointDTO(
                timestamp=f"2026-07-14 10:00:{index % 60:02d}.{index:03d}",
                peer_ap_name="AP-" + ("X" * 500),
            )
            for index in range(400)
        ],
        total_points=400,
        returned_points=400,
    )

    result = MeshAnalysisQueryService._with_chart_metrics(chart, perf_counter())

    assert result.response_budget.degraded is True
    assert result.response_budget.lod_level > 0
    assert result.returned_points < 400
    assert result.payload_bytes < 128 * 1024


def test_chart_payload_reports_when_critical_floor_still_exceeds_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mesh_query_module, "_TARGET_CHART_PAYLOAD_BYTES", 1_024)
    monkeypatch.setattr(mesh_query_module, "_MAX_CHART_PAYLOAD_BYTES", 64 * 1_024)
    chart = MeshPathChartDTO(
        mode="active_path",
        points=[
            MeshChartPointDTO(
                timestamp="2026-07-14 10:00:00.000",
                peer_ap_name="AP-" + ("X" * 8_000),
                is_switch=True,
            )
        ],
        total_points=1,
        returned_points=1,
    )

    result = MeshAnalysisQueryService._with_chart_metrics(chart, perf_counter())

    assert result.payload_bytes > 1_024
    assert result.payload_bytes < 64 * 1_024
    assert result.response_budget.degraded is True
    assert any("最小保留粒度" in reason for reason in result.response_budget.degrade_reasons)


def test_trackside_repository_applies_frame_budget_at_exact_row_cap(tmp_path: Path) -> None:
    _paths, _session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for index in range(10):
            _insert_active_mesh_link(
                conn,
                row_id=index + 1,
                sample_time=f"2026-07-14 10:00:{index:02d}.000",
                radio=1,
                peer_name="AP-01",
                peer_mac="000000000001",
                peer_rssi=40 + index,
            )

    payload = MeshMrRepository(detail, read_only=True).query_trackside_link_chart_segment(
        source_file_id=1,
        radio=1,
        max_rows=10,
        max_frames=2,
        max_series=10,
    )
    segment = dict(payload["run_segment"])
    rows = list(segment["rows"])

    assert segment["source_total_rows"] == 10
    assert segment["repository_downsampled"] is True
    assert 2 <= len(rows) < 10


def test_active_chart_repository_budgets_8490_switch_events(tmp_path: Path) -> None:
    _paths, _session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    sample_times = (
        "2026-07-14 10:00:00.000",
        "2026-07-14 10:00:01.000",
        "2026-07-14 10:00:02.000",
    )
    with sqlite3.connect(detail) as conn:
        conn.execute("DELETE FROM switch_events")
        conn.executemany(
            """
            INSERT INTO switch_events (
                id, event_type, event_time, radio, previous_sample_time,
                current_sample_time, observed_window_ms, from_peer_mac,
                to_peer_mac, details_json, source_file_id
            ) VALUES (?, 'ACTIVE_SWITCH', ?, 1, ?, ?, 1000,
                      '00000000001f', '00000000002f', '{}', 1)
            """,
            (
                (
                    index + 1,
                    sample_times[index % len(sample_times)],
                    sample_times[index % len(sample_times)],
                    sample_times[(index + 1) % len(sample_times)],
                )
                for index in range(8_490)
            ),
        )

    payload = MeshMrRepository(detail, read_only=True).query_active_link_chart_segments(
        source_file_id=1,
        max_rows=10,
        max_events=200,
    )
    segment = dict(payload["run_segment"])

    assert segment["total_events"] == 8_490
    assert segment["returned_events"] <= 200
    assert len(segment["events"]) == segment["returned_events"]


def test_rssi_statistics_exclude_zero_and_report_it_separately(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("UPDATE active_points SET local_rssi_db = 0 WHERE id = 1")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    result = service.get_rssi_statistics("demo", session_id, max_points=10)

    assert result.statistics.sample_count == 1
    assert result.statistics.missing_sample_count == 1
    assert result.statistics.zero_sample_count == 1
    assert result.statistics.avg_rssi == 43
    assert result.statistics.min_rssi == 43
    assert result.statistics.max_rssi == 43


def test_active_chart_marks_short_zero_before_render_sampling(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("UPDATE active_points SET local_rssi_db = 0 WHERE id = 2")
        conn.execute("UPDATE mesh_links SET local_rssi_db = 0 WHERE id = 2")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=10)

    zero_point = next(point for point in chart.points if point.timestamp == "2026-07-14 10:00:01.000")
    assert zero_point.local_rssi is None
    assert zero_point.local_rssi_zero_run is not None
    assert zero_point.local_rssi_zero_run.state == "suppressed"
    assert zero_point.local_rssi_zero_run.duration_ms == 1_000
    assert chart.summary.suppressed_zero_sample_count == 1
    assert chart.summary.suppressed_zero_run_count == 1


def test_active_chart_bridges_only_an_isolated_multi_active_frame(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    payload = {
        "peer_segment": {"rows": []},
        "run_segment": {
            "rows": [
                _active_chart_row(1, "2026-07-24 20:49:14.104", "000000001618"),
                _active_chart_row(2, "2026-07-24 20:49:15.104", "000000001618"),
                _active_chart_row(3, "2026-07-24 20:49:15.104", "000000001620"),
                _active_chart_row(4, "2026-07-24 20:49:16.104", "000000001624"),
                _active_chart_row(
                    5,
                    "2026-07-24 20:49:17.104",
                    "000000001626",
                    link_state="STANDBY",
                ),
            ],
            "events": [],
            "estimated_interval_seconds": 1,
            "continuity_gap_seconds": 5,
        },
    }

    chart = service._chart_dto(
        "demo",
        context,
        payload,
        mode="active_path",
        max_points=10,
        time_from="",
        time_to="",
    )

    ambiguous = next(point for point in chart.points if point.timestamp == "2026-07-24 20:49:15.104")
    no_active = next(point for point in chart.points if point.timestamp == "2026-07-24 20:49:17.104")
    assert ambiguous.is_anomaly is True
    assert ambiguous.bridge_ambiguous_active is True
    assert ambiguous.local_rssi is None
    assert no_active.is_anomaly is True
    assert no_active.bridge_ambiguous_active is False


def test_active_chart_keeps_representative_points_when_key_points_fill_budget(
    tmp_path: Path,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    rows = []
    for index in range(240):
        minute, second = divmod(index, 60)
        peer_mac = (
            "0000000000a1" if index % 2 == 0 else "0000000000b1"
        ) if index < 160 else "0000000000c1"
        rows.append(
            _active_chart_row(
                index + 1,
                f"2026-07-24 20:{minute:02d}:{second:02d}.000",
                peer_mac,
                local_rssi=35 + index % 5,
            )
        )
    payload = {
        "peer_segment": {"rows": []},
        "run_segment": {
            "rows": rows,
            "events": [],
            "estimated_interval_seconds": 1,
            "continuity_gap_seconds": 5,
        },
    }

    chart = service._chart_dto(
        "demo",
        context,
        payload,
        mode="active_path",
        max_points=10,
        time_from="",
        time_to="",
    )

    assert chart.total_points == 240
    assert chart.returned_points == 10
    assert chart.downsampled is True
    assert chart.returned_points < chart.total_points
    assert chart.effective_max_points == chart.requested_max_points == 10
    assert chart.downsample_warning is not None


def test_active_chart_compresses_large_continuous_no_active_run_within_requested_budget(
    tmp_path: Path,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    start = datetime(2026, 8, 6, 8, 0, 0)
    row_count = 113_961
    rows = [
        _active_chart_row(
            index + 1,
            (start + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S.000"),
            "000000001618",
            link_state="STANDBY",
        )
        for index in range(row_count)
    ]

    started = perf_counter()
    chart = service._chart_dto(
        "demo",
        context,
        {
            "peer_segment": {"rows": []},
            "run_segment": {
                "rows": rows,
                "events": [],
                "estimated_interval_seconds": 1,
                "continuity_gap_seconds": 5,
            },
        },
        mode="active_path",
        max_points=600,
        time_from="",
        time_to="",
    )
    elapsed = perf_counter() - started

    assert chart.total_points == row_count
    assert 2 <= chart.returned_points <= chart.effective_max_points == chart.requested_max_points == 600
    assert chart.points[0].timestamp == "2026-08-06 08:00:00.000"
    assert chart.points[-1].timestamp == "2026-08-07 15:39:20.000"
    assert sum(point.is_anomaly for point in chart.points) == 2
    assert chart.payload_bytes < 16 * 1024 * 1024
    assert elapsed < 20


def test_active_chart_omits_disabled_optional_peer_event_and_location_payloads(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart(
        "demo",
        session_id,
        radio=1,
        max_points=10,
        include_peer=False,
        include_standby_context=False,
        include_events=False,
        include_station_band=False,
    )

    assert chart.events == []
    assert chart.location_segments == []
    assert all(
        point.peer_rssi is None
        and point.peer_signal is None
        and point.peer_tx_busy is None
        and point.peer_rx_busy is None
        and point.backups == []
        for point in chart.points
    )


def test_mesh_source_desktop_location_reveals_file_or_existing_parent_only(tmp_path: Path) -> None:
    paths, session_id, _detail, raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    available = service.get_source_desktop_location("demo", session_id)
    assert available == {"target_type": "file", "path": str(raw.resolve())}

    raw.unlink()
    missing_file = service.get_source_desktop_location("demo", session_id)
    assert missing_file == {"target_type": "directory", "path": str(raw.parent.resolve())}

    shutil.rmtree(raw.parent)
    with pytest.raises(MeshAnalysisQueryError, match="原始日志目录不存在"):
        service.get_source_desktop_location("demo", session_id)


def test_real_peer_observation_stays_unresolved_across_mesh_dtos(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute(
            """
            UPDATE mesh_links
            SET peer_mac_raw = '642f-c778-ef5f',
                peer_mac_normalized = '642fc778ef5f',
                peer_mac = '642fc778ef5f',
                peer_ap_name = 'AP2011',
                peer_ap_mac = '642fc778eda0',
                peer_identity_status = 'unresolved',
                peer_identity_source = '',
                peer_identity_reason = 'no_exact_radio_or_bssid'
            WHERE id = 1
            """
        )
        conn.execute(
            """
            UPDATE active_points
            SET peer_mac_raw = '642f-c778-ef5f',
                peer_mac_normalized = '642fc778ef5f',
                peer_mac = '642fc778ef5f',
                peer_ap_name = 'AP2011',
                peer_site = '现场站点'
            WHERE id = 1
            """
        )

    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    link = service.list_link_details("demo", session_id, page_size=10).items[0]
    build = next(
        item
        for item in service.list_active_build_order("demo", session_id, page_size=10).items
        if item.anchor_link_id == 1
    )
    chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=10)
    point = next(item for item in chart.points if item.link_id == 1)

    assert link.peer_mac_raw == "642f-c778-ef5f"
    assert link.peer_ap_name is None
    assert link.peer_ap_mac is None
    assert link.identity_status == "unresolved"
    assert build.peer_mac_raw == "642f-c778-ef5f"
    assert build.peer_ap_name is None
    assert build.peer_ap_mac is None
    assert point.peer_mac == "642fc778ef5f"
    assert point.peer_ap_name is None
    assert point.peer_ap_mac is None
    assert point.identity_status == "unresolved"


def test_mesh_analysis_consumers_reuse_base_radio_alias_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    snapshot = MeshApLocationSnapshot.from_base_data_items(
        (
            SimpleNamespace(
                name="AP-BASE",
                point_code="AP-BASE",
                mac="0000-0000-0010",
                station="杞︾珯A",
                section="杞︾珯A-杞︾珯B",
                mileage=SimpleNamespace(raw="K1+000"),
                line_side="涓婅",
                direction="涓婅",
            ),
        )
    ).with_base_radio_aliases()
    with sqlite3.connect(detail) as conn:
        conn.execute(
            "UPDATE mesh_links SET peer_ap_mac = '', peer_ap_name = '', peer_identity_status = 'unresolved' WHERE id = 1"
        )
        conn.execute(
            "UPDATE active_points SET peer_ap_name = '', peer_site = '' WHERE link_id = 1"
        )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_ap_map", lambda _site_id: snapshot)

    link = service.list_link_details("demo", session_id, page_size=10).items[0]
    rssi = service.get_rssi_statistics("demo", session_id, max_points=10).points[0]
    busy = service.get_channel_busy("demo", session_id, max_points=10).items[0]
    rate = service.get_rate_series("demo", session_id, max_points=10).items[0]
    counter = service.get_counter_deltas("demo", session_id, max_points=10).items[0]
    event = service.list_switch_events("demo", session_id).items[0]
    stats = service.list_ap_statistics("demo", session_id).items[0]

    for item in (link, rssi, busy, rate):
        assert item.identity_status == "matched"
        assert item.peer_ap_name == "AP-BASE"
        assert item.peer_ap_mac.replace("-", "") == "000000000010"
    assert counter.identity_status == "matched"
    assert busy.station == "杞︾珯A"
    assert event.from_identity_status == "matched"
    assert event.from_ap_name
    assert stats.match_status == "matched"
    assert stats.peer_ap_name == "AP-BASE"


def test_catalog_index_serves_summary_and_page_without_opening_detail_databases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    MeshCatalogIndexService(paths).rebuild_now("demo")
    service = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
        schedule_catalog_index=False,
    )
    original = service._connect_readonly
    opened: list[Path] = []

    def counted(path: Path):
        opened.append(path)
        return original(path)

    monkeypatch.setattr(service, "_connect_readonly", counted)
    summary = service.get_summary("demo")
    page = service.list_analysis_sessions("demo", page=1, page_size=1)

    assert summary.session_count == 1
    assert page.total == 1
    assert all(not path.name.endswith(".mesh.sqlite") for path in opened)
    assert len(opened) == 4


def test_empty_catalog_index_returns_zero_summary_without_validation_error(
    tmp_path: Path,
) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    MeshCatalogIndexService(paths).rebuild_now("demo")
    with sqlite3.connect(paths.mesh_catalog_path("demo")) as connection:
        connection.execute("DELETE FROM mesh_session_index")
        connection.commit()

    summary = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
        schedule_catalog_index=False,
    ).get_summary("demo")

    assert summary.session_count == 0
    assert summary.train_count == 0
    assert summary.mr_count == 0
    assert summary.link_record_count == 0
    assert summary.active_link_count == 0
    assert summary.standby_link_count == 0
    assert summary.warning_session_count == 0


def test_catalog_filters_source_whose_registered_detail_database_was_removed(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, raw, _report = create_mesh_analysis_fixture(tmp_path)
    second_detail = detail.with_name("mesh-second.mesh.sqlite")
    second_raw = raw.with_name("mesh-second.log")
    shutil.copyfile(detail, second_detail)
    second_raw.write_text("[1] 2026/07/14 11:00:00.000\nmesh sample\n", encoding="utf-8")
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.row_factory = sqlite3.Row
        source = dict(conn.execute("SELECT * FROM source_files WHERE id = 1").fetchone())
        source.update(
            id=2,
            original_path=str(second_raw),
            archived_path=str(second_raw),
            parsed_db_path=str(second_detail),
            original_filename=second_raw.name,
            archived_filename=second_raw.name,
            sha256="second-source",
            first_sample_time="2026-07-14 11:00:00.000",
            last_sample_time="2026-07-14 11:00:02.000",
        )
        columns = list(source)
        conn.execute(
            f"INSERT INTO source_files ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            [source[column] for column in columns],
        )
    MeshCatalogIndexService(paths).rebuild_now("demo")
    detail.unlink()
    service = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
        schedule_catalog_index=False,
    )

    summary = service.get_summary("demo")
    page = service.list_analysis_sessions("demo")

    assert session_id not in [item.session_id for item in page.items]
    assert [item.session_id for item in page.items] == [f"{session_id.rsplit(':', 1)[0]}:2"]
    assert page.total == 1
    assert summary.session_count == 1


def test_missing_mesh_root_returns_empty_without_recreating_storage(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    mesh_root = paths.site_mesh_root("demo")
    shutil.rmtree(mesh_root)
    service = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
        schedule_catalog_index=False,
    )

    summary = service.get_summary("demo")
    page = service.list_analysis_sessions("demo")

    assert summary.session_count == 0
    assert summary.train_count == 0
    assert summary.mr_count == 0
    assert page.total == 0
    assert page.items == []
    assert not mesh_root.exists()


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
    assert next(item for item in artifacts if item.artifact_type == "raw_mesh_log").deletable is False
    report_artifact = next(item for item in artifacts if item.artifact_type == "analysis_report")
    assert report_artifact.deletable is True
    sidecar = _report.with_name(f"{_report.name}.manifest.json")
    sidecar.write_text("{}", encoding="utf-8")
    name, targets = service.artifact_delete_targets("demo", session_id, report_artifact.artifact_id)
    assert name == report_artifact.name
    manifest = next(
        (
            paths.rail_transit_root("demo")
            / "web_artifacts"
            / "manifests"
        ).glob("*.json")
    )
    assert set(targets) == {_report.resolve(), manifest.resolve()}
    assert sidecar.resolve() not in targets
    raw_artifact = next(item for item in artifacts if item.artifact_type == "raw_mesh_log")
    with pytest.raises(MeshAnalysisQueryError, match="原始导入日志不允许"):
        service.artifact_delete_targets("demo", session_id, raw_artifact.artifact_id)


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
    assert broken.actionable_warning_count > 0


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


def test_info_only_parse_diagnostics_do_not_make_session_partial(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute(
            "INSERT INTO parse_issues VALUES (2, 'INFO', '无效主链快照', '已过滤无效槽位', 2)"
        )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    session = service.get_analysis_session("demo", session_id).session
    anomalies = service.list_anomalies("demo", session_id, page_size=100)

    assert session.data_integrity == "complete"
    assert (session.info_count, session.warning_count, session.error_count) == (1, 0, 0)
    assert session.actionable_warning_count == 0
    assert not [item for item in anomalies.items if item.anomaly_id == "parse:2"]


def test_parse_issue_summary_and_pagination_are_structured(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("INSERT INTO parse_issues VALUES (2, 'ERROR', 'bad_rssi', 'RSSI 字段无法解析', 12)")
        conn.execute("INSERT INTO parse_issues VALUES (3, 'WARNING', 'bad_rssi', 'RSSI 缺失', 18)")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    detail_result = service.get_analysis_session("demo", session_id)
    summary = detail_result.parse_issue_summary
    assert summary.total_count == 2
    assert summary.error_count == 1
    assert summary.warning_count == 1
    assert sum(group.count for group in summary.groups if group.code == "bad_rssi") == 2
    assert any(warning.code == "parse_issues" and "2 条" in warning.message for warning in detail_result.warnings)

    page = service.list_parse_issues("demo", session_id, page=2, page_size=1)
    assert page.total == 2
    assert page.page == 2
    assert len(page.items) == 1
    assert page.items[0].line_number == 18


def test_parse_issue_summary_reports_legacy_missing_detail(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("DROP TABLE parse_issues")
        conn.execute("CREATE TABLE parse_issue_catalog (id INTEGER PRIMARY KEY, count INTEGER)")
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.execute("UPDATE source_files SET parsed_db_path = ? WHERE id = 1", (str(detail),))
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    result = service.get_analysis_session("demo", session_id)
    assert result.parse_issue_summary.available is True
    assert result.parse_issue_summary.total_count == 0


def test_overview_trend_budget_preserves_segments_and_gap_semantics() -> None:
    points = [
        {"local_rssi": 40, "gap_before": False},
        {"local_rssi": 41, "gap_before": False},
        {"local_rssi": None, "gap_before": True},
        {"local_rssi": 30, "gap_before": False},
        {"local_rssi": 31, "gap_before": False},
    ]
    indices = MeshAnalysisQueryService._chart_trend_row_indices(points, max_points=4, preserve_segments=True)
    assert {0, 1, 3, 4}.issubset(indices)
    assert MeshAnalysisQueryService._chart_gap_between(points, 1, 3)
    assert not MeshAnalysisQueryService._chart_gap_between(points, 3, 4)


def test_overview_prioritizes_full_day_trend_over_dense_switches(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    start = datetime(2026, 8, 6, 3, 30, 0)
    rows = [
        _active_chart_row(index + 1, (start + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S.000"), "000000001618", local_rssi=25 + index % 24)
        for index in range(51_324)
    ]
    chart = service._chart_dto(
        "demo", context,
        {"peer_segment": {"rows": []}, "run_segment": {"rows": rows, "events": [], "total_events": 8_490, "estimated_interval_seconds": 1, "continuity_gap_seconds": 5}},
        mode="active_path", max_points=2_000, time_from="", time_to="",
    )
    assert chart.returned_points <= 2_000
    assert chart.points[0].timestamp == rows[0]["sample_time"]
    assert chart.points[-1].timestamp == rows[-1]["sample_time"]
    first_time = datetime.fromisoformat(chart.points[0].timestamp)
    buckets = {int((datetime.fromisoformat(point.timestamp) - first_time).total_seconds()) * 300 // len(rows) for point in chart.points}
    assert len(buckets) >= 200


def test_overview_gap_propagation_keeps_normal_downsample_connected(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    rows = [_active_chart_row(index + 1, f"2026-08-06 03:{30 + index:02d}:00.000", "000000001618", local_rssi=40 + index) for index in range(10)]
    rows += [_active_chart_row(index + 11, f"2026-08-06 06:{index:02d}:00.000", "000000001620", local_rssi=30 + index) for index in range(10)]
    chart = service._chart_dto(
        "demo", context,
        {"peer_segment": {"rows": []}, "run_segment": {"rows": rows, "events": [], "estimated_interval_seconds": 60, "continuity_gap_seconds": 300}},
        mode="active_path", max_points=10, time_from="", time_to="",
    )
    gap_index = next(index for index, point in enumerate(chart.points) if point.timestamp == "2026-08-06 06:00:00.000")
    assert chart.points[gap_index].gap_before is True
    assert chart.points[-1].gap_before is False

def _overview_coverage_ratio(points: list[MeshChartPointDTO], first: datetime, last: datetime, bucket_count: int = 100) -> float:
    if not points or last <= first:
        return 0.0
    span = (last - first).total_seconds()
    if span <= 0:
        return 0.0
    seen: set[int] = set()
    for point in points:
        timestamp = datetime.fromisoformat(point.timestamp)
        position = int((timestamp - first).total_seconds() / span * bucket_count)
        seen.add(min(position, bucket_count - 1))
    return len(seen) / bucket_count


def test_overview_51324_samples_cover_full_day_time_buckets(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    start = datetime(2026, 8, 6, 3, 30, 0)
    rows = [
        _active_chart_row(
            index + 1,
            (start + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S.000"),
            "000000001618",
            local_rssi=-50 + index % 24,
        )
        for index in range(51_324)
    ]
    chart = service._chart_dto(
        "demo",
        context,
        {
            "peer_segment": {"rows": []},
            "run_segment": {
                "rows": rows,
                "events": [],
                "total_events": 8_490,
                "estimated_interval_seconds": 1,
                "continuity_gap_seconds": 5,
            },
        },
        mode="active_path",
        max_points=2_000,
        time_from="",
        time_to="",
    )
    assert chart.view_mode == "overview"
    assert chart.returned_points <= 2_000
    first = datetime.fromisoformat(chart.points[0].timestamp)
    last = datetime.fromisoformat(chart.points[-1].timestamp)
    assert _overview_coverage_ratio(chart.points, first, last) >= 0.95


def test_overview_line_keeps_one_continuous_segment_with_switches_and_triangle(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    start = datetime(2026, 8, 6, 8, 0, 0)
    rows = [
        _active_chart_row(
            index + 1,
            (start + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S.000"),
            "000000001618",
            local_rssi=-40 + index % 20,
            link_count=2 if index % 17 == 0 else 1,
        )
        for index in range(50_000)
    ]
    chart = service._chart_dto(
        "demo",
        context,
        {
            "peer_segment": {"rows": []},
            "run_segment": {
                "rows": rows,
                "events": [],
                "total_events": 8_000,
                "estimated_interval_seconds": 1,
                "continuity_gap_seconds": 5,
            },
        },
        mode="active_path",
        max_points=2_000,
        time_from="",
        time_to="",
    )
    assert chart.view_mode == "overview"
    assert chart.returned_points <= 2_000
    assert chart.summary.display_segment_count == 1
    assert all(point.gap_before is False for point in chart.points)
    assert chart.points[0].timestamp == rows[0]["sample_time"]
    assert chart.points[-1].timestamp == rows[-1]["sample_time"]
    first = datetime.fromisoformat(chart.points[0].timestamp)
    last = datetime.fromisoformat(chart.points[-1].timestamp)
    assert _overview_coverage_ratio(chart.points, first, last) >= 0.95


def test_overview_real_no_active_gap_produces_two_segments_with_null(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    rows = [
        _active_chart_row(
            index + 1,
            f"2026-08-06 08:{index // 60:02d}:{index % 60:02d}.000",
            "000000001618",
            local_rssi=35,
        )
        for index in range(10 * 60)
    ]
    rows += [
        _active_chart_row(
            len(rows) + index + 1,
            f"2026-08-06 08:{10 + index // 60:02d}:{index % 60:02d}.000",
            "000000001618",
            link_state="STANDBY",
        )
        for index in range(5 * 60)
    ]
    rows += [
        _active_chart_row(
            len(rows) + index + 1,
            f"2026-08-06 08:{15 + index // 60:02d}:{index % 60:02d}.000",
            "000000001618",
            local_rssi=38,
        )
        for index in range(15 * 60)
    ]
    chart = service._chart_dto(
        "demo",
        context,
        {
            "peer_segment": {"rows": []},
            "run_segment": {
                "rows": rows,
                "events": [],
                "estimated_interval_seconds": 1,
                "continuity_gap_seconds": 5,
            },
        },
        mode="active_path",
        max_points=2_000,
        time_from="",
        time_to="",
    )
    assert chart.view_mode == "overview"
    assert chart.summary.display_segment_count == 2
    assert any(point.local_rssi is None for point in chart.points)


def test_overview_sampling_jitter_stays_one_segment_while_analysis_gap_counts(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    start = datetime(2026, 8, 6, 8, 0, 0)
    offsets = [0, 2, 4, 9, 11, 17, 19, 24]
    rows = [
        _active_chart_row(
            index + 1,
            (start + timedelta(seconds=offset)).strftime("%Y-%m-%d %H:%M:%S.000"),
            "000000001618",
            local_rssi=-40 + index,
        )
        for index, offset in enumerate(offsets)
    ]
    chart = service._chart_dto(
        "demo",
        context,
        {
            "peer_segment": {"rows": []},
            "run_segment": {
                "rows": rows,
                "events": [],
                "estimated_interval_seconds": 2,
                "continuity_gap_seconds": 3,
            },
        },
        mode="active_path",
        max_points=100,
        time_from="",
        time_to="",
    )
    assert chart.view_mode == "overview"
    assert chart.summary.analysis_gap_count > 0
    assert chart.summary.display_gap_count == 0
    assert chart.summary.display_segment_count == 1
    assert all(point.gap_before is False for point in chart.points)


def test_resolve_chart_view_mode_treats_full_range_explicit_timestamps_as_overview() -> None:
    first = "2026-08-06 03:30:00.000"
    last = "2026-08-06 15:48:00.000"
    assert MeshAnalysisQueryService._resolve_chart_view_mode(None, "", "", first, last) == "overview"
    assert (
        MeshAnalysisQueryService._resolve_chart_view_mode(
            None,
            first,
            last,
            first,
            last,
        )
        == "overview"
    )
    assert (
        MeshAnalysisQueryService._resolve_chart_view_mode(
            None,
            "2026-08-06 10:00:00.000",
            "2026-08-06 10:10:00.000",
            first,
            last,
        )
        == "window"
    )
    assert (
        MeshAnalysisQueryService._resolve_chart_view_mode(
            "overview",
            "2026-08-06 10:00:00.000",
            "2026-08-06 10:10:00.000",
            first,
            last,
        )
        == "overview"
    )


def test_active_chart_full_range_with_explicit_timestamps_uses_overview(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart(
        "demo",
        session_id,
        radio=1,
        max_points=10,
        time_from="2026-07-14 10:00:00.000",
        time_to="2026-07-14 10:00:03.000",
    )
    forced_window = service.get_active_path_chart(
        "demo",
        session_id,
        radio=1,
        max_points=10,
        time_from="2026-07-14 10:00:00.000",
        time_to="2026-07-14 10:00:03.000",
        view_mode="window",
    )

    assert chart.view_mode == "overview"
    assert chart.returned_points <= 10
    assert forced_window.view_mode == "window"


def test_active_chart_long_window_degrades_critical_overflow_instead_of_failing(
    tmp_path: Path,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    start = datetime(2026, 8, 6, 8, 0, 0)
    rows = [
        _active_chart_row(
            index + 1,
            (start + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S.000"),
            "000000001618",
            local_rssi=30 + index % 10,
            link_state="ACTIVE" if index % 2 == 0 else "STANDBY",
        )
        for index in range(6_000)
    ]

    chart = service._chart_dto(
        "demo",
        context,
        {
            "peer_segment": {"rows": []},
            "run_segment": {
                "rows": rows,
                "events": [],
                "estimated_interval_seconds": 1,
                "continuity_gap_seconds": 5,
            },
        },
        mode="active_path",
        max_points=2_000,
        time_from="2026-08-06 08:00:00.000",
        time_to="2026-08-06 09:40:00.000",
        view_mode="window",
    )

    assert chart.view_mode == "window"
    assert chart.returned_points <= 2_000
    assert chart.response_budget.degraded is True
    assert any("代表性节点" in reason for reason in chart.response_budget.degrade_reasons)


def test_identity_revision_staleness_is_read_only_and_exposed_on_source_summary(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.execute("ALTER TABLE source_files ADD COLUMN identity_index_revision INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE source_files ADD COLUMN identity_mapped_at TEXT DEFAULT ''")
        conn.execute("ALTER TABLE source_files ADD COLUMN identity_mapping_status TEXT DEFAULT 'unknown'")
        conn.execute(
            "UPDATE source_files SET identity_index_revision = 1, identity_mapped_at = '2026-07-14 10:11:00', identity_mapping_status = 'ready' WHERE id = 1"
        )
    with sqlite3.connect(paths.site_db_path("demo")) as conn:
        conn.execute(
            "UPDATE ap_identity_index_state SET revision = 2 WHERE site_id = 'current'"
        )

    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    result = service.get_analysis_session("demo", session_id)
    source = result.sources[0]

    assert source.identity_index_revision == 1
    assert source.identity_current_revision == 2
    assert source.identity_mapping_status == "identity_stale"
    assert source.identity_mapped_at == "2026-07-14 10:11:00"
    assert any(warning.code == "identity_mapping_stale" for warning in result.warnings)


def test_missing_relocated_detail_query_does_not_create_database(tmp_path: Path) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    with sqlite3.connect(index) as conn:
        conn.execute("UPDATE source_files SET parsed_db_path = 'Z:/old-data/missing.mesh.sqlite' WHERE id = 1")
    missing = paths.mesh_mr_parsed_dir("demo", "列车01-MR-CT") / "missing.mesh.sqlite"
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    sessions = service.list_analysis_sessions("demo")

    assert sessions.total == 0
    assert sessions.items == []
    assert not missing.exists()


def test_mesh_schema_rebuild_is_registered_in_existing_job_center() -> None:
    assert "mesh_schema_rebuild" in registered_task_types()


def test_active_build_order_uses_site_default_instead_of_old_source_snapshot(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    snapshot = '{"link_time_window":4000,"short_link_tolerance_ms":100}'
    with sqlite3.connect(paths.mesh_mr_db_path("demo", "列车01-MR-CT")) as conn:
        conn.execute("UPDATE source_files SET analysis_params_json = ? WHERE id = 1", (snapshot,))
    save_site_mesh_analysis_params(paths, "demo", {"link_time_window": 2500})
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    repository = MeshMrRepository(detail, read_only=True)

    site_params = mesh_analysis_params_to_json({"link_time_window": 2500})
    repository_rows = repository.query_active_link_build_order(source_file_id=1, analysis_params=site_params)
    page = service.list_active_build_order("demo", session_id, sort_order="asc")
    session = service.get_analysis_session("demo", session_id)

    assert page.total == len(repository_rows) == 3
    assert [item.anchor_link_id for item in page.items] == [row["anchor_link_id"] for row in repository_rows]
    assert page.items[1].pingpong_type == "AP乒乓切换异常"
    assert page.items[1].is_pingpong_abnormal is True
    assert page.items[0].main_link_switch_time_ms == 2500
    assert page.items[0].short_threshold_seconds == 2.5
    assert session.analysis_params.link_time_window == 2500


def test_active_switch_stability_uses_base_time_with_exact_boundary() -> None:
    def point(sample_time: str, peer: str, link_count: int = 1) -> dict[str, object]:
        return {
            "source_file_id": 1,
            "radio": 1,
            "sample_time": sample_time,
            "peer_mac_raw": peer,
            "peer_mac_normalized": peer,
            "peer_ap_mac": peer,
            "local_rssi_db": 40,
            "link_count": link_count,
        }

    rows = _active_build_order_rows_from_points(
        [
            point("2026-08-07 10:00:00.000", "000000000001"),
            point("2026-08-07 10:00:01.000", "000000000002"),
            point("2026-08-07 10:00:02.000", "000000000002", 2),
            point("2026-08-07 10:00:03.499", "000000000002"),
            point("2026-08-07 10:00:04.000", "000000000003"),
            point("2026-08-07 10:00:06.498", "000000000003"),
        ],
        {"link_time_window": 2500, "sample_interval_ms": 1},
    )

    assert [row["build_result"] for row in rows] == ["stable", "normal", "short"]
    assert rows[1]["main_link_duration_seconds"] == 2.5
    assert rows[1]["main_link_switch_time_ms"] == 2500
    assert rows[2]["main_link_duration_seconds"] == 2.499


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
        conn.execute(
            f"INSERT INTO mesh_links ({common_columns}) VALUES ({placeholders})",
            (8, 5, 1, 8, "2026-07-14 10:00:03.000", 1, "STANDBY", "0000-0000-007f", "00000000007f", "00000000007f", "AP-07", "000000000070", "车站E", "radio2", 1, 36, 2, 5, "exact", "mapping", "00000000007f", "", "session-tag", 85, 80, 3, 4, 0, 0, 8, "radio2", "1s", 1, 39, 2, 4, -55, -53),
        )
    before = _fingerprint(detail)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart(
        "demo",
        session_id,
        radio=1,
        time_from="2026-07-14 10:00:03.000",
        time_to="2026-07-14 10:00:03.001",
        max_points=10,
    )

    assert chart.total_points == 2
    assert chart.total_points_in_range == 2
    assert chart.requested_time_from == "2026-07-14 10:00:03.000"
    assert chart.requested_time_to == "2026-07-14 10:00:03.001"
    assert chart.effective_time_from == "2026-07-14 10:00:03.000"
    assert chart.effective_time_to == "2026-07-14 10:00:03.000"
    gap = next(item for item in chart.points if item.timestamp_tag == "")
    tagged = next(item for item in chart.points if item.timestamp_tag == "(2)")
    assert gap.link_state == ""
    assert gap.local_rssi is None
    assert gap.is_anomaly is True
    assert gap.backups == []
    assert tagged.link_state == "ACTIVE"
    assert tagged.local_rssi == 44
    assert tagged.peer_rssi == 46
    assert tagged.local_signal == -50
    assert tagged.peer_signal == -48
    assert [item.link_id for item in tagged.backups] == [7, 8]
    assert all(item.source_file_id == 1 and item.timestamp_tag == "(2)" for item in tagged.backups)
    assert tagged.backups[0].local_rssi == 38
    assert tagged.backups[0].peer_rssi == 40
    assert tagged.backups[0].local_signal == -56
    assert tagged.backups[0].peer_signal == -54
    assert tagged.backups[1].peer_ap_name == "AP-07"
    assert tagged.backups[1].local_rssi == 36
    assert tagged.backups[1].peer_rssi == 39

    without_peer_series = service.get_active_path_chart(
        "demo",
        session_id,
        radio=1,
        time_from="2026-07-14 10:00:03.000",
        time_to="2026-07-14 10:00:03.001",
        max_points=10,
        include_peer=False,
        include_standby_context=True,
    )
    tooltip_point = next(item for item in without_peer_series.points if item.timestamp_tag == "(2)")
    assert tooltip_point.peer_rssi is None
    assert [item.peer_ap_name for item in tooltip_point.backups] == ["AP-06", "AP-07"]
    assert before == _fingerprint(detail)


def test_chart_and_active_order_tolerate_legacy_detail_without_identity_columns(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        for column in (
            "peer_identity_status",
            "peer_identity_source",
            "peer_identity_reason",
            "peer_match_confidence",
        ):
            conn.execute(f"ALTER TABLE mesh_links DROP COLUMN {column}")

    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=10)
    build_order = service.list_active_build_order("demo", session_id, page_size=10)

    assert chart.points
    assert chart.points[0].identity_status == "unresolved"
    assert chart.points[0].peer_ap_name is None
    assert chart.points[0].peer_ap_mac is None
    assert build_order.items
    assert build_order.items[0].identity_status == "unresolved"
    assert build_order.items[0].peer_ap_name is None
    assert build_order.items[0].peer_ap_mac is None


def test_chart_time_range_filters_peer_payload_and_rejects_invalid_order(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    first = service.list_active_build_order("demo", session_id, sort_order="asc", page_size=100).items[0]

    chart = service.get_peer_segment_chart(
        "demo",
        session_id,
        anchor_link_id=int(first.anchor_link_id or 0),
        time_from="2026-07-14 10:00:00.000",
        time_to="2026-07-14 10:00:01.500",
        max_points=10,
        all_visits=True,
    )

    assert chart.requested_time_from == "2026-07-14 10:00:00.000"
    assert chart.requested_time_to == "2026-07-14 10:00:01.500"
    assert chart.total_points == chart.total_points_in_range
    assert all(chart.requested_time_from <= point.timestamp <= chart.requested_time_to for point in chart.points)
    with pytest.raises(MeshAnalysisTimeRangeError, match="time_from 必须早于 time_to"):
        service.get_active_path_chart(
            "demo",
            session_id,
            time_from="2026-07-14 10:00:01.000",
            time_to="2026-07-14 10:00:01.000",
        )


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


def test_active_chart_exposes_location_segments_and_real_switch_rssi(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=10)

    assert [(item.start_time, item.end_time, item.label) for item in chart.location_segments] == [
        ("2026-07-14 10:00:00.000", "2026-07-14 10:00:00.000", "车站A"),
        ("2026-07-14 10:00:01.000", "2026-07-14 10:00:01.000", "区间A-B"),
        ("2026-07-14 10:00:02.000", "2026-07-14 10:00:02.000", "车站A"),
    ]
    first, second = chart.events
    assert first.before_rssi == 42
    assert first.after_rssi is None
    assert first.point_timestamp == "2026-07-14 10:00:00.000"
    assert first.point_rssi == 42
    assert first.point_context is not None
    assert first.point_context.timestamp == first.point_timestamp
    assert first.point_context.local_rssi == first.point_rssi
    assert first.render_aligned is True
    assert first.render_point_timestamp == first.point_timestamp
    assert first.render_point_rssi == first.point_rssi
    assert first.render_busy_aligned is True
    assert first.render_busy_point_timestamp == "2026-07-14 10:00:01.000"
    assert first.render_busy_tx_busy == 3
    assert first.render_busy_rx_busy == 80
    assert first.busy_point_context is not None
    assert first.busy_point_context.timestamp == first.render_busy_point_timestamp
    assert first.busy_point_context.local_tx_busy == first.render_busy_tx_busy
    assert first.busy_point_context.local_rx_busy == first.render_busy_rx_busy
    assert second.before_rssi is None
    assert second.after_rssi == 43
    assert second.point_timestamp == "2026-07-14 10:00:02.000"
    assert second.point_rssi == 43
    assert second.point_context is not None
    assert second.point_context.timestamp == second.point_timestamp
    assert second.point_context.local_rssi == second.point_rssi
    returned = {(point.timestamp, point.link_id): point.local_rssi for point in chart.points}
    for event in chart.events:
        assert event.render_aligned is True
        assert (event.render_point_timestamp, event.point_context.link_id) in returned
        assert returned[(event.render_point_timestamp, event.point_context.link_id)] == event.render_point_rssi
        assert event.render_busy_aligned is True
        assert event.busy_point_context is not None
        assert event.busy_point_context.local_tx_busy is not None or event.busy_point_context.local_rx_busy is not None
        assert event.render_busy_point_timestamp in {point.timestamp for point in chart.points}


def test_trackside_signal_chart_keeps_all_link_series_and_ignores_legacy_top_n(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        for offset in range(4, 14):
            row_id = 100 + offset
            sample_time = f"2026-07-14 10:00:{offset:02d}.000"
            peer_mac = f"{offset:012x}"
            ap_mac = f"{offset + 100:012x}"
            conn.execute("INSERT INTO samples VALUES (?, 1, 1, ?, '')", (row_id, sample_time))
            conn.execute(
                """
                INSERT INTO mesh_links (
                    id, sample_id, source_file_id, record_seq, source_line_number, sample_time, radio, link_state,
                    peer_mac_raw, peer_mac_normalized, peer_mac, peer_ap_name, peer_ap_mac, peer_site,
                    peer_radio_label, duration_seconds, local_rssi_db, peer_rssi_db, local_tx_busy,
                    peer_tx_busy, local_rx_busy, peer_rx_busy, peer_match_rule, peer_resolve_source,
                    peer_radio_mac, timestamp_tag, session_id, local_signal_dbm, peer_signal_dbm
                ) VALUES (?, ?, 1, ?, ?, ?, 1, 'ACTIVE', ?, ?, ?, ?, ?, '车站A',
                    'radio2', 1, ?, ?, 2, 1, 78, 77, 'exact', 'mapping', ?, '', 'session-extra',
                    -53, -50)
                """,
                (
                    row_id,
                    row_id,
                    offset,
                    offset,
                    sample_time,
                    peer_mac,
                    peer_mac,
                    peer_mac,
                    f"AP-{offset:02d}",
                    ap_mac,
                    40 + offset,
                    43 + offset,
                    peer_mac,
                ),
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart(
        "demo",
        session_id,
        radio=1,
        max_points=10,
        include_standby=True,
        top_n=3,
    )

    assert chart.source_id == session_id
    assert chart.radio == 1
    assert chart.total_series == 13
    assert chart.returned_series == 13
    assert chart.effective_max_points >= chart.returned_series
    assert chart.returned_points == sum(len(item.points) for item in chart.series)
    assert {role for item in chart.series for role in item.roles_present} == {"ACTIVE", "STANDBY"}
    assert "000000000030" in {item.ap_mac for item in chart.series}
    assert {item.data_source for item in chart.series} <= {"peer_rssi_db", "peer_signal_dbm", "mixed"}
    assert {point.data_source for item in chart.series for point in item.points} <= {"peer_rssi_db", "peer_signal_dbm"}
    assert any(point.data_source == "peer_signal_dbm" for item in chart.series for point in item.points)
    assert chart.events == []
    assert chart.include_standby is True
    assert chart.included_roles == ["ACTIVE", "STANDBY"]
    assert chart.top_n == 0
    assert all(
        "前 3 组" not in warning
        and "切换事件过多" not in warning
        and "ACTIVE run" not in warning
        and "ACTIVE RSSI 总点数" not in warning
        for warning in chart.warnings
    )
    ap_01 = next(item for item in chart.series if item.peer_name == "AP-01")
    assert [point.break_before for point in ap_01.points] == [False, True]


def test_trackside_signal_chart_falls_back_to_peer_signal_not_local_rssi(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute(
            "UPDATE mesh_links SET peer_rssi_db = NULL, peer_signal_dbm = -57, local_rssi_db = -21 WHERE id = 1"
        )
        conn.execute(
            "UPDATE active_points SET peer_rssi_db = NULL, peer_signal_dbm = -57, local_rssi_db = -21 WHERE link_id = 1"
        )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10, top_n=10)

    point = next(point for series in chart.series for point in series.points if point.link_id == 1)
    assert point.peer_rssi is None
    assert point.peer_signal == -57
    assert point.local_rssi == -21
    assert point.data_source == "peer_signal_dbm"


def test_trackside_signal_chart_keeps_missing_signal_role_context_and_breaks_across_that_frame(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id, timestamp, peer_rssi in (
            (1, "2026-07-15 08:59:00.000", 40),
            (2, "2026-07-15 08:59:01.000", None),
            (3, "2026-07-15 08:59:02.000", 42),
        ):
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=timestamp,
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_rssi=peer_rssi,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    assert chart.total_frames == chart.returned_frames == 3
    assert chart.total_link_points == chart.returned_link_points == 3
    assert chart.skipped_missing_signal_points == 0
    assert chart.total_link_runs == 1
    assert [point.break_before for point in chart.series[0].points] == [False, False, False]
    assert [point.peer_rssi for point in chart.series[0].points] == [40, None, 42]
    assert any("已保留 1 个缺少 peer_rssi / peer_signal" in warning for warning in chart.warnings)


def test_trackside_signal_chart_preserves_role_snapshot_through_zero_rssi_recovery(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        rows = (
            (1, "2026-08-07 10:02:51.478", "ACTIVE", "AP-X_3106", "000000003106", 28),
            (2, "2026-08-07 10:02:51.478", "STANDBY", "AP-X_3108", "000000003108", 30),
            (3, "2026-08-07 10:02:51.798", "ACTIVE", "AP-X_3106", "000000003106", 29),
            (4, "2026-08-07 10:02:51.798", "STANDBY", "AP-X_3107", "000000003107", 31),
            (5, "2026-08-07 10:02:51.873", "ACTIVE", "AP-X_3105", "000000003105", 0),
            (6, "2026-08-07 10:02:51.873", "STANDBY", "AP-X_3107", "000000003107", 32),
            (7, "2026-08-07 10:02:51.873", "STANDBY", "AP-X_3106", "000000003106", 33),
            (8, "2026-08-07 10:02:52.001", "ACTIVE", "AP-X_3105", "000000003105", 0),
            (9, "2026-08-07 10:02:52.001", "STANDBY", "AP-X_3106", "000000003106", 32),
            (10, "2026-08-07 10:02:52.478", "ACTIVE", "AP-X_3105", "000000003105", 0),
            (11, "2026-08-07 10:02:52.478", "STANDBY", "AP-X_3106", "000000003106", 33),
            (12, "2026-08-07 10:02:52.478", "ACTIVE", "AP-X_3105", "000000003105", 43),
        )
        for row_id, timestamp, role, peer_name, peer_mac, peer_rssi in rows:
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=timestamp,
                radio=1,
                peer_name=peer_name,
                peer_mac=peer_mac,
                peer_rssi=peer_rssi,
                link_state=role,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=20)
    by_time = {
        timestamp: [
            point
            for series in chart.series
            for point in series.points
            if point.timestamp == timestamp
        ]
        for timestamp in ("2026-08-07 10:02:51.873", "2026-08-07 10:02:52.001", "2026-08-07 10:02:52.478")
    }

    assert sorted((point.role, point.peer_ap_name) for point in by_time["2026-08-07 10:02:51.873"]) == [
        ("ACTIVE", "AP-X_3105"),
        ("STANDBY", "AP-X_3106"),
        ("STANDBY", "AP-X_3107"),
    ]
    no_rssi_active = next(point for point in by_time["2026-08-07 10:02:52.001"] if point.role == "ACTIVE")
    assert no_rssi_active.peer_ap_name == "AP-X_3105"
    assert no_rssi_active.peer_rssi is None
    assert no_rssi_active.rssi_zero_run is not None
    recovered_active = next(point for point in by_time["2026-08-07 10:02:52.478"] if point.role == "ACTIVE")
    assert recovered_active.peer_ap_name == "AP-X_3105"
    assert recovered_active.peer_rssi == 43
    assert recovered_active.rssi_zero_run is None
    assert sorted((point.role, point.peer_ap_name) for point in by_time["2026-08-07 10:02:52.478"]) == [
        ("ACTIVE", "AP-X_3105"),
        ("STANDBY", "AP-X_3106"),
    ]


def test_trackside_signal_chart_uses_non_rendered_link_state_as_a_gap_frame(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id, timestamp, state in (
            (1, "2026-07-15 08:58:00.000", "ACTIVE"),
            (2, "2026-07-15 08:58:01.000", "DOWN"),
            (3, "2026-07-15 08:58:02.000", "STANDBY"),
        ):
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=timestamp,
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_rssi=40 + row_id,
                link_state=state,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    assert chart.total_link_points == 2
    assert chart.total_link_runs == 2
    assert chart.role_switch_count == 0
    assert [point.role for point in chart.series[0].points] == ["ACTIVE", "STANDBY"]
    assert [point.break_before for point in chart.series[0].points] == [False, True]


def test_trackside_signal_chart_returns_all_active_and_standby_links_in_one_frame(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id, state, name, mac, rssi in (
            (1, "ACTIVE", "AP-A", "00000000000a", 40),
            (2, "STANDBY", "AP-B", "00000000000b", 45),
            (3, "STANDBY", "AP-C", "00000000000c", 42),
            (4, "DOWN", "AP-D", "00000000000d", 39),
            (5, "UNKNOWN", "AP-E", "00000000000e", 38),
        ):
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time="2026-07-15 09:00:00.000",
                radio=1,
                peer_name=name,
                peer_mac=mac,
                peer_rssi=rssi,
                link_state=state,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)
    compatibility_chart = service.get_trackside_signal_chart(
        "demo",
        session_id,
        radio=1,
        max_points=10,
        include_standby=False,
    )
    points = [point for series in chart.series for point in series.points]

    assert chart.total_frames == chart.returned_frames == 1
    assert chart.total_link_points == chart.returned_link_points == 3
    assert chart.active_link_points == 1
    assert chart.standby_link_points == 2
    assert chart.total_series == 3
    assert {point.role for point in points} == {"ACTIVE", "STANDBY"}
    assert {point.peer_ap_name for point in points} == {"AP-A", "AP-B", "AP-C"}
    assert compatibility_chart.include_standby is True
    assert compatibility_chart.standby_link_points == 2


def test_trackside_signal_chart_keeps_one_series_and_run_when_role_changes(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    states = ["ACTIVE", "ACTIVE", "STANDBY", "STANDBY", "ACTIVE"]
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for index, state in enumerate(states, start=1):
            _insert_active_mesh_link(
                conn,
                row_id=index,
                sample_time=f"2026-07-15 09:10:0{index}.000",
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_radio_mac="0000000000aa",
                peer_rssi=30 + index,
                link_state=state,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    assert chart.total_series == 1
    assert chart.total_link_runs == 1
    assert chart.role_switch_count == 2
    assert chart.series[0].roles_present == ["ACTIVE", "STANDBY"]
    assert [point.role for point in chart.series[0].points] == states
    assert [point.break_before for point in chart.series[0].points] == [False] * 5
    assert len({point.run_id for point in chart.series[0].points}) == 1


def test_trackside_signal_chart_keeps_stable_series_when_main_and_backup_swap(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        row_id = 1
        for frame in range(4):
            timestamp = f"2026-07-15 09:20:0{frame}.000"
            for name, mac, state in (
                ("AP-A", "00000000000a", "ACTIVE" if frame < 2 else "STANDBY"),
                ("AP-B", "00000000000b", "STANDBY" if frame < 2 else "ACTIVE"),
            ):
                _insert_active_mesh_link(
                    conn,
                    row_id=row_id,
                    sample_time=timestamp,
                    radio=1,
                    peer_name=name,
                    peer_mac=mac,
                    peer_rssi=40 + row_id,
                    link_state=state,
                )
                row_id += 1
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    assert chart.total_frames == 4
    assert chart.total_link_points == 8
    assert chart.total_series == 2
    assert chart.total_link_runs == 2
    assert chart.role_switch_count == 2
    assert {
        series.peer_name: [point.role for point in series.points]
        for series in chart.series
    } == {
        "AP-A": ["ACTIVE", "ACTIVE", "STANDBY", "STANDBY"],
        "AP-B": ["STANDBY", "STANDBY", "ACTIVE", "ACTIVE"],
    }


def test_trackside_signal_chart_breaks_when_ap_disappears_then_returns(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    rows = (
        ("2026-07-15 09:30:00.000", "AP-A", "00000000000a", "ACTIVE"),
        ("2026-07-15 09:30:01.000", "AP-A", "00000000000a", "STANDBY"),
        ("2026-07-15 09:30:02.000", "AP-B", "00000000000b", "ACTIVE"),
        ("2026-07-15 09:30:03.000", "AP-A", "00000000000a", "STANDBY"),
    )
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id, (timestamp, name, mac, state) in enumerate(rows, start=1):
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=timestamp,
                radio=1,
                peer_name=name,
                peer_mac=mac,
                peer_rssi=40 + row_id,
                link_state=state,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)
    ap_a = next(series for series in chart.series if series.peer_name == "AP-A")

    assert [point.break_before for point in ap_a.points] == [False, False, True]
    assert len({point.run_id for point in ap_a.points}) == 2


def test_trackside_signal_chart_splits_same_ap_name_by_peer_radio_mac(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id, radio_mac, state in (
            (1, "0000000000a1", "ACTIVE"),
            (2, "0000000000a2", "STANDBY"),
        ):
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time="2026-07-15 09:40:00.000",
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_radio_mac=radio_mac,
                peer_rssi=40 + row_id,
                link_state=state,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    assert chart.total_series == 2
    assert len({series.series_id for series in chart.series}) == 2
    assert {series.peer_radio_mac for series in chart.series} == {
        "0000000000a1",
        "0000000000a2",
    }


def test_trackside_signal_chart_downsamples_complete_frames(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        row_id = 1
        for frame in range(20):
            timestamp = f"2026-07-15 09:50:{frame:02d}.000"
            for link_index in range(4):
                state = "ACTIVE" if link_index == (0 if frame < 10 else 1) else "STANDBY"
                _insert_active_mesh_link(
                    conn,
                    row_id=row_id,
                    sample_time=timestamp,
                    radio=1,
                    peer_name=f"AP-{link_index}",
                    peer_mac=f"{link_index + 1:012x}",
                    peer_rssi=30 + frame + link_index,
                    link_state=state,
                )
                row_id += 1
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)
    returned_by_frame: dict[str, int] = defaultdict(int)
    for series in chart.series:
        for point in series.points:
            returned_by_frame[point.timestamp] += 1

    assert chart.total_frames == 20
    assert chart.total_link_points == 80
    assert chart.returned_frames >= 10
    assert chart.returned_link_points == chart.returned_frames * 4
    assert set(returned_by_frame.values()) == {4}
    assert "2026-07-15 09:50:09.000" in returned_by_frame
    assert "2026-07-15 09:50:10.000" in returned_by_frame


def test_rssi_charts_preserve_linkcnt_two_context_and_triangle_statistics(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        _insert_active_mesh_link(
            conn,
            row_id=1,
            sample_time="2026-08-07 10:02:52.478",
            radio=1,
            peer_name="AP-X_3105",
            peer_mac="000000003105",
            peer_rssi=43,
            link_count=2,
        )
        _insert_active_mesh_link(
            conn,
            row_id=2,
            sample_time="2026-08-07 10:02:52.478",
            radio=1,
            peer_name="AP-X_3106",
            peer_mac="000000003106",
            peer_rssi=31,
            link_state="STANDBY",
            link_count=1,
        )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    active_chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=10)
    trackside_chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    assert active_chart.points[0].link_count == 2
    assert active_chart.points[0].backups[0].link_count == 1
    assert active_chart.summary.triangle_link_point_count == 1
    assert trackside_chart.triangle_link_points == 1
    assert trackside_chart.returned_triangle_link_points == 1
    assert {
        (point.peer_ap_name, point.role, point.link_count)
        for series in trackside_chart.series
        for point in series.points
    } == {
        ("AP-X_3105", "ACTIVE", 2),
        ("AP-X_3106", "STANDBY", 1),
    }


@pytest.mark.parametrize("max_points", [600, 2_000])
def test_rssi_chart_downsampling_preserves_linkcnt_two_boundaries(
    tmp_path: Path,
    max_points: int,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    frame_count = max_points + 100
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id in range(1, frame_count + 1):
            minute, second = divmod(row_id - 1, 60)
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=f"2026-08-07 11:{minute:02d}:{second:02d}.000",
                radio=1,
                peer_name="AP-X_3105",
                peer_mac="000000003105",
                peer_rssi=40 + row_id % 3,
                link_count=2 if row_id in {max_points // 2, max_points // 2 + 1} else 1,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    active_chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=max_points)
    trackside_chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=max_points)

    assert active_chart.downsampled is True
    assert {point.link_count for point in active_chart.points} >= {2}
    assert trackside_chart.downsampled is True
    assert {point.link_count for series in trackside_chart.series for point in series.points} >= {2}


def test_trackside_signal_chart_uses_legacy_backup_context_without_duplication(tmp_path: Path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    timestamp = "2026-07-15 10:00:00.000"
    backup = {
        "link_id": 2,
        "peer_mac": "00000000000b",
        "ap_name": "AP-B",
        "peer_radio_mac": "00000000000b",
        "radio": 1,
        "ap_rssi": 45,
        "peer_signal": -50,
        "sample_time": timestamp,
        "source_file_id": 1,
    }
    payload = {
        "run_segment": {
            "rows": [{
                "id": 1,
                "source_file_id": 1,
                "sample_time": timestamp,
                "timestamp_tag": "",
                "radio": 1,
                "link_state": "ACTIVE",
                "peer_mac_normalized": "00000000000a",
                "peer_ap_name": "AP-A",
                "peer_radio_mac": "00000000000a",
                "peer_rssi_db": 40,
            }],
            "segment_start": timestamp,
            "segment_end": timestamp,
            "estimated_interval_seconds": 1,
            "continuity_gap_seconds": 5,
        },
        "timestamp_labels": [timestamp],
        "timestamp_tags": [""],
        "sample_source_file_ids": [1],
        "sample_radios": [1],
        "standby_links_by_index": [[backup, dict(backup)]],
    }

    chart = service._trackside_signal_chart_dto(
        context,
        payload,
        radio=1,
        time_from="",
        time_to="",
        max_points=10,
    )

    assert chart.total_frames == 1
    assert chart.total_link_points == 2
    assert chart.active_link_points == 1
    assert chart.standby_link_points == 1
    points = [point for series in chart.series for point in series.points]
    assert {point.peer_ap_name for point in points} == {None}
    assert {point.identity_status for point in points} == {"unresolved"}
    assert {point.peer_mac for point in points} == {
        "00000000000a",
        "00000000000b",
    }
    assert any("真实备链上下文补充 1 个备用链路点" in warning for warning in chart.warnings)


def test_trackside_signal_chart_does_not_duplicate_structured_standby_by_link_id(
    tmp_path: Path,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    context = service._context("demo", session_id)
    timestamp = "2026-07-15 10:01:00.000"
    payload = {
        "run_segment": {
            "rows": [
                {
                    "id": 1,
                    "source_file_id": 1,
                    "sample_time": timestamp,
                    "timestamp_tag": "",
                    "radio": 1,
                    "link_state": "ACTIVE",
                    "peer_mac_normalized": "00000000000a",
                    "peer_ap_name": "AP-A",
                    "peer_rssi_db": 40,
                },
                {
                    "id": 2,
                    "source_file_id": 1,
                    "sample_time": timestamp,
                    "timestamp_tag": "",
                    "radio": 1,
                    "link_state": "STANDBY",
                    "peer_mac_normalized": "00000000000b",
                    "peer_ap_name": "AP-B",
                    "peer_rssi_db": 45,
                },
            ],
            "segment_start": timestamp,
            "segment_end": timestamp,
            "estimated_interval_seconds": 1,
            "continuity_gap_seconds": 5,
        },
        "timestamp_labels": [timestamp],
        "timestamp_tags": [""],
        "sample_source_file_ids": [1],
        "sample_radios": [1],
        "standby_links_by_index": [[{
            "link_id": 2,
            "peer_mac": "00000000000b",
            "ap_name": "AP-B",
            "peer_radio_mac": "0000000000bb",
            "radio": 1,
            "ap_rssi": 45,
        }]],
    }

    chart = service._trackside_signal_chart_dto(
        context,
        payload,
        radio=1,
        time_from="",
        time_to="",
        max_points=10,
    )

    assert chart.total_link_points == 2
    assert chart.standby_link_points == 1
    assert not any("真实备链上下文补充" in warning for warning in chart.warnings)


def test_trackside_signal_chart_keeps_interleaved_radios_continuous(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for offset, sample_time in enumerate(
            [
                "2026-07-15 10:00:00.000",
                "2026-07-15 10:00:01.000",
                "2026-07-15 10:00:02.000",
            ],
        ):
            _insert_active_mesh_link(
                conn,
                row_id=offset * 2 + 1,
                sample_time=sample_time,
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_rssi=40 + offset,
            )
            _insert_active_mesh_link(
                conn,
                row_id=offset * 2 + 2,
                sample_time=sample_time,
                radio=2,
                peer_name="AP-B",
                peer_mac="00000000000b",
                peer_rssi=45 + offset,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, max_points=10)

    assert chart.total_series == 2
    ap_a = next(item for item in chart.series if item.peer_name == "AP-A")
    ap_b = next(item for item in chart.series if item.peer_name == "AP-B")
    assert [point.peer_rssi for point in ap_a.points] == [40, 41, 42]
    assert [point.break_before for point in ap_a.points] == [False, False, False]
    assert len({point.run_id for point in ap_a.points}) == 1
    assert [point.peer_rssi for point in ap_b.points] == [45, 46, 47]
    assert [point.break_before for point in ap_b.points] == [False, False, False]
    assert len({point.run_id for point in ap_b.points}) == 1


def test_trackside_signal_chart_preserves_sustained_zero_boundaries_before_sampling(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id, peer_rssi in enumerate((35, 0, 0, 38), start=1):
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=f"2026-07-15 10:00:0{row_id - 1}.000",
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_rssi=peer_rssi,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=3)

    ap_a = next(item for item in chart.series if item.peer_name == "AP-A")
    zero_points = [point for point in ap_a.points if point.rssi_zero_run is not None]
    assert [point.rssi_zero_run.boundary for point in zero_points] == ["start", "end"]
    assert all(point.peer_rssi is None for point in zero_points)
    assert all(point.rssi_zero_run.state == "sustained" for point in zero_points)
    assert zero_points[0].rssi_zero_run.duration_ms == 2_000
    assert chart.sustained_zero_run_count == 1
    assert chart.sustained_zero_total_duration_ms == 2_000
    assert chart.effective_max_frames >= 4


def test_trackside_signal_chart_preserves_short_zero_recovery_and_trend_samples(
    tmp_path: Path,
) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    recovery_time = "2026-07-15 11:01:01.000"
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        row_id = 1
        for frame in range(80):
            minute, second = divmod(frame, 60)
            timestamp = f"2026-07-15 11:{minute:02d}:{second:02d}.000"
            if frame == 60:
                peer_rssi = 0
            elif frame == 50:
                peer_rssi = 20
            elif frame == 70:
                peer_rssi = 60
            else:
                peer_rssi = 40 + frame % 4
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=timestamp,
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_rssi=peer_rssi,
            )
            row_id += 1
            if frame <= 20 and frame % 2 == 0:
                _insert_active_mesh_link(
                    conn,
                    row_id=row_id,
                    sample_time=timestamp,
                    radio=1,
                    peer_name="AP-B",
                    peer_mac="00000000000b",
                    peer_rssi=30 + frame,
                    link_state="STANDBY",
                )
                row_id += 1
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    ap_a = next(item for item in chart.series if item.peer_name == "AP-A")
    returned_times = {point.timestamp for point in ap_a.points}
    later_trend_points = [
        point
        for point in ap_a.points
        if point.timestamp >= "2026-07-15 11:00:40.000"
    ]
    assert recovery_time in returned_times
    assert 1 < len(later_trend_points) < 40
    assert chart.suppressed_zero_sample_count == 1
    assert chart.suppressed_zero_run_count == 1
    assert chart.total_frames == 80
    assert chart.returned_frames == 10
    assert chart.downsampled is True


def test_trackside_signal_chart_breaks_when_link_disappears_from_radio_frames(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    sequence = [
        ("AP-A", "00000000000a", 40),
        ("AP-A", "00000000000a", 41),
        ("AP-B", "00000000000b", 50),
        ("AP-B", "00000000000b", 51),
        ("AP-A", "00000000000a", 42),
        ("AP-A", "00000000000a", 43),
    ]
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for index, (peer_name, peer_mac, peer_rssi) in enumerate(sequence, start=1):
            _insert_active_mesh_link(
                conn,
                row_id=index,
                sample_time=f"2026-07-15 11:00:{index:02d}.000",
                radio=1,
                peer_name=peer_name,
                peer_mac=peer_mac,
                peer_rssi=peer_rssi,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=10)

    ap_a = next(item for item in chart.series if item.peer_name == "AP-A")
    ap_b = next(item for item in chart.series if item.peer_name == "AP-B")
    assert [point.peer_rssi for point in ap_a.points] == [40, 41, 42, 43]
    assert [point.break_before for point in ap_a.points] == [False, False, True, False]
    assert len({point.run_id for point in ap_a.points}) == 2
    assert [point.peer_rssi for point in ap_b.points] == [50, 51]
    assert [point.break_before for point in ap_b.points] == [False, False]
    assert len({point.run_id for point in ap_b.points}) == 1


def test_trackside_signal_chart_run_sampling_is_not_capped_at_legacy_2000(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    ap_count = 400
    runs_per_ap = 5
    points_per_run = 28
    samples: list[tuple[int, int, int, str, str]] = []
    links: list[tuple[object, ...]] = []
    row_id = 1
    elapsed_seconds = 0
    for run_index in range(runs_per_ap):
        for ap_index in range(ap_count):
            peer_mac = f"{ap_index + 1:012x}"
            ap_mac = f"{ap_index + 0x1000:012x}"
            peer_name = f"AP-{ap_index:03d}"
            for point_index in range(points_per_run):
                hour, remainder = divmod(elapsed_seconds, 3600)
                minute, second = divmod(remainder, 60)
                sample_time = f"2026-07-15 {hour:02d}:{minute:02d}:{second:02d}.000"
                peer_rssi = 32 + (point_index % 8)
                if point_index == 7:
                    peer_rssi = 18
                elif point_index == 13:
                    peer_rssi = 58
                samples.append((row_id, 1, 1, sample_time, ""))
                links.append(
                    (
                        row_id,
                        row_id,
                        row_id,
                        row_id,
                        sample_time,
                        1,
                        peer_mac,
                        peer_mac,
                        peer_mac,
                        peer_name,
                        ap_mac,
                        peer_rssi - 5,
                        peer_rssi,
                        peer_mac,
                        peer_rssi - 2,
                    )
                )
                row_id += 1
                elapsed_seconds += 1
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        conn.executemany("INSERT INTO samples VALUES (?, ?, ?, ?, ?)", samples)
        conn.executemany(
            """
            INSERT INTO mesh_links (
                id, sample_id, source_file_id, record_seq, source_line_number, sample_time, radio, link_state,
                peer_mac_raw, peer_mac_normalized, peer_mac, peer_ap_name, peer_ap_mac, peer_site,
                peer_radio_label, peer_radio, duration_seconds, local_rssi_db, peer_rssi_db,
                local_tx_busy, peer_tx_busy, local_rx_busy, peer_rx_busy, peer_match_rule, peer_resolve_source,
                peer_radio_mac, timestamp_tag, session_id, local_signal_dbm, peer_signal_dbm
            ) VALUES (?, ?, 1, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, '',
                'radio', 'radio', 1, ?, ?, 1, 1, 1, 1, 'exact', 'mapping',
                ?, '', 'session-large-trackside', -50, ?)
            """,
            links,
        )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_trackside_signal_chart("demo", session_id, radio=1, max_points=2_000)

    expected_total = ap_count * runs_per_ap * points_per_run
    expected_runs = ap_count * runs_per_ap
    minimum_required_points = expected_runs * 2
    run_counts: dict[str, int] = defaultdict(int)
    for series in chart.series:
        for point in series.points:
            assert point.run_id is not None
            run_counts[point.run_id] += 1
    assert chart.total_points == expected_total
    assert chart.total_series == ap_count
    assert chart.returned_series == ap_count
    assert len(run_counts) == expected_runs
    assert min(run_counts.values()) >= 2
    assert chart.effective_max_points >= minimum_required_points
    assert chart.returned_points >= minimum_required_points
    assert chart.returned_points > 2_000
    assert chart.effective_max_points == minimum_required_points
    assert chart.returned_frames <= 20_000
    assert chart.returned_points <= 20_000
    assert any("最终返回" in warning for warning in chart.warnings)


def test_chart_budget_preserves_switch_points_and_expands_requested_limit() -> None:
    switch_indices = set(range(50, 1_000, 95))
    requested, effective, rendered_switches, warning = MeshAnalysisQueryService._chart_render_budget(
        1_000,
        100,
        switch_indices,
    )
    indices = set(render_indices(1_000, 0, 0, set(), effective, pinned_indices=rendered_switches))

    assert requested == effective == 100
    assert warning is None
    assert switch_indices <= indices

    many_switches = set(range(100, 808))
    requested, effective, rendered_switches, warning = MeshAnalysisQueryService._chart_render_budget(
        54_800,
        600,
        many_switches,
    )
    indices = set(render_indices(54_800, 0, 0, set(), effective, pinned_indices=rendered_switches))

    assert requested == 600
    assert effective == 710
    assert many_switches <= indices
    assert warning == "为保留全部 708 个有效切换节点，图表目标点数已从 600 提升到 710。"


def test_natural_second_sampling_prefers_a_real_nonzero_rssi_point() -> None:
    points = [
        {"timestamp": "2026-07-24 20:00:00.100", "local_rssi": 0},
        {"timestamp": "2026-07-24 20:00:00.900", "local_rssi": 38},
        {"timestamp": "2026-07-24 20:00:01.100", "local_rssi": None},
        {"timestamp": "2026-07-24 20:00:02.100", "local_rssi": 42},
    ]

    assert MeshAnalysisQueryService._natural_second_indices(
        points,
        value_key="local_rssi",
    ) == {1, 2, 3}


def test_chart_budget_rejects_valid_switches_exceeding_safe_cap() -> None:
    switch_indices = set(range(1, 25_001))
    with pytest.raises(MeshChartSelectionLimitError):
        MeshAnalysisQueryService._chart_render_budget(
            30_000,
            600,
            switch_indices,
        )


def test_prioritized_render_indices_never_trades_critical_for_natural_seconds() -> None:
    selected = set(
        int(index)
        for index in prioritized_render_indices(
            10_000,
            300,
            critical_indices={101, 5_001, 9_900},
            trend_indices={200, 5_100, 9_800},
            ordinary_indices=set(range(10_000)),
        )
    )

    assert {0, 101, 5_001, 9_900, 9_999} <= selected
    assert len(selected) == 300


def test_trackside_frame_budget_limits_link_points_and_rejects_critical_overflow() -> None:
    weights = {index: 100 for index in range(1_000)}
    selected, effective, warning = MeshAnalysisQueryService._select_trackside_frames(
        1_000,
        600,
        critical_frames={10, 990},
        trend_frames=set(range(1_000)),
        ordinary_frames=set(),
        frame_weights=weights,
    )

    assert {0, 10, 990, 999} <= selected
    assert sum(weights[index] for index in selected) <= 50_000
    assert effective == len(selected)
    assert warning and "50,000" in warning

    with pytest.raises(MeshAnalysisPayloadLimitError):
        MeshAnalysisQueryService._select_trackside_frames(
            1_000,
            600,
            critical_frames=set(range(600)),
            trend_frames=set(),
            ordinary_frames=set(),
            frame_weights={index: 100 for index in range(1_000)},
        )


def test_chart_payload_byte_limit_fails_instead_of_returning_oversized_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(
        paths,
        base_query=EmptyBaseQuery(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "netconsole.services.rail_transit.mesh_analysis_query_service._MAX_CHART_PAYLOAD_BYTES",
        1,
    )

    with pytest.raises(MeshAnalysisPayloadLimitError):
        service.get_active_path_chart("demo", session_id, radio=1, max_points=10)


def test_chart_does_not_render_zero_rssi_switch_anchor(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        conn.execute("UPDATE mesh_links SET local_rssi_db = 0 WHERE id = 1")
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_active_path_chart("demo", session_id, radio=1, max_points=10)
    first = chart.events[0]

    assert first.render_aligned is False
    assert first.render_point_timestamp is None
    assert first.render_point_rssi is None
    assert first.point_context is None
    assert first.render_busy_aligned is True
    assert first.render_busy_point_timestamp == "2026-07-14 10:00:01.000"
    assert first.render_busy_tx_busy == 3
    assert first.busy_point_context is not None


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


def test_peer_chart_initial_window_supports_twenty_thousand_samples(tmp_path: Path) -> None:
    paths, session_id, detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    with sqlite3.connect(detail) as conn:
        _clear_mesh_chart_rows(conn)
        for row_id in range(1, 2_501):
            minute, second = divmod(row_id - 1, 60)
            _insert_active_mesh_link(
                conn,
                row_id=row_id,
                sample_time=f"2026-07-15 11:{minute:02d}:{second:02d}.000",
                radio=1,
                peer_name="AP-A",
                peer_mac="00000000000a",
                peer_rssi=40 + row_id % 4,
            )
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]

    chart = service.get_peer_segment_chart(
        "demo",
        session_id,
        anchor_link_id=1,
        max_points=20_000,
    )

    assert chart.total_points == 2_500
    assert chart.returned_points == 2_500
    assert chart.downsampled is False


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
