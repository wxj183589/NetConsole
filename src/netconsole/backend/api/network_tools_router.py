from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.network_tools import TcpPortTestStartRequest
from netconsole.models.api.traffic import TrafficStartResponse
from netconsole.models.traffic_test import TcpPortTestConfig
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService

from .traffic_router import _execution_target, traffic_run_dto


router = APIRouter(prefix="/network-tools", tags=["network-tools"])


def network_tools_service(request: Request) -> NetworkToolsApplicationService:
    service = getattr(request.app.state, "network_tools_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="网络工具 Web 服务未接线")
    return service


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
