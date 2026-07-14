from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from netconsole.models.api.online_mr_control import OnlineMrWebStartRequestDTO
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.errors import OnlineMrWebControlError
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.web_control_service import OnlineMrWebControlService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


class _ProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs = []
        self.active: set[str] = set()
        self.cancelled: list[str] = []

    def start_job(self, job, *, on_complete=None) -> str:
        del on_complete
        self.jobs.append(job)
        launch = self.tasks.prepare(job)
        self.tasks.mark_running(launch.job.job_id)
        self.active.add(job.job_id)
        return job.job_id

    def cancel_job(self, job_id: str) -> bool:
        self.cancelled.append(job_id)
        if job_id not in self.active:
            return False
        self.active.remove(job_id)
        site = str(self.jobs[0].params["site_name"])
        self.tasks.record_external_event(job_id, "finished", {"result": {"status": "STOPPED"}}, site_name=site)
        return True

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        del timeout
        return job_id not in self.active


def _service(tmp_path: Path, *, enabled: bool = True):
    paths, _db_path = build_rail_transit_base_data_fixture(tmp_path)
    base_query = RailTransitBaseDataQueryService(paths)
    mr = base_query.get_mr("demo", "mr-01-ct")
    assert mr is not None and mr.mr.device_id is not None
    tasks = TaskApplicationService(paths, site_name="demo")
    adapter = _ProcessAdapter(tasks)
    application = OnlineMrApplicationService(
        paths,
        site_name="demo",
        task_service=tasks,
        process_adapter=adapter,
    )
    control = OnlineMrWebControlService(
        paths,
        application,
        base_query,
        OnlineMrQueryService(paths),
        enabled=enabled,
    )
    return control, application, adapter, mr.mr.device_id


def _request(device_id: int, **overrides) -> OnlineMrWebStartRequestDTO:
    payload = {
        "site_id": "demo",
        "device_id": device_id,
        "mr_id": "mr-01-ct",
        "executor": "LOCAL",
        "duration_minutes": 1,
        "fping": {"enabled": True, "target": "127.0.0.1"},
    }
    payload.update(overrides)
    return OnlineMrWebStartRequestDTO.model_validate(payload)


def test_web_control_resolves_formal_mr_and_repository_credentials(tmp_path: Path) -> None:
    control, _application, adapter, device_id = _service(tmp_path)

    started = control.start(_request(device_id), current_site_id="demo")
    duplicate = control.start(_request(device_id), current_site_id="demo")

    assert duplicate.operation_id == started.operation_id
    assert len(adapter.jobs) == 1
    config = adapter.jobs[0].params["config"]
    assert config["mr_id"] == "mr-01-ct"
    assert config["mr_name"] == "列车01-MR-CT"
    assert config["username"] == "private-user"
    assert config["password"] == "private-pass"
    assert adapter.jobs[0].params["owner"] == "web_local"
    assert "private-pass" not in json.dumps(started.model_dump(mode="json"), ensure_ascii=False)
    task = control.application_service.task_service.repository("demo").get(started.task_id)
    assert task is not None and task.owner == "web_local"
    assert "private-pass" not in json.dumps(task.result, ensure_ascii=False)
    assert not control.paths.site_tasks_db_path("site-a").exists()


def test_web_control_normal_stop_is_idempotent_and_uses_application_service(tmp_path: Path) -> None:
    control, application, adapter, device_id = _service(tmp_path)
    started = control.start(_request(device_id), current_site_id="demo")

    stopped = control.stop(started.operation_id, site_id="demo")
    stopped_again = control.stop(started.operation_id, site_id="demo")

    assert stopped.state == "stopped"
    assert stopped_again.operation_id == stopped.operation_id
    assert adapter.cancelled == [started.operation_id]
    assert application.get_operation(started.operation_id, site_id="demo").phase == "TERMINAL"


def test_web_control_rejects_disabled_site_mismatch_and_unbound_mr(tmp_path: Path) -> None:
    disabled, _application, _adapter, device_id = _service(tmp_path / "disabled", enabled=False)
    tasks_db = disabled.paths.site_tasks_db_path("demo")
    before = hashlib.sha256(tasks_db.read_bytes()).hexdigest()
    assert disabled.status("demo").operations == []
    assert hashlib.sha256(tasks_db.read_bytes()).hexdigest() == before
    with pytest.raises(OnlineMrWebControlError, match="默认关闭"):
        disabled.start(_request(device_id), current_site_id="demo")

    control, _application, _adapter, device_id = _service(tmp_path / "enabled")
    with pytest.raises(OnlineMrWebControlError, match="当前局点"):
        control.start(_request(device_id), current_site_id="other")
    with pytest.raises(OnlineMrWebControlError, match="不存在或未绑定"):
        control.start(_request(device_id, mr_id="missing"), current_site_id="demo")


def test_web_control_rejects_non_ip_traffic_targets(tmp_path: Path) -> None:
    control, _application, _adapter, device_id = _service(tmp_path)
    with pytest.raises(OnlineMrWebControlError, match="有效 IP"):
        control.start(
            _request(device_id, iperf={"enabled": True, "server_ip": "not-an-ip"}),
            current_site_id="demo",
        )


def test_web_control_start_failure_does_not_persist_or_return_repository_password(tmp_path: Path) -> None:
    control, application, adapter, device_id = _service(tmp_path)

    def fail_start(*_args, **_kwargs):
        raise RuntimeError("launch failed: private-pass")

    adapter.start_job = fail_start  # type: ignore[method-assign]
    with pytest.raises(OnlineMrWebControlError) as raised:
        control.start(_request(device_id), current_site_id="demo")

    mapping = application.repository("demo").list(limit=1)[0]
    assert "private-pass" not in raised.value.message
    assert "private-pass" not in mapping.error_summary
    assert "<redacted>" in mapping.error_summary
