from __future__ import annotations

from enum import StrEnum


class OnlineMrQueryErrorCode(StrEnum):
    SESSION_NOT_FOUND = "ONLINE_MR_SESSION_NOT_FOUND"
    METADATA_INVALID = "ONLINE_MR_SESSION_METADATA_INVALID"
    SESSION_INCOMPLETE = "ONLINE_MR_SESSION_INCOMPLETE"
    LOG_SOURCE_INVALID = "ONLINE_MR_LOG_SOURCE_INVALID"
    LOG_CURSOR_INVALID = "ONLINE_MR_LOG_CURSOR_INVALID"
    ARTIFACT_NOT_FOUND = "ONLINE_MR_ARTIFACT_NOT_FOUND"
    ARTIFACT_UNSAFE = "ONLINE_MR_ARTIFACT_UNSAFE"
    DATABASE_NOT_FOUND = "ONLINE_MR_DATABASE_NOT_FOUND"
    DATABASE_BUSY = "ONLINE_MR_DATABASE_BUSY"
    DATABASE_INCOMPATIBLE = "ONLINE_MR_DATABASE_INCOMPATIBLE"
    METRIC_UNSUPPORTED = "ONLINE_MR_METRIC_UNSUPPORTED"
    QUERY_LIMIT_EXCEEDED = "ONLINE_MR_QUERY_LIMIT_EXCEEDED"


class OnlineMrQueryError(RuntimeError):
    def __init__(self, code: OnlineMrQueryErrorCode | str, message: str) -> None:
        safe_message = str(message or "Online MR 查询失败").strip()
        super().__init__(safe_message)
        self.code = str(code)
        self.message = safe_message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


__all__ = ["OnlineMrQueryError", "OnlineMrQueryErrorCode"]
