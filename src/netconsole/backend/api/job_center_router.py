from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.models.api.job_center import JobCenterLogTailDTO, JobCenterSummaryDTO, JobCenterTaskDTO
from netconsole.services.job_center.query_service import JobCenterQueryService


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


def _query(callback):
    with map_api_errors("任务数据库暂时不可读"):
        return callback()


__all__ = ["router"]
