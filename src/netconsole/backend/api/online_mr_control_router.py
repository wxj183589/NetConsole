from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.models.api.online_mr_control import (
    OnlineMrWebControlStatusDTO,
    OnlineMrWebOperationDTO,
    OnlineMrWebStartRequestDTO,
)
from netconsole.services.online_mr.errors import OnlineMrWebControlError, OnlineMrWebControlErrorCode
from netconsole.services.online_mr.web_control_service import OnlineMrWebControlService


router = APIRouter(prefix="/rail-transit/online-mr-control", tags=["online-mr-web-control"])


def _service(request: Request) -> OnlineMrWebControlService:
    return request.app.state.online_mr_web_control_service


def _site_id(request: Request) -> str:
    value = str(SiteManager(request.app.state.paths).get_current_site() or "").strip()
    if not value:
        raise OnlineMrWebControlError(
            OnlineMrWebControlErrorCode.INVALID_REQUEST,
            "主程序尚未选择局点",
            status_code=422,
        )
    return SiteManager(request.app.state.paths).validate_site_name(value)


def _require_local_desktop_session(request: Request) -> None:
    if request.app.state.runtime_mode is not RuntimeMode.DESKTOP or request.url.hostname != "127.0.0.1":
        raise OnlineMrWebControlError(
            OnlineMrWebControlErrorCode.LOCAL_ONLY,
            "Online MR Web 控制仅允许主程序 127.0.0.1 WebHost",
            status_code=403,
        )
    if not bool(getattr(request.state, "desktop_session_authenticated", False)):
        raise OnlineMrWebControlError(
            OnlineMrWebControlErrorCode.AUTH_REQUIRED,
            "当前请求缺少主程序短期 WebHost 会话",
            status_code=401,
        )


@router.get("/status", response_model=OnlineMrWebControlStatusDTO)
def status(request: Request) -> OnlineMrWebControlStatusDTO:
    _require_local_desktop_session(request)
    return _service(request).status(_site_id(request))


@router.get("/{operation_id}", response_model=OnlineMrWebOperationDTO)
def operation_detail(request: Request, operation_id: str) -> OnlineMrWebOperationDTO:
    _require_local_desktop_session(request)
    return _service(request).get_operation(operation_id, site_id=_site_id(request))


@router.post("/start", response_model=OnlineMrWebOperationDTO)
def start(request: Request, payload: OnlineMrWebStartRequestDTO) -> OnlineMrWebOperationDTO:
    _require_local_desktop_session(request)
    return _service(request).start(payload, current_site_id=_site_id(request))


@router.post("/{operation_id}/stop", response_model=OnlineMrWebOperationDTO)
def stop(request: Request, operation_id: str) -> OnlineMrWebOperationDTO:
    _require_local_desktop_session(request)
    return _service(request).stop(operation_id, site_id=_site_id(request))


__all__ = ["router"]
