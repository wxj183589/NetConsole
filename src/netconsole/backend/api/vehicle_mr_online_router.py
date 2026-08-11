from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.ac_mesh_link import AcMeshLinkRefreshRequestDTO, AcMeshLinkRefreshResponseDTO
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.vehicle_mr_online import (
    VehicleMrEventPageDTO,
    VehicleMrCollectionStartRequestDTO,
    VehicleMrControllerDTO,
    VehicleMrHistoryExportRequestDTO,
    VehicleMrMappingPreviewDTO,
    VehicleMrMappingSaveRequestDTO,
    VehicleMrOnlinePageDTO,
    VehicleMrTrainStateDTO,
    VehicleMrTrainMappingDTO,
)
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkRefreshApplicationService,
    AcMeshLinkRefreshError,
    AcMeshLinkRefreshErrorCode,
)
from netconsole.services.rail_transit.vehicle_mr_online_query_service import VehicleMrOnlineQueryService


router = APIRouter(prefix="/rail-transit/train-online", tags=["vehicle-mr-online"])
_ACTIONS = {
    "vehicle_mr_online_refresh_all",
    "vehicle_mr_ap_mapping_refresh",
    "vehicle_mr_mapping_save",
    "vehicle_mr_online_collection_start",
    "vehicle_mr_history_export",
    "vehicle_mr_mapping_template_export",
}


def _query_service(request: Request) -> VehicleMrOnlineQueryService:
    return request.app.state.vehicle_mr_online_query_service


def _application_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交应用服务未接线")
    return service


def _mesh_refresh_service(request: Request) -> AcMeshLinkRefreshApplicationService:
    return request.app.state.ac_mesh_link_refresh_service


def _site_id(request: Request) -> str:
    try:
        return SiteManager(request.app.state.paths).validate_site_name(_query_service(request).current_site_id())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


