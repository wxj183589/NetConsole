from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BusinessResultProjection:
    """任务结果的只读兼容投影，不改变 Worker 的七状态生命周期。"""

    business_status: str = ""
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    partial_success: bool = False
    primary_failure_reason: str = ""


_BUSINESS_STATUS_ALIASES = {
    "COMPLETED": "SUCCESS",
    "DONE": "SUCCESS",
    "OK": "SUCCESS",
    "NO_TARGET": "NO_EFFECTIVE_TARGET",
    "NO_TARGETS": "NO_EFFECTIVE_TARGET",
    "NO_EFFECTIVE_TARGET": "NO_EFFECTIVE_TARGET",
    "NO_DATA": "NO_EFFECTIVE_TARGET",
    "PARTIAL": "PARTIAL_SUCCESS",
    "PARTIAL_FAILED": "PARTIAL_SUCCESS",
    "PARTIAL_SUCCESS": "PARTIAL_SUCCESS",
    "SUCCESS": "SUCCESS",
    "SUCCESS_WITH_WARNINGS": "SUCCESS_WITH_WARNINGS",
    "REMOTE_RESULT_UNKNOWN": "REMOTE_RESULT_UNKNOWN",
    "WARNING": "WARNING",
    "ERROR": "FAILED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
}


def project_business_result(
    result: Mapping[str, Any] | None,
    *,
    lifecycle_status: str = "",
    error_message: str = "",
) -> BusinessResultProjection:
    """将历史/异构任务结果投影成稳定的 Job Center 业务字段。

    结果只在查询时读取。特别是旧的 ``NO_TARGET`` 仅映射为
    ``NO_EFFECTIVE_TARGET``，不会回写任务数据库。
    """

    source = dict(result or {})
    nested = _nested_business_result(source)
    # 顶层字段优先，旧 handler 的 collection/summary 作为兼容回退。
    merged = {**nested, **source}
    lifecycle = str(lifecycle_status or "").upper()
    raw_status = _first_text(
        merged,
        "business_status",
        "business_outcome",
        "status",
        "outcome",
    ).upper()
    business_status = (
        _BUSINESS_STATUS_ALIASES.get(raw_status, "UNKNOWN")
        if raw_status
        else ""
    )

    success_count = _count(
        merged,
        "success_count",
        "succeeded_count",
        "successful_count",
        "completed_count",
        "processed_count",
        "deleted",
        "success",
    )
    failed_count = _count(
        merged,
        "failed_count",
        "failure_count",
        "failed",
        "errors_count",
        "rejected_count",
    )
    skipped_count = _count(
        merged,
        "skipped_count",
        "actionable_skipped_count",
        "skipped",
        "not_executed_count",
    )
    warning_count = _count(
        merged,
        "warning_count",
        "warnings_count",
        "warnings",
    )
    partial_success = bool(merged.get("partial_success") is True)

    if not business_status:
        if lifecycle == "CANCELLED":
            business_status = "CANCELLED"
        elif lifecycle == "FAILED":
            business_status = "FAILED"
        elif lifecycle == "COMPLETED":
            if success_count > 0 and (failed_count > 0 or skipped_count > 0):
                business_status = "PARTIAL_SUCCESS"
            elif failed_count > 0:
                business_status = "FAILED"
            elif warning_count > 0:
                business_status = "WARNING"
            elif skipped_count > 0 and success_count == 0:
                business_status = "NO_EFFECTIVE_TARGET"
            elif source:
                business_status = "SUCCESS"
            else:
                business_status = "UNKNOWN"
        elif lifecycle in ACTIVE_TASK_STATE_VALUES:
            business_status = ""
        else:
            business_status = "UNKNOWN" if source else ""

    if business_status == "PARTIAL_SUCCESS":
        partial_success = True
    elif (
        lifecycle == "COMPLETED"
        and success_count > 0
        and (failed_count > 0 or skipped_count > 0)
    ):
        partial_success = True

    primary_failure_reason = _first_text(
        merged,
        "primary_failure_reason",
        "failure_reason",
        "error_code",
        "error",
        "error_message",
        "reason",
    )
    if not primary_failure_reason:
        primary_failure_reason = _dominant_reason(
            merged.get("failure_reason_counts")
        )
    if not primary_failure_reason:
        primary_failure_reason = _dominant_reason(
            merged.get("skipped_reason_counts")
        )
    if not primary_failure_reason and lifecycle == "FAILED":
        primary_failure_reason = str(error_message or "").strip()

    return BusinessResultProjection(
        business_status=business_status,
        success_count=success_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        warning_count=warning_count,
        partial_success=partial_success,
        primary_failure_reason=primary_failure_reason,
    )


def business_result_has_warning(result: dict[str, Any]) -> bool:
    if not result:
        return False
    result = {**_nested_business_result(result), **result}
    outcome = str(
        result.get("business_outcome")
        or result.get("status")
        or result.get("outcome")
        or ""
    ).upper()
    if outcome in {"PARTIAL_SUCCESS", "SUCCESS_WITH_WARNINGS", "WARNING"}:
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


def _nested_business_result(source: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("business_result", "collection", "summary"):
        value = source.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _count(source: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (list, tuple, set)):
            return len(value)
        try:
            if value not in (None, ""):
                return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _first_text(source: Mapping[str, Any], *keys: str) -> str:
    return next(
        (
            str(source[key]).strip()
            for key in keys
            if source.get(key) not in (None, "")
            and not isinstance(source.get(key), (dict, list, tuple, set))
        ),
        "",
    )


def _dominant_reason(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    candidates: list[tuple[int, str]] = []
    for key, count in value.items():
        try:
            parsed = int(count)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            candidates.append((parsed, str(key)))
    return max(candidates, key=lambda item: (item[0], item[1]))[1] if candidates else ""


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
    "BusinessResultProjection",
    "TERMINAL_TASK_STATE_VALUES",
    "business_result_has_warning",
    "project_business_result",
    "task_expires_at",
    "task_requires_attention",
    "utc_time_reached",
]
