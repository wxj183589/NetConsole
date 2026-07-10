from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QProcess

from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob

ProgressHandler = Callable[[dict[str, Any]], None]
CancelChecker = Callable[[], bool]


class BackgroundProcessBridgeCancelled(RuntimeError):
    pass


def run_background_job_process(
    *,
    task_type: str,
    params: dict[str, Any],
    progress_handler: ProgressHandler | None = None,
    should_cancel: CancelChecker | None = None,
    paths: PathResolver | None = None,
) -> dict[str, Any]:
    resolver = paths or PathResolver()
    if not (resolver.app_root / "netconsole").is_dir():
        resolver = PathResolver(data_root=resolver.data_root)
    job_id = uuid.uuid4().hex
    job_dir = resolver.runtime_cache_dir / "background_jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    cancel_path = job_dir / f"{job_id}.cancel"
    job_path = job_dir / f"{job_id}.json"
    job_params = dict(params)
    job_params.setdefault("app_root", str(resolver.app_root))
    job_params.setdefault("data_root", str(resolver.data_root))
    job = BackgroundJob(job_id=job_id, task_type=task_type, params=job_params).with_runtime_paths(cancel_path=str(cancel_path))
    job_path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    process = QProcess()
    process.setProgram(sys.executable)
    process.setArguments(["-m", "netconsole.background_worker", "--job", str(job_path)])
    process.setWorkingDirectory(str(resolver.app_root))
    process.setProcessChannelMode(QProcess.SeparateChannels)
    process.start()
    if not process.waitForStarted(5000):
        _cleanup(job_path, cancel_path)
        raise RuntimeError(process.errorString() or "后台进程启动失败")

    stdout_buffer = ""
    terminal_event: dict[str, Any] | None = None
    cancel_started_at: float | None = None
    while process.state() != QProcess.NotRunning:
        if should_cancel and should_cancel():
            if not cancel_path.exists():
                cancel_path.write_text("cancelled", encoding="utf-8")
            cancel_started_at = cancel_started_at or time.monotonic()
            if time.monotonic() - cancel_started_at > 8:
                process.terminate()
            if time.monotonic() - cancel_started_at > 12:
                process.kill()
        if process.waitForReadyRead(100):
            stdout_buffer, terminal_event = _consume_stdout(process, stdout_buffer, terminal_event, progress_handler)
        process.waitForFinished(1)
    stdout_buffer, terminal_event = _consume_stdout(process, stdout_buffer, terminal_event, progress_handler)
    if stdout_buffer.strip():
        terminal_event = _handle_event_line(stdout_buffer.strip(), terminal_event, progress_handler)

    stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
    exit_code = process.exitCode()
    _cleanup(job_path, cancel_path)
    if terminal_event and terminal_event.get("cancelled"):
        raise BackgroundProcessBridgeCancelled(str(terminal_event.get("message") or "后台任务已取消"))
    if exit_code == 0 and terminal_event and terminal_event.get("type") == "finished":
        return dict(terminal_event.get("result") or {})
    message = str((terminal_event or {}).get("message") or (terminal_event or {}).get("error") or stderr or f"后台任务异常退出，退出码 {exit_code}")
    raise RuntimeError(message)


def _consume_stdout(
    process: QProcess,
    stdout_buffer: str,
    terminal_event: dict[str, Any] | None,
    progress_handler: ProgressHandler | None,
) -> tuple[str, dict[str, Any] | None]:
    stdout_buffer += bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
    while "\n" in stdout_buffer:
        line, stdout_buffer = stdout_buffer.split("\n", 1)
        terminal_event = _handle_event_line(line.strip(), terminal_event, progress_handler)
    return stdout_buffer, terminal_event


def _handle_event_line(line: str, terminal_event: dict[str, Any] | None, progress_handler: ProgressHandler | None) -> dict[str, Any] | None:
    if not line:
        return terminal_event
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return terminal_event
    if not isinstance(event, dict):
        return terminal_event
    event_type = str(event.get("type") or "")
    if event_type == "progress":
        if progress_handler:
            progress_handler(event)
        return terminal_event
    if event_type in {"finished", "error"}:
        return event
    return terminal_event


def _cleanup(*paths: Path) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
