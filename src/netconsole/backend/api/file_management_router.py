from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.core.sites import SiteManager
from netconsole.models.api.file_management import (
    FileDownloadRequestDTO,
    FileDownloadTaskDTO,
    FileManagementStatusDTO,
    ManagedFilePageDTO,
)
from netconsole.services.file_management_service import (
    FileManagementApplicationService,
    FileManagementError,
    FileReferenceNotFound,
)


router = APIRouter(prefix="/file-management", tags=["file-management"])


def _service(request: Request) -> FileManagementApplicationService:
    service = getattr(request.app.state, "file_management_service", None)
    if not isinstance(service, FileManagementApplicationService):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="文件管理 Web 服务未接线")
    return service


def _site_id(request: Request, supplied: str) -> str:
    service = _service(request)
    value = str(supplied or service.current_site_id())
    try:
        return SiteManager(request.app.state.paths).validate_site_name(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="局点标识无效") from exc


def _call(callback):
    try:
        return callback()
    except FileReferenceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileManagementError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="文件索引暂时不可读取") from exc


@router.get("/status", response_model=FileManagementStatusDTO)
def management_status(request: Request, site_id: str = Query(default="", max_length=100)) -> FileManagementStatusDTO:
    return _call(lambda: _service(request).status(_site_id(request, site_id)))


@router.get("/files", response_model=ManagedFilePageDTO)
def list_files(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    category: str = Query(default="", max_length=20),
    search: str = Query(default="", max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
) -> ManagedFilePageDTO:
    return _call(lambda: _service(request).list_files(_site_id(request, site_id), category=category, search=search, limit=limit))


@router.post("/downloads", response_model=FileDownloadTaskDTO, status_code=status.HTTP_202_ACCEPTED)
def start_download(
    request: Request,
    payload: FileDownloadRequestDTO,
    site_id: str = Query(default="", max_length=100),
) -> FileDownloadTaskDTO:
    try:
        return _service(request).submit_download(_site_id(request, site_id), payload.file_ref)
    except FileReferenceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileManagementError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/downloads/{task_id}", response_model=FileDownloadTaskDTO)
def download_task(request: Request, task_id: str, site_id: str = Query(default="", max_length=100)) -> FileDownloadTaskDTO:
    task = _call(lambda: _service(request).download_task(_site_id(request, site_id), task_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="下载任务不存在")
    return task


@router.get("/downloads/{task_id}/file", response_class=FileResponse)
def download_file(request: Request, task_id: str, site_id: str = Query(default="", max_length=100)) -> FileResponse:
    path, name = _call(lambda: _service(request).open_download(_site_id(request, site_id), task_id))
    return FileResponse(path, filename=name)


__all__ = ["router"]
