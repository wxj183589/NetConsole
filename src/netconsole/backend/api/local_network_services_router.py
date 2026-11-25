from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from netconsole.services.local_network_services.log_query import query_service_logs

from netconsole.services.local_network_services.manager import SERVICES, LocalNetworkServiceManager, ServiceConfig, ServiceId

router = APIRouter(prefix="/local-network-services", tags=["local-network-services"])


def _manager(request: Request) -> LocalNetworkServiceManager:
    manager = getattr(request.app.state, "local_network_services", None)
    if manager is None:
        raise HTTPException(503, "network_services_unavailable")
    return manager


@router.get("")
def list_services(request: Request) -> dict:
    manager = _manager(request)
    return {
        "services": [manager.snapshot(kind) for kind in SERVICES],
        "addresses": manager.bind_addresses(),
    }


@router.put("/{kind}/config")
def configure_service(kind: ServiceId, body: ServiceConfig, request: Request) -> dict:
    try:
        return _manager(request).configure(kind, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{kind}/actions/{action}")
def service_action(kind: ServiceId, action: Literal["initialize", "start", "stop", "restart"], request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _manager(request).action(kind, action)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{kind}/logs")
def service_logs(
    kind: ServiceId,
    request: Request,
    response: Response,
    keyword: str = Query("", max_length=500),
    level: Literal["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "",
    since: datetime | None = None,
    until: datetime | None = None,
    history: bool = False,
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if since and until and since.astimezone() > until.astimezone():
        raise HTTPException(422, "invalid_log_time_range")
    return query_service_logs(_manager(request).logs(kind, history=history), keyword=keyword, level=level, since=since, until=until, history=history)
