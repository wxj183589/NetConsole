from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.models.api.job_center import JobCenterLogTailDTO, JobCenterSummaryDTO, JobCenterTaskDTO
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.config_collection_web_service import CONFIG_WEB_OWNER, CONFIG_WEB_TASK_TYPES
from netconsole.services.device_management_web_service import DEVICE_TASK_TYPES, WEB_TASK_OWNER


router = APIRouter(prefix="/job-center", tags=["job-center"])


def _service(request: Request) -> JobCenterQueryService:
    return request.app.state.job_center_query_service


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


@router.get("/tasks/{task_id}", response_model=JobCenterTaskDTO)
def detail(request: Request, task_id: str) -> JobCenterTaskDTO:
    task = _query(lambda: _service(request).get_task(_site_id(request), task_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


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


@router.post("/tasks/{task_id}/cancel", response_model=JobCenterTaskDTO)
def cancel(request: Request, task_id: str) -> JobCenterTaskDTO:
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
        else:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务 owner 未接入统一停止能力")
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
