from __future__ import annotations

import argparse
import json
import os
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
from netconsole.core.runtime_profile import read_host_environment_profile


_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_WARM_HANDOFF_OWNER_RE = re.compile(r"^[a-f0-9]{32}$")


@dataclass(frozen=True)
class ElectronRuntimeOptions:
    host: str
    port: int
    renderer_origin: str | None = None
    development: bool = False


@dataclass(frozen=True)
class ElectronRuntimeHandshake:
    session_token: str
    warm_handoff_owner_id: str = ""


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


def read_runtime_handshake(stream: TextIO) -> ElectronRuntimeHandshake:
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
    owner_id = payload.get("warm_handoff_owner_id", "") if isinstance(payload, dict) else ""
    if not isinstance(owner_id, str) or (owner_id and _WARM_HANDOFF_OWNER_RE.fullmatch(owner_id) is None):
        raise ValueError("invalid Electron runtime warm handoff owner")
    return ElectronRuntimeHandshake(token, owner_id)


def read_session_token(stream: TextIO) -> str:
    return read_runtime_handshake(stream).session_token


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
    handshake = read_runtime_handshake(control_stream)
    session_token = handshake.session_token
    started_at = monotonic()
    try:
        _emit_startup_stage("paths_resolving", started_at)
        paths = PathResolver()
        _emit_startup_stage("paths_resolved", started_at)
        _log_host_environment_summary(paths)
        _emit_startup_stage("instance_lock_acquiring", started_at)
        active_site_id = str(os.environ.get("NETCONSOLE_ACTIVE_SITE_ID") or "").strip()
        with BackendInstanceLock(
            paths,
            active_site_id=active_site_id,
            warm_handoff_owner_id=handshake.warm_handoff_owner_id,
        ) as instance_lock:
            _emit_startup_stage("instance_lock_acquired", started_at)
            if getattr(instance_lock, "warm_handoff", False):
                _emit_startup_stage("storage_manifest_reused", started_at)
            else:
                _emit_startup_stage("storage_manifest_preparing", started_at)
                prepare_storage_manifest(paths)
                _emit_startup_stage("storage_manifest_ready", started_at)
            _emit_startup_stage("listener_binding", started_at)
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
                _emit_startup_stage("application_building", started_at)
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
                    args=(control_stream, server, sys.stdout, lambda: _begin_runtime_shutdown(app, sys.stdout)),
                    name="netconsole-electron-control",
                    daemon=True,
                )
                control_thread.start()
                server.run(sockets=[listener])
                _stop_shutdown_progress_monitor(app)
                _emit_shutdown_progress_from_app(app, sys.stdout, "persistence_draining")
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


def _begin_runtime_shutdown(app: FastAPI, output: TextIO) -> None:
    """Close task admission before uvicorn starts lifespan teardown."""
    app.state.accepting_work = False
    begin_shutdown = getattr(app.state, "task_service", None)
    begin_shutdown = getattr(begin_shutdown, "begin_shutdown", None)
    snapshot = begin_shutdown() if callable(begin_shutdown) else {}
    emit_shutdown_progress(
        output,
        "draining_tasks",
        active_tasks=snapshot.get("active_tasks") if isinstance(snapshot, dict) else None,
        active_workers=snapshot.get("active_workers") if isinstance(snapshot, dict) else None,
    )
    _start_shutdown_progress_monitor(
        app,
        output,
        initial_snapshot=snapshot if isinstance(snapshot, dict) else None,
    )


def _start_shutdown_progress_monitor(
    app: FastAPI,
    output: TextIO,
    *,
    initial_snapshot: dict[str, object] | None = None,
) -> None:
    if getattr(app.state, "shutdown_progress_thread", None) is not None:
        return
    stop_event = threading.Event()
    app.state.shutdown_progress_stop = stop_event

    def monitor() -> None:
        previous: tuple[int | None, int | None] | None = (
            (
                initial_snapshot.get("active_tasks"),
                initial_snapshot.get("active_workers"),
            )
            if initial_snapshot is not None
            else None
        )
        while not stop_event.wait(0.2):
            snapshot_factory = getattr(getattr(app.state, "task_service", None), "active_task_snapshot", None)
            snapshot = snapshot_factory() if callable(snapshot_factory) else {}
            if not isinstance(snapshot, dict):
                continue
            counts = (
                snapshot.get("active_tasks"),
                snapshot.get("active_workers"),
            )
            if counts == previous:
                continue
            previous = counts
            emit_shutdown_progress(
                output,
                "draining_tasks",
                active_tasks=counts[0],
                active_workers=counts[1],
            )

    thread = threading.Thread(
        target=monitor,
        name="netconsole-shutdown-progress",
        daemon=True,
    )
    app.state.shutdown_progress_thread = thread
    thread.start()


