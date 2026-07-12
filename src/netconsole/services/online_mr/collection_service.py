from __future__ import annotations

import json
import time
from threading import Event, Thread
from typing import Callable

from netconsole.models.online_mr_models import STATE_FAILED, OnlineMrConnectionConfig, OnlineMrSnapshot
from netconsole.services.online_mr.collection_models import snapshot_to_payload
from netconsole.services.online_mr.collection_packager import OnlineMrCollectionPackager
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
    ) -> None:
        self.store = store
        self.connection_factory = connection_factory
        self.packager = packager or OnlineMrCollectionPackager()

    def run(
        self,
        config: OnlineMrConnectionConfig,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        package_on_stop: bool = True,
    ) -> dict[str, object]:
        collector = OnlineMrCollector(config, self.store, connection_factory=self.connection_factory)
        monitor_stop = Event()

        def monitor_cancel() -> None:
            while not monitor_stop.wait(0.1):
                if should_cancel is not None and should_cancel():
                    collector.request_stop()
                    return

        monitor = Thread(target=monitor_cancel, name="online-mr-job-cancel-monitor", daemon=True)
        monitor.start()
        last_progress = 0.0

        def emit(stage: str, message: str, current: int = 0, total: int = 0) -> None:
            if progress is not None:
                progress(stage, current, total, message)

        def on_snapshot(snapshot: OnlineMrSnapshot) -> None:
            nonlocal last_progress
            now = time.monotonic()
            if now - last_progress < 0.8:
                return
            last_progress = now
            emit("online_mr_status", json.dumps(snapshot_to_payload(snapshot), ensure_ascii=False))

        package_path = ""
        try:
            meta = collector.start()
            started = meta.to_json_dict()
            started["session_dir"] = str(meta.session_dir or "")
            started["enabled_collectors"] = self._enabled_collectors(config)
            emit("online_mr_started", json.dumps(started, ensure_ascii=False))
            collector.run_forever(on_snapshot, should_cancel=should_cancel)
            if package_on_stop and collector.session is not None:
                emit("online_mr_package", "正在打包在线 MR 会话", 0, 1)
                package_path = str(self.packager.package(collector.session.session_dir))
                emit("online_mr_package", "在线 MR 会话打包完成", 1, 1)
            if collector.status == STATE_FAILED:
                raise RuntimeError("在线 MR 采集异常结束，原始日志已保留")
            session = collector.session
            return {
                "session_id": session.meta.session_id if session else "",
                "session_dir": str(session.session_dir) if session else "",
                "status": collector.status,
                "package_path": package_path,
                "enabled_collectors": self._enabled_collectors(config),
            }
        finally:
            monitor_stop.set()
            monitor.join(timeout=1)
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
