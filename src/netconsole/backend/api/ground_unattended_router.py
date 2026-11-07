from __future__ import annotations

import json
import time
import traceback
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse

from netconsole.backend.api.feature_access import require_feature
from netconsole.core import app_logger
from netconsole.models.api.ground_unattended import (
    GroundActionResponseDTO,
    GroundHistoryExportRequestDTO,
    GroundArchiveDTO,
    GroundArchiveDetailDTO,
    GroundArchiveDeleteRequestDTO,
    GroundArchiveBatchDeleteRequestDTO,
    GroundArchiveBatchDeleteResponseDTO,
    GroundArchivePageDTO,
    GroundConfigCheckRequestDTO,
    GroundDeepCollectionPageDTO,
    GroundDeepCollectionRecordPageDTO,
    GroundHealthDTO,
    GroundHeartbeatPageDTO,
    GroundHeartbeatInventoryRequestDTO,
    GroundHeartbeatInventoryApplyDTO,
    GroundHeartbeatInventoryPreviewDTO,
    GroundMrMonitoringDTO,
    GroundInventorySummaryDTO,
    GroundMrRuntimeStatusPageDTO,
    GroundPingSummaryPageDTO,
    GroundPingSamplePageDTO,
    GroundPingSeriesDTO,
    GroundPriorityUpdateDTO,
    GroundRawFilePageDTO,
    GroundRunPageDTO,
    GroundRunDeleteRequestDTO,
    GroundSyslogRecordPageDTO,
    GroundDeepTaskPageDTO,
    GroundSyslogDeleteAcceptedDTO,
    GroundSyslogDeletePreviewDTO,
    GroundSyslogDeletePreviewRequestDTO,
    GroundSyslogDeleteRequestDTO,
    GroundSyslogTransportStatusDTO,
    GroundTrainPolicyUpdateDTO,
    GroundTimelinePageDTO,
    GroundOperationDTO,
    GroundUnattendedProfileDTO,
    GroundUnattendedProfileUpdateDTO,
    GroundUnattendedStatusDTO,
    GroundUnattendedTrainDTO,
    GroundUnattendedTrainPageDTO,
    GroundQuickPingPageDTO,
    GroundQuickPingRunDTO,
    GroundQuickPingSamplePageDTO,
    GroundHistoryPageDTO,
    GroundQuickPingStartRequestDTO,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
    GroundUnattendedError,
)
from netconsole.models.api.system_maintenance import DesktopActionDTO
from netconsole.models.api.rail_transit_web import RailTransitTaskDTO
from netconsole.application.rail_transit.web_application_service import RailTransitWebError


router = APIRouter(
    prefix="/rail-transit/ground-unattended",
    tags=["ground-unattended"],
    dependencies=[Depends(require_feature("module.ground_unattended"))],
)


def _service(request: Request) -> GroundUnattendedApplicationService:
    service = getattr(request.app.state, "ground_unattended_application_service", None)
    if service is None:
        startup_error = str(
            getattr(request.app.state, "ground_unattended_startup_error", "") or ""
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": (
                    "GROUND_UNATTENDED_STARTUP_FAILED"
                    if startup_error
                    else "GROUND_UNATTENDED_UNAVAILABLE"
                ),
                "message": (
                    f"地面无人值守后台初始化失败（{startup_error}），请查看运行日志"
                    if startup_error
                    else "地面无人值守后台服务未接线"
                ),
                "details": {"startup_error": startup_error},
            },
        )
    return service


def _site_id(request: Request) -> str:
    return _service(request).current_site_id()


@router.post(
    "/history/export", response_model=RailTransitTaskDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.ground_unattended.history_export"))],
)
def export_history(request: Request, payload: GroundHistoryExportRequestDTO) -> RailTransitTaskDTO:
    try:
        return request.app.state.rail_transit_web_application_service.start_ground_history_export(
            _site_id(request), filters=payload.model_dump(),
        )
    except RailTransitWebError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/status", response_model=GroundUnattendedStatusDTO)
def get_status(request: Request) -> GroundUnattendedStatusDTO:
    return _call(lambda: _service(request).status(_site_id(request)))


@router.get("/profile", response_model=GroundUnattendedProfileDTO)
def get_profile(request: Request) -> GroundUnattendedProfileDTO:
    return _call(lambda: _service(request).get_profile(_site_id(request)))


