from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType, AgentRuntimeSnapshot, AgentStatus
from netconsole.models.agent_traffic import (
    AgentTaskDTO,
    AgentTaskEventDTO,
    AgentTaskEventPageDTO,
    AgentTaskResultDTO,
)
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficRun,
    TrafficSyncState,
    TrafficTestType,
    TcpPortTestConfig,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.agent.controller import AgentControllerService, AgentControllerSettings
from netconsole.services.agent.http_client import AgentClientError
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.network_tools.iperf_runner import IperfClientConfig
from netconsole.services.traffic.agent_adapter import AgentTrafficAdapter
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


NOW = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


class FakeTrafficClient:
    def __init__(self) -> None:
        self.task = AgentTaskDTO("remote-1", "fping", "running", NOW, NOW)
        self.events: tuple[AgentTaskEventDTO, ...] = ()
        self.result = AgentTaskResultDTO("remote-1", "fping", "completed", NOW, NOW, {}, (), 0, "", "")
        self.result_error: AgentClientError | None = None
        self.calls: list[tuple[str, str | None, object]] = []
        self.ignore_event_cursor = False

    async def start_fping(self, _url, request, token=None):
        self.calls.append(("start_fping", token, request))
        self.task = replace(self.task, task_type="fping", status="running")
        return self.task

    async def start_ping_probe(self, _url, request, token=None):
        self.calls.append(("start_ping_probe", token, request))
        self.task = replace(self.task, task_type="ping_probe", status="running")
        return self.task

    async def start_iperf_server(self, _url, request, token=None):
        self.calls.append(("start_iperf_server", token, request))
        self.task = replace(self.task, task_type="iperf_server", status="running")
        return self.task

    async def start_iperf_client(self, _url, request, token=None):
        self.calls.append(("start_iperf_client", token, request))
        self.task = replace(self.task, task_type="iperf_client", status="running")
        return self.task

    async def get_task(self, _url, task_id, token=None):
        self.calls.append(("get_task", token, task_id))
        return self.task

    async def stop_task(self, _url, task_id, token=None):
        self.calls.append(("stop_task", token, task_id))
        self.task = replace(self.task, status="stopping")
        return self.task

    async def get_task_events(self, _url, task_id, *, after=0, limit=200, token=None):
        self.calls.append(("get_task_events", token, (task_id, after, limit)))
        events = self.events if self.ignore_event_cursor else tuple(item for item in self.events if item.sequence > after)
        return AgentTaskEventPageDTO(task_id, events[:limit], events[-1].sequence if events else after, False)

    async def get_task_result(self, _url, task_id, token=None):
        self.calls.append(("get_task_result", token, task_id))
        if self.result_error is not None:
            raise self.result_error
        return self.result


def _build(tmp_path, *, token: str = "session-secret"):
    paths = PathResolver(tmp_path)
    client = FakeTrafficClient()
    controller = AgentControllerService(
        paths=paths,
        site_name="demo",
        client=client,
        settings=AgentControllerSettings(health_check_enabled=False),
    )
    record = controller.create_agent(
        name="测试 Agent",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.TOKEN,
        token=token,
    )
    controller.repository.save_runtime(
        AgentRuntimeSnapshot(
            agent_id=record["agent_id"],
            status=AgentStatus.ONLINE,
            capabilities={
                "iperf_server": True,
                "iperf_client": True,
                "fping": True,
                "task_events": True,
                "task_result": True,
                "tcp_ping_probe": True,
            },
            updated_at="2026-07-12T08:00:00Z",
        )
    )
    task_service = TaskApplicationService(paths=paths, site_name="demo")
    repository = TrafficRunRepository(paths.traffic_runs_db_path("demo"))
    adapter = AgentTrafficAdapter(controller, repository, task_service)
    return paths, client, controller, task_service, repository, adapter, record["agent_id"]


def _run(repository, task_service, agent_id, test_type, *, suffix="1") -> TrafficRun:
    task_id = f"controller-{suffix}"
    run_id = f"traffic-{suffix}"
    task_service.create_external_task(
        task_id=task_id,
        task_type=f"traffic.agent.{test_type.value.lower()}",
        task_name="远端流量测试",
        source="agent",
        agent=agent_id,
    )
    run = TrafficRun(
        traffic_run_id=run_id,
        controller_task_id=task_id,
        test_type=test_type,
        role="client" if test_type is TrafficTestType.IPERF_CLIENT else "probe",
        executor_kind=ExecutionTargetKind.AGENT,
        agent_id=agent_id,
        normalized_config={"safe": True},
        status=TaskState.PENDING,
        created_at="2026-07-12T08:00:00Z",
        updated_at="2026-07-12T08:00:00Z",
    )
    repository.create(run)
    return run


