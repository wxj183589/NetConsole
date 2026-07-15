from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.device_management import (
    DeviceConnectionTestDTO,
    DeviceConnectionTestRequestDTO,
    DeviceDetailDTO,
    DeviceEditPreviewDTO,
    DeviceEditPreviewRequestDTO,
    DevicePageDTO,
)
from netconsole.services.device_management_web_service import DeviceManagementWebService


router = APIRouter(prefix="/device-management", tags=["device-management"])


def _service(request: Request) -> DeviceManagementWebService:
    return request.app.state.device_management_service


@router.get("/devices", response_model=DevicePageDTO)
def list_devices(
    request: Request,
    search: str = Query(default="", max_length=200),
    group_id: int | None = Query(default=None, ge=1),
    ungrouped: bool = False,
    device_type: str = Query(default="", max_length=40),
    vendor: str = Query(default="", max_length=40),
    connection_status: str = Query(default="", pattern="^(|UNKNOWN|TESTING|REACHABLE|UNREACHABLE|ERROR)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="name", pattern="^(name|system_name|primary_address|station|device_type|updated_at|status)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> DevicePageDTO:
    return _query(
        lambda: _service(request).list_devices(
            search=search,
            group_id=group_id,
            ungrouped=ungrouped,
            device_type=device_type,
            vendor=vendor,
            connection_status=connection_status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/devices/{device_uuid}", response_model=DeviceDetailDTO)
def device_detail(request: Request, device_uuid: str) -> DeviceDetailDTO:
    return _not_found(lambda: _service(request).get_device_detail(device_uuid), "设备不存在")


@router.post(
    "/devices/{device_uuid}/edit-preview",
    response_model=DeviceEditPreviewDTO,
    dependencies=[Depends(require_feature("web.device_edit_preview"))],
)
def edit_preview(
    request: Request,
    device_uuid: str,
    payload: DeviceEditPreviewRequestDTO,
) -> DeviceEditPreviewDTO:
    return _not_found(lambda: _service(request).preview_edit(device_uuid, payload), "设备不存在")


@router.post(
    "/devices/{device_uuid}/connection-tests",
    response_model=DeviceConnectionTestDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_connection_test"))],
)
def start_connection_test(
    request: Request,
    device_uuid: str,
    payload: DeviceConnectionTestRequestDTO,
) -> DeviceConnectionTestDTO:
    with map_api_errors(
        "连接测试任务暂时无法创建",
        io_detail="连接测试任务暂时无法创建",
        io_errors=(OSError, RuntimeError),
    ):
        try:
            return _service(request).start_connection_test(device_uuid, payload.protocol)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/connection-tests/{task_id}",
    response_model=DeviceConnectionTestDTO,
    dependencies=[Depends(require_feature("web.device_connection_test"))],
)
def connection_test(request: Request, task_id: str) -> DeviceConnectionTestDTO:
    return _not_found(lambda: _service(request).get_connection_test(task_id), "连接测试任务不存在")


def _not_found(callback, message: str):
    try:
        return _query(callback)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc


def _query(callback):
    with map_api_errors("设备数据库暂时不可读"):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = ["router"]
