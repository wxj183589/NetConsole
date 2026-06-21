from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser


class OnlineMrParseWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, session_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)

    def run(self) -> None:
        try:
            summary = OnlineMrDiagnosisParser(self.session_dir).parse()
            self.completed.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
