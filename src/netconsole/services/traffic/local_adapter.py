from __future__ import annotations

import hashlib
import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.core.ping.fping_v5_runner import check_fping_v5_available, run_fping_v5_json
from netconsole.core.ping.fping_v5_stats import FpingV5Stats
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficEvent,
    TrafficEventType,
    TrafficPingSample,
    TrafficRun,
    TrafficSyncState,
    TrafficTestType,
    TcpPortTestConfig,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.network_tools.iperf_runner import (
    IperfClientConfig,
    IperfProcessRunner,
    IperfResultStore,
    IperfServerConfig,
    build_iperf_client_args,
    build_iperf_server_args,
    run_iperf_client_preflight,
)
from netconsole.services.network_tools.toolbox.ping_tools import run_tcp_ping
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError
from netconsole.services.traffic.event_hub import TrafficEventHub
from netconsole.services.traffic.event_store import TrafficEventStore
from netconsole.services.tool_path_resolver import resolve_network_tool


TASK_IPERF_SERVER = "traffic_local_iperf_server"
TASK_IPERF_CLIENT = "traffic_local_iperf_client"
TASK_FPING = "traffic_local_fping"
TASK_TCP_PORT_TEST = "traffic_local_tcp_port_test"
_TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
_TERMINAL_STATE_VALUES = {state.value for state in _TERMINAL_STATES}


@dataclass
class _IperfSummary:
    sample_count: int = 0
    bitrate_sum: float = 0.0
    min_bitrate_mbps: float | None = None
    max_bitrate_mbps: float | None = None
    retransmits: int = 0
    last_jitter_ms: float | None = None
    last_loss_percent: float | None = None

    def add(self, row: dict[str, object]) -> None:
        bitrate = row.get("bitrate_mbps")
        if bitrate is not None:
            value = float(bitrate)
            self.sample_count += 1
            self.bitrate_sum += value
            self.min_bitrate_mbps = value if self.min_bitrate_mbps is None else min(self.min_bitrate_mbps, value)
            self.max_bitrate_mbps = value if self.max_bitrate_mbps is None else max(self.max_bitrate_mbps, value)
        if row.get("retransmits") is not None:
            self.retransmits += int(row["retransmits"])
        if row.get("jitter_ms") is not None:
            self.last_jitter_ms = float(row["jitter_ms"])
        if row.get("loss_percent") is not None:
            self.last_loss_percent = float(row["loss_percent"])

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.sample_count,
            "average_bitrate_mbps": self.bitrate_sum / self.sample_count if self.sample_count else None,
            "min_bitrate_mbps": self.min_bitrate_mbps,
            "max_bitrate_mbps": self.max_bitrate_mbps,
            "retransmits": self.retransmits,
            "last_jitter_ms": self.last_jitter_ms,
            "last_loss_percent": self.last_loss_percent,
        }


