from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from netconsole.backend.api.error_mapping import map_api_errors
from netconsole.backend.api.feature_access import require_feature
from netconsole.models.api.ac_management import (
    AcApDetailDTO,
    AcApHistoryPageDTO,
    AcApPageDTO,
    AcActionConfirmRequestDTO,
    AcActionPlanCreateRequestDTO,
    AcActionPlanDTO,
    AcExternalTerminalActionDTO,
    AcExternalTerminalOptionsDTO,
    AcConfigContentDTO,
    AcConfigDiffDTO,
    AcConfigSnapshotPageDTO,
    AcLldpDTO,
    AcManagementSummaryDTO,
    AcOpticalDTO,
    AcRadioDTO,
    AcExtensionApplyRequestDTO,
    AcExtensionApplyResultDTO,
    AcExtensionPageDTO,
    AcExtensionPreviewDTO,
    AcExtensionRollbackRequestDTO,
    AcExtensionRollbackResultDTO,
    AcFitApDeleteRequestDTO,
    AcFitApMetadataSaveRequestDTO,
    AcFitApResourceExportRequestDTO,
    AcLocalRebuildRequestDTO,
    AcOmniPeekPreviewDTO,
    AcOmniPeekPreferencesDTO,
    AcOmniPeekPreferencesSaveDTO,
    AcOmniPeekRequestDTO,
    AcExternalTerminalRequestDTO,
    AcRefreshRequestDTO,
    AcWebTaskDTO,
)
from netconsole.application.ac.web_application_service import AcWebActionError, AcWebApplicationService
from netconsole.services.ac.query_service import AcManagementQueryService


router = APIRouter(prefix="/ac-management", tags=["ac-management"])


def _service(request: Request) -> AcManagementQueryService:
    return request.app.state.ac_management_query_service


def _site_id(request: Request) -> str:
    return _service(request).current_site_id()


def _web_service(request: Request) -> AcWebApplicationService:
    service = getattr(request.app.state, "ac_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AC Web 服务未接线")
    return service


def _web_site_id(request: Request) -> str:
    return _web_service(request).current_site_id()


@router.get(
    "/summary",
    response_model=AcManagementSummaryDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def summary(request: Request) -> AcManagementSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request)))


