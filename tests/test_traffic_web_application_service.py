from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.models.agent import AgentStatus
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import ExecutionTargetKind, TrafficRun, TrafficTestType
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError
from netconsole.services.traffic.event_hub import TrafficEventHub
from netconsole.services.traffic.web_application_service import TrafficWebApplicationService


class FakeTrafficService:
    def __init__(self, runs: list[TrafficRun]) -> None:
        self.events = TrafficEventHub()
        self.runs = {run.traffic_run_id: run for run in runs}
        self.cancel_calls: list[str] = []
        self.retry_calls: list[str] = []
        self.cancel_entered: asyncio.Event | None = None
        self.cancel_release: asyncio.Event | None = None
        self.retry_error: TrafficTestError | None = None

    def list_runs(self, *, limit: int = 2_000, **_kwargs) -> list[TrafficRun]:
        assert limit == 2_000
        return list(self.runs.values())

    def get_run(self, traffic_run_id: str) -> TrafficRun | None:
        return self.runs.get(traffic_run_id)

    async def cancel(self, controller_task_id: str) -> TrafficRun:
        self.cancel_calls.append(controller_task_id)
        if self.cancel_entered is not None:
            self.cancel_entered.set()
        if self.cancel_release is not None:
            await self.cancel_release.wait()
        run = next(run for run in self.runs.values() if run.controller_task_id == controller_task_id)
        stopped = replace(run, status=TaskState.STOPPING)
        self.runs[run.traffic_run_id] = stopped
        return stopped

    async def retry(self, controller_task_id: str) -> TrafficRun:
        self.retry_calls.append(controller_task_id)
        if self.retry_error is not None:
            raise self.retry_error
        previous = next(run for run in self.runs.values() if run.controller_task_id == controller_task_id)
        retried = replace(
            previous,
            traffic_run_id=f"{previous.traffic_run_id}-retry",
            controller_task_id=f"{previous.controller_task_id}-retry",
            status=TaskState.STARTING,
            retry_of_traffic_run_id=previous.traffic_run_id,
        )
        self.runs[retried.traffic_run_id] = retried
        return retried

    def get_events(self, *_args, **_kwargs):
        return []

    def get_ping_samples(self, *_args, **_kwargs):
        return []

    def get_summary(self, _traffic_run_id: str):
        return {}


class FakeAgentService:
    def list_agents(self) -> list[dict[str, object]]:
        return [
            {
                "agent_id": "online",
                "name": "在线 Agent",
                "enabled": True,
                "status": AgentStatus.ONLINE.value,
                "capabilities": {"iperf_client": True},
            },
            {
                "agent_id": "missing-tool",
                "name": "缺工具 Agent",
                "enabled": True,
                "status": AgentStatus.ONLINE.value,
                "capabilities": {},
            },
            {
                "agent_id": "offline",
                "name": "不可达 Agent",
                "enabled": True,
                "status": AgentStatus.OFFLINE.value,
                "capabilities": {"fping": True},
            },
        ]


def _run(
    run_id: str,
    *,
    status: TaskState = TaskState.FAILED,
    created_at: str = "2026-07-01T00:00:00+00:00",
    updated_at: str = "2026-07-01T00:00:00+00:00",
    executor_kind: ExecutionTargetKind = ExecutionTargetKind.LOCAL,
    agent_id: str = "",
) -> TrafficRun:
    return TrafficRun(
        traffic_run_id=run_id,
        controller_task_id=f"task-{run_id}",
        test_type=TrafficTestType.IPERF_CLIENT,
        role="client",
        executor_kind=executor_kind,
        agent_id=agent_id,
        normalized_config={"server_ip": "192.0.2.1"},
        status=status,
        created_at=created_at,
        updated_at=updated_at,
    )


def test_web_service_filters_sorts_then_pages_and_caps_page_size() -> None:
    runs = [
        _run("old", created_at="2026-07-01", updated_at="2026-07-01"),
        _run("new", created_at="2026-07-03", updated_at="2026-07-03"),
        _run("middle", created_at="2026-07-02", updated_at="2026-07-02"),
        _run("running", status=TaskState.RUNNING, created_at="2026-07-04", updated_at="2026-07-04"),
    ]
    runs.extend(_run(f"extra-{index}") for index in range(501))
    service = TrafficWebApplicationService(FakeTrafficService(runs))

    page = service.list_runs(statuses={TaskState.FAILED}, created_after="2026-07-02", limit=1)
    assert [run.traffic_run_id for run in page.items] == ["new"]
    assert page.total == 2
    assert page.has_more is True

    empty = service.list_runs(statuses={TaskState.FAILED}, offset=999, limit=10)
    assert empty.items == []
    assert empty.has_more is False

    capped = service.list_runs(limit=999)
    assert capped.limit == 500
    assert len(capped.items) == 500
    assert capped.has_more is True


def test_web_service_reports_local_capability_and_agent_unavailability() -> None:
    service = TrafficWebApplicationService(FakeTrafficService([]), FakeAgentService())

    targets = service.list_execution_targets()
    assert targets[0].id == "LOCAL"
    assert targets[0].available is True
    assert targets[1].available is True
    assert targets[2].available is False
    assert targets[2].unavailable_reason == "Agent 未报告流量测试能力"
    assert targets[3].available is False
    assert targets[3].unavailable_reason == "Agent 当前不在线"


def test_web_service_cancel_is_idempotent_for_repeated_and_concurrent_calls() -> None:
    traffic = FakeTrafficService([_run("cancel", status=TaskState.RUNNING)])
    traffic.cancel_entered = asyncio.Event()
    traffic.cancel_release = asyncio.Event()
    service = TrafficWebApplicationService(traffic)

    async def run() -> None:
        first = asyncio.create_task(service.cancel_run("cancel"))
        await traffic.cancel_entered.wait()
        second = asyncio.create_task(service.cancel_run("cancel"))
        await asyncio.sleep(0)
        assert traffic.cancel_calls == ["task-cancel"]
        traffic.cancel_release.set()
        assert (await asyncio.gather(first, second))[0].status is TaskState.STOPPING
        await service.cancel_run("cancel")

    asyncio.run(run())
    assert traffic.cancel_calls == ["task-cancel"]


def test_web_service_retries_failed_runs_but_rejects_running_and_preserves_credential_error() -> None:
    failed = _run("failed")
    running = _run("running", status=TaskState.RUNNING)
    traffic = FakeTrafficService([failed, running])
    service = TrafficWebApplicationService(traffic)

    retried = asyncio.run(service.retry_run("failed"))
    assert retried.traffic_run_id == "failed-retry"
    assert retried.retry_of_traffic_run_id == "failed"

    with pytest.raises(TrafficTestError) as running_error:
        asyncio.run(service.retry_run("running"))
    assert running_error.value.code == TrafficErrorCode.INVALID_CONFIG.value
    assert traffic.retry_calls == ["task-failed"]

    traffic.retry_error = TrafficTestError(
        TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED,
        "Agent Token 未加载",
    )
    with pytest.raises(TrafficTestError) as credential_error:
        asyncio.run(service.retry_run("failed"))
    assert credential_error.value.code == TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED.value


def test_traffic_router_keeps_business_orchestration_out_of_the_router() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("src/netconsole/backend/api/traffic_router.py").read_text(
        encoding="utf-8"
    )

    assert "list_agents" not in source
    assert "runs[offset" not in source
    assert "service.cancel(" not in source
    assert "service.retry(" not in source
    assert "AgentControllerService" not in source
