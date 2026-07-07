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


class OnlineMrReportExportWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)
    progress = Signal(str, int, int, str)

    def __init__(self, session_dir: Path, output_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.session_dir = Path(session_dir)
        self.output_path = Path(output_path)

    def _progress(self, stage: str, current: int, total: int, message: str) -> None:
        self.progress.emit(stage, int(current), int(total), str(message or stage))

    def run(self) -> None:
        try:
            from netconsole.services.vehicle_mr_offline_excel_report import VehicleMrOfflineExcelReportExporter

            self._progress("准备导出数据", 1, 3, "正在读取 parsed 数据")
            output_path = VehicleMrOfflineExcelReportExporter().export(self.session_dir, self.output_path)
            self._progress("保存报告", 2, 3, "正在保存 Excel 报告")
            self._progress("导出完成", 3, 3, "离线分析报告导出完成")
            self.completed.emit(str(output_path))
        except Exception as exc:
            self.failed.emit(str(exc))
