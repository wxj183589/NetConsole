from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver


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


def test_status_api_returns_current_recent_and_readonly_mapping_state(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
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
    assert all(
        route.methods == {"GET"}
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/online-mr/")
    )


def test_current_session_returns_none_when_only_terminal_sessions_exist(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    session = _session(paths)
    meta_path = session / "session_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({"status": "STOPPED", "ended_at": "2026-07-14 10:02:00"})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/api/online-mr/sessions/current")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": None}