@router.get("/heartbeat", response_model=GroundHeartbeatPageDTO)
def get_heartbeat(request: Request, run_id: str = "", query: str = "", status: str = "", station: str = "", abnormal_only: bool = False, role: str = "",
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> GroundHeartbeatPageDTO:
    return _call(lambda: _service(request).heartbeat(_site_id(request), run_id=run_id, query=query, status=status,
                                                    station=station, abnormal_only=abnormal_only, page=page, page_size=page_size, role=role))


@router.post(
    "/heartbeat/inventory/preview", response_model=GroundHeartbeatInventoryPreviewDTO,
    dependencies=[Depends(require_feature("capability.ground_unattended.heartbeat_inventory_manage"))],
)
def heartbeat_inventory_preview(request: Request, payload: GroundHeartbeatInventoryRequestDTO) -> GroundHeartbeatInventoryPreviewDTO:
    return _call(lambda: _service(request).heartbeat_inventory_preview(_site_id(request), action=payload.action))


@router.post(
    "/heartbeat/inventory/apply", response_model=GroundHeartbeatInventoryPreviewDTO,
    dependencies=[Depends(require_feature("capability.ground_unattended.heartbeat_inventory_manage"))],
)
def heartbeat_inventory_apply(request: Request, payload: GroundHeartbeatInventoryApplyDTO) -> GroundHeartbeatInventoryPreviewDTO:
    return _call(lambda: _service(request).heartbeat_inventory_apply(_site_id(request), payload))


@router.get("/mr/{mr_uuid}/monitoring", response_model=GroundMrMonitoringDTO)
def get_mr_monitoring(request: Request, mr_uuid: str, run_id: str = "", start_time: str = "", end_time: str = "") -> GroundMrMonitoringDTO:
    return _call(lambda: _service(request).mr_monitoring(_site_id(request), mr_uuid=mr_uuid, run_id=run_id,
                                                        start_time=start_time, end_time=end_time))


@router.put("/profile", response_model=GroundUnattendedProfileDTO)
def update_profile(
    request: Request,
    payload: GroundUnattendedProfileUpdateDTO,
) -> GroundUnattendedProfileDTO:
    return _call(lambda: _service(request).update_profile(_site_id(request), payload))


@router.post(
    "/start",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def start(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).start_now(_site_id(request)))


@router.post(
    "/pause",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def pause(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).pause(_site_id(request)))


@router.post(
    "/resume",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).resume(_site_id(request)))


@router.post(
    "/stop",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def stop(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).stop(_site_id(request), archive=False))


@router.post(
    "/stop-and-archive",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def stop_and_archive(request: Request) -> GroundActionResponseDTO:
    return _call(lambda: _service(request).stop(_site_id(request), archive=True))


@router.post(
    "/quick-ping",
    response_model=GroundQuickPingRunDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.ground_unattended.quick_ping"))],
)
def start_quick_ping(
    request: Request,
    payload: GroundQuickPingStartRequestDTO,
) -> GroundQuickPingRunDTO:
    return _call(lambda: _service(request).quick_ping_start(_site_id(request), payload))


@router.get("/quick-ping", response_model=GroundQuickPingPageDTO)
def list_quick_ping(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    start_time: str = Query(default="", max_length=64),
    end_time: str = Query(default="", max_length=64),
    query: str = Query(default="", max_length=255),
    state: str = Query(default="", max_length=32),
    train_id: str = Query(default="", max_length=255),
    mr_id: str = Query(default="", max_length=255),
    mr_role: str = Query(default="", max_length=10),
) -> GroundQuickPingPageDTO:
    return _call(lambda: _service(request).quick_ping_list(
        _site_id(request), limit=limit, offset=offset, start_time=start_time,
        end_time=end_time, query=query, state=state, train_id=train_id, mr_id=mr_id, mr_role=mr_role,
    ))


@router.get("/quick-ping/{run_id}/samples", response_model=GroundQuickPingSamplePageDTO)
def quick_ping_samples(
    request: Request, run_id: str,
    target_ip: str = Query(default="", max_length=255),
    start_time: str = Query(default="", max_length=64),
    end_time: str = Query(default="", max_length=64),
    limit: int = Query(default=1000, ge=1, le=2000),
    cursor: str = Query(default="", max_length=512),
) -> GroundQuickPingSamplePageDTO:
    return _call(lambda: _service(request).quick_ping_samples(
        _site_id(request), run_id, target_ip=target_ip, start_time=start_time,
        end_time=end_time, limit=limit, cursor=cursor,
    ))


@router.get("/quick-ping/{run_id}", response_model=GroundQuickPingRunDTO)
def get_quick_ping(request: Request, run_id: str) -> GroundQuickPingRunDTO:
    return _call(lambda: _service(request).quick_ping_status(_site_id(request), run_id))


@router.get("/history", response_model=GroundHistoryPageDTO)
def history(
    request: Request,
    data_type: str = Query(default="", max_length=32),
    run_id: str = Query(default="", max_length=255),
    train_id: str = Query(default="", max_length=255),
    mr_id: str = Query(default="", max_length=255),
    mr_role: str = Query(default="", max_length=10),
    event_type: str = Query(default="", max_length=100),
    start_at: str = Query(default="", max_length=64),
    end_at: str = Query(default="", max_length=64),
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> GroundHistoryPageDTO:
    return _call(lambda: _service(request).history(
        _site_id(request), data_type=data_type, run_id=run_id, train_id=train_id, mr_id=mr_id,
        mr_role=mr_role, event_type=event_type, start_at=start_at, end_at=end_at,
        page=page, page_size=page_size, sort_order=sort_order,
    ))


@router.post(
    "/quick-ping/{run_id}/stop",
    response_model=GroundQuickPingRunDTO,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_feature("capability.ground_unattended.quick_ping"))],
)
def stop_quick_ping(request: Request, run_id: str) -> GroundQuickPingRunDTO:
    return _call(lambda: _service(request).quick_ping_stop(_site_id(request), run_id))


