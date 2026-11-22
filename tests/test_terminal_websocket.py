from __future__ import annotations

import queue
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from netconsole.backend.api.terminal_router import ws_router
from netconsole.services.terminal_workspace import TerminalTicketStore


@dataclass
class _Session:
    listeners: list[queue.Queue] = field(default_factory=list)

    def subscribe(self):
        listener: queue.Queue = queue.Queue()
        listener.put({"type": "snapshot", "session": {"state": "RUNNING"}})
        self.listeners.append(listener)
        return listener

    def unsubscribe(self, listener) -> None:
        self.listeners.remove(listener)


class _Manager:
    MAX_MESSAGE_CHARS = 1024

    def __init__(self) -> None:
        self.tickets = TerminalTicketStore()
        self.session = _Session()
        self.inputs: list[str] = []
        self.sizes: list[tuple[int, int]] = []

    def get_runtime(self, session_id: str):
        if session_id != "session-a":
            raise KeyError(session_id)
        return self.session

    def refresh_activity(self, session_id: str):
        assert session_id == "session-a"
        return {"automation_write_active": False}

    def input(self, session_id: str, data: str) -> None:
        assert session_id == "session-a"
        self.inputs.append(data)

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        assert session_id == "session-a"
        self.sizes.append((cols, rows))

    def close_session(self, session_id: str) -> None:
        assert session_id == "session-a"


def _client() -> tuple[TestClient, _Manager]:
    app = FastAPI()
    manager = _Manager()
    app.state.terminal_session_manager = manager
    app.include_router(ws_router)
    return TestClient(app), manager


def test_terminal_websocket_consumes_ticket_and_accepts_control_messages() -> None:
    client, manager = _client()
    ticket = manager.tickets.issue("session-a")

    with client.websocket_connect(
        f"/ws/terminal/session-a?ticket={ticket.ticket}",
        headers={"origin": "http://testserver"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "snapshot"
        websocket.send_json({"type": "input", "data": "display version\r"})
        websocket.send_json({"type": "resize", "cols": 132, "rows": 40})
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    assert manager.inputs == ["display version\r"]
    assert manager.sizes == [(132, 40)]
    assert manager.session.listeners == []

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            f"/ws/terminal/session-a?ticket={ticket.ticket}",
            headers={"origin": "http://testserver"},
        ):
            pass
    assert exc_info.value.code == 4401


def test_terminal_websocket_rejects_non_loopback_origin() -> None:
    client, manager = _client()
    ticket = manager.tickets.issue("session-a")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            f"/ws/terminal/session-a?ticket={ticket.ticket}",
            headers={"origin": "https://evil.example"},
        ):
            pass
    assert exc_info.value.code == 4403
