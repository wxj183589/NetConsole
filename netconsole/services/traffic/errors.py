from __future__ import annotations

from enum import StrEnum


class TrafficErrorCode(StrEnum):
    INVALID_CONFIG = "TRAFFIC_INVALID_CONFIG"
    EXECUTION_TARGET_INVALID = "TRAFFIC_EXECUTION_TARGET_INVALID"
    AGENT_NOT_FOUND = "TRAFFIC_AGENT_NOT_FOUND"
    AGENT_DISABLED = "TRAFFIC_AGENT_DISABLED"
    AGENT_OFFLINE = "TRAFFIC_AGENT_OFFLINE"
    AGENT_UNAUTHORIZED = "TRAFFIC_AGENT_UNAUTHORIZED"
    AGENT_CREDENTIAL_REQUIRED = "TRAFFIC_AGENT_CREDENTIAL_REQUIRED"
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


def map_agent_error(code: str, message: str) -> TrafficTestError:
    normalized = str(code or "").upper()
    mappings = {
        "AGENT_UNAUTHORIZED": TrafficErrorCode.AGENT_UNAUTHORIZED,
        "AGENT_CREDENTIAL_REQUIRED": TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED,
        "AGENT_TRAFFIC_UNSUPPORTED": TrafficErrorCode.CAPABILITY_UNSUPPORTED,
        "AGENT_TRAFFIC_TOOL_NOT_FOUND": TrafficErrorCode.TOOL_NOT_FOUND,
        "AGENT_TRAFFIC_PROCESS_START_FAILED": TrafficErrorCode.PROCESS_START_FAILED,
        "AGENT_TRAFFIC_PROCESS_FAILED": TrafficErrorCode.PROCESS_EXITED,
        "AGENT_TIMEOUT": TrafficErrorCode.CONNECTION_TIMEOUT,
        "AGENT_CONNECTION_FAILED": TrafficErrorCode.AGENT_OFFLINE,
        "AGENT_TASK_NOT_FOUND": TrafficErrorCode.REMOTE_TASK_NOT_FOUND,
        "AGENT_TRAFFIC_RESULT_NOT_READY": TrafficErrorCode.RESULT_NOT_FOUND,
    }
    selected = mappings.get(normalized, TrafficErrorCode.REMOTE_SYNC_FAILED)
    retryable = selected in {
        TrafficErrorCode.AGENT_OFFLINE,
        TrafficErrorCode.CONNECTION_TIMEOUT,
        TrafficErrorCode.REMOTE_SYNC_FAILED,
    }
    return TrafficTestError(selected, message or "Agent 流量任务请求失败", retryable=retryable)


__all__ = ["TrafficErrorCode", "TrafficTestError", "map_agent_error"]
