from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core import app_logger
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.runtime.task_event_hub import TaskEventHub
from netconsole.services.job_center.runtime.task_state import TaskState
from netconsole.services.job_center.worker_protocol import feed_jsonl, parse_event_line
from netconsole.utils.text_encoding import Utf8IncrementalTextDecoder
from netconsole.services.job_center.web_export_event_safety import (
    is_web_export_task,
    redact_web_export_text,
    sanitize_web_export_event,
)


@dataclass(frozen=True)
class TaskLaunch:
    job: BackgroundJob
    job_path: Path
    cancel_path: Path
    program: str
    arguments: tuple[str, ...]
    working_directory: Path
    environment: dict[str, str]


@dataclass
class _RuntimeTask:
    launch: TaskLaunch
    state: TaskState = TaskState.PENDING
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    terminal_event: dict[str, object] | None = None
    cancel_requested: bool = False
    stdout_decoder: Utf8IncrementalTextDecoder = field(
        default_factory=lambda: Utf8IncrementalTextDecoder(source="worker_stdout")
    )
    stderr_decoder: Utf8IncrementalTextDecoder = field(
        default_factory=lambda: Utf8IncrementalTextDecoder(source="worker_stderr")
    )
    encoding_logged: bool = False


class TaskRuntime:
    """不依赖 Qt 的任务协议、状态和临时文件运行时。"""

    def __init__(self, paths: PathResolver | None = None, event_bus: TaskEventHub | None = None) -> None:
        self.paths = paths or PathResolver()
        self.events = event_bus or TaskEventHub()
        self._tasks: dict[str, _RuntimeTask] = {}

    def prepare(self, job: BackgroundJob) -> TaskLaunch:
        job_id = job.job_id or uuid.uuid4().hex
        if job_id in self._tasks:
            raise RuntimeError("同一后台任务正在执行")
        job_dir = self.paths.runtime_cache_dir / "background_jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        cancel_path = job_dir / f"{job_id}.cancel"
        runtime_job = BackgroundJob.from_dict({**job.to_dict(), "job_id": job_id}).with_runtime_paths(cancel_path=str(cancel_path))
        runtime_job.validate()
        job_path = job_dir / f"{job_id}.json"
        job_path.write_text(json.dumps(runtime_job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        program, arguments = self.worker_command(job_path)
        working_directory = self.worker_code_root()
        environment = dict(os.environ)
        existing_python_path = environment.get("PYTHONPATH", "")
        root_text = str(working_directory)
        environment["PYTHONPATH"] = root_text if not existing_python_path else f"{root_text}{os.pathsep}{existing_python_path}"
        launch = TaskLaunch(
            job=runtime_job,
            job_path=job_path,
            cancel_path=cancel_path,
            program=program,
            arguments=tuple(arguments),
            working_directory=working_directory,
            environment=environment,
        )
        self._tasks[job_id] = _RuntimeTask(launch=launch)
        self._set_state(job_id, TaskState.PENDING)
        self._set_state(job_id, TaskState.STARTING)
        return launch

    def mark_running(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is not None and task.state in {TaskState.PENDING, TaskState.STARTING}:
            self._set_state(job_id, TaskState.RUNNING)

    def feed_stdout(self, job_id: str, chunk: bytes) -> None:
        task = self._tasks.get(job_id)
        if task is None:
            return
        decoded = task.stdout_decoder.decode(chunk)
        self._record_decode_status(task, "stdout", decoded.used_replacement)
        events, diagnostics, task.stdout_buffer = feed_jsonl(
            task.stdout_buffer, decoded.text
        )
        for line in diagnostics:
            message = redact_web_export_text(line) if is_web_export_task(task.launch.job.task_type) else line
            self.events.publish({"type": "diagnostic", "job_id": job_id, "message": message}, source="worker")
        for event in events:
            self._accept_worker_event(task, event)

    def feed_stderr(self, job_id: str, chunk: bytes) -> None:
        task = self._tasks.get(job_id)
        if task is not None:
            decoded = task.stderr_decoder.decode(chunk)
            self._record_decode_status(task, "stderr", decoded.used_replacement)
            task.stderr_buffer += decoded.text

    def request_cancel(self, job_id: str) -> int:
        task = self._tasks.get(job_id)
        if task is None:
            return 0
        task.cancel_requested = True
        self._set_state(job_id, TaskState.STOPPING)
        self._write_cancel_file(task)
        try:
            value = int(task.launch.job.params.get("_cancel_grace_ms") or 0)
        except (TypeError, ValueError):
            value = 0
        return max(0, min(value, 60000))

    def complete(self, job_id: str, exit_code: int) -> dict[str, object] | None:
        task = self._tasks.get(job_id)
        if task is None:
            return None
        self._flush_decoders(task)
        if task.stdout_buffer.strip():
            event = parse_event_line(task.stdout_buffer.strip())
            if event is not None:
                self._accept_worker_event(task, event)
        event = task.terminal_event or {}
        cancelled = bool(event.get("cancelled")) or task.cancel_requested
        if exit_code == 0 and str(event.get("type") or "") == "finished":
            payload = event
            terminal_state = self._finished_terminal_state(event)
        else:
            message = str(event.get("message") or event.get("error") or task.stderr_buffer.strip() or f"后台任务异常退出，退出码 {exit_code}")
            payload = {
                "type": "cancelled" if cancelled else "error",
                "job_id": job_id,
                "stage": "",
                "current": 0,
                "total": 0,
                "message": message,
                "result": None,
                "error": message,
                "traceback": str(event.get("traceback") or task.stderr_buffer),
                "cancelled": cancelled,
            }
            terminal_state = TaskState.CANCELLED if cancelled else TaskState.FAILED
        if is_web_export_task(task.launch.job.task_type):
            payload = sanitize_web_export_event(payload)
        self.events.publish(payload)
        app_logger.log_info(
            "TASK_TEXT_PERSISTED",
            f"job_id={job_id}; terminal_type={payload.get('type', '')}",
        )
        self._set_state(job_id, terminal_state)
        self._finish(job_id)
        return payload

    def fail_start(self, job_id: str, message: str) -> dict[str, object] | None:
        task = self._tasks.get(job_id)
        if task is None:
            return None
        cancelled = task.cancel_requested
        payload = {
            "type": "cancelled" if cancelled else "error",
            "job_id": job_id,
            "stage": "",
            "current": 0,
            "total": 0,
            "message": "后台任务已取消" if cancelled else str(message or "后台进程启动失败"),
            "result": None,
            "error": "后台任务已取消" if cancelled else str(message or "后台进程启动失败"),
            "traceback": "",
            "cancelled": cancelled,
        }
        if is_web_export_task(task.launch.job.task_type):
            payload = sanitize_web_export_event(payload)
        self.events.publish(payload)
        self._set_state(job_id, TaskState.CANCELLED if cancelled else TaskState.FAILED)
        self._finish(job_id)
        return payload

    def abandon(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is None:
            return
        task.cancel_requested = True
        self._write_cancel_file(task)
        self._set_state(job_id, TaskState.CANCELLED)
        self._finish(job_id)

    def is_running(self, job_id: str) -> bool:
        return job_id in self._tasks

    def worker_command(self, job_path: Path) -> tuple[str, list[str]]:
        if getattr(sys, "frozen", False):
            return sys.executable, ["--background-worker", "--job", str(job_path)]
        return sys.executable, ["-m", "netconsole.background_worker", "--job", str(job_path)]

    def worker_code_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return self.paths.app_root
        return Path(__file__).resolve().parents[4]

    def _accept_worker_event(self, task: _RuntimeTask, event: dict[str, object]) -> None:
        if _contains_replacement_character(event):
            self._record_decode_status(task, "event", True)
        if is_web_export_task(task.launch.job.task_type):
            event = sanitize_web_export_event(event)
        event_type = str(event.get("type") or "")
        if event_type in {"finished", "error", "cancelled"}:
            task.terminal_event = event
            return
        if event_type:
            self.events.publish(event, source="worker")

    def _flush_decoders(self, task: _RuntimeTask) -> None:
        stdout = task.stdout_decoder.decode(b"", final=True)
        self._record_decode_status(task, "stdout", stdout.used_replacement)
        if stdout.text:
            events, diagnostics, task.stdout_buffer = feed_jsonl(
                task.stdout_buffer, stdout.text
            )
            for line in diagnostics:
                self.events.publish(
                    {
                        "type": "diagnostic",
                        "job_id": task.launch.job.job_id,
                        "message": line,
                    },
                    source="worker",
                )
            for event in events:
                self._accept_worker_event(task, event)
        stderr = task.stderr_decoder.decode(b"", final=True)
        self._record_decode_status(task, "stderr", stderr.used_replacement)
        task.stderr_buffer += stderr.text

    @staticmethod
    def _record_decode_status(
        task: _RuntimeTask,
        stream: str,
        used_replacement: bool,
    ) -> None:
        job_id = task.launch.job.job_id
        if not task.encoding_logged:
            app_logger.log_info(
                "TASK_TEXT_ENCODING_DETECTED",
                f"job_id={job_id}; encoding=utf-8",
            )
            task.encoding_logged = True
        if used_replacement:
            app_logger.log_warning(
                "TASK_TEXT_DECODE_WARNING",
                f"job_id={job_id}; stream={stream}; encoding=utf-8",
            )

    @staticmethod
    def _finished_terminal_state(event: dict[str, object]) -> TaskState:
        state_text = str(event.get("terminal_state") or "").strip().upper()
        if not state_text:
            return TaskState.COMPLETED
        try:
            state = TaskState(state_text)
        except ValueError:
            return TaskState.COMPLETED
        if state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            return state
        return TaskState.COMPLETED

    def _set_state(self, job_id: str, state: TaskState) -> None:
        task = self._tasks.get(job_id)
        if task is not None:
            task.state = state
        self.events.publish(
            {
                "type": "state",
                "job_id": job_id,
                "task_type": task.launch.job.task_type if task is not None else "",
                "state": state.value,
            }
        )

    @staticmethod
    def _write_cancel_file(task: _RuntimeTask) -> None:
        try:
            task.launch.cancel_path.parent.mkdir(parents=True, exist_ok=True)
            task.launch.cancel_path.write_text("cancelled", encoding="utf-8")
        except OSError:
            # 取消文件失败后仍由宿主执行 terminate/kill，不能让 UI 取消入口抛异常。
            pass

    def _finish(self, job_id: str) -> None:
        task = self._tasks.pop(job_id, None)
        if task is None:
            return
        for path in (task.launch.job_path, task.launch.cancel_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


def _contains_replacement_character(value: object) -> bool:
    if isinstance(value, str):
        return "\ufffd" in value
    if isinstance(value, dict):
        return any(_contains_replacement_character(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_replacement_character(item) for item in value)
    return False
