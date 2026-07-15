from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.agent import AgentAuthenticationType
from netconsole.models.api.online_mr_control import OnlineMrWebStartRequestDTO
from netconsole.models.online_mr_application import OnlineMrMappingState
from netconsole.models.task_state import TaskState
from netconsole.services.agent.controller import (
    AgentControllerService,
    AgentControllerSettings,
)
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.online_mr.agent_controller_service import (
    OnlineMrAgentControllerService,
)
from netconsole.services.online_mr.agent_executor import (
    OnlineMrAgentExecutor,
    OnlineMrAgentExecutorSettings,
)
from netconsole.services.online_mr.agent_web_control_service import (
    OnlineMrAgentWebControlService,
)
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade
from netconsole.services.online_mr.errors import (
    OnlineMrApplicationError,
    OnlineMrApplicationErrorCode,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.web_control_service import OnlineMrWebControlService
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from support.fake_online_mr_agent import FAKE_AGENT_TOKEN, FakeOnlineMrAgent


@dataclass
class MutableClock:
    value: datetime = datetime(2026, 7, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


@dataclass
class AcceptanceStack:
    app: object
    application: OnlineMrApplicationService
    executor: OnlineMrAgentExecutor
    agent_controller: OnlineMrAgentControllerService
    profile_service: AgentControllerService
    profile_id: str
    device_id: int
    clock: MutableClock
    local_control: OnlineMrWebControlService


class PassiveLocalProcessAdapter:
    """只登记正式 LOCAL Task，不启动任何设备采集进程。"""

    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks

    def start_job(self, job, *, on_complete=None) -> str:
        del on_complete
        launch = self.tasks.prepare(job)
        self.tasks.mark_running(launch.job.job_id)
        return job.job_id

    def cancel_job(self, _job_id: str) -> bool:
        return True

    def wait(self, _job_id: str, timeout: float | None = None) -> bool:
        del timeout
        return False


@contextmanager
def _acceptance_stack(
    tmp_path: Path,
    fake: FakeOnlineMrAgent,
    *,
    clock: MutableClock | None = None,
) -> Iterator[AcceptanceStack]:
    paths, _ = build_rail_transit_base_data_fixture(tmp_path)
    base_query = RailTransitBaseDataQueryService(paths)
    mr = base_query.get_mr("demo", "mr-01-ct")
    assert mr is not None and mr.mr.device_id is not None
    profile_service = AgentControllerService(
        paths=paths,
        site_name="demo",
        settings=AgentControllerSettings(health_check_enabled=False),
    )
    profile = profile_service.create_agent(
        name="回环 Fake Agent",
        base_url=fake.base_url,
        enabled=True,
        authentication_type=AgentAuthenticationType.TOKEN,
        token=FAKE_AGENT_TOKEN,
    )
    agent_controller = OnlineMrAgentControllerService(
        paths,
        profile_controller=profile_service,
    )
    tasks = TaskApplicationService(paths, site_name="demo")
    holder: dict[str, OnlineMrApplicationService] = {}
    selected_clock = clock or MutableClock()
    executor = OnlineMrAgentExecutor(
        agent_controller,
        tasks,
        lambda site: holder["application"].repository(site),
        lambda: ["demo"],
        lambda request: holder["application"]._device_identity_matches(request),
        settings=OnlineMrAgentExecutorSettings(
            enabled=True,
            poll_interval_seconds=60,
            status_failure_threshold=2,
        ),
        clock=selected_clock,
    )
    application = OnlineMrApplicationService(
        paths,
        site_name="demo",
        task_service=tasks,
        process_adapter=PassiveLocalProcessAdapter(tasks),  # type: ignore[arg-type]
        agent_executor=executor,
    )
    holder["application"] = application
    query = OnlineMrQueryService(paths)
    local_control = OnlineMrWebControlService(
        paths,
        application,
        base_query,
        query,
        enabled=False,
    )
    agent_web = OnlineMrAgentWebControlService(
        paths,
        application,
        local_control,
        query,
        agent_controller,
        enabled=True,
    )
    app = create_app(
        RuntimeMode.DESKTOP,
        paths=paths,
        agent_service=profile_service,
        task_service=tasks,
        frontend_dist=tmp_path / "missing-dist",
        desktop_session_token="desktop-test-token",
        online_mr_application_service=application,
        online_mr_web_control_service=local_control,
        online_mr_agent_web_control_service=agent_web,
        online_mr_agent_executor_enabled=True,
    )
    app.state.online_mr_api_facade = OnlineMrApiFacade(paths, query, local_control, agent_web)
    try:
        yield AcceptanceStack(
            app=app,
            application=application,
            executor=executor,
            agent_controller=agent_controller,
            profile_service=profile_service,
            profile_id=str(profile["agent_id"]),
            device_id=int(mr.mr.device_id),
            clock=selected_clock,
            local_control=local_control,
        )
    finally:
        application.close()


def _authorized_client(
    app: object, *, base_url: str = "http://127.0.0.1"
) -> TestClient:
    client = TestClient(app, base_url=base_url)  # type: ignore[arg-type]
    response = client.post(
        "/__desktop_session",
        data={"token": "desktop-test-token"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


def _payload(stack: AcceptanceStack, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "site_id": "demo",
        "device_id": stack.device_id,
        "mr_id": "mr-01-ct",
        "agent_profile_id": stack.profile_id,
        "executor": "AGENT",
        "duration_minutes": 0,
    }
    value.update(changes)
    return value


def test_fake_agent_web_full_loop_uses_formal_http_download_and_import(
    tmp_path: Path,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        with _authorized_client(stack.app) as client:
            capabilities = client.get("/api/rail-transit/online-mr-agent/capabilities")
            readiness = client.get(
                f"/api/rail-transit/online-mr-agent/profiles/{stack.profile_id}/readiness"
            )
            started = client.post(
                "/api/rail-transit/online-mr-agent/start",
                json=_payload(stack),
            )
            duplicate = client.post(
                "/api/rail-transit/online-mr-agent/start",
                json=_payload(stack),
            )
            stopped = client.post(
                f"/api/rail-transit/online-mr-agent/{started.json()['operation_id']}/stop"
            )

        assert (
            capabilities.status_code
            == readiness.status_code
            == started.status_code
            == 200
        )
        assert capabilities.json()["agent_executor_enabled"] is True
        assert capabilities.json()["profiles"][0]["address_display"].startswith(
            "http://***:"
        )
        assert fake.base_url not in capabilities.text
        assert FAKE_AGENT_TOKEN not in capabilities.text
        assert readiness.json()["ready"] is True
        assert duplicate.json()["operation_id"] == started.json()["operation_id"]
        assert fake.start_calls == 1 and fake.stop_calls == 1
        assert stopped.json()["state"] == "stopped"
        assert stopped.json()["session_id"] == fake.session_id
        assert stopped.json()["remote_package_id"] == fake.package_id
        assert stopped.json()["data_integrity"] == "complete"
        assert (
            FAKE_AGENT_TOKEN not in stopped.text and "private-pass" not in stopped.text
        )
        assert ("POST", "/api/v1/mr/collect/start") in fake.routes
        assert ("POST", f"/api/v1/tasks/{fake.task_id}/stop") in fake.routes
        assert ("GET", f"/api/v1/packages/{fake.package_id}/download") in fake.routes
        mapping = stack.application.repository("demo").get_by_task(
            started.json()["operation_id"]
        )
        assert (
            mapping is not None
            and mapping.mapping_state is OnlineMrMappingState.TERMINAL
        )
        assert mapping.session_id == fake.session_id
        task = stack.application.task_service.repository("demo").get(
            mapping.controller_task_id
        )
        assert task is not None and task.status is TaskState.COMPLETED
        assert (
            b"private-pass"
            not in stack.application.paths.site_tasks_db_path("demo").read_bytes()
        )
        assert (
            FAKE_AGENT_TOKEN.encode()
            not in stack.application.paths.site_tasks_db_path("demo").read_bytes()
        )


def test_duration_is_controller_driven_by_injected_clock_without_browser(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    with (
        FakeOnlineMrAgent() as fake,
        _acceptance_stack(tmp_path, fake, clock=clock) as stack,
    ):
        with _authorized_client(stack.app) as client:
            started = client.post(
                "/api/rail-transit/online-mr-agent/start",
                json=_payload(stack, duration_minutes=1),
            ).json()
        mapping = stack.application.repository("demo").get_by_task(
            started["operation_id"]
        )
        assert mapping is not None
        clock.value += timedelta(minutes=2)
        final = stack.executor.sync_once(mapping)
        assert final.mapping_state is OnlineMrMappingState.TERMINAL
        assert final.stop_reason == "duration_reached"
        assert fake.stop_calls == 1


def test_transient_status_failure_recovers_and_clears_failure_counter(
    tmp_path: Path,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        with _authorized_client(stack.app) as client:
            started = client.post(
                "/api/rail-transit/online-mr-agent/start", json=_payload(stack)
            ).json()
        mapping = stack.application.repository("demo").get_by_task(
            started["operation_id"]
        )
        assert mapping is not None
        fake.status_failures_remaining = 1
        failed_poll = stack.executor.sync_once(mapping)
        degraded = stack.app.state.online_mr_agent_web_control_service.get_operation(  # type: ignore[attr-defined]
            mapping.controller_task_id,
            site_id="demo",
        )
        recovered = stack.executor.sync_once(failed_poll)
        assert failed_poll.consecutive_status_failures == 1
        assert degraded.state == "remote_status_degraded"
        assert recovered.consecutive_status_failures == 0
        assert recovered.error_code == ""


def test_service_restart_recovers_remote_task_without_starting_another(
    tmp_path: Path,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        with _authorized_client(stack.app) as client:
            started = client.post(
                "/api/rail-transit/online-mr-agent/start", json=_payload(stack)
            ).json()
        stack.application.close()
        holder: dict[str, OnlineMrApplicationService] = {}
        recovered_executor = OnlineMrAgentExecutor(
            stack.agent_controller,
            stack.application.task_service,
            lambda site: holder["application"].repository(site),
            lambda: ["demo"],
            lambda request: holder["application"]._device_identity_matches(request),
            settings=OnlineMrAgentExecutorSettings(
                enabled=True,
                poll_interval_seconds=60,
                status_failure_threshold=2,
            ),
            clock=stack.clock,
        )
        recovered_application = OnlineMrApplicationService(
            stack.application.paths,
            site_name="demo",
            task_service=stack.application.task_service,
            process_adapter=PassiveLocalProcessAdapter(stack.application.task_service),  # type: ignore[arg-type]
            agent_executor=recovered_executor,
        )
        holder["application"] = recovered_application
        try:
            recovered = recovered_application.recover_mappings(site_id="demo")
            assert recovered[0].controller_task_id == started["operation_id"]
            assert recovered[0].last_remote_status == "running"
            final = recovered_application.stop_operation(
                started["operation_id"],
                site_id="demo",
                stop_reason="restart_acceptance_stop",
            )
            assert final.mapping_state is OnlineMrMappingState.TERMINAL
            assert final.session_id == fake.session_id
            assert fake.start_calls == 1 and fake.stop_calls == 1
        finally:
            recovered_application.close()


def test_local_and_agent_starts_are_mutually_exclusive_at_application_boundary(
    tmp_path: Path,
) -> None:
    with (
        FakeOnlineMrAgent() as fake,
        _acceptance_stack(tmp_path / "local-first", fake) as stack,
    ):
        local_request = stack.local_control.build_start_request(
            OnlineMrWebStartRequestDTO(
                site_id="demo",
                device_id=stack.device_id,
                mr_id="mr-01-ct",
                executor="LOCAL",
            )
        )
        stack.application.start_local_collection(local_request)
        with _authorized_client(stack.app) as client:
            rejected = client.post(
                "/api/rail-transit/online-mr-agent/start", json=_payload(stack)
            )
        assert rejected.status_code == 409
        assert fake.start_calls == 0

    with (
        FakeOnlineMrAgent() as fake,
        _acceptance_stack(tmp_path / "agent-first", fake) as stack,
    ):
        with _authorized_client(stack.app) as client:
            client.post("/api/rail-transit/online-mr-agent/start", json=_payload(stack))
        local_request = stack.local_control.build_start_request(
            OnlineMrWebStartRequestDTO(
                site_id="demo",
                device_id=stack.device_id,
                mr_id="mr-01-ct",
                executor="LOCAL",
            )
        )
        with pytest.raises(OnlineMrApplicationError) as raised:
            stack.application.start_local_collection(local_request)
        assert raised.value.code == OnlineMrApplicationErrorCode.MAPPING_CONFLICT


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("invalid", OnlineMrApplicationErrorCode.AGENT_PACKAGE_INVALID.value),
        (
            "session_mismatch",
            OnlineMrApplicationErrorCode.AGENT_SESSION_ID_MISMATCH.value,
        ),
    ],
)
def test_fake_agent_package_failures_reach_web_terminal_state(
    tmp_path: Path,
    mode: str,
    expected_code: str,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        fake.package_mode = mode
        with _authorized_client(stack.app) as client:
            started = client.post(
                "/api/rail-transit/online-mr-agent/start", json=_payload(stack)
            ).json()
            stopped = client.post(
                f"/api/rail-transit/online-mr-agent/{started['operation_id']}/stop"
            )
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "failed"
        assert stopped.json()["error_code"] == expected_code


def test_fake_http_import_conflict_is_reported_without_manual_task_finalization(
    tmp_path: Path,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        with _authorized_client(stack.app) as client:
            started = client.post(
                "/api/rail-transit/online-mr-agent/start", json=_payload(stack)
            ).json()
            client.post(
                f"/api/rail-transit/online-mr-agent/{started['operation_id']}/stop"
            )
        fake.package_id = "fake-package-2"
        fake.package_marker = "different evidence\n"
        result = asyncio.run(
            stack.agent_controller.download_import_package(
                fake.package_id,
                site_id="demo",
                profile_id=stack.profile_id,
                device_id=stack.device_id,
                device_name="列车01-MR-CT",
                mr_id="mr-01-ct",
                mr_name="列车01-MR-CT",
                expected_session_id=fake.session_id,
                agent_task_id=fake.task_id,
                agent_id=fake.agent_id,
            )
        )
        assert not result.success and result.conflict
        assert (
            result.error_code
            == OnlineMrApplicationErrorCode.AGENT_PACKAGE_CONFLICT.value
        )


def test_agent_routes_require_loopback_cookie_and_reject_forbidden_fields(
    tmp_path: Path,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        with TestClient(stack.app, base_url="http://127.0.0.1") as client:  # type: ignore[arg-type]
            unauthorized = client.get("/api/rail-transit/online-mr-agent/capabilities")
            session = client.post(
                "/__desktop_session",
                data={"token": "desktop-test-token"},
                follow_redirects=False,
            )
            assert session.status_code == 303
            non_loopback = client.get(
                "http://localhost/api/rail-transit/online-mr-agent/capabilities",
                headers={"Cookie": "netconsole_desktop_session=desktop-test-token"},
            )
            for field in (
                "username",
                "password",
                "command",
                "commands",
                "output_dir",
                "database_path",
                "agent_url",
                "token",
            ):
                response = client.post(
                    "/api/rail-transit/online-mr-agent/start",
                    json={**_payload(stack), field: "secret-value"},
                )
                assert response.status_code == 422
                assert "secret-value" not in response.text
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "ONLINE_MR_WEB_AUTH_REQUIRED"
        assert non_loopback.status_code == 403


def test_agent_web_capability_and_write_are_disabled_without_backend_flag(
    tmp_path: Path,
) -> None:
    with FakeOnlineMrAgent() as fake, _acceptance_stack(tmp_path, fake) as stack:
        stack.app.state.online_mr_agent_web_control_service.enabled = False  # type: ignore[attr-defined]
        with _authorized_client(stack.app) as client:
            capability = client.get("/api/rail-transit/online-mr-agent/capabilities")
            rejected = client.post(
                "/api/rail-transit/online-mr-agent/start",
                json=_payload(stack),
            )
        assert capability.status_code == 200
        assert capability.json()["agent_executor_enabled"] is False
        assert rejected.status_code == 403
        assert fake.start_calls == 0


def test_agent_route_surface_has_no_destructive_or_arbitrary_actions() -> None:
    from netconsole.backend.api.online_mr_agent_control_router import router

    routes = {
        (route.path, frozenset(route.methods or set())) for route in router.routes
    }
    assert routes == {
        ("/rail-transit/online-mr-agent/capabilities", frozenset({"GET"})),
        ("/rail-transit/online-mr-agent/profiles", frozenset({"GET"})),
        (
            "/rail-transit/online-mr-agent/profiles/{profile_id}/readiness",
            frozenset({"GET"}),
        ),
        ("/rail-transit/online-mr-agent/status", frozenset({"GET"})),
        ("/rail-transit/online-mr-agent/{operation_id}", frozenset({"GET"})),
        ("/rail-transit/online-mr-agent/start", frozenset({"POST"})),
        ("/rail-transit/online-mr-agent/{operation_id}/stop", frozenset({"POST"})),
    }
