from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from netconsole.models.api.common import ApiResponse
from netconsole.models.api.online_mr import (
    OnlineMrCollectorStatusDTO,
    OnlineMrArtifactDTO,
    OnlineMrMetricSeriesDTO,
    OnlineMrRawFileDTO,
    OnlineMrRawTailDTO,
    OnlineMrRealtimePreviewDTO,
    OnlineMrSessionDetailDTO,
    OnlineMrSessionSummaryDTO,
    OnlineMrTimelineEventDTO,
)
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.models.api.rail_transit_web import OnlineMrReportRequestDTO, RailTransitTaskDTO, RailTransitTaskRequestDTO
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade


router = APIRouter(prefix="/online-mr", tags=["online-mr"])


def _facade(request: Request) -> OnlineMrApiFacade:
    return request.app.state.online_mr_api_facade


def _rail_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交 Web 服务未接线")
    return service


@router.get("/sessions/current", response_model=ApiResponse[OnlineMrSessionDetailDTO | None])
def current_session(request: Request) -> ApiResponse[OnlineMrSessionDetailDTO | None]:
    return ApiResponse(data=_facade(request).current_session())


@router.get("/sessions/recent", response_model=ApiResponse[list[OnlineMrSessionSummaryDTO]])
def recent_sessions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[list[OnlineMrSessionSummaryDTO]]:
    return ApiResponse(data=_facade(request).recent_sessions(limit=limit))


@router.get("/sessions/{session_id}", response_model=ApiResponse[OnlineMrSessionDetailDTO])
def session_detail(request: Request, session_id: str) -> ApiResponse[OnlineMrSessionDetailDTO]:
    return ApiResponse(data=_facade(request).session_detail(session_id))


@router.get("/sessions/{session_id}/collectors", response_model=ApiResponse[list[OnlineMrCollectorStatusDTO]])
def collectors(request: Request, session_id: str) -> ApiResponse[list[OnlineMrCollectorStatusDTO]]:
    return ApiResponse(data=_facade(request).collectors(session_id))


@router.get("/sessions/{session_id}/preview", response_model=ApiResponse[OnlineMrRealtimePreviewDTO])
def preview(request: Request, session_id: str) -> ApiResponse[OnlineMrRealtimePreviewDTO]:
    return ApiResponse(data=_facade(request).preview(session_id))


@router.get("/sessions/{session_id}/raw-tail", response_model=ApiResponse[OnlineMrRawTailDTO])
def raw_tail(
    request: Request,
    session_id: str,
    name: str,
    tail: int = Query(default=200, ge=1, le=500),
) -> ApiResponse[OnlineMrRawTailDTO]:
    return ApiResponse(data=_facade(request).raw_tail(session_id, name, tail=tail))


@router.get("/sessions/{session_id}/raw-summary", response_model=ApiResponse[list[OnlineMrRawFileDTO]])
def raw_summary(request: Request, session_id: str) -> ApiResponse[list[OnlineMrRawFileDTO]]:
    return ApiResponse(data=_facade(request).raw_summary(session_id))


@router.get("/sessions/{session_id}/logs", response_model=ApiResponse[OnlineMrRawTailDTO])
def collector_logs(
    request: Request,
    session_id: str,
    tail: int = Query(default=200, ge=1, le=500),
) -> ApiResponse[OnlineMrRawTailDTO]:
    return ApiResponse(data=_facade(request).raw_tail(session_id, "collector_output", tail=tail))


