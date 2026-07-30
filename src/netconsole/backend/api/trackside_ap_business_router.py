from __future__ import annotations

import asyncio
import os
import threading
import time
import traceback
import uuid
from typing import NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.feature_access import require_feature
from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.core import app_logger
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.trackside_ap_business import (
    ApManagementVlanAutoGroupRequestDTO,
    ApManagementVlanPreviewDTO,
    ApManagementVlanPreviewRequestDTO,
    EffectiveManagementNetworkDTO,
    TracksideApBaseExportRequestDTO,
    TracksideApBusinessPageDTO,
    TracksideApPlanDTO,
    TracksideApPlanExportRequestDTO,
    TracksideApOnlineStatusDTO,
    TracksideApPlanPreviewDTO,
    TracksideApPlanWriteRequestDTO,
    TracksideApPointTablePreviewDTO,
    TracksideApRenameCommandExportRequestDTO,
    TracksideApUpdateRequestDTO,
    TracksideSwitchAdapterCatalogDTO,
    TracksideSwitchSampleRequestDTO,
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
    "switch_vendor_sample_collect",
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


@router.get(
    "/switch-adapters",
    response_model=TracksideSwitchAdapterCatalogDTO,
    dependencies=[
        Depends(require_feature("rail.zte_trackside_switch_adapter")),
    ],
)
def switch_adapters(request: Request) -> TracksideSwitchAdapterCatalogDTO:
    return _query_service(request).list_switch_adapters(_site_id(request))


@router.post(
    "/switch-adapters/sample",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("rail.zte_trackside_switch_adapter")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def start_switch_adapter_sample(
    request: Request,
    payload: TracksideSwitchSampleRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_switch_vendor_sample(
            _site_id(request),
            device_uuid=payload.device_uuid,
            vendor=payload.vendor,
            command_profile=payload.command_profile,
            selected_interface=payload.selected_interface,
            requested_commands=payload.requested_commands,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/switch-adapters/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[
        Depends(require_feature("rail.zte_trackside_switch_adapter")),
    ],
)
def download_switch_adapter_sample(
    request: Request,
    artifact_id: str,
) -> FileResponse:
    try:
        path, name = _application_service(request).open_switch_vendor_sample(
            _site_id(request),
            artifact_id,
        )
        return FileResponse(path, filename=name, media_type="application/zip")
    except RailTransitWebError as exc:
        _raise_error(exc)


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
            issues=None if payload.issues is None else [row.model_dump() for row in payload.issues],
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
def plan(request: Request, response: Response) -> TracksideApPlanDTO:
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    path = str(request.url.path)
    site_id = ""
    app_logger.log_info(
        "trackside_ap_plan.request_started",
        (
            f"request_id={request_id} path={path} method={request.method} "
            f"backend_pid={os.getpid()} thread_id={threading.get_ident()}"
        ),
    )
    try:
        site_id = _site_id(request)
        service = _application_service(request)
        with map_api_errors(
            "轨旁 AP 规划数据库暂时不可读",
            structured_database_errors=True,
            database_context=lambda: {
                "request_id": request_id,
                "operation": "trackside_ap_plan_load",
                "route": path,
                "site": site_id,
                "database_path": str(request.app.state.paths.site_db_path(site_id)),
            },
        ):
            result = service.get_trackside_ap_plan(site_id, request_id=request_id)
        # Validate JSON serialization inside the controlled error boundary so a
        # malformed persisted row cannot terminate the response stream.
        payload = result.model_dump(mode="json")
        response.headers["X-Request-ID"] = request_id
        response.headers["X-NetConsole-Backend-PID"] = str(os.getpid())
        app_logger.log_info(
            "trackside_ap_plan.request_completed",
            (
                f"request_id={request_id} path={path} site_id={site_id} "
                f"backend_pid={os.getpid()} thread_id={threading.get_ident()} "
                f"status=200 rows={len(result.items)} json_bytes={len(str(payload).encode('utf-8'))} "
                f"duration_ms={(time.perf_counter() - started) * 1000:.2f}"
            ),
        )
        return result
    except RailTransitWebError as exc:
        _raise_plan_error(
            request_id,
            path,
            site_id,
            started,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=exc.code,
            message=str(exc),
            cause=exc,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        _raise_plan_error(
            request_id,
            path,
            site_id,
            started,
            status_code=exc.status_code,
            code=str(detail.get("code") or "TRACKSIDE_AP_PLAN_REQUEST_INVALID"),
            message=str(detail.get("message") or detail or "轨旁 AP 规划请求失败"),
            cause=exc,
        )
    except Exception as exc:
        _raise_plan_error(
            request_id,
            path,
            site_id,
            started,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="TRACKSIDE_AP_PLAN_LOAD_FAILED",
            message="轨旁 AP 规划加载失败，请查看诊断信息。",
            cause=exc,
        )


@router.get(
    "/plan/online-status",
    response_model=TracksideApOnlineStatusDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def plan_online_status(request: Request) -> TracksideApOnlineStatusDTO:
    try:
        return _application_service(request).get_trackside_ap_online_status(
            _site_id(request)
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/plan/auto-group-preview",
    response_model=ApManagementVlanPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def preview_auto_group(
    request: Request,
    payload: ApManagementVlanAutoGroupRequestDTO,
) -> ApManagementVlanPreviewDTO:
    try:
        return _application_service(request).preview_trackside_ap_vlan_auto_group(
            _site_id(request),
            planning_mode=payload.planning_mode,
            auto_group_station_count=payload.auto_group_station_count,
            current=None if payload.current is None else payload.current.model_dump(),
            reallocation_policy=payload.reallocation_policy,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


def _preview_plan_change(
    request: Request,
    payload: ApManagementVlanPreviewRequestDTO,
) -> ApManagementVlanPreviewDTO:
    try:
        return _application_service(request).preview_trackside_ap_vlan_change(
            _site_id(request),
            proposed=payload.proposed.model_dump(),
            reallocation_policy=payload.reallocation_policy,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/plan/adjustment-preview",
    response_model=ApManagementVlanPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def preview_adjustment(
    request: Request,
    payload: ApManagementVlanPreviewRequestDTO,
) -> ApManagementVlanPreviewDTO:
    return _preview_plan_change(request, payload)


@router.post(
    "/plan/mode-impact-preview",
    response_model=ApManagementVlanPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def preview_mode_impact(
    request: Request,
    payload: ApManagementVlanPreviewRequestDTO,
) -> ApManagementVlanPreviewDTO:
    return _preview_plan_change(request, payload)


@router.post(
    "/plan/validate",
    response_model=ApManagementVlanPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def validate_plan(
    request: Request,
    payload: ApManagementVlanPreviewRequestDTO,
) -> ApManagementVlanPreviewDTO:
    return _preview_plan_change(request, payload)


@router.post(
    "/plan/address-preview",
    response_model=ApManagementVlanPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def preview_addresses(
    request: Request,
    payload: ApManagementVlanPreviewRequestDTO,
) -> ApManagementVlanPreviewDTO:
    return _preview_plan_change(request, payload)


@router.get(
    "/plan/effective-network",
    response_model=EffectiveManagementNetworkDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def effective_network(
    request: Request,
    station_id: str = Query(default="", max_length=100),
    ap_id: str = Query(default="", max_length=100),
) -> EffectiveManagementNetworkDTO:
    if not station_id and not ap_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="station_id 与 ap_id 至少填写一个",
        )
    try:
        return _application_service(
            request
        ).get_effective_trackside_ap_management_network(
            _site_id(request),
            station_id=station_id,
            ap_id=ap_id,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/plan/point-table-preview",
    response_model=TracksideApPointTablePreviewDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_plan"))],
)
def preview_point_table(
    request: Request,
    payload: ApManagementVlanPreviewRequestDTO,
) -> TracksideApPointTablePreviewDTO:
    try:
        return _application_service(request).preview_trackside_ap_point_table(
            _site_id(request),
            proposed=payload.proposed.model_dump(),
        )
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
            draft=None if payload.draft is None else payload.draft.model_dump(),
            expected_revision=payload.expected_revision,
            reallocation_policy=payload.reallocation_policy,
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
        "SWITCH_DEVICE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "BLOCKED_ON_TASK_WINDOW": status.HTTP_503_SERVICE_UNAVAILABLE,
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


def _raise_plan_error(
    request_id: str,
    path: str,
    site_id: str,
    started: float,
    *,
    status_code: int,
    code: str,
    message: str,
    cause: BaseException,
) -> NoReturn:
    original_message = app_logger.sanitize_detail(str(cause))
    safe_traceback = app_logger.sanitize_detail(traceback.format_exc())
    app_logger.log_error(
        "trackside_ap_plan.request_failed",
        (
            f"request_id={request_id} path={path} site_id={site_id} "
            f"backend_pid={os.getpid()} thread_id={threading.get_ident()} "
            f"status={status_code} code={code} exception_type={cause.__class__.__name__} "
            f"message={original_message} duration_ms={(time.perf_counter() - started) * 1000:.2f} "
            f"traceback={safe_traceback}"
        ),
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "request_id": request_id,
            "path": path,
            "status": status_code,
            "details": {
                "site_id": site_id,
                "exception_type": cause.__class__.__name__,
                "original_message": original_message,
            },
        },
        headers={
            "X-Request-ID": request_id,
            "X-NetConsole-Backend-PID": str(os.getpid()),
        },
    ) from cause


__all__ = ["router"]