@router.get(
    "/aps",
    response_model=AcApPageDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def list_aps(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str = Query(default="", max_length=200),
    ap_status: str = Query(default="", alias="status", max_length=30),
    station: str = Query(default="", max_length=100),
    section: str = Query(default="", max_length=100),
    model: str = Query(default="", max_length=100),
    switch: str = Query(default="", max_length=100),
    optical_status: str = Query(default="", max_length=30),
    sort_by: str = Query(default="topology", max_length=30),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> AcApPageDTO:
    return _query(
        lambda: _service(request).list_aps(
            _site_id(request),
            ac_id=ac_id,
            page=page,
            page_size=page_size,
            query=query,
            status=ap_status,
            station=station,
            section=section,
            model=model,
            switch=switch,
            optical_status=optical_status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get(
    "/optical-anomalies",
    response_model=AcApPageDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def optical_anomalies(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str = Query(default="", max_length=200),
) -> AcApPageDTO:
    return _query(
        lambda: _service(request).list_optical_anomalies(
            _site_id(request), ac_id=ac_id, page=page, page_size=page_size, query=query
        )
    )


@router.get(
    "/aps/{ap_id}",
    response_model=AcApDetailDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def ap_detail(request: Request, ap_id: str) -> AcApDetailDTO:
    return _required(_query(lambda: _service(request).get_ap_detail(_site_id(request), ap_id)), "AP 不存在")


@router.get(
    "/aps/{ap_id}/history/{history_kind}",
    response_model=AcApHistoryPageDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_history"))],
)
def ap_history(
    request: Request,
    ap_id: str,
    history_kind: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
) -> AcApHistoryPageDTO:
    result = _query(
        lambda: _service(request).get_ap_history(
            _site_id(request),
            ap_id,
            history_kind,
            page=page,
            page_size=page_size,
        )
    )
    return _required(result, "AP 不存在")


@router.get(
    "/aps/{ap_id}/radios",
    response_model=list[AcRadioDTO],
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def ap_radios(request: Request, ap_id: str) -> list[AcRadioDTO]:
    return _required(_query(lambda: _service(request).get_ap_radios(_site_id(request), ap_id)), "AP 不存在")


@router.get(
    "/aps/{ap_id}/lldp",
    response_model=AcLldpDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def ap_lldp(request: Request, ap_id: str) -> AcLldpDTO:
    return _required(_query(lambda: _service(request).get_ap_lldp(_site_id(request), ap_id)), "AP 不存在")


@router.get(
    "/aps/{ap_id}/optical",
    response_model=AcOpticalDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def ap_optical(request: Request, ap_id: str) -> AcOpticalDTO:
    return _required(_query(lambda: _service(request).get_ap_optical(_site_id(request), ap_id)), "AP 不存在")


@router.get(
    "/config-snapshots",
    response_model=AcConfigSnapshotPageDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def config_snapshots(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    snapshot_type: str = Query(default="", alias="type", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> AcConfigSnapshotPageDTO:
    return _query(
        lambda: _service(request).list_config_snapshots(
            _site_id(request), ac_id=ac_id, snapshot_type=snapshot_type, page=page, page_size=page_size
        )
    )


@router.get(
    "/config-snapshots/{snapshot_id}",
    response_model=AcConfigContentDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def config_snapshot(
    request: Request,
    snapshot_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100_000, ge=1, le=200_000),
) -> AcConfigContentDTO:
    result = _query(lambda: _service(request).get_config_snapshot(_site_id(request), snapshot_id, offset=offset, limit=limit))
    return _required(result, "配置快照不存在")


@router.get(
    "/config-snapshots/{snapshot_id}/diff",
    response_model=AcConfigDiffDTO,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resources"))],
)
def config_diff(
    request: Request,
    snapshot_id: int,
    other_snapshot_id: int | None = Query(default=None, ge=1),
) -> AcConfigDiffDTO:
    result = _query(
        lambda: _service(request).get_config_diff(
            _site_id(request), snapshot_id, other_snapshot_id=other_snapshot_id
        )
    )
    return _required(result, "配置快照不存在")


@router.get(
    "/online-overview",
    response_model=AcManagementSummaryDTO,
    dependencies=[Depends(require_feature("web.ac_online_overview"))],
)
def online_overview(request: Request) -> AcManagementSummaryDTO:
    return _query(lambda: _service(request).get_summary(_site_id(request)))


@router.get(
    "/optical",
    response_model=AcApPageDTO,
    dependencies=[Depends(require_feature("web.ac_optical"))],
)
def optical(
    request: Request,
    ac_id: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    query: str = Query(default="", max_length=200),
    optical_status: str = Query(default="", max_length=30),
) -> AcApPageDTO:
    return _query(lambda: _service(request).list_aps(_site_id(request), ac_id=ac_id, page=page, page_size=page_size, query=query, optical_status=optical_status))


@router.get(
    "/extensions",
    response_model=AcExtensionPageDTO,
    dependencies=[Depends(require_feature("web.ac_extensions"))],
)
def extensions(
    request: Request,
    search: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AcExtensionPageDTO:
    return _query(lambda: _web_service(request).list_extensions(_web_site_id(request), search=search, page=page, page_size=page_size))


@router.post(
    "/extensions/import-preview",
    response_model=AcExtensionPreviewDTO,
    dependencies=[Depends(require_feature("web.ac_extensions_preview"))],
)
async def extension_import_preview(
    request: Request,
    file: UploadFile = File(...),
) -> AcExtensionPreviewDTO:
    try:
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("AP 扩展导入文件超过 10 MiB 限制")
        return _web_service(request).preview_extension(
            _web_site_id(request), file.filename or "", content, file.content_type or ""
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post(
    "/extensions/import-apply",
    response_model=AcExtensionApplyResultDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.ac_extensions_apply"))],
)
def extension_import_apply(request: Request, payload: AcExtensionApplyRequestDTO) -> AcExtensionApplyResultDTO:
    try:
        return _web_service(request).apply_extension(_web_site_id(request), payload.preview_id, payload.preview_digest, payload.explicit_confirmation)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/extensions/audits/{audit_id}/rollback",
    response_model=AcExtensionRollbackResultDTO,
    dependencies=[Depends(require_feature("web.ac_extensions_rollback"))],
)
def extension_rollback(request: Request, audit_id: str, payload: AcExtensionRollbackRequestDTO) -> AcExtensionRollbackResultDTO:
    try:
        return _web_service(request).rollback_extension(_web_site_id(request), audit_id, payload.explicit_confirmation)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/local-rebuild/{rebuild_kind}",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.ac_refresh"))],
)
def local_rebuild(request: Request, rebuild_kind: str, payload: AcLocalRebuildRequestDTO) -> AcWebTaskDTO:
    task_types = {"ac": "ac_overview_refresh", "fit-ap": "ac_fit_ap_resources_refresh", "optical": "ac_fit_ap_optical_refresh", "trackside-plan": "trackside_ap_plan_refresh"}
    try:
        task_type = task_types[rebuild_kind]
        return _web_service(request).start_local_rebuild(_web_site_id(request), task_type, ac_id=payload.ac_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="不支持的 AC 本地重算类型") from exc
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/refresh/{refresh_kind}",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.ac_refresh"))],
)
def refresh_resources(request: Request, refresh_kind: str, payload: AcRefreshRequestDTO) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_refresh(
            _web_site_id(request),
            refresh_kind,
            ac_id=payload.ac_id,
            ap_id=payload.ap_id,
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/fit-aps/delete",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.ac_fit_ap_delete")),
        Depends(require_feature("web.ac_refresh")),
    ],
)
def delete_fit_aps(request: Request, payload: AcFitApDeleteRequestDTO) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_fit_ap_delete(
            _web_site_id(request),
            ac_id=payload.ac_id,
            ap_ids=payload.ap_ids,
            explicit_confirmation=payload.explicit_confirmation,
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/fit-aps/metadata/import",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.ac_fit_ap_metadata_import")),
        Depends(require_feature("web.ac_refresh")),
    ],
)
async def import_fit_ap_metadata(request: Request, file: UploadFile = File(...)) -> AcWebTaskDTO:
    try:
        content = await file.read()
        return _web_service(request).start_fit_ap_metadata_import(
            _web_site_id(request),
            file_name=file.filename or "",
            content=content,
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)
    finally:
        await file.close()


