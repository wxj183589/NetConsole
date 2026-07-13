from __future__ import annotations

import asyncio
import queue
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from netconsole.models.agent import AgentStatus
from netconsole.models.api.traffic import (
    FpingStartRequest,
    IperfClientStartRequest,
    IperfServerStartRequest,
    TrafficCancelResponse,
    TrafficEventDTO,
    TrafficExecutionTargetDTO,
    TrafficExecutionTargetRequest,
    TrafficPingSampleDTO,
    TrafficRetryResponse,
    TrafficRunDTO,
    TrafficStartResponse,
    TrafficSummaryDTO,
)
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import ExecutionTargetDTO, ExecutionTargetKind, HighFrequencyPingConfig, TrafficTestType
from netconsole.services.agent.controller import AgentControllerService
from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfServerConfig
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError
from netconsole.services.traffic.event_hub import TrafficEventStreamClosed, TrafficEventStreamOverflow


router = APIRouter(prefix="/traffic", tags=["traffic"])
ws_router = APIRouter(tags=["traffic"])

_ACTIVE_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING}


def traffic_service(request: Request) -> TrafficTestApplicationService:
    return request.app.state.traffic_service


def agent_service(request: Request) -> AgentControllerService:
    return request.app.state.agent_service


@router.get("/execution-targets", response_model=list[TrafficExecutionTargetDTO])
def list_execution_targets(request: Request) -> list[TrafficExecutionTargetDTO]:
    targets = [
        TrafficExecutionTargetDTO(
            kind=ExecutionTargetKind.LOCAL,
            id="LOCAL",
            display_name="本机",
            capabilities={"iperf_server": True, "iperf_client": True, "fping": True},
        )
    ]
    for agent in agent_service(request).list_agents():
        capabilities = dict(agent.get("capabilities") or {})
        available, reason = _agent_availability(agent, capabilities)
        targets.append(
            TrafficExecutionTargetDTO(
                kind=ExecutionTargetKind.AGENT,
                id=str(agent.get("agent_id") or ""),
                agent_id=str(agent.get("agent_id") or ""),
                display_name=str(agent.get("name") or agent.get("agent_id") or "Agent"),
                available=available,
                unavailable_reason=reason,
                status=str(agent.get("status") or ""),
                platform=str(agent.get("platform") or ""),
                architecture=str(agent.get("architecture") or ""),
                version=str(agent.get("version") or ""),
                capabilities=capabilities,
            )
        )
    return targets


