from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.backend.api.feature_access import require_feature
from netconsole.backend.api.traffic_presentation import execution_target_from_request, traffic_run_dto
from netconsole.models.api.network_tools import (
    NetworkExportRequest,
    NetworkTaskResultPageResponse,
    NetworkTaskResponse,
    NetworkTaskStartRequest,
    NetworkToolArtifactResponse,
    SubnetSplitRequest,
    TcpPortTestStartRequest,
    ToolboxTextRequest,
    VlsmRequest,
    WirelessExportRequest,
    WirelessProjectRequest,
    WirelessScanPageResponse,
    WirelessScanRunDetailResponse,
    WirelessScanStartRequest,
)
from netconsole.models.api.task import TaskDTO
from netconsole.models.api.traffic import TrafficStartResponse
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import TcpPortTestConfig
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService


router = APIRouter(prefix="/network-tools", tags=["network-tools"])


def network_tools_service(request: Request) -> NetworkToolsApplicationService:
    service = getattr(request.app.state, "network_tools_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="网络工具 Web 服务未接线")
    return service


@router.post(
    "/tcp-port-test",
    response_model=TrafficStartResponse,
    status_code=202,
    dependencies=[Depends(require_feature("web.network_tools_tcp_port_test"))],
)
async def start_tcp_port_test(body: TcpPortTestStartRequest, request: Request) -> TrafficStartResponse:
    run = await network_tools_service(request).start_tcp_port_test(
        TcpPortTestConfig(
            target=body.target,
            port=body.port,
            interval_ms=body.interval_ms,
            timeout_ms=body.timeout_ms,
            count=body.count,
        ),
        execution_target_from_request(body.execution_target),
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


@router.post("/toolbox/ipv4", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def calculate_ipv4(body: ToolboxTextRequest, request: Request) -> dict[str, object]:
    return _call_calculation(lambda: network_tools_service(request).calculate_ipv4(body.text))


@router.post("/toolbox/ipv6", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def calculate_ipv6(body: ToolboxTextRequest, request: Request) -> dict[str, object]:
    return _call_calculation(lambda: network_tools_service(request).calculate_ipv6(body.text))


@router.post("/toolbox/vlsm", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def calculate_vlsm(body: VlsmRequest, request: Request) -> dict[str, object]:
    return _call_calculation(lambda: network_tools_service(request).plan_vlsm(body.parent, body.requests))


@router.post("/toolbox/subnets", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def calculate_subnets(body: SubnetSplitRequest, request: Request) -> dict[str, object]:
    return _call_calculation(lambda: network_tools_service(request).split_subnets(body.parent, body.target_prefix, body.page, body.page_size))


@router.post("/toolbox/summarize", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def summarize_routes(body: ToolboxTextRequest, request: Request) -> dict[str, object]:
    return _call_calculation(lambda: network_tools_service(request).summarize_routes(body.text))


@router.post("/toolbox/wildcard", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def calculate_wildcard(body: ToolboxTextRequest, request: Request) -> dict[str, object]:
    return _call_calculation(lambda: network_tools_service(request).wildcard_calculate(body.text))


@router.post("/tasks", response_model=NetworkTaskResponse, status_code=202, dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
async def start_network_task(body: NetworkTaskStartRequest, request: Request) -> NetworkTaskResponse:
    try:
        task = await network_tools_service(request).start_network_task(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return NetworkTaskResponse(task=network_task_dto(task))


@router.get("/runs", response_model=list[TaskDTO], dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def list_network_tasks(request: Request, offset: int = 0, limit: int = 100) -> list[TaskDTO]:
    return [network_task_dto(task) for task in network_tools_service(request).list_network_tasks(offset=offset, limit=limit)]


@router.get("/runs/{task_id}", response_model=TaskDTO, dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def get_network_task(task_id: str, request: Request) -> TaskDTO:
    task = network_tools_service(request).get_network_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网络工具任务不存在")
    return network_task_dto(task)


@router.get("/runs/{task_id}/events", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def get_network_task_events(task_id: str, request: Request, after_sequence: int = 0, limit: int = 500) -> list[dict[str, object]]:
    if network_tools_service(request).get_network_task(task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网络工具任务不存在")
    return [
        {**event, "payload": _safe_task_event_payload(event.get("payload"))}
        for event in network_tools_service(request).list_network_task_events(task_id, after_sequence=after_sequence, limit=limit)
    ]


@router.post("/runs/{task_id}/cancel", response_model=TaskDTO, dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def cancel_network_task(task_id: str, request: Request) -> TaskDTO:
    try:
        return network_task_dto(network_tools_service(request).cancel_network_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网络工具任务不存在") from exc


@router.get("/runs/{task_id}/results", response_model=NetworkTaskResultPageResponse, dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def list_network_task_results(task_id: str, request: Request, offset: int = 0, limit: int = 100) -> NetworkTaskResultPageResponse:
    try:
        result = network_tools_service(request).list_network_task_results(task_id, offset=offset, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网络探测任务不存在") from exc
    return NetworkTaskResultPageResponse(**result)


@router.post("/runs/{task_id}/export", response_model=NetworkTaskResponse, status_code=202, dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
async def export_network_task(task_id: str, body: NetworkExportRequest, request: Request) -> NetworkTaskResponse:
    try:
        task = await network_tools_service(request).export_network_task(task_id, body.format, body.filename)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网络工具任务不存在或没有结果") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return NetworkTaskResponse(task=network_task_dto(task))


@router.get("/runs/{task_id}/artifact", response_model=NetworkToolArtifactResponse, dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def get_network_export_artifact(task_id: str, request: Request) -> NetworkToolArtifactResponse:
    try:
        return NetworkToolArtifactResponse(**network_tools_service(request).get_network_export_artifact(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网络工具导出 Artifact 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}", dependencies=[Depends(require_feature("web.network_tools_toolbox"))])
def download_network_artifact(artifact_id: str, request: Request) -> FileResponse:
    try:
        path, filename, _metadata = network_tools_service(request).open_network_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导出文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return FileResponse(path, filename=filename)


@router.get("/wireless-scan/adapters", dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def list_wireless_adapters(request: Request) -> list[dict[str, object]]:
    return network_tools_service(request).list_wireless_adapters()


@router.get("/wireless-scan/projects", dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def list_wireless_projects(request: Request) -> list[dict[str, object]]:
    return network_tools_service(request).list_wireless_projects()


@router.post("/wireless-scan/projects", dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def create_wireless_project(body: WirelessProjectRequest, request: Request) -> dict[str, object]:
    try:
        return network_tools_service(request).create_wireless_project(body.name, body.description)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/wireless-scan/projects/{project_id}", dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def delete_wireless_project(project_id: str, request: Request) -> dict[str, object]:
    try:
        network_tools_service(request).delete_wireless_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描项目不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"project_id": project_id, "deleted": True}


@router.post("/wireless-scan/tasks", response_model=NetworkTaskResponse, status_code=202, dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
async def start_wireless_scan(body: WirelessScanStartRequest, request: Request) -> NetworkTaskResponse:
    try:
        task = await network_tools_service(request).start_wireless_scan(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return NetworkTaskResponse(task=network_task_dto(task))


@router.get("/wireless-scan/tasks", response_model=list[TaskDTO], dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def list_wireless_tasks(request: Request, offset: int = 0, limit: int = 100) -> list[TaskDTO]:
    return [network_task_dto(task) for task in network_tools_service(request).list_wireless_tasks(offset=offset, limit=limit)]


@router.get("/wireless-scan/tasks/{task_id}", response_model=TaskDTO, dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def get_wireless_task(task_id: str, request: Request) -> TaskDTO:
    task = network_tools_service(request).get_wireless_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描任务不存在")
    return network_task_dto(task)


@router.get("/wireless-scan/tasks/{task_id}/events", dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def get_wireless_task_events(task_id: str, request: Request, after_sequence: int = 0, limit: int = 500) -> list[dict[str, object]]:
    if network_tools_service(request).get_wireless_task(task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描任务不存在")
    return [
        {**event, "payload": _safe_task_event_payload(event.get("payload"))}
        for event in network_tools_service(request).list_wireless_task_events(
            task_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    ]


@router.post("/wireless-scan/tasks/{task_id}/cancel", response_model=TaskDTO, dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def cancel_wireless_task(task_id: str, request: Request) -> TaskDTO:
    try:
        return network_task_dto(network_tools_service(request).cancel_wireless_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描任务不存在") from exc


@router.get(
    "/wireless-scan/runs",
    response_model=WirelessScanPageResponse,
    dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))],
)
def list_wireless_runs(
    request: Request,
    page: int = Query(default=1, ge=1, le=1_000_000),
    page_size: int = Query(default=100, ge=1, le=500),
) -> WirelessScanPageResponse:
    return WirelessScanPageResponse(**network_tools_service(request).list_wireless_runs(page=page, page_size=page_size))


@router.get(
    "/wireless-scan/runs/{scan_id}/results",
    response_model=WirelessScanPageResponse,
    dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))],
)
def list_wireless_results(
    scan_id: str,
    request: Request,
    page: int = Query(default=1, ge=1, le=1_000_000),
    page_size: int = Query(default=100, ge=1, le=500),
) -> WirelessScanPageResponse:
    try:
        return WirelessScanPageResponse(
            **network_tools_service(request).list_wireless_results(
                scan_id,
                page=page,
                page_size=page_size,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描结果不存在") from exc


@router.get(
    "/wireless-scan/runs/{scan_id}",
    response_model=WirelessScanRunDetailResponse,
    dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))],
)
def get_wireless_run_detail(scan_id: str, request: Request) -> WirelessScanRunDetailResponse:
    try:
        return WirelessScanRunDetailResponse(**network_tools_service(request).get_wireless_run_detail(scan_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描记录不存在") from exc


@router.post("/wireless-scan/export", response_model=NetworkTaskResponse, status_code=202, dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
async def export_wireless_scan(body: WirelessExportRequest, request: Request) -> NetworkTaskResponse:
    try:
        task = await network_tools_service(request).export_wireless_scan(body.scan_id, body.format, body.filename)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描结果不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return NetworkTaskResponse(task=network_task_dto(task))


@router.get("/wireless-scan/tasks/{task_id}/artifact", response_model=NetworkToolArtifactResponse, dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def get_wireless_export_artifact(task_id: str, request: Request) -> NetworkToolArtifactResponse:
    try:
        return NetworkToolArtifactResponse(**network_tools_service(request).get_wireless_export_artifact(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描导出 Artifact 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/wireless-scan/artifacts/{artifact_id}", dependencies=[Depends(require_feature("web.network_tools_wireless_scan"))])
def download_wireless_artifact(artifact_id: str, request: Request) -> FileResponse:
    try:
        path, filename, _metadata = network_tools_service(request).open_wireless_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="无线扫描导出文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return FileResponse(path, filename=filename)


def network_task_dto(snapshot: TaskSnapshot) -> TaskDTO:
    return TaskDTO(
        id=snapshot.task_id,
        type=snapshot.task_type,
        name=snapshot.task_name,
        status=snapshot.status,
        progress=snapshot.progress,
        stage=snapshot.stage,
        current=snapshot.current,
        total=snapshot.total,
        message=snapshot.message,
        created_time=snapshot.created_time,
        started_time=snapshot.started_time,
        finished_time=snapshot.finished_time,
        updated_time=snapshot.updated_time,
        owner=snapshot.owner,
        device=snapshot.device,
        agent=snapshot.agent,
        result_path="",
        error_message=snapshot.error_message,
        result=_safe_task_result(snapshot.result),
        source=snapshot.source,
        cancellable=snapshot.status in {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING},
    )


def _safe_task_result(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        return {}
    safe: dict[str, object] = {}
    row_count = result.get("row_count")
    if isinstance(row_count, int) and not isinstance(row_count, bool):
        safe["row_count"] = row_count
    for key in ("result_id",):
        value = result.get(key)
        if isinstance(value, str) and value:
            safe[key] = value
    return safe


def _safe_task_event_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    safe = {
        key: payload[key]
        for key in ("state", "stage", "message", "error", "current", "total")
        if key in payload and isinstance(payload[key], (str, int, float, bool))
    }
    if "result" in payload:
        safe["result"] = _safe_task_result(payload["result"])
    return safe


def _table_response(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return {"rows": [], "summary": result, "errors": []}
    return {"rows": result.rows, "summary": result.summary, "errors": result.errors}


def _call_calculation(callback: Callable[[], object]) -> dict[str, object]:
    try:
        return _table_response(callback())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = ["router"]
