from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request, Response, status

from netconsole.core.version import APP_VERSION
from netconsole.core.runtime_environment import desktop_storage_mode, persistent_storage
from netconsole.models.api.development import DevelopmentRuntimeStatusResponse
from netconsole.models.task_state import TaskState


router = APIRouter(prefix="/dev", tags=["development"])
_ACTIVE_TASK_STATES = {
    TaskState.PENDING,
    TaskState.STARTING,
    TaskState.RUNNING,
    TaskState.STOPPING,
}


@router.get("/runtime-status", response_model=DevelopmentRuntimeStatusResponse)
def runtime_status(request: Request) -> DevelopmentRuntimeStatusResponse:
    _require_loopback(request)
    task_service = request.app.state.task_service
    runtime_services_ready = bool(request.app.state.runtime_services_ready)
    active_tasks = len(task_service.list_tasks(statuses=_ACTIVE_TASK_STATES, limit=1_000))
    storage_mode = desktop_storage_mode()
    return DevelopmentRuntimeStatusResponse(
        runtime_mode=str(request.app.state.development_runtime_label),
        backend_ready=runtime_services_ready,
        data_root="<redacted>",
        storage_mode=storage_mode,
        data_root_kind="temporary" if storage_mode == "isolated_test" else "persistent",
        persistent=persistent_storage(),
        frontend_mode=str(request.app.state.development_frontend_mode),
        active_tasks=active_tasks,
        agent_controller_ready=runtime_services_ready and request.app.state.agent_service is not None,
        traffic_supervisor_ready=runtime_services_ready and request.app.state.traffic_service is not None,
        version=APP_VERSION,
    )


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def create_development_browser_session(request: Request) -> Response:
    _require_loopback(request)
    session_token = request.headers.get("x-netconsole-session", "")
    if not session_token:
        raise HTTPException(status_code=401, detail="development session header required")
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        "netconsole_desktop_session",
        session_token,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client is not None else ""
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=403, detail="development API requires loopback client")
