from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.ping.fping_v5_runner import run_fping_v5_json
from netconsole.core.ping.fping_v5_stats import FpingV5Stats
from netconsole.models.online_mr_models import IperfTrafficConfig, OnlineMrConnectionConfig
from netconsole.services.fping_v5 import find_fping_tool
from netconsole.services.network_tools.iperf_runner import (
    FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
    IperfClientConfig,
    IperfProcessRunner,
    IperfResultStore,
    IperfServerConfig,
    build_iperf_client_args,
    build_iperf_server_args,
    run_iperf_client_preflight,
)
from netconsole.services.network_tools.iperf_tool_service import find_iperf_tool
from netconsole.services.online_mr_session_store import OnlineMrSession


@dataclass
class _TrafficState:
    session: OnlineMrSession
    warnings: list[str] = field(default_factory=list)
    stop_requested: threading.Event = field(default_factory=threading.Event)
    fping_stop: threading.Event = field(default_factory=threading.Event)
    fping_stats: FpingV5Stats = field(default_factory=FpingV5Stats)
    fping_thread: threading.Thread | None = None
    fping_status: str = "disabled"
    iperf_runner: IperfProcessRunner | None = None
    iperf_thread: threading.Thread | None = None
    iperf_server_runner: IperfProcessRunner | None = None
    iperf_server_thread: threading.Thread | None = None
    iperf_status: str = "disabled"
    iperf_server_status: str = "disabled"
    iperf_server_ownership: str = ""
    iperf_server_metadata: dict[str, object] = field(default_factory=dict)
    iperf_error_code: str = ""
    iperf_server_lease_key: tuple[str, int] | None = None
    iperf_server_released: bool = False
    restart_count: int = 0
    restart_reason: str = ""
    iperf_bitrate_sum: float = 0.0
    iperf_bitrate_samples: int = 0
    iperf_snapshot_at: float = 0.0
    iperf_last_snapshot_status: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class _SharedIperfServer:
    key: tuple[str, int]
    runner: IperfProcessRunner
    thread: threading.Thread
    ref_count: int = 0


_SHARED_SERVER_LOCK = threading.RLock()
_SHARED_SERVERS: dict[tuple[str, int], _SharedIperfServer] = {}


