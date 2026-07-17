from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.backend.api.task_router import task_dto
from netconsole.core import app_logger
from netconsole.models.api.command_reference import (
    CommandReferenceExportRequestDTO,
    CommandReferencePageDTO,
)
from netconsole.models.api.task import TaskCancelResponse, TaskDTO
from netconsole.models.task_state import TaskState
from netconsole.services.command_reference_application_service import (
    CommandReferenceApplicationError,
    CommandReferenceApplicationService,
)


router = APIRouter(prefix="/command-reference", tags=["command-reference"])
T = TypeVar("T")


def _service(request: Request) -> CommandReferenceApplicationService:
    return request.app.state.command_reference_application_service


@router.get("", response_model=CommandReferencePageDTO)
def list_references(
    request: Request,
    query: str = Query(default="", max_length=200),
    module: str = Query(default="", max_length=100),
    device_scope: str = Query(default="", max_length=100),
    vendor: str = Query(default="", max_length=100),
    protocol: str = Query(default="", max_length=100),
    category: str = Query(default="", max_length=100),
    risk_level: str = Query(default="", max_length=50),
) -> CommandReferencePageDTO:
    return _call(
        lambda: _service(request).list_references(
            query=query,
            module=module,
            device_scope=device_scope,
            vendor=vendor,
            protocol=protocol,
            category=category,
            risk_level=risk_level,
        )
    )


@router.post("/exports", response_model=TaskDTO, status_code=status.HTTP_202_ACCEPTED)
def start_export(request: Request, payload: CommandReferenceExportRequestDTO) -> TaskDTO:
    return task_dto(_call(lambda: _service(request).start_export(payload.selected_ids)))


@router.get("/exports/{task_id}", response_model=TaskDTO)
def export_task(request: Request, task_id: str) -> TaskDTO:
    return task_dto(_call(lambda: _service(request).get_task(task_id)))


@router.post("/exports/{task_id}/cancel", response_model=TaskCancelResponse)
def cancel_export(request: Request, task_id: str) -> TaskCancelResponse:
    snapshot = _call(lambda: _service(request).cancel_task(task_id))
    return TaskCancelResponse(id=snapshot.task_id, status=TaskState.STOPPING, message="已请求停止任务")


@router.get("/artifacts/{artifact_id}/download", response_class=FileResponse)
def download_artifact(request: Request, artifact_id: str) -> FileResponse:
    path, name = _call(lambda: _service(request).open_artifact(artifact_id))
    return FileResponse(path, filename=name, media_type="text/markdown; charset=utf-8")


def _call(callback: Callable[[], T]) -> T:
    try:
        return callback()
    except CommandReferenceApplicationError as exc:
        app_logger.log_error("COMMAND_REFERENCE_API_FAILED", f"code={exc.code} type={type(exc).__name__}")
        status_code = {
            "EXPORT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            "ARTIFACT_NOT_AVAILABLE": status.HTTP_404_NOT_FOUND,
            "EXPORT_NOT_CANCELLABLE": status.HTTP_409_CONFLICT,
        }.get(exc.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc
    except (OSError, UnicodeError, ValueError) as exc:
        app_logger.log_error(
            "COMMAND_REFERENCE_RESOURCE_FAILED",
            f"code=COMMAND_REFERENCE_RESOURCE_UNAVAILABLE type={type(exc).__name__}",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "COMMAND_REFERENCE_RESOURCE_UNAVAILABLE", "message": "命令说明资源暂时不可用"},
        ) from exc


__all__ = ["router"]
