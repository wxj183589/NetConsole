from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QThread, Signal

from netconsole.services.vehicle_mr_offline_analysis import build_vehicle_mr_analysis_chart_payload
from netconsole.ui.background_process_bridge import BackgroundProcessBridgeCancelled, run_background_job_process


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
            result = run_background_job_process(
                task_type="online_mr_parse",
                params={"session_dir": str(self.session_dir), "force_reparse": self.force_reparse},
                progress_handler=lambda event: self._progress(
                    str(event.get("stage") or ""),
                    int(event.get("current") or 0),
                    int(event.get("total") or 0),
                    str(event.get("message") or ""),
                ),
                should_cancel=lambda: self._cancel_requested,
            )
            self.completed.emit(SimpleNamespace(**result))
        except BackgroundProcessBridgeCancelled as exc:
            self.failed.emit(str(exc))
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
