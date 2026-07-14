from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    AgentTaskMapping,
    ExecutionTargetDTO,
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficRun,
    TrafficSyncState,
    TrafficTestType,
    TcpPortTestConfig,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfServerConfig
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


class FakeLocalAdapter:
    def __init__(self, repository: TrafficRunRepository) -> None:
        self.repository = repository
        self.started: list[tuple[TrafficTestType, str]] = []
        self.cancelled: list[str] = []

    def _start(self, run: TrafficRun) -> str:
        self.started.append((run.test_type, run.traffic_run_id))
        self.repository.save(replace(run, status=TaskState.STARTING, updated_at=utc_now_iso()))
        return run.controller_task_id

    def start_iperf_server(self, run: TrafficRun, _config: object) -> str:
        return self._start(run)

    def start_iperf_client(self, run: TrafficRun, _config: object) -> str:
        return self._start(run)

    def start_high_frequency_ping(self, run: TrafficRun, _config: object) -> str:
        return self._start(run)

    def start_tcp_port_test(self, run: TrafficRun, _config: object) -> str:
        return self._start(run)

    def cancel(self, controller_task_id: str) -> bool:
        self.cancelled.append(controller_task_id)
        run = self.repository.get_by_controller_task(controller_task_id)
        if run is not None and run.status not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            self.repository.save(replace(run, status=TaskState.STOPPING, updated_at=utc_now_iso()))
        return True


class FakeAgentAdapter:
    def __init__(self, repository: TrafficRunRepository) -> None:
        self.repository = repository
        self.validated: list[tuple[str, TrafficTestType]] = []
        self.started: list[str] = []
        self.stopped: list[str] = []

    async def validate_target(self, agent_id: str, test_type: TrafficTestType) -> None:
        self.validated.append((agent_id, test_type))

    async def _start(self, run: TrafficRun, agent_task_type: str) -> AgentTaskMapping:
        self.started.append(run.traffic_run_id)
        now = utc_now_iso()
        mapping = AgentTaskMapping(
            traffic_run_id=run.traffic_run_id,
            controller_task_id=run.controller_task_id,
            agent_id=run.agent_id,
            agent_task_id=f"remote-{run.traffic_run_id}",
            agent_task_type=agent_task_type,
            created_at=now,
            updated_at=now,
        )
        self.repository.save_agent_mapping(mapping)
        self.repository.save(replace(run, status=TaskState.STARTING, updated_at=now))
        return mapping

    async def start_iperf_server(self, run: TrafficRun, _config: object) -> AgentTaskMapping:
        return await self._start(run, "iperf_server")

    async def start_iperf_client(self, run: TrafficRun, _config: object) -> AgentTaskMapping:
        return await self._start(run, "iperf_client")

    async def start_high_frequency_ping(self, run: TrafficRun, _config: object) -> AgentTaskMapping:
        return await self._start(run, "fping")

    async def start_tcp_port_test(self, run: TrafficRun, _config: object) -> AgentTaskMapping:
        return await self._start(run, "ping_probe")

    async def stop(self, mapping: AgentTaskMapping) -> None:
        self.stopped.append(mapping.agent_task_id)


class FakeSupervisor:
    def __init__(self) -> None:
        self.attached: list[str] = []

    def attach(self, traffic_run_id: str) -> None:
        self.attached.append(traffic_run_id)


def _service(tmp_path: Path):
    paths = PathResolver(tmp_path)
    repository = TrafficRunRepository(paths.traffic_runs_db_path("demo"))
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    local = FakeLocalAdapter(repository)
    agent = FakeAgentAdapter(repository)
    supervisor = FakeSupervisor()
    service = TrafficTestApplicationService(
        paths=paths,
        site_name="demo",
        task_service=task_service,
        repository=repository,
        local_adapter=local,
        agent_adapter=agent,
        supervisor=supervisor,
    )
    return service, repository, task_service, local, agent, supervisor


