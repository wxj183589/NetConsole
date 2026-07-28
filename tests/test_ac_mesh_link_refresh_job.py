from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.services.ac.mesh_link_refresh_service import AcMeshLinkRefreshApplicationService
from netconsole.services.job_center.handlers import ac_jobs
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.query_service import JobCenterQueryService


class _PreparedProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []

    def start_job(self, job, *, on_complete=None) -> str:
        self.jobs.append(job)
        self.tasks.prepare(job)
        self.tasks.mark_running(job.job_id)
        return job.job_id

    def shutdown(self) -> None:
        return None


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("site-a")
    database = Database(paths.site_db_path("site-a"))
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO devices (
                device_uuid, name, device_vendor, device_type, primary_address,
                ssh_enabled, ssh_username, ssh_password, created_at, updated_at
            ) VALUES ('ac-1', '测试 AC', 'H3C', 'AC', '10.0.0.1', 1, 'admin', 'secret-value',
                      '2026-07-14', '2026-07-14')
            """
        )
        conn.commit()
    return paths


def test_application_service_is_idempotent_and_task_payload_has_no_credentials_or_commands(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    tasks = TaskApplicationService(paths=paths, site_name="site-a")
    adapter = _PreparedProcessAdapter(tasks)
    service = AcMeshLinkRefreshApplicationService(paths, tasks, process_adapter=adapter)  # type: ignore[arg-type]

    first = service.start_refresh(site_name="site-a", controller_id="ac-1", include_switch_history=True)
    second = service.start_refresh(site_name="site-a", controller_id="ac-1", include_switch_history=True)

    assert first.task.status is TaskState.RUNNING
    assert second.task.task_id == first.task.task_id
    assert second.already_running is True
    assert len(adapter.jobs) == 1
    payload = adapter.jobs[0].params
    assert payload["site_name"] == "site-a"
    assert payload["owner"] == "web_ac_mesh_link"
    assert "secret-value" not in str(payload)
    assert not ({"command", "commands", "username", "password"} & payload.keys())
    assert paths.site_tasks_db_path("site-a").is_file()
    assert not paths.site_tasks_db_path("demo").exists()


def test_job_handler_is_registered_in_existing_ac_partition(monkeypatch) -> None:
    expected = {"snapshot_id": 8}
    monkeypatch.setattr(ac_jobs, "run_ac_mesh_link_refresh", lambda _context: expected)
    context = JobContext("task-1", "ac_mesh_link_refresh", {}, None, None, PathResolver())

    assert "ac_mesh_link_refresh" in ac_jobs.HANDLERS
    assert "ac_mesh_link_resident_poll" in ac_jobs.HANDLERS
    assert ac_jobs.ac_mesh_link_refresh(context) == expected


def test_job_center_exposes_mesh_link_result_and_stable_error_code(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    tasks = TaskApplicationService(paths=paths, site_name="site-a")
    adapter = _PreparedProcessAdapter(tasks)
    service = AcMeshLinkRefreshApplicationService(paths, tasks, process_adapter=adapter)  # type: ignore[arg-type]
    started = service.start_refresh(site_name="site-a", controller_id="ac-1")
    repository = tasks.repository("site-a")
    repository.save(
        replace(
            started.task,
            status=TaskState.COMPLETED,
            result={
                "snapshot_id": 7,
                "records_count": 3,
                "raw_output_reference": "files/rail_transit/ac_mesh_link/raw.log",
                "parser_version": "parser/v1",
            },
        )
    )
    detail = JobCenterQueryService(paths).get_task("site-a", started.task.task_id)

    assert detail is not None
    assert detail.snapshot_id == 7
    assert detail.records_count == 3
    assert detail.parser_version == "parser/v1"

    repository.save(replace(started.task, status=TaskState.FAILED, error_message="AC_MESH_LINK_CONNECT_FAILED: 连接失败"))
    failed = JobCenterQueryService(paths).get_task("site-a", started.task.task_id)
    assert failed is not None
    assert failed.error_code == "AC_MESH_LINK_CONNECT_FAILED"
