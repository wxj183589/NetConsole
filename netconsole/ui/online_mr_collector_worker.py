from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.services.online_mr.core.realtime_cache import OnlineMrRealtimeCache
from netconsole.services.online_mr_collector import ConnectionFactory, OnlineMrCollector
from netconsole.services.online_mr_session_store import OnlineMrSessionStore


class OnlineMrCollectorWorker(QThread):
    snapshot = Signal(object)
    raw_stream_event = Signal(object)
    started_session = Signal(object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        config: OnlineMrConnectionConfig,
        paths: PathResolver,
        connection_factory: ConnectionFactory | None = None,
        realtime_cache: OnlineMrRealtimeCache | None = None,
        config_only: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        store = OnlineMrSessionStore(paths)
        self.collector = OnlineMrCollector(config, store, connection_factory=connection_factory, realtime_cache=realtime_cache)
        self.config_only = config_only

    def cancel(self) -> None:
        self.collector.request_stop()

    def force_stop(self, reason: str = "force_stop") -> None:
        self.collector.force_stop(reason)

    def run(self) -> None:
        try:
            meta = self.collector.collect_config_only() if self.config_only else self.collector.start()
            self.started_session.emit(meta)
            if not self.config_only:
                self.collector.run_forever(
                    lambda snapshot: self.snapshot.emit(snapshot),
                    lambda event: self.raw_stream_event.emit(event),
                )
            self.completed.emit(meta.session_id)
        except Exception as exc:
            self.failed.emit(str(exc))