def _stop_shutdown_progress_monitor(app: FastAPI) -> None:
    stop_event = getattr(app.state, "shutdown_progress_stop", None)
    thread = getattr(app.state, "shutdown_progress_thread", None)
    if stop_event is None:
        return
    stop_event.set()
    if isinstance(thread, threading.Thread) and thread is not threading.current_thread():
        thread.join(timeout=1.0)
    app.state.shutdown_progress_stop = None
    app.state.shutdown_progress_thread = None


def _log_host_environment_summary(paths: PathResolver) -> None:
    """Profile reads are advisory; never trigger synchronous hardware discovery."""
    profile = read_host_environment_profile(paths.host_environment_profile_path)
    if profile is None:
        return
    try:
        def value(group: object, key: str) -> object:
            item = getattr(group, "get", lambda *_: None)(key)
            return getattr(item, "value", "unknown")

        print(
            "HOST_ENVIRONMENT "
            f"os={value(profile.os, 'platform')} "
            f"cpu_logical={value(profile.cpu, 'logical_processors')} "
            f"memory_bytes={value(profile.memory, 'bytes')} "
            f"virtualization={value(profile.virtualization, 'status')}",
            file=sys.stderr,
            flush=True,
        )
        print(
            "STORAGE_ENVIRONMENT "
            f"volume={value(profile.storage, 'volume')} "
            f"media={value(profile.storage, 'media_type')} "
            f"hardware_raid={value(profile.storage, 'hardware_raid')} "
            f"raid_level={value(profile.storage, 'raid_level')}",
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        return


def _emit_shutdown_progress_from_app(app: FastAPI, output: TextIO, phase: str) -> None:
    snapshot_factory = getattr(getattr(app.state, "task_service", None), "active_task_snapshot", None)
    snapshot = snapshot_factory() if callable(snapshot_factory) else {}
    emit_shutdown_progress(
        output,
        phase,
        active_tasks=snapshot.get("active_tasks") if isinstance(snapshot, dict) else None,
        active_workers=snapshot.get("active_workers") if isinstance(snapshot, dict) else None,
    )


def emit_shutdown_received(output: TextIO) -> None:
    print(
        '{"event":"netconsole.electron_backend.shutdown_received"}',
        file=output,
        flush=True,
    )


def emit_shutdown_progress(
    output: TextIO,
    phase: str,
    *,
    active_tasks: int | None = None,
    active_workers: int | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": "netconsole.electron_backend.shutdown_progress",
        "phase": str(phase),
    }
    if active_tasks is not None:
        payload["active_tasks"] = max(0, int(active_tasks))
    if active_workers is not None:
        payload["active_workers"] = max(0, int(active_workers))
    print(json.dumps(payload, separators=(",", ":")), file=output, flush=True)


def emit_shutdown_complete(output: TextIO) -> None:
    print(
        '{"event":"netconsole.electron_backend.shutdown_complete"}',
        file=output,
        flush=True,
    )


def emit_shutdown_ack(output: TextIO) -> None:
    """Legacy command-receipt signal; it never proves lifespan completion."""
    print(
        '{"event":"netconsole.electron_backend.shutdown_ack"}',
        file=output,
        flush=True,
    )


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
    "ElectronRuntimeHandshake",
    "build_app",
    "emit_shutdown_complete",
    "emit_shutdown_ack",
    "emit_shutdown_received",
    "emit_shutdown_progress",
    "main",
    "parse_options",
    "read_runtime_handshake",
    "read_session_token",
    "wait_for_exit_command",
    "watch_control_stream",
]
