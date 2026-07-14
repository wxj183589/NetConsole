from __future__ import annotations

import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from netconsole.models.online_mr_agent import ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES


FAKE_AGENT_TOKEN = "fake-agent-test-token"


class FakeOnlineMrAgent:
    """仅监听 127.0.0.1 的正式路由 Fake Agent。"""

    def __init__(self, *, token: str = FAKE_AGENT_TOKEN) -> None:
        self.token = token
        self.agent_id = "fake-agent"
        self.task_id = "fake-task-1"
        self.session_id = "fake-session-1"
        self.package_id = "fake-package-1"
        self.status = "running"
        self.start_payload: dict[str, Any] = {}
        self.routes: list[tuple[str, str]] = []
        self.start_calls = 0
        self.stop_calls = 0
        self.status_failures_remaining = 0
        self.package_mode = "valid"
        self.package_marker = "fake raw evidence\n"
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("Fake Agent 尚未启动")
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> FakeOnlineMrAgent:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                owner._handle(self)

            def do_POST(self) -> None:  # noqa: N802
                owner._handle(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None

    def __enter__(self) -> FakeOnlineMrAgent:
        return self.start()

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        method = request.command
        path = request.path.split("?", 1)[0]
        self.routes.append((method, path))
        if request.headers.get("X-Agent-Token") != self.token:
            self._json(request, 401, error="unauthorized")
            return
        if method == "GET" and path == "/api/v1/ping":
            self._json(request, 200, {"status": "ok", "time": "2026-07-15T00:00:00Z"})
            return
        if method == "GET" and path == "/api/v1/status":
            self._json(
                request,
                200,
                {
                    "agent_id": self.agent_id,
                    "agent_name": "Loopback Fake Agent",
                    "version": "0.2.0-test",
                    "os": "windows",
                    "arch": "amd64",
                    "current_tasks": 1 if self.status == "running" else 0,
                    "task_count": 1,
                    "package_count": 1 if self.status == "completed" else 0,
                },
            )
            return
        if method == "GET" and path == "/api/v1/tools/status":
            self._json(
                request,
                200,
                {
                    "tools": {
                        "mr_collector": {"exists": True, "ready": True},
                        "fping": {"exists": True, "ready": True},
                        "iperf3": {"exists": True, "ready": True},
                    }
                },
            )
            return
        if method == "POST" and path == "/api/v1/mr/collect/start":
            self.start_calls += 1
            self.start_payload = self._body(request)
            self.status = "running"
            self._json(request, 200, self._task_payload())
            return
        if path == f"/api/v1/tasks/{self.task_id}" and method == "GET":
            if self.status_failures_remaining:
                self.status_failures_remaining -= 1
                self._json(request, 503, error="transient")
                return
            self._json(request, 200, self._task_payload())
            return
        if path == f"/api/v1/tasks/{self.task_id}/stop" and method == "POST":
            self.stop_calls += 1
            self.status = "completed"
            self._json(request, 200, self._task_payload())
            return
        if method == "GET" and path == "/api/v1/packages":
            data = [self._package_payload()] if self.status == "completed" else []
            self._json(request, 200, data)
            return
        if method == "GET" and path == f"/api/v1/packages/{self.package_id}/download":
            if self.status != "completed":
                self._json(request, 404, error="not ready")
                return
            content = (
                b"not-a-zip"
                if self.package_mode == "invalid"
                else self._package_bytes()
            )
            request.send_response(200)
            request.send_header("Content-Type", "application/zip")
            request.send_header("Content-Length", str(len(content)))
            request.end_headers()
            request.wfile.write(content)
            return
        self._json(request, 404, error="not found")

    def _task_payload(self) -> dict[str, Any]:
        params = (
            json.loads(json.dumps(self.start_payload)) if self.start_payload else {}
        )
        session = dict(params.get("session") or {})
        session["session_id"] = self.session_id
        params["session"] = session
        completed = self.status == "completed"
        return {
            "task_id": self.task_id,
            "task_type": "mr_realtime_collect",
            "status": self.status,
            "start_time": "2026-07-15T00:00:00Z",
            "end_time": "2026-07-15T00:02:00Z" if completed else "",
            "package_id": self.package_id if completed else "",
            "package_download_url": (
                f"/api/v1/packages/{self.package_id}/download" if completed else ""
            ),
            "params": params,
        }

    def _package_payload(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "task_type": "mr_realtime_collect",
            "status": "completed",
            "file_name": f"{self.package_id}.zip",
            "size": len(self._package_bytes()),
            "package_download_url": f"/api/v1/packages/{self.package_id}/download",
        }

    def _package_bytes(self) -> bytes:
        session = dict(self.start_payload.get("session") or {})
        target = dict(self.start_payload.get("target") or {})
        source_session = (
            "mismatched-session"
            if self.package_mode == "session_mismatch"
            else self.session_id
        )
        documents: dict[str, object] = {
            "session_meta.json": {
                "session_id": source_session,
                "site": session.get("site_id") or session.get("site"),
                "device_id": session.get("device_id"),
                "device_name": session.get("device_name"),
                "mr_id": session.get("mr_id"),
                "mr_name": session.get("mr_name"),
                "host": target.get("host"),
                "status": "COMPLETED",
                "started_at": "2026-07-15T00:00:00Z",
                "ended_at": "2026-07-15T00:02:00Z",
                "duration_minutes": 2.0,
                "data_integrity": "complete",
            },
            "task.json": {
                "task_id": self.task_id,
                "task_type": "mr_realtime_collect",
                "status": "completed",
                "start_time": "2026-07-15T00:00:00Z",
                "end_time": "2026-07-15T00:02:00Z",
                "params": {"target": {"host": target.get("host")}},
            },
            "manifest.json": {
                "package_type": "netconsole_agent_collect_package",
                "package_version": 1,
                "task_type": "mr_realtime_collect",
                "task_id": self.task_id,
                "agent_id": self.agent_id,
                "status": "completed",
            },
            "agent_info.json": {
                "agent_id": self.agent_id,
                "agent_name": "Loopback Fake Agent",
            },
            "system_info.json": {"os": "windows", "arch": "amd64"},
            "stop_reason.json": {"reason": "completed"},
        }
        output = io.BytesIO()
        root = f"{source_session}_fake/"
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES):
                value = documents.get(name)
                if value is not None:
                    content = json.dumps(value, ensure_ascii=False)
                elif name == "raw/collector_output_raw.log":
                    content = self.package_marker
                elif name.endswith(".json"):
                    content = "{}"
                else:
                    content = ""
                archive.writestr(root + name, content)
        return output.getvalue()

    @staticmethod
    def _body(request: BaseHTTPRequestHandler) -> dict[str, Any]:
        length = int(request.headers.get("Content-Length") or 0)
        value = json.loads(request.rfile.read(length) or b"{}")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _json(
        request: BaseHTTPRequestHandler,
        status: int,
        data: object | None = None,
        *,
        error: str = "",
    ) -> None:
        payload = (
            {"ok": True, "data": data}
            if status < 400
            else {"ok": False, "error": {"message": error or "request failed"}}
        )
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request.send_response(status)
        request.send_header("Content-Type", "application/json; charset=utf-8")
        request.send_header("Content-Length", str(len(content)))
        request.end_headers()
        request.wfile.write(content)


__all__ = ["FAKE_AGENT_TOKEN", "FakeOnlineMrAgent"]
