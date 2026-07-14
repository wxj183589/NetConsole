from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver


def test_preview_and_collectors_use_bounded_view_files(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    session = paths.online_mr_session_dir("demo", "MR-02", "session-2")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-2",
                "site": "demo",
                "mr_name": "MR-02",
                "status": "STOPPED",
                "started_at": "2026-07-14 10:00:00",
                "ended_at": "2026-07-14 10:02:00",
                "intervals": {"mesh_link": 1},
                "fping": {"enabled": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (session / "raw" / "mesh_link_raw.log").write_text("mesh", encoding="utf-8")
    (session / "view" / "live_mr_status.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-07-14T10:02:00",
                "display_context": {"station": "甲站", "section": "甲站-乙站"},
                "collectors": {"mesh_link": {"status": "running", "raw_file": "raw/mesh_link_raw.log"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (session / "view" / "live_link_status.json").write_text(
        json.dumps({"available": True, "updated_at": "2026-07-14T10:02:00", "peer_name": "AP-01", "rssi": -61}),
        encoding="utf-8",
    )
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        preview = client.get("/api/online-mr/sessions/session-2/preview")
        collectors = client.get("/api/online-mr/sessions/session-2/collectors")

    assert preview.status_code == collectors.status_code == 200
    assert preview.json()["data"]["link"]["peer_name"] == "AP-01"
    mesh = next(item for item in collectors.json()["data"] if item["name"] == "mesh_link")
    assert mesh["exists"] is True
    assert mesh["status"] == "stopped"
    assert str(tmp_path) not in preview.text + collectors.text


def test_missing_view_files_return_empty_preview_instead_of_500(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    session = paths.online_mr_session_dir("demo", "MR-02", "session-3")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps({"session_id": "session-3", "site": "demo", "mr_name": "MR-02", "status": "STOPPED"}),
        encoding="utf-8",
    )
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        response = client.get("/api/online-mr/sessions/session-3/preview")

    assert response.status_code == 200
    assert response.json()["data"]["available"] is False
    assert response.json()["data"]["message"] == "暂无实时链路数据"
