from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.vehicle_mr_online import (
    VehicleMrEventPageDTO,
    VehicleMrMappingSaveRequestDTO,
    VehicleMrOnlinePageDTO,
    VehicleMrTrainMappingDTO,
)
from netconsole.services.rail_transit.vehicle_mr_online_query_service import VehicleMrOnlineQueryService


router = APIRouter(prefix="/rail-transit/train-online", tags=["vehicle-mr-online"])
_ACTIONS = {"vehicle_mr_online_refresh_all", "vehicle_mr_ap_mapping_refresh", "vehicle_mr_mapping_save"}


def _query_service(request: Request) -> VehicleMrOnlineQueryService:
    return request.app.state.vehicle_mr_online_query_service


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


@router.get("/trains", response_model=VehicleMrOnlinePageDTO)
def trains(
    request: Request,
    query: str = Query(default="", max_length=200),
    train_status: str = Query(default="", max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> VehicleMrOnlinePageDTO:
    return _query_service(request).list_trains(
        _site_id(request),
        query=query,
        status=train_status,
        page=page,
        page_size=page_size,
    )


@router.get("/mappings", response_model=list[VehicleMrTrainMappingDTO])
def mappings(request: Request) -> list[VehicleMrTrainMappingDTO]:
    return _query_service(request).list_mappings(_site_id(request))


@router.get("/trains/{train_id}/events", response_model=VehicleMrEventPageDTO)
def events(request: Request, train_id: str, limit: int = Query(default=200, ge=1, le=2000)) -> VehicleMrEventPageDTO:
    return _query_service(request).list_events(_site_id(request), train_id, limit=limit)


@router.post(
    "/refresh",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.rail_train_online_refresh"))],
)
def refresh(request: Request) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_vehicle_mr_online_refresh(_site_id(request))
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/ap-mapping/refresh",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.rail_train_online_refresh"))],
)
def refresh_ap_mapping(request: Request, train_id: str = Query(default="", max_length=100)) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_vehicle_mr_ap_mapping_refresh(_site_id(request), train_id=train_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.put(
    "/mappings",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.rail_train_online_mapping_write"))],
)
def save_mappings(request: Request, payload: VehicleMrMappingSaveRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).save_vehicle_mr_mappings(
            _site_id(request),
            [row.model_dump(mode="json") for row in payload.mappings],
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get("/tasks/{task_id}", response_model=RailTransitTaskDTO)
def task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        result = _application_service(request).get_task(_site_id(request), task_id)
        if result.action not in _ACTIONS:
            raise RailTransitWebError("TASK_NOT_FOUND", "列车在线任务不存在")
        return result
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post("/tasks/{task_id}/cancel", response_model=RailTransitTaskDTO)
def cancel_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    task(request, task_id)
    try:
        return _application_service(request).cancel_task(_site_id(request), task_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post("/tasks/recover", response_model=list[RailTransitTaskDTO])
def recover_tasks(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return [item for item in _application_service(request).recover_tasks(_site_id(request)) if item.action in _ACTIONS]
    except RailTransitWebError as exc:
        _raise_error(exc)


def _raise_error(exc: RailTransitWebError) -> None:
    status_code = status.HTTP_404_NOT_FOUND if exc.code == "TASK_NOT_FOUND" else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
