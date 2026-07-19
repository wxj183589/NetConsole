from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.models.api.ac_mesh_link import (
    AcMeshLinkPageDTO,
    AcMeshLinkSummaryDTO,
    AcMeshMrDetailDTO,
    AcMeshMrPageDTO,
    AcMeshRawTailDTO,
    AcMeshLinkRefreshRequestDTO,
    AcMeshLinkRefreshResponseDTO,
    AcMeshSnapshotDetailDTO,
    AcMeshSnapshotPageDTO,
)
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkRefreshApplicationService,
    AcMeshLinkRefreshError,
    AcMeshLinkRefreshErrorCode,
)


router = APIRouter(prefix="/ac-management/mesh-links", tags=["ac-mesh-links"])


def _service(request: Request) -> AcMeshLinkQueryService:
    return request.app.state.ac_mesh_link_query_service


def _site_id(request: Request) -> str:
    return _service(request).current_site_id()


def _refresh_service(request: Request) -> AcMeshLinkRefreshApplicationService:
    return request.app.state.ac_mesh_link_refresh_service


@router.get("/summary", response_model=AcMeshLinkSummaryDTO, deprecated=True)
def summary(request: Request) -> AcMeshLinkSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request)))


@router.post("/refresh", response_model=AcMeshLinkRefreshResponseDTO, status_code=status.HTTP_202_ACCEPTED, deprecated=True)
def refresh_mesh_links(
    request: Request,
    payload: AcMeshLinkRefreshRequestDTO,
) -> AcMeshLinkRefreshResponseDTO:
    try:
        result = _refresh_service(request).start_refresh(
            site_name=_site_id(request),
            controller_id=payload.controller_id,
            include_switch_history=payload.include_switch_history,
        )
    except AcMeshLinkRefreshError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == AcMeshLinkRefreshErrorCode.CONTROLLER_NOT_FOUND
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=f"{exc.code}: {exc.message}") from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AC_MESH_LINK_INTERNAL_ERROR: Mesh-Link 刷新任务暂时无法创建。",
        ) from exc
    return AcMeshLinkRefreshResponseDTO(
        task_id=result.task.task_id,
        status=result.task.status.value,
        already_running=result.already_running,
        message="Mesh-Link 刷新任务正在运行" if result.already_running else "Mesh-Link 刷新任务已创建",
    )


@router.get("/current", response_model=AcMeshLinkPageDTO, deprecated=True)
def current_links(
    request: Request,
    controller_id: str = Query(default="", max_length=100),
    mr_name: str = Query(default="", max_length=120),
    mr_mac: str = Query(default="", max_length=40),
    peer_ap_name: str = Query(default="", max_length=120),
    peer_ap_mac: str = Query(default="", max_length=40),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    line_side: str = Query(default="", max_length=50),
    match_status: str = Query(default="", pattern="^(|matched|unmatched)$"),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="mr_name", max_length=30),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> AcMeshLinkPageDTO:
    return _query(
        lambda: _service(request).list_current_links(
            _site_id(request),
            controller_id=controller_id,
            mr_name=mr_name,
            mr_mac=mr_mac,
            peer_ap_name=peer_ap_name,
            peer_ap_mac=peer_ap_mac,
            station=station,
            section=section,
            line_side=line_side,
            match_status=match_status,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/mrs", response_model=AcMeshMrPageDTO, deprecated=True)
def mrs(
    request: Request,
    online_status: str = Query(default="", pattern="^(|online|offline|stale|unknown)$"),
    train_no: str = Query(default="", max_length=20),
    mr_name: str = Query(default="", max_length=120),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    line_side: str = Query(default="", max_length=50),
    peer_ap_name: str = Query(default="", max_length=120),
    unmatched_only: bool = False,
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="train_no", max_length=30),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> AcMeshMrPageDTO:
    return _query(
        lambda: _service(request).list_mrs(
            _site_id(request),
            online_status=online_status,
            train_no=train_no,
            mr_name=mr_name,
            station=station,
            section=section,
            line_side=line_side,
            peer_ap_name=peer_ap_name,
            unmatched_only=unmatched_only,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/offline-mrs", response_model=AcMeshMrPageDTO, deprecated=True)
def offline_mrs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AcMeshMrPageDTO:
    return _query(lambda: _service(request).list_offline_mrs(_site_id(request), page=page, page_size=page_size))


@router.get("/unmatched", response_model=AcMeshLinkPageDTO, deprecated=True)
def unmatched_links(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str = Query(default="", max_length=200),
) -> AcMeshLinkPageDTO:
    return _query(
        lambda: _service(request).list_unmatched_links(
            _site_id(request), page=page, page_size=page_size, query=query
        )
    )


@router.get("/mrs/{mr_id}", response_model=AcMeshMrDetailDTO, deprecated=True)
def mr_detail(request: Request, mr_id: str) -> AcMeshMrDetailDTO:
    result = _query(lambda: _service(request).get_mr_link_detail(_site_id(request), mr_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车载 MR 不存在")
    return result


@router.get("/snapshots", response_model=AcMeshSnapshotPageDTO, deprecated=True)
def snapshots(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> AcMeshSnapshotPageDTO:
    return _query(lambda: _service(request).list_recent_snapshots(_site_id(request), page=page, page_size=page_size))


@router.get("/raw-tail", response_model=AcMeshRawTailDTO, deprecated=True)
def raw_tail(
    request: Request,
    snapshot_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=300, ge=1, le=300),
) -> AcMeshRawTailDTO:
    return _query(lambda: _service(request).get_raw_tail(_site_id(request), snapshot_id=snapshot_id, limit=limit))


@router.get("/snapshots/{snapshot_id}", response_model=AcMeshSnapshotDetailDTO, deprecated=True)
def snapshot_detail(request: Request, snapshot_id: int) -> AcMeshSnapshotDetailDTO:
    result = _query(lambda: _service(request).get_snapshot(_site_id(request), snapshot_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesh-Link 快照不存在")
    return result


def _query(callback):
    with map_api_errors("Mesh-Link 快照数据库暂时不可读"):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = ["router"]
