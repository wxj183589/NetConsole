from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.core.sites import SiteManager
from netconsole.models.api.mesh_analysis import (
    MeshAlignmentDTO,
    MeshAnalysisSessionDetailDTO,
    MeshAnalysisSessionPageDTO,
    MeshAnalysisSummaryDTO,
    MeshAnomalyPageDTO,
    MeshApStatisticsPageDTO,
    MeshChannelBusyPageDTO,
    MeshDataSourceDTO,
    MeshLinkPageDTO,
    MeshRawTailDTO,
    MeshReportArtifactDTO,
    MeshRssiDTO,
    MeshSwitchEventPageDTO,
    MeshTimelineDTO,
)
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryError, MeshAnalysisQueryService


router = APIRouter(prefix="/rail-transit/mesh-analysis", tags=["rail-transit-mesh-analysis"])
T = TypeVar("T")


def _service(request: Request) -> MeshAnalysisQueryService:
    return request.app.state.mesh_analysis_query_service


def _site_id(request: Request, supplied: str) -> str:
    value = supplied or _service(request).current_site_id()
    try:
        return SiteManager(request.app.state.paths).validate_site_name(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


def _query(callback: Callable[[], T]) -> T:
    with map_api_errors("Mesh 分析结果暂时不可读取"):
        try:
            return callback()
        except MeshAnalysisQueryError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/summary", response_model=MeshAnalysisSummaryDTO)
def summary(request: Request, site_id: str = Query(default="", max_length=100)) -> MeshAnalysisSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request, site_id)))


@router.get("/sessions", response_model=MeshAnalysisSessionPageDTO)
def sessions(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    train: str = Query(default="", max_length=100),
    mr_name: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", max_length=20),
    source_type: str = Query(default="", max_length=50),
    analysis_status: str = Query(default="", max_length=50),
    has_warning: bool | None = None,
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="analysis_time", pattern="^(analysis_time|mr_name|link_record_count)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> MeshAnalysisSessionPageDTO:
    return _query(
        lambda: _service(request).list_analysis_sessions(
            _site_id(request, site_id),
            train=train,
            mr_name=mr_name,
            mr_role=mr_role,
            source_type=source_type,
            analysis_status=analysis_status,
            has_warning=has_warning,
            time_from=time_from,
            time_to=time_to,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/sessions/{session_id}", response_model=MeshAnalysisSessionDetailDTO)
def session_detail(request: Request, session_id: str, site_id: str = Query(default="", max_length=100)) -> MeshAnalysisSessionDetailDTO:
    return _query(lambda: _service(request).get_analysis_session(_site_id(request, site_id), session_id))


@router.get("/sessions/{session_id}/links", response_model=MeshLinkPageDTO)
def links(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    peer_ap_name: str = Query(default="", max_length=100),
    peer_ap_mac: str = Query(default="", max_length=50),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    line_side: str = Query(default="", max_length=50),
    link_role: str = Query(default="", pattern="^(|ACTIVE|STANDBY)$"),
    event_type: str = Query(default="", max_length=50),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    has_warning: bool | None = None,
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    sort_by: str = Query(default="timestamp", pattern="^(timestamp|rssi|peer_ap_name)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> MeshLinkPageDTO:
    return _query(
        lambda: _service(request).list_link_details(
            _site_id(request, site_id),
            session_id,
            peer_ap_name=peer_ap_name,
            peer_ap_mac=peer_ap_mac,
            station=station,
            section=section,
            line_side=line_side,
            link_role=link_role,
            event_type=event_type,
            time_from=time_from,
            time_to=time_to,
            has_warning=has_warning,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/sessions/{session_id}/timeline", response_model=MeshTimelineDTO)
def timeline(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    limit: int = Query(default=2_000, ge=1, le=5_000),
) -> MeshTimelineDTO:
    return _query(lambda: _service(request).get_link_timeline(_site_id(request, site_id), session_id, time_from=time_from, time_to=time_to, limit=limit))


@router.get("/sessions/{session_id}/switch-events", response_model=MeshSwitchEventPageDTO)
def switch_events(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    event_type: str = Query(default="", max_length=50),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> MeshSwitchEventPageDTO:
    return _query(lambda: _service(request).list_switch_events(_site_id(request, site_id), session_id, event_type=event_type, time_from=time_from, time_to=time_to, page=page, page_size=page_size))


@router.get("/sessions/{session_id}/rssi", response_model=MeshRssiDTO)
def rssi(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
) -> MeshRssiDTO:
    return _query(lambda: _service(request).get_rssi_statistics(_site_id(request, site_id), session_id, time_from=time_from, time_to=time_to, max_points=max_points))


@router.get("/sessions/{session_id}/channel-busy", response_model=MeshChannelBusyPageDTO)
def channel_busy(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
) -> MeshChannelBusyPageDTO:
    return _query(lambda: _service(request).get_channel_busy(_site_id(request, site_id), session_id, time_from=time_from, time_to=time_to, max_points=max_points))


@router.get("/sessions/{session_id}/anomalies", response_model=MeshAnomalyPageDTO)
def anomalies(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    anomaly_type: str = Query(default="", max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> MeshAnomalyPageDTO:
    return _query(lambda: _service(request).list_anomalies(_site_id(request, site_id), session_id, anomaly_type=anomaly_type, page=page, page_size=page_size))


@router.get("/sessions/{session_id}/ap-statistics", response_model=MeshApStatisticsPageDTO)
def ap_statistics(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> MeshApStatisticsPageDTO:
    return _query(lambda: _service(request).list_ap_statistics(_site_id(request, site_id), session_id, query=query, page=page, page_size=page_size))


@router.get("/sessions/{session_id}/alignment", response_model=MeshAlignmentDTO)
def alignment(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
) -> MeshAlignmentDTO:
    return _query(lambda: _service(request).get_alignment(_site_id(request, site_id), session_id, max_points=max_points))


@router.get("/sessions/{session_id}/artifacts", response_model=list[MeshReportArtifactDTO])
def artifacts(request: Request, session_id: str, site_id: str = Query(default="", max_length=100)) -> list[MeshReportArtifactDTO]:
    return _query(lambda: _service(request).list_report_artifacts(_site_id(request, site_id), session_id))


@router.get("/sessions/{session_id}/artifacts/{artifact_id}/download", response_class=FileResponse)
def download_artifact(request: Request, session_id: str, artifact_id: str, site_id: str = Query(default="", max_length=100)) -> FileResponse:
    path, name = _query(lambda: _service(request).open_artifact(_site_id(request, site_id), session_id, artifact_id))
    return FileResponse(path, filename=name)


@router.get("/sessions/{session_id}/raw-sources", response_model=list[MeshDataSourceDTO])
def raw_sources(request: Request, session_id: str, site_id: str = Query(default="", max_length=100)) -> list[MeshDataSourceDTO]:
    return _query(lambda: _service(request).get_raw_source_summary(_site_id(request, site_id), session_id))


@router.get("/sessions/{session_id}/raw-sources/{source_id}/tail", response_model=MeshRawTailDTO)
def raw_tail(
    request: Request,
    session_id: str,
    source_id: str,
    site_id: str = Query(default="", max_length=100),
    lines: int = Query(default=100, ge=1, le=200),
) -> MeshRawTailDTO:
    return _query(lambda: _service(request).read_raw_tail(_site_id(request, site_id), session_id, source_id, lines=lines))


__all__ = ["router"]
