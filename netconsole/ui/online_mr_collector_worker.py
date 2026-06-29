from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.online_mr_models import OnlineMrConnectionConfig
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
        store: OnlineMrSessionStore,
        connection_factory: ConnectionFactory | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.collector = OnlineMrCollector(config, store, connection_factory=connection_factory)

    def cancel(self) -> None:
        self.collector.stop()

    def run(self) -> None:
        try:
            meta = self.collector.start()
            self.started_session.emit(meta)
            self.collector.run_forever(
                lambda snapshot: self.snapshot.emit(snapshot),
                lambda event: self.raw_stream_event.emit(event),
            )
            self.completed.emit(meta.session_id)
        except Exception as exc:
            self.failed.emit(str(exc))
