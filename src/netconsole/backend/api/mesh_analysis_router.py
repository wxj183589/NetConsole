from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.application.rail_transit.mesh_bundle_application_service import (
    MeshBundleApplicationError,
    MeshBundleApplicationService,
)
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.mesh_analysis import (
    MeshAnalysisSessionDetailDTO,
    MeshAnalysisSessionPageDTO,
    MeshAnalysisSummaryDTO,
    MeshActiveBuildOrderPageDTO,
    MeshAnomalyPageDTO,
    MeshApStatisticsPageDTO,
    MeshBundleImportRequestDTO,
    MeshBundlePreviewDTO,
    MeshImportContextPrepareDTO,
    MeshChannelBusyPageDTO,
    MeshCounterDeltaPageDTO,
    MeshDataSourceDTO,
    MeshLinkPageDTO,
    MeshPathChartDTO,
    MeshProfileCreateRequestDTO,
    MeshProfileDTO,
    MeshRawTailDTO,
    MeshRebuildRequestDTO,
    MeshReportRequestDTO,
    MeshRatePageDTO,
    MeshReportArtifactDTO,
    MeshRssiDTO,
    MeshSwitchEventPageDTO,
    MeshTimelineDTO,
)
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryError, MeshAnalysisQueryService


router = APIRouter(prefix="/rail-transit/mesh-analysis", tags=["rail-transit-mesh-analysis"])
T = TypeVar("T")


def _service(request: Request) -> MeshAnalysisQueryService:
    return request.app.state.mesh_analysis_query_service


def _rail_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交 Web 服务未接线")
    return service


def _bundle_service(request: Request) -> MeshBundleApplicationService:
    service = getattr(request.app.state, "mesh_bundle_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="MESH ZIP 导入服务未接线")
    return service


def _current_site_id(request: Request) -> str:
    return request.app.state.online_mr_api_facade.current_site_id()


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


def _raise_bundle_error(exc: MeshBundleApplicationError) -> None:
    if exc.code in {"ARCHIVE_TOO_LARGE", "MEMBER_TOO_LARGE", "EXPANDED_SIZE_EXCEEDED"}:
        status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    elif exc.code == "PREVIEW_NOT_FOUND":
        status_code = status.HTTP_404_NOT_FOUND
    elif exc.code == "PREVIEW_EXPIRED":
        status_code = status.HTTP_410_GONE
    elif exc.code in {"IMPORT_BUSY", "ARCHIVE_CONFLICT", "PREVIEW_CACHE_FULL"}:
        status_code = status.HTTP_409_CONFLICT
    elif exc.code == "JOB_START_FAILED":
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.get("/summary", response_model=MeshAnalysisSummaryDTO)
def summary(request: Request, site_id: str = Query(default="", max_length=100)) -> MeshAnalysisSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request, site_id)))


@router.get("/profiles", response_model=list[MeshProfileDTO])
def profiles(request: Request) -> list[MeshProfileDTO]:
    return _query(lambda: _service(request).list_profiles(_current_site_id(request)))


@router.post(
    "/import-context/prepare",
    response_model=MeshImportContextPrepareDTO,
    summary="根据当前局点正式车载 MR 准备 MESH 导入上下文",
)
def prepare_import_context(request: Request) -> MeshImportContextPrepareDTO:
    try:
        return MeshImportContextPrepareDTO.model_validate(
            _bundle_service(request).prepare_import_context(_current_site_id(request))
        )
    except MeshBundleApplicationError as exc:
        _raise_bundle_error(exc)


@router.post(
    "/profiles",
    response_model=MeshProfileDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("web.mesh_analysis_import"))],
)
def create_profile(request: Request, payload: MeshProfileCreateRequestDTO) -> MeshProfileDTO:
    try:
        profile = _rail_service(request).create_mesh_profile(
            _current_site_id(request),
            display_name=payload.display_name,
            linked_mr_id=payload.linked_mr_id,
            notes=payload.notes,
        )
    except RailTransitWebError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if exc.code == "PROFILE_CONFLICT" else status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return MeshProfileDTO.model_validate(profile, from_attributes=True)


@router.post(
    "/import-preview",
    response_model=MeshBundlePreviewDTO,
    summary="统一预览 ZIP、LOG、GZ 或文件夹中的 MESH 日志",
    dependencies=[Depends(require_feature("web.mesh_analysis_import"))],
)
async def preview_import(
    request: Request,
    files: list[UploadFile] = File(...),
) -> MeshBundlePreviewDTO:
    try:
        payload = await asyncio.to_thread(
            _bundle_service(request).preview_files,
            _current_site_id(request),
            [(file.filename or "", file.file) for file in files],
        )
    except MeshBundleApplicationError as exc:
        _raise_bundle_error(exc)
    finally:
        for file in files:
            await file.close()
    return MeshBundlePreviewDTO.model_validate(payload)


@router.post(
    "/bundles/preview",
    response_model=MeshBundlePreviewDTO,
    summary="安全预览 MESH ZIP 并生成映射确认令牌",
    responses={
        413: {"description": "ZIP 本体、成员或解压总量超过安全上限"},
        422: {"description": "ZIP 结构、成员类型、压缩比或文件格式无效"},
    },
    dependencies=[Depends(require_feature("web.mesh_analysis_import"))],
)
async def preview_bundle(
    request: Request,
    file: UploadFile = File(...),
) -> MeshBundlePreviewDTO:
    try:
        payload = await asyncio.to_thread(
            _bundle_service(request).preview_bundle,
            _current_site_id(request),
            file_name=file.filename or "",
            source=file.file,
        )
    except MeshBundleApplicationError as exc:
        _raise_bundle_error(exc)
    finally:
        await file.close()
    return MeshBundlePreviewDTO.model_validate(payload)


