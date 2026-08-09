from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.system_maintenance import (
    AboutDTO,
    ChangelogDTO,
    CleanupStartRequest,
    DesktopActionDTO,
    ExternalLinkDTO,
    LogExportRequest,
    LogPageDTO,
    RuntimeLogSummaryDTO,
    MaintenanceTaskDTO,
    OpenSourceExportRequest,
)
from netconsole.application.system_maintenance import SystemMaintenanceApplicationService, SystemMaintenanceError


router = APIRouter(prefix="/system-maintenance", tags=["system-maintenance"])


def _service(request: Request) -> SystemMaintenanceApplicationService:
    return request.app.state.system_maintenance_service


def _site(request: Request) -> str:
    return _service(request).current_site_id()


def _run(call):
    try:
        return call()
    except SystemMaintenanceError as exc:
        code = status.HTTP_409_CONFLICT
        if exc.code in {"TASK_NOT_FOUND", "LINK_NOT_FOUND", "ARTIFACT_INVALID", "SITE_NOT_FOUND"}:
            code = status.HTTP_404_NOT_FOUND
        elif exc.code.endswith("_INVALID") or exc.code == "LINK_NOT_ALLOWED":
            code = status.HTTP_422_UNPROCESSABLE_ENTITY
        elif exc.code in {"CHANGELOG_UNAVAILABLE", "ARTIFACT_RESERVE_FAILED", "EXPORT_START_FAILED"}:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/logs", response_model=LogPageDTO)
def list_logs(
    request: Request,
    page: int = Query(default=1, ge=1, le=1_000_000),
    page_size: int = Query(default=200, ge=50, le=500),
    keyword: str = Query(default="", max_length=200),
    level: Literal["", "INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"] = Query(default=""),
) -> LogPageDTO:
    if page_size not in {50, 100, 200, 500}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="分页大小无效")
    return _run(lambda: _service(request).list_logs(page=page, page_size=page_size, keyword=keyword, level=level))


@router.get("/logs/summary", response_model=RuntimeLogSummaryDTO)
def runtime_log_summary(request: Request) -> RuntimeLogSummaryDTO:
    return _run(lambda: _service(request).runtime_log_summary())


@router.delete("/logs", response_model=DesktopActionDTO)
def clear_logs(request: Request) -> DesktopActionDTO:
    return _run(lambda: _service(request).clear_logs())


@router.post(
    "/cleanup/tasks",
    response_model=MaintenanceTaskDTO,
    dependencies=[Depends(require_feature("system.disk_cleanup"))],
)
def start_cleanup(request: Request, payload: CleanupStartRequest) -> MaintenanceTaskDTO:
    return _run(
        lambda: _service(request).start_cleanup(
            _site(request),
            dry_run=payload.mode == "scan",
            retention_days=payload.retention_days,
            selected_item_ids=payload.selected_item_ids,
            confirmed=payload.confirmed,
            manual_history=payload.mode == "manual_history_cleanup",
        )
    )


@router.post(
    "/open-source/tasks",
    response_model=MaintenanceTaskDTO,
    dependencies=[Depends(require_feature("system.open_source"))],
)
def start_open_source_scan(request: Request) -> MaintenanceTaskDTO:
    return _run(lambda: _service(request).start_open_source_scan(_site(request)))


@router.post(
    "/exports/logs",
    response_model=MaintenanceTaskDTO,
    dependencies=[Depends(require_feature("web.logs_export"))],
)
def start_log_export(request: Request, payload: LogExportRequest) -> MaintenanceTaskDTO:
    return _run(
        lambda: _service(request).start_log_export(
            _site(request),
            scope=payload.scope,
            keyword=payload.keyword,
            level=payload.level,
            page=payload.page,
            page_size=payload.page_size,
        )
    )


@router.post(
    "/exports/open-source",
    response_model=MaintenanceTaskDTO,
    dependencies=[Depends(require_feature("system.open_source"))],
)
def start_open_source_export(request: Request, payload: OpenSourceExportRequest) -> MaintenanceTaskDTO:
    return _run(lambda: _service(request).start_open_source_export(_site(request), format=payload.format))


@router.get("/tasks", response_model=list[MaintenanceTaskDTO])
def recover_tasks(request: Request) -> list[MaintenanceTaskDTO]:
    return _run(lambda: _service(request).recover_tasks(_site(request)))


@router.get("/tasks/{task_id}", response_model=MaintenanceTaskDTO)
def get_task(request: Request, task_id: str) -> MaintenanceTaskDTO:
    return _run(lambda: _service(request).get_task(_site(request), task_id))


@router.post("/tasks/{task_id}/cancel", response_model=MaintenanceTaskDTO)
def cancel_task(request: Request, task_id: str) -> MaintenanceTaskDTO:
    return _run(lambda: _service(request).cancel_task(_site(request), task_id))


@router.get(
    "/changelog",
    response_model=ChangelogDTO,
    dependencies=[Depends(require_feature("system.changelog"))],
)
def changelog(request: Request) -> ChangelogDTO:
    return _run(lambda: _service(request).changelog())


@router.get("/about", response_model=AboutDTO)
def about(request: Request) -> AboutDTO:
    return _service(request).about()


@router.post("/links/about/{link_id}", response_model=ExternalLinkDTO)
def about_link(request: Request, link_id: str) -> ExternalLinkDTO:
    return _run(lambda: _service(request).about_link(link_id))


@router.post("/links/open-source/{task_id}/{component_index}", response_model=ExternalLinkDTO)
def open_source_link(request: Request, task_id: str, component_index: int) -> ExternalLinkDTO:
    return _run(lambda: _service(request).open_source_link(_site(request), task_id, component_index))


@router.post(
    "/desktop-actions/open-directory/{kind}",
    response_model=DesktopActionDTO,
    dependencies=[Depends(require_feature("desktop.native_bridge"))],
)
def open_directory(request: Request, kind: Literal["logs", "cache"]) -> DesktopActionDTO:
    return _run(lambda: _service(request).open_directory(kind))


@router.get("/artifacts/{kind}/{artifact_id}", response_class=FileResponse)
def download_artifact(request: Request, kind: str, artifact_id: str) -> FileResponse:
    path, name = _run(lambda: _service(request).open_artifact(_site(request), kind, artifact_id))
    media_type = "text/plain; charset=utf-8" if kind == "open_source_txt" else None
    return FileResponse(path, filename=name, media_type=media_type)


__all__ = ["router"]
