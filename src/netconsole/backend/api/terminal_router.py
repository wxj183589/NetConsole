from __future__ import annotations

import asyncio
import json
import queue
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from netconsole.services.terminal_workspace import TerminalSessionManager
from netconsole.services.terminal_sftp import TerminalSftpManager


router = APIRouter(prefix="/terminal", tags=["terminal"])
ws_router = APIRouter()


class TerminalCreateRequest(BaseModel):
    device_uuid: str = Field(min_length=1, max_length=128)
    protocol: Literal["AUTO", "SSH", "TELNET"] = "AUTO"
    cols: int = Field(default=120, ge=20, le=400)
    rows: int = Field(default=32, ge=5, le=200)


class TerminalProfileValues(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    protocol: Literal["SSH", "TELNET"] = "SSH"
    username: str = Field(min_length=1, max_length=256)
    encoding: str = Field(default="utf-8", min_length=1, max_length=32)
    vendor: str = Field(default="Other", max_length=80)
    device_type: str = Field(default="Other", max_length=40)
    folder_id: str = Field(default="", max_length=32)
    favorite: bool = False


class TerminalQuickConnectRequest(TerminalProfileValues):
    password: str = Field(min_length=1, max_length=4096)
    cols: int = Field(default=120, ge=20, le=400)
    rows: int = Field(default=32, ge=5, le=200)
    save_profile: bool = False
    remember_password: bool = False


class TerminalProfileSaveRequest(TerminalProfileValues):
    password: str = Field(default="", max_length=4096)
    remember_password: bool | None = None


class TerminalProfileConnectRequest(BaseModel):
    password: str = Field(default="", max_length=4096)
    cols: int = Field(default=120, ge=20, le=400)
    rows: int = Field(default=32, ge=5, le=200)


class TerminalFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TerminalSettingsUpdateRequest(BaseModel):
    values: dict[str, Any]


class TerminalRulesReplaceRequest(BaseModel):
    rules: list[dict[str, Any]] = Field(max_length=5000)


class TerminalManualLogStartRequest(BaseModel):
    filename: str = Field(default="session", min_length=1, max_length=180)
    format: Literal["txt", "jsonl"] = "txt"


class TerminalSftpConnectRequest(BaseModel):
    device_uuid: str = Field(min_length=1, max_length=128)


class TerminalSftpPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class TerminalSftpRenameRequest(BaseModel):
    source: str = Field(min_length=1, max_length=4096)
    target: str = Field(min_length=1, max_length=4096)
    overwrite: bool = False


class TerminalSftpDeleteRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=500)
    recursive: bool = False


def _manager(request: Request | WebSocket) -> TerminalSessionManager:
    return request.app.state.terminal_session_manager


def _sftp_manager(request: Request) -> TerminalSftpManager:
    return request.app.state.terminal_sftp_manager


def _translate_error(
    exc: BaseException,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> HTTPException:
    detail = str(exc)
    for value in sensitive_values:
        secret = str(value or "")
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=detail.strip("'"))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=detail)
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=503, detail="终端服务暂时不可用")


@router.post("/sessions")
def create_session(payload: TerminalCreateRequest, request: Request) -> dict[str, Any]:
    try:
        session, ticket = _manager(request).create_session(
            payload.device_uuid,
            protocol=payload.protocol,
            cols=payload.cols,
            rows=payload.rows,
        )
        return {
            "session": session,
            "ticket": ticket.ticket,
            "ticket_expires_at_ms": ticket.expires_at_ms,
        }
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/quick-connect")
def quick_connect_session(
    payload: TerminalQuickConnectRequest,
    request: Request,
) -> dict[str, Any]:
    manager = _manager(request)
    values = payload.model_dump(
        exclude={"password", "cols", "rows", "save_profile", "remember_password"}
    )
    try:
        profile = None
        if payload.save_profile:
            profile = manager.profiles.save_profile(
                values,
                password=payload.password,
                remember_password=payload.remember_password,
            )
        session, ticket = manager.create_quick_session(
            values,
            password=payload.password,
            cols=payload.cols,
            rows=payload.rows,
        )
        return {
            "session": session,
            "ticket": ticket.ticket,
            "ticket_expires_at_ms": ticket.expires_at_ms,
            "profile": profile,
        }
    except BaseException as exc:
        raise _translate_error(exc, sensitive_values=(payload.password,)) from exc


