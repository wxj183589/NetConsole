from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.models.api.ac_management import (
    AcApDetailDTO,
    AcApPageDTO,
    AcConfigContentDTO,
    AcConfigDiffDTO,
    AcConfigSnapshotPageDTO,
    AcLldpDTO,
    AcManagementSummaryDTO,
    AcOpticalDTO,
    AcRadioDTO,
)
from netconsole.services.ac.query_service import AcManagementQueryService


router = APIRouter(prefix="/ac-management", tags=["ac-management"])


def _service(request: Request) -> AcManagementQueryService:
    return request.app.state.ac_management_query_service


def _site_id(request: Request) -> str:
    return _service(request).current_site_id()


@router.get("/summary", response_model=AcManagementSummaryDTO)
def summary(request: Request) -> AcManagementSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request)))


@router.get("/aps", response_model=AcApPageDTO)
def list_aps(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str = Query(default="", max_length=200),
    ap_status: str = Query(default="", alias="status", max_length=30),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    model: str = Query(default="", max_length=100),
    switch: str = Query(default="", max_length=100),
    optical_status: str = Query(default="", max_length=30),
    sort_by: str = Query(default="name", max_length=30),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> AcApPageDTO:
    return _query(
        lambda: _service(request).list_aps(
            _site_id(request),
            ac_id=ac_id,
            page=page,
            page_size=page_size,
            query=query,
            status=ap_status,
            station=station,
            section=section,
            model=model,
            switch=switch,
            optical_status=optical_status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/optical-anomalies", response_model=AcApPageDTO)
def optical_anomalies(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str = Query(default="", max_length=200),
) -> AcApPageDTO:
    return _query(
        lambda: _service(request).list_optical_anomalies(
            _site_id(request), ac_id=ac_id, page=page, page_size=page_size, query=query
        )
    )


@router.get("/aps/{ap_id}", response_model=AcApDetailDTO)
def ap_detail(request: Request, ap_id: str) -> AcApDetailDTO:
    return _required(_query(lambda: _service(request).get_ap_detail(_site_id(request), ap_id)), "AP 不存在")


@router.get("/aps/{ap_id}/radios", response_model=list[AcRadioDTO])
def ap_radios(request: Request, ap_id: str) -> list[AcRadioDTO]:
    return _required(_query(lambda: _service(request).get_ap_radios(_site_id(request), ap_id)), "AP 不存在")


@router.get("/aps/{ap_id}/lldp", response_model=AcLldpDTO)
def ap_lldp(request: Request, ap_id: str) -> AcLldpDTO:
    return _required(_query(lambda: _service(request).get_ap_lldp(_site_id(request), ap_id)), "AP 不存在")


@router.get("/aps/{ap_id}/optical", response_model=AcOpticalDTO)
def ap_optical(request: Request, ap_id: str) -> AcOpticalDTO:
    return _required(_query(lambda: _service(request).get_ap_optical(_site_id(request), ap_id)), "AP 不存在")


@router.get("/config-snapshots", response_model=AcConfigSnapshotPageDTO)
def config_snapshots(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    snapshot_type: str = Query(default="", alias="type", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> AcConfigSnapshotPageDTO:
    return _query(
        lambda: _service(request).list_config_snapshots(
            _site_id(request), ac_id=ac_id, snapshot_type=snapshot_type, page=page, page_size=page_size
        )
    )


@router.get("/config-snapshots/{snapshot_id}", response_model=AcConfigContentDTO)
def config_snapshot(
    request: Request,
    snapshot_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100_000, ge=1, le=200_000),
) -> AcConfigContentDTO:
    result = _query(lambda: _service(request).get_config_snapshot(_site_id(request), snapshot_id, offset=offset, limit=limit))
    return _required(result, "配置快照不存在")


@router.get("/config-snapshots/{snapshot_id}/diff", response_model=AcConfigDiffDTO)
def config_diff(
    request: Request,
    snapshot_id: int,
    other_snapshot_id: int | None = Query(default=None, ge=1),
) -> AcConfigDiffDTO:
    result = _query(
        lambda: _service(request).get_config_diff(
            _site_id(request), snapshot_id, other_snapshot_id=other_snapshot_id
        )
    )
    return _required(result, "配置快照不存在")


def _required(value, message: str):
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return value


def _query(callback):
    with map_api_errors(
        "AC 数据库暂时不可读",
        io_detail="配置快照文件不可读",
        io_errors=(OSError, UnicodeError),
        io_status_code=status.HTTP_404_NOT_FOUND,
    ):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = ["router"]