class LocalTrafficAdapter:
    """本地 Traffic Controller 提交器与 Worker 领域执行适配器。

    Controller 仅提交已有 Job Center Worker；Worker 直接写 TrafficEventStore。
    高频样本不会通过 Job stdout 或全局 TaskEventHub。
    """

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_name: str = "demo",
        process_adapter: LocalProcessAdapter | None = None,
        repository: TrafficRunRepository | None = None,
        event_store: TrafficEventStore | None = None,
        event_hub: TrafficEventHub | None = None,
        tail_interval_seconds: float = 0.1,
    ) -> None:
        self.paths = paths
        self.site_name = str(site_name or "demo")
        self.process_adapter = process_adapter
        self.repository = repository or TrafficRunRepository(paths.traffic_runs_db_path(self.site_name))
        self.event_store = event_store or TrafficEventStore(paths, self.repository, self.site_name)
        self.event_hub = event_hub
        self._tail_interval_seconds = max(0.02, float(tail_interval_seconds))
        self._tail_runs: dict[str, int] = {}
        self._tail_terminal_seen: set[str] = set()
        self._tail_lock = threading.RLock()
        self._completion_lock = threading.RLock()
        self._tail_stop = threading.Event()
        self._tail_thread: threading.Thread | None = None

    # Controller-side submission -------------------------------------------------

    def start_iperf_server(self, run: TrafficRun, config: IperfServerConfig) -> str:
        self._validate_run(run, TrafficTestType.IPERF_SERVER)
        return self._submit(
            run,
            TASK_IPERF_SERVER,
            _server_config_dict(config),
            "iPerf 服务端",
            cancel_grace_ms=5_000,
        )

    def start_iperf_client(self, run: TrafficRun, config: IperfClientConfig) -> str:
        self._validate_run(run, TrafficTestType.IPERF_CLIENT)
        return self._submit(
            run,
            TASK_IPERF_CLIENT,
            _client_config_dict(config),
            "iPerf 客户端",
            cancel_grace_ms=5_000,
        )

    def start_high_frequency_ping(self, run: TrafficRun, config: HighFrequencyPingConfig) -> str:
        self._validate_run(run, TrafficTestType.HIGH_FREQUENCY_PING)
        normalized = config.normalized()
        grace_ms = min(60_000, max(5_000, normalized.timeout_ms + 3_000))
        return self._submit(run, TASK_FPING, normalized.to_dict(), "高频 Ping", cancel_grace_ms=grace_ms)

    def start_tcp_port_test(self, run: TrafficRun, config: TcpPortTestConfig) -> str:
        self._validate_run(run, TrafficTestType.TCP_PORT_TEST)
        normalized = config.normalized()
        return self._submit(
            run,
            TASK_TCP_PORT_TEST,
            normalized.to_dict(),
            "TCP 端口测试",
            cancel_grace_ms=min(60_000, max(5_000, normalized.timeout_ms + 3_000)),
        )

    def cancel(self, controller_task_id: str) -> bool:
        if self.process_adapter is None:
            return False
        with self._completion_lock:
            run = self.repository.get_by_controller_task(controller_task_id)
            if run is None or run.status in _TERMINAL_STATES:
                return False
            if run.status is not TaskState.STOPPING:
                now = utc_now_iso()
                self.repository.save(replace(run, status=TaskState.STOPPING, updated_at=now))
                self._append_event(
                    run.traffic_run_id,
                    TrafficEventType.STATE,
                    {"state": TaskState.STOPPING.value, "message": "正在停止本地流量任务"},
                )
            accepted = self.process_adapter.cancel_job(controller_task_id)
            if not accepted:
                self._finish_cancelled(run.traffic_run_id, message="本地 Worker 已结束")
            return accepted

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        if self.process_adapter is not None:
            self.process_adapter.shutdown(timeout_seconds=timeout_seconds)
        for _index in range(20):
            with self._tail_lock:
                before = dict(self._tail_runs)
            self._drain_tail_once()
            with self._tail_lock:
                if self._tail_runs == before:
                    break
        self.stop_event_tail()

    def start_event_tail(self) -> None:
        if self.event_hub is None:
            return
        with self._tail_lock:
            if self._tail_thread is not None and self._tail_thread.is_alive():
                return
            self._tail_stop.clear()
            self._tail_thread = threading.Thread(
                target=self._tail_loop,
                name="local-traffic-event-tail",
                daemon=True,
            )
            self._tail_thread.start()

    def stop_event_tail(self) -> None:
        self._tail_stop.set()
        with self._tail_lock:
            thread = self._tail_thread
            self._tail_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self._tail_interval_seconds * 4))

    def _submit(
        self,
        run: TrafficRun,
        task_type: str,
        config: dict[str, object],
        task_name: str,
        *,
        cancel_grace_ms: int,
    ) -> str:
        if self.process_adapter is None:
            raise RuntimeError("本地 Traffic Adapter 缺少 LocalProcessAdapter")
        params = {
            "traffic_run_id": run.traffic_run_id,
            "controller_task_id": run.controller_task_id,
            "site_name": self.site_name,
            "task_name": task_name,
            "task_source": "local",
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "config": dict(config),
            "_cancel_grace_ms": max(0, int(cancel_grace_ms)),
        }
        job_id = self.process_adapter.start_job(
            BackgroundJob(job_id=run.controller_task_id, task_type=task_type, params=params),
            on_complete=lambda completion: self._handle_process_completion(run.traffic_run_id, completion),
        )
        self._register_tail(run.traffic_run_id)
        return job_id

    def _handle_process_completion(
        self,
        traffic_run_id: str,
        completion: LocalProcessCompletion,
    ) -> None:
        """以父进程观察到的实际 Worker 终态收口 TrafficRun。"""

        with self._completion_lock:
            run = self.repository.get(traffic_run_id)
            if run is None or run.status in _TERMINAL_STATES:
                return
            payload = dict(completion.payload or {})
            if completion.cancelled:
                message = "本地 Worker 已被强制停止" if completion.forced else "本地流量任务已取消"
                self._finish_cancelled(traffic_run_id, forced=completion.forced, message=message)
                return
            if completion.exit_code == 0 and str(payload.get("type") or "") == "finished":
                result = dict(payload.get("result") or {})
                summary = dict(result.get("summary") or run.summary)
                self._finish_completed(traffic_run_id, summary)
                return
            message = str(payload.get("error") or payload.get("message") or "").strip()
            if not message:
                message = f"本地 Worker 异常退出，退出码 {completion.exit_code}"
            self._finish_failed(
                traffic_run_id,
                TrafficTestError(TrafficErrorCode.PROCESS_EXITED, message, retryable=True),
            )

    def _register_tail(self, traffic_run_id: str) -> None:
        if self.event_hub is None:
            return
        with self._tail_lock:
            self._tail_runs.setdefault(traffic_run_id, 0)
        self.start_event_tail()

    def _tail_loop(self) -> None:
        while not self._tail_stop.wait(self._tail_interval_seconds):
            self._drain_tail_once()

    def _drain_tail_once(self) -> None:
        if self.event_hub is None:
            return
        with self._tail_lock:
            cursors = tuple(self._tail_runs.items())
        for traffic_run_id, cursor in cursors:
            try:
                events = self.event_store.list_events(traffic_run_id, after_sequence=cursor, limit=500)
                for event in events:
                    self.event_hub.publish(event)
                    cursor = max(cursor, event.sequence)
                    if (
                        event.type is TrafficEventType.STATE
                        and str(event.payload.get("state") or "") in _TERMINAL_STATE_VALUES
                    ):
                        with self._tail_lock:
                            self._tail_terminal_seen.add(traffic_run_id)
                run = self.repository.get(traffic_run_id)
                terminal = run is not None and run.status in _TERMINAL_STATES
                with self._tail_lock:
                    terminal_seen = traffic_run_id in self._tail_terminal_seen
                    if terminal and terminal_seen and len(events) < 500:
                        self._tail_runs.pop(traffic_run_id, None)
                        self._tail_terminal_seen.discard(traffic_run_id)
                    elif traffic_run_id in self._tail_runs:
                        self._tail_runs[traffic_run_id] = cursor
            except Exception as exc:
                app_logger.log_error("TRAFFIC_LOCAL_EVENT_TAIL_FAILED", f"run_id={traffic_run_id} error={exc}")

    @staticmethod
    def _validate_run(run: TrafficRun, expected_type: TrafficTestType) -> None:
        if run.executor_kind is not ExecutionTargetKind.LOCAL:
            raise TrafficTestError(TrafficErrorCode.EXECUTION_TARGET_INVALID, "本地 Adapter 只能执行 LOCAL 任务")
        if run.test_type is not expected_type:
            raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "Traffic Run 类型与本地任务不匹配")
        if not run.traffic_run_id or not run.controller_task_id:
            raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "Traffic Run 缺少任务关联 ID")

    # Worker-side execution ------------------------------------------------------

    def execute_iperf_server(self, context: JobContext) -> dict[str, object]:
        return self._execute_guarded(context, lambda run: self._run_iperf(context, run, "server"))

    def execute_iperf_client(self, context: JobContext) -> dict[str, object]:
        return self._execute_guarded(context, lambda run: self._run_iperf(context, run, "client"))

    def execute_high_frequency_ping(self, context: JobContext) -> dict[str, object]:
        return self._execute_guarded(context, lambda run: self._run_fping(context, run))

    def execute_tcp_port_test(self, context: JobContext) -> dict[str, object]:
        return self._execute_guarded(context, lambda run: self._run_tcp_port_test(context, run))

    def _execute_guarded(
        self,
        context: JobContext,
        action: Callable[[TrafficRun], dict[str, object]],
    ) -> dict[str, object]:
        traffic_run_id = str(context.params.get("traffic_run_id") or "")
        run = self._require_run(traffic_run_id)
        try:
            context.check_cancelled()
            self._set_status(run.traffic_run_id, TaskState.STARTING, message="本地流量任务正在启动")
            summary = action(run)
            context.check_cancelled()
            completed = self._finish_completed(run.traffic_run_id, summary)
            context.progress("completed", 1, 1, "本地流量任务完成")
            return {
                "traffic_run_id": completed.traffic_run_id,
                "controller_task_id": completed.controller_task_id,
                "summary": completed.summary,
                "result_reference": completed.result_reference,
                "local_iperf_run_id": completed.local_iperf_run_id,
            }
        except BackgroundTaskCancelled:
            self._finish_cancelled(run.traffic_run_id)
            raise
        except TrafficTestError as exc:
            self._finish_failed(run.traffic_run_id, exc)
            raise
        except Exception as exc:
            error = TrafficTestError(
                TrafficErrorCode.PROCESS_EXITED,
                str(exc) or exc.__class__.__name__,
            )
            self._finish_failed(run.traffic_run_id, error)
            raise error from exc

    def _run_iperf(self, context: JobContext, run: TrafficRun, mode: str) -> dict[str, object]:
        resolution = resolve_network_tool("iperf3", context.paths)
        tool = resolution.effective_path
        if tool is None:
            raise TrafficTestError(TrafficErrorCode.TOOL_NOT_FOUND, resolution.validation_message)
        config_value = dict(context.params.get("config") or {})
        if mode == "server":
            config: IperfServerConfig | IperfClientConfig = _server_config(config_value)
            command = build_iperf_server_args(tool, config)
        else:
            config = _client_config(config_value)
            preflight = run_iperf_client_preflight(tool, config)
            if not preflight.ok:
                raw_file = self._iperf_log_path(run.traffic_run_id, mode)
                raw_file.parent.mkdir(parents=True, exist_ok=True)
                raw_file.write_text(preflight.output or preflight.message, encoding="utf-8")
                self._save_run_references(run.traffic_run_id, raw_reference=self._run_reference(run.traffic_run_id, raw_file.name))
                self._append_event(
                    run.traffic_run_id,
                    TrafficEventType.ERROR,
                    {"code": preflight.error_code, "message": preflight.message},
                )
                raise _preflight_error(preflight.error_code, preflight.message)
            command = build_iperf_client_args(tool, config)

        raw_file = self._iperf_log_path(run.traffic_run_id, mode)
        local_iperf_run_id = run.traffic_run_id
        self._save_run_references(
            run.traffic_run_id,
            raw_reference=self._run_reference(run.traffic_run_id, raw_file.name),
            local_iperf_run_id=local_iperf_run_id,
        )
        store = IperfResultStore(context.paths.iperf_db_path(self.site_name))
        summary = _IperfSummary()

        def receive_line(line: str, row: dict[str, object] | None, error: dict[str, object] | None = None) -> None:
            self._append_event(run.traffic_run_id, TrafficEventType.STDOUT, {"line": line})
            if row is not None:
                summary.add(row)
                self._append_event(
                    run.traffic_run_id,
                    TrafficEventType.SAMPLE,
                    {"metric": "iperf_interval", **row},
                )
            if error is not None:
                self._append_event(
                    run.traffic_run_id,
                    TrafficEventType.ERROR,
                    {
                        "code": str(error.get("error_code") or "iperf_error"),
                        "message": str(error.get("error_message") or "iPerf 执行错误"),
                    },
                )

        runner = IperfProcessRunner(
            tool,
            command,
            raw_file,
            store,
            run_id=local_iperf_run_id,
            line_callback=receive_line,
            config=config if isinstance(config, IperfClientConfig) else None,
            mode=mode,
            context={"traffic_run_id": run.traffic_run_id, "controller_task_id": run.controller_task_id},
        )
        monitor_done = threading.Event()
        monitor = threading.Thread(
            target=self._monitor_iperf_cancel,
            args=(context, runner, monitor_done),
            name=f"traffic-iperf-cancel-{run.traffic_run_id}",
            daemon=True,
        )
        self._set_status(run.traffic_run_id, TaskState.RUNNING, message=f"本地 iPerf {mode} 已启动")
        context.progress("running", 0, 0, f"本地 iPerf {mode} 运行中")
        monitor.start()
        try:
            try:
                runner.start()
            except OSError as exc:
                code = (
                    TrafficErrorCode.PROCESS_START_FAILED
                    if runner.process is None
                    else TrafficErrorCode.PROCESS_EXITED
                )
                raise TrafficTestError(
                    code,
                    f"iPerf 进程执行失败（来源：{resolution.source}）：{exc}",
                ) from exc
        finally:
            monitor_done.set()
            monitor.join(timeout=1)
        context.check_cancelled()
        if str(runner.last_status).startswith("FAILED"):
            raise _runner_error(runner.last_error_code, runner.last_status)
        return summary.to_dict()

    @staticmethod
    def _monitor_iperf_cancel(
        context: JobContext,
        runner: IperfProcessRunner,
        done: threading.Event,
    ) -> None:
        while not done.wait(0.05):
            if context.should_cancel is None or not context.should_cancel():
                continue
            while runner.process is None and not done.wait(0.01):
                pass
            if runner.process is not None:
                runner.stop(status="CANCELLED")
            return

    def _run_fping(self, context: JobContext, run: TrafficRun) -> dict[str, object]:
        config = _ping_config(dict(context.params.get("config") or {}))
        if config.source_address:
            raise TrafficTestError(
                TrafficErrorCode.CAPABILITY_UNSUPPORTED,
                "本地 fping 暂不支持指定源地址",
            )
        resolution = resolve_network_tool("fping", context.paths)
        if resolution.effective_path is None:
            raise TrafficTestError(TrafficErrorCode.TOOL_NOT_FOUND, resolution.validation_message)
        availability = check_fping_v5_available(fping_path=resolution.effective_path)
        if not availability.available:
            raise TrafficTestError(
                TrafficErrorCode.TOOL_NOT_FOUND,
                f"fping v5 不可用（来源：{resolution.source}）：{availability.error}",
            )

        run_dir = context.paths.traffic_run_dir(self.site_name, run.traffic_run_id)
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        self._save_run_references(run.traffic_run_id, raw_reference=f"runs/{run.traffic_run_id}/raw")
        self._set_status(run.traffic_run_id, TaskState.RUNNING, message="本地高频 Ping 已启动")
        context.progress("running", 0, 0, "本地高频 Ping 运行中")

        stop_event = threading.Event()
        queue_size = max(256, min(4_096, len(config.targets) * 256))
        output: queue.Queue[tuple[str, str, object | None]] = queue.Queue(maxsize=queue_size)
        threads: list[threading.Thread] = []
        for target in config.targets:
            key = hashlib.sha1(target.encode("utf-8")).hexdigest()[:12]
            thread = threading.Thread(
                target=self._collect_fping_target,
                args=(context, config, target, raw_dir, key, resolution.effective_path, stop_event, output),
                name=f"traffic-fping-{key}",
                daemon=True,
            )
            threads.append(thread)
            thread.start()

        remaining = len(threads)
        pending: list[FpingV5Sample] = []
        errors: list[tuple[str, Exception]] = []
        stats = {target: FpingV5Stats() for target in config.targets}
        last_flush = time.monotonic()
        cancelled = False
        while remaining > 0:
            if context.should_cancel is not None and context.should_cancel():
                cancelled = True
                stop_event.set()
            try:
                kind, target, value = output.get(timeout=0.05)
            except queue.Empty:
                kind = ""
                target = ""
                value = None
            if kind == "sample" and isinstance(value, FpingV5Sample):
                pending.append(value)
                stats[target].add(value)
            elif kind == "error" and isinstance(value, Exception):
                errors.append((target, value))
                stop_event.set()
            elif kind == "done":
                remaining -= 1
            if pending and (len(pending) >= 100 or time.monotonic() - last_flush >= 0.2 or remaining == 0):
                self._flush_ping_samples(run, config, pending)
                pending.clear()
                last_flush = time.monotonic()
        if pending:
            self._flush_ping_samples(run, config, pending)
        for thread in threads:
            thread.join(timeout=1)
        if cancelled:
            context.check_cancelled()
        if errors:
            target, error = errors[0]
            if isinstance(error, FileNotFoundError):
                raise TrafficTestError(TrafficErrorCode.TOOL_NOT_FOUND, str(error))
            if isinstance(error, OSError):
                raise TrafficTestError(TrafficErrorCode.PROCESS_START_FAILED, f"{target}: {error}")
            raise TrafficTestError(TrafficErrorCode.PROCESS_EXITED, f"{target}: {error}")
        if not any(target_stats.sent_count for target_stats in stats.values()):
            raise TrafficTestError(TrafficErrorCode.PARSE_FAILED, "fping 未产生有效响应或超时样本")
        return {
            "targets": {target: target_stats.as_dict() for target, target_stats in stats.items()},
            "target_count": len(config.targets),
        }

    def _run_tcp_port_test(self, context: JobContext, run: TrafficRun) -> dict[str, object]:
        config = _tcp_port_config(dict(context.params.get("config") or {}))
        self._set_status(run.traffic_run_id, TaskState.RUNNING, message="本地 TCP 端口测试已启动")
        context.progress("running", 0, config.count, "本地 TCP 端口测试运行中")
        received = 0
        latencies: list[float] = []
        last_status = "unknown"
        last_error = ""
        for sequence in range(1, config.count + 1):
            context.check_cancelled()
            result = run_tcp_ping(config.target, config.port, timeout_seconds=config.timeout_ms / 1_000)
            ok = result.status == "open"
            if ok:
                received += 1
                if result.latency_ms is not None:
                    latencies.append(result.latency_ms)
            last_status, last_error = result.status, result.error
            event = self.event_store.append(
                TrafficEvent(
                    traffic_run_id=run.traffic_run_id,
                    controller_task_id=run.controller_task_id,
                    source="local",
                    type=TrafficEventType.SAMPLE,
                    payload={
                        "metric": "tcp_port",
                        "target": config.target,
                        "port": config.port,
                        "probe_sequence": sequence,
                        "ok": ok,
                        "rtt_ms": result.latency_ms,
                        "error": result.error,
                    },
                )
            )
            if event is not None:
                self.repository.insert_ping_samples(
                    [
                        TrafficPingSample(
                            traffic_run_id=run.traffic_run_id,
                            sequence=event.sequence,
                            timestamp=result.timestamp,
                            target=config.target,
                            probe_sequence=sequence,
                            ok=ok,
                            rtt_ms=result.latency_ms if ok else None,
                            timeout=result.status == "timeout",
                            error_code=result.status if not ok else "",
                            error_message=result.error,
                        )
                    ],
                    updated_at=utc_now_iso(),
                )
            context.progress("running", sequence, config.count, f"TCP 端口测试 {sequence}/{config.count}")
            if sequence < config.count:
                deadline = time.monotonic() + config.interval_ms / 1_000
                while time.monotonic() < deadline:
                    context.check_cancelled()
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return {
            "target": config.target,
            "port": config.port,
            "sent": config.count,
            "received": received,
            "success_percent": received * 100 / config.count,
            "rtt_min_ms": min(latencies) if latencies else None,
            "rtt_avg_ms": sum(latencies) / len(latencies) if latencies else None,
            "rtt_max_ms": max(latencies) if latencies else None,
            "last_status": last_status,
            "last_error": last_error,
        }

    @staticmethod
    def _collect_fping_target(
        context: JobContext,
        config: HighFrequencyPingConfig,
        target: str,
        raw_dir: Path,
        key: str,
        fping_path: Path,
        stop_event: threading.Event,
        output: queue.Queue[tuple[str, str, object | None]],
    ) -> None:
        try:
            for sample in run_fping_v5_json(
                target=target,
                period_ms=config.interval_ms,
                timeout_ms=config.timeout_ms,
                packet_size=config.packet_size,
                count_json=None if config.continuous else config.count,
                output_jsonl_path=raw_dir / f"fping_{key}.jsonl",
                output_raw_log_path=raw_dir / f"fping_{key}.log",
                stop_event=stop_event,
                fping_path=fping_path,
            ):
                if not sample.target:
                    sample = replace(sample, target=target)
                output.put(("sample", target, sample))
        except Exception as exc:
            output.put(("error", target, exc))
        finally:
            output.put(("done", target, None))

    def _flush_ping_samples(
        self,
        run: TrafficRun,
        config: HighFrequencyPingConfig,
        samples: list[FpingV5Sample],
    ) -> None:
        events = [
            TrafficEvent(
                traffic_run_id=run.traffic_run_id,
                controller_task_id=run.controller_task_id,
                source="local",
                type=TrafficEventType.SAMPLE,
                payload={"metric": "ping", **sample.as_dict()},
            )
            for sample in samples
        ]
        accepted = self.event_store.append_many(events)
        rows: list[TrafficPingSample] = []
        for event, sample in zip(accepted, samples, strict=True):
            if sample.raw_type not in {"resp", "timeout"} or sample.ok is None:
                continue
            timeout = sample.raw_type == "timeout" or not sample.ok
            rows.append(
                TrafficPingSample(
                    traffic_run_id=run.traffic_run_id,
                    sequence=event.sequence,
                    timestamp=sample.ts,
                    target=sample.target,
                    probe_sequence=sample.seq,
                    ok=bool(sample.ok),
                    rtt_ms=None if timeout else sample.rtt_ms,
                    timeout=timeout,
                    packet_size=sample.size if sample.size is not None else config.packet_size,
                    error_code="timeout" if timeout else "",
                    error_message=sample.error,
                )
            )
        self.repository.insert_ping_samples(rows, updated_at=utc_now_iso())

    # Persistence helpers --------------------------------------------------------

    def _require_run(self, traffic_run_id: str) -> TrafficRun:
        if not traffic_run_id:
            raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "后台任务缺少 traffic_run_id")
        run = self.repository.get(traffic_run_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, f"Traffic Run 不存在：{traffic_run_id}")
        return run

    def _set_status(self, traffic_run_id: str, status: TaskState, *, message: str) -> TrafficRun:
        run = self._require_run(traffic_run_id)
        now = utc_now_iso()
        values: dict[str, object] = {"status": status, "updated_at": now}
        if status is TaskState.RUNNING and not run.started_at:
            values["started_at"] = now
        updated = replace(run, **values)
        self.repository.save(updated)
        self._append_event(traffic_run_id, TrafficEventType.STATE, {"state": status.value, "message": message})
        return updated

    def _save_run_references(
        self,
        traffic_run_id: str,
        *,
        raw_reference: str = "",
        local_iperf_run_id: str = "",
    ) -> TrafficRun:
        run = self._require_run(traffic_run_id)
        updated = replace(
            run,
            raw_reference=raw_reference or run.raw_reference,
            local_iperf_run_id=local_iperf_run_id or run.local_iperf_run_id,
            updated_at=utc_now_iso(),
        )
        return self.repository.save(updated)

    def _finish_completed(self, traffic_run_id: str, summary: dict[str, object]) -> TrafficRun:
        self.event_store.write_summary(traffic_run_id, summary)
        run = self._require_run(traffic_run_id)
        now = utc_now_iso()
        updated = replace(
            run,
            status=TaskState.COMPLETED,
            finished_at=now,
            updated_at=now,
            summary=dict(summary),
            result_reference=f"runs/{traffic_run_id}/summary.json",
            sync_state=TrafficSyncState.COMPLETED,
        )
        self.repository.save(updated)
        self._append_event(traffic_run_id, TrafficEventType.SUMMARY, dict(summary))
        self._append_event(
            traffic_run_id,
            TrafficEventType.STATE,
            {"state": TaskState.COMPLETED.value, "message": "本地流量任务完成"},
        )
        return self._require_run(traffic_run_id)

    def _finish_cancelled(
        self,
        traffic_run_id: str,
        *,
        forced: bool = False,
        message: str = "任务已取消",
    ) -> None:
        run = self.repository.get(traffic_run_id)
        if run is None or run.status in _TERMINAL_STATES:
            return
        now = utc_now_iso()
        self.repository.save(
            replace(
                run,
                status=TaskState.CANCELLED,
                finished_at=now,
                updated_at=now,
                error_message=message,
                sync_state=TrafficSyncState.COMPLETED,
            )
        )
        if forced:
            self._append_event(
                traffic_run_id,
                TrafficEventType.SYSTEM,
                {
                    "action": "worker_forced_stop",
                    "message": "取消宽限期结束后已强制回收本地 Worker 进程树",
                },
            )
        self._append_event(
            traffic_run_id,
            TrafficEventType.STATE,
            {"state": TaskState.CANCELLED.value, "message": message},
        )

    def _finish_failed(self, traffic_run_id: str, error: TrafficTestError) -> None:
        run = self.repository.get(traffic_run_id)
        if run is None or run.status in _TERMINAL_STATES:
            return
        now = utc_now_iso()
        self.repository.save(
            replace(
                run,
                status=TaskState.FAILED,
                finished_at=now,
                updated_at=now,
                error_code=error.code,
                error_message=error.message,
                sync_state=TrafficSyncState.ERROR,
            )
        )
        self._append_event(traffic_run_id, TrafficEventType.ERROR, error.as_dict())
        self._append_event(
            traffic_run_id,
            TrafficEventType.STATE,
            {"state": TaskState.FAILED.value, "message": error.message, "error_code": error.code},
        )

    def _append_event(
        self,
        traffic_run_id: str,
        event_type: TrafficEventType,
        payload: dict[str, object],
    ) -> TrafficEvent | None:
        run = self._require_run(traffic_run_id)
        return self.event_store.append(
            TrafficEvent(
                traffic_run_id=traffic_run_id,
                controller_task_id=run.controller_task_id,
                source="local",
                type=event_type,
                payload=dict(payload),
            )
        )

    def _iperf_log_path(self, traffic_run_id: str, mode: str) -> Path:
        return self.paths.traffic_run_dir(self.site_name, traffic_run_id) / f"iperf_{mode}.log"

    @staticmethod
    def _run_reference(traffic_run_id: str, file_name: str) -> str:
        return f"runs/{traffic_run_id}/{file_name}"


