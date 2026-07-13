from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.task_application_service import TaskApplicationService

WORKER_SECRET_ENV_PREFIX = "NETCONSOLE_JOB_SECRET_"


@dataclass
class _RunningBackgroundJob:
    job: BackgroundJob
    process: QProcess
    job_path: Path
    cancel_path: Path


class BackgroundProcessManager(QObject):
    """Qt/QProcess Adapter；任务协议与状态由纯 Python TaskRuntime 管理。"""

    state_changed = Signal(dict)
    progress = Signal(dict)
    log = Signal(dict)
    finished = Signal(dict)
    failed = Signal(dict)
    cancelled = Signal(dict)

    def __init__(self, parent: QObject | None = None, *, paths: PathResolver | None = None) -> None:
        super().__init__(parent)
        self.paths = paths or PathResolver()
        self.task_service = TaskApplicationService(paths=self.paths)
        self.task_service.events.subscribe(self._handle_runtime_event)
        self._jobs: dict[str, _RunningBackgroundJob] = {}
        if parent is not None:
            parent.destroyed.connect(self.shutdown)

    def start_job(self, job: BackgroundJob, *, environment: dict[str, str] | None = None) -> str:
        launch = self.task_service.prepare(job)
        job_id = launch.job.job_id
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        self._jobs[job_id] = _RunningBackgroundJob(
            job=launch.job,
            process=process,
            job_path=launch.job_path,
            cancel_path=launch.cancel_path,
        )
        process.started.connect(lambda job_id=job_id: self.task_service.mark_running(job_id))
        process.readyReadStandardOutput.connect(lambda job_id=job_id: self._read_stdout(job_id))
        process.readyReadStandardError.connect(lambda job_id=job_id: self._read_stderr(job_id))
        process.errorOccurred.connect(lambda _error, job_id=job_id: self._handle_process_error(job_id))
        process.finished.connect(lambda exit_code, _exit_status, job_id=job_id: self._handle_finished(job_id, exit_code))
        program, args = self._worker_command(launch.job_path)
        worker_root = self._worker_code_root()
        process.setWorkingDirectory(str(worker_root))
        process.setProcessEnvironment(self._worker_environment(worker_root, environment))
        app_logger.log_info("BACKGROUND_JOB_STARTED", f"job_id={job_id} type={launch.job.task_type}")
        process.start(program, args)
        return job_id

    def cancel_job(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        grace_ms = self.task_service.request_cancel(job_id)
        if grace_ms > 0:
            QTimer.singleShot(grace_ms, lambda job_id=job_id: self._terminate_if_running(job_id))
        else:
            self._terminate_if_running(job_id)

    def force_stop_job(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        self.task_service.request_cancel(job_id)
        try:
            if state.process.state() != QProcess.NotRunning:
                state.process.kill()
        except RuntimeError:
            pass

    def shutdown(self) -> None:
        """父页面销毁前终止内部 worker，避免遗留子进程。"""

        for job_id, state in list(self._jobs.items()):
            self.task_service.request_cancel(job_id)
            try:
                if state.process.state() != QProcess.NotRunning:
                    state.process.kill()
                    state.process.waitForFinished(1000)
            except RuntimeError:
                pass
            self._jobs.pop(job_id, None)
            self.task_service.abandon(job_id)

    def is_running(self, job_id: str) -> bool:
        return self.task_service.is_running(job_id)

    def _worker_command(self, job_path: Path) -> tuple[str, list[str]]:
        return self.task_service.runtime.worker_command(job_path)

    def _worker_code_root(self) -> Path:
        return self.task_service.runtime.worker_code_root()

    def _worker_environment(
        self,
        worker_root: Path,
        additions: dict[str, str] | None = None,
    ) -> QProcessEnvironment:
        environment = QProcessEnvironment.systemEnvironment()
        existing = environment.value("PYTHONPATH")
        root_text = str(worker_root)
        environment.insert("PYTHONPATH", root_text if not existing else f"{root_text}{os.pathsep}{existing}")
        for key, value in dict(additions or {}).items():
            if key and value:
                if not str(key).startswith(WORKER_SECRET_ENV_PREFIX):
                    raise ValueError("后台任务临时环境变量必须使用受控密钥前缀")
                environment.insert(str(key), str(value))
        return environment

    def _read_stdout(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        try:
            chunk = bytes(state.process.readAllStandardOutput())
        except RuntimeError:
            return
        self.task_service.feed_stdout(job_id, chunk)

    def _read_stderr(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        try:
            chunk = bytes(state.process.readAllStandardError())
        except RuntimeError:
            return
        self.task_service.feed_stderr(job_id, chunk)

    def _handle_runtime_event(self, event: dict[str, object]) -> None:
        event_type = str(event.get("type") or "")
        payload = dict(event.get("payload") or {})
        payload.setdefault("type", event_type)
        payload.setdefault("job_id", str(event.get("task_id") or ""))
        if event_type == "state":
            self._safe_emit(self.state_changed, payload)
        elif event_type == "diagnostic":
            app_logger.log_info("BACKGROUND_JOB_OUTPUT", str(payload.get("message") or ""))
        elif event_type == "log":
            app_logger.log_info("BACKGROUND_JOB_PROCESS_LOG", str(payload.get("message") or ""))
            self._safe_emit(self.log, payload)
        elif event_type == "progress":
            self._safe_emit(self.progress, payload)
        elif event_type == "finished":
            app_logger.log_info("BACKGROUND_JOB_COMPLETED", f"job_id={payload.get('job_id', '')}")
            self._safe_emit(self.finished, payload)
        elif event_type == "cancelled":
            app_logger.log_info("BACKGROUND_JOB_CANCELLED", f"job_id={payload.get('job_id', '')}")
            self._safe_emit(self.cancelled, payload)
        elif event_type == "error":
            app_logger.log_error(
                "BACKGROUND_JOB_FAILED",
                f"job_id={payload.get('job_id', '')} error={payload.get('error') or payload.get('message') or ''}",
            )
            self._safe_emit(self.failed, payload)

    def _handle_finished(self, job_id: str, exit_code: int) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        self._read_stdout(job_id)
        self._read_stderr(job_id)
        self._jobs.pop(job_id, None)
        self.task_service.complete(job_id, exit_code)
        self._safe_delete_process(state.process)

    def _handle_process_error(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        self._read_stdout(job_id)
        self._read_stderr(job_id)
        self._jobs.pop(job_id, None)
        try:
            message = state.process.errorString() or "后台进程启动失败"
        except RuntimeError:
            message = "后台进程启动失败"
        self.task_service.fail_start(job_id, message)
        self._safe_delete_process(state.process)

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

    def _kill_if_running(self, job_id: str) -> None:
        state = self._jobs.get(job_id)
        if state is None:
            return
        try:
            if state.process.state() != QProcess.NotRunning:
                state.process.kill()
        except RuntimeError:
            pass

    @staticmethod
    def _safe_emit(signal: Signal, payload: dict[str, Any]) -> None:
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    @staticmethod
    def _safe_delete_process(process: QProcess) -> None:
        try:
            process.deleteLater()
        except RuntimeError:
            pass


TaskManager = BackgroundProcessManager


__all__ = ["BackgroundProcessManager", "TaskManager"]
