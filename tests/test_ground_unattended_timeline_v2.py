from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver


def test_ground_timeline_filters_count_order_and_dual_times(tmp_path: Path) -> None:
    app = create_app(paths=PathResolver(tmp_path / "app", tmp_path / "data"))
    repo = app.state.ground_unattended_repository
    repo.create_or_get_run(run_id="v2", run_date="2026-11-06",
                           scheduled_start_at="2026-11-06T00:00:00+08:00",
                           scheduled_end_at="2026-11-07T00:00:00+08:00")
    for mr_id, role, stamp in [("mr-ct", "CT", "2026-11-06T08:00:00+08:00"),
                               ("mr-cw", "CW", "2026-11-06T00:00:02Z"),
                               ("mr-ct", "CT", "2026-11-06T00:00:01Z")]:
        repo.add_event(run_id="v2", train_id="train-a", mr_id=mr_id,
                       event_type="mr_offline", title="MR offline", ts=stamp,
                       details={"mr_role": role, "device_time": stamp,
                                "received_at": "2026-11-06T08:00:35+08:00"})
    with TestClient(app) as client:
        response = client.get("/api/rail-transit/ground-unattended/timeline", params={
            "run_id": "v2", "train_id": "train-a", "mr_role": "CT",
            "start_at": "2026-11-06T00:00:00Z", "end_at": "2026-11-06T00:00:03Z",
            "event_type": "mr_offline", "page_size": 1})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2  # Count must not adopt the last projected MR ID.
        assert payload["items"][0]["ts"] == "2026-11-06T00:00:01Z"
        assert payload["items"][0]["device_time"] == "2026-11-06T00:00:01Z"
        assert payload["items"][0]["received_at"] == "2026-11-06T08:00:35+08:00"
        exact = client.get("/api/rail-transit/ground-unattended/timeline", params={
            "run_id": "v2", "mr_id": "mr-cw"}).json()
        assert exact["total"] == 1
        assert exact["items"][0]["mr_id"] == "mr-cw"
        all_items = client.get("/api/rail-transit/ground-unattended/timeline", params={"run_id": "v2"}).json()
        assert all_items["total"] == 3
        assert all_items["items"][0]["mr_id"] == "mr-cw"
        for filters in ({"start_at": "invalid"}, {"start_at": "2026-11-07T00:00:00Z", "end_at": "2026-11-06T00:00:00Z"}):
            assert client.get("/api/rail-transit/ground-unattended/timeline", params=filters).status_code == 422