def _server_config_dict(config: IperfServerConfig) -> dict[str, object]:
    value = _server_config(
        {
            "bind_ip": config.bind_ip,
            "port": config.port,
            "interval_seconds": config.interval_seconds,
            "one_off": config.one_off,
        }
    )
    return {
        "bind_ip": value.bind_ip,
        "port": value.port,
        "interval_seconds": value.interval_seconds,
        "one_off": value.one_off,
    }


def _client_config_dict(config: IperfClientConfig) -> dict[str, object]:
    return config.normalized().as_dict()


def _server_config(value: dict[str, object]) -> IperfServerConfig:
    port = int(value.get("port") or 5201)
    interval = int(value.get("interval_seconds") or 1)
    if not 1 <= port <= 65_535 or not 1 <= interval <= 3_600:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "iPerf 服务端端口或采样间隔无效")
    return IperfServerConfig(
        bind_ip=str(value.get("bind_ip") or "").strip(),
        port=port,
        interval_seconds=interval,
        one_off=bool(value.get("one_off")),
    )


def _client_config(value: dict[str, object]) -> IperfClientConfig:
    try:
        config = IperfClientConfig(
            server_ip=str(value.get("server_ip") or "").strip(),
            port=int(value.get("port") or 5201),
            protocol=str(value.get("protocol") or "TCP"),
            duration_seconds=int(value.get("duration_seconds") or 10),
            interval_seconds=int(value.get("interval_seconds") or 1),
            parallel=int(value.get("parallel") or 1),
            direction=str(value.get("direction") or "upload"),
            target_bandwidth=value.get("target_bandwidth") or None,
            follow_collection=bool(value.get("follow_collection")),
            tcp_block_size=value.get("tcp_block_size") or None,
            packet_length=int(value["packet_length"]) if value.get("packet_length") else None,
            tcp_report_threshold_mbps=value.get("tcp_report_threshold_mbps"),
            tcp_pacing_enabled=bool(value.get("tcp_pacing_enabled")),
            tcp_pacing_mbps=value.get("tcp_pacing_mbps"),
            udp_bitrate_mbps=value.get("udp_bitrate_mbps"),
            udp_report_threshold_mbps=value.get("udp_report_threshold_mbps"),
        ).normalized()
    except (TypeError, ValueError) as exc:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, f"iPerf 客户端配置无效：{exc}") from exc
    if not config.server_ip or not 1 <= config.port <= 65_535:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "iPerf 客户端地址或端口无效")
    if config.direction not in {"upload", "download", "bidirectional"}:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, "iPerf 测试方向无效")
    return config


