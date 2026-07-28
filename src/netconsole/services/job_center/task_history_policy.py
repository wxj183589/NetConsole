from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from netconsole.models.task_state import TaskState


ACTIVE_TASK_STATE_VALUES = frozenset(
    {
        TaskState.PENDING.value,
        TaskState.STARTING.value,
        TaskState.RUNNING.value,
        TaskState.STOPPING.value,
    }
)
TERMINAL_TASK_STATE_VALUES = frozenset(
    {
        TaskState.COMPLETED.value,
        TaskState.FAILED.value,
        TaskState.CANCELLED.value,
    }
)


def business_result_has_warning(result: dict[str, Any]) -> bool:
    if not result:
        return False
    outcome = str(
        result.get("business_outcome")
        or result.get("status")
        or result.get("outcome")
        or ""
    ).upper()
    if outcome in {"PARTIAL_SUCCESS", "WARNING"}:
        return True
    if result.get("partial_success") is True:
        return True
    for key in ("failed_count", "warning_count", "actionable_skipped_count"):
        if _optional_int(result.get(key)) > 0:
            return True
    summary = result.get("summary")
    if isinstance(summary, dict):
        for key in ("failed", "failed_count", "warning", "warning_count", "rejected"):
            if _optional_int(summary.get(key)) > 0:
                return True
    return False


def task_requires_attention(
    status: str | TaskState,
    *,
    error_message: str = "",
    result: dict[str, Any] | None = None,
) -> bool:
    value = str(status).upper()
    if value == TaskState.FAILED.value:
        return True
    return value == TaskState.COMPLETED.value and (
        bool(str(error_message or "").strip())
        or business_result_has_warning(dict(result or {}))
    )


def task_expires_at(
    status: str | TaskState,
    *,
    finished_time: str,
    updated_time: str,
    error_message: str = "",
    result: dict[str, Any] | None = None,
) -> str:
    value = str(status).upper()
    if value not in TERMINAL_TASK_STATE_VALUES:
        return ""
    finished = _parse_utc(finished_time or updated_time)
    if finished is None:
        return ""
    retention_days = (
        30
        if task_requires_attention(
            value,
            error_message=error_message,
            result=result,
        )
        else 7
    )
    return _utc_iso(finished + timedelta(days=retention_days))


def utc_time_reached(value: str, *, now: datetime | None = None) -> bool:
    target = _parse_utc(value)
    if target is None:
        return False
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return target <= current.astimezone(UTC)


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _optional_int(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


__all__ = [
    "ACTIVE_TASK_STATE_VALUES",
    "TERMINAL_TASK_STATE_VALUES",
    "business_result_has_warning",
    "task_expires_at",
    "task_requires_attention",
    "utc_time_reached",
]
