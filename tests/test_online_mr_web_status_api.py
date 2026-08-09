from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.backend.api.online_mr_router import router as online_mr_router
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from support.online_mr_api import wire_online_mr_api_facade


def _session(paths: PathResolver, session_id: str = "session-1") -> Path:
    path = paths.online_mr_session_dir("demo", "MR-01", session_id)
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (path / name).mkdir(parents=True, exist_ok=True)
    (path / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "site": "demo",
                "mr_name": "MR-01",
                "device_id": 7,
                "device_name": "列车07 MR",
                "status": "COLLECTING",
                "started_at": "2026-07-14 10:00:00",
                "controller_task_id": "task-1",
                "executor_kind": "LOCAL",
                "intervals": {"mesh_link": 1, "channel_busy": 9},
                "fping": {"enabled": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_status_api_returns_current_recent_and_readonly_mapping_state(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)
    session = _session(paths)
    app.state.task_service.create_external_task(
        task_id="task-1",
        task_type="online_mr_collection",
        task_name="Online MR",
        source="local",
        site_name="demo",
    )
    with sqlite3.connect(paths.site_tasks_db_path("demo")) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS online_mr_task_sessions ("
            "controller_task_id TEXT, session_id TEXT, site_id TEXT, mapping_state TEXT, "
            "duration_minutes REAL, stop_reason TEXT)"
        )
        conn.execute(
            "INSERT INTO online_mr_task_sessions VALUES (?, ?, ?, ?, ?, ?)",
            ("task-1", "session-1", "demo", "LINKED", 2.5, ""),
        )
    meta_path = session / "session_meta.json"
    before = meta_path.read_bytes()

    with TestClient(app) as client:
        current = client.get("/api/online-mr/sessions/current")
        recent = client.get("/api/online-mr/sessions/recent")
        detail = client.get("/api/online-mr/sessions/session-1")

    assert current.status_code == recent.status_code == detail.status_code == 200
    assert current.json()["data"]["session_id"] == "session-1"
    assert recent.json()["data"][0]["status"] == "COLLECTING"
    assert detail.json()["data"]["mapping_state"] == "LINKED"
    assert detail.json()["data"]["task_status"] == "PENDING"
    assert meta_path.read_bytes() == before
    post_paths = {
        route.path
        for route in online_mr_router.routes
        if getattr(route, "path", "").startswith("/online-mr/")
        and route.methods == {"POST"}
    }
    assert post_paths == {
        "/online-mr/sessions/{session_id}/notes",
        "/online-mr/sessions/{session_id}/desktop-location",
        "/online-mr/sessions/{session_id}/parse",
        "/online-mr/sessions/{session_id}/report",
        "/online-mr/mesh-analysis/import",
        "/online-mr/tasks/{task_id}/cancel",
        "/online-mr/tasks/recover",
    }


def test_current_session_returns_none_when_only_terminal_sessions_exist(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)
    session = _session(paths)
    meta_path = session / "session_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({"status": "STOPPED", "ended_at": "2026-07-14 10:02:00"})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/api/online-mr/sessions/current")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": None}


def test_analysis_api_preserves_metric_paging_units_and_switch_sources(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)
    session = _session(paths)
    with sqlite3.connect(session / "parsed" / "online_diagnosis.sqlite") as conn:
        conn.executescript(
            """
            CREATE TABLE radio_statistics_samples (
                id INTEGER PRIMARY KEY, collector_time TEXT, device_clock TEXT, radio INTEGER,
                metric_name TEXT, metric_value REAL, metric_unit TEXT,
                raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
            );
            CREATE TABLE switch_history_events (
                id INTEGER PRIMARY KEY, event_time_local TEXT, event_time_device TEXT,
                snapshot_collector_time TEXT, radio INTEGER, old_peer_name TEXT, old_peer_mac TEXT,
                old_rssi REAL, new_peer_name TEXT, new_peer_mac TEXT, new_rssi REAL,
                switch_reason_text TEXT, raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
            );
            """
        )
        conn.executemany(
            "INSERT INTO radio_statistics_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-14 10:00:00", "10:00:00", 1, "TxFrameAllCnt", 10, "frame", "raw/ap_radio_statistics_raw.log", 1, 2),
                (2, "2026-07-14 10:00:01", "10:00:01", 1, "RxFrameAllCnt", 20, "frame", "raw/ap_radio_statistics_raw.log", 3, 4),
            ],
        )
        conn.execute(
            "INSERT INTO switch_history_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "2026-07-14 10:01:00", None, None, 1, "AP-A", "aa", -80, "AP-B", "bb", -50, "test", "raw/switch_history_latest.log", 5, 6),
        )

    with TestClient(app) as client:
        metric = client.get(
            "/api/online-mr/sessions/session-1/metric-page",
            params={
                "metric_types": "radio_statistics",
                "start_time": "2026-07-14 10:00:00",
                "end_time": "2026-07-14 10:00:02",
                "limit": 1,
                "offset": 1,
                "downsample": "NONE",
                "bucket_seconds": 1,
            },
        )
        switch = client.get(
            "/api/online-mr/sessions/session-1/switch-rssi-windows",
            params={"source": "history", "limit": 10, "offset": 0},
        )

    assert metric.status_code == 200
    metric_data = metric.json()["data"]
    assert metric_data["offset"] == 1
    assert metric_data["page_size_per_metric"] == 1
    assert metric_data["next_offset"] == 2
    assert metric_data["series"][0]["unit"] == "frame"
    assert metric_data["series"][0]["points"][0]["value"] == 20
    assert switch.status_code == 200
    switch_item = switch.json()["data"]["items"][0]
    assert {key: switch_item[key] for key in (
        "event_id", "source", "event_time", "radio", "reason", "old_peer_name",
        "old_peer_mac", "old_rssi_dbm", "new_peer_name", "new_peer_mac", "new_rssi_dbm",
    )} == {
        "event_id": "history-1",
        "source": "history",
        "event_time": "2026-07-14 10:01:00",
        "radio": 1,
        "reason": "test",
        "old_peer_name": "AP-A",
        "old_peer_mac": "aa",
        "old_rssi_dbm": -80.0,
        "new_peer_name": "AP-B",
        "new_peer_mac": "bb",
        "new_rssi_dbm": -50.0,
    }
    assert "raw_file" not in switch_item
    assert "raw_line_start" not in switch_item


def test_legacy_metrics_endpoint_still_returns_a_series_list(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)
    session = _session(paths)
    with sqlite3.connect(session / "parsed" / "online_diagnosis.sqlite") as conn:
        conn.execute(
            "CREATE TABLE main_link_samples (id INTEGER PRIMARY KEY, device_time TEXT, radio INTEGER, mr_rssi REAL, peer_name TEXT)"
        )
        conn.execute("INSERT INTO main_link_samples VALUES (1, '2026-07-14 10:00:00', 1, -60, 'AP-1')")

    with TestClient(app) as client:
        response = client.get(
            "/api/online-mr/sessions/session-1/metrics",
            params={"metric_types": "rssi"},
        )

    assert response.status_code == 200
    assert isinstance(response.json()["data"], list)
    assert response.json()["data"][0]["points"][0]["value"] == -60