@router.post("/quick-ping/{run_id}/targets/{target_ip}/stop", response_model=GroundQuickPingRunDTO,
             dependencies=[Depends(require_feature("capability.ground_unattended.quick_ping"))])
def stop_quick_ping_target(request: Request, run_id: str, target_ip: str) -> GroundQuickPingRunDTO:
    return _call(lambda: _service(request).quick_ping_stop_target(_site_id(request), run_id, target_ip))


@router.get("/trains", response_model=GroundUnattendedTrainPageDTO)
def trains(request: Request) -> GroundUnattendedTrainPageDTO:
    return _call(lambda: _service(request).list_trains(_site_id(request)))


@router.get(
    "/mr-runtime-status", response_model=GroundMrRuntimeStatusPageDTO
)
def mr_runtime_status(
    request: Request,
    mr_role: str = Query(default="", max_length=10),
    radio_state: str = Query(default="", max_length=32),
    snmp_state: str = Query(default="", max_length=32),
) -> GroundMrRuntimeStatusPageDTO:
    return _call(
        lambda: _service(request).mr_runtime_status(
            _site_id(request),
            mr_role=mr_role,
            radio_state=radio_state,
            snmp_state=snmp_state,
        )
    )


@router.post(
    "/inventory/sync",
    response_model=GroundInventorySummaryDTO,
    dependencies=[Depends(require_feature("capability.ground_unattended.heartbeat_inventory_manage"))],
)
def sync_inventory(request: Request) -> GroundInventorySummaryDTO:
    return _call(lambda: _service(request).sync_inventory(_site_id(request)))


@router.get("/trains/{train_id}", response_model=GroundUnattendedTrainDTO)
def train(request: Request, train_id: str) -> GroundUnattendedTrainDTO:
    return _call(lambda: _service(request).get_train(_site_id(request), train_id))


@router.put("/trains/{train_id}/priority", response_model=GroundUnattendedTrainDTO)
def update_priority(
    request: Request,
    train_id: str,
    payload: GroundPriorityUpdateDTO,
) -> GroundUnattendedTrainDTO:
    return _call(
        lambda: _service(request).set_priority(
            _site_id(request), train_id, payload.priority
        )
    )


@router.put("/trains/{train_id}/policy", response_model=GroundUnattendedTrainDTO)
def update_policy(
    request: Request,
    train_id: str,
    payload: GroundTrainPolicyUpdateDTO,
) -> GroundUnattendedTrainDTO:
    return _call(
        lambda: _service(request).update_train_policy(
            _site_id(request), train_id, payload
        )
    )


