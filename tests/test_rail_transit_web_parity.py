from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.query_service import OnlineMrQueryService


class _FakeProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs: list[BackgroundJob] = []

    def start_job(self, job: BackgroundJob, **_kwargs) -> str:
        self.jobs.append(job)
        launch = self.tasks.prepare(job)
        self.tasks.mark_running(launch.job.job_id)
        return launch.job.job_id


def _service(tmp_path: Path) -> tuple[RailTransitWebApplicationService, _FakeProcessAdapter, TaskApplicationService, PathResolver]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    service = RailTransitWebApplicationService(paths, tasks, OnlineMrQueryService(paths))
    adapter = _FakeProcessAdapter(tasks)
    service.process_adapter = adapter  # type: ignore[assignment]
    return service, adapter, tasks, paths


def test_mesh_import_stages_controlled_fixture_files_and_task_can_cancel(tmp_path: Path) -> None:
    service, adapter, tasks, paths = _service(tmp_path)
    started = service.start_mesh_import(
        "demo",
        profile={"mr_id": "MR-01", "display_name": "车载 MR-01", "safe_folder_name": "MR-01"},
        uploads=[("..\\raw.log", b"fixture log")],
    )

    assert started.task_type == "mesh_log_import"
    assert started.status == "RUNNING"
    assert adapter.jobs[0].params["files"]
    staged = Path(str(adapter.jobs[0].params["files"][0]))
    assert staged.is_file()
    assert staged.is_relative_to(paths.runtime_cache_dir)
    assert tasks.cancel_task(started.task_id) is True
    assert tasks.get_task(started.task_id).status.value == "STOPPING"


def test_mesh_import_rejects_uncontrolled_file_type(tmp_path: Path) -> None:
    service, _adapter, _tasks, _paths = _service(tmp_path)
    with pytest.raises(RailTransitWebError, match="LOG/TXT/CSV"):
        service.start_mesh_import(
            "demo",
            profile={"mr_id": "MR-01", "display_name": "MR-01", "safe_folder_name": "MR-01"},
            uploads=[("passwords.json", b"no")],
        )


def test_online_mr_report_uses_safe_session_reference_and_task_artifact(tmp_path: Path) -> None:
    service, adapter, _tasks, paths = _service(tmp_path)
    session_dir = paths.online_mr_session_dir("demo", "MR-01", "session-1")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session_meta.json").write_text(
        json.dumps({"session_id": "session-1", "site": "demo", "mr_name": "MR-01", "status": "COMPLETED"}),
        encoding="utf-8",
    )

    task = service.start_online_mr_report("demo", "session-1", "report.xlsx")

    assert task.task_type == "online_mr_report_export"
    assert task.artifact_path.endswith("report.xlsx")
    assert Path(str(adapter.jobs[0].params["session_dir"])) == session_dir
    assert Path(str(adapter.jobs[0].params["output_path"])).is_relative_to(paths.rail_transit_root("demo"))
