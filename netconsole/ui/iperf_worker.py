from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfProcessRunner, IperfResultStore


class IperfProcessWorker(QThread):
    line_received = Signal(str)
    interval_received = Signal(object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        iperf_path: Path,
        command: list[str],
        log_file: Path,
        store: IperfResultStore | None = None,
        run_id: str | None = None,
        session_id: str = "",
        device_id: int | None = None,
        config: IperfClientConfig | None = None,
        mode: str = "client",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.runner = IperfProcessRunner(
            iperf_path,
            command,
            log_file,
            store,
            run_id=run_id,
            session_id=session_id,
            device_id=device_id,
            line_callback=self._line_received,
            config=config,
            mode=mode,
        )

    def _line_received(self, line: str, row: dict[str, object] | None) -> None:
        self.line_received.emit(line)
        if row:
            self.interval_received.emit(row)

    def stop(self) -> None:
        self.runner.stop()

    def run(self) -> None:
        try:
            self.runner.start()
            self.completed.emit(self.runner.last_status)
        except Exception as exc:
            self.failed.emit(str(exc))
