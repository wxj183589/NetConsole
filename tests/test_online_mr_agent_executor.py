from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import (
    OnlineMrAgentStatus,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentTaskStatusResponse,
    OnlineMrAgentToolsStatus,
)
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
)
from netconsole.models.online_mr_models import FpingConfig, OnlineMrConnectionConfig, OnlineMrTaskToggles
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import OnlineMrTaskSessionRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.agent_download_service import OnlineMrAgentDownloadImportResult
from netconsole.services.online_mr.agent_executor import OnlineMrAgentExecutor, OnlineMrAgentExecutorSettings
from netconsole.services.online_mr.agent_http_client import OnlineMrAgentClientError
from netconsole.services.online_mr.errors import OnlineMrApplicationError, OnlineMrApplicationErrorCode


class FakeAgentController:
    def __init__(self) -> None:
        self.remote = OnlineMrAgentTaskStatusResponse(
            task_id="agent-task-1",
            task_type="mr_realtime_collect",
            status=OnlineMrAgentStatus.RUNNING,
            start_time="2026-07-15T01:00:00+00:00",
            params={"target": {"host": "192.0.2.7"}},
        )
        self.statuses: list[OnlineMrAgentTaskStatusResponse | BaseException] = []
        self.stop_calls: list[str] = []
        self.started_password = ""
        self.import_success = True
        self.repository: OnlineMrTaskSessionRepository | None = None
        self.task_service: TaskApplicationService | None = None

    async def ping_agent(self, profile_id: str):
        assert profile_id == "profile-1"
        return object()

    async def get_agent_status(self, profile_id: str) -> OnlineMrAgentSystemStatus:
        assert profile_id == "profile-1"
        return OnlineMrAgentSystemStatus(
            agent_id="agent-a",
            version="0.2.0-win-agent",
            os="windows",
            arch="amd64",
        )

    async def get_agent_tools(self, profile_id: str) -> OnlineMrAgentToolsStatus:
        del profile_id
        return OnlineMrAgentToolsStatus.model_validate(
            {
                "mr_collector": {"exists": True, "ready": True},
                "fping": {"exists": True, "ready": True},
                "iperf3": {"exists": True, "ready": True},
            }
        )

    async def start_collection(self, profile_id: str, request):
        assert profile_id == "profile-1"
        self.started_password = request.target.password.get_secret_value()
        return self.remote

    async def get_task(self, profile_id: str, task_id: str):
        assert profile_id == "profile-1" and task_id == "agent-task-1"
        value = self.statuses.pop(0) if self.statuses else self.remote
        if isinstance(value, BaseException):
            raise value
        return value

    async def stop_collection(self, profile_id: str, task_id: str):
        assert profile_id == "profile-1"
        self.stop_calls.append(task_id)
        return self.remote.model_copy(update={"status": OnlineMrAgentStatus.STOPPING})

    async def list_agent_packages(self, profile_id: str):
        del profile_id
        return ()

    async def download_import_package(self, package_id: str, **kwargs):
        del package_id
        if not self.import_success:
            return OnlineMrAgentDownloadImportResult(
                False,
                error_code=OnlineMrApplicationErrorCode.AGENT_PACKAGE_INVALID.value,
                errors=("package invalid",),
            )
        assert self.repository is not None and self.task_service is not None
        mapping = self.repository.get_by_task(str(kwargs["controller_task_id"]))
        assert mapping is not None
        now = datetime.now(UTC).isoformat()
        self.repository.save(
            replace(
                mapping,
                session_id="session-1",
                remote_session_id="session-1",
                phase=OnlineMrPhase.TERMINAL,
                mapping_state=OnlineMrMappingState.TERMINAL,
                updated_at=now,
                terminal_at=now,
                ended_at=now,
            )
        )
        self.task_service.record_external_event(
            mapping.controller_task_id,
            "finished",
            {"result": {"session_id": "session-1"}},
            site_name=mapping.site_id,
        )
        return OnlineMrAgentDownloadImportResult(
            True,
            downloaded=True,
            imported=True,
            task_id=mapping.controller_task_id,
            session_id="session-1",
        )


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("site-a")
    return paths


