from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from tests.support.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture


def _rows(tmp_path, values):
    paths, session_id, detail, raw, _report = create_mesh_analysis_fixture(tmp_path)
    with closing(sqlite3.connect(detail)) as conn, conn:
        conn.row_factory = sqlite3.Row
        template = dict(conn.execute("SELECT * FROM mesh_links WHERE id = 1").fetchone())
        conn.execute("DELETE FROM mesh_links")
        for index, changes in enumerate(values, 1):
            sample_time = (datetime(2026, 7, 14, 10) + timedelta(seconds=index - 1)).isoformat(sep=" ", timespec="milliseconds")
            row = {
                **template,
                "id": index,
                "sample_id": index,
                "record_seq": index,
                "sample_time": sample_time,
                "local_tx": 100 + index * 10,
                **changes,
            }
            columns = ",".join(row)
            conn.execute(
                f"INSERT INTO mesh_links ({columns}) VALUES ({','.join('?' for _ in row)})",
                tuple(row.values()),
            )
        conn.execute("DELETE FROM samples")
        for index, changes in enumerate(values, 1):
            conn.execute(
                "INSERT INTO samples (id, source_file_id, radio, sample_time, timestamp_tag) VALUES (?, 1, ?, ?, ?)",
                (index, changes.get("radio", 1), (datetime(2026, 7, 14, 10) + timedelta(seconds=index - 1)).isoformat(sep=" ", timespec="milliseconds"), str(index)),
            )
    return paths, session_id, MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery()), raw


def test_raw_query_returns_visible_rows_and_one_identity_predecessor(tmp_path):
    paths, session_id, service, _raw = _rows(
        tmp_path,
        [
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a"},
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a"},
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a"},
            {"peer_mac_normalized": "peer-b", "peer_ap_mac": "ap-b"},
        ],
    )

    result = service.list_link_details(
        "demo",
        session_id,
        radio=1,
        time_from="2026-07-14 10:00:01.000",
        time_to="2026-07-14 10:00:02.000",
        raw_samples=True,
        include_context=True,
        raw_max_rows=100,
    )

    assert result.raw_sample_complete is True
    assert result.raw_sample_version == "mesh-raw-v1"
    assert result.total == 2
    assert result.raw_context_count == 1
    assert [item.record_id for item in result.items] == [1, 2, 3]
    assert [item.is_boundary_context for item in result.items] == [True, False, False]
    assert result.items[0].timestamp == "2026-07-14 10:00:00.000"
    assert result.sql_query_count >= 3


def test_raw_query_is_precisely_bounded_and_does_not_mark_truncated_rows_complete(tmp_path):
    _paths, session_id, service, _raw = _rows(
        tmp_path,
        [{"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a"} for _ in range(101)],
    )

    result = service.list_link_details(
        "demo",
        session_id,
        radio=1,
        time_from="2026-07-14 10:00:00.000",
        time_to="2026-07-14 10:01:40.000",
        raw_samples=True,
        include_context=True,
        raw_max_rows=100,
    )

    assert result.total == 101
    assert result.raw_sample_complete is False
    assert result.downsampled is True


def test_raw_query_context_ignores_visible_role_filter(tmp_path):
    _paths, session_id, service, _raw = _rows(
        tmp_path,
        [
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a", "link_state": "STANDBY"},
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a", "link_state": "ACTIVE"},
        ],
    )

    result = service.list_link_details(
        "demo",
        session_id,
        radio=1,
        link_role="ACTIVE",
        time_from="2026-07-14 10:00:01.000",
        time_to="2026-07-14 10:00:01.000",
        raw_samples=True,
        include_context=True,
    )

    assert [item.record_id for item in result.items] == [1, 2]
    assert result.items[0].is_boundary_context is True
    assert result.items[0].link_role == "STANDBY"
    assert result.items[1].link_role == "ACTIVE"


def test_raw_query_http_exposes_version_completeness_and_sql_trace(tmp_path):
    paths, session_id, service, _raw = _rows(
        tmp_path,
        [
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a"},
            {"peer_mac_normalized": "peer-a", "peer_ap_mac": "ap-a"},
        ],
    )
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    app.state.mesh_analysis_query_service = service

    with TestClient(app) as client:
        response = client.get(
            f"/api/rail-transit/mesh-analysis/sessions/{quote(session_id, safe='')}/links"
            "?site_id=demo&radio=1&time_from=2026-07-14%2010%3A00%3A00.000"
            "&time_to=2026-07-14%2010%3A00%3A01.000&raw_samples=true"
            "&include_context=true&raw_max_rows=100"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_kind"] == "raw_samples"
    assert payload["raw_sample_version"] == "mesh-raw-v1"
    assert payload["raw_sample_complete"] is True
    assert payload["sql_query_count"] >= 3
    assert payload["raw_context_count"] == 0