@router.get("/profiles")
def list_terminal_profiles(request: Request) -> dict[str, Any]:
    try:
        return _manager(request).profiles.document()
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/profiles")
def create_terminal_profile(
    payload: TerminalProfileSaveRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        values = payload.model_dump(exclude={"password", "remember_password"})
        return _manager(request).profiles.save_profile(
            values,
            password=payload.password or None,
            remember_password=payload.remember_password,
        )
    except BaseException as exc:
        raise _translate_error(exc, sensitive_values=(payload.password,)) from exc


@router.put("/profiles/{profile_id}")
def update_terminal_profile(
    profile_id: str,
    payload: TerminalProfileSaveRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        values = payload.model_dump(exclude={"password", "remember_password"})
        return _manager(request).profiles.save_profile(
            values,
            profile_id=profile_id,
            password=payload.password or None,
            remember_password=payload.remember_password,
        )
    except BaseException as exc:
        raise _translate_error(exc, sensitive_values=(payload.password,)) from exc


@router.delete("/profiles/{profile_id}")
def delete_terminal_profile(profile_id: str, request: Request) -> dict[str, Any]:
    try:
        _manager(request).profiles.delete_profile(profile_id)
        return {"deleted": True, "profile_id": profile_id}
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/profiles/{profile_id}/connect")
def connect_terminal_profile(
    profile_id: str,
    payload: TerminalProfileConnectRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        session, ticket = _manager(request).create_profile_session(
            profile_id,
            password_override=payload.password,
            cols=payload.cols,
            rows=payload.rows,
        )
        return {
            "session": session,
            "ticket": ticket.ticket,
            "ticket_expires_at_ms": ticket.expires_at_ms,
        }
    except BaseException as exc:
        raise _translate_error(exc, sensitive_values=(payload.password,)) from exc


@router.post("/profile-folders")
def create_terminal_profile_folder(
    payload: TerminalFolderRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _manager(request).profiles.create_folder(payload.name)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.put("/profile-folders/{folder_id}")
def rename_terminal_profile_folder(
    folder_id: str,
    payload: TerminalFolderRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _manager(request).profiles.rename_folder(folder_id, payload.name)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.delete("/profile-folders/{folder_id}")
def delete_terminal_profile_folder(folder_id: str, request: Request) -> dict[str, Any]:
    try:
        _manager(request).profiles.delete_folder(folder_id)
        return {"deleted": True, "folder_id": folder_id}
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/sessions")
def list_sessions(request: Request) -> dict[str, Any]:
    items = _manager(request).list_active()
    return {"items": items, "total": len(items)}


@router.get("/history")
def list_history(
    request: Request,
    keyword: str = Query(default="", max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = _manager(request).history(keyword=keyword, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/history/{session_id}")
def get_history(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _manager(request).session_detail(session_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/history/{session_id}/events")
def get_history_events(
    session_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    try:
        items = _manager(request).recording_events(session_id, offset=offset, limit=limit)
        return {"items": items, "offset": offset, "limit": limit, "has_more": len(items) == limit}
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/history/{session_id}/export/{export_format}", response_class=FileResponse)
def export_history(session_id: str, export_format: str, request: Request) -> FileResponse:
    try:
        path, name = _manager(request).export_path(session_id, export_format)
        media_type = "application/x-ndjson" if name.endswith(".jsonl") else "text/plain; charset=utf-8"
        return FileResponse(path, filename=name, media_type=media_type)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/settings")
def get_terminal_settings(request: Request) -> dict[str, Any]:
    return _manager(request).settings.settings()


@router.put("/settings")
def update_terminal_settings(
    payload: TerminalSettingsUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _manager(request).settings.update_settings(payload.values)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/rules/{kind}")
def get_terminal_rules(kind: Literal["highlight", "dangerous"], request: Request) -> dict[str, Any]:
    try:
        return _manager(request).settings.rule_document(kind)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.put("/rules/{kind}")
def replace_terminal_rules(
    kind: Literal["highlight", "dangerous"],
    payload: TerminalRulesReplaceRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _manager(request).settings.replace_rules(kind, payload.rules)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/{session_id}/ticket")
def issue_ticket(session_id: str, request: Request) -> dict[str, Any]:
    try:
        ticket = _manager(request).issue_ticket(session_id)
        return {
            "ticket": ticket.ticket,
            "session_id": ticket.session_id,
            "ticket_expires_at_ms": ticket.expires_at_ms,
        }
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/{session_id}/reconnect")
def reconnect_session(session_id: str, request: Request) -> dict[str, Any]:
    try:
        session, ticket = _manager(request).reconnect(session_id)
        return {
            "session": session,
            "ticket": ticket.ticket,
            "ticket_expires_at_ms": ticket.expires_at_ms,
        }
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.delete("/sessions/{session_id}")
def close_session(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _manager(request).close_session(session_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/{session_id}/manual-log/start")
def start_manual_log(
    session_id: str,
    payload: TerminalManualLogStartRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _manager(request).start_manual_log(
            session_id,
            filename=payload.filename,
            log_format=payload.format,
        )
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/{session_id}/manual-log/pause")
def pause_manual_log(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _manager(request).pause_manual_log(session_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/{session_id}/manual-log/resume")
def resume_manual_log(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _manager(request).resume_manual_log(session_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sessions/{session_id}/manual-log/stop")
def stop_manual_log(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _manager(request).stop_manual_log(session_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get(
    "/sessions/{session_id}/manual-log/{log_id}/export",
    response_class=FileResponse,
)
def export_manual_log(session_id: str, log_id: str, request: Request) -> FileResponse:
    try:
        path, name = _manager(request).manual_log_export_path(session_id, log_id)
        media_type = "application/x-ndjson" if name.endswith(".jsonl") else "text/plain; charset=utf-8"
        return FileResponse(path, filename=name, media_type=media_type)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions")
def create_sftp_session(payload: TerminalSftpConnectRequest, request: Request) -> dict[str, Any]:
    try:
        return _sftp_manager(request).connect(payload.device_uuid)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.delete("/sftp/sessions/{session_id}")
def close_sftp_session(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _sftp_manager(request).close_session(session_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/sftp/sessions/{session_id}/entries")
def list_sftp_entries(
    session_id: str,
    request: Request,
    path: str = Query(default="", max_length=4096),
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).list_directory(session_id, path)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/directories")
def create_sftp_directory(
    session_id: str,
    payload: TerminalSftpPathRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).mkdir(session_id, payload.path)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/rename")
def rename_sftp_entry(
    session_id: str,
    payload: TerminalSftpRenameRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).rename(
            session_id,
            payload.source,
            payload.target,
            overwrite=payload.overwrite,
        )
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/move")
def move_sftp_entry(
    session_id: str,
    payload: TerminalSftpRenameRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).move(
            session_id,
            payload.source,
            payload.target,
            overwrite=payload.overwrite,
        )
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/delete")
def delete_sftp_entries(
    session_id: str,
    payload: TerminalSftpDeleteRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).delete(
            session_id,
            payload.paths,
            recursive=payload.recursive,
        )
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/copy")
def copy_sftp_entry(
    session_id: str,
    payload: TerminalSftpRenameRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).submit_copy(
            session_id,
            payload.source,
            payload.target,
            overwrite=payload.overwrite,
        )
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/download")
def download_sftp_entry(
    session_id: str,
    payload: TerminalSftpPathRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        return _sftp_manager(request).submit_download(session_id, payload.path)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/sessions/{session_id}/upload")
async def upload_sftp_entry(
    session_id: str,
    request: Request,
    remote_directory: str = Form(..., min_length=1, max_length=4096),
    overwrite: bool = Form(False),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    manager = _sftp_manager(request)
    try:
        staged, _size = await asyncio.to_thread(
            manager.stage_upload,
            str(file.filename or "upload.bin"),
            file.file,
        )
        remote_path = manager.child_path(session_id, remote_directory, staged.name)
        return manager.submit_upload(
            session_id,
            staged,
            remote_path,
            overwrite=overwrite,
        )
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/sftp/transfers")
def list_sftp_transfers(
    request: Request,
    session_id: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    items = _sftp_manager(request).list_tasks(session_id)
    return {"items": items, "total": len(items)}


@router.get("/sftp/transfers/{task_id}")
def get_sftp_transfer(task_id: str, request: Request) -> dict[str, Any]:
    try:
        return _sftp_manager(request).task(task_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/transfers/{task_id}/cancel")
def cancel_sftp_transfer(task_id: str, request: Request) -> dict[str, Any]:
    try:
        return _sftp_manager(request).cancel_task(task_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.post("/sftp/transfers/{task_id}/retry")
def retry_sftp_transfer(task_id: str, request: Request) -> dict[str, Any]:
    try:
        return _sftp_manager(request).retry_task(task_id)
    except BaseException as exc:
        raise _translate_error(exc) from exc


@router.get("/sftp/transfers/{task_id}/file", response_class=FileResponse)
def export_sftp_download(task_id: str, request: Request) -> FileResponse:
    try:
        path, name = _sftp_manager(request).download_result(task_id)
        return FileResponse(path, filename=name, media_type="application/octet-stream")
    except BaseException as exc:
        raise _translate_error(exc) from exc


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = str(websocket.headers.get("origin") or "").strip()
    host = str(websocket.headers.get("host") or "").split(":", 1)[0].casefold()
    if not origin:
        return host in {"127.0.0.1", "localhost", "testserver"}
    parsed = urlparse(origin)
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "testserver"}
        and host in {"127.0.0.1", "localhost", "testserver"}
    )


@ws_router.websocket("/ws/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str) -> None:
    if not _origin_allowed(websocket):
        await websocket.close(code=4403, reason="origin rejected")
        return
    manager = _manager(websocket)
    ticket = str(websocket.query_params.get("ticket") or "")
    if not manager.tickets.consume(ticket, session_id):
        await websocket.close(code=4401, reason="invalid or expired ticket")
        return
    try:
        manager.refresh_activity(session_id)
        session = manager.get_runtime(session_id)
    except KeyError:
        await websocket.close(code=4404, reason="session not found")
        return
    await websocket.accept()
    listener = session.subscribe()

    async def send_messages() -> None:
        while True:
            try:
                message = await asyncio.to_thread(listener.get, True, 1.0)
            except queue.Empty:
                await websocket.send_json({"type": "heartbeat"})
                continue
            await websocket.send_json(message)

    async def receive_messages() -> None:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > manager.MAX_MESSAGE_CHARS:
                await websocket.close(code=4409, reason="message too large")
                return
            try:
                message = json.loads(raw)
            except ValueError:
                await websocket.send_json({"type": "error", "code": "INVALID_MESSAGE"})
                continue
            message_type = str(message.get("type") or "")
            try:
                if message_type == "input":
                    manager.input(session_id, str(message.get("data") or ""))
                elif message_type == "resize":
                    manager.resize(
                        session_id,
                        int(message.get("cols") or 120),
                        int(message.get("rows") or 32),
                    )
                elif message_type == "close":
                    manager.close_session(session_id)
                    return
                elif message_type == "ping":
                    await websocket.send_json({"type": "pong"})
                else:
                    await websocket.send_json({"type": "error", "code": "UNKNOWN_MESSAGE_TYPE"})
            except (ValueError, RuntimeError, queue.Full):
                await websocket.send_json({"type": "error", "code": "SESSION_INPUT_REJECTED"})

    sender = asyncio.create_task(send_messages())
    receiver = asyncio.create_task(receive_messages())
    try:
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        session.unsubscribe(listener)


__all__ = ["router", "ws_router"]
