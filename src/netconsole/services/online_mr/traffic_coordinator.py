from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

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
    build_iperf_client_args,
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
    iperf_status: str = "disabled"
    lock: threading.Lock = field(default_factory=threading.Lock)


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

    def force_stop_traffic_for_session(self, session_id: str) -> None:
        state = self._state(session_id)
        if state is None:
            return
        state.stop_requested.set()
        state.fping_stop.set()
        runner = state.iperf_runner
        if runner is not None:
            runner.stop("FORCED_STOPPED_BY_COLLECTION")

    def flush_traffic_outputs(self, session_id: str, *, timeout_seconds: float = 8.0) -> list[str]:
        state = self._state(session_id)
        if state is None:
            return []
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        for name, thread in (("fping", state.fping_thread), ("iperf", state.iperf_thread)):
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
        threads = (state.fping_thread, state.iperf_thread)
        if not any(thread is not None and thread.is_alive() for thread in threads):
            with self._lock:
                self._states.pop(session_id, None)
        return summary

    def get_traffic_summary(self, session_id: str) -> dict[str, object]:
        state = self._state(session_id)
        if state is None:
            return {"session_id": session_id, "fping": {"status": "not_managed"}, "iperf": {"status": "not_managed"}, "warnings": []}
        with state.lock:
            return {
                "session_id": session_id,
                "fping": {"status": state.fping_status, **state.fping_stats.as_dict()},
                "iperf": {
                    "status": state.iperf_status,
                    "run_id": state.iperf_runner.run_id if state.iperf_runner is not None else "",
                },
                "warnings": list(state.warnings),
                "flush_complete": not any(
                    thread is not None and thread.is_alive()
                    for thread in (state.fping_thread, state.iperf_thread)
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

        client = self._iperf_client_config(traffic)
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
        )
        state.iperf_runner = runner
        state.iperf_status = "running"

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

        state.iperf_thread = threading.Thread(
            target=run,
            name=f"online-mr-iperf-{state.session.meta.session_id}",
            daemon=True,
        )
        state.iperf_thread.start()

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
