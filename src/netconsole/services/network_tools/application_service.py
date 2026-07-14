from __future__ import annotations

from netconsole.models.traffic_test import ExecutionTargetDTO, TcpPortTestConfig, TrafficRun
from netconsole.services.traffic.application_service import TrafficTestApplicationService


class NetworkToolsApplicationService:
    """网络工具 Web 入口；执行与恢复继续由 Traffic/Task 体系负责。"""

    def __init__(self, traffic_service: TrafficTestApplicationService) -> None:
        self.traffic_service = traffic_service

    async def start_tcp_port_test(
        self,
        config: TcpPortTestConfig,
        execution_target: ExecutionTargetDTO,
    ) -> TrafficRun:
        return await self.traffic_service.start_tcp_port_test(config, execution_target)


__all__ = ["NetworkToolsApplicationService"]
