from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from netconsole.backend.api.feature_access import require_feature
from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
    RailTransitWebError,
)
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.models.api.wps_sync import (
    WpsSyncConnectionTestDTO,
    WpsSyncRecentBatchesDTO,
    WpsSyncRequestDTO,
    WpsSyncTargetDTO,
    WpsSyncTargetUpdateDTO,
)
from netconsole.services.wps_trackside_ap_sync import (
    TracksideApWpsSyncService,
    WpsSyncError,
)


router = APIRouter(prefix="/rail-transit/trackside-ap-business/wps", tags=["trackside-ap-business-wps"])


def _service(request: Request) -> TracksideApWpsSyncService:
    service = getattr(request.app.state, "trackside_ap_wps_sync_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="WPS 同步服务未接线")
    return service


def _rail_service(request: Request) -> RailTransitWebApplicationService:
    service = getattr(request.app.state, "rail_transit_web_application_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="轨交后台任务服务未接线")
    return service


def _site_id(request: Request) -> str:
    query_service = request.app.state.trackside_ap_business_query_service
    return SiteManager(request.app.state.paths).validate_site_name(query_service.current_site_id())


def _raise(exc: WpsSyncError) -> None:
    status_code = 422
    if (
        exc.code.startswith(("WPS_HTTP_401", "WPS_HTTP_403"))
        or exc.details.get("http_status") in {401, 403, 404, 429}
        or exc.code.startswith(("WPS_REMOTE_", "WPS_TOKEN_", "WPS_DOCUMENT_PERMISSION_"))
    ):
        status_code = 502
    raise HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    ) from exc


@router.get(
    "/targets",
    response_model=list[WpsSyncTargetDTO],
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def list_targets(request: Request) -> list[WpsSyncTargetDTO]:
    return [WpsSyncTargetDTO.model_validate(item) for item in _service(request).list_targets(_site_id(request))]


@router.put(
    "/targets/{target_code}",
    response_model=WpsSyncTargetDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def update_target(
    request: Request,
    target_code: str,
    payload: WpsSyncTargetUpdateDTO,
) -> WpsSyncTargetDTO:
    try:
        result = _service(request).configure_target(
            _site_id(request),
            target_code,
            token=payload.token,
            document_open_url=payload.document_open_url,
            webhook_url=payload.webhook_url,
            enabled=payload.enabled,
            timeout_seconds=payload.timeout_seconds,
        )
        return WpsSyncTargetDTO.model_validate(result)
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/connection-test",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def connection_test(request: Request, target_code: str) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).connection_test(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/runtime-write-probe",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def runtime_write_probe(request: Request, target_code: str) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).runtime_write_probe(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/migrate-legacy-binding",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def migrate_legacy_binding(request: Request, target_code: str) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).migrate_legacy_binding(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/sync-test-sheet",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def sync_test_sheet(request: Request, target_code: str) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).sync_test_sheet(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/sheet-order-probe",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def sheet_order_probe(request: Request, target_code: str) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).sheet_order_probe(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/sheet-tab-color-probe",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def sheet_tab_color_probe(
    request: Request,
    target_code: str,
) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).sheet_tab_color_probe(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/column-width-probe",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def column_width_probe(
    request: Request,
    target_code: str,
) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).column_width_probe(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/targets/{target_code}/revalidate-deployment",
    response_model=WpsSyncConnectionTestDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def revalidate_deployment(request: Request, target_code: str) -> WpsSyncConnectionTestDTO:
    try:
        return WpsSyncConnectionTestDTO(
            target_code=target_code,
            result=_service(request).revalidate_deployment(_site_id(request), target_code),
        )
    except WpsSyncError as exc:
        _raise(exc)


@router.post(
    "/sync",
    response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def sync(request: Request, payload: WpsSyncRequestDTO) -> RailTransitTaskDTO:
    try:
        return _rail_service(request).start_trackside_ap_wps_sync(
            _site_id(request),
            target_codes=payload.target_codes,
            expected_revision=payload.expected_revision,
            initialize_binding=payload.initialize_binding,
        )
    except RailTransitWebError as exc:
        raise HTTPException(
            status_code=(409 if exc.code == "TASK_RESOURCE_BUSY" else 422),
            detail={"code": exc.code, "message": str(exc), "details": exc.details},
        ) from exc


@router.get(
    "/batches/recent",
    response_model=WpsSyncRecentBatchesDTO,
    dependencies=[Depends(require_feature("web.rail_trackside_ap_business_wps_sync"))],
)
def recent_batches(request: Request) -> WpsSyncRecentBatchesDTO:
    return WpsSyncRecentBatchesDTO(items=_service(request).recent_batches(_site_id(request)))


__all__ = ["router"]
