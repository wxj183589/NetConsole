from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
import threading
from typing import Any, TypeVar

from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType, AgentConfig, AgentStatus
from netconsole.models.agent_traffic import (
    AgentFpingStartRequest,
    AgentIperfClientStartRequest,
    AgentIperfServerStartRequest,
    AgentPingProbeStartRequest,
    AgentTaskDTO,
    AgentTaskEventDTO,
    AgentTaskResultDTO,
)
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.models.traffic_test import (
    AgentTaskMapping,
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficEvent,
    TrafficEventType,
    TrafficPingSample,
    TrafficRun,
    TrafficSyncState,
    TrafficTestType,
    TcpPortTestConfig,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.agent.controller import AgentControllerService
from netconsole.services.agent.http_client import AgentClientError
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.network_tools.iperf_parser import parse_iperf_line
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfResultStore, IperfServerConfig
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError, map_agent_error
from netconsole.services.traffic.event_hub import TrafficEventHub
from netconsole.services.traffic.event_store import TrafficEventStore


_T = TypeVar("_T")
AgentCall = Callable[[str, str | None], Awaitable[_T]]
EventStoreFactory = Callable[[str], TrafficEventStore]

_REMOTE_STATUS_MAP = {
    "created": TaskState.STARTING,
    "running": TaskState.RUNNING,
    "stopping": TaskState.STOPPING,
    "completed": TaskState.COMPLETED,
    "failed": TaskState.FAILED,
    "cancelled": TaskState.CANCELLED,
}
_AGENT_TASK_TYPES = {
    TrafficTestType.IPERF_SERVER: "iperf_server",
    TrafficTestType.IPERF_CLIENT: "iperf_client",
    TrafficTestType.HIGH_FREQUENCY_PING: "fping",
    TrafficTestType.TCP_PORT_TEST: "ping_probe",
}
_REQUIRED_CAPABILITIES = {
    TrafficTestType.IPERF_SERVER: ("iperf_server", "task_events", "task_result"),
    TrafficTestType.IPERF_CLIENT: ("iperf_client", "task_events", "task_result"),
    TrafficTestType.HIGH_FREQUENCY_PING: ("fping", "task_events", "task_result"),
    TrafficTestType.TCP_PORT_TEST: ("tcp_ping_probe", "task_events"),
}


@dataclass(frozen=True)
class AgentSyncOutcome:
    mapping: AgentTaskMapping
    status: TaskState
    processed_events: int = 0
    has_more: bool = False
    terminal: bool = False


class AgentTrafficAdapter:
    """Controller 进程内的 Agent 流量测试适配器。

    凭据只在每次 HTTP 调用前从共享 ``SessionCredentialVault`` 获取，不进入
    Traffic 模型、任务快照、事件或独立 Worker Process。
    """

    def __init__(
        self,
        agent_controller: AgentControllerService,
        traffic_repository: TrafficRunRepository,
        task_service: TaskApplicationService,
        *,
        paths: PathResolver | None = None,
        site_name: str | None = None,
        event_hub: TrafficEventHub | None = None,
        event_store_factory: EventStoreFactory | None = None,
        iperf_store: IperfResultStore | None = None,
    ) -> None:
        self.agent_controller = agent_controller
        self.repository = traffic_repository
        self.task_service = task_service
        self.paths = paths or agent_controller.paths
        self.site_name = str(site_name or agent_controller.site_name or "demo")
        self.events = event_hub or TrafficEventHub()
        self._event_store_factory = event_store_factory or (
            lambda _run_id: TrafficEventStore(self.paths, self.repository, self.site_name)
        )
        self.iperf_store = iperf_store or IperfResultStore(self.paths.iperf_db_path(self.site_name))
        self._raw_log_lock = threading.Lock()

    def validate_target(self, agent_id: str, test_type: TrafficTestType) -> dict[str, Any]:
        """校验新任务执行端并返回不含凭据的 Agent 记录。"""

        config = self._require_agent(agent_id)
        if not config.enabled:
            raise TrafficTestError(TrafficErrorCode.AGENT_DISABLED, "Agent 已禁用")
        self._credential_for(config)
        runtime = self.agent_controller.repository.get_runtime(config.agent_id)
        if runtime is None or runtime.status is not AgentStatus.ONLINE:
            if runtime is not None and runtime.status is AgentStatus.UNAUTHORIZED:
                raise TrafficTestError(TrafficErrorCode.AGENT_UNAUTHORIZED, "Agent 认证失败")
            raise TrafficTestError(TrafficErrorCode.AGENT_OFFLINE, "Agent 当前不在线", retryable=True)
        missing = [name for name in _REQUIRED_CAPABILITIES[test_type] if runtime.capabilities.get(name) is not True]
        if missing:
            raise TrafficTestError(
                TrafficErrorCode.CAPABILITY_UNSUPPORTED,
                f"Agent 缺少流量测试能力：{', '.join(missing)}",
            )
        return self.agent_controller.get_agent(config.agent_id)

    def ensure_sync_ready(self, mapping: AgentTaskMapping) -> None:
        """恢复时只校验配置和凭据；离线 Agent 仍交给 Supervisor 退避重试。"""

        config = self._require_agent(mapping.agent_id)
        if not config.enabled:
            raise TrafficTestError(TrafficErrorCode.AGENT_DISABLED, "Agent 已禁用")
        self._credential_for(config)

    async def start_iperf_server(self, run: TrafficRun | str, config: IperfServerConfig) -> AgentTaskMapping:
        selected = self._run(run, TrafficTestType.IPERF_SERVER)
        request = AgentIperfServerStartRequest(
            bind_address=str(config.bind_ip or "0.0.0.0"),
            port=int(config.port),
            report_interval=float(config.interval_seconds),
            one_off=bool(config.one_off),
        )
        return await self._start_remote(
            selected,
            lambda url, token: self.agent_controller.client.start_iperf_server(url, request, token),
            iperf_config=config,
        )

    async def start_iperf_client(self, run: TrafficRun | str, config: IperfClientConfig) -> AgentTaskMapping:
        selected = self._run(run, TrafficTestType.IPERF_CLIENT)
        normalized = config.normalized()
        direction = str(normalized.direction or "upload").lower()
        request = AgentIperfClientStartRequest(
            server_host=normalized.server_ip,
            server_port=normalized.port,
            protocol=normalized.protocol.lower(),
            duration_sec=normalized.duration_seconds,
            parallel=normalized.parallel,
            bandwidth_mbps=_bandwidth_mbps(normalized),
            reverse=direction == "download",
            bidirectional=direction in {"bidirectional", "bidir"},
            report_interval=float(normalized.interval_seconds),
            udp_packet_length=int(normalized.packet_length or 0),
            tcp_block_size=_size_bytes(normalized.tcp_block_size),
        )
        return await self._start_remote(
            selected,
            lambda url, token: self.agent_controller.client.start_iperf_client(url, request, token),
            iperf_config=normalized,
        )

    async def start_high_frequency_ping(
        self,
        run: TrafficRun | str,
        config: HighFrequencyPingConfig,
    ) -> AgentTaskMapping:
        selected = self._run(run, TrafficTestType.HIGH_FREQUENCY_PING)
        normalized = config.normalized()
        request = AgentFpingStartRequest(
            targets=normalized.targets,
            interval_ms=normalized.interval_ms,
            timeout_ms=normalized.timeout_ms,
            packet_size=normalized.packet_size,
            count=0 if normalized.continuous else normalized.count,
            continuous=normalized.continuous,
            source_address=normalized.source_address,
        )
        return await self._start_remote(
            selected,
            lambda url, token: self.agent_controller.client.start_fping(url, request, token),
        )

    async def start_tcp_port_test(
        self,
        run: TrafficRun | str,
        config: TcpPortTestConfig,
    ) -> AgentTaskMapping:
        selected = self._run(run, TrafficTestType.TCP_PORT_TEST)
        normalized = config.normalized()
        request = AgentPingProbeStartRequest(
            target=normalized.target,
            tcp_port=normalized.port,
            interval_ms=normalized.interval_ms,
            timeout_ms=normalized.timeout_ms,
            count=normalized.count,
        )
        return await self._start_remote(
            selected,
            lambda url, token: self.agent_controller.client.start_ping_probe(url, request, token),
        )

    async def stop(self, mapping: AgentTaskMapping | str) -> AgentTaskDTO:
        current = self._mapping(mapping)
        run = self._require_run(current.traffic_run_id)
        if run.status not in TERMINAL_TASK_STATES and run.status is not TaskState.STOPPING:
            self._record_controller_state(run, TaskState.STOPPING, "正在停止远端任务")
        try:
            task = await self._invoke(
                current.agent_id,
                lambda url, token: self.agent_controller.client.stop_task(url, current.agent_task_id, token),
            )
        except AgentClientError as exc:
            raise _traffic_error(exc) from exc
        self._validate_remote_task(task, current.agent_task_type, current.agent_task_id)
        status = self._map_status(task.status)
        now = utc_now_iso()
        updated = replace(
            current,
            last_remote_status=task.status,
            last_polled_at=now,
            sync_state=TrafficSyncState.ACTIVE,
            sync_error_code="",
            sync_error_message="",
            updated_at=now,
        )
        self.repository.save_agent_mapping(updated)
        if status is TaskState.STOPPING:
            latest_run = self._require_run(run.traffic_run_id)
            if not self._is_start_failure_cleanup(latest_run):
                self._record_controller_state(latest_run, TaskState.STOPPING, "远端任务正在停止")
        return task

    async def sync_once(
        self,
        mapping: AgentTaskMapping | str,
        *,
        event_limit: int = 1_000,
        max_event_pages: int = 4,
    ) -> AgentSyncOutcome:
        current = self._mapping(mapping)
        run = self._require_run(current.traffic_run_id)
        try:
            remote = await self._invoke(
                current.agent_id,
                lambda url, token: self.agent_controller.client.get_task(url, current.agent_task_id, token),
            )
        except AgentClientError as exc:
            raise _traffic_error(exc) from exc
        self._validate_remote_task(remote, current.agent_task_type, current.agent_task_id)
        remote_state = self._map_status(remote.status)

        cursor = current.last_remote_sequence
        processed = 0
        has_more = False
        for _ in range(max(1, int(max_event_pages))):
            try:
                page = await self._invoke(
                    current.agent_id,
                    lambda url, token, after=cursor: self.agent_controller.client.get_task_events(
                        url,
                        current.agent_task_id,
                        after=after,
                        limit=max(1, min(int(event_limit), 1_000)),
                        token=token,
                    ),
                )
            except AgentClientError as exc:
                raise _traffic_error(exc) from exc
            if page.task_id != current.agent_task_id:
                raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "Agent 事件返回了错误的任务 ID")
            if any(event.sequence <= 0 for event in page.events):
                raise TrafficTestError(TrafficErrorCode.EVENT_CURSOR_INVALID, "Agent 事件序号无效")
            candidates = sorted((event for event in page.events if event.sequence > cursor), key=lambda item: item.sequence)
            if candidates:
                await self._persist_remote_events(run, current, candidates)
                cursor = max(cursor, candidates[-1].sequence)
                processed += len(candidates)
            has_more = bool(page.has_more)
            if not has_more:
                break
            if not candidates:
                raise TrafficTestError(TrafficErrorCode.EVENT_CURSOR_INVALID, "Agent 事件游标未前进")

        now = utc_now_iso()
        updated_mapping = replace(
            current,
            last_remote_sequence=cursor,
            last_remote_status=remote.status,
            last_polled_at=now,
            sync_state=TrafficSyncState.ACTIVE,
            sync_error_code="",
            sync_error_message="",
            updated_at=now,
        )
        mapping_changed = (
            cursor != current.last_remote_sequence
            or remote.status != current.last_remote_status
            or current.sync_state is not TrafficSyncState.ACTIVE
            or bool(current.sync_error_code or current.sync_error_message)
        )
        if mapping_changed:
            self.repository.save_agent_mapping(updated_mapping)

        latest_run = self._require_run(run.traffic_run_id)
        if latest_run.status is TaskState.STOPPING and remote_state in {TaskState.STARTING, TaskState.RUNNING}:
            await self.stop(updated_mapping)
            refreshed = self.repository.get_agent_mapping(run.traffic_run_id) or updated_mapping
            return AgentSyncOutcome(refreshed, TaskState.STOPPING, processed, has_more, False)

        if remote_state in TERMINAL_TASK_STATES and not has_more:
            result = await self._terminal_result(current, remote, remote_state)
            final_mapping = self._finalize(run, updated_mapping, remote, remote_state, result)
            return AgentSyncOutcome(final_mapping, remote_state, processed, False, True)

        effective_state = remote_state
        if effective_state not in TERMINAL_TASK_STATES and effective_state != latest_run.status:
            self._record_controller_state(latest_run, effective_state, _state_message(effective_state))
        return AgentSyncOutcome(updated_mapping, effective_state, processed, has_more, False)

    def mark_sync_state(
        self,
        mapping: AgentTaskMapping | str,
        state: TrafficSyncState,
        *,
        error_code: str = "",
        error_message: str = "",
    ) -> AgentTaskMapping:
        current = self._mapping(mapping)
        if (
            current.sync_state is state
            and current.sync_error_code == error_code
            and current.sync_error_message == error_message
        ):
            return current
        now = utc_now_iso()
        updated = replace(
            current,
            sync_state=state,
            sync_error_code=str(error_code or ""),
            sync_error_message=str(error_message or ""),
            updated_at=now,
        )
        self.repository.save_agent_mapping(updated)
        run = self.repository.get(current.traffic_run_id)
        if run is not None and run.sync_state is not state:
            self.repository.save(replace(run, sync_state=state, updated_at=now))
        return updated

    def fail_sync(self, mapping: AgentTaskMapping | str, error: TrafficTestError) -> AgentTaskMapping:
        original = self._mapping(mapping)
        run = self._require_run(original.traffic_run_id)
        if self._is_start_failure_cleanup(run):
            return self._fail_start_failure_cleanup_sync(original, run, error)
        current = self.mark_sync_state(
            original,
            TrafficSyncState.ERROR,
            error_code=error.code,
            error_message=error.message,
        )
        run = self._require_run(current.traffic_run_id)
        if run.status not in TERMINAL_TASK_STATES:
            now = utc_now_iso()
            self.repository.save(
                replace(
                    run,
                    status=TaskState.FAILED,
                    finished_at=now,
                    error_code=error.code,
                    error_message=error.message,
                    sync_state=TrafficSyncState.ERROR,
                    updated_at=now,
                )
            )
            self.task_service.record_external_event(
                run.controller_task_id,
                "error",
                {"code": error.code, "message": "远端任务同步失败", "error": error.message},
                source="agent",
                site_name=self.site_name,
            )
        return current

    def _fail_start_failure_cleanup_sync(
        self,
        mapping: AgentTaskMapping,
        run: TrafficRun,
        error: TrafficTestError,
    ) -> AgentTaskMapping:
        now = utc_now_iso()
        cleanup_complete = error.code == TrafficErrorCode.REMOTE_TASK_NOT_FOUND.value
        sync_state = TrafficSyncState.COMPLETED if cleanup_complete else TrafficSyncState.ERROR
        updated_run = replace(
            run,
            status=TaskState.FAILED,
            finished_at=run.finished_at or now,
            error_code=run.error_code,
            error_message=run.error_message,
            sync_state=sync_state,
            updated_at=now,
        )
        updated_mapping = replace(
            mapping,
            sync_state=sync_state,
            sync_error_code="" if cleanup_complete else error.code,
            sync_error_message="" if cleanup_complete else error.message,
            last_polled_at=now,
            updated_at=now,
        )
        self.repository.save(updated_run)
        self.repository.save_agent_mapping(updated_mapping)
        return updated_mapping

    async def _start_remote(
        self,
        run: TrafficRun,
        operation: AgentCall[AgentTaskDTO],
        *,
        iperf_config: IperfClientConfig | IperfServerConfig | None = None,
    ) -> AgentTaskMapping:
        self.validate_target(run.agent_id, run.test_type)
        try:
            remote = await self._invoke(run.agent_id, operation, require_online=True, test_type=run.test_type)
        except AgentClientError as exc:
            raise _traffic_error(exc) from exc
        expected_type = _AGENT_TASK_TYPES[run.test_type]
        self._validate_remote_task(remote, expected_type)
        state = self._map_status(remote.status)
        controller_state = state if state not in TERMINAL_TASK_STATES else TaskState.STARTING
        now = utc_now_iso()
        mapping = AgentTaskMapping(
            traffic_run_id=run.traffic_run_id,
            controller_task_id=run.controller_task_id,
            agent_id=run.agent_id,
            agent_task_id=remote.task_id,
            agent_task_type=expected_type,
            last_remote_status=remote.status,
            last_polled_at=now,
            sync_state=TrafficSyncState.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        try:
            self.repository.save_agent_mapping(mapping)
            iperf_run_id = run.local_iperf_run_id
            raw_reference = run.raw_reference
            if run.test_type in {TrafficTestType.IPERF_SERVER, TrafficTestType.IPERF_CLIENT}:
                iperf_run_id = iperf_run_id or f"traffic-{run.traffic_run_id}"
                self._start_iperf_result_run(run, iperf_run_id, remote, iperf_config)
                raw_reference = _relative_reference(self._iperf_raw_log_path(run.traffic_run_id), self.paths.site_files_dir(self.site_name))
            updated_run = replace(
                run,
                status=controller_state,
                started_at=_datetime_text(remote.start_time) or now,
                local_iperf_run_id=iperf_run_id,
                raw_reference=raw_reference,
                sync_state=TrafficSyncState.ACTIVE,
                updated_at=now,
            )
            self.repository.save(updated_run)
            self._record_controller_state(updated_run, controller_state, _state_message(controller_state))
            self._record_domain_event(
                updated_run,
                TrafficEventType.STATE,
                {"state": controller_state.value, "agent_task_id": remote.task_id},
            )
        except Exception:
            remote_stopped = False
            try:
                await self._invoke(
                    run.agent_id,
                    lambda url, token: self.agent_controller.client.stop_task(url, remote.task_id, token),
                )
                remote_stopped = True
            except Exception:
                pass
            if remote_stopped:
                try:
                    self.repository.delete_agent_mapping(run.traffic_run_id)
                except Exception:
                    pass
            raise
        return mapping

    async def _terminal_result(
        self,
        mapping: AgentTaskMapping,
        remote: AgentTaskDTO,
        state: TaskState,
    ) -> AgentTaskResultDTO | None:
        try:
            result = await self._invoke(
                mapping.agent_id,
                lambda url, token: self.agent_controller.client.get_task_result(url, mapping.agent_task_id, token),
            )
        except AgentClientError as exc:
            error = _traffic_error(exc)
            if state in {TaskState.FAILED, TaskState.CANCELLED} and error.code == TrafficErrorCode.RESULT_NOT_FOUND.value:
                return None
            if state is TaskState.COMPLETED and error.code == TrafficErrorCode.RESULT_NOT_FOUND.value:
                run = self.repository.get(mapping.traffic_run_id)
                if run is not None and run.test_type is TrafficTestType.TCP_PORT_TEST:
                    return None
                raise TrafficTestError(error.code, error.message, retryable=True) from exc
            raise error from exc
        if result.task_id != mapping.agent_task_id or result.task_type != mapping.agent_task_type:
            raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "Agent 结果与任务映射不一致")
        if self._map_status(result.status) is not state:
            raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "Agent 结果状态与任务终态不一致")
        return result

    def _finalize(
        self,
        run: TrafficRun,
        mapping: AgentTaskMapping,
        remote: AgentTaskDTO,
        state: TaskState,
        result: AgentTaskResultDTO | None,
    ) -> AgentTaskMapping:
        now = utc_now_iso()
        summary = dict(result.summary) if result is not None else {}
        error_code = str((result.error_code if result is not None else "") or remote.error_code or "")
        error_message = str((result.error if result is not None else "") or remote.error_message or "")
        store = self._event_store(run.traffic_run_id)
        result_reference = ""
        if result is not None:
            result_path = store.write_remote_result(run.traffic_run_id, _result_payload(result))
            result_reference = _relative_reference(result_path, self.paths.site_files_dir(self.site_name))
        if summary:
            store.write_summary(run.traffic_run_id, summary)
        latest = self._require_run(run.traffic_run_id)
        cleanup_after_start_failure = self._is_start_failure_cleanup(latest)
        effective_state = TaskState.FAILED if cleanup_after_start_failure else state
        finished = _datetime_text(remote.end_time) or now
        updated_run = replace(
            latest,
            status=effective_state,
            finished_at=finished,
            summary=summary,
            error_code=latest.error_code if cleanup_after_start_failure else error_code,
            error_message=latest.error_message if cleanup_after_start_failure else error_message,
            result_reference=result_reference or latest.result_reference,
            sync_state=TrafficSyncState.COMPLETED,
            updated_at=now,
        )
        updated_mapping = replace(
            mapping,
            last_remote_status=remote.status,
            sync_state=TrafficSyncState.COMPLETED,
            sync_error_code="",
            sync_error_message="",
            last_polled_at=now,
            updated_at=now,
        )
        if updated_run.local_iperf_run_id:
            self.iperf_store.finish_run(
                updated_run.local_iperf_run_id,
                effective_state.value,
                _datetime_value(remote.end_time),
            )
        if cleanup_after_start_failure:
            pass
        elif state is TaskState.COMPLETED:
            self.task_service.record_external_event(
                run.controller_task_id,
                "finished",
                {
                    "message": "远端流量测试已完成",
                    "result": {
                        "traffic_run_id": run.traffic_run_id,
                        "summary": summary,
                        "result_reference": updated_run.result_reference,
                    },
                },
                source="agent",
                site_name=self.site_name,
            )
        elif state is TaskState.CANCELLED:
            self.task_service.record_external_event(
                run.controller_task_id,
                "cancelled",
                {"message": "远端流量测试已取消", "error": error_message or "任务已取消"},
                source="agent",
                site_name=self.site_name,
            )
        else:
            self.task_service.record_external_event(
                run.controller_task_id,
                "error",
                {"code": error_code, "message": "远端流量测试失败", "error": error_message or "Agent 任务失败"},
                source="agent",
                site_name=self.site_name,
            )
        self.repository.save(updated_run)
        self.repository.save_agent_mapping(updated_mapping)
        self._record_domain_event(
            updated_run,
            TrafficEventType.STATE,
            {
                "state": effective_state.value,
                "remote_state": state.value,
                "error_code": updated_run.error_code,
                "error_message": updated_run.error_message,
            },
        )
        return updated_mapping

    async def _persist_remote_events(
        self,
        run: TrafficRun,
        mapping: AgentTaskMapping,
        events: list[AgentTaskEventDTO],
    ) -> None:
        await _to_thread(self._persist_remote_events_sync, run, mapping, events)

    def _persist_remote_events_sync(
        self,
        run: TrafficRun,
        mapping: AgentTaskMapping,
        remote_events: list[AgentTaskEventDTO],
    ) -> None:
        events = [self._traffic_event(run, mapping, item) for item in remote_events]
        store = self._event_store(run.traffic_run_id)
        accepted = store.append_many(events)
        self._append_iperf_raw_events(run, accepted)
        ping_samples: list[TrafficPingSample] = []
        latest_run = self._require_run(run.traffic_run_id)
        started_at = _parse_datetime(latest_run.started_at)
        for event in events:
            if latest_run.test_type is TrafficTestType.IPERF_CLIENT or latest_run.test_type is TrafficTestType.IPERF_SERVER:
                if event.type is TrafficEventType.STDOUT:
                    line = str(event.payload.get("line") or "")
                    row = parse_iperf_line(line, started_at, collector_time=_parse_datetime(event.timestamp)) if line else None
                    if row is not None and latest_run.local_iperf_run_id:
                        key = f"agent:{mapping.agent_id}:{mapping.agent_task_id}:{event.remote_sequence}"
                        self.iperf_store.append_interval(latest_run.local_iperf_run_id, row, source_event_key=key)
            elif latest_run.test_type in {TrafficTestType.HIGH_FREQUENCY_PING, TrafficTestType.TCP_PORT_TEST} and event.type is TrafficEventType.SAMPLE:
                sample = _ping_sample(latest_run.traffic_run_id, event)
                if sample is not None:
                    ping_samples.append(sample)
        if ping_samples:
            self.repository.insert_ping_samples(ping_samples, updated_at=events[-1].timestamp)
        for event in accepted:
            self.events.publish(event)

    def _traffic_event(self, run: TrafficRun, mapping: AgentTaskMapping, event: AgentTaskEventDTO) -> TrafficEvent:
        try:
            event_type = TrafficEventType(str(event.type))
            payload = dict(event.payload)
        except ValueError:
            event_type = TrafficEventType.SYSTEM
            payload = {"remote_type": str(event.type), "remote_payload": dict(event.payload)}
        return TrafficEvent(
            traffic_run_id=run.traffic_run_id,
            controller_task_id=run.controller_task_id,
            source=f"agent:{mapping.agent_id}:{event.source or 'task'}",
            type=event_type,
            payload=payload,
            timestamp=_datetime_text(event.timestamp) or utc_now_iso(),
            remote_sequence=event.sequence,
        )

    def _record_controller_state(self, run: TrafficRun, state: TaskState, message: str) -> None:
        latest = self._require_run(run.traffic_run_id)
        if latest.status in TERMINAL_TASK_STATES:
            return
        if latest.status is TaskState.STOPPING and state in {TaskState.STARTING, TaskState.RUNNING}:
            return
        if latest.status is not state:
            now = utc_now_iso()
            self.repository.save(
                replace(
                    latest,
                    status=state,
                    started_at=latest.started_at or (now if state is TaskState.RUNNING else ""),
                    updated_at=now,
                )
            )
        task = self.task_service.get_task(run.controller_task_id)
        if task is not None and task.status is state:
            return
        self.task_service.record_external_event(
            run.controller_task_id,
            "state",
            {"state": state.value, "message": message},
            source="agent",
            site_name=self.site_name,
        )

    def _record_domain_event(self, run: TrafficRun, event_type: TrafficEventType, payload: dict[str, Any]) -> None:
        event = self._event_store(run.traffic_run_id).append(
            TrafficEvent(
                traffic_run_id=run.traffic_run_id,
                controller_task_id=run.controller_task_id,
                source="controller",
                type=event_type,
                payload=payload,
            )
        )
        if event is not None:
            self.events.publish(event)

    def _start_iperf_result_run(
        self,
        run: TrafficRun,
        iperf_run_id: str,
        remote: AgentTaskDTO,
        config: IperfClientConfig | IperfServerConfig | None,
    ) -> None:
        client_config = config if isinstance(config, IperfClientConfig) else None
        raw_log = self._iperf_raw_log_path(run.traffic_run_id)
        raw_log.parent.mkdir(parents=True, exist_ok=True)
        raw_log.touch(exist_ok=True)
        self.iperf_store.start_run(
            iperf_run_id,
            mode="client" if run.test_type is TrafficTestType.IPERF_CLIENT else "server",
            command=[],
            log_file=raw_log,
            started_at=_datetime_value(remote.start_time) or datetime.now(UTC),
            config=client_config,
        )

    def _iperf_raw_log_path(self, traffic_run_id: str) -> Path:
        return self.paths.traffic_run_dir(self.site_name, traffic_run_id) / "raw" / "agent_iperf.log"

    def _append_iperf_raw_events(self, run: TrafficRun, events: list[TrafficEvent]) -> None:
        if run.test_type not in {TrafficTestType.IPERF_SERVER, TrafficTestType.IPERF_CLIENT}:
            return
        rows: list[str] = []
        for event in events:
            if event.type not in {TrafficEventType.STDOUT, TrafficEventType.STDERR}:
                continue
            line = str(event.payload.get("line") or "")
            if not line:
                continue
            rows.append(f"[{event.timestamp}] [remote_sequence={event.remote_sequence}] [{event.type.value}] {line}\n")
        if not rows:
            return
        path = self._iperf_raw_log_path(run.traffic_run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._raw_log_lock, path.open("a", encoding="utf-8", newline="") as file:
            file.writelines(rows)
            file.flush()

    async def _invoke(
        self,
        agent_id: str,
        operation: AgentCall[_T],
        *,
        require_online: bool = False,
        test_type: TrafficTestType | None = None,
    ) -> _T:
        config = self._require_agent(agent_id)
        if not config.enabled:
            raise TrafficTestError(TrafficErrorCode.AGENT_DISABLED, "Agent 已禁用")
        token = self._credential_for(config)
        if require_online and test_type is not None:
            self.validate_target(agent_id, test_type)
        return await operation(config.base_url, token)

    def _credential_for(self, config: AgentConfig) -> str | None:
        if config.authentication_type is AgentAuthenticationType.NONE:
            return None
        token = self.agent_controller.credentials.get(config.credential_reference)
        if token is None:
            raise TrafficTestError(TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED, "Agent Token 未加载")
        return token

    def _require_agent(self, agent_id: str) -> AgentConfig:
        config = self.agent_controller.repository.get(str(agent_id or ""))
        if config is None:
            raise TrafficTestError(TrafficErrorCode.AGENT_NOT_FOUND, "Agent 不存在或已归档")
        return config

    def _run(self, value: TrafficRun | str, expected: TrafficTestType) -> TrafficRun:
        run = value if isinstance(value, TrafficRun) else self._require_run(str(value or ""))
        if run.test_type is not expected or run.executor_kind is not ExecutionTargetKind.AGENT or not run.agent_id:
            raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "Traffic Run 与 Agent 执行类型不匹配")
        return run

    def _require_run(self, traffic_run_id: str) -> TrafficRun:
        run = self.repository.get(traffic_run_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "Traffic Run 不存在")
        return run

    def _is_start_failure_cleanup(self, run: TrafficRun) -> bool:
        task = self.task_service.get_task(run.controller_task_id)
        return (
            run.status in {TaskState.STOPPING, TaskState.FAILED}
            and bool(run.error_code)
            and task is not None
            and task.status is TaskState.FAILED
        )

    def _mapping(self, value: AgentTaskMapping | str) -> AgentTaskMapping:
        mapping = value if isinstance(value, AgentTaskMapping) else self.repository.get_agent_mapping(str(value or ""))
        if mapping is None:
            raise TrafficTestError(TrafficErrorCode.REMOTE_TASK_NOT_FOUND, "Agent 任务映射不存在")
        return mapping

    @staticmethod
    def _map_status(value: str) -> TaskState:
        status = _REMOTE_STATUS_MAP.get(str(value or "").lower())
        if status is None:
            raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, f"Agent 返回未知任务状态：{value}")
        return status

    @staticmethod
    def _validate_remote_task(task: AgentTaskDTO, expected_type: str, expected_id: str = "") -> None:
        if not task.task_id or (expected_id and task.task_id != expected_id):
            raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "Agent 返回了错误的任务 ID")
        if task.task_type != expected_type:
            raise TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, "Agent 返回了错误的任务类型")
        AgentTrafficAdapter._map_status(task.status)

    def _event_store(self, traffic_run_id: str) -> TrafficEventStore:
        return self._event_store_factory(traffic_run_id)


