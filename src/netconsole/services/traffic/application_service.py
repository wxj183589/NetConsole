from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import replace
from typing import Any

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.models.traffic_test import (
    ExecutionTargetDTO,
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficEvent,
    TrafficEventType,
    TrafficRun,
    TrafficSyncState,
    TrafficTestType,
    TcpPortTestConfig,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfServerConfig
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


class TrafficTestApplicationService:
    """本地和 Agent 流量测试共享的纯 Python 应用层。"""

    def __init__(
        self,
        *,
        paths: PathResolver | None = None,
        site_name: str = "demo",
        task_service: TaskApplicationService | None = None,
        repository: TrafficRunRepository | None = None,
        event_hub: Any | None = None,
        local_adapter: Any | None = None,
        agent_adapter: Any | None = None,
        supervisor: Any | None = None,
        agent_controller: Any | None = None,
    ) -> None:
        self.paths = paths or PathResolver()
        self.site_name = str(site_name or "demo")
        self.task_service = task_service or TaskApplicationService(paths=self.paths, site_name=self.site_name)
        self.repository = repository or TrafficRunRepository(self.paths.traffic_runs_db_path(self.site_name))
        if event_hub is None:
            from netconsole.services.traffic.event_hub import TrafficEventHub

            event_hub = TrafficEventHub()
        self.events = event_hub
        if local_adapter is None:
            from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
            from netconsole.services.traffic.local_adapter import LocalTrafficAdapter

            local_adapter = LocalTrafficAdapter(
                self.paths,
                site_name=self.site_name,
                process_adapter=LocalProcessAdapter(self.task_service),
                repository=self.repository,
                event_hub=self.events,
            )
        if agent_adapter is None and agent_controller is not None:
            from netconsole.services.traffic.agent_adapter import AgentTrafficAdapter

            agent_adapter = AgentTrafficAdapter(
                agent_controller,
                self.repository,
                self.task_service,
                paths=self.paths,
                site_name=self.site_name,
                event_hub=self.events,
            )
        if supervisor is None and agent_adapter is not None:
            from netconsole.services.traffic.agent_supervisor import AgentTrafficSupervisor

            supervisor = AgentTrafficSupervisor(agent_adapter, self.repository)
        self.local_adapter = local_adapter
        self.agent_adapter = agent_adapter
        self.supervisor = supervisor
        self._reconcile_local_runs()

    async def start(self) -> None:
        if self.supervisor is not None:
            await _maybe_await(self.supervisor.start())

    async def stop(self) -> None:
        if self.supervisor is not None:
            await _maybe_await(self.supervisor.stop())
        shutdown = getattr(self.local_adapter, "shutdown", None)
        if shutdown is not None:
            await asyncio.to_thread(shutdown)

    async def start_iperf_server(
        self,
        config: IperfServerConfig,
        execution_target: ExecutionTargetDTO,
        *,
        parent_task_id: str = "",
        correlation_id: str = "",
        retry_of_traffic_run_id: str = "",
    ) -> TrafficRun:
        normalized = _normalize_server_config(config)
        return await self._start(
            TrafficTestType.IPERF_SERVER,
            "server",
            normalized,
            _server_config_dict(normalized),
            execution_target,
            parent_task_id=parent_task_id,
            correlation_id=correlation_id,
            retry_of_traffic_run_id=retry_of_traffic_run_id,
        )

    async def start_iperf_client(
        self,
        config: IperfClientConfig,
        execution_target: ExecutionTargetDTO,
        *,
        parent_task_id: str = "",
        correlation_id: str = "",
        retry_of_traffic_run_id: str = "",
    ) -> TrafficRun:
        normalized = _normalize_client_config(config)
        return await self._start(
            TrafficTestType.IPERF_CLIENT,
            "client",
            normalized,
            normalized.as_dict(),
            execution_target,
            parent_task_id=parent_task_id,
            correlation_id=correlation_id,
            retry_of_traffic_run_id=retry_of_traffic_run_id,
        )

    async def start_high_frequency_ping(
        self,
        config: HighFrequencyPingConfig,
        execution_target: ExecutionTargetDTO,
        *,
        parent_task_id: str = "",
        correlation_id: str = "",
        retry_of_traffic_run_id: str = "",
    ) -> TrafficRun:
        try:
            normalized = config.normalized()
        except (TypeError, ValueError) as exc:
            raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, str(exc)) from exc
        if execution_target.kind is ExecutionTargetKind.LOCAL and normalized.source_address:
            raise TrafficTestError(
                TrafficErrorCode.CAPABILITY_UNSUPPORTED,
                "本地高频 Ping 暂不支持指定源地址",
            )
        return await self._start(
            TrafficTestType.HIGH_FREQUENCY_PING,
            "ping",
            normalized,
            normalized.to_dict(),
            execution_target,
            parent_task_id=parent_task_id,
            correlation_id=correlation_id,
            retry_of_traffic_run_id=retry_of_traffic_run_id,
        )

    async def start_tcp_port_test(
        self,
        config: TcpPortTestConfig,
        execution_target: ExecutionTargetDTO,
        *,
        retry_of_traffic_run_id: str = "",
    ) -> TrafficRun:
        try:
            normalized = config.normalized()
        except (TypeError, ValueError) as exc:
            raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, str(exc)) from exc
        return await self._start(
            TrafficTestType.TCP_PORT_TEST,
            "tcp_probe",
            normalized,
            normalized.to_dict(),
            execution_target,
            parent_task_id="",
            correlation_id="",
            retry_of_traffic_run_id=retry_of_traffic_run_id,
        )

    async def cancel(self, controller_task_id: str) -> TrafficRun:
        run = self._require_run_by_task(controller_task_id)
        if run.status in TERMINAL_TASK_STATES or run.status is TaskState.STOPPING:
            return run
        if run.executor_kind is ExecutionTargetKind.LOCAL:
            if self.local_adapter is None:
                raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "本地执行适配器未配置")
            await _maybe_await(self.local_adapter.cancel(controller_task_id))
            return self.repository.get(run.traffic_run_id) or run

        stopping = replace(run, status=TaskState.STOPPING, updated_at=utc_now_iso())
        self.repository.save(stopping)
        mapping = self.repository.get_agent_mapping(run.traffic_run_id)
        if mapping is None:
            failed = replace(
                stopping,
                status=TaskState.FAILED,
                finished_at=utc_now_iso(),
                error_code=TrafficErrorCode.REMOTE_TASK_NOT_FOUND.value,
                error_message="未找到 Agent 任务映射",
                sync_state=TrafficSyncState.ERROR,
                updated_at=utc_now_iso(),
            )
            self.repository.save(failed)
            try:
                self._record_start_failure_event(failed)
            except Exception:
                app_logger.log_error("TRAFFIC_START_EVENT_PERSIST_FAILED", f"run_id={failed.traffic_run_id}")
            self._record_agent_terminal(failed, "error")
            return failed
        if self.agent_adapter is None:
            raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "Agent 执行适配器未配置")
        self.task_service.record_external_event(
            controller_task_id,
            "state",
            {"state": TaskState.STOPPING.value, "message": "正在停止 Agent 流量任务"},
            source="traffic",
        )
        try:
            await _maybe_await(self.agent_adapter.stop(mapping))
        except TrafficTestError as exc:
            now = utc_now_iso()
            self.repository.save(
                replace(
                    stopping,
                    sync_state=TrafficSyncState.ERROR,
                    error_code=exc.code,
                    error_message=exc.message,
                    updated_at=now,
                )
            )
            marker = getattr(self.agent_adapter, "mark_sync_state", None)
            if marker is not None:
                await _maybe_await(
                    marker(
                        mapping,
                        TrafficSyncState.ERROR,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
            raise
        if self.supervisor is not None:
            self.supervisor.attach(run.traffic_run_id)
        return self.repository.get(run.traffic_run_id) or stopping

    async def retry(self, controller_task_id: str) -> TrafficRun:
        previous = self._require_run_by_task(controller_task_id)
        target = ExecutionTargetDTO(
            kind=previous.executor_kind,
            agent_id=previous.agent_id,
            display_name=previous.agent_id,
        )
        common = {
            "parent_task_id": previous.parent_task_id,
            "correlation_id": previous.correlation_id,
            "retry_of_traffic_run_id": previous.traffic_run_id,
        }
        if previous.test_type is TrafficTestType.IPERF_SERVER:
            return await self.start_iperf_server(_server_config_from_dict(previous.normalized_config), target, **common)
        if previous.test_type is TrafficTestType.IPERF_CLIENT:
            return await self.start_iperf_client(_client_config_from_dict(previous.normalized_config), target, **common)
        if previous.test_type is TrafficTestType.HIGH_FREQUENCY_PING:
            return await self.start_high_frequency_ping(_ping_config_from_dict(previous.normalized_config), target, **common)
        if previous.test_type is TrafficTestType.TCP_PORT_TEST:
            return await self.start_tcp_port_test(
                _tcp_port_config_from_dict(previous.normalized_config),
                target,
                retry_of_traffic_run_id=previous.traffic_run_id,
            )
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "不支持重试该流量任务")

    def get_run(self, traffic_run_id: str) -> TrafficRun | None:
        return self.repository.get(traffic_run_id)

    def get_run_by_task(self, controller_task_id: str) -> TrafficRun | None:
        return self.repository.get_by_controller_task(controller_task_id)

    def list_runs(
        self,
        *,
        statuses: set[TaskState] | None = None,
        test_type: TrafficTestType | None = None,
        executor_kind: ExecutionTargetKind | None = None,
        agent_id: str | None = None,
        limit: int = 200,
    ) -> list[TrafficRun]:
        return self.repository.list(
            statuses=statuses,
            test_type=test_type,
            executor_kind=executor_kind,
            agent_id=agent_id,
            limit=limit,
        )

    def get_events(self, traffic_run_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        if self.repository.get(traffic_run_id) is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        if int(after) < 0:
            raise TrafficTestError(TrafficErrorCode.EVENT_CURSOR_INVALID, "事件游标不能小于 0")
        from netconsole.services.traffic.event_store import TrafficEventStore

        store = TrafficEventStore(self.paths, self.repository, self.site_name)
        events = store.list_events(traffic_run_id, after_sequence=after, limit=limit)
        return [event.to_dict() if hasattr(event, "to_dict") else dict(event) for event in events]

    def get_ping_samples(
        self,
        traffic_run_id: str,
        *,
        after: int = 0,
        target: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 1_000,
    ) -> list[Any]:
        if self.repository.get(traffic_run_id) is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        if int(after) < 0:
            raise TrafficTestError(TrafficErrorCode.EVENT_CURSOR_INVALID, "采样游标不能小于 0")
        return self.repository.list_ping_samples(
            traffic_run_id,
            after_sequence=after,
            target=target,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    def get_summary(self, traffic_run_id: str) -> dict[str, Any]:
        run = self.repository.get(traffic_run_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return dict(run.summary)

    async def _start(
        self,
        test_type: TrafficTestType,
        role: str,
        config: object,
        normalized_config: dict[str, Any],
        execution_target: ExecutionTargetDTO,
        *,
        parent_task_id: str,
        correlation_id: str,
        retry_of_traffic_run_id: str,
    ) -> TrafficRun:
        self._validate_execution_target(execution_target)
        if execution_target.kind is ExecutionTargetKind.AGENT:
            if self.agent_adapter is None:
                raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "Agent 执行适配器未配置")
            validator = getattr(self.agent_adapter, "validate_target", None)
            if validator is not None:
                await _maybe_await(validator(execution_target.agent_id, test_type))

        now = utc_now_iso()
        run = TrafficRun(
            traffic_run_id=uuid.uuid4().hex,
            controller_task_id=uuid.uuid4().hex,
            test_type=test_type,
            role=role,
            executor_kind=execution_target.kind,
            agent_id=execution_target.agent_id,
            normalized_config=dict(normalized_config),
            status=TaskState.PENDING,
            created_at=now,
            updated_at=now,
            retry_of_traffic_run_id=retry_of_traffic_run_id,
            parent_task_id=parent_task_id,
            correlation_id=correlation_id,
            sync_state=TrafficSyncState.ACTIVE,
        )
        self.repository.create(run)
        external_created = False
        try:
            if execution_target.kind is ExecutionTargetKind.LOCAL:
                if self.local_adapter is None:
                    raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "本地执行适配器未配置")
                await _maybe_await(self._start_local(run, config))
            else:
                self.task_service.create_external_task(
                    task_id=run.controller_task_id,
                    task_type=_controller_task_type(run, remote=True),
                    task_name=_task_name(run),
                    source="agent",
                    owner="controller",
                    agent=execution_target.agent_id,
                    site_name=self.site_name,
                )
                external_created = True
                await _maybe_await(self._start_agent(run, config))
                if self.supervisor is not None:
                    self.supervisor.attach(run.traffic_run_id)
        except Exception as exc:
            error = exc if isinstance(exc, TrafficTestError) else TrafficTestError(
                TrafficErrorCode.PROCESS_START_FAILED if execution_target.kind is ExecutionTargetKind.LOCAL else TrafficErrorCode.REMOTE_SYNC_FAILED,
                str(exc) or "流量任务启动失败",
            )
            leftover_mapping = (
                self.repository.get_agent_mapping(run.traffic_run_id)
                if execution_target.kind is ExecutionTargetKind.AGENT
                else None
            )
            cleanup_pending = leftover_mapping is not None
            now = utc_now_iso()
            latest_run = self.repository.get(run.traffic_run_id) or run
            failed = replace(
                latest_run,
                status=TaskState.STOPPING if cleanup_pending else TaskState.FAILED,
                finished_at="" if cleanup_pending else now,
                error_code=error.code,
                error_message=error.message,
                sync_state=TrafficSyncState.ERROR,
                updated_at=now,
            )
            self.repository.save(failed)
            try:
                self._record_start_failure_event(failed)
            except Exception:
                app_logger.log_error("TRAFFIC_START_EVENT_PERSIST_FAILED", f"run_id={failed.traffic_run_id}")
            if cleanup_pending and self.supervisor is not None:
                self.supervisor.attach(run.traffic_run_id)
            if external_created:
                self._record_agent_terminal(failed, "error")
            if error is exc:
                raise error
            raise error from exc
        return self.repository.get(run.traffic_run_id) or run

    def _start_local(self, run: TrafficRun, config: object) -> object:
        if run.test_type is TrafficTestType.IPERF_SERVER:
            return self.local_adapter.start_iperf_server(run, config)
        if run.test_type is TrafficTestType.IPERF_CLIENT:
            return self.local_adapter.start_iperf_client(run, config)
        if run.test_type is TrafficTestType.TCP_PORT_TEST:
            return self.local_adapter.start_tcp_port_test(run, config)
        return self.local_adapter.start_high_frequency_ping(run, config)

    def _start_agent(self, run: TrafficRun, config: object) -> object:
        if run.test_type is TrafficTestType.IPERF_SERVER:
            return self.agent_adapter.start_iperf_server(run, config)
        if run.test_type is TrafficTestType.IPERF_CLIENT:
            return self.agent_adapter.start_iperf_client(run, config)
        if run.test_type is TrafficTestType.TCP_PORT_TEST:
            return self.agent_adapter.start_tcp_port_test(run, config)
        return self.agent_adapter.start_high_frequency_ping(run, config)

    @staticmethod
    def _validate_execution_target(target: ExecutionTargetDTO) -> None:
        if target.kind is ExecutionTargetKind.LOCAL and target.agent_id:
            raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "本地执行端不能包含 agent_id")
        if target.kind is ExecutionTargetKind.AGENT and not target.agent_id:
            raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "Agent 执行端缺少 agent_id")

    def _require_run_by_task(self, controller_task_id: str) -> TrafficRun:
        run = self.repository.get_by_controller_task(controller_task_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return run

    def _record_agent_terminal(self, run: TrafficRun, event_type: str) -> None:
        try:
            self.task_service.record_external_event(
                run.controller_task_id,
                event_type,
                {
                    "message": run.error_message or "Agent 流量任务失败",
                    "error": run.error_message,
                    "error_code": run.error_code,
                },
                source="traffic",
            )
        except KeyError:
            return

    def _record_start_failure_event(self, run: TrafficRun) -> None:
        from netconsole.services.traffic.event_store import TrafficEventStore

        store = TrafficEventStore(self.paths, self.repository, self.site_name)
        event = store.append(
            TrafficEvent(
                traffic_run_id=run.traffic_run_id,
                controller_task_id=run.controller_task_id,
                source="application",
                type=TrafficEventType.ERROR,
                payload={"code": run.error_code, "message": run.error_message},
            )
        )
        if event is not None:
            self.events.publish(event)

    def _reconcile_local_runs(self) -> None:
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        for run in self.repository.list(statuses=active, executor_kind=ExecutionTargetKind.LOCAL, limit=2_000):
            snapshot = self.task_service.get_task(run.controller_task_id)
            if snapshot is not None and snapshot.status in active:
                continue
            if snapshot is not None and snapshot.status is TaskState.COMPLETED:
                continue
            now = utc_now_iso()
            message = (
                snapshot.error_message
                if snapshot is not None and snapshot.error_message
                else "上次本地流量任务宿主已退出，无法接管原 Worker"
            )
            self.repository.save(
                replace(
                    run,
                    status=TaskState.CANCELLED if snapshot is not None and snapshot.status is TaskState.CANCELLED else TaskState.FAILED,
                    finished_at=snapshot.finished_time if snapshot is not None and snapshot.finished_time else now,
                    error_code="" if snapshot is not None and snapshot.status is TaskState.CANCELLED else TrafficErrorCode.PROCESS_EXITED.value,
                    error_message=message,
                    sync_state=TrafficSyncState.COMPLETED if snapshot is not None and snapshot.status is TaskState.CANCELLED else TrafficSyncState.ERROR,
                    updated_at=now,
                )
            )


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_server_config(config: IperfServerConfig) -> IperfServerConfig:
    try:
        port = int(config.port)
        interval = int(config.interval_seconds)
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "iPerf 服务端配置无效") from exc
    if not 1 <= port <= 65_535 or not 1 <= interval <= 60:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "iPerf 端口或报告间隔超出范围")
    return IperfServerConfig(
        bind_ip=str(config.bind_ip or "").strip(),
        port=port,
        interval_seconds=interval,
        one_off=bool(config.one_off),
    )


