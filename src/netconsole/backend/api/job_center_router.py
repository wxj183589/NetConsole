from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.application.web_artifacts import WebArtifactError, WebArtifactStore
from netconsole.application.system_maintenance import (
    SYSTEM_MAINTENANCE_TASK_TYPES,
    SYSTEM_MAINTENANCE_WEB_OWNER,
)
from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.models.api.job_center import (
    JobCenterAcknowledgeRequest,
    JobCenterAcknowledgeResultDTO,
    JobCenterCleanupRequest,
    JobCenterCleanupResultDTO,
    JobCenterLogTailDTO,
    JobCenterSummaryDTO,
    JobCenterTaskDTO,
)
from netconsole.services.job_center.query_service import (
    AC_WEB_OWNER,
    RAIL_WEB_OWNER,
    JobCenterQueryService,
)
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.config_collection_web_service import CONFIG_WEB_OWNER, CONFIG_WEB_TASK_TYPES
from netconsole.services.device_management_web_service import DEVICE_TASK_TYPES, WEB_TASK_OWNER
from netconsole.services.file_contract import artifact_media_type
from netconsole.services.command_reference_application_service import (
    COMMAND_REFERENCE_EXPORT_TASK,
    COMMAND_REFERENCE_WEB_OWNER,
)
from netconsole.services.network_tools.job_handlers import (
    NETWORK_TOOLBOX_TASK_TYPES,
    NETWORK_TOOL_OWNER,
    NETWORK_WIRELESS_TASK_TYPES,
)
from netconsole.services.traffic.application_service import TRAFFIC_CONTROLLER_TASK_TYPES
from netconsole.services.job_center.handlers.site_jobs import SITE_STORAGE_OWNER, SITE_STORAGE_TASK_TYPES
from netconsole.services.traffic.errors import TrafficTestError


router = APIRouter(prefix="/job-center", tags=["job-center"])


def _service(request: Request) -> JobCenterQueryService:
    return request.app.state.job_center_query_service


def _artifact_store(request: Request) -> WebArtifactStore:
    return request.app.state.web_artifact_store


def _task_service(request: Request) -> TaskApplicationService:
    return request.app.state.task_service


def _site_id(request: Request) -> str:
    return _service(request).current_site_id()


@router.get("/tasks", response_model=list[JobCenterTaskDTO])
def list_tasks(
    request: Request,
    task_status: list[str] | None = Query(default=None, alias="status"),
    search: str = Query(default="", max_length=200),
    warning_only: bool = False,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[JobCenterTaskDTO]:
    return _query(
        lambda: _service(request).list_tasks(
            _site_id(request),
            statuses=set(task_status or ()),
            search=search,
            warning_only=warning_only,
            limit=limit,
        )
    )


@router.get("/summary", response_model=JobCenterSummaryDTO)
def summary(request: Request) -> JobCenterSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request)))


@router.post("/cleanup", response_model=JobCenterCleanupResultDTO)
def cleanup_tasks(
    request: Request,
    payload: JobCenterCleanupRequest,
) -> JobCenterCleanupResultDTO:
    site_id = _site_id(request)
    if payload.site_id and payload.site_id != site_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务清理范围与当前局点不一致",
        )
    try:
        result = _task_service(request).cleanup_history_tasks(
            payload.cleanup_type,
            site_name=site_id,
            include_states=payload.include_states,
            exclude_states=payload.exclude_states,
            dismissed_by="local-user",
            dry_run=payload.dry_run,
            delete_artifacts=payload.delete_artifacts,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return JobCenterCleanupResultDTO.model_validate(result)


@router.post("/acknowledge", response_model=JobCenterAcknowledgeResultDTO)
def acknowledge_tasks(
    request: Request,
    payload: JobCenterAcknowledgeRequest,
) -> JobCenterAcknowledgeResultDTO:
    if not payload.all_alerts and not payload.task_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="必须指定任务或选择全部失败和告警任务",
        )
    result = _task_service(request).acknowledge_history_tasks(
        site_name=_site_id(request),
        task_ids=payload.task_ids,
        all_alerts=payload.all_alerts,
    )
    return JobCenterAcknowledgeResultDTO.model_validate(result)


