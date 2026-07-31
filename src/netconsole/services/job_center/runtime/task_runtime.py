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
from netconsole.services.job_center.worker_protocol import (
    WORKER_PROTOCOL_MAX_FRAME_BYTES,
    parse_worker_event_line,
)
from netconsole.utils.text_encoding import Utf8IncrementalTextDecoder
from netconsole.services.job_center.web_export_event_safety import (
    is_web_export_task,
    sanitize_web_export_event,
)

WORKER_PROTOCOL_ERROR_CODE = "WORKER_PROTOCOL_CORRUPTED"
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
        default_factory=lambda: Utf8IncrementalTextDecoder(source="worker_stdout", errors="strict")
    )
    stderr_decoder: Utf8IncrementalTextDecoder = field(
        default_factory=lambda: Utf8IncrementalTextDecoder(source="worker_stderr", errors="strict")
    )
    encoding_logged: bool = False
    protocol_error_reason: str = ""
    protocol_error_payload: dict[str, object] | None = None
    protocol_error_frame_bytes: int | None = None


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
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
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

    def feed_stdout(self, job_id: str, chunk: bytes) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.protocol_error_reason:
            return False
        try:
            decoded = task.stdout_decoder.decode(chunk)
        except UnicodeDecodeError:
            self._fail_protocol(task, "worker_protocol_decode_failed", stream="stdout")
            return True
        self._record_encoding(task)
        return self._feed_stdout_text(task, decoded.text)

    def feed_stderr(self, job_id: str, chunk: bytes) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.protocol_error_reason:
            return False
        try:
            decoded = task.stderr_decoder.decode(chunk)
        except UnicodeDecodeError:
            self._fail_protocol(task, "worker_protocol_decode_failed", stream="stderr")
            return True
        self._record_encoding(task)
        if "\ufffd" in decoded.text:
            self._fail_protocol(
                task,
                "replacement_character_detected_in_current_event",
                stream="stderr",
            )
            return True
        task.stderr_buffer += decoded.text
        return False

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
        if not task.protocol_error_reason and task.stdout_buffer.strip():
            if len(task.stdout_buffer.encode("utf-8")) > WORKER_PROTOCOL_MAX_FRAME_BYTES:
                self._fail_protocol(
                    task,
                    "worker_protocol_frame_too_large",
                    stream="stdout",
                    frame_bytes=len(task.stdout_buffer.encode("utf-8")),
                )
            else:
                event, reason = parse_worker_event_line(task.stdout_buffer.strip())
                if reason:
                    self._fail_protocol(task, reason, stream="stdout")
                elif event is not None:
                    self._accept_worker_event(task, event)
        if task.protocol_error_payload is not None:
            payload = dict(task.protocol_error_payload)
            self._attach_worker_exit_code(payload, exit_code)
            terminal_state = TaskState.FAILED
        else:
            event = task.terminal_event or {}
            cancelled = bool(event.get("cancelled")) or task.cancel_requested
            event_type = str(event.get("type") or "")
            if event_type == "cancelled":
                payload = dict(event)
                terminal_state = TaskState.CANCELLED
            elif event_type == "error":
                payload = dict(event)
                self._attach_worker_exit_code(payload, exit_code)
                terminal_state = TaskState.FAILED
            elif exit_code == 0 and event_type == "finished":
                payload = dict(event)
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
                    "result": dict(event.get("result") or {}) if isinstance(event.get("result"), dict) else None,
                    "error": message,
                    "traceback": str(event.get("traceback") or task.stderr_buffer),
                    "cancelled": cancelled,
                }
                self._attach_worker_exit_code(payload, exit_code)
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
        if task.protocol_error_reason:
            app_logger.log_error(
                "WORKER_PROTOCOL_RUNTIME_UNREGISTERED",
                f"job_id={job_id}; worker_exit_code={exit_code}",
            )
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
        if str(event.get("job_id") or "") != task.launch.job.job_id:
            self._fail_protocol(task, "worker_protocol_schema_invalid", stream="event")
            return
        if _contains_replacement_character(event):
            self._fail_protocol(
                task,
                "replacement_character_detected_in_current_event",
                stream="event",
            )
            return
        if is_web_export_task(task.launch.job.task_type):
            event = sanitize_web_export_event(event)
        event_type = str(event.get("type") or "")
        if event_type in {"finished", "error", "cancelled"}:
            task.terminal_event = event
            return
        if event_type:
            self.events.publish(event, source="worker")

    def _flush_decoders(self, task: _RuntimeTask) -> None:
        if task.protocol_error_reason:
            return
        try:
            stdout = task.stdout_decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            self._fail_protocol(task, "worker_protocol_decode_failed", stream="stdout")
            return
        self._record_encoding(task)
        if stdout.text:
            if self._feed_stdout_text(task, stdout.text):
                return
        try:
            stderr = task.stderr_decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            self._fail_protocol(task, "worker_protocol_decode_failed", stream="stderr")
            return
        if "\ufffd" in stderr.text:
            self._fail_protocol(
                task,
                "replacement_character_detected_in_current_event",
                stream="stderr",
            )
            return
        task.stderr_buffer += stderr.text

    def _feed_stdout_text(self, task: _RuntimeTask, text: str) -> bool:
        combined = task.stdout_buffer + str(text or "")
        lines = combined.split("\n")
        task.stdout_buffer = lines.pop()
        if len(task.stdout_buffer.encode("utf-8")) > WORKER_PROTOCOL_MAX_FRAME_BYTES:
            self._fail_protocol(
                task,
                "worker_protocol_frame_too_large",
                stream="stdout",
                frame_bytes=len(task.stdout_buffer.encode("utf-8")),
            )
            return True
        for raw_line in lines:
            line = raw_line.rstrip("\r").strip()
            if not line:
                continue
            if len(line.encode("utf-8")) > WORKER_PROTOCOL_MAX_FRAME_BYTES:
                self._fail_protocol(
                    task,
                    "worker_protocol_frame_too_large",
                    stream="stdout",
                    frame_bytes=len(line.encode("utf-8")),
                )
                return True
            event, reason = parse_worker_event_line(line)
            if reason:
                self._fail_protocol(task, reason, stream="stdout")
                return True
            assert event is not None
            self._accept_worker_event(task, event)
            if task.protocol_error_reason:
                return True
        return False

    @staticmethod
    def _record_encoding(task: _RuntimeTask) -> None:
        job_id = task.launch.job.job_id
        if not task.encoding_logged:
            app_logger.log_info(
                "TASK_TEXT_ENCODING_DETECTED",
                f"job_id={job_id}; encoding=utf-8-strict",
            )
            task.encoding_logged = True

    def _fail_protocol(
        self,
        task: _RuntimeTask,
        reason: str,
        *,
        stream: str,
        frame_bytes: int | None = None,
    ) -> None:
        if task.protocol_error_reason:
            return
        task.protocol_error_reason = str(reason)
        task.protocol_error_frame_bytes = frame_bytes
        app_logger.log_error(
            "WORKER_PROTOCOL_FATAL_ERROR",
            (
                f"job_id={task.launch.job.job_id}; reason={reason}; stream={stream}; "
                f"frame_bytes={frame_bytes if frame_bytes is not None else ''}; "
                f"max_frame_bytes={WORKER_PROTOCOL_MAX_FRAME_BYTES}; "
                f"worker_mode={'frozen' if getattr(sys, 'frozen', False) else 'source'}"
            ),
        )
        job_id = task.launch.job.job_id
        message = "Worker 内部通信协议损坏，任务已强制终止。"
        payload: dict[str, object] = {
            "type": "error",
            "job_id": job_id,
            "stage": "worker_protocol",
            "current": 0,
            "total": 0,
            "message": message,
            "result": {
                "error_code": WORKER_PROTOCOL_ERROR_CODE,
                "text_integrity": "current_corrupted",
                "text_integrity_reason": reason,
                "reason": reason,
                "stream": stream,
                "frame_bytes": frame_bytes,
                "max_frame_bytes": WORKER_PROTOCOL_MAX_FRAME_BYTES,
                "worker_exit_code": None,
                "data_persisted": None,
            },
            "error": message,
            "error_code": WORKER_PROTOCOL_ERROR_CODE,
            "reason": reason,
            "stream": stream,
            "frame_bytes": frame_bytes,
            "max_frame_bytes": WORKER_PROTOCOL_MAX_FRAME_BYTES,
            "traceback": "",
            "cancelled": False,
        }
        task.protocol_error_payload = payload
        app_logger.log_error("WORKER_PROTOCOL_TASK_FAILED", f"job_id={job_id}; error_code={WORKER_PROTOCOL_ERROR_CODE}")

    @staticmethod
    def _attach_worker_exit_code(payload: dict[str, object], exit_code: int) -> None:
        payload["worker_exit_code"] = int(exit_code)
        result = payload.get("result")
        if not isinstance(result, dict):
            result = {}
        else:
            result = dict(result)
        result["worker_exit_code"] = int(exit_code)
        result.setdefault("data_persisted", None)
        payload["result"] = result

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