def _normalize_client_config(config: IperfClientConfig) -> IperfClientConfig:
    try:
        if not str(config.server_ip or "").strip():
            raise ValueError("iPerf 服务端地址不能为空")
        if not 1 <= int(config.port) <= 65_535:
            raise ValueError("iPerf 端口超出范围")
        if str(config.protocol or "").upper() not in {"TCP", "UDP"}:
            raise ValueError("iPerf 协议必须是 TCP 或 UDP")
        if not 1 <= int(config.duration_seconds) <= 86_400:
            raise ValueError("iPerf 时长必须在 1 到 86400 秒之间")
        if not 1 <= int(config.interval_seconds) <= 60:
            raise ValueError("iPerf 报告间隔必须在 1 到 60 秒之间")
        if not 1 <= int(config.parallel) <= 128:
            raise ValueError("iPerf 并行流必须在 1 到 128 之间")
        if str(config.direction or "").lower() not in {"upload", "download", "bidirectional"}:
            raise ValueError("iPerf 方向无效")
        if config.follow_collection:
            raise ValueError("通用流量测试不支持随 Online MR 采集运行")
        return config.normalized()
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, str(exc)) from exc


def _server_config_dict(config: IperfServerConfig) -> dict[str, Any]:
    return {
        "bind_ip": config.bind_ip,
        "port": config.port,
        "interval_seconds": config.interval_seconds,
        "one_off": config.one_off,
    }


