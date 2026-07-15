from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.online_mr_control import (
    OnlineMrWebControlStatusDTO,
    OnlineMrWebOperationDTO,
    OnlineMrWebStartRequestDTO,
)
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade
from netconsole.services.online_mr.errors import OnlineMrWebControlError, OnlineMrWebControlErrorCode


router = APIRouter(prefix="/rail-transit/online-mr-control", tags=["online-mr-web-control"])


def _facade(request: Request) -> OnlineMrApiFacade:
    return request.app.state.online_mr_api_facade


def require_local_desktop_session(request: Request) -> None:
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
    require_local_desktop_session(request)
    return _facade(request).local_status()


@router.get("/{operation_id}", response_model=OnlineMrWebOperationDTO)
def operation_detail(request: Request, operation_id: str) -> OnlineMrWebOperationDTO:
    require_local_desktop_session(request)
    return _facade(request).local_operation(operation_id)


@router.post("/start", response_model=OnlineMrWebOperationDTO)
def start(request: Request, payload: OnlineMrWebStartRequestDTO) -> OnlineMrWebOperationDTO:
    require_local_desktop_session(request)
    return _facade(request).start_local(payload)


@router.post("/{operation_id}/stop", response_model=OnlineMrWebOperationDTO)
def stop(request: Request, operation_id: str) -> OnlineMrWebOperationDTO:
    require_local_desktop_session(request)
    return _facade(request).stop_local(operation_id)


__all__ = ["require_local_desktop_session", "router"]
