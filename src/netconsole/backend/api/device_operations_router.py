from fastapi import APIRouter, Depends, HTTPException, Query, Request

from netconsole.backend.api.feature_access import require_feature
from netconsole.services.command_template_library import (
    CommandTemplateDefinition,
    CommandTemplateLibrary,
    CommandTemplateRevision,
    SavedTemplateParameters,
    SavedTemplatePreview,
    TemplateRevisionConflict,
)
from netconsole.services.device_task_service import (
    DeviceTaskApplicationService,
    DeviceTaskReference,
    DeviceTaskRequest,
    DeviceTaskSchedule,
    upgrade_lab_enabled,
)
from netconsole.services.h3c_command_template import (
    CommandTemplatePreview,
    CommandTemplatePreviewRequest,
    TemplatePreviewError,
    preview_command_template,
)
from netconsole.services.job_center.task_application_service import TaskResourceConflictError


router = APIRouter(prefix="/device-operations", tags=["device-operations"])


def _service(request: Request) -> DeviceTaskApplicationService:
    return request.app.state.device_task_application_service


def _site(request: Request) -> str:
    return request.app.state.device_management_service.current_site_id()


def _library(request: Request) -> CommandTemplateLibrary:
    return _service(request).template_library(_site(request))


def _require_task_kind(request: Request, kind: object) -> None:
    if kind in {"configuration", "backup"}:
        require_feature("capability.config_collection.fetch")(request)
    if kind == "config_diff":
        require_feature("capability.config_collection.diff")(request)
    if kind in {"config_diff", "config_preview", "config_generate"}:
        require_feature("capability.config_collection.export")(request)
    if kind == "health":
        require_feature("capability.devices.collect")(request)


@router.get("/organizations")
def target_organizations(request: Request) -> list[dict[str, str]]:
    require_feature("module.rail_infrastructure")(request)
    return _service(request).organizations(_site(request))


@router.get("/capabilities", dependencies=[Depends(require_feature("module.devices"))])
def device_task_capabilities() -> dict[str, bool]:
    return {"upgrade_lab": upgrade_lab_enabled()}


@router.post("/templates/preview", response_model=CommandTemplatePreview)
def preview_template(payload: CommandTemplatePreviewRequest) -> CommandTemplatePreview:
    try:
        return preview_command_template(payload)
    except TemplatePreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/templates", response_model=list[CommandTemplateRevision])
def list_templates(request: Request) -> list[CommandTemplateRevision]:
    try:
        return _library(request).list()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/templates", response_model=CommandTemplateRevision, status_code=201)
def create_template(request: Request, payload: CommandTemplateDefinition, offline_configuration: bool = False) -> CommandTemplateRevision:
    if offline_configuration:
        _require_task_kind(request, "config_generate")
    try:
        return _library(request).save(payload, offline_configuration=offline_configuration)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/templates/saved-preview", response_model=SavedTemplatePreview)
def preview_saved_template(request: Request, payload: SavedTemplateParameters) -> SavedTemplatePreview:
    try:
        return _library(request).preview(payload)[1]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    except TemplateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/templates/{template_id}/versions", response_model=list[CommandTemplateRevision])
def template_versions(request: Request, template_id: str) -> list[CommandTemplateRevision]:
    try:
        return _library(request).versions(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/templates/{template_id}", response_model=CommandTemplateRevision)
def update_template(
    request: Request, template_id: str, payload: CommandTemplateDefinition,
    expected_version: int = Query(ge=1),
    offline_configuration: bool = False,
) -> CommandTemplateRevision:
    if offline_configuration:
        _require_task_kind(request, "config_generate")
    try:
        return _library(request).save(payload, template_id=template_id, expected_version=expected_version, offline_configuration=offline_configuration)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    except TemplateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tasks", response_model=DeviceTaskReference, status_code=202,
             dependencies=[Depends(require_feature("module.devices"))])
def start_device_task(request: Request, payload: DeviceTaskRequest) -> DeviceTaskReference:
    _require_task_kind(request, payload.kind)
    if payload.organization_uid is not None:
        require_feature("module.rail_infrastructure")(request)
    try:
        return _service(request).start(_site(request), payload)
    except TaskResourceConflictError as exc:
        raise HTTPException(status_code=409, detail="已有设备任务正在处理一个或多个目标") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    except TemplateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/schedules", response_model=list[DeviceTaskSchedule],
            dependencies=[Depends(require_feature("module.devices"))])
def list_device_schedules(request: Request) -> list[DeviceTaskSchedule]:
    return _service(request).list_schedules(_site(request))


@router.delete("/schedules/{task_id}", status_code=204,
               dependencies=[Depends(require_feature("module.devices"))])
def cancel_device_schedule(request: Request, task_id: str) -> None:
    try:
        _service(request).cancel_schedule(_site(request), task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务计划不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/result")
def device_task_result(request: Request, task_id: str) -> dict[str, object]:
    try:
        return _service(request).result(_site(request), task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="设备任务不存在") from exc


@router.post("/tasks/{task_id}/exports", status_code=202)
def export_device_task(request: Request, task_id: str) -> dict[str, str]:
    try:
        return request.app.state.device_task_export_service.start(_site(request), task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="设备任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/retry", response_model=DeviceTaskReference, status_code=202,
             dependencies=[Depends(require_feature("module.devices"))])
def retry_device_task(request: Request, task_id: str) -> DeviceTaskReference:
    service = _service(request)
    site = _site(request)
    try:
        _require_task_kind(request, service.result(site, task_id).get("kind"))
        return service.retry(site, task_id)
    except TaskResourceConflictError as exc:
        raise HTTPException(status_code=409, detail="已有设备任务正在处理一个或多个目标") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="设备任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
