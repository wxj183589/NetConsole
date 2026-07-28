from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, reset_tzpath

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.services.ground_unattended.schedule import schedule_window


@contextmanager
def _python_tzdata_only():
    previous = os.environ.get("PYTHONTZPATH")
    os.environ["PYTHONTZPATH"] = ""
    reset_tzpath()
    ZoneInfo.clear_cache()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PYTHONTZPATH", None)
        else:
            os.environ["PYTHONTZPATH"] = previous
        reset_tzpath()
        ZoneInfo.clear_cache()


def test_python_tzdata_loads_representative_iana_zones_without_system_tzpath():
    with _python_tzdata_only():
        shanghai = ZoneInfo("Asia/Shanghai")
        utc = ZoneInfo("UTC")
        bucharest = ZoneInfo("Europe/Bucharest")
        new_york = ZoneInfo("America/New_York")

        assert (
            datetime(2026, 1, 1, tzinfo=shanghai).utcoffset().total_seconds()
            == 8 * 3600
        )
        assert datetime(2026, 1, 1, tzinfo=utc).utcoffset().total_seconds() == 0
        assert (
            datetime(2026, 1, 1, tzinfo=bucharest).utcoffset().total_seconds()
            == 2 * 3600
        )
        assert (
            datetime(2026, 7, 1, tzinfo=bucharest).utcoffset().total_seconds()
            == 3 * 3600
        )
        assert (
            datetime(2026, 1, 1, tzinfo=new_york).utcoffset().total_seconds()
            == -5 * 3600
        )
        assert (
            datetime(2026, 7, 1, tzinfo=new_york).utcoffset().total_seconds()
            == -4 * 3600
        )


def test_schedule_window_and_ground_status_use_asia_shanghai_from_python_tzdata(
    tmp_path,
):
    with _python_tzdata_only():
        window = schedule_window(
            datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc),
            "07:00",
            "23:00",
            "Asia/Shanghai",
        )
        assert window.active is True
        assert window.next_start.utcoffset().total_seconds() == 8 * 3600

        paths = PathResolver(tmp_path / "app", tmp_path / "data")
        app = create_app(paths=paths)
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.get("/api/rail-transit/ground-unattended/status")
            second = client.get("/api/rail-transit/ground-unattended/status")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["timezone"] == "Asia/Shanghai"
    assert first.json()["next_start_at"]
    assert first.json()["next_end_at"]
