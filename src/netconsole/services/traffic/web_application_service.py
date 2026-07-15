from __future__ import annotations

import asyncio
from typing import Any

from netconsole.models.agent import AgentStatus
from netconsole.models.api.traffic import TrafficExecutionTargetDTO
from netconsole.models.task_state import TaskState, TERMINAL_TASK_STATES
from netconsole.models.traffic_test import (
    ExecutionTargetDTO,
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficRun,
    TrafficRunPage,
    TrafficTestType,
)
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfServerConfig
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


_MAX_PAGE_SIZE = 500
_LOCAL_CAPABILITIES = {
    "iperf_server": True,
    "iperf_client": True,
    "fping": True,
    "tcp_ping_probe": True,
}


class TrafficWebApplicationService:
    """Traffic REST/WebSocket 使用的最小应用 Facade。"""

    def __init__(self, traffic_service: TrafficTestApplicationService, agent_service: Any | None = None) -> None:
        self.traffic_service = traffic_service
        self.agent_service = agent_service
        self._cancel_lock = asyncio.Lock()

    @property
    def events(self) -> Any:
        return self.traffic_service.events

    async def start_iperf_server(
        self,
        config: IperfServerConfig,
        execution_target: ExecutionTargetDTO,
        **kwargs: str,
    ) -> TrafficRun:
        return await self.traffic_service.start_iperf_server(config, execution_target, **kwargs)

    async def start_iperf_client(
        self,
        config: IperfClientConfig,
        execution_target: ExecutionTargetDTO,
        **kwargs: str,
    ) -> TrafficRun:
        return await self.traffic_service.start_iperf_client(config, execution_target, **kwargs)

    async def start_high_frequency_ping(
        self,
        config: HighFrequencyPingConfig,
        execution_target: ExecutionTargetDTO,
        **kwargs: str,
    ) -> TrafficRun:
        return await self.traffic_service.start_high_frequency_ping(config, execution_target, **kwargs)

    def list_execution_targets(self) -> list[TrafficExecutionTargetDTO]:
        targets = [
            TrafficExecutionTargetDTO(
                kind=ExecutionTargetKind.LOCAL,
                id="LOCAL",
                display_name="本机",
                capabilities=dict(_LOCAL_CAPABILITIES),
            )
        ]
        if self.agent_service is None:
            return targets
        for agent in self.agent_service.list_agents():
            capabilities = dict(agent.get("capabilities") or {})
            available, reason = _agent_availability(agent, capabilities)
            agent_id = str(agent.get("agent_id") or "")
            targets.append(
                TrafficExecutionTargetDTO(
                    kind=ExecutionTargetKind.AGENT,
                    id=agent_id,
                    agent_id=agent_id,
                    display_name=str(agent.get("name") or agent_id or "Agent"),
                    available=available,
                    unavailable_reason=reason,
                    status=str(agent.get("status") or ""),
                    platform=str(agent.get("platform") or ""),
                    architecture=str(agent.get("architecture") or ""),
                    version=str(agent.get("version") or ""),
                    capabilities=capabilities,
                )
            )
        return targets

    def list_runs(
        self,
        *,
        statuses: set[TaskState] | None = None,
        test_type: TrafficTestType | None = None,
        executor_kind: ExecutionTargetKind | None = None,
        agent_id: str | None = None,
        created_after: str = "",
        created_before: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> TrafficRunPage:
        offset, limit = _page_args(offset, limit)
        return self.traffic_service.list_runs_page(
            statuses=set(statuses or ()),
            test_type=test_type,
            executor_kind=executor_kind,
            agent_id=str(agent_id or "").strip() or None,
            created_after=str(created_after or "").strip(),
            created_before=str(created_before or "").strip(),
            offset=offset,
            limit=limit,
        )

    def get_run(self, traffic_run_id: str) -> TrafficRun | None:
        return self.traffic_service.get_run(traffic_run_id)

    def require_run(self, traffic_run_id: str) -> TrafficRun:
        return self._require_run(traffic_run_id)

    def get_events(self, traffic_run_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self.traffic_service.get_events(traffic_run_id, after=after, limit=limit)

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
        return self.traffic_service.get_ping_samples(
            traffic_run_id,
            after=after,
            target=target,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    def get_summary(self, traffic_run_id: str) -> dict[str, Any]:
        return self.traffic_service.get_summary(traffic_run_id)

    async def cancel_run(self, traffic_run_id: str) -> TrafficRun:
        async with self._cancel_lock:
            run = self._require_run(traffic_run_id)
            if run.status in TERMINAL_TASK_STATES or run.status == TaskState.STOPPING:
                return run
            return await self.traffic_service.cancel(run.controller_task_id)

    async def retry_run(self, traffic_run_id: str) -> TrafficRun:
        run = self._require_run(traffic_run_id)
        if run.status not in TERMINAL_TASK_STATES:
            raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "非终态流量任务不允许重试")
        return await self.traffic_service.retry(run.controller_task_id)

    def _require_run(self, traffic_run_id: str) -> TrafficRun:
        run = self.get_run(traffic_run_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return run


def _page_args(offset: int, limit: int) -> tuple[int, int]:
    try:
        selected_offset = max(0, int(offset))
        selected_limit = max(1, min(int(limit), _MAX_PAGE_SIZE))
    except (TypeError, ValueError) as exc:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "流量任务分页参数无效") from exc
    return selected_offset, selected_limit


def _agent_availability(agent: dict[str, object], capabilities: dict[str, object]) -> tuple[bool, str]:
    if not bool(agent.get("enabled")):
        return False, "Agent 已禁用"
    status = str(agent.get("status") or AgentStatus.UNKNOWN.value).upper()
    if status == AgentStatus.UNAUTHORIZED.value:
        return False, "Agent 认证失败或 Token 未加载"
    if status != AgentStatus.ONLINE.value:
        return False, "Agent 当前不在线"
    if not any(bool(capabilities.get(key)) for key in _LOCAL_CAPABILITIES):
        return False, "Agent 未报告流量测试能力"
    return True, ""


__all__ = ["TrafficRunPage", "TrafficWebApplicationService"]
