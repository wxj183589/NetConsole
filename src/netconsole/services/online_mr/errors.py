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
    DATABASE_UNREADABLE = "DATABASE_UNREADABLE"
    DATABASE_CORRUPT = "DATABASE_CORRUPT"
    SCHEMA_LEGACY = "SCHEMA_LEGACY"
    SCHEMA_INCOMPLETE = "SCHEMA_INCOMPLETE"
    PARSE_REQUIRED = "PARSE_REQUIRED"
    RAW_SOURCE_MISSING = "RAW_SOURCE_MISSING"
    QUERY_UNSUPPORTED = "QUERY_UNSUPPORTED"
    METRIC_UNSUPPORTED = "ONLINE_MR_METRIC_UNSUPPORTED"
    QUERY_LIMIT_EXCEEDED = "ONLINE_MR_QUERY_LIMIT_EXCEEDED"


class OnlineMrApplicationErrorCode(StrEnum):
    INVALID_START_REQUEST = "ONLINE_MR_INVALID_START_REQUEST"
    SITE_NOT_FOUND = "ONLINE_MR_SITE_NOT_FOUND"
    DEVICE_NOT_FOUND = "ONLINE_MR_DEVICE_NOT_FOUND"
    EXECUTOR_UNSUPPORTED = "ONLINE_MR_EXECUTOR_UNSUPPORTED"
    TASK_CREATE_FAILED = "ONLINE_MR_TASK_CREATE_FAILED"
    TASK_SUBMIT_FAILED = "ONLINE_MR_TASK_SUBMIT_FAILED"
    SESSION_LINK_FAILED = "ONLINE_MR_SESSION_LINK_FAILED"
    OPERATION_NOT_FOUND = "ONLINE_MR_OPERATION_NOT_FOUND"
    MAPPING_CONFLICT = "ONLINE_MR_MAPPING_CONFLICT"
    STARTUP_CONNECTION_FAILED = "ONLINE_MR_STARTUP_CONNECTION_FAILED"
    STALE_OPERATION = "ONLINE_MR_STALE_OPERATION"


class OnlineMrWebControlErrorCode(StrEnum):
    CONTROL_DISABLED = "ONLINE_MR_WEB_CONTROL_DISABLED"
    LOCAL_ONLY = "ONLINE_MR_WEB_LOCAL_ONLY"
    AUTH_REQUIRED = "ONLINE_MR_WEB_AUTH_REQUIRED"
    INVALID_REQUEST = "ONLINE_MR_WEB_INVALID_REQUEST"
    DEVICE_NOT_FOUND = "ONLINE_MR_WEB_DEVICE_NOT_FOUND"
    CREDENTIAL_UNAVAILABLE = "ONLINE_MR_WEB_CREDENTIAL_UNAVAILABLE"
    ALREADY_RUNNING = "ONLINE_MR_ALREADY_RUNNING"
    REAL_DEVICE_TARGET_REJECTED = "ONLINE_MR_REAL_DEVICE_TARGET_REJECTED"
    STOP_FAILED = "ONLINE_MR_STOP_FAILED"


class OnlineMrSiteContextErrorCode(StrEnum):
    NOT_SELECTED = "ONLINE_MR_SITE_NOT_SELECTED"
    NOT_FOUND = "ONLINE_MR_SITE_NOT_FOUND"
    INVALID = "ONLINE_MR_SITE_INVALID"
    UNAVAILABLE = "ONLINE_MR_SITE_CONTEXT_UNAVAILABLE"


class OnlineMrQueryError(RuntimeError):
    def __init__(self, code: OnlineMrQueryErrorCode | str, message: str) -> None:
        safe_message = str(message or "Online MR 查询失败").strip()
        super().__init__(safe_message)
        self.code = str(code)
        self.message = safe_message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class OnlineMrApplicationError(RuntimeError):
    def __init__(self, code: OnlineMrApplicationErrorCode | str, message: str) -> None:
        safe_message = str(message or "Online MR 操作失败").strip()
        super().__init__(safe_message)
        self.code = str(code)
        self.message = safe_message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class OnlineMrWebControlError(RuntimeError):
    def __init__(self, code: OnlineMrWebControlErrorCode | str, message: str, *, status_code: int = 409) -> None:
        safe_message = str(message or "Online MR Web 控制失败").strip()
        super().__init__(safe_message)
        self.code = str(code)
        self.message = safe_message
        self.status_code = int(status_code)


class OnlineMrSiteContextError(OnlineMrWebControlError):
    pass


__all__ = [
    "OnlineMrApplicationError",
    "OnlineMrApplicationErrorCode",
    "OnlineMrQueryError",
    "OnlineMrQueryErrorCode",
    "OnlineMrSiteContextError",
    "OnlineMrSiteContextErrorCode",
    "OnlineMrWebControlError",
    "OnlineMrWebControlErrorCode",
]