def test_application_service_selects_local_adapter_and_persists_relations(tmp_path: Path) -> None:
    service, repository, _tasks, local, _agent, _supervisor = _service(tmp_path)

    run = asyncio.run(
        service.start_iperf_client(
            IperfClientConfig("192.0.2.10", protocol="UDP", target_bandwidth="20M"),
            ExecutionTargetDTO(ExecutionTargetKind.LOCAL, display_name="本机"),
            parent_task_id="parent-1",
            correlation_id="pair-1",
        )
    )

    assert local.started == [(TrafficTestType.IPERF_CLIENT, run.traffic_run_id)]
    assert run.status is TaskState.STARTING
    assert run.parent_task_id == "parent-1"
    assert run.correlation_id == "pair-1"
    assert repository.get_by_controller_task(run.controller_task_id) == run


def test_application_service_delegates_local_cancel_state_to_adapter(tmp_path: Path) -> None:
    service, repository, _tasks, local, _agent, _supervisor = _service(tmp_path)
    run = asyncio.run(
        service.start_iperf_server(
            IperfServerConfig(port=5202),
            ExecutionTargetDTO(ExecutionTargetKind.LOCAL),
        )
    )

    stopping = asyncio.run(service.cancel(run.controller_task_id))

    assert stopping.status is TaskState.STOPPING
    assert local.cancelled == [run.controller_task_id]
    assert repository.get(run.traffic_run_id).status is TaskState.STOPPING


def test_application_service_creates_external_task_and_agent_mapping(tmp_path: Path) -> None:
    service, repository, tasks, _local, agent, supervisor = _service(tmp_path)

    run = asyncio.run(
        service.start_high_frequency_ping(
            HighFrequencyPingConfig(("192.0.2.1",), packet_size=1256, count=3),
            ExecutionTargetDTO(ExecutionTargetKind.AGENT, agent_id="agent-1", display_name="边缘 Agent"),
        )
    )

    assert agent.validated == [("agent-1", TrafficTestType.HIGH_FREQUENCY_PING)]
    assert repository.get_agent_mapping(run.traffic_run_id).agent_task_id.startswith("remote-")
    snapshot = tasks.get_task(run.controller_task_id)
    assert snapshot is not None and snapshot.source == "agent" and snapshot.owner_pid == 0
    assert supervisor.attached == [run.traffic_run_id]


def test_application_service_cancel_uses_exact_remote_mapping(tmp_path: Path) -> None:
    service, _repository, _tasks, _local, agent, _supervisor = _service(tmp_path)
    run = asyncio.run(
        service.start_iperf_server(
            IperfServerConfig(port=5202),
            ExecutionTargetDTO(ExecutionTargetKind.AGENT, agent_id="agent-1"),
        )
    )

    stopping = asyncio.run(service.cancel(run.controller_task_id))

    assert stopping.status is TaskState.STOPPING
    assert agent.stopped == [f"remote-{run.traffic_run_id}"]


def test_application_service_does_not_fake_cancel_when_agent_stop_times_out(tmp_path: Path) -> None:
    service, repository, tasks, _local, agent, _supervisor = _service(tmp_path)
    run = asyncio.run(
        service.start_iperf_server(
            IperfServerConfig(port=5202),
            ExecutionTargetDTO(ExecutionTargetKind.AGENT, agent_id="agent-1"),
        )
    )

    async def fail_stop(_mapping: AgentTaskMapping) -> None:
        raise TrafficTestError(TrafficErrorCode.CANCEL_TIMEOUT, "Agent 停止确认超时", retryable=True)

    agent.stop = fail_stop

    with pytest.raises(TrafficTestError) as error:
        asyncio.run(service.cancel(run.controller_task_id))

    restored = repository.get(run.traffic_run_id)
    assert error.value.code == TrafficErrorCode.CANCEL_TIMEOUT.value
    assert restored is not None and restored.status is TaskState.STOPPING
    assert restored.sync_state is TrafficSyncState.ERROR
    assert tasks.get_task(run.controller_task_id).status is TaskState.STOPPING


