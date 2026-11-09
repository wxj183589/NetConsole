from __future__ import annotations

import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from urllib.parse import quote

from netconsole.backend.api.main import create_app
from netconsole.services.rail_transit.mesh_analysis_query_service import (
    MeshAnalysisQueryError, MeshAnalysisQueryService,
)
from tests.support.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture


def setup_rows(tmp_path, rows):
    paths, session_id, detail, raw, _ = create_mesh_analysis_fixture(tmp_path)
    with closing(sqlite3.connect(detail)) as conn, conn:
        conn.row_factory = sqlite3.Row
        template = dict(conn.execute("SELECT * FROM mesh_links WHERE id = 1").fetchone())
        conn.execute("DELETE FROM mesh_links")
        for index, changes in enumerate(rows, 1):
            item = {**template, "id": index, "record_seq": index, "local_tx": 100 + index * 35, **changes}
            conn.execute(
                "INSERT INTO mesh_links (" + ",".join(item) + ") VALUES (" + ",".join("?" for _ in item) + ")",
                tuple(item.values()),
            )
    return paths, session_id, detail, raw, MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())


def nearest(service, session_id, **kwargs):
    return service.list_link_details(
        "demo", session_id, radio=1, exact_ap=True,
        time_from="2026-07-14 10:00:00.000", time_to="2026-07-14 10:01:00.000",
        nearest_time=kwargs.pop("nearest_time", "2026-07-14 10:00:02.100"), **kwargs,
    )


def test_nearest_reads_raw_active_millisecond_sample_and_counter_context(tmp_path, monkeypatch):
    _, session_id, _, _, service = setup_rows(tmp_path, [
        {"sample_time": "2026-07-14 10:00:00.100"},
        {"sample_time": "2026-07-14 10:00:00.200"},
        {"sample_time": "2026-07-14 10:00:00.156", "link_state": "STANDBY", "peer_mac_normalized": "standby"},
        {"sample_time": "2026-07-14 10:00:00.155", "radio": 2},
        {"sample_time": "2026-07-14 10:00:00.155", "source_file_id": 2},
    ])
    statements = []
    connect = service._connect_readonly
    def traced(path):
        conn = connect(path)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(service, "_connect_readonly", traced)
    result = nearest(service, session_id, nearest_time="2026-07-14T10:00:00.156")
    assert result.total == 1 and result.page_size == 1 and not result.downsampled
    point = result.items[0]
    assert point.record_id == 2 and point.link_role == "ACTIVE"
    assert point.timestamp == "2026-07-14 10:00:00.200"
    sample = point.counter_samples["local_tx"]
    assert (sample.current, sample.previous, sample.delta) == (170, 135, 35)
    assert sample.interval_seconds == pytest.approx(0.1)
    assert sample.per_second == pytest.approx(350)
    assert point.local_tx_delta == 35
    link_statements = [sql.upper() for sql in statements if "FROM MESH_LINKS" in sql.upper()]
    assert all("COUNT(*)" not in sql and "ABS(" not in sql for sql in link_statements)
    assert sum("SELECT ML.ID, ML.SAMPLE_TIME" in sql and "LIMIT 1" in sql for sql in link_statements) == 2


@pytest.mark.parametrize("middle", [
    {"link_state": "STANDBY"},
    {"peer_mac_normalized": "ap-b", "peer_ap_mac": "ap-b"},
    {"establish_time": "2026-07-14 09:59:00.000"},
    {"peer_radio_mac": "radio-b"},
])
def test_nearest_counter_context_detects_intervening_switch_even_with_ap_filter(tmp_path, middle):
    _, session_id, _, _, service = setup_rows(tmp_path, [
        {"sample_time": "2026-07-14 10:00:00.000"},
        {"sample_time": "2026-07-14 10:00:01.000", **middle},
        {"sample_time": "2026-07-14 10:00:02.000"},
    ])
    result = nearest(service, session_id, peer_ap_mac="000000000010")
    assert result.items[0].record_id == 3
    assert result.items[0].counter_samples["local_tx"].status == "link_changed"
    assert result.items[0].local_tx_delta is None
    monitor = service.list_link_details(
        "demo", session_id, radio=1, exact_ap=True, peer_ap_mac="000000000010",
        link_role="ACTIVE", metric_group="counters",
        time_from="2026-07-14 10:00:00.000", time_to="2026-07-14 10:01:00.000",
    )
    point = next(item for item in monitor.items if item.record_id == 3)
    assert point.counter_samples["local_tx"].status == "link_changed"
    assert point.local_tx_delta is None


def test_nearest_counters_reset_after_real_zero_observation(tmp_path, monkeypatch):
    _, session_id, _, _, service = setup_rows(tmp_path, [
        {"sample_time": "2026-07-14 10:00:00.000"},
        {"sample_time": "2026-07-14 10:00:02.000"},
    ])
    from datetime import datetime
    monkeypatch.setattr(
        "netconsole.services.rail_transit.mesh_analysis_query_service._zero_window",
        lambda *_args: (SimpleNamespace(source_line_number=100, radio=1, sample_time=datetime(2026, 7, 14, 10, 0, 1)),),
    )
    point = nearest(service, session_id).items[0]
    assert point.counter_samples["local_tx"].status == "first"
    assert point.counter_samples["local_tx"].previous is None
    assert point.local_tx_delta is None


def test_nearest_respects_scope_and_returns_empty_without_waiting(tmp_path):
    _, session_id, _, _, service = setup_rows(tmp_path, [{"sample_time": "2026-07-14 10:00:02.000"}])
    assert nearest(service, session_id, peer_ap_mac="unknown").items == []
    assert nearest(service, session_id, link_role="STANDBY").items == []
    with pytest.raises(MeshAnalysisQueryError):
        nearest(service, session_id, nearest_time="bad-time")


def test_nearest_api_passes_parameter_and_retains_all_counter_metadata(tmp_path):
    paths, session_id, _, _, service = setup_rows(tmp_path, [
        {"sample_time": "2026-07-14 10:00:00.000"},
        {"sample_time": "2026-07-14 10:00:02.000"},
    ])
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.mesh_analysis_query_service = service
    with TestClient(app) as client:
        response = client.get(
            f"/api/rail-transit/mesh-analysis/sessions/{quote(session_id, safe='')}/links",
            params={"site_id": "demo", "radio": 1, "nearest_time": "2026-07-14 10:00:02.100",
                    "time_from": "2026-07-14 10:00:00.000", "time_to": "2026-07-14 10:01:00.000"},
        )
    assert response.status_code == 200
    point = response.json()["items"][0]
    assert point["record_id"] == 2
    assert point["counter_samples"]["local_tx"]["per_second"] == 17.5
    assert point["local_tx_delta"] == 35
