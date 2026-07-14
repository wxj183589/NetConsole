from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.network_tools import TcpPortTestStartRequest
from netconsole.models.api.traffic import TrafficStartResponse
from netconsole.models.traffic_test import TcpPortTestConfig
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService

from .traffic_router import _execution_target, traffic_run_dto


router = APIRouter(prefix="/network-tools", tags=["network-tools"])


def network_tools_service(request: Request) -> NetworkToolsApplicationService:
    return NetworkToolsApplicationService(request.app.state.traffic_service)


@router.post(
    "/tcp-port-test",
    response_model=TrafficStartResponse,
    status_code=202,
    dependencies=[Depends(require_feature("web.network_tools_tcp_port_test"))],
)
async def start_tcp_port_test(body: TcpPortTestStartRequest, request: Request) -> TrafficStartResponse:
    run = await network_tools_service(request).start_tcp_port_test(
        TcpPortTestConfig(
            target=body.target,
            port=body.port,
            interval_ms=body.interval_ms,
            timeout_ms=body.timeout_ms,
            count=body.count,
        ),
        _execution_target(body.execution_target),
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


__all__ = ["router"]
