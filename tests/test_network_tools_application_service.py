from __future__ import annotations

import asyncio

from netconsole.models.traffic_test import ExecutionTargetDTO, ExecutionTargetKind, TcpPortTestConfig
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService


class FakeTrafficService:
    def __init__(self) -> None:
        self.calls = []

    async def start_tcp_port_test(self, config, execution_target):
        self.calls.append((config, execution_target))
        return "run"


def test_network_tools_service_delegates_tcp_probe_to_traffic() -> None:
    traffic = FakeTrafficService()
    service = NetworkToolsApplicationService(traffic)
    target = ExecutionTargetDTO(ExecutionTargetKind.LOCAL)

    result = asyncio.run(service.start_tcp_port_test(TcpPortTestConfig("127.0.0.1", 443), target))

    assert result == "run"
    assert traffic.calls == [(TcpPortTestConfig("127.0.0.1", 443), target)]
