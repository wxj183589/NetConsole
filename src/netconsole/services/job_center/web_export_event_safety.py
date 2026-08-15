from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from netconsole.models.task_snapshot import TaskSnapshot


_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r'''(?ix)(?P<quote>["'])(?:file://|[a-z]:[\\/]|\\\\)[^"'\r\n]*?(?P=quote)'''
)
_UNQUOTED_SPACED_FILE_PATH_RE = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_])
    (?:file://|[a-z]:[\\/]|\\\\[^\\/\s]+[\\/])
    [^"'<>|\r\n]*?\.[A-Za-z0-9][A-Za-z0-9_-]{0,31}
    (?=$|[\s,;，；。!?！?)\]}])
    '''
)
_UNQUOTED_ABSOLUTE_PATH_RE = re.compile(
    r'''(?ix)(?<![A-Za-z0-9_])(?:file://|[a-z]:[\\/]|\\\\[^\\/\s]+[\\/])[^\s"'<>|,;，；。!?！?)\]}]*'''
)
_UNQUOTED_ABSOLUTE_DIRECTORY_RE = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_])
    (?:file://|[a-z]:[\\/]|\\\\[^\\/\s]+[\\/])
    [^"'<>|\r\n,;，；。!?！?)\]}]*
    '''
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b((?:x-agent-token|authorization|token|password|credential|secret|community)\s*[:=]\s*(?:bearer\s+)?)\S+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PATH_KEYS = {
    "db_path",
    "generated_files",
    "output_path",
    "package_path",
    "path",
    "relative_path",
    "report_path",
    "result_path",
    "tmp_path",
    "traceback",
}
_SECRET_KEYS = {
    "authorization",
    "community",
    "credential",
    "password",
    "secret",
    "token",
    "x-agent-token",
}
_SENSITIVE_KEYS = _PATH_KEYS | _SECRET_KEYS


def is_web_export_task(task_type: str) -> bool:
    return str(task_type or "").startswith("web_export_")


def redact_web_task_text(value: object) -> str:
    redacted = _QUOTED_ABSOLUTE_PATH_RE.sub("<redacted-path>", str(value or ""))
    redacted = _UNQUOTED_SPACED_FILE_PATH_RE.sub("<redacted-path>", redacted)
    redacted = _UNQUOTED_ABSOLUTE_DIRECTORY_RE.sub("<redacted-path>", redacted)
    redacted = _UNQUOTED_ABSOLUTE_PATH_RE.sub("<redacted-path>", redacted)
    redacted = _SECRET_VALUE_RE.sub(r"\1<redacted>", redacted)
    return _BEARER_RE.sub("Bearer <redacted>", redacted)


def redact_web_export_text(value: object) -> str:
    return redact_web_task_text(value)


def sanitize_web_export_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        sensitive_key_names_removed = False
        for key, item in value.items():
            name = str(key)
            if name.casefold() in _SENSITIVE_KEYS:
                continue
            cleaned = sanitize_web_export_value(item)
            if name.casefold() == "keys" and isinstance(cleaned, list):
                filtered = [
                    candidate
                    for candidate in cleaned
                    if str(candidate).casefold() not in _SENSITIVE_KEYS
                ]
                sensitive_key_names_removed = len(filtered) != len(cleaned)
                cleaned = filtered
            sanitized[name] = cleaned
        if sensitive_key_names_removed:
            sanitized["keys_truncated"] = True
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_web_export_value(item) for item in value]
    if isinstance(value, str):
        return redact_web_export_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_web_export_text(value)


def sanitize_web_export_event(event: dict[str, object]) -> dict[str, object]:
    sanitized = sanitize_web_export_value(event)
    return dict(sanitized) if isinstance(sanitized, dict) else {}


def sanitize_web_export_result_summary(value: object) -> dict[str, Any]:
    sanitized = sanitize_web_export_value(value)
    return dict(sanitized) if isinstance(sanitized, dict) else {}


def sanitize_web_export_snapshot(snapshot: TaskSnapshot) -> TaskSnapshot:
    if not is_web_export_task(snapshot.task_type):
        return snapshot
    result = sanitize_web_export_value(snapshot.result)
    return replace(
        snapshot,
        result_path="",
        result=dict(result) if isinstance(result, dict) else {},
        result_summary=sanitize_web_export_result_summary(snapshot.result_summary),
        message=redact_web_export_text(snapshot.message),
        error_message=redact_web_export_text(snapshot.error_message),
    )


__all__ = [
    "is_web_export_task",
    "redact_web_export_text",
    "redact_web_task_text",
    "sanitize_web_export_event",
    "sanitize_web_export_result_summary",
    "sanitize_web_export_snapshot",
    "sanitize_web_export_value",
]
