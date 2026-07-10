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
from netconsole.services.job_center.worker_protocol import feed_jsonl, parse_event_line


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
        self._write_cancel_file(state)
        grace_ms = self._cancel_grace_ms(state)
        if grace_ms > 0:
            QTimer.singleShot(grace_ms, lambda job_id=job_id: self._terminate_if_running(job_id))
        else:
            self._terminate_if_running(job_id)

    def force_stop_job(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        state.cancel_requested = True
        self._write_cancel_file(state)
        try:
            if state.process.state() != QProcess.NotRunning:
                state.process.kill()
        except RuntimeError:
            pass

    def _write_cancel_file(self, state: _RunningBackgroundJob) -> None:
        try:
            state.cancel_path.parent.mkdir(parents=True, exist_ok=True)
            state.cancel_path.write_text("cancelled", encoding="utf-8")
        except OSError as exc:
            app_logger.log_error("BACKGROUND_JOB_CANCEL_FILE_FAILED", f"job_id={state.job.job_id} error={exc}")

    @staticmethod
    def _cancel_grace_ms(state: _RunningBackgroundJob) -> int:
        try:
            value = int(state.job.params.get("_cancel_grace_ms") or 0)
        except (TypeError, ValueError):
            value = 0
        return max(0, min(value, 60000))

    def _terminate_if_running(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        try:
            if state.process.state() != QProcess.NotRunning:
                state.process.terminate()
                QTimer.singleShot(3000, lambda job_id=job_id: self._kill_if_running(job_id))
        except RuntimeError:
            pass

    def is_running(self, job_id: str) -> bool:
        return job_id in self._jobs

    def _worker_command(self, job_path: Path) -> tuple[str, list[str]]:
        if getattr(sys, "frozen", False):
            return sys.executable, ["--background-worker", "--job", str(job_path)]
        return sys.executable, ["-m", "netconsole.background_worker", "--job", str(job_path)]

    def _worker_code_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return self.paths.app_root
        return Path(__file__).resolve().parents[3]

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
            # Internal JSONL worker protocol, not device/remote command output.
            # Device text must be decoded with text_encoding fallback before it is packed into worker events.
            chunk = bytes(state.process.readAllStandardOutput())
        except RuntimeError:
            return
        events, diagnostics, state.stdout_buffer = feed_jsonl(state.stdout_buffer, chunk)
        for line in diagnostics:
            app_logger.log_info("BACKGROUND_JOB_OUTPUT", line)
        for event in events:
            self._handle_event(state, event)

    def _read_stderr(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is not None:
            try:
                # Internal worker diagnostics only; keep UTF-8 replacement so malformed tracebacks do not break UI.
                # External tool stderr should be decoded at the tool adapter boundary before becoming event payload.
                state.stderr_buffer += bytes(state.process.readAllStandardError()).decode("utf-8", errors="replace")
            except RuntimeError:
                return

    def _handle_stdout_line(self, state: _RunningBackgroundJob, line: str) -> None:
        event = parse_event_line(line)
        if event is None:
            if line:
                app_logger.log_info("BACKGROUND_JOB_OUTPUT", line)
            return
        self._handle_event(state, event)

    def _handle_event(self, state: _RunningBackgroundJob, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "log":
            app_logger.log_info("BACKGROUND_JOB_PROCESS_LOG", str(event.get("message") or ""))
            return
        if event_type == "progress":
            self._safe_emit(self.progress, event)
            return
        if event_type in {"finished", "error", "cancelled"}:
            state.terminal_event = event
            return
        if event_type:
            app_logger.log_info("BACKGROUND_JOB_OUTPUT", json.dumps(event, ensure_ascii=False))

    def _handle_finished(self, job_id: str, exit_code: int) -> None:
        state = self._jobs.pop(job_id, None)
        if state is None:
            return
        if state.stdout_buffer.strip():
            self._handle_stdout_line(state, state.stdout_buffer.strip())
        event = state.terminal_event or {}
        cancelled = bool(event.get("cancelled")) or state.cancel_requested
        if exit_code == 0 and str(event.get("type") or "") == "finished":
            app_logger.log_info("BACKGROUND_JOB_COMPLETED", f"job_id={job_id} type={state.job.task_type}")
            self._safe_emit(self.finished, event)
        else:
            message = str(event.get("message") or event.get("error") or state.stderr_buffer.strip() or f"后台任务异常退出，退出码 {exit_code}")
            payload = {
                "type": "cancelled" if cancelled else "error",
                "job_id": job_id,
                "message": message,
                "error": message,
                "traceback": str(event.get("traceback") or state.stderr_buffer),
                "cancelled": cancelled,
            }
            if cancelled:
                app_logger.log_info("BACKGROUND_JOB_CANCELLED", f"job_id={job_id} type={state.job.task_type}")
                self._safe_emit(self.cancelled, payload)
            else:
                app_logger.log_error("BACKGROUND_JOB_FAILED", f"job_id={job_id} type={state.job.task_type} error={message}")
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
        cancelled = state.cancel_requested
        payload = {
            "type": "cancelled" if cancelled else "error",
            "job_id": job_id,
            "message": "后台任务已取消" if cancelled else message,
            "error": "后台任务已取消" if cancelled else message,
            "traceback": "",
            "cancelled": cancelled,
        }
        self._safe_emit(self.cancelled if cancelled else self.failed, payload)
        self._safe_delete_process(state.process)

    def _kill_if_running(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        try:
            if state.process.state() != QProcess.NotRunning:
                state.process.kill()
        except RuntimeError:
            pass

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