def _mark_start_failure_cleanup(repository, task_service, run: TrafficRun) -> None:
    active = repository.get(run.traffic_run_id)
    repository.save(
        replace(
            active,
            status=TaskState.STOPPING,
            error_code=TrafficErrorCode.REMOTE_SYNC_FAILED.value,
            error_message="本地登记失败，等待远端清理",
            sync_state=TrafficSyncState.ERROR,
        )
    )
    task_service.record_external_event(
        run.controller_task_id,
        "error",
        {"code": TrafficErrorCode.REMOTE_SYNC_FAILED.value, "error": "本地登记失败"},
        source="traffic",
    )


def test_agent_start_uses_typed_request_shared_vault_and_persists_mapping(tmp_path) -> None:
    paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.IPERF_CLIENT)

    mapping = asyncio.run(
        adapter.start_iperf_client(
            run,
            IperfClientConfig(
                server_ip="192.0.2.1",
                protocol="UDP",
                target_bandwidth="100M",
                packet_length=1400,
                direction="bidirectional",
            ),
        )
    )

    request = client.calls[0][2]
    assert client.calls[0][0:2] == ("start_iperf_client", "session-secret")
    assert request.bandwidth_mbps == 100
    assert request.udp_packet_length == 1400
    assert request.bidirectional is True
    assert mapping.agent_task_id == "remote-1"
    assert repository.get_agent_mapping(run.traffic_run_id) == mapping
    assert repository.get(run.traffic_run_id).status is TaskState.RUNNING
    assert task_service.get_task(run.controller_task_id).status is TaskState.RUNNING
    assert b"session-secret" not in paths.traffic_runs_db_path("demo").read_bytes()
    assert b"session-secret" not in paths.site_tasks_db_path("demo").read_bytes()
    assert b"session-secret" not in paths.traffic_run_events_path("demo", run.traffic_run_id).read_bytes()