def _ping_config(value: dict[str, object]) -> HighFrequencyPingConfig:
    try:
        return HighFrequencyPingConfig(
            targets=tuple(str(item) for item in value.get("targets") or ()),
            interval_ms=int(value.get("interval_ms") or 100),
            timeout_ms=int(value.get("timeout_ms") or 100),
            packet_size=int(value.get("packet_size") or 64),
            count=int(value.get("count", 20)),
            continuous=bool(value.get("continuous")),
            source_address=str(value.get("source_address") or ""),
        ).normalized()
    except (TypeError, ValueError) as exc:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, f"高频 Ping 配置无效：{exc}") from exc


def _tcp_port_config(value: dict[str, object]) -> TcpPortTestConfig:
    try:
        return TcpPortTestConfig(
            target=str(value.get("target") or ""),
            port=int(value.get("port") or 0),
            interval_ms=int(value.get("interval_ms") or 1_000),
            timeout_ms=int(value.get("timeout_ms") or 3_000),
            count=int(value.get("count") or 4),
        ).normalized()
    except (TypeError, ValueError) as exc:
        raise TrafficTestError(TrafficErrorCode.INVALID_CONFIG, str(exc)) from exc


def _preflight_error(code: str, message: str) -> TrafficTestError:
    mapping = {
        "tool_missing": TrafficErrorCode.TOOL_NOT_FOUND,
        "server_busy": TrafficErrorCode.SERVER_NOT_READY,
        "connection_refused": TrafficErrorCode.CONNECTION_REFUSED,
        "unable_to_connect": TrafficErrorCode.CONNECTION_REFUSED,
        "timed_out": TrafficErrorCode.CONNECTION_TIMEOUT,
    }
    selected = mapping.get(str(code or ""), TrafficErrorCode.SERVER_NOT_READY)
    return TrafficTestError(selected, message or "iPerf 服务端预检失败", retryable=True)


def _runner_error(code: str, status: str) -> TrafficTestError:
    mapping = {
        "address_in_use": TrafficErrorCode.SERVER_PORT_IN_USE,
        "port_in_use": TrafficErrorCode.SERVER_PORT_IN_USE,
        "bind_failed": TrafficErrorCode.SERVER_PORT_IN_USE,
        "server_busy": TrafficErrorCode.SERVER_NOT_READY,
        "connection_refused": TrafficErrorCode.CONNECTION_REFUSED,
        "unable_to_connect": TrafficErrorCode.CONNECTION_REFUSED,
        "timed_out": TrafficErrorCode.CONNECTION_TIMEOUT,
    }
    selected = mapping.get(str(code or ""), TrafficErrorCode.PROCESS_EXITED)
    return TrafficTestError(selected, f"iPerf 进程异常结束：{status}", retryable=True)


__all__ = [
    "LocalTrafficAdapter",
    "TASK_FPING",
    "TASK_IPERF_CLIENT",
    "TASK_IPERF_SERVER",
]
