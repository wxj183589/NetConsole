from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
from time import monotonic
from dataclasses import dataclass
from typing import Callable, TextIO
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from netconsole.backend.api.main import DESKTOP_SESSION_HEADER, create_app
from netconsole.core.backend_instance_lock import BackendInstanceLock
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import is_packaged_runtime
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.storage_manifest import prepare_storage_manifest


_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


@dataclass(frozen=True)
class ElectronRuntimeOptions:
    host: str
    port: int
    renderer_origin: str | None = None
    development: bool = False


def parse_options(argv: list[str] | None = None) -> ElectronRuntimeOptions:
    parser = argparse.ArgumentParser(prog="netconsole-electron-backend")
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    parser.add_argument("--port", type=_valid_port, required=True)
    parser.add_argument("--renderer-origin", type=_loopback_http_origin)
    parser.add_argument("--dev-mode", action="store_true")
    values = parser.parse_args(argv)
    if values.dev_mode and is_packaged_runtime():
        parser.error("development mode is unavailable in packaged runtime")
    return ElectronRuntimeOptions(values.host, values.port, values.renderer_origin, values.dev_mode)


def read_session_token(stream: TextIO) -> str:
    raw = stream.readline(4097)
    if not raw or len(raw) > 4096:
        raise ValueError("missing or oversized Electron runtime handshake")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid Electron runtime handshake") from exc
    token = payload.get("session_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or _SESSION_TOKEN_RE.fullmatch(token) is None:
        raise ValueError("invalid Electron runtime session token")
    return token


def build_app(
    options: ElectronRuntimeOptions,
    session_token: str,
    *,
    paths: PathResolver | None = None,
    startup_stage: Callable[[str], None] | None = None,
) -> FastAPI:
    if _SESSION_TOKEN_RE.fullmatch(session_token) is None:
        raise ValueError("invalid Electron runtime session token")
    app = create_app(
        RuntimeMode.DESKTOP,
        paths=paths,
        desktop_session_token=session_token,
        rail_base_data_write_feature_enabled=True,
        rail_base_data_desktop_write_enabled=True,
        online_mr_web_control_enabled=True,
        api_documentation_enabled=options.development,
        development_api_enabled=options.development,
        development_runtime_label="electron-development" if options.development else "electron-production",
        development_frontend_mode="vite" if options.renderer_origin else "dist",
        startup_stage=startup_stage,
    )
    if options.renderer_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[options.renderer_origin],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", DESKTOP_SESSION_HEADER],
        )
    return app


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    options = parse_options(argv)
    control_stream = stdin or sys.stdin
    session_token = read_session_token(control_stream)
    started_at = monotonic()
    try:
        paths = PathResolver()
        _emit_startup_stage("paths_resolved", started_at)
        with BackendInstanceLock(paths):
            _emit_startup_stage("instance_lock_acquired", started_at)
            prepare_storage_manifest(paths)
            _emit_startup_stage("storage_manifest_ready", started_at)
            listener = socket.create_server((options.host, options.port), family=socket.AF_INET)
            actual_port = int(listener.getsockname()[1])
            try:
                _emit_startup_stage("listener_bound", started_at)
                print(
                    json.dumps(
                        {
                            "event": "netconsole.electron_backend.listening",
                            "host": options.host,
                            "port": actual_port,
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
                app = build_app(
                    options,
                    session_token,
                    paths=paths,
                    startup_stage=lambda stage: _emit_startup_stage(stage, started_at),
                )
                _emit_startup_stage("application_built", started_at)
                _emit_startup_stage("listener_ready", started_at)
                server = uvicorn.Server(
                    uvicorn.Config(
                        app,
                        host=options.host,
                        port=actual_port,
                        log_level="warning",
                        access_log=False,
                    )
                )
                control_thread = threading.Thread(
                    target=watch_control_stream,
                    args=(control_stream, server, sys.stdout, lambda: setattr(app.state, "accepting_work", False)),
                    name="netconsole-electron-control",
                    daemon=True,
                )
                control_thread.start()
                server.run(sockets=[listener])
                emit_shutdown_complete(sys.stdout)
                wait_for_exit_command(control_stream)
            finally:
                listener.close()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "netconsole.electron_backend.startup_failed",
                    "message": str(exc),
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 3
    return 0


def _emit_startup_stage(stage: str, started_at: float) -> None:
    print(
        json.dumps(
            {
                "event": "netconsole.electron_backend.startup_stage",
                "stage": stage,
                "elapsed_ms": round((monotonic() - started_at) * 1000, 3),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def watch_control_stream(
    stream: TextIO,
    server: uvicorn.Server,
    output: TextIO | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> None:
    for raw in stream:
        if len(raw) > 4096:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if payload == {"command": "shutdown"}:
            if on_shutdown is not None:
                on_shutdown()
            emit_shutdown_received(output or sys.stdout)
            server.should_exit = True
            return
    server.should_exit = True


def emit_shutdown_received(output: TextIO) -> None:
    print(
        '{"event":"netconsole.electron_backend.shutdown_received"}',
        file=output,
        flush=True,
    )


def emit_shutdown_complete(output: TextIO) -> None:
    print(
        '{"event":"netconsole.electron_backend.shutdown_complete"}',
        file=output,
        flush=True,
    )


def emit_shutdown_ack(output: TextIO) -> None:
    """Backward-compatible alias for older smoke callers."""
    emit_shutdown_complete(output)


def wait_for_exit_command(stream: TextIO) -> None:
    for raw in stream:
        if len(raw) > 4096:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if payload == {"command": "exit"}:
            return


def _valid_port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def _loopback_http_origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError("renderer origin has an invalid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError(
            "renderer origin must be an http://127.0.0.1:<port> origin"
        )
    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ElectronRuntimeOptions",
    "build_app",
    "emit_shutdown_complete",
    "emit_shutdown_ack",
    "emit_shutdown_received",
    "main",
    "parse_options",
    "read_session_token",
    "wait_for_exit_command",
    "watch_control_stream",
]
