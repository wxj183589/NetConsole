from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.backend.api.online_mr_control_router import (
    require_local_desktop_session,
)
from netconsole.models.api.online_mr_agent_control import (
    OnlineMrAgentCapabilitiesDTO,
    OnlineMrAgentProfileDTO,
    OnlineMrAgentReadinessDTO,
    OnlineMrAgentWebOperationDTO,
    OnlineMrAgentWebStartRequestDTO,
    OnlineMrAgentWebStatusDTO,
)
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade


router = APIRouter(
    prefix="/rail-transit/online-mr-agent",
    tags=["online-mr-agent-web-control"],
)


def _facade(request: Request) -> OnlineMrApiFacade:
    return request.app.state.online_mr_api_facade


@router.get("/capabilities", response_model=OnlineMrAgentCapabilitiesDTO)
def capabilities(request: Request) -> OnlineMrAgentCapabilitiesDTO:
    require_local_desktop_session(request)
    return _facade(request).agent_capabilities()


@router.get("/profiles", response_model=list[OnlineMrAgentProfileDTO])
def profiles(request: Request) -> list[OnlineMrAgentProfileDTO]:
    require_local_desktop_session(request)
    return _facade(request).agent_profiles()


@router.get(
    "/profiles/{profile_id}/readiness", response_model=OnlineMrAgentReadinessDTO
)
def readiness(request: Request, profile_id: str) -> OnlineMrAgentReadinessDTO:
    require_local_desktop_session(request)
    return _facade(request).agent_readiness(profile_id)


@router.get("/status", response_model=OnlineMrAgentWebStatusDTO)
def status(request: Request) -> OnlineMrAgentWebStatusDTO:
    require_local_desktop_session(request)
    return _facade(request).agent_status()


@router.get("/{operation_id}", response_model=OnlineMrAgentWebOperationDTO)
def operation_detail(
    request: Request, operation_id: str
) -> OnlineMrAgentWebOperationDTO:
    require_local_desktop_session(request)
    return _facade(request).agent_operation(operation_id)


@router.post("/start", response_model=OnlineMrAgentWebOperationDTO)
def start(
    request: Request,
    payload: OnlineMrAgentWebStartRequestDTO,
) -> OnlineMrAgentWebOperationDTO:
    require_local_desktop_session(request)
    return _facade(request).start_agent(payload)


@router.post("/{operation_id}/stop", response_model=OnlineMrAgentWebOperationDTO)
def stop(request: Request, operation_id: str) -> OnlineMrAgentWebOperationDTO:
    require_local_desktop_session(request)
    return _facade(request).stop_agent(operation_id)


__all__ = ["router"]
