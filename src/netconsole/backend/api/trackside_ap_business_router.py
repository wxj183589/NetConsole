from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.trackside_ap_business import (
    TracksideApBusinessPageDTO,
    TracksideApUpdateRequestDTO,
)
from netconsole.services.rail_transit.trackside_ap_business_query_service import TracksideApBusinessQueryService


router = APIRouter(prefix="/rail-transit/trackside-ap-business", tags=["trackside-ap-business"])
_ACTIONS = {"trackside_ap_optical_update"}


def _query_service(request: Request) -> TracksideApBusinessQueryService:
    return request.app.state.trackside_ap_business_query_service


def _application_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交应用服务未接线")
    return service


def _site_id(request: Request) -> str:
    try:
        return SiteManager(request.app.state.paths).validate_site_name(_query_service(request).current_site_id())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


@router.get("/rows", response_model=TracksideApBusinessPageDTO)
def rows(
    request: Request,
    station: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    optical_anomaly_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> TracksideApBusinessPageDTO:
    return _query_service(request).list_rows(
        _site_id(request),
        station=station,
        query=query,
        optical_anomaly_only=optical_anomaly_only,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/update",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_trackside_ap_business_update")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def update(request: Request, payload: TracksideApUpdateRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_update(
            _site_id(request),
            station=payload.station,
            ap_uuid=payload.ap_uuid,
            ap_mac=payload.ap_mac,
            ap_name=payload.ap_name,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/tasks/{task_id}",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        result = _application_service(request).get_task(_site_id(request), task_id)
        if result.action not in _ACTIONS:
            raise RailTransitWebError("TASK_NOT_FOUND", "轨旁 AP 任务不存在")
        return result
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def cancel_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        task(request, task_id)
        return _application_service(request).cancel_task(_site_id(request), task_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/tasks/recover",
    response_model=list[RailTransitTaskDTO],
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def recover_tasks(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return [
            item
            for item in _application_service(request).recover_tasks(_site_id(request))
            if item.action in _ACTIONS
        ]
    except RailTransitWebError as exc:
        _raise_error(exc)


def _raise_error(exc: RailTransitWebError) -> None:
    status_code = status.HTTP_404_NOT_FOUND if exc.code == "TASK_NOT_FOUND" else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
