from __future__ import annotations

import sqlite3

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status

from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_base_data import (
    DataQualityEntityGroupPageDTO,
    DataQualityIssuePageDTO,
    ImportPreviewResultDTO,
    ImportPolicyDTO,
    ImportPolicyResponseDTO,
    RailTransitRelationPageDTO,
    RailTransitSummaryDTO,
    SectionPageDTO,
    StationPageDTO,
    TracksideApDetailDTO,
    TracksideApPageDTO,
    TrainDetailDTO,
    TrainPageDTO,
    VehicleMrDetailDTO,
    VehicleMrPageDTO,
)
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.import_preview_service import (
    MAX_IMPORT_PREVIEW_BYTES,
    RailTransitImportPreviewService,
)
from netconsole.services.rail_transit.source_policy import import_policy_rows


router = APIRouter(prefix="/rail-transit/base-data", tags=["rail-transit-base-data"])


def _service(request: Request) -> RailTransitBaseDataQueryService:
    return request.app.state.rail_transit_base_data_query_service


def _preview_service(request: Request) -> RailTransitImportPreviewService:
    return request.app.state.rail_transit_import_preview_service


def _import_service(request: Request) -> RailTransitBaseDataImportService:
    return request.app.state.rail_transit_base_data_import_service


def _site_id(request: Request, supplied: str) -> str:
    value = supplied or _service(request).current_site_id()
    try:
        return SiteManager(request.app.state.paths).validate_site_name(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


@router.get("/summary", response_model=RailTransitSummaryDTO)
def summary(request: Request, site_id: str = Query(default="", max_length=100)) -> RailTransitSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request, site_id)))


@router.get("/stations", response_model=StationPageDTO)
def stations(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> StationPageDTO:
    return _query(lambda: _service(request).list_stations(_site_id(request, site_id), query=query, page=page, page_size=page_size, sort_order=sort_order))


@router.get("/sections", response_model=SectionPageDTO)
def sections(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    station: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> SectionPageDTO:
    return _query(lambda: _service(request).list_sections(_site_id(request, site_id), station=station, query=query, page=page, page_size=page_size, sort_order=sort_order))


@router.get("/aps", response_model=TracksideApPageDTO)
def aps(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    line_side: str = Query(default="", max_length=50),
    query: str = Query(default="", max_length=200),
    has_issue: bool | None = None,
    issue_severity: str = Query(default="", pattern="^(|error|warning|info)$"),
    fit_ap_status: str = Query(default="", max_length=30),
    optical_status: str = Query(default="", max_length=30),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="name", pattern="^(name|station|section|mileage|updated_at)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> TracksideApPageDTO:
    return _query(lambda: _service(request).list_aps(_site_id(request, site_id), station=station, section=section, line_side=line_side, query=query, has_issue=has_issue, issue_severity=issue_severity, fit_ap_status=fit_ap_status, optical_status=optical_status, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order))


@router.get("/aps/{ap_id}", response_model=TracksideApDetailDTO)
def ap_detail(request: Request, ap_id: str, site_id: str = Query(default="", max_length=100)) -> TracksideApDetailDTO:
    result = _query(lambda: _service(request).get_ap(_site_id(request, site_id), ap_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="轨旁 AP 不存在")
    return result


@router.get("/trains", response_model=TrainPageDTO)
def trains(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    has_issue: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> TrainPageDTO:
    return _query(lambda: _service(request).list_trains(_site_id(request, site_id), query=query, has_issue=has_issue, page=page, page_size=page_size, sort_order=sort_order))


@router.get("/trains/{train_id}", response_model=TrainDetailDTO)
def train_detail(request: Request, train_id: str, site_id: str = Query(default="", max_length=100)) -> TrainDetailDTO:
    result = _query(lambda: _service(request).get_train(_site_id(request, site_id), train_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="列车不存在")
    return result


@router.get("/mrs", response_model=VehicleMrPageDTO)
def mrs(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    train: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", max_length=20),
    query: str = Query(default="", max_length=200),
    has_issue: bool | None = None,
    issue_severity: str = Query(default="", pattern="^(|error|warning|info)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="train_no", pattern="^(train_no|name|role|ip)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> VehicleMrPageDTO:
    return _query(lambda: _service(request).list_mrs(_site_id(request, site_id), train=train, mr_role=mr_role, query=query, has_issue=has_issue, issue_severity=issue_severity, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order))


@router.get("/mrs/{mr_id}", response_model=VehicleMrDetailDTO)
def mr_detail(request: Request, mr_id: str, site_id: str = Query(default="", max_length=100)) -> VehicleMrDetailDTO:
    result = _query(lambda: _service(request).get_mr(_site_id(request, site_id), mr_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车载 MR 不存在")
    return result


@router.get("/issues", response_model=DataQualityIssuePageDTO)
def issues(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    severity: str = Query(default="", pattern="^(|error|warning|info)$"),
    entity_type: str = Query(default="", max_length=30),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DataQualityIssuePageDTO:
    return _query(lambda: _service(request).list_issues(_site_id(request, site_id), severity=severity, entity_type=entity_type, query=query, page=page, page_size=page_size))


@router.get("/issues/groups", response_model=DataQualityEntityGroupPageDTO)
def issue_groups(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    blocking_only: bool | None = None,
    needs_confirmation_only: bool | None = None,
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DataQualityEntityGroupPageDTO:
    return _query(
        lambda: _service(request).list_issue_groups(
            _site_id(request, site_id),
            blocking_only=blocking_only,
            needs_confirmation_only=needs_confirmation_only,
            query=query,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/import-policies", response_model=ImportPolicyResponseDTO)
def import_policies(request: Request) -> ImportPolicyResponseDTO:
    return ImportPolicyResponseDTO(
        write_enabled=_import_service(request).write_enabled,
        identity_boundaries={
            "formal": "正式基础资料长期保存，来源数据不能自动覆盖。",
            "source": "外部文件、AC、Agent 和日志身份保留来源，不自动成为正式身份。",
            "runtime": "在线状态、DHCP IP、RSSI、光衰和 Mesh-Link 只关联展示。",
        },
        items=[ImportPolicyDTO.model_validate(item) for item in import_policy_rows()],
    )


@router.get("/relations", response_model=RailTransitRelationPageDTO)
def relations(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> RailTransitRelationPageDTO:
    return _query(lambda: _service(request).list_relations(_site_id(request, site_id), query=query, page=page, page_size=page_size))


@router.post("/import-preview", response_model=ImportPreviewResultDTO)
async def import_preview(
    request: Request,
    file: UploadFile = File(...),
    site_id: str = Query(default="", max_length=100),
) -> ImportPreviewResultDTO:
    try:
        content = await file.read(MAX_IMPORT_PREVIEW_BYTES + 1)
        return _preview_service(request).preview(
            site_id=_site_id(request, site_id),
            file_name=file.filename or "",
            content=content,
            content_type=file.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        await file.close()


def _query(callback):
    try:
        return callback()
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨道交通基础资料数据库暂时不可读") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = ["router"]