def _server_config_from_dict(value: dict[str, Any]) -> IperfServerConfig:
    return IperfServerConfig(
        bind_ip=str(value.get("bind_ip") or ""),
        port=int(value.get("port") or 5201),
        interval_seconds=int(value.get("interval_seconds") or 1),
        one_off=bool(value.get("one_off")),
    )


def _client_config_from_dict(value: dict[str, Any]) -> IperfClientConfig:
    fields = IperfClientConfig.__dataclass_fields__
    return IperfClientConfig(**{name: value[name] for name in fields if name in value})


def _ping_config_from_dict(value: dict[str, Any]) -> HighFrequencyPingConfig:
    return HighFrequencyPingConfig(
        targets=tuple(str(item) for item in value.get("targets") or ()),
        interval_ms=int(value.get("interval_ms") or 100),
        timeout_ms=int(value.get("timeout_ms") or 100),
        packet_size=int(value.get("packet_size") or 64),
        count=int(value.get("count") if value.get("count") is not None else 20),
        continuous=bool(value.get("continuous")),
        source_address=str(value.get("source_address") or ""),
    )


def _tcp_port_config_from_dict(value: dict[str, Any]) -> TcpPortTestConfig:
    return TcpPortTestConfig(
        target=str(value.get("target") or ""),
        port=int(value.get("port") or 0),
        interval_ms=int(value.get("interval_ms") or 1_000),
        timeout_ms=int(value.get("timeout_ms") or 3_000),
        count=int(value.get("count") or 4),
    )


def _controller_task_type(run: TrafficRun, *, remote: bool) -> str:
    prefix = "traffic_agent" if remote else "traffic_local"
    suffix = {
        TrafficTestType.IPERF_SERVER: "iperf_server",
        TrafficTestType.IPERF_CLIENT: "iperf_client",
        TrafficTestType.HIGH_FREQUENCY_PING: "fping",
        TrafficTestType.TCP_PORT_TEST: "tcp_port_test",
    }[run.test_type]
    return f"{prefix}_{suffix}"


def _task_name(run: TrafficRun) -> str:
    return {
        TrafficTestType.IPERF_SERVER: "iPerf 服务端",
        TrafficTestType.IPERF_CLIENT: "iPerf 客户端",
        TrafficTestType.HIGH_FREQUENCY_PING: "高频 Ping",
        TrafficTestType.TCP_PORT_TEST: "TCP 端口测试",
    }[run.test_type]


__all__ = ["TrafficTestApplicationService"]
