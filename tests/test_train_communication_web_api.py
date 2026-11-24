from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.feature_registry import FEATURES
from netconsole.core.paths import PathResolver
from tests.support.rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


def test_train_communication_is_retired_and_online_mr_inventory_remains(tmp_path: Path) -> None:
    paths, _ = build_rail_transit_base_data_fixture(tmp_path)
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing")
    app.state.feature_gate.features["module.online_mr"] = {
        "visible": True, "enabled": True, "client_package": True, "internal_only": False,
    }
    with TestClient(app) as client:
        assert client.get("/api/rail-transit/train-communication/summary").status_code == 404
        assert client.get("/api/rail-transit/train-communication/point-table").status_code == 404
        assert client.post("/api/rail-transit/train-communication/trains/01/diagnostics").status_code == 404
        assert client.get("/api/rail-transit/online-mr/inventory/summary").status_code == 200
        assert client.get("/api/rail-transit/online-mr/inventory/trains").status_code == 200
    assert not any(
        "train_communication" in feature.feature_id or feature.feature_id == "rail.car_network_diagnostic"
        for feature in FEATURES
    )


def test_missing_iperf_raw_tail_returns_chinese_empty_state(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    session = paths.online_mr_session_dir("demo", "MR-01", "session-1")
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (session / name).mkdir(parents=True, exist_ok=True)
    (session / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "site": "demo",
                "mr_name": "MR-01",
                "status": "STOPPED",
            }
        ),
        encoding="utf-8",
    )
    Database(paths.site_db_path("demo")).initialize()
    app = create_app(paths=paths, frontend_dist=tmp_path / "missing-dist")

    with TestClient(app) as client:
        response = client.get(
            "/api/online-mr/sessions/session-1/raw-tail?name=iperf_client"
        )

    assert response.status_code == 200
    assert response.json()["data"]["exists"] is False
    assert response.json()["data"]["message"] == "文件不存在或尚未生成"