@router.post(
    "/aps/{ap_id}/metadata",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.ac_fit_ap_metadata_write")),
        Depends(require_feature("web.ac_refresh")),
    ],
)
def save_fit_ap_metadata(request: Request, ap_id: str, payload: AcFitApMetadataSaveRequestDTO) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_fit_ap_metadata_save(
            _web_site_id(request),
            ac_id=payload.ac_id,
            ap_id=ap_id,
            metadata=payload.model_dump(exclude={"ac_id"}),
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/fit-aps/omnipeek/preview",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("ac.omnipeek_name_table_export")),
        Depends(require_feature("web.ac_refresh")),
    ],
)
def preview_fit_ap_omnipeek(request: Request, payload: AcOmniPeekRequestDTO) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_omnipeek_preview(
            _web_site_id(request),
            ac_id=payload.ac_id,
            ap_ids=payload.ap_ids,
            options=payload.model_dump(exclude={"ac_id", "ap_ids"}),
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.get(
    "/fit-aps/omnipeek/preview/{task_id}",
    response_model=AcOmniPeekPreviewDTO,
    dependencies=[Depends(require_feature("ac.omnipeek_name_table_export"))],
)
def fit_ap_omnipeek_preview(
    request: Request,
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=20, le=500),
    status_filter: str = Query(default="all", max_length=30),
    search: str = Query(default="", max_length=200),
) -> AcOmniPeekPreviewDTO:
    try:
        return _web_service(request).get_omnipeek_preview(
            _web_site_id(request),
            task_id,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            search=search,
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/fit-aps/omnipeek/export",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("ac.omnipeek_name_table_export")),
        Depends(require_feature("web.ac_refresh")),
    ],
)
def export_fit_ap_omnipeek(request: Request, payload: AcOmniPeekRequestDTO) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_omnipeek_export(
            _web_site_id(request),
            ac_id=payload.ac_id,
            ap_ids=payload.ap_ids,
            options=payload.model_dump(exclude={"ac_id", "ap_ids"}),
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/fit-aps/export",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.ac_fit_ap_resource_export"))],
)
def export_fit_ap_resources(request: Request, payload: AcFitApResourceExportRequestDTO) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_fit_ap_resource_export(
            _web_site_id(request),
            ac_id=payload.ac_id,
            scope=payload.scope,
            selected_ap_ids=payload.selected_ap_ids,
            filters=payload.filters.model_dump(),
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.get(
    "/fit-aps/omnipeek/preferences",
    response_model=AcOmniPeekPreferencesDTO,
    dependencies=[Depends(require_feature("ac.omnipeek_name_table_export"))],
)
def fit_ap_omnipeek_preferences(request: Request) -> AcOmniPeekPreferencesDTO:
    return _web_service(request).omnipeek_preferences(_web_site_id(request))


@router.put(
    "/fit-aps/omnipeek/preferences",
    response_model=AcOmniPeekPreferencesDTO,
    dependencies=[Depends(require_feature("ac.omnipeek_name_table_export"))],
)
def save_fit_ap_omnipeek_preferences(
    request: Request,
    payload: AcOmniPeekPreferencesSaveDTO,
) -> AcOmniPeekPreferencesDTO:
    return _web_service(request).save_omnipeek_preferences(_web_site_id(request), payload.colors)


@router.get(
    "/fit-aps/external-terminal/options",
    response_model=AcExternalTerminalOptionsDTO,
    dependencies=[
        Depends(require_feature("web.ac_fit_ap_external_terminal")),
        Depends(require_feature("desktop.native_bridge")),
    ],
)
def fit_ap_external_terminal_options(request: Request) -> AcExternalTerminalOptionsDTO:
    try:
        return _web_service(request).external_terminal_options()
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/fit-aps/{ap_id}/external-terminal",
    response_model=AcExternalTerminalActionDTO,
    dependencies=[
        Depends(require_feature("web.ac_fit_ap_external_terminal")),
        Depends(require_feature("desktop.native_bridge")),
    ],
)
def fit_ap_external_terminal(
    request: Request,
    ap_id: str,
    payload: AcExternalTerminalRequestDTO,
) -> AcExternalTerminalActionDTO:
    try:
        return _web_service(request).launch_fit_ap_external_terminal(
            _web_site_id(request),
            ac_id=payload.ac_id,
            ap_id=ap_id,
            terminal_type=payload.terminal_type,
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/trackside-business/local-rebuild",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.ac_refresh"))],
)
def trackside_business_local_rebuild(request: Request, payload: AcLocalRebuildRequestDTO) -> AcWebTaskDTO:
    try:
        task = _web_service(request).start_local_rebuild(
            _web_site_id(request),
            "ac_trackside_business_refresh",
            ac_id=payload.ac_id,
        )
        return task
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.get(
    "/web-tasks/{task_id}",
    response_model=AcWebTaskDTO,
    dependencies=[Depends(require_feature("web.ac_refresh"))],
)
def web_task(request: Request, task_id: str) -> AcWebTaskDTO:
    try:
        return _web_service(request).get_task(_web_site_id(request), task_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/web-tasks/{task_id}/cancel",
    response_model=AcWebTaskDTO,
    dependencies=[Depends(require_feature("web.ac_refresh"))],
)
def cancel_web_task(request: Request, task_id: str) -> AcWebTaskDTO:
    try:
        return _web_service(request).cancel_task(_web_site_id(request), task_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/web-tasks/recover",
    response_model=list[AcWebTaskDTO],
    dependencies=[Depends(require_feature("web.ac_refresh"))],
)
def recover_web_tasks(request: Request) -> list[AcWebTaskDTO]:
    try:
        return _web_service(request).recover_tasks(_web_site_id(request))
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/actions/plans",
    response_model=AcActionPlanDTO,
    dependencies=[Depends(require_feature("web.ac_dangerous_actions"))],
)
def create_action_plan(request: Request, payload: AcActionPlanCreateRequestDTO) -> AcActionPlanDTO:
    try:
        return _web_service(request).create_action_plan(_web_site_id(request), payload.target_id, payload.action_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.get(
    "/actions/plans/{plan_id}",
    response_model=AcActionPlanDTO,
    dependencies=[Depends(require_feature("web.ac_dangerous_actions"))],
)
def action_plan(request: Request, plan_id: str) -> AcActionPlanDTO:
    try:
        return _web_service(request).preview_action_plan(_web_site_id(request), plan_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/actions/plans/{plan_id}/confirm",
    response_model=AcActionPlanDTO,
    dependencies=[Depends(require_feature("web.ac_dangerous_actions"))],
)
def confirm_action_plan(request: Request, plan_id: str, payload: AcActionConfirmRequestDTO) -> AcActionPlanDTO:
    try:
        return _web_service(request).confirm_action_plan(_web_site_id(request), plan_id, payload.plan_digest, payload.confirm_token)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/actions/plans/{plan_id}/execute",
    response_model=AcActionPlanDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.ac_dangerous_actions"))],
)
def execute_action_plan(request: Request, plan_id: str) -> AcActionPlanDTO:
    try:
        return _web_service(request).execute_action_plan(_web_site_id(request), plan_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.get(
    "/actions/plans/{plan_id}/audit",
    dependencies=[Depends(require_feature("web.ac_dangerous_actions"))],
)
def action_audit(request: Request, plan_id: str) -> dict[str, object]:
    try:
        return _web_service(request).action_audit(_web_site_id(request), plan_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.post(
    "/extensions/export",
    response_model=AcWebTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_feature("web.ac_extensions_export")),
        Depends(require_feature("web.ac_refresh")),
    ],
)
def extension_export(
    request: Request,
    search: str = Query(default="", max_length=200),
    ac_id: str = Query(default="", max_length=100),
) -> AcWebTaskDTO:
    try:
        return _web_service(request).start_extension_export(_web_site_id(request), search=search, ac_id=ac_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)