@router.post(
    "/bundles/import",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    summary="确认 MESH ZIP 映射并提交独立后台导入任务",
    responses={
        404: {"description": "预览令牌不存在"},
        409: {"description": "导入任务冲突或预览缓存已满"},
        410: {"description": "预览令牌已过期"},
        422: {"description": "人工映射不完整或无效"},
        503: {"description": "Job Center 暂时不可用"},
    },
    dependencies=[
        Depends(require_feature("web.mesh_analysis_import")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def import_bundle(
    request: Request,
    payload: MeshBundleImportRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _bundle_service(request).start_import(
            _current_site_id(request),
            preview_id=payload.preview_id,
            mappings=[mapping.model_dump() for mapping in payload.mappings],
            explicit_confirmation=payload.explicit_confirmation,
        )
    except MeshBundleApplicationError as exc:
        _raise_bundle_error(exc)


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
    page_size: int = Query(default=100, ge=1, le=1_000),
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


@router.get(
    "/sessions/{session_id}/rate-series",
    response_model=MeshRatePageDTO,
    summary="读取 MESH 本端与对端 Rate 原始序列",
)
def rate_series(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
) -> MeshRatePageDTO:
    return _query(
        lambda: _service(request).get_rate_series(
            _site_id(request, site_id),
            session_id,
            time_from=time_from,
            time_to=time_to,
            max_points=max_points,
        )
    )


@router.get(
    "/sessions/{session_id}/active-build-order",
    response_model=MeshActiveBuildOrderPageDTO,
    summary="读取正式主链路建链顺序",
    responses={404: {"description": "分析会话或 compact v3 结果不存在"}},
)
def active_build_order(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    radio: int | None = Query(default=None, ge=1, le=64),
    peer: str = Query(default="", max_length=100),
    station: str = Query(default="", max_length=100),
    build_result: str = Query(default="", max_length=50),
    pingpong_only: bool = False,
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1_000),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> MeshActiveBuildOrderPageDTO:
    return _query(
        lambda: _service(request).list_active_build_order(
            _site_id(request, site_id),
            session_id,
            radio=radio,
            peer=peer,
            station=station,
            build_result=build_result,
            pingpong_only=pingpong_only,
            time_from=time_from,
            time_to=time_to,
            page=page,
            page_size=page_size,
            sort_order=sort_order,
        )
    )


@router.get(
    "/sessions/{session_id}/charts/active-path",
    response_model=MeshPathChartDTO,
    summary="读取全 ACTIVE 主链路动态图数据",
    responses={404: {"description": "分析会话或 compact v3 结果不存在"}},
)
def active_path_chart(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    radio: int | None = Query(default=None, ge=1, le=64),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
) -> MeshPathChartDTO:
    return _query(
        lambda: _service(request).get_active_path_chart(
            _site_id(request, site_id),
            session_id,
            radio=radio,
            time_from=time_from,
            time_to=time_to,
            max_points=max_points,
        )
    )


@router.get(
    "/sessions/{session_id}/charts/peer-segment",
    response_model=MeshPathChartDTO,
    summary="读取单 Peer 连续经过时段动态图数据",
    responses={404: {"description": "分析会话、锚点或 compact v3 结果不存在"}},
)
def peer_segment_chart(
    request: Request,
    session_id: str,
    anchor_link_id: int = Query(ge=1),
    site_id: str = Query(default="", max_length=100),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
    all_visits: bool = Query(default=False),
) -> MeshPathChartDTO:
    return _query(
        lambda: _service(request).get_peer_segment_chart(
            _site_id(request, site_id),
            session_id,
            anchor_link_id=anchor_link_id,
            time_from=time_from,
            time_to=time_to,
            max_points=max_points,
            all_visits=all_visits,
        )
    )


@router.get(
    "/sessions/{session_id}/counter-deltas",
    response_model=MeshCounterDeltaPageDTO,
    summary="读取 MESH Retry 与 Error 计数器增量",
)
def counter_deltas(
    request: Request,
    session_id: str,
    site_id: str = Query(default="", max_length=100),
    time_from: str = Query(default="", max_length=40),
    time_to: str = Query(default="", max_length=40),
    max_points: int = Query(default=1_000, ge=10, le=2_000),
) -> MeshCounterDeltaPageDTO:
    return _query(
        lambda: _service(request).get_counter_deltas(
            _site_id(request, site_id),
            session_id,
            time_from=time_from,
            time_to=time_to,
            max_points=max_points,
        )
    )


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


@router.post(
    "/sessions/{session_id}/rebuild",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.mesh_analysis_import")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def rebuild_session(request: Request, session_id: str, payload: MeshRebuildRequestDTO) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).start_mesh_rebuild(
            _current_site_id(request),
            session_id,
            explicit_confirmation=payload.explicit_confirmation,
        )
    except RailTransitWebError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if exc.code.endswith("NOT_FOUND") else status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post(
    "/sessions/{session_id}/report",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.mesh_analysis_report_export")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def start_report(
    request: Request,
    session_id: str,
    payload: MeshReportRequestDTO | None = None,
) -> RailTransitTaskDTO:
    try:
        override = (
            payload.analysis_params_override.model_dump(exclude_none=True)
            if payload and payload.analysis_params_override
            else None
        )
        return _rail_service(request).start_mesh_report(
            _current_site_id(request),
            session_id,
            analysis_params_override=override,
        )
    except RailTransitWebError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if exc.code.endswith("NOT_FOUND") else status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get(
    "/report-artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.mesh_analysis_report_export"))],
)
def download_generated_report(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _rail_service(request).open_mesh_report(_current_site_id(request), artifact_id)
    except RailTransitWebError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return FileResponse(path, filename=name)


__all__ = ["router"]
