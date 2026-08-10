from __future__ import annotations

import json
import time
from datetime import datetime
from threading import Event, Thread
from typing import Callable

from netconsole.models.online_mr_application import calculate_duration_minutes
from netconsole.models.online_mr_models import STATE_FAILED, OnlineMrConnectionConfig, OnlineMrSnapshot
from netconsole.services.online_mr.collection_models import snapshot_to_payload
from netconsole.services.online_mr.collection_packager import OnlineMrCollectionPackager
from netconsole.services.online_mr.traffic_coordinator import OnlineMrTrafficCoordinator
from netconsole.services.online_mr_collector import ConnectionFactory, OnlineMrCollector
from netconsole.services.online_mr_session_store import OnlineMrSessionStore

ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class OnlineMrCollectionService:
    def __init__(
        self,
        store: OnlineMrSessionStore,
        *,
        connection_factory: ConnectionFactory | None = None,
        packager: OnlineMrCollectionPackager | None = None,
        traffic_coordinator: OnlineMrTrafficCoordinator | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.connection_factory = connection_factory
        self.packager = packager or OnlineMrCollectionPackager()
        self.traffic_coordinator = traffic_coordinator
        self.clock = clock or time.monotonic

    def run(
        self,
        config: OnlineMrConnectionConfig,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        package_on_stop: bool = True,
        controller_task_id: str = "",
        manage_traffic: bool = False,
        traffic_flush_timeout_seconds: float = 8.0,
    ) -> dict[str, object]:
        monitor_stop = Event()
        stop_reason = ["collector_ended"]
        duration_deadline: list[float | None] = [None]
        traffic_started = Event()
        traffic_start_thread: Thread | None = None
        startup_started = self.clock()

        def requested_stop() -> bool:
            if should_cancel is not None and should_cancel():
                stop_reason[0] = "cancel_requested"
                return True
            deadline = duration_deadline[0]
            if deadline is not None and self.clock() >= deadline:
                stop_reason[0] = "duration_elapsed"
                return True
            return False

        def monitor_cancel() -> None:
            while not monitor_stop.wait(0.1):
                if requested_stop():
                    if manage_traffic and collector.session is not None and traffic_started.is_set():
                        coordinator.stop_traffic_for_session(collector.session.meta.session_id)
                        coordinator.flush_traffic_outputs(
                            collector.session.meta.session_id,
                            timeout_seconds=traffic_flush_timeout_seconds,
                        )
                    collector.request_stop()
                    return
        last_progress = 0.0

        def emit(stage: str, message: str, current: int = 0, total: int = 0) -> None:
            if progress is not None:
                progress(stage, current, total, message)

        def elapsed_ms() -> int:
            return max(0, int((self.clock() - startup_started) * 1000))

        def mark_startup(stage: str, *, session=None, status: str = "ok", message: str = "", publish: bool = True) -> None:
            payload = {
                "controller_task_id": controller_task_id,
                "session_id": session.meta.session_id if session is not None else "",
                "site_id": config.site,
                "device_id": config.device_id,
                "stage": stage,
                "elapsed_ms": elapsed_ms(),
                "status": status,
                "message": message,
            }
            if session is not None:
                session.record_startup_milestone(stage, elapsed_ms=payload["elapsed_ms"], status=status, message=message)
            if publish:
                emit("online_mr_startup_stage", json.dumps(payload, ensure_ascii=False))

        coordinator = self.traffic_coordinator or OnlineMrTrafficCoordinator(self.store.paths)

        def start_traffic_async(session) -> None:
            nonlocal traffic_start_thread, traffic_summary
            if not manage_traffic or traffic_started.is_set() or traffic_start_thread is not None:
                return

            def target() -> None:
                nonlocal traffic_summary
                mark_startup("traffic_start_begin", session=session)
                try:
                    traffic_summary = coordinator.start_for_session(session, config)
                    traffic_started.set()
                    mark_startup("traffic_start_submitted", session=session)
                except Exception as exc:
                    warning = f"Traffic 启动失败：{exc}"
                    warnings.append(warning)
                    mark_startup("traffic_start_failed", session=session, status="failed", message=warning)

            traffic_start_thread = Thread(
                target=target,
                name=f"online-mr-traffic-start-{session.meta.session_id}",
                daemon=True,
            )
            traffic_start_thread.start()

        def start_required_fping(session) -> None:
            nonlocal traffic_summary
            if not manage_traffic or traffic_started.is_set():
                return
            mark_startup("required_fping_start_begin", session=session)
            traffic_summary = coordinator.start_for_session(session, config)
            fping_status = str(
                (traffic_summary.get("fping") or {}).get("status") or ""
            ).lower()
            if fping_status != "running":
                raise RuntimeError(
                    "深度采集启动失败：fping 未进入有效运行态，"
                    "无法生成车载 MR 分析所需的 Ping 时序数据"
                )
            traffic_started.set()
            mark_startup("required_fping_running", session=session)

        def on_session_created(meta) -> None:
            payload = {
                "controller_task_id": controller_task_id,
                "session_id": meta.session_id,
                "site_id": config.site,
                "device_id": config.device_id,
                "mr_name": config.mr_name,
            }
            emit("online_mr_session_created", json.dumps(payload, ensure_ascii=False))
            if collector.session is not None:
                mark_startup("session_created", session=collector.session, publish=False)
                if config.fping_required_before_collection:
                    start_required_fping(collector.session)
                else:
                    start_traffic_async(collector.session)

        collector = OnlineMrCollector(
            config,
            self.store,
            connection_factory=self.connection_factory,
            session_created_callback=on_session_created,
        )
        monitor = Thread(target=monitor_cancel, name="online-mr-job-cancel-monitor", daemon=True)
        monitor.start()

        def on_snapshot(snapshot: OnlineMrSnapshot) -> None:
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress < 0.8:
                return
            last_progress = now
            emit("online_mr_status", json.dumps(snapshot_to_payload(snapshot), ensure_ascii=False))

        package_path = ""
        traffic_summary: dict[str, object] = {}
        warnings: list[str] = []
        try:
            try:
                meta = collector.start()
                if collector.session is not None:
                    mark_startup("collector_start_ready", session=collector.session)
            except Exception as exc:
                collector.fail_start(str(exc) or exc.__class__.__name__)
                raise
            started = meta.to_json_dict()
            started.update(
                {
                    "controller_task_id": controller_task_id,
                    "session_dir": str(meta.session_dir or ""),
                    "site_id": config.site,
                    "device_id": config.device_id,
                    "mr_name": config.mr_name,
                    "enabled_collectors": self._enabled_collectors(config),
                }
            )
            emit("online_mr_started", json.dumps(started, ensure_ascii=False))
            if config.duration_minutes is not None and int(config.duration_minutes) > 0:
                duration_deadline[0] = self.clock() + int(config.duration_minutes) * 60
            if manage_traffic and collector.session is not None and not collector.cancelled:
                start_traffic_async(collector.session)
            collector.run_forever(
                on_snapshot,
                should_cancel=(lambda: collector.cancelled) if manage_traffic else should_cancel,
            )
            session = collector.session
            if traffic_start_thread is not None:
                traffic_start_thread.join(timeout=traffic_flush_timeout_seconds)
                if traffic_start_thread.is_alive():
                    warnings.append("Traffic 启动线程仍在运行，停止阶段将继续尝试回收")
            if manage_traffic and session is not None and traffic_started.is_set():
                emit("online_mr_stopping_traffic", "正在停止 Online MR Traffic 子任务")
                coordinator.stop_traffic_for_session(session.meta.session_id)
                warnings = coordinator.flush_traffic_outputs(
                    session.meta.session_id,
                    timeout_seconds=traffic_flush_timeout_seconds,
                )
                traffic_summary = coordinator.finalize_traffic_outputs(session.meta.session_id)
            if collector.status == STATE_FAILED:
                stop_reason[0] = "collector_failed"
            elif stop_reason[0] == "collector_ended":
                stop_reason[0] = "collector_stopped"
            if manage_traffic and session is not None:
                session.meta.duration_minutes = calculate_duration_minutes(
                    session.meta.started_at,
                    session.meta.ended_at or datetime.now(),
                )
                session.meta.stop_reason = stop_reason[0]
                session.meta.force_stopped = False
                session.meta.traffic_summary = traffic_summary
                session.meta.finalization_warnings = list(dict.fromkeys(warnings))
                session.meta.finalization_complete = bool(traffic_summary.get("flush_complete", True))
                session.meta.package_available = bool(package_on_stop and session.meta.finalization_complete)
                session.meta.data_integrity = "complete" if session.meta.finalization_complete else "partial"
                session.write_meta()
            if package_on_stop and session is not None and (
                not manage_traffic or session.meta.finalization_complete
            ):
                emit("online_mr_package", "正在打包在线 MR 会话", 0, 1)
                try:
                    package_path = str(self.packager.package(session.session_dir))
                except Exception as exc:
                    session.meta.finalization_complete = False
                    session.meta.package_available = False
                    session.meta.finalization_warnings.append(f"会话打包失败：{exc}")
                    session.write_meta()
                    raise
                emit("online_mr_package", "在线 MR 会话打包完成", 1, 1)
            if collector.status == STATE_FAILED:
                raise RuntimeError("在线 MR 采集异常结束，原始日志已保留")
            return {
                "session_id": session.meta.session_id if session else "",
                "session_dir": str(session.session_dir) if session else "",
                "status": collector.status,
                "package_path": package_path,
                "enabled_collectors": self._enabled_collectors(config),
                "stop_reason": stop_reason[0],
                "duration_minutes": session.meta.duration_minutes if session else 0.0,
                "traffic_summary": traffic_summary,
                "warnings": list(dict.fromkeys(warnings)),
            }
        finally:
            monitor_stop.set()
            monitor.join(timeout=1)
            if manage_traffic and collector.session is not None and collector.status == STATE_FAILED:
                if traffic_start_thread is not None:
                    traffic_start_thread.join(timeout=traffic_flush_timeout_seconds)
                if traffic_started.is_set():
                    coordinator.stop_traffic_for_session(collector.session.meta.session_id)
                    coordinator.flush_traffic_outputs(
                        collector.session.meta.session_id,
                        timeout_seconds=traffic_flush_timeout_seconds,
                    )
                    coordinator.finalize_traffic_outputs(collector.session.meta.session_id)
            if collector.session is not None and collector.status not in {"STOPPED", "FORCED_STOPPED", "FAILED"}:
                collector.stop()

    @staticmethod
    def _enabled_collectors(config: OnlineMrConnectionConfig) -> list[str]:
        enabled = ["terminal_monitor", *sorted(config.tasks.enabled_tasks())]
        if config.fping.normalized().enabled:
            enabled.append("fping")
        if config.iperf.normalized().enabled:
            enabled.append("iperf")
        return enabled
