from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.backend.api.feature_access import require_feature
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
from netconsole.models.api.rail_transit_web import OnlineMrReportRequestDTO, RailTransitTaskDTO
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


@router.post(
    "/sessions/{session_id}/report",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.online_mr_report_export")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def report(request: Request, session_id: str, payload: OnlineMrReportRequestDTO) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).start_online_mr_report(
            _facade(request).current_site_id(), session_id, payload.output_name
        )
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


@router.post(
    "/mesh-analysis/import",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.mesh_analysis_import")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
async def mesh_analysis_import(
    request: Request,
    files: list[UploadFile] = File(...),
    mr_id: str = Form(default=""),
) -> RailTransitTaskDTO:
    service = _rail_service(request)
    site_id = _facade(request).current_site_id()
    staging = None
    try:
        submitted = await request.form()
        forbidden = {"site_id", "relative_folder_path", "display_name", "safe_folder_name", "linked_device_id", "notes"}
        if forbidden.intersection(submitted):
            raise RailTransitWebError("BROWSER_PROFILE_FORBIDDEN", "Browser 只能提交正式 MESH MR profile 标识")
        staging, staged = await asyncio.to_thread(
            service.stage_mesh_uploads,
            site_id,
            [(upload.filename or "", upload.file) for upload in files],
        )
        return service.start_mesh_import(
            site_id,
            mr_id=mr_id,
            staging_dir=staging,
            uploads=staged,
        )
    except RailTransitWebError as exc:
        if staging is not None:
            service.discard_mesh_staging(site_id, staging)
        _raise_rail_error(exc)
    except Exception:
        if staging is not None:
            service.discard_mesh_staging(site_id, staging)
        raise
    finally:
        for upload in files:
            await upload.close()


@router.get(
    "/report-artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.online_mr_report_export"))],
)
def report_download(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _rail_service(request).open_online_mr_report(
            _facade(request).current_site_id(), artifact_id
        )
    except RailTransitWebError as exc:
        _raise_rail_error(exc)
    return FileResponse(path, filename=name)


@router.get(
    "/tasks/{task_id}",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def task_detail(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).get_task(_facade(request).current_site_id(), task_id)
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def task_cancel(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).cancel_task(_facade(request).current_site_id(), task_id)
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


@router.post(
    "/tasks/recover",
    response_model=list[RailTransitTaskDTO],
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def task_recover(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return _rail_service(request).recover_tasks(_facade(request).current_site_id())
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


def _raise_rail_error(exc: RailTransitWebError) -> None:
    not_found = {"TASK_NOT_FOUND", "SESSION_NOT_FOUND", "MESH_SESSION_NOT_FOUND", "MESH_RESULT_NOT_FOUND", "ARTIFACT_INVALID"}
    status_code = status.HTTP_404_NOT_FOUND if exc.code in not_found else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
