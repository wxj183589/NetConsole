from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.services.network_tools.iperf_runner import IperfClientConfig, IperfProcessRunner, IperfResultStore


class IperfProcessWorker(QThread):
    line_received = Signal(str)
    interval_received = Signal(object)
    error_received = Signal(object)
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
        mirror_log_files: list[Path] | None = None,
        context: dict[str, object] | None = None,
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
            mirror_log_files=mirror_log_files,
            context=context,
        )

    def _line_received(self, line: str, row: dict[str, object] | None, error: dict[str, object] | None = None) -> None:
        self.line_received.emit(line)
        if row:
            self.interval_received.emit(row)
        if error:
            self.error_received.emit(error)

    def add_mirror_log_file(self, log_file: Path, context: dict[str, object] | None = None) -> None:
        self.runner.add_mirror_log_file(log_file, context=context)

    def stop(self) -> None:
        self.runner.stop()

    def run(self) -> None:
        try:
            self.runner.start()
            self.completed.emit(self.runner.last_status)
        except Exception as exc:
            self.failed.emit(str(exc))
