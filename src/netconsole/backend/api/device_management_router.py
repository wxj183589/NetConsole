from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from netconsole.application.device_detail import DeviceDetailApplicationService
from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.device_management import (
    DeviceConnectionTestDTO,
    DeviceCredentialRevealDTO,
    DeviceSecretField,
    DeviceConnectionTestRequestDTO,
    DeviceBatchConnectionRequestDTO,
    DeviceBatchRefreshRequestDTO,
    DeviceDeleteDTO,
    DeviceDeleteRequestDTO,
    DeviceDeletionTokenDTO,
    DeviceDetailDTO,
    DeviceEditProfileDTO,
    DeviceDeletionTokenRequestDTO,
    DeviceExternalTerminalActionDTO,
    DeviceExternalTerminalBatchDTO,
    DeviceExternalTerminalBatchRequestDTO,
    DeviceExternalTerminalConfirmationDTO,
    DeviceExternalTerminalConfirmationRequestDTO,
    DeviceExternalTerminalRequestDTO,
    DeviceExternalTerminalSettingsDTO,
    DeviceExternalTerminalSettingsUpdateDTO,
    DeviceExportRequestDTO,
    DeviceFormConnectionTestRequestDTO,
    DeviceGroupAssignmentDTO,
    DeviceGroupAssignmentRequestDTO,
    DeviceGroupDeleteDTO,
    DeviceGroupDTO,
    DeviceGroupRequestDTO,
    DeviceLifecycleUpdateDTO,
    DeviceLifecycleUpdateRequestDTO,
    DeviceImportConfirmRequestDTO,
    DeviceImportPreviewDTO,
    DevicePageDTO,
    DeviceSecureCrtExportRequestDTO,
    DeviceTaskBatchDTO,
    DeviceTaskReferenceDTO,
    DeviceWriteDTO,
    DeviceWriteRequestDTO,
)
from netconsole.models.api.device_detail import (
    DeviceBusinessAssociationPageDTO,
    DeviceConfigSnapshotPageDTO,
    DeviceDetailTaskPageDTO,
    DeviceHistoryPageDTO,
    DeviceInterfaceDetailDTO,
    DeviceInterfacePageDTO,
    DeviceLldpPageDTO,
    DeviceOverviewDTO,
    DeviceRefreshRequestDTO,
    DeviceRefreshTaskDTO,
    DeviceTransceiverPageDTO,
)
from netconsole.models.device_address import DeviceAddressError
from netconsole.services.device_management_web_service import DeviceManagementWebService
from netconsole.services.device_connection_preflight import (
    DeviceConnectionPreflightError,
)
from netconsole.backend.api.online_mr_control_router import (
    require_local_desktop_session,
)
from netconsole.services.file_contract import artifact_media_type


router = APIRouter(
    prefix="/device-management",
    tags=["device-management"],
    dependencies=[Depends(require_feature("web.device_management"))],
)


def _service(request: Request) -> DeviceManagementWebService:
    return request.app.state.device_management_service


def _detail_service(request: Request) -> DeviceDetailApplicationService:
    return request.app.state.device_detail_application_service


_DEVICE_DETAIL_ERROR_RESPONSES = {
    404: {"description": "设备或详情对象不存在"},
    422: {"description": "筛选参数或受控设备操作无效"},
    503: {"description": "设备详情数据源暂时不可读"},
}


