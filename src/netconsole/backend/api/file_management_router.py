from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.backend.api.feature_access import require_feature
from netconsole.core.sites import SiteManager
from netconsole.models.api.file_management import (
    DeviceFileConnectionRequestDTO,
    FileConnectionDTO,
    FileDesktopActionDTO,
    FileDesktopActionRequestDTO,
    FileDownloadBatchDTO,
    FileDownloadBatchRequestDTO,
    FileDownloadClearDTO,
    FileDownloadClearRequestDTO,
    FileDownloadRequestDTO,
    FileDownloadTaskDTO,
    FileManagementStatusDTO,
    FileRemoteDeviceDTO,
    LocalDirectoryCreateRequestDTO,
    LocalFilePageDTO,
    ManagedFilePageDTO,
    RemoteFilePageDTO,
)
from netconsole.services.file_management_service import (
    FileManagementApplicationService,
    FileManagementError,
    FileReferenceNotFound,
)
from netconsole.services.file_contract import artifact_media_type


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
    with map_api_errors("文件索引暂时不可读取"):
        try:
            return callback()
        except FileReferenceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except FileManagementError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/status", response_model=FileManagementStatusDTO)
def management_status(request: Request, site_id: str = Query(default="", max_length=100)) -> FileManagementStatusDTO:
    return _call(lambda: _service(request).status(_site_id(request, site_id)))


@router.get("/local/entries", response_model=LocalFilePageDTO)
def list_local_entries(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    directory_id: str = Query(default="", max_length=80),
    device_id: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
) -> LocalFilePageDTO:
    return _call(
        lambda: _service(request).list_local_files(
            _site_id(request, site_id),
            directory_id=directory_id,
            device_id=device_id,
            page=page,
            limit=limit,
        )
    )


@router.post(
    "/local/directories",
    response_model=LocalFilePageDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("web.file_management_local_write"))],
)
def create_local_directory(
    request: Request,
    payload: LocalDirectoryCreateRequestDTO,
    site_id: str = Query(default="", max_length=100),
) -> LocalFilePageDTO:
    return _call(
        lambda: _service(request).create_local_directory(
            _site_id(request, site_id),
            directory_id=payload.directory_id,
            device_id=payload.device_id,
            name=payload.name,
        )
    )


@router.get("/local/entries/{entry_id}/file", response_class=FileResponse)
def open_local_file(request: Request, entry_id: str, site_id: str = Query(default="", max_length=100)) -> FileResponse:
    path, name = _call(lambda: _service(request).open_local_file(_site_id(request, site_id), entry_id))
    return FileResponse(path, filename=name)


@router.get(
    "/devices",
    response_model=list[FileRemoteDeviceDTO],
    dependencies=[Depends(require_feature("web.file_management_remote"))],
)
def list_remote_devices(request: Request, site_id: str = Query(default="", max_length=100)) -> list[FileRemoteDeviceDTO]:
    return _call(lambda: _service(request).list_remote_devices(_site_id(request, site_id)))


@router.post(
    "/connections",
    response_model=FileConnectionDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("web.file_management_remote"))],
)
def connect_device(request: Request, payload: DeviceFileConnectionRequestDTO, site_id: str = Query(default="", max_length=100)) -> FileConnectionDTO:
    return _remote_call(
        lambda: _service(request).connect_device(
            _site_id(request, site_id),
            payload.device_id,
            allow_sftp_setup=payload.allow_sftp_setup,
        )
    )


@router.delete(
    "/connections/{connection_id}",
    response_model=FileConnectionDTO,
    dependencies=[Depends(require_feature("web.file_management_remote"))],
)
def disconnect_device(request: Request, connection_id: str, site_id: str = Query(default="", max_length=100)) -> FileConnectionDTO:
    return _remote_call(lambda: _service(request).disconnect_device(_site_id(request, site_id), connection_id))


@router.get(
    "/connections/{connection_id}/entries",
    response_model=RemoteFilePageDTO,
    dependencies=[Depends(require_feature("web.file_management_remote"))],
)
def list_remote_entries(
    request: Request,
    connection_id: str,
    entry_id: str = Query(default="", max_length=80),
    site_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
) -> RemoteFilePageDTO:
    return _remote_call(
        lambda: _service(request).list_remote_files(
            _site_id(request, site_id),
            connection_id,
            entry_id,
            page=page,
            limit=limit,
        )
    )


