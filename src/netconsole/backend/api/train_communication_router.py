from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService, RailTransitWebError
from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import (
    CarNetworkPointPreviewDTO,
    CarNetworkPointTableDTO,
    CarNetworkPointTableExportRequestDTO,
    CarNetworkPointTableTransformRequestDTO,
    CarNetworkPointTableWriteRequestDTO,
    RailTransitTaskDTO,
)
from netconsole.models.api.train_communication import (
    CommunicationPackageDTO,
    CommunicationRawSourceDTO,
    CommunicationTaskDTO,
    MrCommunicationDetailDTO,
    MrCommunicationStatusDTO,
    TrainCommunicationDetailDTO,
    TrainCommunicationPageDTO,
    TrainCommunicationSummaryDTO,
    TrainCommunicationTopologyDTO,
)
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService


router = APIRouter(prefix="/rail-transit/train-communication", tags=["train-communication"])
_POINT_TABLE_ACTIONS = {
    "car_network_generate_point_table",
    "car_network_save_point_table",
    "car_network_point_table_export",
}


def _service(request: Request) -> TrainCommunicationQueryService:
    return request.app.state.train_communication_query_service


def _application_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="轨交应用服务未接线")
    return service


def _site_id(request: Request, supplied: str) -> str:
    value = supplied or _service(request).current_site_id()
    try:
        return SiteManager(request.app.state.paths).validate_site_name(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


@router.get("/summary", response_model=TrainCommunicationSummaryDTO)
def summary(request: Request, site_id: str = Query(default="", max_length=100)) -> TrainCommunicationSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request, site_id)))


