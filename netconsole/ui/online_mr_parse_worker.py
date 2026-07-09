from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser
from netconsole.services.vehicle_mr_offline_analysis import build_vehicle_mr_analysis_chart_payload


class OnlineMrParseWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int, str)

    def __init__(self, session_dir: Path, parent=None, *, force_reparse: bool = True) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)
        self.force_reparse = force_reparse
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def _progress(self, stage: str, current: int, total: int, message: str) -> None:
        self.progress.emit(stage, int(current), int(total), str(message or stage))

    def run(self) -> None:
        try:
            summary = OnlineMrDiagnosisParser(self.session_dir).parse(
                force=self.force_reparse,
                progress=self._progress,
                should_cancel=lambda: self._cancel_requested,
            )
            self.completed.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))

class OnlineMrAnalysisLoadWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int, str)

    def __init__(self, session_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)

    def _progress(self, stage: str, current: int, total: int, message: str) -> None:
        self.progress.emit(stage, int(current), int(total), str(message or stage))

    def run(self) -> None:
        try:
            self._progress("打开解析缓存", 1, 3, "打开 parsed 数据库")
            self._progress("构建图表数据", 2, 3, "后台构建分析图表数据")
            payload = build_vehicle_mr_analysis_chart_payload(self.session_dir)
            self._progress("加载完成", 3, 3, "分析图表数据构建完成")
            self.completed.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))
