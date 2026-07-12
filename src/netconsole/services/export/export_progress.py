from __future__ import annotations

from typing import Any

from netconsole.services.job_center.job_events import (
    cancelled_event as job_cancelled_event,
    error_event as job_error_event,
    finished_event as job_finished_event,
    progress_event as job_progress_event,
)


def progress_event(
    job_id: str,
    stage: str,
    *,
    current: int = 0,
    total: int = 0,
    message: str = "",
) -> dict[str, Any]:
    value = int(current or 0)
    event = job_progress_event(job_id, stage, value, int(total or 0), message or stage)
    event.update({"event": "progress", "done": value})
    return event


def finished_event(job_id: str, output_path: str, *, message: str = "导出完成", row_count: int = 0) -> dict[str, Any]:
    result = {"output_path": output_path, "row_count": int(row_count or 0)}
    event = job_finished_event(job_id, result, message)
    event.update(
        {
            "event": "finished",
            "ok": True,
            "output_path": output_path,
            "row_count": int(row_count or 0),
        }
    )
    return event


def error_event(
    job_id: str,
    message: str,
    *,
    traceback_text: str = "",
    output_path: str = "",
    cancelled: bool = False,
) -> dict[str, Any]:
    event = (
        job_cancelled_event(job_id, message)
        if cancelled
        else job_error_event(job_id, message, traceback_text=traceback_text)
    )
    event.update(
        {
            "event": "cancelled" if cancelled else "error",
            "ok": False,
            "output_path": output_path,
            "traceback": traceback_text,
            "cancelled": bool(cancelled),
        }
    )
    return event
