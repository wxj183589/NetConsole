from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from netconsole.models.api.agent import (
    AgentCreateRequest,
    AgentDTO,
    AgentDeleteDTO,
    AgentEventDTO,
    AgentProbeDTO,
    AgentProbeRequest,
    AgentUpdateRequest,
)
from netconsole.models.api.common import ApiResponse
from netconsole.services.agent.controller import AgentControllerService


router = APIRouter(prefix="/agents", tags=["agents"])
ws_router = APIRouter()


def _service(request: Request) -> AgentControllerService:
    return request.app.state.agent_service


@router.get("", response_model=ApiResponse[list[AgentDTO]])
def list_agents(request: Request) -> ApiResponse[list[AgentDTO]]:
    return ApiResponse(data=[AgentDTO.model_validate(item) for item in _service(request).list_agents()])


@router.post("", response_model=ApiResponse[AgentDTO], status_code=201)
def create_agent(payload: AgentCreateRequest, request: Request) -> ApiResponse[AgentDTO]:
    item = _service(request).create_agent(
        name=payload.name,
        base_url=payload.base_url,
        enabled=payload.enabled,
        authentication_type=payload.authentication_type,
        token=_secret(payload.token),
        tags=payload.tags,
        note=payload.note,
    )
    return ApiResponse(data=AgentDTO.model_validate(item))


@router.post("/probe", response_model=ApiResponse[AgentProbeDTO])
async def probe_unsaved(payload: AgentProbeRequest, request: Request) -> ApiResponse[AgentProbeDTO]:
    result = await _service(request).probe_unsaved(
        base_url=payload.base_url,
        authentication_type=payload.authentication_type,
        token=_secret(payload.token),
    )
    return ApiResponse(data=AgentProbeDTO.model_validate(result))


@router.get("/{agent_id}", response_model=ApiResponse[AgentDTO])
def get_agent(agent_id: str, request: Request) -> ApiResponse[AgentDTO]:
    return ApiResponse(data=AgentDTO.model_validate(_service(request).get_agent(agent_id)))


@router.patch("/{agent_id}", response_model=ApiResponse[AgentDTO])
def update_agent(agent_id: str, payload: AgentUpdateRequest, request: Request) -> ApiResponse[AgentDTO]:
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, exclude={"token"})
    if "token" in payload.model_fields_set:
        changes["token"] = _secret(payload.token)
    return ApiResponse(data=AgentDTO.model_validate(_service(request).update_agent(agent_id, changes)))


@router.post("/{agent_id}/probe", response_model=ApiResponse[AgentDTO])
async def probe_agent(agent_id: str, request: Request) -> ApiResponse[AgentDTO]:
    return ApiResponse(data=AgentDTO.model_validate(await _service(request).probe_agent(agent_id, raise_on_failure=True)))


@router.post("/{agent_id}/enable", response_model=ApiResponse[AgentDTO])
def enable_agent(agent_id: str, request: Request) -> ApiResponse[AgentDTO]:
    return ApiResponse(data=AgentDTO.model_validate(_service(request).set_enabled(agent_id, True)))


@router.post("/{agent_id}/disable", response_model=ApiResponse[AgentDTO])
def disable_agent(agent_id: str, request: Request) -> ApiResponse[AgentDTO]:
    return ApiResponse(data=AgentDTO.model_validate(_service(request).set_enabled(agent_id, False)))


@router.delete("/{agent_id}", response_model=ApiResponse[AgentDeleteDTO])
def delete_agent(agent_id: str, request: Request) -> ApiResponse[AgentDeleteDTO]:
    archived = _service(request).archive_agent(agent_id)
    return ApiResponse(data=AgentDeleteDTO(agent_id=agent_id, archived=archived))


@ws_router.websocket("/ws/agents")
async def agent_events(websocket: WebSocket) -> None:
    await websocket.accept()
    service: AgentControllerService = websocket.app.state.agent_service
    subscription = service.events.subscribe_stream()
    try:
        await websocket.send_json({"type": "snapshot", "agents": service.list_agents()})
        while True:
            event = await service.events.next_event(subscription)
            if event is None:
                await websocket.send_json({"type": "heartbeat"})
            else:
                await websocket.send_json(AgentEventDTO.model_validate(event).model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        subscription.close()


def _secret(value) -> str:
    return value.get_secret_value() if value is not None else ""
