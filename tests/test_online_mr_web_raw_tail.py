from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver


def _app_with_session(tmp_path: Path) -> tuple[TestClient, Path]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    session = paths.online_mr_session_dir("demo", "MR-03", "session-4")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps({"session_id": "session-4", "site": "demo", "mr_name": "MR-03", "status": "COLLECTING"}),
        encoding="utf-8",
    )
    return TestClient(create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")), session


def test_raw_tail_is_whitelisted_bounded_and_missing_safe(tmp_path: Path) -> None:
    client, session = _app_with_session(tmp_path)
    (session / "raw" / "mesh_link_raw.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
    before = (session / "session_meta.json").read_bytes()

    with client:
        found = client.get("/api/online-mr/sessions/session-4/raw-tail", params={"name": "mesh_link", "tail": 2})
        missing = client.get("/api/online-mr/sessions/session-4/raw-tail", params={"name": "fping_summary"})
        rejected = client.get("/api/online-mr/sessions/session-4/raw-tail", params={"name": "../session_meta"})

    assert found.status_code == 200
    assert found.json()["data"]["lines"] == ["two", "three"]
    assert missing.status_code == 200
    assert missing.json()["data"] == {
        "success": True,
        "name": "fping_summary",
        "exists": False,
        "lines": [],
        "message": "文件不存在或尚未生成",
        "size_bytes": 0,
        "modified_at": None,
        "summary": {},
    }
    assert rejected.status_code == 422
    assert (session / "session_meta.json").read_bytes() == before


def test_raw_summary_and_fping_summary_expose_no_absolute_paths(tmp_path: Path) -> None:
    client, session = _app_with_session(tmp_path)
    (session / "raw" / "fping_v5_final_summary.json").write_text(
        json.dumps({"sent": 60, "received": 59, "loss_percent": 1.67}),
        encoding="utf-8",
    )

    with client:
        tail = client.get("/api/online-mr/sessions/session-4/raw-tail", params={"name": "fping_summary"})
        summary = client.get("/api/online-mr/sessions/session-4/raw-summary")

    assert tail.json()["data"]["summary"]["sent"] == 60
    assert any(item["name"] == "fping_summary" and item["exists"] for item in summary.json()["data"])
    assert str(tmp_path) not in tail.text + summary.text


def test_empty_raw_file_is_reported_as_not_generated(tmp_path: Path) -> None:
    client, session = _app_with_session(tmp_path)
    (session / "raw" / "switch_history_latest.log").touch()

    with client:
        response = client.get("/api/online-mr/sessions/session-4/raw-tail", params={"name": "switch_history"})

    assert response.status_code == 200
    assert response.json()["data"]["exists"] is False
    assert response.json()["data"]["message"] == "文件不存在或尚未生成"