@router.get("/trains", response_model=TrainCommunicationPageDTO)
def trains(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    train: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", max_length=20),
    communication_status: str = Query(default="", pattern="^(|normal|warning|critical|stale|unknown)$"),
    mesh_link_status: str = Query(default="", max_length=30),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    line_side: str = Query(default="", max_length=50),
    executor: str = Query(default="", pattern="^(|LOCAL|AGENT)$"),
    data_source: str = Query(default="", max_length=50),
    has_warning: bool | None = None,
    active_only: bool = False,
    agent_only: bool = False,
    optical_anomaly_only: bool = False,
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="train_no", pattern="^(train_no|status|updated_at)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> TrainCommunicationPageDTO:
    return _query(
        lambda: _service(request).list_trains(
            _site_id(request, site_id),
            train=train,
            mr_role=mr_role,
            communication_status=communication_status,
            mesh_link_status=mesh_link_status,
            station=station,
            section=section,
            line_side=line_side,
            executor=executor,
            data_source=data_source,
            has_warning=has_warning,
            active_only=active_only,
            agent_only=agent_only,
            optical_anomaly_only=optical_anomaly_only,
            query=query,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/online", response_model=TrainCommunicationPageDTO)
def online_trains(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> TrainCommunicationPageDTO:
    return _query(
        lambda: _service(request).list_online_trains(
            _site_id(request, site_id),
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/trains/{train_id}/diagnostics",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_car_network_diagnostic_execute")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def start_car_network_diagnostic(request: Request, train_id: str) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_car_network_diagnostic(
            _site_id(request, ""),
            train_id=train_id,
        )
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.get(
    "/diagnostics/{task_id}",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def diagnostic_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        return _application_service(request).get_car_network_diagnostic(_site_id(request, ""), task_id)
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/diagnostics/{task_id}/cancel",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def cancel_car_network_diagnostic(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        return _application_service(request).cancel_car_network_diagnostic(_site_id(request, ""), task_id)
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/diagnostics/recover",
    response_model=list[RailTransitTaskDTO],
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def recover_car_network_diagnostics(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return _application_service(request).recover_car_network_diagnostics(_site_id(request, ""))
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.get(
    "/point-table",
    response_model=CarNetworkPointTableDTO,
    dependencies=[Depends(require_feature("web.train_communication_monitoring"))],
)
def point_table(request: Request) -> CarNetworkPointTableDTO:
    try:
        return _application_service(request).get_car_network_point_table(_site_id(request, ""))
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/import/preview",
    response_model=CarNetworkPointPreviewDTO,
    dependencies=[Depends(require_feature("web.rail_car_network_point_table_write"))],
)
async def preview_point_table_import(
    request: Request,
    file: UploadFile = File(...),
    duplicate_strategy: str = Form(default="replace", pattern="^(replace|skip|error)$"),
) -> CarNetworkPointPreviewDTO:
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        return await asyncio.to_thread(
            _application_service(request).preview_car_network_point_table,
            _site_id(request, ""),
            file_name=file.filename or "point-table.xlsx",
            content=content,
            duplicate_strategy=duplicate_strategy,
        )
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/transform",
    response_model=CarNetworkPointTableDTO,
    dependencies=[Depends(require_feature("web.rail_car_network_point_table_write"))],
)
def transform_point_table(
    request: Request,
    payload: CarNetworkPointTableTransformRequestDTO,
) -> CarNetworkPointTableDTO:
    try:
        return _application_service(request).transform_car_network_point_table(
            _site_id(request, ""),
            operation=payload.operation,
            rows=[row.model_dump() for row in payload.rows],
            global_config=payload.global_config,
        )
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/save",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_car_network_point_table_write")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def save_point_table(
    request: Request,
    payload: CarNetworkPointTableWriteRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_car_network_point_table_save(
            _site_id(request, ""),
            rows=[row.model_dump() for row in payload.rows],
            global_config=payload.global_config,
            overwrite_custom=payload.overwrite_custom,
            explicit_confirmation=payload.explicit_confirmation,
            audit=payload.audit,
            revision=payload.revision,
        )
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/generate",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.rail_car_network_point_table_write")),
        Depends(require_feature("web.rail_task_control")),
    ],
)
def generate_point_table(
    request: Request,
    payload: CarNetworkPointTableWriteRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_car_network_point_table_generate(
            _site_id(request, ""),
            rows=[row.model_dump() for row in payload.rows],
            global_config=payload.global_config,
            target_train=payload.target_train,
        )
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/export",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.rail_car_network_point_table_export"))],
)
def export_point_table(
    request: Request,
    payload: CarNetworkPointTableExportRequestDTO,
) -> RailTransitTaskDTO:
    try:
        return _application_service(request).start_car_network_point_table_export(
            _site_id(request, ""),
            file_format=payload.format,
        )
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.get(
    "/point-table/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.rail_car_network_point_table_export"))],
)
def download_point_table(
    request: Request,
    artifact_id: str,
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
) -> FileResponse:
    try:
        path, name = _application_service(request).open_car_network_point_table_export(
            _site_id(request, ""),
            artifact_id,
            file_format=format,
        )
        return FileResponse(path, filename=name)
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.get(
    "/point-table/tasks/{task_id}",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def point_table_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    try:
        result = _application_service(request).get_task(_site_id(request, ""), task_id)
        if result.action not in _POINT_TABLE_ACTIONS:
            raise RailTransitWebError("TASK_NOT_FOUND", "车内通信点表任务不存在")
        return result
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/tasks/{task_id}/cancel",
    response_model=RailTransitTaskDTO,
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def cancel_point_table_task(request: Request, task_id: str) -> RailTransitTaskDTO:
    point_table_task(request, task_id)
    try:
        return _application_service(request).cancel_task(_site_id(request, ""), task_id)
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.post(
    "/point-table/tasks/recover",
    response_model=list[RailTransitTaskDTO],
    dependencies=[Depends(require_feature("web.rail_task_control"))],
)
def recover_point_table_tasks(request: Request) -> list[RailTransitTaskDTO]:
    try:
        return [
            item
            for item in _application_service(request).recover_tasks(_site_id(request, ""))
            if item.action in _POINT_TABLE_ACTIONS
        ]
    except RailTransitWebError as exc:
        _raise_application_error(exc)


@router.get("/trains/{train_id}", response_model=TrainCommunicationDetailDTO)
def train_detail(
    request: Request,
    train_id: str,
    site_id: str = Query(default="", max_length=100),
) -> TrainCommunicationDetailDTO:
    result = _query(lambda: _service(request).get_train_detail(_site_id(request, site_id), train_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="列车不存在")
    return result


@router.get(
    "/trains/{train_id}/topology",
    response_model=TrainCommunicationTopologyDTO,
    summary="获取列车固定通信拓扑",
    responses={404: {"description": "列车不存在"}},
)
def train_topology(
    request: Request,
    train_id: str,
    site_id: str = Query(default="", max_length=100),
) -> TrainCommunicationTopologyDTO:
    result = _query(lambda: _service(request).get_train_topology(_site_id(request, site_id), train_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="列车不存在")
    return result


@router.get("/mrs/{mr_id}", response_model=MrCommunicationDetailDTO)
def mr_detail(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> MrCommunicationDetailDTO:
    result = _query(lambda: _service(request).get_mr_detail(_site_id(request, site_id), mr_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车载 MR 不存在")
    return result


@router.get("/mrs/{mr_id}/preview", response_model=MrCommunicationStatusDTO)
def mr_preview(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> MrCommunicationStatusDTO:
    result = _query(lambda: _service(request).get_communication_preview(_site_id(request, site_id), mr_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="车载 MR 不存在")
    return result


@router.get("/mrs/{mr_id}/raw-sources", response_model=list[CommunicationRawSourceDTO])
def raw_sources(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> list[CommunicationRawSourceDTO]:
    return _query(lambda: _service(request).get_raw_sources(_site_id(request, site_id), mr_id))


@router.get("/mrs/{mr_id}/tasks", response_model=list[CommunicationTaskDTO])
def related_tasks(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> list[CommunicationTaskDTO]:
    return _query(lambda: _service(request).get_related_tasks(_site_id(request, site_id), mr_id))


@router.get("/mrs/{mr_id}/packages", response_model=list[CommunicationPackageDTO])
def related_packages(
    request: Request,
    mr_id: str,
    site_id: str = Query(default="", max_length=100),
) -> list[CommunicationPackageDTO]:
    return _query(lambda: _service(request).get_related_packages(_site_id(request, site_id), mr_id))


def _query(callback):
    with map_api_errors("车内通信数据暂时不可读"):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _raise_application_error(exc: RailTransitWebError) -> None:
    status_code = {
        "TASK_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "BLOCKED_ON_TASK_WINDOW": status.HTTP_503_SERVICE_UNAVAILABLE,
        "TRAIN_COMMUNICATION_REVISION_CONFLICT": status.HTTP_409_CONFLICT,
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
