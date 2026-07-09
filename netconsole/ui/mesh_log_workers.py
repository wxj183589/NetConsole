from __future__ import annotations

import multiprocessing
import queue
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

from PySide6.QtCore import QThread, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.services.mesh_analysis_report import MeshReportOptions
from netconsole.services.mesh_report_process import MeshReportProcessRequest, run_mesh_report_process
from netconsole.ui.background_process_bridge import BackgroundProcessBridgeCancelled, run_background_job_process


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
            last_emit = 0.0

            def handle_progress(event: dict) -> None:
                nonlocal last_emit
                stage = str(event.get("stage") or "")
                parts = stage.split(":")
                lines = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                parsed = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                skipped = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
                file_index = int(event.get("current") or 0)
                total_files = int(event.get("total") or 0)
                now = monotonic()
                if now - last_emit >= 0.2 or file_index >= total_files:
                    last_emit = now
                    self.progress.emit(file_index, total_files, lines, parsed, skipped)

            result = run_background_job_process(
                task_type="mesh_log_import",
                params={
                    "site_name": self.site_name,
                    "profile": _profile_payload(self.profile),
                    "files": [str(path) for path in self.files],
                },
                progress_handler=handle_progress,
                should_cancel=self.is_cancelled,
                paths=self.paths,
            )
        except BackgroundProcessBridgeCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if self._cancelled:
            self.cancelled.emit()
            return
        self.completed.emit(SimpleNamespace(**result))


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
            run_background_job_process(
                task_type="mesh_derived_rebuild",
                params={"db_path": str(self.db_path)},
                progress_handler=lambda event: self.progress.emit(int(event.get("current") or 0)),
                should_cancel=self.is_cancelled,
            )
        except BackgroundProcessBridgeCancelled:
            return
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

    def __init__(
        self,
        db_path: Path,
        mr_name: str,
        output_path: Path,
        options: MeshReportOptions,
        source_file_ids: tuple[int, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.mr_name = mr_name
        self.output_path = Path(output_path)
        self.temp_path = self.output_path.with_name(self.output_path.stem + ".tmp.xlsx")
        self.options = options
        self.source_file_ids = source_file_ids
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        if self.is_cancelled():
            self._cleanup_temp()
            self.cancelled.emit()
            return
        context = multiprocessing.get_context("spawn")
        progress_queue = context.Queue()
        cancel_event = context.Event()
        request = MeshReportProcessRequest(
            db_path=str(self.db_path),
            mr_name=self.mr_name,
            output_path=str(self.output_path),
            temp_path=str(self.temp_path),
            options=self.options,
            source_file_ids=self.source_file_ids,
        )
        process = context.Process(target=run_mesh_report_process, args=(request, progress_queue, cancel_event), daemon=False)
        process.start()
        last_emit = 0.0
        last_progress: tuple[int, str, int, int, str] | None = None
        terminal: dict[str, object] | None = None
        while process.is_alive() or not progress_queue.empty():
            if self.is_cancelled():
                cancel_event.set()
            try:
                message = progress_queue.get(timeout=0.1)
            except queue.Empty:
                message = None
            if isinstance(message, dict):
                kind = str(message.get("kind") or "")
                if kind == "progress":
                    last_progress = (
                        int(message.get("value") or 0),
                        str(message.get("stage") or ""),
                        int(message.get("file_index") or 0),
                        int(message.get("file_total") or 0),
                        str(message.get("file_name") or ""),
                    )
                elif kind in {"completed", "failed", "cancelled"}:
                    terminal = message
                    if kind == "progress":
                        last_progress = (int(message.get("value") or 0), str(message.get("stage") or ""))
            now = monotonic()
            if last_progress and (now - last_emit >= 0.2 or last_progress[0] >= 100):
                last_emit = now
                stage = f"{last_progress[1]}|||{last_progress[2]}|||{last_progress[3]}|||{last_progress[4]}"
                self.progress.emit(last_progress[0], stage)
                last_progress = None
        if self.is_cancelled() and process.is_alive():
            cancel_event.set()
            process.join(2.0)
            if process.is_alive():
                process.terminate()
                process.join(2.0)
        else:
            process.join(0.2)
        if self.is_cancelled():
            self._cleanup_temp()
            self.cancelled.emit()
            return
        if terminal is None and process.exitcode not in (0, None):
            self._cleanup_temp()
            self.failed.emit(f"报告生成子进程异常退出，exitcode={process.exitcode}")
            return
        if terminal and terminal.get("kind") == "failed":
            self._cleanup_temp()
            detail = str(terminal.get("traceback_summary") or "").strip()
            error = str(terminal.get("error") or "报告生成失败")
            self.failed.emit(f"{error}\n{detail}" if detail else error)
            return
        if terminal and terminal.get("kind") == "cancelled":
            self._cleanup_temp()
            self.cancelled.emit()
            return
        completed_path = str((terminal or {}).get("path") or self.output_path.parent)
        self.completed.emit(completed_path)

    def _cleanup_temp(self) -> None:
        if self.temp_path.exists():
            self.temp_path.unlink()


def _profile_payload(profile: MeshMrProfile) -> dict[str, object]:
    return {
        "mr_id": profile.mr_id,
        "display_name": profile.display_name,
        "safe_folder_name": profile.safe_folder_name,
        "relative_folder_path": profile.relative_folder_path,
        "linked_device_id": profile.linked_device_id,
        "notes": profile.notes,
    }
