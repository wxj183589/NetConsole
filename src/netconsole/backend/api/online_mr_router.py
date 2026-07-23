from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.backend.api.feature_access import require_feature
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.common import ApiResponse
from netconsole.models.api.online_mr import (
    OnlineMrCollectorStatusDTO,
    OnlineMrArtifactDTO,
    OnlineMrBusinessSummaryDTO,
    OnlineMrBusinessTable,
    OnlineMrBusinessTablePageDTO,
    OnlineMrMetricPageDTO,
    OnlineMrMetricSeriesDTO,
    OnlineMrManualNoteDTO,
    OnlineMrRawFileDTO,
    OnlineMrRawTailDTO,
    OnlineMrRealtimePreviewDTO,
    OnlineMrSessionDetailDTO,
    OnlineMrSessionSummaryDTO,
    OnlineMrSwitchRssiPageDTO,
    OnlineMrTimelineEventDTO,
)
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.models.api.rail_transit_web import (
    OnlineMrNoteCreateRequestDTO,
    OnlineMrDeleteRequestDTO,
    OnlineMrDesktopLocationDTO,
    OnlineMrParseRequestDTO,
    OnlineMrReportRequestDTO,
    RailTransitTaskDTO,
)
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade


router = APIRouter(prefix="/online-mr", tags=["online-mr"])


def _facade(request: Request) -> OnlineMrApiFacade:
    return request.app.state.online_mr_api_facade


def _rail_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交 Web 服务未接线")
    return service


def _desktop(request: Request) -> None:
    if (
        request.app.state.runtime_mode is not RuntimeMode.DESKTOP
        or request.url.hostname != "127.0.0.1"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该功能仅在 NetConsole Electron 桌面端可用。",
        )


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


@router.get("/sessions/{session_id}/business-summary", response_model=ApiResponse[OnlineMrBusinessSummaryDTO])
def business_summary(request: Request, session_id: str) -> ApiResponse[OnlineMrBusinessSummaryDTO]:
    return ApiResponse(data=_facade(request).business_summary(session_id))


@router.get("/sessions/{session_id}/business-table", response_model=ApiResponse[OnlineMrBusinessTablePageDTO])
def business_table(
    request: Request,
    session_id: str,
    table: OnlineMrBusinessTable,
    start_time: str = Query(default="", max_length=40),
    end_time: str = Query(default="", max_length=40),
    limit: int = Query(default=500, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> ApiResponse[OnlineMrBusinessTablePageDTO]:
    return ApiResponse(
        data=_facade(request).business_table(
            session_id,
            table,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
    )


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


@router.get("/sessions/{session_id}/metric-page", response_model=ApiResponse[OnlineMrMetricPageDTO])
def metric_page(
    request: Request,
    session_id: str,
    metric_types: str = Query(default="rssi", max_length=300),
    start_time: str = Query(default="", max_length=40),
    end_time: str = Query(default="", max_length=40),
    limit: int = Query(default=1_000, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    downsample: str = Query(default="NONE", pattern="^(NONE|BUCKET_AVG|MIN_MAX|LATEST_PER_BUCKET)$"),
    bucket_seconds: int = Query(default=1, ge=1, le=86_400),
) -> ApiResponse[OnlineMrMetricPageDTO]:
    try:
        data = _rail_service(request).query_metric_page(
            _facade(request).current_site_id(),
            session_id,
            [value.strip() for value in metric_types.split(",") if value.strip()],
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
            downsample=downsample,
            bucket_seconds=bucket_seconds,
        )
    except (RailTransitWebError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ApiResponse(data=data)


@router.get(
    "/sessions/{session_id}/switch-rssi-windows",
    response_model=ApiResponse[OnlineMrSwitchRssiPageDTO],
)
def switch_rssi_windows(
    request: Request,
    session_id: str,
    source: str = Query(pattern="^(history|realtime)$"),
    start_time: str = Query(default="", max_length=40),
    end_time: str = Query(default="", max_length=40),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> ApiResponse[OnlineMrSwitchRssiPageDTO]:
    try:
        data = _rail_service(request).query_switch_rssi_windows(
            _facade(request).current_site_id(),
            session_id,
            source,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
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


@router.get("/sessions/{session_id}/notes", response_model=ApiResponse[list[OnlineMrManualNoteDTO]])
def notes(
    request: Request,
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> ApiResponse[list[OnlineMrManualNoteDTO]]:
    return ApiResponse(data=_rail_service(request).notes(_facade(request).current_site_id(), session_id, limit=limit, offset=offset))


@router.post(
    "/sessions/{session_id}/notes",
    response_model=OnlineMrManualNoteDTO,
    dependencies=[Depends(require_feature("online_mr.collection_notes"))],
)
def add_note(request: Request, session_id: str, payload: OnlineMrNoteCreateRequestDTO) -> OnlineMrManualNoteDTO:
    try:
        return _rail_service(request).add_online_mr_note(
            _facade(request).current_site_id(),
            session_id,
            note=payload.note,
            explicit_confirmation=payload.explicit_confirmation,
            audit=payload.audit,
        )
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


@router.post(
    "/sessions/{session_id}/parse",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.online_mr_parse")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def parse_session(request: Request, session_id: str, payload: OnlineMrParseRequestDTO) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).start_online_mr_parse(
            _facade(request).current_site_id(), session_id, force_reparse=payload.force_reparse
        )
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


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
    "/sessions/{session_id}/desktop-location",
    response_model=OnlineMrDesktopLocationDTO,
    dependencies=[
        Depends(_desktop),
        Depends(require_feature("desktop.native_bridge")),
        Depends(require_feature("web.online_mr_session_open_location")),
    ],
)
def desktop_location(
    request: Request,
    session_id: str,
) -> OnlineMrDesktopLocationDTO:
    try:
        return OnlineMrDesktopLocationDTO.model_validate(
            _rail_service(request).online_mr_desktop_location(
                _facade(request).current_site_id(),
                session_id,
            )
        )
    except RailTransitWebError as exc:
        _raise_rail_error(exc)


@router.delete(
    "/sessions/{session_id}",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.online_mr_session_delete")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def delete_session(
    request: Request,
    session_id: str,
    payload: OnlineMrDeleteRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).start_online_mr_delete(
            _facade(request).current_site_id(),
            session_id,
            expected_session_id=payload.expected_session_id,
            explicit_confirmation=payload.explicit_confirmation,
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
    not_found = {
        "TASK_NOT_FOUND",
        "SESSION_NOT_FOUND",
        "RAW_DATA_NOT_FOUND",
        "MESH_SESSION_NOT_FOUND",
        "MESH_RESULT_NOT_FOUND",
        "ARTIFACT_INVALID",
        "ONLINE_MR_LOCAL_FILES_MISSING",
    }
    conflicts = {
        "ONLINE_MR_SESSION_RUNNING",
        "ONLINE_MR_SESSION_TASK_ACTIVE",
        "TASK_RESOURCE_BUSY",
    }
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code in not_found
        else status.HTTP_409_CONFLICT
        if exc.code in conflicts
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