@router.get("/devices", response_model=DevicePageDTO)
def list_devices(
    request: Request,
    search: str = Query(default="", max_length=200),
    group_id: int | None = Query(default=None, ge=1),
    ungrouped: bool = False,
    device_type: str = Query(default="", max_length=40),
    vendor: str = Query(default="", max_length=40),
    connection_status: str = Query(
        default="",
        pattern="^(|UNKNOWN|TESTING|REACHABLE|UNREACHABLE|AUTH_FAILED|ERROR)$",
    ),
    project_phase: str = Query(
        default="all",
        pattern="^(all|phase_1|phase_2|phase_3|other|unspecified)$",
    ),
    operation_status: str = Query(
        default="in_service",
        pattern="^(all|in_service|not_integrated|commissioning|suspended|retired)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(
        default="name",
        pattern="^(name|system_name|primary_address|station|device_type|updated_at|metadata_updated_at|last_collected_at|last_collect_status|status)$",
    ),
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
            project_phase=project_phase,
            operation_status=operation_status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/groups", response_model=list[DeviceGroupDTO])
def list_groups(request: Request) -> list[DeviceGroupDTO]:
    return _query(lambda: _service(request).list_groups())


@router.post(
    "/groups",
    response_model=DeviceGroupDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def create_group(request: Request, payload: DeviceGroupRequestDTO) -> DeviceGroupDTO:
    return _query(lambda: _service(request).create_group(payload))


@router.patch(
    "/groups/{group_id}",
    response_model=DeviceGroupDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def rename_group(
    request: Request, group_id: int, payload: DeviceGroupRequestDTO
) -> DeviceGroupDTO:
    return _not_found(
        lambda: _service(request).rename_group(group_id, payload), "设备分组不存在"
    )


@router.delete(
    "/groups/{group_id}",
    response_model=DeviceGroupDeleteDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def delete_group(request: Request, group_id: int) -> DeviceGroupDeleteDTO:
    return _not_found(
        lambda: _service(request).delete_group(group_id), "设备分组不存在"
    )


@router.post(
    "/groups/assign",
    response_model=DeviceGroupAssignmentDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def assign_group(
    request: Request, payload: DeviceGroupAssignmentRequestDTO
) -> DeviceGroupAssignmentDTO:
    return _query(lambda: _service(request).assign_group(payload))


@router.patch(
    "/devices/lifecycle",
    response_model=DeviceLifecycleUpdateDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def update_lifecycle(
    request: Request, payload: DeviceLifecycleUpdateRequestDTO
) -> DeviceLifecycleUpdateDTO:
    return _query(lambda: _service(request).update_lifecycle(payload))


@router.post(
    "/devices",
    response_model=DeviceWriteDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def create_device(request: Request, payload: DeviceWriteRequestDTO) -> DeviceWriteDTO:
    return _query(lambda: _service(request).create_device(payload))


@router.put(
    "/devices/{device_uuid}",
    response_model=DeviceWriteDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def update_device(
    request: Request, device_uuid: str, payload: DeviceWriteRequestDTO
) -> DeviceWriteDTO:
    return _not_found(
        lambda: _service(request).update_device(device_uuid, payload), "设备不存在"
    )


@router.post(
    "/devices/{device_uuid}/duplicate",
    response_model=DeviceWriteDTO,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def duplicate_device(request: Request, device_uuid: str) -> DeviceWriteDTO:
    return _not_found(
        lambda: _service(request).duplicate_device(device_uuid), "设备不存在"
    )


@router.post(
    "/devices/delete-confirmation",
    response_model=DeviceDeletionTokenDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def issue_delete_token(request: Request, payload: DeviceDeletionTokenRequestDTO):
    return _not_found(
        lambda: _service(request).issue_delete_token(payload), "设备不存在"
    )


@router.post(
    "/devices/batch-delete",
    response_model=DeviceDeleteDTO,
    dependencies=[Depends(require_feature("web.device_management_write"))],
)
def delete_devices(request: Request, payload: DeviceDeleteRequestDTO):
    return _query(lambda: _service(request).delete_devices(payload))


@router.post(
    "/devices/batch-refresh-details",
    response_model=DeviceTaskBatchDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def batch_refresh_details(
    request: Request, payload: DeviceBatchRefreshRequestDTO
) -> DeviceTaskBatchDTO:
    return _query(lambda: _service(request).start_batch_refresh(payload))


@router.get(
    "/batch-refreshes/{batch_id}",
    response_model=DeviceTaskBatchDTO,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def get_batch_refresh(request: Request, batch_id: str) -> DeviceTaskBatchDTO:
    return _not_found(
        lambda: _service(request).get_batch_refresh(batch_id),
        "批量更新记录不存在",
    )


@router.post(
    "/devices/batch-connection-tests",
    response_model=DeviceTaskBatchDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_connection_test"))],
)
def batch_connection_tests(
    request: Request, payload: DeviceBatchConnectionRequestDTO
) -> DeviceTaskBatchDTO:
    return _query(lambda: _service(request).start_batch_connection_tests(payload))


@router.post(
    "/devices/{device_uuid}/refresh-optical",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def refresh_optical(request: Request, device_uuid: str) -> DeviceTaskReferenceDTO:
    return _not_found(
        lambda: _service(request).start_optical_refresh(device_uuid),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/overview",
    response_model=DeviceOverviewDTO,
    summary="读取设备快速概览",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_overview(request: Request, device_uuid: str) -> DeviceOverviewDTO:
    return _not_found(
        lambda: _detail_service(request).overview(device_uuid), "设备不存在"
    )


@router.get(
    "/devices/{device_uuid}/interfaces",
    response_model=DeviceInterfacePageDTO,
    summary="分页读取设备接口快照",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_interfaces(
    request: Request,
    device_uuid: str,
    search: str = Query(default="", max_length=200),
    status_filter: str = Query(default="", alias="status", max_length=40),
    interface_type: str = Query(default="", max_length=40),
    admin_status: str = Query(default="", max_length=40),
    physical_status: str = Query(default="", max_length=40),
    protocol_status: str = Query(default="", max_length=40),
    media_type: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceInterfacePageDTO:
    return _not_found(
        lambda: _detail_service(request).interfaces(
            device_uuid,
            search=search,
            status=status_filter,
            interface_type=interface_type,
            admin_status=admin_status,
            physical_status=physical_status,
            protocol_status=protocol_status,
            media_type=media_type,
            page=page,
            page_size=page_size,
        ),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/interfaces/{interface_name:path}",
    response_model=DeviceInterfaceDetailDTO,
    summary="读取单个设备接口详情",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_interface_detail(
    request: Request,
    device_uuid: str,
    interface_name: str = Path(min_length=1, max_length=255),
) -> DeviceInterfaceDetailDTO:
    return _not_found(
        lambda: _detail_service(request).interface_detail(device_uuid, interface_name),
        "设备或接口不存在",
    )


@router.get(
    "/devices/{device_uuid}/transceivers",
    response_model=DeviceTransceiverPageDTO,
    summary="分页读取设备光模块快照",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_transceivers(
    request: Request,
    device_uuid: str,
    search: str = Query(default="", max_length=200),
    severity: str = Query(
        default="",
        pattern="^(|normal|notice|warning|alarm|link_abnormal|no_light|no_module|unknown)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceTransceiverPageDTO:
    return _not_found(
        lambda: _detail_service(request).transceivers(
            device_uuid,
            search=search,
            severity=severity,
            page=page,
            page_size=page_size,
        ),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/lldp",
    response_model=DeviceLldpPageDTO,
    summary="分页读取设备 LLDP 邻居",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_lldp(
    request: Request,
    device_uuid: str,
    search: str = Query(default="", max_length=200),
    linked_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceLldpPageDTO:
    return _not_found(
        lambda: _detail_service(request).lldp(
            device_uuid,
            search=search,
            linked_only=linked_only,
            page=page,
            page_size=page_size,
        ),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/config-snapshots",
    response_model=DeviceConfigSnapshotPageDTO,
    summary="分页读取设备配置快照",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_config_snapshots(
    request: Request,
    device_uuid: str,
    snapshot_type: str = Query(default="", pattern="^(|running|saved|diff)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceConfigSnapshotPageDTO:
    return _not_found(
        lambda: _detail_service(request).config_snapshots(
            device_uuid,
            snapshot_type=snapshot_type,
            page=page,
            page_size=page_size,
        ),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/tasks",
    response_model=DeviceDetailTaskPageDTO,
    summary="分页读取设备任务记录",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_detail_tasks(
    request: Request,
    device_uuid: str,
    task_status: str = Query(
        default="",
        alias="status",
        pattern="^(|PENDING|STARTING|RUNNING|STOPPING|COMPLETED|FAILED|CANCELLED)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceDetailTaskPageDTO:
    return _not_found(
        lambda: _detail_service(request).tasks(
            device_uuid,
            status=task_status,
            page=page,
            page_size=page_size,
        ),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/business-associations",
    response_model=DeviceBusinessAssociationPageDTO,
    summary="分页读取设备关联业务",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_business_associations(
    request: Request,
    device_uuid: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceBusinessAssociationPageDTO:
    return _not_found(
        lambda: _detail_service(request).business_associations(
            device_uuid, page=page, page_size=page_size
        ),
        "设备不存在",
    )


@router.post(
    "/devices/{device_uuid}/refresh",
    response_model=DeviceRefreshTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交受控设备详情刷新",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def refresh_device_detail(
    request: Request,
    device_uuid: str,
    payload: DeviceRefreshRequestDTO,
) -> DeviceRefreshTaskDTO:
    return _not_found(
        lambda: _detail_service(request).refresh(
            device_uuid,
            payload.operation_id,
            idempotency_key=payload.idempotency_key,
        ),
        "设备不存在",
    )


@router.post(
    "/imports/preview",
    response_model=DeviceImportPreviewDTO,
    dependencies=[Depends(require_feature("web.device_management_import"))],
)
def preview_import(
    request: Request,
    file: UploadFile = File(...),
    match_strategy: str | None = Form(default=None),
    write_mode: str | None = Form(default=None),
) -> DeviceImportPreviewDTO:
    disposition = file.headers.get("content-disposition", "")
    if any(marker in disposition for marker in ("\\", "/", ":", "\x00")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="上传文件名不得包含本机路径",
        )
    return _query(
        lambda: _service(request).preview_import(
            file.filename or "",
            file.file,
            match_strategy=match_strategy,
            write_mode=write_mode,
        )
    )


@router.post(
    "/imports/confirm",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_import"))],
)
def confirm_import(
    request: Request, payload: DeviceImportConfirmRequestDTO
) -> DeviceTaskReferenceDTO:
    return _query(lambda: _service(request).confirm_import(payload))


@router.post(
    "/exports/csv",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_export"))],
)
def export_csv(
    request: Request, payload: DeviceExportRequestDTO
) -> DeviceTaskReferenceDTO:
    return _query(lambda: _service(request).start_csv_export(payload))


@router.post(
    "/exports/template",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_export"))],
)
def export_template(
    request: Request, payload: DeviceExportRequestDTO
) -> DeviceTaskReferenceDTO:
    return _query(lambda: _service(request).start_template_export())


@router.post(
    "/exports/securecrt",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_export"))],
)
def export_securecrt(
    request: Request, payload: DeviceSecureCrtExportRequestDTO
) -> DeviceTaskReferenceDTO:
    return _query(lambda: _service(request).start_securecrt_export(payload))


@router.post(
    "/exports/securecrt-with-template",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_export"))],
)
def export_securecrt_with_template(
    request: Request,
    selection: str = Form(default="{}"),
    file: UploadFile = File(...),
) -> DeviceTaskReferenceDTO:
    return _query(
        lambda: _service(request).start_securecrt_export(
            DeviceSecureCrtExportRequestDTO.model_validate_json(selection),
            template_name=file.filename or "",
            template_stream=file.file,
        )
    )


@router.get(
    "/exports/{task_id}",
    response_model=DeviceTaskReferenceDTO,
    dependencies=[Depends(require_feature("web.device_management_export"))],
)
def export_status(request: Request, task_id: str) -> DeviceTaskReferenceDTO:
    return _not_found(
        lambda: _service(request).get_export_task(task_id), "导出任务不存在"
    )


@router.get(
    "/exports/{task_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.device_management_export"))],
)
def download_export(
    request: Request,
    task_id: str,
    artifact_id: str = Query(min_length=8, max_length=160),
) -> FileResponse:
    path, filename = _not_found(
        lambda: _service(request).open_export_artifact(task_id, artifact_id),
        "导出任务或文件不存在",
    )
    return FileResponse(
        path, filename=filename, media_type=artifact_media_type(filename)
    )


@router.post(
    "/devices/{device_uuid}/diagnostic-download",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def diagnostic_download(request: Request, device_uuid: str) -> DeviceTaskReferenceDTO:
    return _not_found(
        lambda: _service(request).start_diagnostic_download([device_uuid]), "设备不存在"
    )


@router.post(
    "/diagnostic-download",
    response_model=DeviceTaskReferenceDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def batch_diagnostic_download(
    request: Request, payload: DeviceBatchRefreshRequestDTO
) -> DeviceTaskReferenceDTO:
    return _query(
        lambda: _service(request).start_diagnostic_download(payload.device_uuids)
    )


@router.get(
    "/diagnostics/{task_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.device_management_collect"))],
)
def download_diagnostics(
    request: Request,
    task_id: str,
    artifact_id: str = Query(min_length=8, max_length=160),
) -> FileResponse:
    path, filename = _not_found(
        lambda: _service(request).open_diagnostic_artifact(task_id, artifact_id),
        "诊断任务或文件不存在",
    )
    return FileResponse(path, filename=filename)


@router.get(
    "/external-terminal/settings",
    response_model=DeviceExternalTerminalSettingsDTO,
    dependencies=[Depends(require_feature("web.device_management_desktop"))],
)
def external_terminal_settings(request: Request) -> DeviceExternalTerminalSettingsDTO:
    return _query(lambda: _service(request).get_external_terminal_settings())


@router.put(
    "/external-terminal/settings",
    response_model=DeviceExternalTerminalSettingsDTO,
    dependencies=[Depends(require_feature("web.device_management_desktop"))],
)
def update_external_terminal_settings(
    request: Request,
    payload: DeviceExternalTerminalSettingsUpdateDTO,
) -> DeviceExternalTerminalSettingsDTO:
    return _query(lambda: _service(request).update_external_terminal_settings(payload))


@router.post(
    "/external-terminal/launch",
    response_model=DeviceExternalTerminalBatchDTO,
    dependencies=[Depends(require_feature("web.device_management_desktop"))],
)
def batch_external_terminal(
    request: Request,
    payload: DeviceExternalTerminalBatchRequestDTO,
) -> DeviceExternalTerminalBatchDTO:
    return _query(lambda: _service(request).launch_external_terminals(payload))


@router.post(
    "/external-terminal/confirmation",
    response_model=DeviceExternalTerminalConfirmationDTO,
    dependencies=[Depends(require_feature("web.device_management_desktop"))],
)
def external_terminal_confirmation(
    request: Request,
    payload: DeviceExternalTerminalConfirmationRequestDTO,
) -> DeviceExternalTerminalConfirmationDTO:
    return _query(
        lambda: _service(request).issue_external_terminal_confirmation(payload)
    )


@router.post(
    "/devices/{device_uuid}/external-terminal",
    response_model=DeviceExternalTerminalActionDTO,
    dependencies=[Depends(require_feature("web.device_management_desktop"))],
)
def external_terminal(
    request: Request, device_uuid: str, payload: DeviceExternalTerminalRequestDTO
) -> DeviceExternalTerminalActionDTO:
    return _not_found(
        lambda: _service(request).external_terminal_action(device_uuid, payload),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/edit-profile",
    response_model=DeviceEditProfileDTO,
    summary="读取设备编辑资料",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_edit_profile(request: Request, device_uuid: str) -> DeviceEditProfileDTO:
    return _not_found(
        lambda: _service(request).get_device_edit_profile(device_uuid),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}/credentials/{credential_field}/reveal",
    response_model=DeviceCredentialRevealDTO,
    summary="读取本机已保存设备凭据",
    include_in_schema=False,
    dependencies=[Depends(require_feature("web.device_management_desktop"))],
)
def reveal_device_credentials(
    request: Request, device_uuid: str, credential_field: DeviceSecretField
) -> DeviceCredentialRevealDTO:
    require_local_desktop_session(request)
    return _not_found(
        lambda: _service(request).reveal_device_credentials(
            device_uuid, credential_field
        ),
        "设备不存在",
    )


@router.get(
    "/devices/{device_uuid}",
    response_model=DeviceDetailDTO,
    deprecated=True,
    summary="旧设备全量详情兼容接口（请勿用于新详情或编辑）",
)
def device_detail(request: Request, device_uuid: str) -> DeviceDetailDTO:
    return _not_found(
        lambda: _service(request).get_device_detail(device_uuid), "设备不存在"
    )


@router.get(
    "/devices/{device_uuid}/history",
    response_model=DeviceHistoryPageDTO,
    summary="分页读取设备详情历史",
    responses=_DEVICE_DETAIL_ERROR_RESPONSES,
)
def device_history(
    request: Request,
    device_uuid: str,
    kind: str = Query(pattern="^(interface|optical|lldp)$"),
    object_name: str = Query(min_length=1, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> DeviceHistoryPageDTO:
    return _not_found(
        lambda: _service(request).get_device_history(
            device_uuid,
            kind,
            object_name,
            page=page,
            page_size=page_size,
        ),
        "设备或历史记录不存在",
    )


@router.post(
    "/connection-tests/form",
    response_model=DeviceConnectionTestDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.device_form_connection_test")),
        Depends(require_feature("web.device_management_write")),
    ],
)
def start_form_connection_test(
    request: Request,
    payload: DeviceFormConnectionTestRequestDTO,
) -> DeviceConnectionTestDTO:
    with map_api_errors(
        "表单连接测试任务暂时无法创建",
        io_detail="表单连接测试任务暂时无法创建",
        io_errors=(OSError, RuntimeError),
    ):
        try:
            return _service(request).start_form_connection_test(payload)
        except DeviceConnectionPreflightError as exc:
            _raise_preflight(exc)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="设备不存在"
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc


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
            return _service(request).start_connection_test(
                device_uuid, payload.protocol
            )
        except DeviceConnectionPreflightError as exc:
            _raise_preflight(exc)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="设备不存在"
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc


@router.get(
    "/connection-tests/{task_id}",
    response_model=DeviceConnectionTestDTO,
    dependencies=[Depends(require_feature("web.device_connection_test"))],
)
def connection_test(request: Request, task_id: str) -> DeviceConnectionTestDTO:
    return _not_found(
        lambda: _service(request).get_connection_test(task_id), "连接测试任务不存在"
    )


@router.get("/tasks/{task_id}", response_model=DeviceTaskReferenceDTO)
def task_status(request: Request, task_id: str) -> DeviceTaskReferenceDTO:
    task = _not_found(lambda: _service(request).get_task(task_id), "设备任务不存在")
    _require_task_feature(request, task)
    return task


@router.post("/tasks/{task_id}/cancel", response_model=DeviceTaskReferenceDTO)
def cancel_task(request: Request, task_id: str) -> DeviceTaskReferenceDTO:
    task = _not_found(lambda: _service(request).get_task(task_id), "设备任务不存在")
    _require_task_feature(request, task)
    return _not_found(lambda: _service(request).cancel_task(task_id), "设备任务不存在")


def _require_task_feature(request: Request, task: DeviceTaskReferenceDTO) -> None:
    if task.action in {
        "batch_refresh_details",
        "diagnostic_download",
        "optical_refresh",
    }:
        feature_id = "web.device_management_collect"
    elif task.action == "import_csv":
        feature_id = "web.device_management_import"
    elif task.action == "connection_test":
        feature_id = "web.device_connection_test"
    else:
        feature_id = "web.device_management_export"
    require_feature(feature_id)(request)


def _not_found(callback, message: str):
    try:
        return _query(callback)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=message
        ) from exc


def _query(callback):
    with map_api_errors("设备数据库暂时不可读"):
        try:
            return callback()
        except DeviceConnectionPreflightError as exc:
            _raise_preflight(exc)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在"
            ) from exc
        except DeviceAddressError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc


def _raise_preflight(exc: DeviceConnectionPreflightError) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    ) from exc


__all__ = ["router"]