def test_validate_target_rejects_missing_capability_and_session_credential(tmp_path) -> None:
    _paths, _client, controller, _tasks, _repository, adapter, agent_id = _build(tmp_path)
    runtime = controller.repository.get_runtime(agent_id)
    controller.repository.save_runtime(replace(runtime, capabilities={"fping": True}))
    with pytest.raises(TrafficTestError) as missing:
        adapter.validate_target(agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    assert missing.value.code == TrafficErrorCode.CAPABILITY_UNSUPPORTED.value

    config = controller.repository.get(agent_id)
    controller.credentials.remove(config.credential_reference)
    with pytest.raises(TrafficTestError) as credential:
        adapter.validate_target(agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    assert credential.value.code == TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED.value


def test_agent_fping_cursor_replay_timeout_and_terminal_result(tmp_path) -> None:
    paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    client.events = (
        AgentTaskEventDTO(1, NOW, "sample", "fping", {"target": "192.0.2.10", "probe_sequence": 1, "ok": False, "raw_type": "timeout", "error": "timeout", "rtt_ms": 0}),
        AgentTaskEventDTO(2, NOW, "sample", "fping", {"target": "192.0.2.10", "probe_sequence": 2, "ok": True, "raw_type": "resp", "rtt_ms": 1.25}),
    )
    client.ignore_event_cursor = True

    first = asyncio.run(adapter.sync_once(mapping))
    second = asyncio.run(adapter.sync_once(first.mapping))

    samples = repository.list_ping_samples(run.traffic_run_id)
    assert first.processed_events == 2
    assert second.processed_events == 0
    assert len(samples) == 2
    assert samples[0].timeout is True and samples[0].rtt_ms is None
    assert samples[1].ok is True and samples[1].rtt_ms == 1.25

    client.task = replace(client.task, status="completed", end_time=NOW)
    client.events = (*client.events, AgentTaskEventDTO(3, NOW, "state", "task", {"status": "completed"}))
    client.result = AgentTaskResultDTO("remote-1", "fping", "completed", NOW, NOW, {"sent": 2}, (), 3, "", "")
    final = asyncio.run(adapter.sync_once(first.mapping))

    assert final.terminal is True
    assert repository.get(run.traffic_run_id).status is TaskState.COMPLETED
    assert repository.get_agent_mapping(run.traffic_run_id).sync_state is TrafficSyncState.COMPLETED
    assert task_service.get_task(run.controller_task_id).status is TaskState.COMPLETED
    assert paths.traffic_run_remote_result_path("demo", run.traffic_run_id).is_file()


def test_agent_tcp_port_test_reuses_ping_probe_and_accepts_legacy_empty_result(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.TCP_PORT_TEST)

    mapping = asyncio.run(adapter.start_tcp_port_test(run, TcpPortTestConfig("127.0.0.1", 443, count=1)))
    request = client.calls[0][2]
    assert client.calls[0][0] == "start_ping_probe"
    assert request.tcp_port == 443

    client.task = replace(client.task, status="completed", end_time=NOW)
    client.result_error = AgentClientError("AGENT_TRAFFIC_RESULT_NOT_READY", "结果不存在", status_code=409)
    outcome = asyncio.run(adapter.sync_once(mapping))

    assert outcome.terminal is True
    assert repository.get(run.traffic_run_id).status is TaskState.COMPLETED
    assert repository.get(run.traffic_run_id).summary == {}


def test_agent_iperf_stdout_replay_is_idempotent(tmp_path) -> None:
    paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.IPERF_CLIENT)
    mapping = asyncio.run(adapter.start_iperf_client(run, IperfClientConfig(server_ip="192.0.2.1")))
    client.events = (
        AgentTaskEventDTO(
            1,
            NOW,
            "stdout",
            "iperf",
            {"line": "[  5]   0.00-1.00   sec  10.5 MBytes  88.1 Mbits/sec  0   256 KBytes"},
        ),
    )
    client.ignore_event_cursor = True

    first = asyncio.run(adapter.sync_once(mapping))
    asyncio.run(adapter.sync_once(first.mapping))

    with sqlite3.connect(paths.iperf_db_path("demo")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM iperf_intervals").fetchone()[0] == 1
        assert conn.execute("SELECT source_event_key FROM iperf_intervals").fetchone()[0].endswith(":1")
        assert conn.execute("SELECT log_file FROM iperf_runs").fetchone()[0].endswith("raw\\agent_iperf.log")
    raw_log = paths.traffic_run_dir("demo", run.traffic_run_id) / "raw" / "agent_iperf.log"
    assert raw_log.read_text(encoding="utf-8").count("88.1 Mbits/sec") == 1


def test_failed_agent_task_can_finalize_without_result_document(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    client.task = replace(client.task, status="failed", error_code="REMOTE_FAILED", error_message="Agent 重启")
    client.result_error = AgentClientError("AGENT_TRAFFIC_RESULT_NOT_READY", "结果不存在", status_code=409)

    outcome = asyncio.run(adapter.sync_once(mapping))

    assert outcome.terminal is True
    assert repository.get(run.traffic_run_id).status is TaskState.FAILED
    assert task_service.get_task(run.controller_task_id).status is TaskState.FAILED


def test_completed_agent_task_waits_for_result(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    client.task = replace(client.task, status="completed")
    client.result_error = AgentClientError("AGENT_TRAFFIC_RESULT_NOT_READY", "结果尚未提交", status_code=409)

    with pytest.raises(TrafficTestError) as exc_info:
        asyncio.run(adapter.sync_once(mapping))

    assert exc_info.value.code == TrafficErrorCode.RESULT_NOT_FOUND.value
    assert exc_info.value.retryable is True
    assert repository.get(run.traffic_run_id).status is TaskState.RUNNING


def test_stop_uses_specific_remote_task_and_keeps_stopping_monotonic(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))

    asyncio.run(adapter.stop(mapping))
    client.task = replace(client.task, status="running")
    outcome = asyncio.run(adapter.sync_once(mapping))

    assert any(call[0] == "stop_task" and call[2] == "remote-1" for call in client.calls)
    assert outcome.status is TaskState.STOPPING
    assert repository.get(run.traffic_run_id).status is TaskState.STOPPING
    assert task_service.get_task(run.controller_task_id).status is TaskState.STOPPING


def test_start_failure_cleanup_keeps_failed_controller_result(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    _mark_start_failure_cleanup(repository, task_service, run)

    first = asyncio.run(adapter.sync_once(mapping))
    client.task = replace(client.task, status="cancelled", end_time=NOW)
    client.result = replace(client.result, status="cancelled", error="任务已取消")
    final = asyncio.run(adapter.sync_once(first.mapping))

    restored = repository.get(run.traffic_run_id)
    assert any(call[0] == "stop_task" and call[2] == "remote-1" for call in client.calls)
    assert final.terminal is True
    assert restored.status is TaskState.FAILED
    assert restored.error_code == TrafficErrorCode.REMOTE_SYNC_FAILED.value
    assert restored.sync_state is TrafficSyncState.COMPLETED
    assert task_service.get_task(run.controller_task_id).status is TaskState.FAILED


def test_start_failure_cleanup_recovers_after_run_failed_before_mapping_completed(tmp_path, monkeypatch) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    _mark_start_failure_cleanup(repository, task_service, run)
    first = asyncio.run(adapter.sync_once(mapping))
    client.task = replace(client.task, status="cancelled", end_time=NOW)
    client.result = replace(client.result, status="cancelled", error="任务已取消")

    original_save_mapping = repository.save_agent_mapping
    crashed = {"value": False}

    def crash_after_run_save(mapping_to_save):
        if mapping_to_save.sync_state is TrafficSyncState.COMPLETED and not crashed["value"]:
            crashed["value"] = True
            raise OSError("crash before mapping completed")
        original_save_mapping(mapping_to_save)

    monkeypatch.setattr(repository, "save_agent_mapping", crash_after_run_save)
    with pytest.raises(OSError):
        asyncio.run(adapter.sync_once(first.mapping))

    crashed_run = repository.get(run.traffic_run_id)
    assert crashed_run.status is TaskState.FAILED
    assert crashed_run.error_code == TrafficErrorCode.REMOTE_SYNC_FAILED.value
    assert repository.get_agent_mapping(run.traffic_run_id).sync_state is not TrafficSyncState.COMPLETED

    monkeypatch.setattr(repository, "save_agent_mapping", original_save_mapping)
    final = asyncio.run(adapter.sync_once(repository.get_agent_mapping(run.traffic_run_id)))

    restored = repository.get(run.traffic_run_id)
    assert final.terminal is True
    assert restored.status is TaskState.FAILED
    assert restored.error_code == TrafficErrorCode.REMOTE_SYNC_FAILED.value
    assert restored.sync_state is TrafficSyncState.COMPLETED
    assert repository.get_agent_mapping(run.traffic_run_id).sync_state is TrafficSyncState.COMPLETED
    assert task_service.get_task(run.controller_task_id).status is TaskState.FAILED


def test_start_failure_cleanup_remote_missing_finishes_mapping_without_overwriting_error(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    _mark_start_failure_cleanup(repository, task_service, run)

    updated = adapter.fail_sync(mapping, TrafficTestError(TrafficErrorCode.REMOTE_TASK_NOT_FOUND, "Agent 任务不存在"))

    restored = repository.get(run.traffic_run_id)
    assert updated.sync_state is TrafficSyncState.COMPLETED
    assert updated.sync_error_code == ""
    assert restored.status is TaskState.FAILED
    assert restored.error_code == TrafficErrorCode.REMOTE_SYNC_FAILED.value
    assert restored.error_message == "本地登记失败，等待远端清理"
    assert restored.sync_state is TrafficSyncState.COMPLETED
    assert task_service.get_task(run.controller_task_id).status is TaskState.FAILED


def test_start_rolls_back_mapping_after_local_registration_failure(tmp_path, monkeypatch) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.IPERF_CLIENT)

    def fail_registration(*_args, **_kwargs):
        raise OSError("local store failed")

    monkeypatch.setattr(adapter, "_start_iperf_result_run", fail_registration)
    with pytest.raises(OSError):
        asyncio.run(adapter.start_iperf_client(run, IperfClientConfig(server_ip="192.0.2.1")))

    assert any(call[0] == "stop_task" and call[2] == "remote-1" for call in client.calls)
    assert repository.get_agent_mapping(run.traffic_run_id) is None


def test_unknown_remote_status_does_not_fabricate_task_terminal_state(tmp_path) -> None:
    _paths, client, _controller, task_service, repository, adapter, agent_id = _build(tmp_path)
    run = _run(repository, task_service, agent_id, TrafficTestType.HIGH_FREQUENCY_PING)
    mapping = asyncio.run(adapter.start_high_frequency_ping(run, HighFrequencyPingConfig(("192.0.2.10",))))
    client.task = replace(client.task, status="future-status")

    with pytest.raises(TrafficTestError) as exc_info:
        asyncio.run(adapter.sync_once(mapping))

    assert exc_info.value.code == TrafficErrorCode.REMOTE_SYNC_FAILED.value
    assert repository.get(run.traffic_run_id).status is TaskState.RUNNING
    assert task_service.get_task(run.controller_task_id).status is TaskState.RUNNING
