from __future__ import annotations

from typing import Any


def progress_event(
    job_id: str,
    stage: str,
    *,
    current: int = 0,
    total: int = 0,
    message: str = "",
) -> dict[str, Any]:
    value = int(current or 0)
    return {
        "type": "progress",
        "job_id": job_id,
        "stage": stage,
        "current": value,
        "done": value,
        "total": int(total or 0),
        "message": message or stage,
    }


def finished_event(job_id: str, output_path: str, *, message: str = "导出完成", row_count: int = 0) -> dict[str, Any]:
    return {
        "type": "finished",
        "job_id": job_id,
        "ok": True,
        "output_path": output_path,
        "message": message,
        "row_count": int(row_count or 0),
    }


def error_event(
    job_id: str,
    message: str,
    *,
    traceback_text: str = "",
    output_path: str = "",
    cancelled: bool = False,
) -> dict[str, Any]:
    return {
        "type": "error",
        "job_id": job_id,
        "ok": False,
        "output_path": output_path,
        "message": message,
        "error": message,
        "traceback": traceback_text,
        "cancelled": bool(cancelled),
    }