def test_application_service_retry_creates_new_ids_without_overwriting(tmp_path: Path) -> None:
    service, repository, _tasks, _local, _agent, _supervisor = _service(tmp_path)
    first = asyncio.run(
        service.start_high_frequency_ping(
            HighFrequencyPingConfig(("198.51.100.1",), count=2),
            ExecutionTargetDTO(ExecutionTargetKind.LOCAL),
        )
    )

    retried = asyncio.run(service.retry(first.controller_task_id))

    assert retried.traffic_run_id != first.traffic_run_id
    assert retried.controller_task_id != first.controller_task_id
    assert retried.retry_of_traffic_run_id == first.traffic_run_id
    assert repository.get(first.traffic_run_id) is not None


def test_application_service_submits_and_retries_tcp_port_test(tmp_path: Path) -> None:
    service, repository, _tasks, local, _agent, _supervisor = _service(tmp_path)

    first = asyncio.run(
        service.start_tcp_port_test(
            TcpPortTestConfig("127.0.0.1", 443, interval_ms=250, timeout_ms=500, count=2),
            ExecutionTargetDTO(ExecutionTargetKind.LOCAL),
        )
    )
    retried = asyncio.run(service.retry(first.controller_task_id))

    assert local.started[0][0] is TrafficTestType.TCP_PORT_TEST
    assert retried.retry_of_traffic_run_id == first.traffic_run_id
    assert repository.get(retried.traffic_run_id).normalized_config["port"] == 443


def test_application_service_normalizes_start_failure(tmp_path: Path) -> None:
    service, repository, tasks, _local, agent, _supervisor = _service(tmp_path)

    async def fail(_run: TrafficRun, _config: object) -> None:
        raise TrafficTestError(TrafficErrorCode.AGENT_OFFLINE, "Agent 当前离线")

    agent.start_iperf_client = fail

    with pytest.raises(TrafficTestError) as error:
        asyncio.run(
            service.start_iperf_client(
                IperfClientConfig("203.0.113.1"),
                ExecutionTargetDTO(ExecutionTargetKind.AGENT, agent_id="agent-1"),
            )
        )

    assert error.value.code == TrafficErrorCode.AGENT_OFFLINE.value
    run = repository.list(limit=1)[0]
    assert run.status is TaskState.FAILED
    assert run.sync_state is TrafficSyncState.ERROR
    assert tasks.get_task(run.controller_task_id).status is TaskState.FAILED


def test_application_service_supervises_leftover_remote_mapping_after_cleanup_failure(tmp_path: Path) -> None:
    service, repository, tasks, _local, agent, supervisor = _service(tmp_path)

    async def fail_after_mapping(run: TrafficRun, _config: object) -> None:
        now = utc_now_iso()
        repository.save_agent_mapping(
            AgentTaskMapping(
                traffic_run_id=run.traffic_run_id,
                controller_task_id=run.controller_task_id,
                agent_id=run.agent_id,
                agent_task_id="remote-leftover",
                agent_task_type="iperf_client",
                created_at=now,
                updated_at=now,
            )
        )
        raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "远端清理未确认")

    agent.start_iperf_client = fail_after_mapping

    with pytest.raises(TrafficTestError):
        asyncio.run(
            service.start_iperf_client(
                IperfClientConfig("203.0.113.1"),
                ExecutionTargetDTO(ExecutionTargetKind.AGENT, agent_id="agent-1"),
            )
        )

    run = repository.list(limit=1)[0]
    assert run.status is TaskState.STOPPING
    assert run.error_code == TrafficErrorCode.REMOTE_SYNC_FAILED.value
    assert tasks.get_task(run.controller_task_id).status is TaskState.FAILED
    assert supervisor.attached == [run.traffic_run_id]
    assert repository.get_agent_mapping(run.traffic_run_id).agent_task_id == "remote-leftover"


