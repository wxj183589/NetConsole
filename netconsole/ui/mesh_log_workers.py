from __future__ import annotations

from pathlib import Path
from time import monotonic

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.mesh_analysis_excel_report import MeshAnalysisExcelReportExporter
from netconsole.services.mesh_analysis_report import MeshAnalysisReportService, MeshReportCancelled, MeshReportOptions
from netconsole.services.mesh_import_service import MeshImportService


class MeshLogImportWorker(QThread):
    progress = Signal(int, int, int, int, int)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, site_name: str, paths: PathResolver, profile: MeshMrProfile, files: list[Path], parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.paths = paths
        self.profile = profile
        self.files = files
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            service = MeshImportService(self.site_name, self.paths)
            last_emit = 0.0

            def emit_progress(file_index: int, total_files: int, lines: int, parsed: int, skipped: int) -> None:
                nonlocal last_emit
                now = monotonic()
                if now - last_emit >= 0.2 or file_index >= total_files:
                    last_emit = now
                    self.progress.emit(file_index, total_files, lines, parsed, skipped)

            result = service.import_files(
                self.profile,
                self.files,
                should_cancel=self.is_cancelled,
                progress=emit_progress,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if self._cancelled:
            self.cancelled.emit()
            return
        self.completed.emit(result)


class MeshDerivedAnalysisRebuildWorker(QThread):
    completed = Signal()
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, db_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            MeshMrRepository(self.db_path).rebuild_derived_analysis(
                should_cancel=self.is_cancelled,
                progress=lambda processed: self.progress.emit(int(processed or 0)),
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if not self._cancelled:
            self.completed.emit()


class MeshAnalysisReportWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, db_path: Path, mr_name: str, output_path: Path, options: MeshReportOptions, parent=None) -> None:
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.mr_name = mr_name
        self.output_path = Path(output_path)
        self.temp_path = self.output_path.with_name(self.output_path.stem + ".tmp.xlsx")
        self.options = options
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            if self.is_cancelled():
                self._cleanup_temp()
                self.cancelled.emit()
                return
            service = MeshAnalysisReportService(self.db_path, self.mr_name)
            model = service.build_report(self.options, progress=lambda value, message: self.progress.emit(value, message), should_cancel=self.is_cancelled)
            if self.is_cancelled():
                self._cleanup_temp()
                self.cancelled.emit()
                return
            self.progress.emit(90, "export")
            MeshAnalysisExcelReportExporter().export(model, self.temp_path)
            if self.is_cancelled():
                self._cleanup_temp()
                self.cancelled.emit()
                return
            self.temp_path.replace(self.output_path)
            self.progress.emit(100, "done")
        except MeshReportCancelled:
            self._cleanup_temp()
            self.cancelled.emit()
            return
        except Exception as exc:
            self._cleanup_temp()
            self.failed.emit(str(exc))
            return
        self.completed.emit(str(self.output_path))

    def _cleanup_temp(self) -> None:
        if self.temp_path.exists():
            self.temp_path.unlink()
