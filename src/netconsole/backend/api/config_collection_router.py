from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.config_collection import (
    ConfigActionRequest,
    ConfigDeviceDiffRequest,
    ConfigDevicePageDTO,
    ConfigSnapshotDiffRequest,
    ConfigSnapshotDTO,
    ConfigTaskReferenceDTO,
    ConfigTaskStatusDTO,
)
from netconsole.services.config_collection_web_service import ConfigCollectionApplicationService


router = APIRouter(prefix="/config-collection", tags=["config-collection"])


def _service(request: Request) -> ConfigCollectionApplicationService:
    service = getattr(request.app.state, "config_collection_service", None)
    if service is None:
        service = ConfigCollectionApplicationService(request.app.state.paths, request.app.state.task_service)
        request.app.state.config_collection_service = service
    return service


def _site_id(request: Request) -> str:
    return _service(request).current_site_id()


@router.get("/devices", response_model=ConfigDevicePageDTO)
def list_devices(
    request: Request,
    search: str = Query(default="", max_length=200),
    group_filter: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ConfigDevicePageDTO:
    return _query(
        lambda: _service(request).list_devices(
            _site_id(request), search=search, group_filter=group_filter, page=page, page_size=page_size
        )
    )


@router.get("/devices/{device_id}/snapshots", response_model=list[ConfigSnapshotDTO])
def list_snapshots(
    request: Request,
    device_id: int,
    snapshot_type: str = Query(default="", alias="type", max_length=20),
) -> list[ConfigSnapshotDTO]:
    return _query(lambda: _service(request).list_snapshots(_site_id(request), device_id, snapshot_type))


@router.post(
    "/actions",
    response_model=list[ConfigTaskReferenceDTO],
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.config_collection_fetch"))],
)
def submit_collection(request: Request, payload: ConfigActionRequest) -> list[ConfigTaskReferenceDTO]:
    return _query(lambda: _service(request).submit_collection(_site_id(request), payload.action, payload.device_ids))


@router.post("/snapshots/{snapshot_id}/content", response_model=ConfigTaskReferenceDTO, status_code=status.HTTP_202_ACCEPTED)
def load_snapshot_content(request: Request, snapshot_id: int) -> ConfigTaskReferenceDTO:
    return _query(lambda: _service(request).submit_snapshot_content(_site_id(request), snapshot_id))


@router.post(
    "/devices/{device_id}/diff/latest",
    response_model=ConfigTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.config_collection_diff"))],
)
def compare_latest_snapshots(request: Request, device_id: int) -> ConfigTaskReferenceDTO:
    return _query(lambda: _service(request).submit_latest_diff(_site_id(request), device_id))


@router.post(
    "/diff/snapshots",
    response_model=ConfigTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.config_collection_diff"))],
)
def compare_snapshot_pair(request: Request, payload: ConfigSnapshotDiffRequest) -> ConfigTaskReferenceDTO:
    return _query(
        lambda: _service(request).submit_snapshot_diff(
            _site_id(request), payload.left_snapshot_id, payload.right_snapshot_id
        )
    )


@router.post(
    "/diff/devices",
    response_model=ConfigTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.config_collection_diff"))],
)
def compare_device_pair(request: Request, payload: ConfigDeviceDiffRequest) -> ConfigTaskReferenceDTO:
    return _query(
        lambda: _service(request).submit_device_diff(
            _site_id(request), payload.left_device_id, payload.right_device_id
        )
    )


@router.get("/tasks", response_model=list[ConfigTaskStatusDTO])
def list_tasks(request: Request, limit: int = Query(default=100, ge=1, le=200)) -> list[ConfigTaskStatusDTO]:
    return _query(lambda: _service(request).list_tasks(_site_id(request), limit))


@router.get("/tasks/{task_id}", response_model=ConfigTaskStatusDTO)
def get_task(request: Request, task_id: str) -> ConfigTaskStatusDTO:
    result = _query(lambda: _service(request).get_task(_site_id(request), task_id))
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置任务不存在")
    return result


@router.get(
    "/artifacts/{artifact_id}",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.config_collection_download"))],
)
def download_artifact(request: Request, artifact_id: str) -> FileResponse:
    path, filename = _query(lambda: _service(request).open_artifact(_site_id(request), artifact_id))
    return FileResponse(path, filename=filename)


def _query(callback):
    try:
        return callback()
    except HTTPException:
        raise
    except (FileNotFoundError, KeyError, UnicodeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "配置资源不存在") from exc
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="配置中心数据库暂时不可读") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="配置中心后台任务暂时不可用") from exc


__all__ = ["router"]
