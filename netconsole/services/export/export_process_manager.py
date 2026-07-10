from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.export.export_job import ExportJob


@dataclass
class _RunningExport:
    job: ExportJob
    process: QProcess
    job_path: Path
    tmp_path: Path
    cancel_path: Path
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    terminal_event: dict[str, Any] | None = None
    cancel_requested: bool = False


class ExportProcessManager(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(dict)
    cancelled = Signal(dict)

    def __init__(self, parent: QObject | None = None, *, paths: PathResolver | None = None) -> None:
        super().__init__(parent)
        self.paths = paths or PathResolver()
        self._jobs: dict[str, _RunningExport] = {}

    def start_export(self, job: ExportJob) -> str:
        job_id = job.job_id or uuid.uuid4().hex
        if job_id in self._jobs:
            raise RuntimeError("同一导出任务正在执行")
        output_path = Path(job.output_path)
        tmp_path = Path(job.tmp_path) if job.tmp_path else output_path.with_name(f"{output_path.name}.tmp")
        job_dir = self.paths.runtime_cache_dir / "export_jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        cancel_path = Path(job.cancel_path) if job.cancel_path else job_dir / f"{job_id}.cancel"
        runtime_job = ExportJob.from_dict({**job.to_dict(), "job_id": job_id}).with_runtime_paths(
            tmp_path=str(tmp_path),
            cancel_path=str(cancel_path),
        )
        runtime_job.validate()
        job_path = job_dir / f"{job_id}.json"
        job_path.write_text(json.dumps(runtime_job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        state = _RunningExport(runtime_job, process, job_path, tmp_path, cancel_path)
        self._jobs[job_id] = state
        process.readyReadStandardOutput.connect(lambda job_id=job_id: self._read_stdout(job_id))
        process.readyReadStandardError.connect(lambda job_id=job_id: self._read_stderr(job_id))
        process.errorOccurred.connect(lambda error, job_id=job_id: self._handle_process_error(job_id, error))
        process.finished.connect(lambda exit_code, exit_status, job_id=job_id: self._handle_finished(job_id, exit_code, exit_status))
        program, args = self._export_worker_command(job_path)
        process.setWorkingDirectory(str(self.paths.app_root))
        app_logger.log_info("EXPORT_JOB_STARTED", f"job_id={job_id} type={runtime_job.job_type} output={runtime_job.output_path}")
        process.start(program, args)
        return job_id

    def cancel_export(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        state.cancel_requested = True
        try:
            state.cancel_path.parent.mkdir(parents=True, exist_ok=True)
            state.cancel_path.write_text("cancelled", encoding="utf-8")
        except OSError:
            pass
        app_logger.log_info("EXPORT_JOB_CANCELLED", f"job_id={job_id} requested=1")
        process = state.process
        if process.state() != QProcess.NotRunning:
            process.terminate()
            QTimer.singleShot(3000, lambda job_id=job_id: self._kill_if_running(job_id))

    def is_running(self, job_id: str) -> bool:
        return job_id in self._jobs

    def _export_worker_command(self, job_path: Path) -> tuple[str, list[str]]:
        if getattr(sys, "frozen", False):
            return sys.executable, ["--export-worker", "--job", str(job_path)]
        return sys.executable, ["-m", "netconsole.export_worker", "--job", str(job_path)]

    def _read_stdout(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        # Internal JSONL export-worker protocol, not exported device/log content.
        # Device/log text must be decoded at its source before it is packed into the export job payload.
        raw = bytes(state.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        state.stdout_buffer += raw
        while "\n" in state.stdout_buffer:
            line, state.stdout_buffer = state.stdout_buffer.split("\n", 1)
            self._handle_stdout_line(state, line.strip())

    def _read_stderr(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        # Internal export-worker diagnostics only; replacement prevents malformed tracebacks from breaking UI.
        # External tool stderr should be decoded in that tool's adapter before reaching this process manager.
        state.stderr_buffer += bytes(state.process.readAllStandardError()).decode("utf-8", errors="replace")

    def _handle_stdout_line(self, state: _RunningExport, line: str) -> None:
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            app_logger.log_info("EXPORT_JOB_OUTPUT", line)
            return
        if not isinstance(event, dict):
            return
        event_type = str(event.get("type") or event.get("event") or "")
        if event_type == "started":
            self.progress.emit({**event, "type": "progress", "event": "progress", "current": 0, "total": 0})
            return
        if event_type == "progress":
            app_logger.log_info(
                "EXPORT_JOB_PROGRESS",
                (
                    f"job_id={state.job.job_id} type={state.job.job_type} stage={event.get('stage') or ''} "
                    f"current={event.get('current', event.get('done', 0))} total={event.get('total', 0)}"
                ),
            )
            self.progress.emit(event)
            return
        if event_type in {"finished", "success", "error", "failed", "cancelled", "result"}:
            normalized = dict(event)
            if event_type == "success":
                normalized["type"] = "finished"
                normalized["ok"] = True
            elif event_type in {"failed", "cancelled"}:
                normalized["type"] = "error"
                normalized["ok"] = False
                normalized["cancelled"] = event_type == "cancelled" or bool(normalized.get("cancelled"))
                if "message" not in normalized:
                    normalized["message"] = normalized.get("error_message") or normalized.get("error") or "导出失败"
            state.terminal_event = normalized
            return
        if event_type == "log":
            app_logger.log_error("EXPORT_JOB_PROCESS_LOG", str(event.get("message") or line))

    def _handle_finished(self, job_id: str, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        state = self._jobs.pop(job_id, None)
        if state is None:
            return
        if state.stdout_buffer.strip():
            self._handle_stdout_line(state, state.stdout_buffer.strip())
        event = state.terminal_event or {}
        ok = bool(event.get("ok")) or str(event.get("type") or "") == "finished"
        cancelled = bool(event.get("cancelled")) or state.cancel_requested
        if exit_code == 0 and ok:
            app_logger.log_info("EXPORT_JOB_COMPLETED", f"job_id={job_id} type={state.job.job_type} output={state.job.output_path}")
            self.finished.emit(event)
        else:
            message = self._failed_message(state, event, exit_code, cancelled)
            payload = {
                "type": "error",
                "job_id": job_id,
                "message": message,
                "error": message,
                "traceback": event.get("traceback") or state.stderr_buffer,
                "output_path": state.job.output_path,
                "cancelled": cancelled,
            }
            if cancelled:
                app_logger.log_info("EXPORT_JOB_CANCELLED", f"job_id={job_id} type={state.job.job_type}")
                self.cancelled.emit(payload)
            else:
                app_logger.log_error("EXPORT_JOB_FAILED", f"job_id={job_id} type={state.job.job_type} error={message}")
            self._cleanup_tmp_file(state)
            self.failed.emit(payload)
        self._cleanup_job_files(state)
        state.process.deleteLater()

    def _handle_process_error(self, job_id: str, _error: QProcess.ProcessError) -> None:
        state = self._jobs.pop(job_id, None)
        if state is None:
            return
        message = state.process.errorString() or "导出进程启动失败"
        app_logger.log_error("EXPORT_JOB_FAILED", f"job_id={job_id} type={state.job.job_type} error={message}")
        self._cleanup_tmp_file(state)
        self._cleanup_job_files(state)
        self.failed.emit({"type": "error", "job_id": job_id, "message": f"导出失败：{message}", "error": message, "cancelled": False})
        state.process.deleteLater()

    def _failed_message(self, state: _RunningExport, event: dict[str, Any], exit_code: int, cancelled: bool) -> str:
        if cancelled:
            return "已取消导出"
        message = str(event.get("message") or event.get("error") or "").strip()
        if not message:
            message = state.stderr_buffer.strip() or f"导出进程异常退出，退出码 {exit_code}"
        if any(token in message.lower() for token in ("permission", "access is denied", "另一个程序", "占用")):
            return "导出失败：目标文件可能已被 WPS/Excel 打开，请关闭后重试。"
        return message if message.startswith("导出失败") else f"导出失败：{message}"

    def _kill_if_running(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        if state.process.state() != QProcess.NotRunning:
            state.process.kill()

    def _cleanup_tmp_file(self, state: _RunningExport) -> None:
        try:
            if state.tmp_path.exists():
                state.tmp_path.unlink()
        except OSError:
            pass

    def _cleanup_job_files(self, state: _RunningExport) -> None:
        for path in (state.job_path, state.cancel_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
