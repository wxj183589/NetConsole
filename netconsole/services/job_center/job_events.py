from __future__ import annotations

from typing import Any


def _event(event_type: str, job_id: str, **values: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "job_id": str(job_id or ""),
        "stage": "",
        "current": 0,
        "total": 0,
        "message": "",
        "result": None,
        "error": "",
        "traceback": "",
        "cancelled": False,
    }
    event.update(values)
    return event


def progress_event(job_id: str, stage: str, current: int = 0, total: int = 0, message: str = "") -> dict[str, Any]:
    return _event(
        "progress",
        job_id,
        stage=str(stage or ""),
        current=int(current or 0),
        total=int(total or 0),
        message=str(message or stage or ""),
    )


def log_event(job_id: str, message: str, *, stage: str = "", level: str = "info") -> dict[str, Any]:
    return _event("log", job_id, stage=str(stage or ""), message=str(message or ""), level=str(level or "info"))


def finished_event(job_id: str, result: dict[str, Any] | None = None, message: str = "后台任务完成") -> dict[str, Any]:
    return _event("finished", job_id, message=str(message or "后台任务完成"), result=dict(result or {}))


def error_event(job_id: str, error: str, *, message: str = "", traceback_text: str = "") -> dict[str, Any]:
    error_text = str(error or message or "后台任务失败")
    return _event(
        "error",
        job_id,
        message=str(message or error_text),
        error=error_text,
        traceback=str(traceback_text or ""),
    )


def cancelled_event(job_id: str, message: str = "后台任务已取消") -> dict[str, Any]:
    message_text = str(message or "后台任务已取消")
    return _event("cancelled", job_id, message=message_text, error=message_text, cancelled=True)
