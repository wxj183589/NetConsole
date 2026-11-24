from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.models.api.train_communication import TrainCommunicationPageDTO, TrainCommunicationSummaryDTO
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService
from netconsole.services.site_manager import SiteManager


router = APIRouter(prefix="/rail-transit/online-mr/inventory", tags=["online-mr"])


def _service(request: Request) -> TrainCommunicationQueryService:
    return request.app.state.train_communication_query_service


def _site_id(request: Request, supplied: str) -> str:
    value = supplied or _service(request).current_site_id()
    try:
        return SiteManager(request.app.state.paths).validate_site_name(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


@router.get("/summary", response_model=TrainCommunicationSummaryDTO)
def summary(request: Request, site_id: str = Query(default="", max_length=100)) -> TrainCommunicationSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request, site_id)))


@router.get("/trains", response_model=TrainCommunicationPageDTO)
def trains(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    train: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", max_length=20),
    communication_status: str = Query(default="", pattern="^(|normal|warning|critical|stale|unknown)$"),
    mesh_link_status: str = Query(default="", max_length=30),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    line_side: str = Query(default="", max_length=50),
    executor: str = Query(default="", pattern="^(|LOCAL)$"),
    data_source: str = Query(default="", max_length=50),
    has_warning: bool | None = None,
    active_only: bool = False,
    optical_anomaly_only: bool = False,
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="train_no", pattern="^(train_no|status|updated_at)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> TrainCommunicationPageDTO:
    return _query(
        lambda: _service(request).list_trains(
            _site_id(request, site_id),
            train=train,
            mr_role=mr_role,
            communication_status=communication_status,
            mesh_link_status=mesh_link_status,
            station=station,
            section=section,
            line_side=line_side,
            executor=executor,
            data_source=data_source,
            has_warning=has_warning,
            active_only=active_only,
            optical_anomaly_only=optical_anomaly_only,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


def _query(callback):
    with map_api_errors("车载 MR 资料暂时不可读"):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
