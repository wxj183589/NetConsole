from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.ui.background_process_bridge import BackgroundProcessBridgeCancelled, run_background_job_process


class OnlineMrReportExportWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, session_dir: Path, output_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)
        self.output_path = Path(output_path)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = run_background_job_process(
                task_type="online_mr_report_export",
                params={"session_dir": str(self.session_dir), "output_path": str(self.output_path)},
                should_cancel=lambda: self._cancel_requested,
            )
            self.completed.emit(str(result.get("path") or self.output_path))
        except BackgroundProcessBridgeCancelled:
            self.failed.emit("导出已取消")
        except Exception as exc:
            self.failed.emit(str(exc))
