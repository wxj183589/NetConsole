from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob


@dataclass
class _RunningBackgroundJob:
    job: BackgroundJob
    process: QProcess
    job_path: Path
    cancel_path: Path
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    terminal_event: dict[str, Any] | None = None
    cancel_requested: bool = False


class BackgroundProcessManager(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(dict)
    cancelled = Signal(dict)

    def __init__(self, parent: QObject | None = None, *, paths: PathResolver | None = None) -> None:
        super().__init__(parent)
        self.paths = paths or PathResolver()
        self._jobs: dict[str, _RunningBackgroundJob] = {}

    def start_job(self, job: BackgroundJob) -> str:
        job_id = job.job_id or uuid.uuid4().hex
        if job_id in self._jobs:
            raise RuntimeError("同一后台任务正在执行")
        job_dir = self.paths.runtime_cache_dir / "background_jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        cancel_path = job_dir / f"{job_id}.cancel"
        runtime_job = BackgroundJob.from_dict({**job.to_dict(), "job_id": job_id}).with_runtime_paths(cancel_path=str(cancel_path))
        runtime_job.validate()
        job_path = job_dir / f"{job_id}.json"
        job_path.write_text(json.dumps(runtime_job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        state = _RunningBackgroundJob(runtime_job, process, job_path, cancel_path)
        self._jobs[job_id] = state
        process.readyReadStandardOutput.connect(lambda job_id=job_id: self._read_stdout(job_id))
        process.readyReadStandardError.connect(lambda job_id=job_id: self._read_stderr(job_id))
        process.errorOccurred.connect(lambda _error, job_id=job_id: self._handle_process_error(job_id))
        process.finished.connect(lambda exit_code, _exit_status, job_id=job_id: self._handle_finished(job_id, exit_code))
        program, args = self._worker_command(job_path)
        worker_root = self._worker_code_root()
        process.setWorkingDirectory(str(worker_root))
        process.setProcessEnvironment(self._worker_environment(worker_root))
        app_logger.log_info("BACKGROUND_JOB_STARTED", f"job_id={job_id} type={runtime_job.task_type}")
        process.start(program, args)
        return job_id

    def cancel_job(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        state.cancel_requested = True
        state.cancel_path.write_text("cancelled", encoding="utf-8")
        if state.process.state() != QProcess.NotRunning:
            state.process.terminate()
            QTimer.singleShot(3000, lambda job_id=job_id: self._kill_if_running(job_id))

    def _worker_command(self, job_path: Path) -> tuple[str, list[str]]:
        return sys.executable, ["-m", "netconsole.background_worker", "--job", str(job_path)]

    def _worker_code_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _worker_environment(self, worker_root: Path) -> QProcessEnvironment:
        environment = QProcessEnvironment.systemEnvironment()
        existing = environment.value("PYTHONPATH")
        root_text = str(worker_root)
        environment.insert("PYTHONPATH", root_text if not existing else f"{root_text}{os.pathsep}{existing}")
        return environment

    def _read_stdout(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        try:
            # Internal background worker JSONL protocol; device/remote text uses text_encoding fallback at source.
            chunk = bytes(state.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        except RuntimeError:
            return
        state.stdout_buffer += chunk
        while "\n" in state.stdout_buffer:
            line, state.stdout_buffer = state.stdout_buffer.split("\n", 1)
            self._handle_stdout_line(state, line.strip())

    def _read_stderr(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is not None:
            try:
                # Internal background worker stderr, not device output; keep UTF-8 replacement for malformed diagnostics.
                state.stderr_buffer += bytes(state.process.readAllStandardError()).decode("utf-8", errors="replace")
            except RuntimeError:
                return

    def _handle_stdout_line(self, state: _RunningBackgroundJob, line: str) -> None:
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            app_logger.log_info("BACKGROUND_JOB_OUTPUT", line)
            return
        if not isinstance(event, dict):
            return
        event_type = str(event.get("type") or "")
        if event_type == "progress":
            self.progress.emit(event)
            return
        if event_type in {"finished", "error"}:
            state.terminal_event = event

    def _handle_finished(self, job_id: str, exit_code: int) -> None:
        state = self._jobs.pop(job_id, None)
        if state is None:
            return
        if state.stdout_buffer.strip():
            self._handle_stdout_line(state, state.stdout_buffer.strip())
        event = state.terminal_event or {}
        cancelled = bool(event.get("cancelled")) or state.cancel_requested
        if exit_code == 0 and str(event.get("type") or "") == "finished":
            self._safe_emit(self.finished, event)
        else:
            message = str(event.get("message") or event.get("error") or state.stderr_buffer.strip() or f"后台任务异常退出，退出码 {exit_code}")
            payload = {"type": "error", "job_id": job_id, "message": message, "error": message, "cancelled": cancelled}
            if cancelled:
                self._safe_emit(self.cancelled, payload)
            else:
                self._safe_emit(self.failed, payload)
        self._cleanup_job_files(state)
        self._safe_delete_process(state.process)

    def _handle_process_error(self, job_id: str) -> None:
        state = self._jobs.pop(job_id, None)
        if state is None:
            return
        try:
            message = state.process.errorString() or "后台进程启动失败"
        except RuntimeError:
            message = "后台进程启动失败"
        self._cleanup_job_files(state)
        self._safe_emit(self.failed, {"type": "error", "job_id": job_id, "message": message, "error": message, "cancelled": False})
        self._safe_delete_process(state.process)

    def _kill_if_running(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is not None and state.process.state() != QProcess.NotRunning:
            state.process.kill()

    def _cleanup_job_files(self, state: _RunningBackgroundJob) -> None:
        for path in (state.job_path, state.cancel_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    def _safe_emit(self, signal: Signal, payload: dict[str, Any]) -> None:
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    def _safe_delete_process(self, process: QProcess) -> None:
        try:
            process.deleteLater()
        except RuntimeError:
            pass