@router.get("/trains", response_model=VehicleMrOnlinePageDTO, summary="分页查询列车 Mesh-Link 在线状态")
def trains(
    request: Request,
    query: str = Query(default="", max_length=200),
    overall_status: str = Query(default="", pattern="^(|BOTH_ONLINE|ONE_SIDE_ONLINE|BOTH_OFFLINE|STALE|UNKNOWN)$"),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    data_status: str = Query(default="", pattern="^(|FRESH|STALE|ERROR|NO_DATA|UNKNOWN)$"),
    unmatched_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> VehicleMrOnlinePageDTO:
    return _query_service(request).list_trains(
        _site_id(request),
        query=query,
        status=overall_status,
        station=station,
        section=section,
        data_status=data_status,
        unmatched_only=unmatched_only,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/trains/{train_id}",
    response_model=VehicleMrTrainStateDTO,
    summary="查询单列车 CT/TC 通信详情",
    responses={404: {"description": "列车在线状态不存在"}},
)
def train_detail(request: Request, train_id: str) -> VehicleMrTrainStateDTO:
    result = _query_service(request).get_train(_site_id(request), train_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="列车在线状态不存在")
    return result


@router.get("/mappings", response_model=list[VehicleMrTrainMappingDTO])
def mappings(request: Request) -> list[VehicleMrTrainMappingDTO]:
    return _query_service(request).list_mappings(_site_id(request))


@router.post(
    "/mappings/import/preview",
    response_model=VehicleMrMappingPreviewDTO,
    dependencies=[Depends(require_feature("capability.train_online.mapping_import"))],
)
async def preview_mapping_import(
    request: Request,
    file: UploadFile = File(...),
    duplicate_strategy: str = Form(default="replace", pattern="^(replace|skip|error)$"),
) -> VehicleMrMappingPreviewDTO:
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        return await asyncio.to_thread(
            _application_service(request).preview_vehicle_mr_mappings,
            _site_id(request),
            file_name=file.filename or "vehicle-mr-mapping.xlsx",
            content=content,
            duplicate_strategy=duplicate_strategy,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get("/controllers", response_model=list[VehicleMrControllerDTO])
def controllers(request: Request) -> list[VehicleMrControllerDTO]:
    return _query_service(request).list_controllers(_site_id(request))


@router.get("/trains/{train_id}/events", response_model=VehicleMrEventPageDTO)
def events(
    request: Request,
    train_id: str,
    start_time: str = Query(default="", max_length=30),
    end_time: str = Query(default="", max_length=30),
    car_end_label: str = Query(default="", max_length=10),
    event_status: str = Query(default="", max_length=20),
    station: str = Query(default="", max_length=100),
    ap_name: str = Query(default="", max_length=100),
    limit: int = Query(default=200, ge=1, le=2000),
) -> VehicleMrEventPageDTO:
    return _query_service(request).list_events(
        _site_id(request),
        train_id,
        start_time=start_time,
        end_time=end_time,
        car_end_label=car_end_label,
        status=event_status,
        station=station,
        ap_name=ap_name,
        limit=limit,
    )


@router.post(
    "/collection/start",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("capability.train_online.collect")),
        Depends(require_feature("capability.rail_transit.task_control")),
    ],
)
def start_collection(request: Request, payload: VehicleMrCollectionStartRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_vehicle_mr_online_collection(
            _site_id(request),
            ac_device_id=payload.ac_device_id,
            interval_seconds=payload.interval_seconds,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/collection/{task_id}/stop",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("capability.rail_transit.task_control"))],
)
def stop_collection(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        current = task(request, task_id)
        if current.action != "vehicle_mr_online_collection_start":
            raise RailTransitWebError("TASK_NOT_FOUND", "列车在线连续采集任务不存在")
        return _application_service(request).cancel_task(_site_id(request), task_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/refresh",
    response_model=AcMeshLinkRefreshResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
    summary="创建或复用列车 Mesh-Link 采集任务",
    responses={404: {"description": "AC 不存在"}, 422: {"description": "AC 连接配置无效"}, 503: {"description": "任务暂时无法创建"}},
    dependencies=[Depends(require_feature("capability.train_online.refresh"))],
)
def refresh(request: Request, payload: AcMeshLinkRefreshRequestDTO) -> AcMeshLinkRefreshResponseDTO:
    try:
        result = _mesh_refresh_service(request).start_refresh(
            site_name=_site_id(request),
            controller_id=payload.controller_id,
            include_switch_history=payload.include_switch_history,
        )
    except AcMeshLinkRefreshError as exc:
        status_code = status.HTTP_404_NOT_FOUND if exc.code == AcMeshLinkRefreshErrorCode.CONTROLLER_NOT_FOUND else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AC_MESH_LINK_INTERNAL_ERROR", "message": "Mesh-Link 刷新任务暂时无法创建"},
        ) from exc
    return AcMeshLinkRefreshResponseDTO(
        task_id=result.task.task_id,
        status=result.task.status.value,
        already_running=result.already_running,
        task_mode="resident" if result.resident else "once",
        request_id=result.request_id,
        message=(
            "已请求常驻 AC 会话立即刷新"
            if result.resident
            else "Mesh-Link 刷新任务正在运行"
            if result.already_running
            else "Mesh-Link 刷新任务已创建"
        ),
    )


@router.post(
    "/ap-mapping/refresh",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.train_online.refresh"))],
)
def refresh_ap_mapping(request: Request, train_id: str = Query(default="", max_length=100)) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_vehicle_mr_ap_mapping_refresh(_site_id(request), train_id=train_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.put(
    "/mappings",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.train_online.mapping_write"))],
)
def save_mappings(request: Request, payload: VehicleMrMappingSaveRequestDTO) -> RailTransitTaskDTO:
    try:
        return _application_service(request).save_vehicle_mr_mappings(
            _site_id(request),
            [row.model_dump(mode="json") for row in payload.mappings],
            explicit_confirmation=payload.explicit_confirmation,
            audit=payload.audit,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/mappings/template/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.train_online.mapping_export"))],
)
def export_mapping_template(request: Request) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_vehicle_mr_mapping_template_export(_site_id(request))
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/mappings/template/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("capability.train_online.mapping_export"))],
)
def download_mapping_template(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _application_service(request).open_vehicle_mr_mapping_template(_site_id(request), artifact_id)
        return FileResponse(path, filename=name)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/history/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.train_online.history_export"))],
)
def export_history(request: Request, payload: VehicleMrHistoryExportRequestDTO) -> RailTransitTaskDTO:
    try:
        values = payload.model_dump(exclude={"train_id"})
        return _application_service(request).start_vehicle_mr_history_export(
            _site_id(request),
            train_id=payload.train_id,
            filters=values,
        )
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/history/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("capability.train_online.history_export"))],
)
def download_history(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _application_service(request).open_vehicle_mr_history_export(_site_id(request), artifact_id)
        return FileResponse(path, filename=name)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.get(
    "/tasks/{task_id}",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("capability.rail_transit.task_control"))],
)
def task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        result = _application_service(request).get_task(_site_id(request), task_id)
        if result.action not in _ACTIONS:
            raise RailTransitWebError("TASK_NOT_FOUND", "列车在线任务不存在")
        return result
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("capability.rail_transit.task_control"))],
)
def cancel_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    task(request, task_id)
    try:
        return _application_service(request).cancel_task(_site_id(request), task_id)
    except RailTransitWebError as exc:
        _raise_error(exc)


@router.post(
    "/tasks/recover",
    response_model=list[RailTransitTaskDTO],
    dependencies=[Depends(require_feature("capability.rail_transit.task_control"))],
)
def recover_tasks(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return [item for item in _application_service(request).recover_tasks(_site_id(request)) if item.action in _ACTIONS]
    except RailTransitWebError as exc:
        _raise_error(exc)


def _raise_error(exc: RailTransitWebError) -> None:
    status_code = {
        "TASK_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "BLOCKED_ON_TASK_WINDOW": status.HTTP_503_SERVICE_UNAVAILABLE,
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
