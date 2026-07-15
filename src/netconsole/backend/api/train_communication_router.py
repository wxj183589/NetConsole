from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.core.sites import SiteManager
from netconsole.models.api.train_communication import (
    CommunicationPackageDTO,
    CommunicationRawSourceDTO,
    CommunicationTaskDTO,
    MrCommunicationDetailDTO,
    MrCommunicationStatusDTO,
    TrainCommunicationDetailDTO,
    TrainCommunicationPageDTO,
    TrainCommunicationSummaryDTO,
)
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService


router = APIRouter(prefix="/rail-transit/train-communication", tags=["train-communication"])


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
    executor: str = Query(default="", pattern="^(|LOCAL|AGENT)$"),
    data_source: str = Query(default="", max_length=50),
    has_warning: bool | None = None,
    active_only: bool = False,
    agent_only: bool = False,
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
            agent_only=agent_only,
            optical_anomaly_only=optical_anomaly_only,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/trains/{train_id}", response_model=TrainCommunicationDetailDTO)
def train_detail(
    request: Request,
    train_id: str,
    site_id: str = Query(default="", max_length=100),
) -> TrainCommunicationDetailDTO:
    result = _query(lambda: _service(request).get_train_detail(_site_id(request, site_id), train_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="列车不存在")
    return result


@router.get("/mrs/{mr_id}", response_model=MrCommunicationDetailDTO)
def mr_detail(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> MrCommunicationDetailDTO:
    result = _query(lambda: _service(request).get_mr_detail(_site_id(request, site_id), mr_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车载 MR 不存在")
    return result


@router.get("/mrs/{mr_id}/preview", response_model=MrCommunicationStatusDTO)
def mr_preview(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> MrCommunicationStatusDTO:
    result = _query(lambda: _service(request).get_communication_preview(_site_id(request, site_id), mr_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车载 MR 不存在")
    return result


@router.get("/mrs/{mr_id}/raw-sources", response_model=list[CommunicationRawSourceDTO])
def raw_sources(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> list[CommunicationRawSourceDTO]:
    return _query(lambda: _service(request).get_raw_sources(_site_id(request, site_id), mr_id))


@router.get("/mrs/{mr_id}/tasks", response_model=list[CommunicationTaskDTO])
def related_tasks(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> list[CommunicationTaskDTO]:
    return _query(lambda: _service(request).get_related_tasks(_site_id(request, site_id), mr_id))


@router.get("/mrs/{mr_id}/packages", response_model=list[CommunicationPackageDTO])
def related_packages(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> list[CommunicationPackageDTO]:
    return _query(lambda: _service(request).get_related_packages(_site_id(request, site_id), mr_id))


def _query(callback):
    with map_api_errors("在线列车通信数据暂时不可读"):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = ["router"]