@router.post(
    "/config-check",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def config_check(
    request: Request, payload: GroundConfigCheckRequestDTO
) -> GroundActionResponseDTO:
    return _call(
        lambda: _service(request).request_config_check(
            _site_id(request),
            device_uuid=payload.device_uuid,
            mode=payload.mode,
            allow_target_port_change=payload.allow_target_port_change,
            explicit_confirmation=payload.explicit_confirmation,
        )
    )


@router.get("/health", response_model=GroundHealthDTO)
def health(request: Request) -> GroundHealthDTO:
    return _call(lambda: _service(request).health(_site_id(request)))


@router.get(
    "/syslog-transport-status",
    response_model=GroundSyslogTransportStatusDTO,
)
def syslog_transport_status(request: Request) -> GroundSyslogTransportStatusDTO:
    return _call(
        lambda: _service(request).syslog_transport_status(_site_id(request))
    )


@router.get("/raw-files", response_model=GroundRawFilePageDTO)
def raw_files(
    request: Request,
    data_type: str = Query(default="", max_length=30),
    file_status: str = Query(default="", max_length=30),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> GroundRawFilePageDTO:
    return _call(
        lambda: _service(request).raw_files(
            _site_id(request),
            data_type=data_type,
            status=file_status,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/runs", response_model=GroundRunPageDTO)
def runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> GroundRunPageDTO:
    return _call(
        lambda: _service(request).runs(
            _site_id(request), limit=limit, offset=offset
        )
    )


@router.delete(
    "/runs/{run_id}",
    response_model=GroundActionResponseDTO,
)
def delete_run_history(
    request: Request,
    run_id: str,
    payload: GroundRunDeleteRequestDTO,
) -> GroundActionResponseDTO:
    return _call(
        lambda: _service(request).delete_run_history(
            _site_id(request),
            run_id,
            payload,
        )
    )


@router.post(
    "/archives/batch-delete",
    response_model=GroundArchiveBatchDeleteResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def batch_delete_archives(
    request: Request, payload: GroundArchiveBatchDeleteRequestDTO
) -> GroundArchiveBatchDeleteResponseDTO:
    return _call(
        lambda: _service(request).request_delete_archives(
            _site_id(request), payload
        )
    )


@router.get("/ping-targets", response_model=GroundPingSummaryPageDTO)
def ping_targets(
    request: Request,
    run_id: str = Query(default="", max_length=100),
) -> GroundPingSummaryPageDTO:
    return _call(
        lambda: _service(request).ping_summary(_site_id(request), run_id=run_id)
    )


@router.get("/ping-summary", response_model=GroundPingSummaryPageDTO)
def ping_summary(
    request: Request,
    run_id: str = Query(default="", max_length=100),
) -> GroundPingSummaryPageDTO:
    return _call(
        lambda: _service(request).ping_summary(_site_id(request), run_id=run_id)
    )


@router.get("/ping-series", response_model=GroundPingSeriesDTO)
def ping_series(
    request: Request,
    response: Response,
    run_id: str = Query(default="", max_length=100),
    train_id: str = Query(default="", max_length=100),
    mr_id: str = Query(default="", max_length=100),
    target_ip: str = Query(default="", max_length=100),
    query_identity: str = Query(default="", max_length=1000),
    start_time: str = Query(default="", max_length=100),
    end_time: str = Query(default="", max_length=100),
    include_warmup: bool = False,
    max_points: int = Query(default=3000, ge=10, le=10_000),
) -> GroundPingSeriesDTO:
    return _ping_query_call(
        request,
        response,
        query_kind="INITIAL",
        run_id=run_id,
        train_id=train_id,
        mr_id=mr_id,
        target_ip=target_ip,
        callback=lambda service, site_id: service.ping_series(
            site_id,
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            target_ip=target_ip,
            query_identity=query_identity,
            start_time=start_time,
            end_time=end_time,
            include_warmup=include_warmup,
            max_points=max_points,
        ),
    )


@router.get("/ping-series/incremental", response_model=GroundPingSeriesDTO)
def ping_series_incremental(
    request: Request,
    response: Response,
    run_id: str = Query(min_length=1, max_length=100),
    train_id: str = Query(default="", max_length=100),
    mr_id: str = Query(default="", max_length=100),
    target_ip: str = Query(default="", max_length=100),
    query_identity: str = Query(default="", max_length=1000),
    cursor: str = Query(default="", max_length=20_000),
    after_sequence: int | None = Query(default=None, ge=0),
    after_timestamp: str = Query(default="", max_length=100),
    include_warmup: bool = False,
    max_points: int = Query(default=200, ge=1, le=500),
) -> GroundPingSeriesDTO:
    return _ping_query_call(
        request,
        response,
        query_kind="INCREMENTAL",
        run_id=run_id,
        train_id=train_id,
        mr_id=mr_id,
        target_ip=target_ip,
        callback=lambda service, site_id: service.ping_series_incremental(
            site_id,
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            target_ip=target_ip,
            query_identity=query_identity,
            cursor=cursor,
            after_sequence=after_sequence,
            after_timestamp=after_timestamp,
            include_warmup=include_warmup,
            max_points=max_points,
        ),
    )


@router.get("/ping-samples", response_model=GroundPingSamplePageDTO)
def ping_samples(
    request: Request,
    run_id: str = Query(default="", max_length=100),
    train_id: str = Query(default="", max_length=100),
    mr_id: str = Query(default="", max_length=100),
    target_ip: str = Query(default="", max_length=100),
    query_identity: str = Query(default="", max_length=1000),
    start_time: str = Query(default="", max_length=100),
    end_time: str = Query(default="", max_length=100),
    include_warmup: bool = False,
    page: int = Query(default=1, ge=1, le=200),
    page_size: int = Query(default=100, ge=1, le=500),
) -> GroundPingSamplePageDTO:
    return _call(
        lambda: _service(request).ping_samples(
            _site_id(request),
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            target_ip=target_ip,
            query_identity=query_identity,
            start_time=start_time,
            end_time=end_time,
            include_warmup=include_warmup,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/syslog-records", response_model=GroundSyslogRecordPageDTO)
def syslog_records(
    request: Request,
    response: Response,
    run_id: str = Query(default="", max_length=100),
    train_id: str = Query(default="", max_length=100),
    mr_id: str = Query(default="", max_length=100),
    mr_name: str = Query(default="", max_length=200),
    mr_role: list[str] | None = Query(default=None),
    source_ip: str = Query(default="", max_length=100),
    system_name: str = Query(default="", max_length=200),
    facility: str = Query(default="", max_length=50),
    severity: list[str] | None = Query(default=None),
    identity_status: list[str] | None = Query(default=None),
    event_type: list[str] | None = Query(default=None),
    event_family: list[str] | None = Query(default=None),
    cfg_command_source: list[str] | None = Query(default=None),
    physical_state: list[str] | None = Query(default=None),
    correlation_status: list[str] | None = Query(default=None),
    correlation_confidence: list[str] | None = Query(default=None),
    peer_name: str = Query(default="", max_length=200),
    data_source: list[str] | None = Query(default=None),
    keyword: str = Query(default="", max_length=500),
    start_time: str = Query(default="", max_length=100),
    end_time: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1, le=200),
    page_size: int = Query(default=100, ge=1, le=500),
    sort_order: Literal["asc", "desc"] = "desc",
) -> GroundSyslogRecordPageDTO:
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    filter_values = (
        train_id,
        mr_id,
        mr_name,
        mr_role,
        source_ip,
        system_name,
        facility,
        severity,
        identity_status,
        event_type,
        event_family,
        cfg_command_source,
        physical_state,
        correlation_status,
        correlation_confidence,
        peer_name,
        data_source,
        keyword,
        start_time,
        end_time,
    )
    bound_service = getattr(
        request.app.state, "ground_unattended_application_service", None
    )
    site_id = str(getattr(bound_service, "site_id", "") or "")
    app_logger.log_info(
        "GROUND_SYSLOG_QUERY_STARTED",
        _syslog_log_detail(
            request_id=request_id,
            site_id=site_id,
            run_id=run_id,
            page=page,
            page_size=page_size,
            filter_count=sum(bool(value) for value in filter_values),
            start_time=start_time,
            end_time=end_time,
        ),
    )
    try:
        service = _service(request)
        site_id = service.current_site_id()
        result = service.syslog_records(
            site_id,
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            mr_name=mr_name,
            mr_role=mr_role or "",
            source_ip=source_ip,
            system_name=system_name,
            facility=facility,
            severity=severity or "",
            identity_status=identity_status or "",
            event_type=event_type or "",
            event_family=event_family or "",
            cfg_command_source=cfg_command_source or "",
            physical_state=physical_state or "",
            correlation_status=correlation_status or "",
            correlation_confidence=correlation_confidence or "",
            peer_name=peer_name,
            data_source=data_source or "",
            keyword=keyword,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
            sort_order=sort_order,
        )
        diagnostics = result.diagnostics
        response.headers["X-Request-ID"] = request_id
        app_logger.log_info(
            "GROUND_SYSLOG_QUERY_COMPLETED",
            _syslog_log_detail(
                request_id=request_id,
                site_id=site_id,
                run_id=run_id,
                page=page,
                page_size=page_size,
                filter_count=sum(bool(value) for value in filter_values),
                start_time=start_time,
                end_time=end_time,
                files_considered=diagnostics.files_considered,
                files_scanned=diagnostics.files_scanned,
                records_scanned=diagnostics.records_scanned,
                bytes_scanned=diagnostics.bytes_scanned,
                matched_count=result.total,
                returned_count=len(result.items),
                source_kind=diagnostics.source_kind,
                truncated=diagnostics.truncated,
                elapsed_ms=round((time.monotonic() - started) * 1000, 3),
            ),
        )
        return result
    except GroundUnattendedError as exc:
        app_logger.log_error(
            "GROUND_SYSLOG_QUERY_FAILED",
            _syslog_log_detail(
                request_id=request_id,
                site_id=site_id,
                run_id=run_id,
                page=page,
                page_size=page_size,
                filter_count=sum(bool(value) for value in filter_values),
                start_time=start_time,
                end_time=end_time,
                elapsed_ms=round((time.monotonic() - started) * 1000, 3),
                exception_type=type(exc).__name__,
            ),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        details = (
            dict(detail.get("details") or {})
            if isinstance(detail.get("details"), dict)
            else {}
        )
        details["request_id"] = request_id
        app_logger.log_error(
            "GROUND_SYSLOG_QUERY_FAILED",
            _syslog_log_detail(
                request_id=request_id,
                site_id=site_id,
                run_id=run_id,
                page=page,
                page_size=page_size,
                filter_count=sum(bool(value) for value in filter_values),
                start_time=start_time,
                end_time=end_time,
                elapsed_ms=round((time.monotonic() - started) * 1000, 3),
                exception_type=type(exc).__name__,
            ),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": str(detail.get("code") or "GROUND_SYSLOG_UNAVAILABLE"),
                "message": str(
                    detail.get("message") or "Syslog 查询服务暂时不可用"
                ),
                "details": details,
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    except Exception as exc:
        app_logger.log_error(
            "GROUND_SYSLOG_QUERY_FAILED",
            _syslog_log_detail(
                request_id=request_id,
                site_id=site_id,
                run_id=run_id,
                page=page,
                page_size=page_size,
                filter_count=sum(bool(value) for value in filter_values),
                start_time=start_time,
                end_time=end_time,
                elapsed_ms=round((time.monotonic() - started) * 1000, 3),
                exception_type=type(exc).__name__,
                traceback=traceback.format_exc(),
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "GROUND_SYSLOG_QUERY_FAILED",
                "message": "Syslog 查询失败，请使用请求编号查看 Backend 日志",
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc


@router.post(
    "/syslog-delete-preview",
    response_model=GroundSyslogDeletePreviewDTO,
)
def preview_syslog_delete(
    request: Request,
    payload: GroundSyslogDeletePreviewRequestDTO,
) -> GroundSyslogDeletePreviewDTO:
    return _call(
        lambda: _service(request).preview_syslog_delete(
            _site_id(request),
            payload,
        )
    )


@router.post(
    "/syslog-delete",
    response_model=GroundSyslogDeleteAcceptedDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_syslog_delete(
    request: Request,
    payload: GroundSyslogDeleteRequestDTO,
) -> GroundSyslogDeleteAcceptedDTO:
    return _call(
        lambda: _service(request).submit_syslog_delete(
            _site_id(request),
            payload,
        )
    )


@router.get("/timeline", response_model=GroundTimelinePageDTO)
def timeline(
    request: Request,
    run_id: str = Query(default="", max_length=100),
    train_id: str = Query(default="", max_length=100),
    event_type: str = Query(default="", max_length=100),
    query: str = Query(default="", max_length=500),
    mr_id: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", pattern="^(CT|CW)?$"),
    start_at: str = Query(default="", max_length=64),
    end_at: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> GroundTimelinePageDTO:
    return _call(
        lambda: _service(request).timeline(
            _site_id(request),
            run_id=run_id,
            train_id=train_id,
            event_type=event_type,
            query=query,
            mr_id=mr_id,
            mr_role=mr_role,
            start_at=start_at,
            end_at=end_at,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/deep-collections/tasks", response_model=GroundDeepTaskPageDTO)
def deep_tasks(
    request: Request,
    run_id: str = Query(default="", max_length=100),
    train_id: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", max_length=20),
    state: str = Query(default="", max_length=30),
    query: str = Query(default="", max_length=200),
    start_at: str = Query(default="", max_length=100),
    end_at: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    ascending: bool = False,
) -> GroundDeepTaskPageDTO:
    return _call(lambda: _service(request).deep_tasks(
        _site_id(request), run_id=run_id, train_id=train_id, mr_role=mr_role,
        state=state, query=query, start_at=start_at, end_at=end_at,
        page=page, page_size=page_size, ascending=ascending,
    ))


@router.get("/deep-collections", response_model=GroundDeepCollectionPageDTO)
def deep_collections(
    request: Request,
    run_id: str = Query(default="", max_length=100),
) -> GroundDeepCollectionPageDTO:
    return _call(
        lambda: _service(request).deep_collections(
            _site_id(request), run_id=run_id
        )
    )


@router.get("/deep-collections/records", response_model=GroundDeepCollectionRecordPageDTO)
def deep_collection_records(
    request: Request,
    run_id: str = Query(default="", max_length=100),
    train_id: str = Query(default="", max_length=100),
    mr_id: str = Query(default="", max_length=100),
    mr_role: str = Query(default="", max_length=20),
    operation_id: str = Query(default="", max_length=100),
    category: str = Query(default="ALL", max_length=30),
    keyword: str = Query(default="", max_length=500),
    cursor: str = Query(default="", max_length=20_000),
    limit: int = Query(default=200, ge=1, le=500),
) -> GroundDeepCollectionRecordPageDTO:
    return _call(
        lambda: _service(request).deep_collection_records(
            _site_id(request),
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            mr_role=mr_role,
            operation_id=operation_id,
            category=category,
            keyword=keyword,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get("/coverage", response_model=GroundDeepCollectionPageDTO)
def coverage(
    request: Request,
    run_id: str = Query(default="", max_length=100),
) -> GroundDeepCollectionPageDTO:
    return _call(
        lambda: _service(request).deep_collections(
            _site_id(request), run_id=run_id
        )
    )


@router.get("/operations/latest", response_model=GroundOperationDTO | None)
def latest_operation(request: Request) -> GroundOperationDTO | None:
    return _call(lambda: _service(request).latest_operation(_site_id(request)))


@router.get("/operations/active", response_model=GroundOperationDTO | None)
def active_operation(request: Request) -> GroundOperationDTO | None:
    return _call(lambda: _service(request).active_operation(_site_id(request)))


@router.get("/operations/{operation_id}", response_model=GroundOperationDTO)
def operation(request: Request, operation_id: str) -> GroundOperationDTO:
    return _call(
        lambda: _service(request).operation(_site_id(request), operation_id)
    )


@router.get("/archives", response_model=GroundArchivePageDTO)
def archives(request: Request, response: Response) -> GroundArchivePageDTO:
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    service = getattr(
        request.app.state, "ground_unattended_application_service", None
    )
    site_id = str(getattr(service, "site_id", "") or "")
    paths = getattr(service, "paths", None)
    site_root = str(paths.site_dir(site_id)) if paths is not None and site_id else ""
    archive_root = (
        str(paths.ground_unattended_archives_dir(site_id))
        if paths is not None and site_id
        else ""
    )
    index_path = (
        str(paths.ground_unattended_db_path(site_id))
        if paths is not None and site_id
        else ""
    )
    detail = _syslog_log_detail(
        request_id=request_id,
        site_id=site_id,
        site_root=site_root,
        archive_root=archive_root,
        index_path=index_path,
    )
    try:
        result = _service(request).archives(_site_id(request))
        response.headers["X-Request-ID"] = request_id
        app_logger.log_info(
            "GROUND_ARCHIVES_QUERY_COMPLETED",
            f"{detail} returned_count={len(result.items)} "
            f"elapsed_ms={round((time.monotonic() - started) * 1000, 3)}",
        )
        return result
    except HTTPException:
        response.headers["X-Request-ID"] = request_id
        raise
    except GroundUnattendedError as exc:
        app_logger.log_error(
            "GROUND_ARCHIVES_QUERY_FAILED",
            f"{detail} exception_type={type(exc).__name__} "
            f"failure_code={exc.code} elapsed_ms={round((time.monotonic() - started) * 1000, 3)}",
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    except Exception as exc:
        app_logger.log_error(
            "GROUND_ARCHIVES_QUERY_FAILED",
            f"{detail} exception_type={type(exc).__name__} "
            f"elapsed_ms={round((time.monotonic() - started) * 1000, 3)} "
            f"traceback={traceback.format_exc()}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "GROUND_ARCHIVES_QUERY_FAILED",
                "message": "历史归档查询失败，请使用请求编号查看 Backend 日志",
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc


@router.get("/archives/{archive_id}", response_model=GroundArchiveDTO)
def archive(request: Request, archive_id: str) -> GroundArchiveDTO:
    return _call(lambda: _service(request).archive(_site_id(request), archive_id))


@router.get(
    "/archives/{archive_id}/detail",
    response_model=GroundArchiveDetailDTO,
)
def archive_detail(
    request: Request, archive_id: str
) -> GroundArchiveDetailDTO:
    return _call(
        lambda: _service(request).archive_detail(
            _site_id(request), archive_id
        )
    )


@router.post(
    "/archives/{archive_id}/verify",
    response_model=GroundArchiveDetailDTO,
)
def verify_archive(
    request: Request, archive_id: str
) -> GroundArchiveDetailDTO:
    return _call(
        lambda: _service(request).archive_detail(
            _site_id(request), archive_id, verify=True
        )
    )


@router.get("/archives/{archive_id}/summary-download")
def download_archive_summary(request: Request, archive_id: str) -> Response:
    item = _call(lambda: _service(request).archive(_site_id(request), archive_id))
    content = (
        json.dumps(item.summary, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{item.run_date}_ground_unattended_summary.json"'
            )
        },
    )


@router.get("/artifacts/{archive_id}/download")
def download_archive_artifact(
    request: Request, archive_id: str
) -> FileResponse:
    path, file_name, size_bytes, sha256 = _call(
        lambda: _service(request).archive_artifact(
            _site_id(request), archive_id
        )
    )
    return FileResponse(
        path,
        filename=file_name,
        media_type="application/zip",
        headers={
            "Content-Length": str(size_bytes),
            "X-Content-SHA256": sha256,
        },
    )


@router.get("/artifacts/{archive_id}/summary-download")
def download_archive_summary_artifact(
    request: Request, archive_id: str
) -> Response:
    return download_archive_summary(request, archive_id)


@router.post("/archives/open-directory", response_model=DesktopActionDTO)
def open_archive_directory(request: Request) -> DesktopActionDTO:
    return _call(lambda: _service(request).open_archive_directory(_site_id(request)))


@router.delete(
    "/archives/{archive_id}",
    response_model=GroundActionResponseDTO,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_archive(
    request: Request,
    archive_id: str,
    payload: GroundArchiveDeleteRequestDTO,
) -> GroundActionResponseDTO:
    return _call(
        lambda: _service(request).request_delete_archive(
            _site_id(request),
            archive_id,
            confirmed=payload.explicit_confirmation,
        )
    )


def _ping_query_call(
    request: Request,
    response: Response,
    *,
    query_kind: str,
    run_id: str,
    train_id: str,
    mr_id: str,
    target_ip: str,
    callback,
) -> GroundPingSeriesDTO:
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    bound_service = getattr(
        request.app.state,
        "ground_unattended_application_service",
        None,
    )
    site_id = str(getattr(bound_service, "site_id", "") or "")
    base_detail = {
        "request_id": request_id,
        "query_kind": query_kind,
        "site_id": site_id,
        "run_id": run_id,
        "train_id": train_id,
        "mr_id": mr_id,
        "target_ip": target_ip,
    }
    app_logger.log_info(
        "GROUND_PING_QUERY_STARTED",
        _syslog_log_detail(**base_detail),
    )
    try:
        service = _service(request)
        site_id = service.current_site_id()
        result = callback(service, site_id)
        diagnostics = result.diagnostics
        diagnostics.request_id = request_id
        response.headers["X-Request-ID"] = request_id
        app_logger.log_info(
            "GROUND_PING_QUERY_COMPLETED",
            _syslog_log_detail(
                **{
                    **base_detail,
                    "site_id": site_id,
                    "resolved_train_ids": ",".join(
                        diagnostics.resolved_train_ids
                    ),
                    "resolved_mr_ids": ",".join(
                        diagnostics.resolved_mr_ids
                    ),
                    "files_considered": diagnostics.files_considered,
                    "files_scanned": diagnostics.files_scanned,
                    "records_scanned": diagnostics.records_scanned,
                    "matched_count": result.raw_sample_count,
                    "bytes_scanned": diagnostics.bytes_scanned,
                    "source_kind": diagnostics.source_kind,
                    "data_availability": diagnostics.data_availability,
                    "no_data_reason": diagnostics.no_data_reason,
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000,
                        3,
                    ),
                }
            ),
        )
        return result
    except GroundUnattendedError as exc:
        app_logger.log_error(
            "GROUND_PING_QUERY_FAILED",
            _syslog_log_detail(
                **{
                    **base_detail,
                    "site_id": site_id,
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000,
                        3,
                    ),
                    "exception_type": type(exc).__name__,
                    "failure_code": exc.code,
                    "traceback": traceback.format_exc(),
                }
            ),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        app_logger.log_error(
            "GROUND_PING_QUERY_FAILED",
            _syslog_log_detail(
                **{
                    **base_detail,
                    "site_id": site_id,
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000,
                        3,
                    ),
                    "exception_type": type(exc).__name__,
                    "failure_code": str(
                        detail.get("code") or "GROUND_PING_UNAVAILABLE"
                    ),
                    "traceback": traceback.format_exc(),
                }
            ),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": str(
                    detail.get("code") or "GROUND_PING_UNAVAILABLE"
                ),
                "message": str(
                    detail.get("message")
                    or "长 Ping 查询服务暂时不可用"
                ),
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    except Exception as exc:
        app_logger.log_error(
            "GROUND_PING_QUERY_FAILED",
            _syslog_log_detail(
                **{
                    **base_detail,
                    "site_id": site_id,
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000,
                        3,
                    ),
                    "exception_type": type(exc).__name__,
                    "failure_code": "GROUND_PING_QUERY_FAILED",
                    "traceback": traceback.format_exc(),
                }
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "GROUND_PING_QUERY_FAILED",
                "message": "长 Ping 查询失败，请使用请求编号查看 Backend 日志",
                "details": {"request_id": request_id},
            },
            headers={"X-Request-ID": request_id},
        ) from exc


def _call(callback):
    try:
        return callback()
    except GroundUnattendedError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def _syslog_log_detail(**values: object) -> str:
    return " ".join(
        f"{key}={str(value).replace(chr(13), chr(92) + 'r').replace(chr(10), chr(92) + 'n')}"
        for key, value in values.items()
    )


__all__ = ["router"]
