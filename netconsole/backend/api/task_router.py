from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from netconsole.models.api.task import TaskCancelResponse, TaskDTO, TaskEventDTO
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.services.job_center.task_application_service import TaskApplicationService


router = APIRouter(tags=["tasks"])
ws_router = APIRouter(tags=["tasks"])


def task_service(request: Request) -> TaskApplicationService:
    return request.app.state.task_service


def task_dto(snapshot: TaskSnapshot) -> TaskDTO:
    return TaskDTO(
        id=snapshot.task_id,
        type=snapshot.task_type,
        name=snapshot.task_name,
        status=snapshot.status,
        progress=snapshot.progress,
        stage=snapshot.stage,
        current=snapshot.current,
        total=snapshot.total,
        message=snapshot.message,
        created_time=snapshot.created_time,
        started_time=snapshot.started_time,
        finished_time=snapshot.finished_time,
        updated_time=snapshot.updated_time,
        owner=snapshot.owner,
        device=snapshot.device,
        agent=snapshot.agent,
        result_path=snapshot.result_path,
        error_message=snapshot.error_message,
        result=snapshot.result,
        source=snapshot.source,
        cancellable=snapshot.status in {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING},
    )


@router.get("/tasks", response_model=list[TaskDTO])
def list_tasks(
    request: Request,
    task_status: list[TaskState] | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[TaskDTO]:
    snapshots = task_service(request).list_tasks(statuses=set(task_status or ()), limit=limit)
    return [task_dto(snapshot) for snapshot in snapshots]


@router.get("/tasks/{task_id}", response_model=TaskDTO)
def get_task(task_id: str, request: Request) -> TaskDTO:
    snapshot = task_service(request).get_task(task_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task_dto(snapshot)


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventDTO])
def get_task_events(
    task_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[TaskEventDTO]:
    service = task_service(request)
    if service.get_task(task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return [TaskEventDTO.model_validate(event) for event in service.list_events(task_id, after_sequence=after_sequence, limit=limit)]


@router.post("/tasks/{task_id}/cancel", response_model=TaskCancelResponse)
def cancel_task(task_id: str, request: Request) -> TaskCancelResponse:
    service = task_service(request)
    snapshot = service.get_task(task_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if not service.cancel_task(task_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务当前不可停止")
    return TaskCancelResponse(id=task_id, status=TaskState.STOPPING, message="已请求停止任务")


@ws_router.websocket("/ws/tasks")
async def task_events_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    service: TaskApplicationService = websocket.app.state.task_service
    subscription = service.events.open_stream()
    last_sequence = service.last_event_sequence()
    await websocket.send_json(
        {
            "type": "snapshot",
            "time": "",
            "payload": {
                "tasks": [task.model_dump(mode="json") for task in (task_dto(item) for item in service.list_tasks(limit=200))]
            },
        }
    )
    heartbeat = 0
    try:
        while True:
            sent_ids: set[str] = set()
            try:
                event = await asyncio.to_thread(subscription.get, 0.5)
                sent_ids.add(str(event.get("id") or ""))
                await websocket.send_json(event)
            except queue.Empty:
                pass
            for event in service.list_all_events(after_sequence=last_sequence, limit=500):
                last_sequence = max(last_sequence, int(event["sequence"]))
                if str(event.get("id") or "") in sent_ids:
                    continue
                await websocket.send_json(event)
            heartbeat += 1
            if heartbeat >= 20:
                heartbeat = 0
                await websocket.send_json({"type": "heartbeat"})
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        subscription.close()
