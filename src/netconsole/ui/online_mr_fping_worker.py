from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.models.online_mr_models import FpingConfig
from netconsole.services.online_mr.event_bus import OnlineMrEventBus
from netconsole.services.online_mr.fping_v5_probe import FpingV5ProbeRunner
from netconsole.services.online_mr_session_store import OnlineMrSession


class FpingV5ProbeWorker(QThread):
    snapshot = Signal(object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        session: OnlineMrSession,
        config: FpingConfig,
        fping_path: Path,
        event_bus: OnlineMrEventBus | None = None,
        source_device_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.runner = FpingV5ProbeRunner(
            session,
            config,
            fping_path,
            event_bus=event_bus,
            source_device_id=source_device_id,
        )

    @property
    def stats(self):
        return self.runner.stats

    @property
    def stop_requested(self) -> bool:
        return self.runner.stop_requested

    @property
    def stop_event(self):
        return self.runner.stop_event

    def run(self) -> None:
        result = self.runner.run(self.snapshot.emit)
        if result.error:
            self.failed.emit(result.error)
        else:
            self.completed.emit(result.status)

    def stop(self) -> None:
        self.runner.stop()

    def _handle_sample(self, sample) -> None:
        self.snapshot.emit(self.runner.handle_sample(sample))