class OnlineMrTrafficCoordinator:
    """管理新 Online MR 本地链路中的 fping/iPerf 生命周期，不依赖 Qt。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self._states: dict[str, _TrafficState] = {}
        self._lock = threading.RLock()

    def start_for_session(
        self,
        session: OnlineMrSession,
        config: OnlineMrConnectionConfig,
    ) -> dict[str, object]:
        session_id = session.meta.session_id
        state = _TrafficState(session=session)
        with self._lock:
            if session_id in self._states:
                return self.get_traffic_summary(session_id)
            self._states[session_id] = state

        self._start_fping(state, config)
        self._start_iperf(state, config)
        return self.get_traffic_summary(session_id)

    def stop_traffic_for_session(self, session_id: str) -> None:
        state = self._state(session_id)
        if state is None:
            return
        state.stop_requested.set()
        state.fping_stop.set()
        runner = state.iperf_runner
        if runner is not None:
            runner.stop("STOPPED_BY_COLLECTION")
        self._release_iperf_server(state, "STOPPED_BY_COLLECTION")

    def force_stop_traffic_for_session(self, session_id: str) -> None:
        state = self._state(session_id)
        if state is None:
            return
        state.stop_requested.set()
        state.fping_stop.set()
        runner = state.iperf_runner
        if runner is not None:
            runner.stop("FORCED_STOPPED_BY_COLLECTION")
        self._release_iperf_server(state, "FORCED_STOPPED_BY_COLLECTION")

    def flush_traffic_outputs(self, session_id: str, *, timeout_seconds: float = 8.0) -> list[str]:
        state = self._state(session_id)
        if state is None:
            return []
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        for name, thread in self._traffic_threads(state):
            if thread is None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(remaining)
            if thread.is_alive():
                self._warn(state, f"{name} flush 超时，原始输出完整性未知")
        return list(state.warnings)

    def finalize_traffic_outputs(self, session_id: str) -> dict[str, object]:
        summary = self.get_traffic_summary(session_id)
        state = self._state(session_id)
        if state is None:
            return summary
        threads = tuple(thread for _, thread in self._traffic_threads(state))
        if not any(thread is not None and thread.is_alive() for thread in threads):
            with self._lock:
                self._states.pop(session_id, None)
        return summary

    def get_traffic_summary(self, session_id: str) -> dict[str, object]:
        state = self._state(session_id)
        if state is None:
            return {"session_id": session_id, "fping": {"status": "not_managed"}, "iperf": {"status": "not_managed"}, "warnings": []}
        with state.lock:
            runner = state.iperf_runner
            if runner is not None and runner.last_status not in {"CREATED", "RUNNING"}:
                state.iperf_status = str(runner.last_status).lower()
            server = state.iperf_server_runner
            if server is not None and server.last_status not in {"CREATED", "RUNNING"}:
                state.iperf_server_status = str(server.last_status).lower()
            return {
                "session_id": session_id,
                "fping": {"status": state.fping_status, **state.fping_stats.as_dict()},
                "iperf": {
                    "status": state.iperf_status,
                    "client_status": state.iperf_status,
                    "server_status": state.iperf_server_status,
                    "server_ownership": state.iperf_server_ownership,
                    **self._server_snapshot_fields(state),
                    "run_id": runner.run_id if runner is not None else "",
                    **(runner.diagnostics() if runner is not None and hasattr(runner, "diagnostics") else {}),
                    "restart_count": state.restart_count,
                    "restart_reason": state.restart_reason,
                },
                "warnings": list(state.warnings),
                "flush_complete": not any(
                    thread is not None and thread.is_alive()
                    for _, thread in self._traffic_threads(state)
                ),
            }

    def _start_fping(self, state: _TrafficState, config: OnlineMrConnectionConfig) -> None:
        fping = config.fping.normalized()
        if not fping.enabled:
            state.session.write_fping_final_summary("Status: high frequency ping disabled")
            return
        if not fping.target:
            state.fping_status = "failed"
            self._warn(state, "fping target 为空")
            state.session.write_fping_final_summary("Status: failed\nReason: ping target is empty")
            return
        tool = find_fping_tool(self.paths)
        if tool is None:
            state.fping_status = "failed"
            self._warn(state, "fping v5 工具不可用")
            state.session.write_fping_final_summary("Status: failed\nReason: fping v5 tool is unavailable")
            return

        state.fping_status = "running"
        self._write_fping_snapshot(state, target=fping.target)

        def run() -> None:
            try:
                if state.stop_requested.is_set():
                    state.fping_status = "stopped"
                    return
                raw_dir = state.session.session_dir / "raw"
                for sample in run_fping_v5_json(
                    target=fping.target,
                    period_ms=fping.interval_ms,
                    timeout_ms=fping.loss_threshold_ms,
                    packet_size=fping.packet_size,
                    count_json=None,
                    output_jsonl_path=raw_dir / "fping_v5_samples.jsonl",
                    output_raw_log_path=raw_dir / "fping_v5_raw.log",
                    stop_event=state.fping_stop,
                    fping_path=tool,
                ):
                    state.fping_stats.add(sample)
                    self._write_fping_snapshot(state, target=fping.target, latest=sample.as_dict())
                state.fping_status = "stopped" if state.stop_requested.is_set() else "completed"
            except Exception as exc:
                state.fping_status = "failed"
                self._warn(state, f"fping 运行失败：{exc}")
            finally:
                stats = state.fping_stats.as_dict()
                summary = {
                    "Status": state.fping_status,
                    "target_ip": fping.target,
                    "sent": stats["sent_count"],
                    "received": stats["success_count"],
                    "lost": stats["timeout_count"],
                    "loss_percent": stats["loss_rate_percent"],
                    "min_latency_ms": stats["min_rtt_ms"],
                    "max_latency_ms": stats["max_rtt_ms"],
                    "avg_latency_ms": stats["avg_rtt_ms"],
                }
                state.session.write_fping_final_summary(json.dumps(summary, ensure_ascii=False, indent=2))
                self._write_fping_snapshot(state, target=fping.target)

        state.fping_thread = threading.Thread(
            target=run,
            name=f"online-mr-fping-{state.session.meta.session_id}",
            daemon=True,
        )
        state.fping_thread.start()

    def _start_iperf(self, state: _TrafficState, config: OnlineMrConnectionConfig) -> None:
        traffic = config.iperf.normalized()
        if not traffic.enabled:
            return
        if not traffic.server_ip:
            state.iperf_status = "failed"
            self._warn(state, "iPerf 服务端地址为空")
            return
        tool = find_iperf_tool(self.paths)
        if tool is None:
            state.iperf_status = "failed"
            self._warn(state, "iPerf3 工具不可用")
            return

        if traffic.server_ip == "127.0.0.1" and not self._ensure_loopback_iperf_server(
            state,
            tool=tool,
            port=traffic.port,
            interval_seconds=traffic.interval_seconds,
        ):
            state.iperf_status = "failed"
            self._warn(state, "本地回环 iPerf 服务端启动失败")
            self._safe_write_iperf_snapshot(state, traffic)
            return

        client = self._iperf_client_config(traffic)
        def on_line(_line: str, row: dict[str, object] | None, error: dict[str, object] | None = None) -> None:
            if row is not None and row.get("bitrate_mbps") is not None:
                with state.lock:
                    state.iperf_bitrate_sum += float(row["bitrate_mbps"])
                    state.iperf_bitrate_samples += 1
            now = time.monotonic()
            status_changed = state.iperf_status != state.iperf_last_snapshot_status
            if row is not None or error is not None or status_changed or now - state.iperf_snapshot_at >= 1.0:
                self._safe_write_iperf_snapshot(state, traffic, row=row, error=error)
                state.iperf_snapshot_at = now
                state.iperf_last_snapshot_status = state.iperf_status

        runner = IperfProcessRunner(
            tool,
            build_iperf_client_args(tool, client),
            state.session.session_dir / "raw" / "iperf_client_raw.log",
            store=IperfResultStore(state.session.db_path),
            session_id=state.session.meta.session_id,
            device_id=state.session.meta.device_id,
            config=client,
            mode="client",
            context={"source": "online_mr_application"},
            line_callback=on_line,
        )
        state.iperf_runner = runner
        state.iperf_status = "running"
        self._safe_write_iperf_snapshot(state, traffic)

        def run() -> None:
            try:
                if state.stop_requested.is_set():
                    state.iperf_status = "stopped"
                    return
                runner.start()
                state.iperf_status = str(runner.last_status or "completed").lower()
            except Exception as exc:
                state.iperf_status = "failed"
                self._warn(state, f"iPerf 运行失败：{exc}")
            finally:
                self._safe_write_iperf_snapshot(state, traffic)

        state.iperf_thread = threading.Thread(
            target=run,
            name=f"online-mr-iperf-{state.session.meta.session_id}",
            daemon=True,
        )
        state.iperf_thread.start()

    def _ensure_loopback_iperf_server(
        self,
        state: _TrafficState,
        *,
        tool,
        port: int,
        interval_seconds: int,
    ) -> bool:
        key = (str(Path(tool).resolve()), int(port))
        with _SHARED_SERVER_LOCK:
            shared = _SHARED_SERVERS.get(key)
            if shared is not None and self._runner_is_alive(shared.runner):
                shared.ref_count += 1
                self._attach_shared_server(state, shared, ownership="managed_shared")
                return True
            if shared is not None:
                _SHARED_SERVERS.pop(key, None)

        if self._is_tcp_listener("127.0.0.1", port):
            metadata = self._listener_metadata("127.0.0.1", port)
            state.iperf_server_metadata = metadata
            if self._verify_external_iperf_server(tool, port):
                state.iperf_server_status = "external_verified"
                state.iperf_server_ownership = "external_verified"
                return True
            state.iperf_server_status = "port_conflict"
            state.iperf_server_ownership = "port_conflict"
            state.iperf_error_code = "IPERF_PORT_OCCUPIED_BY_NON_IPERF"
            self._warn(state, "127.0.0.1 回环端口已被非 iPerf 进程占用")
            return False
        config = IperfServerConfig(
            bind_ip="127.0.0.1",
            port=port,
            interval_seconds=interval_seconds,
        )
        runner = IperfProcessRunner(
            tool,
            build_iperf_server_args(tool, config),
            state.session.session_dir / "raw" / "iperf_server_raw.log",
            mode="server",
            context={"source": "online_mr_application", "scope": "loopback_only"},
        )
        thread = threading.Thread(
            target=runner.start,
            name=f"online-mr-iperf-server-{state.session.meta.session_id}",
            daemon=True,
        )
        shared = _SharedIperfServer(key=key, runner=runner, thread=thread, ref_count=1)
        with _SHARED_SERVER_LOCK:
            _SHARED_SERVERS[key] = shared
        state.iperf_server_runner = runner
        state.iperf_server_thread = thread
        state.iperf_server_lease_key = key
        state.iperf_server_ownership = "managed"
        state.iperf_server_status = "starting"
        thread.start()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self._is_tcp_listener("127.0.0.1", port):
                state.iperf_server_status = "running"
                state.iperf_server_metadata = self._managed_listener_metadata(runner, tool)
                return True
            if not thread.is_alive():
                break
            time.sleep(0.05)
        with _SHARED_SERVER_LOCK:
            _SHARED_SERVERS.pop(key, None)
        runner.stop("START_FAILED")
        state.iperf_server_status = "failed"
        state.iperf_server_ownership = "port_conflict"
        state.iperf_error_code = "IPERF_SERVER_START_FAILED"
        return False

    @staticmethod
    def _runner_is_alive(runner: IperfProcessRunner) -> bool:
        process = getattr(runner, "process", None)
        if process is not None:
            try:
                return process.poll() is None
            except Exception:
                return False
        return str(getattr(runner, "last_status", "")).upper() in {"CREATED", "RUNNING"}

    def _attach_shared_server(
        self,
        state: _TrafficState,
        shared: _SharedIperfServer,
        *,
        ownership: str,
    ) -> None:
        state.iperf_server_runner = shared.runner
        state.iperf_server_thread = shared.thread
        state.iperf_server_lease_key = shared.key
        state.iperf_server_status = "running"
        state.iperf_server_ownership = ownership
        state.iperf_server_metadata = self._managed_listener_metadata(
            shared.runner,
            getattr(shared.runner, "iperf_path", Path("iperf3")),
        )
        add_mirror = getattr(shared.runner, "add_mirror_log_file", None)
        if callable(add_mirror):
            add_mirror(
                state.session.session_dir / "raw" / "iperf_server_raw.log",
                {"session_id": state.session.meta.session_id},
            )

    def _release_iperf_server(self, state: _TrafficState, reason: str) -> None:
        if state.iperf_server_released:
            return
        state.iperf_server_released = True
        key = state.iperf_server_lease_key
        if key is None:
            return
        runner_to_stop: IperfProcessRunner | None = None
        with _SHARED_SERVER_LOCK:
            shared = _SHARED_SERVERS.get(key)
            if shared is None:
                return
            shared.ref_count = max(0, shared.ref_count - 1)
            if shared.ref_count == 0:
                _SHARED_SERVERS.pop(key, None)
                runner_to_stop = shared.runner
            else:
                state.iperf_server_ownership = "managed_shared"
        if runner_to_stop is not None:
            runner_to_stop.stop(reason)

    @staticmethod
    def _verify_external_iperf_server(tool: Path, port: int) -> bool:
        result = run_iperf_client_preflight(
            tool,
            IperfClientConfig(
                server_ip="127.0.0.1",
                port=int(port),
                protocol="TCP",
                duration_seconds=1,
                interval_seconds=1,
            ),
            timeout_seconds=3.0,
        )
        return bool(result.ok)

    @staticmethod
    def _listener_metadata(host: str, port: int) -> dict[str, object]:
        metadata: dict[str, object] = {
            "listener_pid": None,
            "listener_process_name": "",
            "listener_executable": "",
            "listener_command_line": "",
            "listener_owner": "external",
            "listener_started_at": None,
        }
        if os.name != "nt":
            return metadata
        script = (
            "$c=Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 OwningProcess; if ($c) {{ $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess); "
            "$o=Invoke-CimMethod -InputObject $p -MethodName GetOwner; "
            "[pscustomobject]@{{listener_pid=[int]$c.OwningProcess; listener_process_name=$p.Name; listener_executable=$p.ExecutablePath; "
            "listener_command_line=$p.CommandLine; listener_owner=($o.Domain+'\\'+$o.User); listener_started_at=$p.CreationDate}} | ConvertTo-Json -Compress }}"
        ).format(port=int(port))
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2.0,
                check=False,
            )
            payload = json.loads(completed.stdout.strip() or "null")
            if isinstance(payload, dict):
                metadata.update(payload)
        except Exception:
            return metadata
        return metadata

    @staticmethod
    def _managed_listener_metadata(runner: IperfProcessRunner, tool: Path) -> dict[str, object]:
        process = getattr(runner, "process", None)
        pid = getattr(process, "pid", None)
        return {
            "listener_pid": int(pid) if pid else None,
            "listener_process_name": Path(str(tool)).name,
            "listener_executable": str(tool),
            "listener_command_line": " ".join(str(part) for part in getattr(runner, "command", []) or []),
            "listener_owner": os.environ.get("USERNAME") or os.environ.get("USER") or "netconsole",
            "listener_started_at": getattr(runner, "started_at", None).isoformat(sep=" ", timespec="milliseconds")
            if getattr(runner, "started_at", None)
            else None,
        }

    @staticmethod
    def _server_snapshot_fields(state: _TrafficState) -> dict[str, object]:
        runner = state.iperf_server_runner
        diagnostics = runner.diagnostics() if runner is not None and hasattr(runner, "diagnostics") else {}
        return {
            "server_pid": diagnostics.get("pid"),
            "server_parent_pid": diagnostics.get("parent_pid"),
            "server_alive": diagnostics.get("alive"),
            "server_exit_code": diagnostics.get("exit_code"),
            "server_last_error": diagnostics.get("last_error", ""),
            "server_stderr_tail": diagnostics.get("stderr_tail", ""),
            "server_last_exit_at": diagnostics.get("last_exit_at"),
            "server_last_data_at": diagnostics.get("last_data_at"),
            "server_bytes_written": diagnostics.get("bytes_written", 0),
            "server_stop_reason": diagnostics.get("stop_reason", ""),
            **state.iperf_server_metadata,
        }

    @staticmethod
    def _is_tcp_listener(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=0.15):
                return True
        except OSError:
            return False

    @staticmethod
    def _traffic_threads(state: _TrafficState) -> tuple[tuple[str, threading.Thread | None], ...]:
        return (
            ("fping", state.fping_thread),
            ("iperf", state.iperf_thread),
            ("iperf_server", state.iperf_server_thread),
        )

    @staticmethod
    def _write_fping_snapshot(
        state: _TrafficState,
        *,
        target: str,
        latest: dict[str, object] | None = None,
    ) -> None:
        state.session.write_view_snapshot(
            "live_fping_status",
            {
                "status": state.fping_status,
                "updated_at": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                "target": target,
                "summary": state.fping_stats.as_dict(),
                "latest": latest or {},
            },
        )

    @staticmethod
    def _write_iperf_snapshot(
        state: _TrafficState,
        config: IperfTrafficConfig,
        *,
        row: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> None:
        normalized = config.normalized()
        runner = state.iperf_runner
        diagnostics = runner.diagnostics() if runner is not None and hasattr(runner, "diagnostics") else {}
        state.session.write_view_snapshot(
            "live_iperf_status",
            {
                "status": state.iperf_status,
                "client_status": state.iperf_status,
                "server_status": state.iperf_server_status,
                "supervisor_status": "running" if state.iperf_status in {"running", "starting"} else state.iperf_status,
                "updated_at": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
                "server_ip": normalized.server_ip,
                "port": normalized.port,
                "protocol": normalized.protocol,
                "target_bandwidth": normalized.target_bandwidth,
                "bitrate_mbps": row.get("bitrate_mbps") if row else None,
                "average_bitrate_mbps": (
                    state.iperf_bitrate_sum / state.iperf_bitrate_samples
                    if state.iperf_bitrate_samples
                    else None
                ),
                "role": row.get("role") if row else None,
                "error_code": error.get("error_code") if error else "",
                "last_error": error.get("error_message") if error else diagnostics.get("last_error", ""),
                "restart_count": state.restart_count,
                "restart_reason": state.restart_reason,
                "server_ownership": state.iperf_server_ownership,
                "server_error_code": state.iperf_error_code,
                **OnlineMrTrafficCoordinator._server_snapshot_fields(state),
                **diagnostics,
            },
        )

    @staticmethod
    def _safe_write_iperf_snapshot(
        state: _TrafficState,
        config: IperfTrafficConfig,
        *,
        row: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
    ) -> None:
        try:
            OnlineMrTrafficCoordinator._write_iperf_snapshot(state, config, row=row, error=error)
        except Exception as exc:
            OnlineMrTrafficCoordinator._warn(
                state,
                f"iPerf 状态快照写入失败，已降级继续运行：{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _iperf_client_config(config: IperfTrafficConfig) -> IperfClientConfig:
        duration = config.duration_seconds or 10
        if config.follow_collection:
            duration = FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS
        return IperfClientConfig(
            server_ip=config.server_ip,
            port=config.port,
            protocol=config.protocol,
            duration_seconds=duration,
            interval_seconds=config.interval_seconds,
            parallel=config.parallel,
            direction=config.direction,
            target_bandwidth=config.target_bandwidth,
            follow_collection=config.follow_collection,
            tcp_block_size=config.tcp_block_size,
            packet_length=config.packet_length,
            tcp_report_threshold_mbps=config.tcp_report_threshold_mbps,
            tcp_pacing_enabled=config.tcp_pacing_enabled,
            tcp_pacing_mbps=config.tcp_pacing_mbps,
            udp_bitrate_mbps=config.udp_bitrate_mbps,
            udp_report_threshold_mbps=config.udp_report_threshold_mbps,
            debug_output_enabled=config.debug_output_enabled,
        ).normalized()

    def _state(self, session_id: str) -> _TrafficState | None:
        with self._lock:
            return self._states.get(str(session_id or ""))

    @staticmethod
    def _warn(state: _TrafficState, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        with state.lock:
            if text not in state.warnings:
                state.warnings.append(text)


__all__ = ["OnlineMrTrafficCoordinator"]