@router.post("/iperf/server", response_model=TrafficStartResponse, status_code=202)
async def start_iperf_server(body: IperfServerStartRequest, request: Request) -> TrafficStartResponse:
    run = await traffic_service(request).start_iperf_server(
        IperfServerConfig(
            bind_ip=body.bind_ip,
            port=body.port,
            interval_seconds=body.interval_seconds,
            one_off=body.one_off,
        ),
        _execution_target(body.execution_target),
        parent_task_id=body.parent_task_id,
        correlation_id=body.correlation_id,
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


@router.post("/iperf/client", response_model=TrafficStartResponse, status_code=202)
async def start_iperf_client(body: IperfClientStartRequest, request: Request) -> TrafficStartResponse:
    run = await traffic_service(request).start_iperf_client(
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
        _execution_target(body.execution_target),
        parent_task_id=body.parent_task_id,
        correlation_id=body.correlation_id,
    )
    return TrafficStartResponse(run=traffic_run_dto(run))


@router.post("/fping", response_model=TrafficStartResponse, status_code=202)
async def start_fping(body: FpingStartRequest, request: Request) -> TrafficStartResponse:
    run = await traffic_service(request).start_high_frequency_ping(
        HighFrequencyPingConfig(
            targets=tuple(body.targets),
            interval_ms=body.interval_ms,
            timeout_ms=body.timeout_ms,
            packet_size=body.packet_size,
            count=body.count,
            continuous=body.continuous,
            source_address=body.source_address,
        ),
        _execution_target(body.execution_target),
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
    fetch_limit = min(2_000, offset + limit)
    runs = traffic_service(request).list_runs(
        statuses=set(run_status or ()),
        test_type=test_type,
        executor_kind=executor_kind,
        agent_id=agent_id or None,
        limit=fetch_limit,
    )
    if created_after:
        runs = [run for run in runs if run.created_at >= created_after]
    if created_before:
        runs = [run for run in runs if run.created_at <= created_before]
    return [traffic_run_dto(run) for run in runs[offset : offset + limit]]


@router.get("/runs/{traffic_run_id}", response_model=TrafficRunDTO)
def get_run(traffic_run_id: str, request: Request) -> TrafficRunDTO:
    return traffic_run_dto(_require_run(traffic_service(request), traffic_run_id))


@router.get("/runs/{traffic_run_id}/summary", response_model=TrafficSummaryDTO)
def get_summary(traffic_run_id: str, request: Request) -> TrafficSummaryDTO:
    run = _require_run(traffic_service(request), traffic_run_id)
    return TrafficSummaryDTO(
        traffic_run_id=traffic_run_id,
        updated_at=run.updated_at,
        summary=traffic_service(request).get_summary(traffic_run_id),
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
    return [TrafficEventDTO.model_validate(event) for event in traffic_service(request).get_events(traffic_run_id, after=cursor, limit=limit)]


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
        for sample in traffic_service(request).get_ping_samples(
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
    service = traffic_service(request)
    run = _require_run(service, traffic_run_id)
    stopped = await service.cancel(run.controller_task_id)
    return TrafficCancelResponse(
        traffic_run_id=stopped.traffic_run_id,
        controller_task_id=stopped.controller_task_id,
        status=stopped.status,
        message="已请求停止流量测试",
    )


@router.post("/runs/{traffic_run_id}/retry", response_model=TrafficRetryResponse, status_code=202)
async def retry_run(traffic_run_id: str, request: Request) -> TrafficRetryResponse:
    service = traffic_service(request)
    run = _require_run(service, traffic_run_id)
    retried = await service.retry(run.controller_task_id)
    return TrafficRetryResponse(run=traffic_run_dto(retried), retry_of_traffic_run_id=traffic_run_id)


@ws_router.websocket("/ws/traffic/{traffic_run_id}")
async def traffic_events_socket(websocket: WebSocket, traffic_run_id: str) -> None:
    service: TrafficTestApplicationService = websocket.app.state.traffic_service
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
    service: TrafficTestApplicationService,
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


def traffic_run_dto(run: object) -> TrafficRunDTO:
    return TrafficRunDTO(
        id=run.traffic_run_id,
        traffic_run_id=run.traffic_run_id,
        controller_task_id=run.controller_task_id,
        test_type=run.test_type,
        role=run.role,
        executor_kind=run.executor_kind,
        agent_id=run.agent_id,
        normalized_config=dict(run.normalized_config),
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        updated_at=run.updated_at,
        summary=dict(run.summary),
        error_code=run.error_code,
        error_message=run.error_message,
        raw_reference=_public_reference(run.raw_reference),
        result_reference=_public_reference(run.result_reference),
        retry_of_traffic_run_id=run.retry_of_traffic_run_id,
        parent_task_id=run.parent_task_id,
        correlation_id=run.correlation_id,
        last_event_sequence=run.last_event_sequence,
        sync_state=run.sync_state,
        cancellable=run.status in _ACTIVE_STATES,
    )


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


def _execution_target(value: TrafficExecutionTargetRequest) -> ExecutionTargetDTO:
    try:
        return ExecutionTargetDTO(
            kind=value.kind,
            agent_id=value.agent_id.strip(),
            display_name=value.display_name.strip(),
        )
    except ValueError as exc:
        raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, str(exc)) from exc


def _require_run(service: TrafficTestApplicationService, traffic_run_id: str) -> object:
    run = service.get_run(traffic_run_id)
    if run is None:
        raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
    return run


def _agent_availability(agent: dict[str, object], capabilities: dict[str, object]) -> tuple[bool, str]:
    if not bool(agent.get("enabled")):
        return False, "Agent 已禁用"
    status = str(agent.get("status") or AgentStatus.UNKNOWN.value)
    if status == AgentStatus.UNAUTHORIZED.value:
        return False, "Agent 认证失败或 Token 未加载"
    if status != AgentStatus.ONLINE.value:
        return False, "Agent 当前不在线"
    if not any(bool(capabilities.get(key)) for key in ("iperf_server", "iperf_client", "fping")):
        return False, "Agent 未报告流量测试能力"
    return True, ""


def _public_reference(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.casefold().startswith("file://") or PureWindowsPath(text).is_absolute() or PurePosixPath(text).is_absolute():
        return ""
    return text
