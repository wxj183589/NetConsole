from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.trackside_ap_business import (
    TracksideApBaseExportRequestDTO,
    TracksideApBusinessPageDTO,
    TracksideApPlanDTO,
    TracksideApPlanExportRequestDTO,
    TracksideApPlanPreviewDTO,
    TracksideApPlanWriteRequestDTO,
    TracksideApRenameCommandExportRequestDTO,
    TracksideApUpdateRequestDTO,
)
from netconsole.services.rail_transit.trackside_ap_business_query_service import TracksideApBusinessQueryService


router = APIRouter(prefix="/rail-transit/trackside-ap-business", tags=["trackside-ap-business"])
_ACTIONS = {
    "trackside_ap_optical_update",
    "trackside_ap_business_export",
    "trackside_ap_plan_save",
    "trackside_ap_plan_export",
    "trackside_ap_base_export",
    "trackside_ap_rename_command_export",
}


def _query_service(request: Request) -> TracksideApBusinessQueryService:
    return request.app.state.trackside_ap_business_query_service


def _application_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交应用服务未接线")
    return service


def _site_id(request: Request) -> str:
    try:
        return SiteManager(request.app.state.paths).validate_site_name(_query_service(request).current_site_id())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


@router.get("/rows", response_model=TracksideApBusinessPageDTO)
def rows(
    request: Request,
    station: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=200),
    optical_anomaly_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> TracksideApBusinessPageDTO:
    return _query_service(request).list_rows(
        _site_id(request),
        station=station,
        query=query,
        optical_anomaly_only=optical_anomaly_only,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    summary="导出轨旁 AP 业务工作簿",
    responses={
        422: {"description": "局点或导出参数无效"},
        503: {"description": "导出任务暂不可用"},
    },
    dependencies=[
        Depends(require_feature("web.rail_trackside_ap_business_export")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def export_business(request: Request) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_business_export(
            _site_id(request)
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    summary="下载轨旁 AP 业务工作簿",
    responses={404: {"description": "Artifact 不存在或不属于当前局点"}},
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_export"))],
)
def download_business_artifact(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _application_service(request).open_trackside_ap_business_export(
            _site_id(request),
            artifact_id,
        )
        return FileResponse(path, filename=name)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/base/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_trackside_ap_base_io")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def export_base(
    request: Request,
    payload: TracksideApBaseExportRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_base_export(
            _site_id(request),
            template=payload.template,
            rows=None if payload.rows is None else [row.model_dump() for row in payload.rows],
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/base/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_base_io"))],
)
def download_base_artifact(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _application_service(request).open_trackside_ap_base_export(
            _site_id(request), artifact_id
        )
        return FileResponse(path, filename=name)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/base/rename-commands/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_trackside_ap_base_io")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def export_rename_commands(
    request: Request,
    payload: TracksideApRenameCommandExportRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_rename_command_export(
            _site_id(request),
            rows=None if payload.rows is None else [row.model_dump() for row in payload.rows],
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/base/rename-commands/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_base_io"))],
)
def download_rename_command_artifact(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _application_service(request).open_trackside_ap_rename_command_export(
            _site_id(request), artifact_id
        )
        return FileResponse(path, filename=name, media_type="text/plain; charset=utf-8")
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/plan",
    response_model=TracksideApPlanDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def plan(request: Request) -> TracksideApPlanDTO:
    try:
        return _application_service(request).get_trackside_ap_plan(_site_id(request))
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/plan/import/preview",
    response_model=TracksideApPlanPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan_write"))],
)
async def preview_plan_import(
    request: Request,
    file: UploadFile = File(...),
    duplicate_strategy: str = Form(default="replace", pattern="^(replace|skip|error)$"),
) -> TracksideApPlanPreviewDTO:
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        return await asyncio.to_thread(
            _application_service(request).preview_trackside_ap_plan,
            _site_id(request),
            file_name=file.filename or "trackside-plan.xlsx",
            content=content,
            duplicate_strategy=duplicate_strategy,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/plan/save",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_trackside_ap_plan_write")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def save_plan(request: Request, payload: TracksideApPlanWriteRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_plan_save(
            _site_id(request),
            rows=[row.model_dump() for row in payload.rows],
            explicit_confirmation=payload.explicit_confirmation,
            audit=payload.audit,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/plan/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan_export"))],
)
def export_plan(request: Request, payload: TracksideApPlanExportRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_plan_export(
            _site_id(request),
            template=payload.template,
            rows=None if payload.rows is None else [row.model_dump() for row in payload.rows],
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/plan/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan_export"))],
)
def download_plan_artifact(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _application_service(request).open_trackside_ap_plan_export(
            _site_id(request),
            artifact_id,
        )
        return FileResponse(path, filename=name)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/update",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_trackside_ap_business_update")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def update(request: Request, payload: TracksideApUpdateRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_trackside_ap_update(
            _site_id(request),
            station=payload.station,
            ap_uuid=payload.ap_uuid,
            ap_mac=payload.ap_mac,
            ap_name=payload.ap_name,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/tasks/{task_id}",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        result = _application_service(request).get_task(_site_id(request), task_id)
        if result.action not in _ACTIONS:
            raise RailTransitWebError("TASK_NOT_FOUND", "轨旁 AP 任务不存在")
        return result
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def cancel_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        task(request, task_id)
        return _application_service(request).cancel_task(_site_id(request), task_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/tasks/recover",
    response_model=list[RailTransitTaskDTO],
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def recover_tasks(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return [
            item
            for item in _application_service(request).recover_tasks(_site_id(request))
            if item.action in _ACTIONS
        ]
    except RailTransitWebError as exc:
        _raise_error(exc)


def _raise_error(exc: RailTransitWebError) -> None:
    status_code = {
        "TASK_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "ARTIFACT_INVALID": status.HTTP_404_NOT_FOUND,
        "BLOCKED_ON_TASK_WINDOW": status.HTTP_503_SERVICE_UNAVAILABLE,
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