def test_application_service_start_failure_preserves_latest_remote_metadata(tmp_path: Path) -> None:
    service, repository, _tasks, _local, agent, _supervisor = _service(tmp_path)

    async def fail_after_partial_remote_start(run: TrafficRun, _config: object) -> None:
        now = utc_now_iso()
        repository.save_agent_mapping(
            AgentTaskMapping(
                traffic_run_id=run.traffic_run_id,
                controller_task_id=run.controller_task_id,
                agent_id=run.agent_id,
                agent_task_id="remote-partial",
                agent_task_type="iperf_client",
                created_at=now,
                updated_at=now,
            )
        )
        repository.save(
            replace(
                run,
                status=TaskState.STARTING,
                started_at=now,
                local_iperf_run_id=f"traffic-{run.traffic_run_id}",
                raw_reference="network_tools/traffic/runs/raw/agent_iperf.log",
                sync_state=TrafficSyncState.ACTIVE,
                updated_at=now,
            )
        )
        raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "远端清理未确认")

    agent.start_iperf_client = fail_after_partial_remote_start

    with pytest.raises(TrafficTestError):
        asyncio.run(
            service.start_iperf_client(
                IperfClientConfig("203.0.113.1"),
                ExecutionTargetDTO(ExecutionTargetKind.AGENT, agent_id="agent-1"),
            )
        )

    run = repository.list(limit=1)[0]
    assert run.status is TaskState.STOPPING
    assert run.local_iperf_run_id.startswith("traffic-")
    assert run.raw_reference == "network_tools/traffic/runs/raw/agent_iperf.log"
    assert repository.get_agent_mapping(run.traffic_run_id).agent_task_id == "remote-partial"


def test_application_service_rejects_invalid_or_online_mr_specific_config(tmp_path: Path) -> None:
    service, *_ = _service(tmp_path)

    with pytest.raises(TrafficTestError) as ping_error:
        asyncio.run(
            service.start_high_frequency_ping(
                HighFrequencyPingConfig(("192.0.2.1",), continuous=True, count=20),
                ExecutionTargetDTO(ExecutionTargetKind.LOCAL),
            )
        )
    with pytest.raises(TrafficTestError) as iperf_error:
        asyncio.run(
            service.start_iperf_client(
                IperfClientConfig("192.0.2.2", follow_collection=True),
                ExecutionTargetDTO(ExecutionTargetKind.LOCAL),
            )
        )

    assert ping_error.value.code == TrafficErrorCode.INVALID_CONFIG.value
    assert iperf_error.value.code == TrafficErrorCode.INVALID_CONFIG.value


def test_application_service_reconciles_only_orphaned_local_traffic(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    traffic = TrafficRunRepository(paths.traffic_runs_db_path("demo"))
    now = utc_now_iso()
    traffic.create(
        TrafficRun(
            traffic_run_id="local-orphan",
            controller_task_id="local-task",
            test_type=TrafficTestType.IPERF_CLIENT,
            role="client",
            executor_kind=ExecutionTargetKind.LOCAL,
            normalized_config={"server_ip": "192.0.2.1"},
            status=TaskState.RUNNING,
            created_at=now,
            updated_at=now,
        )
    )
    tasks = TaskRepository(paths.site_tasks_db_path("demo"))
    tasks.save(
        TaskSnapshot(
            task_id="local-task",
            task_type="traffic_local_iperf_client",
            task_name="本地 iPerf",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            source="local",
            owner_pid=999999,
        )
    )

    TrafficTestApplicationService(paths=paths, site_name="demo", repository=traffic)

    restored = traffic.get("local-orphan")
    assert restored is not None and restored.status is TaskState.FAILED
    assert restored.error_code == TrafficErrorCode.PROCESS_EXITED.value