def _request() -> OnlineMrStartRequest:
    config = OnlineMrConnectionConfig(
        site="site-a",
        mr_id="7",
        mr_name="MR-07",
        safe_mr_name="MR-07__7",
        device_id=7,
        device_name="列车07 MR",
        host="192.0.2.7",
        username="operator",
        password="secret-password",
        fping=FpingConfig(enabled=False),
        tasks=OnlineMrTaskToggles(
            mesh_link=False,
            channel_busy=False,
            ap_radio_statistics=False,
            switch_history=False,
            interface_rate=False,
            wireless_status=False,
        ),
    )
    return OnlineMrStartRequest(
        site_id="site-a",
        device_id=7,
        device_name="列车07 MR",
        mr_name="MR-07",
        config=config,
        executor_kind=OnlineMrExecutorKind.AGENT,
        agent_id="profile-1",
    )


def _executor(tmp_path: Path, *, enabled: bool = True):
    paths = _paths(tmp_path)
    tasks = TaskApplicationService(paths, site_name="site-a")
    repository = OnlineMrTaskSessionRepository(paths.site_tasks_db_path("site-a"), site_id="site-a")
    controller = FakeAgentController()
    controller.repository = repository
    controller.task_service = tasks
    executor = OnlineMrAgentExecutor(
        controller,  # type: ignore[arg-type]
        tasks,
        lambda _site: repository,
        lambda: ["site-a"],
        lambda _request: True,
        settings=OnlineMrAgentExecutorSettings(
            enabled=enabled,
            poll_interval_seconds=60,
            status_failure_threshold=2,
        ),
    )
    return executor, controller, repository, tasks


def test_agent_executor_disabled_by_default_contract(tmp_path: Path) -> None:
    executor, _controller, _repository, _tasks = _executor(tmp_path, enabled=False)
    with pytest.raises(OnlineMrApplicationError) as exc_info:
        executor.start(_request())
    assert exc_info.value.code == OnlineMrApplicationErrorCode.AGENT_EXECUTOR_DISABLED


def test_agent_start_persists_remote_ids_but_never_password(tmp_path: Path) -> None:
    executor, controller, repository, tasks = _executor(tmp_path)
    try:
        mapping = executor.start(_request())
    finally:
        executor.close()
    assert mapping.agent_profile_id == "profile-1"
    assert mapping.agent_id == "agent-a"
    assert mapping.agent_task_id == "agent-task-1"
    assert controller.started_password == "secret-password"
    assert tasks.repository("site-a").get(mapping.controller_task_id).status is TaskState.RUNNING
    assert b"secret-password" not in repository.db_path.read_bytes()


def test_agent_normal_stop_is_idempotent_at_controller_boundary(tmp_path: Path) -> None:
    executor, controller, repository, _tasks = _executor(tmp_path)
    mapping = executor.start(_request())
    stopped = executor.stop(mapping, stop_reason="user_stop")
    assert stopped.stop_reason == "user_stop"
    assert controller.stop_calls == ["agent-task-1"]
    terminal = repository.save(
        replace(stopped, phase=OnlineMrPhase.TERMINAL, mapping_state=OnlineMrMappingState.TERMINAL)
    )
    assert executor.stop(terminal, stop_reason="user_stop") == terminal
    assert controller.stop_calls == ["agent-task-1"]
    executor.close()