@router.get(
    "/extensions/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("web.ac_extensions_export"))],
)
def extension_export_download(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _web_service(request).open_extension_export(_web_site_id(request), artifact_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)
    return FileResponse(path, filename=name)


@router.get(
    "/fit-aps/omnipeek/artifacts/{artifact_id}/download",
    response_class=FileResponse,
    dependencies=[Depends(require_feature("ac.omnipeek_name_table_export"))],
)
def fit_ap_omnipeek_download(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _web_service(request).open_omnipeek_export(_web_site_id(request), artifact_id)
    except AcWebActionError as exc:
        _raise_web_error(exc)
    return FileResponse(path, filename=name)


@router.get(
    "/fit-aps/artifacts/{artifact_id}/download",
    dependencies=[Depends(require_feature("web.ac_fit_ap_resource_export"))],
)
def fit_ap_resource_download(request: Request, artifact_id: str) -> FileResponse:
    try:
        path, name = _web_service(request).open_fit_ap_resource_export(_web_site_id(request), artifact_id)
        return FileResponse(
            path,
            filename=name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except AcWebActionError as exc:
        _raise_web_error(exc)


def _required(value, message: str):
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return value


def _query(callback):
    with map_api_errors(
        "AC 数据库暂时不可读",
        io_detail="配置快照文件不可读",
        io_errors=(OSError, UnicodeError),
        io_status_code=status.HTTP_404_NOT_FOUND,
    ):
        try:
            return callback()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _raise_web_error(exc: AcWebActionError) -> None:
    conflicts = {
        "PLAN_TAMPERED", "PLAN_EXPIRED", "PLAN_ALREADY_CONFIRMED", "CONFIRMATION_REQUIRED",
        "PLAN_SITE_MISMATCH", "TARGET_STALE", "ALREADY_APPLIED", "BASE_DATA_DATABASE_CHANGED",
        "BASE_DATA_ROLLBACK_CONFLICT", "BASE_DATA_IMPORT_CONFLICT", "BASE_DATA_BLOCKING_ISSUES",
        "AC_ACTION_RUNNING",
    }
    not_found = {"PLAN_NOT_FOUND", "ARTIFACT_INVALID", "TASK_NOT_FOUND"}
    status_code = status.HTTP_409_CONFLICT if exc.code in conflicts else status.HTTP_404_NOT_FOUND if exc.code in not_found else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc


__all__ = ["router"]
