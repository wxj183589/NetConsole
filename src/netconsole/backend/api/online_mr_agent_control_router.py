from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.backend.api.online_mr_control_router import (
    _require_local_desktop_session,
    _site_id,
)
from netconsole.models.api.online_mr_agent_control import (
    OnlineMrAgentCapabilitiesDTO,
    OnlineMrAgentProfileDTO,
    OnlineMrAgentReadinessDTO,
    OnlineMrAgentWebOperationDTO,
    OnlineMrAgentWebStartRequestDTO,
    OnlineMrAgentWebStatusDTO,
)
from netconsole.services.online_mr.agent_web_control_service import (
    OnlineMrAgentWebControlService,
)


router = APIRouter(
    prefix="/rail-transit/online-mr-agent",
    tags=["online-mr-agent-web-control"],
)


def _service(request: Request) -> OnlineMrAgentWebControlService:
    return request.app.state.online_mr_agent_web_control_service


@router.get("/capabilities", response_model=OnlineMrAgentCapabilitiesDTO)
def capabilities(request: Request) -> OnlineMrAgentCapabilitiesDTO:
    _require_local_desktop_session(request)
    return _service(request).capabilities(_site_id(request))


@router.get("/profiles", response_model=list[OnlineMrAgentProfileDTO])
def profiles(request: Request) -> list[OnlineMrAgentProfileDTO]:
    _require_local_desktop_session(request)
    return _service(request).profiles()


@router.get(
    "/profiles/{profile_id}/readiness", response_model=OnlineMrAgentReadinessDTO
)
def readiness(request: Request, profile_id: str) -> OnlineMrAgentReadinessDTO:
    _require_local_desktop_session(request)
    return _service(request).readiness(profile_id)


@router.get("/status", response_model=OnlineMrAgentWebStatusDTO)
def status(request: Request) -> OnlineMrAgentWebStatusDTO:
    _require_local_desktop_session(request)
    return _service(request).status(_site_id(request))


@router.get("/{operation_id}", response_model=OnlineMrAgentWebOperationDTO)
def operation_detail(
    request: Request, operation_id: str
) -> OnlineMrAgentWebOperationDTO:
    _require_local_desktop_session(request)
    return _service(request).get_operation(operation_id, site_id=_site_id(request))


@router.post("/start", response_model=OnlineMrAgentWebOperationDTO)
def start(
    request: Request,
    payload: OnlineMrAgentWebStartRequestDTO,
) -> OnlineMrAgentWebOperationDTO:
    _require_local_desktop_session(request)
    return _service(request).start(payload, current_site_id=_site_id(request))


@router.post("/{operation_id}/stop", response_model=OnlineMrAgentWebOperationDTO)
def stop(request: Request, operation_id: str) -> OnlineMrAgentWebOperationDTO:
    _require_local_desktop_session(request)
    return _service(request).stop(operation_id, site_id=_site_id(request))


__all__ = ["router"]