@router.get("/sessions/{session_id}/metrics", response_model=ApiResponse[list[OnlineMrMetricSeriesDTO]])
def metrics(
    request: Request,
    session_id: str,
    metric_types: str = Query(default="rssi", max_length=300),
    start_time: str = Query(default="", max_length=40),
    end_time: str = Query(default="", max_length=40),
    limit: int = Query(default=5_000, ge=1, le=10_000),
    downsample: str = Query(default="NONE", pattern="^(NONE|BUCKET_AVG|MIN_MAX|LATEST_PER_BUCKET)$"),
    bucket_seconds: int = Query(default=1, ge=1, le=86_400),
) -> ApiResponse[list[OnlineMrMetricSeriesDTO]]:
    try:
        data = _rail_service(request).query_metrics(
            _facade(request).current_site_id(),
            session_id,
            [value.strip() for value in metric_types.split(",") if value.strip()],
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            downsample=downsample,
            bucket_seconds=bucket_seconds,
        )
    except (RailTransitWebError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get("/sessions/{session_id}/timeline", response_model=ApiResponse[list[OnlineMrTimelineEventDTO]])
def timeline(
    request: Request,
    session_id: str,
    limit: int = Query(default=500, ge=1, le=10_000),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ApiResponse[list[OnlineMrTimelineEventDTO]]:
    return ApiResponse(data=_rail_service(request).query_timeline(_facade(request).current_site_id(), session_id, limit=limit, offset=offset))


@router.get("/sessions/{session_id}/database-summary", response_model=ApiResponse[dict[str, object]])
def database_summary(request: Request, session_id: str) -> ApiResponse[dict[str, object]]:
    return ApiResponse(data=_rail_service(request).database_summary(_facade(request).current_site_id(), session_id))


@router.get("/sessions/{session_id}/artifacts", response_model=ApiResponse[list[OnlineMrArtifactDTO]])
def artifacts(request: Request, session_id: str) -> ApiResponse[list[OnlineMrArtifactDTO]]:
    return ApiResponse(data=_rail_service(request).artifacts(_facade(request).current_site_id(), session_id))


@router.post("/sessions/{session_id}/report", response_model=RailTransitTaskDTO, status_code=status.HTTP_202_ACCEPTED)
def report(request: Request, session_id: str, payload: OnlineMrReportRequestDTO) -> RailTransitTaskDTO:
    try:
        site_id = payload.site_id or _facade(request).current_site_id()
        return _rail_service(request).start_online_mr_report(site_id, session_id, payload.output_name)
    except RailTransitWebError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/mesh-analysis/import", response_model=RailTransitTaskDTO, status_code=status.HTTP_202_ACCEPTED)
async def mesh_analysis_import(
    request: Request,
    files: list[UploadFile] = File(...),
    site_id: str = Form(default=""),
    mr_id: str = Form(default=""),
    display_name: str = Form(default=""),
    safe_folder_name: str = Form(default=""),
    relative_folder_path: str = Form(default=""),
    linked_device_id: int | None = Form(default=None),
    notes: str = Form(default=""),
) -> RailTransitTaskDTO:
    contents: list[tuple[str, bytes]] = []
    total_size = 0
    try:
        for upload in files:
            content = await upload.read(20 * 1024 * 1024 + 1)
            total_size += len(content)
            if total_size > 100 * 1024 * 1024:
                raise RailTransitWebError("FILES_TOO_LARGE", "MESH 导入文件总大小不得超过 100 MB")
            contents.append((upload.filename or "", content))
        selected_site = site_id or _facade(request).current_site_id()
        return _rail_service(request).start_mesh_import(
            selected_site,
            profile={
                "mr_id": mr_id,
                "display_name": display_name,
                "safe_folder_name": safe_folder_name,
                "relative_folder_path": relative_folder_path,
                "linked_device_id": linked_device_id,
                "notes": notes,
            },
            uploads=contents,
        )
    except RailTransitWebError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": exc.code, "message": str(exc)}) from exc
    finally:
        for upload in files:
            await upload.close()


@router.post("/car-network-diagnostic", response_model=RailTransitTaskDTO, status_code=status.HTTP_202_ACCEPTED)
def car_network_diagnostic(request: Request, payload: RailTransitTaskRequestDTO) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).start_car_network_diagnostic(payload.site_id or _facade(request).current_site_id(), train_id=payload.train_id)
    except RailTransitWebError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