def _traffic_error(error: AgentClientError) -> TrafficTestError:
    direct = {
        "AGENT_TRAFFIC_INVALID_CONFIG": TrafficErrorCode.INVALID_CONFIG,
        "AGENT_TRAFFIC_PORT_IN_USE": TrafficErrorCode.SERVER_PORT_IN_USE,
        "AGENT_TRAFFIC_TASK_NOT_FOUND": TrafficErrorCode.REMOTE_TASK_NOT_FOUND,
        "AGENT_TASK_NOT_FOUND": TrafficErrorCode.REMOTE_TASK_NOT_FOUND,
        "AGENT_TRAFFIC_EVENT_CURSOR_INVALID": TrafficErrorCode.EVENT_CURSOR_INVALID,
    }.get(str(error.code or "").upper())
    if direct is not None:
        return TrafficTestError(direct, error.message)
    return map_agent_error(error.code, error.message)


def _state_message(state: TaskState) -> str:
    return {
        TaskState.STARTING: "远端任务正在启动",
        TaskState.RUNNING: "远端任务运行中",
        TaskState.STOPPING: "远端任务正在停止",
    }.get(state, state.value)


def _bandwidth_mbps(config: IperfClientConfig) -> float:
    if config.protocol == "UDP" and config.udp_bitrate_mbps is not None:
        return max(0.0, float(config.udp_bitrate_mbps))
    text = str(config.target_bandwidth or "").strip().upper()
    if not text:
        return 0.0
    multiplier = {"K": 0.001, "M": 1.0, "G": 1_000.0}.get(text[-1:], 1.0)
    try:
        return max(0.0, float(text[:-1] if text[-1:] in "KMG" else text) * multiplier)
    except ValueError:
        return 0.0


