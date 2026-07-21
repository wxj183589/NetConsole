from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from support.online_mr_api import wire_online_mr_api_facade


def test_preview_and_collectors_use_bounded_view_files(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
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
                "collectors": {
                    "mesh_link": {
                        "status": "running",
                        "raw_file": "raw/mesh_link_raw.log",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (session / "view" / "live_link_status.json").write_text(
        json.dumps(
            {
                "available": True,
                "updated_at": "2026-07-14T10:02:00",
                "peer_name": "AP-01",
                "rssi": -61,
            }
        ),
        encoding="utf-8",
    )
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)

    with TestClient(app) as client:
        preview = client.get("/api/online-mr/sessions/session-2/preview")
        collectors = client.get("/api/online-mr/sessions/session-2/collectors")

    assert preview.status_code == collectors.status_code == 200
    assert preview.json()["data"]["link"]["peer_name"] == "AP-01"
    mesh = next(
        item for item in collectors.json()["data"] if item["name"] == "mesh_link"
    )
    assert mesh["exists"] is True
    assert mesh["status"] == "stopped"
    assert str(tmp_path) not in preview.text + collectors.text


def test_missing_view_files_return_empty_preview_instead_of_500(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    session = paths.online_mr_session_dir("demo", "MR-02", "session-3")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-3",
                "site": "demo",
                "mr_name": "MR-02",
                "status": "STOPPED",
            }
        ),
        encoding="utf-8",
    )
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)

    with TestClient(app) as client:
        response = client.get("/api/online-mr/sessions/session-3/preview")

    assert response.status_code == 200
    assert response.json()["data"]["available"] is False
    assert response.json()["data"]["message"] == "暂无实时链路数据"


def test_preview_falls_back_to_bounded_mesh_raw_tail_without_writing_session(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    session = paths.online_mr_session_dir("demo", "MR-02", "session-raw-preview")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    meta_path = session / "session_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "session_id": "session-raw-preview",
                "site": "demo",
                "mr_name": "MR-02",
                "status": "COLLECTING",
            }
        ),
        encoding="utf-8",
    )
    raw_path = session / "raw" / "mesh_link_raw.log"
    old_sample = (
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        " AP-OUTSIDE-TAIL        aaaa-bbbb-cccc 20   74ad-cb9d-3321 WLAN-MeshLink1    Active(a)        00h 01m 00s\n"
    )
    latest_samples = (
        " Peer Name              Peer MAC       RSSI BSSID          Interface         Link state       Online time\n"
        " AP-STANDBY             1111-2222-3333 31   74ad-cb9d-3321 WLAN-MeshLink1    Standby(a)       00h 02m 00s\n"
        " AP-LATEST              4444-5555-6666 52   74ad-cb9d-3321 WLAN-MeshLink2    Active(a)        00h 03m 00s\n"
    )
    raw_path.write_text(old_sample + ("padding\n" * 20_000) + latest_samples, encoding="utf-8")
    meta_before = meta_path.read_bytes()
    raw_before = raw_path.read_bytes()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")
    wire_online_mr_api_facade(app, paths)

    with TestClient(app) as client:
        response = client.get("/api/online-mr/sessions/session-raw-preview/preview")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["available"] is True
    assert payload["link"] == {
        "status": "active",
        "updated_at": payload["link"]["updated_at"],
        "master": "AP-LATEST",
        "master_ap": "AP-LATEST",
        "peer_name": "AP-LATEST",
        "peer_mac": "444455556666",
        "rssi_dbm": -52,
        "radio": 1,
        "source": "raw_tail",
    }
    assert "AP-OUTSIDE-TAIL" not in response.text
    assert payload["display_context"] == {}
    assert meta_path.read_bytes() == meta_before
    assert raw_path.read_bytes() == raw_before
