from __future__ import annotations

import asyncio

from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import AgentTaskMapping, TrafficSyncState
from netconsole.services.traffic.agent_adapter import AgentSyncOutcome
from netconsole.services.traffic.agent_supervisor import AgentTrafficSupervisor, AgentTrafficSupervisorSettings
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


def _mapping(run_id: str) -> AgentTaskMapping:
    return AgentTaskMapping(
        traffic_run_id=run_id,
        controller_task_id=f"task-{run_id}",
        agent_id="agent-1",
        agent_task_id=f"remote-{run_id}",
        agent_task_type="fping",
        last_remote_status="running",
        sync_state=TrafficSyncState.ACTIVE,
        created_at="2026-07-12T08:00:00Z",
        updated_at="2026-07-12T08:00:00Z",
    )


class FakeRepository:
    def __init__(self, *mappings: AgentTaskMapping) -> None:
        self.mappings = {item.traffic_run_id: item for item in mappings}

    def get_agent_mapping(self, run_id):
        return self.mappings.get(run_id)

    def list_recoverable_agent_mappings(self):
        return list(self.mappings.values())


class FakeAdapter:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.sync_calls: list[str] = []
        self.sync_states: list[tuple[str, TrafficSyncState, str]] = []
        self.fail_sync_calls: list[str] = []
        self.ensure_error: TrafficTestError | None = None
        self.sync_error: TrafficTestError | None = None
        self.terminal = False
        self.delay = 0.0
        self.active = 0
        self.max_active = 0
        self.stop_remote_calls = 0

    def ensure_sync_ready(self, _mapping):
        if self.ensure_error is not None:
            raise self.ensure_error

    async def sync_once(self, mapping, **_kwargs):
        self.sync_calls.append(mapping.traffic_run_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.sync_error is not None:
                raise self.sync_error
            return AgentSyncOutcome(mapping, TaskState.COMPLETED if self.terminal else TaskState.RUNNING, terminal=self.terminal)
        finally:
            self.active -= 1

    def mark_sync_state(self, mapping, state, *, error_code="", error_message=""):
        self.sync_states.append((mapping.traffic_run_id, state, error_code))
        return mapping

    def fail_sync(self, mapping, _error):
        self.fail_sync_calls.append(mapping.traffic_run_id)
        return mapping


def test_supervisor_recovers_and_stops_polling_without_stopping_remote_task() -> None:
    mapping = _mapping("run-1")
    repository = FakeRepository(mapping)
    adapter = FakeAdapter(repository)
    adapter.terminal = True
    supervisor = AgentTrafficSupervisor(
        adapter,
        repository,
        settings=AgentTrafficSupervisorSettings(poll_interval_seconds=0.01),
    )

    async def scenario() -> None:
        await supervisor.start()
        for _ in range(50):
            if adapter.sync_calls:
                break
            await asyncio.sleep(0.01)
        await supervisor.stop()

    asyncio.run(scenario())

    assert adapter.sync_calls == ["run-1"]
    assert adapter.stop_remote_calls == 0
    assert supervisor.running is False


def test_recover_without_token_marks_credential_required_and_does_not_attach() -> None:
    mapping = _mapping("run-credential")
    repository = FakeRepository(mapping)
    adapter = FakeAdapter(repository)
    adapter.ensure_error = TrafficTestError(TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED, "Token 未加载")
    supervisor = AgentTrafficSupervisor(adapter, repository)

    recovered = asyncio.run(supervisor.recover_active_runs())

    assert recovered == ()
    assert adapter.sync_states == [
        ("run-credential", TrafficSyncState.CREDENTIAL_REQUIRED, TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED.value)
    ]
    assert supervisor.detach("run-credential") is False


def test_supervisor_enforces_concurrency_limit() -> None:
    mappings = tuple(_mapping(f"run-{index}") for index in range(5))
    repository = FakeRepository(*mappings)
    adapter = FakeAdapter(repository)
    adapter.delay = 0.03
    adapter.terminal = True
    supervisor = AgentTrafficSupervisor(
        adapter,
        repository,
        settings=AgentTrafficSupervisorSettings(poll_interval_seconds=0.01, max_concurrency=2),
    )

    async def scenario() -> None:
        await supervisor.start()
        for _ in range(100):
            if len(adapter.sync_calls) >= len(mappings):
                break
            await asyncio.sleep(0.01)
        await supervisor.stop()

    asyncio.run(scenario())

    assert set(adapter.sync_calls) == {item.traffic_run_id for item in mappings}
    assert adapter.max_active == 2


def test_offline_error_uses_bounded_backoff() -> None:
    mapping = _mapping("run-offline")
    repository = FakeRepository(mapping)
    adapter = FakeAdapter(repository)
    adapter.sync_error = TrafficTestError(TrafficErrorCode.AGENT_OFFLINE, "Agent 离线", retryable=True)
    supervisor = AgentTrafficSupervisor(
        adapter,
        repository,
        settings=AgentTrafficSupervisorSettings(poll_interval_seconds=0.1, max_backoff_seconds=0.5),
    )
    supervisor.attach(mapping.traffic_run_id)

    asyncio.run(supervisor._poll_one(mapping.traffic_run_id))

    assert adapter.sync_states[-1][1] is TrafficSyncState.AGENT_OFFLINE
    assert supervisor._failures[mapping.traffic_run_id] == 1
    assert supervisor._next_poll[mapping.traffic_run_id] > 0
    assert adapter.fail_sync_calls == []


def test_unknown_remote_state_only_marks_sync_error_and_preserves_task_lifecycle() -> None:
    mapping = _mapping("run-unknown")
    repository = FakeRepository(mapping)
    adapter = FakeAdapter(repository)
    adapter.sync_error = TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "未知远端状态")
    supervisor = AgentTrafficSupervisor(adapter, repository)
    supervisor.attach(mapping.traffic_run_id)

    asyncio.run(supervisor._poll_one(mapping.traffic_run_id))

    assert adapter.sync_states[-1][1] is TrafficSyncState.ERROR
    assert adapter.fail_sync_calls == []
    assert supervisor.detach(mapping.traffic_run_id) is False


def test_supervisor_stop_marks_active_mapping_stale() -> None:
    mapping = _mapping("run-stale")
    repository = FakeRepository(mapping)
    adapter = FakeAdapter(repository)
    supervisor = AgentTrafficSupervisor(adapter, repository)
    supervisor.attach(mapping.traffic_run_id)

    asyncio.run(supervisor.stop())

    assert adapter.sync_states == [("run-stale", TrafficSyncState.STALE, "")]
    assert adapter.stop_remote_calls == 0