def _size_bytes(value: str | None) -> int:
    text = str(value or "").strip().upper()
    if not text:
        return 0
    multiplier = 1
    if text[-1:] == "K":
        multiplier, text = 1_024, text[:-1]
    elif text[-1:] == "M":
        multiplier, text = 1_048_576, text[:-1]
    try:
        return max(0, round(float(text) * multiplier))
    except ValueError:
        return 0


def _ping_sample(traffic_run_id: str, event: TrafficEvent) -> TrafficPingSample | None:
    payload = event.payload
    target = str(payload.get("target") or "")
    if not target or event.remote_sequence is None:
        return None
    ok = bool(payload.get("ok"))
    error = str(payload.get("error") or "")
    timeout = not ok and (str(payload.get("raw_type") or "") == "timeout" or error == "timeout")
    rtt = payload.get("rtt_ms")
    return TrafficPingSample(
        traffic_run_id=traffic_run_id,
        sequence=int(event.remote_sequence),
        timestamp=event.timestamp,
        target=target,
        probe_sequence=int(payload["probe_sequence"]) if payload.get("probe_sequence") is not None else None,
        ok=ok,
        rtt_ms=float(rtt) if ok and rtt is not None else None,
        timeout=timeout,
        packet_size=int(payload["packet_size"]) if payload.get("packet_size") is not None else None,
        error_code=error,
        error_message=error,
    )


def _result_payload(result: AgentTaskResultDTO) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "task_type": result.task_type,
        "status": result.status,
        "started_at": _datetime_text(result.started_at),
        "finished_at": _datetime_text(result.finished_at),
        "summary": dict(result.summary),
        "artifacts": [
            {"name": item.name, "kind": item.kind, "available": item.available}
            for item in result.artifacts
        ],
        "last_sequence": result.last_sequence,
        "error_code": result.error_code,
        "error": result.error,
    }


def _relative_reference(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _datetime_value(value: datetime | None) -> datetime | None:
    return value


def _datetime_text(value: datetime | None) -> str:
    if value is None:
        return ""
    selected = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return selected.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)


async def _to_thread(function: Callable[..., _T], *args: Any) -> _T:
    import asyncio

    return await asyncio.to_thread(function, *args)


__all__ = ["AgentSyncOutcome", "AgentTrafficAdapter"]