@router.get("/tasks/{task_id}", response_model=JobCenterTaskDTO)
def detail(request: Request, task_id: str) -> JobCenterTaskDTO:
    task = _query(lambda: _service(request).get_task(_site_id(request), task_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


@router.post(
    "/tasks/{task_id}/acknowledge",
    response_model=JobCenterAcknowledgeResultDTO,
)
def acknowledge_task(
    request: Request,
    task_id: str,
) -> JobCenterAcknowledgeResultDTO:
    task = _service(request).get_task(_site_id(request), task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    result = _task_service(request).acknowledge_history_tasks(
        site_name=_site_id(request),
        task_ids=[task_id],
    )
    if not result.get("task_ids"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅未处理的失败和告警任务可以标记为已处理",
        )
    return JobCenterAcknowledgeResultDTO.model_validate(result)


@router.post(
    "/tasks/{task_id}/dismiss",
    response_model=JobCenterCleanupResultDTO,
)
def dismiss_task(
    request: Request,
    task_id: str,
) -> JobCenterCleanupResultDTO:
    task = _service(request).get_task(_site_id(request), task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    result = _task_service(request).dismiss_history_task(
        task_id,
        site_name=_site_id(request),
    )
    if result.get("skipped_active"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="运行中、等待中或正在取消的任务不能从任务中心移除",
        )
    if result.get("skipped_unacknowledged"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先将失败或告警任务标记为已处理",
        )
    if not result.get("task_ids"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务已从任务中心移除或当前不可清理",
        )
    return JobCenterCleanupResultDTO.model_validate(result)


@router.get("/tasks/{task_id}/logs", response_model=JobCenterLogTailDTO)
def logs(
    request: Request,
    task_id: str,
    tail: int = Query(default=300, ge=1, le=300),
) -> JobCenterLogTailDTO:
    result = _query(lambda: _service(request).get_logs(_site_id(request), task_id, tail=tail))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return result


@router.get("/artifacts/{artifact_id}")
def download_artifact(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, display_name, _manifest = _artifact_store(request).open_public(
            site_id=_site_id(request),
            artifact_id=artifact_id,
        )
    except WebArtifactError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact 不存在或不可用",
        ) from exc
    return FileResponse(
        path,
        filename=display_name,
        media_type=artifact_media_type(display_name),
    )


@router.post("/tasks/{task_id}/cancel", response_model=JobCenterTaskDTO)
async def cancel(request: Request, task_id: str) -> JobCenterTaskDTO:
    task = _service(request).get_task(_site_id(request), task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if not task.cancellable:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=task.cancel_reason or "任务当前不可停止")
    try:
        if task.owner == WEB_TASK_OWNER and task.type in DEVICE_TASK_TYPES:
            request.app.state.device_management_service.cancel_task(task_id)
        elif task.owner == CONFIG_WEB_OWNER and task.type in CONFIG_WEB_TASK_TYPES:
            request.app.state.config_collection_service.cancel_task(task.site_name, task_id)
        elif task.owner == "web_file_management" and task.type == "file_management_download":
            request.app.state.file_management_service.cancel_download(task.site_name, task_id)
        elif task.owner == "web_file_management" and task.type == "device_sftp_enable":
            if not request.app.state.file_management_service.cancel_sftp_enable_task(task.site_name, task_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SFTP 自动配置任务已结束或不在当前进程")
        elif task.owner == AC_WEB_OWNER:
            request.app.state.ac_web_application_service.cancel_task(task.site_name, task_id)
        elif task.owner == RAIL_WEB_OWNER:
            request.app.state.rail_transit_web_application_service.cancel_task(
                task.site_name, task_id
            )
        elif task.owner == NETWORK_TOOL_OWNER:
            if task.type in NETWORK_TOOLBOX_TASK_TYPES:
                request.app.state.network_tools_service.cancel_network_task(task_id)
            elif task.type in NETWORK_WIRELESS_TASK_TYPES:
                request.app.state.network_tools_service.cancel_wireless_task(task_id)
            else:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="网络任务类型不支持统一停止")
        elif task.owner == COMMAND_REFERENCE_WEB_OWNER and task.type == COMMAND_REFERENCE_EXPORT_TASK:
            request.app.state.command_reference_application_service.cancel_task(task_id)
        elif task.owner == SYSTEM_MAINTENANCE_WEB_OWNER and task.type in SYSTEM_MAINTENANCE_TASK_TYPES:
            request.app.state.system_maintenance_service.cancel_task(task.site_name, task_id)
        elif task.owner == SITE_STORAGE_OWNER and task.type in SITE_STORAGE_TASK_TYPES:
            if not request.app.state.site_process_adapter.cancel_job(task_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="局点存储任务已结束或不在当前进程")
        elif task.owner == "controller" and task.type in TRAFFIC_CONTROLLER_TASK_TYPES:
            await request.app.state.traffic_web_application_service.cancel_controller_task(task_id)
        else:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务 owner 未接入统一停止能力")
    except TrafficTestError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    updated = _service(request).get_task(_site_id(request), task_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if updated.status not in {"STOPPING", "CANCELLED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务 owner 未确认停止请求")
    return updated


def _query(callback):
    with map_api_errors("任务数据库暂时不可读"):
        return callback()


__all__ = ["router"]