@router.get("/files", response_model=ManagedFilePageDTO)
def list_files(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    category: str = Query(default="", max_length=20),
    search: str = Query(default="", max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
) -> ManagedFilePageDTO:
    return _call(lambda: _service(request).list_files(_site_id(request, site_id), category=category, search=search, limit=limit))


@router.post(
    "/downloads",
    response_model=FileDownloadTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def start_download(
    request: Request,
    payload: FileDownloadRequestDTO,
    site_id: str = Query(default="", max_length=100),
) -> FileDownloadTaskDTO:
    if payload.connection_id or payload.remote_entry_id:
        require_feature("web.file_management_remote")(request)
    try:
        return _service(request).submit_download(
            _site_id(request, site_id),
            payload.file_ref,
            connection_id=payload.connection_id,
            remote_entry_id=payload.remote_entry_id,
            local_directory_id=payload.local_directory_id,
        )
    except FileReferenceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileManagementError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post(
    "/downloads/batch",
    response_model=FileDownloadBatchDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.file_management_download")),
        Depends(require_feature("web.file_management_remote")),
    ],
)
def start_download_batch(
    request: Request,
    payload: FileDownloadBatchRequestDTO,
    site_id: str = Query(default="", max_length=100),
) -> FileDownloadBatchDTO:
    return _remote_call(
        lambda: _service(request).submit_download_batch(
            _site_id(request, site_id),
            payload.connection_id,
            payload.remote_entry_ids,
            local_directory_id=payload.local_directory_id,
        )
    )


@router.get(
    "/downloads/{task_id}",
    response_model=FileDownloadTaskDTO,
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def download_task(request: Request, task_id: str, site_id: str = Query(default="", max_length=100)) -> FileDownloadTaskDTO:
    task = _call(lambda: _service(request).download_task(_site_id(request, site_id), task_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="下载任务不存在")
    return task


@router.get(
    "/downloads",
    response_model=list[FileDownloadTaskDTO],
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def list_downloads(
    request: Request,
    site_id: str = Query(default="", max_length=100),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[FileDownloadTaskDTO]:
    return _call(lambda: _service(request).list_download_tasks(_site_id(request, site_id), limit))


@router.post(
    "/downloads/{task_id}/cancel",
    response_model=FileDownloadTaskDTO,
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def cancel_download(request: Request, task_id: str, site_id: str = Query(default="", max_length=100)) -> FileDownloadTaskDTO:
    return _call(lambda: _service(request).cancel_download(_site_id(request, site_id), task_id))


@router.post(
    "/downloads/{task_id}/retry",
    response_model=FileDownloadTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def retry_download(request: Request, task_id: str, site_id: str = Query(default="", max_length=100)) -> FileDownloadTaskDTO:
    return _remote_call(lambda: _service(request).retry_download(_site_id(request, site_id), task_id))


@router.post(
    "/downloads/clear",
    response_model=FileDownloadClearDTO,
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def clear_downloads(
    request: Request,
    payload: FileDownloadClearRequestDTO,
    site_id: str = Query(default="", max_length=100),
) -> FileDownloadClearDTO:
    return _call(lambda: _service(request).clear_downloads(_site_id(request, site_id), payload.statuses))


@router.get(
    "/downloads/{task_id}/file",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.file_management_download"))],
)
def download_file(request: Request, task_id: str, site_id: str = Query(default="", max_length=100)) -> FileResponse:
    path, name = _call(lambda: _service(request).open_download(_site_id(request, site_id), task_id))
    return FileResponse(path, filename=name, media_type=artifact_media_type(name))


@router.post(
    "/desktop-actions/{action}",
    response_model=FileDesktopActionDTO,
    dependencies=[Depends(require_feature("web.file_management_desktop_actions"))],
)
def prepare_desktop_action(
    request: Request,
    action: str,
    payload: FileDesktopActionRequestDTO,
    site_id: str = Query(default="", max_length=100),
) -> FileDesktopActionDTO:
    return _call(
        lambda: _service(request).desktop_action(
            action,
            site_id=_site_id(request, site_id),
            device_id=payload.device_id,
            local_entry_id=payload.local_entry_id,
            task_id=payload.task_id,
        )
    )


def _remote_call(callback):
    try:
        return _call(callback)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


__all__ = ["router"]
