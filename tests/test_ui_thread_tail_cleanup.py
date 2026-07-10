from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage

from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_tasks import run_background_task


def _run(task_type: str, params: dict[str, object]) -> dict[str, object]:
    return run_background_task(BackgroundJob(task_type=task_type, params=params))


def test_wifi_survey_background_round_trip_and_heatmap(tmp_path: Path) -> None:
    db_path = tmp_path / "site.db"
    source = tmp_path / "station.png"
    image = QImage(120, 80, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    assert image.save(str(source), "PNG")

    imported = _run(
        "wifi_survey_floor_import",
        {"db_path": str(db_path), "source_path": str(source), "target_dir": str(tmp_path / "floorplans")},
    )
    floor = dict(imported["floor"])
    created = _run(
        "wifi_survey_create_session",
        {"db_path": str(db_path), "floor_plan_id": int(floor["id"]), "name": "验收会话"},
    )
    session = dict(created["session"])

    for index, (x_px, y_px, rssi) in enumerate(((10.0, 10.0, -52.0), (100.0, 10.0, -66.0), (60.0, 70.0, -79.0)), start=1):
        _run(
            "wifi_survey_save_sample",
            {
                "db_path": str(db_path),
                "session_id": int(session["id"]),
                "x_px": x_px,
                "y_px": y_px,
                "observations": [
                    {
                        "ssid": "CBTC",
                        "bssid": f"00:11:22:33:44:{index:02d}",
                        "rssi_dbm": rssi,
                        "channel": 149,
                        "band": "5 GHz",
                    }
                ],
            },
        )

    snapshot = _run(
        "wifi_survey_refresh",
        {"db_path": str(db_path), "floor_plan_id": int(floor["id"]), "session_id": int(session["id"])},
    )
    assert len(snapshot["points"]) == 3
    assert len(snapshot["observations"]) == 3
    assert len(snapshot["network_rows"]) == 3

    output = tmp_path / "heatmap.png"
    rendered = _run(
        "wifi_survey_heatmap_render",
        {
            "db_path": str(db_path),
            "session_id": int(session["id"]),
            "mode": "ssid",
            "selected_ssids": ["CBTC"],
            "width": 120,
            "height": 80,
            "output_path": str(output),
        },
    )
    assert rendered["valid_count"] == 3
    assert output.is_file()

