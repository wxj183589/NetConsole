from __future__ import annotations

import csv
import hashlib
import time
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.export_worker import run_job
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.export.export_handlers import run_generic_export_handler
from netconsole.services.export.export_job import ExportJob


def _seed(path: Path, count: int) -> GroundUnattendedRepository:
    repo = GroundUnattendedRepository(path, site_id="demo")
    repo.create_or_get_run(run_id="history-run", run_date="2026-11-07", scheduled_start_at="2026-11-07T00:00:00+08:00", scheduled_end_at="2026-11-08T00:00:00+08:00")
    for index in range(count):
        repo.add_event(run_id="history-run", train_id="train-1", mr_id="mr-ct", event_type="mr_offline", title="=危险公式", message=f"中文事件 {index}", ts="2026-11-07T08:00:00+08:00", details={"mr_role": "CT", "device_time": "2026-11-07T08:00:00+08:00", "received_at": "2026-11-07T08:00:35+08:00"})
    return repo


def _job(path: Path, db: Path, filters: dict[str, str] | None = None) -> ExportJob:
    return ExportJob(job_id="history-export", job_type="ground_history_csv", output_path=str(path), tmp_path=str(path.with_suffix(".tmp")), cancel_path=str(path.with_suffix(".cancel")), params={"payload": {"db_path": str(db), "site_id": "demo", "filters": filters or {"data_type": "timeline"}}})


def test_history_export_all_rows_utf8_read_only_and_cancel(tmp_path: Path) -> None:
    db = tmp_path / "index.sqlite"
    _seed(db, 601)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    output = tmp_path / "history.csv"
    job = _job(output, db)
    result = run_generic_export_handler(job)
    assert result["row_count"] == 601
    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) >= 602
    data = [row for row in rows if len(row) == 11 and row[1] == "timeline"]
    assert len(data) == 601
    assert data[0][9].startswith("'=危险公式")
    assert "received_at" in data[0][10]
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    saved = output.read_bytes()
    Path(job.cancel_path).touch()
    assert run_job(job) == 2
    assert output.read_bytes() == saved
    assert not Path(job.tmp_path).exists()


def test_history_export_api_process_artifact_and_filter_validation(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    _seed(paths.ground_unattended_db_path("demo"), 3)
    with TestClient(app) as client:
        invalid = client.post("/api/rail-transit/ground-unattended/history/export", json={"start_at": "invalid"})
        assert invalid.status_code == 422, invalid.text
        invalid_sort = client.get("/api/rail-transit/ground-unattended/history", params={"sort_order": "invalid"})
        assert invalid_sort.status_code == 422
        ascending = client.get("/api/rail-transit/ground-unattended/history", params={"data_type": "timeline", "sort_order": "asc", "page_size": 1})
        assert ascending.status_code == 200, ascending.text
        assert ascending.json()["total"] == 3
        response = client.post("/api/rail-transit/ground-unattended/history/export", json={"sort_order": "asc", "data_type": "timeline", "mr_id": "mr-ct", "mr_role": "CT"})
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]
        deadline = time.monotonic() + 30
        snapshot = {}
        while time.monotonic() < deadline:
            polled = client.get(f"/api/job-center/tasks/{task_id}")
            assert polled.status_code == 200, polled.text
            snapshot = polled.json()
            if snapshot["status"] in {"FAILED", "CANCELLED"}:
                break
            if snapshot["status"] == "COMPLETED" and (snapshot.get("artifact_download") or {}).get("sha256"):
                break
            time.sleep(0.05)
        assert snapshot["status"] == "COMPLETED", snapshot
        artifact = snapshot["artifact_download"]
        assert artifact and artifact["sha256"]
        download = client.get(artifact["api_path"])
        assert download.status_code == 200, download.text
        assert hashlib.sha256(download.content).hexdigest() == artifact["sha256"]
        assert len(list(csv.reader(download.content.decode("utf-8-sig").splitlines()))) >= 4
