from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from netconsole.backend.api.traffic_presentation import (
    execution_target_from_request,
    traffic_run_dto,
)
from netconsole.models.api.traffic import (
    FpingStartRequest,
    IperfClientStartRequest,
    IperfServerStartRequest,
    TrafficCancelResponse,
    TrafficEventDTO,
    TrafficExecutionTargetDTO,
    TrafficPingSampleDTO,
    TrafficRetryResponse,
    TrafficRunDTO,
    TrafficStartResponse,
    TrafficSummaryDTO,
)
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import ExecutionTargetKind, HighFrequencyPingConfig, TrafficTestType
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfServerConfig
from netconsole.services.traffic.event_hub import TrafficEventStreamClosed, TrafficEventStreamOverflow
from netconsole.services.traffic.web_application_service import TrafficWebApplicationService


router = APIRouter(prefix="/traffic", tags=["traffic"])
ws_router = APIRouter(tags=["traffic"])

def traffic_web_service(request: Request) -> TrafficWebApplicationService:
    return request.app.state.traffic_web_application_service


@router.get("/execution-targets", response_model=list[TrafficExecutionTargetDTO])
def list_execution_targets(request: Request) -> list[TrafficExecutionTargetDTO]:
    return traffic_web_service(request).list_execution_targets()


@router.post("/iperf/server", response_model=TrafficStartResponse, status_code=202)
async def start_iperf_server(body: IperfServerStartRequest, request: Request) -> TrafficStartResponse:
    run = await traffic_web_service(request).start_iperf_server(
        IperfServerConfig(
            bind_ip=body.bind_ip,
            port=body.port,
            interval_seconds=body.interval_seconds,
            one_off=body.one_off,
        ),
        execution_target_from_request(body.execution_target),
        parent_task_id=body.parent_task_id,
        correlation_id=body.correlation_id,
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


@router.post("/iperf/client", response_model=TrafficStartResponse, status_code=202)
async def start_iperf_client(body: IperfClientStartRequest, request: Request) -> TrafficStartResponse:
    run = await traffic_web_service(request).start_iperf_client(
        IperfClientConfig(
            server_ip=body.server_ip,
            port=body.port,
            protocol=body.protocol,
            duration_seconds=body.duration_seconds,
            interval_seconds=body.interval_seconds,
            parallel=body.parallel,
            direction=body.direction,
            target_bandwidth=body.target_bandwidth,
            follow_collection=False,
            tcp_block_size=body.tcp_block_size,
            packet_length=body.packet_length,
            tcp_report_threshold_mbps=body.tcp_report_threshold_mbps,
            tcp_pacing_enabled=body.tcp_pacing_enabled,
            tcp_pacing_mbps=body.tcp_pacing_mbps,
            udp_bitrate_mbps=body.udp_bitrate_mbps,
            udp_report_threshold_mbps=body.udp_report_threshold_mbps,
        ),
        execution_target_from_request(body.execution_target),
        parent_task_id=body.parent_task_id,
        correlation_id=body.correlation_id,
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


@router.post("/fping", response_model=TrafficStartResponse, status_code=202)
async def start_fping(body: FpingStartRequest, request: Request) -> TrafficStartResponse:
    run = await traffic_web_service(request).start_high_frequency_ping(
        HighFrequencyPingConfig(
            targets=tuple(body.targets),
            interval_ms=body.interval_ms,
            timeout_ms=body.timeout_ms,
            packet_size=body.packet_size,
            count=body.count,
            continuous=body.continuous,
            source_address=body.source_address,
        ),
        execution_target_from_request(body.execution_target),
        parent_task_id=body.parent_task_id,
        correlation_id=body.correlation_id,
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


@router.get("/runs", response_model=list[TrafficRunDTO])
def list_runs(
    request: Request,
    run_status: list[TaskState] | None = Query(default=None, alias="status"),
    test_type: TrafficTestType | None = None,
    executor_kind: ExecutionTargetKind | None = None,
    agent_id: str | None = None,
    created_after: str = "",
    created_before: str = "",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[TrafficRunDTO]:
    page = traffic_web_service(request).list_runs(
        statuses=set(run_status or ()),
        test_type=test_type,
        executor_kind=executor_kind,
        agent_id=agent_id or None,
        created_after=created_after,
        created_before=created_before,
        offset=offset,
        limit=limit,
    )
    return [traffic_run_dto(run) for run in page.items]


@router.get("/runs/{traffic_run_id}", response_model=TrafficRunDTO)
def get_run(traffic_run_id: str, request: Request) -> TrafficRunDTO:
    return traffic_run_dto(traffic_web_service(request).require_run(traffic_run_id))


@router.get("/runs/{traffic_run_id}/summary", response_model=TrafficSummaryDTO)
def get_summary(traffic_run_id: str, request: Request) -> TrafficSummaryDTO:
    service = traffic_web_service(request)
    run = service.require_run(traffic_run_id)
    return TrafficSummaryDTO(
        traffic_run_id=traffic_run_id,
        updated_at=run.updated_at,
        summary=service.get_summary(traffic_run_id),
    )


@router.get("/runs/{traffic_run_id}/events", response_model=list[TrafficEventDTO])
def get_events(
    traffic_run_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    after_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[TrafficEventDTO]:
    cursor = after if after_sequence is None else after_sequence
    return [TrafficEventDTO.model_validate(event) for event in traffic_web_service(request).get_events(traffic_run_id, after=cursor, limit=limit)]


@router.get("/runs/{traffic_run_id}/ping-samples", response_model=list[TrafficPingSampleDTO])
def get_ping_samples(
    traffic_run_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    after_sequence: int | None = Query(default=None, ge=0),
    target: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = Query(default=1000, ge=1, le=10000),
) -> list[TrafficPingSampleDTO]:
    cursor = after if after_sequence is None else after_sequence
    return [
        ping_sample_dto(sample)
        for sample in traffic_web_service(request).get_ping_samples(
            traffic_run_id,
            after=cursor,
            target=target,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
    ]


@router.post("/runs/{traffic_run_id}/cancel", response_model=TrafficCancelResponse)
async def cancel_run(traffic_run_id: str, request: Request) -> TrafficCancelResponse:
    stopped = await traffic_web_service(request).cancel_run(traffic_run_id)
    return TrafficCancelResponse(
        traffic_run_id=stopped.traffic_run_id,
        controller_task_id=stopped.controller_task_id,
        status=stopped.status,
        message="已请求停止流量测试",
    )


@router.post("/runs/{traffic_run_id}/retry", response_model=TrafficRetryResponse, status_code=202)
async def retry_run(traffic_run_id: str, request: Request) -> TrafficRetryResponse:
    retried = await traffic_web_service(request).retry_run(traffic_run_id)
    return TrafficRetryResponse(run=traffic_run_dto(retried), retry_of_traffic_run_id=traffic_run_id)


@ws_router.websocket("/ws/traffic/{traffic_run_id}")
async def traffic_events_socket(websocket: WebSocket, traffic_run_id: str) -> None:
    service: TrafficWebApplicationService = websocket.app.state.traffic_web_application_service
    if service.get_run(traffic_run_id) is None:
        await websocket.close(code=4404, reason="traffic run not found")
        return
    try:
        last_event_sequence = max(0, int(websocket.query_params.get("after_event", "0")))
        last_sample_sequence = max(0, int(websocket.query_params.get("after_sample", "0")))
    except ValueError:
        await websocket.close(code=4400, reason="invalid traffic cursor")
        return
    await websocket.accept()
    subscription = service.events.open_stream(max_events=2_000)
    heartbeat = 0
    try:
        await websocket.send_json({"type": "ready", "traffic_run_id": traffic_run_id})
        last_event_sequence, last_sample_sequence = await _send_catchup(
            websocket,
            service,
            traffic_run_id,
            last_event_sequence,
            last_sample_sequence,
        )
        while True:
            try:
                event = await asyncio.to_thread(subscription.get, 0.5)
                if event.traffic_run_id == traffic_run_id and event.sequence > last_event_sequence:
                    last_event_sequence = event.sequence
                    await websocket.send_json({"type": "event", "event": TrafficEventDTO.model_validate(event.to_dict()).model_dump(mode="json")})
            except queue.Empty:
                pass
            except TrafficEventStreamOverflow:
                last_event_sequence, last_sample_sequence = await _send_catchup(
                    websocket,
                    service,
                    traffic_run_id,
                    last_event_sequence,
                    last_sample_sequence,
                )
            except TrafficEventStreamClosed:
                return
            last_event_sequence, last_sample_sequence = await _send_catchup(
                websocket,
                service,
                traffic_run_id,
                last_event_sequence,
                last_sample_sequence,
            )
            heartbeat += 1
            if heartbeat >= 4:
                heartbeat = 0
                await websocket.send_json({"type": "heartbeat"})
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        return
    finally:
        subscription.close()


async def _send_catchup(
    websocket: WebSocket,
    service: TrafficWebApplicationService,
    traffic_run_id: str,
    last_event_sequence: int,
    last_sample_sequence: int,
) -> tuple[int, int]:
    events = [TrafficEventDTO.model_validate(item) for item in service.get_events(traffic_run_id, after=last_event_sequence, limit=500)]
    if events:
        last_event_sequence = max(event.sequence for event in events)
        await websocket.send_json({"type": "events", "events": [event.model_dump(mode="json") for event in events]})
    samples = [ping_sample_dto(item) for item in service.get_ping_samples(traffic_run_id, after=last_sample_sequence, limit=1000)]
    if samples:
        last_sample_sequence = max(sample.sequence for sample in samples)
        await websocket.send_json({"type": "samples", "samples": [sample.model_dump(mode="json") for sample in samples]})
    return last_event_sequence, last_sample_sequence


def ping_sample_dto(sample: object) -> TrafficPingSampleDTO:
    return TrafficPingSampleDTO(
        traffic_run_id=sample.traffic_run_id,
        sequence=sample.sequence,
        timestamp=sample.timestamp,
        target=sample.target,
        probe_sequence=sample.probe_sequence,
        ok=sample.ok,
        rtt_ms=sample.rtt_ms,
        timeout=sample.timeout,
        packet_size=sample.packet_size,
        error_code=sample.error_code,
        error_message=sample.error_message,
    )