def test_agent_status_retry_becomes_remote_unknown_without_terminalizing(tmp_path: Path) -> None:
    executor, controller, _repository, tasks = _executor(tmp_path)
    mapping = executor.start(_request())
    error = OnlineMrAgentClientError(OnlineMrApplicationErrorCode.AGENT_TIMEOUT, "timeout")
    controller.statuses = [error, error]
    first = executor.sync_once(mapping)
    second = executor.sync_once(first)
    assert first.consecutive_status_failures == 1
    assert second.error_code == OnlineMrApplicationErrorCode.AGENT_REMOTE_STATUS_UNKNOWN
    assert second.mapping_state is OnlineMrMappingState.LINKED
    assert tasks.repository("site-a").get(mapping.controller_task_id).status is TaskState.RUNNING
    executor.close()


def test_agent_terminal_download_import_finishes_controller_task(tmp_path: Path) -> None:
    executor, controller, _repository, tasks = _executor(tmp_path)
    mapping = executor.start(_request())
    controller.statuses = [
        controller.remote.model_copy(
            update={"status": OnlineMrAgentStatus.COMPLETED, "package_id": "package-1"}
        )
    ]
    final = executor.sync_once(mapping)
    assert final.mapping_state is OnlineMrMappingState.TERMINAL
    assert final.session_id == "session-1"
    assert final.remote_package_id == "package-1"
    assert tasks.repository("site-a").get(mapping.controller_task_id).status is TaskState.COMPLETED
    executor.close()


def test_agent_package_import_failure_is_terminal_and_preserves_package_id(tmp_path: Path) -> None:
    executor, controller, _repository, tasks = _executor(tmp_path)
    controller.import_success = False
    mapping = executor.start(_request())
    controller.statuses = [
        controller.remote.model_copy(
            update={"status": OnlineMrAgentStatus.COMPLETED, "package_id": "package-1"}
        )
    ]
    final = executor.sync_once(mapping)
    assert final.mapping_state is OnlineMrMappingState.TERMINAL
    assert final.remote_package_id == "package-1"
    assert final.error_code == OnlineMrApplicationErrorCode.AGENT_PACKAGE_INVALID
    assert tasks.repository("site-a").get(mapping.controller_task_id).status is TaskState.FAILED
    executor.close()


def test_agent_task_not_found_is_terminal_and_not_revived(tmp_path: Path) -> None:
    executor, controller, _repository, _tasks = _executor(tmp_path)
    mapping = executor.start(_request())
    controller.statuses = [
        OnlineMrAgentClientError(
            OnlineMrApplicationErrorCode.AGENT_TASK_NOT_FOUND,
            "not found",
            status_code=404,
        )
    ]
    terminal = executor.sync_once(mapping)
    assert terminal.mapping_state is OnlineMrMappingState.TERMINAL
    assert executor.sync_once(terminal) == terminal
    executor.close()


def test_agent_recovery_enforces_persisted_deadline_without_browser(tmp_path: Path) -> None:
    executor, controller, repository, _tasks = _executor(tmp_path)
    mapping = executor.start(_request())
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    repository.save(replace(mapping, deadline_at=past))
    executor.close()

    recovered = OnlineMrAgentExecutor(
        controller,  # type: ignore[arg-type]
        controller.task_service,
        lambda _site: repository,
        lambda: ["site-a"],
        lambda _request: True,
        settings=OnlineMrAgentExecutorSettings(enabled=True, poll_interval_seconds=60),
    )
    try:
        rows = recovered.recover("site-a")
    finally:
        recovered.close()
    assert rows[0].phase in {OnlineMrPhase.STOPPING_COLLECTION, OnlineMrPhase.STOPPING_TRAFFIC}
    assert controller.stop_calls == ["agent-task-1"]


def test_agent_and_local_active_mapping_are_mutually_exclusive(tmp_path: Path) -> None:
    executor, _controller, repository, _tasks = _executor(tmp_path)
    request = _request()
    local = executor.start(request)
    with pytest.raises(OnlineMrApplicationError) as exc_info:
        executor.start(request)
    assert exc_info.value.code == OnlineMrApplicationErrorCode.MAPPING_CONFLICT
    assert repository.get_by_task(local.controller_task_id) is not None
    executor.close()
