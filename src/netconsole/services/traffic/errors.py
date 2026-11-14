from __future__ import annotations

from enum import StrEnum


class TrafficErrorCode(StrEnum):
    INVALID_CONFIG = "TRAFFIC_INVALID_CONFIG"
    EXECUTION_TARGET_INVALID = "TRAFFIC_EXECUTION_TARGET_INVALID"
    CAPABILITY_UNSUPPORTED = "TRAFFIC_CAPABILITY_UNSUPPORTED"
    TOOL_NOT_FOUND = "TRAFFIC_TOOL_NOT_FOUND"
    SERVER_PORT_IN_USE = "TRAFFIC_SERVER_PORT_IN_USE"
    SERVER_NOT_READY = "TRAFFIC_SERVER_NOT_READY"
    CONNECTION_REFUSED = "TRAFFIC_CONNECTION_REFUSED"
    CONNECTION_TIMEOUT = "TRAFFIC_CONNECTION_TIMEOUT"
    PROCESS_START_FAILED = "TRAFFIC_PROCESS_START_FAILED"
    PROCESS_EXITED = "TRAFFIC_PROCESS_EXITED"
    PARSE_FAILED = "TRAFFIC_PARSE_FAILED"
    CANCEL_TIMEOUT = "TRAFFIC_CANCEL_TIMEOUT"
    REMOTE_SYNC_FAILED = "TRAFFIC_REMOTE_SYNC_FAILED"
    REMOTE_TASK_NOT_FOUND = "TRAFFIC_REMOTE_TASK_NOT_FOUND"
    RESULT_NOT_FOUND = "TRAFFIC_RESULT_NOT_FOUND"
    EVENT_CURSOR_INVALID = "TRAFFIC_EVENT_CURSOR_INVALID"


class TrafficTestError(RuntimeError):
    def __init__(self, code: TrafficErrorCode | str, message: str, *, retryable: bool = False) -> None:
        safe_message = str(message or "流量测试失败").strip()
        super().__init__(safe_message)
        self.code = str(code)
        self.message = safe_message
        self.retryable = bool(retryable)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


__all__ = ["TrafficErrorCode", "TrafficTestError"]
