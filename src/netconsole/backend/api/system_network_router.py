from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from netconsole.models.api.system_network import (
    LocalIpv4AddressPageDTO,
    SourceIpRecommendationDTO,
    SourceIpRecommendationRequestDTO,
    UdpPortCheckDTO,
    UdpPortCheckRequestDTO,
)
from netconsole.services.system_network_application_service import (
    SystemNetworkApplicationService,
    SystemNetworkError,
)


router = APIRouter(prefix="/system/network", tags=["system-network"])


def _service(request: Request) -> SystemNetworkApplicationService:
    return request.app.state.system_network_application_service


@router.get("/ipv4-addresses", response_model=LocalIpv4AddressPageDTO)
def ipv4_addresses(
    request: Request,
    include_loopback: bool = Query(default=False),
    include_apipa: bool = Query(default=False),
    include_down: bool = Query(default=False),
) -> LocalIpv4AddressPageDTO:
    return _call(
        lambda: _service(request).list_ipv4_addresses(
            include_loopback=include_loopback,
            include_apipa=include_apipa,
            include_down=include_down,
        )
    )


@router.post("/recommend-source-ip", response_model=SourceIpRecommendationDTO)
def recommend_source_ip(
    request: Request,
    payload: SourceIpRecommendationRequestDTO,
) -> SourceIpRecommendationDTO:
    return _call(lambda: _service(request).recommend_source_ip(payload))


@router.post("/check-udp-port", response_model=UdpPortCheckDTO)
def check_udp_port(
    request: Request,
    payload: UdpPortCheckRequestDTO,
) -> UdpPortCheckDTO:
    return _call(lambda: _service(request).check_udp_port(payload))


def _call(callback):
    try:
        return callback()
    except SystemNetworkError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


__all__ = ["router"]
